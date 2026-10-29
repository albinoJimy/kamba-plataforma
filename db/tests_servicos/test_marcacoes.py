"""Criterios 5 e 7 do KAM-047: cancelar, remarcar atomicamente, e o limite.

«`cancelBooking` liberta o intervalo imediatamente; `rescheduleBooking` e
atomico (cancela e marca na mesma transaccao): falha injectada deixa a marcacao
original intacta.»

«O entitlement `marcacoes_mes` e verificado no `holdSlot`; excedido devolve
`LIMIT_EXCEEDED`.»

**«Imediatamente» e literal.** A restricao de exclusao e **parcial** sobre
`estado IN ('hold','confirmada')`: a linha sai do indice no mesmo `UPDATE`, e o
intervalo esta livre antes de a transaccao confirmar — para quem estiver nela.
Nao ha `DELETE`, pelo que o historico fica. E a propriedade que o
`test_cancelar_liberta_na_mesma_transaccao` mede, e que um `DELETE` tornaria
invisivel.
"""

from __future__ import annotations

import pg8000.dbapi

import ligacao
from tests import factories
from tests.base import sqlstate
from tests_ten.base import SQL_CONSUMIR, Consumo
from tests_servicos.base import ComAgenda, intervalo, prazo_do_hold
from tests_servicos.consultas import SQL_CANCELAR, SQL_CRIAR_HOLD

#: As duas consultas vem do **ficheiro do modulo**
#: (`tests_servicos/consultas.py`): o que esta suite exercita e o texto que o
#: `cancelBooking` e o `holdSlot` enviam em producao, e nao uma copia dele.


class TestCancelar(ComAgenda):
    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()
        self.contacto = "11111111-1111-4111-8111-111111111111"
        self.inicio, self.fim = intervalo(60)
        self.semente.execute(
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                self.contacto,
                self.servico,
                self.recurso,
                "slot-a",
                self.inicio,
                self.fim,
                prazo_do_hold(),
            ),
        )
        self.booking = str(self.semente.fetchone()[0])

    def test_cancelar_liberta_na_mesma_transaccao(self) -> None:
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_CANCELAR, (self.booking, self.contacto))
        # O `RETURNING` do modulo devolve as onze colunas da marcacao, pela
        # ordem do `SQL_CANCELAR`: lê-se por nome do indice e nao por desempacote,
        # que ficava a quebrar a cada coluna nova.
        linha = cursor.fetchone()
        colunas = [d[0] for d in cursor.description]
        marcacao = dict(zip(colunas, linha))
        self.assertEqual(str(marcacao["estado"]), "cancelada")
        self.assertEqual(int(marcacao["version"]), 2)
        self.assertIsNone(marcacao["hold_expires_at"])

        # **Sem confirmar**: o intervalo ja esta livre dentro desta transaccao.
        cursor.execute(
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                "22222222-2222-4222-8222-222222222222",
                self.servico,
                self.recurso,
                "slot-b",
                self.inicio,
                self.fim,
                prazo_do_hold(),
            ),
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.connection.commit()
        self.assertEqual(self.contar(self.tenant, "hold"), 1)
        self.assertEqual(self.contar(self.tenant, "cancelada"), 1)

    def test_a_linha_cancelada_fica_no_historico(self) -> None:
        """Cancelar e um `UPDATE`, nao um `DELETE`: o registo nao desaparece."""
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_CANCELAR, (self.booking, self.contacto))
        cursor.fetchone()
        cursor.connection.commit()
        self.assertEqual(
            self.marcacoes(self.tenant), [("cancelada", "slot-a")]
        )

    def test_um_contacto_nao_cancela_a_marcacao_de_outro(self) -> None:
        """X-02: a RLS isola tenants; o `contact_id` do `WHERE` isola contactos."""
        cursor = self.cursor_app(self.tenant)
        cursor.execute(
            SQL_CANCELAR, (self.booking, "99999999-9999-4999-8999-999999999999")
        )
        self.assertIsNone(cursor.fetchone())
        cursor.connection.commit()
        self.assertEqual(self.contar(self.tenant, "hold"), 1)

    def test_cancelar_duas_vezes_nao_altera_duas_vezes(self) -> None:
        """O `estado IN ('hold','confirmada')` do `WHERE` e a idempotencia."""
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_CANCELAR, (self.booking, self.contacto))
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(SQL_CANCELAR, (self.booking, self.contacto))
        self.assertIsNone(cursor.fetchone())
        cursor.connection.commit()
        self.semente.execute(
            "SELECT version FROM servicos.bookings WHERE booking_id = %s",
            (self.booking,),
        )
        self.assertEqual(int(self.semente.fetchone()[0]), 2)


class TestRemarcarAtomico(ComAgenda):
    """Critério 5: a remarcacao e uma transaccao, e a falha deixa tudo como estava."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()
        self.contacto = "11111111-1111-4111-8111-111111111111"
        self.inicio, self.fim = intervalo(60)
        self.semente.execute(
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                self.contacto,
                self.servico,
                self.recurso,
                "slot-original",
                self.inicio,
                self.fim,
                prazo_do_hold(),
            ),
        )
        self.booking = str(self.semente.fetchone()[0])

    def test_remarcar_cancela_e_marca_na_mesma_transaccao(self) -> None:
        novo_inicio, novo_fim = intervalo(180)
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_CANCELAR, (self.booking, self.contacto))
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                self.contacto,
                self.servico,
                self.recurso,
                "slot-novo",
                novo_inicio,
                novo_fim,
                prazo_do_hold(),
            ),
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.connection.commit()
        self.assertEqual(
            sorted(self.marcacoes(self.tenant)),
            [("cancelada", "slot-original"), ("hold", "slot-novo")],
        )

    def test_falha_injectada_deixa_a_marcacao_original_intacta(self) -> None:
        """A falha e real e nao simulada: o slot novo esta ocupado por outro.

        **E uma falha do PostgreSQL e nao um `raise` do teste**, e isso importa:
        o que se prova e que o `ROLLBACK` da transaccao desfaz o cancelamento
        que ja tinha acontecido — nao que o teste sabe parar a meio.
        """
        novo_inicio, novo_fim = intervalo(180)
        # Outro contacto ja tem o intervalo novo.
        self.semente.execute(
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                "33333333-3333-4333-8333-333333333333",
                self.servico,
                self.recurso,
                "slot-ocupado",
                novo_inicio,
                novo_fim,
                prazo_do_hold(),
            ),
        )
        self.semente.fetchone()

        conexao = self.ligar("app")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
            )
            cursor.fetchone()
            cursor.execute(SQL_CANCELAR, (self.booking, self.contacto))
            self.assertIsNotNone(cursor.fetchone())
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                cursor.execute(
                    SQL_CRIAR_HOLD,
                    (
                        self.tenant,
                        self.contacto,
                        self.servico,
                        self.recurso,
                        "slot-novo",
                        novo_inicio,
                        novo_fim,
                        prazo_do_hold(),
                    ),
                )
                cursor.fetchone()
            self.assertEqual(sqlstate(capturado.exception), "23P01")
            conexao.rollback()
        finally:
            # **Nao se fecha aqui.** O `ComBase.ligar` registra a ligacao e o
            # `tearDown` fecha-a; um `close()` nosso levantava
            # `InterfaceError: connection is closed` no `tearDown` e o teste
            # falhava depois de ter medido o que queria. Medido.
            pass

        # **A marcacao original ficou intacta**: estado, versao e tudo.
        self.semente.execute(
            "SELECT estado, version FROM servicos.bookings WHERE booking_id = %s",
            (self.booking,),
        )
        estado, versao = self.semente.fetchone()
        self.assertEqual(str(estado), "hold")
        self.assertEqual(
            int(versao),
            1,
            "a version a dois significa que o cancelamento sobreviveu ao rollback",
        )
        self.assertEqual(self.contar(self.tenant, "hold"), 2)
        self.assertEqual(self.contar(self.tenant, "cancelada"), 0)


class TestOLimiteDeMarcacoes(ComAgenda):
    """Critério 7: `marcacoes_mes` verificado no hold; excedido da `LIMIT_EXCEEDED`.

    A aritmetica **nao esta aqui nem no modulo**: esta na
    `platform.ten_consumir` da revisao `0007` (KAM-009), e o que estes testes
    provam e que o modulo a chama com a chave certa e que a recusa chega. A
    chave `marcacoes_mes` ja estava no dicionario §3.2 e no
    `registry/entitlement_keys.schema.json` — nao e nome novo deste ticket.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()

    def _consumir(self, cursor, chave_idem: str):
        """Uma chamada a `platform.ten_consumir` **pelo SQL da biblioteca**.

        O `SQL_CONSUMIR` vem de `kamba_core.ten.consultas`, que e o espelho
        verificado do `packages/core-ts/src/ten/consultas.ts`, e nao de uma
        copia escrita aqui. A primeira versao deste ficheiro escrevia a chamada
        a mao com `NULL` no `p_agora`, e a revisao `0007` recusa-a com
        `22023 ten_consumir: p_agora nulo` — o `coalesce(%s, now())` do
        `SQL_CONSUMIR` existe precisamente para que o mesmo chamador possa pedir
        as duas coisas. Medido, e e a razao pela qual o `db/tests_ten/base.py`
        importa em vez de copiar.
        """
        cursor.execute(
            SQL_CONSUMIR, (self.tenant, "marcacoes_mes", 1, chave_idem, None, None)
        )
        return Consumo(*cursor.fetchone())

    def test_sem_entitlement_o_consumo_e_negado(self) -> None:
        """«sem tecto» nao quer dizer «sem limite»: `NULL` nega (revisao `0007`)."""
        cursor = self.cursor_app(self.tenant)
        aceite, _, _, limite = self._consumir(cursor, "ensaio-sem-entitlement")
        self.assertFalse(aceite)
        self.assertIsNone(limite)
        cursor.connection.rollback()

    def test_o_limite_esgotado_nega_e_o_contador_nao_passa_do_tecto(self) -> None:
        self.dar_entitlement(self.tenant, 2)
        cursor = self.cursor_app(self.tenant)
        self.assertTrue(self._consumir(cursor, "m1")[0])
        cursor.connection.commit()
        cursor = self.cursor_app(self.tenant)
        self.assertTrue(self._consumir(cursor, "m2")[0])
        cursor.connection.commit()
        cursor = self.cursor_app(self.tenant)
        aceite, valor, _, limite = self._consumir(cursor, "m3")
        self.assertFalse(aceite, "a terceira marcacao excede o tecto de duas")
        self.assertEqual(int(limite), 2)
        self.assertEqual(int(valor), 2, "o contador nao passa do tecto")
        cursor.connection.rollback()

    def test_a_mesma_chave_de_idempotencia_nao_consome_duas_vezes(self) -> None:
        """O duplo toque no mesmo botao gasta **uma** marcacao do balde.

        E a razao pela qual a chave de idempotencia do modulo e
        `servicos:hold:<contacto>:<slot>` e nao um aleatorio: dois toques no
        mesmo botao sao o mesmo pedido.
        """
        self.dar_entitlement(self.tenant, 5)
        cursor = self.cursor_app(self.tenant)
        primeiro = self._consumir(cursor, "servicos:hold:c1:slot1")
        cursor.connection.commit()
        cursor = self.cursor_app(self.tenant)
        segundo = self._consumir(cursor, "servicos:hold:c1:slot1")
        cursor.connection.commit()
        self.assertTrue(primeiro[0])
        self.assertTrue(segundo[0])
        self.assertFalse(primeiro[2], "a primeira nao e repeticao")
        self.assertTrue(segundo[2], "a segunda e repeticao da primeira")
        self.assertEqual(int(segundo[1]), 1, "o contador fica em um, nao em dois")

    def test_um_tenant_nao_consome_o_balde_de_outro(self) -> None:
        """A `ten_consumir` e `SECURITY INVOKER`: corre com a RLS de quem chama.

        **E a recusa e silenciosa, nao e um erro** — e isso mediu-se. A primeira
        versao deste teste esperava uma excepcao; a funcao devolve
        `aceite = false` com `limite` nulo, porque com o contexto do atacante a
        politica esconde a linha de `entitlements` do alvo e «sem tecto» nega
        (revisao `0007`). Falha fechada pelo lado silencioso, que para um
        consumo e o certo: o atacante nao fica a saber se o alvo tem entitlement.

        O que o teste prende e a consequencia que importa: o contador do alvo
        **nao se move**.
        """
        self.dar_entitlement(self.tenant, 5)
        outro = self.criar_tenant()
        factories.entitlement(
            self.semente, outro, modulo="servicos", limites={"marcacoes_mes": 5}
        )
        # Contexto do `outro`, a consumir no nome do primeiro.
        cursor = self.cursor_app(outro)
        resultado = self._consumir(cursor, "ataque")
        self.assertFalse(resultado.aceite)
        self.assertIsNone(resultado.limite, "o tecto do alvo nao e legivel daqui")
        cursor.connection.rollback()

        self.semente.execute(
            "SELECT coalesce(sum(valor), 0) FROM platform.tenant_usage "
            " WHERE tenant_id = %s AND chave_limite = 'marcacoes_mes'",
            (self.tenant,),
        )
        self.assertEqual(
            int(self.semente.fetchone()[0]), 0, "o contador do alvo nao se move"
        )
