"""Criterio 3 do KAM-047: o hold, o prazo, a libertacao e o `HOLD_EXPIRED`.

«`holdSlot` cria `hold` com `hold_expires_at` (TTL *proposta*: 10 min, a
calibrar); hold vencido e libertado com p99 <= 60 s e emite evento; confirmar um
hold expirado devolve `HOLD_EXPIRED`.»

Tres coisas distintas, e cada uma com o seu mecanismo:

- **O prazo** e uma coluna, com um `CHECK` que a amarra ao estado: `(estado =
  'hold') = (hold_expires_at IS NOT NULL)`. Ninguem guarda um hold sem prazo nem
  um prazo numa marcacao confirmada.
- **A libertacao** e a funcao `servicos.expirar_holds`, que altera o estado e
  emite `booking.cancelled` com `motivo = 'hold_expirado'` na **mesma
  transaccao** (outbox, ADR-009).
- **O `HOLD_EXPIRED`** nao depende do varrimento ter corrido: o `WHERE` da
  confirmacao tem `hold_expires_at > now()`, pelo que um hold vencido nao se
  confirma mesmo antes de alguem o libertar. Sem isso, o resultado de confirmar
  um hold vencido era uma corrida com o relogio em vez de uma regra.

**O relogio nao se simula com `sleep`.** As sementes escrevem prazos no passado
directamente — `now() - interval '1 minute'` —, que e a unica forma de medir uma
expiracao sem esperar dez minutos por teste. O que isso **nao** cobre e a
cadencia de quem chama o varrimento, e isso esta dito na verificacao do bloco.
"""

from __future__ import annotations

import pg8000.dbapi

from tests.base import sqlstate
from tests_servicos.base import ComAgenda, intervalo
from tests_servicos.consultas import SQL_CONFIRMAR_HOLD, SQL_EXPIRAR_HOLDS

VIOLACAO_DE_CHECK = "23514"


class TestOPrazoDoHold(ComAgenda):
    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()

    def _inserir(self, estado: str, prazo: str | None, minutos: int = 60) -> str:
        inicio, fim = intervalo(minutos)
        self.semente.execute(
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            f"VALUES (%s, gen_random_uuid(), %s, %s, %s, %s, %s, %s, {prazo or 'NULL'}) "
            "RETURNING booking_id",
            (
                self.tenant,
                self.servico,
                self.recurso,
                f"slot-{estado}-{minutos}",
                inicio,
                fim,
                estado,
            ),
        )
        return str(self.semente.fetchone()[0])

    def test_um_hold_sem_prazo_e_recusado(self) -> None:
        """Um hold sem prazo nunca expirava e ocupava o intervalo para sempre."""
        cursor = self.cursor_app(self.tenant)
        inicio, fim = intervalo(60)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado) "
            "VALUES (%s, gen_random_uuid(), %s, %s, 'sem-prazo', %s, %s, 'hold')",
            (self.tenant, self.servico, self.recurso, inicio, fim),
        )

    def test_uma_marcacao_confirmada_com_prazo_e_recusada(self) -> None:
        """A equivalencia nos dois sentidos: «tem prazo» e «e um hold» e o mesmo facto."""
        cursor = self.cursor_app(self.tenant)
        inicio, fim = intervalo(60)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            "VALUES (%s, gen_random_uuid(), %s, %s, 'confirmada-com-prazo', %s, %s, "
            "        'confirmada', now() + interval '10 minutes')",
            (self.tenant, self.servico, self.recurso, inicio, fim),
        )

    def test_um_intervalo_invertido_e_recusado(self) -> None:
        cursor = self.cursor_app(self.tenant)
        inicio, fim = intervalo(60)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            "VALUES (%s, gen_random_uuid(), %s, %s, 'invertido', %s, %s, 'hold', "
            "        now() + interval '10 minutes')",
            (self.tenant, self.servico, self.recurso, fim, inicio),
        )


class TestAExpiracao(ComAgenda):
    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()

    def _hold_vencido(self, slot: str, minutos: int) -> str:
        inicio, fim = intervalo(minutos)
        self.semente.execute(
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            "VALUES (%s, gen_random_uuid(), %s, %s, %s, %s, %s, 'hold', "
            "        now() - interval '1 minute') "
            "RETURNING booking_id",
            (self.tenant, self.servico, self.recurso, slot, inicio, fim),
        )
        return str(self.semente.fetchone()[0])

    def test_o_varrimento_liberta_o_hold_vencido_e_emite_o_evento(self) -> None:
        booking = self._hold_vencido("vencido", 60)
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_EXPIRAR_HOLDS, (100,))
        self.assertEqual(int(cursor.fetchone()[0]), 1)
        cursor.connection.commit()

        self.semente.execute(
            "SELECT estado, hold_expires_at FROM servicos.bookings "
            " WHERE booking_id = %s",
            (booking,),
        )
        estado, prazo = self.semente.fetchone()
        self.assertEqual(str(estado), "expirada")
        self.assertIsNone(prazo)

        envelopes = self.eventos(self.tenant, "booking.cancelled")
        self.assertEqual(len(envelopes), 1, "um hold libertado, um evento")
        envelope = envelopes[0]
        self.assertEqual(envelope["payload"]["booking_id"], booking)
        self.assertEqual(envelope["payload"]["motivo"], "hold_expirado")
        self.assertEqual(envelope["agregado"]["tipo"], "booking")
        self.assertEqual(
            set(envelope["payload"]),
            {"booking_id", "motivo"},
            "o contrato v1 de booking.cancelled tem `additionalProperties: false` "
            "e pede exactamente estes dois campos",
        )

    def test_o_intervalo_fica_livre_depois_do_varrimento(self) -> None:
        """E o que «libertado» quer dizer: outro contacto consegue a mesma hora."""
        self._hold_vencido("vencido", 120)
        inicio, fim = intervalo(120)
        cursor = self.cursor_app(self.tenant)

        # Antes do varrimento, o intervalo esta ocupado: o hold venceu mas ainda
        # esta `hold`, e o predicado da restricao de exclusao inclui esse estado.
        # E por isso que o varrimento e necessario e nao uma optimizacao.
        self.assertErroSql(
            "23P01",
            cursor,
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            "VALUES (%s, gen_random_uuid(), %s, %s, 'outro', %s, %s, 'hold', "
            "        now() + interval '10 minutes')",
            (self.tenant, self.servico, self.recurso, inicio, fim),
        )

        cursor.execute(SQL_EXPIRAR_HOLDS, (100,))
        cursor.fetchone()
        cursor.execute(
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            "VALUES (%s, gen_random_uuid(), %s, %s, 'outro', %s, %s, 'hold', "
            "        now() + interval '10 minutes') RETURNING booking_id",
            (self.tenant, self.servico, self.recurso, inicio, fim),
        )
        self.assertIsNotNone(cursor.fetchone())
        cursor.connection.commit()
        self.assertEqual(self.contar(self.tenant, "hold"), 1)
        self.assertEqual(self.contar(self.tenant, "expirada"), 1)

    def test_o_varrimento_repetido_nao_emite_duas_vezes(self) -> None:
        """O `estado = 'hold'` no `WHERE` e o que impede o segundo evento.

        Sem ele, uma linha ja expirada por outra chamada concorrente voltava a
        emitir — e o criterio 2 do KAM-048 conta mensagens.
        """
        self._hold_vencido("vencido", 180)
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_EXPIRAR_HOLDS, (100,))
        self.assertEqual(int(cursor.fetchone()[0]), 1)
        cursor.execute(SQL_EXPIRAR_HOLDS, (100,))
        self.assertEqual(int(cursor.fetchone()[0]), 0)
        cursor.connection.commit()
        self.assertEqual(len(self.eventos(self.tenant, "booking.cancelled")), 1)

    def test_o_varrimento_nao_toca_num_hold_que_ainda_vale(self) -> None:
        inicio, fim = intervalo(240)
        self.semente.execute(
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            "VALUES (%s, gen_random_uuid(), %s, %s, 'vivo', %s, %s, 'hold', "
            "        now() + interval '10 minutes')",
            (self.tenant, self.servico, self.recurso, inicio, fim),
        )
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_EXPIRAR_HOLDS, (100,))
        self.assertEqual(int(cursor.fetchone()[0]), 0)
        cursor.connection.commit()
        self.assertEqual(self.contar(self.tenant, "hold"), 1)

    def test_o_tecto_de_linhas_e_respeitado_e_o_varrimento_repete(self) -> None:
        """O varrimento e oportunista: nunca segura a transaccao de quem marca."""
        for n in range(5):
            self._hold_vencido(f"vencido-{n}", 300 + n * 60)
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_EXPIRAR_HOLDS, (2,))
        self.assertEqual(int(cursor.fetchone()[0]), 2)
        cursor.execute(SQL_EXPIRAR_HOLDS, (2,))
        self.assertEqual(int(cursor.fetchone()[0]), 2)
        cursor.execute(SQL_EXPIRAR_HOLDS, (10,))
        self.assertEqual(int(cursor.fetchone()[0]), 1)
        cursor.connection.commit()
        self.assertEqual(self.contar(self.tenant, "expirada"), 5)

    def test_um_tecto_nao_positivo_e_recusado(self) -> None:
        cursor = self.cursor_app(self.tenant)
        for tecto in (0, -1, None):
            with self.subTest(tecto=tecto):
                with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                    cursor.execute(SQL_EXPIRAR_HOLDS, (tecto,))
                    cursor.fetchone()
                self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)
                cursor.connection.rollback()
                cursor = self.cursor_app(self.tenant)

    def test_confirmar_um_hold_vencido_nao_altera_a_linha(self) -> None:
        """O `HOLD_EXPIRED` do criterio 3, **antes** de o varrimento correr.

        E a propriedade que faz dele uma regra e nao uma corrida: o
        `hold_expires_at > now()` do `WHERE` recusa a confirmacao mesmo com a
        linha ainda em `hold`.
        """
        booking = self._hold_vencido("vencido", 360)
        self.semente.execute(
            "SELECT hold_id, contact_id FROM servicos.bookings "
            " WHERE booking_id = %s",
            (booking,),
        )
        hold, contacto = (str(v) for v in self.semente.fetchone())

        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_CONFIRMAR_HOLD, (hold, contacto))
        self.assertIsNone(
            cursor.fetchone(),
            "um hold vencido nao se confirma, mesmo antes de ser libertado",
        )
        cursor.connection.commit()
        self.assertEqual(self.contar(self.tenant, "hold"), 1)
        self.assertEqual(self.contar(self.tenant, "confirmada"), 0)
