"""X-01 — para cada rota, A usa identificadores de B e nao recebe nada de B.

Criterio 3 do KAM-066, primeira metade: «para cada rota, A usa IDs de B (IDOR)
e recebe 403/404 **uniformes** sem canario». A palavra que faz o criterio e
*uniformes*: um 404 numa rota e um 403 noutra, para o mesmo ataque, e um oraculo
de existencia — quem ataca aprende, pela diferenca, que o recurso de B existe.
Por isso cada caso afirma duas coisas distintas: que nada de B saiu, **e** que
as respostas a identificadores de B sao indistinguiveis entre si.

## As rotas desta arvore nao sao todas iguais, e o caso diz qual e qual

```text
14 rotas levam identificadores   o IDOR e possivel, e e o que se ataca
16 rotas sao sonda ou metricas   nao recebem identificador nenhum; o que se
                                 prova e que a resposta nao leva canario nem
                                 `tenant_id`, e que o oraculo morderia se levasse
```

As sete `POST /internal/*` do COM (KAM-178) entram na primeira metade, e o
`ALL /internal/*` da app sem API montada entra nela tambem: ele recebe os mesmos
corpos, e o que se afirma e que os recusa de forma indistinguivel. O
`GET /metrics` do COM entra na segunda.

Uma rota de sonda nao escapa ao criterio por nao ter argumentos: ela responde, e
o que ela responde atravessa o oraculo como qualquer outra. O `/metrics` e o
caso real — as metricas desta casa sao contadores sem etiquetas
(`entrada/metricas.ts`), e um dia em que alguem lhes acrescente um rotulo por
tenant e o dia em que esta bateria tem de ficar vermelha.

## Onde cada metade corre, e porque nao correm no mesmo sitio

* **As cinco rotas do AGR** sao Starlette e vivem em Python: o caso constroi a
  aplicacao com duplos, conduz o ASGI directamente e le a resposta. Corre em
  `services/agr/tests/`, que e onde o `starlette`, o `pydantic` e o `yaml` do
  AGR existem — o *venv* do *gate* 6 tem-nos, mas a suite da base nao tem o
  pacote do AGR no caminho de importacao.
* **As vinte e seis rotas de TypeScript** sao Hono, e uma aplicacao Hono
  responde em processo pelo `app.request()` (e a forma que os testes do GWY ja
  usam). O caso chama um **condutor** em `node` e le o relatorio JSON dele;
  corre em `db/tests_isolamento/`, porque a rota `POST /internal/channels`
  precisa de uma transaccao real contra a base do *gate*. **O grupo
  `com-interna` e a excepcao**: os duplos substituem a porta do COM, pelo que
  ele corre sem base nenhuma — o que se mede nele e a construcao do `ctx`, e nao
  a filtragem.

Nenhuma das duas metades e um servidor levantado: sao as aplicacoes em processo.
Isso nao e so velocidade — e o que torna o caso determinista e o que permite
afirmar que o duplo do executor **nao foi chamado**, que e a afirmacao mais
forte desta bateria.
"""

from __future__ import annotations

from collections.abc import Callable

from ..casos import registar_caso

# --------------------------------------------------------------------- itens
#
# As listas sao **literais de proposito**. Um filtro — «todas as rotas» — fazia
# a cobertura passar para sempre e uma rota nova nascia coberta, que e o «sem
# teste silencioso» que o criterio 2 existe para fechar.

#: As quatro rotas internas do AGR. Levam identificadores no corpo.
ROTAS_INTERNAS_DO_AGR = (
    "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/turn",
    "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/resume",
    "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/event",
    "rota:agr:kamba_agr/api_interna:rotas:POST:/internal/draft-decision",
)

#: A sonda do AGR. Sem identificadores.
SONDA_DO_AGR = ("rota:agr:kamba_agr/app:create_app:GET:/healthz",)

#: As metricas do AGR (KAM-080). Sem identificadores a entrada; o que importa
#: e a **saida**, que e tudo o que o processo contou.
METRICAS_DO_AGR = ("rota:agr:kamba_agr/app:create_app:GET:/metrics",)

#: As sondas e as metricas em TypeScript. Nenhuma recebe identificador.
SONDAS_TS = (
    "rota:com:app:createApp:GET:/healthz",
    "rota:gwy:app:createApp:GET:/healthz",
    "rota:gwy:app:criarAppDeMetricas:GET:/healthz",
    "rota:gwy:app:criarAppDeMetricas:GET:/metrics",
    "rota:onboarding-web:app:createApp:GET:/healthz",
    "rota:worker-canal:agr_shim:criarApp:GET:/healthz",
    "rota:worker-canal:agr_shim:criarApp:GET:/metrics",
    "rota:worker-canal:app:createApp:GET:/healthz",
    "rota:worker-canal:consumidor:criarApp:GET:/healthz",
    "rota:worker-canal:consumidor:criarApp:GET:/metrics",
    "rota:worker-canal:entrada:criarApp:GET:/healthz",
    "rota:worker-canal:entrada:criarApp:GET:/metrics",
    "rota:worker-canal:publicador:criarApp:GET:/healthz",
    "rota:worker-canal:publicador:criarApp:GET:/metrics",
)

#: O *webhook* da Meta. O `GET` e a verificacao `hub.*`; o `POST` traz eventos.
WEBHOOK_DO_GWY = (
    "rota:gwy:webhook:montarWebhook:GET:/wa/webhook",
    "rota:gwy:webhook:montarWebhook:POST:/wa/webhook",
)

#: `POST /internal/channels` — o `tenant_id` vem **no corpo**, e por isso e o
#: alvo de IDOR mais directo do conjunto.
CANAIS_DO_GWY = ("rota:gwy:canais:montarCanais:POST:/internal/channels",)

#: Os estados que contam como recusa. O criterio escreve «403/404», e esta
#: lista e mais larga — com razao escrita, uma a uma:
#:
#:   400  `corpo_invalido` do AGR. Um corpo que mistura o tenant de A com o
#:        `thread_id` de B e recusado por `thread_id_incoerente` **antes** de
#:        qualquer leitura: a recusa mais cedo que ha, e nao diz nada sobre B.
#:   401  sem credencial interna, ou `secret` do *agent bot* errado.
#:   403  a recusa que o criterio nomeia.
#:   404  a recusa que o criterio nomeia, e a do GWY a uma rota nao montada.
#:   409  conflito. E a recusa que o criterio 4 do KAM-016 promete para um
#:        numero ja ligado a outro tenant: diz que ha conflito e nao diz com
#:        quem.
#:   503  `Retry-After`. E a resposta documentada do §14 do `docs/tecnica/02`
#:        para «nao se consome agora e fica na fila» — o consumidor por ligar, o
#:        grafo nao registado, o tecto do tenant cheio. Nao e uma resposta sobre
#:        o recurso: nao distingue um identificador de B de um inexistente, e e
#:        isso que o criterio pede ao escrever «uniformes».
#:
#: **O 2xx fica de fora, e e o unico que importa manter de fora**: um 200 a um
#: identificador de outro tenant e a falha que esta bateria existe para apanhar.
#: O que o caso exige nao e um numero da lista — e que **o mesmo ataque nao
#: produza estados diferentes na mesma rota**.
RECUSAS_ACEITAVEIS = (400, 401, 403, 404, 409, 503)


def _uniformidade(
    rotulo: str, estados: list[int], aceitaveis: tuple[int, ...] = RECUSAS_ACEITAVEIS
) -> list[str]:
    """Os achados de uniformidade de uma rota atacada varias vezes."""
    achados: list[str] = []
    distintos = sorted(set(estados))
    if len(distintos) > 1:
        achados.append(
            f"{rotulo}: identificadores de B produziram estados diferentes "
            f"({distintos}). A diferenca e um oraculo de existencia: quem ataca "
            "aprende, por ela, qual dos identificadores existe. O criterio 3 "
            "pede recusas **uniformes**."
        )
    fora = sorted({estado for estado in distintos if estado not in aceitaveis})
    if not fora:
        return achados
    # **Duas mensagens, e nao uma**, porque os `aceitaveis` nao sao sempre uma
    # lista de recusas: o `aceitaveis_por_item` deixa um item responder 200 (o
    # `GET /metrics` do COM) ou so 503 (o `ALL /internal/*`). Dizer «404 nao e
    # uma recusa» ao `/metrics` era o relatorio a nomear a coisa errada —
    # naquele item um 404 nao e uma fuga, e a rota em baixo.
    if 200 not in aceitaveis:
        achados.append(
            f"{rotulo}: identificadores de B produziram {fora}, que nao e uma "
            f"recusa ({aceitaveis}). Um 2xx a um identificador de outro "
            "tenant e a falha que esta bateria existe para apanhar."
        )
    else:
        achados.append(
            f"{rotulo}: as tentativas produziram {fora}, fora dos estados que "
            f"este item pode responder ({aceitaveis}). Este item responde 2xx "
            "quando esta de pe, pelo que um estado de fora quer dizer que ele "
            "nao respondeu — e entao o caso nao mediu o que diz medir."
        )
    return achados


# ------------------------------------------------------------------ o AGR


def _conduzir_agr(ctx) -> list[str]:  # noqa: ANN001 — Contexto, sem importar o tipo
    """Constroi o AGR com duplos e ataca as quatro rotas internas com IDs de B.

    O duplo do executor **registra o que lhe chega e nao corre nada**. A
    afirmacao mais forte do caso e sobre ele: um corpo que mistura o tenant de
    A com identificadores de B nao chega ao executor. Uma rota que o deixasse
    chegar passava as afirmacoes sobre a resposta (o executor devolvia uma
    recusa) e tinha, apesar disso, aceitado a mistura.
    """
    from ._agr import atacar_rotas_internas  # noqa: PLC0415

    return atacar_rotas_internas(ctx)


def _conduzir_sonda_do_agr(ctx) -> list[str]:  # noqa: ANN001
    from ._agr import atacar_sonda  # noqa: PLC0415

    return atacar_sonda(ctx)


def _conduzir_metricas_do_agr(ctx) -> list[str]:  # noqa: ANN001
    from ._agr import atacar_metricas  # noqa: PLC0415

    return atacar_metricas(ctx)


# --------------------------------------------------------------- TypeScript


def _relatorio_ts(ctx, grupo: str) -> tuple[dict, list[str]]:  # noqa: ANN001
    """Corre o condutor de `node` e devolve `(por item, achados de execucao)`."""
    if ctx.node is None:
        return {}, [
            f"X-01/{grupo}: nao ha condutor de node no contexto. Num gate, "
            "saltar e falhar."
        ]
    relatorio = ctx.node(grupo)
    if not isinstance(relatorio, dict) or "rotas" not in relatorio:
        return {}, [
            f"X-01/{grupo}: o condutor devolveu um relatorio sem `rotas`: "
            f"{str(relatorio)[:200]}"
        ]
    por_item: dict[str, list[dict]] = {}
    for entrada in relatorio["rotas"]:
        por_item.setdefault(str(entrada.get("item")), []).append(entrada)
    return por_item, []


def _varrer_entradas(ctx, rotulo: str, entradas: list[dict]) -> list[str]:  # noqa: ANN001
    """O oraculo sobre o corpo, os cabecalhos e a nota de cada resposta."""
    achados: list[str] = []
    for entrada in entradas:
        fugas = ctx.oraculo.varrer_tudo(
            {
                "corpo": entrada.get("corpo", ""),
                "cabecalhos": entrada.get("cabecalhos", {}),
                "erro": entrada.get("nota", ""),
            }
        )
        achados.extend(f"{rotulo}: {fuga}" for fuga in fugas)
    return achados


def _caso_ts(
    grupo: str,
    itens: tuple[str, ...],
    com_idor: bool,
    aceitaveis: tuple[int, ...] = RECUSAS_ACEITAVEIS,
    aceitaveis_por_item: dict[str, tuple[int, ...]] | None = None,
    afirmacoes: Callable[[str, list[dict]], list[str]] | None = None,
):
    """Fabrica o `fn` de um grupo de rotas de TypeScript.

    `aceitaveis_por_item` sobrepoe o `aceitaveis` **so** para os itens que
    nomeia, e existe porque um grupo pode cobrir superficies cujas respostas
    legitimas nao sao as mesmas: as nove do COM incluem um `/metrics` que
    responde 200 e um `ALL /internal/*` que responde 503. Alargar o
    `RECUSAS_ACEITAVEIS` global para acomodar o 200 enfraquecia os outros casos
    — era deixar de apanhar precisamente a falha que esta bateria existe para
    apanhar.

    `afirmacoes` e `fn(item, entradas) -> list[str]`, para as medicoes que um
    grupo escreve na `nota` de cada entrada e que o oraculo nao ve. Recebe as
    entradas **executadas** de um item; e um parametro e nao um segundo caso
    porque o condutor corre uma vez por grupo.
    """
    por_item_aceitaveis = dict(aceitaveis_por_item or {})

    def correr(ctx) -> list[str]:  # noqa: ANN001
        por_item, achados = _relatorio_ts(ctx, grupo)
        if achados:
            return achados
        for item in itens:
            entradas = por_item.get(item, [])
            if not entradas:
                achados.append(
                    f"{item}: o condutor de node nao a executou. Uma rota "
                    "enumerada que o condutor nao conhece e uma rota sem caso, "
                    "por outras palavras."
                )
                continue
            if not all(entrada.get("executado") for entrada in entradas):
                achados.append(
                    f"{item}: o condutor marcou-a como nao executada "
                    f"({entradas[0].get('nota', 'sem nota')})."
                )
                continue
            achados.extend(_varrer_entradas(ctx, item, entradas))
            if afirmacoes is not None:
                achados.extend(afirmacoes(item, entradas))
            if com_idor:
                achados.extend(
                    _uniformidade(
                        item,
                        [int(e.get("estado", -1)) for e in entradas],
                        por_item_aceitaveis.get(item, aceitaveis),
                    )
                )
            else:
                # Numa sonda nao ha o que ser uniforme: o que ha a provar e que
                # ela responde (uma rota que nao responde nao foi atacada) e que
                # nada de B atravessa.
                estados = {int(entrada.get("estado", -1)) for entrada in entradas}
                if estados - {200}:
                    achados.append(
                        f"{item}: a sonda respondeu {sorted(estados)} e nao 200. "
                        "O caso nao mediu o que queria medir."
                    )
        return achados

    return correr


# ------------------------------------------------------------------ registo

registar_caso(
    id="X-01/agr/rotas-internas",
    bateria="X-01",
    camada="rotas",
    enumeravel=ROTAS_INTERNAS_DO_AGR,
    fn=_conduzir_agr,
    precisa="agr",
    origens=("corpo", "cabecalhos", "logs"),
)

registar_caso(
    id="X-01/agr/sonda",
    bateria="X-01",
    camada="rotas",
    enumeravel=SONDA_DO_AGR,
    fn=_conduzir_sonda_do_agr,
    precisa="agr",
    origens=("corpo", "cabecalhos"),
)

registar_caso(
    id="X-01/agr/metricas",
    bateria="X-01",
    camada="rotas",
    enumeravel=METRICAS_DO_AGR,
    fn=_conduzir_metricas_do_agr,
    precisa="agr",
    origens=("corpo", "cabecalhos"),
)

registar_caso(
    id="X-01/ts/sondas",
    bateria="X-01",
    camada="rotas",
    enumeravel=SONDAS_TS,
    fn=_caso_ts("sondas", SONDAS_TS, com_idor=False),
    precisa="node",
    origens=("corpo", "cabecalhos"),
)

registar_caso(
    id="X-01/ts/webhook",
    bateria="X-01",
    camada="rotas",
    enumeravel=WEBHOOK_DO_GWY,
    fn=_caso_ts("webhook", WEBHOOK_DO_GWY, com_idor=True),
    precisa="node",
    origens=("corpo", "cabecalhos", "erro"),
)

#: O `502` da `POST /internal/channels`, e porque e que ele entra **so neste caso**.
#:
#: Medido: com os identificadores de B no corpo, a rota responde `502` uniforme
#: nas quatro tentativas, com `{"error":"onboarding falhou"}`. O 502 vem de o
#: condutor dar ao `Onboarding` duplos de `graph` e de `cofre` que **levantam**
#: em todos os metodos: o condutor nao fala com a Meta, e nao deve.
#:
#: O que isso quer dizer, dito por inteiro: o ataque **chega a rota**, a rota
#: abre a transaccao com o contexto de A, e recusa — e o oraculo confirma que
#: nada de B saiu no corpo, nos cabecalhos nem na nota. O que **nao** se mede
#: aqui e o `409` que o criterio 4 do KAM-016 promete para um numero ja ligado a
#: outro tenant: para chegar la, a troca com a Meta tem de ter sucesso, e isso
#: pede o simulador (`tools/meta-sim`, KAM-024). Fica dito em vez de ficar por
#: dizer, e esta na caixa do criterio 3 do bloco como **parcial**, com o credor.
ESTADOS_DOS_CANAIS = (*RECUSAS_ACEITAVEIS, 502)

registar_caso(
    id="X-01/ts/canais",
    bateria="X-01",
    camada="rotas",
    enumeravel=CANAIS_DO_GWY,
    fn=_caso_ts("canais", CANAIS_DO_GWY, com_idor=True, aceitaveis=ESTADOS_DOS_CANAIS),
    precisa="node",
    origens=("corpo", "cabecalhos", "erro"),
)


# ------------------------------------------------- a API interna do COM
#
# As nove superficies que o KAM-178 acrescentou ao COM. A propriedade medida
# **nao** e «a RLS filtra» — com um duplo da porta nao ha base de dados —, e
# esta:
#
#     o `ctx` que a porta recebe tem o tenant do cabecalho `x-kamba-tenant` e
#     mais nada
#
# O `ctxDoPedido` de `services/com/src/api/interna.ts` le o tenant **so** do
# cabecalho; o `actor` e o `trace_id` vem do corpo, e nenhum tenant vem de la.
# Por isso cada uma das sete rotas `POST /internal/*` leva tres ataques com a
# credencial certa e `x-kamba-tenant: <A>`: um corpo valido de A com campos
# extra que nomeiam B (`tenant_id`, `tenant`, `merchant_id` e o canario de B num
# campo livre), um corpo cujos identificadores de dominio sao de B, e os dois
# juntos. O condutor registra o `ctx` de cada chamada que chegou ao duplo da
# porta e escreve o veredicto na `nota` da entrada; este caso le-o.
#
# ## A sonda positiva, e as duas portas do *fail-closed*
#
# «Zero canarios de B» e verde quando nada chega ao sitio. O condutor prova, no
# mesmo relatorio, que o caminho esta vivo — a porta foi chamada com o `ctx` de
# A, devolveu um valor com o canario de **A**, e esse canario chegou a resposta —
# e que as duas portas do modulo disparam: sem credencial, 401; com credencial e
# sem `x-kamba-tenant`, 400. As tres medicoes vem em marcas na `nota`, e as tres
# sao exigidas aqui: uma afirmacao nao medida nao e um verde.


#: As sete rotas `POST /internal/*`, pela ordem da constante `ROTAS` do COM.
ROTAS_POST_DA_API_INTERNA_DO_COM = (
    "rota:com:api/interna:apiInterna:POST:/internal/offer-view",
    "rota:com:api/interna:apiInterna:POST:/internal/propose-cart",
    "rota:com:api/interna:apiInterna:POST:/internal/create-order",
    "rota:com:api/interna:apiInterna:POST:/internal/get-order",
    "rota:com:api/interna:apiInterna:POST:/internal/list-orders",
    "rota:com:api/interna:apiInterna:POST:/internal/transition",
    "rota:com:api/interna:apiInterna:POST:/internal/request-owner-confirmation",
)

#: O `GET /metrics` do COM. Sem credencial e sem identificadores (§3.39).
ITEM_DAS_METRICAS_DO_COM = "rota:com:api/interna:rotaDasMetricas:GET:/metrics"

#: O `ALL /internal/*` da app construida **sem** a API montada.
ITEM_SEM_API_DO_COM = "rota:com:app:createApp:ALL:/internal/*"

#: As nove, que e o que o caso cobre. Literais pela razao do topo do modulo: um
#: filtro fazia uma oitava rota nascer coberta.
ROTAS_DA_API_INTERNA_DO_COM = (
    *ROTAS_POST_DA_API_INTERNA_DO_COM,
    ITEM_DAS_METRICAS_DO_COM,
    ITEM_SEM_API_DO_COM,
)

#: Os estados aceitaveis que **nao** sao os do `RECUSAS_ACEITAVEIS`, item a item
#: e com a razao escrita:
#:
#:   200  o `GET /metrics`. Serve a exposicao Prometheus, e servi-la e o que ela
#:        faz. Nao e uma resposta sobre o recurso de ninguem — nao recebe
#:        identificador nenhum —, e a afirmacao sobre ela e outra: o corpo nao
#:        leva canario, nao leva `tenant_id` e nao leva rotulo por tenant
#:        (`OBS-I`). Um 4xx aqui era a rota em baixo, e o caso ficava verde por
#:        nao ter medido nada.
#:   503  o `ALL /internal/*` da app sem `api`. O `services/com/src/app.ts`
#:        escolhe-o de proposito em vez de 404: um 404 dizia a quem chama «essa
#:        rota nao existe», e ela existe — so nao esta montada, que e um defeito
#:        de arranque e nao um pedido errado. E *fail-closed* (nenhuma operacao
#:        corre) e nao distingue tenants, e e isso que as tres tentativas medem.
#:
#: **O `RECUSAS_ACEITAVEIS` global nao se alarga para acomodar o 200**: era
#: deixar de apanhar, em todos os outros casos, precisamente a falha que esta
#: bateria existe para apanhar.
ACEITAVEIS_DA_API_INTERNA_DO_COM: dict[str, tuple[int, ...]] = {
    ITEM_DAS_METRICAS_DO_COM: (200,),
    ITEM_SEM_API_DO_COM: (503,),
}

#: Quantos ataques o criterio pede por rota, e que o condutor tem de ter feito.
ATAQUES_POR_ROTA_DO_COM = 3


def _marca(nota: object, chave: str) -> str | None:
    """O valor de `chave=...` na nota do condutor, ou `None` se nao vier.

    A `nota` deste grupo e uma lista de marcas separadas por espacos, e nao
    texto livre: e o canal por onde uma medicao feita em `node` — o `ctx` com
    que a porta foi chamada — chega ao lado que decide se ha achado. **Nunca
    leva um canario**, pelo mesmo motivo que a `EntradaDeRota` do condutor
    escreve na sua.
    """
    prefixo = f"{chave}="
    for pedaco in str(nota or "").split():
        if pedaco.startswith(prefixo):
            return pedaco[len(prefixo) :]
    return None


def _exigir_marca(
    item: str, entradas: list[dict], chave: str, esperado: str, porque: str
) -> list[str]:
    """Um achado por `(item, chave)` quando alguma entrada nao traz `esperado`."""
    valores = [_marca(entrada.get("nota"), chave) for entrada in entradas]
    maus = sorted(
        {"(em falta)" if valor is None else valor for valor in valores}
        - {esperado}
    )
    if not maus:
        return []
    return [f"{item}: `{chave}` saiu {maus} e nao {[esperado]}. {porque}"]


def _contar_ataques(item: str, entradas: list[dict]) -> list[str]:
    if len(entradas) == ATAQUES_POR_ROTA_DO_COM:
        return []
    return [
        f"{item}: o condutor deixou {len(entradas)} entrada(s) e o criterio pede "
        f"{ATAQUES_POR_ROTA_DO_COM} ataques (corpo de A com campos de B, "
        "identificadores de dominio de B, e os dois juntos). Um ataque que nao "
        "se fez e um ataque que nao mediu, e a uniformidade de dois estados diz "
        "menos do que a de tres."
    ]


def _afirmacoes_da_api_interna_do_com(item: str, entradas: list[dict]) -> list[str]:
    """As medicoes que vem na `nota` do condutor, e que o oraculo nao ve.

    O oraculo diz se algo de B saiu. Estas dizem se o caso mediu o que diz medir:
    o `ctx` com que a porta foi chamada, a sonda positiva, e as duas portas do
    *fail-closed*.
    """
    if item == ITEM_DAS_METRICAS_DO_COM:
        return [
            *_exigir_marca(
                item,
                entradas,
                "metricas",
                "limpa",
                "A exposicao do COM tem de sair sem rotulo por tenant e sem o "
                "`tenant_id` de A no corpo (`OBS-I`): as duas series sao "
                "contagens por filtro, e `rotulo-por-tenant` quer dizer que "
                "alguem lhes acrescentou uma etiqueta com identificador.",
            ),
            *_exigir_marca(
                item,
                entradas,
                "series",
                "com-valor",
                "A serie `com_repo_consultas_total{filtro=\"tenant\"}` saiu a "
                "zero ou nao saiu: a afirmacao de cima correu sobre uma "
                "populacao vazia, e sobre populacao vazia ela passa mesmo que a "
                "exposicao ganhe uma etiqueta por tenant. E o achado que a "
                "revisao adversarial do KAM-178 fez no teste desta rota.",
            ),
            *_exigir_marca(
                item,
                entradas,
                "contadores",
                "subidos",
                "O condutor nao conseguiu fazer subir os contadores pelo "
                "caminho real (`repoBase.noTenant`), pelo que nao se mediu que "
                "o que o repo-base conta e o que a rota serve.",
            ),
        ]

    if item == ITEM_SEM_API_DO_COM:
        return [
            *_contar_ataques(item, entradas),
            *_exigir_marca(
                item,
                entradas,
                "sem-api",
                "corpo-igual",
                "Os tres ataques a app sem `api` montada receberam corpos "
                "diferentes entre si. Um corpo que varie com o identificador "
                "que se manda distingue tenants, que e o oraculo de existencia "
                "que o criterio 3 proibe ao pedir recusas uniformes.",
            ),
        ]

    return [
        *_contar_ataques(item, entradas),
        *_exigir_marca(
            item,
            entradas,
            "ctx",
            "a",
            "**E a afirmacao central deste caso**: o duplo da porta tem de ter "
            "sido chamado, em cada ataque, com `ctx.tenantId` igual ao tenant do "
            "cabecalho `x-kamba-tenant`. `outro-tenant` quer dizer que um campo "
            "do corpo deslocou o `ctx`; `nenhuma-chamada` quer dizer que o "
            "ataque nao chegou a porta, e entao a afirmacao nao se mediu.",
        ),
        *_exigir_marca(
            item,
            entradas,
            "sonda",
            "viva",
            "A sonda positiva: com um corpo legitimo de A, a porta tem de ser "
            "chamada com o `ctx` de A, devolver um valor com o canario de A, e "
            "esse canario tem de chegar a resposta. Sem ela, «o canario de B nao "
            "saiu» e verde por a rota nunca ter chegado a porta.",
        ),
        *_exigir_marca(
            item,
            entradas,
            "fecho-sem-credencial",
            "401",
            "A primeira porta do *fail-closed*: sem `x-kamba-interno`, 401 sem "
            "corpo. Se nao disparou, os duplos estao mal montados e o resto do "
            "caso mede outra coisa que nao a rota.",
        ),
        *_exigir_marca(
            item,
            entradas,
            "fecho-sem-tenant",
            "400",
            "A segunda porta do *fail-closed*: com credencial e sem "
            "`x-kamba-tenant`, 400 `{\"error\":\"ctx\"}` e nenhuma operacao "
            "corre. Se nao disparou, o `ctx` nao vem do cabecalho — e e isso que "
            "este caso diz medir.",
        ),
        *_exigir_marca(
            item,
            entradas,
            "ids-de-b",
            "tenant-b",
            "O condutor usou um UUID substituto no `contact_id` em vez do "
            "identificador de B, porque o `KAMBA_X01_TENANT_B` nao tinha forma "
            "de UUID. O ataque fez-se, mas o identificador real de B nunca "
            "entrou nos campos de dominio: metade do que o caso diz medir ficou "
            "por medir.",
        ),
        *_exigir_marca(
            item,
            entradas,
            "canario-de-b",
            "presente",
            "O condutor nao recebeu `KAMBA_X01_CANARIOS`, pelo que os ataques "
            "levaram um substituto em vez do canario de B. «Nada de B saiu» "
            "ficava verde por B nunca ter entrado.",
        ),
    ]


registar_caso(
    id="X-01/ts/com-interna",
    bateria="X-01",
    camada="rotas",
    enumeravel=ROTAS_DA_API_INTERNA_DO_COM,
    fn=_caso_ts(
        "com-interna",
        ROTAS_DA_API_INTERNA_DO_COM,
        com_idor=True,
        aceitaveis_por_item=ACEITAVEIS_DA_API_INTERNA_DO_COM,
        afirmacoes=_afirmacoes_da_api_interna_do_com,
    ),
    precisa="node",
    origens=("corpo", "cabecalhos", "erro"),
)
