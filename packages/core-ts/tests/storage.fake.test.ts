/**
 * O que é só do *fake* (KAM-011): as URLs que assina, e o que guarda.
 *
 * O comportamento visto pela porta está na bateria de contrato; aqui ficam as
 * arestas de `buscar`, que é a única coisa que o *fake* tem e um servidor não.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { novaChave } from "../src/storage/chave.ts";
import { ESQUEMA_FAKE, criarStorageFake } from "../src/storage/fake.ts";
import { Relogio } from "./apoio/alvos-storage.ts";

const ctx = { tenantId: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa" };
const META = {
  contentType: "audio/ogg",
  classe: "audio",
  retainUntil: new Date("2026-10-13T08:30:00.000Z"),
} as const;

test("a URL do fake tem esquema próprio e não se resolve fora dele", async () => {
  const fake = criarStorageFake();
  assert.equal(fake.storage.nome, "fake");
  const ref = await fake.storage.put(ctx, novaChave(ctx, "audio"), Buffer.from("abc"), META);
  const url = await fake.storage.signUrl(ctx, ref, { ttlSeconds: 60 });
  assert.ok(url.startsWith(`${ESQUEMA_FAKE}//objectos/${ref.key}?`));
  assert.equal(fake.total(), 1);
  assert.deepEqual(await fake.buscar(url), { estado: 200, corpo: new Uint8Array([97, 98, 99]) });
});

test("buscar recusa tudo o que não é uma URL assinada por este fake, intacta e no prazo", async () => {
  const relogio = new Relogio();
  const fake = criarStorageFake({ agora: relogio.agora });
  const ref = await fake.storage.put(ctx, novaChave(ctx, "audio"), Buffer.from("abc"), META);
  const url = await fake.storage.signUrl(ctx, ref, { ttlSeconds: 60 });
  const expira = /expira=(\d+)/.exec(url)?.[1] ?? "";

  const outro = criarStorageFake({ agora: relogio.agora });
  const refOutro = await outro.storage.put(ctx, ref.key, Buffer.from("abc"), META);
  const urlDeOutro = await outro.storage.signUrl(ctx, refOutro, { ttlSeconds: 60 });

  for (const adulterada of [
    "isto não é uma URL",
    "",
    url.replace(ESQUEMA_FAKE, "https:"),
    url.replace("//objectos/", "//outro/"),
    url.replace(`expira=${expira}`, `expira=${Number(expira) + 3600}`),
    url.replace(`expira=${expira}`, "expira=amanha"),
    url.replace(/assinatura=[0-9a-f]+/, "assinatura="),
    url.replace(/assinatura=[0-9a-f]+/, `assinatura=${"0".repeat(64)}`),
    url.replace(/assinatura=([0-9a-f]+)/, "assinatura=$1ff"),
    url.replace(/&assinatura=[0-9a-f]+/, ""),
    urlDeOutro,
  ]) {
    assert.deepEqual(
      await fake.buscar(adulterada),
      { estado: 403, corpo: new Uint8Array(0) },
      adulterada.slice(0, 60),
    );
  }

  // No limite: 59 s serve, 60 s já não.
  relogio.avancar(59);
  assert.equal((await fake.buscar(url)).estado, 200);
  relogio.avancar(1);
  assert.equal((await fake.buscar(url)).estado, 403);
});

test("uma URL válida de um objecto apagado dá 404, e o fake não partilha memória com quem chama", async () => {
  const fake = criarStorageFake();
  const bytes = Buffer.from("abc");
  const ref = await fake.storage.put(ctx, novaChave(ctx, "audio"), bytes, META);
  bytes[0] = 0;
  const url = await fake.storage.signUrl(ctx, ref, { ttlSeconds: 60 });
  const lido = await fake.buscar(url);
  assert.deepEqual(lido.corpo, new Uint8Array([97, 98, 99]), "o put copiou");
  lido.corpo[0] = 0;
  assert.deepEqual((await fake.buscar(url)).corpo, new Uint8Array([97, 98, 99]), "o buscar copiou");

  await fake.storage.delete(ctx, ref);
  assert.deepEqual(await fake.buscar(url), { estado: 404, corpo: new Uint8Array(0) });
  assert.equal(fake.total(), 0);
});
