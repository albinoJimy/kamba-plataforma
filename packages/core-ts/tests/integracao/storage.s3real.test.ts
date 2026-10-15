/**
 * A bateria de contrato contra um servidor S3 **real** (KAM-011).
 *
 * Não corre no *gate* 4: está fora de `tests/*.test.ts` de propósito, e quem a
 * corre é `infra/storage/contrato.py`, que levanta um SeaweedFS descartável,
 * fixado por *digest*, e a aponta para lá. Sem as variáveis de ambiente
 * **falha** — não salta: uma suite de integração que salta em silêncio é uma
 * suite que ninguém corre.
 *
 * O caminho até ao servidor é o de produção, sem atalhos: `lerConfig` lê as
 * `KAMBA_STORAGE_*`, as credenciais vêm de um `EnvSecretProvider`
 * (as duas variáveis de segredo do armazenamento, ADR-L002), e o transporte é
 * o `fetch`.
 *
 * Além da bateria comum, três coisas que só um servidor real responde:
 *
 * 1. **a assinatura é mesmo verificada** — uma chave errada e um pedido anónimo
 *    são recusados. Sem isto, a bateria passava contra um servidor que
 *    aceitasse tudo, e não provava nada sobre o SigV4 escrito à mão;
 * 2. o envio **em partes** aconteceu de facto (e não um `PUT` de 25 MB);
 * 3. *object lock*: **sim ou não**. É um teste de capacidade, não um requisito:
 *    regista o que o servidor faz e só falha se a resposta for indeterminada.
 *
 * Os resultados lêem-se nas linhas `CAPACIDADE …` da saída.
 */

import assert from "node:assert/strict";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { test } from "node:test";
import { setTimeout as esperar } from "node:timers/promises";

import { EnvSecretProvider } from "../../src/secrets/env.ts";
import { isAmbiente } from "../../src/secrets/port.ts";
import { novaChave } from "../../src/storage/chave.ts";
import { type StorageConfig, criarStorageS3, lerConfig } from "../../src/storage/config.ts";
import { ArmazenamentoIndisponivelError, type Ctx } from "../../src/storage/port.ts";
import { type PedidoHttp, type RespostaHttp, transportePorFetch } from "../../src/storage/s3.ts";
import { type Credenciais, assinarPedido } from "../../src/storage/sigv4.ts";
import { type Alvo, bateriaDeContrato } from "../apoio/contrato-storage.ts";

const ambiente = process.env.KAMBA_ENV ?? "dev";
assert.ok(isAmbiente(ambiente), "KAMBA_ENV tem de ser dev, staging ou prod");

// Falha aqui, com os nomes das variáveis em falta, se o orquestrador não as deu.
const config: StorageConfig = lerConfig({ ambiente });
const secrets = new EnvSecretProvider({ ambiente });
const rede = transportePorFetch(120_000);

/** Pedidos que o motor fez, para se poder ver como foi o envio. */
const vistos: PedidoHttp[] = [];
const transporteEspiado = async (pedido: PedidoHttp): Promise<RespostaHttp> => {
  vistos.push(pedido);
  return rede(pedido);
};

async function credenciais(): Promise<Credenciais> {
  return {
    accessKeyId: await secrets.get("storage_access_key_id"),
    secretAccessKey: await secrets.get("storage_secret_access_key"),
  };
}

async function ler(corpo: AsyncIterable<Uint8Array>): Promise<Buffer> {
  const blocos: Uint8Array[] = [];
  for await (const bloco of corpo) blocos.push(bloco);
  return Buffer.concat(blocos);
}

/** Um pedido S3 assinado, fora da porta: para criar o *bucket* e para as sondas. */
async function bruto(
  metodo: string,
  caminho: string,
  o: { query?: Record<string, string>; cabecalhos?: Record<string, string>; corpo?: Uint8Array } = {},
): Promise<{ estado: number; cabecalhos: Readonly<Record<string, string>>; texto: string }> {
  const url = new URL(config.endpoint + caminho);
  for (const [nome, valor] of Object.entries(o.query ?? {})) url.searchParams.set(nome, valor);
  const cabecalhos = assinarPedido({
    metodo,
    url,
    cabecalhos: o.cabecalhos ?? {},
    ...(o.corpo === undefined ? {} : { corpo: o.corpo }),
    credenciais: await credenciais(),
    regiao: config.regiao,
    agora: new Date(),
  });
  delete cabecalhos["host"];
  const resposta = await rede({
    metodo,
    url: url.toString(),
    cabecalhos,
    ...(o.corpo === undefined ? {} : { corpo: o.corpo }),
  });
  return {
    estado: resposta.estado,
    cabecalhos: resposta.cabecalhos,
    texto: (await ler(resposta.corpo)).toString("utf8"),
  };
}

async function garantirBucket(nome: string, cabecalhos: Record<string, string> = {}): Promise<number> {
  const resposta = await bruto("PUT", `/${nome}`, { cabecalhos });
  // 409: já existe (corridas repetidas contra o mesmo servidor).
  assert.ok(
    [200, 409].includes(resposta.estado),
    `criar o bucket devolveu HTTP ${resposta.estado}`,
  );
  return resposta.estado;
}

async function alvoReal(): Promise<Alvo> {
  return {
    storage: criarStorageS3({ config, secrets, transporte: transporteEspiado }),
    buscar: async (url) => {
      const resposta = await fetch(url, { redirect: "manual" });
      return { estado: resposta.status, corpo: new Uint8Array(await resposta.arrayBuffer()) };
    },
    avancar: async (segundos) => {
      await esperar(segundos * 1000);
    },
  };
}

const PRAZO = new Date("2026-10-13T08:30:00.000Z");
const meta = { contentType: "audio/ogg", classe: "audio", retainUntil: PRAZO } as const;

test("[servidor real] preparação: o bucket existe", async () => {
  await garantirBucket(config.bucket);
});

bateriaDeContrato("servidor real", alvoReal);

test("[servidor real] a assinatura é verificada: chave errada e pedido anónimo são recusados", async () => {
  const ctx: Ctx = { tenantId: randomUUID() };
  const bytes = randomBytes(1024);

  const bom = criarStorageS3({ config, secrets });
  const ref = await bom.put(ctx, novaChave(ctx, "audio"), bytes, meta);

  const errado = criarStorageS3({
    config,
    secrets: {
      get: async (nome) =>
        nome === "storage_secret_access_key" ? "valor-errado-de-teste" : secrets.get(nome),
    },
  });
  await assert.rejects(
    errado.put(ctx, novaChave(ctx, "audio"), bytes, meta),
    (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.estado === 403,
    "escrever com a chave errada tem de dar 403",
  );
  await assert.rejects(
    errado.get(ctx, ref),
    (erro: unknown) => erro instanceof ArmazenamentoIndisponivelError && erro.estado === 403,
    "ler com a chave errada tem de dar 403",
  );
  // Uma URL assinada com a chave errada também não abre nada.
  const urlErrada = await errado.signUrl(ctx, ref, { ttlSeconds: 60 });
  assert.equal((await fetch(urlErrada)).status, 403);

  const anonimo = await fetch(`${config.endpoint}/${config.bucket}/${ref.key}`);
  assert.equal(anonimo.status, 403, "sem assinatura, o objecto não se lê");
  const listagemAnonima = await fetch(`${config.endpoint}/${config.bucket}?list-type=2`);
  assert.equal(listagemAnonima.status, 403, "sem assinatura, o bucket não se lista");
});

/**
 * Objectos de interoperabilidade: tenant, chaves e conteúdo fixos, iguais em
 * `libs/py-core/tests/integracao/test_storage_s3real.py`. O orquestrador corre
 * a escrita do lado Python antes desta suite, e a leitura depois.
 */
const INTEROP_CTX: Ctx = { tenantId: "00000000-0000-4000-8000-00000000c0de" };
const INTEROP_CHAVE_PY = `t/${INTEROP_CTX.tenantId}/audio/2026/10/00000000-0000-4000-8000-0000000000b1`;
const INTEROP_CHAVE_TS = `t/${INTEROP_CTX.tenantId}/audio/2026/10/00000000-0000-4000-8000-0000000000a1`;
const INTEROP_DADOS = Buffer.from(Array.from({ length: 1024 }, (_, i) => i % 256));

test("[servidor real] interoperabilidade: o TypeScript lê o que o Python escreveu, e escreve para ele", async () => {
  const storage = criarStorageS3({ config, secrets });

  const lido = await ler(await storage.get(INTEROP_CTX, { key: INTEROP_CHAVE_PY, tamanho: 0, sha256: null }));
  assert.deepEqual(lido, INTEROP_DADOS);
  const info = await storage.head(INTEROP_CTX, { key: INTEROP_CHAVE_PY, tamanho: 0, sha256: null });
  assert.equal(info.classe, "audio");
  assert.equal(info.retainUntil.toISOString(), PRAZO.toISOString());
  assert.equal(info.tamanho, INTEROP_DADOS.length);

  const ref = await storage.put(INTEROP_CTX, INTEROP_CHAVE_TS, INTEROP_DADOS, meta);
  assert.equal(ref.sha256, createHash("sha256").update(INTEROP_DADOS).digest("hex"));
});

test("[servidor real] CAPACIDADE multipart: 25 MB vão em partes e voltam iguais", async (t) => {
  const ctx: Ctx = { tenantId: randomUUID() };
  const bytes = randomBytes(25 * 1024 * 1024);
  const storage = criarStorageS3({ config, secrets, transporte: transporteEspiado });

  vistos.length = 0;
  const ref = await storage.put(ctx, novaChave(ctx, "audio"), bytes, meta);
  const partes = vistos.filter((p) => p.metodo === "PUT" && p.url.includes("partNumber=")).length;
  const aberturas = vistos.filter((p) => p.metodo === "POST" && /[?&]uploads=?(&|$)/.test(p.url)).length;
  const fechos = vistos.filter((p) => p.metodo === "POST" && p.url.includes("uploadId=")).length;
  assert.equal(aberturas, 1);
  assert.equal(partes, 2, "25 MiB com partes de 16 MiB são duas partes");
  assert.equal(fechos, 1);

  const soma = createHash("sha256");
  let tamanho = 0;
  for await (const bloco of await storage.get(ctx, ref)) {
    soma.update(bloco);
    tamanho += bloco.length;
  }
  assert.equal(tamanho, bytes.length);
  assert.equal(soma.digest("hex"), createHash("sha256").update(bytes).digest("hex"));
  assert.equal((await storage.head(ctx, ref)).classe, "audio", "os metadados sobrevivem ao envio em partes");
  t.diagnostic(`CAPACIDADE multipart: sim (1 abertura, ${partes} partes, 1 fecho; sha256 idêntico)`);
});

test("[servidor real] CAPACIDADE object lock: sim ou não", async (t) => {
  const bucket = `kamba-lock-${randomUUID().slice(0, 8)}`;
  const criacao = await bruto("PUT", `/${bucket}`, {
    cabecalhos: { "x-amz-bucket-object-lock-enabled": "true" },
  });
  const passos: string[] = [`criar bucket com object lock: HTTP ${criacao.estado}`];
  let resposta = "não";

  if (criacao.estado === 200) {
    const ate = new Date(Date.now() + 60 * 60 * 1000).toISOString();
    const escrita = await bruto("PUT", `/${bucket}/retido`, {
      cabecalhos: {
        "x-amz-object-lock-mode": "COMPLIANCE",
        "x-amz-object-lock-retain-until-date": ate,
      },
      corpo: Buffer.from("conteudo de teste de retencao"),
    });
    passos.push(`PUT com retenção COMPLIANCE: HTTP ${escrita.estado}`);
    const versao = escrita.cabecalhos["x-amz-version-id"] ?? null;
    passos.push(`x-amz-version-id devolvido: ${versao === null ? "não" : "sim"}`);

    const retencao = await bruto("GET", `/${bucket}/retido`, { query: { retention: "" } });
    const modo = /<Mode>([^<]*)<\/Mode>/.exec(retencao.texto)?.[1] ?? null;
    passos.push(`GET ?retention: HTTP ${retencao.estado}, modo ${modo ?? "ausente"}`);

    if (versao !== null) {
      const apagar = await bruto("DELETE", `/${bucket}/retido`, { query: { versionId: versao } });
      passos.push(`DELETE da versão retida: HTTP ${apagar.estado}`);
      const depois = await bruto("GET", `/${bucket}/retido`, { query: { versionId: versao } });
      passos.push(`GET da versão depois do DELETE: HTTP ${depois.estado}`);
      if (escrita.estado === 200 && modo === "COMPLIANCE" && apagar.estado >= 400 && depois.estado === 200) {
        resposta = "sim";
      }
    }
  }

  for (const passo of passos) t.diagnostic(`  object lock — ${passo}`);
  t.diagnostic(`CAPACIDADE object lock: ${resposta}`);
  // Só a criação do bucket tem de ter uma resposta inteligível; o resto é o
  // que se quer saber, e «não» é uma resposta.
  assert.ok(criacao.estado > 0);
});
