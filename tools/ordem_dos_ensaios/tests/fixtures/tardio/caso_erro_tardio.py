"""Hipotese 3: um erro chega ao `TestResult` **depois** de o caso ter sido
classificado como verde.

E a forma do exemplar medido a 2026-11-05 — um erro de concorrencia num
`asyncio.run` sobre cinquenta tarefas, levantado quando o caso que o lancou ja
tinha terminado. Reproduzi-lo com `threading` real dava uma *fixture*
intermitente, e esta casa recusa isso (ver o `corredor`: a ordem e
deterministica de proposito). Reproduz-se portanto a **forma** e nao o
mecanismo: o caso passa, e a seguir um erro entra no `TestResult` atribuido a
ele.

A entrada e feita **a mao** no `failures` do resultado, sem passar pelo
`addFailure`, e e isso que a torna fiel: se passasse pelo `addFailure`, o
`Registo` derrubava-o e classificava o caso `failure` — e nao havia discordancia
nenhuma para medir. O que o exemplar tinha era precisamente um sinal que chegou
ao `TestResult` sem o `Registo` o ver mudar de ideias sobre o caso.

O `self._outcome.result` e privado do `unittest`. Usa-se aqui, e so aqui, por
nao haver forma publica de um teste encenar o que o proprio `unittest` lhe faz
por baixo — e e uma *fixture*, cujo trabalho e encenar exactamente isso.

Como as irmas, chama-se `caso_*.py`: com um nome `test_*.py` o `unittest
discover` das suites de `tools/` apanhava-a e fazia o *gate* 4 vermelho por
desenho.
"""

from __future__ import annotations

import unittest


class TestTardio(unittest.TestCase):
    def test_passa_e_o_erro_chega_depois(self) -> None:
        resultado = self._outcome.result
        self.addCleanup(
            resultado.failures.append,
            (
                self,
                'Traceback (most recent call last):\n'
                '  ...\n'
                'RuntimeError: erro tardio de proposito\n',
            ),
        )

    def test_passa_e_fica_verde(self) -> None:
        pass
