"""Gate 8: o inventario fechado de colunas de `platform`.

Cada coluna do schema esta aqui com o tipo, a nulidade e a omissao. Uma coluna
nova, ou uma coluna que mude, faz este teste falhar ate alguem a declarar — e e
esse o proposito, por duas razoes que a revisao adversarial mostrou:

**Telefone em claro.** O criterio de aceitacao 5 procurava `msisdn`, `telefone`
e `phone` no **nome** da coluna. Uma `contacto_dono text` ou uma
`whatsapp_cliente text` passavam. Uma lista de fragmentos proibidos nunca fecha;
uma lista de colunas permitidas fecha: quem acrescentar uma coluna de texto tem
de a escrever aqui, e ao escreve-la responde a pergunta «isto guarda dados
pessoais?» na coluna `pessoal`.

**NOT NULL e omissoes.** Retirar o `NOT NULL` a treze colunas, ou trocar a
omissao de `origem` para `plataforma`, deixava a suite verde.

O que isto **nao** garante, e nenhum schema garante: que ninguem grave um
telefone em `nome` ou em `zona`. Isso e do validador de entrada e do KAM-068.
"""

from __future__ import annotations

from tests.base import ComBase

SIM, NAO = "YES", "NO"

#: tabela -> coluna -> (tipo, anulavel, omissao, guarda dados pessoais?)
#:
#: `pessoal`: `nao`, ou a razao pela qual e aceitavel. Nenhuma coluna aqui guarda
#: telefone, BSUID ou nome de pessoa singular em claro.
INVENTARIO = {
    "tenants": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tipo": ("text", NAO, None, "nao"),
        "nome": ("text", NAO, None, "nome do negocio, nao de pessoa singular"),
        "nif": ("text", SIM, None, "identificador fiscal do negocio"),
        "contacto_negocio_enc": ("bytea", SIM, None, "cifrado em aplicacao (ADR-010)"),
        "owner_contact_id": ("uuid", SIM, None, "referencia opaca a contacts (KAM-008)"),
        "zona": ("text", SIM, None, "zona do negocio"),
        "plus_code": ("text", SIM, None, "localizacao do negocio"),
        "plano": ("text", NAO, "'free'::text", "nao"),
        "estado": ("text", NAO, "'onboarding'::text", "nao"),
        "medusa_sales_channel_id": ("text", SIM, None, "nao"),
        "medusa_merchant_id": ("text", SIM, None, "nao"),
        "chatwoot_account_id": ("integer", SIM, None, "nao"),
        "litellm_key_id": ("text", SIM, None, "identificador da chave, nao a chave"),
        "fuso_horario": ("text", NAO, "'Africa/Luanda'::text", "nao"),
        "verificado_at": ("timestamp with time zone", SIM, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "deleted_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "tenant_channels": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "waba_id": ("text", NAO, None, "identificador da conta na Meta"),
        "waac_id": ("text", SIM, None, "identificador da conta na Meta"),
        "phone_number_id": ("text", NAO, None, "identificador opaco da Meta; nao e um telefone"),
        "channel_mode": ("text", NAO, None, "nao"),
        "vertical": ("text", NAO, None, "nao"),
        "origem": ("text", NAO, "'pme'::text", "nao"),
        "estado": ("text", NAO, "'pendente'::text", "nao"),
        "token_ref": ("text", NAO, None, "referencia opaca ao segredo; nunca o token"),
        "quality_rating": ("text", SIM, None, "nao"),
        "messaging_limit": ("text", SIM, None, "nao"),
        "free_tier_used": ("integer", NAO, "0", "nao"),
        "free_tier_month": ("date", SIM, None, "nao"),
        "coexistence_synced_at": ("timestamp with time zone", SIM, None, "nao"),
        "last_account_update_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "entitlements": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "modulo": ("text", NAO, None, "nao"),
        "limites": ("jsonb", NAO, "'{}'::jsonb", "nao"),
        "ativo": ("boolean", NAO, "true", "nao"),
    },
    # ------------------------------------------------------------ KAM-008
    # Identidade de contacto. Aqui a pergunta «guarda dados pessoais?» tem
    # resposta afirmativa em varias linhas, e cada uma diz **em que forma**:
    # nenhuma guarda BSUID nem telefone em claro.
    "contacts": {
        "contact_id": ("uuid", NAO, "gen_random_uuid()", "identificador aleatorio; nunca derivado do telefone (ADR-010)"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "phone_hmac": ("bytea", SIM, None, "pseudonimo do telefone: HMAC-SHA256 com segredo do cofre; continua dado pessoal"),
        "hmac_kid": ("text", SIM, None, "versao do segredo do HMAC; nao e o segredo"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "erased_at": ("timestamp with time zone", SIM, None, "nao"),
        "merged_into": ("uuid", SIM, None, "referencia opaca ao contacto que absorveu este"),
        "merged_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "contact_deks": {
        "dek_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": ("uuid", NAO, None, "referencia opaca ao contacto"),
        "wrapped_dek": ("bytea", SIM, None, "chave de dados embrulhada pela KEK do cofre; nao e dado pessoal, e e o que o apagamento destroi"),
        "kek_id": ("text", NAO, None, "versao da KEK; nao e a chave"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "destroyed_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "contact_endpoints": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": ("uuid", NAO, None, "referencia opaca ao contacto"),
        "tipo": ("text", NAO, None, "nao"),
        "bsuid_hmac": ("bytea", SIM, None, "pseudonimo do BSUID: HMAC-SHA256 com segredo do cofre; so para correspondencia"),
        "hmac_kid": ("text", SIM, None, "versao do segredo do HMAC; nao e o segredo"),
        "bsuid_enc": ("bytea", SIM, None, "BSUID cifrado (AES-256-GCM, DEK por contacto)"),
        "phone_enc": ("bytea", SIM, None, "telefone cifrado (AES-256-GCM, DEK por contacto)"),
        "dek_id": ("uuid", NAO, None, "nao"),
        "finalidade": ("text", SIM, None, "finalidade do tratamento do telefone; nao identifica ninguem"),
        "recolhido_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "expira_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "hmac_key_versions": {
        "kid": ("text", NAO, None, "identificador da versao do segredo; nao e o segredo"),
        "estado": ("text", NAO, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
}


class TestInventario(ComBase):
    def no_catalogo(self) -> dict[str, dict[str, tuple]]:
        linhas = self.consultar(
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'platform'"
        )
        resultado: dict[str, dict[str, tuple]] = {}
        for tabela, coluna, tipo, anulavel, omissao in linhas:
            resultado.setdefault(tabela, {})[coluna] = (tipo, anulavel, omissao)
        return resultado

    def test_o_catalogo_e_exactamente_o_inventario(self) -> None:
        catalogo = self.no_catalogo()
        self.assertEqual(set(catalogo), set(INVENTARIO), "tabelas a mais ou a menos")
        for tabela, colunas in INVENTARIO.items():
            self.assertEqual(
                set(catalogo[tabela]),
                set(colunas),
                f"colunas de {tabela} diferem do inventario: uma coluna nova tem de "
                "ser declarada em db/tests/test_inventario.py, com a resposta a "
                "«guarda dados pessoais?»",
            )
            for coluna, (tipo, anulavel, omissao, _) in colunas.items():
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    self.assertEqual(catalogo[tabela][coluna], (tipo, anulavel, omissao))

    def test_toda_a_coluna_tem_a_pergunta_dos_dados_pessoais_respondida(self) -> None:
        for tabela, colunas in INVENTARIO.items():
            for coluna, (_, _, _, pessoal) in colunas.items():
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    self.assertTrue(pessoal.strip())

    def test_as_fk_nao_apagam_em_cascata(self) -> None:
        """Um `ON DELETE CASCADE` transformava apagar um tenant em apagar os canais.

        `a` e `NO ACTION`: apagar um tenant com canais falha, que e o que o
        soft delete do dicionario §2 quer.
        """
        linhas = self.consultar(
            "SELECT conname, confdeltype, confupdtype FROM pg_constraint "
            "WHERE contype = 'f' AND connamespace = 'platform'::regnamespace "
            "ORDER BY conname"
        )
        self.assertEqual(
            sorted(linhas),
            [
                (nome, "a", "a")
                for nome in sorted(
                    [
                        "contact_deks_contact_fk",
                        "contact_deks_tenant_fk",
                        "contact_endpoints_contact_fk",
                        "contact_endpoints_dek_fk",
                        "contact_endpoints_hmac_kid_fk",
                        "contact_endpoints_tenant_fk",
                        "contacts_hmac_kid_fk",
                        "contacts_merged_fk",
                        "contacts_tenant_fk",
                        "entitlements_tenant_fk",
                        "tenant_channels_tenant_fk",
                        "tenants_owner_fk",
                    ]
                )
            ],
        )

    def test_a_fk_do_dono_e_a_unica_diferida(self) -> None:
        """`tenants_owner_fk` e `DEFERRABLE INITIALLY DEFERRED`; as outras nao.

        O tenant e o seu primeiro contacto nascem na mesma transaccao e
        referem-se um ao outro. Uma FK diferida a mais adiava para o `COMMIT`
        um erro que tem de aparecer na instrucao que o causa.
        """
        linhas = self.consultar(
            "SELECT conname::text FROM pg_constraint "
            "WHERE contype = 'f' AND connamespace = 'platform'::regnamespace "
            "AND (condeferrable OR condeferred)"
        )
        self.assertEqual(linhas, [("tenants_owner_fk",)])
        self.assertEqual(
            self.consultar(
                "SELECT condeferrable, condeferred FROM pg_constraint "
                "WHERE conname = 'tenants_owner_fk'"
            ),
            [(True, True)],
        )

    def test_os_indices_unicos_parciais_sao_os_esperados(self) -> None:
        """Nao sao restricoes no catalogo; sem lista, um que desaparecesse passava."""
        linhas = self.consultar(
            "SELECT indexname::text, indexdef FROM pg_indexes "
            "WHERE schemaname = 'platform' AND indexdef LIKE '%%WHERE%%' ORDER BY 1"
        )
        self.assertEqual(
            sorted(nome for nome, _ in linhas),
            [
                "contact_endpoints_telefone_uq",
                "contacts_phone_hmac_uq",
                "hmac_key_versions_actual_uq",
                "hmac_key_versions_anterior_uq",
                "tenants_nif_uq",
            ],
        )
        for nome, definicao in linhas:
            with self.subTest(indice=nome):
                self.assertIn("CREATE UNIQUE INDEX", definicao)

    def test_as_restricoes_sao_as_esperadas(self) -> None:
        """Lista fechada de CHECK, UNIQUE e PK: uma que desapareca nao passa calada."""
        linhas = self.consultar(
            "SELECT conname FROM pg_constraint "
            "WHERE connamespace = 'platform'::regnamespace AND contype IN ('c', 'u', 'p') "
            "ORDER BY conname"
        )
        self.assertEqual(
            sorted(nome for (nome,) in linhas),
            sorted(
                [
                    "contact_deks_destruida_ck",
                    "contact_deks_kek_id_ck",
                    "contact_deks_pkey",
                    "contact_deks_tenant_dek_uq",
                    "contact_endpoints_bsuid_hmac_ck",
                    "contact_endpoints_bsuid_uq",
                    "contact_endpoints_finalidade_ck",
                    "contact_endpoints_forma_ck",
                    "contact_endpoints_pkey",
                    "contact_endpoints_tipo_ck",
                    "contacts_inactivo_sem_phone_ck",
                    "contacts_merged_outro_ck",
                    "contacts_merged_par_ck",
                    "contacts_phone_hmac_ck",
                    "contacts_phone_par_ck",
                    "contacts_pkey",
                    "contacts_tenant_contact_uq",
                    "hmac_key_versions_estado_ck",
                    "hmac_key_versions_kid_ck",
                    "hmac_key_versions_pkey",
                    "entitlements_limites_ck",
                    "entitlements_modulo_ck",
                    "entitlements_pk",
                    "tenant_channels_channel_mode_ck",
                    "tenant_channels_estado_ck",
                    "tenant_channels_free_tier_used_ck",
                    "tenant_channels_origem_ck",
                    "tenant_channels_phone_number_id_ck",
                    "tenant_channels_phone_number_id_uq",
                    "tenant_channels_pkey",
                    "tenant_channels_token_ref_ck",
                    "tenant_channels_vertical_ck",
                    "tenant_channels_waba_id_ck",
                    "tenants_estado_ck",
                    "tenants_nif_ck",
                    "tenants_nome_ck",
                    "tenants_pkey",
                    "tenants_tipo_ck",
                ]
            ),
        )
