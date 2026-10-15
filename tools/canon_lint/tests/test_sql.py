"""O leitor de DDL: o que tira, e o que recusa em vez de saltar."""

from __future__ import annotations

import unittest

from canon_lint import sql


def obj(texto: str) -> sql.Objectos:
    return sql.analisar(texto)[0]


def checks(texto: str) -> list[tuple[str, list[str], bool]]:
    return [(c.coluna, c.valores, c.fechado) for c in obj(texto).checks]


class TestTokenizar(unittest.TestCase):
    def valores(self, texto: str) -> list[tuple[str, str]]:
        return [(t.tipo, t.valor) for t in sql.tokenizar(texto)]

    def test_comentarios_nao_sao_tokens(self) -> None:
        self.assertEqual(
            self.valores("a -- valor_kz\n/* sig_ok */ b"), [("ident", "a"), ("ident", "b")]
        )

    def test_cadeia_com_plica_dobrada(self) -> None:
        self.assertEqual(self.valores("'d''agua'"), [("str", "d'agua")])

    def test_cadeia_com_prefixo_e_e_plica_escapada(self) -> None:
        """ANALISE-05 m1: `E'a\\'b'` fechava a meio e engolia o DDL seguinte."""
        texto = "COMMENT ON TABLE t IS E'a\\'b'; CREATE TABLE platform.consent_log (id uuid); COMMENT ON TABLE t IS E'c\\'d'"
        o = obj(texto)
        self.assertEqual(o.instrucoes, 3)
        self.assertEqual([n for _, n, _ in o.tabelas], ["consent_log"])
        self.assertEqual(self.valores("E'a\\'b'"), [("str", "a'b")])
        self.assertEqual(self.valores("nome 'x'"), [("ident", "nome"), ("str", "x")], "so o prefixo colado conta")

    def test_identificador_nao_citado_fica_em_minusculas(self) -> None:
        self.assertEqual(self.valores('Valor_KZ "Valor_KZ"'), [("ident", "valor_kz"), ("ident", "Valor_KZ")])

    def test_bloco_dollar_e_um_token_opaco(self) -> None:
        tokens = sql.tokenizar("CREATE FUNCTION f() AS $corpo$ BEGIN x; END $corpo$ LANGUAGE plpgsql")
        self.assertEqual([t.tipo for t in tokens].count("dollar"), 1)
        self.assertEqual(len(sql.instrucoes(tokens)), 1, "o `;` dentro do bloco nao parte a instrucao")

    def test_linhas(self) -> None:
        tokens = sql.tokenizar("a\n\n  b\n'x\ny' c")
        self.assertEqual([(t.valor, t.linha) for t in tokens], [("a", 1), ("b", 3), ("x\ny", 4), ("c", 5)])

    def test_cadeia_por_fechar_e_erro(self) -> None:
        for texto in ("'abc", "/* abc", '"abc', "$$ abc"):
            with self.subTest(texto=texto), self.assertRaises(sql.SqlIlegivel):
                sql.tokenizar(texto)


class TestCreateTable(unittest.TestCase):
    def test_tabela_qualificada_e_colunas(self) -> None:
        o = obj("CREATE TABLE IF NOT EXISTS platform.tenants (id uuid PRIMARY KEY, nome text NOT NULL)")
        self.assertEqual(o.tabelas, [("platform", "tenants", 1)])
        self.assertEqual([(t, c) for t, c, _ in o.colunas], [("tenants", "id"), ("tenants", "nome")])

    def test_restricoes_de_tabela_nao_sao_colunas(self) -> None:
        o = obj(
            "CREATE TABLE t (a int, b int, CONSTRAINT t_pk PRIMARY KEY (a, b), "
            "UNIQUE (b), FOREIGN KEY (a) REFERENCES u (id), CHECK (a > 0))"
        )
        self.assertEqual([c for _, c, _ in o.colunas], ["a", "b"])
        self.assertIn(("t", ["a", "b"], 1), o.unicidades)
        self.assertIn(("t", ["b"], 1), o.unicidades)

    def test_virgula_dentro_de_parenteses_nao_parte_a_coluna(self) -> None:
        o = obj("CREATE TABLE t (preco numeric(12, 2), estado text CHECK (estado IN ('a', 'b')))")
        self.assertEqual([c for _, c, _ in o.colunas], ["preco", "estado"])

    def test_o_tipo_da_coluna_e_guardado_para_ligar_um_enum(self) -> None:
        o = obj("CREATE TABLE t (estado platform.estado_t NOT NULL DEFAULT 'a', nome text)")
        self.assertEqual([(c, tipo) for _, c, tipo, _ in o.tipos_de_coluna], [("estado", ["platform", "estado_t"]), ("nome", ["text"])])

    def test_create_table_as_e_desconhecida_e_nao_tabela_sem_colunas(self) -> None:
        self.assertEqual(len(obj("CREATE TABLE copia AS SELECT * FROM t").desconhecidas), 1)

    def test_particao(self) -> None:
        o = obj("CREATE TABLE q_2026_10 PARTITION OF assistant_queries FOR VALUES FROM ('a') TO ('b')")
        self.assertEqual(o.tabelas, [("", "q_2026_10", 1)])
        self.assertEqual(o.desconhecidas, [])


class TestCheck(unittest.TestCase):
    def test_in_que_e_a_restricao_inteira_e_dominio_fechado(self) -> None:
        self.assertEqual(
            checks("CREATE TABLE t (estado text CONSTRAINT ck CHECK (estado IN ('a','b')))"),
            [("estado", ["a", "b"], True)],
        )

    def test_as_formas_do_pg_dump(self) -> None:
        """ANALISE-05 M1: com `::text` a coluna era lida como `text` e o dominio perdia-se."""
        for expressao in (
            "estado::text IN ('a','b')",
            "(estado)::text IN ('a'::text, 'b'::text)",
            "((estado)::text = ANY ((ARRAY['a'::character varying, 'b'::character varying])::text[]))",
            "(estado = ANY (ARRAY['a'::text, 'b'::text]))",
            "estado::character varying(20) IN ('a','b')",
            "estado = 'a' OR estado = 'b'",
            "((estado = 'a') OR (estado = 'b'))",
        ):
            with self.subTest(expressao=expressao):
                self.assertEqual(
                    checks(f"CREATE TABLE t (estado text, CHECK ({expressao}))"), [("estado", ["a", "b"], True)]
                )

    def test_or_sobre_colunas_diferentes_nao_e_dominio_fechado(self) -> None:
        self.assertEqual(
            checks("CREATE TABLE t (a text, b text, CHECK (a = 'x' OR b = 'y'))"),
            [("a", ["x"], False), ("b", ["y"], False)],
        )

    def test_in_dentro_de_expressao_maior_nao_e_dominio_fechado(self) -> None:
        """`docs/tecnica/04` §6.2: `confirmar_exige_autenticacao`."""
        self.assertEqual(
            checks(
                "CREATE TABLE t (tipo text, metodo text, CONSTRAINT c CHECK "
                "(tipo <> 'confirmado' OR metodo IN ('hmac','manual')))"
            ),
            [("tipo", ["confirmado"], False), ("metodo", ["hmac", "manual"], False)],
        )

    def test_not_in_nao_le_o_not_como_coluna(self) -> None:
        self.assertEqual(checks("CREATE TABLE t (estado text CHECK (estado NOT IN ('x')))"), [])

    def test_o_que_nao_e_comparacao_de_coluna_com_texto_nao_da_valores(self) -> None:
        """As formas da revisao 0001: nenhuma delas e um dominio."""
        o = obj(
            "CREATE TABLE t ("
            " nif text CHECK (nif <> '' AND nif = btrim(nif)),"
            " nome text CHECK (btrim(nome) <> ''),"
            " vertical text CHECK (vertical ~ '^[a-z][a-z0-9_]*$'),"
            " limites jsonb CHECK (jsonb_typeof(limites) = 'object'),"
            " usados integer CHECK (usados >= 0))"
        )
        self.assertEqual(o.checks, [])
        self.assertEqual(len(o.colunas), 5)

    def test_cada_check_fica_registado_em_bruto_mesmo_sem_valores(self) -> None:
        """E o que permite falhar quando uma coluna com dominio esta num CHECK ilegivel."""
        o = obj("CREATE TABLE t (estado text CHECK (estado SIMILAR TO '(a|b)'))")
        self.assertEqual(o.checks, [])
        self.assertEqual([(t, i) for t, i, _ in o.checks_brutos], [("t", ["estado", "similar", "to"])])


class TestOutrasInstrucoes(unittest.TestCase):
    def test_alter_table_add_column(self) -> None:
        o = obj("ALTER TABLE platform.tenants ADD COLUMN IF NOT EXISTS valor_kz int, ADD plano_novo text")
        self.assertEqual([(t, c) for t, c, _ in o.colunas], [("tenants", "valor_kz"), ("tenants", "plano_novo")])

    def test_alter_table_add_constraint_check(self) -> None:
        o = obj("ALTER TABLE t ADD CONSTRAINT ck CHECK (estado IN ('a','b'))")
        self.assertEqual(o.colunas, [])
        self.assertEqual((o.checks[0].tabela, o.checks[0].valores), ("t", ["a", "b"]))

    def test_alter_table_rename(self) -> None:
        o = obj("ALTER TABLE t RENAME COLUMN valor TO valor_kz; ALTER TABLE t RENAME TO consent_log")
        self.assertEqual([(t, c) for t, c, _ in o.colunas], [("t", "valor_kz")])
        self.assertEqual([n for _, n, _ in o.tabelas], ["consent_log"])

    def test_rls_e_politicas_sao_reconhecidas_e_nao_dao_nomes(self) -> None:
        """As formas da revisao 0002 do KAM-004."""
        o = obj(
            "ALTER TABLE platform.tenants ENABLE ROW LEVEL SECURITY;"
            "ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY;"
            "CREATE POLICY tenant_iso ON platform.tenants USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);"
            "CREATE POLICY resolver_leitura ON platform.tenants FOR SELECT TO kamba_resolver USING (true);"
            "GRANT SELECT (id, tipo, estado) ON platform.tenants TO kamba_resolver;"
            "REVOKE ALL ON platform.tenants FROM PUBLIC;"
            "COMMENT ON TABLE platform.tenants IS 'x';"
            "CREATE INDEX i ON platform.tenants (id);"
            "DROP POLICY tenant_iso ON platform.tenants;"
            "ALTER TABLE platform.tenants NO FORCE ROW LEVEL SECURITY, DISABLE ROW LEVEL SECURITY"
        )
        self.assertEqual(o.desconhecidas, [])
        self.assertEqual((o.tabelas, o.colunas, o.checks), ([], [], []))
        self.assertEqual(o.instrucoes, 10)

    def test_create_schema_view_role_type(self) -> None:
        o = obj(
            "CREATE SCHEMA IF NOT EXISTS servicos; CREATE OR REPLACE VIEW platform.v_x AS SELECT 1;"
            "CREATE ROLE kamba_ops; CREATE TYPE platform.estado_t AS ENUM ('a', 'b');"
            "CREATE DOMAIN platform.kz AS bigint; CREATE TYPE par AS (esquerda int, direita int)"
        )
        self.assertEqual([n for n, _ in o.esquemas], ["servicos"])
        self.assertEqual([(e, n) for e, n, _ in o.tabelas], [("platform", "v_x")])
        self.assertEqual([n for n, _ in o.papeis], ["kamba_ops"])
        self.assertEqual(o.enums["estado_t"][0], ["a", "b"])
        self.assertEqual([n for n, _ in o.tipos], ["estado_t", "kz", "par"])
        self.assertEqual([(t, c) for t, c, _ in o.colunas], [("par", "esquerda"), ("par", "direita")])

    def test_alter_type_add_value_e_um_valor_novo(self) -> None:
        o = obj("ALTER TYPE platform.estado_t ADD VALUE IF NOT EXISTS 'inventado' AFTER 'a'")
        self.assertEqual([(c.tabela, c.valores) for c in o.checks], [("estado_t", ["inventado"])])

    def test_indice_unico_sem_where_e_unicidade_e_com_where_nao(self) -> None:
        o = obj(
            "CREATE UNIQUE INDEX a ON platform.payment_events (provider, referencia);"
            "CREATE UNIQUE INDEX b ON platform.tenants (nif) WHERE nif IS NOT NULL"
        )
        self.assertEqual([(t, c) for t, c, _ in o.unicidades], [("payment_events", ["provider", "referencia"])])

    def test_instrucao_de_forma_desconhecida_nao_e_saltada(self) -> None:
        for texto in ("CREATE FOREIGN TABLE x (a int)", "MERGE INTO t USING u ON true", "ALTER SYSTEM SET x = 1", "(SELECT 1)"):
            with self.subTest(texto=texto):
                self.assertEqual(len(obj(texto).desconhecidas), 1)

    def test_ddl_que_cria_nomes_sem_os_mostrar_e_desconhecido(self) -> None:
        """ANALISE-05 M5: todas estas passavam com zero achados."""
        for texto in (
            "DO $$ BEGIN CREATE TABLE platform.x (coisa text); END $$",
            "DO $$ BEGIN CREATE ROLE kamba_inventado; END $$",
            "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN ALTER TABLE t ADD COLUMN x int; END $$",
            "DO $f$ BEGIN EXECUTE 'CREATE TABLE platform.x (valor_kz bigint)'; END $f$",
            "SELECT 1 AS coisa, 2 AS outra INTO platform.x",
            "WITH a AS (SELECT 1) SELECT * INTO platform.x FROM a",
            "CREATE SCHEMA platform CREATE TABLE x (coisa text)",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(len(obj(texto).desconhecidas), 1)

    def test_o_que_nao_cria_nada_continua_a_passar(self) -> None:
        for texto in (
            "DO $$ BEGIN RAISE NOTICE 'ola'; END $$",
            "CREATE FUNCTION platform.deny() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'x'; END $$",
            "SELECT set_config('app.tenant_id', '', false)",
            "INSERT INTO platform.tenants (id) SELECT gen_random_uuid()",
            "WITH a AS (SELECT 1) INSERT INTO platform.t SELECT * FROM a",
            "CREATE SCHEMA platform AUTHORIZATION kamba_migrator",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(obj(texto).desconhecidas, [])

    def test_create_schema_authorization_da_o_nome_do_esquema(self) -> None:
        self.assertEqual([n for n, _ in obj("CREATE SCHEMA AUTHORIZATION kamba_xpto").esquemas], ["kamba_xpto"])

    def test_bloco_dollar_conta_se_como_opaco(self) -> None:
        o = obj("CREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$")
        self.assertEqual((o.opacos, o.desconhecidas), (1, []))

    def test_juntar_desloca_as_linhas(self) -> None:
        a, b = sql.Objectos(), obj("CREATE TABLE t (\n  estado text CHECK (estado IN ('a'))\n)")
        a.juntar(b, 10)
        self.assertEqual(a.tabelas, [("", "t", 11)])
        self.assertEqual(a.colunas, [("t", "estado", 12)])
        self.assertEqual(a.checks[0].linha, 12)


if __name__ == "__main__":
    unittest.main()
