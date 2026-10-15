// Positiva: expressões regulares com `/*` e `//` lá dentro não são comentários.
export function limpar(caminho: string): string {
  return caminho.replace(/\/*$/, "").replace(/\/\//g, "/");
}
