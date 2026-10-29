// A travessia certa: lexical, sem passar por IEEE-754 em passo nenhum.
export function minorDeDecimal2(texto: string): bigint {
  const encontro = /^(\d{1,15})(?:\.(\d{1,2}))?$/.exec(texto);
  if (encontro === null) throw new Error("forma invalida");
  const inteiro = encontro[1] ?? "";
  const fraccao = (encontro[2] ?? "").padEnd(2, "0");
  return BigInt(`${inteiro}${fraccao}`);
}
