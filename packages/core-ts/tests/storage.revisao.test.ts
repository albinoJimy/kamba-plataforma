/**
 * Regressões da revisão adversarial do KAM-011 (`docs/analises/ANALISE-09`).
 *
 * Cada teste aqui existe porque a revisão mostrou um defeito ou uma mutação que
 * sobrevivia. O identificador do achado está no nome; o espelho Python é
 * `libs/py-core/tests/test_storage_revisao.py`.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { createServer } from "node:net";
import type { AddressInfo } from "node:net";
import { test } from "node:test";

import type { Ambiente } from "../src/secrets/port.ts";
import { novaChave, prefixoDoTenant } from "../src/storage/chave.ts";
import {
  ConfigDeArmazenamentoError,
  DestinoSemApdRefError,
  type ProcessEnv,
  lerConfig,
} from "../src/storage/config.ts";
import { criarStorageFake } from "../src/storage/fake.ts";
import { ArmazenamentoPorTenant, lerInstante } from "../src/storage/guarda.ts";
import type { Motor } from "../src/storage/motor.ts";
import {
  ArmazenamentoIndisponivelError,
  type Ctx,
  MetaInvalidaError,
  RespostaDoMotorInvalidaError,
} from "../src/storage/port.ts";
import {
  MotorS3,
  PARTE_POR_OMISSAO,
  type RespostaHttp,
  desescaparXml,
} from "../src/storage/s3.ts";
import { assinatura } from "../src/storage/sigv4.ts";
import { CREDENCIAIS_DE_TESTE, montarS3EmMemoria } from "./apoio/alvos-storage.ts";

const A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa";
const ctxA: Ctx = { tenantId: A };
const PRAZO = new Date("2026-10-13T08:30:00.000Z");
const META = { contentType: "audio/ogg", classe: "audio", retainUntil: PRAZO } as const;

const BOM: ProcessEnv = {
  KAMBA_STORAGE_ENDPOINT: "http://seaweedfs:8333",
  KAMBA_STORAGE_BUCKET: "kamba-dev",
  KAMBA_STORAGE_REGION: "us-east-1",
  KAMBA_STORAGE_DESTINO_COUNTRY: "AO",
  KAMBA_STORAGE_DESTINO_PROVIDER: "seaweedfs_local",
};
const FORA: ProcessEnv = { ...BOM, KAMBA_STORAGE_DESTINO_COUNTRY: "ZA" };

async function* de(...blocos: unknown[]): AsyncIterable<Uint8Array> {
  for (const bloco of blocos) yield bloco as Uint8Array;
}
const xml = (corpo: string): RespostaHttp => ({ estado: 200, cabecalhos: {}, corpo: de(Buffer.from(corpo)) });

// --- A1 ----------------------------------------------------------------------

test("A1: um ambiente fora do domínio é recusado, e não tratado como «não é prod»", () => {
  for (const ambiente of ["PROD", "Prod", "prod ", " prod", "production", "producao", "", null, undefined, 7, "prod\n"]) {
    for (const env of [FORA, BOM]) {
      assert.throws(
        () => lerConfig({ ambiente: ambiente as Ambiente, env }),
        (erro: unknown) =>
          erro instanceof ConfigDeArmazenamentoError && /ambiente desconhecido/.test(erro.message),
        `ambiente ${JSON.stringify(ambiente)}`,
      );
    }
  }
  assert.throws(() => lerConfig({ env: FORA } as never), ConfigDeArmazenamentoError);
  // Os três canónicos continuam a valer.
  for (const ambiente of ["dev", "staging"] as const) {
    assert.equal(lerConfig({ ambiente, env: FORA }).avisos.length, 1);
  }
  assert.throws(() => lerConfig({ ambiente: "prod", env: FORA }), DestinoSemApdRefError);
});

// --- A5 e A6: instantes ------------------------------------------------------

test("A5/A6: só a forma canónica de um instante, e só datas que existem", () => {
  assert.equal(lerInstante("2026-10-13T08:30:00.000Z")?.getTime(), PRAZO.getTime());
  for (const texto of [
    "2026-02-30T00:00:00.000Z",
    "2026-01-01T24:00:00.000Z",
    "0000-01-01T00:00:00.000Z",
    "0999-01-01T00:00:00.000Z",
    "2026-10-13T08:30:00Z",
    "2026-10-13T08:30:00.000+00:00",
    "2026-10-13T08:30:00.000000Z",
    "+010000-01-01T00:00:00.000Z",
    "2026-10-13T08:30:00.000Z\n",
    "",
    null,
    7,
  ]) {
    assert.equal(lerInstante(texto), null, JSON.stringify(texto));
  }
});

test("A6: put recusa um prazo que o head não leria", async () => {
  const fake = criarStorageFake();
  const key = novaChave(ctxA, "audio");
  for (const retainUntil of [
    new Date(8.64e15),
    new Date("+010000-01-01T00:00:00.000Z"),
    new Date("-000001-01-01T00:00:00.000Z"),
    new Date("0999-12-31T00:00:00.000Z"),
  ]) {
    await assert.rejects(
      fake.storage.put(ctxA, key, new Uint8Array(1), { ...META, retainUntil }),
      MetaInvalidaError,
      String(retainUntil.getTime()),
    );
  }
  assert.equal(fake.total(), 0);
  for (const retainUntil of [new Date("1000-01-01T00:00:00.000Z"), new Date("9999-12-31T23:59:59.000Z")]) {
    const ref = await fake.storage.put(ctxA, key, new Uint8Array(1), { ...META, retainUntil });
    assert.equal((await fake.storage.head(ctxA, ref)).retainUntil.getTime(), retainUntil.getTime());
  }
});

test("A5: head recusa datas impossíveis vindas do servidor", async () => {
  let valor = "";
  const motor = {
    nome: "x",
    head: async () => ({ tamanho: 1, contentType: "audio/ogg", metadados: { classe: "audio", "retain-until": valor } }),
  } as unknown as Motor;
  const storage = new ArmazenamentoPorTenant(motor);
  const ref = { key: novaChave(ctxA, "audio"), tamanho: 1, sha256: null };
  for (valor of ["2026-02-30T00:00:00.000Z", "2026-01-01T24:00:00.000Z", "0000-01-01T00:00:00.000Z", "2026-10-13T08:30:00Z"]) {
    await assert.rejects(storage.head(ctxA, ref), RespostaDoMotorInvalidaError, valor);
  }
});

// --- A5: corpo ---------------------------------------------------------------

test("A5: um bloco que não é de bytes é recusado pela porta, e não somado como texto", async () => {
  for (const storage of [criarStorageFake().storage, montarS3EmMemoria().alvo.storage]) {
    for (const corpo of [de("abc"), de(Buffer.from("ab"), "c"), de(Buffer.from("ab"), 7), de(null), de([1, 2, 3])]) {
      await assert.rejects(
        storage.put(ctxA, novaChave(ctxA, "audio"), corpo, META),
        MetaInvalidaError,
        storage.nome,
      );
    }
    assert.deepEqual(await storage.list(ctxA, prefixoDoTenant(ctxA)), []);
    const ref = await storage.put(ctxA, novaChave(ctxA, "audio"), de(Buffer.from("ab"), new Uint8Array([99])), META);
    const blocos: Uint8Array[] = [];
    for await (const bloco of await storage.get(ctxA, ref)) blocos.push(bloco);
    assert.equal(Buffer.concat(blocos).toString(), "abc");
  }
});

// --- A5: configuração igual dos dois lados -----------------------------------

test("A5: endpoints de fronteira têm o mesmo veredicto que do lado Python", () => {
  for (const endpoint of [
    "http://h/?", "http://h/#", "http:h", "http://h/./", "http:\\\\h", "http://h:0",
    "http://exämple.com", "http://h.", "http://a_b:9000", "HTTP://h", "http://H",
    "http://h:65536", "http://h:123456", "http://h//", "http://[::1", "http://-h",
    "http://h:", "http://h:80:80", "http://u@h", "http://h /",
  ]) {
    assert.throws(
      () => lerConfig({ ambiente: "dev", env: { ...BOM, KAMBA_STORAGE_ENDPOINT: endpoint } }),
      ConfigDeArmazenamentoError,
      endpoint,
    );
  }
  const aceites: Record<string, string> = {
    "http://h": "http://h",
    "http://h/": "http://h",
    "http://h:80": "http://h",
    "https://h:443/": "https://h",
    "http://h:443": "http://h:443",
    "https://s3.exemplo.co.ao:8443": "https://s3.exemplo.co.ao:8443",
    "http://127.0.0.1:8333": "http://127.0.0.1:8333",
    "http://0x7f.1": "http://0x7f.1",
    "http://[::1]:8333": "http://[::1]:8333",
    "http://h:65535": "http://h:65535",
  };
  for (const [endpoint, esperado] of Object.entries(aceites)) {
    assert.equal(
      lerConfig({ ambiente: "dev", env: { ...BOM, KAMBA_STORAGE_ENDPOINT: endpoint } }).endpoint,
      esperado,
    );
  }
});

test("A5: só espaço, tabulação e mudança de linha se tiram das pontas de um valor", () => {
  assert.equal(
    lerConfig({ ambiente: "dev", env: { ...BOM, KAMBA_STORAGE_DESTINO_COUNTRY: " \tAO\r\n" } }).destino.country,
    "AO",
  );
  for (const country of ["AO\u001f", "AO﻿", " AO", "AO ", "AO\u000b"]) {
    assert.throws(
      () => lerConfig({ ambiente: "dev", env: { ...BOM, KAMBA_STORAGE_DESTINO_COUNTRY: country } }),
      ConfigDeArmazenamentoError,
      JSON.stringify(country),
    );
  }
});

// --- A5: fake ----------------------------------------------------------------

test("A5: o fake recusa assinatura em maiúsculas, com lixo, e expira fraccionado", async () => {
  const fake = criarStorageFake();
  const ref = await fake.storage.put(ctxA, novaChave(ctxA, "audio"), Buffer.from("abc"), META);
  const url = await fake.storage.signUrl(ctxA, ref, { ttlSeconds: 60 });
  const m = /^(.*)\?expira=([0-9]+)&assinatura=([0-9a-f]+)$/.exec(url);
  assert.ok(m !== null);
  const [, base, expira, sig] = m as unknown as [string, string, string, string];
  assert.equal((await fake.buscar(url)).estado, 200);
  for (const [e, s] of [
    [expira, sig.toUpperCase()],
    [expira, `${sig}zz`],
    [expira, `${sig}00`],
    [`${expira}.0`, sig],
    [`+${expira}`, sig],
    [` ${expira}`, sig],
  ]) {
    assert.equal((await fake.buscar(`${base}?expira=${e}&assinatura=${s}`)).estado, 403, `${e} ${s?.slice(0, 8)}`);
  }
});

// --- A9 ----------------------------------------------------------------------

test("A9: um ponto de código impossível no XML fica como veio, e não rebenta", async () => {
  for (const texto of ["&#x110000;", "&#1114112;", "&#xFFFFFFFFFFFF;", "&#99999999999999999999;"]) {
    assert.equal(desescaparXml(texto), texto);
  }
  assert.equal(desescaparXml("&#x41;&#66;"), "AB");

  const { alvo, servidor } = montarS3EmMemoria();
  servidor.interceptar = () =>
    xml(
      "<ListBucketResult><IsTruncated>false</IsTruncated><Contents>" +
        "<Key>&#x110000;</Key><Size>1</Size></Contents></ListBucketResult>",
    );
  await assert.rejects(alvo.storage.list(ctxA, prefixoDoTenant(ctxA)), RespostaDoMotorInvalidaError);
});

// --- mutações que sobreviviam ------------------------------------------------

test("R10: o limite pedido chega ao servidor como max-keys", async () => {
  const { alvo, servidor } = montarS3EmMemoria();
  for (let i = 0; i < 3; i += 1) await alvo.storage.put(ctxA, novaChave(ctxA, "audio"), new Uint8Array(1), META);
  servidor.pedidos.length = 0;
  await alvo.storage.list(ctxA, prefixoDoTenant(ctxA), { limite: 7 });
  await alvo.storage.list(ctxA, prefixoDoTenant(ctxA));
  await alvo.storage.list(ctxA, prefixoDoTenant(ctxA), { limite: 5000 });
  assert.deepEqual(
    servidor.pedidos.map((p) => new URL(p.url).searchParams.get("max-keys")),
    ["7", "1000", "1000"],
  );
});

test("R14: um 404 numa listagem não é «objecto inexistente»", async () => {
  const { alvo, servidor } = montarS3EmMemoria();
  for (const corpo of ["<Error><Code>NoSuchKey</Code></Error>", ""]) {
    servidor.interceptar = () => ({ estado: 404, cabecalhos: {}, corpo: corpo === "" ? de() : de(Buffer.from(corpo)) });
    await assert.rejects(
      alvo.storage.list(ctxA, prefixoDoTenant(ctxA)),
      (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.estado === 404,
    );
  }
});

test("R15: os espaços de um cabeçalho são normalizados antes de assinar", () => {
  const assinar = (valor: string): string =>
    assinatura(
      {
        metodo: "GET",
        url: new URL("http://s3.teste.invalid:8333/kamba-teste/t/x"),
        cabecalhos: { host: "s3.teste.invalid:8333", "content-type": valor },
        hashDoCorpo: "UNSIGNED-PAYLOAD",
        regiao: "ao-teste-1",
        quando: "20261012T090000Z",
      },
      "valor-de-teste",
    ).assinatura;
  assert.equal(assinar("audio/ogg;  codecs=opus"), assinar("audio/ogg; codecs=opus"));
  assert.equal(assinar("  audio/ogg; codecs=opus \t"), assinar("audio/ogg; codecs=opus"));
  assert.notEqual(assinar("audio/ogg;codecs=opus"), assinar("audio/ogg; codecs=opus"));
  // Valor fixado, igual ao do lado Python.
  assert.equal(
    assinar("audio/ogg;  codecs=opus"),
    "18251ed12bcdbe6d47d12cd6d986d555a3f9e592bd91d15b1b6c6d54adcad741",
  );
});

test("R26: com a parte por omissão, 10 MB vão num pedido e 25 MB em duas partes", async () => {
  assert.equal(PARTE_POR_OMISSAO, 16 * 1024 * 1024);
  const { alvo, servidor } = montarS3EmMemoria();
  await alvo.storage.put(ctxA, novaChave(ctxA, "audio"), randomBytes(10 * 1024 * 1024), META);
  assert.deepEqual(servidor.pedidos.map((p) => p.metodo), ["PUT"]);
  servidor.pedidos.length = 0;
  await alvo.storage.put(ctxA, novaChave(ctxA, "audio"), randomBytes(25 * 1024 * 1024), META);
  assert.deepEqual(servidor.pedidos.map((p) => p.metodo), ["POST", "PUT", "PUT", "POST"]);
  assert.equal(servidor.pedidos[1]?.corpo?.length, 16 * 1024 * 1024);
});

test("R31: um servidor que não responde não pendura o pedido", async () => {
  // Aceita a ligação e cala-se.
  const sockets: { destroy(): void }[] = [];
  const mudo = createServer((socket) => sockets.push(socket));
  await new Promise<void>((pronto) => mudo.listen(0, "127.0.0.1", pronto));
  try {
    const motor = new MotorS3({
      endpoint: `http://127.0.0.1:${(mudo.address() as AddressInfo).port}`,
      bucket: "kamba-teste",
      regiao: "ao-teste-1",
      credenciais: async () => CREDENCIAIS_DE_TESTE,
      tempoLimiteMs: 300,
    });
    const antes = Date.now();
    await assert.rejects(motor.head(`t/${A}/audio/x`), ArmazenamentoIndisponivelError);
    assert.ok(Date.now() - antes < 10_000);
  } finally {
    for (const socket of sockets) socket.destroy();
    await new Promise((fechado) => mudo.close(fechado));
  }
});

test("R36: o mês da chave é o UTC, seja qual for o fuso da máquina", () => {
  const guardado = process.env.TZ;
  try {
    // 1 de Dezembro, 00:30 UTC: em São Paulo ainda é Novembro.
    // 30 de Novembro, 23:30 UTC: em Tóquio já é Dezembro.
    for (const tz of ["America/Sao_Paulo", "Asia/Tokyo", "Africa/Luanda", "UTC"]) {
      process.env.TZ = tz;
      assert.match(novaChave(ctxA, "audio", new Date("2026-12-01T00:30:00.000Z")), /\/2026\/12\//, tz);
      assert.match(novaChave(ctxA, "audio", new Date("2026-11-30T23:30:00.000Z")), /\/2026\/11\//, tz);
      assert.match(novaChave(ctxA, "audio", new Date("2027-01-01T00:30:00.000Z")), /\/2027\/01\//, tz);
    }
  } finally {
    if (guardado === undefined) delete process.env.TZ;
    else process.env.TZ = guardado;
  }
});

test("a query vai na rede em RFC 3986, como do lado Python", async () => {
  const { alvo, servidor } = montarS3EmMemoria();
  let primeira = true;
  servidor.interceptar = () => {
    if (primeira) {
      primeira = false;
      return xml(
        "<ListBucketResult><IsTruncated>true</IsTruncated>" +
          "<NextContinuationToken>a b+c~*/=</NextContinuationToken></ListBucketResult>",
      );
    }
    return xml("<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>");
  };
  await alvo.storage.list(ctxA, prefixoDoTenant(ctxA));
  assert.ok(servidor.pedidos[1]?.url.includes("continuation-token=a%20b%2Bc~%2A%2F%3D"), servidor.pedidos[1]?.url);
  assert.ok(servidor.pedidos[0]?.url.includes(`prefix=t%2F${A}%2F`));
});
