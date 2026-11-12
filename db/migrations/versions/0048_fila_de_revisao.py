"""Fila de revisao por excepcao: review_case, review_decision_log e v_review_sla (KAM-089).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

* `platform.review_case` — um caso por excepcao, com motivo interno, motivo
  publico de lista fechada, evidencias **por referencia**, recomendacao, estado e
  prazo em dias uteis de Luanda (`packages/core-ts/src/revisao/`);
* `platform.review_decision_log` — cada decisao, atribuivel a uma pessoa,
  *append-only* por privilegio **e** por *trigger*;
* `platform.v_review_sla` — o prazo e a primeira decisao de cada caso na vista
  humana, com `security_invoker`;
* duas accoes no dominio do `audit_log` (KAM-012): `review.acesso` (cada
  documento visto, cada campo revelado) e `review.recusa` (cada operacao
  recusada: sem papel, sem MFA, parte no caso, ...).

## As divergencias do DDL do bloco, todas a favor do §2 do dicionario

* **`review_decision_log.id` e `uuid`** e nao `bigserial`: um sequencial dizia
  quantas decisoes a plataforma toma (o precedente e a `screening_decision`).
* **`tenant_id NOT NULL` nas duas**, com RLS `FORCE` pela `tenant_iso`: um caso
  de onboarding tem o seu tenant pre-alocado desde o registo (`0043`), e um caso
  sem onboarding (saga, *trust*, auditoria) e sempre de um tenant.
* **A chave de abertura e `(tipo, tenant_id, onboarding_id, motivo_codigo)` com
  `NULLS NOT DISTINCT`**: com um `onboarding_id` o tenant e o dele, e a chave e a
  do criterio 9; sem ele, o `NULLS DISTINCT` por omissao deixava reentregar sem
  limite um caso sem onboarding.
* **`motivo_publico NOT NULL`**, de lista fechada: o dono le sempre um texto
  fixo, e e assim que o ensaio adversarial (d) e verdadeiro por construcao.
* **Quatro colunas a mais**: `fila_at` (a entrada na vista humana, que e de onde
  o prazo conta — a saida da triagem e a abertura do recurso reiniciam-no),
  `sla_alerta_at` (os 80%, calculados em tempo util em TypeScript, porque a base
  nao conhece os feriados), `sla_alertado_at` (o alerta sai uma vez) e o estado
  `em_triagem_automatica` do ensaio adversarial (b).
* **`review_decision_log` com `tenant_id` e `instancia`**: o primeiro para a RLS
  e para a FK composta; o segundo distingue a primeira instancia do recurso, que
  o criterio 4 exige ser decidido por outro revisor.

## A maquina de estados, tambem na base

Um *trigger* recusa uma transicao de `estado` fora da tabela `TRANSICOES` de
`packages/core-ts/src/revisao/contrato.ts`; o ensaio de base confronta as duas.
`decidido_final` nao sai.

## Privilegios

A fila corre como `kamba_batch` (atravessa tenants, e o papel auditado). O
`kamba_app` **nao tem privilegio nenhum** nas duas tabelas nem na vista: o motivo
interno e so do T&S. **Ninguem tem `DELETE`**, e no `review_decision_log`
ninguem tem `UPDATE`. A auditoria le.

## O `downgrade`

Recusa-se se houver linhas de `audit_log` com as duas accoes novas: o
`audit_log` e *append-only* e o dominio anterior nao as aceita. Senao, larga a
vista, as tabelas e as funcoes, sem `CASCADE`, e repoe o dominio da `0046`.
**Apaga os casos e as decisoes**: uma base onde se desce esta revisao e de
ensaio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"

#: O dominio da accao depois desta revisao: o da `0046` (as onze da `0042` e o
#: `order.refund_record` do KAM-050) e as duas da fila. Copiado e nao importado:
#: uma revisao nao importa outra.
LITERAIS_DE_ACCAO_0048 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa'"
)

#: O que o `downgrade` repoe: o dominio da `0046`.
LITERAIS_DE_ACCAO_0046 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record'"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.review_case (
          id               uuid CONSTRAINT review_case_pkey PRIMARY KEY
                           DEFAULT gen_random_uuid(),
          tipo             text NOT NULL
                           CONSTRAINT review_case_tipo_ck
                           CHECK (tipo IN ('kyc', 'categoria', 'duplicado', 'es_falhado',
                             'saga', 'catalogo', 'recurso', 'trust', 'auditoria')),
          onboarding_id    uuid,
          tenant_id        uuid NOT NULL,
          motivo_codigo    text NOT NULL
                           CONSTRAINT review_case_motivo_codigo_ck
                           CHECK (motivo_codigo ~ '^[a-z0-9_]{1,40}(:[0-9a-z_.-]{1,80})?$'),
          motivo_interno   text NOT NULL
                           CONSTRAINT review_case_motivo_interno_ck
                           CHECK (length(motivo_interno) BETWEEN 1 AND 2000),
          motivo_publico   text NOT NULL
                           CONSTRAINT review_case_motivo_publico_ck
                           CHECK (motivo_publico IN ('nao_foi_possivel_validar',
                             'documento_expirado', 'categoria_nao_permitida',
                             'informacao_em_falta')),
          evidencias       jsonb NOT NULL DEFAULT '[]'
                           CONSTRAINT review_case_evidencias_ck
                           CHECK (jsonb_typeof(evidencias) = 'array'),
          recomendacao     text
                           CONSTRAINT review_case_recomendacao_ck
                           CHECK (recomendacao IN ('aprovar', 'rejeitar', 'pedir_info',
                             'investigar')),
          estado           text NOT NULL DEFAULT 'aberto'
                           CONSTRAINT review_case_estado_ck
                           CHECK (estado IN ('em_triagem_automatica', 'aberto', 'em_analise',
                             'escalado', 'decidido', 'recurso_aberto', 'decidido_final')),
          prioridade       smallint NOT NULL DEFAULT 5
                           CONSTRAINT review_case_prioridade_ck
                           CHECK (prioridade BETWEEN 1 AND 9),
          fila_at          timestamptz NOT NULL DEFAULT now(),
          sla_alerta_at    timestamptz NOT NULL,
          sla_due_at       timestamptz NOT NULL,
          sla_alertado_at  timestamptz,
          criado_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT review_case_sla_ck
            CHECK (fila_at <= sla_alerta_at AND sla_alerta_at <= sla_due_at),
          CONSTRAINT review_case_abertura_uq
            UNIQUE NULLS NOT DISTINCT (tipo, tenant_id, onboarding_id, motivo_codigo),
          CONSTRAINT review_case_id_tenant_uq UNIQUE (id, tenant_id),
          CONSTRAINT review_case_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES platform.onboarding_case (id, tenant_id)
        )
        """
    )
    # A pergunta da consola: a vista humana por prioridade e prazo.
    op.execute(
        "CREATE INDEX review_case_fila_idx ON platform.review_case "
        "(estado, prioridade, sla_due_at)"
    )
    # A pergunta do desbloqueio e da quota: os casos de um onboarding.
    op.execute(
        "CREATE INDEX review_case_onboarding_idx ON platform.review_case "
        "(onboarding_id, fila_at) WHERE onboarding_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX review_case_tenant_idx ON platform.review_case (tenant_id)"
    )
    op.execute(
        "COMMENT ON TABLE platform.review_case IS "
        "'Caso da fila de revisao por excepcao (KAM-089). Idempotente por "
        "(tipo, tenant_id, onboarding_id, motivo_codigo). Evidencias por "
        "referencia, nunca copias. motivo_interno so para T&S; motivo_publico de "
        "lista fechada. Transicoes de estado impostas por trigger.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.review_case_transicao()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF NEW.estado IS DISTINCT FROM OLD.estado AND NOT (
               (OLD.estado = 'em_triagem_automatica' AND NEW.estado = 'aberto')
            OR (OLD.estado = 'aberto' AND NEW.estado IN ('em_analise', 'escalado', 'decidido'))
            OR (OLD.estado = 'em_analise' AND NEW.estado IN ('escalado', 'decidido'))
            OR (OLD.estado = 'escalado' AND NEW.estado = 'decidido')
            OR (OLD.estado = 'decidido' AND NEW.estado = 'recurso_aberto')
            OR (OLD.estado = 'recurso_aberto' AND NEW.estado = 'decidido_final')
          ) THEN
            RAISE EXCEPTION 'transicao de review_case recusada: % -> %', OLD.estado, NEW.estado
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_case_transicao
          BEFORE UPDATE ON platform.review_case
          FOR EACH ROW EXECUTE FUNCTION platform.review_case_transicao()
        """
    )

    op.execute(
        """
        CREATE TABLE platform.review_decision_log (
          id          uuid CONSTRAINT review_decision_log_pkey PRIMARY KEY
                      DEFAULT gen_random_uuid(),
          case_id     uuid NOT NULL,
          tenant_id   uuid NOT NULL,
          revisor_id  uuid NOT NULL,
          decisao     text NOT NULL
                      CONSTRAINT review_decision_log_decisao_ck
                      CHECK (decisao IN ('aprovar', 'rejeitar', 'pedir_info', 'escalar')),
          instancia   text NOT NULL DEFAULT 'primeira'
                      CONSTRAINT review_decision_log_instancia_ck
                      CHECK (instancia IN ('primeira', 'recurso')),
          regra       text
                      CONSTRAINT review_decision_log_regra_ck
                      CHECK (length(regra) BETWEEN 1 AND 120),
          nota_enc    bytea,
          em          timestamptz NOT NULL DEFAULT clock_timestamp(),
          CONSTRAINT review_decision_log_recurso_ck
            CHECK (instancia = 'primeira' OR decisao IN ('aprovar', 'rejeitar')),
          CONSTRAINT review_decision_log_case_fk FOREIGN KEY (case_id, tenant_id)
            REFERENCES platform.review_case (id, tenant_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX review_decision_log_case_idx ON platform.review_decision_log "
        "(case_id, em)"
    )
    op.execute(
        "CREATE INDEX review_decision_log_tenant_idx ON platform.review_decision_log "
        "(tenant_id)"
    )
    op.execute(
        "COMMENT ON TABLE platform.review_decision_log IS "
        "'Decisao de um revisor sobre um review_case (KAM-089). Append-only: "
        "ninguem tem UPDATE nem DELETE, e um trigger recusa-os tambem ao dono. "
        "nota_enc cifrada em aplicacao. em por clock_timestamp: ordena decisoes "
        "da mesma transaccao.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.review_decision_log_imutavel()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          RAISE EXCEPTION
            'uma decisao de revisao nao se emenda nem se apaga: o recurso e uma linha nova'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_decision_log_imutavel
          BEFORE UPDATE OR DELETE ON platform.review_decision_log
          FOR EACH ROW EXECUTE FUNCTION platform.review_decision_log_imutavel()
        """
    )

    op.execute(
        """
        CREATE VIEW platform.v_review_sla WITH (security_invoker = true) AS
        SELECT r.id AS case_id, r.tenant_id, r.tipo, r.estado, r.prioridade,
               r.fila_at, r.sla_alerta_at, r.sla_due_at, d.primeira_decisao_at,
               coalesce(d.primeira_decisao_at, now()) <= r.sla_due_at AS dentro_do_sla
          FROM platform.review_case r
          LEFT JOIN LATERAL (
            SELECT min(l.em) AS primeira_decisao_at
              FROM platform.review_decision_log l
             WHERE l.case_id = r.id AND l.instancia = 'primeira'
          ) d ON true
         WHERE r.estado <> 'em_triagem_automatica'
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_review_sla IS "
        "'Prazo e primeira decisao de cada caso na vista humana (KAM-089). "
        "dentro_do_sla compara com o sla_due_at gravado, que ja e em dias uteis.'"
    )

    rls.enable_tenant_rls("review_case")
    rls.enable_tenant_rls("review_decision_log")
    op.execute("REVOKE ALL ON platform.review_case FROM PUBLIC")
    op.execute("REVOKE ALL ON platform.review_decision_log FROM PUBLIC")
    op.execute("REVOKE ALL ON platform.v_review_sla FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (estado, fila_at, sla_alerta_at, sla_due_at, "
        "sla_alertado_at) ON platform.review_case TO kamba_batch"
    )
    op.execute("GRANT SELECT ON platform.review_case TO kamba_audit")
    op.execute("GRANT SELECT, INSERT ON platform.review_decision_log TO kamba_batch")
    op.execute("GRANT SELECT ON platform.review_decision_log TO kamba_audit")
    op.execute("GRANT SELECT ON platform.v_review_sla TO kamba_batch, kamba_audit")
    op.execute("REVOKE ALL ON FUNCTION platform.review_case_transicao() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION platform.review_decision_log_imutavel() FROM PUBLIC")

    _alargar_o_dominio_da_accao()


def _alargar_o_dominio_da_accao() -> None:
    """As duas accoes da fila no `CHECK` do `audit_log`.

    Com `NO FORCE` a volta, pela armadilha que a `0038` escreveu: a validacao
    das linhas existentes corre como o dono, e com `FORCE` o dono ve zero
    linhas.
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0048}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Desce, e **recusa** se o `audit_log` ja tem linhas da fila.

    A contagem corre com o `FORCE` desligado: com ele, o dono ve zero linhas e a
    guarda passava sempre (a armadilha que o KAM-050 mediu na `0038`).
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log "
            "WHERE action IN ('review.acesso', 'review.recusa')"
        )
        .scalar_one()
    )
    if linhas:
        raise RuntimeError(
            f"downgrade da 0048 recusado: ha {linhas} linha(s) de audit_log com "
            "accao review.* e o dominio da 0046 nao as aceita. O audit_log e "
            "append-only e nenhum papel tem DELETE: exporte a cadeia e decida o que "
            "fazer a essas linhas antes de descer."
        )
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0046}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")

    op.execute("DROP VIEW platform.v_review_sla")
    rls.disable_tenant_rls("review_decision_log")
    rls.disable_tenant_rls("review_case")
    op.execute("DROP TRIGGER review_decision_log_imutavel ON platform.review_decision_log")
    op.execute("DROP FUNCTION platform.review_decision_log_imutavel()")
    op.execute("DROP TABLE platform.review_decision_log")
    op.execute("DROP TRIGGER review_case_transicao ON platform.review_case")
    op.execute("DROP FUNCTION platform.review_case_transicao()")
    op.execute("DROP TABLE platform.review_case")
