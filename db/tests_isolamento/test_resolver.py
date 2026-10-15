"""O papel `kamba_resolver`: leitura estreita, antes de haver contexto.

Criterio de aceitacao 7 do KAM-004: «so tem `SELECT` nas colunas necessarias,
por politica `TO kamba_resolver`; nao consegue ler outras tabelas».

O resolvedor responde a uma pergunta — a que tenant pertence este
`phone_number_id` — e essa pergunta faz-se sem contexto de tenant, pelo que tem
de ver linhas de **todos** os tenants. E o papel mais perigoso depois do
`kamba_batch`, e por isso tudo o que nao e essa pergunta lhe esta vedado.
"""

from __future__ import annotations

from tests.base import PRIVILEGIO_INSUFICIENTE
from tests_isolamento.base import ComDoisTenants, definir_contexto

#: O que a revisao 0002 concede. O teste confere-o nos dois sentidos, coluna a
#: coluna, contra o catalogo.
COLUNAS_LEGIVEIS = {
    "tenant_channels": {
        "id", "tenant_id", "phone_number_id", "vertical", "origem", "estado",
        "channel_mode",
    },
    "tenants": {"id", "tipo", "estado"},
}


class TestResolver(ComDoisTenants):
    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("resolver").cursor()

    def test_resolve_o_tenant_de_um_phone_number_id_sem_contexto(self) -> None:
        """A pergunta para que o papel existe."""
        admin = self.ligar("admin").cursor()
        admin.execute(
            "SELECT phone_number_id FROM platform.tenant_channels WHERE tenant_id = %s",
            (self.b.id,),
        )
        phone_number_id = admin.fetchone()[0]

        self.cursor.execute(
            "SELECT c.tenant_id::text, c.vertical, c.estado, t.estado "
            "FROM platform.tenant_channels c JOIN platform.tenants t ON t.id = c.tenant_id "
            "WHERE c.phone_number_id = %s",
            (phone_number_id,),
        )
        self.assertEqual(
            [tuple(l) for l in self.cursor.fetchall()],
            [(self.b.id, "vendedor", "pendente", "onboarding")],
        )

    def test_ve_as_linhas_dos_dois_tenants(self) -> None:
        self.cursor.execute(
            "SELECT tenant_id::text FROM platform.tenant_channels WHERE tenant_id IN (%s, %s)",
            (self.a.id, self.b.id),
        )
        self.assertEqual({l[0] for l in self.cursor.fetchall()}, {self.a.id, self.b.id})

    def test_as_colunas_legiveis_sao_exactamente_as_concedidas(self) -> None:
        for tabela, esperadas in COLUNAS_LEGIVEIS.items():
            colunas = self.consultar(
                "SELECT column_name::text, has_column_privilege('kamba_resolver', "
                "'platform.' || table_name, column_name::text, 'SELECT') "
                "FROM information_schema.columns "
                "WHERE table_schema = 'platform' AND table_name = %s",
                (tabela,),
            )
            legiveis = {coluna for coluna, pode in colunas if pode}
            self.assertEqual(legiveis, esperadas, tabela)

    def test_nao_le_o_que_nao_precisa(self) -> None:
        """Nem a referencia ao segredo, nem o NIF, nem o nome."""
        for consulta in (
            "SELECT token_ref FROM platform.tenant_channels",
            "SELECT waba_id FROM platform.tenant_channels",
            "SELECT * FROM platform.tenant_channels",
            "SELECT nome FROM platform.tenants",
            "SELECT nif FROM platform.tenants",
            "SELECT contacto_negocio_enc FROM platform.tenants",
            "SELECT * FROM platform.tenants",
        ):
            with self.subTest(consulta=consulta):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, consulta)

    def test_nao_le_outras_tabelas(self) -> None:
        for consulta in (
            "SELECT * FROM platform.entitlements",
            "SELECT count(*) FROM platform.entitlements",
            "SELECT tenant_id FROM platform.entitlements",
            "SELECT * FROM public.alembic_version",
        ):
            with self.subTest(consulta=consulta):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, consulta)

    def _recusada_por_privilegio(self, instrucao: str, parametros: tuple = ()) -> None:
        """Recusada por **falta de privilegio**, e nao pela politica.

        `42501` e o SQLSTATE dos dois casos. Um `INSERT` do resolvedor sem
        contexto e recusado pela RLS **mesmo que ele tenha o privilegio** — e
        com contexto passava. Aceitar qualquer `42501` deixou um `GRANT INSERT`
        ao resolvedor passar nos dois gates (achado 2 da revisao do KAM-004).
        """
        import pg8000.dbapi

        from tests.base import sqlstate

        self.cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.cursor.execute(instrucao, parametros)
        finally:
            self.cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertIn("permission denied", str(capturado.exception))
        self.assertNotIn("row-level security", str(capturado.exception))

    def test_nao_escreve_em_nada(self) -> None:
        for instrucao in (
            "UPDATE platform.tenant_channels SET estado = 'ativo'",
            "UPDATE platform.tenants SET estado = 'suspenso'",
            "DELETE FROM platform.tenant_channels",
            "DELETE FROM platform.tenants",
            "INSERT INTO platform.tenants (id, tipo, nome) "
            "VALUES (gen_random_uuid(), 'pme', 'x')",
            "TRUNCATE platform.tenant_channels",
            "CREATE TABLE platform.do_resolvedor (x integer)",
            "CREATE TEMP TABLE t_resolvedor (x integer)",
        ):
            with self.subTest(instrucao=instrucao):
                self._recusada_por_privilegio(instrucao)

    def test_nem_dando_a_si_proprio_um_contexto_consegue_escrever(self) -> None:
        """O resolvedor pode definir `app.tenant_id` como quiser.

        Com `INSERT` concedido e o contexto certo, a politica `tenant_iso`
        deixava-o criar um tenant e por um `phone_number_id` num tenant a
        escolha — desviar as mensagens de um negocio. So a falta do privilegio o
        impede, e e isso que aqui se mede.
        """
        novo = "99999999-aaaa-4bbb-8ccc-dddddddddddd"
        definir_contexto(self.cursor, novo)
        self._recusada_por_privilegio(
            "INSERT INTO platform.tenants (id, tipo, nome) VALUES (%s, 'platform', 'x')",
            (novo,),
        )
        definir_contexto(self.cursor, self.a.id)
        self._recusada_por_privilegio(
            "INSERT INTO platform.tenant_channels "
            "(tenant_id, phone_number_id, waba_id, vertical, token_ref) "
            "VALUES (%s, 'pnid-sequestro', 'w', 'vendedor', 'r')",
            (self.a.id,),
        )
        self._recusada_por_privilegio(
            "UPDATE platform.tenant_channels SET estado = 'suspenso' WHERE tenant_id = %s",
            (self.a.id,),
        )
        self._recusada_por_privilegio(
            "DELETE FROM platform.tenants WHERE id = %s", (self.a.id,)
        )

    def test_o_catalogo_nao_lhe_da_escrita_em_tabela_nem_em_coluna_nenhuma(self) -> None:
        """A matriz, pelo catalogo: so `SELECT`, e so por coluna."""
        linhas = self.consultar(
            "SELECT c.table_name::text, c.column_name::text, p.privilegio "
            "FROM information_schema.columns c "
            "CROSS JOIN unnest(ARRAY['INSERT', 'UPDATE', 'REFERENCES']) AS p(privilegio) "
            "WHERE c.table_schema = 'platform' "
            "AND has_column_privilege('kamba_resolver', "
            "    'platform.' || c.table_name, c.column_name::text, p.privilegio)"
        )
        self.assertEqual(linhas, [])
        tabelas = self.consultar(
            "SELECT c.relname::text, p.privilegio FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', "
            "    'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p(privilegio) "
            "WHERE n.nspname = 'platform' AND c.relkind IN ('r', 'p') "
            "AND has_table_privilege('kamba_resolver', c.oid, p.privilegio)"
        )
        self.assertEqual(tabelas, [])
        self.assertEqual(
            self.consultar(
                "SELECT has_schema_privilege('kamba_resolver', 'platform', 'CREATE'), "
                "has_schema_privilege('kamba_resolver', 'public', 'CREATE')"
            ),
            [(False, False)],
        )

    def test_nao_assume_outro_papel(self) -> None:
        for papel in ("kamba_app", "kamba_batch", "kamba_migrator"):
            with self.subTest(papel=papel):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, f"SET ROLE {papel}")

    def test_nao_contorna_a_rls_ve_tudo_por_politica_propria(self) -> None:
        linhas = self.consultar(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'kamba_resolver'"
        )
        self.assertEqual(linhas, [(False, False)])
        politicas = self.consultar(
            "SELECT tablename, cmd, roles::text, qual FROM pg_policies "
            "WHERE schemaname = 'platform' AND policyname = 'resolver_leitura' ORDER BY 1"
        )
        self.assertEqual(
            politicas,
            [
                ("tenant_channels", "SELECT", "{kamba_resolver}", "true"),
                ("tenants", "SELECT", "{kamba_resolver}", "true"),
            ],
        )

    def test_a_politica_do_resolvedor_nao_serve_a_kamba_app(self) -> None:
        """`TO kamba_resolver`: a leitura total nao se estende a aplicacao."""
        cursor = self.cursor_app()
        cursor.execute("SELECT count(*) FROM platform.tenant_channels")
        self.assertEqual(cursor.fetchone()[0], 0)

    def test_definir_um_contexto_nao_lhe_da_mais_nada(self) -> None:
        definir_contexto(self.cursor, self.a.id)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.cursor, "SELECT * FROM platform.entitlements"
        )
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.cursor, "SELECT token_ref FROM platform.tenant_channels"
        )
