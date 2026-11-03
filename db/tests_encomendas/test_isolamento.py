"""Criterio 6: RLS `FORCE`, registo *append-only* e ISO-39..42.

O que so aqui se prova, e nenhum duplo de teste pode: que um `INSERT` directo no
`order_state_log` falha por **privilegio** (`42501`) para o `kamba_app` no que
ele nao tem, e que o `deny_mutation` recusa `UPDATE`, `DELETE` e `TRUNCATE`
**ao superutilizador** — que e o unico que nenhum `REVOKE` prende. Uma base
falsa nao tem papeis, logo nao pode falhar por privilegio nenhum.

## A sonda positiva ao lado, sempre

Quatro zeros contra uma tabela vazia nao provam nada: e a licao que o
`db/tests_produtos/test_isolamento.py` escreveu. Cada ensaio de «B nao ve»
tem ao lado o «A ve», sobre a mesma linha.
"""

from __future__ import annotations

import pg8000.dbapi
from tests.base import PRIVILEGIO_INSUFICIENTE, sqlstate
from tests_encomendas.base import ComEncomendas

#: As quatro tabelas com `tenant_id` da revisao. O grafo nao entra: nao a tem.
COM_TENANT = (
    "orders_mirror",
    "order_intents",
    "order_state_log",
    "order_reconciliation_issues",
)

#: O que o `kamba_app` pode alterar na `orders_mirror`, coluna a coluna.
UPDATE_DA_APP_EM_ENCOMENDAS = (
    "estado",
    "confirmacao_dono",
    "total_minor",
    "lines_snapshot",
    "entrega_modo",
    "medusa_order_id",
    "expira_at",
    "paga_at",
    "paga_via",
    "excepcao",
    "entregue_at",
    "entrega_confirmada_por",
    "version",
    "atualizado_at",
    "deleted_at",
)

#: O que ele **nao** pode alterar, e a razao de cada uma esta na revisao `0030`.
SEM_UPDATE_DA_APP = (
    "id",
    "tenant_id",
    "contact_id",
    "origem",
    "numero_publico",
    "intent_key",
    "currency",
    "criado_at",
)


class TestRlsDasEncomendas(ComEncomendas):
    """ISO-39..42: a encomenda de A nao se ve do contexto de B."""

    def setUp(self) -> None:
        super().setUp()
        self.a = self.criar_tenant()
        self.b = self.criar_tenant()
        self.encomenda = self.criar_encomenda(self.a)

    def test_as_quatro_tem_enable_force_e_politica(self) -> None:
        linhas = self.consultar(
            "SELECT c.relname::text, c.relrowsecurity, c.relforcerowsecurity, "
            "       count(p.polname) "
            "  FROM pg_class c LEFT JOIN pg_policy p ON p.polrelid = c.oid "
            " WHERE c.relnamespace = 'platform'::regnamespace "
            "   AND c.relname = ANY(%s) "
            " GROUP BY 1, 2, 3 ORDER BY 1",
            (list(COM_TENANT),),
        )
        self.assertEqual(
            linhas,
            [(tabela, True, True, 1) for tabela in sorted(COM_TENANT)],
        )

    def test_o_grafo_nao_tem_rls_e_nao_e_falta(self) -> None:
        """Tabela de referencia, sem `tenant_id`: o X-05 pergunta pela coluna."""
        linhas = self.consultar(
            # `count(a.attname)` e **nao** `count(*)`: num `LEFT JOIN` sem
            # correspondencia o `count(*)` conta a linha com nulos e devolve 1,
            # que e o que a primeira versao deste ensaio media (e falhava com
            # `(False, 1) != (False, 0)` sobre uma tabela que nao tem a coluna).
            "SELECT relrowsecurity, count(a.attname) FROM pg_class c "
            " LEFT JOIN pg_attribute a ON a.attrelid = c.oid "
            "       AND a.attname = 'tenant_id' AND a.attnum > 0 "
            " WHERE c.oid = 'platform.order_state_graph'::regclass "
            " GROUP BY 1"
        )
        self.assertEqual(linhas, [(False, 0)])

    def test_a_encomenda_de_a_ve_se_de_a_e_nao_de_b(self) -> None:
        _, cursor_a = self.ligar_app(self.a)
        cursor_a.execute(
            "SELECT count(*) FROM platform.orders_mirror WHERE id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_a.fetchone()[0], 1, "a sonda positiva")

        _, cursor_b = self.ligar_app(self.b)
        cursor_b.execute(
            "SELECT count(*) FROM platform.orders_mirror WHERE id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_b.fetchone()[0], 0, "ISO-39: B nao ve a de A")

    def test_sem_contexto_zero_linhas(self) -> None:
        """Falha fechada: `current_setting(..., true)` da NULL e nada iguala NULL."""
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute("SELECT count(*) FROM platform.orders_mirror")
        self.assertEqual(cursor.fetchone()[0], 0)

    def test_com_contexto_invalido_e_erro_e_nao_linhas(self) -> None:
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', 'nao-e-uuid', true)")
        cursor.fetchone()
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            cursor.execute("SELECT count(*) FROM platform.orders_mirror")

    def test_b_nao_escreve_uma_encomenda_com_o_tenant_de_a(self) -> None:
        """O `WITH CHECK` da politica: o `tenant_id` tem de ser o do contexto."""
        contacto = self.criar_contacto(self.a)
        conexao, cursor = self.ligar_app(self.b)
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            cursor.execute(
                "INSERT INTO platform.orders_mirror "
                "       (tenant_id, contact_id, intent_key, total_minor, "
                "        lines_snapshot) "
                "VALUES (%s, %s, 'ik-cruzado', 1, '[]'::jsonb)",
                (self.a, contacto),
            )
        conexao.rollback()

    def test_uma_encomenda_de_a_nao_aponta_para_um_contacto_de_b(self) -> None:
        """ISO-58: a FK **composta**, e a simples deixava passar.

        Medido no spike KAM-041, e a correccao de 2026-10-27 do §5.4 nomeia
        esta tabela. A FK simples e satisfeita pela chave primaria de
        `contacts`, que nao inclui o tenant.
        """
        contacto_de_b = self.criar_contacto(self.b)
        try:
            self.criar_encomenda(self.a, contacto_de_b)
            self.fail("uma encomenda de A nao devia apontar para um contacto de B")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), "23503")

    def test_o_registo_de_a_nao_se_le_do_contexto_de_b(self) -> None:
        self.levar_a(self.a, self.encomenda, "aguarda_pagamento")
        _, cursor_a = self.ligar_app(self.a)
        cursor_a.execute(
            "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_a.fetchone()[0], 1, "a sonda positiva")
        _, cursor_b = self.ligar_app(self.b)
        cursor_b.execute(
            "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_b.fetchone()[0], 0)


class TestRegistoAppendOnly(ComEncomendas):
    """Criterio 6: «so `INSERT` para `kamba_app`»."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.encomenda = self.criar_encomenda(self.tenant)
        self.levar_a(self.tenant, self.encomenda, "aguarda_pagamento")

    def test_o_kamba_app_nao_tem_update_nem_delete_no_registo(self) -> None:
        linhas = self.consultar(
            "SELECT has_table_privilege('kamba_app', 'platform.order_state_log', p) "
            "  FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) AS p"
        )
        self.assertEqual(linhas, [(True,), (True,), (False,), (False,), (False,)])

    def test_o_update_do_kamba_app_no_registo_falha_por_privilegio(self) -> None:
        conexao, cursor = self.ligar_app(self.tenant)
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            cursor.execute(
                "UPDATE platform.order_state_log SET causa = 'reescrita' "
                " WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        conexao.rollback()

    def test_o_deny_mutation_recusa_tambem_ao_superutilizador(self) -> None:
        """O que nenhum `REVOKE` alcanca. Tres instrucoes, as tres recusadas."""
        for sql in (
            "UPDATE platform.order_state_log SET causa = 'x' WHERE tenant_id = %s",
            "DELETE FROM platform.order_state_log WHERE tenant_id = %s",
        ):
            with self.subTest(sql=sql.split()[0]):
                try:
                    self.semente.execute(sql, (self.tenant,))
                    self.fail(f"{sql.split()[0]} nao devia passar")
                except pg8000.dbapi.DatabaseError as erro:
                    self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)

        try:
            self.semente.execute("TRUNCATE platform.order_state_log")
            self.fail("TRUNCATE nao devia passar")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)

    def test_o_delete_sem_linhas_tambem_e_recusado(self) -> None:
        """O *trigger* por instrucao, que e a razao de serem dois.

        Um `BEFORE DELETE FOR EACH ROW` nao dispara quando nao ha linhas, e um
        `DELETE` que nao apaga nada **parecia** passar — o que deixava quem
        auditasse a pensar que a tabela aceita `DELETE`.
        """
        try:
            self.semente.execute(
                "DELETE FROM platform.order_state_log WHERE causa = 'nao-existe'"
            )
            self.fail("um DELETE sem linhas tambem devia ser recusado")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)

    def test_a_mesma_transicao_gravada_duas_vezes_e_unicidade(self) -> None:
        """A idempotencia do DoD, na restricao e nao no codigo."""
        try:
            self.semente.execute(
                "INSERT INTO platform.order_state_log "
                "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
                "VALUES (%s, %s, 'criada', 'aguarda_pagamento', 2, 'repetida', 'ops')",
                (self.tenant, self.encomenda),
            )
            self.fail("a mesma `(order_id, version)` nao devia passar duas vezes")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), "23505")


class TestPrivilegiosPorColuna(ComEncomendas):
    """O `UPDATE` da encomenda e **por coluna**, e nos dois sentidos.

    A matriz de `db/tests/test_privilegios.py` nao o ve: o
    `has_table_privilege(..., 'UPDATE')` devolve `false` com ou sem um
    `GRANT UPDATE (estado)`. E a mesma razao pela qual a `offer_terms` do
    KAM-043 tem o seu ensaio em `db/tests_produtos/test_contrato.py`.
    """

    def test_o_update_e_por_coluna(self) -> None:
        for coluna in UPDATE_DA_APP_EM_ENCOMENDAS:
            with self.subTest(coluna=coluna, sentido="tem"):
                self.assertEqual(
                    self.consultar(
                        "SELECT has_column_privilege('kamba_app', "
                        "       'platform.orders_mirror', %s, 'UPDATE')",
                        (coluna,),
                    ),
                    [(True,)],
                )
        for coluna in SEM_UPDATE_DA_APP:
            with self.subTest(coluna=coluna, sentido="nao tem"):
                self.assertEqual(
                    self.consultar(
                        "SELECT has_column_privilege('kamba_app', "
                        "       'platform.orders_mirror', %s, 'UPDATE')",
                        (coluna,),
                    ),
                    [(False,)],
                    "mudar esta coluna era mudar a identidade da encomenda ou "
                    "a referencia que o cliente tem no telemovel",
                )

    def test_as_duas_listas_cobrem_a_tabela_inteira(self) -> None:
        """Nos dois sentidos: uma coluna nova cai numa das duas ou falha aqui."""
        colunas = {
            coluna
            for (coluna,) in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'platform' AND table_name = 'orders_mirror'"
            )
        }
        self.assertEqual(
            colunas,
            set(UPDATE_DA_APP_EM_ENCOMENDAS) | set(SEM_UPDATE_DA_APP),
        )

    def test_a_divergencia_fecha_se_por_duas_colunas(self) -> None:
        for coluna, esperado in (
            ("estado", True),
            ("resolvida_at", True),
            ("tipo", False),
            ("detalhe", False),
            ("order_id", False),
        ):
            with self.subTest(coluna=coluna):
                self.assertEqual(
                    self.consultar(
                        "SELECT has_column_privilege('kamba_app', "
                        "       'platform.order_reconciliation_issues', %s, 'UPDATE')",
                        (coluna,),
                    ),
                    [(esperado,)],
                )
