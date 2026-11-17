"""Teste ponta a ponta da activacao: conversations.is_test e onboarding_smoke (KAM-094).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

* `conversations.is_test` — a conversa do teste ponta a ponta, fora das
  metricas, da golden e do Score (criterio 4). **Nasce sempre falsa**, por
  *trigger* (`conversations_is_test_nasce_falso`): o `kamba_app` tem `INSERT` na
  tabela inteira (0009), e uma conversa criada ja marcada como teste saia das
  metricas e do Score sem passar pelo teste. So o lote a marca, por `UPDATE`.
* `platform.onboarding_smoke` — as tentativas do teste, para contar as tres
  falhas seguidas do criterio 5 com a base e nao com um duplo.

## O que nao cria, e quem o leva

**A restricao de BD na publicacao da `offer_terms`** (a caixa da DoD
«publicacao protegida por restricao de BD») e do **KAM-202**, por decisao do
orquestrador do lote: a tabela e do KAM-043 e quem lhe escreve e o COM, cujo
`publishProduct` nao chama o screening, e 16 ficheiros de sementes e 11 sitios
que publicam teriam de gravar decisao antes. Uma restricao sem o caminho de
escrita que a satisfaca inutilizava a publicacao do COM. Neste ticket o
`assertPublishable` do KAM-088 corre em TypeScript antes de publicar
(`packages/core-ts/src/activacao/catalogo_minimo.ts`).

## `onboarding_smoke`

Uma linha por tentativa. **A aplicacao abre, e so o lote fecha**: o `kamba_app`
insere o caso, o tenant e a janela (a pagina do dono carrega em «comecar»), e
o `resultado` nasce `pendente` porque a aplicacao nao tem a coluna; o
`kamba_batch` fecha-a, porque o mesmo passo marca o gate `e2e`, e um contexto
de tenant que fechasse o proprio teste como `ok` activava-se a si proprio — a
razao da 0058 para os gates. Uma tentativa fechada nao muda (*trigger*). O
`levou_a_fila` marca a falha que abriu o `review_case`: a contagem das falhas
seguidas recomeca depois dela, e a marca nao se desfaz.

## Descida

Larga a tabela, as duas funcoes de *trigger* e a coluna, sem `CASCADE`. A coluna
`is_test` perde-se, e com ela a marca das conversas de teste: e estado de
medicao e nao prova.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0064"
#: Sobre a `0063`, a dos KPIs de churn (KAM-117): o numero deu-o a integracao,
#: pela ordem de quem fundiu.
down_revision = "0063"
branch_labels = None
depends_on = None

TENTATIVAS = "platform.onboarding_smoke"

#: As quatro causas de um teste falhado (`CAUSAS_DO_TESTE`, `activacao/contrato.ts`).
CAUSAS = ("'sem_inbound'", "'sem_resposta'", "'sem_entrega'", "'sem_consentimento'")

#: Os tres resultados de uma tentativa.
RESULTADOS = ("'pendente'", "'ok'", "'falhou'")


def upgrade() -> None:
    _conversa_de_teste()
    _tentativas()


def _conversa_de_teste() -> None:
    op.execute(
        "ALTER TABLE platform.conversations ADD COLUMN is_test boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "COMMENT ON COLUMN platform.conversations.is_test IS "
        "'Conversa do teste ponta a ponta da activacao (KAM-094). Fora das metricas, "
        "da golden e do Score. Nasce falsa (trigger); so o lote a marca.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.conversations_is_test_nasce_falso()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          NEW.is_test := false;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER conversations_is_test_nasce_falso
          BEFORE INSERT ON platform.conversations
          FOR EACH ROW EXECUTE FUNCTION platform.conversations_is_test_nasce_falso()
        """
    )
    op.execute(
        "ALTER TABLE platform.conversations ENABLE ALWAYS TRIGGER conversations_is_test_nasce_falso"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.conversations_is_test_nasce_falso() FROM PUBLIC")


def _tentativas() -> None:
    op.execute(
        f"""
        CREATE TABLE {TENTATIVAS} (
          id             uuid CONSTRAINT onboarding_smoke_pkey PRIMARY KEY
                         DEFAULT gen_random_uuid(),
          onboarding_id  uuid NOT NULL,
          tenant_id      uuid NOT NULL,
          iniciada_em    timestamptz NOT NULL DEFAULT now(),
          expira_em      timestamptz NOT NULL,
          resultado      text NOT NULL DEFAULT 'pendente'
                         CONSTRAINT onboarding_smoke_resultado_ck
                         CHECK (resultado IN ({", ".join(RESULTADOS)})),
          causa          text
                         CONSTRAINT onboarding_smoke_causa_ck
                         CHECK (causa IN ({", ".join(CAUSAS)})),
          fechada_em     timestamptz,
          levou_a_fila   boolean NOT NULL DEFAULT false,
          CONSTRAINT onboarding_smoke_janela_ck
            CHECK (expira_em > iniciada_em AND expira_em <= iniciada_em + interval '10 minutes'),
          CONSTRAINT onboarding_smoke_causa_do_resultado_ck
            CHECK ((resultado = 'falhou') = (causa IS NOT NULL)),
          CONSTRAINT onboarding_smoke_fecho_ck
            CHECK ((resultado = 'pendente') = (fechada_em IS NULL)),
          CONSTRAINT onboarding_smoke_fila_ck
            CHECK (NOT levou_a_fila OR resultado = 'falhou'),
          CONSTRAINT onboarding_smoke_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES platform.onboarding_case (id, tenant_id)
        )
        """
    )
    op.execute(
        f"CREATE INDEX onboarding_smoke_caso_idx ON {TENTATIVAS} (onboarding_id, iniciada_em)"
    )
    op.execute(f"CREATE INDEX onboarding_smoke_tenant_idx ON {TENTATIVAS} (tenant_id)")
    op.execute(
        f"COMMENT ON TABLE {TENTATIVAS} IS "
        "'Tentativas do teste ponta a ponta assistido pelo dono (KAM-094). A aplicacao "
        "abre, so o lote fecha; uma tentativa fechada nao muda. levou_a_fila marca a "
        "falha que abriu o review_case.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.onboarding_smoke_transicao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF OLD.resultado <> 'pendente'
             AND (NEW.resultado, NEW.causa, NEW.fechada_em)
                 IS DISTINCT FROM (OLD.resultado, OLD.causa, OLD.fechada_em) THEN
            RAISE EXCEPTION 'tentativa de teste ja fechada'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
          IF NEW.levou_a_fila AND NOT OLD.levou_a_fila AND NEW.resultado <> 'falhou' THEN
            RAISE EXCEPTION 'so uma falha leva o caso a fila'
              USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.levou_a_fila AND NOT NEW.levou_a_fila THEN
            RAISE EXCEPTION 'a ida a fila nao se desfaz'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER onboarding_smoke_transicao
          BEFORE UPDATE ON {TENTATIVAS}
          FOR EACH ROW EXECUTE FUNCTION platform.onboarding_smoke_transicao()
        """
    )
    op.execute(f"ALTER TABLE {TENTATIVAS} ENABLE ALWAYS TRIGGER onboarding_smoke_transicao")
    rls.enable_tenant_rls("onboarding_smoke")
    op.execute(f"REVOKE ALL ON {TENTATIVAS} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT (onboarding_id, tenant_id, iniciada_em, expira_em) "
        f"ON {TENTATIVAS} TO kamba_app"
    )
    op.execute(
        f"GRANT SELECT, UPDATE (resultado, causa, fechada_em, levou_a_fila) "
        f"ON {TENTATIVAS} TO kamba_batch"
    )
    op.execute(f"GRANT SELECT ON {TENTATIVAS} TO kamba_audit")
    op.execute("REVOKE ALL ON FUNCTION platform.onboarding_smoke_transicao() FROM PUBLIC")


def downgrade() -> None:
    rls.disable_tenant_rls("onboarding_smoke")
    op.execute(f"DROP TABLE {TENTATIVAS}")
    op.execute("DROP FUNCTION platform.onboarding_smoke_transicao()")
    op.execute("DROP TRIGGER conversations_is_test_nasce_falso ON platform.conversations")
    op.execute("DROP FUNCTION platform.conversations_is_test_nasce_falso()")
    op.execute("ALTER TABLE platform.conversations DROP COLUMN is_test")
