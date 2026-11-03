"""Corre uma suite numa ordem dada e devolve o resultado de cada teste.

## Que ordem, e porque esta

`inversa` e a lista achatada ao contrario: inverte a ordem dos modulos, a das
classes dentro de cada modulo e a dos metodos dentro de cada classe. E a ordem
mais distante da de omissao que continua **deterministica**, e e deliberado que
seja deterministica: uma ordem embaralhada por semente de relogio apanharia
mais acoplamentos e tornaria o *gate* 4 intermitente, o que ensina a reexecutar
em vez de corrigir. Esta casa recusa isso.

Inverter a lista achatada **mantem os metodos de uma classe juntos**, pelo que
o `setUpClass` e o `tearDownClass` continuam a correr uma vez por classe. Um
embaralhamento que os intercalasse fazia-os correr varias vezes, e um teste
vermelho por causa disso nao seria acoplamento — seria a medicao a inventar o
defeito.

## Cada ordem no seu processo, e isso nao e detalhe de implementacao

Correr as duas ordens no mesmo processo media outra coisa. A segunda passagem
herdava o estado que a primeira deixou — o `sys.modules` cheio, os registos a
nivel de modulo sujos, os *loggers* com nome ja criados — e um teste podia
ficar vermelho por causa da passagem anterior e nao da ordem. Quem corre cada
ordem no seu processo e o `cli`; este modulo e o que corre **dentro** de um.
"""

from __future__ import annotations

import io
import unittest
from typing import Iterator, NamedTuple

#: As ordens que este corredor conhece. `normal` e a do `unittest`, e existe
#: para o canario poder afirmar a precondicao («a *fixture* esta verde na ordem
#: de omissao») em vez de a supor.
ORDENS = ('normal', 'inversa')

#: Os estados que nao fazem uma suite vermelha. O `skip` esta aqui porque um
#: teste saltado nos dois lados nao e sinal de ordem; uma suite **toda**
#: saltada e apanhada pela contagem, nao por aqui (ver `cli`).
VERDE = frozenset({'ok', 'skip', 'expected-failure'})


class Resultado(NamedTuple):
    #: `{id do teste: estado}`, com os estados do `Registo` abaixo.
    estado: dict[str, str]
    #: Quantos testes correram. Zero e falha, nunca uma suite limpa.
    corridos: int

    def vermelhos(self) -> list[str]:
        return sorted(i for i, e in self.estado.items() if e not in VERDE)


def achatar(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    """Os casos de uma suite, sem as suites intermedias."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from achatar(item)
        else:
            yield item


def ordenar(
    testes: list[unittest.TestCase], ordem: str
) -> list[unittest.TestCase]:
    if ordem == 'normal':
        return list(testes)
    if ordem == 'inversa':
        return list(reversed(testes))
    raise ValueError(f'ordem desconhecida: {ordem!r}')


class Registo(unittest.TextTestResult):
    """Um `TestResult` que guarda o estado de cada teste pelo seu `id()`.

    O `TextTestResult` do `unittest` conta falhas e nomeia-as, mas nao diz o
    estado de um teste que passou — e e a lista inteira que o canario precisa
    de comparar entre duas ordens.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.estado: dict[str, str] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.estado[test.id()] = 'ok'

    def addError(self, test: unittest.TestCase, err: object) -> None:
        super().addError(test, err)  # type: ignore[arg-type]
        self.estado[test.id()] = 'error'

    def addFailure(self, test: unittest.TestCase, err: object) -> None:
        super().addFailure(test, err)  # type: ignore[arg-type]
        self.estado[test.id()] = 'failure'

    def addSkip(self, test: unittest.TestCase, razao: str) -> None:
        super().addSkip(test, razao)
        self.estado[test.id()] = 'skip'

    def addExpectedFailure(self, test: unittest.TestCase, err: object) -> None:
        super().addExpectedFailure(test, err)  # type: ignore[arg-type]
        self.estado[test.id()] = 'expected-failure'

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self.estado[test.id()] = 'unexpected-success'


def correr(
    start_dir: str, top_level: str, padrao: str, ordem: str
) -> tuple[Resultado, str]:
    """Descobre a suite, corre-a na `ordem`, e devolve o resultado e o relato.

    O relato do `unittest` volta como cadeia em vez de ir para o `stderr`: quem
    o imprime e o `cli`, e so quando ha vermelhos — um relato de mil linhas por
    cada suite verde enterrava o sinal.
    """
    carregador = unittest.defaultTestLoader
    suite = carregador.discover(
        start_dir=start_dir, pattern=padrao, top_level_dir=top_level
    )
    testes = ordenar(list(achatar(suite)), ordem)

    fluxo = io.StringIO()
    registo = Registo(fluxo, True, 1)
    unittest.TestSuite(testes).run(registo)
    return Resultado(registo.estado, len(registo.estado)), fluxo.getvalue()
