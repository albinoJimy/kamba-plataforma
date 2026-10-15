/**
 * Positiva: falar de `console.log` e de `process.stdout` num comentario nao e
 * usa-los.
 */
// console.log("isto e um comentario");
/* process.stderr.write("isto tambem"); */
import { instalar } from "@kamba/core-ts/logger";

const log = instalar("gwy");

export function tratar(): void {
  const endereco = "http://exemplo.invalid/caminho"; // um `//` dentro de uma cadeia
  log.info({ outcome: endereco.length > 0 ? "ok" : "erro" });
}
