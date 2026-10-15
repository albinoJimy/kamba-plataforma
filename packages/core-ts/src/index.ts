/**
 * Núcleo partilhado pelos serviços Node da KAMBÁ (KAM-001).
 *
 * Aqui só entra o que todos os serviços precisam de fazer da mesma maneira.
 * No KAM-001 isso é uma coisa: responder a `/healthz` com a mesma carga útil,
 * para que a sonda sintética e o *rolling deploy* (`docs/tecnica/09` §7) não tenham
 * de saber com que serviço estão a falar.
 */

import type { HealthzResponseV1, ServiceName } from "@kamba/contracts";

/** Subconjunto de `process.env` de que este módulo depende. */
export type ProcessEnv = Record<string, string | undefined>;

/** Nome da variável de ambiente onde o CI injecta o SHA do commit. */
export const COMMIT_ENV = "KAMBA_COMMIT_SHA";

/**
 * Lê o SHA do commit do ambiente.
 *
 * Devolve `"unknown"` quando a variável não está definida, em vez de falhar: a
 * sonda de vivacidade existe para dizer se o processo está vivo, e um processo
 * vivo sem metadados de construção continua vivo. Exigir um SHA real nas
 * imagens publicadas é um gate de CI (KAM-002), não uma condição de arranque.
 */
export function commitSha(env: ProcessEnv = process.env): string {
  const raw = (env[COMMIT_ENV] ?? "").trim().toLowerCase();
  return /^[0-9a-f]{7,40}$/.test(raw) ? raw : "unknown";
}

/** Constrói a resposta de `/healthz` de um serviço. */
export function healthz(
  service: ServiceName,
  version: string,
  env: ProcessEnv = process.env,
): HealthzResponseV1 {
  return {
    status: "ok",
    service,
    version,
    commit: commitSha(env),
  };
}

/**
 * Porta de escuta do serviço.
 *
 * Falha em voz alta se `PORT` estiver definida com lixo: ao contrário do SHA do
 * commit, uma porta errada não é um metadado — é arrancar a escutar no sítio
 * errado, e isso é pior do que não arrancar (`specs/01` §6, princípio 7).
 */
export function port(fallback: number, env: ProcessEnv = process.env): number {
  const raw = (env.PORT ?? "").trim();
  if (raw === "") return fallback;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`PORT inválida: ${JSON.stringify(raw)}`);
  }
  return parsed;
}
