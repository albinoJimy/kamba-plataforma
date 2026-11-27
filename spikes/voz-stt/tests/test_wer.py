import unittest

from wer import OMISSAO, SUBSTITUICAO, agregar, alinhar, alinhar_tokens


class TestOperacoes(unittest.TestCase):
    """Os três casos que os «Testes Requeridos» nomeiam, e o dos numerais."""

    def test_igual(self):
        a = alinhar("quero dois sacos", "quero dois sacos")
        self.assertEqual((a.erros, a.n_referencia, a.wer), (0, 3, 0.0))

    def test_substituicao(self):
        a = alinhar("quero dois sacos", "quero dois sapos")
        self.assertEqual((a.substituicoes, a.omissoes, a.insercoes), (1, 0, 0))
        self.assertAlmostEqual(a.wer, 1 / 3)

    def test_omissao(self):
        a = alinhar("quero dois sacos de arroz", "quero sacos de arroz")
        self.assertEqual((a.substituicoes, a.omissoes, a.insercoes), (0, 1, 0))
        self.assertEqual([o for o, _, _ in a.operacoes].count(OMISSAO), 1)
        self.assertAlmostEqual(a.wer, 1 / 5)

    def test_insercao(self):
        a = alinhar("quero arroz", "eu quero arroz")
        self.assertEqual((a.substituicoes, a.omissoes, a.insercoes), (0, 0, 1))
        self.assertAlmostEqual(a.wer, 1 / 2)

    def test_numerais_por_extenso_contra_algarismos(self):
        a = alinhar("custa mil e quinhentos kwanzas", "custa 1.500 Kz")
        self.assertEqual(a.erros, 0)
        self.assertEqual(a.n_referencia, 3)

    def test_wer_pode_passar_de_um(self):
        a = alinhar("sim", "não não não")
        self.assertEqual(a.erros, 3)
        self.assertEqual(a.wer, 3.0)

    def test_hipotese_vazia_e_tudo_omissao(self):
        a = alinhar("quero dois sacos", "")
        self.assertEqual((a.omissoes, a.wer), (3, 1.0))

    def test_referencia_vazia_nao_tem_wer(self):
        with self.assertRaises(ValueError):
            alinhar("", "olá").wer

    def test_empate_e_deterministico(self):
        a = alinhar_tokens(["a", "b"], ["b", "a"])
        b = alinhar_tokens(["a", "b"], ["b", "a"])
        self.assertEqual(a.operacoes, b.operacoes)
        self.assertEqual(a.erros, 2)


class TestPrecisaoNumerica(unittest.TestCase):
    def test_numero_trocado(self):
        a = alinhar("são doze mil e quinhentos", "são doze mil e seiscentos")
        self.assertEqual((a.numericos_na_referencia, a.numericos_certos), (1, 0))
        self.assertEqual(a.substituicoes, 1)
        self.assertEqual(a.operacoes[1][0], SUBSTITUICAO)

    def test_numero_certo(self):
        a = alinhar("às 14h30 com 3 pessoas", "às 14:30 com três pessoas")
        self.assertEqual((a.numericos_na_referencia, a.numericos_certos), (3, 3))

    def test_numero_inventado_conta_a_parte(self):
        a = alinhar("quero arroz", "quero 2 arroz")
        self.assertEqual((a.numericos_na_referencia, a.insercoes_numericas), (0, 1))


class TestAgregado(unittest.TestCase):
    def test_micro_e_nao_media_de_clips(self):
        curto = alinhar("sim", "não")  # WER 1
        longo = alinhar(" ".join(["a"] * 9), " ".join(["a"] * 9))  # WER 0
        ag = agregar([curto, longo])
        self.assertEqual((ag.palavras, ag.erros), (10, 1))
        self.assertAlmostEqual(ag.wer, 0.1)  # a média por clip daria 0,5

    def test_sem_numeros_a_precisao_nao_e_zero(self):
        self.assertIsNone(agregar([alinhar("sim", "sim")]).precisao_numerica)
        self.assertIsNone(agregar([]).wer)


if __name__ == "__main__":
    unittest.main()
