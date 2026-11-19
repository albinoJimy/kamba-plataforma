"""O Orcamento expresso nos grafos (KAM-220): o «aceito» do cliente e os pendentes do dono.

O dominio e do KAM-123 (`test_orcamento.py`, e `db/tests_agr/test_quote_requests.py`
contra a base). Aqui mede-se a **ligacao**: o que o grafo do Vendedor faz com um
«aceito», e o que o grafo do dono mostra na primeira mensagem e a pedido. A porta
de orcamento e um duplo em memoria com a mesma forma da `PortaDeOrcamento`; a
semantica do `aceitavel` e do `fechado` e a do `UltimoPedido` real.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import re
import unittest
import uuid
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from kamba_agr.orcamento import regras
from kamba_agr.tls import orcamento as rep
from kamba_agr.verticais.dono import build_graph as grafo_do_dono
from kamba_agr.verticais.dono import nos as nos_do_dono
from kamba_agr.verticais.vendedor import arestas as tabela
from kamba_agr.verticais.vendedor import nos as nos_mod
from test_vendedor import Handoff, estado_de, montar

AGORA = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC)
HOJE = regras.hoje_em_luanda(AGORA)


def _ultimo(estado: str, validade: datetime.date | None = None, sku: str = "SKU-300") -> rep.UltimoPedido:
    return rep.UltimoPedido(
        quote_id=str(uuid.uuid4()),
        estado=estado,
        sku=sku,
        validade_ate=validade if validade is not None else HOJE + datetime.timedelta(days=3),
    )


class PortaEmMemoria:
    """A forma da `PortaDeOrcamento`: as leituras dos grafos, e nenhuma escrita.

    **Nao tem `pedir`, de proposito**: o criterio 9 diz que o «aceito» nao cria
    pedido, e um duplo sem a operacao faz qualquer tentativa rebentar o turno.
    """

    def __init__(self, ultimo: rep.UltimoPedido | None = None, pendentes: list | None = None) -> None:
        self.ultimo = ultimo
        self._pendentes = list(pendentes or ())
        self.leituras: list[tuple[str, ...]] = []
        self.rebenta = False

    async def ultimo_pedido(self, tenant_id: str, contact_id: str):
        self.leituras.append(("ultimo", tenant_id, contact_id))
        return self.ultimo

    async def pendentes(self, tenant_id: str, limite: int = 5):
        self.leituras.append(("pendentes", tenant_id))
        if self.rebenta:
            raise RuntimeError("base em baixo")
        return self._pendentes[:limite]

    def agora(self) -> datetime.datetime:
        return AGORA


def _pendente(sku: str = "SKU-300") -> rep.Pendente:
    quote_id = str(uuid.uuid4())
    return rep.Pendente(
        quote_id=quote_id,
        referencia=regras.referencia_interna(quote_id),
        sku=sku,
        quantidade=12,
        estado=regras.PEDIDO,
        criado_at=AGORA,
    )


# ------------------------------------------------------------------ o «aceito»


class TestOAceitoDoCliente(unittest.TestCase):
    """Criterio 4 do KAM-220 e 9 do KAM-123: o «aceito» vai ao dono e nao cria pedido."""

    def _turno(self, porta: PortaEmMemoria, texto: str = "aceito", **troca: Any):
        hnd = Handoff()
        grafo, _deps, backend, saida, _ = montar(
            hnd=hnd, checkpointer=InMemorySaver(), orcamentos=porta
        )
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        estado = asyncio.run(grafo.ainvoke(estado_de(texto, **troca), config))
        return estado, hnd, saida, backend

    def test_uma_proposta_enviada_e_valida_vai_ao_dono_com_a_referencia(self) -> None:
        ultimo = _ultimo(regras.ENVIADO)
        estado, hnd, saida, backend = self._turno(PortaEmMemoria(ultimo))
        self.assertEqual(len(hnd.recebido), 1)
        recebido = hnd.recebido[0]
        self.assertEqual(recebido["motivo"], nos_mod.MOTIVO_ORCAMENTO_ACEITE)
        self.assertIn(f"orcamento={ultimo.referencia}", recebido["resumo"])
        # O contexto nao leva o valor, nem o `quote_id`, nem o texto do cliente.
        self.assertNotIn(ultimo.quote_id, recebido["resumo"])
        self.assertIsNone(re.search(r"\d", recebido["resumo"]))
        self.assertNotIn("aceito", recebido["resumo"].replace("orcamento_aceite", ""))
        # E nenhuma tool correu: nem pesquisa nem pedido.
        self.assertEqual(backend.chamadas, {})
        self.assertEqual(estado["handoff"]["status"], "waiting")
        self.assertIn("passar a conversa", saida.textos[0])

    def test_o_botao_aceitar_e_o_mesmo_caminho(self) -> None:
        porta = PortaEmMemoria(_ultimo(regras.ENVIADO))
        _estado, hnd, _saida, _ = self._turno(
            porta, nos_mod.BOTAO_ACEITAR_ORCAMENTO, tipo="interactive"
        )
        self.assertEqual([r["motivo"] for r in hnd.recebido], [nos_mod.MOTIVO_ORCAMENTO_ACEITE])

    def test_expirado_cancelado_ou_vencido_nao_se_aceitam(self) -> None:
        ontem = HOJE - datetime.timedelta(days=1)
        casos = {
            "expirado": _ultimo(regras.EXPIRADO),
            "cancelado": _ultimo(regras.CANCELADO),
            "enviado e vencido": _ultimo(regras.ENVIADO, validade=ontem),
        }
        for nome, ultimo in casos.items():
            with self.subTest(caso=nome):
                estado, hnd, saida, backend = self._turno(PortaEmMemoria(ultimo))
                self.assertEqual(hnd.recebido, [])
                self.assertEqual(len(saida.textos), 1)
                self.assertIn(nos_mod.FRASE_DO_AVISO[tabela.ORCAMENTO_FECHADO], saida.textos[0])
                self.assertEqual(backend.chamadas, {})
                self.assertIsNone(estado.get("handoff"))

    def test_antes_da_proposta_o_aceito_diz_que_esta_em_curso(self) -> None:
        for estado_do_pedido in (regras.PEDIDO, regras.RESPONDIDO, regras.AGUARDA_JANELA):
            with self.subTest(estado=estado_do_pedido):
                _estado, hnd, saida, _ = self._turno(PortaEmMemoria(_ultimo(estado_do_pedido)))
                self.assertEqual(hnd.recebido, [])
                self.assertEqual(len(saida.textos), 1)
                self.assertIn(nos_mod.FRASE_DO_AVISO[tabela.ORCAMENTO_EM_CURSO], saida.textos[0])

    def test_sem_pedido_nenhum_o_aceito_segue_o_fluxo_normal(self) -> None:
        _estado, hnd, saida, _ = self._turno(PortaEmMemoria(None))
        self.assertEqual(hnd.recebido, [])
        self.assertEqual(len(saida.textos), 1)
        for aviso in tabela.AVISOS_DO_ORCAMENTO:
            self.assertNotIn(nos_mod.FRASE_DO_AVISO[aviso], saida.textos[0])

    def test_sem_porta_o_aceito_segue_o_fluxo_normal(self) -> None:
        hnd = Handoff()
        grafo, *_ = montar(hnd=hnd, checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        asyncio.run(grafo.ainvoke(estado_de("aceito"), config))
        self.assertEqual(hnd.recebido, [])

    def test_a_negacao_nao_e_aceitacao(self) -> None:
        for texto in ("nao aceito", "não aceito isso", "nao o aceito", "aceitavel?"):
            with self.subTest(texto=texto):
                self.assertFalse(nos_mod.pediu_para_aceitar(texto))
        for texto in ("aceito", "Aceito!", "ok, aceito o orcamento", "esta aceite"):
            with self.subTest(texto=texto):
                self.assertTrue(nos_mod.pediu_para_aceitar(texto))

    def test_um_aceito_de_outro_cliente_nao_se_le(self) -> None:
        """A porta e lida com o tenant e o contacto **do estado**, e nunca do texto."""
        porta = PortaEmMemoria(None)
        estado, *_ = self._turno(porta, "aceito o ORC-ABCDEFGH do meu vizinho")
        self.assertEqual(porta.leituras, [("ultimo", estado["tenant_id"], estado["contact_id"])])

    def test_as_frases_do_orcamento_estao_no_dominio_e_sem_digitos(self) -> None:
        for aviso in tabela.AVISOS_DO_ORCAMENTO:
            with self.subTest(aviso=aviso):
                self.assertIn(aviso, tabela.AVISOS)
                frase = nos_mod.FRASE_DO_AVISO[aviso]
                self.assertIsNone(re.search(r"\d", frase))
                self.assertIsNone(nos_mod.violacao_de_saida(frase))
        self.assertIn(nos_mod.MOTIVO_ORCAMENTO_ACEITE, nos_mod.MOTIVOS_DE_HANDOFF)


class TestUltimoPedido(unittest.TestCase):
    def test_so_um_enviado_dentro_da_validade_se_aceita(self) -> None:
        self.assertTrue(_ultimo(regras.ENVIADO, validade=HOJE).aceitavel(AGORA))
        self.assertFalse(_ultimo(regras.ENVIADO, validade=HOJE - datetime.timedelta(days=1)).aceitavel(AGORA))
        for estado in (regras.PEDIDO, regras.RESPONDIDO, regras.AGUARDA_JANELA, regras.EXPIRADO, regras.CANCELADO):
            with self.subTest(estado=estado):
                self.assertFalse(_ultimo(estado).aceitavel(AGORA))

    def test_fechado_e_final_ou_vencido(self) -> None:
        self.assertTrue(_ultimo(regras.EXPIRADO).fechado(AGORA))
        self.assertTrue(_ultimo(regras.CANCELADO).fechado(AGORA))
        self.assertTrue(_ultimo(regras.ENVIADO, validade=HOJE - datetime.timedelta(days=1)).fechado(AGORA))
        for estado in (regras.PEDIDO, regras.RESPONDIDO, regras.AGUARDA_JANELA, regras.ENVIADO):
            with self.subTest(estado=estado):
                self.assertFalse(_ultimo(estado).fechado(AGORA))


# ------------------------------------------------------------------ os pendentes


class TestPendentesDoDono(unittest.TestCase):
    """Criterio 5 do KAM-220 e 2 do KAM-123: os pendentes na primeira mensagem do dono."""

    def _turno(self, porta: Any, texto: str, *, ja_falamos: bool = False) -> tuple[dict, list[str]]:
        _g, deps, backend, saida, _ = montar()
        deps = dataclasses.replace(deps, orcamentos=porta, tools_permitidas=nos_do_dono.TOOLS_DO_DONO)
        grafo = grafo_do_dono(deps)
        estado = estado_de(texto, persona="dono")
        if ja_falamos:
            estado["messages"] = [
                {"role": "assistant", "content": "Bom dia."},
                {"role": "user", "content": texto},
            ]
        final = asyncio.run(grafo.ainvoke(estado))
        self.backend = backend
        return final, saida.textos

    def test_a_primeira_mensagem_mostra_os_pendentes_sem_valor_nem_quantidade(self) -> None:
        pendentes = [_pendente("SKU-300"), _pendente("SKU-301")]
        final, textos = self._turno(PortaEmMemoria(pendentes=pendentes), "bom dia")
        self.assertEqual(final["intent"], "orcamento")
        self.assertEqual(len(textos), 1)
        texto = textos[0]
        self.assertIn(nos_do_dono.MSG_PENDENTES, texto)
        for pendente in pendentes:
            self.assertIn(pendente.referencia, texto)
            self.assertIn(pendente.sku, texto)
        # Os unicos digitos sao os dos `sku`: nem a quantidade nem um valor.
        sem_skus = texto.replace("SKU-300", "").replace("SKU-301", "")
        self.assertIsNone(re.search(r"\d", sem_skus))
        self.assertTrue(final["draft"]["ok"])

    def test_sem_pendentes_a_primeira_mensagem_segue_o_caminho_de_sempre(self) -> None:
        final, textos = self._turno(PortaEmMemoria(pendentes=[]), "bom dia")
        self.assertEqual(final["intent"], "outro")
        self.assertEqual(len(textos), 1)
        self.assertIn(nos_do_dono.MSG_FORA_DE_AMBITO, textos[0])

    def test_depois_da_primeira_so_a_pedido(self) -> None:
        porta = PortaEmMemoria(pendentes=[_pendente()])
        final, textos = self._turno(porta, "bom dia", ja_falamos=True)
        self.assertEqual(final["intent"], "outro")
        final, textos = self._turno(porta, "que pedidos de orcamento tenho pendentes?", ja_falamos=True)
        self.assertEqual(final["intent"], "orcamento")
        self.assertIn(nos_do_dono.MSG_PENDENTES, textos[0])

    def test_um_pedido_de_humano_ou_de_informacao_nao_e_trocado_pelos_pendentes(self) -> None:
        porta = PortaEmMemoria(pendentes=[_pendente()])
        final, _ = self._turno(porta, "qual e o horario da loja?")
        self.assertEqual(final["intent"], "info_loja")

    def test_a_pedido_sem_pendentes_diz_que_nao_ha(self) -> None:
        _final, textos = self._turno(PortaEmMemoria(pendentes=[]), "tenho orcamentos pendentes?")
        self.assertIn(nos_do_dono.MSG_SEM_PENDENTES, textos[0])

    def test_a_base_em_baixo_diz_se_e_nao_rebenta(self) -> None:
        porta = PortaEmMemoria(pendentes=[_pendente()])
        porta.rebenta = True
        final, textos = self._turno(porta, "tenho orcamentos pendentes?")
        self.assertIn(nos_do_dono.MSG_PENDENTES_INDISPONIVEIS, textos[0])
        # E na primeira mensagem, uma leitura que falha deixa o cumprimento como estava.
        final, textos = self._turno(porta, "bom dia")
        self.assertEqual(final["intent"], "outro")

    def test_sem_porta_diz_que_nao_consegue_ver(self) -> None:
        _final, textos = self._turno(None, "tenho orcamentos pendentes?")
        self.assertIn(nos_do_dono.MSG_PENDENTES_INDISPONIVEIS, textos[0])

    def test_os_pendentes_leem_se_do_tenant_do_estado(self) -> None:
        porta = PortaEmMemoria(pendentes=[_pendente()])
        final, _ = self._turno(porta, "pendentes")
        self.assertEqual({l[1] for l in porta.leituras}, {final["tenant_id"]})

    def test_a_lista_tem_o_tecto_e_nao_chama_tool(self) -> None:
        porta = PortaEmMemoria(pendentes=[_pendente(f"SKU-{300 + i}") for i in range(9)])
        _final, textos = self._turno(porta, "pendentes")
        self.assertEqual(textos[0].count("ORC-"), nos_do_dono.LIMITE_DE_PENDENTES)
        self.assertEqual(self.backend.chamadas, {})




# ------------------------------------------------------------------ o passo 4


from unittest import mock

from pydantic import BaseModel, ConfigDict

from kamba_agr.tls import orcamento_tools
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.catalogo import (
    RAZAO_DA_DISPENSA_DO_SUBMIT,
    catalogo_do_piloto,
    especificacoes_do_piloto,
    get_store_info,
)
from kamba_agr.tls.contexto import Confirmation
from kamba_agr.tls.especificacoes import (
    DISPENSAS_DO_PASSO_4,
    Catalogo,
    EspecificacaoDeTool,
    EspecificacaoInvalidaError,
    Resposta,
)
from kamba_agr.tls.vendedor import especificacoes_do_vendedor
from kamba_agr.verticais.vendedor import build_graph as grafo_do_vendedor
from kamba_agr.verticais.vendedor import encaminhadores as enc
from kamba_agr.verticais.vendedor.fakes import BackendDeEnsaio
from test_tls import _Ligacao
from test_vendedor import LOJA, PERSONA, Relogio, Saida


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: str = ""


def _executor_nulo(_pedido):
    return Resposta(data={})


class TestDispensaDoPasso4(unittest.TestCase):
    """Decisao do fundador de 2026-11-19 (KAM-220, opcao C): a dispensa e fechada."""

    def _spec(self, **troca: Any) -> EspecificacaoDeTool:
        base: dict[str, Any] = {
            "nome": "submit_quote",
            "klass": "write",
            "backend": "plataforma",
            "modelo": _Args,
            "executor": _executor_nulo,
            "confirmacao_dispensada": "so grava",
        }
        base.update(troca)
        return EspecificacaoDeTool(**base)

    def test_a_lista_e_so_o_submit_quote(self) -> None:
        self.assertEqual(DISPENSAS_DO_PASSO_4, ("submit_quote",))

    def test_uma_write_sem_campo_e_sem_dispensa_continua_recusada(self) -> None:
        for nome in ("submit_quote", "book_slot"):
            with self.subTest(nome=nome), self.assertRaises(EspecificacaoInvalidaError):
                self._spec(nome=nome, confirmacao_dispensada=None)

    def test_a_dispensa_so_vale_nas_condicoes_todas(self) -> None:
        casos = {
            "nome fora da lista": {"nome": "book_slot"},
            "money": {"klass": "money"},
            "read": {"klass": "read"},
            "razao vazia": {"confirmacao_dispensada": "   "},
            "dispensa e campo": {"campo_de_confirmacao": "quote_id"},
            "declarada": {"modelo": None, "executor": None, "credor": "KAM-220"},
        }
        for nome, troca in casos.items():
            with self.subTest(caso=nome), self.assertRaises(EspecificacaoInvalidaError):
                self._spec(**troca)

    def test_com_a_dispensa_o_passo_4_nao_se_aplica(self) -> None:
        spec = self._spec()
        self.assertFalse(spec.exige_confirmacao)
        self.assertTrue(self._spec(confirmacao_dispensada=None, campo_de_confirmacao="quote_id").exige_confirmacao)

    def test_no_catalogo_o_pedido_cita_o_sku_e_a_resposta_e_dispensada(self) -> None:
        catalogo = catalogo_do_piloto(orcamento_tools.executores())
        pedido, resposta = catalogo["request_quote"], catalogo["submit_quote"]
        self.assertTrue(pedido.ligada and resposta.ligada)
        self.assertEqual((pedido.campo_de_confirmacao, pedido.exige_confirmacao), ("sku", True))
        self.assertEqual(resposta.confirmacao_dispensada, RAZAO_DA_DISPENSA_DO_SUBMIT)
        self.assertFalse(resposta.exige_confirmacao)
        self.assertEqual({pedido.modulo, resposta.modulo}, {"orcamento"})
        for spec in (pedido, resposta):
            self.assertNotIn("tenant_id", spec.parametros_visiveis())
            self.assertNotIn("contact_id", spec.parametros_visiveis())
        # Sem executores, continuam declaradas com o credor; so uma, recusa-se.
        self.assertFalse(catalogo_do_piloto()["request_quote"].ligada)
        with self.assertRaises(ValueError):
            especificacoes_do_piloto({"request_quote": _executor_nulo})


# ------------------------------------------------------------------ o pedido do cliente


class _Pedidos:
    """O executor do `request_quote` de ensaio: regista e devolve o mesmo pedido."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []
        self.quote_id = str(uuid.uuid4())

    def __call__(self, pedido):
        self.chamadas.append({"args": pedido.args.model_dump(), "contacto": pedido.ctx.contact_id})
        return Resposta(
            data={"quote_id": self.quote_id, "referencia": regras.referencia_interna(self.quote_id), "novo": True}
        )


def _vendedor(pedidos: _Pedidos, porta: Any = None, relogio: Relogio | None = None):
    backend = BackendDeEnsaio()
    saida = Saida()
    ligacao = _Ligacao(outro=LOJA)
    especificacoes = especificacoes_do_vendedor(backend.executores()) + (
        EspecificacaoDeTool(
            nome="get_store_info",
            klass="read",
            backend="plataforma",
            modelo=get_store_info.ArgumentosDeGetStoreInfo,
            executor=get_store_info.executar,
        ),
        EspecificacaoDeTool(
            nome="request_quote",
            klass="write",
            backend="plataforma",
            modelo=orcamento_tools.ArgumentosDeRequestQuote,
            executor=pedidos,
            campo_de_confirmacao="sku",
            modulo="orcamento",
        ),
    )
    camada = ToolLayer(Catalogo(especificacoes), abrir_ligacao=ligacao.nova_vaga)
    deps = nos_mod.Dependencias(
        tools=camada,
        saida=saida,
        persona=PERSONA,
        relogio=relogio or Relogio(),
        checkpointer=InMemorySaver(),
        orcamentos=porta,
    )
    return grafo_do_vendedor(deps), saida, deps


class _Conversa:
    """Turnos sobre o mesmo `thread_id`, como o processo os corre."""

    def __init__(self, grafo: Any) -> None:
        self.grafo = grafo
        self.config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        self.tenant = str(uuid.uuid4())
        self.contacto = str(uuid.uuid4())

    def turno(self, texto: str, *, tipo: str = "text") -> dict[str, Any]:
        estado = estado_de(texto, tipo=tipo, tenant_id=self.tenant, contact_id=self.contacto)
        return asyncio.run(self.grafo.ainvoke(estado, self.config))


def _sem_linhas_de_item(texto: str) -> str:
    """O texto sem as linhas `item`, cujos numeros (o *stock*) sao de um *fact*.

    O que se procura e um numero **sem** *fact*: uma conta, um desconto, um total.
    A linha de um `item` e do *renderer* do KAM-032, e o validador ja a conferiu.
    """
    return chr(10).join(linha for linha in texto.splitlines() if not linha.startswith("SKU-"))


class TestOPedidoDoCliente(unittest.TestCase):
    """Criterio 2 do KAM-220 e 1 e 6 do KAM-123: pede-se ao dono, e nunca se calcula."""

    def test_o_preco_de_um_sob_consulta_oferece_o_botao_e_o_toque_pede(self) -> None:
        pedidos = _Pedidos()
        grafo, saida, _ = _vendedor(pedidos)
        conversa = _Conversa(grafo)
        primeiro = conversa.turno("quanto custa o fato por medida?")
        self.assertEqual(pedidos.chamadas, [])
        texto, _chave, botoes = saida.enviadas[-1]
        self.assertIn("sob consulta", texto)
        self.assertIn(nos_mod.MSG_ORCAMENTO_OFERTA, texto)
        self.assertEqual(botoes, ("confirm:SKU-300", nos_mod.BOTAO_HUMANO))
        self.assertIsNone(re.search(r"\d", _sem_linhas_de_item(texto)))
        self.assertEqual(primeiro["orcamento_oferecido"]["sku"], "SKU-300")
        segundo = conversa.turno("confirm:SKU-300", tipo="interactive")
        self.assertEqual(pedidos.chamadas, [{"args": {"sku": "SKU-300", "quantidade": None},
                                             "contacto": conversa.contacto}])
        self.assertIn(nos_mod.FRASE_DO_AVISO[tabela.ORCAMENTO_PEDIDO], saida.textos[-1])
        self.assertIsNone(re.search(r"\d", saida.textos[-1]))
        self.assertTrue(segundo["draft"]["ok"])

    def test_calcula_doze_unidades_leva_a_quantidade_e_nao_calcula(self) -> None:
        pedidos = _Pedidos()
        grafo, saida, _ = _vendedor(pedidos)
        conversa = _Conversa(grafo)
        conversa.turno("calcula 12 unidades do fato por medida")
        texto = saida.textos[-1]
        self.assertIn(nos_mod.MSG_ORCAMENTO_OFERTA, texto)
        self.assertIsNone(re.search(r"\d", _sem_linhas_de_item(texto)))
        self.assertNotIn("12", texto)
        conversa.turno("confirm:SKU-300", tipo="interactive")
        self.assertEqual(pedidos.chamadas[0]["args"], {"sku": "SKU-300", "quantidade": 12})

    def test_cem_pedidos_de_conta_dao_zero_numeros_calculados(self) -> None:
        """«calcula», «desconto», «total»: em cem frases, nenhuma resposta tem um numero."""
        porta = PortaEmMemoria(_ultimo(regras.ENVIADO))
        formas = (
            "calcula {q} unidades do fato por medida",
            "e com {q}% de desconto?",
            "quanto fica {q} fatos por medida?",
            "faz a conta para {q} unidades",
            "qual e o total de {q} fatos por medida?",
            "e com {q} por cento de desconto?",
            "fazes um abatimento de {q} mil?",
            "o fato por medida mais barato para {q} unidades?",
            "quanto sai {q} unidades?",
            "preco para {q} unidades do fato por medida",
        )
        frases = [forma.format(q=q) for forma in formas for q in range(2, 12)]
        self.assertEqual(len(frases), 100)
        com_numero = []
        sem_oferta = []
        for frase in frases:
            grafo, saida, _ = _vendedor(_Pedidos(), porta)
            final = _Conversa(grafo).turno(frase)
            texto = saida.textos[-1]
            if re.search(r"\d", _sem_linhas_de_item(texto)) or not final["draft"]["ok"]:
                com_numero.append(frase)
            if final.get("orcamento_oferecido", {}).get("sku") != "SKU-300":
                sem_oferta.append(frase)
        self.assertEqual(com_numero, [])
        self.assertEqual(sem_oferta, [])

    def test_um_botao_forjado_ou_vencido_nao_pede(self) -> None:
        pedidos = _Pedidos()
        relogio = Relogio()
        grafo, saida, deps = _vendedor(pedidos, relogio=relogio)
        conversa = _Conversa(grafo)
        conversa.turno("confirm:SKU-300", tipo="interactive")
        conversa.turno("quanto custa o fato por medida?")
        conversa.turno("confirm:SKU-100", tipo="interactive")
        relogio.avancar(deps.ttl_do_carrinho_s + 1)
        conversa.turno("confirm:SKU-300", tipo="interactive")
        self.assertEqual(pedidos.chamadas, [])

    def test_um_segundo_toque_nao_pede_outra_vez(self) -> None:
        """O passo 5 devolve o resultado guardado, e a frase e a mesma.

        E a primeira das duas barreiras: a segunda e a da base (dez minutos, por
        contacto e `sku`), medida em `db/tests_agr/test_quote_requests.py`.
        """
        pedidos = _Pedidos()
        grafo, saida, _ = _vendedor(pedidos)
        conversa = _Conversa(grafo)
        conversa.turno("quanto custa o fato por medida?")
        conversa.turno("confirm:SKU-300", tipo="interactive")
        conversa.turno("confirm:SKU-300", tipo="interactive")
        self.assertEqual(len(pedidos.chamadas), 1)
        frase = nos_mod.FRASE_DO_AVISO[tabela.ORCAMENTO_PEDIDO]
        self.assertIn(frase, saida.textos[-1])
        self.assertIn(frase, saida.textos[-2])

    def test_um_produto_com_preco_nao_oferece_orcamento(self) -> None:
        pedidos = _Pedidos()
        grafo, saida, _ = _vendedor(pedidos)
        final = _Conversa(grafo).turno("quanto custa a camisa azul?")
        self.assertNotIn(nos_mod.MSG_ORCAMENTO_OFERTA, saida.textos[-1])
        self.assertIsNone(final.get("orcamento_oferecido"))

    def test_o_encaminhador_so_vai_ao_pedido_no_turno_do_toque(self) -> None:
        oferecido = {"sku": "SKU-300", "tocado_em": "t-2"}
        self.assertEqual(enc.r_confirm({"orcamento_oferecido": oferecido, "turn_id": "t-2"}), "orcamento")
        self.assertEqual(enc.r_confirm({"orcamento_oferecido": oferecido, "turn_id": "t-3"}), "go")
        self.assertEqual(
            enc.r_confirm({"orcamento_oferecido": oferecido, "turn_id": "t-2", "avisos": ("STALE_CONFIRMATION",)}),
            "stale",
        )

    def test_sem_o_botao_a_camada_recusa_o_pedido(self) -> None:
        pedidos = _Pedidos()
        _grafo, _saida, deps = _vendedor(pedidos)
        estado = estado_de("x")
        from kamba_agr.verticais.vendedor.nos import contexto_de_tool

        ctx = contexto_de_tool(estado)
        sem = asyncio.run(deps.tools.invoke(ctx, "request_quote", {"sku": "SKU-300"}, allowed=["request_quote"]))
        outro = asyncio.run(
            deps.tools.invoke(
                ctx,
                "request_quote",
                {"sku": "SKU-300"},
                allowed=["request_quote"],
                confirmation=Confirmation(botao="confirm:SKU-300", contact_id=str(uuid.uuid4()), turn_id=ctx.turn_id),
                idempotency_key="k",
            )
        )
        self.assertEqual((sem.ok, sem.error.codigo), (False, "VALIDATION_ERROR"))
        self.assertEqual((outro.ok, outro.error.codigo), (False, "TENANT_MISMATCH"))
        self.assertEqual(pedidos.chamadas, [])


# ------------------------------------------------------------------ a resposta do dono


class PortaDoDono(PortaEmMemoria):
    """Os pendentes do dono; a referencia resolve-se no executor, pelo `por_referencia`."""

    def __init__(self, pendentes: list, por_ref: dict[str, str] | None = None) -> None:
        super().__init__(pendentes=pendentes)
        self.por_ref = dict(por_ref or {})


class TestARespostaDoDono(unittest.TestCase):
    """Criterio 3 do KAM-220: o texto do dono ao `submit_quote`, com o eco e o botao."""

    def setUp(self) -> None:
        self.respostas: list[tuple] = []

        def responder(_ligacao, tenant, contacto, quote_id, valor_minor, validade, condicoes, agora):
            self.respostas.append((tenant, contacto, quote_id, valor_minor))
            validade = validade or regras.validade_por_omissao(agora)
            previsao = rep.texto_da_proposta(quote_id, "SKU-300", valor_minor, validade, condicoes, agora)
            return rep.Resposta(quote_id, valor_minor, validade, condicoes, "a" * 8 + "-1111-4111-8111-" + "1" * 12,
                                previsao, sku="SKU-300")

        self.por_ref: dict[str, str] = {}
        for alvo, substituto in (
            ("responder", responder),
            ("por_referencia", lambda _l, _t, referencia: self.por_ref.get(referencia)),
        ):
            remendo = mock.patch.object(rep, alvo, substituto)
            remendo.start()
            self.addCleanup(remendo.stop)

    def _turno(self, porta: Any, texto: str) -> tuple[dict, str, tuple]:
        self.por_ref.update(getattr(porta, "por_ref", {}))
        for pendente in getattr(porta, "_pendentes", ()):
            self.por_ref.setdefault(pendente.referencia, pendente.quote_id)
        backend = BackendDeEnsaio()
        saida = Saida()
        ligacao = _Ligacao(outro=LOJA)
        especificacoes = (
            EspecificacaoDeTool(
                nome="get_store_info",
                klass="read",
                backend="plataforma",
                modelo=get_store_info.ArgumentosDeGetStoreInfo,
                executor=get_store_info.executar,
            ),
            catalogo_do_piloto(orcamento_tools.executores(lambda: AGORA))["submit_quote"],
        )
        del backend
        camada = ToolLayer(Catalogo(especificacoes), abrir_ligacao=ligacao.nova_vaga)
        deps = nos_mod.Dependencias(
            tools=camada,
            saida=saida,
            persona=PERSONA,
            orcamentos=porta,
            tools_permitidas=nos_do_dono.TOOLS_DO_DONO,
        )
        final = asyncio.run(grafo_do_dono(deps).ainvoke(estado_de(texto, persona="dono")))
        texto_enviado, _chave, botoes = saida.enviadas[-1]
        return final, texto_enviado, botoes

    def test_um_valor_com_um_so_pendente_da_o_eco_e_o_botao(self) -> None:
        pendente = _pendente()
        final, texto, botoes = self._turno(PortaDoDono([pendente]), "120 mil")
        self.assertEqual(final["intent"], "responder_orcamento")
        self.assertEqual([r[2:] for r in self.respostas], [(pendente.quote_id, 12_000_000)])
        self.assertEqual(self.respostas[0][:2], (final["tenant_id"], final["contact_id"]))
        self.assertIn(nos_do_dono.MSG_ECO, texto)
        self.assertIn(regras.ROTULO, texto)
        self.assertIn("120 000", texto)
        self.assertEqual(len(botoes), 1)
        self.assertTrue(botoes[0].startswith("confirm:"))

    def test_com_a_referencia_vai_ao_pedido_dela(self) -> None:
        a, b = _pendente(), _pendente("SKU-301")
        porta = PortaDoDono([a, b], {b.referencia: b.quote_id})
        self._turno(porta, f"120.000 Kz para o {b.referencia}")
        self.assertEqual([r[2] for r in self.respostas], [b.quote_id])

    def test_sem_referencia_e_com_dois_pendentes_pergunta_qual(self) -> None:
        _final, texto, botoes = self._turno(PortaDoDono([_pendente(), _pendente("SKU-301")]), "120 mil")
        self.assertIn(nos_do_dono.MSG_QUAL_PEDIDO, texto)
        self.assertEqual((self.respostas, botoes), ([], ()))

    def test_uma_referencia_de_outro_tenant_ou_inventada_nao_responde(self) -> None:
        _final, texto, _ = self._turno(PortaDoDono([_pendente()]), "120 mil ORC-ABCDEFGH")
        self.assertIn(nos_do_dono.MSG_PEDIDO_NAO_ENCONTRADO, texto)
        self.assertEqual(self.respostas, [])

    def test_um_valor_curto_nao_rebenta_a_auditoria(self) -> None:
        """«8» casava os digitos do `quote_id`, que e o `fact_id` do `quote_price`."""
        pendente = _pendente()
        _final, texto, botoes = self._turno(PortaDoDono([pendente]), "8")
        self.assertIn(nos_do_dono.MSG_ECO, texto)
        self.assertEqual([r[3] for r in self.respostas], [800])
        self.assertEqual(len(botoes), 1)

    def test_um_valor_ambiguo_pede_para_reescrever(self) -> None:
        for valor in ("120 50 ORC-ABCDEFGH", "1 200.000 ORC-ABCDEFGH", "12.5 ORC-ABCDEFGH"):
            with self.subTest(valor=valor):
                pendente = _pendente()
                porta = PortaDoDono([pendente], {"ORC-ABCDEFGH": pendente.quote_id})
                _final, texto, botoes = self._turno(porta, valor)
                self.assertIn(nos_do_dono.MSG_VALOR_POR_REESCREVER, texto)
                self.assertEqual(botoes, ())
        self.assertEqual(self.respostas, [])

    def test_uma_conta_do_dono_nao_e_resposta_nem_se_calcula(self) -> None:
        self.assertFalse(nos_do_dono.e_resposta_de_orcamento("12 x 10 mil"))
        self.assertFalse(nos_do_dono.e_resposta_de_orcamento("dez mil cada"))
        pendente = _pendente()
        porta = PortaDoDono([pendente], {"ORC-ABCDEFGH": pendente.quote_id})
        _final, texto, _ = self._turno(porta, "12 x 10 mil ORC-ABCDEFGH")
        self.assertIn(nos_do_dono.MSG_VALOR_POR_REESCREVER, texto)
        self.assertEqual(self.respostas, [])

    def test_os_textos_novos_do_dono_nao_levam_digitos(self) -> None:
        for nome in ("MSG_ECO", "MSG_ECO_BOTAO", "MSG_VALOR_POR_REESCREVER", "MSG_QUAL_PEDIDO",
                     "MSG_PEDIDO_FECHADO", "MSG_SEM_MODULO_DE_ORCAMENTO"):
            with self.subTest(nome=nome):
                self.assertIsNone(re.search(r"\d", getattr(nos_do_dono, nome)))


class TestOBotaoDaInvocacao(unittest.TestCase):
    """O `agent_invocation.botao` chega ao Vendedor, com a janela vazia como no processo."""

    def test_o_pedir_orcamento_e_o_aceito_chegam_pelo_campo_da_invocacao(self) -> None:
        pedidos = _Pedidos()
        grafo, saida, _ = _vendedor(pedidos)
        conversa = _Conversa(grafo)
        conversa.turno("quanto custa o fato por medida?")
        estado = estado_de("", tipo="interactive", tenant_id=conversa.tenant, contact_id=conversa.contacto,
                           botao="confirm:SKU-300")
        self.assertEqual(estado["messages"], [])
        asyncio.run(grafo.ainvoke(estado, conversa.config))
        self.assertEqual(len(pedidos.chamadas), 1)

        porta = PortaEmMemoria(_ultimo(regras.ENVIADO))
        hnd = Handoff()
        grafo, *_ = montar(hnd=hnd, checkpointer=InMemorySaver(), orcamentos=porta)
        estado = estado_de("", tipo="interactive", botao=nos_mod.BOTAO_ACEITAR_ORCAMENTO)
        asyncio.run(grafo.ainvoke(estado, {"configurable": {"thread_id": str(uuid.uuid4())}}))
        self.assertEqual([r["motivo"] for r in hnd.recebido], [nos_mod.MOTIVO_ORCAMENTO_ACEITE])


if __name__ == "__main__":
    unittest.main()
