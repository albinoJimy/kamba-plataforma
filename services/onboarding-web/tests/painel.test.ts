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

import { GuiaRecusadoError } from "@kamba/core-ts/guia";
import { cunharReferencia, lerReferencia, NOME_DO_COOKIE, ReferenciaInvalidaError, Telefone } from "@kamba/core-ts/inscricao";

import { createApp } from "../src/app.ts";
import { CanalEmMemoria, CanalPeloCom, SEM_CANAL, type VistaDoCanal } from "../src/painel/canal.ts";
import {
  ComercioEmMemoria,
  ComercioPorHttp,
  ESTADOS_COM_CONTACTO,
  ESTADOS_DA_ENCOMENDA,
  type Encomenda,
  type Oferta,
} from "../src/painel/comercio.ts";
import { Idempotencia } from "../src/painel/idempotencia.ts";
import { MetricasDoPainel } from "../src/painel/metricas.ts";
import {
  inicioDoDiaEmLuanda,
  LIMITE_POR_REDE,
  rotasDoPainel,
  type OpcoesDaReentrada,
  type OpcoesDoPainel,
} from "../src/painel/rotas.ts";
import {
  NOME_DO_COOKIE_DO_PAINEL,
  RevogacoesEmMemoria,
  cunharBilhete,
  cunharSessao,
  lerBilhete,
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
  readonly casos: Map<string, { tenantId: string; fase: string }>;
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
    casos,
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
  assert.match(corpo, /href="\/painel\/produtos\/arroz"/);
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
  const original = m.comercio.obterOferta.bind(m.comercio);
  m.comercio.obterOferta = async (t, a, sku) => {
    await revogacoes.revogar(s);
    return original(t, a, sku);
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
  await m.revogacoes.revogar(s);
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

test("adversarial: XSS no nome do produto sai escapado, na lista e na pagina do produto", async () => {
  const m = montar();
  const sku = "x\"'><svg>";
  m.comercio.semear(TENANT_A, [oferta(sku, { nome: "<script>alert(1)</script>" })]);
  const corpo = await (await m.app.fetch(get("/painel/produtos", cookieDe(sessaoA())))).text();
  assert.doesNotMatch(corpo, /<script>alert/);
  assert.match(corpo, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(corpo, /<svg>/);
  const produto = await (await m.app.fetch(get(`/painel/produtos/${encodeURIComponent(sku)}`, cookieDe(sessaoA())))).text();
  assert.doesNotMatch(produto, /<script>alert/);
  assert.match(produto, /data-sku="x&quot;&#39;&gt;&lt;svg&gt;"/);
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

test("criterio 7: o canal mostra estado, qualidade, escalao, nivel e tecto, com a reconexao do painel quando desligado", async () => {
  const m = montar();
  m.canal.vistas.set(TENANT_A, {
    ...SEM_CANAL,
    estado: "desligado",
    restrito: false,
    qualidade: "amarelo",
    escalao: "TIER_250",
    nivel: 1,
    tectoPedidoMinor: 5_000_000n,
    avisos: ["actividade_limitada", "codigo_desconhecido<b>"],
  });
  const corpo = await (await m.app.fetch(get("/painel/canal", cookieDe(sessaoA())))).text();
  assert.match(corpo, /Desligado/);
  assert.match(corpo, /amarelo/);
  assert.match(corpo, /TIER_250/);
  assert.match(corpo, /Nível de confiança: 1/);
  assert.match(corpo, /50 000 Kz/);
  // **A reconexão é a do painel** (KAM-190): o `/ligar` exigia a sessão do registo.
  assert.match(corpo, /href="\/painel\/ligar"/);
  assert.doesNotMatch(corpo, /href="\/ligar"/);
  // O código público vira a frase; um código fora da lista sai escapado.
  assert.match(corpo, /A actividade da loja está limitada\./);
  assert.match(corpo, /codigo_desconhecido&lt;b&gt;/);
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

// ------------------------------------------------ achados da revisão adversarial

test("o painel nao grava stock: um stock no corpo e 400 stock_por_ligar, e nada chega ao COM", async () => {
  const m = montar();
  const r = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1000000", stock: 3, versao: V0 }, cookieDe(sessaoA())));
  assert.equal(r.status, 400);
  assert.deepEqual(await r.json(), { erro: "campo", campo: "stock_por_ligar" });
  assert.equal(m.comercio.gravacoes.length, 0);
  const pagina = await (await m.app.fetch(get("/painel/produtos/arroz", cookieDe(sessaoA())))).text();
  assert.match(pagina, /name="preco_kz"/);
  assert.doesNotMatch(pagina, /name="stock"/);
});

test("sair apaga as duas sessoes, a do painel e a do registo", async () => {
  const m = montar();
  const r = await m.app.fetch(new Request("http://127.0.0.1/painel/sair", { method: "POST", headers: { cookie: cookieDe(sessaoA()) } }));
  const cookies = r.headers.getSetCookie();
  assert.ok(cookies.some((c) => /^kamba_painel=;.*Max-Age=0/.test(c)), cookies.join(" | "));
  assert.ok(cookies.some((c) => /^kamba_onboarding=;.*Max-Age=0/.test(c)), cookies.join(" | "));
});

test("revogacao: um caso que deixa de estar activo fecha o painel no pedido seguinte", async () => {
  const m = montar();
  const cookie = cookieDe(sessaoA());
  assert.equal((await m.app.fetch(get("/painel/produtos", cookie))).status, 200);
  m.casos.set(CASO_A, { tenantId: TENANT_A, fase: "cancelado" });
  assert.equal((await m.app.fetch(get("/painel/produtos", cookie))).status, 401);
  // E uma sessao cujo tenant nao e o do caso tambem nao serve.
  m.casos.set(CASO_A, { tenantId: TENANT_B, fase: "activo" });
  assert.equal((await m.app.fetch(get("/painel/produtos", cookie))).status, 401);
});

test("criterio 6: o detalhe da propria encomenda abre, com os dados de A", async () => {
  const m = montar();
  const r = await m.app.fetch(get(`/painel/encomendas/${ORDEM_A}`, cookieDe(sessaoA())));
  assert.equal(r.status, 200);
  assert.match(await r.text(), /K7H3Q1/);
});

test("criterio 6: o filtro ate corta as encomendas depois do dia", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [
    encomenda(ORDEM_A, { numeroPublico: "K00001", criadoAt: "2026-11-01T10:00:00.000Z" }),
    encomenda("0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c", { numeroPublico: "K00002", criadoAt: "2026-11-08T10:00:00.000Z" }),
  ]);
  const corpo = await (await m.app.fetch(get("/painel/encomendas?estado=aguarda_pagamento&ate=2026-11-05", cookieDe(sessaoA())))).text();
  assert.match(corpo, /K00001/);
  assert.doesNotMatch(corpo, /K00002/);
});

test("idempotencia: uma resposta 5xx nao fica guardada, e a repeticao com a mesma chave grava", async () => {
  const m = montar();
  const original = m.comercio.obterOferta.bind(m.comercio);
  let falhar = true;
  m.comercio.obterOferta = async (t, a, sku) => {
    if (falhar) {
      falhar = false;
      return { tipo: "erro" as const, erro: "UPSTREAM_DOWN" };
    }
    return original(t, a, sku);
  };
  const idem = chave();
  const corpo = { preco_tipo: "fixo", preco_minor: "1200000", versao: V0 };
  assert.equal((await m.app.fetch(patch("arroz", corpo, cookieDe(sessaoA()), idem))).status, 503);
  const r = await m.app.fetch(patch("arroz", corpo, cookieDe(sessaoA()), idem));
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("idempotent-replayed"), null);
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("idempotencia: o mesmo pedido com outra ordem de chaves e outro espacamento e repeticao, e nao 422", async () => {
  const m = montar();
  const idem = chave();
  const primeiro = new Request("http://127.0.0.1/painel/produtos/arroz", {
    method: "PATCH",
    headers: { "content-type": "application/json", cookie: cookieDe(sessaoA()), "idempotency-key": idem },
    body: '{"preco_tipo":"fixo","preco_minor":"1200000","versao":"' + V0 + '"}',
  });
  const segundo = new Request("http://127.0.0.1/painel/produtos/arroz", {
    method: "PATCH",
    headers: { "content-type": "application/json", cookie: cookieDe(sessaoA()), "idempotency-key": idem },
    body: '{ "versao": "' + V0 + '", "preco_minor": "1200000", "preco_tipo": "fixo" }',
  });
  assert.equal((await m.app.fetch(primeiro)).status, 200);
  const r = await m.app.fetch(segundo);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("idempotent-replayed"), "true");
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("renovacao: uma sessao com a renovacao no futuro e recusada", () => {
  const s = sessaoA();
  const doFuturo = { ...s, renovada: s.renovada + 3600 };
  assert.equal(lerSessao(cunharSessao(doFuturo, CHAVE), [CHAVE], INICIO), null);
});

test("um preco com centimos nao se pre-preenche, para nao se perder numa gravacao", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [oferta("arroz", { precoMinor: 1_250_050n })]);
  const corpo = await (await m.app.fetch(get("/painel/produtos/arroz", cookieDe(sessaoA())))).text();
  assert.match(corpo, /name="preco_kz" inputmode="numeric" pattern="\[0-9\]\*" value=""/);
  assert.match(corpo, /data-kz=""/);
  assert.match(corpo, /12 500,50 Kz/);
});

// ------------------------------------------------------------------ KAM-206

test("KAM-206: a lista de produtos nao tem formularios nem guiao, e liga a pagina de cada produto", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, Array.from({ length: 200 }, (_, i) => oferta(`sku-${i}`, { nome: `Produto ${i}` })));
  const r = await m.app.fetch(get("/painel/produtos", cookieDe(sessaoA())));
  assert.equal(r.status, 200);
  const corpo = await r.text();
  assert.doesNotMatch(corpo, /<form class="oferta|<select|name="preco_kz"/);
  assert.doesNotMatch(corpo, /<script/);
  assert.equal((corpo.match(/<a href="\/painel\/produtos\/sku-\d+">/g) ?? []).length, 200);
  // So o formulario de sair, na barra: nenhum por produto.
  assert.equal((corpo.match(/<form/g) ?? []).length, 1);
});

test("KAM-206: a pagina de um produto tem o formulario e o guiao, com a versao da oferta", async () => {
  const m = montar();
  const r = await m.app.fetch(get("/painel/produtos/arroz", cookieDe(sessaoA())));
  assert.equal(r.status, 200);
  const corpo = await r.text();
  assert.match(corpo, /<form class="oferta cartao" data-sku="arroz" data-versao="2026-11-02T11:00:00.000001Z"/);
  assert.match(corpo, /<script nonce="[^"]+">/);
  assert.match(corpo, /<title>Produto arroz/);
});

test("KAM-206: isolamento - a pagina de um produto de B com a sessao de A e 404, igual a de um que nao existe", async () => {
  const m = montar();
  const deB = await m.app.fetch(get("/painel/produtos/so-de-b", cookieDe(sessaoA())));
  const inexistente = await m.app.fetch(get("/painel/produtos/nao-existe", cookieDe(sessaoA())));
  assert.equal(deB.status, 404);
  assert.equal(inexistente.status, 404);
  const corpoDeB = await deB.text();
  assert.doesNotMatch(corpoDeB, /so-de-b|Produto so-de-b/);
  assert.equal(corpoDeB.replace(/nonce="[^"]+"/g, ""), (await inexistente.text()).replace(/nonce="[^"]+"/g, ""));
  const tenantNaConsulta = await m.app.fetch(get(`/painel/produtos/so-de-b?tenant_id=${TENANT_B}`, cookieDe(sessaoA())));
  assert.equal(tenantNaConsulta.status, 404);
  assert.equal((await m.app.fetch(get("/painel/produtos/arroz", ""))).status, 401);
});

test("KAM-206: o COM em baixo na pagina de um produto e 503, e conta indisponivel", async () => {
  const m = montar();
  m.comercio.obterOferta = async () => ({ tipo: "erro", erro: "UPSTREAM_DOWN" });
  assert.equal((await m.app.fetch(get("/painel/produtos/arroz", cookieDe(sessaoA())))).status, 503);
  assert.match(m.metricas.exposicao(), /painel_erros_total\{rota="produto",motivo="indisponivel"\} 1/);
});

function pedirContacto(caminho: string, cookie: string): Request {
  return new Request(`http://127.0.0.1${caminho}`, { method: "POST", headers: { cookie } });
}

test("KAM-206: o detalhe nao traz o contacto por omissao, e so tem o botao nos estados da regra", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [
    encomenda(ORDEM_A, { estado: "pendente_confirmacao" }),
    encomenda("0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c", { estado: "aguarda_pagamento" }),
  ]);
  m.comercio.mascaras.set(ORDEM_A, "••• ••• 789");
  const comBotao = await (await m.app.fetch(get(`/painel/encomendas/${ORDEM_A}`, cookieDe(sessaoA())))).text();
  assert.match(comBotao, new RegExp(`<form method="post" action="/painel/encomendas/${ORDEM_A}/contacto"`));
  assert.doesNotMatch(comBotao, /789|data-contacto|7c1d5e3a/);
  const semBotao = await (await m.app.fetch(get("/painel/encomendas/0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c", cookieDe(sessaoA())))).text();
  assert.doesNotMatch(semBotao, /\/contacto"/);
  // O detalhe nao pede o contacto ao COM: so o botao o pede.
  assert.equal(m.comercio.contactosPedidos.length, 0);
});

test("KAM-206: o botao mostra o telefone mascarado, pedido ao COM com o tenant da sessao", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [encomenda(ORDEM_A, { estado: "paga" })]);
  m.comercio.mascaras.set(ORDEM_A, "••• ••• 789");
  const r = await m.app.fetch(pedirContacto(`/painel/encomendas/${ORDEM_A}/contacto?tenant_id=${TENANT_B}`, cookieDe(sessaoA())));
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("cache-control"), "no-store");
  const corpo = await r.text();
  assert.match(corpo, /<strong data-contacto>••• ••• 789<\/strong>/);
  assert.doesNotMatch(corpo, /7c1d5e3a|\/contacto"/);
  assert.deepEqual(m.comercio.contactosPedidos, [{ tenantId: TENANT_A, orderId: ORDEM_A }]);
  assert.match(m.metricas.exposicao(), /painel_pedidos_total\{rota="contacto"\} 1/);
});

test("KAM-206: uma encomenda sem telefone diz que nao ha telefone, e nao mostra o resto", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [encomenda(ORDEM_A, { estado: "em_entrega" })]);
  const corpo = await (await m.app.fetch(pedirContacto(`/painel/encomendas/${ORDEM_A}/contacto`, cookieDe(sessaoA())))).text();
  assert.match(corpo, /não tem telefone do cliente para mostrar/);
});

test("KAM-206: isolamento - o contacto da encomenda de B com a sessao de A e 404, igual ao de uma que nao existe e ao de fora da regra", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [encomenda(ORDEM_A, { estado: "entregue" })]);
  m.comercio.semear(TENANT_B, [], [encomenda(ORDEM_B, { estado: "paga", numeroPublico: "B00001" })]);
  m.comercio.mascaras.set(ORDEM_B, "••• ••• 222");
  const sem = (t: string): string => t.replace(/nonce="[^"]+"/g, "");
  const deB = await m.app.fetch(pedirContacto(`/painel/encomendas/${ORDEM_B}/contacto`, cookieDe(sessaoA())));
  const inexistente = await m.app.fetch(pedirContacto("/painel/encomendas/0d0d0d0d-0d0d-4d0d-8d0d-0d0d0d0d0d0d/contacto", cookieDe(sessaoA())));
  const foraDaRegra = await m.app.fetch(pedirContacto(`/painel/encomendas/${ORDEM_A}/contacto`, cookieDe(sessaoA())));
  const malFormada = await m.app.fetch(pedirContacto("/painel/encomendas/nao-e-uuid/contacto", cookieDe(sessaoA())));
  for (const r of [deB, inexistente, foraDaRegra, malFormada]) assert.equal(r.status, 404);
  const corpoDeB = await deB.text();
  assert.doesNotMatch(corpoDeB, /222|B00001/);
  assert.equal(sem(corpoDeB), sem(await inexistente.text()));
  assert.equal(sem(corpoDeB), sem(await foraDaRegra.text()));
  // Nenhum pedido de contacto saiu com o tenant de B.
  assert.ok(m.comercio.contactosPedidos.every((p) => p.tenantId === TENANT_A));
  assert.equal((await m.app.fetch(pedirContacto(`/painel/encomendas/${ORDEM_A}/contacto`, ""))).status, 401);
});

test("KAM-206: adversarial - um COM que devolva o telefone em claro e recusado, e a pagina nao o mostra", async () => {
  const pedidos: string[] = [];
  const com = new ComercioPorHttp("http://com:3002", "cred", async (url) => {
    pedidos.push(url);
    return new Response(JSON.stringify({ tipo: "ok", valor: { orderId: ORDEM_A, telefoneMascarado: "+244 999 000 789" } }));
  });
  const r = await com.contactoDaEncomenda(TENANT_A, { id: CASO_A, traceId: "t" }, ORDEM_A);
  assert.deepEqual(r, { tipo: "erro", erro: "UPSTREAM_DOWN" });
  assert.deepEqual(pedidos, ["http://com:3002/internal/order-contact"]);
  const certo = new ComercioPorHttp("http://com:3002", "cred", async () =>
    new Response(JSON.stringify({ tipo: "ok", valor: { orderId: ORDEM_A, telefoneMascarado: "••• ••• 789" } })),
  );
  assert.deepEqual(await certo.contactoDaEncomenda(TENANT_A, { id: CASO_A, traceId: "t" }, ORDEM_A), {
    tipo: "ok",
    valor: { orderId: ORDEM_A, telefoneMascarado: "••• ••• 789" },
  });
  const m = montar();
  m.comercio.semear(TENANT_A, [], [encomenda(ORDEM_A, { estado: "paga" })]);
  m.comercio.contactoDaEncomenda = async () => ({ tipo: "erro", erro: "UPSTREAM_DOWN" });
  const pagina = await m.app.fetch(pedirContacto(`/painel/encomendas/${ORDEM_A}/contacto`, cookieDe(sessaoA())));
  assert.equal(pagina.status, 503);
  assert.doesNotMatch(await pagina.text(), /999|789/);
  assert.match(m.metricas.exposicao(), /painel_erros_total\{rota="contacto",motivo="indisponivel"\} 1/);
});

test("KAM-206: um POST de outra origem do mesmo sitio e recusado antes de pedir o contacto", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [encomenda(ORDEM_A, { estado: "paga" })]);
  m.comercio.mascaras.set(ORDEM_A, "••• ••• 789");
  for (const sitio of ["same-site", "cross-site"]) {
    const r = await m.app.fetch(
      new Request(`http://127.0.0.1/painel/encomendas/${ORDEM_A}/contacto`, {
        method: "POST",
        headers: { cookie: cookieDe(sessaoA()), "sec-fetch-site": sitio },
      }),
    );
    assert.equal(r.status, 403, sitio);
    assert.doesNotMatch(await r.text(), /789/);
  }
  assert.equal(m.comercio.contactosPedidos.length, 0);
  const daMesma = await m.app.fetch(
    new Request(`http://127.0.0.1/painel/encomendas/${ORDEM_A}/contacto`, {
      method: "POST",
      headers: { cookie: cookieDe(sessaoA()), "sec-fetch-site": "same-origin" },
    }),
  );
  assert.equal(daMesma.status, 200);
});

test("KAM-206: os estados do botao sao os da regra do COM, confrontados com o texto de la", () => {
  const regra = readFileSync(new URL("../../com/src/orders/contacto.ts", import.meta.url), "utf8");
  const bloco = /export const ESTADOS_COM_CONTACTO = \[([\s\S]*?)\] as const;/.exec(regra)?.[1] ?? "";
  const doCom = [...bloco.matchAll(/"([a-z_]+)"/g)].map((x) => x[1]);
  assert.equal(doCom.length, 4);
  assert.deepEqual([...ESTADOS_COM_CONTACTO], doCom);
});

// ------------------------------------------------------------------ KAM-190

test("KAM-190: o PATCH le o preco anterior de uma oferta so, e nunca a lista", async () => {
  const m = montar();
  let listas = 0;
  const original = m.comercio.listarOfertas.bind(m.comercio);
  m.comercio.listarOfertas = async (t: string) => {
    listas += 1;
    return original(t);
  };
  // Uma oferta para la da 200.a: a lista do painel nao a teria, e o PATCH dava 404.
  const muitas = Array.from({ length: 201 }, (_, i) => oferta(`sku-${String(i).padStart(3, "0")}`));
  m.comercio.semear(TENANT_A, muitas);
  const r = await m.app.fetch(patch("sku-200", { preco_tipo: "fixo", preco_minor: "1100000", versao: V0 }, cookieDe(sessaoA())));
  assert.equal(r.status, 200);
  assert.equal(listas, 0, "o PATCH foi a lista");
  assert.equal(m.comercio.gravacoes.length, 1);
});

test("KAM-190: o PATCH de uma oferta arquivada ou de B e 404, e uma falha do COM e 503", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [oferta("velha", { estado: "arquivado" })]);
  for (const sku of ["velha", "so-de-b"]) {
    const r = await m.app.fetch(patch(sku, { preco_tipo: "fixo", preco_minor: "1100000", versao: V0 }, cookieDe(sessaoA())));
    assert.equal(r.status, 404, sku);
  }
  m.comercio.obterOferta = async () => ({ tipo: "erro" as const, erro: "UPSTREAM_DOWN" });
  const r = await m.app.fetch(patch("arroz", { preco_tipo: "fixo", preco_minor: "1100000", versao: V0 }, cookieDe(sessaoA())));
  assert.equal(r.status, 503);
  assert.equal(m.comercio.gravacoes.length, 0);
});

test("KAM-190: o intervalo vai ao COM em instantes de Luanda, e o dia de ate entra inteiro", async () => {
  const m = montar();
  m.comercio.semear(TENANT_A, [], [
    // 23h30 de Luanda do dia 4 e 23h30 de Luanda do dia 5: o dia 5 de Luanda
    // comeca as 23h00 UTC do dia 4.
    encomenda(ORDEM_A, { numeroPublico: "K00004", criadoAt: "2026-11-04T22:30:00.000Z" }),
    encomenda("0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c", { numeroPublico: "K00005", criadoAt: "2026-11-05T22:30:00.000Z" }),
    encomenda("0d0d0d0d-0d0d-4d0d-8d0d-0d0d0d0d0d0d", { numeroPublico: "K00006", criadoAt: "2026-11-05T23:30:00.000Z" }),
  ]);
  const corpo = await (await m.app.fetch(get("/painel/encomendas?estado=aguarda_pagamento&desde=2026-11-05&ate=2026-11-05", cookieDe(sessaoA())))).text();
  assert.deepEqual(m.comercio.filtros.at(-1), {
    estado: "aguarda_pagamento",
    criadoDesde: "2026-11-04T23:00:00.000Z",
    criadoAte: "2026-11-05T23:00:00.000Z",
  });
  assert.match(corpo, /K00005/);
  assert.doesNotMatch(corpo, /K00004|K00006/);
  // E a data mostrada e a de Luanda.
  assert.match(corpo, /2026-11-05/);
});

test("KAM-190: um dia que nao existe, ou um intervalo invertido, e 400 sem ir ao COM", async () => {
  const m = montar();
  for (const q of ["desde=2026-02-31", "ate=2026-13-01", "desde=2026-11-06&ate=2026-11-05", "cursor=a%20b"]) {
    const r = await m.app.fetch(get(`/painel/encomendas?estado=paga&${q}`, cookieDe(sessaoA())));
    assert.equal(r.status, 400, q);
  }
  assert.equal(m.comercio.filtros.length, 0);
  assert.equal(inicioDoDiaEmLuanda("2026-11-05")?.toISOString(), "2026-11-04T23:00:00.000Z");
});

test("KAM-190: o cursor do COM vira a ligacao para as mais antigas, com o mesmo filtro, e volta ao COM", async () => {
  const m = montar();
  const original = m.comercio.listarEncomendas.bind(m.comercio);
  m.comercio.listarEncomendas = async (t, a, f) => {
    const r = await original(t, a, f);
    return r.tipo === "ok" && f.cursor === undefined ? { tipo: "ok" as const, valor: { ...r.valor, proximo: "abc.DEF_-1" } } : r;
  };
  const corpo = await (await m.app.fetch(get("/painel/encomendas?estado=aguarda_pagamento&desde=2026-11-01", cookieDe(sessaoA())))).text();
  assert.match(corpo, /href="\/painel\/encomendas\?estado=aguarda_pagamento&amp;desde=2026-11-01&amp;cursor=abc.DEF_-1"/);
  await m.app.fetch(get("/painel/encomendas?estado=aguarda_pagamento&desde=2026-11-01&cursor=abc.DEF_-1", cookieDe(sessaoA())));
  assert.equal(m.comercio.filtros.at(-1)?.cursor, "abc.DEF_-1");
  assert.equal(m.comercio.filtros.at(-1)?.criadoDesde, "2026-10-31T23:00:00.000Z");
  // Um cursor que o COM recusa (outro intervalo) e 400, e nao a primeira pagina.
  m.comercio.listarEncomendas = async () => ({ tipo: "erro" as const, erro: "VALIDATION_ERROR" });
  assert.equal((await m.app.fetch(get("/painel/encomendas?estado=paga&cursor=x", cookieDe(sessaoA())))).status, 400);
});

test("KAM-190: o canal que nao se le e 503, e nao «sem canal»", async () => {
  const m = montar({ canal: { ler: async () => null } });
  const r = await m.app.fetch(get("/painel/canal", cookieDe(sessaoA())));
  assert.equal(r.status, 503);
  assert.doesNotMatch(await r.text(), /Ligar o número/);
});

test("KAM-190: o CanalPeloCom pede o channel-view com o tenant e o actor da sessao", async () => {
  const pedidos: { url: string; tenant: string | null; corpo: unknown }[] = [];
  const com = new ComercioPorHttp("http://com:3002", "credencial", async (url, init) => {
    const h = new Headers(init.headers);
    pedidos.push({ url, tenant: h.get("x-kamba-tenant"), corpo: JSON.parse(String(init.body)) });
    return new Response(
      JSON.stringify({
        tipo: "ok",
        valor: { estado: "ativo", restrito: false, qualidade: "verde", escalao: "TIER_1K", nivel: 1, tectoPedidoMinor: "5000000", currency: "AOA", avisos: ["conduta_em_analise"] },
      }),
    );
  });
  const m = montar({ canal: new CanalPeloCom(com) });
  const corpo = await (await m.app.fetch(get("/painel/canal", cookieDe(sessaoA())))).text();
  assert.equal(pedidos[0]?.url, "http://com:3002/internal/channel-view");
  assert.equal(pedidos[0]?.tenant, TENANT_A);
  assert.deepEqual((pedidos[0]?.corpo as { actor: unknown }).actor, { kind: "dono", id: CASO_A });
  assert.match(corpo, /Activo/);
  assert.match(corpo, /TIER_1K/);
  assert.match(corpo, /50 000 Kz/);
  // Um estado fora dos quatro, ou o COM em baixo, e «nao se sabe».
  const mau = new ComercioPorHttp("http://com:3002", "c", async () => new Response(JSON.stringify({ tipo: "ok", valor: { estado: "restrito" } })));
  assert.equal(await new CanalPeloCom(mau).ler(TENANT_A, { id: CASO_A, traceId: "t" }), null);
  const caido = new ComercioPorHttp("http://com:3002", "c", async () => {
    throw new Error("rede");
  });
  assert.equal(await new CanalPeloCom(caido).ler(TENANT_A, { id: CASO_A, traceId: "t" }), null);
});

test("KAM-190: o get-offer pede uma oferta com o tenant da sessao", async () => {
  const pedidos: { url: string; tenant: string | null; corpo: Record<string, unknown> }[] = [];
  const com = new ComercioPorHttp("http://com:3002", "credencial", async (url, init) => {
    pedidos.push({ url, tenant: new Headers(init.headers).get("x-kamba-tenant"), corpo: JSON.parse(String(init.body)) });
    return new Response(JSON.stringify({ tipo: "erro", erro: "TENANT_MISMATCH" }), { status: 403 });
  });
  const r = await com.obterOferta(TENANT_A, { id: CASO_A, traceId: "t" }, "arroz");
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  assert.equal(pedidos[0]?.url, "http://com:3002/internal/get-offer");
  assert.equal(pedidos[0]?.tenant, TENANT_A);
  assert.equal(pedidos[0]?.corpo["sku"], "arroz");
});

// ------------------------------------------------- KAM-190: a reentrada

const TELEFONE_A = "+244 999 000 111";
const TELEFONE_SEM_PAINEL = "+244 999 000 222";
const PEPPER = new Uint8Array(32).fill(5);

interface Reentrada {
  readonly opcoes: OpcoesDaReentrada;
  readonly enviados: string[];
  readonly verificados: string[];
  codigo: string;
}

function reentrada(): Reentrada {
  const telA = new Telefone(TELEFONE_A, [PEPPER, null]);
  const anotacoes = new Map<string, number>();
  const r: Reentrada = {
    enviados: [],
    verificados: [],
    codigo: "123456",
    opcoes: undefined as unknown as OpcoesDaReentrada,
  };
  (r as { opcoes: OpcoesDaReentrada }).opcoes = {
    telefoneDoCaso: async (id: string) => (id === CASO_A ? telA : null),
    otp: {
      async enviar(id: string) {
        r.enviados.push(id);
        return { enviado: true as const, expiraEm: new Date(INICIO.getTime() + 300_000) };
      },
      async verificar(id: string, codigo: unknown) {
        r.verificados.push(id);
        return id === CASO_A && codigo === r.codigo ? ("acertou" as const) : id === CASO_A ? ("errou" as const) : ("sem_desafio" as const);
      },
    },
    casosPorTelefone: async (hmac: string) => (telA.hmacs.includes(hmac) ? [{ id: CASO_A, fase: "activo" }] : []),
    anelDoPepper: [PEPPER, null],
    contadores: {
      async anotar(chave: string) {
        const n = (anotacoes.get(chave) ?? 0) + 1;
        anotacoes.set(chave, n);
        return n;
      },
    },
  };
  return r;
}

function post(caminho: string, corpo: unknown, extra: Record<string, string> = {}): Request {
  return new Request(`http://127.0.0.1${caminho}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...extra },
    body: JSON.stringify(corpo),
  });
}

test("KAM-190: reentrada — o telefone com painel recebe o codigo, e o certo cunha a sessao do painel sem a do registo", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  const pedido = await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_A }));
  assert.equal(pedido.status, 200);
  const { referencia } = (await pedido.json()) as { referencia: string };
  await new Promise((resolver) => setImmediate(resolver));
  assert.deepEqual(re.enviados, [CASO_A]);
  const r = await m.app.fetch(post("/painel/verificar", { referencia, codigo: "123456" }));
  assert.equal(r.status, 200);
  const cookies = r.headers.getSetCookie();
  assert.equal(cookies.some((c) => c.startsWith(`${NOME_DO_COOKIE}=`)), false, "cunhou a sessao do registo");
  const painel = cookies.find((c) => c.startsWith(`${NOME_DO_COOKIE_DO_PAINEL}=`)) ?? "";
  const s = lerSessao(painel.slice(NOME_DO_COOKIE_DO_PAINEL.length + 1).split(";")[0], [CHAVE, null], m.agora);
  assert.equal(s?.tenantId, TENANT_A);
  assert.equal(s?.dono, CASO_A);
  // E a sessao abre o painel.
  assert.equal((await m.app.fetch(get("/painel/produtos", painel.split(";")[0] ?? ""))).status, 200);
});

test("KAM-190: reentrada — um telefone sem painel tem a mesma resposta, e o codigo da o mesmo 401", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  const a = await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_A }));
  const b = await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_SEM_PAINEL }));
  assert.equal(a.status, b.status);
  const ca = (await a.json()) as Record<string, string>;
  const cb = (await b.json()) as Record<string, string>;
  assert.deepEqual(Object.keys(ca), Object.keys(cb));
  assert.match(cb["referencia"] ?? "", /^b2\./);
  // **O bilhete nao diz de que caso e** (achado 1 da revisao adversarial): o de A
  // nao leva o caso de A, e dois pedidos do mesmo telefone dao bilhetes diferentes,
  // como dois de um telefone sem painel.
  assert.doesNotMatch(ca["referencia"] ?? "", new RegExp(CASO_A));
  const outraVezA = (await (await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_A }))).json()) as Record<string, string>;
  assert.notEqual(outraVezA["referencia"], ca["referencia"]);
  assert.equal(lerBilhete(outraVezA["referencia"], [CHAVE, null], m.agora), CASO_A);
  await new Promise((resolver) => setImmediate(resolver));
  assert.deepEqual(re.enviados, [CASO_A, CASO_A], "mandou SMS a um telefone sem painel");
  // As falhas sao todas o mesmo 401: errado num caso real, e qualquer um no falso.
  const errado = await m.app.fetch(post("/painel/verificar", { referencia: ca["referencia"], codigo: "000000" }));
  const falso = await m.app.fetch(post("/painel/verificar", { referencia: cb["referencia"], codigo: "123456" }));
  assert.equal(errado.status, 401);
  assert.equal(falso.status, 401);
  assert.deepEqual(await errado.json(), await falso.json());
});

test("KAM-190: reentrada — o envio corre fora do pedido, e um SMS lento nao atrasa a resposta", async () => {
  const re = reentrada();
  let soltar: () => void = () => {};
  const preso = new Promise<void>((resolver) => {
    soltar = resolver;
  });
  const m = montar({
    reentrada: {
      ...re.opcoes,
      otp: {
        ...re.opcoes.otp,
        async enviar() {
          await preso;
          return { enviado: false as const, recusa: "intervalo" as const };
        },
      },
    },
  });
  const r = await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_A }));
  assert.equal(r.status, 200);
  soltar();
});

test("KAM-190: reentrada — o bilhete do painel nao e o ticket do registo, e o do registo nao serve aqui", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  const bilhete = cunharBilhete(CASO_A, CHAVE, m.agora);
  assert.throws(() => lerReferencia("ticket", bilhete, [CHAVE, null], () => m.agora), ReferenciaInvalidaError);
  const ticket = cunharReferencia("ticket", CASO_A, CHAVE, () => m.agora);
  assert.equal(lerBilhete(ticket, [CHAVE, null], m.agora), null);
  const r = await m.app.fetch(post("/painel/verificar", { referencia: ticket, codigo: "123456" }));
  assert.equal(r.status, 401);
  assert.deepEqual(re.verificados, [], "um ticket do registo chegou ao OTP");
  // E um bilhete vencido ou assinado por outra chave tambem nao.
  assert.equal(lerBilhete(bilhete, [OUTRA_CHAVE, null], m.agora), null);
  assert.equal(lerBilhete(bilhete, [CHAVE, null], new Date(m.agora.getTime() + 11 * 60_000)), null);
});

test("KAM-190: reentrada — o codigo certo de um caso que ja nao tem painel nao cunha nada", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  const { referencia } = (await (await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_A }))).json()) as { referencia: string };
  m.casos.set(CASO_A, { tenantId: TENANT_A, fase: "cancelado" });
  const r = await m.app.fetch(post("/painel/verificar", { referencia, codigo: "123456" }));
  assert.equal(r.status, 401);
  assert.equal(r.headers.getSetCookie().length, 0);
});

test("KAM-190: reentrada — o limite por rede vem antes do telefone, e e o mesmo para os dois", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  for (let i = 0; i < LIMITE_POR_REDE; i += 1) {
    assert.equal((await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_SEM_PAINEL }))).status, 200);
  }
  const a = await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_A }));
  const b = await m.app.fetch(post("/painel/codigo", { telefone: TELEFONE_SEM_PAINEL }));
  assert.equal(a.status, 429);
  assert.equal(b.status, 429);
  await new Promise((resolver) => setImmediate(resolver));
  assert.deepEqual(re.enviados, []);
  assert.equal(m.metricas.valor("codigo", "limite"), 2);
});

test("KAM-190: reentrada — telefone invalido e 400, sem JSON e 400, e sem reentrada montada e 503", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  assert.equal((await m.app.fetch(post("/painel/codigo", { telefone: "nao e telefone" }))).status, 400);
  const semJson = new Request("http://127.0.0.1/painel/codigo", { method: "POST", body: "telefone=1" });
  assert.equal((await m.app.fetch(semJson)).status, 400);
  const sem = montar();
  assert.equal((await sem.app.fetch(post("/painel/codigo", { telefone: TELEFONE_A }))).status, 503);
  assert.equal((await sem.app.fetch(post("/painel/verificar", { referencia: "x", codigo: "1" }))).status, 503);
});

test("KAM-190: a pagina sem sessao traz a reentrada, com o guiao do nonce e sem terceiros", async () => {
  const m = montar();
  const r = await m.app.fetch(get("/painel/produtos", ""));
  assert.equal(r.status, 401);
  const corpo = await r.text();
  assert.match(corpo, /id="pedir"/);
  assert.match(corpo, /\/painel\/codigo/);
  assert.match(corpo, /\/painel\/verificar/);
  assert.doesNotMatch(corpo, /\/api\/otp\/verificar/);
  assert.doesNotMatch(corpo, /<script[^>]+src=/);
});

test("KAM-190: o /metrics do onboarding-web serve as series do painel que as rotas contam", async () => {
  const m = montar();
  const app = createApp(
    undefined,
    { anelDaAssinatura: [CHAVE, null] } as never,
    undefined,
    {
      comercio: m.comercio,
      canal: m.canal,
      revogacoes: m.revogacoes,
      metricas: m.metricas,
      casos: { porId: async (id) => m.casos.get(id) ?? null },
      anelDaAssinatura: [CHAVE, null],
    },
  );
  await app.fetch(get("/painel/produtos", ""));
  await app.fetch(get("/painel/produtos", cookieDe(sessaoA())));
  const r = await app.fetch(new Request("http://127.0.0.1/metrics"));
  assert.equal(r.status, 200);
  assert.match(r.headers.get("content-type") ?? "", /^text\/plain; version=0\.0\.4/);
  const corpo = await r.text();
  // **Com valor**: sobre uma populacao a zero, a asserçao do `OBS-I` passava
  // mesmo com uma etiqueta por tenant (o achado do KAM-178 no /metrics do COM).
  assert.match(corpo, /painel_pedidos_total\{rota="produtos"\} 2/);
  assert.match(corpo, /painel_erros_total\{rota="produtos",motivo="sem_sessao"\} 1/);
  assert.match(corpo, /painel_erros_total\{rota="codigo",motivo="limite"\} 0/);
  assert.doesNotMatch(corpo, new RegExp(`${TENANT_A}|${CASO_A}`));
  // E sem painel montado, as series saem a zero.
  const vazio = await (await createApp().fetch(new Request("http://127.0.0.1/metrics"))).text();
  assert.match(vazio, /painel_pedidos_total\{rota="entrar"\} 0/);
});

test("KAM-190: a ligacao pede o codigo e so abre o /ligar depois dele, e a sessao do painel sozinha nao cunha a do registo", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  m.casos.set(CASO_A, { tenantId: TENANT_A, fase: "aguarda_es" });
  const r = await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA())));
  assert.equal(r.status, 200);
  // **Nenhuma sessao do registo sai daqui**: era o ciclo painel -> registo ->
  // painel novo que tornava a sessao perpetua (achado 2 da revisao adversarial).
  assert.equal(r.headers.getSetCookie().some((c) => c.startsWith(`${NOME_DO_COOKIE}=`)), false);
  const pagina = await r.text();
  const bilhete = /data-bilhete="([^"]+)"/.exec(pagina)?.[1] ?? "";
  assert.equal(lerBilhete(bilhete, [CHAVE, null], m.agora), CASO_A);
  await new Promise((resolver) => setImmediate(resolver));
  assert.deepEqual(re.enviados, [CASO_A]);
  // O codigo errado nao cunha nada; o certo cunha as duas e manda para o /ligar.
  const errado = await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "000000", destino: "ligar" }));
  assert.equal(errado.status, 401);
  assert.equal(errado.headers.getSetCookie().length, 0);
  const certo = await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "123456", destino: "ligar" }));
  assert.equal(certo.status, 200);
  assert.deepEqual(await certo.json(), { ok: true, seguinte: "/ligar" });
  const registo = certo.headers.getSetCookie().find((c) => c.startsWith(`${NOME_DO_COOKIE}=`)) ?? "";
  assert.equal(lerReferencia("sessao", registo.slice(NOME_DO_COOKIE.length + 1).split(";")[0] ?? "", [CHAVE, null], () => m.agora), CASO_A);
});

test("KAM-190: a ligacao de um caso fora do passo do ES e 409, sem SMS e sem formulario", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  const r = await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA())));
  assert.equal(r.status, 409);
  assert.doesNotMatch(await r.text(), /data-bilhete/);
  await new Promise((resolver) => setImmediate(resolver));
  assert.deepEqual(re.enviados, []);
  // E um codigo certo com destino «ligar» num caso activo nao cunha o registo.
  const bilhete = cunharBilhete(CASO_A, CHAVE, m.agora);
  const v = await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "123456", destino: "ligar" }));
  assert.equal(v.status, 401);
  assert.equal(v.headers.getSetCookie().length, 0);
  // Sem sessao, 401; sem reentrada montada, 503.
  assert.equal((await m.app.fetch(get("/painel/ligar", ""))).status, 401);
  assert.equal((await montar().app.fetch(get("/painel/ligar", cookieDe(sessaoA())))).status, 503);
});

test("KAM-190: o verificar tem limite por rede, e um bilhete na mao nao gasta as tentativas do dono sem tecto", async () => {
  const re = reentrada();
  const m = montar({ reentrada: re.opcoes });
  const bilhete = cunharBilhete(CASO_A, CHAVE, m.agora);
  for (let i = 0; i < LIMITE_POR_REDE; i += 1) {
    assert.equal((await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "000000" }))).status, 401);
  }
  assert.equal((await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "123456" }))).status, 429);
  assert.equal(re.verificados.length, LIMITE_POR_REDE);
});

test("KAM-190: os nomes do intervalo no fio sao os que o COM le", async () => {
  const corpos: Record<string, unknown>[] = [];
  const com = new ComercioPorHttp("http://com:3002", "c", async (_url, init) => {
    corpos.push(JSON.parse(String(init.body)) as Record<string, unknown>);
    return new Response(JSON.stringify({ tipo: "ok", valor: { itens: [], proximo: null } }));
  });
  await com.listarEncomendas(TENANT_A, { id: CASO_A, traceId: "t" }, {
    estado: "paga",
    criadoDesde: "2026-11-01T00:00:00.000Z",
    criadoAte: "2026-11-02T00:00:00.000Z",
  });
  assert.equal(corpos[0]?.["criado_desde"], "2026-11-01T00:00:00.000Z");
  assert.equal(corpos[0]?.["criado_ate"], "2026-11-02T00:00:00.000Z");
  // E sao os que a API interna do COM le: o painel nao importa codigo do COM
  // (`lint_arch`), e confronta-se o texto, como o `ORDER_STATES`.
  const interna = readFileSync(new URL("../../com/src/api/interna.ts", import.meta.url), "utf8");
  assert.match(interna, /\["criado_desde", "criadoDesde"\]/);
  assert.match(interna, /\["criado_ate", "criadoAte"\]/);
});

test("KAM-190: um canal suspenso nao convida a religar, e um activo limitado di-lo", async () => {
  const m = montar();
  m.canal.vistas.set(TENANT_A, { ...SEM_CANAL, estado: "desligado", restrito: true });
  const corpo = await (await m.app.fetch(get("/painel/canal", cookieDe(sessaoA())))).text();
  assert.match(corpo, /suspenso/);
  assert.doesNotMatch(corpo, /href="\/painel\/ligar"/);
  m.canal.vistas.set(TENANT_A, { ...SEM_CANAL, estado: "ativo", restrito: true });
  const limitado = await (await m.app.fetch(get("/painel/canal", cookieDe(sessaoA())))).text();
  assert.match(limitado, /envio limitado/);
  assert.doesNotMatch(limitado, /href="\/painel\/ligar"/);
});

// ------------------------------------------- KAM-207: a religação de um activo

/** O canal de A caiu, e a reentrada leva a porta do guia, que conta quem religou. */
function religacao(vista: Partial<VistaDoCanal> = { estado: "desligado", restrito: false }) {
  const re = reentrada();
  const religados: string[] = [];
  const m = montar({
    reentrada: {
      ...re.opcoes,
      religar: async (id: string) => {
        religados.push(id);
        return "desligado";
      },
    },
  });
  m.canal.vistas.set(TENANT_A, { ...SEM_CANAL, ...vista });
  return { re, m, religados };
}

/** O bilhete da pagina do codigo da ligacao. */
async function bilheteDa(r: Response): Promise<string> {
  return /data-bilhete="([^"]+)"/.exec(await r.text())?.[1] ?? "";
}

test("KAM-207: um caso activo com o canal desligado pede o codigo e, com o certo, reabre o /ligar sem mudar de fase", async () => {
  const { re, m, religados } = religacao();
  const r = await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA())));
  // **O 409 do KAM-190 deixa de valer a este caso** (criterio 4).
  assert.equal(r.status, 200);
  const bilhete = await bilheteDa(r);
  assert.equal(lerBilhete(bilhete, [CHAVE, null], m.agora), CASO_A);
  await new Promise((resolver) => setImmediate(resolver));
  assert.deepEqual(re.enviados, [CASO_A]);
  assert.deepEqual(religados, [], "religou antes do codigo");
  // A metrica conta a religacao a parte (DoD).
  assert.equal(m.metricas.valor("religar"), 1);
  assert.equal(m.metricas.valor("ligar"), 0);

  const certo = await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "123456", destino: "ligar" }));
  assert.equal(certo.status, 200);
  assert.deepEqual(await certo.json(), { ok: true, seguinte: "/ligar" });
  assert.deepEqual(religados, [CASO_A]);
  const registo = certo.headers.getSetCookie().find((c) => c.startsWith(`${NOME_DO_COOKIE}=`)) ?? "";
  assert.equal(lerReferencia("sessao", registo.slice(NOME_DO_COOKIE.length + 1).split(";")[0] ?? "", [CHAVE, null], () => m.agora), CASO_A);
  // **O caso nao recua de fase** (criterio 3): o painel nao lhe toca.
  assert.equal(m.casos.get(CASO_A)?.fase, "activo");
  assert.equal(m.casos.get(CASO_A)?.tenantId, TENANT_A);
});

test("KAM-207 adversarial: suspenso e encerrado nao reabrem, nem o canal de pe — sem SMS e sem sessao do registo", async () => {
  for (const vista of [
    { estado: "desligado", restrito: true },
    { estado: "ativo", restrito: false },
    { estado: "a_sincronizar", restrito: false },
    { estado: "sem_canal", restrito: false },
  ] as const) {
    const { re, m, religados } = religacao(vista);
    const r = await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA())));
    assert.equal(r.status, 409, JSON.stringify(vista));
    assert.doesNotMatch(await r.text(), /data-bilhete/);
    const v = await m.app.fetch(post("/painel/verificar", { referencia: cunharBilhete(CASO_A, CHAVE, m.agora), codigo: "123456", destino: "ligar" }));
    assert.equal(v.status, 401, JSON.stringify(vista));
    assert.equal(v.headers.getSetCookie().length, 0);
    await new Promise((resolver) => setImmediate(resolver));
    assert.deepEqual(re.enviados, []);
    assert.deepEqual(religados, []);
    assert.equal(m.metricas.valor("religar", "conflito"), 1);
  }
});

test("KAM-207 adversarial: uma suspensao entre o codigo e a verificacao fecha a religacao", async () => {
  const { m, religados } = religacao();
  const bilhete = await bilheteDa(await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA()))));
  m.canal.vistas.set(TENANT_A, { ...SEM_CANAL, estado: "desligado", restrito: true });
  const v = await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "123456", destino: "ligar" }));
  assert.equal(v.status, 401);
  assert.equal(v.headers.getSetCookie().length, 0);
  assert.deepEqual(religados, []);
});

test("KAM-207: o COM em baixo e 503 nas duas pontas, e nao se manda SMS nem se religa", async () => {
  const re = reentrada();
  const religados: string[] = [];
  const m = montar({
    canal: { ler: async () => null },
    reentrada: { ...re.opcoes, religar: async (id: string) => religados.push(id) },
  });
  assert.equal((await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA())))).status, 503);
  const v = await m.app.fetch(post("/painel/verificar", { referencia: cunharBilhete(CASO_A, CHAVE, m.agora), codigo: "123456", destino: "ligar" }));
  assert.equal(v.status, 503);
  assert.equal(v.headers.getSetCookie().length, 0);
  await new Promise((resolver) => setImmediate(resolver));
  assert.deepEqual(re.enviados, []);
  assert.deepEqual(religados, []);
});

test("KAM-207: um guia que recusa religar e o mesmo 401, sem sessao nenhuma", async () => {
  const re = reentrada();
  const m = montar({
    reentrada: {
      ...re.opcoes,
      religar: async () => {
        throw new GuiaRecusadoError("estado_errado");
      },
    },
  });
  m.canal.vistas.set(TENANT_A, { ...SEM_CANAL, estado: "desligado" });
  const v = await m.app.fetch(post("/painel/verificar", { referencia: cunharBilhete(CASO_A, CHAVE, m.agora), codigo: "123456", destino: "ligar" }));
  assert.equal(v.status, 401);
  assert.deepEqual(await v.json(), { erro: "codigo" });
  assert.equal(v.headers.getSetCookie().length, 0);
});

test("KAM-207 isolamento: a sessao de A pergunta pelo canal de A e religa o caso de A, e o canal caido de B nao lhe abre nada", async () => {
  const re = reentrada();
  const religados: string[] = [];
  const perguntados: string[] = [];
  const canal = new CanalEmMemoria();
  const m = montar({
    canal: {
      ler: async (tenantId) => {
        perguntados.push(tenantId);
        return canal.ler(tenantId);
      },
    },
    reentrada: { ...re.opcoes, religar: async (id: string) => religados.push(id) },
  });
  m.casos.set(CASO_B, { tenantId: TENANT_B, fase: "activo" });
  canal.vistas.set(TENANT_A, { ...SEM_CANAL, estado: "ativo" });
  canal.vistas.set(TENANT_B, { ...SEM_CANAL, estado: "desligado" });
  assert.equal((await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA())))).status, 409);
  // Um bilhete forjado para o caso de B com a chave certa nao passa sem o codigo de B.
  const v = await m.app.fetch(post("/painel/verificar", { referencia: cunharBilhete(CASO_B, CHAVE, m.agora), codigo: "123456", destino: "ligar" }));
  assert.equal(v.status, 401);
  assert.deepEqual(perguntados, [TENANT_A]);
  assert.deepEqual(religados, []);
  // Com o canal de A caido, quem religa e A, e so A.
  canal.vistas.set(TENANT_A, { ...SEM_CANAL, estado: "desligado" });
  const bilhete = await bilheteDa(await m.app.fetch(get("/painel/ligar", cookieDe(sessaoA()))));
  const certo = await m.app.fetch(post("/painel/verificar", { referencia: bilhete, codigo: "123456", destino: "ligar" }));
  assert.equal(certo.status, 200);
  assert.deepEqual(religados, [CASO_A]);
  assert.ok(perguntados.every((t) => t === TENANT_A), perguntados.join(","));
});

test("KAM-207: o /metrics serve a etiqueta religar", async () => {
  const m = new MetricasDoPainel();
  assert.match(m.exposicao(), /painel_pedidos_total\{rota="religar"\} 0/);
  assert.match(m.exposicao(), /painel_erros_total\{rota="religar",motivo="conflito"\} 0/);
});
