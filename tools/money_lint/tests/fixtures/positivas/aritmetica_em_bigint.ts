// Dividir e multiplicar em `bigint` e legitimo: o literal e inteiro.
export const MINOR_POR_KZ = 100n;

export function kwanzas(minor: bigint): bigint {
  return minor / MINOR_POR_KZ;
}

export function centimos(minor: bigint): bigint {
  return minor % MINOR_POR_KZ;
}
