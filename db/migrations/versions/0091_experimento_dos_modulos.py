"""O experimento dos modulos de entrada: H10, H11, H12, as decisoes e a coorte (KAM-127).

## O que esta revisao cria

| Objecto | O que e |
|---|---|
| `platform.module_decisions` | a decisao **manter / ajustar / abater** de cada modulo, so de acrescentar |
| `platform.module_experiment_exclusions` | os tenants da equipa e de teste, fora da coorte |
| `platform.experimento_valores(agora)` | o primeiro **resultado de valor** de cada tenant em cada modulo |
| `platform.experimento_coorte(agora)` | os tenants da coorte: o primeiro `tenant.provisioned`, so PME, sem exclusoes |
| `platform.experimento_h10(agora, janela)` | a H10 por tenant: censura e uso de cada modulo na janela |
| `platform.experimento_h11(agora, janela)` | a H11 por tenant: entrou por um modulo, e activou o atendimento |
| `platform.v_h10`, `platform.v_h11` | as duas funcoes com `now()` e as janelas pre-registadas (14 e 30 dias) |
| `platform.v_h12_pagantes` | os tenants com um ciclo pago de um plano de **um so** modulo |

A `v_h12` (custo, preco de teste e racio) e do KAM-124 (`0057`) e nao muda.

## «Usa um modulo» e um resultado de valor (criterio 2)

| Modulo | O resultado | De onde | O instante |
|---|---|---|---|
| `catalogo` | >= 1 produto publicado | `catalog_ingestions.estado = 'publicada'` | `confirmado_at` |
| `foto` | >= 1 versao escolhida | `image_jobs.escolhida`, sem as `sintetica` | `atualizado_at` (**INDICIO**: a tabela nao guarda o instante da escolha) |
| `social` | >= 1 item aprovado | `content.approved` no `events_log` | `ocorrido_em` |
| `orcamento` | >= 1 `quote.sent` | `quote.sent` no `events_log` | `ocorrido_em` |

Os eventos leem-se do **`events_log`** (24 meses, KAM-007) e **nao** do
`events_outbox`, que a retencao apaga 7 dias depois de publicado: uma leitura da
semana 12 sobre o *outbox* nao via o `tenant.provisioned` da semana 1.

## A coorte e o relogio

O instante de entrada e o **primeiro** `tenant.provisioned` do tenant no
`events_log`. Ficam de fora os tenants que nao sao `pme` (`tenants.tipo`) e os
da `module_experiment_exclusions` (equipa e teste). As quatro funcoes recebem o
relogio (`agora`) e as janelas: os ensaios passam um relogio fixo, e as vistas
passam `now()` e as janelas do `config/experimento_modulos.yaml` (um ensaio
confronta os literais com o ficheiro).

## Sem pessoas (ADR-010)

Nenhuma vista nem funcao devolve `contact_id`, telefone, nome ou conteudo: so
`tenant_id`, nomes de modulo, instantes e booleanos. O `contact_id` do payload
le-se por dentro (para separar o cliente do dono na H11) e nao sai.

**O cliente e quem nao e o `tenants.owner_contact_id`**, e nao o
`contacts.papel`: o `kamba_batch` tem `BYPASSRLS`, e um `SELECT` de qualquer
coluna da `contacts` dava-lhe o cofre de identidade de todos os tenants (o
`test_kamba_batch_e_kamba_resolver_nao_tocam_no_cofre`, e a licao do KAM-200).
As duas dizem o mesmo: a `platform.definir_dono` (`0070`) e o escritor unico do
papel **e** do `owner_contact_id`, na mesma transaccao.

## As janelas sao semiabertas

`[inicio, inicio + janela)` nas duas hipoteses: um valor aos 14 dias exactos nao
conta na H10, e uma resposta aos 30 dias exactos nao conta na H11. A censura e a
mesma: aos 14 (ou 30) dias exactos deixa de estar censurado.

## Privilegios

So o `kamba_batch` le as vistas e executa as funcoes, e e ele que escreve as
duas tabelas. Para as funcoes correrem como ele, recebe o `SELECT` de **duas
colunas** que nao tinha — `catalog_ingestions (estado, confirmado_at)` —, e nada
de conteudo. As funcoes sao `SECURITY INVOKER`.

As duas tabelas sao so de acrescentar por dois gatilhos `ENABLE ALWAYS` cada:
um recusa `UPDATE` e `DELETE`, o outro o `TRUNCATE` (que nao dispara gatilhos
de linha), como o *ledger* da `0057`.

## O `downgrade`

Larga as vistas, as funcoes, os gatilhos e as duas tabelas, sem `CASCADE`, e
devolve os dois `SELECT` de coluna. As decisoes e as exclusoes vao com as
tabelas: uma base onde se desce esta revisao e de ensaio.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0091"
#: Sobre a `0090` do KAM-239, o numero que a coordenacao deu (fila 0087 KAM-208,
#: 0088 KAM-209, 0089 KAM-240, 0090 KAM-239).
down_revision = "0086"
branch_labels = None
depends_on = None

DECISOES = "platform.module_decisions"
EXCLUSOES = "platform.module_experiment_exclusions"
PAPEL_DE_LOTE = "kamba_batch"

#: Os quatro modulos de entrada (dicionario §3.7). Copiados e nao importados:
#: uma revisao nao importa outra.
MODULOS = ("'catalogo'", "'foto'", "'social'", "'orcamento'")

#: As tres vistas. As quatro funcoes escrevem-se por extenso no `GRANT` e no
#: `DROP`: o gate 3b nao segue um tuplo de nomes.
VISTAS = ("v_h10", "v_h11", "v_h12_pagantes")

#: As janelas pre-registadas (`config/experimento_modulos.yaml`). Um ensaio
#: confronta-as com o ficheiro.
JANELA_DE_USO_DIAS = 14
JANELA_DE_ACTIVACAO_DIAS = 30


def upgrade() -> None:
    _tabelas()
    _privilegios_de_leitura()
    _funcoes()
    _vistas()
    _privilegios()


def _tabelas() -> None:
    op.execute(
        f"""
        CREATE TABLE {DECISOES} (
          id            uuid CONSTRAINT module_decisions_pkey PRIMARY KEY
                        DEFAULT gen_random_uuid(),
          modulo        text NOT NULL
                        CONSTRAINT module_decisions_modulo_ck CHECK (modulo IN ({", ".join(MODULOS)})),
          data_decisao  date NOT NULL,
          metricas      jsonb NOT NULL
                        CONSTRAINT module_decisions_metricas_ck CHECK (jsonb_typeof(metricas) = 'object'),
          criterio      text
                        CONSTRAINT module_decisions_criterio_ck
                        CHECK (criterio IS NULL OR char_length(criterio) BETWEEN 1 AND 200),
          decisao       text NOT NULL
                        CONSTRAINT module_decisions_decisao_ck
                        CHECK (decisao IN ('manter', 'ajustar', 'abater')),
          responsavel   text NOT NULL
                        CONSTRAINT module_decisions_responsavel_ck
                        CHECK (char_length(responsavel) BETWEEN 1 AND 120),
          justificacao  text NOT NULL
                        CONSTRAINT module_decisions_justificacao_ck
                        CHECK (char_length(justificacao) BETWEEN 1 AND 2000),
          revisao_em    date,
          registado_em  timestamptz NOT NULL DEFAULT clock_timestamp(),
          CONSTRAINT module_decisions_catalogo_ck CHECK (modulo <> 'catalogo' OR decisao <> 'abater'),
          CONSTRAINT module_decisions_ajustar_ck CHECK (decisao <> 'ajustar' OR revisao_em IS NOT NULL),
          CONSTRAINT module_decisions_revisao_ck CHECK (revisao_em IS NULL OR revisao_em >= data_decisao)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {DECISOES} IS "
        "'A decisao manter/ajustar/abater de cada modulo de entrada (KAM-127). Global, sem tenant. "
        "So de acrescentar, por privilegio e por trigger. O catalogo nunca se abate (ADR-020).'"
    )
    op.execute(
        f"""
        CREATE TABLE {EXCLUSOES} (
          tenant_id      uuid CONSTRAINT module_experiment_exclusions_pkey PRIMARY KEY
                         CONSTRAINT module_experiment_exclusions_tenant_fk REFERENCES platform.tenants (id),
          motivo         text NOT NULL
                         CONSTRAINT module_experiment_exclusions_motivo_ck CHECK (motivo IN ('equipa', 'teste')),
          registado_por  text NOT NULL
                         CONSTRAINT module_experiment_exclusions_registado_por_ck
                         CHECK (char_length(registado_por) BETWEEN 1 AND 120),
          registado_em   timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {EXCLUSOES} IS "
        "'Os tenants da equipa e de teste, fora da coorte do experimento dos modulos (KAM-127). "
        "So de acrescentar: uma exclusao feita depois da medicao muda o N, e fica escrita.'"
    )
    op.execute(
        """
        CREATE FUNCTION platform.experimento_so_acrescenta()
          RETURNS trigger
          LANGUAGE plpgsql
          SET search_path = pg_catalog, platform
        AS $$
        BEGIN
          RAISE EXCEPTION 'o registo do experimento dos modulos nao se emenda nem se apaga'
            USING ERRCODE = 'object_not_in_prerequisite_state';
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.experimento_so_acrescenta() FROM PUBLIC")
    for tabela, gatilho, truncar in (
        (DECISOES, "module_decisions_imutavel", "module_decisions_sem_truncate"),
        (EXCLUSOES, "module_experiment_exclusions_imutavel", "module_experiment_exclusions_sem_truncate"),
    ):
        op.execute(
            f"CREATE TRIGGER {gatilho} BEFORE UPDATE OR DELETE ON {tabela} "
            "FOR EACH ROW EXECUTE FUNCTION platform.experimento_so_acrescenta()"
        )
        op.execute(
            f"CREATE TRIGGER {truncar} BEFORE TRUNCATE ON {tabela} "
            "FOR EACH STATEMENT EXECUTE FUNCTION platform.experimento_so_acrescenta()"
        )
        op.execute(f"ALTER TABLE {tabela} ENABLE ALWAYS TRIGGER {gatilho}")
        op.execute(f"ALTER TABLE {tabela} ENABLE ALWAYS TRIGGER {truncar}")
    rls.enable_tenant_rls("module_experiment_exclusions")


def _privilegios_de_leitura() -> None:
    op.execute(f"GRANT SELECT (estado, confirmado_at) ON platform.catalog_ingestions TO {PAPEL_DE_LOTE}")


def _funcoes() -> None:
    op.execute(
        f"""
        CREATE FUNCTION platform.experimento_valores(p_agora timestamptz)
          RETURNS TABLE (tenant_id uuid, modulo text, primeiro_em timestamptz)
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT c.tenant_id, 'catalogo'::text, min(c.confirmado_at)
            FROM platform.catalog_ingestions c
           WHERE c.estado = 'publicada' AND c.confirmado_at <= p_agora
           GROUP BY c.tenant_id
          UNION ALL
          SELECT j.tenant_id, 'foto'::text, min(j.atualizado_at)
            FROM platform.image_jobs j
           WHERE j.escolhida AND NOT j.sintetica AND j.atualizado_at <= p_agora
           GROUP BY j.tenant_id
          UNION ALL
          SELECT l.tenant_id,
                 CASE l.tipo WHEN 'content.approved' THEN 'social' ELSE 'orcamento' END,
                 min(l.ocorrido_em)
            FROM platform.events_log l
           WHERE l.tipo IN ('content.approved', 'quote.sent') AND l.ocorrido_em <= p_agora
           GROUP BY l.tenant_id, l.tipo
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.experimento_coorte(p_agora timestamptz)
          RETURNS TABLE (tenant_id uuid, provisionado_em timestamptz)
          LANGUAGE sql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
          SELECT l.tenant_id, min(l.ocorrido_em)
            FROM platform.events_log l
            JOIN platform.tenants t ON t.id = l.tenant_id
           WHERE l.tipo = 'tenant.provisioned'
             AND l.ocorrido_em <= p_agora
             AND t.tipo = 'pme'
             AND NOT EXISTS (SELECT 1 FROM platform.module_experiment_exclusions x
                              WHERE x.tenant_id = l.tenant_id)
           GROUP BY l.tenant_id
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.experimento_h10(p_agora timestamptz, p_janela_dias integer)
          RETURNS TABLE (tenant_id uuid, provisionado_em timestamptz, censurado boolean,
                         catalogo boolean, foto boolean, social boolean, orcamento boolean,
                         algum boolean)
          LANGUAGE plpgsql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
        #variable_conflict use_column
        BEGIN
          IF p_agora IS NULL OR p_janela_dias IS NULL OR p_janela_dias <= 0 THEN
            RAISE EXCEPTION 'experimento_h10 sem relogio ou com janela invalida'
              USING ERRCODE = 'invalid_parameter_value';
          END IF;
          RETURN QUERY
          WITH c AS (SELECT * FROM platform.experimento_coorte(p_agora)),
               v AS (SELECT * FROM platform.experimento_valores(p_agora)),
               u AS (
                 SELECT c.tenant_id, v.modulo
                   FROM c JOIN v ON v.tenant_id = c.tenant_id
                  WHERE v.primeiro_em < c.provisionado_em + p_janela_dias * interval '1 day'
               )
          SELECT c.tenant_id,
                 c.provisionado_em,
                 c.provisionado_em > p_agora - p_janela_dias * interval '1 day',
                 EXISTS (SELECT 1 FROM u WHERE u.tenant_id = c.tenant_id AND u.modulo = 'catalogo'),
                 EXISTS (SELECT 1 FROM u WHERE u.tenant_id = c.tenant_id AND u.modulo = 'foto'),
                 EXISTS (SELECT 1 FROM u WHERE u.tenant_id = c.tenant_id AND u.modulo = 'social'),
                 EXISTS (SELECT 1 FROM u WHERE u.tenant_id = c.tenant_id AND u.modulo = 'orcamento'),
                 EXISTS (SELECT 1 FROM u WHERE u.tenant_id = c.tenant_id)
            FROM c;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.experimento_h11(p_agora timestamptz, p_janela_dias integer)
          RETURNS TABLE (tenant_id uuid, primeiro_valor_em timestamptz, primeiro_modulo text,
                         primeira_conversa_em timestamptz, entrou_por_modulo boolean,
                         censurado boolean, activou boolean)
          LANGUAGE plpgsql
          STABLE
          SET search_path = pg_catalog, platform
        AS $$
        #variable_conflict use_column
        BEGIN
          IF p_agora IS NULL OR p_janela_dias IS NULL OR p_janela_dias <= 0 THEN
            RAISE EXCEPTION 'experimento_h11 sem relogio ou com janela invalida'
              USING ERRCODE = 'invalid_parameter_value';
          END IF;
          RETURN QUERY
          WITH c AS (SELECT * FROM platform.experimento_coorte(p_agora)),
               v AS (SELECT * FROM platform.experimento_valores(p_agora)),
               primeiro AS (
                 SELECT DISTINCT ON (v.tenant_id) v.tenant_id, v.primeiro_em, v.modulo
                   FROM v
                  ORDER BY v.tenant_id, v.primeiro_em, v.modulo
               ),
               -- A resposta do bot a um **cliente** pelo WhatsApp, numa conversa
               -- que nao e de teste. O cliente e quem nao e o dono do tenant
               -- (`owner_contact_id`, o mesmo escritor do `contacts.papel`). O
               -- `contact_id` le-se aqui e nao sai.
               atendidas AS (
                 SELECT l.tenant_id, l.ocorrido_em
                   FROM platform.events_log l
                   JOIN platform.tenants t ON t.id = l.tenant_id
                   JOIN platform.conversations cv
                     ON cv.tenant_id = l.tenant_id
                    AND cv.id = (l.envelope->'payload'->>'conversation_id')::uuid
                  WHERE l.tipo = 'agent.replied'
                    AND l.envelope->'payload'->>'canal' = 'whatsapp'
                    AND l.ocorrido_em <= p_agora
                    AND (l.envelope->'payload'->>'contact_id')::uuid
                        IS DISTINCT FROM t.owner_contact_id
                    AND NOT cv.is_test
               ),
               primeira AS (
                 SELECT a.tenant_id, min(a.ocorrido_em) AS em FROM atendidas a GROUP BY a.tenant_id
               ),
               linhas AS (
                 SELECT c.tenant_id,
                        p.primeiro_em,
                        p.modulo,
                        pr.em AS conversa_em,
                        (p.primeiro_em IS NOT NULL AND (pr.em IS NULL OR p.primeiro_em < pr.em)) AS entrou
                   FROM c
                   LEFT JOIN primeiro p ON p.tenant_id = c.tenant_id
                   LEFT JOIN primeira pr ON pr.tenant_id = c.tenant_id
               )
          SELECT ln.tenant_id,
                 ln.primeiro_em,
                 ln.modulo,
                 ln.conversa_em,
                 ln.entrou,
                 ln.entrou AND ln.primeiro_em > p_agora - p_janela_dias * interval '1 day',
                 ln.entrou
                   AND EXISTS (
                     SELECT 1 FROM platform.tenant_channels ch
                      WHERE ch.tenant_id = ln.tenant_id AND ch.estado = 'ativo'
                        AND ch.vertical IN ('vendedor', 'servicos'))
                   AND EXISTS (
                     SELECT 1 FROM platform.entitlements e
                      WHERE e.tenant_id = ln.tenant_id AND e.ativo
                        AND e.modulo IN ('vendedor', 'servicos'))
                   AND EXISTS (
                     SELECT 1 FROM atendidas a
                      WHERE a.tenant_id = ln.tenant_id
                        AND a.ocorrido_em < ln.primeiro_em + p_janela_dias * interval '1 day')
            FROM linhas ln;
        END
        $$
        """
    )


def _vistas() -> None:
    op.execute(
        f"""
        CREATE VIEW platform.v_h10 WITH (security_invoker = true) AS
          SELECT * FROM platform.experimento_h10(now(), {JANELA_DE_USO_DIAS})
        """
    )
    op.execute(
        f"""
        CREATE VIEW platform.v_h11 WITH (security_invoker = true) AS
          SELECT * FROM platform.experimento_h11(now(), {JANELA_DE_ACTIVACAO_DIAS})
        """
    )
    # Um plano de **um so** modulo e um plano com uma so linha de preco de teste
    # (`module_test_prices`, KAM-124): os `entrada_<modulo>`. O `entrada_completo`
    # tem quatro e nao conta. O plano e o **actual** da subscricao, como na
    # `v_h12`: um tenant que mudou de plano conta pelo de agora — limite dito.
    # So os tenants da coorte (o primeiro `tenant.provisioned`, PME, sem
    # exclusao), como a H10 e a H11.
    op.execute(
        """
        CREATE VIEW platform.v_h12_pagantes WITH (security_invoker = true) AS
          WITH isolados AS (
            SELECT p.plano, min(p.modulo) AS modulo
              FROM platform.module_test_prices p
             GROUP BY p.plano
            HAVING count(*) = 1
          )
          SELECT s.tenant_id, s.plano, i.modulo,
                 count(*)::integer AS ciclos_pagos
            FROM platform.subscriptions s
            JOIN isolados i ON i.plano = s.plano
            JOIN platform.billing_cycles b
              ON b.subscription_id = s.id AND b.tenant_id = s.tenant_id AND b.estado = 'paga'
            JOIN platform.experimento_coorte(now()) c ON c.tenant_id = s.tenant_id
           GROUP BY s.tenant_id, s.plano, i.modulo
        """
    )


def _privilegios() -> None:
    for tabela in (DECISOES, EXCLUSOES):
        op.execute(f"REVOKE ALL ON {tabela} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT ON {tabela} TO {PAPEL_DE_LOTE}")
    for vista_lida in VISTAS:
        op.execute(f"REVOKE ALL ON platform.{vista_lida} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON platform.{vista_lida} TO {PAPEL_DE_LOTE}")
    op.execute("REVOKE ALL ON FUNCTION platform.experimento_valores(timestamptz) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.experimento_valores(timestamptz) TO kamba_batch")
    op.execute("REVOKE ALL ON FUNCTION platform.experimento_coorte(timestamptz) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.experimento_coorte(timestamptz) TO kamba_batch")
    op.execute("REVOKE ALL ON FUNCTION platform.experimento_h10(timestamptz, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.experimento_h10(timestamptz, integer) TO kamba_batch")
    op.execute("REVOKE ALL ON FUNCTION platform.experimento_h11(timestamptz, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION platform.experimento_h11(timestamptz, integer) TO kamba_batch")


def downgrade() -> None:
    op.execute("DROP VIEW platform.v_h12_pagantes")
    op.execute("DROP VIEW platform.v_h11")
    op.execute("DROP VIEW platform.v_h10")
    op.execute("DROP FUNCTION platform.experimento_h11(timestamptz, integer)")
    op.execute("DROP FUNCTION platform.experimento_h10(timestamptz, integer)")
    op.execute("DROP FUNCTION platform.experimento_coorte(timestamptz)")
    op.execute("DROP FUNCTION platform.experimento_valores(timestamptz)")
    op.execute(f"REVOKE SELECT (estado, confirmado_at) ON platform.catalog_ingestions FROM {PAPEL_DE_LOTE}")
    rls.disable_tenant_rls("module_experiment_exclusions")
    op.execute(f"DROP TABLE {EXCLUSOES}")
    op.execute(f"DROP TABLE {DECISOES}")
    op.execute("DROP FUNCTION platform.experimento_so_acrescenta()")
