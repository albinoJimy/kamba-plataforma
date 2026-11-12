/**
 * Um descodificador de PNG pequeno e limitado (KAM-087, critério 1).
 *
 * Existe para o PNG não precisar do processo isolado que o PDF e o JPEG
 * precisam: o formato é simples o bastante para se ler com o `zlib` do Node e
 * umas dezenas de linhas, e um descodificador que só aceita uma forma tem menos
 * superfície do que uma biblioteca que aceita todas.
 *
 * **Só aceita** profundidade de 8 bits, tipos de cor 0, 2, 4 e 6 (cinzento,
 * RGB, cinzento com alfa, RGBA), sem entrelaçamento. Recusa o resto com
 * `FicheiroInvalidoError` — uma paleta ou 16 bits não é um documento ilegível,
 * é um formato que este módulo não lê, e o dono é pedido a enviar outro.
 *
 * **Duas guardas contra ficheiros hostis**, e são as que importam: o produto
 * largura × altura é limitado **antes** de descomprimir (`pixeisMaximos`), e o
 * `inflateSync` corre com `maxOutputLength` igual ao tamanho exacto que a
 * imagem declarada tem — uma bomba de descompressão pára no primeiro octeto a
 * mais. O CRC de cada pedaço é conferido.
 */

import { crc32, deflateSync, inflateSync } from "node:zlib";

import type { Pagina } from "./contrato.ts";

/** A assinatura de oito octetos de um PNG. */
export const ASSINATURA_PNG = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Levantado quando um ficheiro não é o que diz ser, ou é de uma forma que não se lê. */
export class FicheiroInvalidoError extends Error {
  override readonly name = "FicheiroInvalidoError";
  constructor(motivo: string) {
    super(`ficheiro invalido: ${motivo}`);
  }
}

/** Uma imagem PNG descodificada. */
export interface PngLido {
  readonly pagina: Pagina;
  /** Os valores das chaves de texto que dizem que *software* escreveu o ficheiro. */
  readonly software: readonly string[];
}

const OCTETOS_POR_PIXEL: Readonly<Record<number, number>> = { 0: 1, 2: 3, 4: 2, 6: 4 };

/** As chaves de texto do PNG que nomeiam o *software*. `XML:com.adobe.xmp` lê-se à parte. */
const CHAVES_DE_SOFTWARE = new Set(["software", "creator", "source"]);

function u32(b: Uint8Array, i: number): number {
  return ((b[i]! << 24) | (b[i + 1]! << 16) | (b[i + 2]! << 8) | b[i + 3]!) >>> 0;
}

/** O `CreatorTool` de um pacote XMP, se houver. */
export function ferramentaDoXmp(xmp: string): string[] {
  const achados: string[] = [];
  for (const m of xmp.matchAll(/CreatorTool(?:="([^"]{1,200})"|>([^<]{1,200})<)/g)) {
    achados.push((m[1] ?? m[2] ?? "").trim());
  }
  return achados.filter((s) => s !== "");
}

/**
 * A etiqueta `Software` (0x0131) do primeiro IFD de um bloco TIFF/EXIF. Cada
 * leitura confere-se contra o tamanho do bloco: um deslocamento para fora dele
 * ignora-se, não se segue. Serve o JPEG (`./forense.ts`) e o pedaço `eXIf` do
 * PNG.
 */
export function softwareDoTiff(t: Uint8Array): string[] {
  if (t.length < 8) return [];
  const pequeno = t[0] === 0x49 && t[1] === 0x49;
  if (!pequeno && !(t[0] === 0x4d && t[1] === 0x4d)) return [];
  const u16 = (o: number): number => (pequeno ? t[o]! | (t[o + 1]! << 8) : (t[o]! << 8) | t[o + 1]!);
  const u32 = (o: number): number =>
    (pequeno
      ? t[o]! | (t[o + 1]! << 8) | (t[o + 2]! << 16) | (t[o + 3]! << 24)
      : (t[o]! << 24) | (t[o + 1]! << 16) | (t[o + 2]! << 8) | t[o + 3]!) >>> 0;
  const ifd = u32(4);
  if (ifd + 2 > t.length) return [];
  const entradas = u16(ifd);
  const achados: string[] = [];
  for (let k = 0; k < entradas; k++) {
    const e = ifd + 2 + k * 12;
    if (e + 12 > t.length) break;
    if (u16(e) !== 0x0131 || u16(e + 2) !== 2) continue;
    const n = u32(e + 4);
    const o = n <= 4 ? e + 8 : u32(e + 8);
    if (n === 0 || n > 200 || o + n > t.length) continue;
    achados.push(Buffer.from(t.subarray(o, o + n)).toString("latin1").replace(/\0+$/, ""));
  }
  return achados;
}

/** Descodifica um PNG em cinzento de 8 bits. Ver a nota do módulo. */
export function descodificarPng(bytes: Uint8Array, pixeisMaximos: number): PngLido {
  if (bytes.length < 8 || ASSINATURA_PNG.some((v, i) => bytes[i] !== v)) {
    throw new FicheiroInvalidoError("sem assinatura PNG");
  }
  let i = 8;
  let largura = 0;
  let altura = 0;
  let tipoDeCor = -1;
  const idat: Uint8Array[] = [];
  const software: string[] = [];
  let fim = false;
  while (i + 12 <= bytes.length && !fim) {
    const comprimento = u32(bytes, i);
    const tipo = String.fromCharCode(bytes[i + 4]!, bytes[i + 5]!, bytes[i + 6]!, bytes[i + 7]!);
    const inicio = i + 8;
    const final = inicio + comprimento;
    if (final + 4 > bytes.length) throw new FicheiroInvalidoError("pedaco truncado");
    const dados = bytes.subarray(inicio, final);
    if (crc32(bytes.subarray(i + 4, final)) !== u32(bytes, final)) {
      throw new FicheiroInvalidoError(`CRC errado em ${tipo.replace(/[^A-Za-z]/g, "?")}`);
    }
    if (tipo === "IHDR") {
      if (comprimento !== 13) throw new FicheiroInvalidoError("IHDR com tamanho errado");
      largura = u32(dados, 0);
      altura = u32(dados, 4);
      const profundidade = dados[8]!;
      tipoDeCor = dados[9]!;
      if (profundidade !== 8 || !(tipoDeCor in OCTETOS_POR_PIXEL)) {
        throw new FicheiroInvalidoError("so 8 bits em cinzento, RGB ou com alfa");
      }
      if (dados[10] !== 0 || dados[11] !== 0 || dados[12] !== 0) {
        throw new FicheiroInvalidoError("sem entrelacamento e com o filtro e a compressao normais");
      }
      if (largura === 0 || altura === 0 || largura * altura > pixeisMaximos) {
        throw new FicheiroInvalidoError("dimensoes fora do limite");
      }
    } else if (tipo === "IDAT") {
      idat.push(dados);
    } else if (tipo === "tEXt") {
      const zero = dados.indexOf(0);
      if (zero > 0) {
        const chave = Buffer.from(dados.subarray(0, zero)).toString("latin1");
        const valor = Buffer.from(dados.subarray(zero + 1)).toString("latin1");
        if (CHAVES_DE_SOFTWARE.has(chave.toLowerCase())) software.push(valor.slice(0, 200));
      }
    } else if (tipo === "eXIf") {
      software.push(...softwareDoTiff(dados));
    } else if (tipo === "zTXt") {
      const zero = dados.indexOf(0);
      if (zero > 0 && dados[zero + 1] === 0) {
        const chave = Buffer.from(dados.subarray(0, zero)).toString("latin1");
        if (CHAVES_DE_SOFTWARE.has(chave.toLowerCase())) {
          try {
            // Com tecto: um metadado não tem razão para passar de 4 KiB.
            const valor = inflateSync(dados.subarray(zero + 2), { maxOutputLength: 4096 });
            software.push(valor.toString("latin1").slice(0, 200));
          } catch {
            // Um pedaço que não descomprime no tecto não se lê, e não vale nada.
          }
        }
      }
    } else if (tipo === "iTXt") {
      const zero = dados.indexOf(0);
      // Só o iTXt sem compressão. Comprimido seria uma segunda descompressão
      // sem limite, e para metadados não vale o risco.
      if (zero > 0 && dados[zero + 1] === 0) {
        const chave = Buffer.from(dados.subarray(0, zero)).toString("latin1");
        let j = zero + 3;
        const lingua = dados.indexOf(0, j);
        const traduzida = lingua < 0 ? -1 : dados.indexOf(0, lingua + 1);
        if (traduzida > 0) {
          j = traduzida + 1;
          const valor = Buffer.from(dados.subarray(j)).toString("utf8");
          if (chave === "XML:com.adobe.xmp") software.push(...ferramentaDoXmp(valor));
          else if (CHAVES_DE_SOFTWARE.has(chave.toLowerCase())) software.push(valor.slice(0, 200));
        }
      }
    } else if (tipo === "IEND") {
      fim = true;
    }
    i = final + 4;
  }
  if (tipoDeCor < 0 || idat.length === 0 || !fim) {
    throw new FicheiroInvalidoError("faltam IHDR, IDAT ou IEND");
  }
  const bpp = OCTETOS_POR_PIXEL[tipoDeCor]!;
  const linha = largura * bpp;
  const esperado = altura * (linha + 1);
  let cru: Buffer;
  try {
    cru = inflateSync(Buffer.concat(idat), { maxOutputLength: esperado });
  } catch {
    throw new FicheiroInvalidoError("dados de imagem que nao descomprimem no tamanho declarado");
  }
  if (cru.length !== esperado) throw new FicheiroInvalidoError("dados de imagem com tamanho errado");

  const cinzento = new Uint8Array(largura * altura);
  let anterior = new Uint8Array(linha);
  for (let y = 0; y < altura; y++) {
    const filtro = cru[y * (linha + 1)]!;
    const actual = Uint8Array.from(cru.subarray(y * (linha + 1) + 1, (y + 1) * (linha + 1)));
    for (let x = 0; x < linha; x++) {
      const a = x >= bpp ? actual[x - bpp]! : 0;
      const b = anterior[x]!;
      const c = x >= bpp ? anterior[x - bpp]! : 0;
      let previsto: number;
      switch (filtro) {
        case 0:
          previsto = 0;
          break;
        case 1:
          previsto = a;
          break;
        case 2:
          previsto = b;
          break;
        case 3:
          previsto = (a + b) >> 1;
          break;
        case 4: {
          const p = a + b - c;
          const pa = Math.abs(p - a);
          const pb = Math.abs(p - b);
          const pc = Math.abs(p - c);
          previsto = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
          break;
        }
        default:
          throw new FicheiroInvalidoError("filtro de linha desconhecido");
      }
      actual[x] = (actual[x]! + previsto) & 0xff;
    }
    for (let x = 0; x < largura; x++) {
      const o = x * bpp;
      cinzento[y * largura + x] =
        tipoDeCor === 2 || tipoDeCor === 6
          ? Math.round((actual[o]! * 299 + actual[o + 1]! * 587 + actual[o + 2]! * 114) / 1000)
          : actual[o]!;
    }
    anterior = actual;
  }
  return { pagina: { largura, altura, cinzento }, software };
}

function pedaco(tipo: string, dados: Uint8Array): Buffer {
  const cabeca = Buffer.alloc(8);
  cabeca.writeUInt32BE(dados.length, 0);
  cabeca.write(tipo, 4, "latin1");
  const cauda = Buffer.alloc(4);
  cauda.writeUInt32BE(crc32(Buffer.concat([cabeca.subarray(4), dados])), 0);
  return Buffer.concat([cabeca, dados, cauda]);
}

/**
 * Codifica uma página em PNG cinzento de 8 bits, com pedaços `tEXt` opcionais.
 *
 * Serve para entregar páginas a um motor fora deste processo (o `tesseract`,
 * o `vision_llm`) numa forma que este módulo controla — nunca o ficheiro
 * original, que pode trazer metadados e pedaços que ninguém leu.
 */
export function codificarPngCinzento(
  pagina: Pagina,
  textos: Readonly<Record<string, string>> = {},
): Uint8Array {
  const { largura, altura, cinzento } = pagina;
  const cru = Buffer.alloc(altura * (largura + 1));
  for (let y = 0; y < altura; y++) {
    cru[y * (largura + 1)] = 0;
    cru.set(cinzento.subarray(y * largura, (y + 1) * largura), y * (largura + 1) + 1);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(largura, 0);
  ihdr.writeUInt32BE(altura, 4);
  ihdr[8] = 8;
  ihdr[9] = 0;
  const partes = [Buffer.from(ASSINATURA_PNG), pedaco("IHDR", ihdr)];
  for (const [chave, valor] of Object.entries(textos)) {
    partes.push(pedaco("tEXt", Buffer.from(`${chave}\0${valor}`, "latin1")));
  }
  partes.push(pedaco("IDAT", deflateSync(cru)), pedaco("IEND", new Uint8Array(0)));
  return new Uint8Array(Buffer.concat(partes));
}
