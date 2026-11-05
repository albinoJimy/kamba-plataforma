"""Gate 8: a confirmacao humana auditada, contra um PostgreSQL real (KAM-054).

Oito dos nove Criterios de Aceitacao do bloco medem-se aqui, porque o objecto da
prova e o servidor e nao um duplo. O criterio 1 — o tecto por pedido do
`createCharge` — mede-se no `packages/core-ts/tests/pagamentos.manual.test.ts`,
que e onde o adaptador vive.

## Cada recusa mede-se nas duas direccoes, e a razao esta medida

Quatro dos nove criterios sao recusas. Uma suite que so medisse recusas fica
**verde sobre um caminho que nao funciona de todo** — aconteceu neste
repositorio, e e a razao do padrao da «sonda positiva». Por isso cada recusa
tem par: o caminho ilegitimo e recusado **e** o legitimo passa, com o mesmo
arranjo e a mudar uma coisa so.

E ha uma sonda que vale por todas: a `cobranca_paga` do `manual_base.py` leva uma
cobranca a `paga` **pelo caminho humano inteiro**, e os ensaios da reversao
correm sobre ela. Se a declaracao, o desafio ou a confirmacao estivessem
quebrados, essa semente falhava — isto e, os ensaios do criterio 8 nao podem
ficar verdes sobre um caminho de confirmacao que nao funciona.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import uuid

import ligacao
from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate
from tests_pagamentos.base import VALOR
from tests_pagamentos.manual_base import (
    TECTO_DA_DUPLA,
    ComConfirmacaoManual,
)


class TestDeclaracaoDoCliente(ComConfirmacaoManual):
    """Criterio 3: a declaracao **so** registra, e a imagem nao prova nada."""

    def test_a_declaracao_cria_uma_fase_e_poe_a_cobranca_pendente(self) -> None:
        _, evento, estado, repetida = self.declarar(
            self.cobranca, self.cliente, "msg-1"
        )
        self.assertFalse(repetida)
        self.assertIsNotNone(evento)
        self.assertEqual(estado, "pendente_confirmacao")
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(
            self.fases(self.cobranca), [("declaracao_cliente", None, None, None)]
        )

    def test_a_declaracao_nao_confirma_nada(self) -> None:
        """O «so» do criterio 3, medido e nao lido.

        Nao basta a cobranca ficar `pendente_confirmacao`: tem de **nao** haver
        `pagamento_confirmado` nenhum. E a afirmacao que o criterio faz, e e
        diferente de «o estado esta certo» — um caminho que escrevesse os dois
        eventos deixava o estado certo e o ledger a dizer que o pagamento foi
        confirmado por uma mensagem do cliente.
        """
        self.declarar(self.cobranca, self.cliente, "msg-1")
        self.confirmar(self.cursor, self.tenant)
        tipos = [linha[0] for linha in self.eventos_do_ensaio(self.cobranca)]
        self.assertEqual(tipos, ["confirmacao_manual_pedida"])
        self.assertNotIn("pagamento_confirmado", tipos)

    def test_o_evento_da_declaracao_nao_e_uma_origem_autenticada(self) -> None:
        """`authn_ok = false`, e e uma afirmacao e nao um descuido.

        Uma declaracao do cliente **nao** e uma origem autenticada (G1): poe-la
        a `true` era escrever no ledger o contrario do que o ADR-013 fixa, e
        ficava la para sempre — o registo e *append-only*.
        """
        self.declarar(self.cobranca, self.cliente, "msg-1")
        self.confirmar(self.cursor, self.tenant)
        self.semente.execute(
            "SELECT authn_ok, authn_method, decisao, motivo "
            "  FROM platform.payment_events "
            " WHERE charge_id = %s AND tipo_evento = 'confirmacao_manual_pedida'",
            (self.cobranca,),
        )
        authn_ok, metodo, decisao, motivo = self.semente.fetchone()
        self.assertFalse(authn_ok)
        self.assertEqual(metodo, "manual")
        self.assertEqual(decisao, "informativo")
        self.assertEqual(motivo, "declaracao_do_cliente_nao_e_prova")

    def test_a_evidencia_sem_o_rotulo_nao_entra(self) -> None:
        """O `CHECK` do M-7: nao ha como gravar um anexo sem dizer que nao prova."""
        with self.assertRaises(Exception) as apanhado:
            self.declarar(self.cobranca, self.cliente, "msg-1", "sto://a/b.jpg")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)

    def test_a_evidencia_com_o_rotulo_entra(self) -> None:
        """A sonda positiva do caso acima."""
        self.declarar(
            self.cobranca, self.cliente, "msg-1", "nao_prova:sto://a/b.jpg"
        )
        self.confirmar(self.cursor, self.tenant)
        self.semente.execute(
            "SELECT evidencia_ref FROM platform.manual_confirmations "
            " WHERE charge_id = %s",
            (self.cobranca,),
        )
        self.assertEqual(self.semente.fetchone()[0], "nao_prova:sto://a/b.jpg")

    def test_o_rotulo_tem_de_estar_no_principio(self) -> None:
        """Um `LIKE` mal escrito aceitava o rotulo no meio da cadeia."""
        with self.assertRaises(Exception) as apanhado:
            self.declarar(
                self.cobranca, self.cliente, "msg-1", "sto://a/nao_prova:b.jpg"
            )
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)


class TestQuemConfirma(ComConfirmacaoManual):
    """Criterio 2: so quem esta em `payment_confirmers` activo, e nunca o cliente."""

    def setUp(self) -> None:
        super().setUp()
        self.declarar(self.cobranca, self.cliente, "declaracao")
        self.confirmar(self.cursor, self.tenant)

    def test_um_bsuid_fora_da_tabela_nao_tem_efeito(self) -> None:
        estranho = self.criar_contacto(self.tenant)
        linha = self.confirmar_manual(self.cobranca, estranho, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "rejeita")
        self.assertEqual(linha[4], "sem_confirmador")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")
        self.assertIn(
            "confirmacao_manual_rejeitada",
            [l[0] for l in self.eventos_do_ensaio(self.cobranca)],
        )

    def test_e_o_pagamento_nao_fica_pago(self) -> None:
        estranho = self.criar_contacto(self.tenant)
        self.confirmar_manual(self.cobranca, estranho, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertNotIn(
            "pagamento_confirmado",
            [l[0] for l in self.eventos_da_cobranca(self.cobranca)],
        )

    def test_um_confirmador_inactivo_e_como_um_que_nao_existe(self) -> None:
        inactivo = self.criar_contacto(self.tenant)
        self.criar_confirmador(self.tenant, inactivo, ativo=False)
        linha = self.confirmar_manual(self.cobranca, inactivo, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[4], "sem_confirmador")

    def test_o_cliente_nunca_confirma_o_seu_proprio_pagamento(self) -> None:
        """**O ensaio que o criterio 2 nomeia:** «teste com o BSUID do cliente»."""
        linha = self.confirmar_manual(self.cobranca, self.cliente, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "rejeita")
        self.assertEqual(linha[4], "cliente_nao_confirma")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")

    def test_nem_quando_o_cliente_esta_na_tabela_de_confirmadores(self) -> None:
        """A ordem das portas, medida.

        Com a tabela de confirmadores consultada **antes** do cliente, um erro
        de provisionamento que pusesse o contacto do cliente na lista
        deixava-o confirmar o proprio pagamento. E a fraude mais obvia deste
        caminho, e nao se fecha com disciplina de provisionamento.
        """
        self.criar_confirmador(self.tenant, self.cliente, papel="dono", segunda=True)
        linha = self.confirmar_manual(self.cobranca, self.cliente, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[4], "cliente_nao_confirma")

    def test_o_dono_confirma_e_a_cobranca_fica_paga(self) -> None:
        """A sonda positiva dos cinco casos acima."""
        linha = self.confirmar_manual(self.cobranca, self.dono, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")
        self.assertEqual(linha[2], "paga")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "paga")

    def test_o_authn_ok_distingue_quem_falhou_de_o_que_falhou(self) -> None:
        """Um BSUID forjado nao e uma origem autenticada; um valor errado e.

        Com os dois a `true`, o painel de ops nao separava uma tentativa de
        fraude de um engano de quem tem direito a confirmar — e e a distincao
        que faz o alerta do §4.6 valer alguma coisa.
        """
        estranho = self.criar_contacto(self.tenant)
        self.confirmar_manual(self.cobranca, estranho, "forjado", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.semente.execute(
            "SELECT authn_ok FROM platform.payment_events "
            " WHERE charge_id = %s AND motivo = 'sem_confirmador'",
            (self.cobranca,),
        )
        self.assertFalse(self.semente.fetchone()[0])

        self.declarar(self.cobranca, self.cliente, "declaracao-2")
        self.confirmar(self.cursor, self.tenant)
        self.confirmar_manual(self.cobranca, self.dono, "valor-errado", VALOR - 1)
        self.confirmar(self.cursor, self.tenant)
        self.semente.execute(
            "SELECT authn_ok FROM platform.payment_events "
            " WHERE charge_id = %s AND motivo = 'valor_nao_bate'",
            (self.cobranca,),
        )
        self.assertTrue(self.semente.fetchone()[0])

    def test_sem_declaracao_a_funcao_recusa_em_vez_de_seguir(self) -> None:
        """Falhar fechado: sem declaracao nao se sabe quem e o cliente.

        Se a funcao seguisse, a guarda mais importante deste caminho — o cliente
        nao confirma — **nao corria**, e nada no resultado dizia que ela nao
        tinha corrido. E a diferenca entre uma guarda que falha e uma guarda que
        se salta.

        **E a guarda e inalcancavel pelo caminho publico, e isso diz-se em vez
        de se esconder.** A unica aresta que leva uma cobranca a
        `pendente_confirmacao` e o `confirmacao_manual_pedida`, que so a
        `manual_declarar` escreve — e ela escreve a fase na mesma transaccao.
        Depois de a `manual_confirmar` passar a exigir `pendente_confirmacao`
        (ver o `TestGuardaDeEstado`), uma cobranca sem declaracao e recusada
        **antes**, pelo estado: foi exactamente o que este ensaio mediu quando
        parou de passar, com «esta em emitida e nao espera confirmacao».

        Para medir a guarda que resta, chega-se-lhe pela unica via que existe:
        apagar a fase com o **superutilizador** depois de a cobranca estar em
        `pendente_confirmacao`. Nao e uma via de producao — nenhum papel de
        aplicacao tem `DELETE` nesta tabela —, e e por isso que esta guarda e um
        cinto e nao a barreira. O que o ensaio prova e que ela existe e diz
        porque; sem ele, ninguem saberia se o cinto esta apertado.
        """
        # O `setUp` desta classe ja declarou, e a cobranca esta em
        # `pendente_confirmacao`: declarar outra vez e que falha, porque um
        # segundo `confirmacao_manual_pedida` nao tem aresta a partir dali.
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "pendente_confirmacao")
        self.semente.execute(
            "DELETE FROM platform.manual_confirmations "
            " WHERE charge_id = %s AND fase = 'declaracao_cliente'",
            (self.cobranca,),
        )
        self.assertEqual(self.fases(self.cobranca), [])

        with self.assertRaises(Exception) as apanhado:
            self.confirmar_manual(self.cobranca, self.dono, "msg-x", VALOR)
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("declaracao_cliente", str(apanhado.exception))

    def test_e_com_a_declaracao_no_lugar_passa(self) -> None:
        """A sonda positiva do caso acima, sem a qual ele nao diz nada."""
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "pendente_confirmacao")
        linha = self.confirmar_manual(self.cobranca, self.dono, "msg-ok", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")


class TestDesafioDoValor(ComConfirmacaoManual):
    """Criterio 4: o centimo, e sem tolerancia nenhuma."""

    def setUp(self) -> None:
        super().setUp()
        self.declarar(self.cobranca, self.cliente, "declaracao")
        self.confirmar(self.cursor, self.tenant)

    def test_um_centimo_a_menos_rejeita_e_a_cobranca_volta_a_emitida(self) -> None:
        linha = self.confirmar_manual(self.cobranca, self.dono, "msg-2", VALOR - 1)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "rejeita")
        self.assertEqual(linha[4], "valor_nao_bate")
        self.assertFalse(linha[5])
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")

    def test_um_centimo_a_mais_tambem(self) -> None:
        linha = self.confirmar_manual(self.cobranca, self.dono, "msg-2", VALOR + 1)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[4], "valor_nao_bate")

    def test_o_valor_igual_avanca(self) -> None:
        """A sonda positiva do centimo."""
        linha = self.confirmar_manual(self.cobranca, self.dono, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")
        self.assertTrue(linha[5])

    def test_o_valor_declarado_e_o_veredicto_ficam_no_registo(self) -> None:
        """O M-6: o que o dono escreveu fica auditavel, certo ou errado."""
        self.confirmar_manual(self.cobranca, self.dono, "msg-2", VALOR - 1)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(
            self.fases(self.cobranca),
            [
                ("declaracao_cliente", None, None, None),
                ("rejeicao", False, "valor_nao_bate", VALOR - 1),
            ],
        )


class TestDuplaAprovacao(ComConfirmacaoManual):
    """Criterio 5: acima do tecto, duas pessoas — e nao a mesma duas vezes."""

    def setUp(self) -> None:
        super().setUp()
        self.alta = self.criar_cobranca(
            self.tenant,
            self.conta,
            provider="manual",
            metodo="manual",
            amount_minor=TECTO_DA_DUPLA + 1,
        )
        self.declarar(self.alta, self.cliente, "declaracao-alta")
        self.confirmar(self.cursor, self.tenant)

    def test_no_tecto_exacto_uma_confirmacao_basta(self) -> None:
        no_tecto = self.criar_cobranca(
            self.tenant,
            self.conta,
            provider="manual",
            metodo="manual",
            amount_minor=TECTO_DA_DUPLA,
        )
        self.declarar(no_tecto, self.cliente, "d-tecto")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(no_tecto, self.dono, "c-tecto", TECTO_DA_DUPLA)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")
        self.assertEqual(self.estado_da_cobranca(no_tecto), "paga")

    def test_acima_do_tecto_a_primeira_nao_paga(self) -> None:
        linha = self.confirmar_manual(
            self.alta, self.dono, "c-1", TECTO_DA_DUPLA + 1
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "exige_segunda")
        self.assertEqual(self.estado_da_cobranca(self.alta), "pendente_confirmacao")

    def test_a_segunda_pelo_mesmo_contacto_e_rejeitada(self) -> None:
        self.confirmar_manual(self.alta, self.dono, "c-1", TECTO_DA_DUPLA + 1)
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(
            self.alta, self.dono, "c-2", TECTO_DA_DUPLA + 1
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "rejeita")
        self.assertEqual(linha[4], "mesmo_confirmador")

    def test_outro_confirmador_sem_a_marca_tambem_nao_conclui(self) -> None:
        sem_marca = self.criar_contacto(self.tenant)
        self.criar_confirmador(
            self.tenant, sem_marca, papel="funcionario", segunda=False
        )
        self.confirmar_manual(self.alta, self.dono, "c-1", TECTO_DA_DUPLA + 1)
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(
            self.alta, sem_marca, "c-2", TECTO_DA_DUPLA + 1
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[4], "sem_segunda_aprovacao")

    def test_so_outro_confirmador_com_a_marca_conclui(self) -> None:
        """A sonda positiva das duas acima, e o caminho feliz do criterio 5."""
        self.confirmar_manual(self.alta, self.dono, "c-1", TECTO_DA_DUPLA + 1)
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(
            self.alta, self.segundo, "c-2", TECTO_DA_DUPLA + 1
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")
        self.assertEqual(self.estado_da_cobranca(self.alta), "paga")
        self.assertEqual(
            [fase for fase, *_ in self.fases(self.alta)],
            ["declaracao_cliente", "confirmacao", "segunda_aprovacao"],
        )

    def test_o_evento_humano_tem_actor_e_authn_method_manual(self) -> None:
        """O M-6, e o que o criterio 5 chama `humano_auditado`.

        **O valor e `manual`.** O criterio escreve `humano_auditado`, que nao
        existe no dominio de quatro do §6.2 — e o
        `payment_events_authn_method_ck` recusa-o. O lado errado e o criterio: o
        §4.2 M-6, que e a regra que ele implementa, escreve `manual`. Ver a
        emenda 1.60 do dicionario.
        """
        self.confirmar_manual(self.alta, self.dono, "c-1", TECTO_DA_DUPLA + 1)
        self.confirmar(self.cursor, self.tenant)
        self.confirmar_manual(self.alta, self.segundo, "c-2", TECTO_DA_DUPLA + 1)
        self.confirmar(self.cursor, self.tenant)
        self.semente.execute(
            "SELECT authn_method, authn_ok, decisao, actor_kind, actor_id "
            "  FROM platform.payment_events "
            " WHERE charge_id = %s AND tipo_evento = 'pagamento_confirmado'",
            (self.alta,),
        )
        metodo, ok, decisao, especie, actor = self.semente.fetchone()
        self.assertEqual(metodo, "manual")
        self.assertTrue(ok)
        self.assertEqual(decisao, "aceite")
        self.assertEqual(especie, "dono")
        self.assertEqual(str(actor), self.segundo)

    def test_sem_tecto_da_dupla_declarado_exige_sempre_a_segunda(self) -> None:
        """«Sem tecto» nao quer dizer «sem limite», e aqui quer dizer «dupla»."""
        outro = self.criar_tenant()
        conta = self.criar_conta(outro, provider="manual")
        self.dar_limites(outro, manual_dupla_acima_minor=None)
        cliente = self.criar_contacto(outro)
        dono = self.criar_contacto(outro)
        self.criar_confirmador(outro, dono)
        cobranca = self.criar_cobranca(
            outro, conta, provider="manual", metodo="manual", amount_minor=1_000
        )
        cursor = self.cursor_papel("app", outro)
        self.declarar(cobranca, cliente, "d", cursor=cursor)
        self.confirmar(cursor, outro)
        linha = self.confirmar_manual(cobranca, dono, "c", 1_000, cursor=cursor)
        self.confirmar(cursor, outro)
        self.assertEqual(linha[3], "exige_segunda")


class TestLimitesDaJanela(ComConfirmacaoManual):
    """Criterio 6: os dois limites retem para ops, com o sinal escrito."""

    def test_o_limite_diario_excedido_retem(self) -> None:
        self.dar_limites(self.tenant, manual_daily_max_minor=VALOR - 1)
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "retem")
        self.assertEqual(linha[4], "limite_diario")
        self.assertIsNotNone(linha[6])
        self.assertEqual(
            self.sinais(self.cobranca),
            [("manual_limite_diario", 3, "reter_confirmacao")],
        )
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "pendente_confirmacao")

    def test_retida_nao_fica_paga(self) -> None:
        self.dar_limites(self.tenant, manual_daily_max_minor=VALOR - 1)
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertNotIn(
            "pagamento_confirmado",
            [l[0] for l in self.eventos_da_cobranca(self.cobranca)],
        )

    def test_no_tecto_diario_exacto_passa(self) -> None:
        """A sonda positiva do limite diario, e a fronteira dos dois lados."""
        self.dar_limites(self.tenant, manual_daily_max_minor=VALOR)
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")
        self.assertEqual(self.sinais(self.cobranca), [])

    def test_o_limite_por_contacto_excedido_retem_com_a_outra_regra(self) -> None:
        self.dar_limites(self.tenant, manual_max_por_contacto_24h=0)
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[4], "limite_por_contacto")
        self.assertEqual(
            self.sinais(self.cobranca),
            [("manual_limite_por_contacto_24h", 3, "reter_confirmacao")],
        )

    def test_uma_abaixo_do_tecto_do_contacto_passa(self) -> None:
        """A sonda positiva do limite por contacto."""
        self.dar_limites(self.tenant, manual_max_por_contacto_24h=1)
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")

    def test_sem_tecto_de_janela_declarado_retem(self) -> None:
        self.dar_limites(self.tenant, manual_daily_max_minor=None)
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[4], "limite_diario")

    # ------------------------------------------------- a acumulacao, medida
    #
    # **Os ensaios acima mediam um tecto por pedido e nao um tecto de janela.**
    # Em todos eles a soma do dia e a contagem do contacto comecavam a zero,
    # pelo que `soma + amount > tecto` e `contagem + 1 > tecto` davam o mesmo
    # resultado que `amount > tecto` e `1 > tecto`. A revisao adversarial
    # nomeou a mutacao que isso deixava sobreviver: apagar
    # `v_janela.soma_do_dia_minor +` e `v_janela.confirmacoes_do_contacto +` da
    # funcao, e os ensaios todos ficavam verdes — sobre a regra que o §9 nomeia
    # contra «um comprador a juntar confirmacoes».
    #
    # Os tres ensaios abaixo confirmam **uma** cobranca e medem a seguinte. E a
    # unica forma de a acumulacao entrar na decisao.

    def _confirmar_uma(self, valor: int = VALOR) -> str:
        """Confirma uma cobranca nova deste tenant, e devolve o `id`."""
        cobranca = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual",
            amount_minor=valor,
        )
        self.declarar(cobranca, self.cliente, f"d-{uuid.uuid4().hex}")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(
            cobranca, self.dono, f"c-{uuid.uuid4().hex}", valor
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma", "a semente da acumulacao tem de pagar")
        return cobranca

    def test_a_primeira_confirmacao_conta_para_o_tecto_da_segunda(self) -> None:
        """A acumulacao do tecto diario, a entrar numa decisao.

        Duas cobrancas de `VALOR` com tecto diario `2 * VALOR - 1`: a primeira
        passa (0 + VALOR <= tecto) e a segunda retem (VALOR + VALOR > tecto).
        **Sem o termo acumulado, a segunda passava** — e e por isso que este
        ensaio e o que mede o criterio 6.
        """
        self.dar_limites(self.tenant, manual_daily_max_minor=2 * VALOR - 1)
        self._confirmar_uma()

        segunda = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(segunda, self.cliente, "d-2")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(segunda, self.dono, "c-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "retem")
        self.assertEqual(linha[4], "limite_diario")

    def test_e_com_o_tecto_a_dar_para_as_duas_a_segunda_passa(self) -> None:
        """A sonda positiva da acumulacao: o mesmo arranjo, tecto a chegar."""
        self.dar_limites(self.tenant, manual_daily_max_minor=2 * VALOR)
        self._confirmar_uma()

        segunda = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(segunda, self.cliente, "d-2")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(segunda, self.dono, "c-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")

    def test_a_contagem_do_contacto_acumula_entre_cobrancas(self) -> None:
        """A acumulacao do tecto por contacto, a entrar numa decisao.

        Tecto de **uma** confirmacao por contacto em 24 h: a primeira passa, a
        segunda do **mesmo** cliente retem. Sem o `contagem + 1`, a segunda
        passava.
        """
        self.dar_limites(self.tenant, manual_max_por_contacto_24h=1)
        self._confirmar_uma()

        segunda = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(segunda, self.cliente, "d-2")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(segunda, self.dono, "c-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "retem")
        self.assertEqual(linha[4], "limite_por_contacto")

    def test_e_a_contagem_e_do_contacto_e_nao_do_tenant(self) -> None:
        """A sonda que separa «conta» de «conta a dimensao certa».

        O mesmo tecto de uma por contacto, mas a segunda cobranca declarada por
        **outro** cliente: passa. Sem a dimensao do contacto — se a contagem
        fosse por tenant — esta ficava retida, e o tecto do §9 deixava de ser
        «historico do contacto» para ser um tecto de vendas da PME.
        """
        self.dar_limites(self.tenant, manual_max_por_contacto_24h=1)
        self._confirmar_uma()

        outro_cliente = self.criar_contacto(self.tenant)
        segunda = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(segunda, outro_cliente, "d-2")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(segunda, self.dono, "c-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")

    def test_uma_retencao_nao_conta_para_o_tecto_do_dia(self) -> None:
        """So o que **concluiu** conta, e e a coluna `decisao` que o diz.

        Uma retencao escreve `fase='confirmacao'` com `valor_bate` verdadeiro.
        Enquanto a janela filtrava pela fase, essa retencao somava ao dia o
        dinheiro de uma cobranca que **nao** foi paga — e a primeira retencao do
        dia empurrava a seguinte, propagando «retido para analise» a
        confirmacoes legitimas. Medido pelas tres revisoes adversariais.
        """
        self.dar_limites(self.tenant, manual_daily_max_minor=VALOR)
        # Esta retem: VALOR + VALOR > VALOR.
        grande = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual",
            amount_minor=2 * VALOR,
        )
        self.declarar(grande, self.cliente, "d-grande")
        self.confirmar(self.cursor, self.tenant)
        retida = self.confirmar_manual(grande, self.dono, "c-grande", 2 * VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(retida[3], "retem")

        # E a seguinte, de VALOR, passa: a retida nao conta.
        segunda = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(segunda, self.cliente, "d-2")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(segunda, self.dono, "c-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(
            linha[3],
            "confirma",
            "uma retencao nao e dinheiro confirmado e nao pode consumir o tecto",
        )

    def test_a_janela_conta_o_contacto_que_declarou_e_nao_quem_confirma(self) -> None:
        """A dimensao do M-3, medida.

        E a dimensao que o §9 nomeia («historico do contacto»): o risco e um
        comprador a juntar confirmacoes. Um tecto por **confirmador** era um
        tecto de vendas — o dono confirma todas, por definicao.
        """
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)

        do_cliente = self.janela(self.tenant, self.cliente)
        self.assertEqual(int(do_cliente[2]), 1)
        do_dono = self.janela(self.tenant, self.dono)
        self.assertEqual(int(do_dono[2]), 0)
        self.confirmar(self.cursor, self.tenant)

    def test_a_soma_do_dia_e_por_tenant_e_so_das_confirmadas(self) -> None:
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        antes = self.janela(self.tenant, self.cliente)
        self.assertEqual(int(antes[0]), 0)
        self.confirmar(self.cursor, self.tenant)

        self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        depois = self.janela(self.tenant, self.cliente)
        self.assertEqual(int(depois[0]), VALOR)
        self.assertEqual(int(depois[1]), 100_000_000)
        self.confirmar(self.cursor, self.tenant)

    def test_a_janela_nao_ve_o_tenant_vizinho(self) -> None:
        """A soma do dia e por tenant, e e a RLS que o garante.

        Sem isto, uma PME com muitas vendas esgotava o tecto diario da PME ao
        lado — e o sintoma era «retido para verificacao» em transaccoes
        legitimas de quem nao fez nada.
        """
        vizinho = self.criar_tenant()
        conta = self.criar_conta(vizinho, provider="manual")
        self.dar_limites(vizinho)
        cliente = self.criar_contacto(vizinho)
        dono = self.criar_contacto(vizinho)
        self.criar_confirmador(vizinho, dono)
        cobranca = self.criar_cobranca(
            vizinho, conta, provider="manual", metodo="manual"
        )
        cursor = self.cursor_papel("app", vizinho)
        self.declarar(cobranca, cliente, "d", cursor=cursor)
        self.confirmar(cursor, vizinho)
        self.confirmar_manual(cobranca, dono, "c", VALOR, cursor=cursor)
        self.confirmar(cursor, vizinho)

        meu = self.janela(self.tenant, self.cliente)
        self.assertEqual(int(meu[0]), 0)
        self.confirmar(self.cursor, self.tenant)


class TestSilencioDoDono(ComConfirmacaoManual):
    """Criterio 7: o F-18, e a reserva que **nao** se perde."""

    def setUp(self) -> None:
        super().setUp()
        self.declarar(self.cobranca, self.cliente, "declaracao")
        self.confirmar(self.cursor, self.tenant)

    def test_dentro_da_janela_nao_expira(self) -> None:
        """A sonda negativa: a funcao nao expira o que ainda tem tempo."""
        self.assertEqual(self.expirar(self.cobranca, horas=24), [])
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(
            self.estado_da_cobranca(self.cobranca), "pendente_confirmacao"
        )

    def test_passada_a_janela_volta_a_emitida(self) -> None:
        """Relogio simulado pela **janela** e nao pelo relogio.

        «TTL de 24 h com relogio simulado» (Testes Requeridos). Simula-se
        passando `p_janela_horas => 0`, que e o mesmo que pôr a declaracao 24 h
        atras — e tem a vantagem de nao mexer no `now()` do servidor, que
        falsearia tambem a janela de 24 h da `manual_janela` e a cadeia de
        *hashes*.
        """
        linhas = self.expirar(self.cobranca, horas=0)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][2], "emitida")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")

    def test_e_escreve_a_rejeicao_e_o_evento(self) -> None:
        self.expirar(self.cobranca, horas=0)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(
            self.fases(self.cobranca),
            [
                ("declaracao_cliente", None, None, None),
                ("rejeicao", False, "silencio_do_dono", None),
            ],
        )
        self.semente.execute(
            "SELECT motivo, authn_ok, actor_kind FROM platform.payment_events "
            " WHERE charge_id = %s AND tipo_evento = 'confirmacao_manual_rejeitada'",
            (self.cobranca,),
        )
        motivo, ok, especie = self.semente.fetchone()
        self.assertEqual(motivo, "silencio_do_dono")
        self.assertFalse(ok)
        self.assertEqual(especie, "sistema")

    def test_a_janela_e_em_horas_e_nao_noutra_unidade(self) -> None:
        """A unidade do `p_janela_horas`, medida — e nao so o facto de ser lida.

        Os dois ensaios acima passam `24` sobre uma declaracao com segundos de
        vida e `0`. O par prova que o parametro e lido e **nada** sobre o seu
        significado: trocar `hours =>` por `mins =>` na funcao deixava os dois
        verdes, porque 24 minutos tambem nao passaram e 0 continua a expirar
        tudo. Medido pela revisao adversarial.

        Este mede a grandeza: a declaracao e empurrada **duas horas** para tras
        pela semente, e entao `3` horas nao expira e `1` expira. Com a unidade
        em minutos, o primeiro expirava e o ensaio ficava vermelho.
        """
        self.semente.execute(
            "UPDATE platform.manual_confirmations "
            "   SET criado_at = criado_at - interval '2 hours' "
            " WHERE charge_id = %s AND fase = 'declaracao_cliente'",
            (self.cobranca,),
        )
        self.assertEqual(
            self.expirar(self.cobranca, horas=3),
            [],
            "duas horas nao chegam a uma janela de tres",
        )
        self.confirmar(self.cursor, self.tenant)
        linhas = self.expirar(self.cobranca, horas=1)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(len(linhas), 1, "duas horas passam uma janela de uma")
        self.assertEqual(linhas[0][2], "emitida")

    def test_a_reserva_mantem_se_ate_expira_at(self) -> None:
        """A metade do criterio 7 que e facil de perder.

        Expirar a **confirmacao** nao expira a **cobranca**: o `valid_until`
        fica onde estava e nao se escreve `cobranca_expirada` nenhum. Uma
        implementacao que «limpasse» tudo de uma vez cancelava uma reserva
        valida por o dono nao ter respondido a tempo — isto e, punia o cliente
        por um silencio que nao e dele.
        """
        self.semente.execute(
            "SELECT valid_until FROM platform.payment_charges WHERE id = %s",
            (self.cobranca,),
        )
        antes = self.semente.fetchone()[0]
        self.expirar(self.cobranca, horas=0)
        self.confirmar(self.cursor, self.tenant)
        self.semente.execute(
            "SELECT valid_until FROM platform.payment_charges WHERE id = %s",
            (self.cobranca,),
        )
        self.assertEqual(self.semente.fetchone()[0], antes)
        self.assertNotIn(
            "cobranca_expirada",
            [l[0] for l in self.eventos_da_cobranca(self.cobranca)],
        )

    def test_depois_de_voltar_a_emitida_o_cliente_pode_declarar_outra_vez(self) -> None:
        """A sonda positiva do criterio inteiro: o caminho continua a funcionar."""
        self.expirar(self.cobranca, horas=0)
        self.confirmar(self.cursor, self.tenant)
        _, _, estado, repetida = self.declarar(
            self.cobranca, self.cliente, "declaracao-2"
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertFalse(repetida)
        self.assertEqual(estado, "pendente_confirmacao")
        linha = self.confirmar_manual(self.cobranca, self.dono, "c-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")

    def test_dois_varrimentos_sobre_a_mesma_omissao_nao_escrevem_duas(self) -> None:
        """O `canal_msg_id` sintetico e deterministico, e e por isso que isto fecha."""
        self.expirar(self.cobranca, horas=0)
        self.confirmar(self.cursor, self.tenant)
        # A cobranca ja nao esta em `pendente_confirmacao`, pelo que o segundo
        # varrimento devolve zero linhas pela primeira guarda. O que este ensaio
        # prende e a contagem de fases: uma so.
        self.assertEqual(self.expirar(self.cobranca, horas=0), [])
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(
            len([f for f in self.fases(self.cobranca) if f[0] == "rejeicao"]), 1
        )


class TestReversao(ComConfirmacaoManual):
    """Criterio 8: reverter escreve, e a contagem do ledger so cresce."""

    def setUp(self) -> None:
        super().setUp()
        self.cobranca_paga()
        self.confirmar(self.cursor, self.tenant)
        self.eventos_antes = self.quantos_eventos(self.cobranca)
        # **O actor de ops e um confirmador activo**, porque a `manual_reverter`
        # passou a exigi-lo. A fixture era anterior a guarda, e os cinco ensaios
        # desta classe caíram quando ela entrou — o que e a guarda a morder.
        self.ops = self.criar_contacto(self.tenant)
        self.criar_confirmador(self.tenant, self.ops, papel="dono", segunda=True)

    def test_a_reversao_abre_o_caso_e_move_a_cobranca(self) -> None:
        _, evento, estado, caso = self.reverter(
            self.cobranca, self.ops, "rev-1", "fraude descoberta na conciliacao"
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertIsNotNone(evento)
        self.assertEqual(estado, "reembolso_pendente")
        self.assertIsNotNone(caso)
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "reembolso_pendente")
        self.assertEqual(
            self.casos_de_reembolso(self.cobranca),
            [("aberto", VALOR, "fraude descoberta na conciliacao")],
        )

    def test_nenhuma_linha_e_apagada_e_a_contagem_so_cresce(self) -> None:
        """A propriedade que o criterio 8 nao negoceia."""
        self.reverter(self.cobranca, self.ops, "rev-1", "fraude descoberta")
        self.confirmar(self.cursor, self.tenant)
        depois = self.quantos_eventos(self.cobranca)
        self.assertGreater(depois, self.eventos_antes)
        self.assertIn(
            "pagamento_confirmado",
            [l[0] for l in self.eventos_da_cobranca(self.cobranca)],
            "o evento que a reversao desfaz **fica** no ledger",
        )
        self.assertIn(
            "confirmacao_manual_revertida",
            [l[0] for l in self.eventos_da_cobranca(self.cobranca)],
        )

    def test_e_a_barreira_nao_e_a_funcao_mas_a_tabela(self) -> None:
        """Ao superutilizador, e mesmo sem casar linha nenhuma (KAM-175).

        A funcao nao apaga porque nao tem como; esta medicao e sobre a base.
        Sem ela, «nenhuma linha e apagada» era uma afirmacao sobre o codigo que
        se escreveu, e nao sobre o que a base aceita.
        """
        self.reverter(self.cobranca, self.ops, "rev-1", "fraude descoberta")
        self.confirmar(self.cursor, self.tenant)
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        for sql in (
            "DELETE FROM platform.payment_events WHERE charge_id = %s",
            "DELETE FROM platform.payment_events WHERE charge_id IS NULL",
            "UPDATE platform.payment_events SET motivo = 'x' WHERE charge_id IS NULL",
        ):
            with self.subTest(sql=sql):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, cursor, sql, (self.cobranca,)
                    if "%s" in sql
                    else (),
                )

    def test_quem_nao_e_confirmador_nao_reverte(self) -> None:
        """A guarda que a revisao adversarial obrigou.

        A primeira versao aceitava **qualquer** `p_actor_contact_id` e escrevia
        `actor_kind => 'ops'`: um turno de conversa movia qualquer cobranca
        `paga` para `reembolso_pendente` e abria um caso pelo valor inteiro, que
        e a «abuso de reembolso» do §9. O argumento escrito de defesa protegia o
        **montante** do caso e nao a legitimidade de quem o abre.
        """
        estranho = self.criar_contacto(self.tenant)
        with self.assertRaises(Exception) as apanhado:
            self.reverter(self.cobranca, estranho, "rev-x", "motivo escrito")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("confirmador activo", str(apanhado.exception))

    def test_e_um_confirmador_inactivo_tambem_nao(self) -> None:
        """A mesma guarda, pela outra metade do predicado."""
        inactivo = self.criar_contacto(self.tenant)
        self.criar_confirmador(self.tenant, inactivo, ativo=False)
        with self.assertRaises(Exception) as apanhado:
            self.reverter(self.cobranca, inactivo, "rev-y", "motivo escrito")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)

    def test_um_confirmador_de_outro_tenant_nao_reverte(self) -> None:
        """O predicado filtra pelo tenant da **cobranca**, e nao so pela tabela."""
        vizinho = self.criar_tenant()
        de_b = self.criar_contacto(vizinho)
        self.criar_confirmador(vizinho, de_b, papel="dono", segunda=True)
        with self.assertRaises(Exception) as apanhado:
            self.reverter(self.cobranca, de_b, "rev-z", "motivo escrito")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)

    def test_reverter_sem_motivo_e_recusado(self) -> None:
        for motivo in (None, "", "   "):
            with self.subTest(motivo=motivo):
                with self.assertRaises(Exception) as apanhado:
                    self.reverter(self.cobranca, self.ops, f"rev-{motivo}", motivo)
                self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
                self.cursor.execute("ROLLBACK")
                self.cursor.execute(
                    "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
                )
                self.cursor.fetchone()

    def test_o_caso_leva_o_valor_da_cobranca_e_nao_um_argumento(self) -> None:
        """Nao ha por onde abrir um caso de montante diferente do confirmado.

        E a «abuso de reembolso» da tabela do §9: um ciclo pagar–disputar em que
        o caso vale mais do que o pagamento. A assinatura da funcao nao tem
        parametro de valor, e e isso que o fecha.
        """
        _, _, _, caso = self.reverter(
            self.cobranca, self.ops, "rev-1", "engano do dono"
        )
        self.confirmar(self.cursor, self.tenant)
        self.semente.execute(
            "SELECT valor_minor FROM platform.refund_cases WHERE id = %s", (caso,)
        )
        self.assertEqual(int(self.semente.fetchone()[0]), VALOR)

    def test_a_segunda_reversao_com_a_mesma_mensagem_e_idempotente(self) -> None:
        primeira = self.reverter(self.cobranca, self.ops, "rev-1", "engano")
        self.confirmar(self.cursor, self.tenant)
        contagem = self.quantos_eventos(self.cobranca)
        segunda = self.reverter(self.cobranca, self.ops, "rev-1", "engano")
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(segunda[0], primeira[0])
        self.assertEqual(segunda[3], primeira[3])
        self.assertEqual(self.quantos_eventos(self.cobranca), contagem)
        self.assertEqual(len(self.casos_de_reembolso(self.cobranca)), 1)

    def test_um_canal_msg_id_de_uma_confirmacao_nao_e_uma_reversao_repetida(self) -> None:
        """A primeira versao devolvia a linha da confirmacao e nao revertia nada.

        A guarda de idempotencia casava por `canal_msg_id` em **qualquer** fase,
        pelo que um identificador ja usado por uma confirmacao fazia esta funcao
        sair pelo ramo da repeticao — em silencio, sem reverter, com um
        `refund_case_id` de outro caso ou nulo. Apanhado pela revisao
        adversarial; e a mesma classe do `CASE` da `manual_confirmar`.

        Procura agora so fases `reversao`, pelo que o `canal_msg_id` da
        confirmacao **reverte** de verdade — e e isso que este ensaio mede.
        """
        self.semente.execute(
            "SELECT canal_msg_id FROM platform.manual_confirmations "
            " WHERE charge_id = %s AND fase = 'confirmacao'",
            (self.cobranca,),
        )
        msg_da_confirmacao = self.semente.fetchone()[0]

        # **A recusa e explicita, e nao um nome de restricao.** Com a guarda de
        # repeticao a casar so fases `reversao`, este identificador deixa de
        # sair pelo ramo da repeticao — e bateria no
        # `manual_confirmations_msg_uq` tres linhas abaixo, porque a unicidade e
        # `(charge_id, canal_msg_id)`. O que o ensaio mede e que a funcao o diz
        # por extenso em vez de deixar um `23505` chegar a quem chama.
        with self.assertRaises(Exception) as apanhado:
            self.reverter(
                self.cobranca, self.ops, msg_da_confirmacao, "engano do dono"
            )
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("nao e uma reversao", str(apanhado.exception))
        self.cursor.execute("ROLLBACK")
        self.cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
        )
        self.cursor.fetchone()

        # E a sonda positiva: com identificador proprio, reverte.
        _, evento, estado, caso = self.reverter(
            self.cobranca, self.ops, "rev-propria", "engano do dono"
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertIsNotNone(evento, "com identificador proprio, reverte")
        self.assertEqual(estado, "reembolso_pendente")
        self.assertIsNotNone(caso)

    def test_a_quinta_aresta_existe_e_so_de_paga(self) -> None:
        """A aresta nova, e **so** ela: de `emitida` continua recusada."""
        self.cursor.execute(
            "SELECT platform.next_state('paga', 'confirmacao_manual_revertida', "
            "  'rejeitada')"
        )
        self.assertEqual(self.cursor.fetchone()[0], "reembolso_pendente")
        self.cursor.execute(
            "SELECT platform.next_state('emitida', 'confirmacao_manual_revertida', "
            "  'rejeitada')"
        )
        self.assertIsNone(self.cursor.fetchone()[0])


class TestIdempotencia(ComConfirmacaoManual):
    """Criterio 9: a mesma mensagem duas vezes produz **uma** confirmacao."""

    def test_a_mesma_declaracao_duas_vezes_da_uma_fase(self) -> None:
        primeira = self.declarar(self.cobranca, self.cliente, "msg-1")
        self.confirmar(self.cursor, self.tenant)
        contagem = self.quantos_eventos(self.cobranca)
        segunda = self.declarar(self.cobranca, self.cliente, "msg-1")
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(segunda[0], primeira[0])
        self.assertTrue(segunda[3])
        self.assertIsNone(segunda[1])
        self.assertEqual(len(self.fases(self.cobranca)), 1)
        self.assertEqual(self.quantos_eventos(self.cobranca), contagem)

    def test_a_mesma_confirmacao_duas_vezes_da_uma_confirmacao(self) -> None:
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        primeira = self.confirmar_manual(self.cobranca, self.dono, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        contagem = self.quantos_eventos(self.cobranca)
        segunda = self.confirmar_manual(self.cobranca, self.dono, "msg-2", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(segunda[0], primeira[0])
        self.assertTrue(segunda[7])
        self.assertEqual(self.quantos_eventos(self.cobranca), contagem)
        self.assertEqual(
            len([f for f in self.fases(self.cobranca) if f[0] == "confirmacao"]), 1
        )

    def test_a_repeticao_nao_levanta(self) -> None:
        """E uma decisao, e esta escrita na funcao.

        Quem reentrega uma mensagem — o CHR, por retentativa — teria de
        distinguir «ja estava» de «falhou» apanhando um `23505` pelo nome da
        restricao. Devolver a linha com `repetida = true` da-lhe a resposta sem
        o obrigar a ler mensagens de erro.
        """
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        for _ in range(3):
            self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)

    def test_repetir_uma_retida_devolve_retem_e_nao_confirma(self) -> None:
        """**O defeito perfeito, e esta e a medicao que faltava.**

        A reentrega de uma mensagem e a razao escrita para este ramo nao
        levantar: quem reentrega e o CHR, por retentativa. Enquanto a decisao
        era derivada da **fase**, uma confirmacao **retida** voltava como
        `decisao = 'confirma'` com `motivo = 'limite_diario'` e
        `estado_novo = 'pendente_confirmacao'` — tres campos a contradizerem-se,
        e o primeiro a dizer a quem chama que um pagamento retido para ops foi
        confirmado. E a frase que o `TestAcordoComATabelaPura` usa para se
        justificar: «o agente diz ao dono uma razao que nao e a razao».
        """
        self.dar_limites(self.tenant, manual_daily_max_minor=VALOR - 1)
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        primeira = self.confirmar_manual(self.cobranca, self.dono, "msg-r", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(primeira[3], "retem")

        segunda = self.confirmar_manual(self.cobranca, self.dono, "msg-r", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(segunda[3], "retem", "a repeticao devolve o que ficou gravado")
        self.assertEqual(segunda[4], "limite_diario")
        self.assertTrue(segunda[7])

    def test_repetir_uma_a_espera_da_segunda_devolve_exige_segunda(self) -> None:
        """O mesmo, no caminho da dupla do M-5."""
        alta = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual",
            amount_minor=TECTO_DA_DUPLA + 1,
        )
        self.declarar(alta, self.cliente, "d-alta")
        self.confirmar(self.cursor, self.tenant)
        primeira = self.confirmar_manual(alta, self.dono, "msg-e", TECTO_DA_DUPLA + 1)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(primeira[3], "exige_segunda")

        segunda = self.confirmar_manual(alta, self.dono, "msg-e", TECTO_DA_DUPLA + 1)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(segunda[3], "exige_segunda")
        self.assertTrue(segunda[7])

    def test_o_canal_msg_id_da_declaracao_nao_e_uma_confirmacao_repetida(self) -> None:
        """Era a via pela qual o cliente obtinha um «confirma».

        O `canal_msg_id` da mensagem «paguei» do proprio cliente, passado a
        `manual_confirmar`, casava a fase `declaracao_cliente` e o `CASE`
        devolvia `confirma` com `valor_bate` nulo — sem passar por confirmador
        nenhum. Uma mensagem que pertence a uma fase que esta funcao nao escreve
        e outro facto com o mesmo identificador, e recusa-se.
        """
        self.declarar(self.cobranca, self.cliente, "msg-do-cliente")
        self.confirmar(self.cursor, self.tenant)
        with self.assertRaises(Exception) as apanhado:
            self.confirmar_manual(self.cobranca, self.dono, "msg-do-cliente", VALOR)
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("nao e uma confirmacao", str(apanhado.exception))

    def test_a_unicidade_e_por_cobranca_e_nao_global(self) -> None:
        """O mesmo `canal_msg_id` noutra cobranca e outro facto.

        Os identificadores de mensagem vem da Meta e nao de nos. Com unicidade
        global, uma colisao fazia a segunda cobranca recusar uma confirmacao
        legitima — e o dono via «ja confirmou» sobre um pedido que nunca tocou.
        """
        outra = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(self.cobranca, self.cliente, "msg-colidida")
        self.declarar(outra, self.cliente, "msg-colidida")
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(len(self.fases(self.cobranca)), 1)
        self.assertEqual(len(self.fases(outra)), 1)

    def test_duas_confirmacoes_simultaneas_em_ligacoes_proprias(self) -> None:
        """Concorrencia (Testes Requeridos), e **em paralelo de verdade**.

        A primeira versao deste ensaio abria duas ligacoes e chamava a funcao nas
        duas **na mesma linha de execucao**, sem confirmar a primeira. Isso nao e
        concorrencia: e um bloqueio. O `FOR UPDATE` da primeira ficava pendurado
        numa transaccao aberta e a segunda chamada esperava por ele para sempre —
        a suite inteira parou nos 900 s do `gate_bd.py`, e a mensagem que ele
        imprime («provavelmente um bloqueio entre ligacoes») estava certa a
        primeira. Fica escrito porque o ensaio parecia correcto: as ligacoes
        **eram** duas.

        Com `ThreadPoolExecutor`, como o `test_concorrencia.py` do ledger: cada
        chamada tem a sua ligacao **e** a sua linha de execucao, e cada uma
        confirma a sua transaccao. O `FOR UPDATE` serializa-as — nao as faz
        colidir —, pelo que a segunda a entrar ve a fase da primeira e bate no
        `mesmo_confirmador`. Uma paga, a outra nao, e o ledger tem **um**
        `pagamento_confirmado`.
        """
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)

        def confirmar_noutra_ligacao(indice: int):
            conexao = ligacao.ligar("app")
            try:
                cursor = conexao.cursor()
                cursor.execute(
                    "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
                )
                cursor.fetchone()
                linha = self.confirmar_manual(
                    self.cobranca, self.dono, f"c-{indice}", VALOR, cursor=cursor
                )
                conexao.commit()
                return linha[3], None
            except Exception as erro:  # noqa: BLE001 — o SQLSTATE e o resultado
                conexao.rollback()
                return None, sqlstate(erro)
            finally:
                conexao.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as piscina:
            resultados = [
                tarefa.result()
                for tarefa in concurrent.futures.as_completed(
                    [piscina.submit(confirmar_noutra_ligacao, i) for i in range(2)]
                )
            ]

        # **A segunda e recusada pela guarda de estado, e isso e o desenho e
        # nao uma falha.** Este ensaio comecou por exigir que as duas
        # devolvessem decisao — uma `confirma` e outra `rejeita` —, e o que ele
        # encontrou foi um `23514` na segunda, com uma mensagem sobre
        # transicoes do §7.1. A causa era real: a primeira paga a cobranca, e
        # uma **rejeicao** sobre uma cobranca `paga` nao tem aresta nenhuma.
        #
        # A correccao foi na funcao e nao no ensaio: a `manual_confirmar` passou
        # a exigir `pendente_confirmacao` e a recusar com a razao certa. O que
        # este ensaio mede agora e a propriedade que importa — uma paga, a outra
        # nao, e **um** `pagamento_confirmado` no ledger.
        decisoes = sorted(d for d, _ in resultados if d is not None)
        recusas = [e for d, e in resultados if d is None]
        self.assertEqual(decisoes, ["confirma"], "exactamente uma confirma")
        self.assertEqual(
            recusas,
            [VIOLACAO_DE_CHECK],
            "a segunda e recusada pela guarda de estado, nao por uma colisao",
        )
        self.assertEqual(
            len(
                [
                    l
                    for l in self.eventos_da_cobranca(self.cobranca)
                    if l[0] == "pagamento_confirmado"
                ]
            ),
            1,
            "uma cobranca nao se paga duas vezes",
        )


class TestGuardaDeEstado(ComConfirmacaoManual):
    """So se confirma uma cobranca que **espera** confirmacao.

    A guarda saiu de um defeito que o ensaio de concorrencia encontrou — ver o
    comentario na `manual_confirmar` da revisao `0032` —, e fecha mais do que
    uma mensagem de erro: sem ela, uma confirmacao sobre uma cobranca em
    qualquer outro estado **escrevia a fase** em `manual_confirmations` antes de
    o `append_payment_event` recusar. E a fase, com `valor_bate` verdadeiro, e
    exactamente o que o G8 exige — isto e, o desenho passava a depender de a
    transaccao reverter.
    """

    def test_uma_cobranca_emitida_ainda_nao_espera_confirmacao(self) -> None:
        with self.assertRaises(Exception) as apanhado:
            self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("nao espera", str(apanhado.exception))

    def test_uma_cobranca_paga_ja_nao_espera(self) -> None:
        self.cobranca_paga()
        self.confirmar(self.cursor, self.tenant)
        with self.assertRaises(Exception) as apanhado:
            self.confirmar_manual(self.cobranca, self.segundo, "c-2", VALOR)
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("esta em paga", str(apanhado.exception))

    def test_e_nenhuma_das_duas_deixa_fase_escrita(self) -> None:
        """A parte que importa: a recusa vem **antes** de escrever a fase."""
        with self.assertRaises(Exception):
            self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.cursor.execute("ROLLBACK")
        self.cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
        )
        self.cursor.fetchone()
        self.assertEqual(self.fases(self.cobranca), [])

    def test_em_pendente_confirmacao_passa(self) -> None:
        """A sonda positiva dos tres acima."""
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[3], "confirma")


class TestG8DoCaminhoHumano(ComConfirmacaoManual):
    """O G8 do §5, nas duas direccoes — e ao superutilizador.

    Era o *gate* que nao existia em sitio nenhum: um `pagamento_confirmado` com
    `authn_method='manual'` e um `actor_id` qualquer passava, sem confirmador,
    sem desafio de valor e sem limites. O caminho humano era o unico dos tres do
    G1 sem guarda, e e o mais atacavel dos tres.
    """

    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin")
        self.directo = self.admin.cursor()

    def test_sem_fase_o_confirmado_humano_e_recusado(self) -> None:
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)

    def test_com_a_fase_passa(self) -> None:
        """A sonda positiva: sem ela, o caso acima podia recusar por outra razao."""
        self.semente.execute(
            "INSERT INTO platform.manual_confirmations "
            "(tenant_id, charge_id, fase, actor_contact_id, canal_msg_id, "
            " valor_declarado_minor, valor_bate, decisao) "
            "VALUES (%s, %s, 'confirmacao', %s, 'g8-ok', %s, true, 'confirma')",
            (self.tenant, self.cobranca, self.dono, VALOR),
        )
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.directo.execute(sql, args)
        self.admin.rollback()

    def test_a_fase_de_outro_actor_nao_serve(self) -> None:
        """O `actor_id` tem de **bater**, e nao so existir.

        Sem a igualdade, uma confirmacao legitima do dono deixava passar um
        evento com o `actor_id` de outra pessoa — e a atribuicao do acto humano
        no ledger deixava de ser verificavel, que e o que o M-6 garante.
        """
        self.semente.execute(
            "INSERT INTO platform.manual_confirmations "
            "(tenant_id, charge_id, fase, actor_contact_id, canal_msg_id, "
            " valor_declarado_minor, valor_bate, decisao) "
            "VALUES (%s, %s, 'confirmacao', %s, 'g8-outro', %s, true, 'confirma')",
            (self.tenant, self.cobranca, self.dono, VALOR),
        )
        sql, args = self.inserir_evento_humano(
            self.cobranca, self.segundo, self.directo
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)

    def test_uma_fase_com_o_valor_errado_nao_serve(self) -> None:
        self.semente.execute(
            "INSERT INTO platform.manual_confirmations "
            "(tenant_id, charge_id, fase, actor_contact_id, canal_msg_id, "
            " valor_declarado_minor, valor_bate, decisao) "
            "VALUES (%s, %s, 'confirmacao', %s, 'g8-valor', %s, false, 'confirma')",
            (self.tenant, self.cobranca, self.dono, VALOR - 1),
        )
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)

    def test_uma_declaracao_nao_e_uma_fase_que_conclui(self) -> None:
        """O caminho mais directo do ataque: o cliente declara e isso basta.

        A `declaracao_cliente` tem actor e `canal_msg_id`; o que nao tem e
        `valor_bate`. Se o G8 aceitasse qualquer fase, o cliente declarava o
        pagamento e um `pagamento_confirmado` com o `actor_id` dele passava.
        """
        self.semente.execute(
            "INSERT INTO platform.manual_confirmations "
            "(tenant_id, charge_id, fase, actor_contact_id, canal_msg_id) "
            "VALUES (%s, %s, 'declaracao_cliente', %s, 'g8-decl')",
            (self.tenant, self.cobranca, self.cliente),
        )
        sql, args = self.inserir_evento_humano(
            self.cobranca, self.cliente, self.directo
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)

    def _semear_fase(self, decisao: str, fase: str = "confirmacao",
                     actor: str | None = None, bate: bool = True) -> None:
        """Uma fase com a decisao pedida, pela semente (nao pela funcao).

        Serve os ensaios que precisam de uma fase que a `manual_confirmar`
        produz mas que o ensaio nao quer produzir pelo caminho inteiro.
        """
        self.semente.execute(
            "INSERT INTO platform.manual_confirmations "
            "(tenant_id, charge_id, fase, actor_contact_id, canal_msg_id, "
            " valor_declarado_minor, valor_bate, decisao) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                self.tenant, self.cobranca, fase, actor or self.dono,
                f"g8-{decisao}-{uuid.uuid4().hex}", VALOR, bate, decisao,
            ),
        )

    def test_uma_fase_retida_nao_serve(self) -> None:
        """**O buraco que as tres revisoes adversariais encontraram.**

        Uma confirmacao que o M-3 **retirou de circulacao** escreve
        `fase='confirmacao'` com `valor_bate` verdadeiro — porque o M-4 ja tinha
        passado. Enquanto o G8 pedia so a fase, essa linha era a prova que ele
        exige: bastava chamar a porta do ledger com `authn_method='manual'` e o
        `actor_id` daquela tentativa para a cobranca ficar **paga**, por cima de
        uma retencao para ops. E o `kamba_app` tem `EXECUTE` nessa porta — tem
        de ter, e o caminho do facilitador.

        O que fecha o buraco e a coluna `decisao`, e e este ensaio que o mede.
        """
        self._semear_fase("retem")
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)

    def test_uma_fase_a_espera_da_segunda_assinatura_tambem_nao(self) -> None:
        """O mesmo buraco pelo outro lado, e este paga **sem a dupla do M-5**.

        Acima do limiar, a primeira aprovacao escreve `fase='confirmacao'` com
        `valor_bate` e fica a espera da segunda. Enquanto o G8 pedia so a fase,
        uma cobranca que exige **duas** assinaturas ficava paga com a prova de
        **uma**.
        """
        self._semear_fase("exige_segunda")
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)

    def test_uma_fase_de_rejeicao_nao_serve(self) -> None:
        """A terceira decisao que escreve fase, e a mais obvia."""
        self._semear_fase("rejeita", fase="rejeicao", bate=False)
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)

    def test_so_a_decisao_confirma_serve(self) -> None:
        """A sonda positiva das tres acima, e a que separa fase de decisao.

        A **mesma** fase (`confirmacao`), o **mesmo** `valor_bate`, o **mesmo**
        actor — e a decisao a mudar. Sem este par, os tres ensaios acima podiam
        estar verdes porque a semente estava mal feita.
        """
        self._semear_fase("confirma")
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.directo.execute(sql, args)
        self.admin.rollback()

    def test_o_confirmado_por_hmac_nao_e_afectado(self) -> None:
        """A sonda que separa «o G8 funciona» de «o G8 parte o outro caminho».

        O *trigger* e so para `authn_method='manual'`. Sem esta medicao, uma
        guarda escrita sem a primeira condicao bloqueava o caminho do
        facilitador — e as 103 medicoes da suite do ledger continuavam verdes,
        porque nenhuma delas confirma por via humana.
        """
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.directo.execute(
            sql.replace("'manual', true, 'aceite', 'dono'", "'hmac', true, 'aceite', 'provider'"),
            args,
        )
        self.admin.rollback()

    def test_o_trigger_e_always_e_o_replica_nao_o_salta(self) -> None:
        """`ENABLE ALWAYS`, e aqui vale mais do que nos outros dois.

        Sem o `ALWAYS`, um superutilizador em
        `session_replication_role = replica` confirmava um pagamento por via
        humana sem fase nenhuma — e nada no catalogo dizia que isso era
        possivel.
        """
        self.directo.execute("SET session_replication_role = replica")
        sql, args = self.inserir_evento_humano(self.cobranca, self.dono, self.directo)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.directo, sql, args)
        self.directo.execute("SET session_replication_role = origin")


class TestPrivilegiosDasQuatroTabelas(ComConfirmacaoManual):
    """A aplicacao **le** as quatro e nao escreve nenhuma.

    O que se prova nao e que a politica recusa: e que **o privilegio nem
    existe**, que e mais forte — nao depende de a politica estar certa. E a
    mesma escolha da `payment_accounts` na `0027`.
    """

    TABELAS = (
        "payment_confirmers",
        "manual_confirmations",
        "refund_cases",
        "fraud_signals",
    )

    def test_a_aplicacao_le_as_quatro(self) -> None:
        """A sonda positiva. **Sem ela, os casos abaixo nao dizem nada.**"""
        for tabela in self.TABELAS:
            with self.subTest(tabela=tabela):
                self.cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertIsNotNone(self.cursor.fetchone()[0])

    def test_a_aplicacao_nao_insere_em_nenhuma(self) -> None:
        for tabela in self.TABELAS:
            with self.subTest(tabela=tabela):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    self.cursor,
                    f"INSERT INTO platform.{tabela} (tenant_id) VALUES (%s)",
                    (self.tenant,),
                )

    def test_a_aplicacao_nao_altera_nem_apaga_as_duas_de_registo(self) -> None:
        for tabela in ("manual_confirmations", "fraud_signals"):
            for verbo in ("UPDATE platform.{} SET motivo = 'x'", "DELETE FROM platform.{}"):
                with self.subTest(tabela=tabela, verbo=verbo):
                    sql = verbo.format(tabela)
                    if tabela == "fraud_signals" and "motivo" in sql:
                        sql = sql.replace("motivo = 'x'", "regra = 'x'")
                    self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, sql, ())

    def test_e_a_aplicacao_executa_as_cinco_funcoes(self) -> None:
        """A sonda positiva do conjunto: ler-e-nao-escrever nao bloqueia o caminho."""
        self.declarar(self.cobranca, self.cliente, "d")
        linha = self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.assertEqual(linha[3], "confirma")
        self.janela(self.tenant, self.cliente)
        self.confirmar(self.cursor, self.tenant)


class TestIsolamentoDaConfirmacao(ComConfirmacaoManual):
    """A RLS, e a prova de que o `DEFINER` nao contorna o `FORCE`.

    E a afirmacao central do `db/rls.py`, que a `0029` mediu para a
    `append_payment_event`. Mede-se outra vez para as quatro funcoes novas
    porque uma delas escrita com `SET search_path` errado, ou com uma leitura
    sem filtro, perdia-a sem que nada mais mudasse.
    """

    def setUp(self) -> None:
        super().setUp()
        self.declarar(self.cobranca, self.cliente, "d")
        self.confirmar_manual(self.cobranca, self.dono, "c", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.vizinho = self.criar_tenant()
        self.cursor_b = self.cursor_papel("app", self.vizinho)

    def test_b_nao_ve_as_fases_de_a(self) -> None:
        self.cursor_b.execute(
            "SELECT count(*) FROM platform.manual_confirmations WHERE charge_id = %s",
            (self.cobranca,),
        )
        self.assertEqual(int(self.cursor_b.fetchone()[0]), 0)

    def test_b_nao_ve_os_confirmadores_de_a(self) -> None:
        self.cursor_b.execute(
            "SELECT count(*) FROM platform.payment_confirmers WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(int(self.cursor_b.fetchone()[0]), 0)

    def test_a_ve_as_suas(self) -> None:
        """A sonda positiva dos dois casos acima."""
        self.cursor.execute(
            "SELECT count(*) FROM platform.manual_confirmations WHERE charge_id = %s",
            (self.cobranca,),
        )
        self.assertGreater(int(self.cursor.fetchone()[0]), 0)
        self.cursor.execute(
            "SELECT count(*) FROM platform.payment_confirmers WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(int(self.cursor.fetchone()[0]), 2)

    def test_a_funcao_definer_recusa_no_contexto_de_b(self) -> None:
        """O `DEFINER` da privilegio e **nao** da isolamento."""
        with self.assertRaises(Exception) as apanhado:
            self.declarar(self.cobranca, self.cliente, "d-cruzada", cursor=self.cursor_b)
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("nao e visivel", str(apanhado.exception))

    def test_e_a_de_confirmar_tambem(self) -> None:
        """E **discrimina** a recusa, que era o que faltava.

        A primeira versao corria sobre a `self.cobranca`, que o `setUp` desta
        classe leva a `paga` — e afirmava so o `SQLSTATE`. Sobre uma cobranca
        `paga`, a invisibilidade da RLS e a guarda de estado levantam **o
        mesmo** `23514`: tirar o `FOR UPDATE` filtrado pela politica deixava o
        ensaio verde, porque a cobranca passava a ser vista e era recusada por
        estar paga. Medido pela revisao adversarial.

        Corre agora sobre uma cobranca em `pendente_confirmacao` — onde a guarda
        de estado **nao** dispara — e prende a mensagem da RLS.
        """
        pendente = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(pendente, self.cliente, "d-pendente")
        self.confirmar(self.cursor, self.tenant)

        with self.assertRaises(Exception) as apanhado:
            self.confirmar_manual(
                pendente, self.dono, "c-cruzada", VALOR, cursor=self.cursor_b
            )
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn(
            "nao e visivel",
            str(apanhado.exception),
            "a recusa tem de ser a da RLS e nao a da guarda de estado",
        )

    def test_sem_contexto_de_tenant_nenhuma_das_quatro_devolve_linhas(self) -> None:
        sem = self.cursor_papel("app", None)
        for tabela in (
            "payment_confirmers",
            "manual_confirmations",
            "refund_cases",
            "fraud_signals",
        ):
            with self.subTest(tabela=tabela):
                sem.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertEqual(int(sem.fetchone()[0]), 0)

    def test_um_confirmador_de_b_nao_confirma_uma_cobranca_de_a(self) -> None:
        """A RLS cruzada em `payment_confirmers` que o DoD nomeia.

        O contacto esta em `payment_confirmers` — do tenant **B**. A leitura da
        `manual_confirmar` filtra por `tenant_id` da cobranca, pelo que ele e um
        desconhecido aqui. Sem esse filtro, a lista de confirmadores era global.
        """
        de_b = self.criar_contacto(self.vizinho)
        self.criar_confirmador(self.vizinho, de_b, papel="dono", segunda=True)
        # **Cobranca propria, porque o `setUp` ja pagou a outra.** Uma
        # confirmacao sobre uma cobranca `paga` e recusada pela guarda de estado
        # — certo, mas por outra razao que nao a que este ensaio mede.
        outra = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        self.declarar(outra, self.cliente, "d2")
        self.confirmar(self.cursor, self.tenant)
        linha = self.confirmar_manual(outra, de_b, "c-de-b", VALOR)
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(linha[4], "sem_confirmador")


class TestAcordoComATabelaPura(ComConfirmacaoManual):
    """A tabela do `manual.ts` e esta funcao decidem o mesmo, caso a caso.

    O `avaliarConfirmacao` do modulo de aplicacao e o oraculo da suite de
    unidade e a mensagem que o agente mostra ao dono. A recusa que **vale** e a
    desta funcao. As duas a divergir e o defeito perfeito: a suite de unidade
    verde, a base a recusar outra coisa, e o agente a dizer ao dono uma razao que
    nao e a razao.

    Os casos vem escritos aqui e nao importados do TypeScript: esta suite nao
    corre Node. O que os prende e o nome do motivo, que e o mesmo nos dois lados
    — uma divergencia de nomes faz este ensaio falhar.
    """

    #: `(descricao, mudanca, decisao esperada, motivo esperado)`
    CASOS = (
        ("legitimo", {}, "confirma", None),
        ("cliente", {"actor": "cliente"}, "rejeita", "cliente_nao_confirma"),
        ("estranho", {"actor": "estranho"}, "rejeita", "sem_confirmador"),
        ("inactivo", {"actor": "inactivo"}, "rejeita", "sem_confirmador"),
        ("valor a menos", {"valor": -1}, "rejeita", "valor_nao_bate"),
        ("valor a mais", {"valor": 1}, "rejeita", "valor_nao_bate"),
        ("diario", {"diario": VALOR - 1}, "retem", "limite_diario"),
        ("por contacto", {"contacto": 0}, "retem", "limite_por_contacto"),
        ("sem diario", {"diario": None}, "retem", "limite_diario"),
        ("acima da dupla", {"dupla": 1}, "exige_segunda", None),
        ("sem dupla", {"dupla": None}, "exige_segunda", None),
    )

    def test_cada_caso_da_o_mesmo_dos_dois_lados(self) -> None:
        for descricao, mudanca, decisao, motivo in self.CASOS:
            with self.subTest(caso=descricao):
                self._correr(descricao, mudanca, decisao, motivo)

    def _correr(self, descricao, mudanca, decisao, motivo) -> None:
        tenant = self.criar_tenant()
        conta = self.criar_conta(tenant, provider="manual")
        limites = {}
        if "diario" in mudanca:
            limites["manual_daily_max_minor"] = mudanca["diario"]
        if "contacto" in mudanca:
            limites["manual_max_por_contacto_24h"] = mudanca["contacto"]
        if "dupla" in mudanca:
            limites["manual_dupla_acima_minor"] = mudanca["dupla"]
        self.dar_limites(tenant, **limites)

        cliente = self.criar_contacto(tenant)
        dono = self.criar_contacto(tenant)
        self.criar_confirmador(tenant, dono)
        inactivo = self.criar_contacto(tenant)
        self.criar_confirmador(tenant, inactivo, ativo=False)
        estranho = self.criar_contacto(tenant)

        actor = {
            "cliente": cliente,
            "estranho": estranho,
            "inactivo": inactivo,
        }.get(mudanca.get("actor", ""), dono)

        cobranca = self.criar_cobranca(
            tenant, conta, provider="manual", metodo="manual"
        )
        cursor = self.cursor_papel("app", tenant)
        self.declarar(cobranca, cliente, f"d-{descricao}", cursor=cursor)
        self.confirmar(cursor, tenant)
        linha = self.confirmar_manual(
            cobranca, actor, f"c-{descricao}", VALOR + mudanca.get("valor", 0),
            cursor=cursor,
        )
        self.confirmar(cursor, tenant)
        self.assertEqual(linha[3], decisao, descricao)
        self.assertEqual(linha[4], motivo, descricao)


class TestCadeiasDoModulo(ComConfirmacaoManual):
    """As cadeias que o `manual.ts` envia **correm**, lidas do proprio ficheiro.

    E o padrao do `hooks.ts` e do `services/com/src/produtos/consultas.ts`: a
    suite le o texto que o modulo envia em vez de uma copia que envelhece
    sozinha. Sem isto, uma mudanca de nome de parametro na revisao deixava o
    modulo a falar com uma funcao que nao existe, e nenhum gate dava por nada —
    o gate 4 compila TypeScript e nao fala com a base.
    """

    #: `(constante, argumentos)`. A ordem dos `$n` e a do ficheiro.
    CADEIAS = {
        "SQL_MANUAL_CONFIRMADOR": ("tenant", "contacto"),
        "SQL_MANUAL_DECLARAR": ("cobranca", "contacto", "msg", "evidencia"),
        "SQL_MANUAL_CONFIRMAR": ("cobranca", "contacto", "msg", "valor"),
        "SQL_MANUAL_EXPIRAR_CONFIRMACAO": ("cobranca", "horas"),
        "SQL_MANUAL_REVERTER": ("cobranca", "contacto", "msg", "motivo"),
        "SQL_MANUAL_JANELA": ("tenant", "contacto", "agora"),
    }

    def _ler_cadeias(self) -> dict[str, str]:
        import re
        from pathlib import Path

        fonte = (
            Path(__file__).resolve().parents[2]
            / "packages"
            / "core-ts"
            / "src"
            / "pagamentos"
            / "manual.ts"
        ).read_text(encoding="utf-8")
        padrao = re.compile(
            r"export const (SQL_MANUAL_[A-Z_]+) = `(.*?)`;", re.S
        )
        return {nome: corpo for nome, corpo in padrao.findall(fonte)}

    def test_as_seis_cadeias_estao_no_ficheiro(self) -> None:
        """A sonda positiva: sem isto, um ficheiro renomeado dava zero cadeias."""
        lidas = self._ler_cadeias()
        self.assertEqual(set(lidas), set(self.CADEIAS))

    #: Em que estado cada cadeia precisa de encontrar a cobranca.
    #:
    #: **Nao e um detalhe do ensaio: e o que ele descobriu.** A primeira versao
    #: corria as seis sobre a mesma cobranca, e a segunda cadeia batia num
    #: `23514` — a cobranca ja estava em `pendente_confirmacao` e um segundo
    #: `confirmacao_manual_pedida` nao tem aresta. Cada cadeia tem um estado de
    #: partida, e escreve-lo aqui diz **qual** com mais clareza do que a
    #: assinatura dela.
    PARTIDA = {
        "SQL_MANUAL_CONFIRMADOR": "emitida",
        "SQL_MANUAL_JANELA": "emitida",
        "SQL_MANUAL_DECLARAR": "emitida",
        "SQL_MANUAL_CONFIRMAR": "pendente_confirmacao",
        "SQL_MANUAL_EXPIRAR_CONFIRMACAO": "pendente_confirmacao",
        "SQL_MANUAL_REVERTER": "paga",
    }

    def test_cada_cadeia_corre_contra_a_base(self) -> None:
        lidas = self._ler_cadeias()
        agora = datetime.datetime.now(datetime.timezone.utc)
        for nome, argumentos in self.CADEIAS.items():
            with self.subTest(cadeia=nome):
                cobranca = self._cobranca_em(self.PARTIDA[nome])
                sql = lidas[nome]
                for indice in range(len(argumentos), 0, -1):
                    sql = sql.replace(f"${indice}", "%s")
                valores = {
                    "tenant": self.tenant,
                    "contacto": self.dono,
                    "cobranca": cobranca,
                    "msg": f"{nome}-{uuid.uuid4().hex}",
                    "valor": VALOR,
                    "evidencia": None,
                    "horas": 24,
                    "motivo": "motivo escrito para a cadeia",
                    "agora": agora,
                }
                self.cursor.execute(sql, tuple(valores[a] for a in argumentos))
                self.cursor.fetchall()
                self.confirmar(self.cursor, self.tenant)

    def _cobranca_em(self, estado: str) -> str:
        """Uma cobranca nova no estado pedido, **pelo caminho humano**."""
        cobranca = self.criar_cobranca(
            self.tenant, self.conta, provider="manual", metodo="manual"
        )
        if estado == "emitida":
            return cobranca
        self.declarar(cobranca, self.cliente, f"d-{uuid.uuid4().hex}")
        self.confirmar(self.cursor, self.tenant)
        if estado == "pendente_confirmacao":
            return cobranca
        veredicto = self.confirmar_manual(
            cobranca, self.dono, f"c-{uuid.uuid4().hex}", VALOR
        )
        self.confirmar(self.cursor, self.tenant)
        self.assertEqual(veredicto[3], "confirma")
        self.assertEqual(self.estado_da_cobranca(cobranca), estado)
        return cobranca
