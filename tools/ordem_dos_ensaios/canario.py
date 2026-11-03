"""O canario deste portao: a prova de que ele morde, e de que nao morde tudo.

## Porque sao duas *fixtures* e nao uma

Um portao sem canario «passa por vazio», que e o defeito que este ticket existe
para nao repetir. Mas um canario com **so** o caso que morde tem o defeito
simetrico, e e mais facil de nao ver: um verificador que declarasse qualquer
suite dependente da ordem — por ter o comparador invertido, por contar um
`skip` como vermelho, por falhar no arranque — fazia esse caso morder e passava
o canario. Ficava um portao que nunca deixa fundir nada, provado por um canario
que nunca mediu se ele distingue.

Daí as duas:

    dependente     tem de estar VERDE na ordem de omissao e VERMELHA na inversa
    independente   tem de estar VERDE nas duas

A primeira prova que morde; a segunda, que distingue.

## A precondicao, e o que ela fecha

Cada caso declara o que tem de acontecer **nas duas** ordens, e nao so na que o
interessa. E a licao do `env_lint/canario.py`, numa forma diferente: la o modo
de falha e a arvore mudar e a mutacao deixar de mudar nada; aqui e a *fixture*
quebrar — um `import` partido, um nome de teste renomeado — e ficar vermelha nas
duas ordens. O caso `dependente` passava a «morder» por a *fixture* nao
arrancar, sem nenhuma ordem ter sido medida.

Por isso o caso que morde declara tambem **qual** teste tem de ficar vermelho.
Um vermelho noutro teste e `prova invalida`, nunca um verde.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .corredor import Resultado

#: Onde vivem as *fixtures*. Ficam debaixo de `tests/` por duas razoes que nao
#: se adivinham: o `--omit="*/tests/*"` do alvo `coverage-python` deixa-as fora
#: da medicao de cobertura, e o `unittest discover` das suites de `tools/` usa
#: o padrao `test*.py`, pelo que nunca apanha um `caso_*.py`. Uma *fixture*
#: deliberadamente dependente da ordem descoberta pela suite de `tools/` fazia
#: o *gate* 4 vermelho por desenho.
FIXTURES = Path(__file__).resolve().parent / 'tests' / 'fixtures'

#: O padrao das *fixtures*, diferente do das suites reais exactamente por isso.
PADRAO = 'caso_*.py'


@dataclass(frozen=True)
class Caso:
    codigo: str
    descricao: str
    #: Subpasta de `FIXTURES`.
    pasta: str
    #: O que tem de acontecer na ordem de omissao do `unittest`.
    normal_verde: bool
    #: O que tem de acontecer na ordem inversa.
    inversa_verde: bool
    #: Quando a inversa tem de ficar vermelha, o `id()` do teste que o portao
    #: tem de nomear. `None` quando o caso nao morde.
    vermelho_esperado: str | None


CASOS = (
    Caso(
        codigo='dependente',
        descricao='estado de processo sujo por uma classe, lido por outra',
        pasta='dependente',
        normal_verde=True,
        inversa_verde=False,
        vermelho_esperado='caso_registo.TestALeitura.test_o_registo_comeca_vazio',
    ),
    Caso(
        codigo='independente',
        descricao='o mesmo estado de processo, reposto por quem o suja',
        pasta='independente',
        normal_verde=True,
        inversa_verde=True,
        vermelho_esperado=None,
    ),
)

#: Assinatura de quem corre uma ordem fora deste processo: `(pasta, ordem)`
#: devolve o resultado. Injectado pelo `cli` para o canario exercitar o
#: **mesmo** caminho que o `check`, e nao uma copia dele.
Corredor = Callable[[Path, str], Resultado]


def verificar(caso: Caso, correr_fora: Corredor) -> list[str]:
    """As queixas deste caso. Lista vazia e conforme."""
    pasta = FIXTURES / caso.pasta
    queixas: list[str] = []
    if not pasta.is_dir():
        return [f'{caso.codigo}: a fixture {pasta} nao existe']

    for ordem, esperado_verde in (
        ('normal', caso.normal_verde),
        ('inversa', caso.inversa_verde),
    ):
        resultado = correr_fora(pasta, ordem)
        if resultado.corridos == 0:
            queixas.append(
                f'{caso.codigo}/{ordem}: precondicao — a fixture nao correu '
                'um unico teste'
            )
            continue
        vermelhos = resultado.vermelhos()
        if esperado_verde and vermelhos:
            rotulo = 'precondicao' if ordem == 'normal' else 'prova'
            queixas.append(
                f'{caso.codigo}/{ordem}: {rotulo} — esperava verde e deu '
                f'vermelho em {vermelhos}'
            )
        elif not esperado_verde and not vermelhos:
            queixas.append(
                f'{caso.codigo}/{ordem}: prova — esperava vermelho e a '
                'fixture passou. O portao deixou de morder.'
            )
        elif not esperado_verde and caso.vermelho_esperado not in vermelhos:
            queixas.append(
                f'{caso.codigo}/{ordem}: prova invalida — ficou vermelho em '
                f'{vermelhos}, e o caso declara {caso.vermelho_esperado!r}'
            )
    return queixas
