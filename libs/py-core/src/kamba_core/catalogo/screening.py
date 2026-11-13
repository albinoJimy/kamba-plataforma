"""O screening de categoria do produto, pela porta do KAM-088 (KAM-049, criterio 7).

O motor do screening e o do KAM-088, em TypeScript
(`packages/core-ts/src/screening/`): a politica `policy/categorias/politica.yaml`
compilada, as regras, o classificador barato e o `screen` que grava a
`platform.screening_decision`. **Nao se reescreve aqui.** Um segundo motor em
Python era uma segunda leitora da mesma politica, e duas leitoras divergem sem
que nenhum portao o veja (a licao do KAM-069). Esta porta e o contrato do
`screen` com `sujeitoTipo = 'produto'`, com os nomes do lado TypeScript, e o
ensaio compara o dominio das decisoes com o `tipos.ts`.

## Falha fechada, e a forma dela

So `permitida` deixa a ingestao seguir. `condicional` e `bloqueada` levam a
`bloqueada_categoria`, com a `categoria_restrita` preenchida — e e a mesma
regra do `assertPublishable` («`condicional` nao publica sem humano»). Uma
porta que levanta, ou que devolve uma decisao fora do dominio, tambem: a
`categoria_restrita` fica `screening_indisponivel`, e um humano do T&S (o
recurso do `docs/tecnica/10` §8.2) e quem a levanta.

## A `categoria_restrita`

O dominio e deste ticket (dicionario §3.40, KAM-043: «o dominio dos valores e
do KAM-049»). E o `id` da entrada da politica que decidiu — `medicamentos_saude`,
`armas`, `jogos`, `tabaco`, `alcool`, … — ou uma das regras sinteticas do motor
(`classificador_indisponivel`, `nao_listada`, …), ou `screening_indisponivel`
quando a porta nem respondeu. A forma e a do `CHECK` da revisao `catalogo_ai`; a lista nao se
fecha na base porque a politica e versionada e cresce sem revisao de base.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

#: As tres decisoes, pela ordem de restricao. Iguais a `DECISOES` do `tipos.ts`.
DECISOES: Final = ("permitida", "condicional", "bloqueada")
PERMITIDA: Final = "permitida"

#: Quando a porta nao respondeu, ou respondeu fora do contrato.
SCREENING_INDISPONIVEL: Final = "screening_indisponivel"

#: A forma do `CHECK` de `catalog_ingestions.categoria_restrita` (revisao `catalogo_ai`).
FORMA_DA_CATEGORIA: Final = re.compile(r"^[a-z0-9_]{1,60}$")


@dataclass(frozen=True)
class ResultadoDoScreen:
    """O `ResultadoDoScreen` do `tipos.ts`, campo a campo."""

    decisao: str
    regras: tuple[str, ...]
    versao_politica: str
    confianca: float


@runtime_checkable
class PortaDeScreening(Protocol):
    """O `screen` do KAM-088 para um produto (`sujeitoTipo = 'produto'`)."""

    def screen(
        self,
        tenant_id: str,
        sujeito_ref: str,
        categoria_declarada: str,
        textos: Sequence[str],
    ) -> ResultadoDoScreen: ...


class ScreeningPorLigar:
    """A porta enquanto o motor do KAM-088 nao tem ponte para Python.

    **Levanta sempre**, e a ingestao trata isso como `screening_indisponivel`:
    nada passa por ela. E a omissao honesta — uma porta que devolvesse
    `permitida` era um *screening* que nao corre a dizer que correu.
    """

    nome = "screening-por-ligar"

    def screen(
        self,
        tenant_id: str,
        sujeito_ref: str,
        categoria_declarada: str,
        textos: Sequence[str],
    ) -> ResultadoDoScreen:
        raise RuntimeError(
            "o screening do KAM-088 corre em TypeScript e nao tem ponte para o "
            "Catalogo AI: falha fechada (credor no bloco do KAM-049)"
        )


def categoria_restrita(resultado: ResultadoDoScreen | None) -> str | None:
    """`None` se publica; senao o valor de `catalog_ingestions.categoria_restrita`."""
    if resultado is None or resultado.decisao not in DECISOES:
        return SCREENING_INDISPONIVEL
    if resultado.decisao == PERMITIDA:
        return None
    for regra in resultado.regras:
        if FORMA_DA_CATEGORIA.fullmatch(regra):
            return regra
    # Uma decisao restritiva sem regra legivel continua restritiva.
    return resultado.decisao
