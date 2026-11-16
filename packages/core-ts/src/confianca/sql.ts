/**
 * Confiança gradual — o adaptador PostgreSQL (KAM-096).
 *
 * As consultas são constantes **literais** exportadas: a suite de base de dados
 * (`db/tests/test_confianca_schema.py`) executa estas cadeias e não uma cópia
 * delas, e um `${...}` dentro de uma delas chegava ao PostgreSQL tal e qual.
 *
 * ## Dois papéis
 *
 * * **`kamba_batch`** — o recálculo (`RepositorioDeConfiancaSql`). Lê a
 *   encomenda, o registo de estados, os sinais e o K1, e é o único que escreve
 *   `trust_level`. Tem `BYPASSRLS`, e por isso **toda** a leitura filtra pelo
 *   tenant em `$1`.
 * * **`kamba_app`** — o caminho de cobrança (`LeitorDoTectoSql`). Lê só as
 *   colunas do tecto, e só do tenant do contexto (RLS).
 */

import type { ClienteSql } from "../eventos/publicador.ts";
import { NIVEIS_DE_CONFIANCA, type NivelDeConfianca } from "./config.ts";
import type { LeitorDoTecto } from "./guard.ts";
import type { Decisao, MotivoDoNivel, NivelGravado, PedidoLido, RepositorioDeConfianca } from "./niveis.ts";

export type { ClienteSql };

/**
 * A tranca exclusiva do tenant, a **primeira** coisa do recálculo e na mesma
 * transacção das leituras. É a chave do `trust_level_guardar` e do *trigger* da
 * cobrança: com ela tomada antes de ler, um sinal ou uma disputa que chegue a
 * meio não fica para trás de um `desde` posterior a eles.
 */
export const SQL_TRANCAR = `
  SELECT pg_advisory_xact_lock(hashtextextended('platform.trust_level:' || $1::text, 0))
`;

/** A linha do tenant. Só o lote. */
export const SQL_NIVEL_DO_TENANT = `
  SELECT nivel, tecto_pedido_minor::text AS tecto_pedido_minor, motivo, desde
    FROM platform.trust_level
   WHERE tenant_id = $1
`;

/** O tecto do tenant do contexto. É o que a aplicação lê. */
export const SQL_TECTO_DO_TENANT = `
  SELECT tecto_pedido_minor::text AS tecto_pedido_minor
    FROM platform.trust_level
   WHERE tenant_id = $1
`;

/**
 * O K1 completo: o mesmo predicado do gate `kyc` do KAM-092 e do
 * `trust_level_guardar`, pela `aprovacao_em_falta`.
 */
export const SQL_K1_COMPLETO = `
  SELECT EXISTS (
    SELECT 1 FROM platform.onboarding_case c
     WHERE c.tenant_id = $1
       AND NOT ('kyc' = ANY (platform.aprovacao_em_falta(c.id)))
  ) AS completo
`;

/**
 * Os pedidos entregues de um tenant desde `$2`, com pelo menos `$3` de valor.
 *
 * O comprador é o contacto **canónico** (a cadeia de `merged_into`, até oito
 * passos, como o `SQL_PEDIDO_E_COMPRADOR` do KAM-097): dois contactos do mesmo
 * telefone fundidos são um comprador. A disputa na janela é uma entrada em
 * `em_disputa` antes de passarem `$4` dias da entrega.
 */
export const SQL_PEDIDOS_ENTREGUES = `
  WITH RECURSIVE pedidos AS (
      SELECT o.id, o.contact_id, o.total_minor, o.criado_at, o.entregue_at,
             o.entrega_confirmada_por
        FROM platform.orders_mirror o
       WHERE o.tenant_id = $1 AND o.estado = 'entregue'
         AND o.entregue_at > $2 AND o.total_minor >= $3::bigint
    ), cadeia(order_id, actual, passos) AS (
      SELECT p.id, p.contact_id, 0 FROM pedidos p
      UNION ALL
      SELECT k.order_id, c.merged_into, k.passos + 1
        FROM cadeia k
        JOIN platform.contacts c ON c.tenant_id = $1 AND c.contact_id = k.actual
       WHERE c.merged_into IS NOT NULL AND k.passos < 8
    )
  SELECT p.id::text AS order_id,
         (SELECT k.actual::text FROM cadeia k WHERE k.order_id = p.id
           ORDER BY k.passos DESC LIMIT 1) AS comprador_ref,
         p.total_minor::text AS valor_minor, p.criado_at, p.entregue_at,
         p.entrega_confirmada_por = 'cliente' AS confirmado_pelo_cliente,
         EXISTS (SELECT 1 FROM platform.order_state_log l
                  WHERE l.tenant_id = $1 AND l.order_id = p.id AND l.para = 'em_disputa'
                    AND l.em <= p.entregue_at + make_interval(days => $4::int)) AS disputa_na_janela
    FROM pedidos p
   ORDER BY p.entregue_at, p.id
`;

/**
 * Os dois factos negativos mais recentes: uma disputa aceite contra o dono
 * (`em_disputa → reembolso_pendente`) e um sinal de severidade alta. O sinal
 * conta pelo `criado_at`, que é quando a plataforma o soube: um sinal gravado
 * depois de uma subida, sobre um evento anterior a ela, tem de descer o tenant.
 */
export const SQL_FACTOS_NEGATIVOS = `
  SELECT (SELECT max(l.em) FROM platform.order_state_log l
           WHERE l.tenant_id = $1 AND l.de = 'em_disputa' AND l.para = 'reembolso_pendente')
           AS ultima_disputa_aceite,
         (SELECT max(s.criado_at) FROM platform.ts_signal s
           WHERE s.tenant_id = $1 AND s.severidade = 'alta') AS ultimo_sinal_alto
`;

/**
 * Grava o nível. Uma linha igual **não se escreve** — nem `UPDATE`, nem
 * *trigger*, nem `audit_log` —, que é a idempotência do recálculo. As datas são
 * do *trigger* `trust_level_guardar`, e não de quem escreve.
 */
export const SQL_DEFINIR_NIVEL = `
  INSERT INTO platform.trust_level (tenant_id, nivel, tecto_pedido_minor, motivo, actor, versao_config)
  VALUES ($1, $2, $3::bigint, $4, $5, $6)
  ON CONFLICT (tenant_id) DO UPDATE
     SET nivel = EXCLUDED.nivel, tecto_pedido_minor = EXCLUDED.tecto_pedido_minor,
         motivo = EXCLUDED.motivo, actor = EXCLUDED.actor, versao_config = EXCLUDED.versao_config
   WHERE (platform.trust_level.nivel, platform.trust_level.tecto_pedido_minor)
         IS DISTINCT FROM (EXCLUDED.nivel, EXCLUDED.tecto_pedido_minor)
  RETURNING nivel
`;

/** As cadeias que a suite de base de dados exercita deste ficheiro. */
export const CADEIAS_DA_CONFIANCA = [
  "SQL_TRANCAR",
  "SQL_NIVEL_DO_TENANT",
  "SQL_TECTO_DO_TENANT",
  "SQL_K1_COMPLETO",
  "SQL_PEDIDOS_ENTREGUES",
  "SQL_FACTOS_NEGATIVOS",
  "SQL_DEFINIR_NIVEL",
] as const;

type Linha = Record<string, unknown>;

function data(v: unknown): Date {
  return v instanceof Date ? v : new Date(String(v));
}

/** O nivel lido, pelo dominio e sem `Number(...)`: um valor fora dele falha fechado. */
function nivelDe(v: unknown): NivelDeConfianca {
  const n = NIVEIS_DE_CONFIANCA.find((x) => String(x) === String(v));
  if (n === undefined) throw new Error(`trust_level.nivel fora do dominio: ${String(v)}`);
  return n;
}

function dataOuNula(v: unknown): Date | null {
  return v === null || v === undefined ? null : data(v);
}

/** O recálculo, como `kamba_batch`. */
export class RepositorioDeConfiancaSql implements RepositorioDeConfianca {
  readonly #bd: ClienteSql;

  constructor(bd: ClienteSql) {
    this.#bd = bd;
  }

  async trancar(tenantId: string): Promise<void> {
    await this.#bd.query(SQL_TRANCAR, [tenantId]);
  }

  async nivel(tenantId: string): Promise<NivelGravado | null> {
    const l: Linha | undefined = (await this.#bd.query(SQL_NIVEL_DO_TENANT, [tenantId])).rows[0];
    if (l === undefined) return null;
    return {
      nivel: nivelDe(l["nivel"]),
      tectoPedidoMinor: BigInt(String(l["tecto_pedido_minor"])),
      motivo: String(l["motivo"]) as MotivoDoNivel,
      desde: data(l["desde"]),
    };
  }

  async k1Completo(tenantId: string): Promise<boolean> {
    return (await this.#bd.query(SQL_K1_COMPLETO, [tenantId])).rows[0]?.["completo"] === true;
  }

  async pedidosEntregues(
    tenantId: string,
    desde: Date,
    valorMinimoMinor: bigint,
    janelaAntiFraudeDias: number,
  ): Promise<readonly PedidoLido[]> {
    const r = await this.#bd.query(SQL_PEDIDOS_ENTREGUES, [
      tenantId,
      desde,
      valorMinimoMinor.toString(),
      janelaAntiFraudeDias,
    ]);
    return r.rows.map((l: Linha) => ({
      orderId: String(l["order_id"]),
      compradorRef: String(l["comprador_ref"]),
      valorMinor: BigInt(String(l["valor_minor"])),
      criadoEm: data(l["criado_at"]),
      entregueEm: data(l["entregue_at"]),
      confirmadoPeloCliente: l["confirmado_pelo_cliente"] === true,
      disputaNaJanela: l["disputa_na_janela"] === true,
    }));
  }

  async factosNegativos(tenantId: string) {
    const l: Linha = (await this.#bd.query(SQL_FACTOS_NEGATIVOS, [tenantId])).rows[0] ?? {};
    return {
      ultimaDisputaAceite: dataOuNula(l["ultima_disputa_aceite"]),
      ultimoSinalAlto: dataOuNula(l["ultimo_sinal_alto"]),
    };
  }

  async definir(tenantId: string, d: Decisao, actor: string, versaoConfig: string): Promise<boolean> {
    const r = await this.#bd.query(SQL_DEFINIR_NIVEL, [
      tenantId,
      d.nivel,
      d.tectoPedidoMinor.toString(),
      d.motivo,
      actor,
      versaoConfig,
    ]);
    return r.rows.length === 1;
  }
}

/** O tecto no caminho de cobrança, como `kamba_app` com o contexto do tenant. */
export class LeitorDoTectoSql implements LeitorDoTecto {
  readonly #bd: ClienteSql;

  constructor(bd: ClienteSql) {
    this.#bd = bd;
  }

  async tectoDoTenant(tenantId: string): Promise<bigint | null> {
    const l: Linha | undefined = (await this.#bd.query(SQL_TECTO_DO_TENANT, [tenantId])).rows[0];
    return l === undefined ? null : BigInt(String(l["tecto_pedido_minor"]));
  }
}
