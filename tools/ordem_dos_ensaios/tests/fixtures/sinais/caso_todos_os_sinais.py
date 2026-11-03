"""Um teste por sinal do `unittest`, para o `Registo` os classificar todos.

Esta *fixture* existe por causa do buraco que a revisao adversarial encontrou, e
mais ainda por causa da **razao** pela qual ele escapou: nenhum caso da suite
deste modulo fazia passar um vermelho **atraves** do `Registo`. Os que havia ou
corriam combinacoes que ficam verdes, ou construiam um `Resultado` a mao. Um
sinal em falta — e faltava o `addSubTest` — era invisivel.

Com esta *fixture*, um `hook` que desapareca ou mude de assinatura faz o
`test_corredor.TestOsSinaisDoUnittest` ficar vermelho, em vez de dar um teste
classificado `ok` que falhou.

Nao e dependente da ordem: cada caso e o que e em qualquer ordem. Nao e uma
*fixture* do canario — e material da suite — e por isso **nao** entra em
`canario.CASOS`. O nome `caso_*.py` e o que impede o `unittest discover` das
suites de `tools/` de a apanhar, como nas irmas.
"""

from __future__ import annotations

import unittest


class TestOk(unittest.TestCase):
    def test_passa(self) -> None:
        pass


class TestFalha(unittest.TestCase):
    def test_falha(self) -> None:
        self.fail('vermelho de proposito')


class TestErro(unittest.TestCase):
    def test_erro(self) -> None:
        raise RuntimeError('erro de proposito')


class TestSaltado(unittest.TestCase):
    @unittest.skip('saltado de proposito')
    def test_saltado(self) -> None:
        pass


class TestFalhaEsperada(unittest.TestCase):
    @unittest.expectedFailure
    def test_falha_esperada(self) -> None:
        self.fail('esperado')


class TestSucessoInesperado(unittest.TestCase):
    @unittest.expectedFailure
    def test_sucesso_inesperado(self) -> None:
        pass


class TestSubTest(unittest.TestCase):
    def test_falha_dentro_de_subtest(self) -> None:
        """O sinal que faltava: o `unittest` nao chama `addFailure` aqui."""
        for valor in (1, 2):
            with self.subTest(valor=valor):
                self.assertEqual(valor, 1)
