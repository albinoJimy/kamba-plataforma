"""Um `setUpModule` que salta, para injectar no `estado` uma frase que nao e um
caso. Ver o `caso_colapso.py` desta pasta: sao duas, e sao duas porque e isso
que enche a conta de `corridos - len(estado)` ate ela fechar.
"""

from __future__ import annotations

import unittest


def setUpModule() -> None:
    raise unittest.SkipTest('modulo saltado de proposito')


class TestNuncaCorre2(unittest.TestCase):
    def test_nunca_corre(self) -> None:
        pass
