"""Corre uma suite numa ordem dada e devolve o resultado de cada teste.

## Que ordem, e porque esta

`inversa` e a lista achatada ao contrario: inverte a ordem dos modulos, a das
classes dentro de cada modulo e a dos metodos dentro de cada classe. E a ordem
mais distante da de omissao que continua **deterministica**, e e deliberado que
seja deterministica: uma ordem embaralhada por semente de relogio apanharia
mais acoplamentos e tornaria o *gate* 4 intermitente, o que ensina a reexecutar
em vez de corrigir. Esta casa recusa isso.

Inverter a lista achatada **mantem os metodos de uma classe juntos**, pelo que
o `setUpClass` e o `tearDownClass` continuam a correr uma vez por classe. Esta
medido, e nao so afirmado: na suite de `libs/py-core` a inversao da 100 blocos
de classe para 100 classes distintas e 18 blocos de modulo para 18 modulos
distintos, nas duas ordens — nenhum bloco repartido. Um embaralhamento que os
intercalasse fazia-os correr varias vezes, e um teste vermelho por causa disso
nao seria acoplamento: seria a medicao a inventar o defeito.

## Cada ordem no seu processo, e isso nao e detalhe de implementacao

Correr as duas ordens no mesmo processo media outra coisa. A segunda passagem
herdava o estado que a primeira deixou — o `sys.modules` cheio, os registos a
nivel de modulo sujos, os *loggers* com nome ja criados — e um teste podia
ficar vermelho por causa da passagem anterior e nao da ordem. Quem corre cada
ordem no seu processo e o `cli`; este modulo e o que corre **dentro** de um.

## O veredicto vem do `TestResult`, e nao do dicionario

`estado` e um `dict` indexado pelo `id()` do teste, e e **com perdas**: um
`id()` repetido colapsa duas entradas, e um sinal do `unittest` que ninguem
derrube nunca chega la. A primeira versao derivava o veredicto dele, e a
revisao adversarial mostrou tres falsos verdes por isso — o pior deles medido:
uma falha dentro de `self.subTest(...)` vinha a `addSubTest`, que nao estava
derrubado, e a suite saia **verde** com o `unittest` a dizer
`FAILED (failures=1)`. Nas duas suites que este portao fecha ha 332 usos de
`subTest` em 55 ficheiros, pelo que o buraco cobria-os todos.

Por isso o `Resultado` leva tambem o `testsRun` e o `wasSuccessful()` do
proprio `TestResult`, e o `cli` **cruza-os** com o dicionario: um `sucesso`
falso sem nenhum vermelho nomeado e falha do instrumento, nao verde da suite.
E a rede que fecha qualquer sinal que o `unittest` acrescente no futuro, e nao
so os tres que foram encontrados.
"""

from __future__ import annotations

import traceback
import unittest
from typing import Iterator, NamedTuple

#: As ordens que este corredor conhece. `normal` e a do `unittest`.
ORDENS = ('normal', 'inversa')

#: Os estados que nao fazem uma suite vermelha. O `skip` esta aqui porque um
#: teste saltado nas **duas** ordens nao e sinal de ordem; um teste que exista
#: numa passagem e nao na outra — o que um `SkipTest` de modulo ou de classe
#: produz — e apanhado pela comparacao de inventarios do `cli`, que foi o
#: segundo falso verde que a revisao adversarial encontrou.
VERDE = frozenset({'ok', 'skip', 'expected-failure'})


class Resultado(NamedTuple):
    #: `{id do teste: estado}`, com os estados do `Registo` abaixo. **Com
    #: perdas**: ver o cabecalho deste modulo.
    estado: dict[str, str]
    #: O `testsRun` do `TestResult`, nao o tamanho do `estado`. Dois casos com
    #: o mesmo `id()` colapsam no dicionario e nao aqui.
    corridos: int
    #: O `wasSuccessful()` do `TestResult`. E o veredicto; o resto e diagnostico.
    sucesso: bool
    #: As falhas e os erros formatados, para quem ler o *gate* vermelho saber o
    #: que rebentou. Vazio quando `sucesso`.
    relato: str

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


class Registo(unittest.TestResult):
    """Um `TestResult` que guarda tambem o estado de cada teste pelo seu `id()`.

    Deriva do `TestResult` cru e nao do `TextTestResult`: nao ha fluxo de texto
    para escrever — o relato monta-se do `failures`/`errors` no fim — e o
    `TextTestResult` pedia tres argumentos posicionais por nada.

    **Todos os sinais do `unittest` estao derrubados**, o `addSubTest`
    incluido. Faltar um nao da erro: da um teste classificado `ok` que falhou,
    e foi assim que a primeira versao deixou passar 332 usos de `subTest`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.estado: dict[str, str] = {}
        #: `(id do pai, sub-caso, traceback)` por falha de `subTest`. O
        #: `TestResult` nao as guarda em lado nenhum legivel.
        self.subfalhas: list[tuple[str, str, str]] = []

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.estado[test.id()] = 'ok'

    def addError(self, test: unittest.TestCase, err: object) -> None:
        super().addError(test, err)  # type: ignore[arg-type]
        self.estado[test.id()] = 'error'

    def addFailure(self, test: unittest.TestCase, err: object) -> None:
        super().addFailure(test, err)  # type: ignore[arg-type]
        self.estado[test.id()] = 'failure'

    def addSubTest(
        self,
        test: unittest.TestCase,
        subtest: unittest.TestCase,
        err: object,
    ) -> None:
        """Uma falha dentro de `self.subTest(...)`.

        O `unittest` **nao** chama `addFailure` nestes casos, e o `err` e
        `None` quando o sub-caso passou. Guarda-se sob o `id()` do teste-pai,
        para o inventario continuar comparavel entre as duas ordens: um
        sub-caso nao existe na ordem de omissao nem na inversa como entrada
        propria.
        """
        super().addSubTest(test, subtest, err)  # type: ignore[arg-type]
        if err is None:
            return
        self.subfalhas.append(
            (test.id(), str(subtest), ''.join(traceback.format_exception(*err)))
        )
        if self.estado.get(test.id()) in (None, 'ok'):
            self.estado[test.id()] = 'subtest-failure'

    def addSkip(self, test: unittest.TestCase, razao: str) -> None:
        super().addSkip(test, razao)
        self.estado[test.id()] = 'skip'

    def addExpectedFailure(self, test: unittest.TestCase, err: object) -> None:
        super().addExpectedFailure(test, err)  # type: ignore[arg-type]
        self.estado[test.id()] = 'expected-failure'

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self.estado[test.id()] = 'unexpected-success'


def _relatar(registo: Registo) -> str:
    """As falhas e os erros, com o *traceback*.

    A primeira versao passava um `io.StringIO` ao `TextTestResult` e devolvia o
    que ele escrevia — que e a cadeia de pontos (`'.F'`), porque o
    `printErrors()` so e chamado pelo `TextTestRunner`. Numa suite de 1 361
    testes isso dava ao programador um `id` e a palavra `failure`. Monta-se
    aqui, do que o `TestResult` tem.
    """
    pedacos = []
    for rotulo, lista in (('FALHA', registo.failures), ('ERRO', registo.errors)):
        for teste, texto in lista:
            pedacos.append(f'{rotulo}: {teste}\n{texto}')
    for teste, subteste, erro in registo.subfalhas:
        pedacos.append(f'FALHA (subTest): {teste} [{subteste}]\n{erro}')
    return '\n'.join(pedacos)


def correr(
    start_dir: str, top_level: str, padrao: str, ordem: str
) -> Resultado:
    """Descobre a suite, corre-a na `ordem`, e devolve o resultado.

    O relato volta dentro do `Resultado` em vez de ir para o `stderr`: quem o
    imprime e o `cli`, e so quando ha vermelhos — um relato de mil linhas por
    cada suite verde enterrava o sinal.
    """
    carregador = unittest.defaultTestLoader
    suite = carregador.discover(
        start_dir=start_dir, pattern=padrao, top_level_dir=top_level
    )
    testes = ordenar(list(achatar(suite)), ordem)

    registo = Registo()
    unittest.TestSuite(testes).run(registo)

    return Resultado(
        estado=registo.estado,
        corridos=registo.testsRun,
        sucesso=registo.wasSuccessful(),
        relato=_relatar(registo),
    )
