"""Gate 8: o que o catalogo do PostgreSQL diz, e nao o que o DDL parece dizer.

Criterios de aceitacao 5 e 6 do KAM-003, e as linhas de isolamento e
privacidade do DoD.
"""

from __future__ import annotations

from tests import factories
from tests.base import PRIVILEGIO_INSUFICIENTE, TABELAS, ComBase

#: Colunas com `msisdn`, `telefone` ou `phone` no nome que sao aceites.
#:
#: O criterio de aceitacao 5 do KAM-003 da uma **lista fechada de duas** —
#: `contacts.phone_hmac` e `contact_endpoints.phone_enc`, ambas do KAM-008, que
#: as criou na revisao 0003: a primeira e um HMAC com segredo do cofre, a
#: segunda e cifra AES-256-GCM com DEK por contacto. Nenhuma guarda o numero. A
#: terceira esta aqui porque o criterio 3 do mesmo ticket **exige**
#: `tenant_channels.phone_number_id`, que contem `phone`: os dois criterios
#: contradizem-se a letra. `phone_number_id` e o identificador opaco que a Meta
#: atribui ao numero do negocio na Cloud API — nao e um telefone, nao e de um
#: cliente e nao esta em claro em sentido nenhum que o ADR-010 proteja. A
#: contradicao esta registada na verificacao do ticket e devolvida a quem
#: escreveu o criterio; a lista continua fechada, e cada entrada tem razao.
COLUNAS_DE_TELEFONE_ACEITES = {
    ("contacts", "phone_hmac"),
    ("contact_endpoints", "phone_enc"),
    ("tenant_channels", "phone_number_id"),
}
FRAGMENTOS_DE_TELEFONE = ("msisdn", "telefone", "phone")


class TestSemTelefoneEmClaro(ComBase):
    """CA 5 e ADR-010: telefone nunca em claro e nunca como chave."""

    def colunas(self) -> list[tuple[str, str, str]]:
        return self.consultar(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'platform' ORDER BY 1, 2"
        )

    def test_nenhuma_coluna_de_telefone_fora_da_lista_fechada(self) -> None:
        suspeitas = {
            (tabela, coluna)
            for tabela, coluna, _ in self.colunas()
            if any(fragmento in coluna.lower() for fragmento in FRAGMENTOS_DE_TELEFONE)
        }
        self.assertEqual(
            suspeitas - COLUNAS_DE_TELEFONE_ACEITES,
            set(),
            "ha colunas de telefone fora da lista fechada",
        )

    def test_as_colunas_com_phone_sao_exactamente_as_tres_da_lista(self) -> None:
        """Nos dois sentidos: nem uma a mais, nem uma entrada morta na lista.

        Ate ao KAM-008 so existia a da Meta; a revisao 0003 criou as outras
        duas, e a lista fechada passou a estar toda no catalogo.
        """
        suspeitas = {
            (tabela, coluna)
            for tabela, coluna, _ in self.colunas()
            if any(fragmento in coluna.lower() for fragmento in FRAGMENTOS_DE_TELEFONE)
        }
        self.assertEqual(suspeitas, COLUNAS_DE_TELEFONE_ACEITES)

    def test_as_colunas_de_telefone_do_kam_008_nao_guardam_texto(self) -> None:
        """`bytea` nas duas: um HMAC de 32 octetos e uma cifra, nunca o numero."""
        tipos = {
            (tabela, coluna): tipo
            for tabela, coluna, tipo in self.colunas()
            if (tabela, coluna) in COLUNAS_DE_TELEFONE_ACEITES
        }
        self.assertEqual(tipos[("contacts", "phone_hmac")], "bytea")
        self.assertEqual(tipos[("contact_endpoints", "phone_enc")], "bytea")

    def test_o_telefone_nao_e_chave_de_nada(self) -> None:
        """ADR-010: nenhuma chave primaria nem FK assenta numa coluna de telefone.

        `contacts_phone_hmac_uq` e um indice unico **parcial** sobre o HMAC, para
        que dois contactos com o mesmo telefone se fundam; nao e chave primaria,
        nao e alvo de FK, e o HMAC nao e o numero.
        """
        linhas = self.consultar(
            "SELECT c.conname::text, a.attname::text FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
            "WHERE c.connamespace = 'platform'::regnamespace AND c.contype IN ('p', 'f') "
            "AND (a.attname LIKE '%%phone%%' OR a.attname LIKE '%%msisdn%%' "
            " OR a.attname LIKE '%%telefone%%')"
        )
        self.assertEqual(linhas, [])

    def test_o_que_e_cifrado_e_bytea(self) -> None:
        """Uma coluna `_enc` em `text` convidava a guardar o valor em claro."""
        for tabela, coluna, tipo in self.colunas():
            if coluna.endswith("_enc"):
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    self.assertEqual(tipo, "bytea")


class TestConvencoes(ComBase):
    """Dicionario §2: identificadores, tempos e isolamento."""

    def test_so_ha_as_tabelas_declaradas(self) -> None:
        """Sem encomendas, pagamentos nem eventos: sao de outros tickets."""
        tabelas = self.consultar(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
        )
        self.assertEqual(tuple(t for (t,) in tabelas), TABELAS)

    def test_as_chaves_primarias_sao_uuid_com_omissao_gerada(self) -> None:
        linhas = self.consultar(
            "SELECT table_name, data_type, column_default FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND column_name = 'id'"
        )
        self.assertEqual(
            {t for t, _, _ in linhas}, {"tenants", "tenant_channels", "contact_endpoints"}
        )
        for tabela, tipo, omissao in linhas:
            with self.subTest(tabela=tabela):
                self.assertEqual(tipo, "uuid")
                self.assertEqual(omissao, "gen_random_uuid()")

    def test_as_chaves_primarias_sao_as_declaradas(self) -> None:
        """Todas `uuid` geradas, menos duas que tem razao escrita.

        `entitlements` tem chave composta (KAM-003). `hmac_key_versions.kid` e
        `text`: e o identificador que o cofre da a versao do segredo, e nao um
        identificador que a base gere.
        """
        linhas = self.consultar(
            "SELECT c.relname::text, a.attname::text, format_type(a.atttypid, a.atttypmod), "
            "pg_get_expr(d.adbin, d.adrelid) FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE i.indisprimary AND c.relnamespace = 'platform'::regnamespace "
            "ORDER BY 1, 2"
        )
        self.assertEqual(
            linhas,
            [
                ("contact_deks", "dek_id", "uuid", "gen_random_uuid()"),
                ("contact_endpoints", "id", "uuid", "gen_random_uuid()"),
                ("contacts", "contact_id", "uuid", "gen_random_uuid()"),
                ("entitlements", "modulo", "text", None),
                ("entitlements", "tenant_id", "uuid", None),
                ("hmac_key_versions", "kid", "text", None),
                ("tenant_channels", "id", "uuid", "gen_random_uuid()"),
                ("tenants", "id", "uuid", "gen_random_uuid()"),
            ],
        )

    def test_a_chave_de_tenants_chama_se_id(self) -> None:
        """Dicionario §3.2 (emenda 1.2): `id`, nao `tenant_id`."""
        linhas = self.consultar(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'platform.tenants'::regclass AND i.indisprimary"
        )
        self.assertEqual(linhas, [("id",)])

    def test_toda_a_coluna_at_e_timestamptz(self) -> None:
        linhas = self.consultar(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND column_name LIKE '%%\\_at'"
        )
        self.assertTrue(linhas, "nao encontrei colunas de tempo")
        for tabela, coluna, tipo in linhas:
            with self.subTest(coluna=f"{tabela}.{coluna}"):
                self.assertEqual(tipo, "timestamp with time zone")

    def test_nao_ha_timestamp_sem_fuso_em_lado_nenhum(self) -> None:
        linhas = self.consultar(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' "
            "AND data_type = 'timestamp without time zone'"
        )
        self.assertEqual(linhas, [])

    def test_tenant_id_e_not_null_e_vem_primeiro_num_indice(self) -> None:
        """DoD: `tenant_id` presente e indexado, pronto para a RLS do KAM-004.

        Em primeiro lugar no indice, porque e o predicado que a RLS acrescenta
        a todas as consultas: num indice `(estado, tenant_id)` nao serviria.
        """
        com_tenant = self.consultar(
            "SELECT table_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND column_name = 'tenant_id'"
        )
        self.assertEqual(
            {t for t, _ in com_tenant},
            {"tenant_channels", "entitlements", "contacts", "contact_deks",
             "contact_endpoints"},
        )
        for tabela, anulavel in com_tenant:
            with self.subTest(tabela=tabela):
                self.assertEqual(anulavel, "NO")
                primeiras = self.consultar(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    " AND a.attnum = i.indkey[0] "
                    "WHERE i.indrelid = %s::regclass",
                    (f"platform.{tabela}",),
                )
                self.assertIn(("tenant_id",), primeiras)

    def test_nao_ha_colunas_de_dinheiro_nem_saldos(self) -> None:
        """DoD: o DDL nao modela saldos — a plataforma nao detem fundos."""
        linhas = self.consultar(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND (column_name LIKE '%%saldo%%' "
            " OR column_name LIKE '%%balance%%' OR column_name LIKE '%%\\_minor' "
            " OR column_name LIKE '%%\\_kz')"
        )
        self.assertEqual(linhas, [])

    def test_nao_ha_fk_para_fora_de_platform(self) -> None:
        """As FK entre `platform` e `medusa` sao logicas (texto), nunca de base."""
        linhas = self.consultar(
            "SELECT conname, confrelid::regclass::text FROM pg_constraint "
            "WHERE contype = 'f' AND connamespace = 'platform'::regnamespace"
        )
        self.assertEqual(len(linhas), 12)
        for nome, alvo in linhas:
            with self.subTest(fk=nome):
                self.assertTrue(alvo.startswith("platform."), alvo)


class TestPapeis(ComBase):
    """CA 6: os tres papeis existem, e `kamba_app` nao cria tabelas."""

    def atributos(self) -> dict[str, tuple]:
        linhas = self.consultar(
            "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, "
            "rolcanlogin, rolreplication FROM pg_roles WHERE rolname LIKE 'kamba\\_%%'"
        )
        return {linha[0]: linha[1:] for linha in linhas}

    def test_existem_os_cinco_e_so_os_cinco(self) -> None:
        """Os tres do KAM-003, o `kamba_resolver` do KAM-004 e o `kamba_identity` do KAM-008."""
        self.assertEqual(
            set(self.atributos()),
            {"kamba_migrator", "kamba_app", "kamba_batch", "kamba_resolver",
             "kamba_identity"},
        )

    def test_nenhum_e_superutilizador_nem_cria_bases_ou_papeis(self) -> None:
        for papel, (super_, createdb, createrole, _, login, replicacao) in (
            self.atributos().items()
        ):
            with self.subTest(papel=papel):
                self.assertFalse(super_)
                self.assertFalse(createdb)
                self.assertFalse(createrole)
                self.assertFalse(replicacao)
                self.assertTrue(login)

    def test_so_o_batch_contorna_a_rls(self) -> None:
        contorna = {papel: a[3] for papel, a in self.atributos().items()}
        self.assertEqual(
            contorna,
            {
                "kamba_migrator": False,
                "kamba_app": False,
                "kamba_batch": True,
                "kamba_resolver": False,
                "kamba_identity": False,
            },
        )

    def test_create_table_sob_kamba_app_falha(self) -> None:
        cursor = self.ligar("app").cursor()
        for schema in ("platform", "public"):
            with self.subTest(schema=schema):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    f"CREATE TABLE {schema}.nao_devia_existir (x integer)",
                )

    def test_kamba_app_nao_altera_nem_apaga_tabelas(self) -> None:
        cursor = self.ligar("app").cursor()
        for instrucao in (
            "ALTER TABLE platform.tenants ADD COLUMN intrusa text",
            "DROP TABLE platform.entitlements",
            "CREATE SCHEMA nao_devia_existir",
            "TRUNCATE platform.entitlements",
        ):
            with self.subTest(instrucao=instrucao):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, instrucao)

    def test_kamba_batch_tambem_nao_faz_ddl(self) -> None:
        """`BYPASSRLS` e sobre linhas, nao sobre estrutura."""
        cursor = self.ligar("batch").cursor()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            "CREATE TABLE platform.nao_devia_existir (x integer)",
        )

    def test_app_e_batch_leem_e_escrevem_as_tres_tabelas(self) -> None:
        for identidade in ("app", "batch"):
            with self.subTest(identidade=identidade):
                cursor = self.ligar(identidade).cursor()
                tenant = factories.tenant(cursor)
                factories.canal(cursor, tenant)
                factories.entitlement(cursor, tenant)
                cursor.execute(
                    "UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,)
                )
                cursor.execute(
                    "SELECT count(*) FROM platform.tenant_channels WHERE tenant_id = %s",
                    (tenant,),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_o_migrator_nao_e_dono_de_nada_fora_do_que_criou(self) -> None:
        linhas = self.consultar(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE tableowner = 'kamba_migrator' ORDER BY 1, 2"
        )
        self.assertEqual(
            linhas,
            [("platform", tabela) for tabela in TABELAS]
            + [("public", "alembic_version")],
        )

    def test_public_nao_tem_create_no_schema_public(self) -> None:
        linhas = self.consultar(
            "SELECT has_schema_privilege('public', 'public', 'CREATE'), "
            "has_schema_privilege('kamba_app', 'platform', 'CREATE'), "
            "has_schema_privilege('kamba_app', 'platform', 'USAGE')"
        )
        self.assertEqual(linhas, [(False, False, True)])
