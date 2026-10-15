/**
 * `@kamba/core-ts/storage` — a porta de armazenamento de objectos (KAM-011, ADR-014).
 *
 * ```ts
 * import { criarStorageS3, lerConfig, novaChave } from "@kamba/core-ts/storage";
 *
 * const storage = criarStorageS3({ config: lerConfig({ ambiente }), secrets });
 *
 * const ctx = { tenantId };
 * const key = novaChave(ctx, "audio");
 * const ref = await storage.put(ctx, key, bytes, {
 *   contentType: "audio/ogg",
 *   classe: "audio",
 *   retainUntil,
 * });
 * const url = await storage.signUrl(ctx, ref, { ttlSeconds: 60 });
 * ```
 *
 * Trocar de servidor — SeaweedFS, S3 gerido — é trocar variáveis de ambiente
 * (`config.ts`); a decisão D6 não está neste código. Nos testes,
 * `criarStorageFake()` dá a mesma porta sobre memória.
 *
 * **Os motores não são exportados daqui como forma de uso.** `MotorS3` e
 * `MotorEmMemoria` não têm noção de tenant; quem os usa directamente saltou o
 * isolamento. As fábricas devolvem a porta já com a guarda.
 */

export {
  ArmazenamentoIndisponivelError,
  ChaveForaDoTenantError,
  ChaveInvalidaError,
  CtxEmFaltaError,
  LIMITE_DE_LISTAGEM,
  ListagemTruncadaError,
  MetaInvalidaError,
  ObjectoInexistenteError,
  RespostaDoMotorInvalidaError,
  TTL_MAXIMO_S,
  TenantInvalidoError,
  TtlInvalidoError,
} from "./port.ts";
export type {
  Corpo,
  Ctx,
  ObjectInfo,
  ObjectKey,
  ObjectMeta,
  ObjectRef,
  StorageProvider,
} from "./port.ts";

export { novaChave, partesDaChave, prefixoDoTenant } from "./chave.ts";
export type { PartesDaChave } from "./chave.ts";

export { criarStorageFake } from "./fake.ts";
export type { RespostaFake, StorageFake } from "./fake.ts";

export {
  ConfigDeArmazenamentoError,
  DestinoSemApdRefError,
  PAIS_SEM_TRANSFERENCIA,
  VARIAVEIS,
  criarStorageS3,
  lerConfig,
} from "./config.ts";
export type {
  DestinoDeArmazenamento,
  CofreLeitor,
  StorageConfig,
} from "./config.ts";
