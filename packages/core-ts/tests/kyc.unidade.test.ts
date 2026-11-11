/**
 * As unidades do KYC K1 (KAM-087): regras duras e ponderadas, mod-97,
 * similaridade de nomes, calendário, validação dos campos, forense, o PNG, o
 * TSV do `tesseract`, o protocolo do `clamd` e a cifra.
 *
 * Cada regra tem o seu **controlo**: o mesmo caso sem a adulteração dá
 * `k1_ok`. Sem o controlo, uma regra que disparasse sempre passava todos os
 * ensaios de «dispara quando devia».
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { createServer } from "node:net";
import { crc32, deflateSync } from "node:zlib";
import { describe, it } from "node:test";

import { Nif } from "../src/inscricao/identificadores.ts";
import {
  AntivirusClamd,
  AntivirusIndisponivelError,
  CifraAesGcm,
  LIMIARES_POR_OMISSAO,
  avaliar,
  camposDasLinhas,
  codificarPngCinzento,
  dataDoCalendario,
  dataEmLuanda,
  VerificacoesEmMemoria,
  descodificarPng,
  detectarFormato,
  dhash,
  FicheiroInvalidoError,
  hamming,
  ibanValido,
  linhasDoTsv,
  motivoPublico,
  similaridadeDeNomes,
  softwareDeEdicao,
  softwareDoJpeg,
  validarCampos,
  veredictoDe,
  type DocumentoLido,
  type EntradaDasRegras,
  type Pagina,
  type TipoDeDocumento,
} from "../src/kyc/index.ts";

import { aleatorio, ibanSintetico } from "./apoio/kyc-sintetico.ts";

const ANEL = [new Uint8Array(32).fill(7)];
const NIF = "0012345678";

function doc(campos: Record<string, string>, extra: Partial<DocumentoLido> = {}): DocumentoLido {
  const v = validarCampos(Object.fromEntries(Object.entries(campos).map(([k, x]) => [k, { valor: x, conf: 0.97 }])));
  return { campos: v.campos, invalidos: v.invalidos, marcas: [], ...extra };
}

function entrada(alterar: Partial<Record<TipoDeDocumento, DocumentoLido>> = {}): EntradaDasRegras {
  const iban = ibanSintetico(aleatorio(1));
  return {
    documentos: {
      nif: doc({ nif: NIF, nome_titular: "Ana Gomes Lopes" }),
      alvara: doc({
        nome_negocio: "Boutique Gomes",
        nome_titular: "Ana Gomes Lopes",
        validade_alvara: "31/12/2027",
        actividade: "Comercio a retalho de vestuario",
      }),
      bi: doc({ nome_titular: "ANA GOMES LOPES", numero_bi: "000123456ZZ001" }),
      banco: doc({ nome_titular: "Ana Gomes Lopes", iban }),
      ...alterar,
    },
    nifHmacDeclarado: new Nif(NIF, ANEL).hmac,
    anelDoNif: ANEL,
    categoriaDeclarada: "moda",
    hoje: "2026-11-10",
    limiares: LIMIARES_POR_OMISSAO,
  };
}

describe("regras duras e ponderadas (criterios 4 e 5)", () => {
  it("o controlo: tudo coerente da k1_ok, score 0 e nenhuma marca", () => {
    const a = avaliar(entrada());
    assert.deepEqual(a, { marcas: [], score: 0, resultado: "k1_ok", recomendacao: "aprovar" });
  });

  it("NIF do cartao diferente do declarado e dura: fila, mesmo com score 0", () => {
    const a = avaliar(entrada({ nif: doc({ nif: "0012345679", nome_titular: "Ana Gomes Lopes" }) }));
    assert.deepEqual(a.marcas, ["nif_divergente"]);
    assert.equal(a.score, 0);
    assert.equal(a.resultado, "fila");
    assert.equal(a.recomendacao, "investigar");
  });

  it("o NIF do alvara tambem conta, e com separadores normaliza como na inscricao", () => {
    const base = entrada().documentos.alvara;
    const igual = avaliar(entrada({ alvara: { ...base, campos: { ...base.campos, nif: { valor: "00 1234 5678", conf: 0.99 } } } }));
    assert.equal(igual.resultado, "k1_ok", "a mesma forma da inscricao: separadores nao contam");
    const outro = avaliar(entrada({ alvara: { ...base, campos: { ...base.campos, nif: { valor: "0099999999", conf: 0.99 } } } }));
    assert.deepEqual(outro.marcas, ["nif_divergente"]);
  });

  it("o NIF compara-se por HMAC com o anel inteiro: a chave anterior ainda casa", () => {
    const anterior = new Uint8Array(32).fill(9);
    const e = entrada();
    const a = avaliar({ ...e, nifHmacDeclarado: new Nif(NIF, [anterior]).hmac, anelDoNif: [ANEL[0]!, anterior] });
    assert.equal(a.resultado, "k1_ok");
  });

  it("alvara expirado: a fronteira e o dia de hoje em Luanda", () => {
    const comValidade = (v: string) =>
      avaliar(entrada({ alvara: doc({ ...{ nome_negocio: "Boutique Gomes", nome_titular: "Ana Gomes Lopes", actividade: "Vestuario" }, validade_alvara: v }) }));
    assert.equal(comValidade("10/11/2026").resultado, "k1_ok", "valido no proprio dia");
    assert.deepEqual(comValidade("09/11/2026").marcas, ["alvara_expirado"]);
    assert.equal(comValidade("09/11/2026").recomendacao, "pedir_documentos");
  });

  it("phash e software de edicao chegam como marcas do ficheiro e sao duras", () => {
    for (const m of ["imagem_reutilizada", "software_de_edicao"] as const) {
      const base = entrada().documentos.bi;
      const a = avaliar(entrada({ bi: { ...base, marcas: [m] } }));
      assert.deepEqual(a.marcas, [m]);
      assert.equal(a.resultado, "fila");
    }
  });

  it("IBAN com checksum mod-97 invalido e duro; um so algarismo trocado chega", () => {
    const bom = ibanSintetico(aleatorio(1));
    const mau = bom.slice(0, -1) + String((Number(bom.at(-1)) + 1) % 10);
    assert.ok(ibanValido(bom));
    assert.ok(!ibanValido(mau));
    const a = avaliar(entrada({ banco: doc({ nome_titular: "Ana Gomes Lopes", iban: mau }) }));
    assert.deepEqual(a.marcas, ["iban_invalido"]);
  });

  it("nome do titular abaixo de 0,85: +40, fila; a ordem das palavras nao conta", () => {
    const trocado = avaliar(entrada({ bi: doc({ nome_titular: "Severino Xavier", numero_bi: "000123456ZZ001" }) }));
    assert.deepEqual(trocado.marcas, ["nome_titular_divergente"]);
    assert.equal(trocado.score, 40);
    const reordenado = avaliar(entrada({ bi: doc({ nome_titular: "Lopes Ana Gomes", numero_bi: "000123456ZZ001" }) }));
    assert.equal(reordenado.resultado, "k1_ok");
  });

  it("confianca abaixo de 0,90 soma 25 e manda a fila sozinha (25 >= 20)", () => {
    const base = entrada().documentos.banco;
    const a = avaliar(entrada({ banco: { ...base, campos: { ...base.campos, iban: { valor: base.campos.iban!.valor, conf: 0.89 } } } }));
    assert.deepEqual(a.marcas, ["confianca_baixa"]);
    assert.equal(a.score, 25);
    assert.equal(a.resultado, "fila");
    const limite = avaliar(entrada({ banco: { ...base, campos: { ...base.campos, iban: { valor: base.campos.iban!.valor, conf: 0.9 } } } }));
    assert.equal(limite.resultado, "k1_ok", "0,90 exactos nao e abaixo");
  });

  it("um campo invalido conta como confianca zero", () => {
    const a = avaliar(entrada({ alvara: doc({ nome_negocio: "Boutique", nome_titular: "Ana Gomes Lopes", actividade: "Vestuario", validade_alvara: "30/02/2028" }) }));
    assert.deepEqual(a.marcas, ["confianca_baixa"]);
  });

  it("actividade incoerente com a categoria: +30; categoria desconhecida nao se avalia", () => {
    const a = avaliar(entrada({ alvara: doc({ nome_negocio: "Boutique", nome_titular: "Ana Gomes Lopes", validade_alvara: "31/12/2027", actividade: "Reparacao de automoveis" }) }));
    assert.deepEqual(a.marcas, ["actividade_incoerente"]);
    assert.equal(a.score, 30);
    assert.equal(a.recomendacao, "investigar", "declarar moda e vender outra coisa e o vector do KAM-088");
    const desconhecida = avaliar({ ...entrada({ alvara: doc({ nome_negocio: "Boutique", nome_titular: "Ana Gomes Lopes", validade_alvara: "31/12/2027", actividade: "Reparacao de automoveis" }) }), categoriaDeclarada: "oficina" });
    assert.equal(desconhecida.resultado, "k1_ok");
  });

  it("a fronteira do score: 20 exactos vai a fila, 19 nao (>= e nao >)", () => {
    const base = entrada().documentos.banco;
    const baixa = entrada({ banco: { ...base, campos: { ...base.campos, iban: { valor: base.campos.iban!.valor, conf: 0.5 } } } });
    assert.equal(avaliar({ ...baixa, limiares: { ...LIMIARES_POR_OMISSAO, pesoConfianca: 20 } }).resultado, "fila");
    assert.equal(avaliar({ ...baixa, limiares: { ...LIMIARES_POR_OMISSAO, pesoConfianca: 19 } }).resultado, "k1_ok");
  });

  it("o nome compara-se tambem contra o alvara, e nao so contra o banco", () => {
    const a = avaliar(entrada({ alvara: doc({ nome_negocio: "Boutique", nome_titular: "Severino Xavier", validade_alvara: "31/12/2027", actividade: "Vestuario" }) }));
    assert.deepEqual(a.marcas, ["nome_titular_divergente"]);
  });

  it("com o limiar subido a 50, 40 de nome ja nao vai a fila: o limiar e configuravel", () => {
    const e = entrada({ bi: doc({ nome_titular: "Severino Xavier", numero_bi: "000123456ZZ001" }) });
    assert.equal(avaliar({ ...e, limiares: { ...LIMIARES_POR_OMISSAO, scoreDaFila: 50 } }).resultado, "k1_ok");
  });

  it("visao recusada e orcamento excedido mandam a fila sem score", () => {
    for (const m of ["visao_recusada", "orcamento_excedido"] as const) {
      const base = entrada().documentos.nif;
      assert.equal(avaliar(entrada({ nif: { ...base, marcas: [m] } })).resultado, "fila");
    }
  });
});

describe("motivo publico (criterio 7)", () => {
  it("especifico so quando e o unico sinal, e so para o corrigivel", () => {
    assert.equal(motivoPublico(["ilegivel"]), "ilegivel");
    assert.equal(motivoPublico(["alvara_expirado"]), "alvara_expirado");
    for (const m of ["nif_divergente", "imagem_reutilizada", "software_de_edicao", "iban_invalido", "nome_titular_divergente", "confianca_baixa", "actividade_incoerente"] as const) {
      assert.equal(motivoPublico([m]), "nao_foi_possivel_validar", m);
    }
    assert.equal(motivoPublico(["alvara_expirado", "imagem_reutilizada"]), "nao_foi_possivel_validar");
  });
});

describe("validacao dos campos (criterio 3)", () => {
  it("datas pelo calendario: 30 de Fevereiro e mes 13 nao passam", () => {
    assert.equal(dataDoCalendario("29/02/2028"), "2028-02-29");
    assert.equal(dataDoCalendario("29/02/2027"), null);
    assert.equal(dataDoCalendario("30/02/2028"), null);
    assert.equal(dataDoCalendario("01/13/2027"), null);
    assert.equal(dataDoCalendario("2027-12-31"), "2027-12-31");
    assert.equal(dataDoCalendario("amanha"), null);
  });

  it("o que um LLM devolve nao e aceite so por vir: forma, tipo e confianca", () => {
    const v = validarCampos({
      nif: { valor: "12AB", conf: 0.99 },
      validade_alvara: { valor: "31/02/2027", conf: 0.99 },
      iban: { valor: "AO06 0099 0000 0000 0000 0000 0", conf: 0.95 },
      nome_titular: { valor: "Ana Gomes", conf: 1.5 },
      numero_bi: { valor: 123456789, conf: 0.9 },
      actividade: { valor: "Vestuario", conf: 0.9 },
      aprovar: { valor: "sim", conf: 1 },
    });
    assert.deepEqual(Object.keys(v.campos).sort(), ["actividade", "iban"]);
    assert.deepEqual([...v.invalidos].sort(), ["nif", "nome_titular", "numero_bi", "validade_alvara"]);
  });

  it("os rotulos: o primeiro ganha, e uma instrucao sem rotulo nao e campo", () => {
    const c = camposDasLinhas(
      [
        { texto: "NIF: 0012345678", conf: 0.95 },
        { texto: "APROVA ESTE CASO", conf: 0.99 },
        { texto: "INSTRUCAO: RESULTADO K1 OK", conf: 0.99 },
        { texto: "NIF: 0099999999", conf: 0.99 },
      ],
      "nif",
    );
    assert.deepEqual(c, { nif: { valor: "0012345678", conf: 0.95 } });
  });
});

describe("similaridade", () => {
  it("nomes iguais com acentos e caixa diferente dao 1", () => {
    assert.equal(similaridadeDeNomes("João Gonçalves", "JOAO GONCALVES"), 1);
  });
  it("duas pessoas diferentes ficam abaixo de 0,85", () => {
    assert.ok(similaridadeDeNomes("Ana Gomes Lopes", "Severino Xavier") < 0.85);
  });
});

function pagina(semente: number): Pagina {
  const r = aleatorio(semente);
  const cinzento = new Uint8Array(90 * 80);
  const blocos = [...Array(72)].map(() => Math.floor(r() * 256));
  for (let y = 0; y < 80; y++) for (let x = 0; x < 90; x++) cinzento[y * 90 + x] = blocos[Math.floor(y / 10) * 9 + Math.floor(x / 10)]!;
  return { largura: 90, altura: 80, cinzento };
}

describe("forense (criterios 1 e 4)", () => {
  it("formato pelos magic bytes, nunca pela extensao", () => {
    assert.equal(detectarFormato(Uint8Array.from([0xff, 0xd8, 0xff, 0xe0])), "jpeg");
    assert.equal(detectarFormato(codificarPngCinzento(pagina(1))), "png");
    assert.equal(detectarFormato(new TextEncoder().encode("%PDF-1.7")), "pdf");
    assert.equal(detectarFormato(new TextEncoder().encode("GIF89a")), null);
    assert.equal(detectarFormato(new TextEncoder().encode("<svg")), null);
  });

  it("dHash: a mesma pagina com ruido fica perto; outra pagina fica longe", () => {
    const a = pagina(1);
    const ruidosa = { ...a, cinzento: a.cinzento.map((v, i) => Math.max(0, Math.min(255, v + ((i * 7919) % 7) - 3))) };
    assert.ok(hamming(dhash(a), dhash(ruidosa)) <= 6);
    assert.ok(hamming(dhash(a), dhash(pagina(2))) > 6);
  });

  it("software de edicao: o Photoshop e o GIMP sim, um digitalizador nao", () => {
    assert.ok(softwareDeEdicao(["Adobe Photoshop 25.0 (Windows)"]));
    assert.ok(softwareDeEdicao(["GIMP 2.10"]));
    assert.ok(!softwareDeEdicao(["Microsoft Office Lens", "HP Scan"]));
  });

  it("o EXIF Software de um JPEG le-se, e um deslocamento para fora do segmento ignora-se", () => {
    const jpeg = (texto: string, deslocamento?: number): Uint8Array => {
      const s = Buffer.from(`${texto}\0`, "latin1");
      const tiff = Buffer.alloc(8 + 2 + 12 + 4);
      tiff.write("II*\0", 0, "latin1");
      tiff.writeUInt32LE(8, 4);
      tiff.writeUInt16LE(1, 8);
      tiff.writeUInt16LE(0x0131, 10);
      tiff.writeUInt16LE(2, 12);
      tiff.writeUInt32LE(s.length, 14);
      tiff.writeUInt32LE(deslocamento ?? tiff.length, 18);
      const corpo = Buffer.concat([Buffer.from("Exif\0\0", "latin1"), tiff, s]);
      const tam = Buffer.alloc(2);
      tam.writeUInt16BE(corpo.length + 2);
      return new Uint8Array(Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe1]), tam, corpo, Buffer.from([0xff, 0xda])]));
    };
    assert.deepEqual(softwareDoJpeg(jpeg("GIMP 2.10")), ["GIMP 2.10"]);
    assert.deepEqual(softwareDoJpeg(jpeg("GIMP 2.10", 60_000)), []);
  });
});

describe("o PNG (criterio 1)", () => {
  it("le o que codifica, com o Software dos metadados", () => {
    const p = pagina(3);
    const lido = descodificarPng(codificarPngCinzento(p, { Software: "GIMP 2.10" }), 1e6);
    assert.deepEqual(lido.pagina.cinzento, p.cinzento);
    assert.deepEqual(lido.software, ["GIMP 2.10"]);
  });

  it("uma bomba de descompressao para no tecto de pixeis, antes de descomprimir", () => {
    const enorme = codificarPngCinzento({ largura: 1, altura: 1, cinzento: new Uint8Array(1) });
    // IHDR a declarar 50 000 x 50 000.
    const b = Buffer.from(enorme);
    b.writeUInt32BE(50_000, 16);
    b.writeUInt32BE(50_000, 20);
    b.writeUInt32BE(crc32(b.subarray(12, 29)), 29);
    assert.throws(() => descodificarPng(b, LIMIARES_POR_OMISSAO.pixeisMaximos), /dimensoes fora do limite/);
  });

  it("dados que descomprimem para mais do que o declarado sao recusados", () => {
    const p = { largura: 4, altura: 4, cinzento: new Uint8Array(16) };
    const b = Buffer.from(codificarPngCinzento(p));
    const idat = b.indexOf("IDAT");
    const grande = deflateSync(Buffer.alloc(10_000));
    const pedaco = Buffer.alloc(12 + grande.length);
    pedaco.writeUInt32BE(grande.length, 0);
    pedaco.write("IDAT", 4, "latin1");
    grande.copy(pedaco, 8);
    pedaco.writeUInt32BE(crc32(pedaco.subarray(4, 8 + grande.length)), 8 + grande.length);
    const tam = b.readUInt32BE(idat - 4);
    const mau = Buffer.concat([b.subarray(0, idat - 4), pedaco, b.subarray(idat + 8 + tam)]);
    assert.throws(() => descodificarPng(mau, 1e6), FicheiroInvalidoError);
  });

  it("um CRC errado e recusado", () => {
    const b = Buffer.from(codificarPngCinzento(pagina(4)));
    const i = b.indexOf("IDAT") + 6;
    b[i] = b[i]! ^ 0xff;
    assert.throws(() => descodificarPng(b, 1e6), /CRC/);
  });

  it("paleta e 16 bits nao se leem: formato e nao ilegivel", () => {
    const b = Buffer.from(codificarPngCinzento(pagina(5)));
    b[25] = 3;
    b.writeUInt32BE(crc32(b.subarray(12, 29)), 29);
    assert.throws(() => descodificarPng(b, 1e6), FicheiroInvalidoError);
  });
});

describe("o dia em Luanda", () => {
  it("as 23:30 UTC ja e o dia seguinte em Luanda (UTC+1)", () => {
    assert.equal(dataEmLuanda(new Date("2026-11-10T22:59:59Z")), "2026-11-10");
    assert.equal(dataEmLuanda(new Date("2026-11-10T23:00:00Z")), "2026-11-11");
  });
});

describe("o duplo do phash diz o mesmo que o SQL", () => {
  it("fronteira em 6 e o proprio caso nao conta", async () => {
    const v = new VerificacoesEmMemoria();
    const base = 0x0123456789abcdefn;
    const hex = (n: bigint) => n.toString(16).padStart(16, "0");
    await v.inserir({ onboardingId: "outro", tipo: "bi", docRef: "x", sha256: "a".repeat(64), phash: hex(base), extraidoCifrado: null, flags: [], resultado: "pendente", versaoRegras: "1.0.0", custoMicroUsd: 0 });
    assert.equal(await v.phashVistoNoutroCaso("este", hex(base ^ 0b111111n), 6), true);
    assert.equal(await v.phashVistoNoutroCaso("este", hex(base ^ 0b1111111n), 6), false);
    assert.equal(await v.phashVistoNoutroCaso("outro", hex(base), 6), false);
  });
});

function comPedaco(png: Uint8Array, tipo: string, dados: Uint8Array): Uint8Array {
  const b = Buffer.from(png);
  const fim = b.indexOf("IEND") - 4;
  const p = Buffer.alloc(12 + dados.length);
  p.writeUInt32BE(dados.length, 0);
  p.write(tipo, 4, "latin1");
  Buffer.from(dados).copy(p, 8);
  p.writeUInt32BE(crc32(p.subarray(4, 8 + dados.length)), 8 + dados.length);
  return new Uint8Array(Buffer.concat([b.subarray(0, fim), p, b.subarray(fim)]));
}

describe("os metadados do PNG que a primeira versao nao lia", () => {
  it("o pedaco eXIf e o zTXt com Software sao lidos", () => {
    const base = codificarPngCinzento(pagina(6));
    const s = Buffer.from("GIMP 2.10\0", "latin1");
    const tiff = Buffer.alloc(8 + 2 + 12 + 4);
    tiff.write("MM\0*", 0, "latin1");
    tiff.writeUInt32BE(8, 4);
    tiff.writeUInt16BE(1, 8);
    tiff.writeUInt16BE(0x0131, 10);
    tiff.writeUInt16BE(2, 12);
    tiff.writeUInt32BE(s.length, 14);
    tiff.writeUInt32BE(tiff.length, 18);
    assert.deepEqual(descodificarPng(comPedaco(base, "eXIf", Buffer.concat([tiff, s])), 1e6).software, ["GIMP 2.10"]);
    const z = Buffer.concat([Buffer.from("Software\0\0", "latin1"), deflateSync(Buffer.from("Adobe Photoshop 25.0"))]);
    assert.deepEqual(descodificarPng(comPedaco(base, "zTXt", z), 1e6).software, ["Adobe Photoshop 25.0"]);
  });
});

describe("o TSV do tesseract", () => {
  it("agrupa palavras por linha e faz a media das confiancas, sem as de -1", () => {
    const tsv = [
      "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
      "4\t1\t1\t1\t1\t0\t0\t0\t10\t10\t-1\t",
      "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t96\tNIF:",
      "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t90\t0012345678",
      "5\t1\t1\t1\t2\t1\t0\t0\t10\t10\t-1\t",
      "5\t1\t1\t1\t2\t2\t0\t0\t10\t10\t80\tNOME:",
    ].join("\n");
    assert.deepEqual(linhasDoTsv(tsv), [
      { texto: "NIF: 0012345678", conf: 0.93 },
      { texto: "NOME:", conf: 0.8 },
    ]);
  });
});

describe("o antivirus (criterio 1)", () => {
  async function servidor(resposta: (recebido: Buffer) => string | null): Promise<{ porta: number; fechar: () => void; recebido: () => Buffer }> {
    let todo = Buffer.alloc(0);
    const s = createServer((c) => {
      c.on("data", (d) => {
        todo = Buffer.concat([todo, d]);
        if (todo.subarray(-4).equals(Buffer.alloc(4)) && todo.length > 14) {
          const r = resposta(todo);
          if (r === null) c.destroy();
          else c.end(r);
        }
      });
    });
    await new Promise<void>((ok) => s.listen(0, "127.0.0.1", ok));
    return { porta: (s.address() as { port: number }).port, fechar: () => s.close(), recebido: () => todo };
  }

  it("fala INSTREAM: comando, pedacos com tamanho big-endian e quatro zeros", async () => {
    const s = await servidor(() => "stream: OK\0");
    const ficheiro = randomBytes(100);
    try {
      assert.deepEqual(await new AntivirusClamd({ host: "127.0.0.1", porta: s.porta }).verificar(ficheiro), { limpo: true });
      const r = s.recebido();
      assert.equal(r.subarray(0, 10).toString("latin1"), "zINSTREAM\0");
      assert.equal(r.readUInt32BE(10), 100);
      assert.deepEqual(r.subarray(14, 114), ficheiro);
      assert.deepEqual(r.subarray(114), Buffer.alloc(4));
    } finally {
      s.fechar();
    }
  });

  it("uma assinatura encontrada e suja, e uma resposta desconhecida lanca", async () => {
    assert.deepEqual(veredictoDe("stream: Eicar-Signature FOUND\0"), { limpo: false, assinatura: "Eicar-Signature" });
    assert.throws(() => veredictoDe("INSTREAM size limit exceeded. ERROR\0"), AntivirusIndisponivelError);
  });

  it("falha fechada: ligacao recusada nunca e limpo", async () => {
    const s = await servidor(() => null);
    try {
      await assert.rejects(new AntivirusClamd({ host: "127.0.0.1", porta: s.porta }).verificar(randomBytes(10)), AntivirusIndisponivelError);
    } finally {
      s.fechar();
    }
  });
});

describe("a cifra do extraido_enc", () => {
  it("decifra com o mesmo contexto e recusa outro", async () => {
    const c = new CifraAesGcm(randomBytes(32));
    const claro = new TextEncoder().encode('{"nif":"0012345678"}');
    const cifrado = await c.cifrar(claro, "caso-a:nif");
    assert.ok(!Buffer.from(cifrado).includes(Buffer.from("0012345678")));
    assert.deepEqual(await c.decifrar(cifrado, "caso-a:nif"), claro);
    await assert.rejects(c.decifrar(cifrado, "caso-b:nif"));
  });
});
