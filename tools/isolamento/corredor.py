"""O corredor: chama os `fn` dos casos registados e junta os achados.

Separado do registo porque sao duas responsabilidades diferentes, e porque
quem o chama sao dois sitios: o `python -m isolation` corre os casos que nao
precisam de nada, e `db/tests_isolamento/test_casos_cruzados.py` corre os que
precisam da base e do `node`.

## Num gate, saltar e falhar

E a regra que `db/correr_suite.py` ja aplica a suite da base, e aplica-se aqui
pela mesma razao: «uma variavel de ambiente mal posta fazia o gate 8 passar
verde sem ter aplicado uma unica migracao». Um caso cujo `precisa` nao esta
satisfeito **nao e saltado**: devolve um achado que diz o que faltava. Quem
corre o corredor a mao, fora de um gate, passa `permitir_salto=True` e recebe a
lista do que ficou por correr.

## O oraculo confirma-se antes do primeiro caso

A sonda positiva (`Oraculo.confirmar_que_morde`) corre **uma vez**, antes de
tudo, e falha o corredor inteiro. Deixa-la a cada caso era repeti-la dezenas de
vezes; nao a correr era deixar todas as afirmacoes de «zero canarios» a valer
tanto quanto um `varrer` que devolvesse `[]`.

## As origens declaradas confrontam-se com as varridas

O criterio 9 pede que «o oraculo varra **tambem** logs e traces OTel de cada
caso». Um caso declara em `origens` o que varre; o corredor nao consegue
inspeccionar o que o `fn` fez por dentro, pelo que verifica o que pode: que um
caso que declara `logs` tem onde os buscar (`ctx.logs`) e que nenhum caso
declara uma origem fora das cinco. O resto e revisao de codigo, e esta dito em
vez de ficar por dizer.
"""

from __future__ import annotations

import dataclasses
import time

from .casos import Caso, carregar_casos
from .contexto import Contexto
from .oraculo import ORIGENS


@dataclasses.dataclass(frozen=True)
class Resultado:
    achados: list[str]
    corridos: tuple[str, ...]
    saltados: tuple[str, ...]
    #: Segundos de relogio por caso, para o relatorio de desempenho do bloco.
    duracao: dict[str, float]

    @property
    def conforme(self) -> bool:
        return not self.achados and not self.saltados


def correr(
    ctx: Contexto,
    precisa: set[str] | None = None,
    *,
    permitir_salto: bool = False,
) -> Resultado:
    """Corre os casos cujo `precisa` esta em `precisa` (ou todos, se `None`)."""
    casos = carregar_casos()
    achados: list[str] = []
    corridos: list[str] = []
    saltados: list[str] = []
    duracao: dict[str, float] = {}

    if ctx.oraculo is not None:
        ctx.oraculo.confirmar_que_morde()

    for identificador in sorted(casos):
        caso = casos[identificador]
        if precisa is not None and caso.precisa not in precisa:
            continue
        achados.extend(_origens_invalidas(caso))
        if not ctx.tem(caso.precisa):
            if permitir_salto:
                saltados.append(identificador)
                continue
            achados.append(
                f"{identificador}: precisa de {caso.precisa!r} e o contexto nao "
                "o traz. Num gate, saltar e falhar: um caso de isolamento que "
                "nao corre e um caso que nao existe."
            )
            saltados.append(identificador)
            continue

        ctx.logs.clear()
        ctx.spans.clear()
        inicio = time.monotonic()
        try:
            resultado = caso.fn(ctx)
        except Exception as erro:  # noqa: BLE001 — um caso que levanta e um achado
            resultado = [
                f"{identificador}: o caso levantou {type(erro).__name__}: {erro}"
            ]
        duracao[identificador] = time.monotonic() - inicio
        corridos.append(identificador)
        if not isinstance(resultado, list):
            achados.append(
                f"{identificador}: o `fn` devolveu {type(resultado).__name__} e "
                "nao uma lista de achados. Um `fn` que devolve `None` faz o "
                "caso passar sempre."
            )
            continue
        achados.extend(str(achado) for achado in resultado)

    return Resultado(
        achados=achados,
        corridos=tuple(corridos),
        saltados=tuple(saltados),
        duracao=duracao,
    )


def _origens_invalidas(caso: Caso) -> list[str]:
    fora = sorted(set(caso.origens) - set(ORIGENS))
    if not fora:
        return []
    return [
        f"{caso.id}: declara as origens {fora}, que nao sao do criterio 9 "
        f"({ORIGENS}). Uma origem inventada nao entra na contagem do caso."
    ]


def relatorio(resultado: Resultado) -> str:
    """O registo que vai para a evidencia do bloco."""
    linhas = [
        f"casos corridos: {len(resultado.corridos)}",
        f"casos saltados: {len(resultado.saltados)}",
        f"achados: {len(resultado.achados)}",
    ]
    for identificador in resultado.corridos:
        linhas.append(f"  {identificador}: {resultado.duracao[identificador]:.2f}s")
    for identificador in resultado.saltados:
        linhas.append(f"  {identificador}: SALTADO")
    return "\n".join(linhas)
