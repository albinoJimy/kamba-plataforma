/**
 * O repositório base — a injecção de `tenant_id`/`merchant_id` (KAM-042).
 *
 * **A primeira barreira de isolamento do COM vive aqui**, e a RLS do esquema
 * `platform` é a segunda (`../docs/tecnica/03` §5.5). A ordem importa: a RLS
 * protege de um `WHERE` esquecido, **não** de código que escolha o tenant
 * errado — é textualmente o RR-01 —, e no Registo da opção B não há RLS
 * nenhuma, porque o Medusa não é multi-tenant nativo e os seus *links*
 * «store only the IDs of the linked records and do not hold a foreign key
 * constraint» (§3.3, CONFIRMADO no KAM-041). Logo, no lado do Registo, **esta é
 * a única barreira que existe**.
 *
 * O desenho, em uma frase: **uma consulta que não nomeie o seu filtro não
 * chega à base.** O repo-base não tenta adivinhar onde enfiar um `AND` num SQL
 * que lhe deram — cirurgia textual sobre SQL é como se perde um filtro sem
 * ninguém ver. Em vez disso exige que a consulta escreva o predicado ela
 * mesma, com o valor em `$1`, e **verifica que o escreveu** antes de a
 * executar. Quem se esquecer leva `FiltroEmFaltaError` no primeiro teste, e
 * não um resultado maior do que devia em produção.
 *
 * O que isto **não** faz, e tem de ficar dito: não lê SQL como um parser.
 * A verificação é sobre o texto do predicado, pelo que um SQL construído para
 * a enganar — um predicado dentro de um comentário, um `OR true` a seguir —
 * passa. **Não é a defesa contra código hostil**; é a defesa contra o
 * esquecimento, que é o modo de falha real de trinta repositórios escritos por
 * pessoas e agentes diferentes. Contra o `OR` está o ISO-10, e contra a escolha
 * errada de tenant está a revisão do código que escolhe.
 */

import type { ClienteSql } from "../port/contrato.ts";
import { eUuid } from "../port/contrato.ts";

/** A métrica de recusas. Uma barreira que ninguém vê disparar não se opera. */
export const METRICA_FILTRO_EM_FALTA = "com_repo_filtro_em_falta_total";

/** O nome do contador de consultas que passaram, por tipo de filtro. */
export const METRICA_CONSULTAS = "com_repo_consultas_total";

/**
 * Os dois filtros, e porque são dois e não um.
 *
 * `tenant`  o esquema `platform`, onde a coluna é `tenant_id` e há RLS atrás.
 * `merchant` o Registo da opção B, onde a coluna é `merchant_id` e **não há
 *           nada atrás**. É o `platform.tenants.medusa_merchant_id` do tenant,
 *           resolvido uma vez por operação — e nunca um valor que venha do
 *           chamador.
 */
export const FILTROS = ["tenant", "merchant"] as const;
export type Filtro = (typeof FILTROS)[number];

/** A coluna que cada filtro exige no predicado. */
export const COLUNA_DO_FILTRO: Readonly<Record<Filtro, string>> = {
  tenant: "tenant_id",
  merchant: "merchant_id",
};

/**
 * O predicado que a consulta tem de conter, por filtro.
 *
 * Aceita `merchant_id = $1`, `m.merchant_id=$1` e `"merchant_id" = $1`, com
 * qualquer espaçamento — e **só** com `$1`. O `$1` é do repo-base e de mais
 * ninguém: os parâmetros de quem chama começam no `$2`, e é isso que torna
 * impossível a consulta que declara o predicado e lhe passa outro valor.
 */
function predicadoDe(filtro: Filtro): RegExp {
  const coluna = COLUNA_DO_FILTRO[filtro];
  return new RegExp(`(?:^|[^a-z0-9_"])"?${coluna}"?\\s*=\\s*\\$1(?![0-9])`, "i");
}

/** Uma consulta chegou ao repo-base sem nomear o filtro que a limita. */
export class FiltroEmFaltaError extends Error {
  override readonly name = "FiltroEmFaltaError";
  constructor(filtro: Filtro, sql: string) {
    super(
      `a consulta nao contem "${COLUNA_DO_FILTRO[filtro]} = $1" e o repo-base ` +
        "nao a executa: no Registo da opcao B nao ha RLS atras desta barreira " +
        `(KAM-042, criterio 4). SQL recusado: ${resumir(sql)}`,
    );
  }
}

/** O `merchant_id` do tenant não está provisionado. Falha fechada. */
export class MerchantEmFaltaError extends Error {
  override readonly name = "MerchantEmFaltaError";
  constructor(tenantId: string) {
    super(
      `o tenant ${tenantId} nao tem medusa_merchant_id em platform.tenants: ` +
        "o provisionamento do criterio 5 nao correu para ele, e uma consulta " +
        "ao Registo sem merchant_id devolvia as linhas de todos os tenants " +
        "(KAM-042, criterio 5)",
    );
  }
}

/** Um `tenant_id` que não é um UUID canónico nunca entra num predicado. */
export class TenantInvalidoError extends Error {
  override readonly name = "TenantInvalidoError";
  constructor(valor: unknown) {
    super(
      `tenant_id invalido no repo-base: ${JSON.stringify(String(valor))}. ` +
        "O ctx vem do estado do agente ou da sessao autenticada e nunca do " +
        "texto do cliente (KAM-042, criterio 1)",
    );
  }
}

/** O SQL recusado, cortado: a mensagem vai para o *log*, que tem allowlist. */
function resumir(sql: string): string {
  const limpo = sql.replace(/\s+/g, " ").trim();
  return limpo.length > 120 ? `${limpo.slice(0, 120)}…` : limpo;
}

export class Contadores {
  readonly filtroEmFalta = new Map<Filtro, number>();
  readonly consultas = new Map<Filtro, number>();

  contar(mapa: Map<Filtro, number>, filtro: Filtro): void {
    mapa.set(filtro, (mapa.get(filtro) ?? 0) + 1);
  }
}

export const CONTADORES = new Contadores();

/**
 * O que o repo-base devolve a quem o usa.
 *
 * Duas operações e não uma: `noTenant` para o esquema `platform` (o filtro é o
 * `tenant_id` do `ctx`) e `noMerchant` para o Registo (o filtro é o
 * `merchant_id` resolvido do tenant). Separá-las é deliberado — com um só
 * método e um parâmetro, o sítio onde se escolhe o filtro era o sítio onde se
 * podia escolher o errado, e passava a ser invisível na chamada.
 */
export interface RepoBase {
  /** `SELECT`/`INSERT`/`UPDATE` no `platform`, com `tenant_id = $1`. */
  noTenant(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;

  /** O mesmo no Registo, com `merchant_id = $1`. */
  noMerchant(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;

  /** O `tenant_id` que este repo-base injecta. Para o *log* e as métricas. */
  readonly tenantId: string;
}

/** A consulta que resolve o `merchant_id` de um tenant. Lida pelo gate 8. */
export const SQL_MERCHANT_DO_TENANT =
  "SELECT medusa_merchant_id, medusa_sales_channel_id " +
  "FROM platform.tenants WHERE id = $1 AND deleted_at IS NULL";

/**
 * O par de identificadores do Registo, para um tenant.
 *
 * Lê-se **de `platform.tenants`**, uma vez por operação, e nunca de um
 * argumento. A razão está no §5.4 e no ISO-58 do spike: com o `merchant_id` a
 * vir do chamador, a porta aceitava o do tenant B com o `ctx` de A e a FK não
 * o impedia — o *link* do Medusa não tem FK nenhuma para impedir.
 */
export interface IdsDoRegisto {
  readonly merchantId: string;
  readonly salesChannelId: string | null;
}

export async function idsDoRegisto(
  cliente: ClienteSql,
  tenantId: string,
): Promise<IdsDoRegisto> {
  if (!eUuid(tenantId)) throw new TenantInvalidoError(tenantId);
  const { rows } = await cliente.query(SQL_MERCHANT_DO_TENANT, [tenantId]);
  const merchantId = rows[0]?.["medusa_merchant_id"];
  if (typeof merchantId !== "string" || merchantId.length === 0) {
    throw new MerchantEmFaltaError(tenantId);
  }
  const canal = rows[0]?.["medusa_sales_channel_id"];
  return {
    merchantId,
    salesChannelId: typeof canal === "string" && canal.length > 0 ? canal : null,
  };
}

/**
 * Um repo-base ligado a um cliente, a um tenant e a um `merchant_id`.
 *
 * Recebe o cliente **já dentro** de uma transacção com `app.tenant_id`
 * definido: quem o monta é o adaptador, dentro do `comTenant`. O repo-base não
 * abre transacções nem escolhe ligações, pela mesma razão que o `ComTenant` do
 * módulo `servicos` não recebe o cliente — quem decide de onde vem a ligação é
 * quem monta, e dar essa decisão a um repositório é dar-lhe a possibilidade de
 * a tomar mal.
 */
export function repoBase(
  cliente: ClienteSql,
  tenantId: string,
  merchantId: string,
): RepoBase {
  if (!eUuid(tenantId)) throw new TenantInvalidoError(tenantId);
  if (typeof merchantId !== "string" || merchantId.length === 0) {
    throw new MerchantEmFaltaError(tenantId);
  }

  async function executar(
    filtro: Filtro,
    valor: string,
    sql: string,
    parametros: readonly unknown[],
  ): Promise<readonly Readonly<Record<string, unknown>>[]> {
    if (!predicadoDe(filtro).test(sql)) {
      CONTADORES.contar(CONTADORES.filtroEmFalta, filtro);
      throw new FiltroEmFaltaError(filtro, sql);
    }
    CONTADORES.contar(CONTADORES.consultas, filtro);
    const { rows } = await cliente.query(sql, [valor, ...parametros]);
    return rows;
  }

  return {
    tenantId,
    noTenant: (sql, parametros = []) =>
      executar("tenant", tenantId, sql, parametros),
    noMerchant: (sql, parametros = []) =>
      executar("merchant", merchantId, sql, parametros),
  };
}
