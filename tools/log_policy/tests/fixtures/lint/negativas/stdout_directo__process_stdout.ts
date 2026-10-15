// Negativa: escrita directa no descritor.
export function tratar(pedido: string): void {
  process.stdout.write(`${pedido}\n`);
}
