/**
 * Identidade do serviço, lida do seu próprio `package.json`.
 *
 * A versão não se escreve aqui à mão: o `package.json` é o que o `pnpm` vê e o
 * que o Renovate actualiza, e duas versões em dois sítios divergem.
 */

import { createRequire } from "node:module";

import type { ServiceName } from "@kamba/contracts";

const require = createRequire(import.meta.url);
const manifest = require("../package.json") as { version: string };

export const SERVICE: ServiceName = "gwy";
export const VERSION: string = manifest.version;
export const DEFAULT_PORT = 3000;
