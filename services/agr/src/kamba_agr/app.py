"""Aplicacao ASGI do AGR; esqueleto.

Starlette em vez de FastAPI: no KAM-001 nao ha esquemas de pedido para validar
nem OpenAPI para gerar, e FastAPI traria Pydantic para servir uma rota que
devolve quatro campos. Quando o AGR tiver uma API interna com corpo (`/internal/turn`,
EPIC-03), reavalia-se — e fica registado em `docs/adr/ADR-L001-toolchain.md`.
"""

from __future__ import annotations

from kamba_core import healthz
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .meta import SERVICE, VERSION


async def healthz_endpoint(_request: Request) -> JSONResponse:
    return JSONResponse(healthz(SERVICE, VERSION))


def create_app() -> Starlette:
    return Starlette(routes=[Route("/healthz", healthz_endpoint, methods=["GET"])])


app = create_app()
