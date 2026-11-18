"""A revisao de dados da subscricao do CHR (KAM-201), contra o PostgreSQL.

A forma e a do `test_subscricoes_0052.py` (KAM-194), e as razoes tambem: sobe,
desce e volta a subir com as linhas **exactas** da constante `LINHAS`; o
`downgrade` apaga essas e so essas, mesmo uma linha alheia do mesmo `consumer`;
e uma linha ja presente faz falhar o `upgrade`. Que a constante diz o mesmo que
o `registry/chr.yaml` prova-o o `services/agr/tests/test_subscricoes_0052.py`.

O numero e o `down_revision` leem-se do ficheiro, e nao se escrevem aqui: um
ensaio preso a `"0061"` partia-se no dia de uma renumeracao sem nada errado.
"""

from __future__ import annotations

import ast
import unittest

from tests import base
from tests.base import alembic_ok, exigir_base_descartavel

SUFIXO = "_subscricao_do_chr.py"


def _revisao() -> tuple[str, str, list[tuple[str, ...]]]:
    [ficheiro] = sorted((base.DB / "migrations" / "versions").glob(f"*{SUFIXO}"))
    valores: dict[str, object] = {}
    for no in ast.parse(ficheiro.read_text(encoding="utf-8")).body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1:
            nome = getattr(no.targets[0], "id", None)
            if nome in ("revision", "down_revision", "LINHAS"):
                valores[nome] = ast.literal_eval(no.value)
    return (
        str(valores["revision"]),
        str(valores["down_revision"]),
        [tuple(linha) for linha in valores["LINHAS"]],  # type: ignore[union-attr]
    )


REVISAO, ANTERIOR, LINHAS = _revisao()
CONSUMIDORES = sorted({linha[0] for linha in LINHAS})


class TestRevisaoDaSubscricaoDoChr(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        base.bootstrap.aplicar()
        alembic_ok("upgrade", "head")

    def tearDown(self) -> None:
        # Deixa a base na cabeca para a classe seguinte, desca onde descer.
        alembic_ok("upgrade", "head")

    def _consultar(self, sql: str, parametros: tuple = ()) -> list[tuple]:
        conexao = base.ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(sql, parametros)
            return [tuple(linha) for linha in cursor.fetchall()]
        finally:
            conexao.close()

    def _nossas(self) -> set[tuple]:
        chaves = {(linha[0], linha[1]) for linha in LINHAS}
        return set(
            linha
            for linha in self._consultar(
                "SELECT consumer, tipo, versao_max::text, finalidade, "
                "       CASE WHEN exige_ordem THEN 'true' ELSE 'false' END, activo "
                "  FROM platform.evt_subscricoes WHERE consumer = ANY(%s)",
                (CONSUMIDORES,),
            )
            if (linha[0], linha[1]) in chaves
        )

    def _alheias(self) -> list[tuple]:
        """As linhas que a revisao **nao** escreveu, pela chave e nao pelo `consumer`.

        Pela chave: uma linha alheia do **mesmo** `consumer` (`chr`,
        `tenant.reactivated`) tem de sobreviver a descida, e um filtro por
        `consumer` escondia-a (o achado da revisao adversarial do KAM-194).
        Era a `tenant.suspended` ate o KAM-098 a subscrever (revisao
        `*_offboarding.py`): com ela, o `tearDown` subia a cabeca antes do
        `addCleanup` a apagar, e o `INSERT` da revisao colidia.
        """
        nossas = {(linha[0], linha[1]) for linha in LINHAS}
        return sorted(
            linha
            for linha in self._consultar("SELECT consumer, tipo FROM platform.evt_subscricoes")
            if tuple(linha) not in nossas
        )

    def test_sobe_desce_e_volta_a_subir_com_as_linhas_exactas(self) -> None:
        esperadas = {(*linha, True) for linha in LINHAS}

        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self._nossas(), set(), "o downgrade apaga as linhas da revisao")

        alembic_ok("upgrade", REVISAO)
        self.assertEqual(self._nossas(), esperadas)

        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self._nossas(), set())

        alembic_ok("upgrade", REVISAO)
        self.assertEqual(self._nossas(), esperadas)

    def test_o_downgrade_nao_toca_numa_subscricao_alheia(self) -> None:
        # Primeiro **na propria revisao**: uma revisao de dados por cima (a
        # subscricao do CHR do KAM-201 sobre a do KAM-194) escreve linhas que a
        # descida tambem apaga, e o «antes» medido na cabeca contava-as como
        # alheias. A licao dos ensaios de descida presos a cabeca.
        alembic_ok("downgrade", REVISAO)
        conexao = base.ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "INSERT INTO platform.evt_subscricoes (consumer, tipo, finalidade) "
                "VALUES ('ensaio_0061', 'catalog.product_changed', 'transacao'), "
                "       ('chr', 'tenant.reactivated', 'transacao') "
                "ON CONFLICT DO NOTHING"
            )
            conexao.commit()
        finally:
            conexao.close()
        self.addCleanup(
            self._consultar_e_confirmar,
            "DELETE FROM platform.evt_subscricoes WHERE consumer = 'ensaio_0061' "
            "OR (consumer = 'chr' AND tipo = 'tenant.reactivated')",
        )
        antes = self._alheias()
        self.assertIn(("ensaio_0061", "catalog.product_changed"), antes)
        self.assertIn(("chr", "tenant.reactivated"), antes)
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self._alheias(), antes)

    def test_uma_linha_ja_presente_faz_falhar_o_upgrade(self) -> None:
        """Sem `ON CONFLICT`: uma linha que a revisao nao criou nao se adopta.

        Se se adoptasse, o `downgrade` apagava-a. Falha alto, e a base fica onde
        estava — a revisao corre numa transaccao.
        """
        alembic_ok("downgrade", ANTERIOR)
        consumer, tipo, *_ = LINHAS[0]
        self._consultar_e_confirmar(
            "INSERT INTO platform.evt_subscricoes (consumer, tipo, finalidade) "
            "VALUES (%s, %s, 'transacao')",
            (consumer, tipo),
        )
        resultado = base.alembic("upgrade", REVISAO)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertEqual(self._nossas(), {(consumer, tipo, "1", "transacao", "false", True)})
        self._consultar_e_confirmar(
            "DELETE FROM platform.evt_subscricoes WHERE consumer = %s AND tipo = %s",
            (consumer, tipo),
        )

    def _consultar_e_confirmar(self, sql: str, parametros: tuple = ()) -> None:
        conexao = base.ligacao.ligar("admin")
        try:
            conexao.cursor().execute(sql, parametros)
            conexao.commit()
        finally:
            conexao.close()


if __name__ == "__main__":
    unittest.main()
