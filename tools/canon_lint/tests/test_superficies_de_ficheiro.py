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
        self.assertIn("`valor_kz` → `valor_minor`, dicionário §3.4", achados[0].mensagem)
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
        self.assertEqual(self.classes(migracao(base.format("'hmac','hmac_sha256'"))), [REGRA])

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
        self.assertEqual(self.classes(SERVICOS + "tools: [book_slot]\n"), [FORA])
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
