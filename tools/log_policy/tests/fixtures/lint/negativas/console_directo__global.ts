// Negativa: o mesmo objecto, por `globalThis`.
export function tratar(pedido: unknown): void {
  globalThis.console.error("falhou", pedido);
}
