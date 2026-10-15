// Negativa: o Node imprime o texto de um aviso no stderr.
export function tratar(cliente: string): void {
  process.emitWarning(`cliente ${cliente} excedeu o limite`);
}
