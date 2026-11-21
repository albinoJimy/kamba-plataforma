"""A revisao `finalidade_do_screening` (KAM-195, criterio 2): a finalidade do classificador.

Duas coisas, e a segunda e a que o bloco nomeia nos Testes Requeridos:

1. o dominio de `tenant_destinations.purpose` tem as **quinze**, e a
   `classificacao_de_catalogo` e aceite — e um erro de escrita dela nao;
2. o `downgrade` **recusa-se** com um destino `classificacao_de_catalogo` (e um
   registo de uma decisao de transferencia, e nao se apaga para descer) e deixa
   a base como estava; sem ele desce, o dominio volta as catorze, e volta a
   subir — a descida e reversivel.

**Desde o KAM-230 a cabeca e a `finalidade_das_condicoes`**, que reescreve o
mesmo `CHECK` com dezasseis. O que **esta** revisao escreve ja nao se le na
cabeca: le-se subindo so ate ela (`upgrade <esta>`), e e ai que o ensaio da
descida conta as quinze. Sem isso, a mutacao que lhe tira a
`classificacao_de_catalogo` sobrevivia, porque a revisao de cima a repoe.

A revisao descobre-se por *glob* e o `revision` e o `down_revision` leem-se do
ficheiro: o numero e provisorio (a fila de integracao renumera), e nenhum
literal daqui muda com ele.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    VIOLACAO_DE_CHECK,
    ComBase,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

RAIZ = Path(__file__).resolve().parents[2]
VERSOES = RAIZ / "db" / "migrations" / "versions"
DESTINOS = "platform.tenant_destinations"
FINALIDADE = "classificacao_de_catalogo"

#: As catorze da `foto_de_produtos`, a que o `downgrade` volta. Por extenso: o
#: oraculo nao se le da revisao que mede.
FINALIDADES_DA_FOTO = (
    "alojamento", "canal", "conversa", "copias_de_seguranca", "embeddings",
    "entrega_de_conteudo", "facturacao", "imagem", "observabilidade",
    "otp_e_avisos_de_servico", "pagamentos", "segredos", "transcricao", "visao",
)
FINALIDADES = tuple(sorted((*FINALIDADES_DA_FOTO, FINALIDADE)))

SQL_DEFINICAO = (
    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conname = 'tenant_destinations_purpose_ck'"
)


def _revisao() -> tuple[str, str]:
    """`(revision, down_revision)` da revisao desta suite, lidos do ficheiro."""
    [ficheiro] = list(VERSOES.glob("*_finalidade_do_screening.py"))
    texto = ficheiro.read_text(encoding="utf-8")
    revisao = re.search(r'^revision = "(\d{4})"$', texto, re.M)
    abaixo = re.search(r'^down_revision = "(\d{4})"$', texto, re.M)
    assert revisao and abaixo, "a revisao nao declara revision e down_revision"
    return revisao.group(1), abaixo.group(1)


class TestAFinalidadeDoScreening(ComBase):
    def test_o_dominio_tem_as_quinze_e_a_classificacao_e_aceite(self) -> None:
        admin = self.ligar("admin").cursor()
        admin.execute(SQL_DEFINICAO)
        definicao = admin.fetchone()[0]
        for finalidade in FINALIDADES:
            with self.subTest(finalidade=finalidade):
                self.assertIn(f"'{finalidade}'", definicao)
        # Na cabeca ha mais (a `finalidade_das_condicoes`, KAM-230): as quinze
        # desta revisao contam-se no ensaio da descida, subindo so ate ela.
        self.assertGreaterEqual(definicao.count("'::text"), 15)
        tenant = factories.tenant(admin)
        sql = (
            f"INSERT INTO {DESTINOS} (tenant_id, provider, country, purpose, status, "
            "retencao_zero, sem_treino) VALUES (%s, 'anthropic', 'US', %s, 'pendente', false, false)"
        )
        admin.execute(sql, (tenant, FINALIDADE))
        self.assertEqual(admin.rowcount, 1)
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, sql, (tenant, "classificacao"))
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, sql, (tenant, "screening"))


class TestDowngradeDaFinalidadeDoScreening(unittest.TestCase):
    """O `downgrade` recusa com um destino da finalidade, e sem ele desce e volta.

    **Nao exige `em_head()` depois de descer**, pela licao da `foto_de_produtos`:
    com outra revisao por cima, o Alembic desce-a primeiro, e o que se mede e o
    dominio na revisao de baixo desta.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _executar(self, sql: str, parametros: tuple = ()) -> str | None:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(sql, parametros)
            linha = cursor.fetchone() if cursor.description else None
            conexao.commit()
            return linha[0] if linha else None
        finally:
            conexao.close()

    def _definicao(self) -> str:
        return self._executar(SQL_DEFINICAO)  # type: ignore[return-value]

    def test_com_um_destino_recusa_e_sem_ele_desce_e_volta(self) -> None:
        esta, abaixo = _revisao()
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            tenant = factories.tenant(cursor)
            conexao.commit()
        finally:
            conexao.close()
        self.addCleanup(self._executar, "DELETE FROM platform.tenants WHERE id = %s", (tenant,))
        destino = self._executar(
            f"INSERT INTO {DESTINOS} (tenant_id, provider, country, purpose, status, "
            "retencao_zero, sem_treino) VALUES (%s, 'anthropic', 'US', %s, 'pendente', "
            "false, false) RETURNING id::text",
            (tenant, FINALIDADE),
        )
        try:
            recusa = alembic("downgrade", abaixo)
            self.assertNotEqual(recusa.returncode, 0, "a descida com o destino devia recusar")
            self.assertIn(f"purpose {FINALIDADE}", recusa.stdout + recusa.stderr)
            # A base fica como estava: o destino e o dominio de quinze.
            self.assertEqual(
                self._executar(f"SELECT count(*) FROM {DESTINOS} WHERE id = %s", (destino,)), 1
            )
            self.assertIn(f"'{FINALIDADE}'", self._definicao())
        finally:
            self._executar(f"DELETE FROM {DESTINOS} WHERE id = %s", (destino,))
            if not em_head():
                alembic_ok("upgrade", "head")

        alembic_ok("downgrade", abaixo)
        try:
            definicao = self._definicao()
            self.assertNotIn(f"'{FINALIDADE}'", definicao)
            for finalidade in FINALIDADES_DA_FOTO:
                self.assertIn(f"'{finalidade}'", definicao)
            self.assertEqual(definicao.count("'::text"), 14)
            # O que **esta** revisao escreve: sobe-se so ate ela, e nao a
            # cabeca, porque a de cima reescreve o mesmo `CHECK` (KAM-230).
            alembic_ok("upgrade", esta)
            definicao = self._definicao()
            self.assertIn(f"'{FINALIDADE}'", definicao)
            self.assertEqual(definicao.count("'::text"), 15)
        finally:
            alembic_ok("upgrade", "head")
        self.assertIn(f"'{FINALIDADE}'", self._definicao())


if __name__ == "__main__":
    unittest.main()
