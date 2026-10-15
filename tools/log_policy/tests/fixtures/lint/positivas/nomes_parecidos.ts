// Positiva: nomes que contem as palavras proibidas sem o serem.
export const consola = 1;
export const processStdout = 2;
export const reprint = 3;

export function tratar(processo: { stdoutLivre: number }): number {
  return consola + processStdout + reprint + processo.stdoutLivre;
}
