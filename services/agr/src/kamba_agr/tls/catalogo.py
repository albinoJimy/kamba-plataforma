"""O catalogo de tools do Piloto: as **onze** de `docs/tecnica/02` §6.2.

Os nomes, as classes e os botoes de confirmacao desta lista nao se decidem aqui:
sao canon desde a emenda **1.35** do dicionario (§3.26), que os transcreve do
§6.2 e escreve, por cada um, «as especificacoes sao do KAM-028 e do KAM-031; o
que entra aqui e o **nome**».

## Uma esta `ligada`, dez estao `declaradas`

| Tool | Vertical | `klass` | Estado | Credor |
|---|---|---|---|---|
| `search_catalog` | Vendedor | `read` | declarada | KAM-031 |
| `get_price_stock` | Vendedor | `read` | declarada | KAM-031 |
| `propose_cart` | Vendedor | `read` | declarada | KAM-031 |
| `criar_pedido` | Vendedor | **`money`** | declarada | KAM-031 |
| `get_order_status` | Vendedor | `read` | declarada | KAM-031 |
| `get_store_info` | ambas | `read` | **ligada** | — |
| `list_services` | Servicos | `read` | declarada | KAM-035 |
| `get_availability` | Servicos | `read` | declarada | KAM-035 |
| `book_slot` | Servicos | **`write`** | declarada | KAM-035 |
| `cancel_booking` | Servicos | `write` | declarada | KAM-035 |
| `reschedule_booking` | Servicos | `write` | declarada | KAM-035 |

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

#: As onze do §6.2, pela ordem em que esse documento as escreve. **As cinco do
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
    E o caso do `search_catalog`, cujo backend e o IDX: o `idx.candidatos` e o
    **KAM-061**, de fase 1, e nao existe na arvore. Liga-la a um `stand-in` era
    servir um catalogo que nao e o catalogo.

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
    return (*do_vendedor, *_AS_SEIS_QUE_NAO_SAO_DO_VENDEDOR)


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
