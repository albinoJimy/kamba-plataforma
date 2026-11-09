/**
 * O aceite contratual versionado (KAM-090): hash canónico, versão vigente,
 * evidência, recibos de abertura, o caso de uso do aceite e a prova.
 *
 * O caso adversarial «aceite sem abrir os documentos (cliente adulterado)» é
 * deste ficheiro e não da base: a prova de abertura é um recibo que o servidor
 * emite ao servir o texto. Os outros três (versão antiga, OTP reutilizado,
 * texto alterado) são da base e estão em `db/tests/test_contratos_schema.py`.
 */

import assert from "node:assert/strict";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import {
  TIPOS,
  type Documento,
  type LinhaDeAceite,
  type PedidoDeAceite,
  type PortasDoAceite,
  type Tipo,
  ProvaInconsistenteError,
  aceitar,
  canonizar,
  compararVersoes,
  emitirRecibo,
  evidencia,
  exportarProva,
  hashDoPrefixoDeIp,
  reciboValido,
  sha256DoConteudo,
  versaoValida,
  vigente,
} from "../src/contratos/index.ts";

const AGORA = new Date("2026-11-09T12:00:00Z");

/** O vetor da evidência, calculado em `hashlib` (ver o ensaio que o usa). */
const VETOR_DA_EVIDENCIA = "4936cf07cef2053dda27d129a3540eaa22f4bf4907e349ddd3464ec373b9646c";

function documento(tipo: Tipo, versao: string, vigenteDesde: string): Documento {
  return {
    documentId: randomUUID(),
    tipo,
    versao,
    sha256: sha256DoConteudo(canonizar(`${tipo} ${versao}`)),
    vigenteDesde: new Date(vigenteDesde),
  };
}

describe("contratos: o texto canónico e a versão", () => {
  it("canoniza NFC, fins de linha e um único \\n final", () => {
    const decomposto = "Cláusula\r\nsegunda\r\n\r\n";
    assert.equal(canonizar(decomposto), "Cláusula\nsegunda\n");
    assert.equal(canonizar("a\rb"), "a\nb\n");
    assert.throws(() => canonizar(" \r\n\n"));
  });

  it("o sha256 é o do texto canónico em UTF-8", () => {
    const texto = canonizar("Termos de serviço");
    assert.deepEqual(sha256DoConteudo(texto), createHash("sha256").update(Buffer.from(texto, "utf8")).digest());
  });

  it("SemVer sem sufixos, comparado número a número", () => {
    assert.equal(versaoValida("1.0.0"), true);
    for (const v of ["1.0", "v1.0.0", "1.0.0-rc1", "01.0.0", "1.0.0+x"]) assert.equal(versaoValida(v), false, v);
    assert.equal(compararVersoes("1.10.0", "1.9.0"), 1);
    assert.equal(compararVersoes("2.0.0", "2.0.0"), 0);
    assert.equal(compararVersoes("0.9.9", "1.0.0"), -1);
    assert.throws(() => compararVersoes("1.0", "1.0.0"));
  });

  it("a vigente é a mais recente que não está no futuro, por tipo", () => {
    const v1 = documento("dpa", "1.0.0", "2026-01-01T00:00:00Z");
    const v2 = documento("dpa", "1.1.0", "2026-06-01T00:00:00Z");
    const futura = documento("dpa", "2.0.0", "2027-01-01T00:00:00Z");
    const outroTipo = documento("tos", "9.0.0", "2026-10-01T00:00:00Z");
    assert.equal(vigente([futura, v1, outroTipo, v2], "dpa", AGORA), v2);
    assert.equal(vigente([futura], "dpa", AGORA), null);
    // Na fronteira, vigora: a base usa `vigente_desde <= now()`.
    assert.equal(vigente([v2], "dpa", new Date("2026-06-01T00:00:00Z")), v2);
  });
});

describe("contratos: a evidência do critério 3", () => {
  it("é sha256 dos quatro campos de largura fixa, pela ordem do critério", () => {
    const doc = randomBytes(32);
    const signatario = "11111111-2222-4333-8444-555555555555";
    const otp = "66666666-7777-4888-9999-aaaaaaaaaaaa";
    const micros = 1_762_689_600_123_456n;
    const instante = Buffer.alloc(8);
    instante.writeBigInt64BE(micros);
    const esperado = createHash("sha256")
      .update(Buffer.concat([doc, Buffer.from(signatario.replace(/-/g, ""), "hex"), instante, Buffer.from(otp.replace(/-/g, ""), "hex")]))
      .digest();
    assert.deepEqual(evidencia({ docSha256: doc, signatarioRef: signatario, aceiteEmMicros: micros, otpChallengeId: otp }), esperado);
  });

  it("bate o vetor fixo que a bateria da base também confronta", () => {
    // O mesmo vetor está em `db/tests/test_contratos_schema.py`, contra a
    // `platform.contrato_evidencia` instalada: é o que liga as duas
    // implementações sem que nenhuma copie a outra.
    const h = evidencia({
      docSha256: Buffer.from(Array.from({ length: 32 }, (_v, i) => i)),
      signatarioRef: "11111111-2222-4333-8444-555555555555",
      aceiteEmMicros: 1_762_689_600_123_456n,
      otpChallengeId: "66666666-7777-4888-9999-aaaaaaaaaaaa",
    });
    assert.equal(h.toString("hex"), VETOR_DA_EVIDENCIA);
  });

  it("muda com cada campo, e recusa formas impossíveis", () => {
    const base = { docSha256: randomBytes(32), signatarioRef: randomUUID(), aceiteEmMicros: 1n, otpChallengeId: randomUUID() };
    const h = evidencia(base);
    assert.notDeepEqual(evidencia({ ...base, aceiteEmMicros: 2n }), h);
    assert.notDeepEqual(evidencia({ ...base, otpChallengeId: randomUUID() }), h);
    assert.notDeepEqual(evidencia({ ...base, signatarioRef: randomUUID() }), h);
    assert.throws(() => evidencia({ ...base, docSha256: randomBytes(31) }));
    assert.throws(() => evidencia({ ...base, signatarioRef: "nao-e-uuid" }));
  });
});

describe("contratos: o recibo de abertura", () => {
  const chave = randomBytes(32);
  const abertura = { onboardingId: randomUUID(), documentId: randomUUID(), sha256: randomBytes(32) };

  it("vale para o caso e o texto que o servidor serviu, e para mais nenhum", () => {
    const recibo = emitirRecibo(chave, abertura);
    assert.equal(reciboValido(recibo, abertura, [chave, null]), true);
    assert.equal(reciboValido(recibo, { ...abertura, onboardingId: randomUUID() }, [chave]), false);
    assert.equal(reciboValido(recibo, { ...abertura, documentId: randomUUID() }, [chave]), false);
    assert.equal(reciboValido(recibo, { ...abertura, sha256: randomBytes(32) }, [chave]), false);
    assert.equal(reciboValido(recibo, abertura, [randomBytes(32)]), false);
  });

  it("aceita as duas chaves do anel, e recusa formas que não são recibo", () => {
    const antiga = randomBytes(32);
    assert.equal(reciboValido(emitirRecibo(antiga, abertura), abertura, [chave, antiga]), true);
    for (const lixo of [undefined, "", "x".repeat(43), 42, "a.b"]) {
      assert.equal(reciboValido(lixo, abertura, [chave]), false);
    }
    assert.throws(() => emitirRecibo(randomBytes(16), abertura));
  });
});

/** Portas falsas: os documentos vigentes, um OTP que acerta, e um escritor que guarda. */
function montar(opcoes: { veredicto?: string; desafioId?: string | null } = {}) {
  const chave = randomBytes(32);
  const documentos = TIPOS.map((tipo) => documento(tipo, "1.0.0", "2026-01-01T00:00:00Z"));
  const gravadas: LinhaDeAceite[][] = [];
  let verificacoes = 0;
  const portas: PortasDoAceite = {
    documentos: { publicados: async () => documentos },
    otp: {
      verificar: async () => {
        verificacoes += 1;
        return {
          veredicto: opcoes.veredicto ?? "acertou",
          desafioId: opcoes.desafioId === undefined ? randomUUID() : opcoes.desafioId,
        };
      },
    },
    escritor: { gravar: async (linhas) => void gravadas.push([...linhas]) },
    anel: [chave],
    relogio: () => AGORA,
  };
  const onboardingId = randomUUID();
  const recibos: Partial<Record<Tipo, string>> = {};
  for (const d of documentos) {
    recibos[d.tipo] = emitirRecibo(chave, { onboardingId, documentId: d.documentId, sha256: d.sha256 });
  }
  const pedido: PedidoDeAceite = {
    onboardingId,
    tenantId: randomUUID(),
    signatarioRef: randomUUID(),
    codigoOtp: "123456",
    declaracaoDePoderes: true,
    recibos,
    ipPrefixHash: null,
  };
  return { portas, pedido, documentos, gravadas, verificacoes: () => verificacoes };
}

describe("contratos: o aceite (critérios 2, 3 e 5)", () => {
  it("grava os quatro documentos vigentes com o id do desafio do OTP", async () => {
    const { portas, pedido, documentos, gravadas } = montar({ desafioId: "0a0a0a0a-0b0b-4c0c-8d0d-0e0e0e0e0e0e" });
    const resultado = await aceitar(pedido, portas);
    assert.equal(resultado.tipo, "aceite");
    assert.equal(gravadas.length, 1);
    const linhas = gravadas[0] ?? [];
    assert.deepEqual(linhas.map((l) => l.documentId), documentos.map((d) => d.documentId));
    for (const linha of linhas) {
      assert.equal(linha.otpChallengeId, "0a0a0a0a-0b0b-4c0c-8d0d-0e0e0e0e0e0e");
      assert.equal(linha.signatarioRef, pedido.signatarioRef);
    }
  });

  it("cliente adulterado: sem recibo de um dos três, recusa e não gasta o OTP", async () => {
    for (const tipo of ["dpa", "privacidade", "tos"] as const) {
      const { portas, pedido, gravadas, verificacoes } = montar();
      const resto: Partial<Record<Tipo, unknown>> = { ...pedido.recibos };
      delete resto[tipo];
      const resultado = await aceitar({ ...pedido, recibos: resto }, portas);
      assert.deepEqual(resultado, { tipo: "recusado", motivo: "documento_por_abrir", documento: tipo });
      assert.equal(gravadas.length, 0);
      assert.equal(verificacoes(), 0, "o OTP nao se gasta antes de os documentos estarem abertos");
    }
  });

  it("cliente adulterado: o recibo de outro caso ou de outra versão não serve", async () => {
    const um = montar();
    const outro = montar();
    const resultado = await aceitar({ ...um.pedido, recibos: outro.pedido.recibos }, um.portas);
    assert.equal(resultado.tipo, "recusado");
  });

  it("sem declaração de poderes literal, recusa", async () => {
    for (const declaracao of [false, "true", 1, undefined]) {
      const { portas, pedido, gravadas } = montar();
      const resultado = await aceitar({ ...pedido, declaracaoDePoderes: declaracao }, portas);
      assert.deepEqual(resultado, { tipo: "recusado", motivo: "sem_declaracao" });
      assert.equal(gravadas.length, 0);
    }
  });

  it("OTP que não acerta, ou sem id de desafio, recusa", async () => {
    for (const opcoes of [{ veredicto: "errou" }, { veredicto: "expirado" }, { desafioId: null }]) {
      const { portas, pedido, gravadas } = montar(opcoes);
      assert.deepEqual(await aceitar(pedido, portas), { tipo: "recusado", motivo: "otp" });
      assert.equal(gravadas.length, 0);
    }
  });

  it("sem versão vigente de um dos quatro tipos, o gate fecha antes de tudo", async () => {
    const { portas, pedido } = montar();
    const semLista: PortasDoAceite = {
      ...portas,
      documentos: { publicados: async () => (await portas.documentos.publicados()).filter((d) => d.tipo !== "subprocessadores") },
    };
    assert.deepEqual(await aceitar(pedido, semLista), {
      tipo: "recusado",
      motivo: "sem_versao_vigente",
      documento: "subprocessadores",
    });
  });
});

describe("contratos: o prefixo do IP", () => {
  const chave = randomBytes(32);
  it("o mesmo /24 e o mesmo /48 dão o mesmo resumo; outro prefixo, outro", () => {
    assert.deepEqual(hashDoPrefixoDeIp("192.0.2.10", chave), hashDoPrefixoDeIp("192.0.2.200", chave));
    assert.notDeepEqual(hashDoPrefixoDeIp("192.0.2.10", chave), hashDoPrefixoDeIp("192.0.3.10", chave));
    assert.deepEqual(hashDoPrefixoDeIp("2001:db8:1::1", chave), hashDoPrefixoDeIp("2001:0db8:0001:ffff::9", chave));
    assert.notDeepEqual(hashDoPrefixoDeIp("2001:db8:1::1", chave), hashDoPrefixoDeIp("2001:db8:2::1", chave));
    assert.equal(hashDoPrefixoDeIp("nao-e-ip", chave), null);
    assert.equal(hashDoPrefixoDeIp("192.0.2.10", chave)?.length, 32);
  });
});

describe("contratos: a exportação da prova (critério 9)", () => {
  function linha(tipo: Tipo) {
    const campos = { docSha256: randomBytes(32), signatarioRef: randomUUID(), aceiteEmMicros: 1_762_689_600_123_456n, otpChallengeId: randomUUID() };
    return { documentId: randomUUID(), tipo, versao: "1.0.0", ...campos, evidenceHash: evidencia(campos) };
  }

  it("verifica cada evidência, ordena por tipo e resume o documento", () => {
    const linhas = [linha("tos"), linha("dpa")];
    const prova = exportarProva("caso", linhas);
    assert.deepEqual(prova.aceites.map((a) => a.tipo), ["dpa", "tos"]);
    assert.equal(prova.aceites[0]?.aceite_em, "2025-11-09T12:00:00.123456Z");
    assert.equal(prova.sha256, createHash("sha256").update(JSON.stringify(prova.aceites)).digest("hex"));
  });

  it("uma evidência que não se reproduz não se exporta", () => {
    const adulterada = { ...linha("dpa"), evidenceHash: randomBytes(32) };
    assert.throws(() => exportarProva("caso", [adulterada]), ProvaInconsistenteError);
  });
});
