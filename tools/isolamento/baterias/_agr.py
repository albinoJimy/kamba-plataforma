"""O ataque as rotas do AGR, conduzido sobre o ASGI em processo.

Separado do `x01_rotas.py` por uma razao que e a razao de ser do pacote: o
`x01_rotas` tem de ser importavel **sem** o AGR (e o que permite medir a
cobertura a seco, sem `starlette` nem `pydantic`), e este modulo importa o AGR.
Por isso o `x01_rotas` importa-o dentro do `fn`, e nao no topo.

## Conduz o ASGI, e nao um cliente HTTP

O `starlette.testclient.TestClient` traria o `httpx`, que o *venv* desta casa
nao tem por causa do AGR — tem-no por causa de mais nada. Uma aplicacao ASGI e
um chamavel de tres argumentos, e conduzi-lo sao trinta linhas: menos uma
dependencia, e nenhuma camada entre o caso e o que a rota devolveu.

## Os duplos nao decidem nada, e e isso que faz a afirmacao forte

O duplo do executor **registra e nao corre**. A pergunta do caso nao e «que
estado devolveu a rota» — e «chegou ao executor um corpo que mistura o tenant
de A com identificadores de B?». Uma rota que o deixasse passar devolvia uma
recusa vinda do executor e passava todas as afirmacoes sobre a resposta, tendo
aceitado a mistura. Por isso o duplo e um registador e o caso le-o.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[3]


def _no_caminho() -> None:
    for relativo in ("services/agr/src", "libs/py-core/src"):
        caminho = str(RAIZ / relativo)
        if caminho not in sys.path:
            sys.path.insert(0, caminho)


#: A credencial interna do ensaio. Nao e um segredo: a rota compara-a com o que
#: o duplo devolve, e os dois vivem neste ficheiro.
CREDENCIAL = "credencial-interna-do-x01"


class _Registador:
    """Um duplo que registra as chamadas e nao faz nada."""

    def __init__(self, devolver: Any = None) -> None:
        self.chamadas: list[tuple[tuple, dict]] = []
        self._devolver = devolver

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.chamadas.append((args, kwargs))
        return self._devolver

    def sincrono(self, *args: Any, **kwargs: Any) -> Any:
        self.chamadas.append((args, kwargs))
        return self._devolver


async def _pedir(
    app: Any,
    metodo: str,
    caminho: str,
    corpo: bytes = b"",
    cabecalhos: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    """`(estado, cabecalhos, corpo)` de um pedido conduzido sobre o ASGI."""
    saida: list[dict] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": metodo,
        "scheme": "http",
        "path": caminho,
        "raw_path": caminho.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (chave.lower().encode(), valor.encode())
            for chave, valor in (cabecalhos or {}).items()
        ],
        "client": ("127.0.0.1", 0),
        "server": ("ensaio", 80),
    }

    async def receber() -> dict:
        return {"type": "http.request", "body": corpo, "more_body": False}

    async def enviar(mensagem: dict) -> None:
        saida.append(mensagem)

    await app(scope, receber, enviar)

    estado = 0
    resposta_cabecalhos: dict[str, str] = {}
    pedacos: list[bytes] = []
    for mensagem in saida:
        if mensagem["type"] == "http.response.start":
            estado = int(mensagem["status"])
            resposta_cabecalhos = {
                chave.decode(): valor.decode()
                for chave, valor in mensagem.get("headers", [])
            }
        elif mensagem["type"] == "http.response.body":
            pedacos.append(mensagem.get("body", b"") or b"")
    return estado, resposta_cabecalhos, b"".join(pedacos).decode("latin-1")


def _montar(ctx) -> tuple[Any, dict[str, _Registador]]:  # noqa: ANN001
    """O AGR com as quatro rotas internas e duplos em todas as portas."""
    _no_caminho()
    from kamba_agr import api_interna  # noqa: PLC0415
    from kamba_agr.app import create_app  # noqa: PLC0415

    duplos = {
        "executar": _Registador(),
        "retomar": _Registador(devolver="retomado"),
        "decidir": _Registador(devolver="aprovado"),
        "eventos": _Registador(),
        "aviso": _Registador(),
        "verificar_bot": _Registador(),
    }

    class _Admissao:
        """Recusa sempre, e registra. A admissao nao e o que este caso mede."""

        def __init__(self) -> None:
            self.chamadas: list[Any] = []

        def admitir(self, *args: Any, **kwargs: Any) -> Any:
            self.chamadas.append((args, kwargs))
            raise RuntimeError("admissao de ensaio: nao admite")

    class _Trancas:
        def tomar(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("trancas de ensaio: nao toma")

    admissao = _Admissao()
    rotas = api_interna.rotas(
        credencial=lambda: CREDENCIAL,
        executar=duplos["executar"],
        admissao=admissao,
        trancas=_Trancas(),
        retomar=duplos["retomar"],
        # O verificador do *agent bot* recusa: o que este caso mede e o
        # isolamento, e uma retoma que passasse a autenticacao media outra coisa.
        verificar_bot=lambda cabecalho, thread: None,
        aviso=duplos["aviso"].sincrono,
        eventos=None,
        decidir=duplos["decidir"],
    )
    return create_app(rotas_internas=rotas), duplos


def _corpos_com_ids_de_b(ctx) -> dict[str, list[dict]]:  # noqa: ANN001
    """Por caminho, os corpos que misturam o tenant de A com coisas de B.

    Tres formas de IDOR, e as tres sao o mesmo ataque por portas diferentes:
    o `tenant_id` de B com o resto de A, o `tenant_id` de A com os
    identificadores de B, e o canario de B posto num campo de dominio aberto.
    """
    a, b = ctx.a.id, ctx.b.id
    contacto_de_b = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kamba-x01:{b}"))
    canario_de_b = next(iter(ctx.oraculo.proibidos.values()))
    thread_de_b = f"{b}:{contacto_de_b}"
    return {
        "/internal/turn": [
            {
                "tenant_id": b,
                "contact_id": contacto_de_b,
                "conversation_id": str(uuid.uuid4()),
                "channel_id": str(uuid.uuid4()),
                "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
                "type": "text",
                "modo": "bot",
                "thread_id": thread_de_b,
                "vertical": "vendedor",
            },
            {
                "tenant_id": a,
                "contact_id": contacto_de_b,
                "conversation_id": str(uuid.uuid4()),
                "channel_id": str(uuid.uuid4()),
                "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
                "type": "text",
                "modo": "bot",
                "thread_id": thread_de_b,
                "vertical": "vendedor",
            },
            {
                "tenant_id": a,
                "contact_id": contacto_de_b,
                "conversation_id": str(uuid.uuid4()),
                "channel_id": str(uuid.uuid4()),
                "wamid": "wamid." + canario_de_b,
                "type": "text",
                "modo": "bot",
                "thread_id": thread_de_b,
                "vertical": "vendedor",
            },
        ],
        "/internal/resume": [
            {"thread_id": thread_de_b, "handoff_id": str(uuid.uuid4()), "outcome": "resolved"},
            {"thread_id": thread_de_b, "handoff_id": canario_de_b, "outcome": "resolved"},
        ],
        "/internal/event": [
            {"event_id": str(uuid.uuid4()), "tenant_id": b, "tipo": "payment.confirmed"},
            {"event_id": canario_de_b, "tenant_id": b, "tipo": "payment.confirmed"},
        ],
        "/internal/draft-decision": [
            {"thread_id": thread_de_b, "draft_id": uuid.uuid4().hex, "decisao": "aprovado"},
            {"thread_id": thread_de_b, "draft_id": canario_de_b, "decisao": "aprovado"},
        ],
    }


#: Caminho -> o identificador do item enumerado. Uma so fonte para os dois.
ITEM_DE = {
    "/internal/turn": "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/turn",
    "/internal/resume": "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/resume",
    "/internal/event": "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/event",
    "/internal/draft-decision": (
        "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/draft-decision"
    ),
}


def atacar_rotas_internas(ctx) -> list[str]:  # noqa: ANN001
    """O X-01 das quatro rotas internas do AGR."""
    from .x01_rotas import _uniformidade  # noqa: PLC0415

    app, duplos = _montar(ctx)
    achados: list[str] = []

    for caminho, corpos in _corpos_com_ids_de_b(ctx).items():
        item = ITEM_DE[caminho]
        estados: list[int] = []
        for corpo in corpos:
            estado, cabecalhos, texto = asyncio.run(
                _pedir(
                    app,
                    "POST",
                    caminho,
                    json.dumps(corpo).encode(),
                    {"content-type": "application/json", "x-kamba-interno": CREDENCIAL},
                )
            )
            estados.append(estado)
            achados.extend(
                f"{item}: {fuga}"
                for fuga in ctx.oraculo.varrer_tudo(
                    {"corpo": texto, "cabecalhos": cabecalhos, "logs": ctx.logs}
                )
            )
        achados.extend(_uniformidade(item, estados))

    # A afirmacao que a resposta nao da: o executor nao recebeu nada.
    for nome in ("executar", "retomar", "decidir"):
        chamadas = duplos[nome].chamadas
        if chamadas:
            achados.append(
                f"X-01/agr: o duplo de `{nome}` foi chamado {len(chamadas)} "
                "vez(es) com um corpo que mistura tenants. A rota devolveu uma "
                "recusa, mas aceitou a mistura antes de a devolver — e a "
                "proxima versao do executor pode nao a recusar."
            )

    # A metade positiva: com o corpo bem formado de A, a rota **chega** ao
    # executor. Sem isto, as afirmacoes acima passavam com uma rota que recusa
    # tudo — ou que nem existe.
    corpo_de_a = {
        "tenant_id": ctx.a.id,
        "contact_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "channel_id": str(uuid.uuid4()),
        "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
        "type": "text",
        "modo": "bot",
        "thread_id": "",
        "vertical": "vendedor",
    }
    from kamba_agr.contexto import thread_id_de  # noqa: PLC0415

    corpo_de_a["thread_id"] = thread_id_de(ctx.a.id, corpo_de_a["contact_id"])
    estado, _, _ = asyncio.run(
        _pedir(
            app,
            "POST",
            "/internal/turn",
            json.dumps(corpo_de_a).encode(),
            {"content-type": "application/json", "x-kamba-interno": CREDENCIAL},
        )
    )
    if estado == 404:
        achados.append(
            "X-01/agr: a sonda positiva falhou — um corpo coerente de A tambem "
            "deu 404. A rota nao esta montada, e as recusas acima nao provam "
            "isolamento nenhum."
        )
    return achados


def atacar_sonda(ctx) -> list[str]:  # noqa: ANN001
    """O X-01 da `/healthz` do AGR: responde, e nao leva nada de B."""
    app, _ = _montar(ctx)
    estado, cabecalhos, texto = asyncio.run(_pedir(app, "GET", "/healthz"))
    achados: list[str] = []
    if estado != 200:
        achados.append(
            f"rota:agr:…/healthz: a sonda respondeu {estado} e nao 200; o caso "
            "nao mediu o que queria medir."
        )
    achados.extend(
        f"rota:agr:…/healthz: {fuga}"
        for fuga in ctx.oraculo.varrer_tudo({"corpo": texto, "cabecalhos": cabecalhos})
    )
    return achados
