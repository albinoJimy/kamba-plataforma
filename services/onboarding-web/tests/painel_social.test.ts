/**
 * A página Social do painel (KAM-246), pela superfície HTTP.
 *
 * O AGR é um duplo que regista o tenant de cada pedido: o que se mede é a
 * ligação — o tenant que a rota passa é o da sessão, e nunca o do pedido — e a
 * página que sai. O cliente HTTP do AGR (`socialPeloAgr`) mede-se com um
 * `fetch` de duplo, e as rotas do lado do AGR têm os seus ensaios em
 * `services/agr/tests/test_social_painel.py`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { CABECALHO_INTERNO } from "@kamba/core-ts/agr";

import { CanalEmMemoria } from "../src/painel/canal.ts";
import { ComercioEmMemoria } from "../src/painel/comercio.ts";
import { MetricasDoPainel } from "../src/painel/metricas.ts";
import { rotasDoPainel, type OpcoesDoPainel } from "../src/painel/rotas.ts";
import { NOME_DO_COOKIE_DO_PAINEL, RevogacoesEmMemoria, cunharSessao, novaSessao } from "../src/painel/sessao.ts";
import {
  CABECALHO_DA_CREDENCIAL,
  ROTA_DA_DESCARGA_NO_AGR,
  ROTA_DOS_ITENS_NO_AGR,
  cspComImagens,
  origensDasImagens,
  socialPeloAgr,
  type ItemDoSocial,
  type ResultadoDoSocial,
  type SocialDoPainel,
} from "../src/painel/social.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CASO_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a";
const CHAVE = new Uint8Array(32).fill(7);
const INICIO = new Date("2026-11-23T09:00:00.000Z");
const LIGACAO_DE_A = "bGlnYWNhby1kZS1h.YXNzaW5hdHVyYQ";
const LIGACAO_DE_B = "bGlnYWNhby1kZS1i.YXNzaW5hdHVyYQ";

function item(tenant: string, extra: Partial<ItemDoSocial> = {}): ItemDoSocial {
  return {
    referencia: tenant === TENANT_A ? "SOC-ABCDEFGH" : "SOC-HGFEDCBA",
    estado: "aprovado",
    tema: `Tema de ${tenant.slice(0, 1)}`,
    legenda: `Legenda de ${tenant.slice(0, 1)}`,
    nota: "Ao publicar, active o rotulo de IA da rede social.",
    imagem: `https://sto.ensaio.invalid/t/${tenant}/arte.jpg?assinatura=x`,
    ligacao: tenant === TENANT_A ? LIGACAO_DE_A : LIGACAO_DE_B,
    ...extra,
  };
}

/** O AGR de duplo: a lista e a abertura por tenant, e o tenant de cada pedido. */
class SocialDuplo implements SocialDoPainel {
  readonly tenants: string[] = [];
  readonly itensPorTenant = new Map<string, ItemDoSocial[]>([
    [TENANT_A, [item(TENANT_A)]],
    [TENANT_B, [item(TENANT_B)]],
  ]);
  emBaixo = false;

  async itens(tenantId: string): Promise<ResultadoDoSocial<readonly ItemDoSocial[]>> {
    this.tenants.push(tenantId);
    if (this.emBaixo) return { tipo: "indisponivel" };
    return { tipo: "ok", valor: this.itensPorTenant.get(tenantId) ?? [] };
  }

  async abrir(tenantId: string, ligacao: string): Promise<ResultadoDoSocial<string>> {
    this.tenants.push(tenantId);
    if (this.emBaixo) return { tipo: "indisponivel" };
    const de = ligacao === LIGACAO_DE_A ? TENANT_A : ligacao === LIGACAO_DE_B ? TENANT_B : null;
    return de === tenantId ? { tipo: "ok", valor: `https://sto.ensaio.invalid/t/${de}/arte.jpg?cinco=minutos` } : { tipo: "recusada" };
  }
}

function montar(extra: Partial<OpcoesDoPainel> = {}) {
  const social = new SocialDuplo();
  const app = rotasDoPainel({
    comercio: new ComercioEmMemoria(),
    canal: new CanalEmMemoria(),
    revogacoes: new RevogacoesEmMemoria(),
    metricas: new MetricasDoPainel(),
    casos: { porId: async (id) => (id === CASO_A ? { tenantId: TENANT_A, fase: "activo" } : null) },
    anelDaAssinatura: [CHAVE, null],
    relogio: () => INICIO,
    social,
    ...extra,
  });
  return { app, social };
}

const COOKIE = `${NOME_DO_COOKIE_DO_PAINEL}=${cunharSessao(novaSessao(TENANT_A, CASO_A, INICIO), CHAVE)}`;

function get(caminho: string, cookie = COOKIE, extra: Record<string, string> = {}): Request {
  return new Request(`http://127.0.0.1${caminho}`, { headers: { cookie, ...extra } });
}

test("KAM-246: a página Social mostra a imagem, a legenda para copiar, a nota e a ligação de A, e só de A", async () => {
  const { app, social } = montar();
  const r = await app.request(get(`/painel/social?tenant_id=${TENANT_B}`, COOKIE, { "x-kamba-tenant": TENANT_B }));
  assert.equal(r.status, 200);
  const html = await r.text();
  assert.deepEqual(social.tenants, [TENANT_A], "o tenant é o da sessão, e não o do pedido");
  assert.match(html, /<textarea readonly rows="6">Legenda de a<\/textarea>/);
  assert.match(html, /<img src="https:\/\/sto\.ensaio\.invalid\/t\/aaaaaaaa/);
  assert.match(html, /active o rotulo de IA/);
  assert.match(html, /href="\/painel\/social\/descarga\?l=bGlnYWNhby1kZS1h\.YXNzaW5hdHVyYQ"/);
  assert.doesNotMatch(html, /Legenda de b|bbbbbbbb/);
  // A CSP desta página deixa as imagens vir da origem do STO, e só dela.
  const csp = r.headers.get("content-security-policy") ?? "";
  assert.match(csp, /default-src 'none'/);
  assert.match(csp, /; img-src https:\/\/sto\.ensaio\.invalid$/);
});

test("KAM-246: nenhum botão de publicação nem ligação a uma rede na página", async () => {
  const { app } = montar();
  const html = await (await app.request(get("/painel/social"))).text();
  assert.doesNotMatch(html, /<button[^>]*>[^<]*public/i);
  assert.doesNotMatch(html, /href="https?:\/\/[^"]*(instagram|facebook|tiktok|threads)/i);
  assert.doesNotMatch(html, /<form[^>]*action="[^"]*social/i, "a página não submete nada");
});

test("KAM-246: tudo o que vem do AGR passa pelo escapar", async () => {
  const { app, social } = montar();
  social.itensPorTenant.set(TENANT_A, [item(TENANT_A, { legenda: "<script>alert(1)</script>", tema: '"><img src=x>' })]);
  const html = await (await app.request(get("/painel/social"))).text();
  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /"><img src=x>/);
});

test("KAM-246: sem sessão, 401 nas duas, e o AGR não é chamado", async () => {
  const { app, social } = montar();
  for (const caminho of ["/painel/social", `/painel/social/descarga?l=${LIGACAO_DE_A}`]) {
    assert.equal((await app.request(get(caminho, ""))).status, 401, caminho);
  }
  assert.deepEqual(social.tenants, []);
});

test("KAM-246: sem a porta, ou com o AGR em baixo, 503 — o custo aceite da Q2 = A", async () => {
  const sem = montar({ social: undefined });
  assert.equal((await sem.app.request(get("/painel/social"))).status, 503);
  assert.equal((await sem.app.request(get(`/painel/social/descarga?l=${LIGACAO_DE_A}`))).status, 503);
  const { app, social } = montar();
  social.emBaixo = true;
  assert.equal((await app.request(get("/painel/social"))).status, 503);
  assert.equal((await app.request(get(`/painel/social/descarga?l=${LIGACAO_DE_A}`))).status, 503);
});

test("KAM-246: a ligação de A abre com 302 para o URL de cinco minutos, sem cache e sem Referer", async () => {
  const { app, social } = montar();
  const r = await app.request(get(`/painel/social/descarga?l=${encodeURIComponent(LIGACAO_DE_A)}`));
  assert.equal(r.status, 302);
  assert.equal(r.headers.get("location"), `https://sto.ensaio.invalid/t/${TENANT_A}/arte.jpg?cinco=minutos`);
  assert.equal(r.headers.get("cache-control"), "no-store");
  assert.equal(r.headers.get("referrer-policy"), "no-referrer");
  assert.deepEqual(social.tenants, [TENANT_A]);
});

test("KAM-246: a ligação de B na sessão de A, uma adulterada ou fora da forma dão o mesmo 404", async () => {
  const { app, social } = montar();
  const corpos = new Set<string>();
  for (const l of [LIGACAO_DE_B, `${LIGACAO_DE_A}x`, "sem-ponto", "a".repeat(2000), "<script>.x"]) {
    const r = await app.request(get(`/painel/social/descarga?l=${encodeURIComponent(l)}&tenant_id=${TENANT_B}`));
    assert.equal(r.status, 404, l.slice(0, 20));
    corpos.add((await r.text()).replace(/nonce-[0-9a-f]+|nonce="[0-9a-f]+"/g, ""));
  }
  assert.equal(corpos.size, 1, "a mesma página para todas as recusas");
  assert.ok(social.tenants.every((t) => t === TENANT_A), "o AGR só ouviu o tenant da sessão");
  // As fora da forma não chegam ao AGR: só a de B e a adulterada.
  assert.equal(social.tenants.length, 2);
});

test("KAM-246: o cliente do AGR leva a credencial do painel, o tenant e só isso", async () => {
  const pedidos: { url: string; init: RequestInit }[] = [];
  const buscar = (async (url: string | URL | Request, init?: RequestInit) => {
    pedidos.push({ url: String(url), init: init ?? {} });
    if (String(url).endsWith(ROTA_DOS_ITENS_NO_AGR)) {
      return new Response(JSON.stringify({ itens: [item(TENANT_A)] }), { status: 200 });
    }
    return new Response(JSON.stringify({ url: "https://sto.ensaio.invalid/x?y=z" }), { status: 200 });
  }) as typeof fetch;
  const porta = socialPeloAgr({ agr: "http://agr.interno:8000", credencial: () => "credencial-do-painel", buscar });
  assert.deepEqual(await porta.itens(TENANT_A), { tipo: "ok", valor: [item(TENANT_A)] });
  assert.deepEqual(await porta.abrir(TENANT_A, LIGACAO_DE_A), { tipo: "ok", valor: "https://sto.ensaio.invalid/x?y=z" });
  assert.deepEqual(
    pedidos.map((p) => [p.url, JSON.parse(String(p.init.body))]),
    [
      [`http://agr.interno:8000${ROTA_DOS_ITENS_NO_AGR}`, { tenant_id: TENANT_A }],
      [`http://agr.interno:8000${ROTA_DA_DESCARGA_NO_AGR}`, { tenant_id: TENANT_A, ligacao: LIGACAO_DE_A }],
    ],
  );
  for (const p of pedidos) {
    assert.equal((p.init.headers as Record<string, string>)[CABECALHO_DA_CREDENCIAL], "credencial-do-painel");
  }
});

test("KAM-246: uma resposta do AGR fora da forma é o AGR indisponível, e um URL que não é http não passa", async () => {
  const responder = (estado: number, corpo: unknown) =>
    socialPeloAgr({
      agr: "http://agr.interno:8000",
      credencial: () => "c",
      buscar: (async () => new Response(JSON.stringify(corpo), { status: estado })) as typeof fetch,
    });
  for (const imagem of ["javascript:alert(1)", "data:image/png;base64,AA", "//sem-esquema/x"]) {
    assert.deepEqual(await responder(200, { itens: [item(TENANT_A, { imagem })] }).itens(TENANT_A), { tipo: "indisponivel" });
  }
  assert.deepEqual(await responder(200, { itens: [item(TENANT_A, { referencia: "SOC-12345678" })] }).itens(TENANT_A), {
    tipo: "indisponivel",
  });
  assert.deepEqual(await responder(200, { url: "javascript:alert(1)" }).abrir(TENANT_A, LIGACAO_DE_A), { tipo: "indisponivel" });
  assert.deepEqual(await responder(404, { outcome: "ligacao_recusada" }).abrir(TENANT_A, LIGACAO_DE_A), { tipo: "recusada" });
  assert.deepEqual(await responder(401, { outcome: "nao_autorizado" }).itens(TENANT_A), { tipo: "indisponivel" });
  const semCofre = socialPeloAgr({
    agr: "http://agr.interno:8000",
    credencial: () => {
      throw new Error("sem segredo");
    },
    buscar: (async () => new Response("{}", { status: 200 })) as typeof fetch,
  });
  assert.deepEqual(await semCofre.itens(TENANT_A), { tipo: "indisponivel" });
  const semRede = socialPeloAgr({
    agr: "http://agr.interno:8000",
    credencial: () => "c",
    buscar: (async () => {
      throw new Error("ECONNREFUSED");
    }) as typeof fetch,
  });
  assert.deepEqual(await semRede.abrir(TENANT_A, LIGACAO_DE_A), { tipo: "indisponivel" });
});

test("KAM-246: um URL do STO em http é recusado fora de dev, e passa em dev", async () => {
  const responder = (corpo: unknown, aceitarHttp?: boolean) =>
    socialPeloAgr({
      agr: "http://agr.interno:8000",
      credencial: () => "c",
      buscar: (async () => new Response(JSON.stringify(corpo), { status: 200 })) as typeof fetch,
      ...(aceitarHttp === undefined ? {} : { aceitarHttp }),
    });
  const emClaro = "http://sto.ensaio.invalid/x?assinatura=y";
  // Fora de dev (a omissão): a lista inteira e a descarga ficam indisponíveis.
  for (const aceitarHttp of [undefined, false]) {
    assert.deepEqual(await responder({ itens: [item(TENANT_A, { imagem: emClaro })] }, aceitarHttp).itens(TENANT_A), {
      tipo: "indisponivel",
    });
    assert.deepEqual(await responder({ url: emClaro }, aceitarHttp).abrir(TENANT_A, LIGACAO_DE_A), { tipo: "indisponivel" });
  }
  // Em dev passa, e o img-src leva a origem em http.
  const lista = await responder({ itens: [item(TENANT_A, { imagem: emClaro })] }, true).itens(TENANT_A);
  assert.equal(lista.tipo, "ok");
  if (lista.tipo === "ok") assert.deepEqual(origensDasImagens(lista.valor), ["http://sto.ensaio.invalid"]);
  assert.deepEqual(await responder({ url: emClaro }, true).abrir(TENANT_A, LIGACAO_DE_A), { tipo: "ok", valor: emClaro });
  // O processo só aceita http em dev.
  const servidor = readFileSync(new URL("../src/server.ts", import.meta.url), "utf8");
  assert.match(servidor, /aceitarHttp: env === "dev"/);
});

test("KAM-246: o cabeçalho e as rotas são os mesmos do AGR", () => {
  assert.equal(CABECALHO_DA_CREDENCIAL, CABECALHO_INTERNO);
  const fonte = readFileSync(new URL("../../agr/src/kamba_agr/social/painel.py", import.meta.url), "utf8");
  assert.match(fonte, new RegExp(`ROTA_DOS_ITENS: Final = "${ROTA_DOS_ITENS_NO_AGR}"`));
  assert.match(fonte, new RegExp(`ROTA_DA_DESCARGA: Final = "${ROTA_DA_DESCARGA_NO_AGR}"`));
});

test("KAM-246: a CSP só ganha img-src com origens", () => {
  assert.equal(cspComImagens("default-src 'none'", []), "default-src 'none'");
  assert.equal(cspComImagens("default-src 'none'", ["https://a", "https://b"]), "default-src 'none'; img-src https://a https://b");
});
