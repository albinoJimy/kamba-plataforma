"""Os executores das tools de comercio e o duplo toque pelo grafo (KAM-178).

## O que esta bateria mede, e o que ela **nao** mede

Mede tres coisas, e a terceira e a que o criterio 7 pedia e que nao existia:

```text
1. os executores        os dois cabecalhos, a traducao dos codigos, o Fact
2. a barreira da TLS    o `cart_id` do passo 4 e a chave do passo 5 (KAM-029)
3. o grafo              o no a re-executar sobre o MESMO checkpoint envia a
                        MESMA identidade de intencao ao COM
```

**O que ela nao mede e a composicao das duas barreiras num processo so.** A
barreira do COM e o `INSERT … ON CONFLICT (tenant_id, intent_key) DO NOTHING` da
`platform.order_intents`, que vive em TypeScript e num PostgreSQL; o que esta
bateria tem do outro lado da rede e um **substituto** que reproduz a semantica
pela mesma chave. Logo:

* que o grafo envia a mesma `intent_key` em duas execucoes do no — **CONFIRMADO
  aqui**, e e a metade que faltava;
* que a mesma `intent_key` da **uma** encomenda — **CONFIRMADO em
  `services/com/tests/orders.saga.test.ts`** (KAM-046), e herda-se com o estado
  de verificacao dele;
* que as duas, encadeadas, dao uma encomenda de ponta a ponta — **NAO
  VERIFICADO**: precisa de um arnes que levante o COM e um PostgreSQL e conduza o
  grafo contra eles. Credor na verificacao do bloco KAM-178.

Dizer «ponta a ponta» sobre a soma de (1) e (2) era a conclusao a andar um passo
a mais do que a medicao.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.com import (
    CABECALHO_INTERNO,
    CABECALHO_TENANT,
    ClienteDoCom,
    RespostaDoCom,
    executores_do_com,
)
from kamba_agr.tls.contexto import ToolContext
from kamba_agr.tls.especificacoes import Catalogo, EspecificacaoDeTool, ErroDeBackend
from kamba_agr.tls.erros import LIMIT_EXCEEDED, NOT_FOUND, PRICE_CHANGED
from kamba_agr.tls.vendedor import especificacoes_do_vendedor

# O `_Ligacao` e a loja de ensaio vivem no `test_tls` e no `test_vendedor`, e
# importam-se de la em vez de se reescreverem: a forma de uma tomada de ensaio
# e a mesma, e duas copias divergem no dia em que a camada pedir mais um metodo.
from test_tls import _Ligacao  # type: ignore[import-not-found]
from test_vendedor import LOJA  # type: ignore[import-not-found]

TENANT = "11111111-1111-4111-8111-111111111111"
CONTACTO = "22222222-2222-4222-8222-222222222222"
CREDENCIAL = "a-credencial-do-com"


def contexto() -> ToolContext:
    return ToolContext(
        tenant_id=TENANT,
        channel_id="c1",
        contact_id=CONTACTO,
        conversation_id="conv1",
        turn_id="turno-1",
        vertical="vendedor",
        run_id="r1",
        graph_version="1",
    )


class ComDeEnsaio:
    """Um substituto do COM que reproduz a semantica da `intent_key`.

    **E um substituto e nao o COM**, e a nota do modulo diz o que isso custa a
    cada afirmacao. O que ele reproduz e exactamente a propriedade do §6.3 que
    importa aqui: o recibo e por `(tenant_id, intent_key)`, e a `intent_key`
    deriva-se de `(tenant_id, contact_id, draft_id, draft_version)` — pelo que
    duas chamadas com o mesmo rascunho encontram o mesmo recibo.

    A derivacao e um `repr` das quatro partes e nao o HMAC do COM: o que se mede
    e que as **partes** sao as mesmas, e um HMAC aqui era reimplementar o COM
    para depois o comparar consigo mesmo.
    """

    def __init__(self) -> None:
        self.pedidos: list[dict[str, Any]] = []
        self.cabecalhos: list[dict[str, str]] = []
        self.encomendas: dict[tuple[str, str, int], str] = {}
        self.avarias: dict[str, list[tuple[int, str]]] = {}
        self._n = 0

    def transporte(
        self,
        url: str,
        cabecalhos: dict[str, str],
        corpo: dict[str, Any],
        timeout: float,
    ) -> RespostaDoCom:
        rota = url[url.index("/internal/") :]
        self.pedidos.append({"rota": rota, "corpo": json.loads(json.dumps(corpo))})
        self.cabecalhos.append(dict(cabecalhos))
        fila = self.avarias.get(rota) or []
        if fila:
            estado, codigo = fila.pop(0)
            return RespostaDoCom(estado, {"tipo": "erro", "erro": codigo})
        if rota == "/internal/offer-view":
            return RespostaDoCom(
                200,
                {
                    "tipo": "ok",
                    "valor": {
                        "sku": corpo["sku"],
                        "precoTipo": "fixo",
                        "precoDisplay": "12 500 Kz",
                        "stockModo": "garantido",
                        "disponibilidade": "disponivel",
                        "atualizadoAt": "2026-11-04T10:00:00.000Z",
                    },
                },
            )
        if rota == "/internal/propose-cart":
            total = sum(12_50_000 * int(l["qty"]) for l in corpo["linhas"])
            return RespostaDoCom(
                200,
                {
                    "tipo": "ok",
                    "valor": {
                        "cart_id": "C7H3Q9ABCDEFGHJKMNPQRSTVWX",
                        "total_minor": str(total),
                        "currency": "AOA",
                        "exige_confirmacao_do_dono": False,
                        "linhas": [],
                    },
                },
            )
        if rota == "/internal/create-order":
            # **As quatro partes, e o `contact_id` e a quarta.** A versao anterior
            # deste duplo tinha tres e a docstring dizia quatro: um defeito que
            # mandasse o contacto errado era invisivel aqui, embora ele participe
            # da `intent_key` **e** da derivacao do `cart_id` (o `cartIdValido`
            # do COM inclui-o). Achado da revisao adversarial, medido com uma
            # mutacao que trocava o contacto e que a bateria nao via.
            chave = (
                cabecalhos[CABECALHO_TENANT],
                corpo["contact_id"],
                corpo["draft_id"],
                int(corpo["draft_version"]),
            )
            existente = self.encomendas.get(chave)
            if existente is not None:
                # A **mesma resposta** para N toques, com a marca de repeticao:
                # e a letra do passo 2 do algoritmo do §6.3.
                return RespostaDoCom(
                    200,
                    {
                        "tipo": "ok",
                        "valor": {
                            "orderId": existente,
                            "numeroPublico": "K7H3Q1",
                            "estado": "criada",
                            "repeticao": True,
                        },
                    },
                )
            self._n += 1
            order = f"0000000{self._n}-0000-4000-8000-000000000000"
            self.encomendas[chave] = order
            return RespostaDoCom(
                200,
                {
                    "tipo": "ok",
                    "valor": {
                        "orderId": order,
                        "numeroPublico": "K7H3Q1",
                        "estado": "criada",
                        "repeticao": False,
                    },
                },
            )
        if rota == "/internal/get-order":
            return RespostaDoCom(
                200,
                {
                    "tipo": "ok",
                    "valor": {
                        "orderId": corpo["order_id"],
                        "numeroPublico": "K7H3Q1",
                        "estado": "criada",
                        "contactId": corpo.get("_contacto", CONTACTO),
                    },
                },
            )
        return RespostaDoCom(404, {})

    def cliente(self) -> ClienteDoCom:
        return ClienteDoCom(
            base="http://com:3002",
            credencial=lambda: CREDENCIAL,
            transporte=self.transporte,
        )


RASCUNHO = {
    "draft_id": "d" * 64,
    "draft_version": 1,
    "entrega_modo": "levantamento",
    "linhas": ({"sku": "arroz-5kg", "qty": 2},),
}


class TestExecutores(unittest.TestCase):
    """O criterio 5: os executores ligados, um a um."""

    def setUp(self) -> None:
        self.com = ComDeEnsaio()
        self.executores = executores_do_com(self.com.cliente())

    def _pedido(self, nome: str, args: Any, **extra: Any):
        from kamba_agr.tls.especificacoes import Pedido

        return Pedido(ctx=contexto(), args=args, timeout_ms=2000, **extra)

    def test_os_dois_cabecalhos_vao_em_todas_as_chamadas(self) -> None:
        """O criterio 2 visto do lado de quem chama.

        A metade do critero 4 do KAM-042 que um *lint* nao consegue impor — «a
        TLS so chama a API interna do COM com `tenant_id` em cabecalho» — e uma
        regra sobre o **chamador**, e e esta a sua medicao. O lado do chamado
        tem a sentinela do `lint_arch medusa`.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeGetPriceStock

        self.executores["get_price_stock"](
            self._pedido(
                "get_price_stock", ArgumentosDeGetPriceStock(skus=("arroz-5kg",))
            )
        )
        self.assertEqual(len(self.com.cabecalhos), 1)
        cabecalhos = self.com.cabecalhos[0]
        self.assertEqual(cabecalhos[CABECALHO_INTERNO], CREDENCIAL)
        self.assertEqual(cabecalhos[CABECALHO_TENANT], TENANT)

    def test_o_tenant_do_cabecalho_e_o_do_ctx_e_nunca_outro(self) -> None:
        """O `ctx` constroi-se do estado, e o cabecalho sai dele.

        E o que fecha o caminho do ADR-015 deste lado: nenhum argumento de tool
        pode mudar o tenant, porque o cabecalho nao se le dos `args`.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeGetOrderStatus

        self.executores["get_order_status"](
            self._pedido(
                "get_order_status",
                ArgumentosDeGetOrderStatus(order_id="o1"),
            )
        )
        self.assertEqual(self.com.cabecalhos[0][CABECALHO_TENANT], TENANT)

    def test_o_contacto_do_corpo_e_o_do_ctx_e_nunca_outro(self) -> None:
        """O par do caso de cima, e faltava.

        O `contact_id` participa da `intent_key` **e** da derivacao do `cart_id`
        (o `cartIdValido` do COM inclui-o), e nenhuma asserçao o prendia: uma
        mutacao que mandasse o contacto de outra pessoa passava a bateria
        inteira. Achado da revisao adversarial.

        Vai no **corpo** e nao no cabecalho, ao contrario do tenant, e a razao
        esta no `ClienteDoCom`: o tenant e o que um proxy pode registar sem abrir
        o corpo e e o que o `lint_arch medusa` verifica na rota; o contacto e do
        turno.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeProposeCart, ItemDoCarrinho

        self.executores["propose_cart"](
            self._pedido(
                "propose_cart",
                ArgumentosDeProposeCart(
                    items=(ItemDoCarrinho(sku="arroz-5kg", qty=1),)
                ),
                rascunho=RASCUNHO,
            )
        )
        self.assertEqual(self.com.pedidos[0]["corpo"]["contact_id"], CONTACTO)

    def test_o_propose_cart_devolve_o_fact_total_construido_na_tls(self) -> None:
        """O criterio 5 e a caixa «numeros so de tools» da DoD (ADR-007).

        **O `Fact` e da TLS e o numero e do backend**, e as duas metades medem-se
        aqui: o `value` e exactamente o `total_minor` que o COM devolveu, e o
        `fact_id` e **opaco** — nao deriva do `sku` nem do valor, porque entra na
        coluna `fact_ids` da `tool_audit`.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeProposeCart, ItemDoCarrinho

        resposta = self.executores["propose_cart"](
            self._pedido(
                "propose_cart",
                ArgumentosDeProposeCart(
                    items=(ItemDoCarrinho(sku="arroz-5kg", qty=2),)
                ),
                rascunho=RASCUNHO,
            )
        )
        self.assertEqual(len(resposta.facts), 1)
        fact = resposta.facts[0]
        self.assertEqual(fact.kind, "total")
        self.assertEqual(fact.value, 2_500_000)
        self.assertNotIn("arroz", fact.fact_id)
        self.assertNotIn("2500000", fact.fact_id)
        # E o total **nao** foi somado aqui: veio como cadeia de digitos do COM.
        enviado = self.com.pedidos[0]
        self.assertEqual(enviado["rota"], "/internal/propose-cart")
        self.assertEqual(enviado["corpo"]["draft_id"], RASCUNHO["draft_id"])

    def test_sem_rascunho_o_propose_cart_recusa_e_nao_chama_o_com(self) -> None:
        """O rascunho do §6.3 e obrigatorio, e a falta dele e uma **resposta**.

        `VALIDATION_ERROR` e nao uma excepcao, pela razao do `erros.py`: «os onze
        sao respostas previstas e o grafo decide sobre elas». Uma excepcao fazia
        o turno falhar com 500 em vez de o `compose` dizer que nao conseguiu.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeProposeCart, ItemDoCarrinho

        with self.assertRaises(ErroDeBackend) as capturado:
            self.executores["propose_cart"](
                self._pedido(
                    "propose_cart",
                    ArgumentosDeProposeCart(
                        items=(ItemDoCarrinho(sku="arroz-5kg", qty=1),)
                    ),
                )
            )
        self.assertEqual(capturado.exception.codigo, "VALIDATION_ERROR")
        self.assertEqual(self.com.pedidos, [])

    def test_os_codigos_do_com_chegam_pelo_nome_e_nao_pelo_estado_http(self) -> None:
        """Os nove do `OrdersModule.erro` atravessam intactos.

        **E isto que o alargamento da porta compra.** Antes dele, um
        `PRICE_CHANGED` nao cabia na lista de cinco do §3.39 e o COM tinha de o
        traduzir — e a unica traducao disponivel era dizer ao cliente que o
        pedido dele nao serve. O grafo trata os tres de maneiras diferentes
        (§6.5), e por isso o nome tem de chegar.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeCriarPedido

        for estado, codigo in [
            (409, PRICE_CHANGED),
            (409, "OUT_OF_STOCK"),
            (409, "INTENT_REUSED_WITH_DIFFERENT_CONTENT"),
            (429, LIMIT_EXCEEDED),
            (404, NOT_FOUND),
        ]:
            self.com.avarias["/internal/create-order"] = [(estado, codigo)]
            with self.assertRaises(ErroDeBackend) as capturado:
                self.executores["criar_pedido"](
                    self._pedido(
                        "criar_pedido",
                        ArgumentosDeCriarPedido(cart_id="C7H3Q9"),
                        rascunho={**RASCUNHO, "total_esperado_minor": 2_500_000},
                    )
                )
            self.assertEqual(capturado.exception.codigo, codigo)

    def test_um_conflito_de_cas_nao_chega_como_validation_error(self) -> None:
        """O terceiro caso do `Resultado`, visto deste lado.

        O COM responde 409 com `tipo: conflito` e **sem** codigo: nenhum dos
        treze do §3.27 diz «rele e reavalia». O que o grafo pode fazer e repetir
        com o que ler agora, e o codigo que o §6.5 manda tratar assim e o
        `UPSTREAM_TIMEOUT` (um *retry*, depois handoff) — **nunca** o
        `VALIDATION_ERROR`, que dizia ao cliente que o pedido dele nao serve.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeCriarPedido

        def conflito(url, cabecalhos, corpo, timeout):  # noqa: ANN001
            return RespostaDoCom(409, {"tipo": "conflito", "valor": {"version": 7}})

        executores = executores_do_com(
            ClienteDoCom(
                base="http://com:3002",
                credencial=lambda: CREDENCIAL,
                transporte=conflito,
            )
        )
        with self.assertRaises(ErroDeBackend) as capturado:
            executores["criar_pedido"](
                self._pedido(
                    "criar_pedido",
                    ArgumentosDeCriarPedido(cart_id="C7H3Q9"),
                    rascunho={**RASCUNHO, "total_esperado_minor": 2_500_000},
                )
            )
        self.assertEqual(capturado.exception.codigo, "UPSTREAM_TIMEOUT")
        self.assertNotEqual(capturado.exception.codigo, "VALIDATION_ERROR")

    def test_o_get_order_status_nao_ve_encomenda_de_outro_contacto(self) -> None:
        """O ambito de dados do §6.2: «tenant **e** contacto».

        A porta filtra por tenant — e isso e certo, porque ela serve tambem o
        dono e o `ops`. Quem estreita para o contacto e quem chama em nome de um
        cliente, e e o executor. E a resposta e **a mesma** que um `order_id` que
        nao existe: distingui-las era o oraculo que o X-09 procura.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeGetOrderStatus

        def de_outro(url, cabecalhos, corpo, timeout):  # noqa: ANN001
            return RespostaDoCom(
                200,
                {
                    "tipo": "ok",
                    "valor": {
                        "orderId": corpo["order_id"],
                        "numeroPublico": "K7H3Q1",
                        "estado": "criada",
                        "contactId": "33333333-3333-4333-8333-333333333333",
                    },
                },
            )

        executores = executores_do_com(
            ClienteDoCom(
                base="http://com:3002",
                credencial=lambda: CREDENCIAL,
                transporte=de_outro,
            )
        )
        with self.assertRaises(ErroDeBackend) as capturado:
            executores["get_order_status"](
                self._pedido(
                    "get_order_status", ArgumentosDeGetOrderStatus(order_id="o1")
                )
            )
        self.assertEqual(capturado.exception.codigo, NOT_FOUND)

    def test_o_get_price_stock_nao_devolve_facts_e_isso_esta_dito(self) -> None:
        """O achado do criterio 5, medido em vez de escrito.

        O §6.2 diz que esta tool «devolve *facts* `price` e `stock`», e a
        `OfferView` do §3.2 **nao tem numero**: o preco vem ja formatado (preco
        opaco, KAM-043) e o stock vem como *modo*. Logo nao ha numero com
        proveniencia a construir, e inventar um a partir de um texto formatado
        era o pior dos dois mundos.
        """
        from kamba_agr.tls.vendedor import ArgumentosDeGetPriceStock

        resposta = self.executores["get_price_stock"](
            self._pedido(
                "get_price_stock",
                ArgumentosDeGetPriceStock(skus=("arroz-5kg",)),
            )
        )
        self.assertEqual(resposta.facts, ())
        linha = resposta.data["linhas"][0]
        self.assertEqual(linha["preco_display"], "12 500 Kz")
        self.assertEqual(linha["stock_modo"], "garantido")

    def test_um_sku_fora_do_catalogo_nao_recusa_a_lista_inteira(self) -> None:
        """Um `NOT_FOUND` de um `sku` com os outros a existir e o catalogo a mudar."""
        from kamba_agr.tls.vendedor import ArgumentosDeGetPriceStock

        self.com.avarias["/internal/offer-view"] = [(404, NOT_FOUND)]
        resposta = self.executores["get_price_stock"](
            self._pedido(
                "get_price_stock",
                ArgumentosDeGetPriceStock(skus=("nao-existe", "arroz-5kg")),
            )
        )
        self.assertEqual(len(resposta.data["linhas"]), 1)
        # E com **todos** fora, recusa: uma lista vazia era lida como «a loja nao
        # tem nada», que e diferente de «nenhum destes».
        self.com.avarias["/internal/offer-view"] = [(404, NOT_FOUND)]
        with self.assertRaises(ErroDeBackend) as capturado:
            self.executores["get_price_stock"](
                self._pedido(
                    "get_price_stock",
                    ArgumentosDeGetPriceStock(skus=("nao-existe",)),
                )
            )
        self.assertEqual(capturado.exception.codigo, NOT_FOUND)


class TestOCanalDoRascunho(unittest.TestCase):
    """O rascunho atravessa a camada **fora** dos argumentos (KAM-178)."""

    def test_o_invoke_leva_o_rascunho_ao_executor_sem_o_expor_ao_modelo(self) -> None:
        """A propriedade que faz deste canal um canal e nao um argumento.

        O esquema que o modelo ve e o do `ArgumentosDeCriarPedido`, que tem
        `cart_id` e mais nada com `extra=\"forbid\"`. Se o `draft_id` fosse um
        argumento, o modelo podia inventa-lo — e um `draft_id` inventado e uma
        encomenda a mais por toque.
        """
        com = ComDeEnsaio()
        catalogo = Catalogo(
            especificacoes_do_vendedor(
                {
                    **executores_do_com(com.cliente()),
                    # O `search_catalog` fica com um executor de ensaio: esta
                    # bateria nao mede o IDX, e o `especificacoes_do_vendedor`
                    # exige os cinco.
                    "search_catalog": lambda pedido: None,  # type: ignore[arg-type,return-value]
                }
            )
        )
        camada = ToolLayer(catalogo, abrir_ligacao=lambda: _Ligacao(outro=LOJA))
        resultado = asyncio.run(
            camada.invoke(
                contexto(),
                "criar_pedido",
                {"cart_id": "C7H3Q9"},
                allowed=("criar_pedido",),
                confirmation=None,
                idempotency_key="turno-1:1",
                rascunho={**RASCUNHO, "total_esperado_minor": 2_500_000},
            )
        )
        # O passo 4 recusa sem botao, e isso e o esperado: o que este caso mede e
        # o **canal**, e por isso basta ver que o rascunho chegou ou que a recusa
        # e a do botao e nao a do rascunho.
        self.assertFalse(resultado.ok)
        assert resultado.error is not None
        self.assertEqual(resultado.error.codigo, "VALIDATION_ERROR")
        # O esquema que o modelo ve **nao** tem o `draft_id`.
        visiveis = catalogo.parametros_visiveis("criar_pedido")
        self.assertEqual(visiveis, frozenset({"cart_id"}))
        self.assertNotIn("draft_id", visiveis)


# ------------------------------------------- criterio 7: o duplo toque pelo grafo


class TestDuploToquePeloGrafo(unittest.TestCase):
    """O criterio 7, na metade que faltava.

    O KAM-046 mediu **cinquenta `createOrder` concorrentes** dentro do COM. O que
    este criterio pede e outro caminho: «o duplo toque do mesmo botao
    `confirm:{cart_id}` **atraves do grafo** — isto e, com o no a re-executar
    sobre o mesmo *checkpoint*».

    A propriedade que isso tem de ter, e que ninguem tinha medido, e esta: **a
    identidade da intencao que chega ao COM e a mesma nas duas execucoes**. Ela
    nao vem dos argumentos da tool (que sao so o `cart_id`) nem do turno (que e
    outro): vem do `cart` que o *checkpoint* guardou, com o `draft_id` e a
    `draft_version` que o `cart_build` gerou **uma vez**. Se viesse do turno, duas
    execucoes davam duas `intent_key` e duas encomendas — que e o defeito que o
    §6.3 existe para fechar.

    Ver a nota do modulo para o que esta bateria **nao** mede: a composicao das
    duas barreiras num processo so.
    """

    def _conversa(self):
        from langgraph.checkpoint.memory import InMemorySaver

        import test_vendedor as tv  # type: ignore[import-not-found]

        com = ComDeEnsaio()
        executores = {
            **executores_do_com(com.cliente()),
            # O `search_catalog` fala com o IDX (KAM-061) e esta bateria nao o
            # mede: entra com o executor de ensaio da vertical, que e onde ele
            # vive e de onde nenhum arranque o importa.
            "search_catalog": tv.BackendDeEnsaio().search_catalog,
        }
        catalogo = Catalogo(
            especificacoes_do_vendedor(executores)
            + (
                EspecificacaoDeTool(
                    nome="get_store_info",
                    klass="read",
                    backend="plataforma",
                    modelo=tv.get_store_info.ArgumentosDeGetStoreInfo,
                    executor=tv.get_store_info.executar,
                ),
            )
        )
        camada = ToolLayer(catalogo, abrir_ligacao=lambda: _Ligacao(outro=LOJA))
        conversa = tv._Conversa.__new__(tv._Conversa)
        conversa.tenant = TENANT
        conversa.contacto = CONTACTO
        saida = tv.Saida()
        conversa.saida = saida
        conversa.ligacao = _Ligacao(outro=LOJA)
        conversa.backend = com
        conversa.deps = tv.Dependencias(
            tools=camada,
            saida=saida,
            persona=tv.PERSONA,
            hnd=None,
            metricas=None,
            relogio=tv.Relogio(),
            checkpointer=InMemorySaver(),
        )
        conversa.grafo = tv.build_graph(conversa.deps)
        conversa._primeiro = True
        return conversa, com

    def test_o_cart_build_poe_a_identidade_da_intencao_no_checkpoint(self) -> None:
        """A precondicao do criterio 7, e nao se da por sabida.

        Sem `draft_id` no `cart`, o caso de baixo media o nada: duas execucoes
        mandavam `None` as duas vezes e o substituto do COM achava que era a
        mesma intencao. **Uma mutacao que nao muda nada e uma falha, nunca um
        verde** — e esta e a precondicao que o evita.
        """
        conversa, com = self._conversa()
        primeiro = conversa.turno("quero comprar uma camisa azul")
        carrinho = primeiro["cart"]
        self.assertIsInstance(carrinho.get("draft_id"), str)
        self.assertEqual(len(carrinho["draft_id"]), 64)
        self.assertEqual(carrinho["draft_version"], 1)
        self.assertEqual(carrinho["entrega_modo"], "levantamento")
        self.assertTrue(carrinho["linhas"])
        # E o total que o botao cita e o do backend, guardado: e por ele que o
        # COM mede o `PRICE_CHANGED`.
        self.assertIsInstance(carrinho["total_minor"], int)
        # O `propose_cart` levou a mesma identidade ao COM.
        proposta = [p for p in com.pedidos if p["rota"] == "/internal/propose-cart"]
        self.assertEqual(len(proposta), 1)
        self.assertEqual(proposta[0]["corpo"]["draft_id"], carrinho["draft_id"])

    def test_o_segundo_toque_no_mesmo_botao_e_barrado_antes_do_backend(self) -> None:
        """A barreira da TLS, medida pelo que ela faz e nao pelo que se esperava.

        **Este caso chamava-se «manda a mesma intencao e da uma encomenda» e as
        asseroes de identidade dele viviam num ramo morto** — um
        `if len(criacoes) == 2:` que nunca era tomado, porque o segundo toque e
        barrado pelo `stage` antes de chegar ao backend. O que ficava de pe era
        `len(encomendas) == 1`, que passava por ter havido **uma** chamada ao
        todo: aparelho de prova vazio no meio da citacao do criterio 7. Achado da
        revisao adversarial, medido com um `self.fail()` dentro do ramo.

        A substancia do criterio esta no caso seguinte, que re-executa o no e
        **assere sem condicao**. Este mede a outra propriedade, que tambem e
        real: num segundo turno com o mesmo botao, o `confirm_gate` recusa e o
        `create_order` **nao corre** — pelo que a barreira do COM nem e
        exercitada.
        """
        conversa, com = self._conversa()
        primeiro = conversa.turno("quero comprar uma camisa azul")
        cart_id = primeiro["cart"]["cart_id"]

        segundo = conversa.turno("confirm:" + cart_id, tipo="interactive")
        self.assertEqual(segundo["stage"], "awaiting_payment")
        criacoes = [p for p in com.pedidos if p["rota"] == "/internal/create-order"]
        self.assertEqual(len(criacoes), 1, "o primeiro toque nao criou nada")

        terceiro = conversa.turno("confirm:" + cart_id, tipo="interactive")

        # **O segundo toque nao chega ao backend**, e e isso que se afirma — sem
        # ramo e sem condicao.
        criacoes = [p for p in com.pedidos if p["rota"] == "/internal/create-order"]
        self.assertEqual(len(criacoes), 1, "o segundo toque chegou ao backend")
        self.assertIn("STALE_CONFIRMATION", terceiro.get("avisos") or ())
        self.assertEqual(len(com.encomendas), 1, "duas encomendas: %r" % (com.encomendas,))

    def test_a_segunda_execucao_do_no_reenvia_a_mesma_intencao(self) -> None:
        """A re-execucao **do no**, e nao do turno, e e o que o criterio escreve.

        Em vez de um segundo turno, chama-se o grafo duas vezes com o **mesmo**
        estado e o mesmo `thread_id`: e o que o LangGraph faz quando um no
        reinicia depois de um `interrupt()` (ADR-002) e e o caso que o §6.3
        nomeia por extenso («o estado do LangGraph pode re-executar o no apos
        `interrupt()`; sem identidade estavel da intencao, um *replay* cria nova
        chave»).

        A barreira do `stage` nao se aplica aqui, porque o estado que entra e o
        mesmo nas duas: o que tem de segurar e a **identidade**.
        """
        conversa, com = self._conversa()
        primeiro = conversa.turno("quero comprar uma camisa azul")
        carrinho = dict(primeiro["cart"])

        import test_vendedor as tv  # type: ignore[import-not-found]

        def estado_do_toque() -> dict:
            invocacao = tv.ler_invocacao(
                tv.invocacao_crua(
                    type="interactive", tenant_id=TENANT, contact_id=CONTACTO
                )
            )
            return {
                **tv.estado_de(
                    "confirm:" + str(carrinho["cart_id"]),
                    tipo="interactive",
                    tenant_id=TENANT,
                    contact_id=CONTACTO,
                ),
                "turn_id": invocacao.turn_id,
                "cart": dict(carrinho),
                "stage": "awaiting_confirm",
            }

        asyncio.run(
            conversa.grafo.ainvoke(
                estado_do_toque(), {"configurable": {"thread_id": "replay"}}
            )
        )
        asyncio.run(
            conversa.grafo.ainvoke(
                estado_do_toque(), {"configurable": {"thread_id": "replay"}}
            )
        )

        criacoes = [p for p in com.pedidos if p["rota"] == "/internal/create-order"]
        self.assertEqual(len(criacoes), 2, "o no nao re-executou")
        # **A mesma identidade nas duas**: e isto que o criterio 7 pedia e que
        # nao estava medido. Sem ela, duas `intent_key` e duas encomendas.
        self.assertEqual(
            criacoes[0]["corpo"]["draft_id"], criacoes[1]["corpo"]["draft_id"]
        )
        self.assertEqual(
            criacoes[0]["corpo"]["draft_version"],
            criacoes[1]["corpo"]["draft_version"],
        )
        # E o substituto do COM devolve o recibo da primeira: **uma** encomenda.
        self.assertEqual(len(com.encomendas), 1)

    def test_uma_recompra_identica_e_intencao_nova_e_da_encomenda_nova(self) -> None:
        """O ACHADO 1 da revisao adversarial, fixado pelo nome.

        «Recompra ⇒ novo `draft_id` ⇒ nova encomenda» (§6.3), e o caso que fecha
        e o do conteudo **igual** — nao o do carrinho editado, que o caso de
        baixo ja media. Com o rascunho a sobreviver a criacao da encomenda, a
        mesma frase outra vez na mesma conversa reusava o `draft_id` **e** a
        `draft_version` (as linhas nao mudaram), derivava a mesma `intent_key`, e
        o COM devolvia o recibo da primeira: o cliente confirmava e recebia o
        numero da encomenda anterior, **sem encomenda nova e sem recusa**.

        Medido antes da correccao: duas chamadas ao backend com
        `draft_id` igual nas duas, e **uma** encomenda. Caminho feliz de uma tool
        de classe `money`.
        """
        conversa, com = self._conversa()
        primeiro = conversa.turno("quero comprar uma camisa azul")
        conversa.turno("confirm:" + primeiro["cart"]["cart_id"], tipo="interactive")
        self.assertEqual(len(com.encomendas), 1)

        # **A mesma frase**: o mesmo artigo, a mesma quantidade, a mesma conversa.
        segundo = conversa.turno("quero comprar uma camisa azul")
        self.assertEqual(
            tuple(segundo["cart"]["linhas"]),
            tuple(primeiro["cart"]["linhas"]),
            "a sonda deixou de medir o conteudo igual",
        )
        # O rascunho anterior esta **gasto**, pelo que o `draft_id` e outro.
        self.assertNotEqual(
            segundo["cart"]["draft_id"],
            primeiro["cart"]["draft_id"],
            "o rascunho gasto foi reusado: a recompra fica bloqueada",
        )
        conversa.turno("confirm:" + segundo["cart"]["cart_id"], tipo="interactive")
        self.assertEqual(
            len(com.encomendas), 2, "uma recompra identica tem de dar encomenda nova"
        )
        criacoes = [p for p in com.pedidos if p["rota"] == "/internal/create-order"]
        self.assertEqual(len(criacoes), 2)
        self.assertNotEqual(
            criacoes[0]["corpo"]["draft_id"], criacoes[1]["corpo"]["draft_id"]
        )

    def test_um_carrinho_editado_antes_de_confirmar_sobe_a_versao(self) -> None:
        """«Carrinho editado ⇒ nova `draft_version`» (§6.3), e **antes** de confirmar.

        **Este caso nao existia, e e o que a frase do §6.3 descreve.** A versao
        anterior dele editava o carrinho **depois** de confirmar e afirmava a
        propriedade deste — `draft_id` igual, `draft_version` a subir —, o que
        era medir o caso (b) com a asserçao do caso (a). Os dois sao diferentes e
        os dois importam:

            (a) editado ANTES de confirmar  -> mesmo draft_id, versao sobe
            (b) editado DEPOIS de confirmar -> recompra, draft_id novo

        Separa-los saiu da correccao do ACHADO 1: ao marcar o rascunho como
        gasto, o caso antigo passou a medir (b) e a asserçao de (a) ficou
        vermelha — o que foi a prova de que ela estava no caso errado.

        O (a) e o que **nao** pode partir com a correccao: dois carrinhos antes
        de haver encomenda sao a mesma intencao a ser editada, e um `draft_id`
        novo a cada edicao fazia de cada toque uma encomenda nova.
        """
        conversa, com = self._conversa()
        primeiro = conversa.turno("quero comprar uma camisa azul")
        # **Sem confirmar.** O cliente muda de ideias antes de tocar no botao.
        segundo = conversa.turno("quero comprar 3 unidades da camisa azul")

        self.assertEqual(segundo["cart"]["draft_id"], primeiro["cart"]["draft_id"])
        self.assertEqual(segundo["cart"]["draft_version"], 2)
        self.assertNotEqual(
            tuple(segundo["cart"]["linhas"]), tuple(primeiro["cart"]["linhas"])
        )
        self.assertEqual(len(com.encomendas), 0, "nada se criou sem confirmacao")

        conversa.turno("confirm:" + segundo["cart"]["cart_id"], tipo="interactive")
        self.assertEqual(len(com.encomendas), 1, "a edicao confirmada da uma encomenda")

    def test_um_carrinho_editado_depois_de_confirmar_e_recompra(self) -> None:
        """O caso (b): depois de haver encomenda, editar e recomprar.

        E a mesma propriedade do `test_uma_recompra_identica...` com conteudo
        diferente, e fica ao lado dele porque a distincao entre os dois casos e o
        que o ACHADO 1 custou: um deles passava e o outro nao, e o que passava
        era o que nao fechava.
        """
        conversa, com = self._conversa()
        primeiro = conversa.turno("quero comprar uma camisa azul")
        conversa.turno("confirm:" + primeiro["cart"]["cart_id"], tipo="interactive")

        segundo = conversa.turno("quero comprar 3 unidades da camisa azul")
        # O rascunho anterior esta gasto: `draft_id` novo e versao de volta a um.
        self.assertNotEqual(segundo["cart"]["draft_id"], primeiro["cart"]["draft_id"])
        self.assertEqual(segundo["cart"]["draft_version"], 1)

        conversa.turno("confirm:" + segundo["cart"]["cart_id"], tipo="interactive")
        self.assertEqual(
            len(com.encomendas), 2, "um carrinho editado tem de dar encomenda nova"
        )


if __name__ == "__main__":
    unittest.main()
