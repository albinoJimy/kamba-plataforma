"""KAM-039 — a prova da regra de dois: as duas verticais num runtime so.

## O que esta bateria mede, e porque e uma bateria nova

O ADR-012 afirma que uma vertical e configuracao e nao codigo. As baterias de
cada vertical (`test_vendedor.py`, `test_servicos.py`) medem cada uma **a sua**,
e o `TestReuso` do KAM-035 ja mede que os doze nos reaproveitados sao o **mesmo
objecto** do Vendedor. O que nenhuma delas mede e a afirmacao central: que as
duas correm **ao mesmo tempo, no mesmo processo, sobre a mesma ToolLayer**.

Duas verticais que passam separadas podem nao poder coexistir — e a classe de
defeito que a revisao adversarial do KAM-038 encontrou pelo outro lado: com o
*handler* indexado pelo tipo do evento, um *tenant* com as duas verticais activas
recebia a mesma mensagem duas vezes. Cada bateria sozinha dava verde.

```text
(a)  as duas verticais no mesmo AGR/TLS/EVT/TEN, uma conversa de cada,
     sem flag de vertical no caminho partilhado
(b)  os dois eventos de pagamento, produzidos pelo fluxo de uma encomenda
     do Vendedor, entregues ao handler de Servicos sem alterar o bus, o
     envelope nem o nucleo
```

**O *tenant* desta bateria tem as DUAS verticais activas**, e nao e uma
conveniencia de ensaio: e o *tenant* do *gate* da Fase 0 (`docs/tecnica/00`
§13.2, KAM-108), onde o Vendedor produz e os Servicos consomem. Uma loja, duas
verticais, um processo.

## O que esta bateria NAO mede, e onde isso se mede

* **a condicao (d)** — «nenhum nome de vertical no nucleo» — mede-se por
  varrimento estatico da arvore inteira, que e trabalho de `tools/`:
  `tools/reuse_metric/tests/test_nucleo.py`, com canario de mutacao por cada
  forma de escrever a excepcao. Aqui mede-se a metade que so o *runtime*
  mostra: que o caminho partilhado nao **recebe** a vertical como parametro que
  mude o que ele faz;
* **a metrica de reuso** — `tools/reuse_metric/tests/test_repositorio.py`;
* **a suite cruzada de isolamento ponta a ponta (X-02, X-09)** — e o KAM-066, e
  nao esta na base. Ver a seccao de verificacao do bloco do KAM-039: a caixa (c)
  fica vazia com credor;
* **o efeito de negocio do consumo cruzado** — confirmar uma marcacao com sinal
  e agendar o lembrete e o **KAM-047** (modulo `servicos`) e o **KAM-048**
  (lembretes). O que ha hoje esta medido abaixo, com o credor pinado: um teste
  que pina a divida fica vermelho no dia em que ela for paga, e obriga a
  actualizar esta bateria em vez de a deixar a afirmar o estado antigo.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from kamba_agr.estado import ConversaState
from kamba_agr.eventos import handlers, subscricoes
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.catalogo import get_store_info
from kamba_agr.tls.erros import TOOL_NOT_ALLOWED
from kamba_agr.tls.especificacoes import Catalogo, EspecificacaoDeTool
from kamba_agr.tls.servicos import especificacoes_de_servicos
from kamba_agr.tls.vendedor import especificacoes_do_vendedor
from kamba_agr.verticais.servicos import Dependencias as DependenciasDeServicos
from kamba_agr.verticais.servicos import build_graph as grafo_de_servicos
from kamba_agr.verticais.servicos import nos as nos_de_servicos
from kamba_agr.verticais.servicos.fakes import AgendaFalsa, executores_de_ensaio
from kamba_agr.verticais.vendedor import Dependencias as DependenciasDoVendedor
from kamba_agr.verticais.vendedor import build_graph as grafo_do_vendedor
from kamba_agr.verticais.vendedor import nos as nos_do_vendedor
from kamba_agr.verticais.vendedor.fakes import BackendDeEnsaio

# Os andaimes das duas baterias por vertical, e o duplo de ligacao da
# ToolLayer. Importam-se em vez de se copiarem pela razao que o
# `test_vendedor.py` escreve sobre o `_Ligacao`: duas copias do mesmo duplo
# divergem no dia em que alguem corrigir uma. E aqui a razao e mais forte — uma
# copia de um *fake* de vertical era precisamente a duplicacao que este ticket
# existe para medir.
from test_servicos import AGORA, DIA_DA_GRELHA, Relogio, Saida, estado_de as estado_de_servicos
from test_tls import _Ligacao
from test_vendedor import estado_de as estado_de_vendedor

#: A loja do *tenant* das duas verticais. **Uma so**, de proposito: o criterio
#: (a) pede as duas no mesmo TEN, e duas lojas eram dois *tenants*.
LOJA = (
    ("nome", "zona", "plus_code", "fuso_horario"),
    [("Casa Kianda", "Luanda", "6GCR2F", "Africa/Luanda")],
)

#: As personas. O **texto** e proprio de cada vertical (§5.4, linha «Persona /
#: prompts»), e a `loja` e a mesma porque o *tenant* e o mesmo.
PERSONA_DO_VENDEDOR = {
    "nome": "Vendedor",
    "apresentacao": "Sou o assistente automatico de {loja}.",
    "loja": "Casa Kianda",
}
PERSONA_DE_SERVICOS = {
    "nome": "Rececionista",
    "apresentacao": "Sou o assistente automatico de {loja}.",
    "loja": "Casa Kianda",
}


class Runtime:
    """Um AGR com as duas verticais: **uma** ToolLayer, **dois** grafos.

    E o sujeito do criterio (a). A ToolLayer e uma so e o catalogo e o das onze
    tools do §6.2 — as cinco do Vendedor, as cinco de Servicos e a
    `get_store_info`, que e a unica comum. O que distingue as duas verticais
    sao **campos** das `Dependencias` (a `persona` e a `tools_permitidas`) e
    nao tipos, nem ramos, nem flags.
    """

    def __init__(self) -> None:
        self.relogio = Relogio(AGORA)
        self.ligacao = _Ligacao(outro=LOJA)
        self.saida = Saida()
        self.backend = BackendDeEnsaio()
        self.agenda = AgendaFalsa(relogio=self.relogio, dia=DIA_DA_GRELHA)

        self.catalogo = Catalogo(
            especificacoes_do_vendedor(self.backend.executores())
            + especificacoes_de_servicos(executores_de_ensaio(self.agenda))
            + (
                EspecificacaoDeTool(
                    nome="get_store_info",
                    klass="read",
                    backend="plataforma",
                    modelo=get_store_info.ArgumentosDeGetStoreInfo,
                    executor=get_store_info.executar,
                ),
            )
        )
        #: **A unica.** As duas verticais invocam tools por aqui.
        self.tools = ToolLayer(self.catalogo, abrir_ligacao=lambda: self.ligacao)

        self.deps_do_vendedor = DependenciasDoVendedor(
            tools=self.tools,
            saida=self.saida,
            persona=PERSONA_DO_VENDEDOR,
            relogio=self.relogio,
            tools_permitidas=nos_do_vendedor.TOOLS_DO_VENDEDOR,
        )
        self.deps_de_servicos = DependenciasDeServicos(
            tools=self.tools,
            saida=self.saida,
            persona=PERSONA_DE_SERVICOS,
            relogio=self.relogio,
            tools_permitidas=nos_de_servicos.TOOLS_DE_SERVICOS,
        )

        self.vendedor = grafo_do_vendedor(self.deps_do_vendedor)
        self.servicos = grafo_de_servicos(self.deps_de_servicos)

    def turno(self, grafo, estado: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(grafo.ainvoke(estado))


# ===========================================================================
# Criterio (a) — as duas verticais no mesmo AGR/TLS/EVT/TEN
# ===========================================================================


class TestCriterioAAsDuasNoMesmoRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.r = Runtime()

    def test_uma_conversa_de_cada_vertical_corre_no_mesmo_processo(self) -> None:
        """O criterio (a) a letra: «processa uma conversa de cada».

        As duas perguntas atravessam o grafo inteiro — `ingest`, `classify`, a
        tool, `compose`, `validate`, `guard_out`, `send` — e as duas respostas
        saiem pelo **mesmo** Outbound.
        """
        self.r.turno(self.r.vendedor, estado_de_vendedor("qual e o horario da loja?"))
        self.r.turno(self.r.servicos, estado_de_servicos("que servicos tem"))

        self.assertEqual(len(self.r.saida.enviadas), 2, self.r.saida.textos)
        do_vendedor, de_servicos = self.r.saida.textos
        # A do Vendedor passou pela `get_store_info`; a de Servicos pela
        # `list_services`. Duas tools diferentes, uma camada.
        self.assertIn("Casa Kianda", do_vendedor)
        self.assertIn("Luanda", do_vendedor)
        self.assertIn("preco sob consulta", de_servicos)

    def test_a_ToolLayer_e_a_MESMA_e_serviu_as_duas(self) -> None:
        """**O canario do criterio (a).** Medido por identidade, nao por tipo.

        Se alguem der a Servicos uma ToolLayer propria — ou um catalogo proprio
        —, as duas verticais passam a correr em dois TLS e o criterio (a) deixa
        de se verificar sem nenhum teste de vertical o notar. Aqui compara-se
        `is`, e conta-se que as duas invocaram **por ela**: um `is` sobre uma
        camada que nenhuma das duas usou nao provava nada.
        """
        self.assertIs(self.r.deps_do_vendedor.tools, self.r.deps_de_servicos.tools)

        antes = len(self.r.ligacao.sql)
        self.r.turno(self.r.vendedor, estado_de_vendedor("qual e o horario da loja?"))
        meio = len(self.r.ligacao.sql)
        self.r.turno(self.r.servicos, estado_de_servicos("que servicos tem"))
        depois = len(self.r.ligacao.sql)

        self.assertGreater(meio, antes, "o turno do Vendedor nao invocou tool nenhuma")
        self.assertGreater(depois, meio, "o turno de Servicos nao invocou tool nenhuma")

    def test_o_catalogo_unico_tem_as_onze_tools_das_duas_verticais(self) -> None:
        nomes = set(self.r.catalogo.nomes())
        self.assertEqual(len(nomes), 11)
        self.assertTrue({"search_catalog", "criar_pedido"} <= nomes)
        self.assertTrue({"list_services", "book_slot"} <= nomes)
        self.assertIn("get_store_info", nomes)

    def test_a_lista_de_permitidas_separa_as_duas_e_nao_um_ramo(self) -> None:
        """O que isola as verticais e **dados**, e nao um `if` no nucleo.

        A `tools_permitidas` e um campo das `Dependencias` e corre no passo 1 do
        `invoke` para qualquer vertical. E a forma do ADR-012: configuracao.
        """
        self.assertEqual(len(nos_de_servicos.TOOLS_DE_SERVICOS), 6)
        self.assertEqual(len(nos_do_vendedor.TOOLS_DO_VENDEDOR), 6)
        self.assertEqual(
            set(nos_de_servicos.TOOLS_DE_SERVICOS)
            & set(nos_do_vendedor.TOOLS_DO_VENDEDOR),
            {"get_store_info"},
        )

    def test_uma_vertical_nao_alcanca_a_tool_da_outra_pelo_catalogo_comum(self) -> None:
        """O risco que o catalogo unico cria, fechado.

        Com as onze tools na mesma camada, a unica coisa entre o grafo de
        Servicos e uma tool do Vendedor e a lista de permitidas.

        **Mede-se o CODIGO da recusa e nao que ela aconteceu**, e a correccao e
        de uma mutacao: a primeira versao deste ensaio pedia o `criar_pedido`
        (uma entrada `declarada`, sem executor) e afirmava `not ok`. Com a
        mutacao que punha o `criar_pedido` **dentro** de `TOOLS_DE_SERVICOS`, o
        ensaio continuava verde — a invocacao falhava por falta de executor, e
        nao pela lista. Media o caso errado, e passava com confianca.

        Agora pede uma tool **ligada** do Vendedor e exige o
        `TOOL_NOT_ALLOWED`, que e o codigo do passo 1.
        """
        contexto = nos_de_servicos.contexto_de_tool(estado_de_servicos(""))
        permitidas = nos_de_servicos.TOOLS_DE_SERVICOS

        recusada = asyncio.run(
            self.r.tools.invoke(
                contexto,
                "get_order_status",
                {"referencia": "ABC-123"},
                allowed=permitidas,
            )
        )
        self.assertFalse(recusada.ok, "a camada aceitou uma tool da outra vertical")
        self.assertEqual(
            recusada.error.codigo,
            TOOL_NOT_ALLOWED,
            f"recusou pela razao errada: {recusada.error}",
        )

        # **O par positivo**, na mesma camada e no mesmo contexto, com uma tool
        # **dela**. Sem ele, uma camada que recusasse tudo passava o teste de
        # cima — e um canario de recusa sem o caminho legitimo ao lado nao prova
        # nada.
        aceite = asyncio.run(
            self.r.tools.invoke(contexto, "list_services", {}, allowed=permitidas)
        )
        self.assertTrue(aceite.ok, aceite)

        # E o Vendedor alcanca a **sua**: a recusa de cima e da lista, e nao de
        # a tool nao estar no catalogo unico.
        do_vendedor = asyncio.run(
            self.r.tools.invoke(
                nos_do_vendedor.contexto_de_tool(estado_de_vendedor("")),
                "get_order_status",
                {"referencia": "ABC-123"},
                allowed=nos_do_vendedor.TOOLS_DO_VENDEDOR,
            )
        )
        self.assertIsNotNone(do_vendedor)

    def test_as_Dependencias_sao_a_MESMA_classe(self) -> None:
        """Um tipo por vertical era a primeira divergencia (KAM-035).

        Esta pinado aqui e nao so na bateria de Servicos porque e uma
        propriedade **das duas**: se o Vendedor ganhar um `Dependencias`
        proprio, os doze nos importados deixam de receber o mesmo objecto.
        """
        self.assertIs(DependenciasDeServicos, DependenciasDoVendedor)

    def test_o_estado_partilhado_nao_nomeia_vertical_nenhuma(self) -> None:
        """A metade do criterio (d) que o *runtime* mostra.

        O `ConversaState` e atravessado pelas duas. Tem um campo `vertical` —
        que e **dado**, e e o que o §5.3 manda — e nao tem campo nenhum com o
        nome de uma vertical. Os dois nomes, e nao so um: o ensaio do KAM-035
        mede `servicos`, e um campo `cart_do_vendedor` passava por ele.
        """
        chaves = set(ConversaState.__annotations__)
        for proibido in ("vendedor", "servicos", "assistente"):
            self.assertEqual(
                [c for c in chaves if proibido in c.lower()],
                [],
                f"o estado partilhado ganhou um campo com `{proibido}` no nome",
            )
        self.assertIn("vertical", chaves)

    def test_as_duas_verticais_saiem_do_registo_e_nao_de_codigo(self) -> None:
        """«Verticais como configuracao»: a lista vem dos `registry/*.yaml`."""
        import pathlib

        from kamba_agr.registo import carregar
        from kamba_agr.registo.validar import AmbienteDoRegisto
        from kamba_agr.tls.catalogo import catalogo_do_piloto

        raiz = pathlib.Path(__file__).resolve().parents[3]
        ambiente = AmbienteDoRegisto.do_repositorio(raiz, catalogo=catalogo_do_piloto())
        verticais, _, _ = carregar(ambiente, raiz / "registry")
        self.assertEqual(sorted(verticais), ["servicos", "vendedor"])
        # E cada uma aponta para o **seu** `build_graph` pelo registo, sem que
        # nenhum codigo do nucleo escolha qual.
        self.assertEqual(
            verticais["servicos"].graph, "kamba_agr.verticais.servicos:build_graph"
        )
        self.assertEqual(
            verticais["vendedor"].graph, "kamba_agr.verticais.vendedor:build_graph"
        )


# ===========================================================================
# Criterio (b) — o evento do Vendedor consumido pelo handler de Servicos
# ===========================================================================


class _ComConsumidorDasDuas(unittest.TestCase):
    """O consumidor sobre a base falsa, com as **duas** verticais activas.

    O `monta` do `test_eventos.py` poe so o Vendedor por omissao, pela razao que
    a sua *docstring* da. Aqui passa-se a tabela inteira dos
    `registry/*.yaml`, que e o que o criterio (b) exige: o mesmo evento
    entregue as duas.
    """

    def setUp(self) -> None:
        from kamba_agr import metricas as m

        from test_eventos import (
            HndEspiao,
            OutboundEspiao,
            com_conversa,
            monta,
            tabela_do_registo,
        )

        m.METRICAS.repor()
        self.servidor = com_conversa()
        self.outbound = OutboundEspiao()
        self.hnd = HndEspiao()
        self.tabela = tabela_do_registo()
        self.consumidor = monta(
            self.servidor,
            outbound=self.outbound,
            hnd=self.hnd,
            tabela=self.tabela,
        )

    def entregar(self, corpo_da_entrega: dict):
        return asyncio.run(self.consumidor.entregar(corpo_da_entrega))


class TestCriterioBOsDoisEventosDePagamento(_ComConsumidorDasDuas):
    """Os **dois** tipos, e nao so o `payment.confirmed`.

    O criterio (b) nomeia `payment.confirmed` v1 **e**
    `payment.manual_confirmed` v1, e os dois tem de atravessar. O segundo e o
    unico caminho de pagamento que existe hoje (o `ManualProvider`, KAM-055), e
    o `registry/vendedor.yaml` escreve por extenso que quem nao distingue os
    dois caminhos subscreve os dois. A bateria do KAM-038 media so o primeiro.
    """

    TIPOS = ("payment.confirmed", "payment.manual_confirmed")

    def envelope_de(self, tipo: str) -> dict:
        """Um envelope valido **para este tipo**, e nao o do outro.

        Os dois contratos nao tem o mesmo *payload*: o
        `payment.manual_confirmed` nao permite `provider` nem `referencia` (nao
        ha provedor num pagamento confirmado a mao). Reaproveitar o *payload* do
        `payment.confirmed` dava um envelope **invalido** e o evento ia para a
        DLQ — e o teste falhava a dizer «o consumo cruzado nao funciona» quando
        o que nao funcionava era o ensaio. Medido ao escrever esta bateria.
        """
        from test_eventos import envelope_cru

        bruto = envelope_cru(tipo=tipo)
        if tipo == "payment.manual_confirmed":
            bruto["payload"] = {
                chave: valor
                for chave, valor in bruto["payload"].items()
                if chave not in ("provider", "referencia")
            }
        return bruto

    def test_os_dois_tipos_chegam_as_duas_verticais(self) -> None:
        from test_eventos import corpo

        for tipo in self.TIPOS:
            with self.subTest(tipo=tipo):
                self.setUp()
                desfecho = self.entregar(corpo(self.envelope_de(tipo)))
                self.assertEqual(
                    sorted(desfecho.por_consumidor),
                    [("agr_servicos", "sem_accao"), ("agr_vendedor", "aplicado")],
                )

    def test_os_dois_tipos_estao_subscritos_pelas_duas_verticais(self) -> None:
        """Pelo registo, e nao por codigo: e a forma do ADR-012."""
        for tipo in self.TIPOS:
            verticais = {c.vertical for c in self.tabela if c.tipo == tipo}
            self.assertEqual(verticais, {"servicos", "vendedor"}, tipo)

    def test_o_consumo_de_servicos_escreve_a_sua_linha_em_events_consumed(self) -> None:
        """«o *handler* registra o consumo idempotente», a letra do criterio.

        Duas linhas e nao uma: o `consumer` e por vertical (dicionario §3.33), e
        e isso que torna verdadeira a contagem «1 linha por vertical».
        """
        from test_eventos import corpo

        self.entregar(corpo())
        self.assertEqual(
            {consumidor for consumidor, _ in self.servidor.consumidos},
            {"agr_vendedor", "agr_servicos"},
        )

    def test_cinco_entregas_dao_UM_efeito(self) -> None:
        """O DoD: «consumo cruzado repetido 5 vezes produz 1 efeito» (ADR-009).

        Cinco e nao duas, porque e o numero que a linha do DoD escreve — e «>= 5
        execucoes» com duas nao esta cumprido.
        """
        from test_eventos import corpo

        desfechos = [self.entregar(corpo()) for _ in range(5)]

        self.assertEqual(len(self.servidor.consumidos), 2, "uma linha por vertical")
        self.assertEqual(len(self.outbound.chamadas), 1, "uma mensagem ao cliente")
        self.assertEqual(len(self.hnd.chamadas), 1, "um aviso ao dono")
        # A primeira entrega aplica; as quatro seguintes dizem `duplicado`.
        primeiro = dict(desfechos[0].por_consumidor)
        self.assertEqual(primeiro["agr_vendedor"], "aplicado")
        for seguinte in desfechos[1:]:
            self.assertEqual(dict(seguinte.por_consumidor)["agr_vendedor"], "duplicado")

    def test_o_contrato_v1_NAO_permite_booking_id_no_payload(self) -> None:
        """**Um achado, e nao uma confirmacao.** O efeito *proposta* nao cabe no v1.

        Os Detalhes Tecnicos do bloco dao o efeito *proposta* do consumo
        cruzado: «o *handler* de Servicos reage a
        `payment.confirmed`/`payment.manual_confirmed` **com `booking_id` no
        *payload***». Medido: os contratos publicados dos dois tipos **nao
        permitem** o `booking_id` —

        ```text
        payment.confirmed         permitidos: autenticacao, currency, order_id,
                                              provider, referencia, valor_minor
        payment.manual_confirmed  permitidos: autenticacao, currency, order_id,
                                              valor_minor
        ```

        — e a lista e fechada: um campo a mais torna o envelope invalido e o
        evento vai para a DLQ. Logo a segunda metade do criterio (b) **nao e
        implementavel como esta escrita** sem tocar no catalogo de esquemas, o
        que acrescenta o **KAM-007** aos credores, ao lado do KAM-047.

        O que se mede aqui e o facto, nos dois sentidos: o envelope com
        `booking_id` e recusado, e o mesmo envelope sem ele passa. Isto nao
        **reprova** o bus: mostra que ele faz o que promete — a lista de campos
        e fechada por desenho (§4). O que esta em falta e o campo, e o caminho
        para o obter esta escrito na seccao de verificacao do bloco.
        """
        from test_eventos import corpo

        com_booking = self.envelope_de("payment.confirmed")
        com_booking["payload"] = dict(
            com_booking["payload"], booking_id=com_booking["payload"]["order_id"]
        )
        recusado = self.entregar(corpo(com_booking))
        self.assertNotIn(
            "aplicado",
            [desfecho for _, desfecho in recusado.por_consumidor],
            "o contrato v1 passou a aceitar `booking_id`: o credor KAM-007 mudou "
            "de estado e a seccao de verificacao do KAM-039 tem de ser revista",
        )
        self.assertEqual(recusado.desfecho, "para_dlq")

        # **O par positivo**, para que a recusa de cima nao se leia como «o bus
        # rejeita tudo»: o mesmo envelope, sem o campo, atravessa.
        self.setUp()
        passou = self.entregar(corpo(self.envelope_de("payment.confirmed")))
        self.assertEqual(
            sorted(passou.por_consumidor),
            [("agr_servicos", "sem_accao"), ("agr_vendedor", "aplicado")],
        )


class TestCriterioBSemAlterarONucleo(_ComConsumidorDasDuas):
    """«sem alterar o bus, o envelope nem o `core/`», medido e nao afirmado."""

    def test_o_consumidor_e_o_do_KAM_038_e_nao_um_segundo(self) -> None:
        """Um bus por vertical era a violacao obvia do criterio (b).

        O que se mede e que **um** `ConsumidorDeEventos` serve as duas, e que a
        vertical lhe chega como **dado** na tabela de consumidores — nao como
        parametro de construcao nem como ramo.
        """
        from kamba_agr.eventos.consumo import ConsumidorDeEventos

        self.assertIsInstance(self.consumidor, ConsumidorDeEventos)
        verticais = {c.vertical for c in self.tabela}
        self.assertEqual(verticais, {"servicos", "vendedor"})
        # O `consumer` deriva-se do `id` da vertical e nao de uma lista
        # literal: uma vertical nova ganha consumidor sem passar por codigo.
        self.assertEqual(
            {subscricoes.nome_do_consumidor(v) for v in verticais},
            {"agr_servicos", "agr_vendedor"},
        )

    def test_nenhum_codigo_do_AGR_marca_a_encomenda_paga(self) -> None:
        """O DoD: «nenhum codigo marca `paga`» (ADR-013).

        Quem transita a encomenda e o COM e quem decide o pagamento e o PAY. O
        AGR consome o evento e nao aplica transicao nenhuma — e o
        `aplica_transicao=False` do `_correr_consumo`, medido pelo efeito: o
        consumo de um `payment.confirmed` passa **sem** maquina de estados.
        """
        import inspect

        from kamba_agr.eventos import consumo

        fonte = inspect.getsource(consumo.ConsumidorDeEventos._correr_consumo)
        self.assertIn("aplica_transicao=False", fonte)

        from test_eventos import corpo

        desfecho = self.entregar(corpo())
        self.assertEqual(dict(desfecho.por_consumidor)["agr_vendedor"], "aplicado")

    def test_a_accao_de_servicos_tem_credor_nomeado_e_e_o_KAM_047(self) -> None:
        """**O teste que pina a divida**, e o unico desta bateria que quer ficar
        vermelho um dia.

        A segunda metade do criterio (b) — «confirma a marcacao com sinal e
        agenda o lembrete» — **nao esta escrita**, e o credor esta no codigo:
        o `ACCOES_POR_LIGAR` do `eventos/handlers.py` nomeia o KAM-047 para os
        dois eventos de pagamento em Servicos. Quando o KAM-047 ligar a accao,
        esta linha fica vermelha e obriga a actualizar esta bateria — que e o
        contrario de uma divida que apodrece em silencio.
        """
        for tipo in ("payment.confirmed", "payment.manual_confirmed"):
            self.assertEqual(
                handlers.accao_por_ligar("servicos", tipo),
                "KAM-047",
                f"a accao de Servicos para {tipo} mudou de estado",
            )
        # E o Vendedor **tem** accao escrita para os dois: sem este par
        # positivo, um `accao_por_ligar` que devolvesse sempre um credor
        # passava o teste de cima.
        for tipo in ("payment.confirmed", "payment.manual_confirmed"):
            self.assertIsNone(handlers.accao_por_ligar("vendedor", tipo))

    def test_toda_a_subscricao_das_duas_verticais_tem_handler(self) -> None:
        """Uma subscricao sem *handler* era um consumidor calado.

        Corre sobre a tabela das **duas**: o `exige_handlers` e do KAM-038, e o
        que aqui se acrescenta e correr-lhe o registo inteiro em vez de o de uma
        vertical.
        """
        pares = tuple((c.vertical, c.tipo) for c in self.tabela)
        handlers.exigir_handlers(pares)  # nao levanta

    def test_um_par_sem_handler_levanta(self) -> None:
        """O canario do teste de cima: sem isto, ele passava por vazio."""
        with self.assertRaises(handlers.SemHandlerError):
            handlers.exigir_handlers((("vertical_inventada", "payment.confirmed"),))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
