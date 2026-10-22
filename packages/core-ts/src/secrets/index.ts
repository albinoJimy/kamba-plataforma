/**
 * `@kamba/core-ts/secrets` — a porta de segredos (KAM-010).
 *
 * ```ts
 * import { EnvSecretProvider, Secrets } from "@kamba/core-ts/secrets";
 *
 * const secrets = await Secrets.arrancar({
 *   servico: "gwy",
 *   provider: new EnvSecretProvider({ ambiente: "dev" }),
 *   obrigatorios: ["meta_app_secret", "meta_verify_token"],
 * });
 *
 * const [actual, anterior] = await secrets.getRing("meta_app_secret");
 * ```
 *
 * Trocar de implementação é trocar a linha do `provider` — é esse o conteúdo
 * verificável de «trocar de implementação é só configuração», e a suite
 * `tests/secrets.contrato.test.ts` corre a mesma bateria sobre as três.
 */

export {
  AMBIENTES,
  AmbienteErradoError,
  CofreInacessivelError,
  SecretAusenteError,
  SecretRefInvalidaError,
  anel,
  familiaDaRef,
  isAmbiente,
  validarRef,
} from "./port.ts";
export type {
  Ambiente,
  SecretProvider,
  SecretRef,
  SecretRing,
  SecretRingTuple,
} from "./port.ts";

export {
  EnvSecretProvider,
  PREFIXO,
  SUFIXO_ANTERIOR,
  VERSOES,
  nomeDaVariavel,
} from "./env.ts";
export type { EnvSecretProviderOpcoes, ProcessEnv } from "./env.ts";

export { OpenBaoFakeProvider } from "./openbao-fake.ts";
export type { OpenBaoFakeOpcoes } from "./openbao-fake.ts";

export {
  FamiliaInvalidaError,
  OCTETOS_DO_SUFIXO,
  SemEscritaError,
  cunharRef,
  validarFamilia,
} from "./escrita.ts";
export type { SecretWriter } from "./escrita.ts";

export {
  A_CONFIRMAR,
  DopplerSecretProvider,
  interpretarDescargaPlana,
} from "./doppler.ts";
export type {
  DopplerOpcoes,
  Interpretar,
  PedidoHttp,
  RespostaHttp,
  Transporte,
} from "./doppler.ts";

export { ArranqueAbortadoError, Secrets, TTL_ULTIMO_VALOR_MS } from "./arranque.ts";
export type { SecretsOpcoes } from "./arranque.ts";
