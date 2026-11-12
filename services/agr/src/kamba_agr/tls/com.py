"""Os executores das tools de comercio: a TLS a falar com o COM (KAM-178).

O KAM-031 escreveu os **modelos** das cinco tools do Vendedor e deferiu os
**executores**, com a razao escrita: «entregar as cinco `ligadas` com executores
de ensaio punha o `catalogo_do_piloto()` a servir precos inventados a quem o
chamasse em producao», deixando-os «com o credor que **liga o backend**». Este
modulo e esse credor para as que falam com o COM.

## Quatro e nao cinco, e a quinta tem credor

| Tool | Rota | Estado |
|---|---|---|
| `get_price_stock` | `POST /internal/offer-view` | ligada, **sem *facts* numericos** |
| `propose_cart` | `POST /internal/propose-cart` | ligada, com *fact* `total` |
| `criar_pedido` | `POST /internal/create-order` | ligada |
| `get_order_status` | `POST /internal/get-order` | ligada |
| `search_catalog` | — | nao e daqui: fala com o **IDX**, em `tls/idx.py` (KAM-061) |

O `search_catalog` fala com o **IDX** (§6.2) e nao com o COM: o `idx.candidatos`
vive na base da plataforma (ADR-006), e o executor dele esta em `tls/idx.py`,
ligado pelo KAM-061.

## O `get_price_stock` nao devolve *facts*, e isso e um achado e nao um atalho

O §6.2 diz que ele «devolve *facts* `price` e `stock`». A `OfferView` do §3.2 —
que e o que o `getOfferView` da porta entrega — tem `precoTipo`,
`precoDisplay`, `stockModo`, `disponibilidade` e `atualizadoAt`, e **nenhum
numero**: o preco vem **ja formatado** («preco opaco», KAM-043) e o stock vem
como *modo* e nao como quantidade, porque o §5.4 poe a quantidade no Registo e
da a `offer_terms` so o modo.

Logo um *fact* `price` construido daqui teria de levar uma **cadeia** no `value`,
e o dicionario manda dinheiro em unidade menor inteira; e um *fact* `stock`
teria de levar um modo onde o KAM-032 espera uma quantidade. Inventar um numero
a partir de um texto formatado era o pior dos dois mundos — um numero com
proveniencia a dizer o que ninguem mediu.

Por isso este executor devolve os **dados** (que e o que o `compose` precisa
para dizer o preco pelo texto que o COM formatou) e **nenhum *fact***, e a
divergencia fica devolvida com o credor na verificacao do bloco KAM-178: dar
numero ao `get_price_stock` e alargar a `OfferView` do §3.39/§3.40, que e canon.

## O ambito de dados do `get_order_status` e **do executor**

O §6.2 da-lhe «tenant **e** contacto», e o `getOrder` da porta filtra **so por
tenant** — e isso e certo do lado da porta, que serve tambem o dono e o `ops`.
Quem estreita para o contacto e quem chama em nome de um cliente, e e aqui: uma
encomenda de outro contacto do mesmo tenant da **a mesma** resposta que uma que
nao existe (`NOT_FOUND`). Distingui-las era o oraculo que o X-09 procura.

## O transporte e injectavel, e o `httpx` importa-se **dentro** da funcao

A mesma forma do `llm/cliente.py`, e pela mesma razao: importar este modulo nao
custa o `httpx`, e a bateria corre sem rede. O executor e **sincrono** porque e
isso que o `invoke` espera — ele corre o executor numa *thread*
(`asyncio.to_thread`), e um executor assincrono obrigava a camada a saber qual
dos dois recebeu.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Final

from .erros import (
    NOT_FOUND,
    UPSTREAM_DOWN,
    UPSTREAM_TIMEOUT,
    VALIDATION_ERROR,
    Fact,
)
from .especificacoes import ErroDeBackend, Pedido, Resposta

#: O cabecalho da credencial interna do COM. Dicionario §3.24.
CABECALHO_INTERNO: Final = "x-kamba-interno"

#: O cabecalho do tenant. Dicionario §3.39.
CABECALHO_TENANT: Final = "x-kamba-tenant"

#: O `id` do segredo da credencial no inventario (`ops/secrets-inventory.yaml`).
#:
#: **Nao e o `agr_internal_token`**: uma credencial por servico, porque quem a
#: tem alcanca tudo o que o servico serve. Escrito aqui e no
#: `services/com/src/api/interna.ts`, que e o lado que a verifica — e os dois
#: nomeiam a mesma entrada do inventario, que e o dono.
SEGREDO_DO_COM: Final = "com_internal_token"

#: A variavel com a base da API interna do COM. Sem ela o arranque **nao liga**
#: os executores e as cinco entradas continuam `declaradas` — o que e visivel no
#: `log` de arranque (`ligadas_N_de_11`) e nao em silencio.
VARIAVEL_DA_BASE: Final = "KAMBA_COM_URL"

#: O `entrega_modo` que o grafo do Vendedor usa. **`levantamento`, *proposta***.
#:
#: O §6.3 poe a `entrega` no rascunho e o grafo do Vendedor nao a modela: nao ha
#: no que a pergunte, e o `COM_DELIVERY_ENABLED` esta desligado no Piloto (as
#: duas transicoes da entrega estao atras da bandeira na revisao `0030`). Fixa-se
#: `levantamento` em vez de se adivinhar, e calibra-se no ticket que der ao grafo
#: um no de entrega — credor escrito na verificacao do bloco KAM-178.
ENTREGA_DO_PILOTO: Final = "levantamento"

#: Os codigos que a API interna devolve no corpo e que **sao** erros da TLS.
#:
#: **Sao nove, e sao os nove do `OrdersModule.erro`** (dicionario §3.44) — que e
#: a lista que o COM pode devolver depois do KAM-178, e nao os treze do §3.27. A
#: primeira versao desta nota dizia «os onze do §6.5 mais os dois do §6.3» sobre
#: um conjunto de nove, e isso nao e cosmetico: se algum dia um dos quatro
#: codigos canonicos que faltam (`ENTITLEMENT_DENIED`, `TOOL_NOT_ALLOWED`,
#: `SLOT_TAKEN`, `HOLD_EXPIRED`) vier no corpo, cai em `UPSTREAM_DOWN` e **perde
#: o nome** — e o comentario dizia o contrario. Os quatro nao vem: os dois
#: primeiros sao do passo 2 do `invoke` e os dois ultimos sao do modulo
#: `servicos`, que nao e servido por esta API. Achado da revisao adversarial.
#:
#: O `NOT_IMPLEMENTED` **nao** esta aqui, e por desenho: ele para na API interna
#: do COM, que o traduz para 501 (§3.39), e um 501 cai no ramo do estado — nao no
#: do nome.
_CODIGOS_DA_TLS: Final = frozenset(
    {
        "NOT_FOUND",
        "VALIDATION_ERROR",
        "TENANT_MISMATCH",
        "PRICE_CHANGED",
        "OUT_OF_STOCK",
        "LIMIT_EXCEEDED",
        "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_DOWN",
    }
)


class RespostaDoCom:
    """O que uma chamada a API interna devolveu: estado e corpo."""

    __slots__ = ("estado", "corpo")

    def __init__(self, estado: int, corpo: Mapping[str, Any]) -> None:
        self.estado = estado
        self.corpo = corpo


#: O transporte: recebe (url, cabecalhos, corpo, timeout_s) e devolve a resposta.
Transporte = Callable[[str, dict[str, str], dict[str, Any], float], RespostaDoCom]


def _transporte_httpx(
    url: str, cabecalhos: dict[str, str], corpo: dict[str, Any], timeout: float
) -> RespostaDoCom:
    """O transporte por omissao. O `httpx` ja esta no fecho desde o KAM-026."""
    import httpx

    try:
        resposta = httpx.post(url, headers=cabecalhos, json=corpo, timeout=timeout)
    except httpx.TimeoutException as excepcao:
        raise TimeoutError(str(excepcao)) from excepcao
    try:
        lido = resposta.json()
    except ValueError:
        lido = {}
    return RespostaDoCom(
        resposta.status_code, lido if isinstance(lido, dict) else {}
    )


@dataclass(frozen=True, slots=True)
class ClienteDoCom:
    """O cliente da API interna do COM. **Nao sabe nada de tools.**

    Separado dos executores de propósito: o que ele faz — pôr os dois
    cabeçalhos, traduzir o corpo de erro para `ErroDeBackend` e nada mais — é o
    mesmo para as quatro tools, e escrevê-lo quatro vezes dava quatro
    oportunidades de esquecer um dos cabeçalhos.
    """

    base: str
    #: A credencial, **lida a cada chamada** e nao guardada.
    #:
    #: E um `callable` e nao uma cadeia por duas razoes, e a segunda e a que
    #: obriga: o `api_interna.py` do AGR ja o faz assim (`credencial=lambda:
    #: segredos.get(...)`), pelo que uma rotacao do cofre chega sem reinicio; e o
    #: catalogo da ToolLayer constroi-se **antes** do `Secrets.arrancar` no
    #: `__main__.py` — ele e a fonte da validacao (1) do §5.2, que corre com o
    #: registo —, pelo que uma cadeia lida no momento da construcao nao existia
    #: ainda. Trocar a ordem do arranque mudava os codigos de saida que o
    #: dicionario §3.26 fixa.
    credencial: Callable[[], str]
    transporte: Transporte = _transporte_httpx

    def chamar(
        self, rota: str, ctx: Any, corpo: Mapping[str, Any], timeout_ms: int
    ) -> Mapping[str, Any]:
        """Uma chamada, com o `ctx` do turno nos cabeçalhos e no corpo.

        **O `tenant_id` vai no cabeçalho e o `actor`/`trace_id` no corpo**, que é
        a forma que o COM exige: o tenant é o que um proxy pode registar sem
        abrir o corpo, e é o que o `lint_arch medusa` verifica na rota. Nenhum dos
        três vem de texto do cliente — vêm do `ToolContext`, que se constrói do
        estado (§6.1, ADR-015).

        Levanta `ErroDeBackend` com o código canónico do corpo. **Um estado HTTP
        sem código no corpo é `UPSTREAM_DOWN`**: a API interna põe sempre o nome
        lá, pelo que um corpo sem ele é o COM a não responder como o COM.
        """
        url = f"{self.base.rstrip('/')}{rota}"
        cabecalhos = {
            CABECALHO_INTERNO: self.credencial(),
            CABECALHO_TENANT: ctx.tenant_id,
            "content-type": "application/json",
        }
        pedido = {
            # O `actor` é `agente`: quem chama é o grafo, e os quatro `kind` do
            # §3.39 são do lado da porta. Um `sistema` aqui dava a uma chamada de
            # conversa o actor que o §6.2 reserva ao PAY.
            "actor": {"kind": "agente", "id": f"grafo-{ctx.vertical}"},
            # O `traceId` é obrigatório na porta, e o `turn_id` é o fio que liga
            # a intenção à encomenda na reconciliação do §10.3.
            "trace_id": ctx.turn_id,
            **dict(corpo),
        }
        resposta = self.transporte(url, cabecalhos, pedido, timeout_ms / 1000)
        if resposta.estado == 200:
            valor = resposta.corpo.get("valor")
            return valor if isinstance(valor, Mapping) else {}
        codigo = resposta.corpo.get("erro")
        if isinstance(codigo, str) and codigo in _CODIGOS_DA_TLS:
            raise ErroDeBackend(codigo, f"o COM recusou {rota}")
        if resposta.estado == 409 and resposta.corpo.get("tipo") == "conflito":
            # **O terceiro caso do `Resultado` chega como 409 e sem código**, e é
            # isso que ele quer dizer: «relê e reavalia». Nenhum dos treze erros
            # do §3.27 o diz — e é precisamente a razão por que o COM não o
            # traduziu para `VALIDATION_ERROR` (KAM-044, KAM-046). Para o grafo,
            # o que resta é repetir o turno com o que ler agora, e o código que
            # o §6.5 manda tratar assim é o `UPSTREAM_TIMEOUT`: um `retry` e
            # depois handoff.
            raise ErroDeBackend(
                UPSTREAM_TIMEOUT, f"conflito de CAS em {rota}: relê e reavalia"
            )
        if resposta.estado in (502, 503, 504):
            raise ErroDeBackend(UPSTREAM_DOWN, f"o COM nao respondeu a {rota}")
        raise ErroDeBackend(
            UPSTREAM_DOWN,
            f"resposta inesperada do COM em {rota}: http_{resposta.estado}",
        )


# ------------------------------------------------------------------ executores


def _contador() -> Callable[[], str]:
    """Gera `fact_id` **opacos**, e é por isso que é um contador.

    «Um `fact_id` é opaco. Não se deriva de um argumento nem do valor» (KAM-028):
    ele entra na coluna `fact_ids` da `tool_audit`, e um `fact_id` derivado de
    texto do cliente põe texto do cliente no registo de auditoria.
    """
    estado = {"n": 0}

    def proximo() -> str:
        estado["n"] += 1
        return f"f{estado['n']}"

    return proximo


def executores_do_com(cliente: ClienteDoCom) -> dict[str, Any]:
    """As quatro tools do Vendedor que falam com o COM.

    Devolve o mapa que o `especificacoes_do_vendedor()` espera, **sem** o
    `search_catalog`: aquele fala com o IDX e o executor é o de `tls/idx.py`
    (KAM-061). Quem junta os dois mapas é o `__main__`.
    """
    proximo_fact = _contador()

    def get_price_stock(pedido: Pedido) -> Resposta:
        """Uma `OfferView` por `sku`. **Sem *facts***: ver a nota do módulo."""
        linhas = []
        for sku in pedido.args.skus:  # type: ignore[attr-defined]
            try:
                vista = cliente.chamar(
                    "/internal/offer-view",
                    pedido.ctx,
                    {"sku": sku},
                    pedido.timeout_ms,
                )
            except ErroDeBackend as erro:
                # **Um `sku` que não existe não recusa a lista inteira**: o
                # `get_price_stock` recebe até vinte e o cliente perguntou por
                # todos. O que se perde é a linha, não a resposta — e um
                # `NOT_FOUND` de um `sku` com os outros a existir é o catálogo a
                # ter mudado, não um pedido inválido.
                if erro.codigo != NOT_FOUND:
                    raise
                continue
            linhas.append(
                {
                    "sku": str(vista.get("sku", sku)),
                    "preco_tipo": str(vista.get("precoTipo", "")),
                    "preco_display": vista.get("precoDisplay"),
                    "stock_modo": str(vista.get("stockModo", "")),
                    "disponibilidade": str(vista.get("disponibilidade", "")),
                    "atualizado_at": str(vista.get("atualizadoAt", "")),
                }
            )
        if not linhas:
            raise ErroDeBackend(NOT_FOUND, "nenhum dos skus esta no catalogo")
        return Resposta(data={"linhas": tuple(linhas)})

    def propose_cart(pedido: Pedido) -> Resposta:
        """O total somado no **backend**, com *fact* `total` (ADR-007)."""
        rascunho = _rascunho_de(pedido)
        corpo = cliente.chamar(
            "/internal/propose-cart",
            pedido.ctx,
            {
                **rascunho,
                # As linhas do rascunho são a **única** fonte: o `items` dos
                # argumentos já entrou nelas, e passar as duas era o defeito que
                # o `RascunhoDoCarrinho` do COM descreve («um pedido com
                # `rascunho.linhas` de 2 e `itens` de 5 criava uma encomenda de
                # 5 com o `draft_hash` de 2»).
            },
            pedido.timeout_ms,
        )
        total = corpo.get("total_minor")
        if not isinstance(total, str) or not total.isdigit():
            # O total vem como **cadeia de dígitos** porque é `bigint` do outro
            # lado; um `number` em JSON arredonda em silêncio acima de 2^53.
            raise ErroDeBackend(
                UPSTREAM_DOWN, "o COM devolveu um total que nao e inteiro"
            )
        return Resposta(
            data={
                "cart_id": str(corpo.get("cart_id", "")),
                "items": tuple(
                    (linha["sku"], linha["qty"]) for linha in rascunho["linhas"]
                ),
                "exige_confirmacao_do_dono": bool(
                    corpo.get("exige_confirmacao_do_dono")
                ),
            },
            # **O `Fact` constroi-se aqui e nunca no COM** (ADR-007, e o
            # `cart.ts` escreve-o do outro lado): o COM devolve o número e a
            # proveniência, e quem o embrulha é a ToolLayer, que é dona da forma.
            facts=(
                Fact(
                    fact_id=proximo_fact(),
                    kind="total",
                    value=int(total),
                    retrieved_at=str(corpo.get("retrieved_at") or _agora()),
                ),
            ),
        )

    def criar_pedido(pedido: Pedido) -> Resposta:
        """A *saga* do §6.3, idempotente pela `intent_key` que o COM deriva."""
        rascunho = _rascunho_de(pedido)
        total = rascunho.pop("total_esperado_minor", None)
        if total is None:
            raise ErroDeBackend(
                VALIDATION_ERROR,
                "o rascunho nao traz o total que o cliente confirmou",
            )
        corpo = cliente.chamar(
            "/internal/create-order",
            pedido.ctx,
            {
                **rascunho,
                "total_esperado_minor": str(total),
                "cart_id": pedido.args.cart_id,  # type: ignore[attr-defined]
            },
            pedido.timeout_ms,
        )
        return Resposta(
            data={
                "order_id": str(corpo.get("orderId", "")),
                "numero_publico": str(corpo.get("numeroPublico", "")),
                "estado": str(corpo.get("estado", "")),
                # **O `repeticao` do COM é o `idempotent_replay` da TLS**, e os
                # dois nomes são o mesmo facto visto dos dois lados: «esta
                # resposta repete uma criação anterior».
                "idempotent_replay": bool(corpo.get("repeticao")),
            }
        )

    def get_order_status(pedido: Pedido) -> Resposta:
        """O estado de uma encomenda **do próprio contacto** (§6.2)."""
        corpo = cliente.chamar(
            "/internal/get-order",
            pedido.ctx,
            {"order_id": pedido.args.order_id},  # type: ignore[attr-defined]
            pedido.timeout_ms,
        )
        if str(corpo.get("contactId", "")) != pedido.ctx.contact_id:
            # A mesma resposta que um `order_id` que não existe. Ver a nota do
            # módulo.
            raise ErroDeBackend(
                NOT_FOUND, "encomenda inexistente ou de outro contacto"
            )
        return Resposta(
            data={
                "order_id": str(corpo.get("orderId", "")),
                "numero_publico": str(corpo.get("numeroPublico", "")),
                "estado": str(corpo.get("estado", "")),
            }
        )

    return {
        "get_price_stock": get_price_stock,
        "propose_cart": propose_cart,
        "criar_pedido": criar_pedido,
        "get_order_status": get_order_status,
    }


def _agora() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rascunho_de(pedido: Pedido) -> dict[str, Any]:
    """O rascunho do §6.3, validado. **Levanta se faltar.**

    Um executor sem rascunho é um defeito de montagem do grafo e não uma recusa
    de domínio — mas sai como `VALIDATION_ERROR` e não como excepção, pela razão
    do `erros.py`: «os onze são respostas previstas e o grafo decide sobre elas».
    Uma excepção aqui fazia o turno falhar com 500 em vez de o `compose` dizer
    que não conseguiu.
    """
    rascunho = pedido.rascunho
    if not isinstance(rascunho, Mapping):
        raise ErroDeBackend(
            VALIDATION_ERROR, "a invocacao nao traz o rascunho do §6.3"
        )
    linhas = rascunho.get("linhas")
    if (
        not isinstance(rascunho.get("draft_id"), str)
        or not rascunho["draft_id"]
        or not isinstance(rascunho.get("draft_version"), int)
        or rascunho["draft_version"] < 1
        or not isinstance(linhas, (list, tuple))
        or not linhas
    ):
        raise ErroDeBackend(
            VALIDATION_ERROR, "o rascunho do §6.3 nao tem identidade utilizavel"
        )
    saida: dict[str, Any] = {
        "contact_id": pedido.ctx.contact_id,
        "draft_id": rascunho["draft_id"],
        "draft_version": rascunho["draft_version"],
        "entrega_modo": str(rascunho.get("entrega_modo") or ENTREGA_DO_PILOTO),
        "linhas": [
            {"sku": str(linha["sku"]), "qty": int(linha["qty"])} for linha in linhas
        ],
    }
    if "total_esperado_minor" in rascunho:
        saida["total_esperado_minor"] = int(rascunho["total_esperado_minor"])
    return saida


__all__ = [
    "CABECALHO_INTERNO",
    "CABECALHO_TENANT",
    "ClienteDoCom",
    "ENTREGA_DO_PILOTO",
    "RespostaDoCom",
    "SEGREDO_DO_COM",
    "Transporte",
    "VARIAVEL_DA_BASE",
    "executores_do_com",
]