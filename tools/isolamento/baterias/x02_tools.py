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


def _esquema_da_tool(nome: str, especificacao) -> dict | None:  # noqa: ANN001
    """O esquema de argumentos da tool, **mesmo quando ela e `declarada`**.

    E a correccao do achado 2 da revisao adversarial, e e a que torna esta
    bateria um ataque. Medido antes: as onze tools eram invocadas com `{}` —
    as dez `declaradas` porque a entrada do catalogo nao tem `modelo`, e a
    `get_store_info` porque o modelo dela **nao tem um unico campo**. Logo
    «argumentos que referem entidades de B», que e o que o criterio 3 pede, nao
    era exercitado em sitio nenhum: uma tool que ecoasse o seu argumento de
    texto numa mensagem de erro passava este caso, porque nenhum argumento de
    texto lhe chegava.

    Os modelos das dez existem — `tls/vendedor.py` e `tls/servicos.py`
    declaram-nos em `MODELOS` — e o que falta e a **ligacao** ao catalogo, que e
    dos tickets que ligam cada *backend* (KAM-043, KAM-046, KAM-061, KAM-035).
    Esta funcao le-os de onde eles estao: pelo catalogo quando a entrada esta
    `ligada`, pelos `MODELOS` da vertical quando nao esta.

    **O que isto nao finge ser:** invocar a tool com o modelo dela nao a liga.
    A camada continua a recusar uma entrada `declarada` no passo 1, e e isso que
    o caso afirma. O que muda e que a recusa passa a ser medida **com o canario
    de B dentro dos argumentos**, que e onde a fuga sairia.
    """
    if especificacao.ligada:
        return especificacao.esquema()
    from kamba_agr.tls import servicos, vendedor  # noqa: PLC0415

    modelo = vendedor.MODELOS.get(nome) or servicos.MODELOS.get(nome)
    return modelo.model_json_schema() if modelo is not None else None


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
    """O oraculo sobre `data`, **`facts`** e `error` — as saidas de `invoke`.

    **Os `facts` faltavam, e sao o campo que volta ao modelo.** O `ToolResult`
    tem quatro saidas (`tls/erros.py`) e este varredor olhava para tres; a
    *docstring* do modulo e a desta funcao diziam as duas que os `facts`
    entravam. Era a resposta directa a pergunta «em que forma e que um canario
    atravessa sem ser encontrado»: por ali. Achado 3 da revisao adversarial.

    Vao numa origem propria (`corpo`) e nao concatenados ao `data`: um `Fact` e
    uma estrutura, o `achatar` sabe percorre-la, e separar as origens faz a
    mensagem do achado dizer **onde** vazou.
    """
    return [
        f"{rotulo}: {fuga}"
        for fuga in ctx.oraculo.varrer_tudo(
            {
                "corpo": (
                    getattr(resultado, "data", {}),
                    getattr(resultado, "facts", ()),
                ),
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
    #: Quantas tools foram atacadas com **algum** argumento, e quantas **tem**
    #: campos no esquema. A comparacao entre os dois e que e o sentinela: zero
    #: atacadas **havendo** tools com campos e um achado — era o estado medido
    #: antes do achado 2 da revisao adversarial, e um caso que invoca tudo com
    #: `{}` nao mede a metade do criterio 3 que fala de «argumentos que referem
    #: entidades de B».
    #:
    #: **Mas zero atacadas e zero com campos nao e achado**, e a execucao do
    #: *gate* mostrou porque: a `get_store_info` e a `list_services` tem esquema
    #: **sem um unico campo**, por desenho — a loja e os servicos leem-se do
    #: contexto. Nelas o ataque e o contexto de A sozinho, e exigir-lhes um
    #: argumento era exigir o que o desenho nao tem.
    com_argumentos = 0
    com_campos = 0

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
        esquema = _esquema_da_tool(nome, especificacao)
        if (esquema or {}).get("properties"):
            com_campos += 1
        tentativas = _argumentos_de_b(ctx, esquema)
        if any(tentativa for tentativa in tentativas):
            com_argumentos += 1
        for argumentos in tentativas:
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
            if not especificacao.ligada and resultado.ok:  # noqa: SIM102
                achados.append(
                    f"{item}: e uma entrada `declarada` (credor "
                    f"{especificacao.credor}) e `invoke` devolveu `ok=True`. Ou "
                    "o executor foi ligado sem passar pelo ticket dele, ou a "
                    "camada parou de distinguir declarada de ligada."
                )
    if com_campos and not com_argumentos:
        achados.append(
            f"X-02: {com_campos} das {len(nomes)} tool(s) tem campos no esquema e "
            "**nenhuma** foi atacada com argumentos. Todas foram invocadas com "
            "`{}`, pelo que a metade do criterio 3 que fala de «argumentos que "
            "referem entidades de B» nao foi exercitada. Era o estado medido "
            "antes do achado 2 da revisao adversarial: os modelos das "
            "`declaradas` estao em `tls/vendedor.py` e `tls/servicos.py` "
            "(`MODELOS`) e e de la que `_esquema_da_tool` os le."
        )
    return achados


def _declaradas(ctx) -> list[str]:  # noqa: ANN001
    """As dez `declaradas`, invocadas com o contexto de A e argumentos de B.

    **A ligacao vem do contexto quando ha uma**, e isso e uma correccao: a
    primeira versao passava um `abrir_ligacao` que levantava, para afirmar de
    passagem que uma entrada `declarada` nunca chega a base. A afirmacao e
    plausivel — a recusa vem do passo 1 do pipeline (§6.1) — mas o pipeline
    escreve `tool_audit` para `write`/`money` (criterio 5 do KAM-028), e o
    `criar_pedido` e `money` **e** declarado: uma escrita de auditoria numa
    recusa abria a ligacao, o duplo levantava, e o caso reportava um achado que
    era do duplo e nao do codigo. Um caso que acusa o seu proprio andaime
    ensina a ignorar a lista.
    """

    def sem_base():  # noqa: ANN202
        raise RuntimeError(
            "a ToolLayer pediu uma ligacao e este contexto nao tem base. O "
            "caso corre em `db/tests_isolamento/`, onde ha uma."
        )

    return _atacar(ctx, TOOLS_DECLARADAS, ctx.abrir_ligacao or sem_base)


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
