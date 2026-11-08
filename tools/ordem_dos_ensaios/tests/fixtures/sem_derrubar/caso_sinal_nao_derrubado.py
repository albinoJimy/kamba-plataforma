"""Hipotese 1: um sinal do `unittest` que o `Registo` nao derruba.

E a forma exacta do falso verde que o KAM-173 mediu: uma falha dentro de
`self.subTest(...)` chegava ao `TestResult` com o `id()` do **sub-caso**
(`...test_x [valor=2]`), que nunca passou pelo `startTest` e portanto nunca
existiu no `estado`. Com o `addSubTest` derrubado, esse buraco esta fechado; o
que **nao** esta fechado e o proximo sinal que o `unittest` acrescente, e e esse
que esta *fixture* encena.

O sinal entra no `errors` do resultado com um objecto que tem `id()` de teste e
que o `Registo` nunca viu comecar. Nao se encena desligando o `addSubTest` — isso
media a versao antiga do corredor e nao a de hoje.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar.
"""

from __future__ import annotations

import unittest


def sinal_de_fora(identificador: str) -> unittest.TestCase:
    """Um sinal com `id()` de teste que nunca passou pelo `startTest`.

    A forma e a do `unittest.case._SubTest`: um `TestCase` com o `id()` do
    caso-pai mais um sufixo. **E um `TestCase` de proposito** — e o que o
    distingue do `unittest.suite._ErrorHolder`, que nao e um caso e por isso
    nao tem `id()` de teste para nomear (ver a *fixture* `sem_caso/`). O que
    importa e que o `Registo` nunca o classificou.

    A classe e **local a esta funcao** e nao de modulo, e a razao esta medida:
    de modulo, o `loadTestsFromModule` apanhava-a — ele colhe todas as
    subclasses de `TestCase` que o `dir()` do modulo mostra, o nome nao conta —
    e corria o seu `runTest`, pelo que a *fixture* ficava vermelha pelo
    caminho normal e deixava de encenar o sinal por derrubar.
    """

    class SinalDeFora(unittest.TestCase):
        def __init__(self) -> None:
            super().__init__('runTest')

        def runTest(self) -> None:
            raise AssertionError('este sinal nunca e corrido, so acusado')

        def id(self) -> str:
            return identificador

        def __str__(self) -> str:
            return identificador

    return SinalDeFora()


class TestSinal(unittest.TestCase):
    def test_passa_e_o_sinal_entra_por_fora(self) -> None:
        resultado = self._outcome.result
        sinal = sinal_de_fora(f'{self.id()} [sinal-que-ninguem-derruba]')
        resultado.errors.append(
            (
                sinal,
                'Traceback (most recent call last):\n'
                '  ...\n'
                'RuntimeError: sinal nao derrubado, de proposito\n',
            )
        )
