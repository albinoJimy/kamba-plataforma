// Negativa: o fluxo tirado de `process` para uma variável.
const { stderr } = process;

export function tratar(pedido: string): void {
  stderr.write(pedido);
}
