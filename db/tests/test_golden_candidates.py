"""O esquema da exportação do *golden* (KAM-114, critério 7).

O critério 7 pede, por extenso: «um teste de esquema prova **0** campos de texto
livre ou de identificador». Esta bateria é esse teste, e **não corre contra a
base**: o que ela confronta é a lista de campos exportados com o `CREATE TABLE`
da revisão `0024`, lido do ficheiro.

**Lido do ficheiro e não de uma cópia à mão**, que é o ponto: uma segunda lista
de colunas aqui nunca falharia quando a tabela ganhasse uma. O teste tem de
falhar no dia em que alguém acrescente uma coluna e não a classifique — é isso
que impede um campo novo de entrar na exportação em silêncio.

Vive em `db/tests/` e não em `db/tests_agr/` porque **não precisa de PostgreSQL**:
é leitura de ficheiros e comparação de listas. Corre no `make test-py` com as
outras baterias de `db/tests/` que não levantam base.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ / "db") not in sys.path:
    sys.path.insert(0, str(_RAIZ / "db"))

import golden_candidates as gc  # noqa: E402


class TestOEsquemaDaExportacao(unittest.TestCase):
    """Critério 7: 0 campos de texto livre ou de identificador."""

    def test_o_esquema_e_conforme(self) -> None:
        """O comando `esquema` sai a zero achados.

        É a mesma função que o comando corre (`achados_do_esquema`), e não uma
        reimplementação: o que o operador vê e o que o teste mede são o mesmo
        código.
        """
        self.assertEqual(gc.achados_do_esquema(_RAIZ), [])

    def test_as_colunas_leem_se_da_revisao_e_sao_treze(self) -> None:
        colunas = gc.colunas_da_revisao(_RAIZ)
        self.assertEqual(len(colunas), 13)
        self.assertEqual(colunas[0], "draft_id")
        self.assertIn("decidido_at", colunas)

    def test_todas_as_colunas_da_revisao_estao_classificadas(self) -> None:
        colunas = set(gc.colunas_da_revisao(_RAIZ))
        self.assertEqual(colunas - set(gc.CLASSES_DAS_COLUNAS), set())

    def test_nenhuma_classificacao_esta_morta(self) -> None:
        """Uma classificação que a revisão não tem é pior do que nenhuma."""
        colunas = set(gc.colunas_da_revisao(_RAIZ))
        self.assertEqual(set(gc.CLASSES_DAS_COLUNAS) - colunas, set())

    def test_nenhum_campo_exportado_e_identificador_ou_instante(self) -> None:
        """A metade «0 campos de identificador» do critério, directa."""
        for campo in gc.CAMPOS_DA_EXPORTACAO:
            with self.subTest(campo=campo):
                self.assertIn(gc.CLASSES_DAS_COLUNAS[campo], gc.CLASSES_QUE_SAEM)

    def test_os_identificadores_todos_ficam_de_fora(self) -> None:
        identificadores = {
            coluna
            for coluna, classe in gc.CLASSES_DAS_COLUNAS.items()
            if classe == "identificador"
        }
        # Cinco: `draft_id`, `tenant_id`, `thread_id`, `turn_id`, `turn_seq`.
        self.assertEqual(len(identificadores), 5)
        self.assertEqual(identificadores & set(gc.CAMPOS_DA_EXPORTACAO), set())

    def test_os_instantes_ficam_de_fora(self) -> None:
        """Um instante com precisão de microssegundo sobre um universo pequeno
        re-identifica a conversa tão bem como um identificador.
        """
        instantes = {
            coluna
            for coluna, classe in gc.CLASSES_DAS_COLUNAS.items()
            if classe == "instante"
        }
        self.assertEqual(instantes, {"criado_at", "decidido_at"})
        self.assertEqual(instantes & set(gc.CAMPOS_DA_EXPORTACAO), set())

    def test_nao_ha_classe_de_texto_livre(self) -> None:
        """A afirmação em que a prova assenta, medida.

        Era **falsa** na primeira versão: o `graph_version` era `text` sem
        `CHECK` de forma — a própria migração o dizia, porque era onde o canário
        do X-03 ia — e sai nesta exportação. Isto é, havia um campo livre a
        atravessar para fora. Apanhado pela revisão adversarial; a `0024` passou
        a impor SemVer naquela coluna e o canário mudou-se para o `turn_id`.
        """
        self.assertNotIn("texto", set(gc.CLASSES_DAS_COLUNAS.values()))
        fonte = (_RAIZ / gc.REVISAO).read_text(encoding="utf-8")
        self.assertIn("draft_decisions_graph_version_ck", fonte)
        self.assertIn("^[0-9]+[.][0-9]+[.][0-9]+$", fonte)


class TestOCanarioDoEsquema(unittest.TestCase):
    """A prova de que este teste **morde**.

    Um teste de esquema que só corre contra um esquema conforme não prova nada —
    é a lição dos passos de canário dos *gates* 3b, 9 e 11.
    """

    def setUp(self) -> None:
        self._classes = dict(gc.CLASSES_DAS_COLUNAS)
        self._campos = gc.CAMPOS_DA_EXPORTACAO

    def tearDown(self) -> None:
        gc.CLASSES_DAS_COLUNAS.clear()
        gc.CLASSES_DAS_COLUNAS.update(self._classes)
        gc.CAMPOS_DA_EXPORTACAO = self._campos

    def test_uma_coluna_sem_classe_e_apanhada(self) -> None:
        del gc.CLASSES_DAS_COLUNAS["thread_id"]
        achados = gc.achados_do_esquema(_RAIZ)
        self.assertTrue(achados)
        self.assertIn("sem classe", achados[0])

    def test_um_identificador_na_exportacao_e_apanhado(self) -> None:
        gc.CAMPOS_DA_EXPORTACAO = (*self._campos, "thread_id")
        achados = gc.achados_do_esquema(_RAIZ)
        self.assertTrue(achados)
        self.assertIn("identificador", " ".join(achados))

    def test_um_instante_na_exportacao_e_apanhado(self) -> None:
        gc.CAMPOS_DA_EXPORTACAO = (*self._campos, "criado_at")
        self.assertTrue(gc.achados_do_esquema(_RAIZ))

    def test_uma_classificacao_morta_e_apanhada(self) -> None:
        gc.CLASSES_DAS_COLUNAS["coluna_que_nao_existe"] = "rotulo"
        achados = gc.achados_do_esquema(_RAIZ)
        self.assertTrue(achados)
        self.assertIn("que a revisao nao tem", " ".join(achados))


class TestAOrigemSintetica(unittest.TestCase):
    """ADR-018: o *golden* recebe reescritas sintéticas, nunca cópias."""

    def test_cada_registo_leva_a_origem(self) -> None:
        """A origem vai no **registo** e não no cabeçalho do ficheiro: um
        cabeçalho perde a marca no dia em que alguém parta a lista em duas.
        """

        class CursorFalso:
            def execute(self, _sql, _p=()):
                pass

            def fetchall(self):
                return [("editado", "tom", True, "1.1.0", 0.4)]

        linhas = gc.exportar(CursorFalso())
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["origem"], "sintetico")
        # E nada mais do que os cinco campos e a origem.
        self.assertEqual(
            set(linhas[0]), set(gc.CAMPOS_DA_EXPORTACAO) | {"origem"}
        )

    def test_a_razao_de_edicao_sai_arredondada(self) -> None:
        """Minimização e não estética: três casas sobre um universo pequeno é
        quase um identificador.
        """
        self.assertIn("round(d.razao_edicao, 1)", gc.SQL_CANDIDATOS)

    def test_a_consulta_nao_leva_identificadores(self) -> None:
        for coluna in ("draft_id", "tenant_id", "thread_id", "turn_id"):
            with self.subTest(coluna=coluna):
                self.assertNotIn(f"d.{coluna}", gc.SQL_CANDIDATOS)


if __name__ == "__main__":
    unittest.main()
