"""As tres superficies de ficheiro: migracoes, schemas de evento e registo.

Os testes correm contra o dicionario **real** do repositorio. E deliberado: o
que interessa provar e que os nomes que o §3 substitui sao recusados, e nao que
um dicionario de brinquedo funciona.

Os casos marcados com um identificador (`M1`, `s20`, `j01`, `r08`…) sao as
evasoes que a revisao adversarial encontrou (ANALISE-05); cada um passava com
zero achados antes da correccao.
"""

from __future__ import annotations

import json
import unittest

from canon_lint import ddl, eventos, registo, yamlreg
from canon_lint.achados import FORA, ILEGIVEL, REGRA, VARIANTE

from .base import saber


def migracao(sql: str) -> str:
    return f'from alembic import op\n\n\ndef upgrade():\n    op.execute("""\n{sql}\n""")\n'


class TestMigracoes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.saber = saber()

    def achados(self, fonte: str, ficheiro: str = "db/migrations/versions/0009_x.py"):
        return ddl.verificar(ficheiro, fonte, self.saber)[0]

    def classes(self, fonte: str) -> list[str]:
        return [a.classe for a in self.achados(fonte)]

    # --- nivel 1 -----------------------------------------------------------------
    def test_a_mutacao_do_ticket_valor_kz_numa_migracao(self) -> None:
        achados = self.achados(migracao("ALTER TABLE platform.tenants ADD COLUMN valor_kz integer"))
        self.assertEqual([a.classe for a in achados], [VARIANTE])
        self.assertIn("`valor_kz` → `valor_minor + currency ∈ {AOA}`, dicionário §3.4", achados[0].mensagem)
        self.assertEqual(achados[0].linha, 6, "a linha e a do ficheiro, nao a do bloco SQL")

    def test_variante_e_apanhada_em_qualquer_posicao(self) -> None:
        """`kamba_ops` nao e tabela nem coluna: e um papel num GRANT e num REVOKE."""
        for sql in (
            "GRANT SELECT ON platform.tenants TO kamba_app, kamba_ops",
            "REVOKE ALL ON platform.tenants FROM PUBLIC, kamba_ops",
            "CREATE INDEX i ON platform.consent_log (tenant_id)",
            "CREATE POLICY p ON platform.tenants USING (sig_ok)",
            "COMMENT ON COLUMN platform.payment_events.callback_hmac_ok IS 'x'",
            "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS $$ SELECT count(*) FROM platform.llm_calls $$",
            'CREATE INDEX "Valor_Kz" ON platform.tenants (id)',  # m2: entre aspas e com maiusculas
            'CREATE TABLE platform.entitlements ("Valor_Kz" integer)',
        ):
            with self.subTest(sql=sql):
                self.assertIn(VARIANTE, self.classes(migracao(sql)))

    def test_variante_dentro_de_uma_cadeia(self) -> None:
        """M3: `valor_max_pedido_kz` e uma chave de `limites jsonb`; em SQL so existe entre plicas."""
        for sql in (
            """INSERT INTO platform.entitlements (tenant_id, modulo, limites) VALUES (gen_random_uuid(), 'vendedor', '{"valor_max_pedido_kz": 5000000}')""",
            "UPDATE platform.entitlements SET limites = jsonb_build_object('valor_max_pedido_kz', 5000000)",
            "ALTER TABLE platform.entitlements ADD CONSTRAINT c CHECK (limites ? 'valor_max_pedido_kz')",
            "CREATE INDEX ix ON platform.entitlements ((limites->>'valor_max_pedido_kz'))",
            "COMMENT ON TABLE platform.tenants IS 'substitui consent_log'",
            "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN PERFORM 'llm_calls'; END $$",
        ):
            with self.subTest(sql=sql):
                achados = self.achados(migracao(sql))
                self.assertEqual({a.classe for a in achados}, {VARIANTE}, [str(a) for a in achados])

    def test_a_fronteira_de_palavra_vale_dentro_das_cadeias(self) -> None:
        self.assertEqual(
            self.classes(migracao("""UPDATE platform.entitlements SET limites = '{"max_preco_kz_total": 1, "xvalor_kz": 2}'""")),
            [],
        )

    def test_variante_de_valor(self) -> None:
        achados = self.achados(
            migracao("CREATE TABLE platform.entitlements (ativo boolean, modulo text CHECK (modulo = 'exato'))")
        )
        self.assertIn("`exato` →", " ".join(a.mensagem for a in achados))

    def test_variante_em_comentario_sql_nao_conta(self) -> None:
        self.assertEqual(self.classes(migracao("-- substitui valor_kz\nCREATE SCHEMA platform")), [])

    def test_identificador_que_so_contem_a_variante_nao_conta(self) -> None:
        self.assertNotIn(
            VARIANTE,
            self.classes(migracao("CREATE TABLE platform.entitlements (ativo boolean, max_preco_kz integer)")),
        )

    # --- nivel 2 -----------------------------------------------------------------
    def test_coluna_fora_do_dicionario(self) -> None:
        achados = self.achados(migracao("ALTER TABLE platform.tenants ADD COLUMN cor_favorita text"))
        self.assertEqual([a.classe for a in achados], [FORA])
        self.assertIn("`tenants.cor_favorita` → `platform.tenants(id uuid)`, dicionário §3.2", achados[0].mensagem)
        self.assertIn("canon/extensoes.yaml", achados[0].mensagem)

    def test_a_extensao_e_qualificada_e_nao_vale_noutra_tabela(self) -> None:
        """`tenants.nif` esta em extensoes; `entitlements.nif` nao."""
        self.assertEqual(self.classes(migracao("ALTER TABLE platform.tenants ADD COLUMN nif text")), [])
        self.assertEqual(self.classes(migracao("ALTER TABLE platform.entitlements ADD COLUMN nif text")), [FORA])

    def test_tabela_e_esquema_fora_do_dicionario(self) -> None:
        self.assertEqual(self.classes(migracao("CREATE TABLE platform.coisas (id uuid)")), [FORA])
        self.assertEqual(self.classes(migracao("CREATE SCHEMA analitica")), [FORA])
        self.assertEqual(self.classes(migracao("CREATE TABLE analitica.entitlements (ativo boolean)")), [FORA])
        self.assertEqual(self.classes(migracao("CREATE SCHEMA servicos; CREATE SCHEMA lg; CREATE SCHEMA idx")), [])

    def test_palavras_de_tipo_e_metades_de_evento_nao_sao_nomes(self) -> None:
        """M2 (s58, s59): tudo isto passava por estar algures entre crases no §3."""
        achados = self.achados(
            migracao(
                "CREATE TABLE platform.payment (confirmed boolean, uuid text, boolean text, yaml text, a text, z0 text);"
                "CREATE TABLE platform.confirmed (ativo boolean);"
                "CREATE TABLE platform.boolean (ativo boolean)"
            )
        )
        recusados = sorted(a.mensagem.split("`")[1] for a in achados if a.classe == FORA)
        self.assertEqual(
            recusados,
            ["boolean", "confirmed", "payment", "payment.a", "payment.boolean", "payment.confirmed",
             "payment.uuid", "payment.yaml", "payment.z0"],
        )

    def test_esquema_e_papel_tem_conjunto_proprio(self) -> None:
        """M2/M31: um nome conhecido como coluna nao serve de esquema nem de papel."""
        self.assertEqual(self.classes(migracao("CREATE SCHEMA tenants")), [FORA])
        self.assertEqual(self.classes(migracao("CREATE ROLE tenants")), [FORA])
        self.assertEqual(self.classes(migracao("CREATE ROLE kamba_inventado")), [FORA])
        self.assertEqual(self.classes(migracao("CREATE ROLE kamba_batch")), [])
        self.assertEqual(self.classes(migracao("CREATE SCHEMA AUTHORIZATION kamba_xpto")), [FORA])  # s54

    def test_tipos_e_dominios_sql(self) -> None:
        """M5 (s29, s30, s28)."""
        self.assertEqual(self.classes(migracao("CREATE DOMAIN platform.kz_xpto AS bigint")), [FORA])
        self.assertEqual(
            self.classes(migracao("CREATE TYPE platform.dinheiro_xpto AS (valor_inventado bigint)")), [FORA, FORA]
        )
        self.assertEqual(
            self.classes(migracao("ALTER TYPE platform.estado ADD VALUE 'inventado_xpto'")), [FORA]
        )

    # --- dominios ------------------------------------------------------------------
    def test_dominio_fechado_falha_por_falta_e_por_excesso(self) -> None:
        falta = self.achados(
            migracao("CREATE TABLE platform.tenant_channels (id uuid, origem text CHECK (origem IN ('pme')))")
        )
        self.assertEqual([a.classe for a in falta], [REGRA])
        self.assertIn("falta: plataforma", falta[0].mensagem)
        a_mais = self.achados(
            migracao(
                "CREATE TABLE platform.tenant_channels (id uuid, estado text CHECK (estado IN "
                "('pendente','ativo','restrito','desligado','suspenso','encerrado','pausado')))"
            )
        )
        self.assertEqual([a.classe for a in a_mais], [REGRA])
        self.assertIn("a mais: pausado", a_mais[0].mensagem)

    def test_um_dominio_fechado_pode_crescer_numa_revisao_posterior(self) -> None:
        """KAM-029: a revisao antiga declara o dominio antigo, e isso e historia.

        Um dominio fechado cresce por `DROP CONSTRAINT` + `ADD CONSTRAINT` numa
        revisao posterior. Sem esta regra, **nenhum dominio fechado deste
        repositorio podia crescer**: a revisao que o criou passava a estar sempre
        em falta, e a unica saida era editar uma revisao ja fundida — que e coisa
        que nunca se fez aqui (cada revisao tem um `commit`, do seu ticket).

        Sao **tres** asserçoes e nao uma, porque a regra tem de morder nos dois
        sentidos e nao servir de dispensa:
        """
        estreito = migracao(
            "CREATE TABLE platform.tenant_channels (id uuid, origem text "
            "CHECK (origem IN ('pme')))"
        )
        # 1. sem substituicao declarada, continua a faltar — a regra nao e uma
        #    dispensa por omissao.
        self.assertIn("falta: plataforma", self.achados(estreito)[0].mensagem)
        # 2. com uma revisao posterior a redeclarar o par, a antiga passa.
        substituidos = frozenset({("tenant_channels", "origem")})
        self.assertEqual(
            ddl.verificar(
                "db/migrations/versions/0009_x.py", estreito, self.saber, substituidos
            )[0],
            [],
        )
        # 3. **o excesso continua a cobrar-se**, substituida ou nao: um valor que
        #    o dicionario ja nao tem e defeito em qualquer revisao.
        com_excesso = migracao(
            "CREATE TABLE platform.tenant_channels (id uuid, origem text "
            "CHECK (origem IN ('pme','plataforma','inventado')))"
        )
        achados = ddl.verificar(
            "db/migrations/versions/0009_x.py", com_excesso, self.saber, substituidos
        )[0]
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("a mais: inventado", achados[0].mensagem)

    def test_quem_declara_um_dominio_fechado_e_quem_o_diz(self) -> None:
        """O `declaracoes_fechadas`, que e o que a pre-passagem do `cli` usa.

        Um `CHECK` fechado conta; um que **nao** seja o dominio inteiro da coluna
        nao conta — senao uma restricao parcial numa revisao posterior dispensava
        a anterior de ter o dominio todo, que era a dispensa pela porta do lado.
        """
        fechado = migracao(
            "CREATE TABLE platform.tenant_channels (id uuid, origem text "
            "CHECK (origem IN ('pme','plataforma')))"
        )
        self.assertIn(
            ("tenant_channels", "origem"),
            ddl.declaracoes_fechadas("db/migrations/versions/0009_x.py", fechado, self.saber),
        )
        parcial = migracao(
            "CREATE TABLE platform.tenant_channels (id uuid, origem text, "
            "CONSTRAINT x CHECK (origem IN ('pme') OR id IS NULL))"
        )
        self.assertNotIn(
            ("tenant_channels", "origem"),
            ddl.declaracoes_fechadas("db/migrations/versions/0009_x.py", parcial, self.saber),
        )

    def test_o_dominio_nao_se_contorna_pela_forma_do_pg_dump(self) -> None:
        """M1 (s18, s20, s21): `tenants.estado` sem `restrito`, em tres formas honestas."""
        for expressao in (
            "estado::text IN ('onboarding','ativo','suspenso','encerrado')",
            "((estado)::text = ANY ((ARRAY['onboarding'::character varying, 'ativo'::character varying, "
            "'suspenso'::character varying, 'encerrado'::character varying])::text[]))",
            "estado = 'onboarding' OR estado = 'ativo' OR estado = 'suspenso' OR estado = 'encerrado'",
        ):
            with self.subTest(expressao=expressao):
                achados = self.achados(migracao(f"CREATE TABLE platform.tenants (id uuid, estado text CHECK ({expressao}))"))
                self.assertEqual([a.classe for a in achados], [REGRA])
                self.assertIn("falta: restrito", achados[0].mensagem)

    def test_valor_de_outro_dominio_com_cast(self) -> None:
        """M1 (s63)."""
        achados = self.achados(
            migracao(
                "CREATE TABLE platform.tenants (id uuid, estado text CHECK (estado::text IN "
                "('onboarding','ativo','restrito','suspenso','encerrado','pendente')))"
            )
        )
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("a mais: pendente", achados[0].mensagem)

    def test_enum_e_o_dominio_da_coluna_que_o_usa(self) -> None:
        """M1 (s26)."""
        sem_restrito = (
            "CREATE TYPE platform.estado AS ENUM ('onboarding','ativo','suspenso','encerrado');"
            "CREATE TABLE platform.tenants (id uuid, estado platform.estado NOT NULL)"
        )
        achados = self.achados(migracao(sem_restrito))
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("falta: restrito", achados[0].mensagem)
        completo = sem_restrito.replace("'ativo',", "'ativo','restrito',")
        self.assertEqual(self.classes(migracao(completo)), [])

    def test_coluna_com_dominio_e_sem_check_falha(self) -> None:
        """M1 (s25): o dominio do §3 nao se cumpre por omissao."""
        achados = self.achados(migracao("CREATE TABLE platform.tenants (id uuid, estado text NOT NULL)"))
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("`tenants.estado` sem CHECK fechado", achados[0].mensagem)
        em_duas = (
            "CREATE TABLE platform.tenants (id uuid, estado text NOT NULL);"
            "ALTER TABLE platform.tenants ADD CONSTRAINT ck CHECK "
            "(estado IN ('onboarding','ativo','restrito','suspenso','encerrado'))"
        )
        self.assertEqual(self.classes(migracao(em_duas)), [], "o CHECK pode vir noutra instrucao da mesma revisao")

    def test_coluna_com_dominio_num_check_ilegivel_falha(self) -> None:
        """M1 (s22, s23, s61)."""
        for expressao in ("estado SIMILAR TO '(ativo|inventado)'", "estado ~ '^(ativo|inventado)$'"):
            with self.subTest(expressao=expressao):
                achados = self.achados(migracao(f"CREATE TABLE platform.tenants (id uuid, estado text CHECK ({expressao}))"))
                self.assertIn(ILEGIVEL, [a.classe for a in achados])
                self.assertIn("aparece num CHECK que o gate 3b nao consegue ler", " ".join(a.mensagem for a in achados))
        achados = self.achados(
            migracao("CREATE TABLE platform.payment_events (id uuid, authn_method text CHECK (authn_method LIKE 'h%'))")
        )
        self.assertEqual([a.classe for a in achados], [ILEGIVEL])

    def test_o_dominio_de_modulo_nao_se_aplica_ao_ddl(self) -> None:
        """n2: o §3.2 diz que `entitlements.modulo` tem CHECK de forma; e o que a 0001 faz."""
        self.assertEqual(
            self.classes(migracao("CREATE TABLE platform.entitlements (ativo boolean, modulo text CHECK (modulo ~ '^[a-z]+$'))")),
            [],
        )

    def test_o_ddl_de_tenant_channels_do_doc_03_seria_recusado(self) -> None:
        """A segunda divergencia que o KAM-003 deixou registada: tres estados."""
        achados = self.achados(
            migracao(
                "CREATE TABLE platform.tenant_channels (id uuid, persona text, "
                "estado text CHECK (estado IN ('ativo','pausado','revogado')))"
            )
        )
        self.assertEqual(sorted(a.classe for a in achados), [FORA, REGRA])

    def test_valor_dentro_de_expressao_so_tem_de_pertencer_ao_dominio(self) -> None:
        base = "CREATE TABLE platform.payment_events (tipo text, authn_method text, CONSTRAINT c CHECK (tipo <> 'pme' OR authn_method IN ({})))"
        self.assertEqual(self.classes(migracao(base.format("'hmac','manual'"))), [])
        # Dois achados e nao um, desde a emenda 1.13 (KAM-141, linha 4): o
        # `hmac_sha256` passou a ser **variante registada** de `authn_method`,
        # alem de estar fora do dominio. Os dois dizem coisas diferentes a quem
        # le — «este nome foi substituido» e «este valor nao pertence ao
        # dominio» — e perder o primeiro era perder a razao da substituicao.
        self.assertEqual(
            self.classes(migracao(base.format("'hmac','hmac_sha256'"))), [VARIANTE, REGRA]
        )

    def test_valor_de_check_sem_dominio(self) -> None:
        """M34: nenhum teste cobria os valores de um CHECK cuja coluna nao tem dominio no §3."""
        base = "CREATE TABLE platform.tenants (id uuid, plano text CHECK (plano IN ({})))"
        self.assertEqual(self.classes(migracao(base.format("'pme','ativo'"))), [])
        achados = self.achados(migracao(base.format("'pme','plano_xpto'")))
        self.assertEqual([a.classe for a in achados], [FORA])
        self.assertIn("tenants.plano=plano_xpto", achados[0].mensagem)

    def test_unicidade_proibida_pelo_dicionario(self) -> None:
        for sql in (
            "CREATE TABLE platform.payment_events (provider text, referencia text, UNIQUE (provider, referencia))",
            "CREATE TABLE platform.payment_events (provider text, referencia text, CONSTRAINT u UNIQUE (referencia, provider))",
            "ALTER TABLE platform.payment_events ADD CONSTRAINT u UNIQUE (provider, referencia)",
            "CREATE UNIQUE INDEX u ON platform.payment_events (provider, referencia)",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(self.classes(migracao(sql)), [REGRA])
        self.assertEqual(
            self.classes(migracao("ALTER TABLE platform.payment_events ADD CONSTRAINT u UNIQUE (provider, account_id, referencia)")),
            [],
        )

    # --- falha fechada -------------------------------------------------------------
    def test_sql_que_nao_e_literal_falha(self) -> None:
        for corpo in (
            'op.execute(f"CREATE TABLE {esquema}.valor_kz (id uuid)")',
            'op.execute("CREATE TABLE {}.t (id uuid)".format(esquema))',
            "op.execute(sql_local)",
            'conn.execute(construir("x"))',
        ):
            with self.subTest(corpo=corpo):
                fonte = f"from alembic import op\n\ndef upgrade():\n    {corpo}\n"
                self.assertEqual(self.classes(fonte), [ILEGIVEL])

    def test_api_de_operacoes_e_metadados_falham(self) -> None:
        fonte = "from alembic import op\nimport sqlalchemy as sa\n\ndef upgrade():\n    op.create_table('valor_kz')\n    op.add_column('tenants', None)\n"
        self.assertEqual(self.classes(fonte), [ILEGIVEL, ILEGIVEL])
        com_metadados = "from alembic import op\nimport sqlalchemy as sa\n\ndef upgrade():\n    sa.Table('x', sa.MetaData()).create(op.get_bind())\n"
        self.assertEqual(set(self.classes(com_metadados)), {ILEGIVEL})

    def test_f_string_sobre_constantes_de_modulo_le_se(self) -> None:
        """A forma da revisao 0002 do KAM-004: o SQL resolve-se, e e verificado."""
        fonte = (
            "from alembic import op\n\n"
            'TABELAS = {"tenants": ("id", "tipo"), "consent_log": ("id",)}\n\n'
            "def upgrade():\n"
            "    for tabela, colunas in TABELAS.items():\n"
            "        op.execute(f\"GRANT SELECT ({', '.join(colunas)}) ON platform.{tabela} TO kamba_app\")\n"
        )
        achados = self.achados(fonte)
        self.assertEqual([a.classe for a in achados], [VARIANTE])
        self.assertIn("`consent_log` →", achados[0].mensagem)

    def test_instrucao_desconhecida_e_sql_partido_falham(self) -> None:
        self.assertEqual(self.classes(migracao("CREATE FOREIGN TABLE platform.x (id uuid)")), [ILEGIVEL])
        self.assertEqual(self.classes(migracao("CREATE TABLE platform.tenants (id uuid, nome text DEFAULT 'abc)")), [ILEGIVEL])
        self.assertEqual(self.classes(migracao("DO $$ BEGIN CREATE ROLE kamba_inventado; END $$")), [ILEGIVEL])  # s57

    def test_python_invalido_falha(self) -> None:
        self.assertEqual(self.classes("def upgrade(:\n"), [ILEGIVEL])

    def test_ficheiro_sql(self) -> None:
        achados = self.achados("CREATE TABLE platform.consents (id uuid);\n", "db/migrations/x.sql")
        self.assertEqual([(a.classe, a.linha) for a in achados], [(VARIANTE, 1)])

    def test_contagem(self) -> None:
        _, contagem = ddl.verificar(
            "x.py",
            migracao("CREATE TABLE platform.tenants (id uuid, estado text CHECK (estado IN ('onboarding','ativo','restrito','suspenso','encerrado')));\nGRANT SELECT ON platform.tenants TO kamba_app"),
            self.saber,
        )
        self.assertEqual(
            (contagem.instrucoes, contagem.tabelas, contagem.colunas, contagem.valores), (2, 1, 2, 5)
        )


def schema(payload: dict | None = None, **topo) -> str:
    propriedades = {
        "id": {"type": "string"},
        "tipo": {"const": "payment.confirmed"},
        "versao": {"const": 1},
        "tenant_id": {"type": "string"},
        "payload": {"type": "object", "properties": payload or {"valor_minor": {"type": "integer"}}},
    }
    propriedades.update(topo)
    return json.dumps({"type": "object", "properties": {k: v for k, v in propriedades.items() if v is not None}})


class TestEventos(unittest.TestCase):
    FICHEIRO = "contratos/eventos/payment/confirmed/v1.schema.json"

    @classmethod
    def setUpClass(cls) -> None:
        cls.saber = saber()

    def achados(self, fonte: str, ficheiro: str | None = None):
        return eventos.verificar(ficheiro or self.FICHEIRO, fonte, self.saber)

    def classes(self, fonte: str, ficheiro: str | None = None) -> list[str]:
        return [a.classe for a in self.achados(fonte, ficheiro)]

    def test_schema_canonico_passa(self) -> None:
        self.assertEqual(self.classes(schema()), [])

    def test_variante_num_campo_do_payload_a_qualquer_profundidade(self) -> None:
        self.assertEqual(self.classes(schema({"valor_kz": {"type": "integer"}})), [VARIANTE])
        aninhado = {"autenticacao": {"type": "object", "properties": {"callback_hmac_ok": {"type": "boolean"}}}}
        self.assertIn(VARIANTE, self.classes(schema(aninhado)))
        em_lista = {"itens": {"type": "array", "items": {"type": "object", "properties": {"preco_kz": {}}}}}
        self.assertIn(VARIANTE, self.classes(schema(em_lista)))

    def test_variante_debaixo_de_qualquer_palavra_chave(self) -> None:
        """M7 (j04, j05, j06, j08, j18, j19, j24, j32): o nivel 1 le o documento inteiro."""
        for nome, corpo in (
            ("patternProperties", {"patternProperties": {"^valor_kz$": {"type": "integer"}}}),
            ("propertyNames", {"propertyNames": {"enum": ["valor_kz", "sig_ok"]}}),
            ("required", {"required": ["valor_kz"]}),
            ("enum", {"properties": {"valor_minor": {"items": {"enum": ["exato"]}}}}),
            ("prefixItems", {"prefixItems": [{"properties": {"valor_kz": {}}}]}),
            ("unevaluatedProperties", {"unevaluatedProperties": {"properties": {"valor_kz": {}}}}),
            ("dependentRequired", {"dependentRequired": {"valor_kz": ["sig_ok"]}}),
            ("dependencies", {"dependencies": {"valor_kz": {"properties": {"valor_minor": {}}}}}),
        ):
            with self.subTest(palavra=nome):
                fonte = json.dumps(
                    {"properties": {"tipo": {"const": "payment.confirmed"}, "versao": {"const": 1},
                                    "payload": {"type": "object", **corpo}}}
                )
                self.assertIn(VARIANTE, self.classes(fonte))

    def test_ref_interno_e_seguido(self) -> None:
        """M7 (j01): a forma idiomatica de JSON Schema escondia os campos do payload."""
        fonte = json.dumps(
            {
                "properties": {
                    "tipo": {"const": "payment.confirmed"},
                    "versao": {"$ref": "#/$defs/v1"},
                    "payload": {"$ref": "#/$defs/corpo"},
                },
                "$defs": {
                    "v1": {"const": 1},
                    "corpo": {"properties": {"campo_inventado": {}, "valor_minor": {}}, "required": ["montante_aoa"]},
                },
            }
        )
        achados = self.achados(fonte)
        self.assertEqual([a.classe for a in achados], [FORA, FORA])
        self.assertEqual(
            sorted(a.mensagem.split("`")[1] for a in achados),
            ["payment.confirmed.campo_inventado", "payment.confirmed.montante_aoa"],
        )

    def test_ref_interno_que_nao_aponta_para_nada_e_ciclo(self) -> None:
        partido = json.dumps({"properties": {"tipo": {"const": "payment.confirmed"}, "versao": {"const": 1}, "payload": {"$ref": "#/$defs/nao_ha"}}})
        self.assertEqual(self.classes(partido), [ILEGIVEL])
        ciclo = json.dumps(
            {"properties": {"tipo": {"const": "payment.confirmed"}, "versao": {"const": 1}, "payload": {"$ref": "#/$defs/a"}},
             "$defs": {"a": {"properties": {"valor_minor": {"$ref": "#/$defs/a"}}}}}
        )
        self.assertEqual(self.classes(ciclo), [])

    def test_pattern_properties_no_payload_e_ilegivel(self) -> None:
        fonte = schema({"valor_minor": {}}).replace('"payload": {', '"payload": {"patternProperties": {"^x_": {}}, ')
        self.assertEqual(self.classes(fonte), [ILEGIVEL])

    def test_campo_do_payload_fora_do_dicionario(self) -> None:
        achados = self.achados(schema({"cor_favorita": {"type": "string"}}))
        self.assertEqual([a.classe for a in achados], [FORA])
        self.assertIn("payment.confirmed.cor_favorita", achados[0].mensagem)

    def test_o_que_o_dicionario_escreve_com_maiusculas_nao_e_nome_de_campo(self) -> None:
        """M2: `SELECT`, `HMAC`, `ManualProvider` e `SecretRef` estao entre crases no §3
        e nao sao nomes de dados (mutacao M2a sobrevivia sem este teste)."""
        achados = self.achados(schema({"SELECT": {}, "HMAC": {}, "ManualProvider": {}, "SecretRef": {}}))
        self.assertEqual([a.classe for a in achados], [FORA] * 4)

    def test_campo_de_topo_fora_do_envelope(self) -> None:
        achados = self.achados(schema(gravado_em={"type": "string"}))
        self.assertEqual([a.classe for a in achados], [FORA])
        self.assertIn("envelope.gravado_em", achados[0].mensagem)

    def test_os_catorze_do_envelope_passam(self) -> None:
        """A emenda 1.11 (KAM-007) poe no envelope os seis do §6.1.

        Este teste existe porque o anterior usava `registado_em` como exemplo
        de campo de topo intruso, e deixou de o ser: a lista do dicionario
        cresceu de nove para catorze nomes. Um exemplo que envelhece em
        silencio e um teste que passa a provar outra coisa — aqui prova-se a
        lista inteira, que e o que importa, e o intruso passa a ser um nome
        que o dicionario nao tem em sitio nenhum.
        """
        topo = {
            nome: {"type": "string"}
            for nome in ("ocorrido_em", "registado_em", "produtor", "correlacao_id",
                         "causa_id", "trace_id", "classe_pii", "finalidades")
        }
        topo["agregado"] = {"type": "object", "properties": {
            "tipo": {"type": "string"}, "id": {"type": "string"}, "seq": {"type": "integer"}}}
        self.assertEqual(self.classes(schema(**topo)), [])

    def test_tipo_de_evento_tem_de_ser_um_evento_do_dicionario(self) -> None:
        self.assertEqual(self.classes(schema(tipo={"const": "pagamento.feito"})), [FORA])
        self.assertEqual(self.classes(schema(tipo={"const": "boolean"})), [FORA])  # j10
        self.assertEqual(self.classes(schema(tipo={"const": "tenants"})), [FORA])
        self.assertEqual(self.classes(schema(tipo={"enum": ["payment.confirmed", "payment.manual_confirmed"]})), [])
        self.assertEqual(self.classes(schema(tipo={"enum": ["payment.confirmed", "pagamento.feito"]})), [FORA])

    def test_tipo_livre_falha(self) -> None:
        self.assertEqual(self.classes(schema(tipo={"type": "string"})), [REGRA])
        self.assertEqual(self.classes(schema(tipo=None)), [REGRA])

    def test_versao_tem_de_estar_fixa_e_bater_com_o_nome_do_ficheiro(self) -> None:
        self.assertEqual(self.classes(schema(versao={"type": "integer"})), [REGRA])
        self.assertEqual(self.classes(schema(versao={"const": 2})), [REGRA])
        self.assertEqual(self.classes(schema(versao={"enum": [1, 2]})), [REGRA])
        self.assertEqual(self.classes(schema(versao={"const": True})), [REGRA], "j12: True == 1 em Python")
        self.assertEqual(self.classes(schema(versao={"const": "1"})), [REGRA])
        self.assertEqual(
            self.classes(schema(versao={"const": 2}), "contratos/eventos/payment/confirmed/v2.schema.json"), []
        )

    def test_o_nome_do_ficheiro_tem_de_dizer_a_versao(self) -> None:
        """M7 (j14, j15): outro nome dispensava o `tipo` e a `versao` fixos."""
        livre = schema(tipo={"type": "string"}, versao={"type": "integer"})
        for nome in ("V1.schema.json", "payment.confirmed.v1.schema.json", "v01.schema.json", "envelope.schema.json"):
            with self.subTest(nome=nome):
                achados = self.achados(livre, f"contratos/eventos/payment/{nome}")
                self.assertEqual([a.classe for a in achados], [REGRA])
                self.assertIn("chama-se `v<N>.schema.json`", achados[0].mensagem)

    def test_chave_repetida(self) -> None:
        """M7 (j40): o JSON fica com a ultima, e a primeira nao era lida."""
        fonte = '{"properties": {"payload": {"properties": {"valor_kz": {}}}}, "properties": {"tipo": {"const": "order.created"}, "versao": {"const": 1}}}'
        achados = self.achados(fonte)
        self.assertEqual([a.classe for a in achados], [ILEGIVEL])
        self.assertIn("repetida", achados[0].mensagem)

    def test_propriedades_por_allof_e_defs(self) -> None:
        fonte = json.dumps(
            {
                "allOf": [
                    {"properties": {"tipo": {"const": "order.created"}, "versao": {"const": 1}}},
                    {"properties": {"payload": {"$ref": "#/$defs/p"}}},
                ],
                "$defs": {"p": {"properties": {"total_kz": {"type": "integer"}}}},
            }
        )
        self.assertEqual(self.classes(fonte), [VARIANTE])

    def test_json_invalido_falha(self) -> None:
        self.assertEqual(self.classes("{ nao e json"), [ILEGIVEL])
        self.assertEqual(self.classes("[1, 2]"), [ILEGIVEL])


SERVICOS = """\
id: servicos
version: 1.0.0
phase: P
persona: { nome: "Rececionista", idioma: pt }
graph: kamba.verticals.servicos:build_graph
entitlements: { modulo: servicos, limites: [msgs_ai_mes, marcacoes_mes] }
subscriptions:
  - { tipo: booking.created,          versao: 1 }
  - { tipo: payment.confirmed,        versao: 1 }
  - { tipo: payment.manual_confirmed, versao: 1 }
"""


class TestRegisto(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.saber = saber()

    def achados(self, fonte: str):
        return registo.verificar("registry/servicos.yaml", fonte, self.saber)

    def classes(self, fonte: str) -> list[str]:
        return [a.classe for a in self.achados(fonte)]

    def test_ficheiro_canonico_passa(self) -> None:
        self.assertEqual(self.classes(SERVICOS), [])

    def test_o_exemplo_do_doc_02_seria_recusado_pelo_limite(self) -> None:
        """A terceira divergencia que o KAM-003 deixou registada."""
        fonte = SERVICOS.replace("id: servicos", "id: vendedor").replace(
            "limites: [msgs_ai_mes, marcacoes_mes]", "limites: [msgs_ai_mes, valor_max_pedido_kz]"
        ).replace("modulo: servicos", "modulo: vendedor")
        achados = self.achados(fonte)
        self.assertEqual([a.classe for a in achados], [VARIANTE])
        self.assertIn("`valor_max_pedido_kz` →", achados[0].mensagem)
        self.assertIn("valor_max_pedido_minor", achados[0].mensagem)

    def test_variante_numa_chave_e_dentro_de_um_texto(self) -> None:
        self.assertIn(VARIANTE, self.classes(SERVICOS + "guardrails: { sig_ok: true }\n"))
        self.assertIn(VARIANTE, self.classes(SERVICOS + 'golden: { nota: "le de consent_ledger por contacto" }\n'))

    def test_chave_de_topo_desconhecida_falha(self) -> None:
        """M8 (r08, r09): uma chave com outro nome passava o ficheiro ao lado das verificacoes."""
        for extra in (
            "subscricoes:\n  - { tipo: pagamento.inventado }\n",
            "ferramentas: [tool_inventada]\n",
            "limites: [limite_inventado]\n",
            "events: { subscriptions: [ { tipo: x.y } ] }\n",
        ):
            with self.subTest(extra=extra):
                achados = self.achados(SERVICOS + extra)
                self.assertEqual([a.classe for a in achados], [ILEGIVEL])
                self.assertIn("desconhecida no topo do ficheiro", achados[0].mensagem)
        self.assertEqual(
            self.classes(SERVICOS.replace("modulo: servicos,", "modulo: servicos, extra: 1,")), [ILEGIVEL]
        )
        self.assertEqual(
            self.classes(SERVICOS.replace("{ tipo: booking.created,          versao: 1 }", "{ tipo: booking.created, canal: x }")),
            [ILEGIVEL],
        )

    def test_o_nome_do_provider_nao_e_uma_chave_de_limite(self) -> None:
        """O exportador colhe todos os nomes entre crases da linha «Entitlement
        (chaves)», e ela escreve `ManualProvider` em prosa. Antes do KAM-009
        isso fazia de `ManualProvider` uma chave de `limites` aceite — e a
        coluna `tenant_usage.chave_limite` recusa-a pelo `CHECK` de forma."""
        self.assertEqual(self.classes(SERVICOS.replace("marcacoes_mes]", "ManualProvider]")), [FORA])

    def test_id_modulo_e_limite_fora_do_dicionario(self) -> None:
        self.assertEqual(self.classes(SERVICOS.replace("id: servicos", "id: assistente")), [FORA])
        self.assertEqual(self.classes(SERVICOS.replace("modulo: servicos", "modulo: xpto")), [FORA])
        self.assertEqual(self.classes(SERVICOS.replace("marcacoes_mes]", "pedidos_mes]")), [FORA])
        self.assertEqual(self.classes(SERVICOS.replace("modulo: servicos", "modulo: foto")), [])

    def test_subscricao_a_evento_fora_do_dicionario(self) -> None:
        self.assertEqual(self.classes(SERVICOS.replace("booking.created", "booking.feita")), [FORA])
        self.assertEqual(self.classes(SERVICOS.replace("booking.created", "tenants.tipo")), [FORA], "M2: nao e evento")

    def test_um_evento_de_pagamento_sem_o_outro(self) -> None:
        sem_manual = SERVICOS.replace("  - { tipo: payment.manual_confirmed, versao: 1 }\n", "")
        sem_facilitador = SERVICOS.replace("  - { tipo: payment.confirmed,        versao: 1 }\n", "")
        nenhum = sem_manual.replace("  - { tipo: payment.confirmed,        versao: 1 }\n", "")
        self.assertEqual(self.classes(sem_manual), [REGRA])
        self.assertEqual(self.classes(sem_facilitador), [REGRA])
        self.assertEqual(self.classes(nenhum), [], "quem nao subscreve pagamentos nao tem de subscrever os dois")

    def test_identificador_de_confirmacao_por_vertical(self) -> None:
        def com(vertical: str, botao: str) -> list[str]:
            fonte = SERVICOS.replace("id: servicos", f"id: {vertical}")
            return self.classes(fonte + f'guardrails: {{ confirmacao: "{botao}" }}\n')

        self.assertEqual(com("servicos", "confirm:{hold_id}"), [])
        self.assertEqual(com("servicos", "confirm:{cart_id}"), [REGRA])
        self.assertEqual(com("vendedor", "confirm:{cart_id}"), [])
        self.assertEqual(com("vendedor", "confirm:{hold_id}"), [REGRA])
        self.assertEqual(com("catalogo", "confirm:{item_id}"), [])
        self.assertEqual(com("catalogo", "confirm:{cart_id}"), [REGRA], "r18: o Vendedor nao empresta o identificador")

    def test_formas_erradas_do_identificador_de_confirmacao(self) -> None:
        """M8 (r17): nao batiam no padrao certo e por isso passavam."""
        for forma in ("confirm:{{cart_id}}", "confirm:<hold_id>", "confirm:hold_id", "confirm:{coisa_id}"):
            with self.subTest(forma=forma):
                self.assertEqual(self.classes(SERVICOS + f'guardrails: {{ confirmacao: "{forma}" }}\n'), [REGRA])

    def test_tools_e_parametros(self) -> None:
        self.assertEqual(self.classes(SERVICOS + "tools: [enhance_image]\n"), [])
        # `book_slot` esteve aqui como a tool fora do dicionario, e deixou de o
        # ser: a emenda 1.35 (KAM-027) poe as onze tools do catalogo do §6.2 no
        # dicionario. A negativa passa a ser a tool que o §6.2 diz que **nao
        # existe**: «Nao existe tool de envio de mensagem: o unico caminho para
        # o cliente e o no `send`».
        self.assertEqual(self.classes(SERVICOS + "tools: [book_slot]\n"), [])
        self.assertEqual(self.classes(SERVICOS + "tools: [enviar_mensagem]\n"), [FORA])
        com_parametros = SERVICOS + "tools:\n  - nome: enhance_image\n    parametros:\n      contact_id: uuid\n      cor_favorita: text\n"
        achados = self.achados(com_parametros)
        self.assertEqual([a.classe for a in achados], [FORA])
        self.assertIn("enhance_image.cor_favorita", achados[0].mensagem)
        self.assertEqual(self.classes(SERVICOS + "tools:\n  - { descricao: sem nome }\n"), [ILEGIVEL])
        # r11, r12: parametros numa chave que o lint nao le
        for chave in ("input_schema: { properties: { cor_favorita: {} } }", "parameters: { cor_favorita: text }"):
            with self.subTest(chave=chave):
                achados = self.achados(SERVICOS + f"tools:\n  - nome: enhance_image\n    {chave}\n")
                self.assertEqual([a.classe for a in achados], [ILEGIVEL])
                self.assertIn("na tool `enhance_image`", achados[0].mensagem)

    def test_so_uma_tool_do_dicionario_e_tool(self) -> None:
        """M2 (r13): um papel, um tipo SQL ou uma tabela nao servem de tool."""
        achados = self.achados(SERVICOS + "tools: [kamba_migrator, tenants, payment, contact_id]\n")
        self.assertEqual([a.classe for a in achados], [FORA] * 4)

    def test_yaml_que_nao_se_le_falha(self) -> None:
        for fonte in ("id: &a servicos\n", "id: servicos\nnota: |\n  texto\n", "- a\n- b\n", "id: [a, b\n"):
            with self.subTest(fonte=fonte):
                self.assertEqual(self.classes(fonte), [ILEGIVEL])


#: A segunda forma da superficie 3 (KAM-009). O ficheiro real e
#: `registry/plans.yaml`; esta e a forma minima, para as mutacoes.
PLANOS = """\
version: 1.0.0
plans:
  free:
    estado: hipotese_nao_validada
    nota: "o plano do DEFAULT da coluna"
    entitlements:
      - modulo: vendedor
        ativo: true
        limites: { msgs_ai_mes: 1000, manual_max_minor: 5000000 }
"""


class TestPlanos(unittest.TestCase):
    """A forma `plans` — e uma negativa por regra.

    Sem uma negativa por regra, o gate herda o buraco que o `plans.yaml` tinha
    antes de existir: um ficheiro que nenhuma verificacao lia.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.saber = saber()

    def achados(self, fonte: str, ficheiro: str = "registry/plans.yaml"):
        return registo.verificar(ficheiro, fonte, self.saber)

    def classes(self, fonte: str) -> list[str]:
        return [a.classe for a in self.achados(fonte)]

    def unico(self, fonte: str, classe: str, trecho: str):
        achados = self.achados(fonte)
        self.assertEqual([a.classe for a in achados], [classe], [str(a) for a in achados])
        self.assertIn(trecho, achados[0].mensagem)
        return achados[0]

    # --- o ficheiro real e a forma minima -----------------------------------------
    def test_o_ficheiro_real_do_repositorio_passa(self) -> None:
        from .base import ROOT

        fonte = (ROOT / "registry/plans.yaml").read_text(encoding="utf-8")
        achados = registo.verificar("registry/plans.yaml", fonte, self.saber)
        self.assertEqual([str(a) for a in achados], [])

    def test_a_forma_minima_passa(self) -> None:
        self.assertEqual(self.classes(PLANOS), [])

    def test_a_forma_nao_vem_do_nome_do_ficheiro(self) -> None:
        """O discriminante e a chave `plans`, e nao o nome: o mesmo conteudo
        passa com qualquer nome, e um `plans.yaml` com forma de vertical e lido
        como vertical."""
        self.assertEqual(self.classes(PLANOS), [])
        self.assertEqual([a.classe for a in registo.verificar("registry/tarifas.yaml", PLANOS, self.saber)], [])
        self.assertEqual([a.classe for a in registo.verificar("registry/plans.yaml", SERVICOS, self.saber)], [])

    # --- regra: o limite e confrontado com as dez chaves do dicionario -------------
    def test_limite_que_o_dicionario_nao_tem(self) -> None:
        """A regra que torna o ficheiro util, e a mesma que `entitlements.limites[]` ja tinha."""
        self.unico(PLANOS.replace("msgs_ai_mes", "mensagens_mes"), FORA, "`mensagens_mes`")
        self.unico(PLANOS.replace("msgs_ai_mes", "manual_max_por_contacto"), FORA, "dicionário §3.2")

    def test_limite_que_e_uma_variante_do_dicionario(self) -> None:
        achados = self.achados(PLANOS.replace("manual_max_minor", "valor_max_pedido_kz"))
        self.assertEqual([a.classe for a in achados], [VARIANTE], [str(a) for a in achados])
        self.assertIn("valor_max_pedido_minor", achados[0].mensagem)

    def test_as_dez_chaves_do_dicionario_passam(self) -> None:
        dez = (
            "msgs_ai_mes: 1, marcacoes_mes: 1, imagens_mes: 1, posts_mes: 1, orcamentos_mes: 1, "
            "valor_max_pedido_minor: 1, manual_max_minor: 1, manual_dupla_acima_minor: 1, "
            "manual_daily_max_minor: 1, manual_max_por_contacto_24h: 1"
        )
        fonte = PLANOS.replace("msgs_ai_mes: 1000, manual_max_minor: 5000000", dez)
        self.assertEqual(self.classes(fonte), [])

    # --- regra: listas fechadas de chaves ------------------------------------------
    def test_chave_de_topo_desconhecida_falha(self) -> None:
        self.unico(PLANOS + "precos: {}\n", ILEGIVEL, "desconhecida no topo do ficheiro de planos")
        self.unico(PLANOS + "tools: [enhance_image]\n", ILEGIVEL, "no topo do ficheiro de planos")

    def test_chave_desconhecida_num_plano_falha(self) -> None:
        fonte = PLANOS.replace("    estado:", "    preco_mensal_minor: 500000\n    estado:")
        self.unico(fonte, ILEGIVEL, "desconhecida no plano `free`")

    def test_chave_desconhecida_num_entitlement_falha(self) -> None:
        fonte = PLANOS.replace("        ativo: true\n", "        ativo: true\n        limits: {}\n")
        self.unico(fonte, ILEGIVEL, "desconhecida num entitlement no plano `free`")

    # --- regra: `estado` ------------------------------------------------------------
    def test_estado_em_falta_num_plano(self) -> None:
        fonte = PLANOS.replace("    estado: hipotese_nao_validada\n", "")
        self.unico(fonte, REGRA, "nao declara `estado`")

    def test_estado_que_o_canon_nao_escreve(self) -> None:
        self.unico(PLANOS.replace("hipotese_nao_validada", "validado"), REGRA, "`estado: validado`")

    # --- regra: `modulo` -------------------------------------------------------------
    def test_modulo_fora_do_dicionario(self) -> None:
        self.unico(PLANOS.replace("modulo: vendedor", "modulo: xpto"), FORA, "`modulo`")
        self.assertEqual(self.classes(PLANOS.replace("modulo: vendedor", "modulo: foto")), [])

    def test_entitlement_sem_modulo(self) -> None:
        fonte = PLANOS.replace("      - modulo: vendedor\n        ativo: true\n", "      - ativo: true\n")
        self.unico(fonte, REGRA, "sem `modulo`")

    # --- regra: a forma dos valores ---------------------------------------------------
    def test_valor_de_limite_que_nao_e_inteiro_nao_negativo(self) -> None:
        for valor in ("'mil'", "-1", "true"):
            with self.subTest(valor=valor):
                fonte = PLANOS.replace("msgs_ai_mes: 1000", f"msgs_ai_mes: {valor}")
                self.unico(fonte, ILEGIVEL, "inteiro nao negativo")

    def test_ativo_que_nao_e_booleano(self) -> None:
        self.unico(PLANOS.replace("ativo: true", "ativo: sim"), ILEGIVEL, "`ativo`")

    def test_plano_sem_entitlements(self) -> None:
        fonte = PLANOS.replace(
            "    entitlements:\n      - modulo: vendedor\n        ativo: true\n"
            "        limites: { msgs_ai_mes: 1000, manual_max_minor: 5000000 }\n",
            "",
        )
        self.unico(fonte, ILEGIVEL, "lista `entitlements`")

    def test_entitlement_sem_limites(self) -> None:
        fonte = PLANOS.replace("        limites: { msgs_ai_mes: 1000, manual_max_minor: 5000000 }\n", "")
        self.unico(fonte, ILEGIVEL, "mapa `chave: valor`")

    def test_plans_que_nao_e_um_mapa_de_planos(self) -> None:
        self.unico("version: 1.0.0\nplans: []\n", ILEGIVEL, "pelo menos um plano")
        self.unico("plans:\n  free: nenhum\n", ILEGIVEL, "nao e um mapa")

    # --- regra: nem uma forma nem a outra ---------------------------------------------
    def test_um_ficheiro_que_nao_e_nenhuma_das_formas_falha(self) -> None:
        """A regra que fechou o buraco: antes, so a forma da vertical existia."""
        achado = self.unico('version: 1.0.0\nnota: "tabela de precos"\n', REGRA, "sem `id`")
        self.assertIn("sem `plans`", achado.mensagem)
        self.unico("version: 1.0.0\n", REGRA, "nao e nenhuma delas")

    def test_as_duas_formas_no_mesmo_ficheiro_falham(self) -> None:
        self.unico(PLANOS + "id: vendedor\n", REGRA, "nao se misturam")

    # --- o nivel 1 continua a valer -----------------------------------------------------
    def test_nivel_1_em_qualquer_chave_ou_texto_de_um_plano(self) -> None:
        self.assertIn(VARIANTE, self.classes(PLANOS.replace("do DEFAULT da coluna", "le de consent_ledger")))
        self.assertIn(VARIANTE, self.classes(PLANOS.replace("  free:", "  consent_log:")))

    def test_yaml_que_nao_se_le_falha(self) -> None:
        self.assertEqual(self.classes("plans: &a\n"), [ILEGIVEL])


class TestRegistoDeChaves(unittest.TestCase):
    """`registry/entitlement_keys.schema.json` contra o dicionario §3.2.

    O ficheiro esta em `fora_de_ambito` (bate na sentinela `*.schema.json` e
    nao e um schema de evento), e sem este teste as dez chaves nao eram
    confrontadas com nada — era o buraco que a entrada da politica abria.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from .base import ROOT

        cls.saber = saber()
        cls.schema = json.loads((ROOT / "registry/entitlement_keys.schema.json").read_text(encoding="utf-8"))

    def test_as_chaves_sao_exactamente_as_do_dicionario(self) -> None:
        self.assertEqual(
            sorted(self.schema["properties"]),
            sorted(registo.chaves_de_limite(self.saber.politica)),
        )
        self.assertEqual(len(self.schema["properties"]), 10, "a emenda 1.17 pos as chaves em dez")

    def test_uma_chave_desconhecida_e_rejeitada_na_escrita(self) -> None:
        """Criterio 1 do bloco do KAM-009, no proprio schema."""
        self.assertIs(self.schema["additionalProperties"], False)

    def test_cada_chave_declara_o_que_e(self) -> None:
        categorias = set(self.schema["x-kamba-categorias"])
        self.assertEqual(
            categorias, {"contador_por_periodo", "tecto_por_pedido", "tecto_por_janela"}
        )
        for nome, chave in self.schema["properties"].items():
            with self.subTest(chave=nome):
                self.assertIn(chave["x-kamba-categoria"], categorias)
                self.assertIn(chave["x-kamba-unidade"], ("minor", "contagem"))
                self.assertTrue(chave["x-kamba-fonte"])

    def test_so_um_contador_por_periodo_e_consumivel(self) -> None:
        """Consumir um tecto por pedido seria um defeito: `platform.ten_consumir`
        acumula contra o periodo, e um tecto por pedido nao acumula."""
        for nome, chave in self.schema["properties"].items():
            with self.subTest(chave=nome):
                self.assertEqual(
                    chave["x-kamba-consumivel"],
                    chave["x-kamba-categoria"] == "contador_por_periodo",
                )

    def test_o_que_e_dinheiro_acaba_em_minor(self) -> None:
        """`docs/tecnica/03` §5.1 n.o 2 e a convencao de nomes do conjunto."""
        for nome, chave in self.schema["properties"].items():
            with self.subTest(chave=nome):
                self.assertEqual(chave["x-kamba-unidade"] == "minor", nome.endswith("_minor"))
                if nome.endswith("_minor"):
                    self.assertEqual(chave["x-kamba-moeda"], "AOA")

    def test_os_limites_do_plans_yaml_sao_chaves_deste_registo(self) -> None:
        from .base import ROOT

        documento = yamlreg.ler((ROOT / "registry/plans.yaml").read_text(encoding="utf-8"))
        usados = {
            chave
            for plano in documento["plans"].values()
            for entitlement in plano["entitlements"]
            for chave in entitlement["limites"]
        }
        self.assertTrue(usados)
        self.assertLessEqual(usados, set(self.schema["properties"]))


GATES = """\
version: 1.0.0
gates:
  vendedor:
    golden: golden/vendedor/v1
    validacoes:
      tools: { modo: aviso, credor: KAM-028 }
      grafo: { modo: aviso, credor: KAM-031 }
      golden: { modo: aviso, credor: KAM-040 }
"""


class TestGates(unittest.TestCase):
    """A forma `gates` (KAM-027) — e uma negativa por regra.

    A razao e a que o `TestPlanos` escreveu para a segunda forma: sem uma
    negativa por regra, o gate herda o buraco que o ficheiro tinha antes de
    existir — um ficheiro que nenhuma verificacao lia.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.saber = saber()

    def achados(self, fonte: str, ficheiro: str = "registry/gates.yaml"):
        return registo.verificar(ficheiro, fonte, self.saber)

    def classes(self, fonte: str) -> list[str]:
        return [a.classe for a in self.achados(fonte)]

    def test_ficheiro_canonico_passa(self) -> None:
        self.assertEqual(self.classes(GATES), [])

    def test_a_chave_de_um_gate_e_uma_vertical(self) -> None:
        self.assertEqual(self.classes(GATES.replace("  vendedor:", "  assistente:")), [FORA])
        self.assertEqual(self.classes(GATES.replace("  vendedor:", "  servicos:")), [])

    def test_validacao_fora_das_seis_falha(self) -> None:
        """Um `tool` por `tools` desligava a validacao em silencio."""
        achados = self.achados(GATES.replace("      tools: {", "      tool: {"))
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("nao e uma das seis validacoes", achados[0].mensagem)
        self.assertEqual(self.classes(GATES.replace("      tools: {", "      fase: {")), [])

    def test_modo_fora_dos_dois_falha(self) -> None:
        """O `docs/tecnica/02` §5.1 escreve `warn`, que e o nome antigo.

        E e por isso que o `warn` nao se registou como variante do dicionario
        (emenda 1.35): e uma palavra inglesa corrente, e quem a recusa e esta
        lista fechada — aqui, onde ela significa um modo de validacao.
        """
        for errado in ("warn", "block", "Aviso", "sim"):
            with self.subTest(modo=errado):
                achados = self.achados(
                    GATES.replace("modo: aviso, credor: KAM-028", f"modo: {errado}, credor: KAM-028")
                )
                self.assertEqual([a.classe for a in achados], [REGRA])
                self.assertIn(f"`modo: {errado}`", achados[0].mensagem)
        self.assertEqual(
            self.classes(GATES.replace("tools: { modo: aviso, credor: KAM-028 }", "tools: { modo: bloqueio }")),
            [],
        )

    def test_aviso_sem_credor_falha_e_bloqueio_com_credor_tambem(self) -> None:
        achados = self.achados(GATES.replace("{ modo: aviso, credor: KAM-028 }", "{ modo: aviso }"))
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("sem `credor`", achados[0].mensagem)
        for credor in ("KAM-28", "kam-028", "o KAM-028", "em breve"):
            with self.subTest(credor=credor):
                self.assertEqual(
                    self.classes(GATES.replace("credor: KAM-028", f'credor: "{credor}"')), [REGRA]
                )
        sobra = self.achados(
            GATES.replace("tools: { modo: aviso, credor: KAM-028 }", "tools: { modo: bloqueio, credor: KAM-028 }")
        )
        self.assertEqual([a.classe for a in sobra], [REGRA])
        self.assertIn("o credor e de quem espera", sobra[0].mensagem)

    def test_chave_desconhecida_no_topo_no_gate_e_na_validacao(self) -> None:
        self.assertEqual(self.classes(GATES + "golden_gate: warn\n"), [ILEGIVEL])
        # `dataset:` em vez de `golden:` da **dois** achados, e os dois contam:
        # a chave que o lint nao conhece, e o `golden` que passou a faltar.
        self.assertEqual(
            self.classes(
                GATES.replace("    golden: golden/vendedor/v1", "    dataset: golden/vendedor/v1")
            ),
            [ILEGIVEL, REGRA],
        )
        self.assertEqual(self.classes(GATES.replace("{ modo: aviso, credor: KAM-028 }", "{ modo: aviso, credor: KAM-028, nota: x }")), [ILEGIVEL])

    def test_um_gate_sem_golden_falha_antes_de_producao(self) -> None:
        """O `GateDaVertical` do AGR exige-o, e sem isto o CI ficava verde.

        O `load_all` confronta o `golden` do gate com o `golden.dataset` da
        vertical; um `gates.yaml` sem ele passava aqui e o AGR saia com 5 em
        producao. Achado da revisao adversarial do KAM-027.
        """
        sem_golden = "version: 1.0.0\ngates:\n  vendedor:\n    validacoes:\n      tools: { modo: aviso, credor: KAM-028 }\n"
        achados = self.achados(sem_golden)
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("nao declara `golden`", achados[0].mensagem)
        self.assertEqual(
            self.classes(GATES.replace("    golden: golden/vendedor/v1", '    golden: ""')),
            [REGRA],
        )

    def test_gate_sem_validacoes_falha(self) -> None:
        """`bloqueio` e a omissao: quem nao tem nada a declarar nao se escreve."""
        so_golden = "version: 1.0.0\ngates:\n  vendedor:\n    golden: golden/vendedor/v1\n"
        achados = self.achados(so_golden)
        self.assertEqual([a.classe for a in achados], [ILEGIVEL])
        self.assertIn("nao tem um mapa `validacoes`", achados[0].mensagem)
        self.assertEqual(self.classes("version: 1.0.0\ngates: {}\n"), [ILEGIVEL])

    def test_as_tres_formas_nao_se_misturam(self) -> None:
        achados = self.achados(GATES + "id: vendedor\n")
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("nao se misturam", achados[0].mensagem)
        self.assertEqual([a.classe for a in self.achados(GATES + "plans: {}\n")], [REGRA])

    def test_um_ficheiro_que_nao_e_nenhuma_das_tres_falha(self) -> None:
        achados = self.achados("version: 1.0.0\ngate: { vendedor: aviso }\n")
        self.assertEqual([a.classe for a in achados], [REGRA])
        self.assertIn("`gates`", achados[0].mensagem)

    def test_o_ficheiro_do_repositorio_cobre_as_validacoes_adiadas(self) -> None:
        """O que o critero 8 do KAM-027 manda registar aqui, e a outra.

        E o unico teste desta classe que le o ficheiro real: as seis validacoes
        correm em `bloqueio` por omissao, e as que nao correm tem de estar aqui
        **com o credor nomeado** — senao ficam `bloqueio` no codigo e `aviso` na
        cabeca de quem escreveu o ticket.

        **Eram tres e passaram a duas com o KAM-028**, e o nome deste teste
        deixou de levar o numero pela razao que o KAM-027 escreveu para as
        listas literais: a invariante e «as adiadas estao aqui com credor», nao
        «as adiadas sao tres». A `tools` saiu porque o catalogo da ToolLayer
        existe e a validacao (1) passou a `bloqueio` — e fechar um `aviso` e
        **apagar a linha**, que e o que este ficheiro descreve.
        """
        from .base import ROOT

        documento = yamlreg.ler((ROOT / "registry/gates.yaml").read_text(encoding="utf-8"))
        self.assertEqual(sorted(documento["gates"]), ["servicos", "vendedor"])
        for vertical, grafo in (("vendedor", "KAM-031"), ("servicos", "KAM-035")):
            validacoes = documento["gates"][vertical]["validacoes"]
            self.assertEqual(sorted(validacoes), ["golden", "grafo"])
            self.assertEqual({v["modo"] for v in validacoes.values()}, {"aviso"})
            self.assertNotIn(
                "tools",
                validacoes,
                "a validacao (1) fechou com o KAM-028; um `aviso` que sobreviva "
                "ao credor e erro de arranque",
            )
            self.assertEqual(validacoes["grafo"]["credor"], grafo)
            self.assertEqual(validacoes["golden"]["credor"], "KAM-040")


class TestYamlDoRegisto(unittest.TestCase):
    def test_os_dois_exemplos_do_doc_02_leem_se(self) -> None:
        """`docs/tecnica/02` §5.1 e a forma dos ficheiros que vao existir."""
        import re

        from .base import ROOT

        texto = (ROOT / "docs/tecnica/02_Agent_Runtime_Verticais.md").read_text(encoding="utf-8")
        blocos = [b for b in re.findall(r"```yaml\n(.*?)```", texto, re.S) if b.startswith("# registry/")]
        self.assertEqual(len(blocos), 2)
        lidos = [yamlreg.ler(b) for b in blocos]
        self.assertEqual([d["id"] for d in lidos], ["vendedor", "servicos"])
        self.assertEqual(lidos[0]["subscriptions"][0], {"tipo": "payment.confirmed", "versao": 1})
        self.assertEqual(lidos[1]["entitlements"], {"modulo": "servicos", "limites": ["msgs_ai_mes", "marcacoes_mes"]})
        self.assertLessEqual(set(lidos[0]), registo.CHAVES_DE_TOPO, "a lista fechada cobre o exemplo do desenho")
        self.assertLessEqual(set(lidos[1]), registo.CHAVES_DE_TOPO)

    def test_bloco_e_fluxo(self) -> None:
        documento = yamlreg.ler(
            "a: 1\nb: 'dois: tres'   # comentario\nc:\n  - x\n  - d: 1\n    e: [1, {f: g}]\nh:\n- i\nj: {}\nk: []\n"
        )
        self.assertEqual(
            documento,
            {"a": 1, "b": "dois: tres", "c": ["x", {"d": 1, "e": [1, {"f": "g"}]}], "h": ["i"], "j": {}, "k": []},
        )

    def test_o_que_recusa(self) -> None:
        for texto in (
            "a: 1\na: 2\n", "a:\n\tb: 1\n", "a: *b\n", "a: !!str b\n", "a: >\n  b\n", "---\na: 1\n",
            "a: {b: 1\n", "a: [1, 2] sobra\n", "a: {b: 1, b: 2}\n", "  a: 1\n", "a: 1\n   b: 2\n",
        ):
            with self.subTest(texto=texto), self.assertRaises(yamlreg.YamlIlegivel):
                yamlreg.ler(texto)

    def test_documento_vazio(self) -> None:
        self.assertIsNone(yamlreg.ler("# so um comentario\n"))


if __name__ == "__main__":
    unittest.main()
