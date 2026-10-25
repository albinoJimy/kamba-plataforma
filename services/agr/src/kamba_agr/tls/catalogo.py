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

from typing import Final

from . import get_store_info
from .especificacoes import Catalogo, EspecificacaoDeTool

#: O credor das cinco tools do Vendedor (grafo do Vendedor).
CREDOR_DO_VENDEDOR: Final = "KAM-031"

#: O credor das cinco tools de Servicos (grafo de Servicos).
CREDOR_DE_SERVICOS: Final = "KAM-035"

#: As onze do §6.2, pela ordem em que esse documento as escreve.
ESPECIFICACOES_DO_PILOTO: Final = (
    EspecificacaoDeTool(
        nome="search_catalog", klass="read", backend="idx", credor=CREDOR_DO_VENDEDOR
    ),
    EspecificacaoDeTool(
        nome="get_price_stock", klass="read", backend="com", credor=CREDOR_DO_VENDEDOR
    ),
    EspecificacaoDeTool(
        nome="propose_cart", klass="read", backend="com", credor=CREDOR_DO_VENDEDOR
    ),
    # `money`: o unico nome do catalogo em portugues, como o §6.2 o escreve. O
    # botao e `confirm:{cart_id}`, e o campo que ele cita entra com o modelo —
    # que e do KAM-031.
    EspecificacaoDeTool(
        nome="criar_pedido", klass="money", backend="com", credor=CREDOR_DO_VENDEDOR
    ),
    EspecificacaoDeTool(
        nome="get_order_status", klass="read", backend="com", credor=CREDOR_DO_VENDEDOR
    ),
    # A unica `ligada`. `backend="plataforma"`: le a `platform.tenants`, que e a
    # nossa base, e nao o COM.
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


def catalogo_do_piloto() -> Catalogo:
    """O catalogo que o arranque liga ao `AgentRegistry` (§5.2, validacao 1).

    E uma funcao e nao uma constante de modulo porque o `Catalogo` valida ao
    construir-se: uma constante punha essa validacao a correr no `import`, e um
    erro de especificacao rebentava antes de o `__main__` ter o log montado —
    com um *stack trace* de importacao em vez do codigo de saida que o
    dicionario §3.26 lhe da.
    """
    return Catalogo(ESPECIFICACOES_DO_PILOTO)
