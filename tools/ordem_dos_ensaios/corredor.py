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

## E quando a rede morde, o `TestResult` ainda sabe de quem (KAM-182)

A rede ficou a dizer «perdi a informacao» quando a informacao **estava no
processo**: medido a 2026-11-05 no *gate* 4 do PR #137, `corridos=1402,
classificados=1402, sucesso=False` — a contagem fecha, nenhum vermelho e
nomeado — e o `relato` impresso logo a seguir tinha o nome e o *traceback*. O
que faltava nao era medir mais: era **ler o que o `unittest` ja devolveu**.

Por isso o `Resultado` leva tambem o que o proprio `TestResult` acusa, pelos
seus `failures`, `errors` e `unexpectedSuccesses`, separado em duas listas:

    acusados   os `id()` de **casos** (ver `acusacoes`)
    sem_caso   as entradas que nao sao casos, pela etiqueta com que aparecem

A separacao e o ponto. Um erro de `setUpClass`, `tearDownClass`, `setUpModule`
ou `tearDownModule` entra num `unittest.suite._ErrorHolder`, cujo `id()` e uma
frase (`tearDownModule (modulo)`) e nao um identificador de caso: tratar essa
frase como um `id()` de teste era inventar um caso que nao existe — e era o que
este modulo fazia, com a frase a entrar no `estado` como se fosse um teste
vermelho. O `cli` usa a diferenca entre os `acusados` e os vermelhos do
dicionario para **nomear** a hipotese; o `sem_caso` e o que mantem a recusa
necessaria, porque com ele nao ha caso nenhum para nomear e o portao continua a
sair com codigo nao-zero.
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
    #: Os `id()` de **casos** que o proprio `TestResult` acusa (KAM-182). Nao
    #: sai do `estado`: sai do `failures`, do `errors` e dos
    #: `unexpectedSuccesses`, que e o lado que o dicionario nao perde.
    acusados: tuple[str, ...] = ()
    #: As entradas acusadas que **nao** sao casos — o `_ErrorHolder` dos erros
    #: de `setUpClass`/`tearDownModule` e companhia —, pela etiqueta com que o
    #: `unittest` as apresenta. Nao sao `id()` de teste e nao se usam como tal.
    sem_caso: tuple[str, ...] = ()

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
        # E o unico sinal que recebe algo que nao e um caso: os erros de
        # `setUpClass`, `tearDownClass`, `setUpModule` e `tearDownModule` vem
        # num `unittest.suite._ErrorHolder`, cujo `id()` e uma frase. Ate ao
        # KAM-182 essa frase entrava aqui como se fosse um teste vermelho —
        # inventava um caso que nao existe, e o `cli` comparava-a entre as duas
        # ordens como se fosse inventario. O erro **nao** se perde: esta no
        # `errors` do `TestResult`, logo no `wasSuccessful()`, no `relato` e no
        # `sem_caso` das `acusacoes`, e e a rede do `cli` que o apanha.
        if isinstance(test, unittest.TestCase):
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


def _etiqueta(entrada: object) -> tuple[str | None, str]:
    """`(id() de caso, etiqueta)` de uma entrada do `failures`/`errors`.

    O `id()` de caso e `None` quando a entrada **nao** e um caso, que e o do
    `unittest.suite._ErrorHolder`: ele nao deriva de `TestCase` e o seu `id()`
    devolve uma frase. A discriminacao e por tipo e nao pela forma da cadeia de
    proposito — distinguir `tearDownModule (modulo)` de um `id()` de teste por
    conter um espaco funcionava ate alguem ter um `subTest` com espacos.

    Um `unittest.case._SubTest` **e** um caso, e dobra-se para o `id()` do
    caso-pai pelo seu `test_case`: o `id()` do sub-caso (`...test_x [valor=2]`)
    nunca passa pelo `startTest`, pelo que sem a dobra um `subTest` vermelho
    aparecia como um `id()` que o `Registo` nunca viu — a hipotese 1 do
    KAM-182 — quando o `addSubTest` esta derrubado e classificou o pai.
    """
    pai = getattr(entrada, 'test_case', None)
    if isinstance(pai, unittest.TestCase):
        entrada = pai
    identificador = getattr(entrada, 'id', None)
    etiqueta = identificador() if callable(identificador) else str(entrada)
    if isinstance(entrada, unittest.TestCase):
        return etiqueta, etiqueta
    return None, etiqueta


def acusacoes(registo: unittest.TestResult) -> tuple[tuple[str, ...], ...]:
    """`(acusados, sem_caso)`: o que o `TestResult` acusa, pelo seu lado.

    E a metade que faltava a rede (KAM-182). O `estado` do `Registo` e com
    perdas; o `failures`/`errors`/`unexpectedSuccesses` do `TestResult` nao e, e
    e dele que vem o `wasSuccessful()` que a rede cruza. Quando os dois
    discordam, e aqui que esta o nome.

    Os `unexpectedSuccesses` entram porque o `wasSuccessful()` os conta: um
    `expectedFailure` que passa deixa o portao vermelho, e tem de poder ser
    nomeado pela mesma via.
    """
    casos: set[str] = set()
    sem_caso: set[str] = set()
    entradas: list[object] = [teste for teste, _ in registo.failures]
    entradas += [teste for teste, _ in registo.errors]
    entradas += list(getattr(registo, 'unexpectedSuccesses', ()))
    for entrada in entradas:
        identificador, etiqueta = _etiqueta(entrada)
        (casos if identificador is not None else sem_caso).add(etiqueta)
    return tuple(sorted(casos)), tuple(sorted(sem_caso))


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
    acusados, sem_caso = acusacoes(registo)

    return Resultado(
        estado=registo.estado,
        corridos=registo.testsRun,
        sucesso=registo.wasSuccessful(),
        relato=_relatar(registo),
        acusados=acusados,
        sem_caso=sem_caso,
    )
