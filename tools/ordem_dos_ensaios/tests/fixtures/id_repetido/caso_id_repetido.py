"""Hipotese 2: dois casos com o mesmo `id()`, e o verde do ultimo apaga o
vermelho do meio.

O `estado` do `Registo` e um dicionario indexado pelo `id()` (esta escrito no
cabecalho do `corredor`: **com perdas**). Tres metodos a devolver o mesmo `id()`
colapsam numa entrada so, e a ultima escrita ganha. Os tres estao dispostos para
a ultima escrita ser **verde nas duas ordens**: `a` passa, `b` falha, `c` passa.
Na ordem de omissao corre `a, b, c` e na inversa `c, b, a` — nas duas o ultimo a
escrever e um verde, pelo que nas duas o dicionario esconde a falha.

E o que distingue esta hipotese das outras duas sem adivinhar: `corridos` vem do
`testsRun` do `TestResult` e conta tres, e o `estado` tem **uma** chave. A
diferenca entre os dois numeros e a prova do `id()` repetido, e no exemplar de
2026-11-05 ela era zero (1402 e 1402) — que e como esta hipotese fica excluida
la.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar.
"""

from __future__ import annotations

import unittest

#: O `id()` que os tres metodos partilham.
IDENTIFICADOR = 'caso_id_repetido.TestColapso.test_o_mesmo_id'


class TestColapso(unittest.TestCase):
    def id(self) -> str:
        return IDENTIFICADOR

    def test_a_passa(self) -> None:
        pass

    def test_b_falha(self) -> None:
        self.fail('vermelho de proposito, escondido pelo id() repetido')

    def test_c_passa(self) -> None:
        pass
