"""A activacao do lexico de *dataset* contra um PostgreSQL real (KAM-199).

A metade do criterio 7 do KAM-062 que a `0049` deixou presa: uma entrada
`origem = 'dataset'` so fica `activo` com um relatorio **verde** do *gate* de
avaliacao anexado (`idx.eval_relatorio`) **que a mediu** (os `termos` dele). O
que aqui se mede:

* o caminho de escrita, com os ficheiros do repositorio: a linha de base
  `1.0.0` e o relatorio de que nasceu passam pelo `gate.anexo_de` e entram pelo
  `indice.SQL_ANEXAR_RELATORIO` — e, como essa corrida nao semeou lexico, nao
  soltam entrada nenhuma;
* uma entrada que o relatorio mediu activa-se, e uma que nao mediu (o mesmo
  termo com outro canonico incluido) fica presa;
* a `CHECK` do verde na base, nos dois limites do §14.3 (2 pontos de nDCG@3,
  1 de zero-result) e por um passo acima de cada um;
* que sem relatorio, ou com um que nao existe, a entrada continua presa;
* que o relatorio anexado nao se apaga nem se reescreve;
* a descida da revisao: a `CHECK` antiga volta, e **recusa** com uma entrada
  de *dataset* activa.

A revisao descobre-se pelo *glob* e nao pelo numero, que e provisorio.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unittest
import uuid
from pathlib import Path

import bootstrap
import ligacao
from tests.base import (
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests_produtos.test_indice import ComIndice

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ / "tools") not in sys.path:
    sys.path.insert(0, str(_RAIZ / "tools"))

import indice  # noqa: E402
from eval_search import gate  # noqa: E402

_REVISAO = next((_RAIZ / "db" / "migrations" / "versions").glob("*_activacao_do_lexico_de_dataset.py"))


def _da_revisao(campo: str) -> str:
    achado = re.search(rf'^{campo} = "(\d+)"$', _REVISAO.read_text(encoding="utf-8"), re.MULTILINE)
    assert achado, f"{_REVISAO.name} sem `{campo}`"
    return achado.group(1)


#: Esta revisao e a de baixo, lidas do ficheiro.
REVISAO = _da_revisao("revision")
ANTERIOR = _da_revisao("down_revision")


def _sha256() -> str:
    """Um `sha256` novo em cada chamada: a coluna e unica."""
    return hashlib.sha256(os.urandom(16)).hexdigest()


def _termo(termo: str, canonico: str = "frigorifico", tipo: str = "sinonimo") -> dict[str, str]:
    return {"tipo": tipo, "termo": termo, "canonico": canonico}


def _anexar(cursor, termos=(), ndcg_base=0.9, ndcg=0.9, zero_base=0.04, zero=0.04, quem="ensaio-kam-199") -> int:
    cursor.execute(
        indice.SQL_ANEXAR_RELATORIO,
        (_sha256(), "1.0.0", "1.0.0", ndcg_base, ndcg, zero_base, zero, json.dumps(list(termos)), quem),
    )
    return int(cursor.fetchone()[0])


_INSERIR_DATASET = (
    "INSERT INTO idx.termo_canonico "
    "(tenant_id, tipo, termo, canonico, origem, activo, aprovado_por, eval_relatorio_id) "
    "VALUES (NULL, 'sinonimo', %s, 'frigorifico', 'dataset', %s, 'ops', %s) RETURNING id"
)


def _novo() -> str:
    return f"ds{uuid.uuid4().hex[:8]}"


class TestActivacao(ComIndice):
    """Numa ligacao de administrador com transaccao: desfaz-se no fim."""

    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()

    def test_o_relatorio_versionado_anexa_se_e_nao_solta_nada(self) -> None:
        """O caminho de escrita com os ficheiros que o *gate* usa.

        A linha de base `1.0.0` nasceu de uma corrida sem lexico: o relatorio e
        verde e anexa-se, e por isso mesmo nao solta entrada nenhuma — e o
        caso que a primeira versao desta revisao deixava passar.
        """
        base = json.loads(gate.LINHA_DE_BASE.read_text(encoding="utf-8"))
        caminho = gate.LINHA_DE_BASE.parent / "reports" / f"{base['versao']}.json"
        linha = gate.anexo_de(
            json.loads(caminho.read_text(encoding="utf-8")),
            base,
            hashlib.sha256(caminho.read_bytes()).hexdigest(),
            "ensaio-kam-199",
        )
        self.assertEqual(linha["termos"], [])
        self.admin.execute(
            indice.SQL_ANEXAR_RELATORIO,
            tuple(json.dumps(linha[c]) if c == "termos" else linha[c] for c in indice.COLUNAS_DO_ANEXO),
        )
        relatorio = int(self.admin.fetchone()[0])
        self.assertErroSql(VIOLACAO_DE_CHECK, self.admin, _INSERIR_DATASET, (_novo(), True, relatorio))

    def test_uma_entrada_medida_activa_se(self) -> None:
        termo, directo = _novo(), _novo()
        relatorio = _anexar(self.admin, termos=[_termo(termo), _termo(directo)])
        # Criada inactiva e activada depois, que e o caminho de *ops*.
        self.admin.execute(_INSERIR_DATASET, (termo, False, None))
        termo_id = int(self.admin.fetchone()[0])
        self.admin.execute(
            "UPDATE idx.termo_canonico SET activo = true, eval_relatorio_id = %s WHERE id = %s",
            (relatorio, termo_id),
        )
        self.admin.execute("SELECT activo FROM idx.termo_canonico WHERE id = %s", (termo_id,))
        self.assertIs(self.admin.fetchone()[0], True)
        # E criada ja activa.
        self.admin.execute(_INSERIR_DATASET, (directo, True, relatorio))

    def test_uma_entrada_que_o_relatorio_nao_mediu_fica_presa(self) -> None:
        termo = _novo()
        casos = {
            "outro termo": [_termo(_novo())],
            "o mesmo termo com outro canonico": [_termo(termo, canonico="arca")],
            "o mesmo termo de outro tipo": [_termo(termo, tipo="erro_comum")],
        }
        for nome, termos in casos.items():
            with self.subTest(nome):
                relatorio = _anexar(self.admin, termos=termos)
                self.assertErroSql(VIOLACAO_DE_CHECK, self.admin, _INSERIR_DATASET, (termo, True, relatorio))

    def test_sem_relatorio_a_entrada_continua_presa(self) -> None:
        self.assertErroSql(VIOLACAO_DE_CHECK, self.admin, _INSERIR_DATASET, (_novo(), True, None))
        self.admin.execute(_INSERIR_DATASET, (_novo(), False, None))
        termo_id = int(self.admin.fetchone()[0])
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            self.admin,
            "UPDATE idx.termo_canonico SET activo = true WHERE id = %s",
            (termo_id,),
        )

    def test_um_relatorio_que_nao_existe_nao_solta(self) -> None:
        """Recusa o gatilho, antes de a FK chegar a ver: e uma das duas barreiras."""
        self.admin.execute("SELECT COALESCE(max(id), 0) + 1000 FROM idx.eval_relatorio")
        inexistente = int(self.admin.fetchone()[0])
        self.assertErroSql(VIOLACAO_DE_CHECK, self.admin, _INSERIR_DATASET, (_novo(), True, inexistente))

    def test_os_dois_limites_do_verde(self) -> None:
        """Cair 2 pontos e subir 1 ainda e verde; um passo acima, nao."""
        _anexar(self.admin, ndcg_base=0.883125, ndcg=0.863125, zero_base=0.04, zero=0.05)
        for ndcg, zero in ((0.863124, 0.04), (0.883125, 0.050001)):
            with self.subTest(ndcg=ndcg, zero=zero):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.admin,
                    indice.SQL_ANEXAR_RELATORIO,
                    (_sha256(), "1.0.0", "1.0.0", 0.883125, ndcg, 0.04, zero, "[]", "ensaio"),
                )

    def test_a_forma_do_relatorio(self) -> None:
        casos = (
            ("sha256 em maiusculas", (_sha256().upper(), 0.9, "[]", "ops")),
            ("sha256 curto", (_sha256()[:40], 0.9, "[]", "ops")),
            ("metrica fora de [0, 1]", (_sha256(), 1.5, "[]", "ops")),
            ("termos que nao sao uma lista", (_sha256(), 0.9, '{"tipo": "sinonimo"}', "ops")),
            ("sem quem regista", (_sha256(), 0.9, "[]", "  ")),
        )
        for nome, (sha256, ndcg, termos, quem) in casos:
            with self.subTest(nome):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.admin,
                    indice.SQL_ANEXAR_RELATORIO,
                    (sha256, "1.0.0", "1.0.0", ndcg, ndcg, 0.04, 0.04, termos, quem),
                )

    def test_o_relatorio_anexado_nao_se_apaga_nem_se_reescreve(self) -> None:
        termo = _novo()
        relatorio = _anexar(self.admin, termos=[_termo(termo)])
        self.admin.execute(_INSERIR_DATASET, (termo, True, relatorio))
        self.assertErroSql(
            VIOLACAO_DE_FK, self.admin, "DELETE FROM idx.eval_relatorio WHERE id = %s", (relatorio,)
        )
        for nome, sql in (
            ("para vermelho", "UPDATE idx.eval_relatorio SET ndcg_at_3 = 0.5 WHERE id = %s"),
            (
                "um termo que nao mediu",
                "UPDATE idx.eval_relatorio SET termos = termos || "
                """'[{"tipo": "sinonimo", "termo": "outro", "canonico": "x"}]'::jsonb WHERE id = %s""",
            ),
            ("a mesma coisa", "UPDATE idx.eval_relatorio SET registado_por = registado_por WHERE id = %s"),
        ):
            with self.subTest(nome):
                self.assertErroSql(VIOLACAO_DE_CHECK, self.admin, sql, (relatorio,))


class TestDowngradeDaActivacao(unittest.TestCase):
    """A descida desta revisao, pelo numero lido do ficheiro.

    Controla ela propria a revisao em que a base esta, como o
    `TestDowngradeDa0037`, e repoe `head` no fim. **Desce primeiro ate esta
    revisao**, e so depois a de baixo: com outra revisao por cima, uma descida
    de `head` que recusasse aqui deixava a base num sitio que dependia de como
    o Alembic agrupa as transaccoes. E por isso a recusa afirma-se contra esta
    revisao, e nunca contra a `head`.
    """

    QUEM = "ensaio-descida-kam-199"

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        try:
            if self._existe_a_tabela():
                self.cursor.execute("DELETE FROM idx.termo_canonico WHERE aprovado_por = %s", (self.QUEM,))
                self.cursor.execute("DELETE FROM idx.eval_relatorio WHERE registado_por = %s", (self.QUEM,))
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    def _existe_a_tabela(self) -> bool:
        self.cursor.execute("SELECT to_regclass('idx.eval_relatorio') IS NOT NULL")
        return bool(self.cursor.fetchone()[0])

    def _restricoes(self) -> set[str]:
        self.cursor.execute(
            "SELECT conname::text FROM pg_constraint "
            " WHERE conrelid = 'idx.termo_canonico'::regclass AND conname LIKE 'termo_canonico_dataset_%'"
        )
        return {str(linha[0]) for linha in self.cursor.fetchall()}

    def _objectos(self) -> set[str]:
        """Os gatilhos e as funcoes que esta revisao cria."""
        self.cursor.execute(
            "SELECT tgname::text FROM pg_trigger WHERE tgname IN "
            "('termo_canonico_dataset_medido', 'eval_relatorio_imutavel') "
            "UNION ALL SELECT p.proname::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'idx' AND p.proname IN "
            "('f_exigir_termo_medido', 'f_recusar_alteracao_de_relatorio')"
        )
        return {str(linha[0]) for linha in self.cursor.fetchall()}

    def _versao(self) -> list[tuple]:
        self.cursor.execute("SELECT version_num FROM public.alembic_version")
        return [tuple(linha) for linha in self.cursor.fetchall()]

    def test_desce_e_a_check_antiga_volta(self) -> None:
        alembic_ok("downgrade", REVISAO)
        self.assertEqual(self._restricoes(), set())
        self.assertEqual(len(self._objectos()), 4)

        alembic_ok("downgrade", ANTERIOR)
        self.assertFalse(self._existe_a_tabela(), "a descida deixou o idx.eval_relatorio")
        self.assertEqual(self._restricoes(), {"termo_canonico_dataset_inactivo_ck"})
        self.assertEqual(self._objectos(), set(), "a descida deixou gatilhos ou funcoes")
        self.cursor.execute(
            "SELECT count(*) FROM information_schema.columns "
            " WHERE table_schema = 'idx' AND table_name = 'termo_canonico' "
            "   AND column_name = 'eval_relatorio_id'"
        )
        self.assertEqual(int(self.cursor.fetchone()[0]), 0)

        alembic_ok("upgrade", "head")
        self.assertTrue(self._existe_a_tabela())
        self.assertEqual(self._restricoes(), set())
        self.assertEqual(len(self._objectos()), 4)

    def test_com_uma_entrada_de_dataset_activa_a_descida_recusa(self) -> None:
        """Descer nao desactiva lexico em silencio: a transaccao desfaz-se."""
        alembic_ok("downgrade", REVISAO)
        termo = _novo()
        relatorio = _anexar(self.cursor, termos=[_termo(termo, canonico="y")], quem=self.QUEM)
        self.cursor.execute(
            "INSERT INTO idx.termo_canonico "
            "(tenant_id, tipo, termo, canonico, origem, activo, aprovado_por, eval_relatorio_id) "
            "VALUES (NULL, 'sinonimo', %s, 'y', 'dataset', true, %s, %s)",
            (termo, self.QUEM, relatorio),
        )

        resultado = alembic("downgrade", ANTERIOR)
        self.assertNotEqual(resultado.returncode, 0, "a descida passou com lexico de dataset activo")
        self.assertIn("termo_canonico_dataset_inactivo_ck", resultado.stderr)
        self.assertEqual(self._versao(), [(REVISAO,)])
        self.assertTrue(self._existe_a_tabela())
        self.assertEqual(self._restricoes(), set())
        self.assertEqual(len(self._objectos()), 4)


if __name__ == "__main__":
    unittest.main()
