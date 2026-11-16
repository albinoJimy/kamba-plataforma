"""KPIs de onboarding, sinais de churn e tenants dormentes (KAM-117).

## O que esta revisao cria

* `platform.churn_signal_episode` — um **episodio** de sinal por linha: abre
  quando a condicao passa a valer, fecha (`fechado_at`) na primeira corrida em
  que deixa de valer. Seis sinais: os cinco do criterio 2 e o `dormente`. O
  indice unico parcial `(tenant_id, sinal) WHERE fechado_at IS NULL` e o que da
  «1x por episodio»: duas corridas no mesmo dia nao abrem duas linhas. RLS
  `FORCE` pela `tenant_iso`; so o `kamba_batch` escreve, e so as quatro colunas
  do fecho, do aviso e do orcamento; ninguem apaga. **O orcamento so vai a zero
  depois do aviso** (`churn_signal_episode_orcamento_ck`): sem `avisado_at` nao
  ha `orcamento_zerado_at`, e e a base que o diz.
* `platform.churn_dono_at(tenant, agora)` — o instante da ultima actividade do
  dono: o *echo* da app do dono (`channel_coexistence.ultimo_echo_em`, que so
  conta *echoes* que nao sao nossos), qualquer linha do `audit_log` com
  `actor_type = 'owner'` (o painel do KAM-099 escreve `price.update` e
  `stock.adjust` como `owner`), e, como piso, a **primeira** entrada do tenant
  em `ativo`. O piso existe para que um tenant activado ha tres dias nao tenha
  «7 dias sem actividade»; e a primeira e nao a ultima porque um levantamento
  de `restrito` para `ativo` e da equipa e nao do dono, e nao reinicia relogios.
* `platform.churn_sinais(agora, limiares)` — os sinais que valem **agora** para
  cada tenant `ativo`. O relogio e os limiares sao parametros: o *job* passa o
  `config/kpis.yaml`, e um ensaio passa um relogio fixo. **Falha fechada**: um
  limiar em falta, nulo ou nao positivo levanta `22023`, e nao devolve zero
  sinais.
* `platform.v_churn_signals` e `platform.v_tenant_dormente` —
  `security_invoker`, os episodios abertos. Sem `contact_id`, telefone, nome
  nem conteudo: so `tenant_id`, o sinal e instantes.
* `platform.v_onboarding_kpis_semanal` — **consome** a `v_onboarding_kpis` do
  KAM-092 (nao a duplica) e a `v_review_sla` do KAM-089: por semana de
  activacao (`Africa/Luanda`) e acumulado (`acumulado = true`, `semana` nula),
  os quatro KPIs de onboarding e a fila de excepcoes. A fila **exclui** os casos
  em recurso: o recurso reescreve o `sla_due_at` com o prazo dele, e a primeira
  decisao ficava medida contra o prazo errado.
* Duas accoes novas no dominio do `audit_log.action`: `llm.orcamento_zerado` e
  `llm.orcamento_reposto`, as acções do criterio 6 sobre o orcamento da chave
  LiteLLM de um dormente.

## As fronteiras

`dono_inactivo` dispara com `dono_at <= agora - 7 dias` (6 d 23 h nao dispara,
7 d dispara); o mesmo `<=` nos outros tres limiares em dias. O `dormente` abre
`dormente_aviso_dias` antes (o aviso), e so e «pleno» com **mais de**
`dormente_dias` (`<`, porque o bloco escreve «> 60 dias»). O pagamento conta em
**dias de calendario de Luanda** desde o inicio do ciclo: o ciclo nao tem coluna
de vencimento (`0055`), e o inicio do periodo e o vencimento *proposta*.

## O que fica de fora

* **Recursos orfaos**: a reconciliacao nocturna do KAM-091 so os conta num
  *gauge* em memoria (`saga_orfaos`); nenhuma tabela os guarda, e a vista nao
  os pode ler.
* **O canal desligado** le o estado actual da `tenant_channels`, que nao tem
  instante de mudanca: o sinal e «imediato» na corrida seguinte.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0063"
#: **Provisorio**: encaixa na `0062` do KAM-096, que corre em paralelo. O numero
#: final e a ordem da cadeia da-os a integracao.
down_revision = "0062"
branch_labels = None
depends_on = None

EPISODIOS = "platform.churn_signal_episode"
AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"

PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"

#: Os cinco sinais do criterio 2 e o `dormente`. Igual ao `SINAIS` do
#: `kamba_core.kpis.metricas` mais o `dormente`, por ensaio.
SINAIS = (
    "'dono_inactivo'",
    "'sem_pedidos'",
    "'canal_desligado'",
    "'pagamento_em_atraso'",
    "'catalogo_desactualizado'",
    "'dormente'",
)

#: As chaves do `jsonb` dos limiares. As mesmas do `config/kpis.yaml`, menos o
#: `modo_ensaio_dias`, que e do *job* e nao da funcao.
CHAVES_DOS_LIMIARES = (
    "'dono_sem_actividade_dias'",
    "'sem_pedidos_dias'",
    "'pagamento_em_atraso_dias'",
    "'catalogo_desactualizado_dias'",
    "'dormente_dias'",
    "'dormente_janela_clientes_dias'",
    "'dormente_aviso_dias'",
)

#: O dominio da accao depois desta revisao: o da `0048` e as duas do orcamento.
#: Copiado e nao importado: uma revisao nao importa outra.
LITERAIS_DE_ACCAO_KPIS = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado', "
    "'order.refund_record', "
    "'review.acesso', 'review.recusa', "
    "'llm.orcamento_zerado', 'llm.orcamento_reposto'"
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

DONO_AT = "platform.churn_dono_at(uuid, timestamptz)"
CHURN_SINAIS = "platform.churn_sinais(timestamptz, jsonb)"


def upgrade() -> None:
    _episodios()
    _funcoes()
    _vistas()
    _accoes_de_auditoria()
    _privilegios()


def _episodios() -> None:
    op.execute(
        f"""
        CREATE TABLE {EPISODIOS} (
          id                    uuid CONSTRAINT churn_signal_episode_pkey PRIMARY KEY
                                DEFAULT gen_random_uuid(),
          tenant_id             uuid NOT NULL
                                CONSTRAINT churn_signal_episode_tenant_fk
                                REFERENCES platform.tenants (id),
          sinal                 text NOT NULL
                                CONSTRAINT churn_signal_episode_sinal_ck
                                CHECK (sinal IN ({", ".join(SINAIS)})),
          aberto_at             timestamptz NOT NULL,
          fechado_at            timestamptz,
          ensaio                boolean NOT NULL,
          avisado_at            timestamptz,
          orcamento_zerado_at   timestamptz,
          orcamento_reposto_at  timestamptz,
          CONSTRAINT churn_signal_episode_fecho_ck
            CHECK (fechado_at IS NULL OR fechado_at >= aberto_at),
          CONSTRAINT churn_signal_episode_aviso_ck
            CHECK (avisado_at IS NULL
                   OR (sinal = 'dormente' AND avisado_at >= aberto_at)),
          CONSTRAINT churn_signal_episode_orcamento_ck
            CHECK (orcamento_zerado_at IS NULL
                   OR (sinal = 'dormente' AND avisado_at IS NOT NULL
                       AND orcamento_zerado_at >= avisado_at)),
          CONSTRAINT churn_signal_episode_reposicao_ck
            CHECK (orcamento_reposto_at IS NULL
                   OR (orcamento_zerado_at IS NOT NULL
                       AND orcamento_reposto_at >= orcamento_zerado_at))
        )
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX churn_signal_episode_aberto_uq ON {EPISODIOS} "
        "(tenant_id, sinal) WHERE fechado_at IS NULL"
    )
    op.execute(
        f"CREATE INDEX churn_signal_episode_tenant_idx ON {EPISODIOS} (tenant_id, aberto_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {EPISODIOS} IS "
        "'Episodios de sinal de churn e de dormente (KAM-117). Um aberto por "
        "(tenant, sinal); fecha na primeira corrida em que a condicao deixa de "
        "valer. So o lote escreve; ninguem apaga.'"
    )
    rls.enable_tenant_rls("churn_signal_episode")


def _funcoes() -> None:
    op.execute(
        """
        CREATE FUNCTION platform.churn_dono_at(p_tenant_id uuid, p_agora timestamptz)
          RETURNS timestamptz
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT greatest(
                   coalesce((SELECT min(l.em) FROM platform.tenant_state_log l
                              WHERE l.tenant_id = p_tenant_id AND l.para = 'ativo'
                                AND l.em <= p_agora),
                            (SELECT t.criado_at FROM platform.tenants t
                              WHERE t.id = p_tenant_id)),
                   (SELECT max(c.ultimo_echo_em) FROM platform.channel_coexistence c
                     WHERE c.tenant_id = p_tenant_id AND c.ultimo_echo_em <= p_agora),
                   (SELECT max(a.criado_at) FROM platform.audit_log a
                     WHERE a.tenant_id = p_tenant_id AND a.actor_type = 'owner'
                       AND a.criado_at <= p_agora))
        $$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {DONO_AT} IS "
        "'Ultima actividade do dono ate agora (KAM-117): echo da app do dono, "
        "linha owner do audit_log, e como piso a entrada em ativo.'"
    )

    op.execute(
        f"""
        CREATE FUNCTION platform.churn_sinais(p_agora timestamptz, p_limiares jsonb)
          RETURNS TABLE (tenant_id uuid, sinal text, referencia_at timestamptz,
                         dormente_pleno boolean)
          LANGUAGE plpgsql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_dono     integer;
          v_pedidos  integer;
          v_pagar    integer;
          v_catalogo integer;
          v_dormente integer;
          v_janela   integer;
          v_aviso    integer;
          v_hoje     date;
          v_chave    text;
        BEGIN
          IF p_agora IS NULL OR p_limiares IS NULL
             OR jsonb_typeof(p_limiares) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'churn_sinais sem relogio ou sem limiares'
              USING ERRCODE = 'invalid_parameter_value';
          END IF;
          -- **Falha fechada**: um limiar em falta, nulo, nao inteiro ou nao
          -- positivo levanta, e nao devolve zero sinais. Ate cinco digitos: um
          -- numero maior nao e um limiar em dias, e nao rebenta o `::int`.
          FOREACH v_chave IN ARRAY ARRAY[{", ".join(CHAVES_DOS_LIMIARES)}] LOOP
            IF (p_limiares->>v_chave) IS NULL
               OR (p_limiares->>v_chave) !~ '^[0-9]{{1,5}}$'
               OR (p_limiares->>v_chave)::int <= 0 THEN
              RAISE EXCEPTION 'limiar % em falta ou invalido', v_chave
                USING ERRCODE = 'invalid_parameter_value';
            END IF;
          END LOOP;
          v_dono     := (p_limiares->>'dono_sem_actividade_dias')::int;
          v_pedidos  := (p_limiares->>'sem_pedidos_dias')::int;
          v_pagar    := (p_limiares->>'pagamento_em_atraso_dias')::int;
          v_catalogo := (p_limiares->>'catalogo_desactualizado_dias')::int;
          v_dormente := (p_limiares->>'dormente_dias')::int;
          v_janela   := (p_limiares->>'dormente_janela_clientes_dias')::int;
          v_aviso    := (p_limiares->>'dormente_aviso_dias')::int;
          IF v_aviso >= v_dormente THEN
            RAISE EXCEPTION 'dormente_aviso_dias tem de ser menor do que dormente_dias'
              USING ERRCODE = 'invalid_parameter_value';
          END IF;
          v_hoje := (p_agora AT TIME ZONE 'Africa/Luanda')::date;

          RETURN QUERY
          WITH t AS (
            SELECT tn.id AS tid,
                   coalesce((SELECT min(l.em) FROM platform.tenant_state_log l
                              WHERE l.tenant_id = tn.id AND l.para = 'ativo'
                                AND l.em <= p_agora),
                            tn.criado_at) AS ativo_desde
              FROM platform.tenants tn
             WHERE tn.estado = 'ativo'
          ), a AS (
            SELECT t.tid,
                   platform.churn_dono_at(t.tid, p_agora) AS dono_at,
                   (SELECT max(o.criado_at) FROM platform.orders_mirror o
                     WHERE o.tenant_id = t.tid AND o.criado_at <= p_agora) AS pedido_at,
                   greatest(t.ativo_desde,
                            (SELECT max(au.criado_at) FROM platform.audit_log au
                              WHERE au.tenant_id = t.tid AND au.entity = 'offer_terms'
                                AND au.action IN ('price.update', 'stock.adjust')
                                AND au.criado_at <= p_agora)) AS catalogo_at,
                   (SELECT max(cv.last_inbound_at) FROM platform.conversations cv
                     WHERE cv.tenant_id = t.tid AND cv.last_inbound_at <= p_agora)
                     AS cliente_at,
                   EXISTS (SELECT 1 FROM platform.tenant_channels ch
                            WHERE ch.tenant_id = t.tid AND ch.estado = 'desligado')
                     AND NOT EXISTS (SELECT 1 FROM platform.tenant_channels ch
                                      WHERE ch.tenant_id = t.tid
                                        AND ch.estado IN ('pendente', 'ativo', 'restrito'))
                     AS canal_desligado,
                   (SELECT min(lower(b.periodo)) FROM platform.billing_cycles b
                     WHERE b.tenant_id = t.tid
                       AND b.estado IN ('cobranca_emitida', 'em_atraso')) AS divida_desde,
                   t.ativo_desde
              FROM t
          )
          SELECT a.tid, 'dono_inactivo'::text, a.dono_at, NULL::boolean FROM a
           WHERE a.dono_at <= p_agora - make_interval(days => v_dono)
          UNION ALL
          SELECT a.tid, 'sem_pedidos', greatest(a.ativo_desde, a.pedido_at), NULL FROM a
           WHERE greatest(a.ativo_desde, a.pedido_at)
                 <= p_agora - make_interval(days => v_pedidos)
          UNION ALL
          SELECT a.tid, 'canal_desligado', NULL::timestamptz, NULL FROM a
           WHERE a.canal_desligado
          UNION ALL
          SELECT a.tid, 'pagamento_em_atraso',
                 (a.divida_desde::timestamp AT TIME ZONE 'Africa/Luanda'), NULL FROM a
           WHERE a.divida_desde + v_pagar <= v_hoje
          UNION ALL
          SELECT a.tid, 'catalogo_desactualizado', a.catalogo_at, NULL FROM a
           WHERE a.catalogo_at <= p_agora - make_interval(days => v_catalogo)
          UNION ALL
          -- **Nunca com mensagens de clientes na janela**: e a condicao que o
          -- criterio 5 manda provar, e vive aqui e outra vez no *job*, dentro da
          -- transaccao que zera o orcamento.
          SELECT a.tid, 'dormente', a.dono_at,
                 a.dono_at < p_agora - make_interval(days => v_dormente) FROM a
           WHERE a.dono_at <= p_agora - make_interval(days => v_dormente - v_aviso)
             AND coalesce(a.pedido_at, '-infinity') <= p_agora - make_interval(days => v_janela)
             AND coalesce(a.cliente_at, '-infinity') <= p_agora - make_interval(days => v_janela);
        END
        $$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {CHURN_SINAIS} IS "
        "'Sinais de churn e dormente que valem agora por tenant ativo (KAM-117). "
        "Relogio e limiares por parametro; falha fechada num limiar invalido.'"
    )


def _vistas() -> None:
    op.execute(
        f"""
        CREATE VIEW platform.v_churn_signals WITH (security_invoker = true) AS
        SELECT e.tenant_id, e.sinal, e.aberto_at, e.ensaio
          FROM {EPISODIOS} e
         WHERE e.fechado_at IS NULL AND e.sinal <> 'dormente'
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_churn_signals IS "
        "'Sinais de churn abertos por tenant (KAM-117). Sem contacto nem conteudo.'"
    )
    op.execute(
        f"""
        CREATE VIEW platform.v_tenant_dormente WITH (security_invoker = true) AS
        SELECT e.tenant_id,
               e.aberto_at,
               e.avisado_at,
               e.orcamento_zerado_at,
               e.orcamento_zerado_at IS NOT NULL AS orcamento_a_zero,
               e.ensaio
          FROM {EPISODIOS} e
         WHERE e.fechado_at IS NULL AND e.sinal = 'dormente'
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_tenant_dormente IS "
        "'A marca de dormente (KAM-117): nao e um estado do tenant. Inclui a "
        "fase de aviso; avisado_at e quando o aviso ao dono saiu, e o orcamento "
        "so vai a zero depois dele.'"
    )
    op.execute(
        """
        CREATE VIEW platform.v_onboarding_kpis_semanal WITH (security_invoker = true) AS
        WITH activados AS (
          SELECT date_trunc('week', c.activo_at AT TIME ZONE 'Africa/Luanda')::date AS semana,
                 k.owner_active_seconds, k.dias_calendario, k.intervencao_humana,
                 k.saga_primeira_tentativa
            FROM platform.v_onboarding_kpis k
            JOIN platform.onboarding_case c ON c.id = k.onboarding_id
           WHERE k.fase = 'activo' AND c.activo_at IS NOT NULL
        ), a AS (
          SELECT GROUPING(semana) = 1 AS acumulado,
                 semana,
                 count(*) AS casos_activados,
                 percentile_cont(0.5) WITHIN GROUP (ORDER BY owner_active_seconds) / 60
                   AS owner_active_minutos_mediana,
                 percentile_cont(0.5) WITHIN GROUP (ORDER BY dias_calendario)
                   AS dias_calendario_mediana,
                 avg(CASE WHEN intervencao_humana THEN 0 ELSE 1 END)
                   AS sem_intervencao_ratio,
                 avg(CASE WHEN saga_primeira_tentativa THEN 1 ELSE 0 END)
                   FILTER (WHERE saga_primeira_tentativa IS NOT NULL)
                   AS saga_primeira_tentativa_ratio
            FROM activados
           GROUP BY GROUPING SETS ((semana), ())
        ), fila AS (
          SELECT date_trunc('week', s.fila_at AT TIME ZONE 'Africa/Luanda')::date AS semana,
                 (s.primeira_decisao_at IS NOT NULL
                  AND s.primeira_decisao_at <= s.sla_due_at) AS no_sla
            FROM platform.v_review_sla s
            JOIN platform.review_case r ON r.id = s.case_id
           WHERE r.onboarding_id IS NOT NULL AND s.tipo <> 'auditoria'
             AND s.estado NOT IN ('recurso_aberto', 'decidido_final')
             AND (s.primeira_decisao_at IS NOT NULL OR s.sla_due_at <= now())
        ), f AS (
          SELECT GROUPING(semana) = 1 AS acumulado,
                 semana,
                 count(*) AS fila_casos,
                 avg(CASE WHEN no_sla THEN 1 ELSE 0 END) AS fila_no_sla_ratio
            FROM fila
           GROUP BY GROUPING SETS ((semana), ())
        )
        SELECT coalesce(a.acumulado, f.acumulado) AS acumulado,
               coalesce(a.semana, f.semana) AS semana,
               coalesce(a.casos_activados, 0) AS casos_activados,
               a.owner_active_minutos_mediana,
               a.dias_calendario_mediana,
               a.sem_intervencao_ratio,
               a.saga_primeira_tentativa_ratio,
               coalesce(f.fila_casos, 0) AS fila_casos,
               f.fila_no_sla_ratio
          FROM a
          FULL JOIN f
            ON a.acumulado = f.acumulado
           AND coalesce(a.semana, '-infinity'::date) = coalesce(f.semana, '-infinity'::date)
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_onboarding_kpis_semanal IS "
        "'KPIs de onboarding por semana de activacao (Africa/Luanda) e acumulado "
        "(KAM-117), sobre a v_onboarding_kpis (KAM-092) e a v_review_sla (KAM-089). "
        "A fila conta os casos decididos ou ja vencidos; no_sla e a 1a decisao "
        "ate ao sla_due_at, que ja e de 1 dia util.'"
    )


def _accoes_de_auditoria() -> None:
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_KPIS}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")


def _privilegios() -> None:
    op.execute(f"REVOKE ALL ON {EPISODIOS} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON {EPISODIOS} TO {PAPEL_DE_LOTE}")
    op.execute(
        f"GRANT UPDATE (fechado_at, avisado_at, orcamento_zerado_at, orcamento_reposto_at) "
        f"ON {EPISODIOS} TO {PAPEL_DE_LOTE}"
    )
    op.execute(f"GRANT SELECT ON {EPISODIOS} TO {PAPEL_DE_AUDITORIA}")
    for vista in ("v_churn_signals", "v_tenant_dormente", "v_onboarding_kpis_semanal"):
        op.execute(f"REVOKE ALL ON platform.{vista} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON platform.{vista} TO {PAPEL_DE_LOTE}")
    for vista in ("v_churn_signals", "v_tenant_dormente"):
        op.execute(f"GRANT SELECT ON platform.{vista} TO {PAPEL_DE_AUDITORIA}")
    for funcao in (DONO_AT, CHURN_SINAIS):
        op.execute(f"REVOKE ALL ON FUNCTION {funcao} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {funcao} TO {PAPEL_DE_LOTE}")


def downgrade() -> None:
    """Desce, e **recusa** se o `audit_log` ja tem linhas das duas accoes novas.

    A contagem corre com o `FORCE` desligado: com ele, o dono ve zero linhas e a
    guarda passava sempre (a armadilha que o KAM-050 mediu na `0038`). Os
    episodios **nao** guardam a descida: sao recalculaveis pelo *job*, e a
    accao que conta (zerar ou repor um orcamento) esta no `audit_log`.
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log "
            "WHERE action IN ('llm.orcamento_zerado', 'llm.orcamento_reposto')"
        )
        .scalar_one()
    )
    if linhas:
        raise RuntimeError(
            f"downgrade da 0063 recusado: ha {linhas} linha(s) de audit_log com "
            "accao llm.orcamento_* e o dominio da 0048 nao as aceita. O audit_log "
            "e append-only e nenhum papel tem DELETE: exporte a cadeia e decida o "
            "que fazer a essas linhas antes de descer."
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

    op.execute("DROP VIEW platform.v_onboarding_kpis_semanal")
    op.execute("DROP VIEW platform.v_tenant_dormente")
    op.execute("DROP VIEW platform.v_churn_signals")
    op.execute(f"DROP FUNCTION {CHURN_SINAIS}")
    op.execute(f"DROP FUNCTION {DONO_AT}")
    rls.disable_tenant_rls("churn_signal_episode")
    op.execute(f"DROP TABLE {EPISODIOS}")
