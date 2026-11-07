"""O caso em que **nao ha** `id()` de teste para nomear: um `tearDownModule` que
levanta.

Erros de `setUpClass`, `tearDownClass`, `setUpModule` e `tearDownModule` entram
no `TestResult` dentro de um `unittest.suite._ErrorHolder`, cujo `id()` e uma
frase (`tearDownModule (caso_sem_caso)`) e nao um identificador de caso. Tratar
essa frase como um `id()` de teste era inventar um caso que nao existe.

E esta *fixture* que mantem o critério 2 do KAM-182 necessario: quando nem o
`TestResult` nomeia um caso, o portao **continua** a sair com codigo nao-zero e
a dizer que nao conseguiu atribuir a falha. Um corredor que nomeasse melhor mas
passasse a dar verde quando nao sabe era pior do que o de hoje.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar.
"""

from __future__ import annotations

import unittest


def tearDownModule() -> None:
    raise RuntimeError('tearDownModule vermelho de proposito')


class TestPassa(unittest.TestCase):
    def test_passa(self) -> None:
        pass
