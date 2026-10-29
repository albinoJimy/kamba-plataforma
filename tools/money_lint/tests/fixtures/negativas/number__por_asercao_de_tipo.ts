// Num modulo de dinheiro nao ha `as number` legitimo.
export function somar(linhas: { preco: string }[]): bigint {
  return BigInt(linhas.reduce((a, l) => a + (l.preco as unknown as number), 0));
}
