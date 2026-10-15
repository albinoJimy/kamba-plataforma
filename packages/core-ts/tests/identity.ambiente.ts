/**
 * O ambiente de chaves dos testes de identidade (KAM-008).
 *
 * As variáveis `KAMBA_SECRET_*` montam-se aqui a partir das **referências** do
 * inventário, pela mesma função que o `EnvSecretProvider` usa para as ler. Assim
 * os testes não escrevem os nomes das variáveis à mão — e não podem divergir do
 * que o provedor lê.
 */

import { SUFIXO_ANTERIOR, nomeDaVariavel } from "../src/secrets/index.ts";

/** As chaves a pôr no ambiente. O que não vier fica por definir. */
export interface ChavesDeEnsaio {
  /** `[actual, anterior?]` da chave de pesquisa (`pepper_contact_hmac`). */
  readonly pesquisa?: readonly [string, string?];
  /** `[actual, anterior?]` da KEK (`kek_contact_dek`). */
  readonly kek?: readonly [string, string?];
  /** Época `YYYYMM` → chave de época (`sujeito_epoch_key/<YYYYMM>`). */
  readonly epocas?: Readonly<Record<string, string>>;
  /** `KAMBA_ENV`, se for para o declarar. */
  readonly ambiente?: string;
}

function porAnel(
  env: Record<string, string>,
  ref: string,
  anel: readonly [string, string?] | undefined,
): void {
  if (anel === undefined) return;
  const variavel = nomeDaVariavel(ref);
  env[variavel] = anel[0];
  if (anel[1] !== undefined) env[variavel + SUFIXO_ANTERIOR] = anel[1];
}

/** O objecto de ambiente com as chaves pedidas, pronto para um `EnvKeyProvider`. */
export function ambienteDeChaves(chaves: ChavesDeEnsaio): Record<string, string> {
  const env: Record<string, string> = {};
  if (chaves.ambiente !== undefined) env.KAMBA_ENV = chaves.ambiente;
  porAnel(env, "pepper_contact_hmac", chaves.pesquisa);
  porAnel(env, "kek_contact_dek", chaves.kek);
  for (const [epoca, chave] of Object.entries(chaves.epocas ?? {})) {
    env[nomeDaVariavel(`sujeito_epoch_key/${epoca}`)] = chave;
  }
  return env;
}

/** Roda a chave de pesquisa de um ambiente: a actual passa a anterior. */
export function rodarPesquisa(env: Record<string, string>, nova: string): void {
  const variavel = nomeDaVariavel("pepper_contact_hmac");
  const actual = env[variavel];
  if (actual !== undefined) env[variavel + SUFIXO_ANTERIOR] = actual;
  env[variavel] = nova;
}

/** Tira a versão anterior da chave de pesquisa. Devolve a que lá estava. */
export function esquecerPesquisaAnterior(env: Record<string, string>): string | undefined {
  const variavel = nomeDaVariavel("pepper_contact_hmac") + SUFIXO_ANTERIOR;
  const anterior = env[variavel];
  delete env[variavel];
  return anterior;
}

/** Repõe como actual uma chave de pesquisa já conhecida, sem tocar na anterior. */
export function definirPesquisa(env: Record<string, string>, actual: string): void {
  env[nomeDaVariavel("pepper_contact_hmac")] = actual;
}
