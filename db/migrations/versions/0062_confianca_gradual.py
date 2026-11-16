"""Confianca gradual: trust_level e o tecto por pedido na cobranca (KAM-096).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

* `platform.trust_level` — o nivel de confianca de cada tenant e o tecto por
  pedido que lhe corresponde, em unidade menor (`tecto_pedido_minor`), com o
  motivo, o actor e a versao da configuracao de onde o valor veio. Uma linha
  por tenant. O servico que decide o nivel esta em
  `packages/core-ts/src/confianca/`;
* o *trigger* `trust_level_guardar` (`BEFORE INSERT OR UPDATE`): a linha so
  nasce com o K1 do tenant completo, o `tenant_id` nao muda, e o `desde` so
  anda quando o **nivel** muda — e e quem escolhe as duas datas, e nao quem
  escreve;
* o *trigger* `trust_level_auditado` (`AFTER INSERT OR UPDATE`): cada
  alteracao escreve uma linha `trust.tecto` no `audit_log` (KAM-012, criterio 7), com o
  actor da linha. Um `INSERT ... ON CONFLICT DO UPDATE ... WHERE` que nao muda
  nada nao dispara um `AFTER`, e e isso que torna o recalculo idempotente
  tambem no registo. **A excepcao e o nascimento pelo superutilizador**, e
  esta escrita na seccao seguinte;
* o *trigger* `payment_charges_dentro_do_tecto` (`BEFORE INSERT`, `ENABLE
  ALWAYS`) na `payment_charges`: uma cobranca de encomenda cujo pedido passe o
  tecto do tenant, ou de um tenant sem nivel, **nao entra** — na mesma transaccao e na
  mesma instrucao que a escreve. E a barreira; o `assertWithinTrustCeiling` do
  TypeScript e a mensagem fixa que o agente mostra.

## O nascimento pelo superutilizador nao se audita, e porque

O `audit_log` e *append-only* e o dominio da `action` e fechado. Uma linha
`trust.tecto` *committed* torna impossivel descer abaixo desta revisao — e abaixo
da `0048`, da `0046`, da `0042` e da `0038`, que repoem o `CHECK` antigo
validado. As sementes das suites de base (`factories.confianca`) escrevem o
nivel com o administrador, que e superutilizador, e *committed* (a
`tests_pagamentos` e `autocommit`): com a auditoria do nascimento, o
`test_downgrade` dessa suite deixava de poder descer a `0028`. E a mesma
armadilha que o `test_downgrade_0046.py` do KAM-050 escreve por extenso.

Por isso o *trigger* nao audita um `INSERT` feito por um superutilizador. Nao e
uma porta: o superutilizador ignora a RLS e pode desligar qualquer *trigger*,
pelo que nenhuma auditoria por *trigger* o prende — fingir o contrario era
teatro. O `kamba_batch`, que e o escritor de producao, e auditado no `INSERT` e
no `UPDATE`; o `UPDATE` e auditado para todos, superutilizador incluido.

## A concorrencia no limite do tecto

As duas pontas tomam a mesma tranca consultiva da transaccao, chaveada pelo
tenant: a cobranca em modo **partilhado**, a escrita do nivel em modo
**exclusivo**. Uma descida que fez *commit* nunca e atravessada por uma
cobranca que le o tecto depois dela: a cobranca espera pela tranca e, em
`READ COMMITTED`, a leitura do tecto que vem a seguir ve a linha nova. E o
contrario tambem: uma cobranca em curso faz a descida esperar pelo seu
*commit*. Uma tranca de linha (`FOR SHARE`) pedia `UPDATE` na tabela ao
`kamba_app`, que e exactamente o que ele nao pode ter.

**Exige `READ COMMITTED`**, que e a omissao e o que o `audit_append` ja exige:
sob `REPEATABLE READ` a fotografia e a do inicio da transaccao.

## As divergencias do DDL do bloco

* **Quatro colunas a mais**: `currency` (a moeda explicita do dicionario §2),
  `actor` (quem decidiu: `sistema:<versao>` ou `revisor:<id>`, o criterio 7),
  `versao_config` (a configuracao versionada de onde o tecto veio) e
  `alterado_em` (o tecto pode mudar sem o nivel mudar, numa recalibracao).
* **O nivel 2 existe e nao se atribui** (`trust_level_piloto_ck`): e do K2/selo,
  que e das Clusters. Cai com uma revisao, e nao com uma linha de codigo.
* **Sem `trust_order_eligibility`.** A elegibilidade calcula-se a cada
  recalculo a partir das fontes (a encomenda, o registo de estados, o sinal de
  independencia do KAM-097): uma segunda copia do mesmo facto era uma tabela a
  divergir da primeira, e o recalculo deixava de ser uma funcao do estado.

## Os privilegios

O `kamba_batch` passa a ler tres colunas da `contacts` (`tenant_id`,
`contact_id`, `merged_into`): o recalculo junta os pedidos de um comprador pela
cadeia de fusoes, e a tabela de identidade nao lhe dava nada.

So o `kamba_batch` escreve, e por coluna: o `tenant_id` e a `currency` nao
estao no `UPDATE`. O `kamba_app` le **so** as colunas do tecto (`tenant_id`,
`nivel`, `tecto_pedido_minor`, `currency`) do seu tenant, que e o que o
*trigger* da cobranca precisa quando ele a escreve; o motivo e o actor nao.
Ninguem apaga: uma descida e um `UPDATE` auditado.

## O `downgrade`

**Recusa** se o `audit_log` ja tem linhas `trust.tecto`: o registo e
*append-only*, nenhum papel tem `DELETE`, e o dominio da `0048` nao as aceita.
Sem elas, larga o *trigger* da cobranca, os dois da tabela, a tabela e as tres
funcoes, sem `CASCADE`.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"

#: O dominio da accao depois desta revisao: o da `0048` e o `trust.tecto`.
#: Copiado e nao importado: uma revisao nao importa outra.
LITERAIS_DE_ACCAO_0062 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'trust.tecto'"
)

#: O que o `downgrade` repoe: o dominio da `0048`.
LITERAIS_DE_ACCAO_0048 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa'"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.trust_level (
          tenant_id           uuid CONSTRAINT trust_level_pkey PRIMARY KEY,
          nivel               smallint NOT NULL
                              CONSTRAINT trust_level_nivel_ck CHECK (nivel IN (0, 1, 2)),
          tecto_pedido_minor  bigint NOT NULL
                              CONSTRAINT trust_level_tecto_pedido_minor_ck CHECK (tecto_pedido_minor > 0),
          currency            text NOT NULL DEFAULT 'AOA'
                              CONSTRAINT trust_level_currency_ck CHECK (currency = 'AOA'),
          motivo              text NOT NULL
                              CONSTRAINT trust_level_motivo_ck
                              CHECK (motivo IN ('k1_completo', 'historico_independente',
                                'disputa_aceite', 'sinal_alto', 'sancao', 'recalibracao')),
          actor               text NOT NULL
                              CONSTRAINT trust_level_actor_ck
                              CHECK (actor ~ '^(sistema|revisor):[!-~]{1,120}$'),
          versao_config       text NOT NULL
                              CONSTRAINT trust_level_versao_config_ck
                              CHECK (versao_config ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}\\.[0-9]+$'),
          desde               timestamptz NOT NULL DEFAULT now(),
          alterado_em         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT trust_level_piloto_ck CHECK (nivel < 2),
          CONSTRAINT trust_level_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.trust_level IS "
        "'Nivel de confianca e tecto por pedido de cada tenant (KAM-096). So nasce "
        "com o K1 completo; o nivel 2 nao se atribui no Piloto. Escreve o kamba_batch, "
        "cada alteracao vai ao audit_log (trust.tecto). A cobranca de encomenda acima "
        "do tecto e recusada pelo trigger payment_charges_dentro_do_tecto.'"
    )
    _guardar()
    _auditar()
    _tecto_na_cobranca()
    _alargar_o_dominio_da_accao()

    rls.enable_tenant_rls("trust_level")
    op.execute("REVOKE ALL ON platform.trust_level FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (nivel, tecto_pedido_minor, motivo, actor, "
        "versao_config, desde, alterado_em) ON platform.trust_level TO kamba_batch"
    )
    op.execute(
        "GRANT SELECT (tenant_id, nivel, tecto_pedido_minor, currency) "
        "ON platform.trust_level TO kamba_app"
    )
    op.execute("GRANT SELECT ON platform.trust_level TO kamba_audit")
    # O recalculo junta os pedidos do mesmo comprador pela cadeia de fusoes
    # (`merged_into`), como o T&S do KAM-097. O `kamba_batch` nao tinha nada na
    # `contacts`; pede-se por revisao, e so as tres colunas da cadeia — nenhuma
    # delas e dado pessoal.
    op.execute("GRANT SELECT (tenant_id, contact_id, merged_into) ON platform.contacts TO kamba_batch")


def _guardar() -> None:
    """A barreira da escrita: K1, chave imutavel e as duas datas.

    O K1 e o mesmo predicado que o agregador do KAM-092 usa para o gate `kyc`
    (`aprovacao_em_falta`): o ultimo lote de verificacoes todo `k1_ok`, ou o
    caso `kyc` aprovado na fila de revisao. Um segundo predicado aqui era uma
    segunda resposta a mesma pergunta. So se pergunta no **nascimento** da linha:
    um `INSERT ... ON CONFLICT` sobre um tenant que ja tem nivel passa por este
    *trigger* antes de o conflito se detectar, e nao e um nascimento.
    """
    op.execute(
        """
        CREATE FUNCTION platform.trust_level_guardar()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_caso uuid;
        BEGIN
          PERFORM pg_advisory_xact_lock(
            hashtextextended('platform.trust_level:' || NEW.tenant_id::text, 0));
          IF TG_OP = 'UPDATE' THEN
            IF NEW.tenant_id <> OLD.tenant_id THEN
              RAISE EXCEPTION 'trust_level: o tenant de uma linha nao muda'
                USING ERRCODE = 'check_violation';
            END IF;
            NEW.desde := CASE WHEN NEW.nivel <> OLD.nivel THEN now() ELSE OLD.desde END;
            NEW.alterado_em := now();
            RETURN NEW;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM platform.trust_level t WHERE t.tenant_id = NEW.tenant_id) THEN
            SELECT c.id INTO v_caso FROM platform.onboarding_case c WHERE c.tenant_id = NEW.tenant_id;
            IF v_caso IS NULL OR 'kyc' = ANY (platform.aprovacao_em_falta(v_caso)) THEN
              RAISE EXCEPTION 'trust_level: sem K1 completo nao ha nivel (KAM-096, criterio 2)'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          NEW.desde := now();
          NEW.alterado_em := now();
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.trust_level_guardar() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER trust_level_guardar
          BEFORE INSERT OR UPDATE ON platform.trust_level
          FOR EACH ROW EXECUTE FUNCTION platform.trust_level_guardar()
        """
    )
    op.execute("ALTER TABLE platform.trust_level ENABLE ALWAYS TRIGGER trust_level_guardar")


def _auditar() -> None:
    """Cada alteracao do tecto no `audit_log`, com o actor da linha.

    O nascimento pelo superutilizador nao se audita: ver o cabecalho.
    """
    op.execute(
        """
        CREATE FUNCTION platform.trust_level_auditar()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF TG_OP = 'INSERT'
             AND (SELECT r.rolsuper FROM pg_catalog.pg_roles r WHERE r.rolname = current_user) THEN
            RETURN NULL;
          END IF;
          PERFORM platform.audit_append(
            NEW.tenant_id,
            CASE WHEN NEW.actor LIKE 'sistema:%' THEN 'system' ELSE 'staff' END,
            NEW.actor, 'trust.tecto', 'trust_level', NEW.tenant_id::text, NULL,
            sha256(convert_to(
              NEW.nivel::text || chr(31) || NEW.tecto_pedido_minor::text || chr(31) ||
              NEW.currency || chr(31) || NEW.motivo || chr(31) || NEW.versao_config,
              'UTF8')));
          RETURN NULL;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.trust_level_auditar() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER trust_level_auditado
          AFTER INSERT OR UPDATE ON platform.trust_level
          FOR EACH ROW EXECUTE FUNCTION platform.trust_level_auditar()
        """
    )
    op.execute("ALTER TABLE platform.trust_level ENABLE ALWAYS TRIGGER trust_level_auditado")


def _tecto_na_cobranca() -> None:
    """A cobranca de encomenda acima do tecto nao entra.

    O tecto e **por pedido**, e por isso le-se o `total_minor` da encomenda e nao
    so o montante da cobranca: a `payment_charges_activa_uq` so cobre os estados
    activos, e uma encomenda de 200 000 Kz cobrada em quatro tentativas de
    50 000 passava uma a uma. Uma cobranca acima do total tambem nao passa.

    So as de **encomenda** (`order_id` preenchido): a cobranca de um ciclo de
    *billing* e receita da plataforma (KAM-059), nao uma venda da PME, e o tecto
    de confianca limita o dano de um registo falso a vender. Sem linha de nivel
    a cobranca e recusada: sem K1 nao ha nivel, e sem nivel nao ha producao.
    """
    op.execute(
        """
        CREATE FUNCTION platform.payment_charge_dentro_do_tecto()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_tecto bigint;
          v_total bigint;
        BEGIN
          IF NEW.order_id IS NULL THEN
            RETURN NEW;
          END IF;
          PERFORM pg_advisory_xact_lock_shared(
            hashtextextended('platform.trust_level:' || NEW.tenant_id::text, 0));
          SELECT t.tecto_pedido_minor INTO v_tecto
            FROM platform.trust_level t WHERE t.tenant_id = NEW.tenant_id;
          IF v_tecto IS NULL THEN
            RAISE EXCEPTION 'cobranca recusada: o tenant nao tem nivel de confianca (KAM-096)'
              USING ERRCODE = 'check_violation';
          END IF;
          SELECT o.total_minor INTO v_total
            FROM platform.orders_mirror o
           WHERE o.tenant_id = NEW.tenant_id AND o.id = NEW.order_id;
          -- Sem encomenda visivel, quem recusa e a FK composta da `0035`, com o
          -- codigo dela (23503): recusar aqui antes dela tirava-lhe a voz.
          IF NEW.amount_minor > v_tecto OR coalesce(v_total, 0) > v_tecto THEN
            RAISE EXCEPTION 'cobranca recusada: acima do tecto de confianca do tenant (KAM-096)'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.payment_charge_dentro_do_tecto() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER payment_charges_dentro_do_tecto
          BEFORE INSERT ON platform.payment_charges
          FOR EACH ROW EXECUTE FUNCTION platform.payment_charge_dentro_do_tecto()
        """
    )
    op.execute(
        "ALTER TABLE platform.payment_charges ENABLE ALWAYS TRIGGER payment_charges_dentro_do_tecto"
    )


def _alargar_o_dominio_da_accao() -> None:
    """O `trust.tecto` no `CHECK` do `audit_log`, com `NO FORCE` a volta (`0038`)."""
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0062}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Desce, e **recusa** se o `audit_log` ja tem linhas `trust.tecto`."""
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql("SELECT count(*) FROM platform.audit_log WHERE action = 'trust.tecto'")
        .scalar_one()
    )
    if linhas:
        raise RuntimeError(
            f"downgrade da 0062 recusado: ha {linhas} linha(s) de audit_log com "
            "accao trust.tecto e o dominio da 0048 nao as aceita. O audit_log e "
            "append-only e nenhum papel tem DELETE: exporte a cadeia e decida o que "
            "fazer a essas linhas antes de descer."
        )
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0048}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")

    op.execute("REVOKE SELECT (tenant_id, contact_id, merged_into) ON platform.contacts FROM kamba_batch")
    op.execute("DROP TRIGGER payment_charges_dentro_do_tecto ON platform.payment_charges")
    op.execute("DROP FUNCTION platform.payment_charge_dentro_do_tecto()")
    rls.disable_tenant_rls("trust_level")
    op.execute("DROP TABLE platform.trust_level")
    op.execute("DROP FUNCTION platform.trust_level_auditar()")
    op.execute("DROP FUNCTION platform.trust_level_guardar()")
