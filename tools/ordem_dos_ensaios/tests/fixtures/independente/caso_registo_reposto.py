"""As mesmas duas classes, com o mesmo estado de processo, **reposto por quem o
suja**. Verdes nas duas ordens.

Existe para a metade do canario que se esquece: um verificador que declarasse
toda a suite dependente da ordem — comparador invertido, um `skip` contado como
vermelho, uma falha no arranque — tambem fazia a *fixture* `dependente/`
morder, e passava o canario sem nunca ter medido se distingue. Este caso e o
que mede isso.

A diferenca com a *fixture* irma e uma linha: o `addCleanup`. E a forma da
correccao que este portao pede a quem o faz ficar vermelho.

O nome do ficheiro **nao** e igual ao da irma de proposito: o canario corre
cada *fixture* no seu processo e dois `caso_registo` nao se veriam, mas a suite
deste modulo corre as duas no mesmo processo e o segundo `import` devolvia o
primeiro modulo do `sys.modules`. E a mesma familia de defeito que o portao
existe para apanhar, dentro do portao.
"""

from __future__ import annotations

import unittest

REGISTO: set[str] = set()


class TestALeitura(unittest.TestCase):
    def test_o_registo_comeca_vazio(self) -> None:
        self.assertEqual(REGISTO, set())


class TestZEscrita(unittest.TestCase):
    def test_escreve_no_registo_e_repoe_o(self) -> None:
        self.addCleanup(REGISTO.discard, 'temporario')
        REGISTO.add('temporario')
        self.assertIn('temporario', REGISTO)
