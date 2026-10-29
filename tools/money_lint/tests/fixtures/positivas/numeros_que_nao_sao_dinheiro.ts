// `chargeTtl`, `refMaxLen` e `idempotencyWindow` sao `number` e **nao** sao
// dinheiro: sao segundos e comprimentos. O lint tem de os deixar passar, senao
// o remedio era tipar segundos como `bigint`.
export type Capacidades = {
  readonly chargeTtl: { readonly min: number; readonly max: number };
  readonly idempotencyWindow: number;
  readonly refMaxLen: number;
};
