/**
 * O painel do dono (KAM-099), pela superfície HTTP.
 *
 * As baterias submetem pedidos e contam o que chega ao COM — o duplo
 * `ComercioEmMemoria` guarda cada gravação com o tenant e o actor. É a ligação
 * que se mede: um *refactor* que lesse o tenant de outro sítio que não a sessão
 * punha os casos de isolamento vermelhos, porque o duplo só encontra o `sku` no
 * mapa do tenant que recebe.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { gzipSync } from "node:zlib";

import { cunharReferencia, NOME_DO_COOKIE } from "@kamba/core-ts/inscricao";

import { createApp } from "../src/app.ts";
import { CanalEmMemoria } from "../src/painel/canal.ts";
import {
  ComercioEmMemoria,
  ComercioPorHttp,
  ESTADOS_DA_ENCOMENDA,
  type Encomenda,
  type Oferta,
} from "../src/painel/comercio.ts";
import { Idempotencia } from "../src/painel/idempotencia.ts";
import { MetricasDoPainel } from "../src/painel/metricas.ts";
import { rotasDoPainel, type OpcoesDoPainel } from "../src/painel/rotas.ts";
import {
  NOME_DO_COOKIE_DO_PAINEL,
  RevogacoesEmMemoria,
  cunharSessao,
  lerSessao,
  novaSessao,
  type Revogacoes,
  type SessaoDoPainel,
} from "../src/painel/sessao.ts";
import { lerPedido, pedeConfirmacao, precoMaximoKz, variacaoPct } from "../src/painel/validacao.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CASO_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a";
const CASO_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";
const ORDEM_B = "0e0e0e0e-0e0e-4e0e-8e0e-0e0e0e0e0e0e";
const ORDEM_A = "0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f";
const CHAVE = new Uint8Array(32).fill(7);
const OUTRA_CHAVE = new Uint8Array(32).fill(9);
const V0 = "2026-11-02T11:00:00.000001Z";
const INICIO = new Date("2026-11-10T09:00:00.000Z");

function oferta(sku: string, extra: Partial<Oferta> = {}): Oferta {
  return {
    sku,
    nome: `Produto ${sku}`,
    precoTipo: "fixo",
    precoMinor: 1_000_000n,
    currency: "AOA",
    stockModo: "indicativo",
    stockQuantidade: 12,
    stockReservada: 0,
    estado: "publicado",
    versao: V0,
    ...extra,
  };
}

function encomenda(orderId: string, extra: Partial<Encomenda> = {}): Encomenda {
  return {
    orderId,
    numeroPublico: "K7H3Q1",
    estado: "aguarda_pagamento",
    totalMinor: 2_500_000n,
    currency: "AOA",
    criadoAt: "2026-11-09T10:00:00.000Z",
    contactId: "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e",
    ...extra,
  };
}

interface Montagem {
  readonly app: ReturnType<typeof rotasDoPainel>;
  readonly comercio: ComercioEmMemoria;
  readonly revogacoes: RevogacoesEmMemoria;
  readonly metricas: MetricasDoPainel;
  readonly canal: CanalEmMemoria;
  agora: Date;
}

function montar(extra: Partial<OpcoesDoPainel> = {}): Montagem {
  const comercio = new ComercioEmMemoria();
  comercio.semear(TENANT_A, [oferta("arroz"), oferta("sabao")], [encomenda(ORDEM_A)]);
  comercio.semear(TENANT_B, [oferta("so-de-b")], [encomenda(ORDEM_B, { numeroPublico: "B00001" })]);
  const revogacoes = new RevogacoesEmMemoria();
  const metricas = new MetricasDoPainel();
  const canal = new CanalEmMemoria();
  const casos = new Map([
    [CASO_A, { tenantId: TENANT_A, fase: "activo" }],
    [CASO_B, { tenantId: TENANT_B, fase: "kyc_pendente" }],
  ]);
  const m: Montagem = {
    comercio,
    revogacoes,
    metricas,
    canal,
    agora: INICIO,
    app: undefined as unknown as Montagem["app"],
  };
  (m as { app: Montagem["app"] }).app = rotasDoPainel({
    comercio,
    canal,
    revogacoes,
    metricas,
    casos: { porId: async (id) => casos.get(id) ?? null },
    anelDaAssinatura: [CHAVE, null],
    relogio: () => m.agora,
    ...extra,
  });
  return m;
}

function cookieDe(s: SessaoDoPainel, chave = CHAVE): string {
  return `${NOME_DO_COOKIE_DO_PAINEL}=${cunharSessao(s, chave)}`;
}

function sessaoA(agora = INICIO): SessaoDoPainel {
  return novaSessao(TENANT_A, CASO_A, agora);
}

let contador = 0;
function chave(): string {
  contador += 1;
  return `chave-de-ensaio-${String(contador).padStart(6, "0")}`;
}

function patch(sku: string, corpo: unknown, cookie: string, idem = chave(), extra: Record<string, string> = {}): Request {
  return new Request(`http://127.0.0.1/painel/produtos/${encodeURIComponent(sku)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json", cookie, "idempotency-key": idem, ...extra },
    body: JSON.stringify(corpo),
  });
}

function get(caminho: string, cookie: string): Request {
  return new Request(`http://127.0.0.1${caminho}`, { headers: { cookie } });
}

// --------------------------------------------------------------- a entrada

test("criterio 1: sem a sessao do OTP a entrada e 401, e nao cunha nada", async () => {
  const m = montar();
  const r = await m.app.fetch(get("/painel/entrar", ""));
  assert.equal(r.status, 401);
  assert.equal(r.headers.get("set-cookie"), null);
});

test("criterio 1: com a sessao do OTP de um caso activo, a entrada cunha a sessao do painel do tenant do caso", async () => {
  const m = montar();
  const sessao = cunharReferencia("sessao", CASO_A, CHAVE, () => INICIO);
  const r = await m.app.fetch(get("/painel/entrar", `${NOME_DO_COOKIE}=${sessao}`));
  assert.equal(r.status, 303);
  const cookie = r.headers.get("set-cookie") ?? "";
  assert.match(cookie, /^kamba_painel=/);
  assert.match(cookie, /HttpOnly; Secure; SameSite=Lax; Path=\/; Max-Age=2592000/);
  const valor = cookie.split(";")[0]?.split("=")[1];
  const lida = lerSessao(valor, [CHAVE], INICIO);
  assert.equal(lida?.tenantId, TENANT_A);
  assert.equal(lida?.dono, CASO_A);
});

test("criterio 1: um caso antes do provisionamento nao abre o painel", async () => {
  const m = montar();
  const sessao = cunharReferencia("sessao", CASO_B, CHAVE, () => INICIO);
  const r = await m.app.fetch(get("/painel/entrar", `${NOME_DO_COOKIE}=${sessao}`));
  assert.equal(r.status, 401);
});

test("criterio 1: a sessao do registo nao serve de sessao do painel, nem o contrario", async () => {
  const m = montar();
  const doRegisto = cunharReferencia("sessao", CASO_A, CHAVE, () => INICIO);
  const r = await m.app.fetch(get("/painel/produtos", `${NOME_DO_COOKIE_DO_PAINEL}=${doRegisto}`));
  assert.equal(r.status, 401);
  const doPainel = cunharSessao(sessaoA(), CHAVE);
  const e = await m.app.fetch(get("/painel/entrar", `${NOME_DO_COOKIE}=${doPainel}`));
  assert.equal(e.status, 401);
});

test("criterio 1: uma sessao com o tenant trocado ou assinada por outra chave e recusada", async () => {
  const m = montar();
  const boa = cunharSessao(sessaoA(), CHAVE);
  const trocada = boa.replace(TENANT_A, TENANT_B);
  for (const valor of [trocada, cunharSessao(sessaoA(), OUTRA_CHAVE), "v1.lixo", ""]) {
    const r = await m.app.fetch(get("/painel/produtos", `${NOME_DO_COOKIE_DO_PAINEL}=${valor}`));
    assert.equal(r.status, 401, valor);
  }
});

// ------------------------------------------------------- isolamento (critério 8)

test("criterio 8: a lista de produtos so mostra os do tenant da sessao", async () => {
  const m = montar();
  const corpo = await (await m.app.fetch(get("/painel/produtos", cookieDe(sessaoA())))).text();
  assert.match(corpo, /data-sku="arroz"/);
  assert.doesNotMatch(corpo, /so-de-b/);
});

test("criterio 8: IDOR — o dono de A grava o sku de B e recebe 404, e B nao muda", async () => {
  const m = montar();
  const r = await m.app.fetch(patch("so-de-b", { preco_tipo: "fixo", preco_minor: "100", versao: V0 }, cookieDe(sessaoA())));
  assert.equal(r.status, 404);
  assert.deepEqual(await r.json(), { erro: "nao_encontrado" });
  assert.equal(m.comercio.gravacoes.length, 0);
  assert.equal(m.comercio.ofertas.get(TENANT_B)?.get("so-de-b")?.precoMinor, 1_000_000n);
});

test("criterio 8: o 404 de um recurso de B e igual ao de um recurso que nao existe", async () => {
  const m = montar();
  const deB = await m.app.fetch(get(`/painel/encomendas/${ORDEM_B}`, cookieDe(sessaoA())));
  const inexistente = await m.app.fetch(get("/painel/encomendas/01010101-0101-4101-8101-010101010101", cookieDe(sessaoA())));
  assert.equal(deB.status, 404);
  assert.equal(inexistente.status, 404);
  const semNonce = (t: string) => t.replace(/nonce="[0-9a-f]+"/g, "");
  assert.equal(semNonce(await deB.text()), semNonce(await inexistente.text()));
});

test("criterio 8: o tenant vem da sessao e nunca do pedido — cabecalho, consulta e corpo de B sao ignorados", async () => {
  const m = montar();
  const r = await m.app.fetch(
    new Request(`http://127.0.0.1/painel/produtos/arroz?tenant_id=${TENANT_B}`, {
      method: "PATCH",
      headers: {
        "content-type": "application/json",
        cookie: cookieDe(sessaoA()),
        "idempotency-key": chave(),
        "x-kamba-tenant": TENANT_B,
      },
      body: JSON.stringify({ preco_tipo: "fixo", preco_minor: "1200000", versao: V0, tenant_id: TENANT_B }),
    }),
  );
  assert.equal(r.status, 200);
  assert.deepEqual(m.comercio.gravacoes, [{ tenantId: TENANT_A, sku: "arroz", actor: CASO_A }]);
});

test("criterio 8: sem sessao nenhuma rota le nada, e todas respondem 401", async () => {
  const m = montar();
  for (const caminho of ["/painel/produtos", "/painel/encomendas", `/painel/encomendas/${ORDEM_A}`, "/painel/canal"]) {
    const r = await m.app.fetch(get(caminho, ""));
    assert.equal(r.status, 401, caminho);
    assert.doesNotMatch(await r.text(), /arroz|K7H3Q1/);
  }
  const p = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "100", versao: V0 }, ""));
  assert.equal(p.status, 401);
  assert.equal(m.comercio.gravacoes.length, 0);
});

test("criterio 8: o adaptador HTTP poe o tenant da sessao no x-kamba-tenant, e um TENANT_MISMATCH e 404", async () => {
  const vistos: { url: string; init: RequestInit }[] = [];
  const com = new ComercioPorHttp("http://com:3002/", "cred", async (url, init) => {
    vistos.push({ url, init });
    return new Response(JSON.stringify({ tipo: "erro", erro: "TENANT_MISMATCH" }), { status: 403 });
  });
  const r = await com.obterEncomenda(TENANT_A, { id: CASO_A, traceId: "t" }, ORDEM_B);
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  const h = vistos[0]?.init.headers as Record<string, string>;
  assert.equal(vistos[0]?.url, "http://com:3002/internal/get-order");
  assert.equal(h["x-kamba-tenant"], TENANT_A);
  assert.equal(h["x-kamba-interno"], "cred");
  const corpo = JSON.parse(String(vistos[0]?.init.body)) as Record<string, unknown>;
  assert.deepEqual(corpo["actor"], { kind: "dono", id: CASO_A });
});

test("o adaptador HTTP passa o preco como cadeia e le-o como bigint, e uma rede em baixo e UPSTREAM_DOWN", async () => {
  let corpo: Record<string, unknown> = {};
  const com = new ComercioPorHttp("http://com:3002", "cred", async (_u, init) => {
    corpo = JSON.parse(String(init.body)) as Record<string, unknown>;
    return new Response(JSON.stringify({ tipo: "ok", valor: { ...oferta("arroz"), precoMinor: "1500000" } }));
  });
  const r = await com.alterarOferta(TENANT_A, { id: CASO_A, traceId: "t" }, {
    sku: "arroz", precoTipo: "fixo", precoMinor: 1_500_000n, versao: V0, stock: 3,
  });
  assert.equal(corpo["preco_minor"], "1500000");
  assert.equal(corpo["stock"], 3);
  assert.equal(r.tipo === "ok" ? r.valor.precoMinor : null, 1_500_000n);
  const caido = new ComercioPorHttp("http://com:3002", "cred", async () => {
    throw new Error("ECONNREFUSED");
  });
  assert.deepEqual(await caido.listarOfertas(TENANT_A, { id: CASO_A, traceId: "t" }), { tipo: "erro", erro: "UPSTREAM_DOWN" });
});

// ----------------------------------------------------- escrita (critérios 3 e 5)

test("criterio 3: gravar o preco chega ao COM com o actor dono e devolve a versao nova", async () => {
  const m = montar();
  const r = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1200000", versao: V0 }, cookieDe(sessaoA())));
  assert.equal(r.status, 200);
  const corpo = (await r.json()) as { versao: string; oferta: { precoMinor: string } };
  assert.notEqual(corpo.versao, V0);
  assert.equal(corpo.oferta.precoMinor, "1200000");
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("conflito: com a versao velha a resposta e 409 com a versao actual", async () => {
  const m = montar();
  const cookie = cookieDe(sessaoA());
  assert.equal((await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1100000", versao: V0 }, cookie))).status, 200);
  const r = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1050000", versao: V0 }, cookie));
  assert.equal(r.status, 409);
  const corpo = (await r.json()) as { erro: string; versao: string };
  assert.equal(corpo.erro, "conflito");
  assert.notEqual(corpo.versao, V0);
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("idempotencia: a mesma Idempotency-Key duas vezes da uma gravacao, e a segunda diz que repetiu", async () => {
  const m = montar();
  const idem = chave();
  const corpo = { preco_tipo: "fixo", preco_minor: "1200000", versao: V0 };
  const r1 = await m.app.fetch(patch("arroz", corpo, cookieDe(sessaoA()), idem));
  const r2 = await m.app.fetch(patch("arroz", corpo, cookieDe(sessaoA()), idem));
  assert.equal(r1.status, 200);
  assert.equal(r2.status, 200);
  assert.equal(r2.headers.get("idempotent-replayed"), "true");
  assert.deepEqual(await r1.json(), await r2.json());
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("idempotencia: dois pedidos simultaneos com a mesma chave gravam uma vez", async () => {
  const m = montar();
  const idem = chave();
  const corpo = { preco_tipo: "fixo", preco_minor: "1200000", versao: V0 };
  const respostas = await Promise.all([1, 2, 3].map(() => m.app.fetch(patch("arroz", corpo, cookieDe(sessaoA()), idem))));
  assert.deepEqual(respostas.map((r) => r.status), [200, 200, 200]);
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("idempotencia: a mesma chave com outro corpo e 422 e nao grava", async () => {
  const m = montar();
  const idem = chave();
  await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1200000", versao: V0 }, cookieDe(sessaoA()), idem));
  const r = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "90000", versao: V0 }, cookieDe(sessaoA()), idem));
  assert.equal(r.status, 422);
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("idempotencia: a chave e por tenant — a de A nao devolve a resposta a B", async () => {
  const idem = new Idempotencia(() => 0);
  let corridas = 0;
  const fazer = async () => ({ estado: 200, corpo: { n: (corridas += 1) } });
  await idem.uma(TENANT_A, "k".repeat(16), "x", fazer);
  const deB = await idem.uma(TENANT_B, "k".repeat(16), "x", fazer);
  assert.equal(deB.tipo, "nova");
  assert.equal(corridas, 2);
});

test("idempotencia: sem chave, ou com uma chave curta, e 400", async () => {
  const m = montar();
  for (const idem of ["", "curta"]) {
    const r = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "100", versao: V0 }, cookieDe(sessaoA()), idem));
    assert.equal(r.status, 400, idem);
  }
  assert.equal(m.comercio.gravacoes.length, 0);
});

test("criterio 5: precos e stocks invalidos sao 400 com o campo, e nada chega ao COM", async () => {
  const m = montar({ precoMaximoKz: 50_000n });
  const maus = [
    { preco_tipo: "fixo", preco_minor: "-100", versao: V0 },
    { preco_tipo: "fixo", preco_minor: "1250.5", versao: V0 },
    { preco_tipo: "fixo", preco_minor: "5000100", versao: V0 },
    { preco_tipo: "fixo", preco_minor: "1250050", versao: V0 },
    { preco_tipo: "fixo", versao: V0 },
    { preco_tipo: "sob_consulta", preco_minor: "1000", versao: V0 },
    { preco_tipo: "preco_modo", preco_minor: "1000", versao: V0 },
    { preco_tipo: "fixo", preco_minor: "1000", stock: -1, versao: V0 },
    { preco_tipo: "fixo", preco_minor: "1000", stock: 1.5, versao: V0 },
    { preco_tipo: "fixo", preco_minor: "1000" },
  ];
  for (const corpo of maus) {
    const r = await m.app.fetch(patch("arroz", corpo, cookieDe(sessaoA())));
    assert.equal(r.status, 400, JSON.stringify(corpo));
  }
  assert.equal(m.comercio.gravacoes.length, 0);
});

test("criterio 5: o preco maximo le-se do ambiente, e um valor ilegivel falha o arranque", () => {
  assert.equal(precoMaximoKz(undefined), 100_000_000n);
  assert.equal(precoMaximoKz(" 5000 "), 5000n);
  for (const mau of ["0", "-3", "1e6", "abc"]) assert.throws(() => precoMaximoKz(mau), mau);
});

test("criterio 5: uma variacao acima de 50% pede confirmacao, e com ela grava", async () => {
  const m = montar();
  const cookie = cookieDe(sessaoA());
  const semConfirmar = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1500100", versao: V0 }, cookie));
  assert.equal(semConfirmar.status, 422);
  assert.deepEqual(await semConfirmar.json(), { erro: "confirmacao", variacao_pct: "51" });
  assert.equal(m.comercio.gravacoes.length, 0);
  const confirmada = await m.app.fetch(
    patch("arroz", { preco_tipo: "fixo", preco_minor: "1500100", versao: V0, confirmar_variacao: true }, cookie),
  );
  assert.equal(confirmada.status, 200);
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("criterio 5: a fronteira dos 50% — exactamente 50% nao pede, e a descida tambem conta", () => {
  assert.equal(pedeConfirmacao(1_000_000n, 1_500_000n), false);
  assert.equal(pedeConfirmacao(1_000_000n, 1_500_100n), true);
  assert.equal(pedeConfirmacao(1_000_000n, 499_900n), true);
  assert.equal(pedeConfirmacao(null, 1_000n), false);
  assert.equal(variacaoPct(0n, 100n), 1_000_000n);
  assert.equal(lerPedido({ preco_tipo: "fixo", preco_minor: 1200, versao: V0 }, 100n).tipo, "ok");
});

test("criterio 5: o pedido sem application/json e 415, e um corpo grande e 400", async () => {
  const m = montar();
  const r = await m.app.fetch(
    new Request("http://127.0.0.1/painel/produtos/arroz", {
      method: "PATCH",
      headers: { "content-type": "text/plain", cookie: cookieDe(sessaoA()), "idempotency-key": chave() },
      body: "preco_tipo=fixo",
    }),
  );
  assert.equal(r.status, 415);
  const grande = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "100", versao: V0, x: "a".repeat(5000) }, cookieDe(sessaoA())));
  assert.equal(grande.status, 400);
  assert.equal(m.comercio.gravacoes.length, 0);
});

// --------------------------------------------------------- revogação e renovação

test("revogacao: depois de sair, a mesma sessao da 401 em tudo", async () => {
  const m = montar();
  const cookie = cookieDe(sessaoA());
  const sair = await m.app.fetch(new Request("http://127.0.0.1/painel/sair", { method: "POST", headers: { cookie } }));
  assert.equal(sair.status, 200);
  assert.match(sair.headers.get("set-cookie") ?? "", /Max-Age=0/);
  assert.equal((await m.app.fetch(get("/painel/produtos", cookie))).status, 401);
  assert.equal((await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1200000", versao: V0 }, cookie))).status, 401);
  assert.equal(m.comercio.gravacoes.length, 0);
});

test("revogacao: um PATCH a meio quando a sessao e revogada nao grava", async () => {
  // A revogação chega **enquanto** o painel lê a lista para o critério dos 50%:
  // o pedido passou pela primeira verificação e tem de parar na segunda.
  const revogacoes = new RevogacoesEmMemoria();
  const s = sessaoA();
  const m = montar({ revogacoes });
  const original = m.comercio.listarOfertas.bind(m.comercio);
  m.comercio.listarOfertas = async (t: string) => {
    await revogacoes.revogar(s.sid);
    return original(t);
  };
  const r = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1200000", versao: V0 }, cookieDe(s)));
  assert.equal(r.status, 401);
  assert.equal(m.comercio.gravacoes.length, 0);
});

test("revogacao: revogar o tenant ate um instante leva todas as sessoes emitidas ate ele", async () => {
  const revogacoes: Revogacoes = new RevogacoesEmMemoria();
  const velha = sessaoA(INICIO);
  const nova = sessaoA(new Date(INICIO.getTime() + 60_000));
  await revogacoes.revogarDoTenant(TENANT_A, velha.emitida);
  assert.equal(await revogacoes.revogada(velha), true);
  assert.equal(await revogacoes.revogada(nova), false);
});

test("renovacao: depois de um dia a resposta traz a sessao renovada, com o mesmo sid", async () => {
  const m = montar();
  const s = sessaoA();
  m.agora = new Date(INICIO.getTime() + 2 * 24 * 3600 * 1000);
  const r = await m.app.fetch(get("/painel/produtos", cookieDe(s)));
  assert.equal(r.status, 200);
  const valor = (r.headers.get("set-cookie") ?? "").split(";")[0]?.split("=")[1];
  const renovada = lerSessao(valor, [CHAVE], m.agora);
  assert.equal(renovada?.sid, s.sid);
  assert.equal(renovada?.emitida, s.emitida);
  assert.ok((renovada?.renovada ?? 0) > s.renovada);
});

test("renovacao: no primeiro dia nao se renova", async () => {
  const m = montar();
  const r = await m.app.fetch(get("/painel/produtos", cookieDe(sessaoA())));
  assert.equal(r.headers.get("set-cookie"), null);
});

test("renovacao: uma sessao revogada nao se renova, e a renovada de uma revogada tambem e recusada", async () => {
  const m = montar();
  const s = sessaoA();
  await m.revogacoes.revogar(s.sid);
  m.agora = new Date(INICIO.getTime() + 2 * 24 * 3600 * 1000);
  const r = await m.app.fetch(get("/painel/produtos", cookieDe(s)));
  assert.equal(r.status, 401);
  assert.equal(r.headers.get("set-cookie"), null);
  // Uma renovada cunhada à mão (o mesmo `sid`) continua revogada.
  const renovadaAMao = { ...s, renovada: Math.floor(m.agora.getTime() / 1000) };
  assert.equal((await m.app.fetch(get("/painel/produtos", cookieDe(renovadaAMao)))).status, 401);
});

test("renovacao: uma sessao expirada (30 dias sem uso) nao se renova, e o tecto de 90 dias vale mesmo renovando", async () => {
  const m = montar();
  const s = sessaoA();
  m.agora = new Date(INICIO.getTime() + 31 * 24 * 3600 * 1000);
  const expirada = await m.app.fetch(get("/painel/produtos", cookieDe(s)));
  assert.equal(expirada.status, 401);
  assert.equal(expirada.headers.get("set-cookie"), null);
  m.agora = new Date(INICIO.getTime() + 91 * 24 * 3600 * 1000);
  const renovadaOntem = { ...s, renovada: Math.floor(m.agora.getTime() / 1000) - 3600 };
  assert.equal((await m.app.fetch(get("/painel/produtos", cookieDe(renovadaOntem)))).status, 401);
});

// ----------------------------------------------------------- páginas

test("adversarial: XSS no nome do produto sai escapado", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [oferta("x\"'><svg>", { nome: "<script>alert(1)</script>" })]);
  const corpo = await (await m.app.fetch(get("/painel/produtos", cookieDe(sessaoA())))).text();
  assert.doesNotMatch(corpo, /<script>alert/);
  assert.match(corpo, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(corpo, /data-sku="x&quot;&#39;&gt;&lt;svg&gt;"/);
});

test("criterio 9: a pagina dos produtos cabe em 200 KB comprimida, e nao tem scripts de terceiros", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, Array.from({ length: 200 }, (_, i) => oferta(`sku-${i}`, { nome: `Produto com nome longo ${i}` })));
  const r = await m.app.fetch(get("/painel/produtos", cookieDe(sessaoA())));
  const corpo = await r.text();
  const comprimida = gzipSync(Buffer.from(corpo, "utf8")).length;
  assert.ok(comprimida <= 200 * 1024, `${comprimida} octetos`);
  assert.doesNotMatch(corpo, /<script[^>]+src=/);
  assert.match(r.headers.get("content-security-policy") ?? "", /default-src 'none'/);
  assert.match(corpo, /lang="pt-AO"/);
});

test("criterio 6: as encomendas filtram por estado e por data, e nao mostram o contacto", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [
    encomenda(ORDEM_A, { numeroPublico: "K00001", criadoAt: "2026-11-01T10:00:00.000Z" }),
    encomenda("0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c", { numeroPublico: "K00002", criadoAt: "2026-11-08T10:00:00.000Z" }),
    encomenda("0d0d0d0d-0d0d-4d0d-8d0d-0d0d0d0d0d0d", { numeroPublico: "K00003", estado: "paga" }),
  ]);
  const corpo = await (await m.app.fetch(get("/painel/encomendas?estado=aguarda_pagamento&desde=2026-11-05", cookieDe(sessaoA())))).text();
  assert.match(corpo, /K00002/);
  assert.doesNotMatch(corpo, /K00001|K00003/);
  assert.doesNotMatch(corpo, /7c1d5e3a/);
  assert.match(corpo, /25 000 Kz/);
  const mau = await m.app.fetch(get("/painel/encomendas?estado=inventado", cookieDe(sessaoA())));
  assert.equal(mau.status, 400);
});

test("criterio 7: o canal mostra estado, nivel e tecto, com a ligacao de reconexao quando desligado", async () => {
  const m = montar();
  m.canal.vistas.set(TENANT_A, { estado: "desligado", nivel: "restrito", tecto: 250, avisos: ["canal_desligado"] });
  const corpo = await (await m.app.fetch(get("/painel/canal", cookieDe(sessaoA())))).text();
  assert.match(corpo, /Desligado/);
  assert.match(corpo, /restrito/);
  assert.match(corpo, /250/);
  assert.match(corpo, /href="\/ligar"/);
  assert.match(corpo, /canal_desligado/);
});

// ------------------------------------------------------- o resto da ligação

test("as metricas contam uso e erros, sem tenant em etiqueta", async () => {
  const m = montar();
  await m.app.fetch(get("/painel/produtos", ""));
  await m.app.fetch(get("/painel/produtos", cookieDe(sessaoA())));
  assert.equal(m.metricas.valor("produtos"), 2);
  assert.equal(m.metricas.valor("produtos", "sem_sessao"), 1);
  const exposicao = m.metricas.exposicao();
  assert.match(exposicao, /# TYPE painel_pedidos_total counter/);
  assert.doesNotMatch(exposicao, new RegExp(TENANT_A));
});

test("os estados da encomenda do painel sao os da porta do COM, pela mesma ordem", () => {
  const porta = readFileSync(new URL("../../com/src/port/contrato.ts", import.meta.url), "utf8");
  const bloco = /export const ORDER_STATES = \[([\s\S]*?)\] as const;/.exec(porta)?.[1] ?? "";
  const daPorta = [...bloco.matchAll(/"([a-z_]+)"/g)].map((x) => x[1]);
  assert.deepEqual([...ESTADOS_DA_ENCOMENDA], daPorta);
});

test("sem a inscricao montada o painel nao e servido", async () => {
  const m = montar();
  const app = createApp(undefined, undefined, undefined, {
    comercio: m.comercio,
    canal: m.canal,
    revogacoes: m.revogacoes,
    casos: { porId: async () => null },
    anelDaAssinatura: [CHAVE, null],
  });
  assert.equal((await app.fetch(get("/painel/produtos", cookieDe(sessaoA())))).status, 404);
});
