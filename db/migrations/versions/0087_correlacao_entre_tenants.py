"""Correlacao entre tenants por comprador: o pseudonimo sem tenant e a funcao do lote (KAM-208).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao faz

As tres pecas da decisao do fundador de 2026-11-21 (bloco do KAM-208, D2, D4,
D5 e D6), e nenhuma outra:

* `platform.contact_xtenant_pseudonym` — um pseudonimo do telefone **sem
  tenant** por contacto (HMAC-SHA256 com chave e dominio proprios,
  `packages/core-ts/src/identity/correlacao.ts`), com a versao da chave
  (`kid`) e o instante da ultima resolucao (`visto_at`). Escreve-a **so** o
  `kamba_identity`, ao resolver o contacto; o `kamba_app` e o `kamba_batch`
  **nao tem privilegio nenhum** nela. RLS `tenant_iso` com `FORCE`, como todas
  as tabelas com `tenant_id`.
* `platform.ts_compradores_noutra_loja_do_dono(uuid[])` — a comparacao.
  Devolve `(tenant_id, contagem)`: por tenant, os compradores (contacto de
  encomenda paga ou entregue nos ultimos 30 dias, D6) cujo pseudonimo compra
  tambem noutro tenant do **mesmo dono** — o `owner_contact_id` com o mesmo
  pseudonimo nos dois (D5). O comprador e o dono seguem as fusoes ate ao
  contacto que ficou. **Nunca devolve o pseudonimo nem o outro tenant.**
  Pseudonimos de `kid` diferentes nunca se comparam (D3, rotacao preguicosa), e
  os de compradores vistos ha mais de 90 dias nao contam (D4). **O do dono nao
  vence enquanto ele for dono** (decisao do fundador de 2026-11-22, opcao B). **As duas janelas sao da
  funcao, e nao de quem chama** (achado 3 da revisao adversarial): com os
  instantes como argumento, o lote bissectava o `paga_at` de uma encomenda
  concreta e ficava a saber que comprador de A compra em B.
* `platform.contact_xtenant_purgar(uuid[], timestamptz)` — a retencao (D4):
  apaga os pseudonimos vistos antes do instante, e devolve quantos. **Menos o do
  dono de cada tenant** (o `owner_contact_id`, seguido pelas fusoes): esse nao
  vence enquanto for dono (opcao B de 2026-11-22). Na troca de dono, o antigo
  perde a excepcao e volta aos 90 dias desde o `visto_at` — se ja os passou,
  sai na purga seguinte.
* `ts_signal.tipo` ganha `comprador_noutra_loja_do_dono`, de severidade
  `baixa` (D6: informativo, peso 0 na politica de risco).
* o *trigger* `contacts_xtenant_esquecer` (funcao
  `platform.contact_xtenant_esquecer()`, `SECURITY INVOKER`): quando um
  contacto perde o telefone (`phone_hmac` nulo), e fundido ou e apagado, o
  pseudonimo dele vai (D4, «apaga-se com o contacto»). Na base e nao so no
  `eraseContact`, porque ha mais de um caminho que apaga contactos — a purga do
  cofre no encerramento do tenant (`kamba_core/offboarding/cofre.py`, KAM-218)
  escreve o seu proprio SQL. Quem actualiza essas tres colunas e so o
  `kamba_identity` (`0003`), que tem `DELETE` na tabela e corre com o contexto
  do tenant: o *trigger* corre como ele.

## As duas funcoes sao `SECURITY DEFINER` e percorrem os tenants um a um

O `db/rls.py` diz porque e que um `SECURITY DEFINER` nao le uma tabela com
`FORCE`: o dono e o `kamba_migrator`, `NOBYPASSRLS`, e sem contexto ve zero
linhas. A saida e a da `0067`: a funcao poe o `app.tenant_id` em cada tenant
da lista, le ou apaga **so desse tenant**, e no fim repoe o que estava. A lista
de tenants vem de quem chama (o `kamba_batch`, que le `platform.tenants`), e
uma lista com tenants a mais ou inventados so da linhas que nao existem.

**O limite que fica, e dito:** a funcao nao enumera os tenants sozinha (o
`FORCE` da `tenants` nao a deixa), pelo que um `kamba_batch` que a chame com um
**subconjunto** — `[A, B]`, par a par — fica a saber se A e B tem o mesmo dono e
compradores em comum. O `kamba_batch` e o papel auditado que atravessa tenants
e ja le as encomendas e os donos de todos; o que a funcao lhe nega e o
pseudonimo e o comprador. O SQL do modulo (`SQL_COMPRADORES_NOUTRA_LOJA_DO_DONO`)
passa sempre a lista inteira, e cada corrida fica no `audit_log`.

O `EXECUTE` das duas e **so** do `kamba_batch`; o `PUBLIC` perde-o. E nenhum
papel ganha `SELECT` na tabela alem do `kamba_identity`, que e quem a escreve
(o `INSERT ... ON CONFLICT DO UPDATE` le a linha que substitui).

## Em producao nao corre nada

Nao e esta revisao que o garante: e o interruptor do `correlacao.ts`
(`KAMBA_CORRELACAO_ENTRE_TENANTS`), trancado em `prod` no codigo ate um PR o
levantar com o parecer anexado (D1). A tabela existe em `prod` e fica vazia.

## Numero

`0087`, a vaga que a coordenacao do lote 18 deu ao KAM-208, sobre a `0086` do
KAM-233.

## Downgrade

Recusa se a `ts_signal` tem linhas do tipo novo: a tabela e *append-only* e o
dominio da `0056` nao as aceita. Senao larga as funcoes e a tabela — os
pseudonimos sao derivados e apagam-se sem copia: nao ha nada neles que nao se
recalcule do telefone na proxima resolucao — e repoe o dominio da `0056`.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None

TABELA = "platform.contact_xtenant_pseudonym"
FUNCAO_DO_ESQUECIMENTO = "platform.contact_xtenant_esquecer()"
SINAIS = "platform.ts_signal"

FUNCAO_DA_COMPARACAO = "platform.ts_compradores_noutra_loja_do_dono(uuid[])"
FUNCAO_DA_PURGA = "platform.contact_xtenant_purgar(uuid[], timestamptz)"

#: O dominio do tipo de sinal depois desta revisao: os nove da `0056` e o novo.
TIPOS_0087 = (
    "'auto_compra', 'burla_provavel', 'confirmacao_suspeita', "
    "'foto_repetida', 'preco_anomalo', 'queixa_recorrente', 'nao_entrega', "
    "'mudanca_de_conta', 'violacao_de_categoria', "
    "'comprador_noutra_loja_do_dono'"
)
#: O que o `downgrade` repoe: o dominio da `0056`.
TIPOS_0056 = (
    "'auto_compra', 'burla_provavel', 'confirmacao_suspeita', "
    "'foto_repetida', 'preco_anomalo', 'queixa_recorrente', 'nao_entrega', "
    "'mudanca_de_conta', 'violacao_de_categoria'"
)

#: A severidade fixa por tipo, depois desta revisao.
SEVERIDADE_0087 = """
               (tipo IN ('auto_compra', 'burla_provavel', 'mudanca_de_conta',
                         'violacao_de_categoria') AND severidade = 'alta')
            OR (tipo IN ('confirmacao_suspeita', 'queixa_recorrente', 'nao_entrega')
                AND severidade = 'media')
            OR (tipo IN ('foto_repetida', 'preco_anomalo',
                         'comprador_noutra_loja_do_dono') AND severidade = 'baixa')
"""
#: A da `0056`.
SEVERIDADE_0056 = """
               (tipo IN ('auto_compra', 'burla_provavel', 'mudanca_de_conta',
                         'violacao_de_categoria') AND severidade = 'alta')
            OR (tipo IN ('confirmacao_suspeita', 'queixa_recorrente', 'nao_entrega')
                AND severidade = 'media')
            OR (tipo IN ('foto_repetida', 'preco_anomalo') AND severidade = 'baixa')
"""


def _trocar_o_dominio(tipos: str, severidade: str) -> None:
    """Troca os dois `CHECK` do tipo, com `NO FORCE` a volta (a armadilha da `0038`)."""
    op.execute(f"ALTER TABLE {SINAIS} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SINAIS} DROP CONSTRAINT ts_signal_severidade_ck")
    op.execute(f"ALTER TABLE {SINAIS} DROP CONSTRAINT ts_signal_tipo_ck")
    op.execute(
        f"ALTER TABLE {SINAIS} ADD CONSTRAINT ts_signal_tipo_ck CHECK (tipo IN ({tipos}))"
    )
    op.execute(
        f"ALTER TABLE {SINAIS} ADD CONSTRAINT ts_signal_severidade_ck CHECK ({severidade})"
    )
    op.execute(f"ALTER TABLE {SINAIS} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.contact_xtenant_pseudonym (
          tenant_id    uuid NOT NULL
                       CONSTRAINT contact_xtenant_pseudonym_tenant_fk
                       REFERENCES platform.tenants (id),
          contact_id   uuid NOT NULL,
          pseudonimo   bytea NOT NULL
                       CONSTRAINT contact_xtenant_pseudonym_pseudonimo_ck
                       CHECK (octet_length(pseudonimo) = 32),
          kid          text NOT NULL
                       CONSTRAINT contact_xtenant_pseudonym_kid_ck
                       CHECK (kid ~ '^[a-z0-9][a-z0-9_.-]{0,62}$'),
          visto_at     timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT contact_xtenant_pseudonym_pkey PRIMARY KEY (tenant_id, contact_id),
          CONSTRAINT contact_xtenant_pseudonym_contact_fk
            FOREIGN KEY (tenant_id, contact_id)
            REFERENCES platform.contacts (tenant_id, contact_id)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.contact_xtenant_pseudonym IS
          'KAM-208: pseudonimo do telefone sem tenant (HMAC com chave e dominio proprios), por contacto. So o kamba_identity escreve e le; o lote compara-o so pela funcao ts_compradores_noutra_loja_do_dono, que devolve tenant e contagem. Retencao: 90 dias desde visto_at (proposta), purgada pelo lote. Base legal do tratamento cruzado (a confirmar por parecer).'
        """
    )
    op.execute(
        """
        CREATE INDEX contact_xtenant_pseudonym_visto_idx
          ON platform.contact_xtenant_pseudonym (tenant_id, visto_at)
        """
    )
    rls.enable_tenant_rls("contact_xtenant_pseudonym")

    op.execute(f"REVOKE ALL ON {TABELA} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABELA} TO kamba_identity")

    op.execute(
        """
        CREATE FUNCTION platform.ts_compradores_noutra_loja_do_dono(p_tenants uuid[])
          RETURNS TABLE (tenant_id uuid, contagem integer)
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = pg_catalog, platform
        AS $$
        #variable_conflict use_column
        DECLARE
          v_antes    text := current_setting('app.tenant_id', true);
          -- As janelas (D6 e D4, *propostas*): da funcao, e nao de quem chama.
          v_compra_desde timestamptz := now() - interval '30 days';
          v_visto_desde  timestamptz := now() - interval '90 days';
          v_tenant   uuid;
          v_dono_t   uuid[]  := '{}';
          v_dono_k   text[]  := '{}';
          v_dono_p   bytea[] := '{}';
          v_comp_t   uuid[]  := '{}';
          v_comp_k   text[]  := '{}';
          v_comp_p   bytea[] := '{}';
          v_linha    record;
        BEGIN
          FOREACH v_tenant IN ARRAY coalesce(p_tenants, '{}'::uuid[]) LOOP
            -- So este tenant: a RLS `FORCE` vincula tambem o dono da funcao.
            PERFORM set_config('app.tenant_id', v_tenant::text, true);

            -- O pseudonimo do dono deste tenant, pelo contacto que ficou se o
            -- do `owner_contact_id` foi absorvido numa fusao (achado 6). **Sem
            -- janela do `visto_at`**: o do dono nao vence enquanto ele for dono
            -- (decisao do fundador de 2026-11-22, opcao B).
            FOR v_linha IN
              WITH RECURSIVE dono(actual, passos) AS (
                  SELECT t.owner_contact_id, 0
                    FROM platform.tenants t
                   WHERE t.id = v_tenant AND t.owner_contact_id IS NOT NULL
                  UNION ALL
                  SELECT c.merged_into, k.passos + 1
                    FROM dono k
                    JOIN platform.contacts c
                      ON c.tenant_id = v_tenant AND c.contact_id = k.actual
                   WHERE c.merged_into IS NOT NULL AND k.passos < 16
                )
              SELECT DISTINCT x.kid, x.pseudonimo
                FROM dono k
                JOIN platform.contact_xtenant_pseudonym x
                  ON x.tenant_id = v_tenant AND x.contact_id = k.actual
            LOOP
              v_dono_t := v_dono_t || v_tenant;
              v_dono_k := v_dono_k || v_linha.kid;
              v_dono_p := v_dono_p || v_linha.pseudonimo;
            END LOOP;

            -- Os compradores deste tenant: o contacto da encomenda, seguido
            -- pelas fusoes ate ao que ficou (16 saltos, o tecto do KAM-008).
            FOR v_linha IN
              WITH RECURSIVE cadeia(origem, actual, passos) AS (
                  SELECT o.contact_id, o.contact_id, 0
                    FROM platform.orders_mirror o
                   WHERE o.tenant_id = v_tenant
                     AND (o.paga_at >= v_compra_desde OR o.entregue_at >= v_compra_desde)
                  UNION ALL
                  SELECT k.origem, c.merged_into, k.passos + 1
                    FROM cadeia k
                    JOIN platform.contacts c
                      ON c.tenant_id = v_tenant AND c.contact_id = k.actual
                   WHERE c.merged_into IS NOT NULL AND k.passos < 16
                )
              SELECT DISTINCT x.kid, x.pseudonimo
                FROM cadeia k
                JOIN platform.contact_xtenant_pseudonym x
                  ON x.tenant_id = v_tenant AND x.contact_id = k.actual
               WHERE x.visto_at >= v_visto_desde
            LOOP
              v_comp_t := v_comp_t || v_tenant;
              v_comp_k := v_comp_k || v_linha.kid;
              v_comp_p := v_comp_p || v_linha.pseudonimo;
            END LOOP;
          END LOOP;

          PERFORM set_config('app.tenant_id', coalesce(v_antes, ''), true);

          RETURN QUERY
            WITH donos AS (
                SELECT * FROM unnest(v_dono_t, v_dono_k, v_dono_p) AS d(t, k, p)
              ),
              comp AS (
                SELECT DISTINCT * FROM unnest(v_comp_t, v_comp_k, v_comp_p) AS c(t, k, p)
              )
            SELECT c.t, count(DISTINCT (c.k, c.p))::integer
              FROM comp c
              JOIN donos d  ON d.t = c.t
              JOIN donos d2 ON d2.k = d.k AND d2.p = d.p AND d2.t <> d.t
              JOIN comp c2  ON c2.t = d2.t AND c2.k = c.k AND c2.p = c.p
             GROUP BY c.t
             ORDER BY c.t;
        END
        $$
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION {FUNCAO_DA_COMPARACAO} IS
          'KAM-208: por tenant, quantos compradores compram tambem noutro tenant do mesmo dono. Devolve so o tenant e a contagem, nunca o pseudonimo nem o outro tenant. SECURITY DEFINER com o app.tenant_id de cada tenant da lista, reposto no fim. So o kamba_batch a executa.'
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.contact_xtenant_purgar(p_tenants uuid[], p_antes timestamptz)
          RETURNS integer
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_antes    text := current_setting('app.tenant_id', true);
          v_tenant   uuid;
          v_n        integer;
          v_total    integer := 0;
        BEGIN
          IF p_antes IS NULL THEN
            RAISE EXCEPTION 'contact_xtenant_purgar: o instante e obrigatorio'
              USING ERRCODE = '22004';
          END IF;
          FOREACH v_tenant IN ARRAY coalesce(p_tenants, '{}'::uuid[]) LOOP
            PERFORM set_config('app.tenant_id', v_tenant::text, true);
            -- O dono do tenant (e o contacto que o absorveu, se houve fusao)
            -- nao vence enquanto for dono (opcao B de 2026-11-22).
            WITH RECURSIVE dono(actual, passos) AS (
                SELECT t.owner_contact_id, 0
                  FROM platform.tenants t
                 WHERE t.id = v_tenant AND t.owner_contact_id IS NOT NULL
                UNION ALL
                SELECT c.merged_into, k.passos + 1
                  FROM dono k
                  JOIN platform.contacts c
                    ON c.tenant_id = v_tenant AND c.contact_id = k.actual
                 WHERE c.merged_into IS NOT NULL AND k.passos < 16
              )
            DELETE FROM platform.contact_xtenant_pseudonym x
             WHERE x.tenant_id = v_tenant AND x.visto_at < p_antes
               AND NOT EXISTS (SELECT 1 FROM dono d WHERE d.actual = x.contact_id);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_total := v_total + v_n;
          END LOOP;
          PERFORM set_config('app.tenant_id', coalesce(v_antes, ''), true);
          RETURN v_total;
        END
        $$
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION {FUNCAO_DA_PURGA} IS
          'KAM-208: a retencao do pseudonimo sem tenant. Apaga os vistos antes do instante, tenant a tenant, menos o do dono enquanto for dono, e devolve quantos. So o kamba_batch a executa.'
        """
    )
    for funcao in (FUNCAO_DA_COMPARACAO, FUNCAO_DA_PURGA):
        op.execute(f"REVOKE ALL ON FUNCTION {funcao} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {funcao} TO kamba_batch")

    op.execute(
        """
        CREATE FUNCTION platform.contact_xtenant_esquecer()
          RETURNS trigger
          LANGUAGE plpgsql
          SECURITY INVOKER
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          DELETE FROM platform.contact_xtenant_pseudonym x
           WHERE x.tenant_id = NEW.tenant_id AND x.contact_id = NEW.contact_id;
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION {FUNCAO_DO_ESQUECIMENTO} IS
          'KAM-208: o pseudonimo sem tenant vai quando o contacto perde o telefone, e fundido ou e apagado. SECURITY INVOKER: corre como o kamba_identity, que e quem muda essas colunas.'
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCAO_DO_ESQUECIMENTO} FROM PUBLIC")
    op.execute(
        f"""
        CREATE TRIGGER contacts_xtenant_esquecer
          AFTER UPDATE OF phone_hmac, erased_at, merged_into ON platform.contacts
          FOR EACH ROW
          WHEN (NEW.phone_hmac IS NULL OR NEW.erased_at IS NOT NULL OR NEW.merged_into IS NOT NULL)
          EXECUTE FUNCTION {FUNCAO_DO_ESQUECIMENTO}
        """
    )

    _trocar_o_dominio(TIPOS_0087, SEVERIDADE_0087)


def downgrade() -> None:
    """Desce, e **recusa** se a `ts_signal` ja tem sinais do tipo novo.

    A contagem corre com o `FORCE` desligado: com ele, o dono ve zero linhas e a
    guarda passava sempre (a armadilha que o KAM-050 mediu na `0038`).
    """
    op.execute(f"ALTER TABLE {SINAIS} NO FORCE ROW LEVEL SECURITY")
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.ts_signal "
            "WHERE tipo = 'comprador_noutra_loja_do_dono'"
        )
        .scalar_one()
    )
    op.execute(f"ALTER TABLE {SINAIS} FORCE ROW LEVEL SECURITY")
    if linhas:
        raise RuntimeError(
            f"downgrade da 0087 recusado: ha {linhas} sinal(is) comprador_noutra_loja_do_dono "
            "na ts_signal e o dominio da 0056 nao os aceita. A ts_signal e append-only: "
            "decida o que fazer a essas linhas antes de descer."
        )
    _trocar_o_dominio(TIPOS_0056, SEVERIDADE_0056)
    op.execute("DROP TRIGGER contacts_xtenant_esquecer ON platform.contacts")
    op.execute(f"DROP FUNCTION {FUNCAO_DO_ESQUECIMENTO}")
    op.execute(f"DROP FUNCTION {FUNCAO_DA_PURGA}")
    op.execute(f"DROP FUNCTION {FUNCAO_DA_COMPARACAO}")
    rls.disable_tenant_rls("contact_xtenant_pseudonym")
    op.execute("DROP TABLE platform.contact_xtenant_pseudonym")
