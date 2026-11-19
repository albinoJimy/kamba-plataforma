"""O Orcamento expresso contra o PostgreSQL (KAM-123).

O que os duplos de `services/agr/tests/test_orcamento.py` nao provam, e so a
base diz:

| Propriedade | Porque precisa da base |
|---|---|
| reenviar o pedido em dez minutos da o **mesmo** `quote_id`, 1 linha, 1 `quote.requested` | a tranca consultiva e a transaccao que junta linha, evento e consumo |
| duas mensagens concorrentes dao **um** pedido | a tranca, entre duas sessoes |
| duplo toque no botao -> **1** mensagem e **1** `quote.sent` | o *compare-and-set* do KAM-118 e o `FOR UPDATE` do envio |
| o botao de um valor anterior nao envia o valor novo | a marca do `ref` contra o `respondido_at` da linha |
| janela fechada -> `aguarda_janela`, sem evento; o valor so sai depois | o desfecho do Outbound a mudar o estado na mesma transaccao |
| um pedido final nao muda; uma transicao fora da lista recusa | o gatilho `quote_requests_transicao` |
| o dono de B nao ve nem responde os pedidos de A | a RLS `FORCE` |
| `orcamentos_mes` aplica-se | o `platform.ten_consumir` do TEN |

As instrucoes sao as de `kamba_agr.tls.orcamento`, chamadas pelas
funcoes do modulo — nao uma copia do SQL.
"""

from __future__ import annotations

import datetime
import json
import re
import threading
import types

import ligacao as ligacao_bd
from tests import factories
from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr.dono import accoes  # noqa: E402
from kamba_agr.orcamento import regras  # noqa: E402
from kamba_agr.tls import orcamento as rep  # noqa: E402

SKU = "SKU-300"


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Saida:
    """O Outbound visto pelo `enviar`: devolve o desfecho pedido e guarda as chamadas."""

    def __init__(self, desfecho: str = "livre") -> None:
        self.desfecho = desfecho
        self.chamadas: list[tuple[str, object, str]] = []
        self._trinco = threading.Lock()

    def notificar(self, *, tenant_id, notificacao, chave):
        with self._trinco:
            self.chamadas.append((tenant_id, notificacao, chave))
        return self.desfecho


class ComOrcamento(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.tenant = self.conversa.tenant_id
        self.cliente = self.conversa.contact_id
        self.dono = factories.contacto(self.semente, self.tenant)
        self.semente.execute(
            "UPDATE platform.contacts SET papel = 'dono' WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.dono),
        )
        factories.entitlement(self.semente, self.tenant, modulo="orcamento",
                              limites={"orcamentos_mes": 500})
        self._oferta(self.tenant, SKU)
        self._oferta(self.tenant, "SKU-301")
        factories.contexto(self.semente, None)
        # Antes dos contactos e dos tenants: a limpeza do `ComAgr` foi
        # registada primeiro, pelo que corre depois desta.
        self.addCleanup(self._limpar_orcamentos)
        self.app = self.ligar("app")

    def _oferta(self, tenant: str, sku: str, preco_tipo: str = "sob_consulta") -> None:
        self.semente.execute(
            "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, estado) "
            "VALUES (%s, %s, %s, %s, %s, 'publicado')",
            (tenant, sku, f"produto {sku}", preco_tipo, None if preco_tipo == "sob_consulta" else 100),
        )

    def _limpar_orcamentos(self) -> None:
        for tenant in self._tenants:
            for tabela in ("quote_requests", "owner_actions", "offer_terms", "usage_ledger", "tenant_usage",
                           "entitlements", "events_outbox", "events_log", "evt_agregado_seq"):
                self.semente.execute(f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,))

    # -------------------------------------------------------------- leituras

    def _linhas(self, tenant: str | None = None) -> list[tuple]:
        self.semente.execute(
            "SELECT quote_id::text, estado, valor_minor FROM platform.quote_requests "
            "WHERE tenant_id = %s",
            (tenant or self.tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def _eventos(self, tipo: str, tenant: str | None = None) -> list[dict]:
        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox WHERE tenant_id = %s AND tipo = %s",
            (tenant or self.tenant, tipo),
        )
        return [e if isinstance(e, dict) else json.loads(e) for (e,) in self.semente.fetchall()]

    def _consumidos(self) -> int:
        self.semente.execute(
            "SELECT count(*) FROM platform.usage_ledger WHERE tenant_id = %s", (self.tenant,)
        )
        return int(self.semente.fetchone()[0])

    def _pedir(self, ligacao=None, quantidade=None) -> rep.Pedido:
        return rep.pedir(ligacao or self.app, self.tenant, self.cliente,
                         self.conversa.conversation_id, SKU, quantidade, _agora())

    def _responder(self, quote_id: str, valor: str = "120 mil", **kw) -> rep.Resposta:
        return rep.responder(self.app, self.tenant, self.dono, quote_id,
                             regras.ler_valor_do_dono(valor), kw.get("validade"),
                             kw.get("condicoes"), kw.get("agora", _agora()))

    def _tocar(self, action_id: str, saida: Saida, ligacao=None) -> rep.Envio | str:
        ligacao = ligacao or self.app
        desfecho = accoes.confirmar(ligacao, self.tenant, self.dono, f"confirm:{action_id}", _agora())
        if desfecho != accoes.CONFIRMADA:
            return desfecho
        return rep.enviar(ligacao, self.tenant, self.dono, action_id, saida, _agora())


class TestPedido(ComOrcamento):
    def test_tres_pedidos_em_dez_minutos_dao_um_quote_id_uma_linha_um_evento(self) -> None:
        pedidos = [self._pedir(quantidade=12) for _ in range(3)]
        self.assertEqual(len({p.quote_id for p in pedidos}), 1)
        self.assertEqual([p.novo for p in pedidos], [True, False, False])
        self.assertEqual(len(self._linhas()), 1)
        eventos = self._eventos(rep.EVENTO_PEDIDO)
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["payload"]["quote_id"], pedidos[0].quote_id)
        self.assertEqual(eventos[0]["payload"]["quantidade"], 12)
        self.assertEqual(eventos[0]["agregado"]["tipo"], "quote")
        # Um so consumo de `orcamentos_mes`: o pedido repetido nao conta.
        self.assertEqual(self._consumidos(), 1)

    def test_duas_mensagens_concorrentes_dao_um_pedido(self) -> None:
        ligacoes = [self.ligar("app"), self.ligar("app")]
        barreira = threading.Barrier(2)
        ids: list[str] = []

        erros: list[BaseException] = []

        def pedir(ligacao) -> None:
            try:
                barreira.wait()
                ids.append(self._pedir(ligacao).quote_id)
            except BaseException as erro:  # noqa: BLE001 — o fio nao propaga
                erros.append(erro)

        fios = [threading.Thread(target=pedir, args=(c,)) for c in ligacoes]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self._linhas()), 1)
        self.assertEqual(len(self._eventos(rep.EVENTO_PEDIDO)), 1)

    def test_fora_da_janela_de_repeticao_e_outro_pedido(self) -> None:
        primeiro = self._pedir()
        self.semente.execute(
            "ALTER TABLE platform.quote_requests DISABLE TRIGGER quote_requests_transicao"
        )
        try:
            # Recua o relogio do pedido: o `criado_at` nao e da aplicacao.
            self.semente.execute(
                "UPDATE platform.quote_requests SET criado_at = now() - interval '11 minutes' "
                "WHERE quote_id = %s", (primeiro.quote_id,)
            )
        finally:
            self.semente.execute(
                "ALTER TABLE platform.quote_requests ENABLE TRIGGER quote_requests_transicao"
            )
        self.assertNotEqual(self._pedir().quote_id, primeiro.quote_id)

    def test_sem_o_modulo_nao_ha_pedido_nem_evento(self) -> None:
        self.semente.execute(
            "DELETE FROM platform.entitlements WHERE tenant_id = %s", (self.tenant,)
        )
        with self.assertRaises(rep.OrcamentoRecusadoError) as caso:
            self._pedir()
        self.assertEqual(caso.exception.codigo, rep.SEM_ORCAMENTOS)
        self.assertEqual(self._linhas(), [])
        self.assertEqual(self._eventos(rep.EVENTO_PEDIDO), [])

    def test_fora_do_catalogo_ou_com_preco_publicado_nao_ha_pedido(self) -> None:
        """Criterio 10: um `sku` que nao e do catalogo, ou que tem preco, nao e ingerido."""
        self._oferta(self.tenant, "SKU-FIXO", preco_tipo="fixo")
        outra = self.criar_conversa()
        self._oferta(outra.tenant_id, "SKU-DE-B")
        factories.contexto(self.semente, None)
        for sku in ("SKU-NAO-EXISTE", "SKU-FIXO", "SKU-DE-B", "https://loja-de-outro.example/pdf"):
            with self.subTest(sku=sku):
                with self.assertRaises(rep.OrcamentoRecusadoError) as caso:
                    rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                              sku, None, _agora())
                self.assertEqual(caso.exception.codigo, rep.FORA_DO_CATALOGO)
        self.assertEqual(self._linhas(), [])
        self.assertEqual(self._consumidos(), 0)

    def test_o_balde_esgotado_recusa_o_pedido_seguinte(self) -> None:
        self.semente.execute(
            "UPDATE platform.entitlements SET limites = '{\"orcamentos_mes\": 1}'::jsonb "
            "WHERE tenant_id = %s", (self.tenant,)
        )
        self._pedir()
        with self.assertRaises(rep.OrcamentoRecusadoError):
            rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                      "SKU-301", None, _agora())
        self.assertEqual(len(self._linhas()), 1)


class TestResposta(ComOrcamento):
    def test_o_dono_responde_e_recebe_o_botao(self) -> None:
        pedido = self._pedir(quantidade=12)
        resposta = self._responder(pedido.quote_id, "120.000")
        self.assertEqual(resposta.valor_minor, 12_000_000)
        self.assertEqual(self._linhas(), [(pedido.quote_id, "respondido", 12_000_000)])
        self.assertIn("120 000 Kz", resposta.previsao)
        self.assertIn(regras.ROTULO, resposta.previsao)
        self.semente.execute(
            "SELECT tipo, ref, estado FROM platform.owner_actions WHERE action_id = %s",
            (resposta.action_id,),
        )
        tipo, ref, estado = self.semente.fetchone()
        self.assertEqual((tipo, estado), ("enviar_proposta", "pendente"))
        self.assertTrue(ref.startswith(pedido.quote_id + "/"))

    def test_um_cliente_nao_responde(self) -> None:
        pedido = self._pedir()
        with self.assertRaises(rep.OrcamentoRecusadoError) as caso:
            rep.responder(self.app, self.tenant, self.cliente, pedido.quote_id, 100, None, None, _agora())
        self.assertEqual(caso.exception.codigo, rep.NAO_E_DONO)
        self.assertEqual(self._linhas()[0][1], "pedido")

    def test_validade_no_passado_recusa(self) -> None:
        pedido = self._pedir()
        ontem = regras.hoje_em_luanda(_agora()) - datetime.timedelta(days=1)
        with self.assertRaises(rep.OrcamentoRecusadoError) as caso:
            self._responder(pedido.quote_id, validade=ontem)
        self.assertEqual(caso.exception.codigo, rep.VALIDADE_NO_PASSADO)

    def test_cem_pedidos_com_quantidades_diferentes_nunca_dao_um_total_calculado(self) -> None:
        """Criterio 3: o valor gravado e enviado e o que o dono digitou, sempre."""
        saida = Saida()
        for quantidade in range(1, 101):
            # O mesmo `sku`: depois de enviado, o pedido ja nao esta aberto e o
            # seguinte e outro.
            pedido = self._pedir(quantidade=quantidade)
            resposta = self._responder(pedido.quote_id, "7 500 Kz")
            self.assertIsInstance(self._tocar(resposta.action_id, saida), rep.Envio)
        valores = {e["payload"]["valor_minor"] for e in self._eventos(rep.EVENTO_ENVIADO)}
        self.assertEqual(valores, {750_000})
        self.assertEqual(len(saida.chamadas), 100)
        for _t, notificacao, _c in saida.chamadas:
            # O unico valor monetario da mensagem e o do dono.
            self.assertIn("7 500 Kz", notificacao.texto)
            self.assertEqual(notificacao.texto.count(" Kz"), 1)


class TestCorreccoesDaRevisao(ComOrcamento):
    def test_duas_respostas_no_mesmo_instante_dao_dois_botoes(self) -> None:
        """Achado 10: a marca e estritamente crescente, mesmo com o mesmo `agora`."""
        pedido = self._pedir()
        agora = _agora()
        a = self._responder(pedido.quote_id, "100 mil", agora=agora)
        b = self._responder(pedido.quote_id, "120 mil", agora=agora)
        self.assertNotEqual(a.action_id, b.action_id)
        saida = Saida("livre")
        self.assertEqual(self._tocar(a.action_id, saida).desfecho, rep.DESACTUALIZADO)
        self.assertEqual(self._tocar(b.action_id, saida).desfecho, rep.ENVIADO)

    def test_uma_proposta_invalida_nao_deixa_resposta_nem_botao(self) -> None:
        """Achado 11: o validador corre antes da escrita."""
        self._oferta(self.tenant, "Kz")
        factories.contexto(self.semente, None)
        pedido = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                           "Kz", None, _agora())
        with self.assertRaises(rep.PropostaInvalidaError):
            self._responder(pedido.quote_id)
        self.assertEqual(self._linhas()[0][1:], ("pedido", None))
        self.semente.execute("SELECT count(*) FROM platform.owner_actions WHERE tenant_id = %s", (self.tenant,))
        self.assertEqual(self.semente.fetchone()[0], 0)

    def test_quantidade_fora_do_dominio_fica_por_dizer(self) -> None:
        """Achado 12: «200 000 unidades» nao rebenta o pedido."""
        pedido = self._pedir(quantidade=200_000)
        self.semente.execute("SELECT quantidade FROM platform.quote_requests WHERE quote_id = %s",
                             (pedido.quote_id,))
        self.assertIsNone(self.semente.fetchone()[0])

    def test_os_pendentes_mais_novos_aparecem_primeiro(self) -> None:
        """Achado 4: com mais abertos do que o limite, os novos nao se escondem."""
        primeiro = self._pedir()
        ultimo = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                           "SKU-301", None, _agora())
        self.assertEqual([p.quote_id for p in rep.pendentes(self.app, self.tenant, limite=1)],
                         [ultimo.quote_id])
        self.assertNotEqual(primeiro.quote_id, ultimo.quote_id)

    def test_a_referencia_encontra_um_e_so_um(self) -> None:
        """Achado 8: a referencia e o prefixo, contra todos os abertos."""
        pedido = self._pedir()
        ref = regras.referencia_interna(pedido.quote_id)
        self.assertEqual(rep.por_referencia(self.app, self.tenant, ref), pedido.quote_id)
        self.assertEqual(rep.por_referencia(self.app, self.tenant, ref.lower()), pedido.quote_id)
        self.assertIsNone(rep.por_referencia(self.app, self.tenant, "ORC-AAAAAAAA"))
        outra = self.criar_conversa()
        self.assertIsNone(rep.por_referencia(self.app, outra.tenant_id, ref))

    def test_uma_proposta_vencida_nao_sai_pela_janela(self) -> None:
        """Achado 5: o cliente responde depois da validade."""
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        self.assertEqual(self._tocar(resposta.action_id, Saida("template")).desfecho, rep.AGUARDA_JANELA)
        depois = _agora() + datetime.timedelta(days=9)
        aberta = Saida("livre")
        self.assertEqual(rep.libertar_da_janela(self.app, self.tenant, self.cliente, aberta, depois), [])
        self.assertEqual(aberta.chamadas, [])
        self.assertEqual(self._linhas()[0][1], "expirado")

    def test_um_toque_depois_da_validade_nao_envia(self) -> None:
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        accoes.confirmar(self.app, self.tenant, self.dono, f"confirm:{resposta.action_id}", _agora())
        depois = _agora() + datetime.timedelta(days=9)
        saida = Saida("livre")
        envio = rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, saida, depois)
        self.assertEqual(envio.desfecho, rep.DESACTUALIZADO)
        self.assertEqual(saida.chamadas, [])
        self.assertEqual(self._linhas()[0][1], "expirado")

    def test_um_desfecho_fora_do_contrato_nao_muda_nada(self) -> None:
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        with self.assertRaises(ValueError):
            self._tocar(resposta.action_id, Saida("talvez"))
        self.assertEqual(self._linhas()[0][1], "respondido")
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO), [])
        # E o mesmo botao repete o envio.
        self.assertEqual(
            rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, Saida("livre"), _agora()).desfecho,
            rep.ENVIADO,
        )


class TestEnvio(ComOrcamento):
    def _respondido(self, valor: str = "120 mil") -> tuple[str, rep.Resposta]:
        pedido = self._pedir()
        return pedido.quote_id, self._responder(pedido.quote_id, valor)

    def test_um_toque_envia_uma_mensagem_e_um_evento(self) -> None:
        quote_id, resposta = self._respondido()
        saida = Saida("livre")
        envio = self._tocar(resposta.action_id, saida)
        self.assertEqual(envio, rep.Envio(rep.ENVIADO, quote_id))
        self.assertEqual(len(saida.chamadas), 1)
        _tenant, notificacao, chave = saida.chamadas[0]
        self.assertEqual(notificacao.contact_id, self.cliente)
        self.assertEqual(notificacao.conversation_id, self.conversa.conversation_id)
        self.assertEqual(notificacao.template, rep.TEMPLATE_ORCAMENTO_PRONTO)
        self.assertTrue(chave.startswith(f"orcamento:{quote_id}:"))
        self.assertEqual(self._linhas()[0][1], "enviado")
        enviados = self._eventos(rep.EVENTO_ENVIADO)
        self.assertEqual(len(enviados), 1)
        self.assertEqual(enviados[0]["payload"]["valor_minor"], 12_000_000)

    def test_duplo_toque_duas_vezes_da_uma_mensagem(self) -> None:
        _quote_id, resposta = self._respondido()
        saida = Saida("livre")
        primeiro = self._tocar(resposta.action_id, saida)
        segundo = self._tocar(resposta.action_id, saida)
        self.assertEqual(primeiro.desfecho, rep.ENVIADO)
        self.assertEqual(segundo, accoes.JA_CONFIRMADA)
        # E mesmo chamando o envio outra vez, a linha ja nao esta `respondido`.
        self.assertEqual(
            rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, saida, _agora()).desfecho,
            rep.JA_ENVIADO,
        )
        self.assertEqual(len(saida.chamadas), 1)
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)

    def test_duplo_toque_concorrente_da_uma_mensagem(self) -> None:
        _quote_id, resposta = self._respondido()
        saida = Saida("livre")
        ligacoes = [self.ligar("app"), self.ligar("app")]
        barreira = threading.Barrier(2)

        erros: list[BaseException] = []
        desfechos: list[object] = []

        def tocar(ligacao) -> None:
            try:
                barreira.wait()
                desfechos.append(self._tocar(resposta.action_id, saida, ligacao))
            except BaseException as erro:  # noqa: BLE001 — o fio nao propaga
                erros.append(erro)

        fios = [threading.Thread(target=tocar, args=(c,)) for c in ligacoes]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(len(desfechos), 2)
        self.assertEqual(len(saida.chamadas), 1)
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)

    def test_o_botao_de_um_valor_anterior_nao_envia_o_valor_novo(self) -> None:
        quote_id, antiga = self._respondido("100 mil")
        nova = self._responder(quote_id, "120 mil")
        self.assertNotEqual(antiga.action_id, nova.action_id)
        saida = Saida("livre")
        self.assertEqual(self._tocar(antiga.action_id, saida).desfecho, rep.DESACTUALIZADO)
        self.assertEqual(saida.chamadas, [])
        self.assertEqual(self._tocar(nova.action_id, saida).desfecho, rep.ENVIADO)
        self.assertIn("120 000 Kz", saida.chamadas[0][1].texto)

    def test_janela_fechada_espera_e_o_valor_so_sai_depois(self) -> None:
        quote_id, resposta = self._respondido()
        fechada = Saida("template")
        self.assertEqual(self._tocar(resposta.action_id, fechada).desfecho, rep.AGUARDA_JANELA)
        self.assertEqual(self._linhas()[0][1], "aguarda_janela")
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO), [])
        aberta = Saida("livre")
        envios = rep.libertar_da_janela(self.app, self.tenant, self.cliente, aberta, _agora())
        self.assertEqual(envios, [rep.Envio(rep.ENVIADO, quote_id)])
        self.assertEqual(self._linhas()[0][1], "enviado")
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)
        self.assertNotEqual(fechada.chamadas[0][2], aberta.chamadas[0][2])

    def test_sem_template_nada_sai_e_o_pedido_fica(self) -> None:
        _quote_id, resposta = self._respondido()
        saida = Saida("sem_template")
        self.assertEqual(self._tocar(resposta.action_id, saida).desfecho, rep.NAO_ENVIADO)
        self.assertEqual(self._linhas()[0][1], "respondido")
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO), [])
        # O botao ja esta gasto (`ja_confirmada`), e o envio repete-se com ele.
        envio = rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, Saida("livre"), _agora())
        self.assertEqual(envio.desfecho, rep.ENVIADO)

    def test_outro_tipo_de_accao_nao_e_orcamento(self) -> None:
        action_id = accoes.propor(self.app, self.tenant, self.dono, "aprovar_conteudo", "c-1", _agora())
        envio = self._tocar(action_id, Saida())
        self.assertEqual(envio.desfecho, rep.NAO_E_ORCAMENTO)


class TestFecho(ComOrcamento):
    def test_expirado_nao_se_responde_nem_se_envia(self) -> None:
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        depois = _agora() + datetime.timedelta(days=9)
        self.assertEqual(rep.expirar_vencidos(self.app, self.tenant, depois), 1)
        self.assertEqual(self._linhas()[0][1], "expirado")
        with self.assertRaises(rep.OrcamentoRecusadoError) as caso:
            self._responder(pedido.quote_id)
        self.assertEqual(caso.exception.codigo, rep.FECHADO)
        saida = Saida()
        self.assertEqual(self._tocar(resposta.action_id, saida).desfecho, rep.DESACTUALIZADO)
        self.assertEqual(saida.chamadas, [])
        self.assertEqual(rep.ultimo_do_cliente(self.app, self.tenant, self.cliente),
                         (pedido.quote_id, "expirado"))

    def test_cancelado_e_final(self) -> None:
        pedido = self._pedir()
        self.assertTrue(rep.cancelar(self.app, self.tenant, self.dono, pedido.quote_id))
        self.assertFalse(rep.cancelar(self.app, self.tenant, self.dono, pedido.quote_id))
        self.assertEqual(rep.pendentes(self.app, self.tenant), [])

    def _transicao_recusada_pelo_gatilho(self, quote_id: str, sql: str) -> None:
        with self.assertRaises(Exception) as caso:
            self.semente.execute(sql, (quote_id,))
        self.assertEqual(sqlstate(caso.exception), VIOLACAO_DE_CHECK)
        self.assertIn("quote_requests", str(caso.exception))

    def test_o_gatilho_recusa_mudar_um_enviado_e_saltar_estados(self) -> None:
        """Transicoes que **so** o gatilho recusa: todos os `CHECK` as aceitavam
        (achado 6 da revisao — `pedido -> enviado` caia no `respondido_ck`)."""
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        # `respondido -> pedido`: a linha tem resposta, e os CHECK aceitam-na.
        self._transicao_recusada_pelo_gatilho(
            pedido.quote_id,
            "UPDATE platform.quote_requests SET estado = 'pedido' WHERE quote_id = %s",
        )
        self._tocar(resposta.action_id, Saida("livre"))
        with self.assertRaises(Exception) as caso:
            self.semente.execute(
                "UPDATE platform.quote_requests SET valor_minor = 1 WHERE quote_id = %s",
                (pedido.quote_id,),
            )
        self.assertEqual(sqlstate(caso.exception), VIOLACAO_DE_CHECK)

    def test_a_aplicacao_nao_muda_a_identidade_nem_apaga(self) -> None:
        pedido = self._pedir()
        cursor = self.app.cursor()
        for instrucao in (
            "UPDATE platform.quote_requests SET sku = 'SKU-999' WHERE quote_id = %s",
            "DELETE FROM platform.quote_requests WHERE quote_id = %s",
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                factories.contexto(cursor, self.tenant)
                with self.assertRaises(Exception) as caso:
                    cursor.execute(instrucao, (pedido.quote_id,))
                self.assertEqual(sqlstate(caso.exception), PRIVILEGIO_INSUFICIENTE)
                self.app.rollback()


class TestIsolamento(ComOrcamento):
    def test_o_dono_de_b_nao_ve_nem_responde_os_pedidos_de_a(self) -> None:
        pedido = self._pedir()
        outra = self.criar_conversa()
        dono_b = factories.contacto(self.semente, outra.tenant_id)
        self.semente.execute(
            "UPDATE platform.contacts SET papel = 'dono' WHERE tenant_id = %s AND contact_id = %s",
            (outra.tenant_id, dono_b),
        )
        factories.contexto(self.semente, None)
        self.assertEqual(rep.pendentes(self.app, outra.tenant_id), [])
        with self.assertRaises(rep.OrcamentoRecusadoError) as caso:
            rep.responder(self.app, outra.tenant_id, dono_b, pedido.quote_id, 100, None, None, _agora())
        self.assertEqual(caso.exception.codigo, rep.DESCONHECIDO)
        self.assertEqual(self._linhas()[0][1], "pedido")
        self.assertEqual([p.quote_id for p in rep.pendentes(self.app, self.tenant)], [pedido.quote_id])

    def test_o_cliente_x_nao_ve_o_ultimo_pedido_de_y(self) -> None:
        self._pedir()
        outro_cliente = factories.contacto(self.semente, self.tenant)
        factories.contexto(self.semente, None)
        self.assertIsNone(rep.ultimo_do_cliente(self.app, self.tenant, outro_cliente))


# ---------------------------------------------------------------- KAM-221


class SaidaQueDeduplica(Saida):
    """O Outbound como ele e: a mesma chave da **uma** mensagem.

    O `Saida` do KAM-015 guarda a chave na `outbound_messages` e devolve o
    resultado da primeira a uma repeticao, sem chamada HTTP. Este duplo faz o
    mesmo, e conta as mensagens que **sairiam** — que e a medida do «uma
    mensagem» quando duas chamadas concorrentes chegam as duas ao Outbound.
    """

    def __init__(self, desfecho: str = "livre") -> None:
        super().__init__(desfecho)
        self.mensagens: dict[str, object] = {}

    def notificar(self, *, tenant_id, notificacao, chave):
        desfecho = super().notificar(tenant_id=tenant_id, notificacao=notificacao, chave=chave)
        with self._trinco:
            self.mensagens.setdefault(chave, notificacao)
        return desfecho


class SaidaQueEspreita(Saida):
    """Corre `durante(chave)` no instante do envio, e depois devolve o desfecho."""

    def __init__(self, desfecho: str, durante) -> None:
        super().__init__(desfecho)
        self._durante = durante

    def notificar(self, *, tenant_id, notificacao, chave):
        self._durante(chave)
        return super().notificar(tenant_id=tenant_id, notificacao=notificacao, chave=chave)


def _contagem_do_lote(job: str) -> int:
    from kamba_core import tenant_guard

    return tenant_guard.CONTADORES.ler().get(f"{tenant_guard.METRICA_BATCH}:{job}", 0)


class TestEnvioForaDaTransaccao(ComOrcamento):
    """Credor do achado 2 da revisao do KAM-123: o Outbound fora da transaccao."""

    def _confirmado(self) -> tuple[str, rep.Resposta]:
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        accoes.confirmar(self.app, self.tenant, self.dono, f"confirm:{resposta.action_id}", _agora())
        return pedido.quote_id, resposta

    def _outra(self):
        """Outra sessao `kamba_app`, que desiste de uma tranca ao fim de 30 s.

        O tecto existe para que um defeito pendure o ensaio por 30 s e nao para
        sempre: a outra sessao espera pela tranca de quem a esta a chamar.
        """
        outra = self.ligar("app")
        outra.cursor().execute("SET lock_timeout = '30s'")
        outra.commit()
        return outra

    def _durante_o_envio(self, accao):
        """Corre `accao` noutro fio durante o envio, e mede se ela esperou.

        Devolve `(saida, fio)`: a porta lanca o fio, espera um segundo, regista
        se ele ainda esta a espera e so depois devolve `livre`.
        """
        resultado: dict[str, object] = {}

        def correr() -> None:
            try:
                resultado["valor"] = accao()
            except BaseException as erro:  # noqa: BLE001 — o fio nao propaga
                resultado["erro"] = erro

        fio = threading.Thread(target=correr)

        def durante(_chave) -> None:
            fio.start()
            fio.join(1.0)
            resultado["esperou"] = fio.is_alive()

        return SaidaQueEspreita("livre", durante), fio, resultado

    def _trancar_sem_esperar(self, quote_id: str) -> None:
        """Outra sessao tranca a linha com `NOWAIT`: levanta se alguem a tiver."""
        from kamba_core import tenant_guard

        outra = self.ligar("app")
        with tenant_guard.tx(outra, self.tenant) as cursor:
            cursor.execute(
                "SELECT 1 FROM platform.quote_requests WHERE tenant_id = %s AND quote_id = %s "
                "FOR UPDATE NOWAIT",
                (self.tenant, quote_id),
            )
            self.assertIsNotNone(cursor.fetchone())

    def test_no_instante_do_envio_a_linha_nao_esta_trancada(self) -> None:
        """Com o Outbound dentro da transaccao, o `NOWAIT` dava `55P03`."""
        quote_id, resposta = self._confirmado()
        saida = SaidaQueEspreita("livre", lambda _chave: self._trancar_sem_esperar(quote_id))
        envio = rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, saida, _agora())
        self.assertEqual(envio.desfecho, rep.ENVIADO)
        self.assertEqual(self._linhas()[0][1], "enviado")
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)

    def test_na_libertacao_tambem_nao(self) -> None:
        quote_id, resposta = self._confirmado()
        rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, Saida("template"), _agora())
        saida = SaidaQueEspreita("livre", lambda _chave: self._trancar_sem_esperar(quote_id))
        envios = rep.libertar_da_janela(self.app, self.tenant, self.cliente, saida, _agora())
        self.assertEqual(envios, [rep.Envio(rep.ENVIADO, quote_id)])

    def test_um_cancelamento_durante_o_envio_espera_e_nao_cancela(self) -> None:
        """Achado 1 da revisao: a proposta que saiu fica `enviado`, com o evento.

        Sem a tranca do envio, o cancelamento corria debaixo da chamada ao
        Outbound: o cliente recebia a proposta e o pedido ficava `cancelado`,
        sem `quote.sent`.
        """
        quote_id, resposta = self._confirmado()
        outra = self._outra()
        saida, fio, resultado = self._durante_o_envio(
            lambda: rep.cancelar(outra, self.tenant, self.dono, quote_id)
        )
        envio = rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, saida, _agora())
        fio.join(30)
        self.assertTrue(resultado["esperou"])
        self.assertEqual(envio.desfecho, rep.ENVIADO)
        self.assertNotIn("erro", resultado)
        self.assertIs(resultado["valor"], False)
        self.assertEqual(self._linhas()[0][1], "enviado")
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)

    def test_uma_correccao_durante_o_envio_espera_e_encontra_fechado(self) -> None:
        """O dono corrige o valor enquanto a proposta sai: a correccao espera."""
        quote_id, resposta = self._confirmado()
        outra = self._outra()
        saida, fio, resultado = self._durante_o_envio(
            lambda: rep.responder(outra, self.tenant, self.dono, quote_id,
                                  regras.ler_valor_do_dono("130 mil"), None, None, _agora())
        )
        envio = rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, saida, _agora())
        fio.join(30)
        self.assertTrue(resultado["esperou"])
        self.assertEqual(envio.desfecho, rep.ENVIADO)
        self.assertIsInstance(resultado.get("erro"), rep.OrcamentoRecusadoError)
        self.assertEqual(resultado["erro"].codigo, rep.FECHADO)
        self.assertEqual(self._linhas()[0][1:], ("enviado", 12_000_000))
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)

    def test_dois_envios_concorrentes_dao_uma_mensagem_e_um_evento(self) -> None:
        """O no `confirm` chama o envio tambem num `ja_confirmada`: dois toques
        concorrentes chegam os dois ao envio. A tranca do envio faz o segundo
        esperar e ler `ja_enviado`: **uma** chamada ao Outbound e **um**
        `quote.sent`."""
        quote_id, resposta = self._confirmado()
        saida = SaidaQueDeduplica("livre")
        ligacoes = [self.ligar("app"), self.ligar("app")]
        barreira = threading.Barrier(2)
        erros: list[BaseException] = []
        desfechos: list[str] = []

        def enviar(ligacao) -> None:
            try:
                barreira.wait()
                envio = rep.enviar(ligacao, self.tenant, self.dono, resposta.action_id, saida, _agora())
                desfechos.append(envio.desfecho)
            except BaseException as erro:  # noqa: BLE001 — o fio nao propaga
                erros.append(erro)

        fios = [threading.Thread(target=enviar, args=(c,)) for c in ligacoes]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(sorted(desfechos), sorted([rep.ENVIADO, rep.JA_ENVIADO]))
        self.assertEqual(len(saida.chamadas), 1)
        self.assertEqual(self._linhas()[0][1], "enviado")
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO)[0]["payload"]["quote_id"], quote_id)

    def test_a_reentrega_do_template_nao_sai_outra_vez(self) -> None:
        _quote_id, resposta = self._confirmado()
        saida = Saida("template")
        self.assertEqual(
            rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, saida, _agora()).desfecho,
            rep.AGUARDA_JANELA,
        )
        self.assertEqual(
            rep.enviar(self.app, self.tenant, self.dono, resposta.action_id, saida, _agora()).desfecho,
            rep.JA_ENVIADO,
        )
        self.assertEqual(len(saida.chamadas), 1)
        self.assertEqual(self._linhas()[0][1], "aguarda_janela")


class TestJanela(ComOrcamento):
    """O criterio 2 do KAM-221, contra a base: o valor sai uma vez."""

    def _a_espera(self) -> str:
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        self._tocar(resposta.action_id, Saida("template"))
        return pedido.quote_id

    def test_o_cliente_responde_duas_vezes_e_o_valor_sai_uma(self) -> None:
        quote_id = self._a_espera()
        saida = SaidaQueDeduplica("livre")
        primeira = rep.libertar_da_janela(self.app, self.tenant, self.cliente, saida, _agora())
        segunda = rep.libertar_da_janela(self.app, self.tenant, self.cliente, saida, _agora())
        self.assertEqual(primeira, [rep.Envio(rep.ENVIADO, quote_id)])
        self.assertEqual(segunda, [])
        self.assertEqual(len(saida.chamadas), 1)
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)

    def test_duas_mensagens_concorrentes_do_cliente_dao_um_valor(self) -> None:
        quote_id = self._a_espera()
        saida = SaidaQueDeduplica("livre")
        ligacoes = [self.ligar("app"), self.ligar("app")]
        barreira = threading.Barrier(2)
        erros: list[BaseException] = []

        def libertar(ligacao) -> None:
            try:
                barreira.wait()
                rep.libertar_da_janela(ligacao, self.tenant, self.cliente, saida, _agora())
            except BaseException as erro:  # noqa: BLE001 — o fio nao propaga
                erros.append(erro)

        fios = [threading.Thread(target=libertar, args=(c,)) for c in ligacoes]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(len(saida.chamadas), 1)
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO)[0]["payload"]["quote_id"], quote_id)

    def test_uma_proposta_que_falha_nao_para_as_outras_do_mesmo_cliente(self) -> None:
        """Achado 3 da revisao: a primeira levanta, a segunda sai, a primeira espera."""
        primeira = self._a_espera()
        segundo = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                            "SKU-301", None, _agora())
        resposta = self._responder(segundo.quote_id)
        self._tocar(resposta.action_id, Saida("template"))

        class Rebenta(Saida):
            def notificar(self, *, tenant_id, notificacao, chave):
                if chave.startswith(f"orcamento:{primeira}:"):
                    raise RuntimeError("outbound em baixo")
                return super().notificar(tenant_id=tenant_id, notificacao=notificacao, chave=chave)

        envios = rep.libertar_da_janela(self.app, self.tenant, self.cliente, Rebenta("livre"), _agora())
        self.assertEqual(
            sorted(envios, key=lambda e: e.quote_id),
            sorted([rep.Envio(rep.AGUARDA_JANELA, primeira), rep.Envio(rep.ENVIADO, segundo.quote_id)],
                   key=lambda e: e.quote_id),
        )
        estados = {q: e for q, e, _v in self._linhas()}
        self.assertEqual((estados[primeira], estados[segundo.quote_id]), ("aguarda_janela", "enviado"))

    def test_a_mensagem_de_um_cliente_nao_expira_as_de_outro(self) -> None:
        """Achado 6 da revisao: a expiracao da janela e so das propostas de quem escreveu."""
        quote_id = self._a_espera()
        outro = factories.contacto(self.semente, self.tenant)
        factories.contexto(self.semente, None)
        depois = _agora() + datetime.timedelta(days=9)
        self.assertEqual(rep.libertar_da_janela(self.app, self.tenant, outro, Saida("livre"), depois), [])
        self.assertEqual({q: e for q, e, _v in self._linhas()}[quote_id], "aguarda_janela")

    def test_cancelado_durante_a_espera_nao_sai(self) -> None:
        quote_id = self._a_espera()
        self.assertTrue(rep.cancelar(self.app, self.tenant, self.dono, quote_id))
        saida = Saida("livre")
        self.assertEqual(rep.libertar_da_janela(self.app, self.tenant, self.cliente, saida, _agora()), [])
        self.assertEqual(saida.chamadas, [])
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO), [])

    def test_outro_cliente_nao_liberta(self) -> None:
        self._a_espera()
        outro = factories.contacto(self.semente, self.tenant)
        factories.contexto(self.semente, None)
        saida = Saida("livre")
        self.assertEqual(rep.libertar_da_janela(self.app, self.tenant, outro, saida, _agora()), [])
        self.assertEqual(saida.chamadas, [])

    def test_a_porta_do_processo_liberta_so_pela_mensagem_de_um_cliente(self) -> None:
        """O `libertar` da `PortaDeOrcamento`, que e o que o `ExecutorDeTurnos` chama."""
        import asyncio

        from kamba_agr.contexto import PERSONA_CLIENTE, PERSONA_DONO
        from kamba_agr.orcamento.porta import PortaDeOrcamento

        quote_id = self._a_espera()
        saida = Saida("livre")
        # Uma ligacao que a porta abre **e fecha**: a do `self.ligar` fechava-se
        # outra vez no `tearDown`.
        porta = PortaDeOrcamento(lambda: ligacao_bd.ligar("app"), saida=saida)
        invocacao = types.SimpleNamespace(tenant_id=self.tenant, contact_id=self.cliente, persona=PERSONA_DONO)
        self.assertEqual(asyncio.run(porta.libertar(invocacao)), [])
        self.assertEqual(saida.chamadas, [])
        invocacao.persona = PERSONA_CLIENTE
        self.assertEqual(asyncio.run(porta.libertar(invocacao)), [rep.Envio(rep.ENVIADO, quote_id)])
        self.assertEqual(self._linhas()[0][1], "enviado")


class TestSemRespostaDoDono(ComOrcamento):
    """O criterio 3 do KAM-221: a mensagem neutra das 24 h, com relogio fixo."""

    def _com_idade(self, quote_id: str, horas: float) -> None:
        self.semente.execute(
            "UPDATE platform.quote_requests SET criado_at = now() - %s::interval WHERE quote_id = %s",
            (f"{horas} hours", quote_id),
        )

    def test_vinte_e_quatro_horas_dao_uma_mensagem_neutra_sem_numero(self) -> None:
        pedido = self._pedir()
        saida = Saida("template")
        self._com_idade(pedido.quote_id, 23)
        self.assertEqual(rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())["template"], 0)
        self._com_idade(pedido.quote_id, 25)
        contagem = rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())
        self.assertEqual(contagem, {"livre": 0, "template": 1, "sem_template": 0, "falhou": 0})
        tenant, notificacao, chave = saida.chamadas[0]
        self.assertEqual(tenant, self.tenant)
        self.assertEqual(chave, f"orcamento:{pedido.quote_id}:sem_resposta")
        self.assertEqual(notificacao.template, rep.TEMPLATE_ORCAMENTO_EM_ESPERA)
        self.assertEqual(notificacao.contact_id, self.cliente)
        self.assertEqual(notificacao.conversation_id, self.conversa.conversation_id)
        self.assertIsNone(re.search(r"\d", notificacao.texto))
        self.assertIn(regras.PALAVRA_DE_HUMANO, notificacao.texto)
        # O pedido nao muda e nada se emite: o dono ainda responde.
        self.assertEqual(self._linhas()[0][1], "pedido")
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO), [])

    def test_a_volta_seguinte_repete_a_mesma_chave(self) -> None:
        """A «uma mensagem» e a chave do Outbound, e nao uma coluna."""
        pedido = self._pedir()
        self._com_idade(pedido.quote_id, 25)
        saida = SaidaQueDeduplica("livre")
        rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())
        rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())
        self.assertEqual(len(saida.chamadas), 2)
        self.assertEqual(list(saida.mensagens), [f"orcamento:{pedido.quote_id}:sem_resposta"])

    def test_um_valor_escrito_e_nunca_enviado_tambem_recebe_a_mensagem(self) -> None:
        """Achado 7 da revisao: para o cliente, o dono nao respondeu."""
        pedido = self._pedir()
        self._responder(pedido.quote_id)
        self._com_idade(pedido.quote_id, 25)
        saida = Saida("livre")
        self.assertEqual(rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())["livre"], 1)
        self.assertEqual(saida.chamadas[0][2], f"orcamento:{pedido.quote_id}:sem_resposta")

    def test_o_tecto_serve_primeiro_os_que_acabaram_de_passar_as_24_horas(self) -> None:
        """Achado 2 da revisao: com o tecto cheio, o mais novo nao fica para tras."""
        velho = self._pedir()
        self._com_idade(velho.quote_id, 40)
        novo = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                         "SKU-301", None, _agora())
        self._com_idade(novo.quote_id, 25)
        saida = Saida("livre")
        rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora(), tecto=1)
        self.assertEqual([c for _t, _n, c in saida.chamadas], [f"orcamento:{novo.quote_id}:sem_resposta"])

    def test_enviado_a_espera_cancelado_ou_fora_do_horizonte_nao_recebem_nada(self) -> None:
        enviado = self._pedir()
        resposta = self._responder(enviado.quote_id)
        self._com_idade(enviado.quote_id, 25)
        self._tocar(resposta.action_id, Saida("template"))
        cancelado = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                              "SKU-301", None, _agora())
        # Envelhece-se antes de cancelar: um cancelado e final, e o gatilho
        # recusa mudar-lhe a linha.
        self._com_idade(cancelado.quote_id, 25)
        rep.cancelar(self.app, self.tenant, self.dono, cancelado.quote_id)
        saida = Saida("livre")
        self.assertEqual(rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())["livre"], 0)
        velho = self._pedir()
        self._com_idade(velho.quote_id, 49)
        self.assertEqual(rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())["livre"], 0)
        self.assertEqual(saida.chamadas, [])

    def test_uma_porta_que_levanta_conta_e_nao_para_as_outras(self) -> None:
        primeiro = self._pedir()
        segundo = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                            "SKU-301", None, _agora())
        self._com_idade(primeiro.quote_id, 26)
        self._com_idade(segundo.quote_id, 25)

        class Rebenta(Saida):
            def notificar(self, *, tenant_id, notificacao, chave):
                if chave.startswith(f"orcamento:{primeiro.quote_id}"):
                    raise RuntimeError("outbound em baixo")
                return super().notificar(tenant_id=tenant_id, notificacao=notificacao, chave=chave)

        saida = Rebenta("livre")
        contagem = rep.avisar_sem_resposta(self.app, self.tenant, saida, _agora())
        self.assertEqual((contagem["falhou"], contagem["livre"]), (1, 1))

    def test_o_tenant_b_nao_avisa_os_clientes_de_a(self) -> None:
        pedido = self._pedir()
        self._com_idade(pedido.quote_id, 25)
        outra = self.criar_conversa()
        factories.contexto(self.semente, None)
        saida = Saida("livre")
        rep.avisar_sem_resposta(self.app, outra.tenant_id, saida, _agora())
        self.assertEqual(saida.chamadas, [])


class TestVarredura(ComOrcamento):
    """Os dois *jobs* nomeados, com a listagem como `kamba_batch`.

    **O tenant do ensaio fica em `onboarding`**, e de proposito: activa-lo exige
    o aceite dos quatro documentos (revisao `0040`), que escreve linhas
    *append-only* no `contract_acceptance` e no `tenant_state_log` que poluem as
    descidas da suite. A orquestracao por *tenant* mede-se pelo *job* da
    expiracao, que corre em todos menos os encerrados; o das 24 h mede-se a
    **nao** avisar um *tenant* que nao esta activo, e o corpo dele por *tenant*
    esta no `TestSemRespostaDoDono`.
    """

    def _varredura(self, saida, agora=None):
        from kamba_agr.orcamento.varredura import VarreduraDeOrcamentos

        # Ligacoes que a varredura abre **e fecha**: as do `self.ligar`
        # fechavam-se outra vez no `tearDown`.
        return VarreduraDeOrcamentos(
            abrir_lote=lambda: ligacao_bd.ligar("batch"),
            abrir_app=lambda: ligacao_bd.ligar("app"),
            saida=saida,
            relogio=lambda: agora or _agora(),
        )

    def test_o_job_das_vinte_e_quatro_horas_so_avisa_tenants_activos(self) -> None:
        from kamba_agr.orcamento.varredura import JOB_SEM_RESPOSTA

        pedido = self._pedir()
        self.semente.execute(
            "UPDATE platform.quote_requests SET criado_at = now() - interval '25 hours' WHERE quote_id = %s",
            (pedido.quote_id,),
        )
        antes = _contagem_do_lote(JOB_SEM_RESPOSTA)
        saida = Saida("livre")
        varredura = self._varredura(saida)
        self.assertNotIn(self.tenant, varredura.tenants(JOB_SEM_RESPOSTA, varredura_sql("SQL_TENANTS_ACTIVOS")))
        contagem = varredura.sem_resposta()
        self.assertEqual(contagem["falhou"], 0)
        self.assertEqual([c for t, _n, c in saida.chamadas if t == self.tenant], [])
        # A listagem correu como `kamba_batch`, pelo `tx_batch` com o nome do *job*.
        self.assertEqual(_contagem_do_lote(JOB_SEM_RESPOSTA), antes + 2)

    def test_o_job_da_expiracao_fecha_as_vencidas_sem_ninguem_tocar(self) -> None:
        from kamba_agr.orcamento.varredura import JOB_EXPIRAR

        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        self._tocar(resposta.action_id, Saida("template"))
        aberto = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                           "SKU-301", None, _agora())
        antes = _contagem_do_lote(JOB_EXPIRAR)
        depois = _agora() + datetime.timedelta(days=9)
        varredura = self._varredura(Saida(), depois)
        self.assertIn(self.tenant, varredura.tenants(JOB_EXPIRAR, varredura_sql("SQL_TENANTS_POR_EXPIRAR")))
        contagem = varredura.expirar()
        self.assertEqual(contagem["falhou"], 0)
        self.assertGreaterEqual(contagem["expirados"], 1)
        self.assertEqual(_contagem_do_lote(JOB_EXPIRAR), antes + 2)
        estados = {q: e for q, e, _v in self._linhas()}
        self.assertEqual(estados[pedido.quote_id], "expirado")
        # Um `pedido` sem resposta nao expira: continua visivel ao dono.
        self.assertEqual(estados[aberto.quote_id], "pedido")


def varredura_sql(nome: str) -> str:
    from kamba_agr.orcamento import varredura

    return getattr(varredura, nome)
