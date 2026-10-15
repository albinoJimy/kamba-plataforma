"""Comparacao de versoes e leitura de especificadores, com postura fail-closed.

A unica pergunta que interessa aqui e: *consigo provar que a versao resolvida
desta dependencia esta igual ou acima do limiar?* Se nao conseguir, bloqueia.
O principio 7 do §6 do Engineering Standards ("fail-closed por omissao") aplica-se
com mais razao ainda a um pacote que ja foi vector de ataque (`litellm`).
"""

from __future__ import annotations

import re

_NUMERIC = re.compile(r"^[0-9]+$")
# Pin exacto, nas formas que os manifestos usam: "1.2.3", "==1.2.3", "=1.2.3".
_EXACT_PIN = re.compile(r"^\s*(?:==|=)?\s*v?([0-9]+(?:\.[0-9]+)*)\s*$")


def parse(version: str) -> tuple[int, ...] | None:
    """Converte "1.83.0" em (1, 83, 0). Devolve None se nao for puramente numerica."""
    parts = version.strip().split(".")
    if not parts or not all(_NUMERIC.match(p) for p in parts):
        return None
    return tuple(int(p) for p in parts)


def compare(left: str, right: str) -> int | None:
    """-1, 0 ou 1. None se alguma das duas nao for comparavel."""
    a, b = parse(left), parse(right)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def exact_pin(spec: str) -> str | None:
    """Devolve a versao se `spec` for um pin exacto; caso contrario None.

    `^1.83.0`, `>=1.83.0`, `~1.83`, `*` e `latest` **nao** sao pins exactos: todos
    permitem que a resolucao traga outra coisa, e para um pacote com historico de
    comprometimento isso nao serve como prova.
    """
    match = _EXACT_PIN.match(spec or "")
    return match.group(1) if match else None


def satisfies_floor(spec: str, floor: str) -> tuple[bool, str]:
    """A dependencia prova estar em `floor` ou acima?

    Devolve (permitido, motivo). Permitido so quando `spec` e um pin exacto cuja
    versao e >= `floor`. Qualquer outra coisa e recusada com o motivo por escrito.
    """
    pinned = exact_pin(spec)
    if pinned is None:
        return False, (
            f"a versao nao esta fixada exactamente ({spec!r}); "
            f"exige-se um pin exacto >= {floor}"
        )
    result = compare(pinned, floor)
    if result is None:
        return False, f"versao {pinned!r} nao e comparavel com o limiar {floor}"
    if result < 0:
        return False, f"versao {pinned} esta abaixo do limiar {floor}"
    return True, f"versao {pinned} >= {floor}"
