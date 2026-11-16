"""Eventos do tenant: gates de activacao, transicoes, agregador e KPIs (KAM-092).

## O que esta revisao cria

* `platform.onboarding_gate` — os **seis** gates de activacao de um caso
  (`meta_es`, `meta_pagamento`, `catalogo_minimo`, `consentimento`, `dpa`,
  `e2e`), um por linha, com o ultimo valor. RLS `FORCE` pelo `tenant_id`
  pre-alocado do caso, e FK **composta** para o caso: o gate de um caso nao
  junta o tenant de outro. **So o lote os escreve**: os gates sao a condicao da
  activacao, e um contexto de tenant que os pusesse a verde activava-se a si
  proprio (a razao da emenda 1.18 para tirar o `UPDATE` de `tenants.estado` a
  `kamba_app`). A aplicacao le-os, para o painel do dono. O `em` e do *trigger*.
* `platform.tenant_state_log` — cada transicao de `tenants.estado`, *append-only*
  por privilegio **e** por *trigger* (`55000` tambem ao dono, porque o `REVOKE`
  nao prende o dono da tabela).
* `platform.tenant_transicoes()` — as **oito** arestas do `docs/tecnica/00`
  §6.2, e so elas.
* `platform.transition_tenant(tenant, para, motivo, actor)` — a unica porta de
  transicao do tenant que este ticket entrega. Recusa (`23514`) o que nao e
  aresta; repetir a transicao em que o tenant ja esta devolve `false` sem
  registo nem evento; corre **sob `app.tenant_id`** do proprio tenant (`42501`
  fora dele); `onboarding -> ativo` exige o caso em `aguarda_teste` e os seis
  gates verdes, poe o caso em `activo` e emite `tenant.activated`, tudo na mesma
  transaccao.
* `platform.onboarding_transicoes()` e `platform.advance_case(caso, evento,
  actor)` — os sub-estados do caso (PA-GOV-6) por evento, e os dois pontos em
  que a maquina emite: `aprovar`/`recurso_aprovado` emitem `tenant.approved` (e
  so com `platform.aprovacao_em_falta` vazio), e `es_concluido` emite
  `tenant.provisioned`. `activar` delega no `transition_tenant`.
* `platform.onboarding_gates_em_falta(caso)` e
  `platform.aprovacao_em_falta(caso)` — as duas perguntas, cada uma numa funcao
  so, como o `contrato_em_falta` do KAM-090.
* `platform.v_onboarding_kpis` (por caso) e `platform.v_onboarding_kpis_agregado`
  (mediana e p90), `security_invoker`.
* O `kamba_batch` passa a poder emitir: `EXECUTE` no `evt_emitir`, `INSERT` no
  *outbox* e `SELECT, INSERT, UPDATE (seq)` na sequencia. As duas portas correm
  como ele, porque e o unico papel com `UPDATE` em `tenants.estado`.

## A idempotencia vem do estado, e nao do (agregado, seq)

O `evt_emitir` da um `seq` novo a cada chamada, pelo que a unicidade
`(tenant_id, agregado_tipo, agregado_id, agregado_seq)` do *outbox* impede dois
eventos com o mesmo `seq` e **nao** impede o segundo evento. O que da «2x a
mesma transicao, 1 evento» e o `SELECT ... FOR UPDATE` sobre a linha do caso ou
do tenant: a segunda transaccao espera pela primeira, ve o estado de destino e
devolve sem emitir. A unicidade do *outbox* e o que garante que os dois `seq`
nao colidem quando ha duas transicoes diferentes.

## O que fica de fora

* **Ninguem chama ainda as duas portas.** O `ServicoDeRevisao` escreve `aprovado`
  com um `UPDATE` directo, e o `decidir` do KYC nao muda a fase num `k1_ok`;
  liga-los ao `advance_case` (e ao `amostrar` do KAM-089) e trabalho de
  TypeScript sobre suites de outros tickets, e fica com credor no bloco.
* **Eventos das outras arestas** (`tenant.suspended`, `.reactivated`,
  `.closed`): o `transition_tenant` regista-as e nao as emite. O `motivo` e
  texto livre, e um texto livre num *payload* e a superficie de PII que o
  contrato fechado existe para nao ter.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0058"
#: **Encaixa na `0057` do KAM-124** (#199), pela ordem da fila que o orquestrador
#: do lote deu a 2026-11-16. Foi escrita como `0057` sobre a `0056` do KAM-097 e
#: renumerada na integracao.
down_revision = "0057"
branch_labels = None
depends_on = None

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"

GATES = "platform.onboarding_gate"
REGISTO = "platform.tenant_state_log"
CASOS = "platform.onboarding_case"

#: Os seis gates do criterio 3, pela ordem do bloco.
GATES_DE_ACTIVACAO = (
    "'meta_es'",
    "'meta_pagamento'",
    "'catalogo_minimo'",
    "'consentimento'",
    "'dpa'",
    "'e2e'",
)

#: Os cinco estados de `tenants.estado` (`tenants_estado_ck`, revisao 0001).
ESTADOS_DO_TENANT = (
    "'onboarding'",
    "'ativo'",
    "'restrito'",
    "'suspenso'",
    "'encerrado'",
)

#: A assinatura do `evt_emitir` (revisao 0004), para o `GRANT` e o `REVOKE`.
ARGUMENTOS_DE_EVT_EMITIR = (
    "text, smallint, uuid, text, text, jsonb, text, text[], uuid, uuid, text, "
    "text, timestamptz"
)

TRANSITION_TENANT = "platform.transition_tenant(uuid, text, text, text)"
ADVANCE_CASE = "platform.advance_case(uuid, text, text)"
GATES_EM_FALTA = "platform.onboarding_gates_em_falta(uuid)"
APROVACAO_EM_FALTA = "platform.aprovacao_em_falta(uuid)"
TRANSICOES_DO_TENANT = "platform.tenant_transicoes()"
TRANSICOES_DO_CASO = "platform.onboarding_transicoes()"
REVISAO_APROVADA = "platform.revisao_aprovada(uuid, uuid, text)"
EVENTO_EMITIDO = "platform.evento_emitido(uuid, text)"


def upgrade() -> None:
    _gates()
    _registo()
    _perguntas()
    _transicoes()
    _vistas()
    _privilegios()


def _gates() -> None:
    op.execute(
        f"""
        CREATE TABLE {GATES} (
          onboarding_id  uuid NOT NULL,
          tenant_id      uuid NOT NULL,
          gate           text NOT NULL
                         CONSTRAINT onboarding_gate_gate_ck
                         CHECK (gate IN ({", ".join(GATES_DE_ACTIVACAO)})),
          ok             boolean NOT NULL,
          evidencia_ref  text
                         CONSTRAINT onboarding_gate_evidencia_ck
                         CHECK (length(evidencia_ref) BETWEEN 1 AND 200),
          em             timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT onboarding_gate_pkey PRIMARY KEY (onboarding_id, gate),
          CONSTRAINT onboarding_gate_caso_fk FOREIGN KEY (onboarding_id, tenant_id)
            REFERENCES {CASOS} (id, tenant_id)
        )
        """
    )
    op.execute(f"CREATE INDEX onboarding_gate_tenant_idx ON {GATES} (tenant_id)")
    op.execute(
        f"COMMENT ON TABLE {GATES} IS "
        "'Os seis gates de activacao de um caso, com o ultimo valor (KAM-092). "
        "So o lote escreve; o em e do trigger.'"
    )
    # O `em` e da base: em qualquer `INSERT` e em qualquer `UPDATE`.
    op.execute(
        f"""
        CREATE FUNCTION platform.onboarding_gate_em()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          NEW.em := now();
          RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.onboarding_gate_em() FROM PUBLIC")
    op.execute(
        f"""
        CREATE TRIGGER onboarding_gate_em
          BEFORE INSERT OR UPDATE ON {GATES}
          FOR EACH ROW EXECUTE FUNCTION platform.onboarding_gate_em()
        """
    )
    op.execute(f"ALTER TABLE {GATES} ENABLE ALWAYS TRIGGER onboarding_gate_em")
    rls.enable_tenant_rls("onboarding_gate")


def _registo() -> None:
    op.execute(
        f"""
        CREATE TABLE {REGISTO} (
          id         uuid CONSTRAINT tenant_state_log_pkey PRIMARY KEY
                     DEFAULT gen_random_uuid(),
          tenant_id  uuid NOT NULL
                     CONSTRAINT tenant_state_log_tenant_fk
                     REFERENCES platform.tenants (id),
          de         text NOT NULL
                     CONSTRAINT tenant_state_log_de_ck
                     CHECK (de IN ({", ".join(ESTADOS_DO_TENANT)})),
          para       text NOT NULL
                     CONSTRAINT tenant_state_log_para_ck
                     CHECK (para IN ({", ".join(ESTADOS_DO_TENANT)})),
          motivo     text NOT NULL
                     CONSTRAINT tenant_state_log_motivo_ck
                     CHECK (length(motivo) BETWEEN 1 AND 200),
          actor      text NOT NULL
                     CONSTRAINT tenant_state_log_actor_ck
                     CHECK (length(actor) BETWEEN 1 AND 120),
          em         timestamptz NOT NULL DEFAULT clock_timestamp(),
          CONSTRAINT tenant_state_log_mudanca_ck CHECK (de <> para)
        )
        """
    )
    op.execute(
        f"CREATE INDEX tenant_state_log_tenant_idx ON {REGISTO} (tenant_id, em)"
    )
    op.execute(
        f"COMMENT ON TABLE {REGISTO} IS "
        "'Cada transicao de tenants.estado pelo transition_tenant (KAM-092). "
        "Append-only por privilegio e por trigger. em por clock_timestamp: "
        "ordena duas transicoes da mesma transaccao.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.tenant_state_log_imutavel()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          RAISE EXCEPTION
            'o registo de estados do tenant nao se emenda nem se apaga'
            USING ERRCODE = 'object_not_in_prerequisite_state';
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform.tenant_state_log_imutavel() FROM PUBLIC"
    )
    op.execute(
        f"""
        CREATE TRIGGER tenant_state_log_imutavel
          BEFORE UPDATE OR DELETE ON {REGISTO}
          FOR EACH ROW EXECUTE FUNCTION platform.tenant_state_log_imutavel()
        """
    )
    op.execute(
        f"ALTER TABLE {REGISTO} ENABLE ALWAYS TRIGGER tenant_state_log_imutavel"
    )
    rls.enable_tenant_rls("tenant_state_log")


def _perguntas() -> None:
    """As duas perguntas, cada uma numa funcao so.

    **Os gates em falta** sao os seis menos os que tem `ok`. **A aprovacao em
    falta** sao tres condicoes, pelos nomes `kyc`, `screening` e `aceite`:

    * `kyc` — as verificacoes do instante mais recente do caso sao todas
      `k1_ok` (o `decidir` do KYC grava a decisao em todas as que a sustentam;
      no empate, basta uma que nao o seja), **ou** a ultima decisao de um
      `review_case` `kyc` do caso e `aprovar`;
    * `screening` — a decisao de categoria que vale (a ultima humana, se houver;
      senao a ultima) existe e nao e `bloqueada`. Sem decisao nenhuma, falta: o
      gate nao abre por ausencia;
    * `aceite` — o `contrato_em_falta` das versoes vigentes vem vazio.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.onboarding_gates_em_falta(p_onboarding_id uuid)
          RETURNS text[]
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT coalesce(array_agg(g.gate ORDER BY g.ordem), ARRAY[]::text[])
            FROM unnest(ARRAY[{", ".join(GATES_DE_ACTIVACAO)}])
                 WITH ORDINALITY AS g(gate, ordem)
           WHERE NOT EXISTS (
                   SELECT 1 FROM platform.onboarding_gate o
                    WHERE o.onboarding_id = p_onboarding_id
                      AND o.gate = g.gate
                      AND o.ok)
        $$
        """
    )
    # Se um evento do tenant ja saiu: no *outbox* ou, publicado e limpo dele, no
    # arquivo. E a prova de «ja feito por mim» da repeticao e da ordem do tripleto.
    op.execute(
        """
        CREATE FUNCTION platform.evento_emitido(p_tenant_id uuid, p_tipo text)
          RETURNS boolean
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT EXISTS (SELECT 1 FROM platform.events_outbox o
                          WHERE o.tenant_id = p_tenant_id AND o.tipo = p_tipo
                            AND o.agregado_tipo = 'tenant'
                            AND o.agregado_id = p_tenant_id::text)
              OR EXISTS (SELECT 1 FROM platform.events_log l
                          WHERE l.tenant_id = p_tenant_id AND l.tipo = p_tipo
                            AND l.agregado_tipo = 'tenant'
                            AND l.agregado_id = p_tenant_id::text)
        $$
        """
    )
    # **Todos os casos do tipo, e nao um.** A chave de abertura da fila inclui o
    # `motivo_codigo` (0048), pelo que um onboarding pode ter dois casos `kyc`:
    # um aprovado e outro rejeitado, ou por decidir, nao e uma aprovacao.
    op.execute(
        """
        CREATE FUNCTION platform.revisao_aprovada(
            p_onboarding_id uuid, p_tenant_id uuid, p_tipo text)
          RETURNS boolean
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT EXISTS (SELECT 1 FROM platform.review_case r
                          WHERE r.onboarding_id = p_onboarding_id
                            AND r.tenant_id = p_tenant_id
                            AND r.tipo = p_tipo)
             AND NOT EXISTS (
                   SELECT 1 FROM platform.review_case r
                    WHERE r.onboarding_id = p_onboarding_id
                      AND r.tenant_id = p_tenant_id
                      AND r.tipo = p_tipo
                      AND (SELECT l.decisao FROM platform.review_decision_log l
                            WHERE l.case_id = r.id
                            ORDER BY l.em DESC, l.id DESC
                            LIMIT 1) IS DISTINCT FROM 'aprovar')
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.aprovacao_em_falta(p_onboarding_id uuid)
          RETURNS text[]
          LANGUAGE plpgsql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_tenant uuid;
          v_falta  text[] := ARRAY[]::text[];
        BEGIN
          SELECT c.tenant_id INTO v_tenant
            FROM platform.onboarding_case c WHERE c.id = p_onboarding_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'caso de onboarding % nao existe', p_onboarding_id
              USING ERRCODE = 'no_data_found';
          END IF;

          IF NOT (
               coalesce((SELECT bool_and(k.resultado = 'k1_ok')
                           FROM platform.kyc_check k
                          WHERE k.onboarding_id = p_onboarding_id
                            AND k.criado_at = (SELECT max(m.criado_at)
                                                 FROM platform.kyc_check m
                                                WHERE m.onboarding_id = p_onboarding_id)),
                        false)
            OR platform.revisao_aprovada(p_onboarding_id, v_tenant, 'kyc')
          ) THEN
            v_falta := v_falta || 'kyc'::text;
          END IF;

          -- **So o mais restritivo conta, e a origem nao levanta nada.** O
          -- `kamba_app` tem `INSERT` na `screening_decision` (0044), com a
          -- `origem` que quiser: uma linha `permitida` ou `humano` dele nao pode
          -- tapar uma `bloqueada`. Levanta-a o recurso da T&S na fila (um
          -- `review_case` de `categoria` aprovado), que a aplicacao nao escreve.
          IF NOT EXISTS (SELECT 1 FROM platform.screening_decision s
                          WHERE s.onboarding_id = p_onboarding_id
                            AND s.tenant_id = v_tenant
                            AND s.sujeito_tipo = 'categoria')
             OR (EXISTS (SELECT 1 FROM platform.screening_decision s
                          WHERE s.onboarding_id = p_onboarding_id
                            AND s.tenant_id = v_tenant
                            AND s.sujeito_tipo = 'categoria'
                            AND s.decisao = 'bloqueada')
                 AND NOT platform.revisao_aprovada(p_onboarding_id, v_tenant, 'categoria'))
          THEN
            v_falta := v_falta || 'screening'::text;
          END IF;

          IF cardinality(platform.contrato_em_falta(v_tenant, true)) > 0 THEN
            v_falta := v_falta || 'aceite'::text;
          END IF;
          RETURN v_falta;
        END
        $$
        """
    )


def _transicoes() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {TRANSICOES_DO_TENANT}
          RETURNS TABLE (de text, para text)
          LANGUAGE sql
          IMMUTABLE
          SET search_path = pg_catalog, platform
        AS $$
          VALUES ('onboarding', 'ativo'),
                 ('ativo', 'restrito'),
                 ('restrito', 'ativo'),
                 ('ativo', 'suspenso'),
                 ('restrito', 'suspenso'),
                 ('suspenso', 'ativo'),
                 ('ativo', 'encerrado'),
                 ('suspenso', 'encerrado')
        $$
        """
    )
    # A maquina dos sub-estados (PA-GOV-6, proposta). **Um destino por evento**:
    # e o que deixa a repeticao de um evento ser reconhecida pelo destino.
    op.execute(
        f"""
        CREATE FUNCTION {TRANSICOES_DO_CASO}
          RETURNS TABLE (de text, evento text, para text)
          LANGUAGE sql
          IMMUTABLE
          SET search_path = pg_catalog, platform
        AS $$
          VALUES ('registo', 'otp_enviado', 'otp_pendente'),
                 ('otp_pendente', 'otp_confirmado', 'kyc_pendente'),
                 ('kyc_pendente', 'kyc_fila', 'em_revisao'),
                 ('em_revisao', 'pedir_info', 'kyc_pendente'),
                 ('kyc_pendente', 'aprovar', 'aprovado'),
                 ('em_revisao', 'aprovar', 'aprovado'),
                 ('kyc_pendente', 'rejeitar', 'rejeitado'),
                 ('em_revisao', 'rejeitar', 'rejeitado'),
                 ('rejeitado', 'recurso_aprovado', 'aprovado'),
                 ('aprovado', 'saga_iniciada', 'provisionando'),
                 ('provisionando', 'saga_concluida', 'aguarda_es'),
                 ('aguarda_es', 'es_sem_vaga', 'lista_espera'),
                 ('lista_espera', 'es_com_vaga', 'aguarda_es'),
                 ('aguarda_es', 'es_concluido', 'aguarda_catalogo'),
                 ('aguarda_catalogo', 'catalogo_minimo', 'aguarda_teste'),
                 ('aguarda_teste', 'activar', 'activo'),
                 ('registo', 'abandonar', 'abandonado'),
                 ('otp_pendente', 'abandonar', 'abandonado'),
                 ('kyc_pendente', 'abandonar', 'abandonado'),
                 ('aguarda_es', 'abandonar', 'abandonado'),
                 ('lista_espera', 'abandonar', 'abandonado'),
                 ('aguarda_catalogo', 'abandonar', 'abandonado'),
                 ('aguarda_teste', 'abandonar', 'abandonado'),
                 ('registo', 'cancelar', 'cancelado'),
                 ('otp_pendente', 'cancelar', 'cancelado'),
                 ('kyc_pendente', 'cancelar', 'cancelado'),
                 ('em_revisao', 'cancelar', 'cancelado'),
                 ('aprovado', 'cancelar', 'cancelado'),
                 ('aguarda_es', 'cancelar', 'cancelado'),
                 ('lista_espera', 'cancelar', 'cancelado'),
                 ('aguarda_catalogo', 'cancelar', 'cancelado'),
                 ('aguarda_teste', 'cancelar', 'cancelado')
        $$
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION platform.transition_tenant(
            p_tenant_id uuid, p_para text, p_motivo text, p_actor text)
          RETURNS boolean
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_de     text;
          v_plano  text;
          v_caso   platform.onboarding_case%ROWTYPE;
          v_tem_caso boolean;
          v_falta  text[];
        BEGIN
          IF p_tenant_id IS NULL
             OR current_setting('app.tenant_id', true) IS DISTINCT FROM p_tenant_id::text THEN
            RAISE EXCEPTION 'transition_tenant fora do contexto do tenant'
              USING ERRCODE = 'insufficient_privilege';
          END IF;

          -- **O caso antes do tenant**, pela mesma ordem do `advance_case`: com
          -- as duas portas a trancar em ordens opostas, uma activacao por cada
          -- uma ao mesmo tempo dava `40P01`.
          SELECT * INTO v_caso FROM platform.onboarding_case c
           WHERE c.tenant_id = p_tenant_id FOR UPDATE;
          v_tem_caso := FOUND;
          SELECT t.estado, t.plano INTO v_de, v_plano
            FROM platform.tenants t WHERE t.id = p_tenant_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'tenant % nao existe', p_tenant_id
              USING ERRCODE = 'no_data_found';
          END IF;
          IF v_de = p_para THEN
            RETURN false;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM {TRANSICOES_DO_TENANT} a
                          WHERE a.de = v_de AND a.para = p_para) THEN
            RAISE EXCEPTION 'transicao de tenant recusada: % -> %', v_de, p_para
              USING ERRCODE = 'check_violation';
          END IF;

          IF v_de = 'onboarding' THEN
            IF NOT v_tem_caso OR v_caso.fase <> 'aguarda_teste' THEN
              RAISE EXCEPTION 'tenant % sem caso em aguarda_teste', p_tenant_id
                USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            v_falta := platform.onboarding_gates_em_falta(v_caso.id);
            IF cardinality(v_falta) > 0 THEN
              RAISE EXCEPTION 'tenant sem os gates de activacao'
                USING ERRCODE = 'check_violation',
                      DETAIL = array_to_string(v_falta, ',');
            END IF;
            -- **A fase nao prova o caminho.** O `kamba_app` escreve a `fase`
            -- (`UPDATE` por coluna da 0043), pelo que `aguarda_teste` pode ter sido
            -- posta a mao: a activacao volta a perguntar ao agregador e exige os
            -- dois eventos anteriores do tripleto.
            v_falta := platform.aprovacao_em_falta(v_caso.id);
            IF NOT platform.evento_emitido(p_tenant_id, 'tenant.approved') THEN
              v_falta := v_falta || 'tenant.approved'::text;
            END IF;
            IF NOT platform.evento_emitido(p_tenant_id, 'tenant.provisioned') THEN
              v_falta := v_falta || 'tenant.provisioned'::text;
            END IF;
            IF cardinality(v_falta) > 0 THEN
              RAISE EXCEPTION 'tenant sem a aprovacao e o provisionamento'
                USING ERRCODE = 'check_violation',
                      DETAIL = array_to_string(v_falta, ',');
            END IF;
          END IF;

          UPDATE platform.tenants SET estado = p_para WHERE id = p_tenant_id;
          INSERT INTO platform.tenant_state_log (tenant_id, de, para, motivo, actor)
          VALUES (p_tenant_id, v_de, p_para, p_motivo, p_actor);

          IF v_de = 'onboarding' THEN
            UPDATE platform.onboarding_case
               SET fase = 'activo', activo_at = now()
             WHERE id = v_caso.id;
            PERFORM platform.evt_emitir(
              'tenant.activated', 1::smallint, p_tenant_id, 'tenant', p_tenant_id::text,
              jsonb_strip_nulls(jsonb_build_object(
                'onboarding_id', v_caso.id,
                'plano', v_plano,
                'owner_active_seconds', v_caso.owner_active_seconds,
                'intervencao_humana', EXISTS (
                  SELECT 1 FROM platform.review_case r
                   WHERE r.onboarding_id = v_caso.id AND r.tipo <> 'auditoria'))));
          END IF;
          RETURN true;
        END
        $$
        """
    )

    # **Os valores fixos do `tenant.approved`**, e de onde vem cada um: o plano
    # `free` e o unico com fonte (`registry/plans.yaml`, o `DEFAULT` da 0001); a
    # vertical `vendedor` e a unica que esse plano da por omissao (a nota dele);
    # o tecto e o `valor_max_pedido_minor` do `free`, nivel 0 do KAM-096. O
    # ensaio confronta os tres com o `registry/plans.yaml`.
    # shortcut: tres constantes num so plano; revem-se quando o caso tiver plano
    # proprio (KAM-109, lista de planos) ou o KAM-096 der o tecto por caso.
    op.execute(
        f"""
        CREATE FUNCTION platform.advance_case(
            p_onboarding_id uuid, p_evento text, p_actor text)
          RETURNS text
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_caso   platform.onboarding_case%ROWTYPE;
          v_para   text;
          v_falta  text[];
          v_canal  record;
          v_canais bigint;
          v_tipo   text;
        BEGIN
          SELECT * INTO v_caso FROM platform.onboarding_case c
           WHERE c.id = p_onboarding_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'caso de onboarding % nao existe', p_onboarding_id
              USING ERRCODE = 'no_data_found';
          END IF;
          IF current_setting('app.tenant_id', true) IS DISTINCT FROM v_caso.tenant_id::text THEN
            RAISE EXCEPTION 'advance_case fora do contexto do tenant do caso'
              USING ERRCODE = 'insufficient_privilege';
          END IF;

          v_tipo := CASE p_evento
                      WHEN 'aprovar' THEN 'tenant.approved'
                      WHEN 'recurso_aprovado' THEN 'tenant.approved'
                      WHEN 'es_concluido' THEN 'tenant.provisioned'
                      WHEN 'activar' THEN 'tenant.activated'
                    END;

          SELECT t.para INTO v_para FROM {TRANSICOES_DO_CASO} t
           WHERE t.de = v_caso.fase AND t.evento = p_evento;
          IF NOT FOUND THEN
            -- A repeticao: o caso ja esta onde o evento leva. Sem escrita, sem
            -- evento — **e, num evento que emite, so se o evento ja saiu**: uma
            -- fase escrita por outro caminho nao e «ja feito por mim».
            IF EXISTS (SELECT 1 FROM {TRANSICOES_DO_CASO} t
                        WHERE t.evento = p_evento AND t.para = v_caso.fase) THEN
              IF v_tipo IS NOT NULL
                 AND NOT platform.evento_emitido(v_caso.tenant_id, v_tipo) THEN
                RAISE EXCEPTION 'fase % escrita fora do advance_case: % nao saiu',
                  v_caso.fase, v_tipo
                  USING ERRCODE = 'object_not_in_prerequisite_state';
              END IF;
              RETURN v_caso.fase;
            END IF;
            RAISE EXCEPTION 'evento % recusado na fase %', p_evento, v_caso.fase
              USING ERRCODE = 'check_violation';
          END IF;

          IF p_evento = 'activar' THEN
            -- Activar e sair de `onboarding`: um tenant suspenso nao e levantado
            -- por aqui, e um ja activo com o caso por fechar e um estado partido.
            IF (SELECT t.estado FROM platform.tenants t WHERE t.id = v_caso.tenant_id)
               IS DISTINCT FROM 'onboarding' THEN
              RAISE EXCEPTION 'caso % com o tenant fora de onboarding', v_caso.id
                USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            PERFORM platform.transition_tenant(
              v_caso.tenant_id, 'ativo', 'gates de activacao cumpridos', p_actor);
            RETURN 'activo';
          END IF;

          IF v_para = 'aprovado' THEN
            v_falta := platform.aprovacao_em_falta(v_caso.id);
            IF cardinality(v_falta) > 0 THEN
              RAISE EXCEPTION 'aprovacao sem as condicoes do agregador'
                USING ERRCODE = 'check_violation',
                      DETAIL = array_to_string(v_falta, ',');
            END IF;
          END IF;

          -- **Um canal vivo, e so um.** O Piloto liga um numero por tenant; com
          -- dois, escolher um era decidir por ordem fisica qual o evento anuncia.
          -- Um canal `desligado` ou `encerrado` de uma tentativa antiga nao conta.
          IF p_evento = 'es_concluido' THEN
            SELECT count(*) INTO v_canais
              FROM platform.tenant_channels ch
             WHERE ch.tenant_id = v_caso.tenant_id
               AND ch.estado NOT IN ('desligado', 'encerrado');
            IF v_canais <> 1 THEN
              RAISE EXCEPTION 'caso % sem um canal ligado (tem %)', v_caso.id, v_canais
                USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            SELECT ch.id, ch.channel_mode, ch.vertical INTO v_canal
              FROM platform.tenant_channels ch
             WHERE ch.tenant_id = v_caso.tenant_id
               AND ch.estado NOT IN ('desligado', 'encerrado');
          END IF;

          UPDATE platform.onboarding_case SET fase = v_para WHERE id = v_caso.id;

          IF v_para = 'aprovado' THEN
            PERFORM platform.evt_emitir(
              'tenant.approved', 1::smallint, v_caso.tenant_id, 'tenant',
              v_caso.tenant_id::text,
              jsonb_build_object(
                'vertical', 'vendedor',
                'plano', 'free',
                'onboarding_id', v_caso.id,
                'kyc_nivel', 'K1',
                'tecto_inicial_minor', 5000000,
                'currency', 'AOA',
                'intervencao_humana', EXISTS (
                  SELECT 1 FROM platform.review_case r
                   WHERE r.onboarding_id = v_caso.id AND r.tipo <> 'auditoria')));
          ELSIF p_evento = 'es_concluido' THEN
            PERFORM platform.evt_emitir(
              'tenant.provisioned', 1::smallint, v_caso.tenant_id, 'tenant',
              v_caso.tenant_id::text,
              jsonb_build_object(
                'vertical', v_canal.vertical,
                'onboarding_id', v_caso.id,
                'channel_id', v_canal.id,
                'channel_mode', v_canal.channel_mode));
          END IF;
          RETURN v_para;
        END
        $$
        """
    )


def _vistas() -> None:
    op.execute(
        """
        CREATE VIEW platform.v_onboarding_kpis WITH (security_invoker = true) AS
        SELECT c.id AS onboarding_id,
               c.tenant_id,
               c.fase,
               c.owner_active_seconds,
               CASE WHEN c.activo_at IS NOT NULL
                    THEN extract(epoch FROM c.activo_at - c.criado_at) / 86400
               END AS dias_calendario,
               EXISTS (SELECT 1 FROM platform.review_case r
                        WHERE r.onboarding_id = c.id
                          AND r.tipo <> 'auditoria') AS intervencao_humana,
               (SELECT bool_and(p.attempt = 1) FROM platform.provisioning_step p
                 WHERE p.onboarding_id = c.id) AS saga_primeira_tentativa
          FROM platform.onboarding_case c
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_onboarding_kpis IS "
        "'KPIs de onboarding por caso (KAM-092, docs/tecnica/10 secao 16). "
        "dias_calendario so com o caso activo; intervencao_humana e existir "
        "review_case que nao seja de amostragem; saga_primeira_tentativa e nulo "
        "sem passos.'"
    )
    op.execute(
        """
        CREATE VIEW platform.v_onboarding_kpis_agregado WITH (security_invoker = true) AS
        SELECT count(*) AS casos_activos,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY k.owner_active_seconds)
                 AS owner_active_seconds_mediana,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY k.owner_active_seconds)
                 AS owner_active_seconds_p90,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY k.dias_calendario)
                 AS dias_calendario_mediana,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY k.dias_calendario)
                 AS dias_calendario_p90,
               avg(CASE WHEN k.intervencao_humana THEN 0 ELSE 1 END)
                 AS sem_intervencao_ratio,
               avg(CASE WHEN k.saga_primeira_tentativa THEN 1 ELSE 0 END)
                 FILTER (WHERE k.saga_primeira_tentativa IS NOT NULL)
                 AS saga_primeira_tentativa_ratio
          FROM platform.v_onboarding_kpis k
         WHERE k.fase = 'activo'
        """
    )
    op.execute(
        "COMMENT ON VIEW platform.v_onboarding_kpis_agregado IS "
        "'Mediana e p90 dos casos activos (KAM-092). Os alvos sao propostas do "
        "docs/tecnica/10 secao 16.'"
    )


def _privilegios() -> None:
    op.execute(f"GRANT SELECT ON {GATES} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT, INSERT ON {GATES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT UPDATE (ok, evidencia_ref) ON {GATES} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT, INSERT ON {REGISTO} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT ON {REGISTO} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"GRANT SELECT ON platform.v_onboarding_kpis TO {PAPEL_DE_LOTE}")
    op.execute(
        f"GRANT SELECT ON platform.v_onboarding_kpis_agregado TO {PAPEL_DE_LOTE}"
    )
    # Emitir. O `kamba_batch` ja tinha `SELECT, UPDATE, DELETE` no *outbox*.
    op.execute(f"GRANT INSERT ON platform.events_outbox TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT, INSERT ON platform.evt_agregado_seq TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT UPDATE (seq) ON platform.evt_agregado_seq TO {PAPEL_DE_LOTE}")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.evt_emitir({ARGUMENTOS_DE_EVT_EMITIR}) "
        f"TO {PAPEL_DE_LOTE}"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {ADVANCE_CASE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ADVANCE_CASE} TO {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE ALL ON FUNCTION {TRANSITION_TENANT} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {TRANSITION_TENANT} TO {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE ALL ON FUNCTION {APROVACAO_EM_FALTA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {APROVACAO_EM_FALTA} TO {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE ALL ON FUNCTION {GATES_EM_FALTA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {GATES_EM_FALTA} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {GATES_EM_FALTA} TO {PAPEL_DA_APP}")
    op.execute(f"REVOKE ALL ON FUNCTION {TRANSICOES_DO_CASO} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {TRANSICOES_DO_CASO} TO {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE ALL ON FUNCTION {TRANSICOES_DO_TENANT} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {TRANSICOES_DO_TENANT} TO {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE ALL ON FUNCTION {REVISAO_APROVADA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {REVISAO_APROVADA} TO {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE ALL ON FUNCTION {EVENTO_EMITIDO} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {EVENTO_EMITIDO} TO {PAPEL_DE_LOTE}")


def downgrade() -> None:
    """O inverso, com uma recusa: o registo de estados nao se perde.

    **A contagem corre com o `FORCE` desligado**, pela licao do KAM-050: sob
    `FORCE` sem contexto um `count(*)` le zero.
    """
    op.execute(f"ALTER TABLE {REGISTO} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $guarda$
        BEGIN
          IF EXISTS (SELECT 1 FROM {REGISTO}) THEN
            RAISE EXCEPTION
              'downgrade da 0058 recusado: o registo de estados do tenant tem '
              'linhas, e e append-only (KAM-092)'
              USING ERRCODE = 'object_not_in_prerequisite_state';
          END IF;
        END $guarda$
        """
    )
    op.execute(f"ALTER TABLE {REGISTO} FORCE ROW LEVEL SECURITY")

    op.execute(f"REVOKE EXECUTE ON FUNCTION {GATES_EM_FALTA} FROM {PAPEL_DA_APP}")
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION platform.evt_emitir({ARGUMENTOS_DE_EVT_EMITIR}) "
        f"FROM {PAPEL_DE_LOTE}"
    )
    op.execute(f"REVOKE UPDATE (seq) ON platform.evt_agregado_seq FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE SELECT, INSERT ON platform.evt_agregado_seq FROM {PAPEL_DE_LOTE}")
    op.execute(f"REVOKE INSERT ON platform.events_outbox FROM {PAPEL_DE_LOTE}")

    op.execute("DROP VIEW platform.v_onboarding_kpis_agregado")
    op.execute("DROP VIEW platform.v_onboarding_kpis")
    op.execute(f"DROP FUNCTION {ADVANCE_CASE}")
    op.execute(f"DROP FUNCTION {TRANSITION_TENANT}")
    op.execute(f"DROP FUNCTION {APROVACAO_EM_FALTA}")
    op.execute(f"DROP FUNCTION {REVISAO_APROVADA}")
    op.execute(f"DROP FUNCTION {EVENTO_EMITIDO}")
    op.execute(f"DROP FUNCTION {GATES_EM_FALTA}")
    op.execute(f"DROP FUNCTION {TRANSICOES_DO_CASO}")
    op.execute(f"DROP FUNCTION {TRANSICOES_DO_TENANT}")

    rls.disable_tenant_rls("tenant_state_log")
    op.execute(f"DROP TABLE {REGISTO}")
    op.execute("DROP FUNCTION platform.tenant_state_log_imutavel()")
    rls.disable_tenant_rls("onboarding_gate")
    op.execute(f"DROP TABLE {GATES}")
    op.execute("DROP FUNCTION platform.onboarding_gate_em()")
