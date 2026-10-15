/**
 * A bateria de contrato de `StorageProvider` (KAM-011).
 *
 * **Uma bateria, escrita uma vez.** O critério de aceitação 5 diz «a mesma
 * suite de contrato passa na implementação *fake* e contra SeaweedFS». A forma
 * de essa frase ser verificável é esta função: recebe uma fábrica de alvos e
 * regista os mesmos casos, com as mesmas asserções, sobre o que lhe derem.
 *
 * Quem a chama:
 *
 * - `tests/storage.contrato.test.ts` — sobre o *fake* e sobre o motor S3 ligado
 *   a um servidor S3 em memória. Corre no *gate* 4.
 * - `tests/integracao/storage.s3real.test.ts` — sobre o motor S3 ligado a um
 *   servidor real (SeaweedFS), quando há um. **Não** corre no *gate* 4.
 *
 * Cada caso usa tenants novos, com UUID aleatório: os alvos reais não se
 * limpam entre casos, e um caso não pode depender do que outro deixou.
 */

import assert from "node:assert/strict";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { test } from "node:test";

import { novaChave, prefixoDoTenant } from "../../src/storage/chave.ts";
import {
  ChaveForaDoTenantError,
  type Ctx,
  CtxEmFaltaError,
  ListagemTruncadaError,
  type ObjectRef,
  ObjectoInexistenteError,
  type StorageProvider,
  TtlInvalidoError,
} from "../../src/storage/port.ts";

/** Uma implementação sob teste. */
export interface Alvo {
  readonly storage: StorageProvider;
  /** `GET` de uma URL assinada, sem mais credencial nenhuma. */
  readonly buscar: (url: string) => Promise<{ estado: number; corpo: Uint8Array }>;
  /**
   * Faz passar `segundos`. Num alvo com relógio injectado é instantâneo; num
   * servidor real **espera-se** — é a única forma de provar que é o servidor,
   * e não o nosso relógio, que recusa a URL.
   */
  readonly avancar: (segundos: number) => Promise<void>;
  readonly fechar?: () => Promise<void>;
}

const KB = 1024;
const MB = 1024 * 1024;

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

async function juntar(fluxo: AsyncIterable<Uint8Array>): Promise<Uint8Array> {
  const blocos: Uint8Array[] = [];
  for await (const bloco of fluxo) blocos.push(bloco);
  return Buffer.concat(blocos);
}

async function* emBlocos(bytes: Uint8Array, tamanho: number): AsyncIterable<Uint8Array> {
  for (let i = 0; i < bytes.length; i += tamanho) {
    yield bytes.subarray(i, Math.min(i + tamanho, bytes.length));
  }
}

function tenant(): Ctx {
  return { tenantId: randomUUID() };
}

const PRAZO = new Date("2026-10-13T08:30:00.000Z");

async function guardar(
  storage: StorageProvider,
  ctx: Ctx,
  bytes: Uint8Array,
  classe = "audio",
): Promise<ObjectRef> {
  return storage.put(ctx, novaChave(ctx, classe), bytes, {
    contentType: "audio/ogg",
    classe,
    retainUntil: PRAZO,
  });
}

/**
 * Regista a bateria sobre um alvo.
 *
 * @param nome prefixo dos nomes dos casos (`fake`, `s3 em memória`, `seaweedfs`).
 * @param criar fábrica; é chamada uma vez por caso.
 */
export function bateriaDeContrato(nome: string, criar: () => Promise<Alvo>): void {
  const caso = (titulo: string, corpo: (alvo: Alvo) => Promise<void>): void => {
    test(`[${nome}] ${titulo}`, async () => {
      const alvo = await criar();
      try {
        await corpo(alvo);
      } finally {
        await alvo.fechar?.();
      }
    });
  };

  // --- CA2: ida e volta com checksum idêntico --------------------------------

  for (const [rotulo, tamanho] of [
    ["1 KB", 1 * KB],
    ["10 MB", 10 * MB],
    ["25 MB", 25 * MB],
  ] as const) {
    caso(`ida e volta de ${rotulo} com checksum idêntico`, async ({ storage }) => {
      const ctx = tenant();
      const original = randomBytes(tamanho);
      const soma = sha256(original);

      const ref = await guardar(storage, ctx, original);
      assert.equal(ref.tamanho, tamanho);
      assert.equal(ref.sha256, soma, "a soma que `put` devolve é a do que foi enviado");

      const devolvido = await juntar(await storage.get(ctx, ref));
      assert.equal(devolvido.length, tamanho);
      assert.equal(sha256(devolvido), soma, "o que volta é o que foi");
    });
  }

  caso("o corpo pode ser um fluxo, em blocos de tamanho irregular", async ({ storage }) => {
    const ctx = tenant();
    const original = randomBytes(300 * KB + 17);
    const key = novaChave(ctx, "imagem");
    const ref = await storage.put(ctx, key, emBlocos(original, 7 * KB + 3), {
      contentType: "image/jpeg",
      classe: "imagem",
      retainUntil: PRAZO,
    });
    assert.equal(ref.sha256, sha256(original));
    assert.equal(sha256(await juntar(await storage.get(ctx, ref))), sha256(original));
  });

  caso("um objecto vazio é um objecto", async ({ storage }) => {
    const ctx = tenant();
    const ref = await guardar(storage, ctx, new Uint8Array(0));
    assert.equal(ref.tamanho, 0);
    assert.equal((await juntar(await storage.get(ctx, ref))).length, 0);
  });

  // --- CA8: metadados --------------------------------------------------------

  caso("cada objecto leva `classe` e `retain_until`, lidos do servidor", async ({ storage }) => {
    const ctx = tenant();
    const key = novaChave(ctx, "audio");
    const ref = await storage.put(ctx, key, randomBytes(2 * KB), {
      contentType: "audio/ogg; codecs=opus",
      classe: "audio",
      retainUntil: PRAZO,
    });
    const info = await storage.head(ctx, ref);
    assert.equal(info.key, key);
    assert.equal(info.classe, "audio");
    assert.equal(info.retainUntil.toISOString(), PRAZO.toISOString());
    assert.equal(info.tamanho, 2 * KB);
    assert.match(info.contentType, /^audio\/ogg/);
  });

  // --- CA3: URL assinada ------------------------------------------------------

  caso("signUrl recusa um TTL acima de 300 s, e tudo o que não é um inteiro positivo", async ({
    storage,
  }) => {
    const ctx = tenant();
    const ref = await guardar(storage, ctx, randomBytes(KB));
    for (const ttl of [301, 3600, 0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      await assert.rejects(storage.signUrl(ctx, ref, { ttlSeconds: ttl }), TtlInvalidoError, `ttl ${ttl}`);
    }
    await assert.rejects(
      storage.signUrl(ctx, ref, { ttlSeconds: "60" as unknown as number }),
      TtlInvalidoError,
    );
    // O limite é inclusivo: 300 serve.
    assert.equal(typeof (await storage.signUrl(ctx, ref, { ttlSeconds: 300 })), "string");
  });

  caso("uma URL com TTL de 60 s devolve 200 antes e 403 depois de 65 s", async (alvo) => {
    const ctx = tenant();
    const original = randomBytes(4 * KB);
    const ref = await guardar(alvo.storage, ctx, original);

    const url = await alvo.storage.signUrl(ctx, ref, { ttlSeconds: 60 });
    const antes = await alvo.buscar(url);
    assert.equal(antes.estado, 200);
    assert.equal(sha256(antes.corpo), sha256(original));

    await alvo.avancar(65);
    const depois = await alvo.buscar(url);
    assert.equal(depois.estado, 403, "a URL expirou");
    assert.equal(Buffer.from(depois.corpo).includes(original.subarray(0, 64)), false);
  });

  caso("uma URL assinada para um objecto não abre outro", async (alvo) => {
    const a = tenant();
    const b = tenant();
    const refA = await guardar(alvo.storage, a, randomBytes(KB));
    const segredoDeB = randomBytes(KB);
    const refB = await guardar(alvo.storage, b, segredoDeB);

    const url = await alvo.storage.signUrl(a, refA, { ttlSeconds: 60 });
    assert.ok(url.includes(refA.key), "pré-condição: a chave vai em claro na URL");
    const trocada = url.replace(refA.key, refB.key);
    const resposta = await alvo.buscar(trocada);
    assert.equal(resposta.estado, 403);
    assert.equal(Buffer.from(resposta.corpo).includes(segredoDeB.subarray(0, 64)), false);
  });

  // --- delete e list ----------------------------------------------------------

  caso("delete apaga, e apagar outra vez não é erro", async ({ storage }) => {
    const ctx = tenant();
    const ref = await guardar(storage, ctx, randomBytes(KB));
    await storage.delete(ctx, ref);
    await assert.rejects(storage.get(ctx, ref), ObjectoInexistenteError);
    await assert.rejects(storage.head(ctx, ref), ObjectoInexistenteError);
    await storage.delete(ctx, ref);
  });

  caso("list devolve o que está sob o prefixo, com tamanhos, por ordem", async ({ storage }) => {
    const ctx = tenant();
    const audios = [
      await guardar(storage, ctx, randomBytes(10), "audio"),
      await guardar(storage, ctx, randomBytes(20), "audio"),
    ];
    const imagem = await guardar(storage, ctx, randomBytes(30), "imagem");

    const tudo = await storage.list(ctx, prefixoDoTenant(ctx));
    assert.deepEqual(
      tudo.map((r) => r.key),
      [...audios, imagem].map((r) => r.key).sort(),
    );
    assert.deepEqual(
      Object.fromEntries(tudo.map((r) => [r.key, r.tamanho])),
      Object.fromEntries([...audios, imagem].map((r) => [r.key, r.tamanho])),
    );

    const soAudio = await storage.list(ctx, `${prefixoDoTenant(ctx)}audio/`);
    assert.deepEqual(soAudio.map((r) => r.key), audios.map((r) => r.key).sort());

    assert.deepEqual(await storage.list(ctx, `${prefixoDoTenant(ctx)}video/`), []);
  });

  caso("list não corta em silêncio: acima do limite, lança", async ({ storage }) => {
    const ctx = tenant();
    for (let i = 0; i < 3; i += 1) await guardar(storage, ctx, randomBytes(8));
    await assert.rejects(storage.list(ctx, prefixoDoTenant(ctx), { limite: 2 }), ListagemTruncadaError);
    assert.equal((await storage.list(ctx, prefixoDoTenant(ctx), { limite: 3 })).length, 3);
  });

  // --- CA1 e CA4 (X-08): isolamento ------------------------------------------

  caso("X-08: com o contexto de A, nada do que é de B se lê, assina, apaga ou lista", async (alvo) => {
    const { storage } = alvo;
    const a = tenant();
    const b = tenant();
    const canarioDeB = randomBytes(2 * KB);
    const refB = await guardar(storage, b, canarioDeB);
    const refA = await guardar(storage, a, randomBytes(KB));

    // Metade positiva primeiro: B vê o seu, A vê o seu. «A não vê B» prova-se
    // trivialmente com um armazenamento vazio.
    assert.equal(sha256(await juntar(await storage.get(b, refB))), sha256(canarioDeB));
    assert.deepEqual((await storage.list(a, prefixoDoTenant(a))).map((r) => r.key), [refA.key]);

    await assert.rejects(storage.get(a, refB), ChaveForaDoTenantError);
    await assert.rejects(storage.head(a, refB), ChaveForaDoTenantError);
    await assert.rejects(storage.signUrl(a, refB, { ttlSeconds: 60 }), ChaveForaDoTenantError);
    await assert.rejects(storage.delete(a, refB), ChaveForaDoTenantError);
    await assert.rejects(storage.list(a, prefixoDoTenant(b)), ChaveForaDoTenantError);
    await assert.rejects(storage.list(a, `${prefixoDoTenant(b)}audio/`), ChaveForaDoTenantError);

    // Nenhuma listagem de A traz chaves de B, por nenhum prefixo que A possa pedir.
    for (const prefixo of [prefixoDoTenant(a), `${prefixoDoTenant(a)}audio/`]) {
      for (const ref of await storage.list(a, prefixo)) {
        assert.ok(ref.key.startsWith(prefixoDoTenant(a)), "a listagem de A só tem chaves de A");
        assert.notEqual(ref.key, refB.key);
      }
    }

    // E o que A tentou não teve efeito: o objecto de B está intacto.
    assert.equal(sha256(await juntar(await storage.get(b, refB))), sha256(canarioDeB));
  });

  caso("X-08: A não escreve no prefixo de B", async ({ storage }) => {
    const a = tenant();
    const b = tenant();
    const chaveDeB = novaChave(b, "audio");
    await assert.rejects(
      storage.put(a, chaveDeB, randomBytes(KB), {
        contentType: "audio/ogg",
        classe: "audio",
        retainUntil: PRAZO,
      }),
      ChaveForaDoTenantError,
    );
    assert.deepEqual(await storage.list(b, prefixoDoTenant(b)), [], "nada foi escrito em B");
  });

  caso("sem `ctx.tenantId` não há operação nenhuma", async ({ storage }) => {
    const ctx = tenant();
    const ref = await guardar(storage, ctx, randomBytes(KB));
    for (const vazio of [{}, { tenantId: "" }, { tenantId: null }, null, undefined]) {
      const semCtx = vazio as unknown as Ctx;
      await assert.rejects(storage.get(semCtx, ref), CtxEmFaltaError);
      await assert.rejects(storage.head(semCtx, ref), CtxEmFaltaError);
      await assert.rejects(storage.signUrl(semCtx, ref, { ttlSeconds: 60 }), CtxEmFaltaError);
      await assert.rejects(storage.delete(semCtx, ref), CtxEmFaltaError);
      await assert.rejects(storage.list(semCtx, prefixoDoTenant(ctx)), CtxEmFaltaError);
      await assert.rejects(
        storage.put(semCtx, ref.key, randomBytes(8), {
          contentType: "audio/ogg",
          classe: "audio",
          retainUntil: PRAZO,
        }),
        CtxEmFaltaError,
      );
    }
    // O objecto continua lá: nenhuma das recusas apagou nada.
    assert.equal((await storage.head(ctx, ref)).tamanho, KB);
  });
}
