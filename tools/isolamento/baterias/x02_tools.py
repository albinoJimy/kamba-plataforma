"""X-02 — cada tool invocada com estado de A e argumentos de B nao devolve nada de B.

Criterio 3 do KAM-066, segunda metade. E tambem a **unica caixa por marcar do
KAM-028**, que a deixou escrita por extenso: «X-02: cada tool invocada com
estado de A e referencia a entidade de B devolve 0 canarios». Fecha-se aqui.

## Onde esta a defesa, e porque e que o ataque e pelo `args`

A assinatura de uma tool **nao tem** `tenant_id` (`docs/tecnica/08` §3.2, com
*lint* de CI a prova-lo desde o KAM-028): o `tenant_id` vem do `ToolContext`,
derivado do estado, e o modelo nunca o ve nem o fornece. Logo um modelo
capturado por injeccao nao pode *pedir* outro tenant — so pode **nomear
entidades** de outro tenant nos argumentos que existem: um `sku`, um
`order_id`, um `booking_id`, um termo de pesquisa.

E isso que esta bateria faz: o contexto e sempre de A, e os argumentos nomeiam
coisas de B — incluindo o canario de B, posto onde o esquema aceitar texto. O
que se exige e que nada de B volte, **nem no `data`, nem nos `facts`, nem no
`error.detalhe`**. A terceira e a que se esquece: uma mensagem de erro que diga
«o pedido <uuid-de-B> nao e deste tenant» nao devolve canario nenhum e entrega a
existencia de B.

## As onze tools nao estao no mesmo estado, e a bateria trata disso

Uma esta `ligada` (`get_store_info`, com modelo e executor) e dez estao
`declaradas` (nome, classe e credor; sem executor). Isso nao as dispensa:

* a **ligada** invoca-se de verdade, contra a base, com o contexto de A;
* as **declaradas** invocam-se tambem, e o que se exige e que a camada as
  recuse — e que a recusa nao leve nada de B. Uma entrada declarada que
  respondesse era um executor ligado sem passar pelo seu ticket; uma recusa que
  repetisse o argumento era a fuga pela mensagem de erro.

Quando o credor de uma delas a ligar, o caso ja esta escrito: ele le o catalogo
e trata-a pelo estado em que ela estiver.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from ..casos import registar_caso

RAIZ = Path(__file__).resolve().parents[3]

#: As onze tools do REG, pela ordem do catalogo. Literais de proposito (ver o
#: comentario das listas em `x01_rotas.py`).
TOOLS_LIGADAS = ("tool:get_store_info",)

TOOLS_DECLARADAS = (
    "tool:search_catalog",
    "tool:get_price_stock",
    "tool:propose_cart",
    "tool:criar_pedido",
    "tool:get_order_status",
    "tool:list_services",
    "tool:get_availability",
    "tool:book_slot",
    "tool:cancel_booking",
    "tool:reschedule_booking",
)


def _no_caminho() -> None:
    for relativo in ("services/agr/src", "libs/py-core/src"):
        caminho = str(RAIZ / relativo)
        if caminho not in sys.path:
            sys.path.insert(0, caminho)


def _contexto_de_a(ctx):  # noqa: ANN001, ANN202
    """Um `ToolContext` de A. Todos os campos sao de A, e nenhum vem de texto."""
    _no_caminho()
    from kamba_agr.tls.contexto import ToolContext  # noqa: PLC0415

    return ToolContext(
        tenant_id=ctx.a.id,
        channel_id=str(uuid.uuid4()),
        contact_id=str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        turn_id=str(uuid.uuid4()),
        vertical="vendedor",
        run_id=str(uuid.uuid4()),
        graph_version="1.0.0",
    )


def _argumentos_de_b(ctx, esquema: dict | None) -> list[dict]:  # noqa: ANN001
    """Argumentos que nomeiam entidades de B, moldados ao esquema da tool.

    Deriva-se do **esquema** e nao de uma lista por tool: uma tool nova, ou um
    modelo que ganhe um campo, passa a ser atacada no campo novo sem ninguem
    vir aqui. Um esquema sem campos de texto fica com o dicionario vazio — e
    ainda assim a invocacao corre, porque o contexto e de A e a pergunta e se a
    resposta leva algo de B.
    """
    canario = next(iter(ctx.oraculo.proibidos.values()))
    valores = (canario, ctx.b.id, f"{ctx.b.id}:{canario}")
    if not esquema:
        return [{}]
    propriedades = esquema.get("properties") or {}
    tentativas: list[dict] = []
    for valor in valores:
        argumentos: dict[str, object] = {}
        for nome, forma in propriedades.items():
            tipo = forma.get("type")
            if tipo == "string":
                argumentos[nome] = valor
            elif tipo == "integer":
                argumentos[nome] = 1
            elif tipo == "number":
                argumentos[nome] = 1
            elif tipo == "boolean":
                argumentos[nome] = True
            elif tipo == "array":
                argumentos[nome] = []
        if argumentos:
            tentativas.append(argumentos)
    return tentativas or [{}]


def _varrer_resultado(ctx, rotulo: str, resultado) -> list[str]:  # noqa: ANN001
    """O oraculo sobre `data`, `facts` e `error` — as tres saidas de `invoke`."""
    return [
        f"{rotulo}: {fuga}"
        for fuga in ctx.oraculo.varrer_tudo(
            {
                "corpo": getattr(resultado, "data", {}),
                "erro": getattr(resultado, "error", None),
                "logs": ctx.logs,
            }
        )
    ]


def _camada(ctx, abrir_ligacao):  # noqa: ANN001, ANN202
    _no_caminho()
    from kamba_agr.tls.camada import ToolLayer  # noqa: PLC0415
    from kamba_agr.tls.catalogo import catalogo_do_piloto  # noqa: PLC0415

    return ToolLayer(catalogo_do_piloto(), abrir_ligacao=abrir_ligacao, ligacoes=1)


def _invocar(camada, contexto, nome: str, argumentos: dict, permitidas):  # noqa: ANN001
    import asyncio  # noqa: PLC0415

    return asyncio.run(
        camada.invoke(contexto, nome, argumentos, allowed=list(permitidas))
    )


def _atacar(ctx, nomes: tuple[str, ...], abrir_ligacao) -> list[str]:  # noqa: ANN001
    """Invoca cada tool com o contexto de A e argumentos que nomeiam B."""
    _no_caminho()
    from kamba_agr.tls.catalogo import catalogo_do_piloto  # noqa: PLC0415

    catalogo = catalogo_do_piloto()
    camada = _camada(ctx, abrir_ligacao)
    contexto = _contexto_de_a(ctx)
    permitidas = [nome.split(":", 1)[1] for nome in nomes]
    achados: list[str] = []

    for item in nomes:
        nome = item.split(":", 1)[1]
        especificacao = catalogo.get(nome)
        if especificacao is None:
            achados.append(
                f"{item}: a tool esta no REG (`registry/*.yaml`) e **nao** esta "
                "no catalogo da TLS. As duas listas tem de dizer o mesmo: a "
                "camada recusa o que nao esta no catalogo, pelo que esta tool "
                "nunca responderia, e nenhum ensaio a cobria."
            )
            continue
        esquema = especificacao.esquema() if especificacao.ligada else None
        for argumentos in _argumentos_de_b(ctx, esquema):
            try:
                resultado = _invocar(camada, contexto, nome, argumentos, permitidas)
            except Exception as erro:  # noqa: BLE001 — a excepcao tambem e saida
                achados.extend(
                    f"{item}: {fuga}"
                    for fuga in ctx.oraculo.varrer_tudo({"erro": erro})
                )
                achados.append(
                    f"{item}: `invoke` levantou {type(erro).__name__} em vez de "
                    "devolver um `ToolResult`. Um passo do pipeline que levanta "
                    "nao falha fechado: falha aberto para quem chama."
                )
                continue
            achados.extend(_varrer_resultado(ctx, item, resultado))
            if not especificacao.ligada and resultado.ok:
                achados.append(
                    f"{item}: e uma entrada `declarada` (credor "
                    f"{especificacao.credor}) e `invoke` devolveu `ok=True`. Ou "
                    "o executor foi ligado sem passar pelo ticket dele, ou a "
                    "camada parou de distinguir declarada de ligada."
                )
    return achados


def _declaradas(ctx) -> list[str]:  # noqa: ANN001
    """As dez `declaradas`. Sem base: nenhuma chega a abrir ligacao."""

    def abrir_ligacao():  # noqa: ANN202
        raise AssertionError(
            "uma entrada `declarada` abriu ligacao. A recusa tem de vir antes "
            "do passo 6 do pipeline (§6.1), e uma tool sem executor que chega a "
            "base e um passo fora de ordem."
        )

    return _atacar(ctx, TOOLS_DECLARADAS, abrir_ligacao)


def _ligadas(ctx) -> list[str]:  # noqa: ANN001
    """A `get_store_info`, contra a base do *gate*, com o contexto de A.

    E o unico caso desta bateria que mede a RLS pelo caminho que a producao
    usa: o executor abre `tenant_guard.tx(ligacao, ctx.tenant_id)` e a politica
    e a ultima barreira. O ataque e o contexto de A com argumentos que nomeiam
    B — e, como o esquema da `get_store_info` nao tem campos, o ataque e o
    contexto de A a tentar ler o que so B tem.
    """
    if ctx.abrir_ligacao is None:
        return [
            "X-02/tls/ligada: o contexto nao traz `abrir_ligacao`. Num gate, "
            "saltar e falhar."
        ]
    achados = _atacar(ctx, TOOLS_LIGADAS, ctx.abrir_ligacao)

    # A metade positiva: a mesma tool, no mesmo contexto, **devolve a loja de
    # A**. Sem isto, «zero canarios de B» passava com um executor que devolvesse
    # sempre vazio — ou com uma base sem a linha de A.
    camada = _camada(ctx, ctx.abrir_ligacao)
    contexto = _contexto_de_a(ctx)
    resultado = _invocar(camada, contexto, "get_store_info", {}, ["get_store_info"])
    if not resultado.ok:
        achados.append(
            "X-02/tls/ligada: a sonda positiva falhou — a `get_store_info` de A "
            f"devolveu {resultado.error.codigo if resultado.error else '?'}. "
            "As afirmacoes de «zero canarios de B» acima nao provam isolamento "
            "nenhum se a tool nao devolve nada a ninguem."
        )
    else:
        canario_de_a = ctx.a.canarios.get(("platform", "tenants"))
        from ..oraculo import achatar  # noqa: PLC0415

        if canario_de_a and canario_de_a not in achatar(resultado.data):
            achados.append(
                "X-02/tls/ligada: a sonda positiva falhou — a resposta de A nao "
                f"leva o canario de A ({canario_de_a!r}). O ataque corre contra "
                "uma tool que nao le a linha que se semeou."
            )
    return achados


registar_caso(
    id="X-02/tls/declaradas",
    bateria="X-02",
    camada="tls",
    enumeravel=TOOLS_DECLARADAS,
    fn=_declaradas,
    precisa="agr",
    origens=("corpo", "erro", "logs"),
)

registar_caso(
    id="X-02/tls/ligada",
    bateria="X-02",
    camada="tls",
    enumeravel=TOOLS_LIGADAS,
    fn=_ligadas,
    precisa="postgres",
    origens=("corpo", "erro", "logs"),
)
