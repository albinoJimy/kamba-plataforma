// `1e2` e a conversao kwanzas->centimos por `number`, com o mesmo erro.
export function centimos(kwanzas: bigint): bigint {
  return BigInt(1e2) * kwanzas;
}
