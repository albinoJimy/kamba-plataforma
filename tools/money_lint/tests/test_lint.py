"""O `money_lint` acusa o que deve e deixa passar o que deve (KAM-052).

O canario (`python -m money_lint canario`) ja prova que cada regra morde, e corre
**no gate 2**. Esta bateria mede o que ele nao mede: os falsos positivos que
tornariam o lint insustentavel, a aritmetica das linhas, e o comportamento do
varrimento quando a arvore nao tem a forma esperada.

A distincao entre as duas nao e cerimonia. Um lint que acusa a mais e desligado
por quem o encontra, e desligado nao protege nada — e por isso os ensaios de
«deixa passar» sao mais do que os de «acusa».
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from money_lint import cli, lint  # noqa: E402

RAIZ = Path(__file__).resolve().parents[3]


def regras(fonte: str) -> set[str]:
    return {a.regra for a in lint.varrer_texto(fonte, "ensaio.ts")}


class TestAcusa(unittest.TestCase):
    def test_um_literal_decimal_e_achado(self):
        self.assertIn(lint.FLUTUANTE, regras("const f = 1.14;"))

    def test_um_montante_tipado_number_e_achado(self):
        for fonte in (
            "type C = { amount: number };",
            "type C = { readonly valor_minor: number };",
            "let montante: number = 0n;",
            "function f(preco: number) {}",
            "type C = { fee?: number };",
        ):
            with self.subTest(fonte=fonte):
                self.assertIn(lint.NUMBER, regras(fonte), fonte)

    def test_as_conversoes_por_float_sao_achado(self):
        for fonte in (
            "const v = parseFloat(t);",
            "const v = parseInt(t, 10);",
            "const v = Number(t);",
            "const v = x.toFixed(2);",
            "const v = Math.round(x);",
            "const v = Math.trunc(x);",
        ):
            with self.subTest(fonte=fonte):
                self.assertIn(lint.CONVERSAO, regras(fonte), fonte)

    def test_a_aritmetica_com_literal_decimal_e_achado(self):
        for fonte in ("const v = minor / 100.0;", "const v = 1.14 * base;"):
            with self.subTest(fonte=fonte):
                self.assertIn(lint.DIVISAO, regras(fonte), fonte)

    def test_os_nomes_que_a_g3_proibe_sao_achado(self):
        for fonte in (
            "type C = { walletId: string };",
            "const balance = 0n;",
            "function abrirEscrow() {}",
            "const saldoDaPme = 0n;",
            "type C = { carteira: string };",
        ):
            with self.subTest(fonte=fonte):
                self.assertIn(lint.SEM_FUNDOS, regras(fonte), fonte)

    def test_minor_que_nao_seja_bigint_e_achado(self):
        for fonte in ("type Minor = number;", "type Minor = string;", "type Minor = Big;"):
            with self.subTest(fonte=fonte):
                self.assertIn(lint.MINOR, regras(fonte), fonte)

    def test_minor_bigint_nao_e_achado(self):
        self.assertNotIn(lint.MINOR, regras("export type Minor = bigint;"))


class TestDeixaPassar(unittest.TestCase):
    """Os falsos positivos que tornariam o lint insustentavel."""

    def test_segundos_e_comprimentos_sao_number_legitimo(self):
        fonte = (
            "type Capacidades = {\n"
            "  readonly chargeTtl: { readonly min: number; readonly max: number };\n"
            "  readonly idempotencyWindow: number;\n"
            "  readonly refMaxLen: number;\n"
            "};\n"
        )
        self.assertEqual(regras(fonte), set())

    def test_a_aritmetica_em_bigint_passa(self):
        fonte = "const kz = minor / 100n;\nconst c = minor % 100n;\n"
        self.assertEqual(regras(fonte), set())

    def test_um_comentario_pode_falar_de_floats(self):
        fonte = (
            "/**\n"
            " * Nunca `0.1 + 0.2`, nunca `parseFloat`, nunca `wallet`.\n"
            " */\n"
            "// E `balance` tambem nao: 0.14.\n"
            "export const X = 1n;\n"
        )
        self.assertEqual(regras(fonte), set())

    def test_uma_cadeia_pode_conter_o_que_o_codigo_nao_pode(self):
        fonte = 'export const NOTA = "nunca 0.14, nunca parseFloat, nunca wallet";\n'
        self.assertEqual(regras(fonte), set())

    def test_uma_propriedade_com_ponto_nao_e_um_decimal(self):
        self.assertEqual(regras("const v = conta.valor;\nconst w = a.b.c;\n"), set())

    def test_number_max_safe_integer_nao_e_uma_conversao(self):
        self.assertEqual(regras("if (x > Number.MAX_SAFE_INTEGER) {}"), set())

    def test_um_separador_de_milhares_nao_e_um_decimal(self):
        self.assertEqual(regras("const v = 102_409n;\nconst w = 1_000_000;\n"), set())


class TestAritmeticaDasLinhas(unittest.TestCase):
    """O numero de linha tem de apontar para o sitio certo.

    Sem isto, cada achado depois de um comentario de bloco aponta para a linha
    errada — e um lint que aponta para o sitio errado e um lint que se ignora.
    """

    def test_a_linha_sobrevive_a_um_comentario_de_bloco(self):
        fonte = "/*\n linha 2\n linha 3\n*/\nconst f = 1.14;\n"
        achados = lint.varrer_texto(fonte, "ensaio.ts")
        self.assertEqual([a.linha for a in achados], [5])

    def test_a_linha_do_minor_e_a_da_declaracao(self):
        fonte = "// um\n// dois\ntype Minor = number;\n"
        achados = [a for a in lint.varrer_texto(fonte, "ensaio.ts") if a.regra == lint.MINOR]
        self.assertEqual([a.linha for a in achados], [3])


class TestVarrimentoDaArvore(unittest.TestCase):
    def test_varre_o_modulo_real_e_nao_acusa_nada(self):
        achados, lidos = lint.varrer(RAIZ)
        self.assertEqual([str(a) for a in achados], [])
        # **E leu alguma coisa.** Um verde sobre zero ficheiros nao diz nada.
        self.assertGreaterEqual(lidos, 8)

    def test_zero_ficheiros_levanta_em_vez_de_passar(self):
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.varrer(Path(__file__).parent)

    def test_os_ficheiros_sao_os_do_modulo(self):
        nomes = {p.name for p in lint.ficheiros(RAIZ)}
        for esperado in ("tipos.ts", "dinheiro.ts", "registo.ts", "index.ts"):
            self.assertIn(esperado, nomes)


class TestCanario(unittest.TestCase):
    def test_o_canario_passa(self):
        falhas, numeros = lint.canario(RAIZ / cli.PASTA_DO_CANARIO)
        self.assertEqual(falhas, [])
        self.assertEqual(numeros["negativas"], len(lint.REGRAS_OBRIGATORIAS))
        self.assertGreaterEqual(numeros["positivas"], 1)

    def test_ha_uma_negativa_por_regra_obrigatoria(self):
        pasta = RAIZ / cli.PASTA_DO_CANARIO / "negativas"
        prefixos = {p.name.split("__", 1)[0] for p in pasta.glob("*.ts")}
        self.assertEqual(prefixos, set(lint.REGRAS_OBRIGATORIAS))

    def test_uma_pasta_vazia_e_falha_e_nao_um_verde(self):
        falhas, numeros = lint.canario(Path(__file__).parent / "nao-existe")
        self.assertEqual(numeros, {"negativas": 0, "positivas": 0})
        self.assertNotEqual(falhas, [])


class TestCodigosDeSaida(unittest.TestCase):
    """0 = limpo, 1 = achados, 2 = configuracao. A distincao e o ponto.

    Um modulo que mudou de sitio nao pode parecer um modulo limpo — e a licao do
    `canon_lint`, e a do `lint_arch`, que sai com 2 e parece verde a quem le a
    ultima linha em vez do codigo.
    """

    def test_o_modulo_real_sai_com_zero(self):
        self.assertEqual(cli.main(["--root", str(RAIZ), "lint"]), 0)

    def test_o_canario_sai_com_zero(self):
        self.assertEqual(cli.main(["--root", str(RAIZ), "canario"]), 0)

    def test_uma_arvore_sem_o_modulo_sai_com_dois(self):
        self.assertEqual(cli.main(["--root", str(Path(__file__).parent), "lint"]), 2)

    def test_um_ficheiro_com_achado_sai_com_um(self):
        negativa = RAIZ / cli.PASTA_DO_CANARIO / "negativas" / "minor__minor_como_number.ts"
        self.assertEqual(cli.main(["ficheiro", str(negativa)]), 1)

    def test_um_ficheiro_limpo_sai_com_zero(self):
        positiva = RAIZ / cli.PASTA_DO_CANARIO / "positivas" / "aritmetica_em_bigint.ts"
        self.assertEqual(cli.main(["ficheiro", str(positiva)]), 0)

    def test_um_ficheiro_que_nao_existe_sai_com_dois(self):
        self.assertEqual(cli.main(["ficheiro", str(RAIZ / "nao-existe.ts")]), 2)


if __name__ == "__main__":
    unittest.main()
