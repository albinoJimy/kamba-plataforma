"""Screening de categorias: screening_decision (KAM-088).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o ensaio que compara a saida no
processo com a do executavel diverge na codificacao com acentos.

## O que esta revisao cria

A `platform.screening_decision`, uma linha por decisao do motor de screening
(`packages/core-ts/src/screening/`), com RLS `FORCE` pela `tenant_iso`. O DDL e
o dos Detalhes Tecnicos do bloco do KAM-088, com as divergencias que a emenda
1.81 do dicionario (§3.58) decide a favor do §2:

* **`id` `uuid`** e nao `bigserial`: um sequencial dizia quantas decisoes a
  plataforma toma;
* **`tenant_id NOT NULL`**: e tabela de negocio com RLS, e o caso de onboarding
  tem o seu tenant pre-alocado desde o registo (`0043`);
* **`criado_at` por `clock_timestamp()`** e nao por `now()`: com um `id`
  aleatorio e ele que ordena as decisoes, e o `now()` e o mesmo para a
  transaccao inteira — duas decisoes na mesma transaccao empatavam (achado F17
  da revisao adversarial do KAM-088);
* **`conteudo_sha256`**, que o bloco nao tem: sem ela, a `permitida` de
  «camisola» valia para o mesmo `sku` depois de o titulo passar a «whisky».

E uma FK composta `(onboarding_id, tenant_id)` para a unicidade com o mesmo par
da `onboarding_case`: uma decisao nao junta o caso de um com o tenant de outro.
O `onboarding_id` e anulavel — a decisao de um produto nao tem caso.

## Append-only, tambem para o dono

O `kamba_app` tem `SELECT` e `INSERT`, e mais nada: e ele que corre o `screen`
dentro do `comTenant`. O `kamba_batch` le (a re-analise do catalogo atravessa
tenants) e a auditoria le. **Ninguem tem `UPDATE` nem `DELETE`**, e um *trigger*
recusa-os tambem ao dono, pela razao da `contract_acceptance` da `0040`: o
`kamba_migrator` tem todos os privilegios, e uma decisao `bloqueada` que se
emendasse para `permitida` publicava o produto sem rasto. O recurso humano e uma
linha **nova** com `origem = 'humano'`.

## O `downgrade`

Larga a tabela e a funcao do *trigger*, sem `CASCADE`: se alguma coisa passar a
depender delas, o `downgrade` deve falhar em vez de a levar atras. **Apaga as
decisoes**: uma base onde se desce esta revisao e uma base de ensaio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

TABELA = "platform.screening_decision"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.screening_decision (
          id               uuid CONSTRAINT screening_decision_pkey PRIMARY KEY
                           DEFAULT gen_random_uuid(),
          tenant_id        uuid NOT NULL,
          onboarding_id    uuid,
          sujeito_tipo     text NOT NULL
                           CONSTRAINT screening_decision_sujeito_tipo_ck
                           CHECK (sujeito_tipo IN ('categoria', 'produto')),
          sujeito_ref      text NOT NULL
                           CONSTRAINT screening_decision_sujeito_ref_ck
                           CHECK (sujeito_ref <> ''),
          decisao          text NOT NULL
                           CONSTRAINT screening_decision_decisao_ck
                           CHECK (decisao IN ('permitida', 'condicional', 'bloqueada')),
          regras           text[] NOT NULL,
          versao_politica  text NOT NULL
                           CONSTRAINT screening_decision_versao_politica_ck
                           CHECK (versao_politica ~ '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\+[0-9A-Za-z.]+$'),
          origem           text NOT NULL
                           CONSTRAINT screening_decision_origem_ck
                           CHECK (origem IN ('regra', 'llm', 'humano')),
          conteudo_sha256  bytea NOT NULL
                           CONSTRAINT screening_decision_conteudo_sha256_ck
                           CHECK (octet_length(conteudo_sha256) = 32),
          criado_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
          CONSTRAINT screening_decision_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES platform.onboarding_case (id, tenant_id)
        )
        """
    )
    # A pergunta do `assertPublishable` e a da re-analise: a chave inteira, pela
    # ordem do `criado_at`.
    op.execute(
        "CREATE INDEX screening_decision_chave_idx ON platform.screening_decision "
        "(tenant_id, sujeito_tipo, sujeito_ref, versao_politica, criado_at)"
    )
    op.execute(
        "COMMENT ON TABLE platform.screening_decision IS "
        "'Decisao de screening de categoria ou produto (KAM-088). Append-only: "
        "ninguem tem UPDATE nem DELETE, e um trigger recusa-os tambem ao dono. "
        "O recurso humano e uma linha nova com origem humano. versao_politica "
        "leva a versao do motor como metadado SemVer (+m.N).'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.screening_decision_imutavel()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          RAISE EXCEPTION
            'uma decisao de screening nao se emenda nem se apaga: o recurso e uma linha nova'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER screening_decision_imutavel
          BEFORE UPDATE OR DELETE ON platform.screening_decision
          FOR EACH ROW EXECUTE FUNCTION platform.screening_decision_imutavel()
        """
    )
    rls.enable_tenant_rls("screening_decision")
    op.execute("REVOKE ALL ON platform.screening_decision FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON platform.screening_decision TO kamba_app")
    op.execute("GRANT SELECT ON platform.screening_decision TO kamba_batch")
    op.execute("GRANT SELECT ON platform.screening_decision TO kamba_audit")
    op.execute("REVOKE ALL ON FUNCTION platform.screening_decision_imutavel() FROM PUBLIC")


def downgrade() -> None:
    rls.disable_tenant_rls("screening_decision")
    op.execute("DROP TRIGGER screening_decision_imutavel ON platform.screening_decision")
    op.execute("DROP FUNCTION platform.screening_decision_imutavel()")
    op.execute("DROP TABLE platform.screening_decision")
