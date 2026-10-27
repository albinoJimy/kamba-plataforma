"""Os backends de ensaio das cinco tools do Vendedor — *fakes* por contrato.

## Onde isto corre, e onde nao corre

Corre na bateria e no *smoke* do *golden*. **Nao corre em producao, e nenhum
arranque importa este modulo**: o `catalogo_do_piloto()` mantem as cinco entradas
`declaradas` com o credor que liga cada backend (KAM-043, KAM-044, KAM-046,
KAM-061), e a razao esta escrita em `tls/vendedor.py` — um executor de ensaio
registado no catalogo de producao devolvia um `ToolResult` `ok` com *facts* que
nenhuma loja tem, e o validador de citacao **aceita-os**, porque sao *facts* de
uma tool. Era abrir no sitio mais caro o buraco que o ADR-007 fecha.

## «Por contrato» quer dizer o que

Cada *fake* satisfaz o contrato que o backend real tera de satisfazer, e nao
menos:

* **devolve *facts*** com `fact_id` **opaco** — nao derivado do argumento nem do
  valor (KAM-028: um `fact_id` derivado de texto do cliente poe texto do cliente
  na `tool_audit`);
* **e idempotente pela chave** no `criar_pedido`: o §6.3 ponto (iii) diz que
  «mesmo que ambos corram em concorrencia, a chave devolve o resultado
  guardado», e e o que torna o criterio 3 do bloco mensuravel sem base de dados.
  Quem o serializa em producao e o `INSERT … ON CONFLICT DO NOTHING` da
  `tool_idempotency` (KAM-029); aqui e um `dict`, e o limite esta escrito na
  seccao de verificacao do bloco;
* **respeita o ambito de dados** do §6.2: o `get_order_status` so ve encomendas
  **do proprio contacto**, e nao so do proprio tenant. E a metade do X-09 que
  vive na tool, e sem ela o ensaio cruzado media o nada.

## O catalogo de ensaio tem tres produtos, e os tres existem por uma razao

Um com preco `fixo` e stock, um `a_partir_de` e um `sob_consulta` — os tres modos
do `03` §7.1, que o *renderer* do KAM-032 trata de tres maneiras. Um catalogo so
com precos fixos deixava o caminho do `sob_consulta` sem exercicio, que e o
caminho do KAM-123.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from ...tls.erros import (
    LIMIT_EXCEEDED,
    NOT_FOUND,
    OUT_OF_STOCK,
    PRICE_CHANGED,
    Fact,
)
from ...tls.especificacoes import ErroDeBackend, Pedido, Resposta

#: O instante dos *facts* de ensaio. Fixo para que uma bateria nao dependa do
#: relogio; quem precisar de o mover passa `retrieved_at` ao construir.
INSTANTE: Final = "2026-10-27T09:00:00Z"


@dataclass(frozen=True, slots=True)
class Produto:
    """Uma linha do catalogo de ensaio."""

    sku: str
    designacao: str
    preco_tipo: str
    #: Em centimos de AOA (`value_minor`, emenda 1.39). `None` em `sob_consulta`.
    preco_minor: int | None
    stock: int


CATALOGO: Final = (
    Produto("SKU-100", "Camisa Azul", "fixo", 1_250_000, 7),
    Produto("SKU-200", "Vestido de Festa", "a_partir_de", 3_500_000, 2),
    Produto("SKU-300", "Fato por medida", "sob_consulta", None, 0),
)


@dataclass
class BackendDeEnsaio:
    """Os cinco executores, com o estado que um backend real teria.

    **Nao e `frozen`**: um backend guarda carrinhos e encomendas. O que esta
    `frozen` e o catalogo, porque um *fake* que deixasse o teste mudar o preco
    por baixo do grafo media outra coisa.
    """

    catalogo: tuple[Produto, ...] = CATALOGO
    retrieved_at: str = INSTANTE
    #: Quantas vezes o backend foi chamado, por tool. E o que o criterio 3 le
    #: para dizer «exactamente 1 pedido».
    chamadas: dict[str, int] = field(default_factory=dict)
    #: `cart_id` -> itens, para o `criar_pedido` saber o que confirma.
    carrinhos: dict[str, tuple[tuple[str, int], ...]] = field(default_factory=dict)
    #: `chave` de idempotencia -> `order_id`. O §6.3 ponto (iii).
    por_chave: dict[str, str] = field(default_factory=dict)
    #: `order_id` -> (contact_id, estado). O ambito de dados do §6.2.
    encomendas: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: Codigos a levantar na proxima chamada de uma tool, para exercitar o §6.5.
    avarias: dict[str, list[str]] = field(default_factory=dict)
    _contador: int = 0

    # ------------------------------------------------------------- utilitarios
    def _proximo(self, prefixo: str) -> str:
        self._contador += 1
        return f"{prefixo}{self._contador}"

    def _fact(self, kind: str, value: Any, sku: str | None = None) -> Fact:
        # O `fact_id` e **opaco**: um contador, e nao o `sku` nem o valor.
        return Fact(
            fact_id=self._proximo("f"),
            kind=kind,
            value=value,
            retrieved_at=self.retrieved_at,
            sku=sku,
        )

    def _contar(self, tool: str) -> None:
        self.chamadas[tool] = self.chamadas.get(tool, 0) + 1

    def _avaria(self, tool: str) -> None:
        """Levanta o codigo que o ensaio tenha posto na fila desta tool."""
        fila = self.avarias.get(tool) or []
        if fila:
            raise ErroDeBackend(fila.pop(0), f"avaria de ensaio em {tool}")

    def _produto(self, sku: str) -> Produto:
        for produto in self.catalogo:
            if produto.sku == sku:
                return produto
        raise ErroDeBackend(NOT_FOUND, "sku fora do catalogo")

    # ---------------------------------------------------------------- read
    def search_catalog(self, pedido: Pedido) -> Resposta:
        """Candidatos **sem preco no ranking** (§6.2, primeira linha).

        O `score` e a fraccao da **designacao do produto** que a pergunta cobre,
        e nao a fraccao da pergunta — que foi a primeira versao e estava errada:
        «quero comprar uma camisa azul» tem tres palavras de enchimento, pelo
        que a Camisa Azul dava 0,4 e caia abaixo do limiar. O que se quer medir
        e quanto do produto foi nomeado.

        Nao e o RRF do KAM-061 e nao finge ser: e uma ordem monotona e
        explicavel, que e o que o `retrieve` precisa para decidir contra um
        limiar. **E o par (pontuador, limiar) tem um dono so**: o valor de
        `LIMIAR_IDX` so quer dizer algo contra um pontuador, e os dois mudam
        juntos quando o KAM-061 trouxer o indice real.
        """
        self._contar("search_catalog")
        self._avaria("search_catalog")
        palavras = {p for p in _palavras(pedido.args.query) if len(p) > 2}
        candidatos = []
        for produto in self.catalogo:
            alvo = {p for p in _palavras(produto.designacao) if len(p) > 2}
            if not palavras or not alvo:
                continue
            score = len(palavras & alvo) / len(alvo)
            if score > 0:
                candidatos.append(
                    {
                        "sku": produto.sku,
                        "nome": produto.designacao,
                        "preco_tipo": produto.preco_tipo,
                        "score": round(score, 4),
                    }
                )
        candidatos.sort(key=lambda c: (-c["score"], c["sku"]))
        return Resposta(data={"candidatos": tuple(candidatos)})

    def get_price_stock(self, pedido: Pedido) -> Resposta:
        """*Facts* `price` e `stock` por `sku`, com `retrieved_at` (§6.2)."""
        self._contar("get_price_stock")
        self._avaria("get_price_stock")
        facts: list[Fact] = []
        linhas = []
        for sku in pedido.args.skus:
            produto = self._produto(sku)
            linhas.append(
                {
                    "sku": produto.sku,
                    "nome": produto.designacao,
                    "preco_tipo": produto.preco_tipo,
                }
            )
            # Um `sob_consulta` **nao** leva *fact* `price`: o preco nao existe,
            # e inventar um zero era o pior dos dois mundos — um numero com
            # proveniencia a dizer que o fato e de graca.
            if produto.preco_minor is not None:
                facts.append(self._fact("price", produto.preco_minor, produto.sku))
            facts.append(self._fact("stock", produto.stock, produto.sku))
        return Resposta(data={"linhas": tuple(linhas)}, facts=tuple(facts))

    def propose_cart(self, pedido: Pedido) -> Resposta:
        """Total calculado no backend, `cart_id` e *fact* `total`; sem efeitos."""
        self._contar("propose_cart")
        self._avaria("propose_cart")
        total = 0
        itens: list[tuple[str, int]] = []
        for item in pedido.args.items:
            produto = self._produto(item.sku)
            if produto.preco_minor is None:
                raise ErroDeBackend(
                    NOT_FOUND, "produto sob consulta nao entra em carrinho (KAM-123)"
                )
            if produto.stock < item.qty:
                raise ErroDeBackend(OUT_OF_STOCK, f"{produto.sku} tem {produto.stock}")
            total += produto.preco_minor * item.qty
            itens.append((produto.sku, item.qty))
        cart_id = self._proximo("c")
        self.carrinhos[cart_id] = tuple(itens)
        return Resposta(
            data={"cart_id": cart_id, "items": tuple(itens)},
            facts=(self._fact("total", total),),
        )

    def get_order_status(self, pedido: Pedido) -> Resposta:
        """So encomendas **do proprio contacto** (§6.2, «evita fuga intra-tenant»)."""
        self._contar("get_order_status")
        self._avaria("get_order_status")
        linha = self.encomendas.get(pedido.args.order_id)
        # Um `order_id` de outro contacto da **a mesma** resposta que um que nao
        # existe. Distingui-los era um oraculo: «esta encomenda existe, tua e
        # que nao e» responde a pergunta que o X-09 faz.
        if linha is None or linha[0] != pedido.ctx.contact_id:
            raise ErroDeBackend(NOT_FOUND, "encomenda inexistente ou de outro contacto")
        return Resposta(data={"order_id": pedido.args.order_id, "estado": linha[1]})

    # ---------------------------------------------------------------- money
    def criar_pedido(self, pedido: Pedido) -> Resposta:
        """Um pedido por carrinho, idempotente pela chave do §6.3.

        **A chave vem no `Pedido` e nao se deriva aqui.** O criterio 4 do KAM-029
        diz que «o backend e idempotente pela chave», e um backend que a derivasse
        outra vez dos argumentos nao estava a satisfazer o contrato — estava a
        repetir um calculo que podia divergir do de quem o chamou.
        """
        self._contar("criar_pedido")
        self._avaria("criar_pedido")
        chave = pedido.chave
        if chave is None:
            raise ErroDeBackend(
                LIMIT_EXCEEDED, "uma tool `money` sem chave de idempotencia nao executa"
            )
        guardado = self.por_chave.get(chave)
        if guardado is not None:
            # O resultado guardado, **sem** criar nada: e isto que faz os
            # cinquenta toques concorrentes darem uma encomenda.
            return Resposta(data={"order_id": guardado, "idempotent_replay": True})
        itens = self.carrinhos.get(pedido.args.cart_id)
        if itens is None:
            raise ErroDeBackend(NOT_FOUND, "carrinho inexistente")
        for sku, qty in itens:
            produto = self._produto(sku)
            if produto.stock < qty:
                raise ErroDeBackend(OUT_OF_STOCK, f"{sku} tem {produto.stock}")
        order_id = self._proximo("o")
        self.por_chave[chave] = order_id
        self.encomendas[order_id] = (pedido.ctx.contact_id, "pendente")
        return Resposta(data={"order_id": order_id, "estado": "pendente"})

    # ---------------------------------------------------------------- registo
    def executores(self) -> dict[str, Any]:
        """O mapa que o `especificacoes_do_vendedor()` espera."""
        return {
            "search_catalog": self.search_catalog,
            "get_price_stock": self.get_price_stock,
            "propose_cart": self.propose_cart,
            "criar_pedido": self.criar_pedido,
            "get_order_status": self.get_order_status,
        }


def _palavras(texto: str) -> list[str]:
    """As palavras de um texto, sem acentos, sem pontuacao e em minusculas.

    Usa a normalizacao do validador (KAM-032) em vez de uma propria: duas
    maneiras de tirar acentos no mesmo servico divergem no dia em que uma delas
    ganhar um caractere.

    **A pontuacao tem de sair, e a primeira versao nao a tirava.** Com um
    `split()` simples, «tem algum fato?» dava `fato?` — que nao casa `fato` —, e
    a ultima palavra de **toda** a pergunta terminada em `?` deixava de contar.
    A consequencia nao era um teste vermelho: era um emparelhamento degradado a
    passar a bateria inteira, e foi uma mutacao sobrevivente que o denunciou (a
    do limiar: nao havia candidato nenhum para o limiar recusar). E a licao do
    KAM-032 outra vez — o que nao se extrai nao se valida.
    """
    import re as _re

    from ...validador.normalizacao import sem_acento

    return [p for p in _re.split(r"[^a-z0-9]+", sem_acento(texto.lower())) if p]


#: Os codigos que um ensaio pode pôr em `avarias` e que o §6.5 manda tratar no
#: grafo. Nao e a lista dos onze: e a dos que **um backend de catalogo ou de
#: encomendas** pode devolver. Um `TENANT_MISMATCH` nao vem do backend — vem do
#: passo 2 do `invoke`, e quem o exercita e a bateria da ToolLayer.
AVARIAS_POSSIVEIS: Final = (NOT_FOUND, OUT_OF_STOCK, PRICE_CHANGED, LIMIT_EXCEEDED)
