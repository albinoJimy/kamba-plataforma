"""X-01 — para cada rota, A usa identificadores de B e nao recebe nada de B.

Criterio 3 do KAM-066, primeira metade: «para cada rota, A usa IDs de B (IDOR)
e recebe 403/404 **uniformes** sem canario». A palavra que faz o criterio e
*uniformes*: um 404 numa rota e um 403 noutra, para o mesmo ataque, e um oraculo
de existencia — quem ataca aprende, pela diferenca, que o recurso de B existe.
Por isso cada caso afirma duas coisas distintas: que nada de B saiu, **e** que
as respostas a identificadores de B sao indistinguiveis entre si.

## As rotas desta arvore nao sao todas iguais, e o caso diz qual e qual

```text
7 rotas levam identificadores   o IDOR e possivel, e e o que se ataca
15 rotas sao sonda ou metricas  nao recebem identificador nenhum; o que se
                                prova e que a resposta nao leva canario nem
                                `tenant_id`, e que o oraculo morderia se levasse
```

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
* **As dezassete rotas de TypeScript** sao Hono, e uma aplicacao Hono responde
  em processo pelo `app.request()` (e a forma que os testes do GWY ja usam).
  O caso chama um **condutor** em `node` e le o relatorio JSON dele; corre em
  `db/tests_isolamento/`, porque a rota `POST /internal/channels` precisa de uma
  transaccao real contra a base do *gate*.

Nenhuma das duas metades e um servidor levantado: sao as aplicacoes em processo.
Isso nao e so velocidade — e o que torna o caso determinista e o que permite
afirmar que o duplo do executor **nao foi chamado**, que e a afirmacao mais
forte desta bateria.
"""

from __future__ import annotations

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
    if fora:
        achados.append(
            f"{rotulo}: identificadores de B produziram {fora}, que nao e uma "
            f"recusa ({aceitaveis}). Um 2xx a um identificador de outro "
            "tenant e a falha que esta bateria existe para apanhar."
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
):
    """Fabrica o `fn` de um grupo de rotas de TypeScript."""

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
            if com_idor:
                achados.extend(
                    _uniformidade(
                        item,
                        [int(e.get("estado", -1)) for e in entradas],
                        aceitaveis,
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
