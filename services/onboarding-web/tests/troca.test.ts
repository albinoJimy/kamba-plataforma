/**
 * A troca de telefone do dono pelo painel (KAM-211, critério «Troca de
 * telefone»), com a prova de posse do KAM-223 (decisão 3 do fundador, opção C),
 * pela superfície HTTP.
 *
 * O `Otp` é o **real** do KAM-086 (com o repositório em memória e o SMS falso do
 * KAM-116) e a `TrocaDeTelefone` é a **real** do KAM-118; o repositório da troca
 * é o `TrocasEmMemoria`, com as mesmas transições condicionais da base. Falsas
 * são só as portas de base — o contacto do número, a `definir_dono` e os avisos
 * —, que registam o que lhes pedem. O estado e o papel na base medem-se contra o
 * PostgreSQL em `packages/core-ts/tests_bd/dono.bd.test.ts`.
 *
 * Os números são fictícios, com 999, e escritos com espaços.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  ESPERA_DA_TROCA_MS,
  TrocaDeTelefone,
  TrocasEmMemoria,
  otpDaTrocaPorChave,
  type DestinoDoAviso,
  type MomentoDoAviso,
} from "@kamba/core-ts/dono";
import {
  ContadoresEmMemoria,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  Telefone,
} from "@kamba/core-ts/inscricao";
import { FakeSmsProvider } from "@kamba/core-ts/sms";

import { CanalEmMemoria } from "../src/painel/canal.ts";
import { ComercioEmMemoria } from "../src/painel/comercio.ts";
import { MetricasDoPainel } from "../src/painel/metricas.ts";
import { FASE_DA_TROCA, LIMITE_POR_REDE, pedidoDaTroca, rotasDoPainel } from "../src/painel/rotas.ts";
import { RevogacoesEmMemoria, cunharSessao, novaSessao } from "../src/painel/sessao.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CASO_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a";
const CASO_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";
const CHAVE = new Uint8Array(32).fill(7);
const PEPPER = Buffer.alloc(32, 0x5a);
const PEPPER_DO_DESTINO = Buffer.alloc(32, 0x71);
const INICIO = new Date("2026-11-18T09:00:00.000Z");

/** Números fictícios, com 999. O antigo é o do dono de cada tenant. */
const NUMERO_NOVO = "+244 999 000 411";
const NUMERO_ANTIGO = "+244 999 000 400";
const NUMERO_DE_B = "+244 999 000 422";
const NUMERO_ALHEIO = "+244 999 000 433";

interface Montagem {
  app: ReturnType<typeof rotasDoPainel>;
  contadores: ContadoresEmMemoria;
  troca: TrocaDeTelefone;
  casos: Map<string, { tenantId: string; fase: string }>;
  sms: FakeSmsProvider;
  metricas: MetricasDoPainel;
  /** O que a `definir_dono` recebeu: `(tenant, contacto)`. */
  trocas: { tenantId: string; contactId: string }[];
  /** O dono de cada tenant, como a porta o deixa. */
  donos: Map<string, string>;
  avisos: { tenantId: string; destino: DestinoDoAviso; momento: MomentoDoAviso }[];
  agora: Date;
}

/** O contacto de um número: o «antigo» é o dono, o resto é pelo HMAC. */
function contactoDe(tenantId: string, telefone: Telefone, antigoHmac: string): string {
  const quem = telefone.hmac === antigoHmac ? "dono-antigo" : `contacto-${telefone.hmac.slice(0, 8)}`;
  return `${quem}-de-${tenantId.slice(0, 8)}`;
}

function montar(opcoes: { readonly avisoFalha?: boolean } = {}): Montagem {
  const m = {
    agora: INICIO,
    trocas: [],
    avisos: [],
    donos: new Map([
      [TENANT_A, "dono-antigo-de-aaaaaaaa"],
      [TENANT_B, "dono-antigo-de-bbbbbbbb"],
    ]),
  } as unknown as Montagem;
  const relogio = (): Date => m.agora;
  m.contadores = new ContadoresEmMemoria();
  m.sms = new FakeSmsProvider({ relogio });
  m.metricas = new MetricasDoPainel();
  const otp = new Otp({
    repositorio: new OtpEmMemoria(),
    contadores: new ContadoresEmMemoria(),
    provedor: new OtpPorSmsLocal({ sms: m.sms, pepperDoDestino: PEPPER_DO_DESTINO }),
    chave: PEPPER,
    relogio,
  });
  m.troca = new TrocaDeTelefone({
    relogio,
    otp: otpDaTrocaPorChave(otp),
    repositorio: new TrocasEmMemoria(async ({ tenantId, contactId }) => {
      m.trocas.push({ tenantId, contactId });
      const anterior = m.donos.get(tenantId) ?? null;
      m.donos.set(tenantId, contactId);
      return { anterior };
    }),
    contacto: async ({ tenantId, telefone }) => ({ contactId: contactoDe(tenantId, telefone, HMAC_ANTIGO) }),
    avisar: async (aviso) => {
      m.avisos.push(aviso);
      if (opcoes.avisoFalha === true) throw new Error("aviso_em_baixo");
    },
  });
  const casos = new Map([
    [CASO_A, { tenantId: TENANT_A, fase: "activo" }],
    [CASO_B, { tenantId: TENANT_B, fase: "activo" }],
  ]);
  m.casos = casos;
  m.app = rotasDoPainel({
    comercio: new ComercioEmMemoria(),
    canal: new CanalEmMemoria(),
    revogacoes: new RevogacoesEmMemoria(),
    metricas: m.metricas,
    casos: { porId: async (id) => casos.get(id) ?? null },
    anelDaAssinatura: [CHAVE, null],
    relogio,
    troca: { troca: m.troca, anelDoPepper: [PEPPER, null], contadores: m.contadores },
  });
  return m;
}

/** O HMAC do número antigo, com o *pepper* das rotas, para o contacto falso o reconhecer. */
const HMAC_ANTIGO = new Telefone(NUMERO_ANTIGO, [PEPPER, null]).hmac;

/** Uma sessao nova do painel: cada chamada da um `sid` novo. */
function cookie(tenant: string, caso: string, m: Montagem): string {
  return `kamba_painel=${cunharSessao(novaSessao(tenant, caso, m.agora), CHAVE)}`;
}

function post(m: Montagem, caminho: string, corpo: unknown, cabecalhoDoCookie?: string, extra: Record<string, string> = {}) {
  return m.app.request(caminho, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(cabecalhoDoCookie === undefined ? {} : { cookie: cabecalhoDoCookie }),
      ...extra,
    },
    body: JSON.stringify(corpo),
  });
}

function get(m: Montagem, caminho: string, cabecalhoDoCookie?: string) {
  return m.app.request(caminho, { headers: cabecalhoDoCookie === undefined ? {} : { cookie: cabecalhoDoCookie } });
}

function ultimoCodigo(m: Montagem): string {
  const codigo = /([0-9]{6})/.exec(m.sms.enviados.at(-1)?.corpo ?? "")?.[1] ?? "";
  assert.match(codigo, /^[0-9]{6}$/);
  return codigo;
}

/** O número novo pedido e provado: a troca fica pendente. */
async function pendente(m: Montagem, sessao: string, numero = NUMERO_NOVO): Promise<Response> {
  assert.equal((await post(m, "/painel/telefone", { telefone: numero }, sessao)).status, 200);
  return post(m, "/painel/telefone/verificar", { telefone: numero, codigo: ultimoCodigo(m) }, sessao);
}

/** O estado da troca viva, pelo `GET /painel/telefone`. */
async function estadoDaTroca(m: Montagem, sessao: string): Promise<string | null> {
  const corpo = (await (await get(m, "/painel/telefone", sessao)).json()) as { troca: { estado: string } | null };
  return corpo.troca?.estado ?? null;
}

const avancar = (m: Montagem, ms: number): void => {
  m.agora = new Date(m.agora.getTime() + ms);
};

describe("KAM-223 — a troca com prova de posse pelo painel", () => {
  let m: Montagem;
  let deA: string;

  beforeEach(() => {
    m = montar();
    deA = cookie(TENANT_A, CASO_A, m);
  });

  it("o codigo vai ao numero novo, e ate ele acertar nada muda", async () => {
    const r = await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    assert.equal(r.status, 200);
    assert.equal(m.sms.enviados.length, 1);
    assert.deepEqual([m.trocas, m.avisos], [[], []]);
  });

  it("o codigo certo do numero novo poe a troca pendente 72 h, avisa, e o papel nao muda", async () => {
    const r = await pendente(m, deA);
    assert.equal(r.status, 200);
    assert.deepEqual(await r.json(), {
      estado: "pendente",
      prazo: new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS).toISOString(),
    });
    assert.deepEqual(m.trocas, []);
    assert.deepEqual(
      m.avisos.map((a) => `${a.destino}:${a.momento}`),
      ["numero_antigo:pendente", "email:pendente"],
    );
    const estado = await get(m, "/painel/telefone", deA);
    assert.equal(estado.status, 200);
    const corpo = await estado.text();
    assert.deepEqual(JSON.parse(corpo), {
      troca: { estado: "pendente", prazo: new Date(INICIO.getTime() + ESPERA_DA_TROCA_MS).toISOString() },
    });
    // Sem numero nenhum na resposta: nem o novo, nem os digitos dele.
    assert.ok(!corpo.includes("411") && !corpo.includes("999"));
  });

  it("um cookie roubado sem o OTP do antigo nao troca antes das 72 h", async () => {
    await pendente(m, deA);
    avancar(m, ESPERA_DA_TROCA_MS - 1);
    const cedo = await post(m, "/painel/telefone/concluir", {}, deA);
    assert.equal(cedo.status, 409);
    assert.deepEqual(await cedo.json(), { erro: "cedo" });
    assert.equal(m.trocas.length, 0);
    avancar(m, 1);
    const feita = await post(m, "/painel/telefone/concluir", {}, deA);
    assert.equal(feita.status, 200);
    assert.deepEqual(await feita.json(), { estado: "feita" });
    assert.deepEqual(m.trocas.map((t) => t.tenantId), [TENANT_A]);
  });

  it("com o OTP do numero antigo, a troca e imediata", async () => {
    await pendente(m, deA);
    assert.equal(
      (await post(m, "/painel/telefone", { telefone: NUMERO_ANTIGO, numero: "antigo" }, deA)).status,
      200,
    );
    const r = await post(
      m,
      "/painel/telefone/verificar",
      { telefone: NUMERO_ANTIGO, codigo: ultimoCodigo(m), numero: "antigo" },
      deA,
    );
    assert.equal(r.status, 200);
    assert.deepEqual(await r.json(), { estado: "feita" });
    assert.equal(m.donos.get(TENANT_A), contactoDe(TENANT_A, new Telefone(NUMERO_NOVO, [PEPPER, null]), HMAC_ANTIGO));
    assert.deepEqual(await (await get(m, "/painel/telefone", deA)).json(), { troca: null });
  });

  it("o codigo certo de um numero que nao e o do dono da 401 e nao troca", async () => {
    await pendente(m, deA);
    await post(m, "/painel/telefone", { telefone: NUMERO_ALHEIO, numero: "antigo" }, deA);
    const r = await post(
      m,
      "/painel/telefone/verificar",
      { telefone: NUMERO_ALHEIO, codigo: ultimoCodigo(m), numero: "antigo" },
      deA,
    );
    assert.equal(r.status, 401);
    assert.deepEqual(await r.json(), { erro: "codigo" });
    assert.equal(m.donos.get(TENANT_A), "dono-antigo-de-aaaaaaaa");
    assert.equal(await estadoDaTroca(m, deA), "pendente");
  });

  it("achado 1: o cookie roubado nao passa o codigo do seu segundo numero pelo numero do dono", async () => {
    // Com o `Otp` real: o «antigo» pedido ao numero do dono (o codigo vai ao
    // dono), depois ao segundo numero do atacante (o codigo chega-lhe), e outra
    // vez ao do dono, que o intervalo de 60 s recusa — o HMAC do antigo fica o do
    // dono, e o desafio o do segundo numero. O codigo do segundo nao verifica o dono.
    await pendente(m, deA);
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_ANTIGO, numero: "antigo" }, deA)).status, 200);
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_ALHEIO, numero: "antigo" }, deA)).status, 200);
    const doAtacante = ultimoCodigo(m);
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_ANTIGO, numero: "antigo" }, deA)).status, 429);
    const r = await post(
      m,
      "/painel/telefone/verificar",
      { telefone: NUMERO_ANTIGO, codigo: doAtacante, numero: "antigo" },
      deA,
    );
    assert.equal(r.status, 401);
    assert.equal(m.donos.get(TENANT_A), "dono-antigo-de-aaaaaaaa");
    assert.equal(await estadoDaTroca(m, deA), "pendente");
  });

  it("o dono legitimo, noutra sessao, ve a troca pendente e cancela-a; depois das 72 h ja nao se faz", async () => {
    await pendente(m, deA);
    const doDono = cookie(TENANT_A, CASO_A, m);
    assert.equal(await estadoDaTroca(m, doDono), "pendente");
    assert.equal((await post(m, "/painel/telefone/cancelar", {}, doDono)).status, 200);
    avancar(m, ESPERA_DA_TROCA_MS + 1);
    const r = await post(m, "/painel/telefone/concluir", {}, deA);
    assert.equal(r.status, 409);
    assert.deepEqual(await r.json(), { erro: "sem_troca" });
    assert.deepEqual(m.trocas, []);
    assert.deepEqual(m.avisos.slice(2).map((a) => a.momento), ["cancelada", "cancelada"]);
  });

  it("o numero vem com o codigo: outro numero com o codigo certo da 401", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    const r = await post(m, "/painel/telefone/verificar", { telefone: NUMERO_ALHEIO, codigo: ultimoCodigo(m) }, deA);
    assert.equal(r.status, 401);
    assert.deepEqual(m.avisos, []);
  });

  it("um codigo errado da 401 e nao abre a espera; o pedido continua vivo", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    const certo = ultimoCodigo(m);
    const errado = certo === "000000" ? "111111" : "000000";
    const r = await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo: errado }, deA);
    assert.equal(r.status, 401);
    assert.deepEqual(await r.json(), { erro: "codigo" });
    assert.deepEqual(m.avisos, []);
    assert.equal((await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo: certo }, deA)).status, 200);
  });

  it("o pedido gasta-se: o mesmo codigo outra vez da 401", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    const codigo = ultimoCodigo(m);
    assert.equal((await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo }, deA)).status, 200);
    assert.equal((await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo }, deA)).status, 401);
  });

  it("uma troca viva por tenant: outra sessao recebe 409; a mesma sessao pede outra vez e o primeiro codigo deixa de valer", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    const primeiro = ultimoCodigo(m);
    const outra = await post(m, "/painel/telefone", { telefone: NUMERO_ALHEIO }, cookie(TENANT_A, CASO_A, m));
    assert.equal(outra.status, 409);
    assert.deepEqual(await outra.json(), { erro: "ocupado" });
    avancar(m, 61_000);
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_ALHEIO }, deA)).status, 200);
    assert.equal(
      (await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo: primeiro }, deA)).status,
      401,
    );
    assert.equal(
      (await post(m, "/painel/telefone/verificar", { telefone: NUMERO_ALHEIO, codigo: ultimoCodigo(m) }, deA)).status,
      200,
    );
  });

  it("o numero antigo sem troca pendente da 409, e o mesmo numero do novo da 400", async () => {
    const sem = await post(m, "/painel/telefone", { telefone: NUMERO_ANTIGO, numero: "antigo" }, deA);
    assert.equal(sem.status, 409);
    assert.deepEqual(await sem.json(), { erro: "sem_troca" });
    await pendente(m, deA);
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO, numero: "antigo" }, deA)).status, 400);
  });

  it("um `numero` fora dos dois, um telefone ilegivel e um corpo que nao e JSON dao 400", async () => {
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO, numero: "outro" }, deA)).status, 400);
    for (const telefone of ["", "nao e telefone", 999, null]) {
      assert.equal((await post(m, "/painel/telefone", { telefone }, deA)).status, 400);
    }
    const r = await m.app.request("/painel/telefone", {
      method: "POST",
      headers: { "content-type": "text/plain", cookie: deA },
      body: NUMERO_NOVO,
    });
    assert.equal(r.status, 400);
    assert.equal((await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo: 123456 }, deA)).status, 400);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo: "123456" }, deA)).status, 400);
    assert.equal(m.sms.enviados.length, 0);
  });

  it("sem sessao e 401, e sem a troca configurada e 503, nas cinco rotas", async () => {
    for (const [metodo, caminho] of [
      ["POST", "/painel/telefone"],
      ["POST", "/painel/telefone/verificar"],
      ["GET", "/painel/telefone"],
      ["POST", "/painel/telefone/concluir"],
      ["POST", "/painel/telefone/cancelar"],
    ] as const) {
      const r = metodo === "GET" ? await get(m, caminho) : await post(m, caminho, {});
      assert.equal(r.status, 401, caminho);
    }
    assert.equal(m.sms.enviados.length, 0);
    const sem = rotasDoPainel({
      comercio: new ComercioEmMemoria(),
      canal: new CanalEmMemoria(),
      revogacoes: new RevogacoesEmMemoria(),
      casos: { porId: async () => ({ tenantId: TENANT_A, fase: "activo" }) },
      anelDaAssinatura: [CHAVE, null],
      relogio: () => m.agora,
    });
    for (const caminho of ["/painel/telefone/concluir", "/painel/telefone/cancelar"]) {
      const r = await sem.request(caminho, { method: "POST", headers: { "content-type": "application/json", cookie: deA }, body: "{}" });
      assert.equal(r.status, 503, caminho);
    }
    assert.equal((await sem.request("/painel/telefone", { headers: { cookie: deA } })).status, 503);
  });

  it("um aviso que falha sobe depois de gravar, e a troca fica pendente", async () => {
    const falhado = montar({ avisoFalha: true });
    const sessao = cookie(TENANT_A, CASO_A, falhado);
    const r = await pendente(falhado, sessao);
    assert.equal(r.status, 500);
    assert.equal((await falhado.troca.estado(TENANT_A))?.estado, "pendente");
  });

  it("antes de `activo` as rotas da troca recusam com 409 e nao mandam codigo (achado 4 do KAM-211)", async () => {
    for (const fase of ["aguarda_es", "lista_espera", "aguarda_catalogo", "aguarda_teste"]) {
      m.casos.set(CASO_A, { tenantId: TENANT_A, fase });
      assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA)).status, 409, fase);
      assert.equal((await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo: "123456" }, deA)).status, 409, fase);
      assert.equal((await get(m, "/painel/telefone", deA)).status, 409, fase);
      assert.equal((await post(m, "/painel/telefone/concluir", {}, deA)).status, 409, fase);
      assert.equal((await post(m, "/painel/telefone/cancelar", {}, deA)).status, 409, fase);
    }
    assert.equal(m.sms.enviados.length, 0);
    assert.equal(FASE_DA_TROCA, "activo");
  });

  it("ha limite por rede: o seguinte ao limite da 429 e nao envia (achado 3 do KAM-211)", async () => {
    for (let n = 0; n < LIMITE_POR_REDE; n += 1) {
      const numero = `+244 999 000 ${String(500 + n)}`;
      // Uma sessao nova de cada vez, e a anterior cancela: uma troca viva por tenant.
      const sessao = cookie(TENANT_A, CASO_A, m);
      assert.equal((await post(m, "/painel/telefone", { telefone: numero }, sessao)).status, 200, numero);
      await m.troca.cancelar(TENANT_A);
    }
    const r = await post(m, "/painel/telefone", { telefone: "+244 999 000 599" }, cookie(TENANT_A, CASO_A, m));
    assert.equal(r.status, 429);
    assert.equal(m.sms.enviados.length, LIMITE_POR_REDE);
  });

  it("a chave do pedido e a sessao, com o prefixo da troca", () => {
    const s = novaSessao(TENANT_A, CASO_A, INICIO);
    assert.equal(pedidoDaTroca(s), `troca:${s.sid}`);
    assert.notEqual(pedidoDaTroca(s), CASO_A);
  });

  it("as rotas contam-se nas metricas do painel", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO });
    await post(m, "/painel/telefone/verificar", { codigo: "x" }, deA);
    await post(m, "/painel/telefone/concluir", {}, deA);
    await post(m, "/painel/telefone/cancelar", {}, deA);
    await get(m, "/painel/telefone", deA);
    assert.equal(m.metricas.valor("troca"), 1);
    assert.equal(m.metricas.valor("troca", "sem_sessao"), 1);
    assert.equal(m.metricas.valor("troca_verificar", "invalido"), 1);
    assert.equal(m.metricas.valor("troca_concluir", "conflito"), 1);
    assert.equal(m.metricas.valor("troca_cancelar", "conflito"), 1);
    assert.equal(m.metricas.valor("troca_estado"), 1);
  });
});

describe("KAM-223 — a troca isola o tenant e a sessao", () => {
  it("o tenant de B no corpo, na consulta ou num cabecalho nao muda nada: a troca e de A", async () => {
    for (const [caminho, extra, corpoExtra] of [
      ["/painel/telefone", {}, { tenant_id: TENANT_B }],
      [`/painel/telefone?tenant_id=${TENANT_B}`, {}, {}],
      ["/painel/telefone", { "x-kamba-tenant": TENANT_B }, {}],
    ] as const) {
      const m = montar();
      const sessao = cookie(TENANT_A, CASO_A, m);
      await post(m, caminho, { telefone: NUMERO_NOVO, ...corpoExtra }, sessao, extra);
      const codigo = ultimoCodigo(m);
      const r = await post(
        m,
        `/painel/telefone/verificar?tenant_id=${TENANT_B}`,
        { telefone: NUMERO_NOVO, codigo, tenant_id: TENANT_B },
        sessao,
        extra,
      );
      assert.equal(r.status, 200);
      assert.equal((await m.troca.estado(TENANT_A))?.estado, "pendente");
      assert.equal(await m.troca.estado(TENANT_B), null);
      avancar(m, ESPERA_DA_TROCA_MS);
      await post(m, `/painel/telefone/concluir?tenant_id=${TENANT_B}`, { tenant_id: TENANT_B }, sessao, extra);
      assert.ok(m.trocas.length === 1 && m.trocas.every((t) => t.tenantId === TENANT_A));
    }
  });

  it("a sessao de A nao verifica o pedido de B, nem com o numero e o codigo certos de B", async () => {
    const m = montar();
    const deB = cookie(TENANT_B, CASO_B, m);
    await post(m, "/painel/telefone", { telefone: NUMERO_DE_B }, deB);
    const codigoDeB = ultimoCodigo(m);
    const deA = cookie(TENANT_A, CASO_A, m);
    const r = await post(m, "/painel/telefone/verificar", { telefone: NUMERO_DE_B, codigo: codigoDeB, tenant_id: TENANT_B }, deA);
    assert.equal(r.status, 401);
    assert.equal(await m.troca.estado(TENANT_A), null);
    // E o de B continua vivo para B.
    assert.equal((await post(m, "/painel/telefone/verificar", { telefone: NUMERO_DE_B, codigo: codigoDeB }, deB)).status, 200);
  });

  it("a sessao de A nao ve, nao conclui e nao cancela a troca pendente de B", async () => {
    const m = montar();
    const deB = cookie(TENANT_B, CASO_B, m);
    await pendente(m, deB, NUMERO_DE_B);
    const deA = cookie(TENANT_A, CASO_A, m);
    assert.deepEqual(await (await get(m, `/painel/telefone?tenant_id=${TENANT_B}`, deA)).json(), { troca: null });
    assert.equal((await post(m, "/painel/telefone/cancelar", { tenant_id: TENANT_B }, deA)).status, 409);
    avancar(m, ESPERA_DA_TROCA_MS);
    assert.equal((await post(m, "/painel/telefone/concluir", { tenant_id: TENANT_B }, deA)).status, 409);
    assert.equal((await m.troca.estado(TENANT_B))?.estado, "pendente");
    assert.deepEqual(m.trocas, []);
  });

  it("outra sessao do mesmo tenant nao verifica o numero novo pedido pela primeira", async () => {
    const m = montar();
    const primeira = cookie(TENANT_A, CASO_A, m);
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, primeira);
    const codigo = ultimoCodigo(m);
    const segunda = cookie(TENANT_A, CASO_A, m);
    assert.equal((await post(m, "/painel/telefone/verificar", { telefone: NUMERO_NOVO, codigo }, segunda)).status, 401);
    assert.equal((await m.troca.estado(TENANT_A))?.estado, "pedida");
  });

  it("uma sessao forjada com o sid de B nao passa a assinatura", async () => {
    const m = montar();
    const forjada = `kamba_painel=${cunharSessao(novaSessao(TENANT_B, CASO_B, INICIO), new Uint8Array(32).fill(9))}`;
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, forjada)).status, 401);
    assert.equal(m.sms.enviados.length, 0);
  });
});
