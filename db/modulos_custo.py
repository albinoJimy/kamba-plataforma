"""As vistas e a consolidacao do custo por modulo de entrada (KAM-124).

O SQL das duas vistas vive **aqui** e nao na revisao, pela razao do
`db/custo.py` (KAM-081): os ensaios importam-no em vez de o copiarem, e o
*gate* 3b le-o seguindo o corpo de `criar_vistas()` — este ficheiro esta
declarado em `ci/canon-lint.yaml` como modulo auxiliar de migracao. Por isso as
consultas sao cadeias **literais**, sem *f-strings*.

**Mudar uma vista e uma revisao nova**, que faz `DROP VIEW` e chama a versao
nova; a `custo_dos_modulos` nao se reescreve.

## As duas vistas

* `platform.v_module_cost_month` — uma linha por `(tenant_id, mes, modulo,
  rubrica)`. O `mes` e o de `platform.ten_periodo` (Africa/Luanda), o mesmo
  periodo em que o `imagens_mes` e os outros contadores fecham: o custo de um
  mes e o uso desse mes falam do mesmo intervalo.
* `platform.v_h12` — uma linha por `(tenant_id, mes, modulo)`, com o preco de
  teste do plano do tenant, o racio custo/preco e a margem. **Sem preco, o
  racio e a margem sao nulos**, e nao zero: um tenant fora dos planos
  `entrada_*` nao tem hipotese a medir.

O cambio e o parametro de sessao `app.fx_aoa_per_usd` (omissao 913), lido como
na `v_tenant_cost_daily`: um valor ilegivel, zero ou negativo **levanta**.

## Sem pessoas

Nenhuma coluna aponta para uma pessoa: nem `contact_id`, nem telefone, nem
conteudo. As colunas sao listas fechadas (`COLUNAS_DO_MES`, `COLUNAS_DA_H12`) e
o ensaio da ausencia de PII compara-as com a base por igualdade.

## A consolidacao

Tres consultas, uma por rubrica, que o `h12-export consolidar` corre como
`kamba_batch`. Cada uma escreve pela `platform.module_cost_gravar` com uma chave
de idempotencia derivada da linha de origem (`llm:<id>`, `imagem:<id>`,
`mensagem:<id>`), pelo que correr duas vezes nao duplica nada — e correr de 5
em 5 minutos e o que poe o consumo de uma PME no painel no prazo do criterio 9.

**So o que o ledger ainda nao tem** (o `NOT EXISTS` pela chave), e por duas
razoes medidas na revisao adversarial. A primeira: uma linha ja consolidada que
hoje se calculasse diferente — uma tarifa da Meta revista, um *template*
remapeado — fazia a `module_cost_gravar` levantar `23514` em **todas** as
corridas seguintes, e o ledger parava sem aviso. Um custo consolidado fica como
foi registado; uma tarifa nova vale para o que entrar depois. A segunda: sem o
filtro, cada corrida chamava a funcao uma vez por linha de todo o historico.

* **imagem** — `platform.image_jobs` em estado **final** (`concluido`,
  `falhado`) com custo. Um trabalho ainda vivo pode vir a custar mais (a
  contingencia), e um custo consolidado nao se reescreve. O instante e o
  `criado_at`, e nao o `atualizado_at`: este muda quando o dono escolhe a
  versao, e o mes de um custo nao pode depender de quando a consolidacao
  correu. E o mesmo instante que a guarda de orcamento le
  (`kamba_core.modulos.uso`).
* **llm** — `dat.llm_call_log` cuja `vertical` e um modulo de entrada. E esta a
  etiqueta `modulo` do cliente LLM: as verticais `catalogo` e `social` sao
  modulos. **O orcamento expresso corre dentro do Vendedor** (KAM-123), e por
  isso o seu custo LLM nao e separavel pela `vertical` — fica como divida, com
  credor no bloco.
* **mensagem** — `platform.outbound_messages` entregues e cobraveis cujo
  `template_name` o mapa *template* -> modulo conhece
  (`config/templates_por_modulo.yaml`). Tarifa da categoria, como na
  `v_tenant_cost_daily`.
"""

from __future__ import annotations

from typing import Final

from alembic import op

VISTA_DO_MES: Final = "platform.v_module_cost_month"
VISTA_DA_H12: Final = "platform.v_h12"

#: Os quatro modulos de entrada (dicionario §3.7). Lista fechada, igual ao
#: `CHECK` das duas tabelas da revisao.
MODULOS: Final = ("catalogo", "foto", "social", "orcamento")

#: As tres rubricas do ledger.
RUBRICAS: Final = ("llm", "imagem", "mensagem")

#: As colunas de cada vista, pela ordem do `SELECT`. **Listas fechadas.**
COLUNAS_DO_MES: Final = (
    "tenant_id",
    "mes",
    "modulo",
    "rubrica",
    "unidades",
    "custo_usd",
    "custo_aoa_minor",
    "fx_aoa_per_usd",
)
COLUNAS_DA_H12: Final = (
    "tenant_id",
    "mes",
    "modulo",
    "custo_usd",
    "custo_aoa_minor",
    "fx_aoa_per_usd",
    "preco_teste_minor",
    "racio",
    "margem_minor",
)

#: O contador de uso de cada modulo (`registry/entitlement_keys.schema.json`).
#: O `catalogo` nao tem contador proprio.
CHAVE_DE_USO: Final = {
    "foto": "imagens_mes",
    "social": "posts_mes",
    "orcamento": "orcamentos_mes",
}

SQL_CRIAR_VISTA_DO_MES: Final = """
CREATE VIEW platform.v_module_cost_month
  WITH (security_invoker = true) AS
WITH cambio_lido AS (
    SELECT COALESCE(
               NULLIF(current_setting('app.fx_aoa_per_usd', true), '')::numeric,
               913
           ) AS valor
),
cambio AS (
    SELECT CASE
               WHEN c.valor > 0 THEN c.valor
               ELSE (c.valor::text || ' nao e um cambio positivo')::numeric
           END AS fx_aoa_per_usd
      FROM cambio_lido c
),
custo AS (
    SELECT l.tenant_id,
           platform.ten_periodo(l.ocorrido_em) AS mes,
           l.modulo,
           l.rubrica,
           count(*) AS unidades,
           sum(l.custo_usd) AS custo_usd
      FROM platform.module_cost_ledger l
     GROUP BY l.tenant_id, platform.ten_periodo(l.ocorrido_em), l.modulo, l.rubrica
)
SELECT r.tenant_id,
       r.mes,
       r.modulo,
       r.rubrica,
       r.unidades,
       r.custo_usd,
       round(r.custo_usd * c.fx_aoa_per_usd * 100)::bigint AS custo_aoa_minor,
       c.fx_aoa_per_usd
  FROM custo r
 CROSS JOIN cambio c
"""

SQL_CRIAR_VISTA_DA_H12: Final = """
CREATE VIEW platform.v_h12
  WITH (security_invoker = true) AS
WITH custo AS (
    SELECT m.tenant_id,
           m.mes,
           m.modulo,
           sum(m.custo_usd) AS custo_usd,
           max(m.fx_aoa_per_usd) AS fx_aoa_per_usd
      FROM platform.v_module_cost_month m
     GROUP BY m.tenant_id, m.mes, m.modulo
),
em_kz AS (
    SELECT c.tenant_id,
           c.mes,
           c.modulo,
           c.custo_usd,
           round(c.custo_usd * c.fx_aoa_per_usd * 100)::bigint AS custo_aoa_minor,
           c.fx_aoa_per_usd
      FROM custo c
)
SELECT k.tenant_id,
       k.mes,
       k.modulo,
       k.custo_usd,
       k.custo_aoa_minor,
       k.fx_aoa_per_usd,
       p.preco_teste_minor,
       CASE
           WHEN p.preco_teste_minor > 0
           THEN round(k.custo_aoa_minor::numeric / p.preco_teste_minor, 6)
       END AS racio,
       p.preco_teste_minor - k.custo_aoa_minor AS margem_minor
  FROM em_kz k
  JOIN platform.tenants t ON t.id = k.tenant_id
  LEFT JOIN platform.module_test_prices p
         ON p.plano = t.plano AND p.modulo = k.modulo
"""

SQL_COMENTAR_VISTA_DO_MES: Final = """
COMMENT ON VIEW platform.v_module_cost_month IS
'Custo por tenant, mes (Africa/Luanda), modulo de entrada e rubrica (KAM-124), do platform.module_cost_ledger. Kz ao cambio do parametro app.fx_aoa_per_usd, omissao 913 (INDICIO). Sem contact_id, telefone nem conteudo. security_invoker: corre com a RLS de quem le.'
"""

SQL_COMENTAR_VISTA_DA_H12: Final = """
COMMENT ON VIEW platform.v_h12 IS
'H12 por tenant, mes e modulo (KAM-124): custo, preco de teste do plano do tenant (hipotese_nao_validada), racio custo/preco e margem, em centimos de Kz. Sem preco, racio e margem nulos. Sem contact_id, telefone nem conteudo.'
"""

SQL_CONCEDER_VISTA_DO_MES: Final = (
    "GRANT SELECT ON platform.v_module_cost_month TO kamba_batch, kamba_app"
)
SQL_CONCEDER_VISTA_DA_H12: Final = "GRANT SELECT ON platform.v_h12 TO kamba_batch"

SQL_REMOVER_VISTA_DA_H12: Final = "DROP VIEW platform.v_h12"
SQL_REMOVER_VISTA_DO_MES: Final = "DROP VIEW platform.v_module_cost_month"


def criar_vistas() -> None:
    """Cria as duas vistas, comenta-as e concede a leitura. Chamado pela revisao."""
    op.execute(SQL_CRIAR_VISTA_DO_MES)
    op.execute(SQL_COMENTAR_VISTA_DO_MES)
    op.execute(SQL_CONCEDER_VISTA_DO_MES)
    op.execute(SQL_CRIAR_VISTA_DA_H12)
    op.execute(SQL_COMENTAR_VISTA_DA_H12)
    op.execute(SQL_CONCEDER_VISTA_DA_H12)


def remover_vistas() -> None:
    """O inverso, pela ordem das dependencias. Sem `CASCADE`."""
    op.execute(SQL_REMOVER_VISTA_DA_H12)
    op.execute(SQL_REMOVER_VISTA_DO_MES)


# --------------------------------------------------------------- consolidacao
#
# Os tres `SELECT` devolvem quantas linhas a funcao gravou (`gravado = true`).
# O parametro e o cambio do registo; o da mensagem leva tambem os dois *arrays*
# do mapa *template* -> modulo.

SQL_CONSOLIDAR_IMAGEM: Final = """
SELECT count(*) FILTER (WHERE g.gravado) AS gravadas
  FROM platform.image_jobs j
 CROSS JOIN LATERAL platform.module_cost_gravar(
           j.tenant_id, 'foto', 'imagem', j.custo_usd, j.image_job_id::text,
           'imagem:' || j.image_job_id::text, j.criado_at, %s) g
 WHERE j.estado IN ('concluido', 'falhado')
   AND j.custo_usd > 0
   AND NOT EXISTS (
       SELECT 1 FROM platform.module_cost_ledger l
        WHERE l.tenant_id = j.tenant_id
          AND l.idempotency_key = 'imagem:' || j.image_job_id::text)
"""

SQL_CONSOLIDAR_LLM: Final = """
SELECT count(*) FILTER (WHERE g.gravado) AS gravadas
  FROM dat.llm_call_log c
 CROSS JOIN LATERAL platform.module_cost_gravar(
           c.tenant_id, c.vertical, 'llm', c.custo_usd, c.id::text,
           'llm:' || c.id::text, c.ts, %s) g
 WHERE c.vertical IN ('catalogo', 'foto', 'social', 'orcamento')
   AND c.resultado <> 'destino_negado'
   AND c.custo_usd > 0
   AND NOT EXISTS (
       SELECT 1 FROM platform.module_cost_ledger l
        WHERE l.tenant_id = c.tenant_id
          AND l.idempotency_key = 'llm:' || c.id::text)
"""

SQL_CONSOLIDAR_MENSAGEM: Final = """
WITH mapa AS (
    SELECT * FROM unnest(%s::text[], %s::text[]) AS m(template_name, modulo)
),
entregues AS (
    SELECT o.id,
           o.tenant_id,
           m.modulo,
           o.delivered_at,
           CASE o.pricing ->> 'category'
               WHEN 'service' THEN 4000
               WHEN 'utility' THEN 4000
               WHEN 'authentication' THEN 4000
               WHEN 'marketing' THEN 22500
           END AS usd_micro
      FROM platform.outbound_messages o
      JOIN mapa m ON m.template_name = o.template_name
     WHERE o.delivered_at IS NOT NULL
       AND CASE
               WHEN jsonb_typeof(o.pricing -> 'billable') = 'boolean'
               THEN (o.pricing -> 'billable')::boolean
               ELSE false
           END
       AND NOT EXISTS (
           SELECT 1 FROM platform.module_cost_ledger l
            WHERE l.tenant_id = o.tenant_id
              AND l.idempotency_key = 'mensagem:' || o.id::text)
)
SELECT count(*) FILTER (WHERE g.gravado) AS gravadas
  FROM entregues e
 CROSS JOIN LATERAL platform.module_cost_gravar(
           e.tenant_id, e.modulo, 'mensagem', e.usd_micro::numeric / 1000000,
           e.id::text, 'mensagem:' || e.id::text, e.delivered_at, %s) g
 WHERE e.usd_micro IS NOT NULL
"""

#: Mensagens cobraveis de *template* mapeado e categoria desconhecida: nao
#: entram no ledger (nao ha tarifa) e contam-se para o alerta de custo por medir.
SQL_MENSAGENS_SEM_TARIFA: Final = """
SELECT count(*)
  FROM platform.outbound_messages o
 WHERE o.delivered_at IS NOT NULL
   AND o.template_name = ANY(%s::text[])
   AND CASE
           WHEN jsonb_typeof(o.pricing -> 'billable') = 'boolean'
           THEN (o.pricing -> 'billable')::boolean
           ELSE false
       END
   AND coalesce(o.pricing ->> 'category', '')
       NOT IN ('service', 'utility', 'authentication', 'marketing')
"""
