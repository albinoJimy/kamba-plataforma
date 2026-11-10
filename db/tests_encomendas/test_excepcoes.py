"""KAM-050: a excepcao da encomenda, a auditoria do reembolso e a re-reserva.

Tres barreiras da revisao `0046` e as cinco cadeias do modulo que as usam,
corridas contra PostgreSQL com o texto que o TypeScript envia:

```text
excepcao     o quarto valor entra no dominio; a primeira excepcao fica
auditoria    a accao `order.refund_record` entra no dominio fechado do audit_log
re-reserva   o indice parcial deixa reservar outra vez uma linha libertada, e
             nao deixa duas reservas vivas; o savepoint desfaz a re-reserva
```

**Este modulo corre depois dos `test_downgrade*`, e isso nao e acaso.** As linhas
que ele deixa — uma de `audit_log` com a accao nova, que ninguem pode apagar —
fazem o `downgrade` da `0046` **recusar**, que e o que ele deve fazer. A suite
corre numa base so dela (`db/gate_bd.py`) e pela ordem alfabetica dos modulos.
"""

from __future__ import annotations

import pg8000.dbapi

from tests.base import VIOLACAO_DE_CHECK, VIOLACAO_DE_UNICIDADE, sqlstate
from tests_encomendas.consultas import (
    SQL_ABRIR_RERESERVA,
    SQL_AUDITAR_REEMBOLSO,
    SQL_DESFAZER_RERESERVA,
    SQL_FECHAR_RERESERVA,
    SQL_LIBERTAR,
    SQL_MARCAR_EXCEPCAO,
    SQL_RESERVAR,
)
from tests_encomendas.test_reservas import ComReservas

#: A linha de reserva como o repo-base a constroi (`inserirNoTenant`).
INSERIR_RESERVA = (
    "INSERT INTO platform.stock_reservations "
    "       (tenant_id, order_id, line_no, sku, qty, expira_at) "
    "VALUES (%s, %s, %s, %s, %s, now() + interval '48 hours')"
)


class TestExcepcaoDaEncomenda(ComReservas):
    """Regras 2, 3 e 4 do `03` §6.6: a marca na coluna, sem transicao."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()

    def _marcar(self, encomenda: str, excepcao: str):
        conexao, cursor = self.ligar_app(self.tenant)
        cursor.execute(
            SQL_MARCAR_EXCEPCAO.sql,
            SQL_MARCAR_EXCEPCAO.args(self.tenant, encomenda, excepcao),
        )
        linha = cursor.fetchone()
        conexao.commit()
        return linha

    def test_as_quatro_excepcoes_entram_no_dominio(self) -> None:
        for excepcao in (
            "pagamento_tardio_sem_stock",
            "pagamento_duplicado",
            "valor_divergente",
            "pagamento_apos_cancelamento",
        ):
            with self.subTest(excepcao=excepcao):
                encomenda = self.criar_encomenda(self.tenant)
                self.assertEqual(self._marcar(encomenda, excepcao)[1], excepcao)

    def test_uma_excepcao_fora_do_dominio_e_recusada(self) -> None:
        encomenda = self.criar_encomenda(self.tenant)
        with self.assertRaises(pg8000.dbapi.DatabaseError) as recusa:
            self._marcar(encomenda, "inventada")
        self.assertEqual(sqlstate(recusa.exception), VIOLACAO_DE_CHECK)

    def test_a_primeira_excepcao_fica(self) -> None:
        encomenda = self.criar_encomenda(self.tenant)
        self._marcar(encomenda, "pagamento_tardio_sem_stock")
        linha = self._marcar(encomenda, "pagamento_duplicado")
        self.assertEqual(linha[1], "pagamento_tardio_sem_stock")

    def test_marcar_nao_e_transicao(self) -> None:
        """A `version` nao sobe e nao ha linha de registo: o estado nao mudou."""
        encomenda = self.criar_encomenda(self.tenant)
        versao = self.levar_a(self.tenant, encomenda, "cancelada")
        self._marcar(encomenda, "pagamento_apos_cancelamento")
        self.assertEqual(self.estado_de(encomenda), ("cancelada", versao))
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
                (encomenda,),
            ),
            [(versao - 1,)],
        )

    def test_o_filtro_de_tenant_impede_marcar_a_encomenda_de_outro(self) -> None:
        outro = self.criar_tenant()
        alheia = self.criar_encomenda(outro)
        conexao, cursor = self.ligar_app(self.tenant)
        cursor.execute(
            SQL_MARCAR_EXCEPCAO.sql,
            SQL_MARCAR_EXCEPCAO.args(self.tenant, alheia, "pagamento_duplicado"),
        )
        self.assertIsNone(cursor.fetchone())
        conexao.rollback()


class TestAuditoriaDoReembolso(ComReservas):
    """Criterio 5: o registo do reembolso escreve `audit_log`, com a accao nova."""

    def test_a_accao_order_refund_record_escreve_se_como_kamba_app(self) -> None:
        tenant = self.criar_tenant()
        encomenda = self.criar_encomenda(tenant)
        conexao, cursor = self.ligar_app(tenant)
        cursor.execute(
            SQL_AUDITAR_REEMBOLSO.sql,
            SQL_AUDITAR_REEMBOLSO.args(
                tenant,
                "staff",
                "op-7",
                "order.refund_record",
                "orders_mirror",
                encomenda,
                None,
                "order.refund_record\x1f" + encomenda + "\x1f4\x1fTRF-1",
            ),
        )
        conexao.commit()
        self.assertEqual(
            self.consultar(
                "SELECT actor_type, actor_id, action, entity, octet_length(payload_hash) "
                "  FROM platform.audit_log WHERE entity_id = %s",
                (encomenda,),
            ),
            [("staff", "op-7", "order.refund_record", "orders_mirror", 32)],
        )

    def test_o_dominio_continua_fechado(self) -> None:
        tenant = self.criar_tenant()
        conexao, cursor = self.ligar_app(tenant)
        with self.assertRaises(pg8000.dbapi.DatabaseError) as recusa:
            cursor.execute(
                SQL_AUDITAR_REEMBOLSO.sql,
                SQL_AUDITAR_REEMBOLSO.args(
                    tenant, "staff", "op-7", "order.refund_inventado",
                    "orders_mirror", "x", None, "x",
                ),
            )
        self.assertEqual(sqlstate(recusa.exception), VIOLACAO_DE_CHECK)
        conexao.rollback()


class TestReReserva(ComReservas):
    """Regra 1: a linha libertada reserva-se outra vez, e so uma fica viva."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.sku = self.criar_oferta(self.tenant)
        self.encomenda = self.criar_encomenda(self.tenant)

    def _reservar(self, cursor) -> None:
        cursor.execute(INSERIR_RESERVA, (self.tenant, self.encomenda, 0, self.sku, 1))

    def test_uma_linha_libertada_reserva_se_outra_vez(self) -> None:
        conexao, cursor = self.ligar_app(self.tenant)
        self._reservar(cursor)
        cursor.execute(
            SQL_LIBERTAR.sql, SQL_LIBERTAR.args(self.tenant, self.encomenda, "expirada")
        )
        self._reservar(cursor)
        conexao.commit()
        self.assertEqual(
            self.consultar(
                "SELECT estado FROM platform.stock_reservations "
                " WHERE order_id = %s ORDER BY criado_at, estado",
                (self.encomenda,),
            ),
            [("ativa",), ("libertada",)],
        )

    def test_duas_reservas_vivas_na_mesma_linha_sao_recusadas(self) -> None:
        conexao, cursor = self.ligar_app(self.tenant)
        self._reservar(cursor)
        with self.assertRaises(pg8000.dbapi.DatabaseError) as recusa:
            self._reservar(cursor)
        self.assertEqual(sqlstate(recusa.exception), VIOLACAO_DE_UNICIDADE)
        conexao.rollback()

    def test_o_savepoint_desfaz_a_re_reserva_e_deixa_a_transaccao_viva(self) -> None:
        conexao, cursor = self.ligar_app(self.tenant)
        cursor.execute(SQL_ABRIR_RERESERVA.sql)
        cursor.execute(SQL_RESERVAR.sql, SQL_RESERVAR.args(self.tenant, self.sku, 3))
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute(SQL_DESFAZER_RERESERVA.sql)
        cursor.execute(
            "SELECT stock_reservada FROM platform.offer_terms "
            " WHERE tenant_id = %s AND sku = %s",
            (self.tenant, self.sku),
        )
        self.assertEqual(cursor.fetchone()[0], 0, "o savepoint devolveu as tres")
        # E a transaccao continua: a segunda tentativa confirma.
        cursor.execute(SQL_ABRIR_RERESERVA.sql)
        cursor.execute(SQL_RESERVAR.sql, SQL_RESERVAR.args(self.tenant, self.sku, 2))
        cursor.execute(SQL_FECHAR_RERESERVA.sql)
        conexao.commit()
        self.assertEqual(self.stock_de(self.tenant, self.sku)[1], 2)
