/**
 * Contratos da KAMBÁ — fonte única para TypeScript e Python.
 *
 * Os esquemas em `schemas/` são a verdade; este módulo apenas dá acesso
 * tipado a eles. Nenhum tipo é escrito à mão duas vezes: um tipo escrito à
 * mão e um esquema divergem, e a divergência só aparece em produção.
 *
 * Versionamento: o nome do ficheiro carrega a versão (`*.v1.json`). Campos
 * novos são aditivos; uma quebra de contrato é um ficheiro `v2` e um
 * *release* MAJOR (`specs/01` §5).
 */

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

/** Serviços do Piloto, conforme `docs/tecnica/09` §3.1. */
export const SERVICES = [
  "gwy",
  "worker-canal",
  "agr",
  "com",
  "onboarding-web",
] as const;

export type ServiceName = (typeof SERVICES)[number];

/** Resposta de `/healthz`, validada por `schemas/healthz.response.v1.json`. */
export interface HealthzResponseV1 {
  status: "ok";
  service: ServiceName;
  /** SemVer do pacote do serviço. */
  version: string;
  /** SHA do commit injectado na construção, ou `"unknown"` fora do CI. */
  commit: string;
}

/**
 * Caminho do esquema de `/healthz`, para quem precise de o validar.
 *
 * `../schemas/` resolve bem dos dois sítios: deste ficheiro em `src/` e do
 * ficheiro emitido em `dist/`, porque `src/` e `dist/` são irmãos de `schemas/`.
 * Os esquemas **não** são copiados para `dist/`: o JSON é o artefacto publicado
 * e tem um só exemplar.
 */
export const HEALTHZ_RESPONSE_V1_PATH = require.resolve(
  "../schemas/healthz.response.v1.json",
);
