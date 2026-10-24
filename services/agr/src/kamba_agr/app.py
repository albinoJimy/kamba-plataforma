"""Aplicacao ASGI do AGR.

Starlette em vez de FastAPI: a razao esta em `docs/adr/ADR-L001-toolchain.md`, e
o KAM-025 **reavaliou-a**, como o KAM-001 pediu por escrito («quando o AGR tiver
uma API interna com corpo (`/internal/turn`, EPIC-03), reavalia-se»). Decisao:
mantem-se. O corpo e um contrato de nove campos de forma fechada
(`contexto.ler_invocacao`), e nao ha OpenAPI a gerar para uma API que so dois
processos nossos chamam; trazer o FastAPI e o Pydantic para producao por isso
era pagar uma arvore de dependencias por nove `isinstance`. A nota fica aqui,
e nao num ADR novo, porque confirmar uma decisao nao e tomar outra.

`create_app()` sem argumentos continua a dar a aplicacao do KAM-001 — so a
`/healthz`. As rotas internas montam-se quando as portas existem, e e o
`__main__.py` que as liga: uma aplicacao construida sem elas **nao** tem
`/internal/*`, em vez de as ter a responder 500. Um esqueleto que expoe uma rota
que nao funciona e pior do que um que a nao expoe.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from kamba_core import healthz
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .meta import SERVICE, VERSION


async def healthz_endpoint(_request: Request) -> JSONResponse:
    return JSONResponse(healthz(SERVICE, VERSION))


def create_app(
    rotas_internas: Sequence[Route] | None = None,
    ao_encerrar: Callable[[], Awaitable[None]] | None = None,
) -> Starlette:
    """A aplicacao do AGR. Sem `rotas_internas`, so a sonda.

    `ao_encerrar` corre no encerramento do processo — e e onde as ligacoes da
    tranca se fecham. **Pelo `lifespan` e nao por `add_event_handler`**: o
    Starlette 1.7 ja nao tem o segundo, e a primeira tentativa rebentou com
    `AttributeError` na propria bateria (que e onde se quer que rebente).
    Fechar a tomada larga as trancas que ela tivesse, e sem isso as trancas de
    um processo que para ficam ate o PostgreSQL notar a tomada fechada.
    """
    rotas: list[Route] = [Route("/healthz", healthz_endpoint, methods=["GET"])]
    rotas.extend(rotas_internas or ())

    if ao_encerrar is None:
        return Starlette(routes=rotas)

    @contextlib.asynccontextmanager
    async def ciclo(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await ao_encerrar()

    return Starlette(routes=rotas, lifespan=ciclo)


app = create_app()
