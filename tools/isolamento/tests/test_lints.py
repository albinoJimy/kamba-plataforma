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

    def test_num_ts_um_literal_com_barra_e_asterisco_nao_esconde_o_que_vem_depois(
        self,
    ) -> None:
        """A outra metade do defeito que o KAM-178 mediu, deste lado.

        O limpador de comentarios era uma expressao regular cega as cadeias, e
        o `/*` dentro de um literal — `app.use("/internal/*", ...)` — abria um
        comentario falso que o proximo `*/` fechava. Do lado da enumeracao isso
        apagou sete rotas; deste lado apaga **codigo que o *lint* tinha de
        varrer**, e o «0 achados» passa a medir menos do que diz. O mesmo vale
        para o `//` de um `"https://..."`, que apagava o resto da linha.

        O canario tem as duas formas e um `set_config(..., false)` depois de
        cada uma.
        """
        ficheiro = self.raiz / "packages" / "core" / "src" / "guarda.ts"
        # **A disposicao das linhas e que faz o canario morder**, e a primeira
        # versao disto nao mordia: tinha o `*/` antes do `set_config` e o
        # `https://` numa linha so sua, pelo que a versao cega apagava apenas
        # ruido e os dois achados apareciam de qualquer maneira. Um canario
        # que passa com a mutacao aplicada e um canario morto — a classe de
        # defeito que este ticket existe para fechar. Medido, e redisposto
        # para que o codigo a esconder fique **dentro** do bloco falso e
        # **depois** do `//` na mesma linha.
        ficheiro.write_text(
            'const rota = "/internal/*";\n'
            "export const SQL_A = `SELECT set_config('app.tenant_id', $1, false)`;\n"
            "/* o fecho do bloco falso vem aqui, depois do SQL_A. */\n"
            'const u = "https://exemplo/x"; '
            "export const SQL_B = `SELECT set_config('app.tenant_id', $1, false)`;\n",
            encoding="utf-8",
        )
        achados = lints.verificar(self.raiz)
        self.assertEqual(len(achados), 2, achados)
        for achado in achados:
            with self.subTest(achado=achado):
                self.assertIn("escrito a letra", achado)


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

    def test_as_duas_excepcoes_sao_as_medidas_e_cada_uma_conta_um_sitio(self) -> None:
        """Ha **duas**, e as duas apareceram por medicao e nao por conveniencia.

        A primeira e a leitura do envelope fora de transaccao (KAM-038). A
        segunda e o verificador da cadeia de auditoria (KAM-012), e **so entrou
        quando o corpus deixou de ser quatro globs**: a revisao adversarial
        mediu que `db/auditoria.py` tem um `set_config(..., false)` escrito a
        letra e ficava fora da varredura, pelo que o «0 achados» media menos do
        que dizia.

        Este ensaio existe para que uma terceira entrada seja uma alteracao
        visivel, e para que o `ocorrencias` de cada uma nao cresca sem ninguem
        dar por isso — e com ele que «um segundo `false` no mesmo sitio e achado
        novo» passa de promessa a verdade.
        """
        excepcoes = lints.ler_excepcoes(self.RAIZ)
        self.assertEqual(
            {chave: entrada.credor for chave, entrada in excepcoes.items()},
            {
                "packages/core-ts/src/eventos/trabalhador_bullmq.ts"
                "#SQL_DEFINIR_TENANT": "KAM-038",
                "db/auditoria.py#main": "KAM-012",
            },
        )
        for chave, entrada in excepcoes.items():
            with self.subTest(excepcao=chave):
                self.assertEqual(entrada.ocorrencias, 1)

    def test_o_corpus_ve_o_db_inteiro_e_nao_tres_ficheiros(self) -> None:
        """O `db/auditoria.py` **tem** de estar no corpus: e la o segundo `false`.

        A primeira versao do `CORPUS` levava `rls.py`, `bootstrap.py` e as
        revisoes, debaixo da frase «codigo que corre contra a base, e so esse» —
        e `db/` tem mais codigo que corre contra a base do que isso. Uma lista a
        mao de ficheiros a **incluir** falha para o lado errado: o ficheiro novo
        fica de fora em silencio.
        """
        no_corpus = {
            caminho.relative_to(self.RAIZ).as_posix()
            for caminho in lints._ficheiros(self.RAIZ)
        }
        for ficheiro in (
            "db/auditoria.py",
            "db/ligacao.py",
            "tools/isolamento/semente.py",
        ):
            with self.subTest(ficheiro=ficheiro):
                self.assertIn(ficheiro, no_corpus)

    def test_o_corpus_nao_varre_a_lista_de_mutacoes(self) -> None:
        """`db/mutacoes.py` contem `…, %s, false)` como **dado**.

        E a mutacao «helper: set_config de sessao (false)», que existe para
        provar que a suite mata a versao de sessao. Varrer a lista de mutacoes
        fazia este *lint* acusar a prova de que o defeito e apanhado.
        """
        self.assertIn("db/mutacoes.py", lints.FORA_DO_CORPUS)


if __name__ == "__main__":
    unittest.main()
