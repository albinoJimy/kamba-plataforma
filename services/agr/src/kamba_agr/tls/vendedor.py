"""Os argumentos das cinco tools do Vendedor (§6.2), e so os argumentos.

## Porque e que os modelos estao aqui e os executores nao

O §6.2 fixa as cinco tools do Vendedor e o `registry/vendedor.yaml` fixa a lista
fechada que a ToolLayer aceita. O que falta para elas serem `ligadas` sao duas
coisas: o **modelo** dos argumentos — que e contrato, nasce do canon e nao muda
quando o backend chegar — e o **executor**, que fala com o COM e com o IDX e que
nao existe (KAM-043, KAM-044, KAM-046, KAM-061).

Entregar as cinco `ligadas` com executores de ensaio punha o
`catalogo_do_piloto()` a servir precos inventados a quem o chamasse em producao,
e o `invoke` nao tem como distinguir um executor de ensaio de um real: dava um
`ToolResult` `ok` com *facts* que nenhuma loja tem, e o validador de citacao
**aceitava-os** — sao *facts* de uma tool, que e exactamente o que ele exige.
Seria abrir no sitio mais caro o buraco que o ADR-007 existe para fechar.

Por isso: os modelos aqui, as cinco entradas do catalogo continuam `declaradas`
com o credor que **liga o backend**, e os executores de ensaio vivem no pacote da
vertical (`verticais/vendedor/fakes.py`), de onde nenhum arranque os importa.
O `especificacoes_do_vendedor()` deste modulo e quem junta os dois, e quem o
chama e a bateria.

## O `qty` e inteiro >= 1, e o `sku` nao e validado por forma

Um `qty` zero ou negativo nao e um pedido: e um argumento que o modelo inventou,
e o passo 3 do `invoke` recusa-o antes de o backend o ver. O `sku`, pelo
contrario, **nao leva padrao**: o `05` §6.3 nao fixa a forma de um `sku` e o
KAM-046 ainda nao a fixou; um padrao adivinhado aqui recusava um catalogo real
no dia em que ele chegasse. Quem valida a existencia do `sku` e o backend, com
`NOT_FOUND`.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from .especificacoes import EspecificacaoDeTool, Executor

#: Os creditos por tool, e **sao quatro tickets e nao tres**. Os Detalhes
#: Tecnicos do bloco do KAM-031 escrevem «a ligacao real a COM/IDX e por KAM-043,
#: KAM-046 e KAM-061», e o `get_order_status` nao cabe em nenhum dos tres: quem
#: cria a maquina de estados das encomendas e o `orders_mirror` que ele le e o
#: **KAM-044**, que e tambem dependencia do KAM-046. Fica dito aqui para que o
#: credor nomeie quem pode pagar.
CREDOR_DO_CATALOGO: Final = "KAM-061"
CREDOR_DO_PRECO: Final = "KAM-043"
CREDOR_DO_CARRINHO: Final = "KAM-046"
CREDOR_DAS_ENCOMENDAS: Final = "KAM-044"


class ArgumentosDeSearchCatalog(BaseModel):
    """`search_catalog(query, filtros)` — §6.2, primeira linha.

    Os `filtros` sao um mapa aberto de propósito: o §6.2 nao os enumera e o
    `05` §6.3 e quem os fixara. **Aberto nos valores, nao nas chaves do pedido**
    — o `extra="forbid"` continua a recusar um argumento de topo inventado, que e
    o que o passo 3 existe para apanhar.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=256)
    filtros: dict[str, str] = Field(default_factory=dict)


class ArgumentosDeGetPriceStock(BaseModel):
    """`get_price_stock(skus[])` — devolve *facts* `price` e `stock`."""

    model_config = ConfigDict(extra="forbid")

    skus: tuple[str, ...] = Field(min_length=1, max_length=20)


class ItemDoCarrinho(BaseModel):
    """Uma linha do `propose_cart`."""

    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(ge=1, le=99)


class ArgumentosDeProposeCart(BaseModel):
    """`propose_cart(items[])` — calcula o total no backend e devolve `cart_id`."""

    model_config = ConfigDict(extra="forbid")

    items: tuple[ItemDoCarrinho, ...] = Field(min_length=1, max_length=20)


class ArgumentosDeCriarPedido(BaseModel):
    """`criar_pedido(cart_id)` — classe `money`, botao `confirm:{cart_id}`.

    E o **unico** nome do catalogo em portugues, como o §6.2 o escreve.
    """

    model_config = ConfigDict(extra="forbid")

    cart_id: str = Field(min_length=1, max_length=64)


class ArgumentosDeGetOrderStatus(BaseModel):
    """`get_order_status(order_id)` — ambito tenant **e** contacto (§6.2)."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=64)


#: O modelo de cada tool do Vendedor, pelo nome canonico.
MODELOS: Final = {
    "search_catalog": ArgumentosDeSearchCatalog,
    "get_price_stock": ArgumentosDeGetPriceStock,
    "propose_cart": ArgumentosDeProposeCart,
    "criar_pedido": ArgumentosDeCriarPedido,
    "get_order_status": ArgumentosDeGetOrderStatus,
}

#: O backend de cada uma (§6.2), que e a unidade do disjuntor (§6.5).
BACKENDS: Final = {
    "search_catalog": "idx",
    "get_price_stock": "com",
    "propose_cart": "com",
    "criar_pedido": "com",
    "get_order_status": "com",
}

#: A classe de cada uma. So o `criar_pedido` e `money`.
CLASSES: Final = {
    "search_catalog": "read",
    "get_price_stock": "read",
    "propose_cart": "read",
    "criar_pedido": "money",
    "get_order_status": "read",
}

#: O credor de cada entrada `declarada`.
CREDORES: Final = {
    "search_catalog": CREDOR_DO_CATALOGO,
    "get_price_stock": CREDOR_DO_PRECO,
    "propose_cart": CREDOR_DO_CARRINHO,
    "criar_pedido": CREDOR_DO_CARRINHO,
    "get_order_status": CREDOR_DAS_ENCOMENDAS,
}


def especificacoes_do_vendedor(
    executores: dict[str, Executor],
) -> tuple[EspecificacaoDeTool, ...]:
    """As cinco `ligadas`, com os executores que quem chama fornecer.

    Levanta se faltar um executor: uma especificacao com modelo e sem executor
    nao e construivel (o invariante do `EspecificacaoDeTool`), e um catalogo
    meio ligado era pior do que nenhum — a tool aparecia ao modelo e recusava.
    """
    faltam = sorted(set(MODELOS) - set(executores))
    if faltam:
        raise KeyError(f"sem executor para {faltam}")
    return tuple(
        EspecificacaoDeTool(
            nome=nome,
            klass=CLASSES[nome],
            backend=BACKENDS[nome],
            modelo=modelo,
            executor=executores[nome],
            campo_de_confirmacao="cart_id" if nome == "criar_pedido" else None,
        )
        for nome, modelo in MODELOS.items()
    )
