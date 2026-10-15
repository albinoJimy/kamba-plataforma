/**
 * Um processo a sério que instala o *logger* e deixa um erro por tratar.
 *
 * Corrido como processo-filho por `logger.test.ts`, que lhe lê o `stdout` e o
 * `stderr` verdadeiros: é a única forma de provar que o Node não imprime a
 * pilha e a mensagem por cima da linha do *logger* (KAM-068, primeira revisão).
 */

import { instalar } from "../../src/logger/index.ts";

instalar("gwy");

const modo = process.argv[2];
const canario = process.argv[3] ?? "";

if (modo === "rejeicao") {
  void Promise.reject(new RangeError(`cliente ${canario} recusado`));
} else if (modo === "aviso") {
  process.emitWarning(`cliente ${canario} excedeu o limite`);
} else {
  throw new TypeError(`PORT invalida: ${canario}`);
}
