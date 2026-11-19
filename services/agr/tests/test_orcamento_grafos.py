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


if __name__ == "__main__":
    unittest.main()
