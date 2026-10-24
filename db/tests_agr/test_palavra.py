"""Quem tem a palavra, contra a base (KAM-025 criterio 6, e o X-02 do DoD).

A consulta e o `SQL_PALAVRA_DA_CONVERSA` da aplicacao, importado — nao uma copia
dele. Uma base falsa compara SQL por texto e nunca o interpreta: um erro de
sintaxe, uma coluna com outro nome, um `%s` fora de ordem, um `EXISTS` que filtra
pela conversa errada — nada disso o *gate* 4 ve, e tudo isso da uma resposta
plausivel.
"""

from __future__ import annotations

import unittest
import uuid

from tests import factories
from tests_agr.base import ComAgr


class TestOCaminhoDoBot(ComAgr):
    def test_uma_conversa_em_bot_sem_handoff_abre_a_porta(self) -> None:
        conversa = self.criar_conversa()
        conexao = self.ligar("app")
        self.assertEqual(self.ler_palavra(conexao, conversa), ("bot", False))

    def test_a_consulta_corre_de_verdade(self) -> None:
        # O que esta suite existe para dizer: o texto que a aplicacao envia e
        # SQL valido contra este esquema. Sem isto, um `conversations.modo` em
        # vez de `conversations.mode` passava o gate 4 inteiro.
        conversa = self.criar_conversa()
        conexao = self.ligar("app")
        self.assertIsNotNone(self.ler_palavra(conexao, conversa))


class TestOsTresModosQueFecham(ComAgr):
    def test_dono_humano_e_pausada_fecham_a_porta(self) -> None:
        # Criterio 6, e a invariante do `docs/tecnica/02` §11 regra 4.
        for modo in ("dono", "humano", "pausada"):
            with self.subTest(modo=modo):
                conversa = self.criar_conversa(modo=modo)
                conexao = self.ligar("app")
                lido = self.ler_palavra(conexao, conversa)
                self.assertIsNotNone(lido)
                self.assertEqual(lido[0], modo)
                # O `do_humano` do `turno.py` e `modo != 'bot' or handoff`.
                self.assertNotEqual(lido[0], "bot")

    def test_o_check_da_coluna_recusa_um_modo_inventado(self) -> None:
        # Nao e deste ticket, mas e o que torna a lista de permitidos do
        # `turno.py` suficiente: a base nao deixa entrar um quinto valor.
        conversa = self.criar_conversa()
        with self.assertRaises(Exception):
            self.semente.execute(
                "UPDATE platform.conversations SET mode = 'inventado' WHERE id = %s",
                (conversa.conversation_id,),
            )


class TestOHandoffAEspera(ComAgr):
    def test_um_handoff_waiting_fecha_a_porta_mesmo_em_bot(self) -> None:
        conversa = self.criar_conversa()
        self.abrir_handoff(conversa, estado="waiting")
        conexao = self.ligar("app")
        self.assertEqual(self.ler_palavra(conexao, conversa), ("bot", True))

    def test_os_outros_quatro_estados_deixam_passar(self) -> None:
        # «`waiting -> resumed | timeout | cancelled | degraded`» (§3.15): os
        # outros quatro sao passagens **acabadas**, e o turno entra. E por isso
        # que o predicado nomeia `waiting` em vez de negar os outros — um estado
        # novo no dominio nao pode fechar a porta por omissao.
        for estado in ("resumed", "timeout", "cancelled", "degraded"):
            with self.subTest(estado=estado):
                conversa = self.criar_conversa()
                self.abrir_handoff(conversa, estado=estado)
                conexao = self.ligar("app")
                self.assertEqual(self.ler_palavra(conexao, conversa), ("bot", False))

    def test_um_handoff_de_outra_conversa_do_mesmo_tenant_nao_conta(self) -> None:
        # O `EXISTS` filtra por `(tenant_id, conversation_id)`. Se filtrasse so
        # pelo tenant, um *handoff* aberto numa conversa fechava a porta a
        # **todas** as conversas da loja — e a resposta continuava plausivel.
        #
        # A segunda conversa vai num **canal** novo do mesmo tenant: a
        # `conversations_tenant_contact_channel_uq` nao deixa duas conversas do
        # mesmo trio, e o primeiro desenho deste teste copiava a linha e morria
        # nela (medido).
        tranquila = self.criar_conversa()
        segundo_canal = factories.canal(self.semente, tranquila.tenant_id)
        agitada = str(uuid.uuid4())
        self.semente.execute(
            "INSERT INTO platform.conversations "
            "(id, tenant_id, contact_id, channel_id, mode, "
            " last_inbound_at, window_expires_at) "
            "VALUES (%s, %s, %s, %s, 'bot', now(), now() + interval '24 hours')",
            (agitada, tranquila.tenant_id, tranquila.contact_id, segundo_canal),
        )
        self.semente.execute(
            "INSERT INTO platform.handoffs "
            "(handoff_id, tenant_id, conversation_id, status, motivo) "
            "VALUES (%s, %s, %s, 'waiting', 'ensaio')",
            (f"h-{uuid.uuid4().hex}", tranquila.tenant_id, agitada),
        )
        factories.contexto(self.semente, None)

        conexao = self.ligar("app")
        self.assertEqual(
            self.ler_palavra(conexao, tranquila),
            ("bot", False),
            "um handoff noutra conversa da mesma loja fechou a porta a esta",
        )
        # E, do outro lado, na conversa certa o handoff **conta**: senao este
        # teste passava com um `EXISTS` que nunca encontra nada.
        agitada_ref = type(tranquila)(
            tranquila.tenant_id, tranquila.contact_id, segundo_canal, agitada
        )
        self.assertEqual(self.ler_palavra(conexao, agitada_ref), ("bot", True))


class TestIsolamento(ComAgr):
    """O X-02 do DoD: a RLS esconde a conversa de A do contexto de B."""

    def test_o_contexto_de_b_nao_ve_a_conversa_de_a(self) -> None:
        a = self.criar_conversa()
        b = self.criar_conversa()
        conexao = self.ligar("app")
        # A mesma consulta, os mesmos parametros, outro contexto.
        self.assertIsNone(
            self.ler_palavra(conexao, a, como=b.tenant_id),
            "o contexto do tenant B leu a conversa do tenant A",
        )

    def test_zero_linhas_e_o_que_o_agr_le_como_nao_entra(self) -> None:
        # E a razao pela qual o `turno.py` nao tem `or 'bot'`: a resposta de um
        # contexto trocado e **indistinguivel** de «a conversa nao existe», e as
        # duas tem de fechar a porta.
        a = self.criar_conversa()
        b = self.criar_conversa()
        conexao = self.ligar("app")
        inexistente = type(a)(a.tenant_id, a.contact_id, a.canal_id, str(uuid.uuid4()))
        self.assertIsNone(self.ler_palavra(conexao, inexistente))
        self.assertIsNone(self.ler_palavra(conexao, a, como=b.tenant_id))

    def test_sem_contexto_nenhum_nao_ha_resposta(self) -> None:
        # A RLS e `FORCE`: sem `app.tenant_id`, zero linhas. Um AGR que corresse
        # sem contexto nao leria a conversa de outro — leria nada, que e a falha
        # certa.
        conversa = self.criar_conversa()
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        try:
            from tests_agr.base import SQL_PALAVRA_DA_CONVERSA

            cursor.execute(
                SQL_PALAVRA_DA_CONVERSA,
                (
                    conversa.tenant_id,
                    conversa.conversation_id,
                    conversa.tenant_id,
                    conversa.conversation_id,
                ),
            )
            self.assertIsNone(cursor.fetchone())
        finally:
            cursor.close()

    def test_o_handoff_de_a_nao_e_visivel_no_contexto_de_b(self) -> None:
        # O `EXISTS` corre sob a RLS de `handoffs` tambem, e e preciso que
        # corra: um `EXISTS` que atravessasse a politica dizia a B que A tem uma
        # conversa com um humano.
        a = self.criar_conversa()
        self.abrir_handoff(a, estado="waiting")
        b = self.criar_conversa()
        conexao = self.ligar("app")
        self.assertIsNone(self.ler_palavra(conexao, a, como=b.tenant_id))


if __name__ == "__main__":
    unittest.main()
