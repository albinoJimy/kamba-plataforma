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
import threading
import uuid

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
        self.assertIsNone(rep.ultimo_pedido(self.app, self.tenant, outro_cliente))

    def test_o_ultimo_pedido_de_a_nao_se_le_no_contexto_de_b(self) -> None:
        """A RLS `FORCE`: com o tenant de B, o cliente de A nao tem pedido nenhum."""
        self._pedir()
        outra = self.criar_conversa()
        factories.contexto(self.semente, None)
        self.assertIsNone(rep.ultimo_pedido(self.app, outra.tenant_id, self.cliente))


class TestPelaToolLayer(ComOrcamento):
    """KAM-220: cliente -> pedido -> dono -> envio, pelas duas tools **ligadas**.

    Os oito passos do §6.1 a serio — o entitlement `orcamento`, o botao do
    passo 4 no `request_quote` e a dispensa no `submit_quote` (decisao do
    fundador de 2026-11-19, opcao C), a `tool_audit` com os *facts* — sobre os
    executores reais de `tls/orcamento_tools.py`.
    """

    def setUp(self) -> None:
        super().setUp()
        import asyncio as _asyncio

        from kamba_agr.tls import orcamento_tools
        from kamba_agr.tls.camada import ToolLayer
        from kamba_agr.tls.catalogo import catalogo_do_piloto

        self._asyncio = _asyncio
        factories.aceitar_contratos_vigentes(self.semente, self.tenant)
        self.semente.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (self.tenant,))
        factories.contexto(self.semente, None)
        self.addCleanup(
            lambda: self.semente.execute(
                "DELETE FROM platform.tool_idempotency WHERE tenant_id = %s", (self.tenant,)
            )
        )
        self.camada = ToolLayer(
            catalogo_do_piloto(orcamento_tools.executores()), abrir_ligacao=lambda: self.app
        )

    def _contexto(self, contacto: str, turno: str = "t-1", vertical: str = "vendedor"):
        from kamba_agr.tls.contexto import ToolContext

        return ToolContext.de_estado(
            {
                "tenant_id": self.tenant,
                "channel_id": self.conversa.canal_id,
                "contact_id": contacto,
                "conversation_id": self.conversa.conversation_id,
                "turn_id": turno,
                "vertical": vertical,
            },
            run_id="r-1",
            graph_version="1.3.0",
        )

    def _invocar(self, nome: str, args: dict, contacto: str, botao: str | None = None, turno: str = "t-1"):
        from kamba_agr.tls.contexto import Confirmation

        confirmacao = None if botao is None else Confirmation(botao=botao, contact_id=contacto, turn_id=turno)
        return self._asyncio.run(
            self.camada.invoke(
                self._contexto(contacto, turno),
                nome,
                args,
                allowed=[nome],
                confirmation=confirmacao,
                idempotency_key=f"{turno}:0" if botao is not None else None,
            )
        )

    def _auditoria(self) -> list[tuple]:
        self.semente.execute(
            "SELECT tool, status, error_code, fact_ids::text FROM platform.tool_audit "
            "WHERE tenant_id = %s ORDER BY id",
            (self.tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def test_cliente_pedido_dono_envio(self) -> None:
        pedido = self._invocar("request_quote", {"sku": SKU, "quantidade": 12}, self.cliente,
                               botao=f"confirm:{SKU}")
        self.assertTrue(pedido.ok, pedido.error)
        self.assertEqual(pedido.facts, ())
        quote_id = pedido.data["quote_id"]
        self.assertEqual(self._linhas(), [(quote_id, "pedido", None)])
        self.assertEqual(len(self._eventos(rep.EVENTO_PEDIDO)), 1)
        # O dono responde **sem botao**: o passo 4 esta dispensado para esta tool.
        resposta = self._invocar("submit_quote", {"quote_id": quote_id, "valor": "120 mil"}, self.dono,
                                 turno="t-2")
        self.assertTrue(resposta.ok, resposta.error)
        self.assertEqual(self._linhas(), [(quote_id, "respondido", 12_000_000)])
        self.assertEqual([f.kind for f in resposta.facts], ["quote_price", "datetime"])
        self.assertEqual(resposta.facts[0].value, 12_000_000)
        self.assertEqual(resposta.facts[0].sku, SKU)
        self.assertIn("120 000", resposta.data["previsao"])
        # Nada saiu ainda: o envio e o botao `confirm:{action_id}`, e so ele.
        self.assertEqual(self._eventos(rep.EVENTO_ENVIADO), [])
        saida = Saida("livre")
        self.assertEqual(self._tocar(resposta.data["action_id"], saida).desfecho, rep.ENVIADO)
        self.assertEqual(len(saida.chamadas), 1)
        self.assertEqual(len(self._eventos(rep.EVENTO_ENVIADO)), 1)
        auditoria = self._auditoria()
        self.assertEqual([(t, s) for t, s, _c, _f in auditoria],
                         [("request_quote", "ok"), ("submit_quote", "ok")])
        self.assertIn(quote_id, auditoria[1][3])

    def test_sem_o_botao_do_cliente_nada_se_pede(self) -> None:
        for botao in (None, "confirm:SKU-301", "confirm:"):
            with self.subTest(botao=botao):
                resultado = self._invocar("request_quote", {"sku": SKU}, self.cliente, botao=botao)
                self.assertFalse(resultado.ok)
                self.assertEqual(resultado.error.codigo, "VALIDATION_ERROR")
        self.assertEqual(self._linhas(), [])
        self.assertEqual(self._consumidos(), 0)

    def test_fora_do_catalogo_e_o_valor_ambiguo_recusam_com_o_codigo(self) -> None:
        fora = self._invocar("request_quote", {"sku": "SKU-999"}, self.cliente, botao="confirm:SKU-999")
        self.assertEqual((fora.ok, fora.error.codigo, fora.error.detalhe), (False, "NOT_FOUND", rep.FORA_DO_CATALOGO))
        pedido = self._invocar("request_quote", {"sku": SKU}, self.cliente, botao=f"confirm:{SKU}")
        quote_id = pedido.data["quote_id"]
        for valor in ("120 50", "12 x 10 mil", "120 dolares"):
            with self.subTest(valor=valor):
                ambiguo = self._invocar("submit_quote", {"quote_id": quote_id, "valor": valor}, self.dono)
                self.assertEqual(ambiguo.error.codigo, "VALIDATION_ERROR")
                self.assertIn(ambiguo.error.detalhe, regras.RECUSAS_DO_VALOR)
        self.assertEqual(self._linhas(), [(quote_id, "pedido", None)])

    def test_um_cliente_nao_responde_pelo_dono_nem_forja_o_quote_id(self) -> None:
        pedido = self._invocar("request_quote", {"sku": SKU}, self.cliente, botao=f"confirm:{SKU}")
        quote_id = pedido.data["quote_id"]
        cliente = self._invocar("submit_quote", {"quote_id": quote_id, "valor": "1 Kz"}, self.cliente)
        self.assertEqual((cliente.ok, cliente.error.codigo), (False, "TENANT_MISMATCH"))
        forjado = self._invocar("submit_quote", {"quote_id": str(uuid.uuid4()), "valor": "120 mil"}, self.dono)
        self.assertEqual(forjado.error.codigo, "NOT_FOUND")
        self.assertEqual(self._linhas(), [(quote_id, "pedido", None)])


class TestOAceito(ComOrcamento):
    """KAM-220: o que o «aceito» le da base, pelo caminho real do pedido e do envio."""

    def test_um_enviado_aceita_se_e_o_contexto_nao_leva_o_valor(self) -> None:
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        self.assertEqual(self._tocar(resposta.action_id, Saida("livre")).desfecho, rep.ENVIADO)
        ultimo = rep.ultimo_pedido(self.app, self.tenant, self.cliente)
        self.assertEqual((ultimo.quote_id, ultimo.estado, ultimo.sku), (pedido.quote_id, "enviado", SKU))
        self.assertEqual(ultimo.validade_ate, resposta.validade_ate)
        self.assertTrue(ultimo.aceitavel(_agora()))
        self.assertEqual(ultimo.referencia, regras.referencia_interna(pedido.quote_id))
        # O «aceito» nao cria pedido: ler o ultimo nao escreve nada.
        self.assertEqual(len(self._linhas()), 1)
        self.assertEqual(len(self._eventos(rep.EVENTO_PEDIDO)), 1)

    def test_um_enviado_vencido_ou_um_cancelado_nao_se_aceitam(self) -> None:
        pedido = self._pedir()
        resposta = self._responder(pedido.quote_id)
        self._tocar(resposta.action_id, Saida("livre"))
        depois = _agora() + datetime.timedelta(days=9)
        ultimo = rep.ultimo_pedido(self.app, self.tenant, self.cliente)
        self.assertFalse(ultimo.aceitavel(depois))
        self.assertTrue(ultimo.fechado(depois))
        outro = rep.pedir(self.app, self.tenant, self.cliente, self.conversa.conversation_id,
                          "SKU-301", None, _agora())
        rep.cancelar(self.app, self.tenant, self.dono, outro.quote_id)
        ultimo = rep.ultimo_pedido(self.app, self.tenant, self.cliente)
        self.assertEqual((ultimo.quote_id, ultimo.estado), (outro.quote_id, "cancelado"))
        self.assertTrue(ultimo.fechado(_agora()))
        self.assertFalse(ultimo.aceitavel(_agora()))
