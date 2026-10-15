// Negativa: uma expressão regular com `/*` lá dentro não abre um comentário
// (a primeira versão do lint apagava o resto do ficheiro a partir dela).
export function tratar(caminho: string): string {
  const limpo = caminho.replace(/\/*$/, "");
  console.log(limpo);
  return limpo;
}
