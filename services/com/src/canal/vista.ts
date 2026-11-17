/**
 * O estado do canal que o painel do dono mostra (KAM-190, critério 7 do KAM-099).
 *
 * ```text
 * vistaDoCanal(r)   SQL_CANAL_DO_PAINEL         platform.tenant_channels
 *                   SQL_SINCRONIZACAO_DO_CANAL  platform.channel_coexistence (uma por canal)
 *                   SQL_NIVEL_DO_TENANT         platform.trust_level   (KAM-096)
 *                   ServicoDeTrust.avisosDoPainel                      (KAM-097)
 * ```
 *
 * ## Porque é que vive no COM, que não é o dono do canal
 *
 * O `onboarding-web` não tem rota para a base: em `prod` está só na rede `app`
 * (`infra/compose/docker-compose.prod.yml`), e dar-lhe a `data` era pôr uma
 * ligação ao PostgreSQL no único serviço que serve páginas a um navegador. Das
 * superfícies internas que ele já alcança, a do COM é a que tem as duas
 * barreiras que esta leitura precisa — a credencial (`com_internal_token`) e o
 * tenant num cabeçalho, que o repo-base injecta e a RLS confirma. A do GWY
 * (`/internal/channels`, KAM-016) não tem credencial, e o tenant vem no corpo.
 * **Lê e não escreve**: nenhuma das quatro consultas muda uma linha.
 *
 * ## O tenant é o do `ctx`, nas quatro leituras
 *
 * As três consultas deste ficheiro passam pelo `repo.noTenant`, que exige o
 * `tenant_id = $1` e o injecta. Os avisos passam pelo `RepositorioDeTrustSql` do
 * KAM-097, em modo `app`, sobre um cliente que **só** aceita o tenant do `ctx`
 * como primeiro parâmetro (`clienteDoTenant`): a consulta dele é a mesma forma, e
 * um tenant diferente levanta em vez de ler.
 *
 * ## Os quatro estados do painel, a partir de seis e de quatro
 *
 * `tenant_channels.estado` tem seis valores (§3.2) e a `channel_coexistence.estado`
 * quatro (§3.21); o painel mostra quatro (§3.56):
 *
 * ```text
 * sem linha em tenant_channels                         sem_canal
 * desligado, suspenso, encerrado                       desligado
 * pendente                                             a_sincronizar
 * ativo, restrito  + sincronização a_sincronizar       a_sincronizar
 * ativo, restrito  + o resto, ou sem sincronização     ativo
 * ```
 *
 * O `restrito` não vira um estado do painel: o canal continua ligado, e o que o
 * dono precisa de saber é que está limitado — vai no `restrito`, com a qualidade
 * ao lado. O `suspenso` e o `encerrado` são `desligado` **e** `restrito`: o
 * número não funciona, e religá-lo não é o que o dono deve fazer.
 */

import type { ClienteSql } from "@kamba/core-ts/eventos";
import { ServicoDeTrust, RepositorioDeTrustSql } from "@kamba/core-ts/trust";

import type { Registo } from "../adapters/medusa/index.ts";
import { ok, type Resultado } from "../port/contrato.ts";

/** Os quatro estados do canal no painel (dicionário §3.56). */
export const ESTADOS_DO_CANAL_NO_PAINEL = ["ativo", "a_sincronizar", "desligado", "sem_canal"] as const;
export type EstadoDoCanalNoPainel = (typeof ESTADOS_DO_CANAL_NO_PAINEL)[number];

/** O que o painel mostra. Nenhum telefone, nenhum `phone_number_id`, nenhum identificador da Meta. */
export interface VistaDoCanal {
  readonly estado: EstadoDoCanalNoPainel;
  /**
   * O canal está limitado ou suspenso, e **religá-lo não é o passo**:
   * `tenant_channels.estado` em `restrito`, `suspenso` ou `encerrado`. A página
   * não oferece a ligação a um canal destes — repetir o ES sobre uma suspensão
   * da Meta ou de T&S era o dano que o `sem_canal` existe para evitar.
   */
  readonly restrito: boolean;
  /** A qualidade canónica do KAM-021 (`tenant_channels.quality_rating`), ou `null`. */
  readonly qualidade: string | null;
  /** O escalão de conversas que a Meta anunciou (`tenant_channels.messaging_limit`), ou `null`. */
  readonly escalao: string | null;
  /** O nível de confiança do KAM-096 (`trust_level.nivel`), ou `null` antes do K1. */
  readonly nivel: number | null;
  /** O tecto por pedido do KAM-096, em unidade menor, ou `null`. */
  readonly tectoPedidoMinor: bigint | null;
  readonly currency: string | null;
  /** Os códigos públicos das sanções em vigor, do mais recente para o mais antigo (KAM-097). */
  readonly avisos: readonly string[];
}

/**
 * O canal da PME do tenant. **Um**, e escolhido por uma ordem total: o que está
 * ligado primeiro, e o `id` a desempatar, para a resposta não depender do plano.
 * Os de `origem = 'plataforma'` não entram: são o Fluxo B, que o ADR-011 recusa
 * em produção, e não são o número do dono.
 */
export const SQL_CANAL_DO_PAINEL = `
  SELECT id::text AS channel_id, estado, quality_rating, messaging_limit
    FROM platform.tenant_channels
   WHERE tenant_id = $1 AND origem = 'pme'
   ORDER BY CASE estado
              WHEN 'ativo' THEN 0
              WHEN 'restrito' THEN 1
              WHEN 'pendente' THEN 2
              ELSE 3
            END,
            id
   LIMIT 1
`;

/**
 * A sincronização de um canal (KAM-017). **Uma por canal**, pela
 * `channel_coexistence_canal_uq` da `0018`: o predicado que decide é o
 * `channel_id`, e é ele que o *gate* 8 mede.
 */
export const SQL_SINCRONIZACAO_DO_CANAL = `
  SELECT estado
    FROM platform.channel_coexistence
   WHERE tenant_id = $1 AND channel_id = $2::uuid
`;

/** O nível e o tecto do tenant (KAM-096). Só as quatro colunas que o `kamba_app` lê. */
export const SQL_NIVEL_DO_TENANT = `
  SELECT nivel, tecto_pedido_minor, currency
    FROM platform.trust_level
   WHERE tenant_id = $1
`;

/** O estado do painel, pela tabela da nota do módulo. */
export function estadoNoPainel(estadoDoCanal: string | null, sincronizacao: string | null): EstadoDoCanalNoPainel {
  if (estadoDoCanal === null) return "sem_canal";
  if (estadoDoCanal === "desligado" || estadoDoCanal === "suspenso" || estadoDoCanal === "encerrado") return "desligado";
  if (estadoDoCanal === "pendente") return "a_sincronizar";
  return sincronizacao === "a_sincronizar" ? "a_sincronizar" : "ativo";
}

/**
 * Um `ClienteSql` sobre o repo-base, que **só** serve o tenant do `ctx`.
 *
 * O `RepositorioDeTrustSql` passa o tenant como `$1`; o repo-base injecta-o e
 * exige o `tenant_id = $1` na consulta. Um primeiro parâmetro diferente é um
 * defeito de quem chama — levanta, em vez de ler outro tenant.
 */
export function clienteDoTenant(r: Pick<Registo, "repo">): ClienteSql {
  return {
    async query(sql, parametros = []) {
      if (parametros[0] !== r.repo.tenantId) {
        throw new Error("o cliente do painel so le o tenant do ctx");
      }
      const rows = (await r.repo.noTenant(sql, parametros.slice(1))) as Record<string, unknown>[];
      return { rows, rowCount: rows.length };
    },
  };
}

function texto(valor: unknown): string | null {
  return valor === null || valor === undefined ? null : String(valor);
}

/** O estado do canal do tenant do `ctx`. Lê e não escreve. */
export async function vistaDoCanal(r: Pick<Registo, "repo">): Promise<Resultado<VistaDoCanal>> {
  const canal = (await r.repo.noTenant(SQL_CANAL_DO_PAINEL))[0];
  const channelId = canal === undefined ? null : String(canal["channel_id"]);
  const sincronizacao =
    channelId === null ? undefined : (await r.repo.noTenant(SQL_SINCRONIZACAO_DO_CANAL, [channelId]))[0];
  const nivel = (await r.repo.noTenant(SQL_NIVEL_DO_TENANT))[0];
  const trust = new ServicoDeTrust({ repositorio: new RepositorioDeTrustSql(clienteDoTenant(r), "app") });
  const avisos = await trust.avisosDoPainel(r.repo.tenantId);
  const estadoDoCanal = texto(canal?.["estado"]);
  return ok({
    estado: estadoNoPainel(estadoDoCanal, texto(sincronizacao?.["estado"])),
    restrito: estadoDoCanal === "restrito" || estadoDoCanal === "suspenso" || estadoDoCanal === "encerrado",
    qualidade: texto(canal?.["quality_rating"]),
    escalao: texto(canal?.["messaging_limit"]),
    nivel: nivel === undefined ? null : Number(nivel["nivel"]),
    tectoPedidoMinor: nivel === undefined ? null : BigInt(String(nivel["tecto_pedido_minor"])),
    currency: texto(nivel?.["currency"]),
    avisos,
  });
}
