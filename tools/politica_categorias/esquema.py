"""Um validador de JSON Schema **para as palavras-chave que a politica usa**.

Nao e um validador de JSON Schema. O repositorio nao tem nenhum (o
`packages/core-ts/src/eventos/contratos.ts` explica porque), e a politica de
categorias usa onze palavras-chave. Este modulo implementa essas onze e
**recusa o esquema** que use outra: um validador que ignorasse em silencio uma
palavra-chave que nao conhece validava menos do que o esquema diz, e o ficheiro
`politica.esquema.json` passava a mentir sobre o que o gate garante.
"""

from __future__ import annotations

import re
from typing import Any

#: As palavras-chave implementadas. `$schema`, `$id`, `title` e `description`
#: sao anotacoes: nao validam nada e por isso podem estar presentes.
IMPLEMENTADAS = frozenset(
    {
        "type",
        "required",
        "properties",
        "additionalProperties",
        "enum",
        "pattern",
        "items",
        "minItems",
        "minLength",
        "uniqueItems",
    }
)
ANOTACOES = frozenset({"$schema", "$id", "title", "description"})

_TIPOS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "null": lambda v: v is None,
    # `bool` e subclasse de `int` em Python, e o JSON Schema distingue-os.
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


class EsquemaInvalido(ValueError):
    """O proprio esquema usa o que este validador nao implementa."""


def _verificar_esquema(esquema: dict, onde: str) -> None:
    desconhecidas = set(esquema) - IMPLEMENTADAS - ANOTACOES
    if desconhecidas:
        raise EsquemaInvalido(
            f"{onde}: palavra-chave nao implementada {sorted(desconhecidas)}"
        )
    if esquema.get("additionalProperties", False) not in (False,):
        raise EsquemaInvalido(f"{onde}: so `additionalProperties: false` e implementado")
    for nome, sub in esquema.get("properties", {}).items():
        _verificar_esquema(sub, f"{onde}.{nome}")
    if "items" in esquema:
        _verificar_esquema(esquema["items"], f"{onde}[]")


def erros(valor: Any, esquema: dict, onde: str = "$") -> list[str]:
    """Os erros de `valor` contra `esquema`, por ordem. Lista vazia = valido."""
    _verificar_esquema(esquema, onde)
    return _erros(valor, esquema, onde)


def _erros(valor: Any, esquema: dict, onde: str) -> list[str]:
    saida: list[str] = []
    tipos = esquema.get("type")
    if tipos is not None:
        lista = [tipos] if isinstance(tipos, str) else list(tipos)
        if not any(_TIPOS[t](valor) for t in lista):
            return [f"{onde}: tipo {type(valor).__name__}, esperado {'|'.join(lista)}"]
    if "enum" in esquema and valor not in esquema["enum"]:
        saida.append(f"{onde}: {valor!r} fora de {esquema['enum']}")
    if isinstance(valor, str):
        if "minLength" in esquema and len(valor) < esquema["minLength"]:
            saida.append(f"{onde}: menos de {esquema['minLength']} caracteres")
        if "pattern" in esquema and re.search(esquema["pattern"], valor) is None:
            saida.append(f"{onde}: {valor!r} nao casa {esquema['pattern']}")
    if isinstance(valor, list):
        if "minItems" in esquema and len(valor) < esquema["minItems"]:
            saida.append(f"{onde}: menos de {esquema['minItems']} itens")
        if esquema.get("uniqueItems"):
            vistos: list[Any] = []
            for item in valor:
                if item in vistos:
                    saida.append(f"{onde}: item repetido {item!r}")
                vistos.append(item)
        if "items" in esquema:
            for indice, item in enumerate(valor):
                saida.extend(_erros(item, esquema["items"], f"{onde}[{indice}]"))
    if isinstance(valor, dict):
        for chave in esquema.get("required", []):
            if chave not in valor:
                saida.append(f"{onde}: falta a chave {chave!r}")
        propriedades = esquema.get("properties", {})
        if esquema.get("additionalProperties") is False:
            for chave in valor:
                if chave not in propriedades:
                    saida.append(f"{onde}: chave nao prevista {chave!r}")
        for chave, sub in propriedades.items():
            if chave in valor:
                saida.extend(_erros(valor[chave], sub, f"{onde}.{chave}"))
    return saida
