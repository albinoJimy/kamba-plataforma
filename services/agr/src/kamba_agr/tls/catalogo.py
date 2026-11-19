"""O catalogo de tools do Piloto: as **onze** de `docs/tecnica/02` §6.2, e as
**quatro** do modulo `catalogo` do §21.3 (KAM-118).

Os nomes, as classes e os botoes de confirmacao desta lista nao se decidem aqui:
sao canon desde a emenda **1.35** do dicionario (§3.26), que os transcreve do
§6.2 e escreve, por cada um, «as especificacoes sao do KAM-028 e do KAM-031; o
que entra aqui e o **nome**».

## Uma esta `ligada`, dezasseis estao `declaradas`

| Tool | Vertical | `klass` | Estado | Credor |
|---|---|---|---|---|
| `search_catalog` | Vendedor | `read` | declarada | KAM-031 |
| `get_price_stock` | Vendedor | `read` | declarada | KAM-031 |
| `propose_cart` | Vendedor | `read` | declarada | KAM-031 |
| `criar_pedido` | Vendedor | **`money`** | declarada | KAM-031 |
| `get_order_status` | Vendedor | `read` | declarada | KAM-031 |
| `get_store_info` | todas | `read` | **ligada** | — |
| `list_services` | Servicos | `read` | declarada | KAM-035 |
| `get_availability` | Servicos | `read` | declarada | KAM-035 |
| `book_slot` | Servicos | **`write`** | declarada | KAM-035 |
| `cancel_booking` | Servicos | `write` | declarada | KAM-035 |
| `reschedule_booking` | Servicos | `write` | declarada | KAM-035 |
| `create_product_draft` | Dono | **`write`** | declarada | KAM-119 |
| `ask_missing_fields` | Dono | `read` | declarada | KAM-119 |
| `publish_product` | Dono | **`write`** | declarada | KAM-119 |
| `get_catalog_status` | Dono | `read` | declarada | KAM-119 |
| `request_quote` | Vendedor | **`write`** | ligada com executor (KAM-220) | — |
| `submit_quote` | Dono | **`write`** | ligada com executor (KAM-220) | — |

## As quatro do dono entram declaradas, e e o que o KAM-118 pode fazer

O `registry/dono.yaml` lista-as, e a validacao (1) do §5.2 recusa uma tool que
nao esteja aqui: sem estas quatro linhas a persona do dono nao arrancava. O
nome e a classe sao do §21.3 (`publish_product` e escrita **com confirmacao**);
o modelo de argumentos, o executor e o campo que o botao `confirm:{…}` cita
sao do **KAM-119**, que escreve o modulo — uma entrada declarada nao pode dizer
que campo o botao cita, porque o campo e do modelo. Ate la o `invoke` recusa-as
com `TOOL_NOT_ALLOWED`, a todos, e o `for_context` nao as mostra ao modelo.

O `backend` e `plataforma` (*proposta*): o catalogo minimo do KAM-094 vive em
`platform.catalog_ingestions`, na nossa base. Quem o confirma contra o executor
real e o KAM-119.

A `especificacoes.py` explica porque e que os dois estados existem e porque e
que e isso que deixa a validacao (1) do §5.2 passar de `aviso` a `bloqueio`
neste ticket. O que aqui importa e o que a tabela mostra: as onze existem, uma
responde, e cada uma das dez diz quem a liga.

## O `backend` de uma entrada declarada ja esta decidido, e nao e adivinhacao

O `backend` e a unidade do *disjuntor* (§6.5) e nao depende do modelo de
argumentos: o §6.2 diz, por cada tool, com quem ela fala — o `search_catalog`
com o IDX, o `criar_pedido` com o COM **e** o PAY, as de marcacao com o COM. Nos
casos de dois, declara-se o backend que o §6.2 nomeia primeiro para o efeito que
a tool tem: o `criar_pedido` reserva stock (COM) e so depois cobra (PAY), e um
disjuntor que abrisse pelo PAY deixava passar reservas que ninguem ia poder
pagar. Quem confirmar isto contra o codigo real e o KAM-031.

## O que **nao** esta aqui, e e critero

Nao existe tool de envio de mensagem: «o unico caminho para o cliente e o no
`send` → Outbound» (§6.2). E nao existe, nas verticais voltadas ao cliente, tool
que altere preco, stock ou estado de pagamento — o `criar_pedido` **reserva**
stock e cria uma cobranca, e o estado de pagamento muda so por evento
autenticado (ADR-013). Ha um teste que enumera este catalogo contra
`registry/*.yaml` e prova as duas ausencias; e nao e um teste de leitura, e uma
enumeracao, porque a ausencia de uma coisa nao se vê a ler a lista do que ha.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from . import get_store_info
from . import orcamento_tools
from . import vendedor
from .especificacoes import Catalogo, EspecificacaoDeTool, Executor

#: O credor das cinco tools do Vendedor. **Era `KAM-031` e passou a ser o ticket
#: que liga cada backend** (`tls/vendedor.py`, `CREDORES`), e a correccao e do
#: proprio KAM-031: o credor de uma entrada `declarada` e «o ticket que a liga»,
#: e os Detalhes Tecnicos do bloco dizem por extenso que «a ligacao real a
#: COM/IDX e por KAM-043, KAM-046 e KAM-061». O KAM-031 escreve os modelos e os
#: executores de ensaio; ligar o COM e o IDX nao esta no alcance dele. Deixar o
#: nome antigo depois deste ticket fundir era deixar cinco entradas a nomear um
#: ticket fechado — e a regra da casa e que «um atalho sem o ticket que o fecha
#: nao e atalho».

#: O credor das cinco tools de Servicos (grafo de Servicos).
CREDOR_DE_SERVICOS: Final = "KAM-035"

#: As seis que nao sao do Vendedor: a unica `ligada` do KAM-028 e as cinco de
#: Servicos. Separadas porque sao as que o `especificacoes_do_piloto` nao mexe.
_AS_SEIS_QUE_NAO_SAO_DO_VENDEDOR: Final = (
    # A `get_store_info`. `backend="plataforma"`: le a `platform.tenants`, que e
    # a nossa base, e nao o COM.
    EspecificacaoDeTool(
        nome="get_store_info",
        klass="read",
        backend="plataforma",
        modelo=get_store_info.ArgumentosDeGetStoreInfo,
        executor=get_store_info.executar,
    ),
    EspecificacaoDeTool(
        nome="list_services", klass="read", backend="com", credor=CREDOR_DE_SERVICOS
    ),
    EspecificacaoDeTool(
        nome="get_availability", klass="read", backend="com", credor=CREDOR_DE_SERVICOS
    ),
    EspecificacaoDeTool(
        nome="book_slot", klass="write", backend="com", credor=CREDOR_DE_SERVICOS
    ),
    EspecificacaoDeTool(
        nome="cancel_booking", klass="write", backend="com", credor=CREDOR_DE_SERVICOS
    ),
    EspecificacaoDeTool(
        nome="reschedule_booking",
        klass="write",
        backend="com",
        credor=CREDOR_DE_SERVICOS,
    ),
)

#: O credor das quatro tools do modulo `catalogo` do §21.3: o ticket que as liga.
CREDOR_DO_DONO: Final = "KAM-119"

#: As quatro do Assistente do Dono, `declaradas` (KAM-118). Ver o cabecalho.
#: O modulo que fecha as quatro no passo 2 (decisao do fundador de 2026-11-18):
#: o dono de um tenant sem `catalogo` e atendido, e estas recusam pelo entitlement.
MODULO_DO_DONO: Final = "catalogo"

_AS_QUATRO_DO_DONO: Final = (
    EspecificacaoDeTool(
        nome="create_product_draft",
        klass="write",
        backend="plataforma",
        credor=CREDOR_DO_DONO,
        modulo=MODULO_DO_DONO,
    ),
    EspecificacaoDeTool(
        nome="ask_missing_fields",
        klass="read",
        backend="plataforma",
        credor=CREDOR_DO_DONO,
        modulo=MODULO_DO_DONO,
    ),
    EspecificacaoDeTool(
        nome="publish_product",
        klass="write",
        backend="plataforma",
        credor=CREDOR_DO_DONO,
        modulo=MODULO_DO_DONO,
    ),
    EspecificacaoDeTool(
        nome="get_catalog_status",
        klass="read",
        backend="plataforma",
        credor=CREDOR_DO_DONO,
        modulo=MODULO_DO_DONO,
    ),
)

#: O credor das duas tools do modulo `orcamento` do §21.3: o ticket que as liga
#: ao grafo (KAM-123 escreve o dominio e o envio pelo botao; ver o bloco).
CREDOR_DO_ORCAMENTO: Final = "KAM-220"

#: O modulo que as fecha no passo 2: um tenant sem `orcamento` nao pede nem
#: responde orcamentos.
MODULO_DO_ORCAMENTO: Final = "orcamento"

#: As duas do Orcamento expresso, `declaradas` (KAM-123). **A terceira do
#: §21.3, o `send_quote`, nao e tool**, e a ausencia e o desenho: o §6.2 manda
#: que nenhuma tool envie («o unico caminho para o cliente e o no `send` ->
#: Outbound»), e o envio de uma proposta e o botao `confirm:{action_id}` do
#: portao do KAM-118, que o no `confirm` do dono executa fora do modelo
#: (`orcamento/porta.py`). Uma `send_quote` que o modelo pudesse chamar era
#: uma tool de envio, e o `test_nao_existe_tool_de_envio_de_mensagem` recusa-a.
_AS_DUAS_DO_ORCAMENTO: Final = (
    EspecificacaoDeTool(
        nome="request_quote",
        klass="write",
        backend="plataforma",
        credor=CREDOR_DO_ORCAMENTO,
        modulo=MODULO_DO_ORCAMENTO,
    ),
    EspecificacaoDeTool(
        nome="submit_quote",
        klass="write",
        backend="plataforma",
        credor=CREDOR_DO_ORCAMENTO,
        modulo=MODULO_DO_ORCAMENTO,
    ),
)

#: As onze do §6.2, pela ordem em que esse documento as escreve, e as quatro do
#: §21.3 no fim, e as duas do orcamento (KAM-123) depois delas. **As cinco do
#: Vendedor `declaradas`**, que e o estado sem os executores do KAM-178 — e e o
#: que a bateria do registo compara contra o `registry/*.yaml`.
ESPECIFICACOES_DO_PILOTO: Final = (
    # As cinco do Vendedor, `declaradas`. **Derivam-se das tabelas do
    # `vendedor.py`** em vez de se reescreverem uma a uma: a `klass`, o `backend`
    # e o credor de cada uma tem um dono so, e escrever a lista duas vezes era a
    # divergencia que o `CREDORES` daquele ficheiro ja fechou uma vez.
    *(
        EspecificacaoDeTool(
            nome=nome,
            klass=vendedor.CLASSES[nome],
            backend=vendedor.BACKENDS[nome],
            credor=vendedor.CREDORES[nome],
        )
        for nome in vendedor.MODELOS
    ),
    *_AS_SEIS_QUE_NAO_SAO_DO_VENDEDOR,
    *_AS_QUATRO_DO_DONO,
    *_AS_DUAS_DO_ORCAMENTO,
)

#: A razao da dispensa do passo 4 do `submit_quote` (decisao do fundador de
#: 2026-11-19, KAM-220, opcao C). Fica na especificacao, e nao so aqui, porque e
#: a especificacao que a `especificacoes.py` confere.
RAZAO_DA_DISPENSA_DO_SUBMIT: Final = (
    "so grava a resposta do dono e propoe o botao confirm:{action_id} da "
    "owner_actions; o envio ao cliente continua a exigir esse botao"
)


def _do_orcamento(ligaveis: Mapping[str, Executor]) -> tuple[EspecificacaoDeTool, ...]:
    """As duas do orcamento: **ligadas** com o executor, declaradas sem ele (KAM-220).

    * `request_quote` cita o `sku` no botao `confirm:{sku}` que o cliente toca
      («Pedir orcamento»): o toque e a confirmacao do passo 4 **e** o
      consentimento para gastar um `orcamentos_mes` (opcao C do fundador);
    * `submit_quote` tem a dispensa do passo 4, com a razao escrita.

    As duas ligam-se juntas ou nenhuma: um executor so de uma era um catalogo
    meio ligado, e o grafo do dono pedia uma resposta que nada podia enviar.
    """
    pedir = ligaveis.get("request_quote")
    responder = ligaveis.get("submit_quote")
    if pedir is None and responder is None:
        return _AS_DUAS_DO_ORCAMENTO
    if pedir is None or responder is None:
        raise ValueError("as duas tools do orcamento ligam-se juntas, ou nenhuma")
    return (
        EspecificacaoDeTool(
            nome="request_quote",
            klass="write",
            backend="plataforma",
            modelo=orcamento_tools.ArgumentosDeRequestQuote,
            executor=pedir,
            campo_de_confirmacao="sku",
            modulo=MODULO_DO_ORCAMENTO,
        ),
        EspecificacaoDeTool(
            nome="submit_quote",
            klass="write",
            backend="plataforma",
            modelo=orcamento_tools.ArgumentosDeSubmitQuote,
            executor=responder,
            confirmacao_dispensada=RAZAO_DA_DISPENSA_DO_SUBMIT,
            modulo=MODULO_DO_ORCAMENTO,
        ),
    )


def especificacoes_do_piloto(
    executores: Mapping[str, Executor] | None = None,
) -> tuple[EspecificacaoDeTool, ...]:
    """As onze, com as do Vendedor **ligadas** onde houver executor (KAM-178).

    Uma entrada do Vendedor passa de `declarada` a `ligada` quando o chamador
    traz o executor dela, e so entao: o modelo de argumentos e do KAM-031 e esta
    sempre aqui, mas uma especificacao com modelo e sem executor **nao e
    construivel** (o invariante do `EspecificacaoDeTool`) — e um catalogo meio
    ligado era pior do que nenhum, porque a tool aparecia ao modelo e recusava.

    **As que nao tem executor ficam `declaradas`, com o credor que ja tinham.**
    Era o caso do `search_catalog` ate ao **KAM-061**, que o liga ao IDX em
    `tls/idx.py`: o `__main__` passa-lhe esse executor, e uma chamada sem ele
    continua a devolve-lo `declarado`. Liga-lo a um `stand-in` era servir um
    catalogo que nao e o catalogo.

    Chamar isto **sem** executores devolve as onze como o KAM-031 as deixou, que
    e o que a bateria do registo compara.
    """
    ligaveis = dict(executores or {})
    do_vendedor = []
    for nome, modelo in vendedor.MODELOS.items():
        executor = ligaveis.get(nome)
        if executor is None:
            do_vendedor.append(
                EspecificacaoDeTool(
                    nome=nome,
                    klass=vendedor.CLASSES[nome],
                    backend=vendedor.BACKENDS[nome],
                    credor=vendedor.CREDORES[nome],
                )
            )
            continue
        do_vendedor.append(
            EspecificacaoDeTool(
                nome=nome,
                klass=vendedor.CLASSES[nome],
                backend=vendedor.BACKENDS[nome],
                modelo=modelo,
                executor=executor,
                # O botao `confirm:{cart_id}` cita o `cart_id`, e so a tool
                # `money` o exige — uma `read` que pedisse botao punha o runtime
                # a pedir confirmacao para responder ao horario da loja.
                campo_de_confirmacao=(
                    "cart_id" if nome == "criar_pedido" else None
                ),
            )
        )
    # A ordem e a do §6.2: as cinco do Vendedor, a `get_store_info`, as cinco de
    # Servicos. **Reconstroi-se em vez de se filtrar o `ESPECIFICACOES_DO_PILOTO`**
    # porque uma entrada `ligada` e uma `declarada` sao objectos diferentes, e
    # filtrar uma tupla fixa dava duas listas a manter em sincronia.
    return (
        *do_vendedor,
        *_AS_SEIS_QUE_NAO_SAO_DO_VENDEDOR,
        *_AS_QUATRO_DO_DONO,
        *_do_orcamento(ligaveis),
    )


def catalogo_do_piloto(
    executores: Mapping[str, Executor] | None = None,
) -> Catalogo:
    """O catalogo que o arranque liga ao `AgentRegistry` (§5.2, validacao 1).

    E uma funcao e nao uma constante de modulo porque o `Catalogo` valida ao
    construir-se: uma constante punha essa validacao a correr no `import`, e um
    erro de especificacao rebentava antes de o `__main__` ter o log montado —
    com um *stack trace* de importacao em vez do codigo de saida que o
    dicionario §3.26 lhe da.

    Os `executores` sao os do KAM-178 (`tls/com.py`); sem eles o catalogo e o que
    o KAM-031 deixou, e o `log` de arranque di-lo (`ligadas_N_de_11`).
    """
    return Catalogo(especificacoes_do_piloto(executores))
