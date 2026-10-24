"""Apoio das baterias do AGR: conduzir ASGI, e fabricar invocacoes validas.

Conduz a aplicacao ASGI directamente, em vez de usar o `TestClient` do
Starlette, pela razao que o `test_healthz.py` do KAM-001 escreveu: o
`TestClient` exige `httpx`, e acrescentar `httpx` ao lock do AGR para testar
rotas que devolvem quatro campos seria pagar uma arvore de dependencias em
producao por conveniencia de teste. O protocolo ASGI e estavel e a chamada
directa exercita o encaminhamento real do Starlette.
"""

from __future__ import annotations

import asyncio
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
    """Um `agent_invocation` valido, com UUID novos. `sobrepor` muda campos.

    **O `conversation_id` segue o par (tenant, contacto) por omissao**, e isso
    e uma correccao: antes gerava-se um UUID novo em cada chamada, pelo que
    duas invocacoes do **mesmo** contacto saiam com conversas **diferentes**.
    O teste da coalescencia juntava assim seis conversas num lote e passava,
    porque o duplo de `ler_palavra` devolvia a mesma `Palavra` para qualquer
    invocacao — o duplo tornava a propriedade impossivel de falhar, e escondeu
    o defeito que a revisao adversarial encontrou (um lote a atravessar
    conversas aplica a decisao de uma a outra e perde a mensagem da outra).

    Quem quer duas conversas do mesmo contacto — o caso de dois canais, que a
    `conversations_tenant_contact_channel_uq` permite — passa
    `conversation_id` explicitamente.
    """
    tenant_id = sobrepor.pop("tenant_id", str(uuid.uuid4()))
    contact_id = sobrepor.pop("contact_id", str(uuid.uuid4()))
    corpo = {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "conversation_id": _conversa_de(tenant_id, contact_id),
        "channel_id": str(uuid.uuid4()),
        "wamid": "wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8],
        "type": "text",
        "modo": "bot",
        "thread_id": thread_id_de(tenant_id, contact_id),
        "vertical": "vendedor",
    }
    corpo.update(sobrepor)
    return corpo


def _conversa_de(tenant_id: str, contact_id: str) -> str:
    """Um `conversation_id` estavel para um par (tenant, contacto).

    Deriva-se do par por `uuid5` para que duas chamadas com o mesmo par dem a
    mesma conversa, sem o apoio ter de guardar estado. **Nao e um nome do
    dicionario nem um esquema de producao**: em producao o `conversation_id` e
    a chave primaria de `platform.conversations`, gerada pela base. E so uma
    forma de o apoio ser deterministico.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"kamba-teste:{tenant_id}:{contact_id}"))


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
    """A tranca, sem base: **exclui** por chave, e registra a ordem e as esperas.

    A primeira versao nao excluia nada — contava sobreposicoes e nunca as
    impedia —, e isso tornava-a um duplo que nao modela o que substitui: com a
    fila por conversa, os dois canais de um contacto pedem a **mesma** chave ao
    mesmo tempo, e um duplo que deixa passar as duas afirma o contrario da
    propriedade. A revisao adversarial apanhou-o (o achado M3 aponta ao mesmo
    sitio pelo outro lado: um duplo que serializa sem excluir mede o dreno e
    nao a tranca).

    Agora ha um `asyncio.Lock` por chave, e o duplo tem duas saidas:

    - `sobrepostas` tem de ser **0** sempre: e a invariante.
    - `esperas` diz quantas vezes alguem teve de **esperar** por uma chave que
      outro detinha. Um teste de contencao que da `esperas == 0` nao mediu
      contencao nenhuma, e diz isso em vez de passar por acidente.

    **Isto nao substitui a *suite* do *gate* 8.** Que o `pg_try_advisory_lock`
    exclui entre **processos** so a base o pode dizer, e e la que esta medido
    (`db/tests_agr/test_tranca.py`).
    """

    def __init__(self) -> None:
        self.tomadas: list[str] = []
        self.dentro = 0
        self.sobrepostas = 0
        self.esperas = 0
        self._por_chave: dict[str, asyncio.Lock] = {}

    def tomar(self, thread_id: str):
        import contextlib

        trinco = self._por_chave.setdefault(thread_id, asyncio.Lock())

        @contextlib.asynccontextmanager
        async def gerir():
            if trinco.locked():
                self.esperas += 1
            async with trinco:
                self.tomadas.append(thread_id)
                self.dentro += 1
                if self.dentro > 1:
                    self.sobrepostas += 1
                try:
                    yield
                finally:
                    self.dentro -= 1

        return gerir()
