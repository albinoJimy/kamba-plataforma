"""Schema `platform`: tenants, tenant_channels, entitlements (KAM-003).

Revisao: 0001
Anterior: nenhuma

A fonte de cada tabela, porque as duas fontes do desenho divergem e a escolha
esta escrita no ticket e no dicionario §3.2 (emenda 1.2):

    tenants          DDL de `docs/tecnica/03` §5.2, com `estado` ampliado para
                     os cinco valores do `docs/tecnica/00` §6.2 (falta `restrito`
                     no doc 03).
    tenant_channels  colunas de `docs/tecnica/01` §7.1 — e **nao** as do doc 03,
                     que tem tres estados e uma coluna `persona`. A persona nao
                     e coluna: deriva do registo da vertical (ADR-012).
    entitlements     DDL de `docs/tecnica/03` §5.2.

O que esta revisao **nao** faz, e de quem e:

    RLS                          KAM-004. Aqui so se garante `tenant_id` em
                                 primeiro lugar num indice de cada tabela.
    FK tenants.owner_contact_id  KAM-008, que cria `contacts`. A ordem do
                                 desenho e `tenants -> contacts -> tenant_channels`.
    Colunas de telefone          nenhuma, nem aqui nem nunca em claro (ADR-010).
    `canal`, `criado_at` do canal  estao no DDL do doc 03 e **nao** no do doc 01,
                                 que e o que o ticket manda seguir. Ficam de
                                 fora; o canal nao tem data de criacao, e isso
                                 esta registado no bloco do KAM-003.

Tudo isto e SQL **proposto ate correr**: o gate 8 e o que o promove.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `CREATE SCHEMA` sem `IF NOT EXISTS`: se o schema ja existir, alguem criou
    # objectos fora das migracoes, e isso tem de falhar aqui e nao passar.
    op.execute("CREATE SCHEMA platform")

    op.execute(
        """
        CREATE TABLE platform.tenants (
          id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tipo                     text NOT NULL
                                   CONSTRAINT tenants_tipo_ck
                                   CHECK (tipo IN ('pme','courier','reseller','agent','platform')),
          nome                     text NOT NULL
                                   CONSTRAINT tenants_nome_ck CHECK (btrim(nome) <> ''),
          nif                      text
                                   CONSTRAINT tenants_nif_ck
                                   CHECK (nif <> '' AND nif = btrim(nif)),
          contacto_negocio_enc     bytea,
          owner_contact_id         uuid,
          zona                     text,
          plus_code                text,
          plano                    text NOT NULL DEFAULT 'free',
          estado                   text NOT NULL DEFAULT 'onboarding'
                                   CONSTRAINT tenants_estado_ck
                                   CHECK (estado IN ('onboarding','ativo','restrito','suspenso','encerrado')),
          medusa_sales_channel_id  text,
          medusa_merchant_id       text,
          chatwoot_account_id      integer,
          litellm_key_id           text,
          fuso_horario             text NOT NULL DEFAULT 'Africa/Luanda',
          verificado_at            timestamptz,
          criado_at                timestamptz NOT NULL DEFAULT now(),
          deleted_at               timestamptz
        )
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.tenants.owner_contact_id IS
          'Sem FK nesta revisao: platform.contacts e do KAM-008, que acrescenta a FK diferida.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.tenants.contacto_negocio_enc IS
          'Cifrado em aplicacao. Nunca em claro e nunca usado como chave (ADR-010).'
        """
    )
    # Unico parcial: dois tenants sem NIF coexistem, e um NIF de um tenant
    # apagado (soft delete) fica livre para um registo novo.
    op.execute(
        """
        CREATE UNIQUE INDEX tenants_nif_uq ON platform.tenants (nif)
          WHERE nif IS NOT NULL AND deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE platform.tenant_channels (
          id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id               uuid NOT NULL
                                  CONSTRAINT tenant_channels_tenant_fk
                                  REFERENCES platform.tenants (id),
          waba_id                 text NOT NULL
                                  CONSTRAINT tenant_channels_waba_id_ck
                                  CHECK (waba_id <> '' AND waba_id = btrim(waba_id)),
          waac_id                 text,
          phone_number_id         text NOT NULL
                                  CONSTRAINT tenant_channels_phone_number_id_uq UNIQUE
                                  CONSTRAINT tenant_channels_phone_number_id_ck
                                  CHECK (phone_number_id <> ''
                                         AND phone_number_id = btrim(phone_number_id)),
          channel_mode            text NOT NULL
                                  CONSTRAINT tenant_channels_channel_mode_ck
                                  CHECK (channel_mode IN ('coexistencia','cloud_only')),
          vertical                text NOT NULL
                                  CONSTRAINT tenant_channels_vertical_ck
                                  CHECK (vertical ~ '^[a-z][a-z0-9_]*$'),
          origem                  text NOT NULL DEFAULT 'pme'
                                  CONSTRAINT tenant_channels_origem_ck
                                  CHECK (origem IN ('pme','plataforma')),
          estado                  text NOT NULL DEFAULT 'pendente'
                                  CONSTRAINT tenant_channels_estado_ck
                                  CHECK (estado IN ('pendente','ativo','restrito','desligado','suspenso','encerrado')),
          token_ref               text NOT NULL
                                  CONSTRAINT tenant_channels_token_ref_ck
                                  CHECK (btrim(token_ref) <> ''),
          quality_rating          text,
          messaging_limit         text,
          free_tier_used          integer NOT NULL DEFAULT 0
                                  CONSTRAINT tenant_channels_free_tier_used_ck
                                  CHECK (free_tier_used >= 0),
          free_tier_month         date,
          coexistence_synced_at   timestamptz,
          last_account_update_at  timestamptz
        )
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.tenant_channels.phone_number_id IS
          'Identificador que a Meta atribui ao numero do negocio. Nao e um telefone: e uma chave opaca da Cloud API.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.tenant_channels.token_ref IS
          'Referencia opaca ao segredo (SecretProvider, KAM-010). Nunca o token, e nunca se interpreta.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.tenant_channels.vertical IS
          'Chave do AgentRegistry. O CHECK e de forma (minusculas, snake_case), nao de dominio: as verticais sao configuracao (ADR-012).'
        """
    )
    # `tenant_id` em primeiro lugar: e o predicado que a RLS do KAM-004 vai
    # acrescentar a todas as consultas.
    op.execute(
        """
        CREATE INDEX tenant_channels_tenant_estado_idx
          ON platform.tenant_channels (tenant_id, estado)
        """
    )

    op.execute(
        """
        CREATE TABLE platform.entitlements (
          tenant_id  uuid NOT NULL
                     CONSTRAINT entitlements_tenant_fk
                     REFERENCES platform.tenants (id),
          modulo     text NOT NULL
                     CONSTRAINT entitlements_modulo_ck
                     CHECK (modulo ~ '^[a-z][a-z0-9_]*$'),
          limites    jsonb NOT NULL DEFAULT '{}'::jsonb
                     CONSTRAINT entitlements_limites_ck
                     CHECK (jsonb_typeof(limites) = 'object'),
          ativo      boolean NOT NULL DEFAULT true,
          CONSTRAINT entitlements_pk PRIMARY KEY (tenant_id, modulo)
        )
        """
    )

    # Privilegios, tabela a tabela e — onde importa — coluna a coluna. Sem
    # `ALTER DEFAULT PRIVILEGES`: cada revisao diz o que concede, para que uma
    # tabela nova nao fique acessivel a aplicacao sem ninguem o ter escrito.
    #
    # `kamba_app` **nao tem DELETE em tabela nenhuma**. O dicionario §2 diz
    # «soft delete: estado, nunca DELETE», e a primeira versao desta revisao
    # dava-lho nas tres: um `DELETE FROM platform.tenants` sob o papel da
    # aplicacao era aceite. Quem apaga linhas e o `kamba_batch` (retencao).
    #
    # E ha quatro colunas que `kamba_app` **nao pode alterar** depois do insert:
    #
    #   tenants.tipo, tenant_channels.origem   sao a costura do Fluxo B. Com
    #       UPDATE livre, um tenant `platform` passava a `pme` e saia da vista
    #       da guarda do ADR-011.
    #   tenant_channels.tenant_id              mover um canal de tenant e o CHR
    #       passar a entregar as mensagens de um negocio a outro.
    #   tenants.id, tenant_channels.id, criado_at   identidade e registo.
    #
    # O resto de `tenants` (plano, estado, verificado_at) continua alteravel por
    # `kamba_app`. Restringi-lo e uma decisao de desenho que nenhum documento
    # toma — quem muda o plano de um tenant? — e fica registada como lacuna no
    # bloco do KAM-003, para o KAM-004 e o KAM-009, em vez de decidida aqui.
    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_app, kamba_batch")

    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
          ON platform.tenants, platform.tenant_channels, platform.entitlements
          TO kamba_batch
        """
    )

    op.execute(
        """
        GRANT SELECT, INSERT
          ON platform.tenants, platform.tenant_channels, platform.entitlements
          TO kamba_app
        """
    )
    op.execute(
        """
        GRANT UPDATE (nome, nif, contacto_negocio_enc, owner_contact_id, zona,
                      plus_code, plano, estado, medusa_sales_channel_id,
                      medusa_merchant_id, chatwoot_account_id, litellm_key_id,
                      fuso_horario, verificado_at, deleted_at)
          ON platform.tenants TO kamba_app
        """
    )
    op.execute(
        """
        GRANT UPDATE (waba_id, waac_id, phone_number_id, channel_mode, vertical,
                      estado, token_ref, quality_rating, messaging_limit,
                      free_tier_used, free_tier_month, coexistence_synced_at,
                      last_account_update_at)
          ON platform.tenant_channels TO kamba_app
        """
    )
    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")


def downgrade() -> None:
    # Pela ordem inversa das FK. `DROP SCHEMA` sem `CASCADE`: se houver em
    # `platform` um objecto que esta revisao nao criou, o `downgrade` falha em
    # vez de o apagar em silencio.
    op.execute("DROP TABLE platform.entitlements")
    op.execute("DROP TABLE platform.tenant_channels")
    op.execute("DROP TABLE platform.tenants")
    op.execute("DROP SCHEMA platform")
