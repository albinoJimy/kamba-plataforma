"""Trust & Safety: ts_signal e ts_sanction, append-only (KAM-097).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

**O numero e provisorio.** A cadeia deste lote e 0052 (KAM-194), 0053 (este),
0054 (KAM-059) e 0055 (KAM-120); o numero final da-o a integracao, pela ordem
de quem fica pronto.

## O que esta revisao cria

* `platform.ts_signal` — um sinal de T&S (auto-compra, burla provavel,
  confirmacao suspeita, foto repetida, preco anomalo, queixa recorrente, nao
  entrega, mudanca de conta, violacao de categoria), com a severidade **fixa por
  tipo** e o `detalhe` fechado a chaves de referencia: nenhum dado pessoal, so
  identificadores (`packages/core-ts/src/trust/`).
* `platform.ts_sanction` — cada passo da escada (`aviso`, `limitacao`,
  `suspensao`, `encerramento`) e cada desfecho de recurso, como linhas novas:
  nada se emenda.

## As divergencias do DDL do bloco, e porque

* **`id uuid` e nao `bigserial`** nas duas: um sequencial dizia quantos sinais e
  quantas sancoes a plataforma conta (o precedente e a `review_decision_log` da
  `0048`).
* **`ref_evento` e a referencia do sinal**: o `event_id` quando o sinal nasce de
  um evento, e o identificador do agregado quando o sinal e **por agregado** — a
  auto-compra e por encomenda (o `order_id`), para que o `order.created` e o
  `order.paid` da mesma encomenda deem **um** sinal e nao dois (ensaio
  adversarial (e)); a nao-entrega e por encomenda; a foto repetida e por
  ingestao. A chave `(tenant_id, tipo, ref_evento)` e a do bloco.
* **`recurso_estado` nao se actualiza**: uma tabela append-only nao muda uma
  coluna depois de escrita. O desfecho de um recurso e uma **linha nova**, com
  `recurso_de` a apontar a sancao recorrida e `recurso_estado` em
  `provido`/`negado`; a chave `recurso:<id>` faz o recurso unico por sancao.
* **Colunas a mais em `ts_sanction`**: `chave` (a idempotencia), `regra`, `sinais`
  (os `ts_signal.id` em que assenta), `case_id` (o `review_case` da decisao
  humana), `justificacao_salto` e `recurso_de`.
* **`motivo_publico NOT NULL`, de lista fechada**: o dono le sempre um texto fixo
  e a heuristica nunca sai (criterio 9), por construcao e nao por cuidado.

## Quem escreve, e o que cada um nao consegue

O consumidor de eventos e o `kamba_app` (e o unico papel com `INSERT` em
`events_consumed`, `0005`), e escreve sinais e sancoes **automaticas** do seu
tenant. Nao e o vigiado a escrever o registo de vigilancia no sentido que a
`0032` recusou, e a razao esta medida em tres barreiras:

1. a **severidade e fixa por tipo** (`ts_signal_severidade_ck`): um sinal escrito
   antes do consumidor com a mesma chave sai igual ao do consumidor;
2. **nada se apaga nem se emenda** (privilegio e *trigger*): um sinal ou uma
   sancao nao se retiram;
3. o `kamba_app` **nao escreve** uma linha humana nem um desfecho de recurso
   (`ts_sanction_regras`), e a chave e o autor de cada linha estao presos a
   origem (`ts_sanction_chave_ck`): nao ocupa a chave `recurso:<id>` de um
   recurso que ainda nao foi decidido. Levantar a propria sancao era o unico
   abuso com ganho;
4. o `ocorrido_em` de um sinal fica entre ontem e agora (`ts_signal_instante`):
   um sinal escrito antes do consumidor e datado do passado nao decai para zero,
   e o consumidor corre a escada mesmo sobre um sinal repetido.

A auto-compra compara com o `owner_contact_id`, e esta revisao **retira** ao
`kamba_app` o `UPDATE` dessa coluna: o dono anulava-a antes de comprar a si
proprio. Nenhum codigo da aplicacao a escreve.

O que sobra ao `kamba_app` e escrever sinais e avisos **contra si proprio**. O
lote (`kamba_batch`) escreve as linhas humanas e as varreduras que atravessam
tenants. O `kamba_app` nao le o `motivo_interno`, a `regra`, os `sinais` nem o
`detalhe`: a heuristica e so do T&S.

## A escada, tambem na base

O mesmo *trigger* recusa uma `suspensao` ou um `encerramento` que nao sejam
humanos (tambem por `CHECK`), e um passo que **salta** degraus sobre o que esta
em vigor sem `justificacao_salto` escrita.

## O `downgrade`

Larga as tabelas e as funcoes, sem `CASCADE`. **Apaga os sinais e as sancoes**:
uma base onde se desce esta revisao e de ensaio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.ts_signal (
          id           uuid CONSTRAINT ts_signal_pkey PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id    uuid NOT NULL CONSTRAINT ts_signal_tenant_fk
                       REFERENCES platform.tenants (id),
          tipo         text NOT NULL
                       CONSTRAINT ts_signal_tipo_ck
                       CHECK (tipo IN ('auto_compra', 'burla_provavel', 'confirmacao_suspeita',
                         'foto_repetida', 'preco_anomalo', 'queixa_recorrente', 'nao_entrega',
                         'mudanca_de_conta', 'violacao_de_categoria')),
          severidade   text NOT NULL
                       CONSTRAINT ts_signal_severidade_dominio_ck
                       CHECK (severidade IN ('baixa', 'media', 'alta')),
          ref_evento   uuid NOT NULL,
          detalhe      jsonb NOT NULL DEFAULT '{}'
                       CONSTRAINT ts_signal_detalhe_ck
                       CHECK (jsonb_typeof(detalhe) = 'object'
                         AND (detalhe - ARRAY['order_id', 'coincidencia', 'contagem', 'sku',
                           'versao_politica', 'pedidos']) = '{}'::jsonb),
          ocorrido_em  timestamptz NOT NULL,
          criado_at    timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ts_signal_severidade_ck CHECK (
               (tipo IN ('auto_compra', 'burla_provavel', 'mudanca_de_conta',
                         'violacao_de_categoria') AND severidade = 'alta')
            OR (tipo IN ('confirmacao_suspeita', 'queixa_recorrente', 'nao_entrega')
                AND severidade = 'media')
            OR (tipo IN ('foto_repetida', 'preco_anomalo') AND severidade = 'baixa')),
          CONSTRAINT ts_signal_chave_uq UNIQUE (tenant_id, tipo, ref_evento),
          CONSTRAINT ts_signal_id_tenant_uq UNIQUE (id, tenant_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ts_signal_tenant_idx ON platform.ts_signal (tenant_id, ocorrido_em)"
    )
    # Quem grava escolhe o `ocorrido_em`, e o risco decai com ele: um sinal
    # datado de 2000 pesava zero. O *trigger* prende-o a [agora - 1 dia, agora]:
    # um evento entregue tarde conta como recente, o que e o lado seguro.
    op.execute(
        """
        CREATE FUNCTION platform.ts_signal_instante()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          NEW.ocorrido_em := greatest(least(NEW.ocorrido_em, now()), now() - interval '1 day');
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER ts_signal_instante
          BEFORE INSERT ON platform.ts_signal
          FOR EACH ROW EXECUTE FUNCTION platform.ts_signal_instante()
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.ts_signal IS "
        "'Sinal de Trust & Safety (KAM-097). Append-only. Severidade fixa por tipo. "
        "detalhe so com chaves de referencia, sem dados pessoais. Idempotente por "
        "(tenant_id, tipo, ref_evento); ref_evento e o evento, ou o agregado quando o "
        "sinal e por agregado.'"
    )

    op.execute(
        """
        CREATE TABLE platform.ts_sanction (
          id                  uuid CONSTRAINT ts_sanction_pkey PRIMARY KEY
                              DEFAULT gen_random_uuid(),
          tenant_id           uuid NOT NULL CONSTRAINT ts_sanction_tenant_fk
                              REFERENCES platform.tenants (id),
          chave               text NOT NULL
                              CONSTRAINT ts_sanction_chave_forma_ck
                              CHECK (chave ~ '^(auto|caso|recurso):[0-9a-z_:.-]{1,120}$'),
          passo               text NOT NULL
                              CONSTRAINT ts_sanction_passo_ck
                              CHECK (passo IN ('aviso', 'limitacao', 'suspensao', 'encerramento')),
          origem              text NOT NULL
                              CONSTRAINT ts_sanction_origem_ck
                              CHECK (origem IN ('automatica', 'humana')),
          motivo_interno      text NOT NULL
                              CONSTRAINT ts_sanction_motivo_interno_ck
                              CHECK (length(btrim(motivo_interno)) BETWEEN 1 AND 2000),
          motivo_publico      text NOT NULL
                              CONSTRAINT ts_sanction_motivo_publico_ck
                              CHECK (motivo_publico IN ('conduta_em_analise',
                                'actividade_limitada', 'loja_suspensa', 'loja_encerrada',
                                'recurso_aceite', 'recurso_mantido')),
          autor               text NOT NULL
                              CONSTRAINT ts_sanction_autor_ck
                              CHECK (autor ~ '^(sistema:[0-9]+\\.[0-9]+\\.[0-9]+|[0-9a-f-]{36})$'),
          regra               text
                              CONSTRAINT ts_sanction_regra_ck
                              CHECK (length(regra) BETWEEN 1 AND 120),
          sinais              jsonb NOT NULL DEFAULT '[]'
                              CONSTRAINT ts_sanction_sinais_ck
                              CHECK (jsonb_typeof(sinais) = 'array'),
          case_id             uuid,
          justificacao_salto  text
                              CONSTRAINT ts_sanction_justificacao_ck
                              CHECK (length(btrim(justificacao_salto)) BETWEEN 1 AND 2000),
          recurso_de          uuid,
          recurso_estado      text
                              CONSTRAINT ts_sanction_recurso_estado_ck
                              CHECK (recurso_estado IN ('provido', 'negado')),
          em                  timestamptz NOT NULL DEFAULT clock_timestamp(),
          CONSTRAINT ts_sanction_grave_humana_ck
            CHECK (origem = 'humana' OR passo IN ('aviso', 'limitacao')),
          CONSTRAINT ts_sanction_humana_com_caso_ck
            CHECK (origem = 'automatica' OR case_id IS NOT NULL),
          CONSTRAINT ts_sanction_recurso_ck
            CHECK ((recurso_de IS NULL) = (recurso_estado IS NULL)
              AND (recurso_de IS NULL OR origem = 'humana')),
          CONSTRAINT ts_sanction_chave_ck CHECK (
               (origem = 'automatica' AND recurso_de IS NULL
                AND left(chave, 5) = 'auto:' AND left(autor, 8) = 'sistema:')
            OR (origem = 'humana' AND recurso_de IS NULL
                AND chave = concat('caso:', case_id) AND left(autor, 8) <> 'sistema:')
            OR (origem = 'humana' AND recurso_de IS NOT NULL
                AND chave = concat('recurso:', recurso_de) AND left(autor, 8) <> 'sistema:')),
          CONSTRAINT ts_sanction_chave_uq UNIQUE (tenant_id, chave),
          CONSTRAINT ts_sanction_id_tenant_uq UNIQUE (id, tenant_id),
          CONSTRAINT ts_sanction_caso_fk FOREIGN KEY (case_id, tenant_id)
            REFERENCES platform.review_case (id, tenant_id),
          CONSTRAINT ts_sanction_recurso_fk FOREIGN KEY (recurso_de, tenant_id)
            REFERENCES platform.ts_sanction (id, tenant_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ts_sanction_tenant_idx ON platform.ts_sanction (tenant_id, em)"
    )
    op.execute(
        "COMMENT ON TABLE platform.ts_sanction IS "
        "'Escada de sancoes de Trust & Safety (KAM-097). Append-only: cada passo e "
        "cada desfecho de recurso e uma linha nova. suspensao e encerramento so "
        "humanos, com review_case. Saltar passos exige justificacao_salto. "
        "motivo_publico de lista fechada; motivo_interno so para T&S.'"
    )

    op.execute(
        """
        CREATE FUNCTION platform.ts_imutavel()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          RAISE EXCEPTION
            'um sinal ou uma sancao de T&S nao se emenda nem se apaga: o recurso e uma linha nova'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for tabela in ("ts_signal", "ts_sanction"):
        op.execute(
            f"""
            CREATE TRIGGER {tabela}_imutavel
              BEFORE UPDATE OR DELETE ON platform.{tabela}
              FOR EACH ROW EXECUTE FUNCTION platform.ts_imutavel()
            """
        )

    op.execute(
        """
        CREATE FUNCTION platform.ts_sanction_regras()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          em_vigor integer;
        BEGIN
          IF current_user = 'kamba_app'
             AND (NEW.origem <> 'automatica' OR NEW.recurso_de IS NOT NULL) THEN
            RAISE EXCEPTION
              'o kamba_app so escreve sancoes automaticas: a humana e o recurso sao do lote'
              USING ERRCODE = '42501';
          END IF;
          IF NEW.recurso_de IS NULL THEN
            -- Duas insercoes concorrentes do mesmo tenant liam o mesmo passo em
            -- vigor e passavam as duas a verificacao do salto.
            PERFORM pg_advisory_xact_lock(hashtext('ts_sanction:' || NEW.tenant_id::text));
            SELECT max(array_position(
                     ARRAY['aviso', 'limitacao', 'suspensao', 'encerramento'], s.passo))
              INTO em_vigor
              FROM platform.ts_sanction s
             WHERE s.tenant_id = NEW.tenant_id
               AND s.recurso_de IS NULL
               AND NOT EXISTS (
                 SELECT 1 FROM platform.ts_sanction r
                  WHERE r.recurso_de = s.id AND r.recurso_estado = 'provido');
            IF array_position(ARRAY['aviso', 'limitacao', 'suspensao', 'encerramento'],
                              NEW.passo) > coalesce(em_vigor, 0) + 1
               AND NEW.justificacao_salto IS NULL THEN
              RAISE EXCEPTION 'saltar passos da escada exige justificacao escrita: % sobre %',
                NEW.passo, coalesce(em_vigor, 0) USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER ts_sanction_regras
          BEFORE INSERT ON platform.ts_sanction
          FOR EACH ROW EXECUTE FUNCTION platform.ts_sanction_regras()
        """
    )

    rls.enable_tenant_rls("ts_signal")
    rls.enable_tenant_rls("ts_sanction")
    for tabela in ("ts_signal", "ts_sanction"):
        op.execute(f"REVOKE ALL ON platform.{tabela} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT ON platform.{tabela} TO kamba_batch")
        op.execute(f"GRANT SELECT ON platform.{tabela} TO kamba_audit")
    op.execute(
        "GRANT INSERT, SELECT (id, tenant_id, tipo, severidade, ref_evento, ocorrido_em) "
        "ON platform.ts_signal TO kamba_app"
    )
    op.execute(
        "GRANT INSERT, SELECT (id, tenant_id, chave, passo, origem, motivo_publico, "
        "recurso_de, recurso_estado, em) ON platform.ts_sanction TO kamba_app"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.ts_imutavel() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION platform.ts_sanction_regras() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION platform.ts_signal_instante() FROM PUBLIC")
    # A auto-compra ancora-se no `owner_contact_id`, e o `kamba_app` podia
    # anula-lo antes de comprar a si proprio (achado 9). Nenhum codigo da
    # aplicacao o escreve; quem o escreve e o provisioning (KAM-092), pelo lote.
    op.execute("REVOKE UPDATE (owner_contact_id) ON platform.tenants FROM kamba_app")
    # A varredura da foto repetida (critério 4): o lote compara o *phash* entre
    # tenants. So as tres colunas que a comparacao precisa, e nada do resto da
    # ingestao (o `extraido` e os media continuam fora do lote).
    op.execute(
        "GRANT SELECT (id, tenant_id, phash) ON platform.catalog_ingestions TO kamba_batch"
    )


def downgrade() -> None:
    op.execute("GRANT UPDATE (owner_contact_id) ON platform.tenants TO kamba_app")
    op.execute(
        "REVOKE SELECT (id, tenant_id, phash) ON platform.catalog_ingestions FROM kamba_batch"
    )
    rls.disable_tenant_rls("ts_sanction")
    rls.disable_tenant_rls("ts_signal")
    op.execute("DROP TRIGGER ts_sanction_regras ON platform.ts_sanction")
    op.execute("DROP FUNCTION platform.ts_sanction_regras()")
    op.execute("DROP TRIGGER ts_signal_instante ON platform.ts_signal")
    op.execute("DROP FUNCTION platform.ts_signal_instante()")
    op.execute("DROP TRIGGER ts_sanction_imutavel ON platform.ts_sanction")
    op.execute("DROP TRIGGER ts_signal_imutavel ON platform.ts_signal")
    op.execute("DROP FUNCTION platform.ts_imutavel()")
    op.execute("DROP TABLE platform.ts_sanction")
    op.execute("DROP TABLE platform.ts_signal")
