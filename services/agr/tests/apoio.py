"""Apoio das baterias do AGR: conduzir ASGI, e fabricar invocacoes validas.

Conduz a aplicacao ASGI directamente, em vez de usar o `TestClient` do
Starlette, pela razao que o `test_healthz.py` do KAM-001 escreveu: o
`TestClient` exige `httpx`, e acrescentar `httpx` ao lock do AGR para testar
rotas que devolvem quatro campos seria pagar uma arvore de dependencias em
producao por conveniencia de teste. O protocolo ASGI e estavel e a chamada
directa exercita o encaminhamento real do Starlette.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from kamba_agr.contexto import thread_id_de

#: A credencial das baterias. **Nao e um segredo**: e um valor de teste, com
#: espacos de proposito — o *gate* 9 recusa cadeias com forma de segredo, e
#: nenhum segredo tem espacos (`docs/ci.md` §3, *gate* 9).
CREDENCIAL = "credencial de teste do agr"


async def pedir(
    app: Any,
    caminho: str,
    metodo: str = "GET",
    corpo: bytes | None = None,
    cabecalhos: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Um pedido HTTP a uma aplicacao ASGI, sem servidor nem cliente HTTP."""
    cru = corpo or b""
    cabecalhos_asgi = [(b"host", b"testserver")]
    if corpo is not None:
        cabecalhos_asgi.append((b"content-type", b"application/json"))
        cabecalhos_asgi.append((b"content-length", str(len(cru)).encode()))
    for nome, valor in (cabecalhos or {}).items():
        cabecalhos_asgi.append((nome.lower().encode(), valor.encode()))

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
        "headers": cabecalhos_asgi,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    recebidas: list[dict] = []
    enviado = {"feito": False}

    async def receive() -> dict:
        if enviado["feito"]:
            return {"type": "http.disconnect"}
        enviado["feito"] = True
        return {"type": "http.request", "body": cru, "more_body": False}

    async def send(mensagem: dict) -> None:
        recebidas.append(mensagem)

    await app(scope, receive, send)

    inicio = next(m for m in recebidas if m["type"] == "http.response.start")
    corpo_resposta = b"".join(
        m.get("body", b"") for m in recebidas if m["type"] == "http.response.body"
    )
    cabecalhos_resposta = {
        k.decode().lower(): v.decode() for k, v in inicio.get("headers", [])
    }
    return inicio["status"], cabecalhos_resposta, corpo_resposta


def invocacao_crua(**sobrepor: Any) -> dict[str, Any]:
    """Um `agent_invocation` valido, com UUID novos. `sobrepor` muda campos."""
    tenant_id = sobrepor.pop("tenant_id", str(uuid.uuid4()))
    contact_id = sobrepor.pop("contact_id", str(uuid.uuid4()))
    corpo = {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "conversation_id": str(uuid.uuid4()),
        "channel_id": str(uuid.uuid4()),
        "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
        "type": "text",
        "modo": "bot",
        "thread_id": thread_id_de(tenant_id, contact_id),
        "vertical": "vendedor",
    }
    corpo.update(sobrepor)
    return corpo


def como_json(corpo: dict[str, Any]) -> bytes:
    return json.dumps(corpo).encode("utf-8")


class Relogio:
    """Um relogio que so anda quando se lhe manda. Em segundos."""

    def __init__(self, inicio: float = 1_000.0) -> None:
        self.agora = inicio

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


class TrancaFalsa:
    """A tranca, sem base: registra a ordem e recusa a sobreposicao.

    E o duplo que torna o criterio 2 mensuravel sem PostgreSQL. **Nao substitui
    a *suite* do *gate* 8**: o que uma tranca falsa prova e que o executor pede
    a tranca e so corre um lote de cada vez; que o `pg_advisory_lock` e exclusao
    mutua entre **processos** so a base pode dizer, e e la que esta medido.
    """

    def __init__(self) -> None:
        self.tomadas: list[str] = []
        self.dentro = 0
        self.sobrepostas = 0

    def tomar(self, thread_id: str):
        import contextlib

        @contextlib.asynccontextmanager
        async def gerir():
            self.tomadas.append(thread_id)
            self.dentro += 1
            if self.dentro > 1:
                self.sobrepostas += 1
            try:
                yield
            finally:
                self.dentro -= 1

        return gerir()
