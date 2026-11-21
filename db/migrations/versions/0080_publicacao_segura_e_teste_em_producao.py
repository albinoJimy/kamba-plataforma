"""Publicacao segura na base, o sinal do teste e o teste fora das metricas (KAM-202).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

1. **A publicacao protegida pela base** (criterio 4, a caixa da DoD do KAM-094
   «publicacao protegida por restricao de BD»):

   * `platform.conteudo_sha256_do_produto(categoria, nome)` — o
     `conteudo_sha256` do KAM-088 para um produto, **byte a byte** o do
     `conteudoSha256` de `packages/core-ts/src/screening/motor.ts`: o `sha256` do
     JSON `[categoria_declarada, [nome]]` sem espacos, a entrada do
     `SQL_POR_REANALISAR` e a do `assertPublishable` de um `sku`. O
     `to_json(text)` do PostgreSQL escapa o mesmo conjunto que o
     `JSON.stringify`; a fixture `packages/core-ts/tests/fixtures/conteudo_sha256.json`
     prende os dois lados aos mesmos bytes, com os casos dificeis;
   * `platform.oferta_publicavel(tenant, sku, nome)` — a regra do
     `assertPublishable` **na base**: `NULL` se o produto pode ser publicado com
     este nome; senao o motivo, `sem_decisao`, `bloqueada` ou `por_rever`;
   * o *trigger* `offer_terms_publicacao_segura`.

2. **O sinal do teste ponta a ponta** (criterio 1): `conversations.teste_recebido_at`,
   o instante em que a palavra do teste chegou a conversa, que o CHR grava e o
   observador de producao le. So o instante: nem o texto, nem o telefone.

3. **A decisao humana so do lote** (criterio 6, decisao do fundador de
   2026-11-20): o *trigger* `screening_decision_humano_so_do_lote` recusa a
   `origem = 'humano'` de qualquer papel que nao seja o `kamba_batch`, e o
   `kamba_batch` passa a ter `INSERT` na tabela.

4. **A conversa de teste fora das metricas e da golden** (criterio 3, decisao do
   fundador de 2026-11-20): o `cliente_at` do `platform.churn_sinais` e a
   `platform.v_draft_metrics` deixam de contar as conversas `is_test`.

## Os caminhos de escrita da oferta, e o que o trigger faz a cada um

| Caminho | O que escreve | O que o *trigger* faz |
|---|---|---|
| `inserirNoTenant` (rascunho) | `INSERT` sem `estado` | nada: nasce `rascunho` |
| `SQL_ACTUALIZAR_TERMOS` | `nome` e termos | so com o nome **diferente** num `publicado`: sem decisao para o nome novo, o produto **sai** para `rascunho` |
| `SQL_PUBLICAR` | `estado = 'publicado'` | sem decisao, **salta a linha**: zero linhas, que o `publishProduct` ja le como recusa de dominio |
| stock, preco, reservas | stock e preco | nada |
| `deleted_at` | o *soft delete* | nada |

**Saltar a linha, e nao `23514`, na transicao para `publicado`.** O
`publishProduct` trata zero linhas como recusa de dominio e devolve-a no
`Resultado`; um `23514` era uma excepcao que o COM nao espera. Um `INSERT` ja
`publicado` de um papel de servico recusa com `23514`: nenhum caminho do COM o
faz, logo so o faz quem esta a contornar o rascunho.

**O dono da tabela fica de fora**, nos dois *triggers*: pode desliga-los
(`ALTER TABLE ... DISABLE TRIGGER`), pelo que medi-lo nao acrescenta barreira, e
as sementes de ensaio inserem como dono ofertas ja publicadas e decisoes
humanas. A barreira e para os papeis de servico, que sao os que um defeito de
aplicacao usa.

## A versao da politica

A versao corrente esta no codigo e nao na base. A funcao le a versao da
**decisao mais recente do motor** (`regra` ou `llm`) para o conteudo de agora — e
nao a da linha mais recente, porque uma decisao humana copia a versao do caso de
revisao, que pode ser anterior (achado 2 da revisao adversarial: uma humana em v1
gravada depois de uma `bloqueada` em v2 publicava o que a v2 bloqueia). Chega, e
a razao e o papel
desta barreira: a base apanha o que contorna o COM, e o COM exige a versao
corrente no `assertPublishable` antes de publicar. Um publicado com a decisao
numa versao antiga e o caso da re-analise do KAM-088, que o ve (o
`SQL_POR_REANALISAR` compara a versao e o resumo) e grava a nova.

## A `permitida` de `regra` e `llm` que a aplicacao grava

Fica aceite, por decisao do fundador de 2026-11-20: o COM e o unico motor do
`screen`, e e o `kamba_app` quem grava a decisao do motor. Esta barreira e
contra defeitos e contra o que contorna o COM, nao contra uma aplicacao
comprometida — essa escreve a oferta directamente.

## Descida

Larga os dois *triggers* e as tres funcoes, a coluna `teste_recebido_at` (o sinal
e estado de medicao e nao prova), os dois privilegios novos, e devolve o
`churn_sinais` e a `v_draft_metrics` a forma da `0063` e da `0024`. Sem
`CASCADE`.
"""

from __future__ import annotations

from alembic import op

revision = "0080"
#: Da fila de migracoes, depois da `0077` (KAM-223), da `0078` (KAM-230) e da
#: `0079` (KAM-121).
down_revision = "0079"
branch_labels = None
depends_on = None

OFERTAS = "platform.offer_terms"
DECISOES = "platform.screening_decision"
CONVERSAS = "platform.conversations"
VISTA_DO_CONCIERGE = "platform.v_draft_metrics"

CONTEUDO = "platform.conteudo_sha256_do_produto(text, text)"
PUBLICAVEL = "platform.oferta_publicavel(uuid, text, text)"
CHURN_SINAIS = "platform.churn_sinais(timestamptz, jsonb)"

#: Os papeis que escrevem a oferta: o *trigger* corre com os privilegios deles.
PAPEIS_DA_OFERTA = ("kamba_app", "kamba_batch")

#: As colunas da conversa que o `kamba_audit` precisa para ler a vista do
#: concierge sem a conversa de teste. So estas tres: o `kamba_audit` nao le a
#: conversa.
COLUNAS_DA_AUDITORIA = ("tenant_id", "contact_id", "is_test")

#: Os limiares do `churn_sinais`, os da `0063`. Copiado e nao importado: uma
#: revisao nao importa outra.
CHAVES_DOS_LIMIARES = (
    "'dono_sem_actividade_dias'",
    "'sem_pedidos_dias'",
    "'pagamento_em_atraso_dias'",
    "'catalogo_desactualizado_dias'",
    "'dormente_dias'",
    "'dormente_janela_clientes_dias'",
    "'dormente_aviso_dias'",
)

#: O que esta revisao acrescenta as duas leituras do criterio 3.
SEM_TESTE_NO_CHURN = "AND NOT cv.is_test "
SEM_TESTE_NO_CONCIERGE = (
    "WHERE NOT EXISTS (SELECT 1 FROM platform.conversations cv "
    "WHERE cv.tenant_id = d.tenant_id AND cv.is_test "
    "AND d.thread_id = cv.tenant_id::text || ':' || cv.contact_id::text) "
)


def churn_sinais(filtro: str) -> str:
    """O `platform.churn_sinais` da `0063`, com o `filtro` no `cliente_at`."""
    return f"""
        CREATE OR REPLACE FUNCTION platform.churn_sinais(p_agora timestamptz, p_limiares jsonb)
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
                     WHERE cv.tenant_id = t.tid {filtro}AND cv.last_inbound_at <= p_agora)
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
          SELECT a.tid, 'dormente', a.dono_at,
                 a.dono_at < p_agora - make_interval(days => v_dormente) FROM a
           WHERE a.dono_at <= p_agora - make_interval(days => v_dormente - v_aviso)
             AND coalesce(a.pedido_at, '-infinity') <= p_agora - make_interval(days => v_janela)
             AND coalesce(a.cliente_at, '-infinity') <= p_agora - make_interval(days => v_janela);
        END
        $$
        """


def vista_do_concierge(filtro: str) -> str:
    """A `platform.v_draft_metrics` da `0024`, com o `filtro` antes do `GROUP BY`."""
    return f"""
        CREATE OR REPLACE VIEW platform.v_draft_metrics WITH (security_invoker = true) AS
        SELECT
            d.tenant_id,
            d.graph_version,
            count(*)                                         AS draft_total,
            count(*) FILTER (WHERE d.decisao IS NULL)         AS draft_pendentes,
            (count(*) FILTER (WHERE d.decisao IN ('aprovado', 'editado')))::numeric
                / NULLIF(count(*) FILTER (WHERE d.decisao IS NOT NULL), 0)
                                                             AS draft_approved_ratio,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY d.razao_edicao)
                                                             AS draft_edit_ratio_p50,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY d.latencia_ms / 1000.0)
                                                      AS draft_decision_latency_s_p50,
            percentile_cont(0.9) WITHIN GROUP (ORDER BY d.latencia_ms / 1000.0)
                                                      AS draft_decision_latency_s_p90
        FROM platform.draft_decisions d
        {filtro}GROUP BY d.tenant_id, d.graph_version
        """


def upgrade() -> None:
    _publicacao_segura()
    _sinal_do_teste()
    _humano_so_do_lote()
    _teste_fora_das_metricas()


def _publicacao_segura() -> None:
    op.execute(
        """
        CREATE FUNCTION platform.conteudo_sha256_do_produto(p_categoria text, p_nome text)
          RETURNS bytea
          LANGUAGE sql
          IMMUTABLE
          STRICT
          SET search_path = pg_catalog
        AS $$
          SELECT sha256(convert_to(
            '[' || to_json(p_categoria)::text || ',[' || to_json(p_nome)::text || ']]',
            'UTF8'))
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.oferta_publicavel(p_tenant_id uuid, p_sku text, p_nome text)
          RETURNS text
          LANGUAGE plpgsql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_categoria text;
          v_sha       bytea;
          v_versao    text;
          v_humana    text;
        BEGIN
          SELECT c.sujeito_ref INTO v_categoria
            FROM platform.screening_decision c
           WHERE c.tenant_id = p_tenant_id AND c.sujeito_tipo = 'categoria'
           ORDER BY c.criado_at DESC, c.id DESC
           LIMIT 1;
          v_sha := platform.conteudo_sha256_do_produto(coalesce(v_categoria, ''), p_nome);

          -- A versao corrente e a da decisao mais recente **do motor**: uma
          -- humana copia a versao do caso de revisao, que pode ser anterior.
          SELECT d.versao_politica INTO v_versao
            FROM platform.screening_decision d
           WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
             AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
           ORDER BY (d.origem = 'humano'), d.criado_at DESC, d.id DESC
           LIMIT 1;
          IF NOT FOUND THEN
            RETURN 'sem_decisao';
          END IF;

          SELECT d.decisao INTO v_humana
            FROM platform.screening_decision d
           WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
             AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
             AND d.versao_politica = v_versao AND d.origem = 'humano'
           ORDER BY d.criado_at DESC, d.id DESC
           LIMIT 1;
          IF FOUND THEN
            RETURN CASE v_humana WHEN 'permitida' THEN NULL
                                 WHEN 'bloqueada' THEN 'bloqueada'
                                 ELSE 'por_rever' END;
          END IF;

          IF EXISTS (SELECT 1 FROM platform.screening_decision d
                      WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
                        AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
                        AND d.versao_politica = v_versao AND d.decisao = 'bloqueada') THEN
            RETURN 'bloqueada';
          END IF;
          IF EXISTS (SELECT 1 FROM platform.screening_decision d
                      WHERE d.tenant_id = p_tenant_id AND d.sujeito_tipo = 'produto'
                        AND d.sujeito_ref = p_sku AND d.conteudo_sha256 = v_sha
                        AND d.versao_politica = v_versao AND d.decisao <> 'permitida') THEN
            RETURN 'por_rever';
          END IF;
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.offer_terms_publicacao_segura()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_motivo text;
        BEGIN
          IF NEW.estado <> 'publicado' THEN
            RETURN NEW;
          END IF;
          -- O dono da tabela pode desligar este trigger; medi-lo nao acrescenta
          -- barreira. Ver a nota da revisao.
          IF EXISTS (SELECT 1 FROM pg_roles r, pg_class c
                      WHERE r.rolname = current_user AND c.oid = TG_RELID
                        AND (r.rolsuper OR r.oid = c.relowner)) THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.estado = 'publicado'
             AND OLD.nome IS NOT DISTINCT FROM NEW.nome THEN
            RETURN NEW;
          END IF;

          v_motivo := platform.oferta_publicavel(NEW.tenant_id, NEW.sku, NEW.nome);
          IF v_motivo IS NULL THEN
            RETURN NEW;
          END IF;

          IF TG_OP = 'INSERT' THEN
            RAISE EXCEPTION 'oferta nao publicavel: %', v_motivo
              USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.estado = 'publicado' THEN
            -- O nome mudou num publicado e o nome novo nao tem decisao que o
            -- deixe: sai de publicado. O resto da escrita fica.
            NEW.estado := 'rascunho';
            RETURN NEW;
          END IF;
          -- A transicao para publicado sem decisao: zero linhas, que o COM le
          -- como recusa de dominio.
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER offer_terms_publicacao_segura
          BEFORE INSERT OR UPDATE OF estado, nome ON {OFERTAS}
          FOR EACH ROW EXECUTE FUNCTION platform.offer_terms_publicacao_segura()
        """
    )
    op.execute(f"ALTER TABLE {OFERTAS} ENABLE ALWAYS TRIGGER offer_terms_publicacao_segura")
    op.execute(f"REVOKE ALL ON FUNCTION {CONTEUDO} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON FUNCTION {PUBLICAVEL} FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION platform.offer_terms_publicacao_segura() FROM PUBLIC")
    # O *trigger* corre com os privilegios de quem escreve: os papeis que
    # escrevem a oferta precisam de poder chamar as duas funcoes.
    for papel in PAPEIS_DA_OFERTA:
        op.execute(f"GRANT EXECUTE ON FUNCTION {CONTEUDO} TO {papel}")
        op.execute(f"GRANT EXECUTE ON FUNCTION {PUBLICAVEL} TO {papel}")


def _sinal_do_teste() -> None:
    op.execute(f"ALTER TABLE {CONVERSAS} ADD COLUMN teste_recebido_at timestamptz")
    op.execute(
        f"COMMENT ON COLUMN {CONVERSAS}.teste_recebido_at IS "
        "'Instante em que a palavra do teste ponta a ponta chegou a esta conversa "
        "(KAM-202). Gravado pelo CHR; lido pelo observador do teste. Sem texto nem telefone.'"
    )
    op.execute(f"GRANT UPDATE (teste_recebido_at) ON {CONVERSAS} TO kamba_app")


def _humano_so_do_lote() -> None:
    op.execute(
        """
        CREATE FUNCTION platform.screening_decision_humano_so_do_lote()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          IF NEW.origem <> 'humano' OR current_user = 'kamba_batch' THEN
            RETURN NEW;
          END IF;
          -- O dono da tabela pode desligar este trigger; as sementes dele passam.
          IF EXISTS (SELECT 1 FROM pg_roles r, pg_class c
                      WHERE r.rolname = current_user AND c.oid = TG_RELID
                        AND (r.rolsuper OR r.oid = c.relowner)) THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'a decisao humana de screening so a grava o processo de lote'
            USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER screening_decision_humano_so_do_lote
          BEFORE INSERT ON {DECISOES}
          FOR EACH ROW EXECUTE FUNCTION platform.screening_decision_humano_so_do_lote()
        """
    )
    op.execute(f"ALTER TABLE {DECISOES} ENABLE ALWAYS TRIGGER screening_decision_humano_so_do_lote")
    op.execute("REVOKE ALL ON FUNCTION platform.screening_decision_humano_so_do_lote() FROM PUBLIC")
    op.execute(f"GRANT INSERT ON {DECISOES} TO kamba_batch")


def _teste_fora_das_metricas() -> None:
    op.execute(churn_sinais(SEM_TESTE_NO_CHURN))
    op.execute(vista_do_concierge(SEM_TESTE_NO_CONCIERGE))
    op.execute(f"GRANT SELECT ({', '.join(COLUNAS_DA_AUDITORIA)}) ON {CONVERSAS} TO kamba_audit")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ({', '.join(COLUNAS_DA_AUDITORIA)}) ON {CONVERSAS} FROM kamba_audit")
    op.execute(vista_do_concierge(""))
    op.execute(churn_sinais(""))

    op.execute(f"REVOKE INSERT ON {DECISOES} FROM kamba_batch")
    op.execute(f"DROP TRIGGER screening_decision_humano_so_do_lote ON {DECISOES}")
    op.execute("DROP FUNCTION platform.screening_decision_humano_so_do_lote()")

    op.execute(f"REVOKE UPDATE (teste_recebido_at) ON {CONVERSAS} FROM kamba_app")
    op.execute(f"ALTER TABLE {CONVERSAS} DROP COLUMN teste_recebido_at")

    op.execute(f"DROP TRIGGER offer_terms_publicacao_segura ON {OFERTAS}")
    op.execute("DROP FUNCTION platform.offer_terms_publicacao_segura()")
    op.execute(f"DROP FUNCTION {PUBLICAVEL}")
    op.execute(f"DROP FUNCTION {CONTEUDO}")
