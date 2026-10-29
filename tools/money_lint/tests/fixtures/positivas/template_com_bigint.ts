// Formatar por template e legitimo **se** nao houver conversao: estes sao
// `bigint` e o lint tem de os deixar passar, senao o remedio era nao formatar.
export function decimal2(kz: bigint, centimos: bigint): string {
  return `${kz}.${`${centimos}`.padStart(2, "0")}`;
}
