"""Lista de espera do limite de onboarding: waitlist_entry e onboarding_capacity (KAM-095).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

* `platform.waitlist_entry` — uma entrada por caso que pediu vaga para o
  Embedded Signup: estado, a chave FIFO, o convite de uso unico **em hash** e as
  expiracoes. O servico esta em `packages/core-ts/src/capacidade/`;
* `platform.onboarding_capacity` — o limite em vigor (`es_max_por_7d`), com a
  **origem** (`confirmado` ou `nao_verificado`) e o fundamento. Uma linha so,
  presa pela chave `unica` (`boolean`, sempre `true`) e nao por um `id`: uma
  chave que diz «esta e a linha» nao e um identificador. Mudar o
  limite e um `UPDATE` desta linha, e nao um *deploy* (criterio 3);
* o *trigger* `waitlist_entry_do_caso`, que e a barreira do criterio 1.

## As divergencias do DDL do bloco

* **`tenant_id NOT NULL`, com RLS `FORCE` pela `tenant_iso`** e FK composta
  `(onboarding_id, tenant_id)` para a `onboarding_case`, pela razao da `0048`:
  uma linha nao junta o caso de um com o tenant de outro, e o X-05 agarra a
  tabela pelo tenant.
* **Tres colunas a mais**: `na_fila_desde` (a chave da ordem — o `aprovado_em`
  ate o caso voltar ao fim da fila, por convite expirado ou por reentrada, e o
  instante em que voltou depois disso; o `aprovado_em` fica como facto),
  `concluido_em` (a vaga dada, que e o que conta na janela de 7 dias) e
  `criado_em` (o tempo medio de espera do criterio 8).
* **O `aprovado_em` e o `fase_at` do caso** no instante em que entra, e quem o
  escreve e o *trigger*, nao quem insere: e o adversarial (c), «saltar a fila
  alterando o pedido», recusado pela base. A data da aprovacao em si nao tem
  coluna no caso; o `fase_at` de `aprovado` ou de `aguarda_es` e o instante mais
  proximo que a base guarda, e a ordem entre casos e a mesma.
* **`tentativas` entre 0 e 2**: a segunda expiracao abandona o caso.

## Os privilegios

So o `kamba_batch` escreve, e por coluna: o `aprovado_em` e o `tenant_id` nao
estao no `UPDATE`. O `kamba_app` **nao tem nada**: a vaga e a posicao sao contas
sobre a fila inteira, que atravessa tenants (ver `capacidade/sql.ts`), e o dono
le a sua posicao pela rota, que so aceita o caso da sessao. Ninguem apaga: a
desistencia e um estado. A `onboarding_capacity` le-se pelo lote e pela
auditoria; muda-a o dono do esquema.

## O `downgrade`

Larga as duas tabelas e a funcao do *trigger*, sem `CASCADE`.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.onboarding_capacity (
          unica          boolean CONSTRAINT onboarding_capacity_pkey PRIMARY KEY DEFAULT true
                         CONSTRAINT onboarding_capacity_unica_ck CHECK (unica),
          es_max_por_7d  integer NOT NULL
                         CONSTRAINT onboarding_capacity_es_max_por_7d_ck CHECK (es_max_por_7d >= 0),
          origem         text NOT NULL
                         CONSTRAINT onboarding_capacity_origem_ck
                         CHECK (origem IN ('confirmado', 'nao_verificado')),
          fundamento     text NOT NULL
                         CONSTRAINT onboarding_capacity_fundamento_ck CHECK (length(fundamento) BETWEEN 1 AND 500),
          alterado_em    timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT onboarding_capacity_confirmacao_ck
            CHECK (es_max_por_7d <= 10 OR origem = 'confirmado')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.onboarding_capacity IS "
        "'Limite de clientes novos por 7 dias perante a Meta (KAM-095). Uma linha. "
        "Acima de 10 exige origem confirmado: o patamar seguinte e NAO VERIFICADO "
        "(E1 Q9). Mudar o limite e um UPDATE desta linha, sem deploy.'"
    )
    op.execute(
        "INSERT INTO platform.onboarding_capacity (es_max_por_7d, origem, fundamento) "
        "VALUES (10, 'confirmado', 'E1 secao 3: 10 clientes novos por 7 dias sem verificacao completa')"
    )

    op.execute(
        """
        CREATE TABLE platform.waitlist_entry (
          onboarding_id      uuid CONSTRAINT waitlist_entry_pkey PRIMARY KEY,
          tenant_id          uuid NOT NULL,
          aprovado_em        timestamptz NOT NULL,
          na_fila_desde      timestamptz NOT NULL,
          estado             text NOT NULL DEFAULT 'aguardando'
                             CONSTRAINT waitlist_entry_estado_ck
                             CHECK (estado IN ('aguardando', 'convidado', 'concluido', 'expirado', 'desistiu')),
          convite_hash       bytea
                             CONSTRAINT waitlist_entry_convite_hash_ck CHECK (octet_length(convite_hash) = 32),
          convidado_em       timestamptz,
          convite_expira_em  timestamptz,
          tentativas         smallint NOT NULL DEFAULT 0
                             CONSTRAINT waitlist_entry_tentativas_ck CHECK (tentativas BETWEEN 0 AND 2),
          concluido_em       timestamptz,
          criado_em          timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT waitlist_entry_convite_uq UNIQUE (convite_hash),
          CONSTRAINT waitlist_entry_convite_ck CHECK (
            (estado = 'convidado') = (convite_hash IS NOT NULL)
            AND (convite_hash IS NULL) = (convite_expira_em IS NULL)
            AND (estado <> 'convidado' OR convite_expira_em > convidado_em)
          ),
          CONSTRAINT waitlist_entry_concluido_ck CHECK ((estado = 'concluido') = (concluido_em IS NOT NULL)),
          CONSTRAINT waitlist_entry_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES platform.onboarding_case (id, tenant_id)
        )
        """
    )
    op.execute("CREATE INDEX waitlist_entry_tenant_idx ON platform.waitlist_entry (tenant_id)")
    op.execute(
        "COMMENT ON TABLE platform.waitlist_entry IS "
        "'Lista de espera do limite de onboarding da Meta (KAM-095). So casos em "
        "aprovado ou aguarda_es entram (trigger). Ordem FIFO por na_fila_desde, que "
        "nasce do fase_at do caso. Convite de uso unico guardado em hash SHA-256.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.waitlist_entry_do_caso()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          caso record;
        BEGIN
          SELECT fase, fase_at INTO caso FROM platform.onboarding_case WHERE id = NEW.onboarding_id;
          IF NOT FOUND OR caso.fase NOT IN ('aprovado', 'aguarda_es') THEN
            RAISE EXCEPTION 'waitlist_entry so admite casos aprovados'
              USING ERRCODE = '23514';
          END IF;
          NEW.aprovado_em := caso.fase_at;
          NEW.na_fila_desde := caso.fase_at;
          NEW.estado := 'aguardando';
          NEW.convite_hash := NULL;
          NEW.convidado_em := NULL;
          NEW.convite_expira_em := NULL;
          NEW.tentativas := 0;
          NEW.concluido_em := NULL;
          NEW.criado_em := now();
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER waitlist_entry_do_caso
          BEFORE INSERT ON platform.waitlist_entry
          FOR EACH ROW EXECUTE FUNCTION platform.waitlist_entry_do_caso()
        """
    )

    rls.enable_tenant_rls("waitlist_entry")
    op.execute("REVOKE ALL ON platform.waitlist_entry FROM PUBLIC")
    op.execute("REVOKE ALL ON platform.onboarding_capacity FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (estado, na_fila_desde, convite_hash, convidado_em, "
        "convite_expira_em, tentativas, concluido_em) ON platform.waitlist_entry TO kamba_batch"
    )
    op.execute("GRANT SELECT ON platform.waitlist_entry TO kamba_audit")
    op.execute("GRANT SELECT ON platform.onboarding_capacity TO kamba_batch")
    op.execute("GRANT SELECT ON platform.onboarding_capacity TO kamba_audit")
    op.execute("REVOKE ALL ON FUNCTION platform.waitlist_entry_do_caso() FROM PUBLIC")


def downgrade() -> None:
    rls.disable_tenant_rls("waitlist_entry")
    op.execute("DROP TABLE platform.waitlist_entry")
    op.execute("DROP FUNCTION platform.waitlist_entry_do_caso()")
    op.execute("DROP TABLE platform.onboarding_capacity")
