// `a + b` nao e uma conversao. O lint so acusa o `+` nos contextos em que ele
// so pode ser unario.
export function somar(a: bigint, b: bigint): bigint {
  return a + b;
}

export function tres(a: bigint, b: bigint, c: bigint): bigint {
  return a + b + c;
}
