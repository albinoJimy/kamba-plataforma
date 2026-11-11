/**
 * Forense: o formato pela assinatura, o *hash* perceptual e o *software* nos
 * metadados (KAM-087, critérios 1 e 4).
 *
 * Nada aqui lê o texto do documento. São três perguntas sobre o **ficheiro**:
 * é o que diz ser, já foi visto noutro caso, e passou por um editor de imagem.
 */

import { ferramentaDoXmp, softwareDoTiff } from "./png.ts";
import type { Formato, Pagina } from "./contrato.ts";

/**
 * O formato pelos primeiros octetos, ou `null`. **Nunca** pela extensão nem
 * pelo `Content-Type` que o cliente mandou (critério 1).
 */
export function detectarFormato(bytes: Uint8Array): Formato | null {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "jpeg";
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) {
    return "png";
  }
  if (
    bytes.length >= 5 &&
    bytes[0] === 0x25 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x44 &&
    bytes[3] === 0x46 &&
    bytes[4] === 0x2d
  ) {
    return "pdf";
  }
  return null;
}

/**
 * O *software* que um JPEG declara: a etiqueta EXIF `Software` (0x0131) e o
 * `CreatorTool` do XMP.
 *
 * Lê só os segmentos APP1 antes do início da imagem, e cada leitura é
 * conferida contra o tamanho do segmento — um EXIF com deslocamentos para fora
 * dele é ignorado, não seguido.
 */
export function softwareDoJpeg(bytes: Uint8Array): string[] {
  const achados: string[] = [];
  let i = 2;
  while (i + 4 <= bytes.length && bytes[i] === 0xff) {
    const marcador = bytes[i + 1]!;
    if (marcador === 0xda || marcador === 0xd9) break;
    const tamanho = (bytes[i + 2]! << 8) | bytes[i + 3]!;
    const inicio = i + 4;
    const fim = i + 2 + tamanho;
    if (tamanho < 2 || fim > bytes.length) break;
    if (marcador === 0xe1) {
      const seg = bytes.subarray(inicio, fim);
      const cabeca = Buffer.from(seg.subarray(0, 29)).toString("latin1");
      if (cabeca.startsWith("Exif\0\0")) achados.push(...softwareDoTiff(seg.subarray(6)));
      else if (cabeca.startsWith("http://ns.adobe.com/xap/1.0/")) {
        achados.push(...ferramentaDoXmp(Buffer.from(seg).toString("utf8")));
      }
    }
    i = fim;
  }
  return achados;
}

/**
 * Os editores de imagem e de PDF cujo nome nos metadados é sinal duro
 * (critério 4). ***Proposta***, e lista e não heurística: um nome novo é um
 * diff. Não estão os programas que **criam** documentos legítimos — um
 * processador de texto, o *software* de um digitalizador, o Acrobat a
 * digitalizar papel —, porque um alvará emitido em PDF por uma repartição é
 * escrito por um deles.
 */
export const EDITORES = [
  "photoshop",
  "gimp",
  "paint.net",
  "pixelmator",
  "affinity photo",
  "canva",
  "pixlr",
  "picsart",
  "snapseed",
  "fotor",
  "photopea",
  "inkscape",
  "illustrator",
  "coreldraw",
  "ilovepdf",
  "sejda",
  "pdfescape",
  "smallpdf",
  "pdf-xchange editor",
  "foxit phantompdf",
  "foxit pdf editor",
  "nitro pro",
] as const;

/** Algum dos nomes nos metadados é de um editor? */
export function softwareDeEdicao(software: readonly string[]): boolean {
  return software.some((s) => {
    const n = s.normalize("NFKC").toLowerCase();
    return EDITORES.some((e) => n.includes(e));
  });
}

/**
 * O dHash de 64 bits de uma página, em hexadecimal.
 *
 * A página reduz-se a 9 × 8 por média de áreas e cada bit diz se um ponto é
 * mais escuro do que o vizinho da direita. Sobrevive a recompressão, a mudança
 * de escala e a pequenos ajustes de brilho, que é o que separa «a mesma
 * fotografia enviada outra vez» de «outra fotografia do mesmo documento».
 */
export function dhash(p: Pagina): string {
  const L = 9;
  const A = 8;
  const media = new Float64Array(L * A);
  for (let gy = 0; gy < A; gy++) {
    const y0 = Math.floor((gy * p.altura) / A);
    const y1 = Math.max(y0 + 1, Math.floor(((gy + 1) * p.altura) / A));
    for (let gx = 0; gx < L; gx++) {
      const x0 = Math.floor((gx * p.largura) / L);
      const x1 = Math.max(x0 + 1, Math.floor(((gx + 1) * p.largura) / L));
      let soma = 0;
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) soma += p.cinzento[y * p.largura + x] ?? 0;
      }
      media[gy * L + gx] = soma / ((y1 - y0) * (x1 - x0));
    }
  }
  let bits = 0n;
  for (let gy = 0; gy < A; gy++) {
    for (let gx = 0; gx < L - 1; gx++) {
      bits = (bits << 1n) | (media[gy * L + gx]! < media[gy * L + gx + 1]! ? 1n : 0n);
    }
  }
  return bits.toString(16).padStart(16, "0");
}

/** A distância de Hamming entre dois dHash em hexadecimal. */
export function hamming(a: string, b: string): number {
  let x = BigInt(`0x${a}`) ^ BigInt(`0x${b}`);
  let n = 0;
  while (x > 0n) {
    n += Number(x & 1n);
    x >>= 1n;
  }
  return n;
}
