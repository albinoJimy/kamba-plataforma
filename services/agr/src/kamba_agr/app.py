"""Aplicacao ASGI do AGR.

Starlette em vez de FastAPI: a razao esta em `docs/adr/ADR-L001-toolchain.md`, e
o KAM-025 **reavaliou-a**, como o KAM-001 pediu por escrito («quando o AGR tiver
uma API interna com corpo (`/internal/turn`, EPIC-03), reavalia-se»). Decisao:
mantem-se. O corpo e um contrato de nove campos de forma fechada
(`contexto.ler_invocacao`), e nao ha OpenAPI a gerar para uma API que so dois
processos nossos chamam; trazer o FastAPI e o Pydantic para producao por isso
era pagar uma arvore de dependencias por nove `isinstance`. A nota fica aqui,
e nao num ADR novo, porque confirmar uma decisao nao e tomar outra.

`create_app()` sem argumentos da a `/healthz` **e a `/metrics`** (esta desde o
KAM-080). As rotas **internas** montam-se quando as portas existem, e e o
`__main__.py` que as liga: uma aplicacao construida sem elas **nao** tem
`/internal/*`, em vez de as ter a responder 500. Um esqueleto que expoe uma rota
que nao funciona e pior do que um que a nao expoe.

A `/metrics` nao segue essa regra, e a razao esta no `metricas_endpoint`: o
registo de metricas vive em memoria e nao depende de porta nenhuma, pelo que
monta-la com as rotas internas fazia-a responder 404 exactamente no arranque —
que e quando um painel precisa de distinguir «zero turnos» de «nao arrancou».
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from kamba_core import healthz
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from kamba_core.idx.metricas import METRICAS as METRICAS_DO_IDX

from .meta import SERVICE, VERSION
from .metricas import METRICAS

#: O `Content-Type` do formato de exposicao do Prometheus.
#:
#: E o mesmo do `services/com/src/metricas.ts` e do
#: `packages/core-ts/src/ten/metricas.ts` — «quem serve as metricas de um
#: processo serve-as todas do mesmo modo». **O corpo e texto e nao JSON**: um
#: `application/json` fazia o *scraper* recusar a resposta.
TIPO_DE_CONTEUDO_DAS_METRICAS = "text/plain; version=0.0.4; charset=utf-8"


async def healthz_endpoint(_request: Request) -> JSONResponse:
    return JSONResponse(healthz(SERVICE, VERSION))


async def metricas_endpoint(_request: Request) -> PlainTextResponse:
    """As 44 metricas do AGR, no formato de exposicao do Prometheus (KAM-080).

    **Esta rota nasceu com o KAM-080, e nao antes.** O `metricas.py` declarava as
    44 desde o KAM-025 e dizia, no proprio modulo, que «no AGR ainda nao expoe»;
    o `docs/runbooks/degradacao-do-agr.md` nomeava a falta por escrito. Era a
    maior lacuna de observabilidade medida nesta arvore: das 109 metricas do
    repositorio, 44 viviam aqui sem nenhuma rota que as servisse.

    Fica na **mesma** aplicacao que a `/healthz`, e nao numa segunda porta como
    no GWY. A diferenca entre os dois nao e de gosto: a aplicacao publica do GWY
    recebe *webhooks* da Internet, e por isso os contadores dele vivem numa app
    interna separada (3010). O AGR **nao tem superficie publica** — so
    `/internal/*`, na rede `app`, sem `ports:` no compose —, pelo que uma
    segunda porta so acrescentava uma porta. E a mesma leitura do COM, que serve
    `/metrics` na porta da sua API interna (KAM-178).
    """
    # **Dois registos na mesma rota** desde o KAM-193: o do AGR e o do IDX
    # (`kamba_core.idx.metricas`), que vive na biblioteca porque a pesquisa e do
    # dominio do indice e o AGR e so quem a chama. Os dois omitem uma serie
    # que ainda nao foi escrita, pelo que um processo fresco continua a servir
    # corpo vazio (`test_um_processo_fresco_serve_corpo_vazio`).
    return PlainTextResponse(
        METRICAS.exposicao() + METRICAS_DO_IDX.exposicao(),
        media_type=TIPO_DE_CONTEUDO_DAS_METRICAS,
    )


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
    # A `/metrics` entra **sempre**, como a `/healthz`, e nao com as
    # `rotas_internas`. A razao e a do docstring do modulo, ao contrario: uma
    # rota que nao funciona sem as portas nao se monta sem elas, e esta
    # funciona sem nenhuma — o registo de metricas vive em memoria no processo
    # e nao depende de base de dados, de tranca nem de LLM. Monta-la so com as
    # portas fazia o `/metrics` do AGR responder 404 exactamente no arranque,
    # que e quando um painel precisa de distinguir «zero turnos» de «nao
    # arrancou».
    rotas: list[Route] = [
        Route("/healthz", healthz_endpoint, methods=["GET"]),
        Route("/metrics", metricas_endpoint, methods=["GET"]),
    ]
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
