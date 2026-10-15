"""Anfitriao e porta de escuta, equivalentes ao `port()` de `packages/core-ts`.

Existe para que a regra seja a mesma nas duas linguagens: o contentor define
`HOST=0.0.0.0`, e correr o servico a mao na maquina de alguem continua a escutar
so em `127.0.0.1` (DoD do KAM-001). Sem isto, o AGR tinha `0.0.0.0` escrito no
`CMD` e as variaveis de ambiente eram decoracao.
"""

from __future__ import annotations

import os

#: Escuta local por omissao. Abrir a interface e uma decisao do contentor.
DEFAULT_HOST = "127.0.0.1"


def host(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return (source.get("HOST") or "").strip() or DEFAULT_HOST


def port(fallback: int, env: dict[str, str] | None = None) -> int:
    """Porta de escuta.

    Falha em voz alta com um valor invalido: ao contrario do SHA do commit, uma
    porta errada nao e um metadado — e arrancar a escutar no sitio errado, e isso
    e pior do que nao arrancar (`specs/01` §6, principio 7).
    """
    source = os.environ if env is None else env
    raw = (source.get("PORT") or "").strip()
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"PORT invalida: {raw!r}") from None
    if not 1 <= value <= 65535:
        raise ValueError(f"PORT invalida: {raw!r}")
    return value
