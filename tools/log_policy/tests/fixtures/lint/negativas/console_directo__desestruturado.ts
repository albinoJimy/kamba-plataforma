// Negativa: o metodo tirado para uma variavel.
const { warn } = console;

export function tratar(pedido: unknown): void {
  warn(pedido);
}
