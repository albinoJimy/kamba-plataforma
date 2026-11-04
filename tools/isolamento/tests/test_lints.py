"""O *lint* do `SET LOCAL` morde — e a prova e por canario, nao por leitura.

Criterio 7 do KAM-066, segunda metade. Um *lint* que nunca encontra nada e
indistinguivel de um *lint* desligado, e por isso cada regra tem aqui o seu
canario: escreve-se o defeito numa arvore de ensaio e exige-se que ele seja
nomeado. A regressao sobre a arvore real vem no fim, e e a outra metade: o
repositorio esta conforme com uma excepcao declarada, e tem de continuar.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from isolamento import lints
from isolamento.tests import apoio


class ComArvore(unittest.TestCase):
    def setUp(self) -> None:
        self._directorio = tempfile.TemporaryDirectory()
        self.raiz = apoio.arvore(Path(self._directorio.name))
        self.modulo = self.raiz / "libs" / "core" / "src" / "guarda.py"
        self.modulo.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self._directorio.cleanup()

    def escrever(self, corpo: str) -> None:
        self.modulo.write_text(corpo, encoding="utf-8")


class TestOsCanarios(ComArvore):
    def test_um_set_de_sessao_e_apanhado(self) -> None:
        self.escrever('SQL = "SET app.tenant_id = %s"\n')
        achados = lints.verificar(self.raiz)
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("SET de **sessao**", achados[0])

    def test_um_set_session_tambem(self) -> None:
        self.escrever('SQL = "SET SESSION app.tenant_id = %s"\n')
        self.assertTrue(lints.verificar(self.raiz))

    def test_um_set_local_passa(self) -> None:
        self.escrever('SQL = "SET LOCAL app.tenant_id = %s"\n')
        self.assertEqual(lints.verificar(self.raiz), [])

    def test_um_set_config_com_false_literal_e_apanhado(self) -> None:
        self.escrever("SQL = \"SELECT set_config('app.tenant_id', %s, false)\"\n")
        achados = lints.verificar(self.raiz)
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("escrito a letra", achados[0])

    def test_um_set_config_com_true_literal_passa(self) -> None:
        self.escrever("SQL = \"SELECT set_config('app.tenant_id', %s, true)\"\n")
        self.assertEqual(lints.verificar(self.raiz), [])

    def test_um_chamador_que_passa_false_e_apanhado(self) -> None:
        """A regra 3: o `is_local` vem por parametro, e veem-se os chamadores.

        E a regra que apanhou o unico sitio real deste conjunto, e nenhuma das
        outras duas o via: o SQL esta correcto e e **a chamada** que esta errada.
        """
        self.escrever(
            "SQL_CONTEXTO = \"SELECT set_config('app.tenant_id', %s, %s)\"\n"
            "\n"
            "def mal(bd, tenant):\n"
            "    bd.executar(SQL_CONTEXTO, (tenant, False))\n"
        )
        achados = lints.verificar(self.raiz)
        self.assertTrue(achados, "o chamador que passa `False` tem de ser nomeado")
        self.assertIn("is_local = false", " ".join(achados).lower())

    def test_um_chamador_que_passa_true_passa(self) -> None:
        self.escrever(
            "SQL_CONTEXTO = \"SELECT set_config('app.tenant_id', %s, %s)\"\n"
            "\n"
            "def bem(bd, tenant):\n"
            "    bd.executar(SQL_CONTEXTO, (tenant, True))\n"
        )
        self.assertEqual(lints.verificar(self.raiz), [])

    def test_um_is_local_indecifravel_falha_fechado(self) -> None:
        self.escrever(
            "SQL = \"SELECT set_config('app.tenant_id', %s, " "nao_sei_o_que_isto_e)\"\n"
        )
        achados = lints.verificar(self.raiz)
        self.assertTrue(achados)
        self.assertIn("nao sabe decidir", " ".join(achados))

    def test_o_mesmo_texto_num_comentario_nao_e_achado(self) -> None:
        """Um *lint* com falsos positivos em prosa e um *lint* que se desliga.

        As *docstrings* dos dois `tenant_guard` falam de `set_config` e de `SET
        LOCAL`, e o `consumo.py` desenha um `SET LOCAL app.tenant_id = …` num
        diagrama. Varrer o ficheiro inteiro dava achados nessas linhas.
        """
        self.escrever(
            '"""Esta docstring fala de SET app.tenant_id e de '
            "set_config('app.tenant_id', x, false), e nao e codigo.\"\"\"\n"
        )
        self.assertEqual(lints.verificar(self.raiz), [])

    def test_num_ts_o_comentario_tambem_nao_conta(self) -> None:
        ficheiro = self.raiz / "packages" / "core" / "src" / "guarda.ts"
        ficheiro.write_text(
            "// Nunca SET app.tenant_id de sessao, e nunca\n"
            "/* set_config('app.tenant_id', $1, false) */\n"
            "export const SQL = `SELECT set_config('app.tenant_id', $1, true)`;\n",
            encoding="utf-8",
        )
        self.assertEqual(lints.verificar(self.raiz), [])


class TestAsExcepcoes(ComArvore):
    def escrever_excepcao(self, razao: str, sitio: str = "SQL_CONTEXTO") -> None:
        (self.raiz / "ci" / "isolamento-set-sessao.yaml").write_text(
            "version: 1\nexcepcoes:\n"
            "  - ficheiro: libs/core/src/guarda.py\n"
            f"    sitio: {sitio}\n"
            "    credor: KAM-001\n"
            f"    razao: {razao}\n",
            encoding="utf-8",
        )

    def test_uma_excepcao_declarada_cala_o_achado(self) -> None:
        self.escrever(
            "SQL_CONTEXTO = \"SELECT set_config('app.tenant_id', %s, %s)\"\n"
            "\n"
            "def deliberado(bd, tenant):\n"
            "    bd.executar(SQL_CONTEXTO, (tenant, False))\n"
        )
        self.escrever_excepcao("x" * 80)
        self.assertEqual(lints.verificar(self.raiz), [])

    def test_uma_excepcao_morta_falha(self) -> None:
        """Uma porta que ficou aberta sem ninguem a usar."""
        self.escrever(
            "SQL_CONTEXTO = \"SELECT set_config('app.tenant_id', %s, %s)\"\n"
            "\n"
            "def bem(bd, tenant):\n"
            "    bd.executar(SQL_CONTEXTO, (tenant, True))\n"
        )
        self.escrever_excepcao("x" * 80)
        achados = lints.verificar(self.raiz)
        self.assertTrue(achados)
        self.assertIn("excepcao esta morta", achados[0])

    def test_uma_razao_curta_recusa_o_ficheiro(self) -> None:
        self.escrever_excepcao("curta demais")
        with self.assertRaises(lints.LintInvalido):
            lints.ler_excepcoes(self.raiz)

    def test_um_credor_sem_forma_de_ticket_recusa_o_ficheiro(self) -> None:
        (self.raiz / "ci" / "isolamento-set-sessao.yaml").write_text(
            "version: 1\nexcepcoes:\n"
            "  - ficheiro: libs/core/src/guarda.py\n"
            "    sitio: SQL_CONTEXTO\n"
            "    credor: o-dono-do-evt\n"
            f"    razao: {'x' * 80}\n",
            encoding="utf-8",
        )
        with self.assertRaises(lints.LintInvalido):
            lints.ler_excepcoes(self.raiz)


class TestORepositorio(unittest.TestCase):
    """A regressao: a arvore real esta conforme, com a excepcao que declara."""

    RAIZ = Path(__file__).resolve().parents[3]

    def test_conforme(self) -> None:
        self.assertEqual(lints.verificar(self.RAIZ), [])

    def test_a_unica_excepcao_e_a_do_trabalhador_do_evt(self) -> None:
        """Ha **uma**, e e a leitura do envelope fora de transaccao (KAM-038).

        Este teste existe para que uma segunda entrada seja uma alteracao
        visivel: o `is_local` falso e a unica forma de `app.tenant_id` neste
        conjunto que atravessa uma fronteira de transaccao, e a lista nao deve
        crescer sem alguem dar por isso.
        """
        excepcoes = lints.ler_excepcoes(self.RAIZ)
        self.assertEqual(len(excepcoes), 1, sorted(excepcoes))
        unica = next(iter(excepcoes.values()))
        self.assertEqual(
            unica.ficheiro, "packages/core-ts/src/eventos/trabalhador_bullmq.ts"
        )
        self.assertEqual(unica.credor, "KAM-038")

    def test_o_corpus_nao_varre_a_lista_de_mutacoes(self) -> None:
        """`db/mutacoes.py` contem `…, %s, false)` como **dado**.

        E a mutacao «helper: set_config de sessao (false)», que existe para
        provar que a suite mata a versao de sessao. Varrer a lista de mutacoes
        fazia este *lint* acusar a prova de que o defeito e apanhado.
        """
        self.assertIn("db/mutacoes.py", lints.FORA_DO_CORPUS)


if __name__ == "__main__":
    unittest.main()
