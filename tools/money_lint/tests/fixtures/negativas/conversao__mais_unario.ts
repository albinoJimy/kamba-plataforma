// A conversao mais curta de um montante de callback para `number`, e a que um
// atalho produz. Estava na docstring do lint e nao estava implementada.
export function ler(corpo: { amount: string }): bigint {
  const valor = +corpo.amount;
  return BigInt(valor);
}
