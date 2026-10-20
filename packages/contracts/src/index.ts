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

/**
 * Os contratos de evento, gerados a partir de `contratos/eventos/`.
 *
 * Reexportados daqui e **nao** escritos aqui: o ficheiro
 * `eventos.gerado.ts` sai do `python -m contract_diff gerar`, e o gate 7
 * falha se estiver desactualizado. Um tipo de evento escrito a mao e um
 * schema divergem, e a divergencia so aparece em producao — que e a mesma
 * razao pela qual este modulo nunca escreveu o `HealthzResponseV1` duas
 * vezes.
 */
export * from "./eventos.gerado.ts";

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

/**
 * Caminho do esquema do *job* que o CHR entrega ao AGR (KAM-014, criterio 6).
 *
 * **Nao ha interface escrita a mao a acompanha-lo neste pacote**, ao contrario
 * do `HealthzResponseV1`, e isso e deliberado: o tipo vive em
 * `@kamba/core-ts/chr` (`AgentInvocation`), que e quem monta a mensagem, e um
 * tipo escrito duas vezes divergia — a mesma razao que o cabecalho deste modulo
 * ja da para o `eventos.gerado.ts`. O que este pacote publica e o **esquema**,
 * que e o artefacto que o AGR (Python) tambem le.
 *
 * O caminho do ficheiro **nao** e o que o criterio 6 do KAM-014 escreve
 * (`packages/contracts/agent_invocation.schema.json`): os esquemas vivem em
 * `schemas/` com a versao no nome, e um `*.schema.json` bate numa sentinela do
 * gate 3b que o exige dentro de `contratos/eventos/`. Esta registado na secao
 * de verificacao do ticket, com a caixa por marcar.
 */
export const AGENT_INVOCATION_V1_PATH = require.resolve(
  "../schemas/agent_invocation.v1.json",
);
