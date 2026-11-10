"""A vista de custo diario por tenant e por rubrica (KAM-081, criterio 1).

O SQL da `platform.v_tenant_cost_daily` vive **aqui** e nao na revisao, por duas
razoes que se pagam uma a outra:

* os ensaios de base de dados importam-no deste modulo em vez de o copiar. Uma
  copia no ensaio passava verde no dia em que a revisao mudasse, e a revisao e
  o ensaio deixavam de falar da mesma vista;
* a revisao chama `custo.criar_vista()`, e o *gate* 3b le o SQL **por aqui**:
  este ficheiro esta declarado em `ci/canon-lint.yaml` como modulo auxiliar de
  migracao, como o `db/rls.py`, e o lint segue o corpo da funcao com o SQL que
  ela executa. Por isso o SQL e uma cadeia **literal**, sem *f-strings* nem
  chamadas: o que o lint nao segue, recusa.

## O que a vista diz, e o que nao diz

Uma linha por `(tenant_id, dia, rubrica)`. O dia e o do **fuso do tenant**
(`tenants.fuso_horario`), que e onde o periodo de uso ja vive desde a `0007`; nao
ha fuso por canal (divida 66, `0013`).

* **`llm`** — a soma de `dat.llm_call_log.custo_usd`. As recusas do *gate* de
  destino (`resultado = 'destino_negado'`) nao entram: sao chamadas que nao
  aconteceram, e o `CHECK` da `0023` ja lhes recusa custo. **Uma chamada com
  *tokens* e sem preco nao conta como zero**: conta em `sem_preco`, porque
  escrever zero era afirmar que foi gratuita (`llm/precos.yaml`);
* **`meta_<categoria>`** — o custo das mensagens **entregues** cujo `pricing`
  diz `billable`, a tarifa da categoria que a Meta escreveu no `pricing` e nao a
  nossa (`packages/core-ts/src/outbound/tarifas.ts`, `microUsdDe`). Uma
  categoria fora das quatro vai para `meta_outra`, com custo **nulo** e contada
  em `sem_preco`: uma categoria que nao conhecemos nao se converte num numero
  inventado;
* **STT nao existe aqui, e nao e esquecimento.** Nao ha registo de chamadas de
  transcricao em lado nenhum: o `papel` da `0023` e uma lista fechada de quatro
  (`router`, `chat`, `vision`, `embed`) e o STT entra com o KAM-036. Uma rubrica
  `stt` a zero dizia «a voz nao custou nada» sobre o que ninguem regista.

## Tarifas e cambio

As tarifas da Meta estao no `CASE` em micro-dolares inteiros, iguais as de
`config/meta_rates.yaml` (efectivas 2026-10-01, CONFIRMADO, `E1` §1). **Mudar
uma tarifa e uma revisao nova**, e e de proposito: a vista diz com que tabela
foi calculada. O `db/tests/test_custo.py` compara as duas como texto.

O cambio e o parametro de sessao `app.fx_aoa_per_usd`, com omissao **913**
(INDICIO, `docs/tecnica/09` §14.1, 2026-09-30). Os modos de sensibilidade sao
o mesmo parametro com outro valor — `981` (+7,4%, a venda do BNI) e `1232`
(+35%, o choque do §14.5) — e a vista devolve o cambio que usou na coluna
`fx_aoa_per_usd`, para que nenhuma leitura em Kz fique sem a taxa ao lado. Um
valor que nao seja numero, ou que seja zero ou negativo, **levanta** (`22P02`),
e isso e o comportamento certo: um cambio ilegivel nao cai em silencio para a
omissao, e um negativo dava custos negativos. O erro do nao-positivo vem de uma
conversao que depende do valor lido, e nao de uma constante: uma constante no
ramo `ELSE` era dobrada no planeamento e levantava sempre.

**Cobravel e so o `billable` booleano verdadeiro.** Um `"billable": "yes"` em
texto nao conta, como no `tarifa_micro_usd` daqui — e, sem a guarda, um
`"talvez"` levantava na conversao e derrubava a vista inteira, para todos os
tenants. A guarda vai num `CASE` e nao num `AND`, porque o PostgreSQL nao
garante a ordem de avaliacao de um `AND`.

O Kz sai em unidade menor inteira (`custo_aoa_minor`, centimos), arredondado
**uma vez**, na linha da vista. A soma de linhas ja arredondadas pode divergir
em centimos da conversao da soma; quem quer o total exacto converte o
`custo_usd` somado.

## Sem pessoas

Nenhuma coluna desta vista aponta para uma pessoa: nem `contact_id`, nem
`conversation_id`, nem telefone, nem `wamid`, nem texto. O `contact_id` de
`outbound_messages` e lido para **nada** — a agregacao e por tenant e dia. O
ensaio da ausencia de PII compara as colunas da vista com `COLUNAS` por
igualdade, e o mesmo ensaio fica vermelho se alguem acrescentar um
identificador (`db/tests/test_custo.py`).

## Quem le

So o `kamba_batch`, que e o unico papel com `SELECT` em `dat.llm_call_log` **e**
em `platform.outbound_messages`, e o unico que atravessa tenants (`BYPASSRLS`).
A vista leva `security_invoker = true`, que o *gate* 6 exige a todas: corre com
os privilegios e a RLS de quem a le. O `kamba_app` nao ganha nada — escreve o
registo de custo e nao o le (KAM-030).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from alembic import op

#: O nome qualificado da vista.
VISTA: Final = "platform.v_tenant_cost_daily"

#: As colunas, pela ordem do `SELECT`. **Lista fechada**: o ensaio da ausencia
#: de PII compara as da base com esta por igualdade.
COLUNAS: Final = (
    "tenant_id",
    "dia",
    "rubrica",
    "unidades",
    "sem_preco",
    "custo_usd",
    "custo_aoa_minor",
    "fx_aoa_per_usd",
)

#: O parametro de sessao do cambio. O prefixo `app.` e o do `app.tenant_id`.
PARAMETRO_DO_CAMBIO: Final = "app.fx_aoa_per_usd"

#: Omissao do cambio, AOA por USD. INDICIO (`docs/tecnica/09` §14.1).
CAMBIO_POR_OMISSAO: Final = Decimal("913")

#: Os tres modos de cambio do criterio 1. Os valores sao os do criterio e do
#: `docs/tecnica/09` §14.1 e §14.5, nao calculados aqui: 913 x 1,074 da 980,6 e
#: 913 x 1,35 da 1232,6, e o criterio fixa 981 e 1.232.
MODOS_DE_CAMBIO: Final = {
    "base": Decimal("913"),
    "venda_bni": Decimal("981"),
    "choque": Decimal("1232"),
}

#: As tarifas da Meta em micro-dolares, por categoria. **Tem de ser igual** ao
#: `config/meta_rates.yaml`; o ensaio de paridade le as duas.
TARIFAS_MICRO_USD: Final = {
    "service": 4000,
    "utility": 4000,
    "authentication": 4000,
    "marketing": 22500,
}

#: A data em que as tarifas do `CASE` entraram em vigor.
TARIFAS_EFECTIVAS_EM: Final = "2026-10-01"

#: As rubricas que a vista pode devolver. Lista fechada.
RUBRICAS: Final = (
    "llm",
    "meta_service",
    "meta_utility",
    "meta_authentication",
    "meta_marketing",
    "meta_outra",
)

MICRO_USD_POR_USD: Final = 1_000_000

SQL_CRIAR_VISTA: Final = """
CREATE VIEW platform.v_tenant_cost_daily
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
custo_llm AS (
    SELECT l.tenant_id,
           (l.ts AT TIME ZONE t.fuso_horario)::date AS dia,
           'llm'::text AS rubrica,
           count(*) AS unidades,
           count(*) FILTER (
               WHERE l.custo_usd IS NULL
                 AND (l.tokens_in IS NOT NULL OR l.tokens_out IS NOT NULL)
           ) AS sem_preco,
           sum(l.custo_usd) AS custo_usd
      FROM dat.llm_call_log l
      JOIN platform.tenants t ON t.id = l.tenant_id
     WHERE l.resultado <> 'destino_negado'
     GROUP BY l.tenant_id, (l.ts AT TIME ZONE t.fuso_horario)::date
),
mensagens_meta AS (
    SELECT o.tenant_id,
           (o.delivered_at AT TIME ZONE t.fuso_horario)::date AS dia,
           CASE o.pricing ->> 'category'
               WHEN 'service' THEN 'meta_service'
               WHEN 'utility' THEN 'meta_utility'
               WHEN 'authentication' THEN 'meta_authentication'
               WHEN 'marketing' THEN 'meta_marketing'
               ELSE 'meta_outra'
           END AS rubrica,
           CASE o.pricing ->> 'category'
               WHEN 'service' THEN 4000
               WHEN 'utility' THEN 4000
               WHEN 'authentication' THEN 4000
               WHEN 'marketing' THEN 22500
           END AS usd_micro
      FROM platform.outbound_messages o
      JOIN platform.tenants t ON t.id = o.tenant_id
     WHERE o.delivered_at IS NOT NULL
       AND CASE
               WHEN jsonb_typeof(o.pricing -> 'billable') = 'boolean'
               THEN (o.pricing -> 'billable')::boolean
               ELSE false
           END
),
custo_meta AS (
    SELECT m.tenant_id,
           m.dia,
           m.rubrica,
           count(*) AS unidades,
           count(*) FILTER (WHERE m.usd_micro IS NULL) AS sem_preco,
           sum(m.usd_micro)::numeric / 1000000 AS custo_usd
      FROM mensagens_meta m
     GROUP BY m.tenant_id, m.dia, m.rubrica
),
rubricas AS (
    SELECT * FROM custo_llm
    UNION ALL
    SELECT * FROM custo_meta
)
SELECT r.tenant_id,
       r.dia,
       r.rubrica,
       r.unidades,
       r.sem_preco,
       r.custo_usd,
       round(r.custo_usd * c.fx_aoa_per_usd * 100)::bigint AS custo_aoa_minor,
       c.fx_aoa_per_usd
  FROM rubricas r
 CROSS JOIN cambio c
"""

SQL_COMENTAR_VISTA: Final = """
COMMENT ON VIEW platform.v_tenant_cost_daily IS
'Custo diario por tenant e rubrica (KAM-081): llm de dat.llm_call_log e meta_<categoria> do pricing dos statuses, tarifas de config/meta_rates.yaml efectivas 2026-10-01. Sem STT: nao ha registo de transcricao (KAM-036). Cambio no parametro app.fx_aoa_per_usd, omissao 913 (INDICIO). Sem contact_id, conversa, telefone nem texto. security_invoker: corre com a RLS de quem le.'
"""

SQL_CONCEDER: Final = "GRANT SELECT ON platform.v_tenant_cost_daily TO kamba_batch"

SQL_REMOVER_VISTA: Final = "DROP VIEW platform.v_tenant_cost_daily"


def criar_vista() -> None:
    """Cria a vista, comenta-a e concede a leitura. Chamado pela revisao."""
    op.execute(SQL_CRIAR_VISTA)
    op.execute(SQL_COMENTAR_VISTA)
    op.execute(SQL_CONCEDER)


def remover_vista() -> None:
    """O inverso, para o `downgrade`. Sem `CASCADE`: um dependente faz falhar."""
    op.execute(SQL_REMOVER_VISTA)


def cambio(modo: str | None = None, valor: Decimal | str | None = None) -> Decimal:
    """O cambio a usar: um valor explicito, um modo, ou a omissao.

    Recusa zero e negativos. Um valor e um modo ao mesmo tempo e erro de uso.
    """
    if modo is not None and valor is not None:
        raise ValueError("indique o modo ou o valor do cambio, nao os dois")
    if modo is not None:
        if modo not in MODOS_DE_CAMBIO:
            raise ValueError(f"modo de cambio desconhecido: {modo!r}")
        return MODOS_DE_CAMBIO[modo]
    if valor is None:
        return CAMBIO_POR_OMISSAO
    taxa = Decimal(str(valor))
    if not taxa.is_finite() or taxa <= 0:
        raise ValueError(f"cambio invalido: {valor!r}")
    return taxa


def para_aoa_minor(custo_usd: Decimal, fx_aoa_per_usd: Decimal) -> int:
    """USD em centimos de Kz, arredondado como o `round(numeric)` da vista.

    O `round` do PostgreSQL arredonda metades **para longe do zero**; para custos,
    que nao sao negativos, e o `ROUND_HALF_UP` do `Decimal`.
    """
    centimos = (custo_usd * fx_aoa_per_usd * 100).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return int(centimos)


def tarifa_micro_usd(pricing: dict | None) -> int | None:
    """O custo de uma mensagem entregue, em micro-dolares, pela regra da vista.

    `0` quando nao e cobravel; `None` quando e cobravel e a categoria e
    desconhecida (a vista conta-a em `sem_preco`).
    """
    if not pricing or pricing.get("billable") is not True:
        return 0
    return TARIFAS_MICRO_USD.get(str(pricing.get("category")))
