/**
 * Isolamento por tenant no armazenamento: chaves, prefixos e recusas (KAM-011).
 *
 * A bateria de contrato já tem o X-08 visto de fora — A contra B, nos alvos
 * todos. Esta suite ataca o mesmo por dentro, onde as arestas estão:
 *
 * 1. **a forma da chave**: tudo o que não é exactamente
 *    `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}` é recusado, e a lista de
 *    tentativas abaixo é a de quem quer sair do seu prefixo;
 * 2. **o dono da chave**: a recusa acontece **antes** de o motor ser tocado —
 *    conta-se, não se presume;
 * 3. **o prefixo de listagem**;
 * 4. **a segunda camada**: um motor que mente (devolve chaves de outro tenant)
 *    não consegue fazer a porta devolvê-las.
 *
 * Cada caso de recusa confere a **classe** do erro e que o motor ficou
 * intocado. Um teste que aceitasse «lançou qualquer coisa» passava com a
 * validação partida noutro sítio.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  chaveDoCtx,
  novaChave,
  partesDaChave,
  prefixoDoCtx,
  prefixoDoTenant,
  tenantDoCtx,
} from "../src/storage/chave.ts";
import { ArmazenamentoPorTenant } from "../src/storage/guarda.ts";
import type { InfoBruta, ItemListado, MetaBruta, Motor } from "../src/storage/motor.ts";
import {
  ChaveForaDoTenantError,
  ChaveInvalidaError,
  type Ctx,
  CtxEmFaltaError,
  MetaInvalidaError,
  type ObjectRef,
  RespostaDoMotorInvalidaError,
  TenantInvalidoError,
} from "../src/storage/port.ts";

// Com letras, de propósito: `A.toUpperCase()` tem de ser diferente de `A`.
const A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa";
const B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb";
const ID = "cccccccc-3333-4333-8333-cccccccccccc";
const ctxA: Ctx = { tenantId: A };
const ctxB: Ctx = { tenantId: B };

const PRAZO = new Date("2026-10-13T08:30:00.000Z");
const META = { contentType: "audio/ogg", classe: "audio", retainUntil: PRAZO } as const;

/** Um motor que só regista o que lhe pedem, e devolve o que lhe mandarem devolver. */
class MotorEspiao implements Motor {
  readonly nome = "espiao";
  readonly chamadas: string[] = [];
  listagem: ItemListado[] = [];
  truncada = false;
  info: InfoBruta = {
    tamanho: 3,
    contentType: "audio/ogg",
    metadados: { classe: "audio", "retain-until": PRAZO.toISOString() },
  };

  async put(chave: string, corpo: AsyncIterable<Uint8Array>, _meta: MetaBruta) {
    this.chamadas.push(`put ${chave}`);
    let tamanho = 0;
    for await (const bloco of corpo) tamanho += bloco.length;
    return { tamanho, sha256: "0".repeat(64) };
  }
  async get(chave: string): Promise<AsyncIterable<Uint8Array>> {
    this.chamadas.push(`get ${chave}`);
    return (async function* () {})();
  }
  async head(chave: string) {
    this.chamadas.push(`head ${chave}`);
    return this.info;
  }
  async delete(chave: string) {
    this.chamadas.push(`delete ${chave}`);
  }
  async list(prefixo: string, maximo: number) {
    this.chamadas.push(`list ${prefixo} ${maximo}`);
    return { itens: this.listagem, truncada: this.truncada };
  }
  async signUrl(chave: string, ttl: number) {
    this.chamadas.push(`signUrl ${chave} ${ttl}`);
    return `http://exemplo.invalid/${chave}`;
  }
}

function montar(): { motor: MotorEspiao; storage: ArmazenamentoPorTenant } {
  const motor = new MotorEspiao();
  return { motor, storage: new ArmazenamentoPorTenant(motor) };
}

const chaveDe = (tenant: string, classe = "audio"): string => `t/${tenant}/${classe}/2026/10/${ID}`;
const ref = (key: string): ObjectRef => ({ key, tamanho: 3, sha256: null });

// --- a forma -----------------------------------------------------------------

test("novaChave cunha t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}, com ano e mês em UTC", () => {
  // 31 de Dezembro às 23:30 de Luanda (UTC+1) ainda é Dezembro em UTC; às 00:30
  // de Luanda de 1 de Janeiro também. O mês da chave é o UTC.
  const key = novaChave(ctxA, "audio", new Date("2026-12-31T23:30:00.000Z"));
  assert.match(key, new RegExp(`^t/${A}/audio/2026/12/[0-9a-f-]{36}$`));
  const partes = partesDaChave(key);
  assert.deepEqual(
    { tenantId: partes.tenantId, classe: partes.classe, ano: partes.ano, mes: partes.mes },
    { tenantId: A, classe: "audio", ano: "2026", mes: "12" },
  );
  assert.match(novaChave(ctxA, "audio", new Date("2027-01-01T00:30:00.000+01:00")), /\/2026\/12\//);
  assert.match(novaChave(ctxA, "kyc_documento", new Date("2026-03-05T12:00:00Z")), /\/kyc_documento\/2026\/03\//);
});

test("novaChave não repete identificadores e não aceita classe nem data inválidas", () => {
  const chaves = new Set(Array.from({ length: 200 }, () => novaChave(ctxA, "audio")));
  assert.equal(chaves.size, 200);
  for (const classe of ["", "A", "a", "Audio", "áudio", "au dio", "au/dio", "..", "a".repeat(33), "1audio", 7]) {
    assert.throws(() => novaChave(ctxA, classe as string), MetaInvalidaError, `classe ${String(classe)}`);
  }
  assert.throws(() => novaChave(ctxA, "audio", new Date("isto não é uma data")), ChaveInvalidaError);
  assert.throws(() => novaChave({ tenantId: "" }, "audio"), CtxEmFaltaError);
});

/**
 * Tentativas de sair do prefixo. Todas começam por algo que parece do tenant A
 * ou que um servidor permissivo podia normalizar para outro sítio.
 */
const MAL_FORMADAS: readonly string[] = [
  "",
  "t",
  "t/",
  `t/${A}`,
  `t/${A}/`,
  `t/${A}/audio/2026/10`,
  `t/${A}/audio/2026/10/`,
  `t/${A}/audio/2026/10/${ID}/`,
  `t/${A}/audio/2026/10/${ID}/extra`,
  `/t/${A}/audio/2026/10/${ID}`,
  `t//${A}/audio/2026/10/${ID}`,
  `t/${A}//audio/2026/10/${ID}`,
  `t/${A}/audio/2026/10/../../../../${B}/audio/2026/10/${ID}`,
  `t/${A}/../${B}/audio/2026/10/${ID}`,
  `t/${A}/audio/../../${B}/2026/10/${ID}`,
  `t/${A}/audio/2026/10/..`,
  `t/${A}/audio/2026/10/%2e%2e`,
  `t/${A}%2faudio/2026/10/${ID}`,
  `t/${A}/audio/2026/10/${ID}%00`,
  `t/${A}/audio/2026/10/${ID}\u0000`,
  `t/${A}/audio/2026/10/${ID}\n`,
  `t/${A}/audio/2026/10/${ID} `,
  ` t/${A}/audio/2026/10/${ID}`,
  `t/${A}/audio/2026/10/${ID}?versionId=1`,
  `t/${A}/audio/2026/10/${ID}#x`,
  `T/${A}/audio/2026/10/${ID}`,
  `t/${A.toUpperCase()}/audio/2026/10/${ID}`,
  `t/${A}/AUDIO/2026/10/${ID}`,
  `t/${A}/audio/2026/10/${ID.toUpperCase()}`,
  `t/${A}/audio/2026/13/${ID}`,
  `t/${A}/audio/2026/00/${ID}`,
  `t/${A}/audio/2026/1/${ID}`,
  `t/${A}/audio/26/10/${ID}`,
  `t/${A}/audio/2026/10/nao-e-um-uuid`,
  `t/${A.replaceAll("-", "")}/audio/2026/10/${ID}`,
  `t/${A}/a/2026/10/${ID}`,
  `t/${A}/${"a".repeat(33)}/2026/10/${ID}`,
  `t/${A}/media/audio/2026/10/${ID}`,
  `t\\${A}\\audio\\2026\\10\\${ID}`,
  `x/${A}/audio/2026/10/${ID}`,
  `t/*/audio/2026/10/${ID}`,
];

test("uma chave que não é exactamente a forma canónica é recusada em todas as operações", async () => {
  for (const key of MAL_FORMADAS) {
    const { motor, storage } = montar();
    const nome = JSON.stringify(key);
    assert.throws(() => partesDaChave(key), ChaveInvalidaError, nome);
    await assert.rejects(storage.put(ctxA, key, new Uint8Array(1), META), ChaveInvalidaError, nome);
    await assert.rejects(storage.get(ctxA, ref(key)), ChaveInvalidaError, nome);
    await assert.rejects(storage.head(ctxA, ref(key)), ChaveInvalidaError, nome);
    await assert.rejects(storage.signUrl(ctxA, ref(key), { ttlSeconds: 60 }), ChaveInvalidaError, nome);
    await assert.rejects(storage.delete(ctxA, ref(key)), ChaveInvalidaError, nome);
    assert.deepEqual(motor.chamadas, [], `o motor não foi tocado por ${nome}`);
  }
});

test("o que não é texto não é chave: números, objectos, referências sem `key`", async () => {
  const { motor, storage } = montar();
  for (const key of [null, undefined, 7, {}, [], [chaveDe(A)], { toString: () => chaveDe(A) }]) {
    await assert.rejects(storage.get(ctxA, { key } as unknown as ObjectRef), ChaveInvalidaError);
    await assert.rejects(
      storage.put(ctxA, key as unknown as string, new Uint8Array(1), META),
      ChaveInvalidaError,
    );
  }
  for (const referencia of [null, undefined, "t/…", 7]) {
    await assert.rejects(storage.get(ctxA, referencia as unknown as ObjectRef), ChaveInvalidaError);
    await assert.rejects(storage.delete(ctxA, referencia as unknown as ObjectRef), ChaveInvalidaError);
  }
  assert.deepEqual(motor.chamadas, []);
});

test("a mensagem de uma chave recusada não repete a chave", () => {
  const segredoPorEngano = "valor-passado-por-engano-no-sitio-da-chave";
  for (const tentativa of [segredoPorEngano, `t/${A}/audio/2026/10/${segredoPorEngano}`]) {
    try {
      partesDaChave(tentativa);
      assert.fail("devia ter lançado");
    } catch (erro) {
      assert.ok(erro instanceof ChaveInvalidaError);
      assert.equal(erro.message.includes(segredoPorEngano), false);
    }
  }
});

// --- o dono ------------------------------------------------------------------

test("uma chave bem formada de outro tenant é recusada antes de o motor ser tocado", async () => {
  const { motor, storage } = montar();
  const deB = chaveDe(B);

  assert.throws(() => chaveDoCtx(ctxA, deB, "get"), ChaveForaDoTenantError);
  await assert.rejects(storage.put(ctxA, deB, new Uint8Array(1), META), ChaveForaDoTenantError);
  await assert.rejects(storage.get(ctxA, ref(deB)), ChaveForaDoTenantError);
  await assert.rejects(storage.head(ctxA, ref(deB)), ChaveForaDoTenantError);
  await assert.rejects(storage.signUrl(ctxA, ref(deB), { ttlSeconds: 60 }), ChaveForaDoTenantError);
  await assert.rejects(storage.delete(ctxA, ref(deB)), ChaveForaDoTenantError);
  assert.deepEqual(motor.chamadas, [], "nenhuma das seis tentativas chegou ao motor");

  // A metade positiva, no mesmo motor: com o contexto certo, chega.
  await storage.get(ctxB, ref(deB));
  await storage.signUrl(ctxB, ref(deB), { ttlSeconds: 60 });
  await storage.delete(ctxB, ref(deB));
  await storage.put(ctxB, deB, new Uint8Array(3), META);
  assert.deepEqual(motor.chamadas, [`get ${deB}`, `signUrl ${deB} 60`, `delete ${deB}`, `put ${deB}`]);
});

test("a recusa não diz de quem é a chave, nem se o objecto existe", async () => {
  const { storage } = montar();
  for (const operacao of [
    () => storage.get(ctxA, ref(chaveDe(B))),
    () => storage.signUrl(ctxA, ref(chaveDe(B)), { ttlSeconds: 60 }),
    () => storage.list(ctxA, prefixoDoTenant(ctxB)),
  ]) {
    try {
      await operacao();
      assert.fail("devia ter lançado");
    } catch (erro) {
      assert.ok(erro instanceof ChaveForaDoTenantError);
      assert.equal(erro.message.includes(B), false, "o tenant alheio não aparece na mensagem");
      assert.equal(erro.message.includes(ID), false);
    }
  }
});

test("dois tenants que diferem num só carácter não se confundem", async () => {
  const quase = `${A.slice(0, -1)}2`;
  const { motor, storage } = montar();
  await assert.rejects(storage.get(ctxA, ref(chaveDe(quase))), ChaveForaDoTenantError);
  await assert.rejects(storage.list(ctxA, `t/${quase}/`), ChaveForaDoTenantError);
  assert.deepEqual(motor.chamadas, []);
});

test("o contexto valida-se primeiro, e só aceita o UUID canónico em minúsculas", async () => {
  const { motor, storage } = montar();
  for (const tenantId of [undefined, null, ""]) {
    const ctx = { tenantId } as unknown as Ctx;
    assert.throws(() => tenantDoCtx(ctx), CtxEmFaltaError);
    // Mesmo com uma chave que também é inválida, o erro é o do contexto.
    await assert.rejects(storage.get(ctx, ref("lixo")), CtxEmFaltaError);
  }
  for (const tenantId of [
    A.toUpperCase(),
    A.replaceAll("-", ""),
    `{${A}}`,
    ` ${A}`,
    `${A}\n`,
    `${A}/`,
    "*",
    "..",
    7,
    {},
    [A],
  ]) {
    const ctx = { tenantId } as unknown as Ctx;
    assert.throws(() => tenantDoCtx(ctx), TenantInvalidoError, String(tenantId));
    await assert.rejects(storage.get(ctx, ref(chaveDe(A))), TenantInvalidoError);
    await assert.rejects(storage.list(ctx, `t/${A}/`), TenantInvalidoError);
  }
  assert.deepEqual(motor.chamadas, []);
  // A mensagem diz o tipo e o comprimento, não o valor.
  try {
    tenantDoCtx({ tenantId: "valor-que-nao-devia-aparecer" });
    assert.fail("devia ter lançado");
  } catch (erro) {
    assert.ok(erro instanceof TenantInvalidoError);
    assert.equal(erro.message.includes("valor-que-nao-devia-aparecer"), false);
  }
});

// --- o prefixo ---------------------------------------------------------------

test("um prefixo de listagem tem de começar por t/{ctx.tenantId}/, com a barra", async () => {
  const { motor, storage } = montar();
  for (const prefixo of [
    "",
    "t",
    "t/",
    `t/${A}`,
    `t/${A.slice(0, 8)}`,
    `t/${B}/`,
    `t/${B}/audio/`,
    `/t/${A}/`,
    `T/${A}/`,
    `x/${A}/`,
    `t/${A.toUpperCase()}/`,
  ]) {
    assert.throws(() => prefixoDoCtx(ctxA, prefixo), ChaveForaDoTenantError, JSON.stringify(prefixo));
    await assert.rejects(storage.list(ctxA, prefixo), ChaveForaDoTenantError, JSON.stringify(prefixo));
  }
  for (const prefixo of [
    `t/${A}/../${B}/`,
    `t/${A}/audio/../../${B}/`,
    `t/${A}//`,
    `t/${A}/audio//2026/`,
    `t/${A}/%2e%2e/`,
    `t/${A}/Audio/`,
    `t/${A}/audio/*`,
    `t/${A}/audio/ `,
    `t/${A}/audio/\u0000`,
    `t/${A}/${"a/".repeat(60)}`,
  ]) {
    assert.throws(() => prefixoDoCtx(ctxA, prefixo), ChaveInvalidaError, JSON.stringify(prefixo));
    await assert.rejects(storage.list(ctxA, prefixo), ChaveInvalidaError, JSON.stringify(prefixo));
  }
  for (const prefixo of [null, undefined, 7, {}]) {
    await assert.rejects(storage.list(ctxA, prefixo as unknown as string), ChaveInvalidaError);
  }
  assert.deepEqual(motor.chamadas, [], "nenhum prefixo recusado chegou ao motor");

  for (const prefixo of [`t/${A}/`, `t/${A}/audio/`, `t/${A}/audio/2026/`, `t/${A}/audio/2026/10/cccc`, `t/${A}/au`]) {
    assert.equal(prefixoDoCtx(ctxA, prefixo), prefixo);
  }
});

// --- a segunda camada --------------------------------------------------------

test("um motor que devolve chaves de outro tenant não as faz chegar a quem listou", async () => {
  const { motor, storage } = montar();
  const minha = chaveDe(A);

  // Metade positiva: uma listagem honesta passa.
  motor.listagem = [{ chave: minha, tamanho: 3 }];
  assert.deepEqual(await storage.list(ctxA, `t/${A}/`), [{ key: minha, tamanho: 3, sha256: null }]);

  for (const intrusa of [
    chaveDe(B),
    `t/${B}/`,
    `t/${A.slice(0, -1)}2/audio/2026/10/${ID}`,
    `x${minha}`,
    "",
    `T/${A}/audio/2026/10/${ID}`,
  ]) {
    motor.listagem = [
      { chave: minha, tamanho: 3 },
      { chave: intrusa, tamanho: 9 },
    ];
    // Falha inteira: não devolve «as boas», porque isso esconderia o defeito.
    await assert.rejects(storage.list(ctxA, `t/${A}/`), RespostaDoMotorInvalidaError, JSON.stringify(intrusa));
  }

  // Dentro do tenant mas fora do prefixo pedido também é uma resposta errada.
  motor.listagem = [{ chave: chaveDe(A, "imagem"), tamanho: 1 }];
  await assert.rejects(storage.list(ctxA, `t/${A}/audio/`), RespostaDoMotorInvalidaError);

  motor.listagem = [{ chave: 7 as unknown as string, tamanho: 1 }];
  await assert.rejects(storage.list(ctxA, `t/${A}/`), RespostaDoMotorInvalidaError);
});

test("head recusa um objecto cujos metadados não batem com a chave ou não se lêem", async () => {
  const { motor, storage } = montar();
  const key = chaveDe(A);

  const info = await storage.head(ctxA, ref(key));
  assert.equal(info.classe, "audio");
  assert.equal(info.retainUntil.toISOString(), PRAZO.toISOString());

  for (const metadados of [
    { classe: "imagem", "retain-until": PRAZO.toISOString() },
    { "retain-until": PRAZO.toISOString() },
    { classe: "audio" },
    { classe: "audio", "retain-until": "amanhã" },
    { classe: "audio", "retain-until": "" },
    // O `Date` do JavaScript lê estas três; a porta não, para recusar o mesmo
    // que o lado Python recusa.
    { classe: "audio", "retain-until": "2026-10-13" },
    { classe: "audio", "retain-until": "2026-10-13T08:30:00" },
    { classe: "audio", "retain-until": "13 Oct 2026 08:30:00 GMT" },
    { classe: "audio", "retain-until": "2026-13-45T99:99:99Z" },
    {},
  ] as Record<string, string>[]) {
    motor.info = { tamanho: 3, contentType: "audio/ogg", metadados };
    await assert.rejects(storage.head(ctxA, ref(key)), RespostaDoMotorInvalidaError, JSON.stringify(metadados));
  }
});

// --- metadados na escrita ----------------------------------------------------

test("put exige classe igual à da chave, tipo de conteúdo e retainUntil válidos", async () => {
  const { motor, storage } = montar();
  const key = chaveDe(A);
  const corpo = new Uint8Array(3);

  for (const meta of [
    { ...META, classe: "imagem" },
    { ...META, classe: "Audio" },
    { ...META, classe: undefined },
    { ...META, contentType: "" },
    { ...META, contentType: "audio" },
    { ...META, contentType: "audio/ogg\r\nx-amz-meta-classe: imagem" },
    { ...META, contentType: "audio/ogg\nx-injectado: 1" },
    { ...META, contentType: 7 },
    { ...META, retainUntil: undefined },
    { ...META, retainUntil: null },
    { ...META, retainUntil: new Date("lixo") },
    { ...META, retainUntil: "2026-10-13T08:30:00Z" },
    { ...META, retainUntil: 1791880200000 },
    null,
    undefined,
    "audio",
  ]) {
    await assert.rejects(
      storage.put(ctxA, key, corpo, meta as never),
      MetaInvalidaError,
      JSON.stringify(meta),
    );
  }
  await assert.rejects(storage.put(ctxA, key, "texto" as never, META), MetaInvalidaError);
  await assert.rejects(storage.put(ctxA, key, null as never, META), MetaInvalidaError);
  assert.deepEqual(motor.chamadas, [], "nenhum put recusado chegou ao motor");

  const escrito = await storage.put(ctxA, key, corpo, { ...META, contentType: "audio/ogg; codecs=opus" });
  assert.deepEqual(escrito, { key, tamanho: 3, sha256: "0".repeat(64) });
});

test("list valida o limite e passa-o ao motor", async () => {
  const { motor, storage } = montar();
  for (const limite of [0, -1, 1.5, 10_001, Number.NaN, "7", true, {}]) {
    await assert.rejects(
      storage.list(ctxA, `t/${A}/`, { limite: limite as number }),
      MetaInvalidaError,
      String(limite),
    );
  }
  assert.deepEqual(motor.chamadas, []);
  await storage.list(ctxA, `t/${A}/`);
  await storage.list(ctxA, `t/${A}/`, { limite: 7 });
  // Sem opções, ou com opções vazias, vale o limite por omissão.
  await storage.list(ctxA, `t/${A}/`, null as never);
  await storage.list(ctxA, `t/${A}/`, {});
  assert.deepEqual(motor.chamadas, [
    `list t/${A}/ 1000`,
    `list t/${A}/ 7`,
    `list t/${A}/ 1000`,
    `list t/${A}/ 1000`,
  ]);
});

test("o nome da porta é o do motor", () => {
  assert.equal(montar().storage.nome, "espiao");
});
