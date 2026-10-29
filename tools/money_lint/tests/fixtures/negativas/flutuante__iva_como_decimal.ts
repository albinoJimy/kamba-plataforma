// O IVA de 14% escrito como factor: o literal e o defeito.
export function comIva(valor: bigint): bigint {
  const factor = 1.14;
  return BigInt(factor);
}
