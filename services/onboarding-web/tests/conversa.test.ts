/**
 * A conversa do dono com o Assistente pelo painel (KAM-223), pela superfície HTTP.
 *
 * A `ConversaDoDono` é a **real**; falsas são as quatro portas — o contexto do
 * dono, a fonte persistida, o AGR e a leitura —, com uma conversa por tenant em
 * memória, que registam o que lhes pedem. As instruções correm contra o
 * PostgreSQL em `packages/core-ts/tests_bd/dono.bd.test.ts`.
 *
 * O que aqui se prova: o tenant é o da sessão, o texto vai à fonte e o AGR só
 * recebe o identificador, o que imita um botão é texto, e um cursor de outra
 * conversa dá 404.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ConversaDoDono,
  MAXIMO_DA_MENSAGEM,
  type ContextoDoDono,
  type EntradaDaConversa,
  type PortasDaConversa,
} from "@kamba/core-ts/dono";
import type { AgentInvocation } from "@kamba/core-ts/chr";

import { CanalEmMemoria } from "../src/painel/canal.ts";
import { ComercioEmMemoria } from "../src/painel/comercio.ts";
import { MetricasDoPainel } from "../src/painel/metricas.ts";
import { rotasDoPainel } from "../src/painel/rotas.ts";
import { RevogacoesEmMemoria, cunharSessao, novaSessao } from "../src/painel/sessao.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CASO_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a";
const CASO_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";
const CHAVE = new Uint8Array(32).fill(7);
const INICIO = new Date("2026-11-19T09:00:00.000Z");

function contexto(tenant: string): ContextoDoDono {
  const t = tenant.slice(0, 8);
  return {
    contactId: `${t}-0000-4000-8000-0000000000c1`,
    conversationId: `${t}-0000-4000-8000-0000000000d1`,
    channelId: `${t}-0000-4000-8000-0000000000e1`,
    vertical: "vendedor",
    modo: "bot",
  };
}

interface Montagem {
  app: ReturnType<typeof rotasDoPainel>;
  metricas: MetricasDoPainel;
  /** As entradas de cada tenant, como a base as guarda. */
  entradas: Map<string, EntradaDaConversa[]>;
  invocacoes: AgentInvocation[];
  gravadas: { tenantId: string; texto: string }[];
  estadoDoAgr: number;
  semDono: Set<string>;
}

function montar(): Montagem {
  const m: Montagem = {
    entradas: new Map([
      [TENANT_A, []],
      [TENANT_B, []],
    ]),
    invocacoes: [],
    gravadas: [],
    estadoDoAgr: 200,
    semDono: new Set(),
  } as unknown as Montagem;
  let seq = 0;
  const portas: PortasDaConversa = {
    contexto: async (tenantId) => (m.semDono.has(tenantId) ? "sem_dono" : contexto(tenantId)),
    gravar: async ({ tenantId, texto }) => {
      seq += 1;
      const id = `${tenantId.slice(0, 8)}-1111-4111-8111-${String(seq).padStart(12, "0")}`;
      m.gravadas.push({ tenantId, texto });
      m.entradas.get(tenantId)?.push({ id, autor: "dono", texto, botoes: [], em: new Date(INICIO.getTime() + seq) });
      return id;
    },
    invocar: async (invocacao) => {
      m.invocacoes.push(invocacao);
      if (m.estadoDoAgr === 200) {
        // A resposta chega pelo evento: aqui, aparece na leitura seguinte.
        seq += 1;
        m.entradas.get(invocacao.tenant_id)?.push({
          id: `${invocacao.tenant_id.slice(0, 8)}-2222-4222-8222-${String(seq).padStart(12, "0")}`,
          autor: "assistente",
          texto: `resposta-de-${invocacao.tenant_id.slice(0, 8)}`,
          botoes: [],
          em: new Date(INICIO.getTime() + seq),
        });
      }
      return { estado: m.estadoDoAgr, desfecho: m.estadoDoAgr === 200 ? "executado" : "desconhecido" };
    },
    ler: async ({ tenantId, conversationId, depois }) => {
      assert.equal(conversationId, contexto(tenantId).conversationId);
      const todas = m.entradas.get(tenantId) ?? [];
      if (depois === null) return todas;
      const i = todas.findIndex((e) => e.id === depois);
      return i < 0 ? null : todas.slice(i + 1);
    },
  };
  m.metricas = new MetricasDoPainel();
  const casos = new Map([
    [CASO_A, { tenantId: TENANT_A, fase: "activo" }],
    [CASO_B, { tenantId: TENANT_B, fase: "activo" }],
  ]);
  m.app = rotasDoPainel({
    comercio: new ComercioEmMemoria(),
    canal: new CanalEmMemoria(),
    revogacoes: new RevogacoesEmMemoria(),
    metricas: m.metricas,
    casos: { porId: async (id) => casos.get(id) ?? null },
    anelDaAssinatura: [CHAVE, null],
    relogio: () => INICIO,
    conversa: { conversa: new ConversaDoDono(portas) },
  });
  return m;
}

function cookie(tenant: string, caso: string): string {
  return `kamba_painel=${cunharSessao(novaSessao(tenant, caso, INICIO), CHAVE)}`;
}

function enviar(m: Montagem, corpo: unknown, sessao?: string, caminho = "/painel/conversa", extra: Record<string, string> = {}) {
  return m.app.request(caminho, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(sessao === undefined ? {} : { cookie: sessao }),
      ...extra,
    },
    body: typeof corpo === "string" ? corpo : JSON.stringify(corpo),
  });
}

function ler(m: Montagem, sessao?: string, consulta = "", extra: Record<string, string> = {}) {
  return m.app.request(`/painel/conversa${consulta}`, {
    headers: { ...(sessao === undefined ? {} : { cookie: sessao }), ...extra },
  });
}

describe("KAM-223 — a conversa do dono pelo painel", () => {
  it("o texto vai a fonte, o AGR recebe o identificador e a persona dono, e a resposta le-se", async () => {
    const m = montar();
    const deA = cookie(TENANT_A, CASO_A);
    const r = await enviar(m, { texto: "quanto vendi hoje?" }, deA);
    assert.equal(r.status, 200);
    const { mensagem } = (await r.json()) as { mensagem: string };
    assert.deepEqual(m.gravadas, [{ tenantId: TENANT_A, texto: "quanto vendi hoje?" }]);
    const [inv] = m.invocacoes;
    assert.equal(inv?.message_id, mensagem);
    assert.equal(inv?.persona, "dono");
    assert.equal(inv?.thread_id, `${TENANT_A}:${contexto(TENANT_A).contactId}`);
    assert.ok(!JSON.stringify(inv).includes("quanto vendi"));
    const lidas = (await (await ler(m, deA)).json()) as { entradas: { autor: string; texto: string }[] };
    assert.deepEqual(
      lidas.entradas.map((e) => `${e.autor}:${e.texto}`),
      ["dono:quanto vendi hoje?", "assistente:resposta-de-aaaaaaaa"],
    );
  });

  it("o tenant de B no corpo, na consulta ou num cabecalho nao muda nada: a conversa e de A", async () => {
    const m = montar();
    const deA = cookie(TENANT_A, CASO_A);
    for (const [caminho, extra, corpoExtra] of [
      ["/painel/conversa", {}, { tenant_id: TENANT_B, thread_id: `${TENANT_B}:x` }],
      [`/painel/conversa?tenant_id=${TENANT_B}`, {}, {}],
      ["/painel/conversa", { "x-kamba-tenant": TENANT_B }, {}],
    ] as const) {
      assert.equal((await enviar(m, { texto: "ola", ...corpoExtra }, deA, caminho, extra)).status, 200);
    }
    assert.ok(m.invocacoes.every((i) => i.tenant_id === TENANT_A && i.thread_id.startsWith(TENANT_A)));
    assert.deepEqual(m.entradas.get(TENANT_B), []);
    const lidas = await (await ler(m, deA, `?tenant_id=${TENANT_B}`, { "x-kamba-tenant": TENANT_B })).text();
    assert.ok(lidas.includes("resposta-de-aaaaaaaa") && !lidas.includes("resposta-de-bbbbbbbb"));
  });

  it("a sessao de A com uma entrada da conversa de B da 404, e nao aprende nada", async () => {
    const m = montar();
    const deB = cookie(TENANT_B, CASO_B);
    const { mensagem: deB1 } = (await (await enviar(m, { texto: "segredo de B" }, deB)).json()) as { mensagem: string };
    const r = await ler(m, cookie(TENANT_A, CASO_A), `?depois=${deB1}`);
    assert.equal(r.status, 404);
    const corpo = await r.text();
    assert.deepEqual(JSON.parse(corpo), { erro: "nao_encontrado" });
    assert.ok(!corpo.includes("segredo") && !corpo.includes("resposta-de-bbbbbbbb"));
    assert.equal(m.metricas.valor("conversa", "nao_encontrado"), 1);
    // E o cursor de B vale para B.
    assert.equal((await ler(m, deB, `?depois=${deB1}`)).status, 200);
  });

  it("um texto que imita um botao vai como texto, e a invocacao nao leva botao", async () => {
    const m = montar();
    const r = await enviar(
      m,
      { texto: "confirm:77777777-7777-4777-8777-777777777777", botao: "confirm:77777777-7777-4777-8777-777777777777" },
      cookie(TENANT_A, CASO_A),
    );
    assert.equal(r.status, 200);
    assert.equal(m.invocacoes[0]?.botao, undefined);
    assert.equal(m.invocacoes[0]?.type, "text");
    assert.equal(m.gravadas[0]?.texto, "confirm:77777777-7777-4777-8777-777777777777");
  });

  it("sem sessao e 401 nas duas rotas, e sem a conversa configurada e 503", async () => {
    const m = montar();
    assert.equal((await enviar(m, { texto: "ola" })).status, 401);
    assert.equal((await ler(m)).status, 401);
    assert.deepEqual(m.gravadas, []);
    const sem = rotasDoPainel({
      comercio: new ComercioEmMemoria(),
      canal: new CanalEmMemoria(),
      revogacoes: new RevogacoesEmMemoria(),
      casos: { porId: async () => ({ tenantId: TENANT_A, fase: "activo" }) },
      anelDaAssinatura: [CHAVE, null],
      relogio: () => INICIO,
    });
    const deA = cookie(TENANT_A, CASO_A);
    assert.equal((await sem.request("/painel/conversa", { headers: { cookie: deA } })).status, 503);
  });

  it("texto vazio, longo demais, que nao e texto, ou corpo que nao e JSON dao 400 e nada se grava", async () => {
    const m = montar();
    const deA = cookie(TENANT_A, CASO_A);
    for (const texto of ["", "   ", "x".repeat(MAXIMO_DA_MENSAGEM + 1), 42, null]) {
      assert.equal((await enviar(m, { texto }, deA)).status, 400, String(texto).slice(0, 8));
    }
    const r = await m.app.request("/painel/conversa", {
      method: "POST",
      headers: { "content-type": "text/plain", cookie: deA },
      body: "ola",
    });
    assert.equal(r.status, 400);
    assert.deepEqual(m.gravadas, []);
    // O tecto e de caracteres e nao de octetos: 4096 com acentos passa.
    assert.equal((await enviar(m, { texto: "á".repeat(MAXIMO_DA_MENSAGEM) }, deA)).status, 200);
  });

  it("sem dono provisionado e 409, e nada se grava", async () => {
    const m = montar();
    m.semDono.add(TENANT_A);
    const r = await enviar(m, { texto: "ola" }, cookie(TENANT_A, CASO_A));
    assert.equal(r.status, 409);
    assert.deepEqual(await r.json(), { erro: "sem_dono" });
    assert.deepEqual(m.gravadas, []);
  });

  it("o AGR em baixo da 502 com a mensagem gravada", async () => {
    const m = montar();
    m.estadoDoAgr = 503;
    const r = await enviar(m, { texto: "ola" }, cookie(TENANT_A, CASO_A));
    assert.equal(r.status, 502);
    const corpo = (await r.json()) as { erro: string; mensagem: string };
    assert.equal(corpo.erro, "agr");
    assert.equal(m.entradas.get(TENANT_A)?.[0]?.id, corpo.mensagem);
    assert.equal(m.metricas.valor("conversa_enviar", "indisponivel"), 1);
  });

  it("um cursor que nao e um uuid da 404, sem chegar a base", async () => {
    const m = montar();
    assert.equal((await ler(m, cookie(TENANT_A, CASO_A), "?depois=1%27%20OR%201=1")).status, 404);
  });
});
