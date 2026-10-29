// A conversao dentro de `${...}` e codigo e nao prosa. A primeira versao deste
// lint apagava o literal de template inteiro e nao via nada aqui.
export function apresentar(minor: bigint): string {
  return `${Number(minor) / 100} Kz`;
}
