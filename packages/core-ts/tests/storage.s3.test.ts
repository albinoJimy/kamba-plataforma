/**
 * O motor S3 por dentro (KAM-011): assinatura, envio em partes, paginação e
 * tradução de erros.
 *
 * A bateria de contrato prova o comportamento visto pela porta. Aqui prova-se o
 * que ela não vê: **que pedidos** o motor faz, e o que faz quando o servidor
 * responde mal. O servidor é o de `apoio/s3-em-memoria.ts`, com um gancho para
 * forçar respostas.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { test } from "node:test";

import { novaChave, prefixoDoTenant } from "../src/storage/chave.ts";
import {
  ArmazenamentoIndisponivelError,
  type Ctx,
  ListagemTruncadaError,
  ObjectoInexistenteError,
} from "../src/storage/port.ts";
import {
  MotorS3,
  PARTE_MINIMA,
  type RespostaHttp,
  desescaparXml,
  elementoXml,
  transportePorFetch,
} from "../src/storage/s3.ts";
import {
  assinarPedido,
  assinatura,
  caminhoCanonico,
  codificar,
  dataAmz,
  presignarGet,
  queryCanonica,
} from "../src/storage/sigv4.ts";
import {
  CONFIG_DE_TESTE,
  CREDENCIAIS_DE_TESTE,
  montarS3EmMemoria,
} from "./apoio/alvos-storage.ts";

const ctx: Ctx = { tenantId: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa" };
const META = {
  contentType: "audio/ogg",
  classe: "audio",
  retainUntil: new Date("2026-10-13T08:30:00.000Z"),
} as const;

async function* nada(): AsyncIterable<Uint8Array> {}
async function* texto(valor: string): AsyncIterable<Uint8Array> {
  yield Buffer.from(valor, "utf8");
}
const resposta = (estado: number, corpo = "", cabecalhos: Record<string, string> = {}): RespostaHttp => ({
  estado,
  cabecalhos,
  corpo: corpo === "" ? nada() : texto(corpo),
});
const erroXml = (codigo: string): string => `<Error><Code>${codigo}</Code></Error>`;

function metodos(servidor: { pedidos: readonly { metodo: string; url: string }[] }): string[] {
  return servidor.pedidos.map((p) => {
    const q = new URL(p.url).searchParams;
    if (q.has("uploads")) return `${p.metodo} uploads`;
    if (q.has("partNumber")) return `${p.metodo} parte ${q.get("partNumber")}`;
    if (q.has("uploadId")) return `${p.metodo} envio`;
    return p.metodo;
  });
}

// --- envio em partes ---------------------------------------------------------

test("a fronteira do envio em partes: até uma parte, um pedido; um byte acima, duas", async () => {
  const exacto = montarS3EmMemoria({ tamanhoDaParte: PARTE_MINIMA });
  await exacto.alvo.storage.put(ctx, novaChave(ctx, "audio"), randomBytes(PARTE_MINIMA), META);
  assert.deepEqual(metodos(exacto.servidor), ["PUT"]);

  const acima = montarS3EmMemoria({ tamanhoDaParte: PARTE_MINIMA });
  const bytes = randomBytes(PARTE_MINIMA + 1);
  const ref = await acima.alvo.storage.put(ctx, novaChave(ctx, "audio"), bytes, META);
  assert.deepEqual(metodos(acima.servidor), ["POST uploads", "PUT parte 1", "PUT parte 2", "POST envio"]);
  assert.equal(acima.servidor.pedidos[1]?.corpo?.length, PARTE_MINIMA);
  assert.equal(acima.servidor.pedidos[2]?.corpo?.length, 1);
  assert.equal(ref.tamanho, PARTE_MINIMA + 1);
  assert.deepEqual(Buffer.from(acima.servidor.objectos.get(ref.key)?.bytes ?? []), bytes);
});

test("três partes, com o fluxo cortado em blocos que não coincidem com as partes", async () => {
  const { alvo, servidor } = montarS3EmMemoria({ tamanhoDaParte: PARTE_MINIMA });
  const bytes = randomBytes(2 * PARTE_MINIMA + 12345);
  async function* blocos(): AsyncIterable<Uint8Array> {
    for (let i = 0; i < bytes.length; i += 1_000_003) yield bytes.subarray(i, i + 1_000_003);
  }
  const ref = await alvo.storage.put(ctx, novaChave(ctx, "audio"), blocos(), META);
  assert.deepEqual(metodos(servidor), [
    "POST uploads",
    "PUT parte 1",
    "PUT parte 2",
    "PUT parte 3",
    "POST envio",
  ]);
  assert.deepEqual(
    servidor.pedidos.slice(1, 4).map((p) => p.corpo?.length),
    [PARTE_MINIMA, PARTE_MINIMA, 12345],
  );
  assert.deepEqual(Buffer.from(servidor.objectos.get(ref.key)?.bytes ?? []), bytes);
  // Os metadados vão na abertura do envio, e ficam no objecto.
  const guardado = servidor.objectos.get(ref.key)?.cabecalhos ?? {};
  assert.equal(guardado["x-amz-meta-classe"], "audio");
  assert.equal(guardado["x-amz-meta-retain-until"], "2026-10-13T08:30:00.000Z");
  assert.equal(guardado["content-type"], "audio/ogg");
});

test("um envio em partes que falha a meio é abortado, e o erro que sobe é o original", async () => {
  const { alvo, servidor } = montarS3EmMemoria({ tamanhoDaParte: PARTE_MINIMA });
  servidor.interceptar = (pedido) =>
    new URL(pedido.url).searchParams.get("partNumber") === "2"
      ? resposta(500, erroXml("InternalError"))
      : null;
  await assert.rejects(
    alvo.storage.put(ctx, novaChave(ctx, "audio"), randomBytes(PARTE_MINIMA + 10), META),
    (erro: unknown) =>
      erro instanceof ArmazenamentoIndisponivelError &&
      erro.operacao === "put" &&
      erro.estado === 500 &&
      erro.codigo === "InternalError",
  );
  assert.deepEqual(metodos(servidor), ["POST uploads", "PUT parte 1", "PUT parte 2", "DELETE envio"]);
  assert.equal(servidor.envios.size, 0, "o envio não ficou aberto");
  assert.equal(servidor.objectos.size, 0, "nada ficou escrito");
});

test("se até o aborto falhar, o erro que sobe continua a ser o original", async () => {
  const { alvo, servidor } = montarS3EmMemoria({ tamanhoDaParte: PARTE_MINIMA });
  servidor.interceptar = (pedido) => {
    const q = new URL(pedido.url).searchParams;
    if (q.get("partNumber") === "1") return resposta(503, erroXml("SlowDown"));
    if (pedido.metodo === "DELETE") throw new Error("rede em baixo");
    return null;
  };
  await assert.rejects(
    alvo.storage.put(ctx, novaChave(ctx, "audio"), randomBytes(PARTE_MINIMA + 10), META),
    (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.codigo === "SlowDown",
  );
});

test("respostas incompletas do servidor num envio em partes são erro, não sucesso", async () => {
  const bytes = randomBytes(PARTE_MINIMA + 10);
  const casos: readonly (readonly [string, (p: { metodo: string; url: string }) => RespostaHttp | null, string])[] = [
    [
      "abertura sem UploadId",
      (p) => (new URL(p.url).searchParams.has("uploads") ? resposta(200, "<Resultado/>") : null),
      "SemUploadId",
    ],
    [
      "parte sem ETag",
      (p) => (new URL(p.url).searchParams.has("partNumber") ? resposta(200) : null),
      "SemETag",
    ],
    [
      "fecho com 200 e erro no corpo",
      (p) =>
        p.metodo === "POST" && new URL(p.url).searchParams.has("uploadId")
          ? resposta(200, erroXml("InternalError"))
          : null,
      "InternalError",
    ],
  ];
  for (const [nome, interceptar, codigo] of casos) {
    const { alvo, servidor } = montarS3EmMemoria({ tamanhoDaParte: PARTE_MINIMA });
    servidor.interceptar = interceptar;
    await assert.rejects(
      alvo.storage.put(ctx, novaChave(ctx, "audio"), bytes, META),
      (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.codigo === codigo,
      nome,
    );
    assert.equal(servidor.objectos.size, 0, nome);
  }
});

test("uma parte abaixo de 5 MiB não se configura", () => {
  for (const tamanhoDaParte of [PARTE_MINIMA - 1, 0, 1.5 * PARTE_MINIMA + 0.5, Number.NaN]) {
    assert.throws(() => montarS3EmMemoria({ tamanhoDaParte }), RangeError);
  }
});

// --- listagem ----------------------------------------------------------------

test("a listagem segue as páginas até ao fim", async () => {
  const { alvo, servidor } = montarS3EmMemoria({ pagina: 2 });
  const refs = [];
  for (let i = 0; i < 5; i += 1) {
    refs.push(await alvo.storage.put(ctx, novaChave(ctx, "audio"), randomBytes(i + 1), META));
  }
  servidor.pedidos.length = 0;
  const lista = await alvo.storage.list(ctx, prefixoDoTenant(ctx));
  assert.deepEqual(lista.map((r) => r.key), refs.map((r) => r.key).sort());
  assert.equal(servidor.pedidos.length, 3, "5 chaves em páginas de 2 são 3 pedidos");
  assert.equal(new URL(servidor.pedidos[0]!.url).searchParams.get("prefix"), prefixoDoTenant(ctx));
  assert.ok(new URL(servidor.pedidos[1]!.url).searchParams.has("continuation-token"));

  // O limite também se respeita através das páginas.
  await assert.rejects(alvo.storage.list(ctx, prefixoDoTenant(ctx), { limite: 4 }), ListagemTruncadaError);
  await assert.rejects(alvo.storage.list(ctx, prefixoDoTenant(ctx), { limite: 3 }), ListagemTruncadaError);
  assert.equal((await alvo.storage.list(ctx, prefixoDoTenant(ctx), { limite: 5 })).length, 5);
});

test("uma listagem que o motor não consegue ler até ao fim é erro, não meia listagem", async () => {
  const casos: readonly (readonly [string, string, string])[] = [
    [
      "truncada sem continuação",
      `<ListBucketResult><IsTruncated>true</IsTruncated><Contents><Key>t/${ctx.tenantId}/audio/x</Key><Size>1</Size></Contents></ListBucketResult>`,
      "SemContinuacao",
    ],
    [
      "entrada sem tamanho",
      `<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>t/${ctx.tenantId}/audio/x</Key></Contents></ListBucketResult>`,
      "ListagemIlegivel",
    ],
    [
      "entrada sem chave",
      "<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Size>1</Size></Contents></ListBucketResult>",
      "ListagemIlegivel",
    ],
  ];
  for (const [nome, xml, codigo] of casos) {
    const { alvo, servidor } = montarS3EmMemoria();
    servidor.interceptar = () => resposta(200, xml);
    await assert.rejects(
      alvo.storage.list(ctx, prefixoDoTenant(ctx)),
      (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.codigo === codigo,
      nome,
    );
  }
});

test("as chaves de uma listagem são desescapadas antes de serem conferidas", async () => {
  assert.equal(desescaparXml("a&amp;b&lt;c&gt;d&quot;e&apos;f&#47;g&#x2F;h&desconhecida;"), "a&b<c>d\"e'f/g/h&desconhecida;");
  assert.equal(elementoXml("<A><Code>NoSuchKey</Code></A>", "Code"), "NoSuchKey");
  assert.equal(elementoXml("<A/>", "Code"), null);
});

// --- erros -------------------------------------------------------------------

test("404 num objecto é «inexistente»; 404 num bucket é configuração errada", async () => {
  const { alvo, servidor } = montarS3EmMemoria();
  const ref = { key: novaChave(ctx, "audio"), tamanho: 0, sha256: null };
  await assert.rejects(alvo.storage.get(ctx, ref), ObjectoInexistenteError);
  await assert.rejects(alvo.storage.head(ctx, ref), ObjectoInexistenteError);

  servidor.interceptar = () => resposta(404, erroXml("NoSuchBucket"));
  for (const operacao of [
    () => alvo.storage.get(ctx, ref),
    () => alvo.storage.delete(ctx, ref),
    () => alvo.storage.list(ctx, prefixoDoTenant(ctx)),
    () => alvo.storage.put(ctx, ref.key, new Uint8Array(1), META),
  ]) {
    await assert.rejects(
      operacao(),
      (erro: unknown) =>
        erro instanceof ArmazenamentoIndisponivelError &&
        erro.estado === 404 &&
        erro.codigo === "NoSuchBucket",
    );
  }
});

test("apagar o que o servidor diz não existir não é erro", async () => {
  // Há servidores que respondem 404 a um DELETE de chave inexistente, em vez do
  // 204 do S3. A porta promete idempotência nos dois casos.
  const { alvo, servidor } = montarS3EmMemoria();
  servidor.interceptar = () => resposta(404, erroXml("NoSuchKey"));
  await alvo.storage.delete(ctx, { key: novaChave(ctx, "audio"), tamanho: 0, sha256: null });
  assert.deepEqual(servidor.pedidos.map((p) => p.metodo), ["DELETE"]);
});

test("um fluxo que rebenta a meio também aborta o envio", async () => {
  const { alvo, servidor } = montarS3EmMemoria({ tamanhoDaParte: PARTE_MINIMA });
  async function* fluxo(): AsyncIterable<Uint8Array> {
    yield randomBytes(PARTE_MINIMA + 10);
    throw new Error("a origem dos bytes falhou");
  }
  await assert.rejects(
    alvo.storage.put(ctx, novaChave(ctx, "audio"), fluxo(), META),
    /a origem dos bytes falhou/,
  );
  assert.deepEqual(metodos(servidor), ["POST uploads", "PUT parte 1", "DELETE envio"]);
  assert.equal(servidor.objectos.size, 0);
});

test("um erro do servidor leva o estado e o código, e nunca a URL nem as credenciais", async () => {
  const { alvo, servidor } = montarS3EmMemoria();
  const ref = await alvo.storage.put(ctx, novaChave(ctx, "audio"), new Uint8Array(4), META);
  const fugas = [
    CREDENCIAIS_DE_TESTE.secretAccessKey,
    CREDENCIAIS_DE_TESTE.accessKeyId,
    "Signature=",
    CONFIG_DE_TESTE.endpoint,
    ref.key,
  ];
  const conferir = (erro: unknown, estado: number | null, codigo: string | null): boolean => {
    assert.ok(erro instanceof ArmazenamentoIndisponivelError);
    assert.equal(erro.estado, estado);
    assert.equal(erro.codigo, codigo);
    const visivel = `${erro.message}\n${erro.stack ?? ""}\n${JSON.stringify(erro)}\n${String(erro.cause ?? "")}`;
    for (const fuga of fugas) assert.equal(visivel.includes(fuga), false, `fuga: ${fuga}`);
    return true;
  };

  servidor.interceptar = () => resposta(500, erroXml("InternalError") + CREDENCIAIS_DE_TESTE.secretAccessKey);
  await assert.rejects(alvo.storage.get(ctx, ref), (e: unknown) => conferir(e, 500, "InternalError"));

  servidor.interceptar = () => resposta(403, "isto não é XML");
  await assert.rejects(alvo.storage.head(ctx, ref), (e: unknown) => conferir(e, 403, null));

  // Uma falha de rede traz, tipicamente, a URL na mensagem. Não sobe.
  servidor.interceptar = (pedido) => {
    throw new Error(`connect ECONNREFUSED ${pedido.url} ${pedido.cabecalhos["authorization"]}`);
  };
  await assert.rejects(alvo.storage.get(ctx, ref), (e: unknown) => conferir(e, null, null));
  await assert.rejects(alvo.storage.delete(ctx, ref), (e: unknown) => conferir(e, null, null));
  await assert.rejects(
    alvo.storage.list(ctx, prefixoDoTenant(ctx)),
    (e: unknown) => conferir(e, null, null),
  );
});

test("head sem content-length não inventa um tamanho", async () => {
  const { alvo, servidor } = montarS3EmMemoria();
  const ref = { key: novaChave(ctx, "audio"), tamanho: 0, sha256: null };
  servidor.interceptar = () => resposta(200, "", { "x-amz-meta-classe": "audio" });
  await assert.rejects(
    alvo.storage.head(ctx, ref),
    (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.codigo === "SemContentLength",
  );
});

// --- assinatura --------------------------------------------------------------

/**
 * Assinatura fixada de um pedido fixo. Calculada por esta implementação, que um
 * SeaweedFS 4.48 aceita (`docs/evidencia/KAM-011-seaweedfs.md`), e repetida em
 * `libs/py-core/tests/test_storage_s3.py`: as duas implementações foram
 * escritas em separado e têm de dar o mesmo.
 */
const VECTOR_PARTILHADO = "b0f4568593201ae85b731edd60ec680731274d72d131c016189e5ad4bdee6ae2";

test("todos os pedidos vão assinados, com os metadados dentro da assinatura", async () => {
  const { alvo, servidor } = montarS3EmMemoria();
  const ref = await alvo.storage.put(ctx, novaChave(ctx, "audio"), new Uint8Array(4), META);
  await alvo.storage.head(ctx, ref);
  await alvo.storage.list(ctx, prefixoDoTenant(ctx));
  await alvo.storage.delete(ctx, ref);
  assert.equal(servidor.pedidos.length, 4);
  for (const pedido of servidor.pedidos) {
    const autorizacao = pedido.cabecalhos["authorization"] ?? "";
    assert.match(autorizacao, /^AWS4-HMAC-SHA256 Credential=chave-de-teste\/20261012\/ao-teste-1\/s3\/aws4_request, /);
    assert.equal(autorizacao.includes(CREDENCIAIS_DE_TESTE.secretAccessKey), false);
    assert.equal("host" in pedido.cabecalhos, false, "o Host é do cliente HTTP");
    assert.ok(pedido.url.startsWith(`${CONFIG_DE_TESTE.endpoint}/${CONFIG_DE_TESTE.bucket}`));
  }
  const assinados = /SignedHeaders=(\S+),/.exec(servidor.pedidos[0]!.cabecalhos["authorization"] ?? "")?.[1];
  assert.equal(
    assinados,
    "content-type;host;x-amz-content-sha256;x-amz-date;x-amz-meta-classe;x-amz-meta-retain-until",
  );
});

test("um pedido adulterado depois de assinado é recusado pelo servidor de teste", async () => {
  // Prova que o servidor em memória confere mesmo: sem isto, a bateria «s3 em
  // memória» passava com uma assinatura qualquer.
  const { alvo, servidor } = montarS3EmMemoria();
  const original = servidor.transporte;
  const adulterar = (mudar: (p: Parameters<typeof original>[0]) => Parameters<typeof original>[0]) =>
    montarComTransporte(async (pedido) => original(mudar(pedido)));
  function montarComTransporte(transporte: typeof original) {
    return new MotorS3({
      endpoint: CONFIG_DE_TESTE.endpoint,
      bucket: CONFIG_DE_TESTE.bucket,
      regiao: CONFIG_DE_TESTE.regiao,
      credenciais: async () => CREDENCIAIS_DE_TESTE,
      transporte,
      agora: () => new Date("2026-10-12T09:00:00.000Z"),
    });
  }
  const chave = novaChave(ctx, "audio");
  const meta = { contentType: "audio/ogg", metadados: { classe: "audio", "retain-until": "2026-10-13T08:30:00.000Z" } };
  async function* corpo(): AsyncIterable<Uint8Array> {
    yield new Uint8Array(4);
  }
  const recusado = (erro: unknown): boolean =>
    erro instanceof ArmazenamentoIndisponivelError && (erro.estado === 403 || erro.estado === 400);

  await montarComTransporte(original).put(chave, corpo(), meta);
  await assert.rejects(
    adulterar((p) => ({ ...p, cabecalhos: { ...p.cabecalhos, "x-amz-meta-classe": "imagem" } })).put(chave, corpo(), meta),
    recusado,
    "metadado trocado",
  );
  await assert.rejects(
    adulterar((p) => ({ ...p, corpo: new Uint8Array(5) })).put(chave, corpo(), meta),
    recusado,
    "corpo trocado",
  );
  await assert.rejects(
    adulterar((p) => ({ ...p, url: p.url.replace("/audio/", "/imagem/") })).get(chave),
    recusado,
    "chave trocada",
  );
  await assert.rejects(
    adulterar((p) => ({ ...p, cabecalhos: { ...p.cabecalhos, authorization: "" } })).get(chave),
    recusado,
    "sem assinatura",
  );
  await assert.rejects(
    new MotorS3({
      endpoint: CONFIG_DE_TESTE.endpoint,
      bucket: CONFIG_DE_TESTE.bucket,
      regiao: CONFIG_DE_TESTE.regiao,
      credenciais: async () => ({ ...CREDENCIAIS_DE_TESTE, secretAccessKey: "valor-errado" }),
      transporte: original,
      agora: () => new Date("2026-10-12T09:00:00.000Z"),
    }).get(chave),
    recusado,
    "chave de assinatura errada",
  );
  // E o pedido honesto continua a passar.
  for await (const _ of await alvo.storage.get(ctx, { key: chave, tamanho: 4, sha256: null })) {
    // esvazia
  }
});

test("a assinatura é determinista e sensível a cada parte do pedido", () => {
  const base = {
    metodo: "GET",
    url: new URL("http://s3.teste.invalid:8333/kamba-teste/t/x?list-type=2&prefix=t%2Fx%2F"),
    cabecalhos: { host: "s3.teste.invalid:8333", "x-amz-date": "20261012T090000Z" },
    hashDoCorpo: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    regiao: "ao-teste-1",
    quando: "20261012T090000Z",
  } as const;
  const referencia = assinatura(base, "valor-de-teste");
  assert.match(referencia.assinatura, /^[0-9a-f]{64}$/);
  assert.equal(referencia.assinados, "host;x-amz-date");
  assert.deepEqual(assinatura(base, "valor-de-teste"), referencia);

  assert.equal(referencia.assinatura, VECTOR_PARTILHADO);

  const variantes = [
    assinatura({ ...base, metodo: "HEAD" }, "valor-de-teste"),
    assinatura({ ...base, url: new URL(base.url.toString().replace("/t/x", "/t/y")) }, "valor-de-teste"),
    assinatura({ ...base, url: new URL(base.url.toString().replace("list-type=2", "list-type=1")) }, "valor-de-teste"),
    assinatura({ ...base, cabecalhos: { ...base.cabecalhos, host: "outro:8333" } }, "valor-de-teste"),
    assinatura({ ...base, hashDoCorpo: "UNSIGNED-PAYLOAD" }, "valor-de-teste"),
    assinatura({ ...base, regiao: "us-east-1" }, "valor-de-teste"),
    assinatura({ ...base, quando: "20261012T090001Z" }, "valor-de-teste"),
    assinatura({ ...base, quando: "20261013T090000Z" }, "valor-de-teste"),
    assinatura(base, "valor-de-testf"),
  ];
  const distintas = new Set([referencia.assinatura, ...variantes.map((v) => v.assinatura)]);
  assert.equal(distintas.size, variantes.length + 1);
});

test("canonicalização: codificação RFC 3986, ordem da query e data", () => {
  assert.equal(codificar("a b/c~d-e_f.g!'()*é"), "a%20b%2Fc~d-e_f.g%21%27%28%29%2A%C3%A9");
  assert.equal(caminhoCanonico("/kamba-teste/t/a b/c%20d"), "/kamba-teste/t/a%20b/c%20d");
  assert.equal(
    queryCanonica([
      ["prefix", "t/x/"],
      ["list-type", "2"],
      ["a", "2"],
      ["a", "1"],
      ["uploads", ""],
    ]),
    "a=1&a=2&list-type=2&prefix=t%2Fx%2F&uploads=",
  );
  assert.equal(dataAmz(new Date("2026-10-12T09:05:07.891Z")), "20261012T090507Z");
});

test("assinarPedido e presignarGet: o que entra e o que nunca entra", () => {
  const cabecalhos = assinarPedido({
    metodo: "PUT",
    url: new URL("http://s3.teste.invalid:8333/kamba-teste/t/x"),
    cabecalhos: { "Content-Type": "audio/ogg", "X-Amz-Meta-Classe": "audio" },
    corpo: Buffer.from("abc"),
    credenciais: CREDENCIAIS_DE_TESTE,
    regiao: "ao-teste-1",
    agora: new Date("2026-10-12T09:00:00.000Z"),
  });
  assert.deepEqual(Object.keys(cabecalhos).sort(), [
    "authorization",
    "content-type",
    "host",
    "x-amz-content-sha256",
    "x-amz-date",
    "x-amz-meta-classe",
  ]);
  assert.equal(
    cabecalhos["x-amz-content-sha256"],
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
  assert.equal(cabecalhos["host"], "s3.teste.invalid:8333");

  const url = presignarGet({
    url: new URL("http://s3.teste.invalid:8333/kamba-teste/t/x"),
    credenciais: CREDENCIAIS_DE_TESTE,
    regiao: "ao-teste-1",
    agora: new Date("2026-10-12T09:00:00.000Z"),
    expiraS: 60,
  });
  const lida = new URL(url);
  assert.equal(lida.origin + lida.pathname, "http://s3.teste.invalid:8333/kamba-teste/t/x");
  assert.equal(lida.searchParams.get("X-Amz-Expires"), "60");
  assert.equal(lida.searchParams.get("X-Amz-Date"), "20261012T090000Z");
  assert.equal(lida.searchParams.get("X-Amz-SignedHeaders"), "host");
  assert.equal(lida.searchParams.get("X-Amz-Algorithm"), "AWS4-HMAC-SHA256");
  assert.match(lida.searchParams.get("X-Amz-Signature") ?? "", /^[0-9a-f]{64}$/);
  assert.equal(url.includes(CREDENCIAIS_DE_TESTE.secretAccessKey), false);
  // A mesma URL do lado Python: as duas implementações assinam igual.
  assert.equal(
    lida.searchParams.get("X-Amz-Signature"),
    "d7afce495852f7aca64e58187e49aabc92528e6808b5b71db9d3463c0302eccd",
  );
});

// --- transporte --------------------------------------------------------------

test("o transporte por fetch entrega método, cabeçalhos e corpo, e não segue redireccionamentos", async () => {
  const vistos: { metodo: string; url: string; meta: string | undefined; corpo: string }[] = [];
  const servidor = createServer((pedido, respostaHttp) => {
    const blocos: Buffer[] = [];
    pedido.on("data", (bloco: Buffer) => blocos.push(bloco));
    pedido.on("end", () => {
      vistos.push({
        metodo: pedido.method ?? "",
        url: pedido.url ?? "",
        meta: pedido.headers["x-amz-meta-classe"] as string | undefined,
        corpo: Buffer.concat(blocos).toString("utf8"),
      });
      if (pedido.url === "/redireccionar") {
        respostaHttp.writeHead(307, { location: "/outro-sitio" }).end();
      } else if (pedido.method === "HEAD") {
        respostaHttp.writeHead(200, { "X-Amz-Meta-Classe": "audio", "content-length": "0" }).end();
      } else {
        respostaHttp.writeHead(200, { ETag: '"abc"' }).end("olá");
      }
    });
  });
  await new Promise<void>((pronto) => servidor.listen(0, "127.0.0.1", pronto));
  try {
    const base = `http://127.0.0.1:${(servidor.address() as AddressInfo).port}`;
    const transporte = transportePorFetch(5000);

    const escrita = await transporte({
      metodo: "PUT",
      url: `${base}/b/chave`,
      cabecalhos: { "x-amz-meta-classe": "audio" },
      corpo: Buffer.from("conteúdo"),
    });
    assert.equal(escrita.estado, 200);
    assert.equal(escrita.cabecalhos["etag"], '"abc"', "os nomes dos cabeçalhos vêm em minúsculas");
    const blocos: Uint8Array[] = [];
    for await (const bloco of escrita.corpo) blocos.push(bloco);
    assert.equal(Buffer.concat(blocos).toString("utf8"), "olá");

    const cabeca = await transporte({ metodo: "HEAD", url: `${base}/b/chave`, cabecalhos: {} });
    assert.equal(cabeca.cabecalhos["x-amz-meta-classe"], "audio");
    for await (const _ of cabeca.corpo) assert.fail("um HEAD não tem corpo");

    const redireccionado = await transporte({ metodo: "GET", url: `${base}/redireccionar`, cabecalhos: {} });
    assert.equal(redireccionado.estado, 307, "o pedido assinado não segue para outro sítio");
    for await (const _ of redireccionado.corpo) {
      // esvazia
    }

    assert.deepEqual(vistos, [
      { metodo: "PUT", url: "/b/chave", meta: "audio", corpo: "conteúdo" },
      { metodo: "HEAD", url: "/b/chave", meta: undefined, corpo: "" },
      { metodo: "GET", url: "/redireccionar", meta: undefined, corpo: "" },
    ]);
  } finally {
    await new Promise((fechado) => servidor.close(fechado));
  }
});
