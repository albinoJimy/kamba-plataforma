// Negativa: `registar` é a porta sem tipos do logger; fora dele não se usa.
import { instalar } from "@kamba/core-ts/logger";

const log = instalar("gwy");

export function tratar(pedido: unknown): void {
  log.registar("info", ["pedido recebido"], pedido);
}
