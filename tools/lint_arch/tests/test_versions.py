"""Comparacao de versoes e a postura fail-closed do limiar.

O caso que estes testes guardam e o do LiteLLM: `>=1.83.0` **nao** basta como
prova de que a versao instalada esta acima do limiar, porque a resolucao pode
trazer outra coisa. Para um pacote que ja foi vector de ataque, exige-se pin
exacto (`docs/tecnica/08` §4.8, E4 §2.7).
"""

from __future__ import annotations

import unittest

from lint_arch import versions


class TestParse(unittest.TestCase):
    def test_numericas(self) -> None:
        self.assertEqual(versions.parse("1.83.0"), (1, 83, 0))
        self.assertEqual(versions.parse("1"), (1,))

    def test_nao_numericas(self) -> None:
        for texto in ("1.83.0rc1", "latest", "", "^1.2.3", "1.x", "1..2"):
            with self.subTest(texto=texto):
                self.assertIsNone(versions.parse(texto))


class TestCompare(unittest.TestCase):
    def test_ordem(self) -> None:
        self.assertEqual(versions.compare("1.83.0", "1.83.0"), 0)
        self.assertEqual(versions.compare("1.104.2", "1.83.0"), 1)
        self.assertEqual(versions.compare("1.82.8", "1.83.0"), -1)

    def test_larguras_diferentes(self) -> None:
        self.assertEqual(versions.compare("1.83", "1.83.0"), 0)
        self.assertEqual(versions.compare("2", "1.83.0"), 1)

    def test_comparacao_numerica_e_nao_lexicografica(self) -> None:
        # O erro classico: "1.9" > "1.10" em texto, mas nao em versao.
        self.assertEqual(versions.compare("1.10.0", "1.9.0"), 1)

    def test_incomparaveis(self) -> None:
        self.assertIsNone(versions.compare("latest", "1.83.0"))


class TestExactPin(unittest.TestCase):
    def test_reconhece_pins(self) -> None:
        for texto, esperado in (
            ("1.83.0", "1.83.0"),
            ("==1.83.0", "1.83.0"),
            ("=1.83.0", "1.83.0"),
            ("  1.83.0  ", "1.83.0"),
            ("v1.83.0", "1.83.0"),
        ):
            with self.subTest(texto=texto):
                self.assertEqual(versions.exact_pin(texto), esperado)

    def test_recusa_intervalos(self) -> None:
        for texto in (
            "^1.83.0",
            "~1.83.0",
            ">=1.83.0",
            ">1.83.0",
            "*",
            "latest",
            "1.x",
            ">=1.83.0,<2",
            "",
        ):
            with self.subTest(texto=texto):
                self.assertIsNone(versions.exact_pin(texto))


class TestSatisfiesFloor(unittest.TestCase):
    def test_pin_acima_passa(self) -> None:
        for texto in ("1.83.0", "==1.104.2", "2.0.0"):
            with self.subTest(texto=texto):
                permitido, _ = versions.satisfies_floor(texto, "1.83.0")
                self.assertTrue(permitido)

    def test_pin_abaixo_falha(self) -> None:
        for texto in ("1.82.7", "==1.82.8", "1.0.0"):
            with self.subTest(texto=texto):
                permitido, motivo = versions.satisfies_floor(texto, "1.83.0")
                self.assertFalse(permitido)
                self.assertIn("abaixo do limiar", motivo)

    def test_intervalo_que_permitiria_versao_boa_falha_mesmo_assim(self) -> None:
        """`>=1.83.0` nao prova nada: e o nucleo da postura fail-closed."""
        for texto in (">=1.83.0", "^1.83.0", "~1.104", "*", "latest", ""):
            with self.subTest(texto=texto):
                permitido, motivo = versions.satisfies_floor(texto, "1.83.0")
                self.assertFalse(permitido)
                self.assertIn("pin exacto", motivo)


if __name__ == "__main__":
    unittest.main()
