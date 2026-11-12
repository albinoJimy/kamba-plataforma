/**
 * O motor de OCR local de produção: o `tesseract` (Apache-2.0), num processo
 * local (KAM-087, critério 2).
 *
 * As páginas chegam já rasterizadas e são reescritas em PNG cinzento por
 * `codificarPngCinzento` — o `tesseract` nunca vê o ficheiro que o dono
 * enviou. O resultado lê-se no formato TSV, que dá a confiança palavra a
 * palavra; a confiança de uma linha é a **média** das das palavras, à escala
 * `[0, 1]`.
 *
 * **NÃO VERIFICADO contra o binário.** O *runner* do CI não tem o `tesseract`
 * instalado, e instalá-lo é mudar um *job*, que é do fundador. O que está
 * medido é a leitura do TSV, sobre linhas escritas à mão pela forma documentada
 * do formato, e a construção dos argumentos. Que a qualidade de leitura do
 * `tesseract` sobre documentos angolanos chegue aos 0,90 do critério 5 é a
 * pergunta que só documentos reais respondem — e esses não entram neste
 * repositório.
 */

import { codificarPngCinzento } from "./png.ts";
import type { LinhaLida, MotorDeOcr, Pagina } from "./contrato.ts";

/** Executa um programa com `args` e `entrada` no *stdin*; nunca por *shell*. */
export type Executor = (
  programa: string,
  args: readonly string[],
  entrada: Uint8Array,
) => Promise<{ readonly codigo: number; readonly saida: string }>;

/**
 * Os argumentos: `-` para a entrada e para a saída padrão (aceite desde o
 * `tesseract` 4, INDÍCIO da documentação e NÃO VERIFICADO contra o binário),
 * português, um bloco uniforme, TSV.
 */
export const ARGUMENTOS = ["-", "-", "-l", "por", "--psm", "6", "tsv"] as const;

/**
 * As linhas de um TSV do `tesseract`.
 *
 * Colunas: `level page_num block_num par_num line_num word_num left top width
 * height conf text`. Só as linhas de nível 5 (palavra) com confiança ≥ 0
 * contam; agrupam-se por `(page, block, par, line)`.
 */
export function linhasDoTsv(tsv: string): LinhaLida[] {
  const grupos = new Map<string, { palavras: string[]; confs: number[] }>();
  for (const linha of tsv.split(/\r?\n/).slice(1)) {
    const c = linha.split("\t");
    if (c.length < 12 || c[0] !== "5") continue;
    const conf = Number(c[10]);
    const texto = c.slice(11).join("\t").trim();
    if (!Number.isFinite(conf) || conf < 0 || texto === "") continue;
    const chave = `${c[1]}.${c[2]}.${c[3]}.${c[4]}`;
    const g = grupos.get(chave) ?? { palavras: [], confs: [] };
    g.palavras.push(texto);
    g.confs.push(Math.min(100, conf));
    grupos.set(chave, g);
  }
  return [...grupos.values()].map((g) => ({
    texto: g.palavras.join(" "),
    conf: g.confs.reduce((a, b) => a + b, 0) / g.confs.length / 100,
  }));
}

export class MotorTesseract implements MotorDeOcr {
  readonly nome = "tesseract";
  readonly #executar: Executor;
  readonly #programa: string;

  constructor(executar: Executor, programa = "tesseract") {
    this.#executar = executar;
    this.#programa = programa;
  }

  async ler(pagina: Pagina): Promise<readonly LinhaLida[]> {
    const r = await this.#executar(this.#programa, ARGUMENTOS, codificarPngCinzento(pagina));
    if (r.codigo !== 0) throw new Error(`tesseract saiu com ${r.codigo}`);
    return linhasDoTsv(r.saida);
  }
}
