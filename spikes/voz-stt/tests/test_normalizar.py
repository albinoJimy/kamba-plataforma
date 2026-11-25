import unittest

from normalizar import VERSAO_DAS_REGRAS, normalizar, numerico


class TestNumerais(unittest.TestCase):
    """O exemplo da letra do bloco, e as composições que o rodeiam."""

    CASOS = {
        "mil e quinhentos": ["1500"],
        "1.500": ["1500"],
        "1500": ["1500"],
        "mil quinhentos": ["1500"],
        "dois mil e trezentos": ["2300"],
        "dois mil trezentos e cinco": ["2305"],
        "cento e vinte e cinco": ["125"],
        "duzentos mil e quinhentos": ["200500"],
        "um milhão e duzentos mil": ["1200000"],
        "cento e cinquenta mil": ["150000"],
        "2 mil": ["2000"],
        "mil": ["1000"],
        "vinte e três": ["23"],
        "trezentas e sessenta": ["360"],
        "dois mil e vinte e sete": ["2027"],
        "dezasseis": ["16"],
        "dezesseis": ["16"],
        "catorze": ["14"],
        "quatorze": ["14"],
        "15.000": ["15000"],
        "150.000 kwanzas": ["150000", "kz"],
    }

    def test_casos(self):
        for texto, esperado in self.CASOS.items():
            with self.subTest(texto=texto):
                self.assertEqual(normalizar(texto), esperado)

    def test_referencia_e_hipotese_dao_o_mesmo(self):
        self.assertEqual(normalizar("Doze mil e quinhentos kwanzas"), normalizar("12.500 Kz"))
        self.assertEqual(normalizar("custa 7.200 Kz."), normalizar("custa sete mil e duzentos kwanzas"))

    def test_dois_numeros_nao_se_colam(self):
        self.assertEqual(normalizar("vinte cinco"), ["20", "5"])
        self.assertEqual(normalizar("entre vinte e cinco e trinta mil"), ["entre", "25", "e", "30000"])

    def test_e_acentuado_e_verbo_e_nao_compoe(self):
        self.assertEqual(normalizar("dez é cinco"), ["10", "é", "5"])

    def test_um_e_cento_sozinhos_nao_sao_numeros(self):
        self.assertEqual(normalizar("um saco"), ["um", "saco"])
        self.assertEqual(normalizar("uma caixa"), ["uma", "caixa"])
        self.assertEqual(normalizar("dez por cento"), ["10", "por", "cento"])
        self.assertEqual(normalizar("10%"), normalizar("dez por cento"))

    def test_um_e_cento_compostos_sao_numeros(self):
        self.assertEqual(normalizar("vinte e um"), ["21"])
        self.assertEqual(normalizar("um milhão"), ["1000000"])
        self.assertEqual(normalizar("cento e um"), ["101"])
        self.assertEqual(normalizar("mil cento e vinte"), ["1120"])

    def test_pontuacao_separa_numeros(self):
        self.assertEqual(normalizar("custa mil. Dois sacos"), ["custa", "1000", "2", "sacos"])
        self.assertEqual(normalizar("mil, dois mil, três mil"), ["1000", "2000", "3000"])

    def test_milhares_com_decimal(self):
        self.assertEqual(normalizar("1.500,50"), ["1500,50"])

    def test_hora_certa(self):
        self.assertEqual(normalizar("às 19h00"), normalizar("às dezanove horas"))
        self.assertEqual(normalizar("às 19h00"), normalizar("às 19h"))


class TestTexto(unittest.TestCase):
    def test_minusculas_e_sem_pontuacao(self):
        self.assertEqual(normalizar("Bom dia, Kota! Está bom?"), ["bom", "dia", "kota", "está", "bom"])

    def test_acentos_ficam(self):
        self.assertNotEqual(normalizar("esta"), normalizar("está"))

    def test_moeda(self):
        for forma in ("kz", "Kz", "kwanza", "kwanzas", "kuanzas", "AKZ", "aoa"):
            with self.subTest(forma=forma):
                self.assertEqual(normalizar(forma), ["kz"])

    def test_horas(self):
        self.assertEqual(normalizar("às 14h30"), normalizar("às 14:30"))
        self.assertEqual(normalizar("às 14h30"), ["às", "14", "h", "30"])
        self.assertEqual(normalizar("dezasseis horas"), ["16", "h"])

    def test_decimal_fica_num_token(self):
        self.assertEqual(normalizar("2,5 kg"), ["2,5", "kg"])
        self.assertTrue(numerico("2,5"))
        self.assertFalse(numerico("kz"))

    def test_versao(self):
        self.assertEqual(VERSAO_DAS_REGRAS, "1")


class TestLimitacoes(unittest.TestCase):
    """O que a versão 1 **não** iguala, fixado para que se veja ao mudar de versão."""

    def test_hora_dita_com_e_nao_iguala_a_escrita(self):
        self.assertEqual(normalizar("catorze e trinta"), ["14", "e", "30"])
        self.assertNotEqual(normalizar("catorze e trinta"), normalizar("14h30"))

    def test_grafia_brasileira_conta_como_diferente(self):
        self.assertNotEqual(normalizar("factura"), normalizar("fatura"))

    def test_outras_formas_que_a_v1_nao_iguala(self):
        pares = (
            ("nove e meia", "9h30"),
            ("dois mil e quinhentos", "2,5 mil"),
            ("doze mil e quinhentos", "12 500"),
            ("sete mil e duzentos", "7,200"),
            ("um saco", "1 saco"),
        )
        for a, b in pares:
            with self.subTest(a=a, b=b):
                self.assertNotEqual(normalizar(a), normalizar(b))
        self.assertEqual(normalizar("dez e um quarto"), ["11", "quarto"])
        self.assertEqual(normalizar("1000 500"), ["1000", "500"])


if __name__ == "__main__":
    unittest.main()
