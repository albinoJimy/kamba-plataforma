"""Sonda de vivacidade, equivalente ao `healthz()` de `packages/core-ts`.

A forma da resposta e fixada por `packages/contracts/schemas/healthz.response.v1.json`,
que e a fonte unica das duas implementacoes.
"""

from __future__ import annotations

import os
import re

#: Variavel de ambiente onde o CI injecta o SHA do commit.
COMMIT_ENV = "KAMBA_COMMIT_SHA"

_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def commit_sha(env: dict[str, str] | None = None) -> str:
    """Le o SHA do commit do ambiente, ou `"unknown"`.

    Nao falha quando a variavel nao existe: a sonda de vivacidade diz se o
    processo esta vivo, e um processo vivo sem metadados de construcao continua
    vivo. Exigir um SHA real nas imagens publicadas e um gate de CI (KAM-002).
    """
    source = os.environ if env is None else env
    raw = (source.get(COMMIT_ENV) or "").strip().lower()
    return raw if _SHA.match(raw) else "unknown"


def healthz(service: str, version: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """Constroi a resposta de `/healthz` de um servico."""
    return {
        "status": "ok",
        "service": service,
        "version": version,
        "commit": commit_sha(env),
    }
