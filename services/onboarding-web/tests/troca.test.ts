/**
 * A troca de telefone do dono pelo painel (KAM-211, critério «Troca de
 * telefone»), pela superfície HTTP.
 *
 * O `Otp` é o **real** do KAM-086 (com o repositório em memória e o SMS falso do
 * KAM-116) e a `TrocaDeTelefone` é a **real** do KAM-118; falsas são só as três
 * portas de base — o contacto do número, a `definir_dono` e os avisos —, que
 * registam o que lhes pedem. O papel move-se na base pela porta, e isso mede-se
 * contra o PostgreSQL em `packages/core-ts/tests_bd/dono.bd.test.ts`.
 *
 * O que aqui se prova é a ligação: o código vai ao número novo, só o código
 * certo chama a porta, o tenant é o da sessão, e uma sessão não verifica o
 * pedido de outra.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { TrocaDeTelefone, type DestinoDoAviso } from "@kamba/core-ts/dono";
import {
  ContadoresEmMemoria,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  Telefone,
} from "@kamba/core-ts/inscricao";
import { FakeSmsProvider } from "@kamba/core-ts/sms";

import { CanalEmMemoria, SEM_CANAL } from "../src/painel/canal.ts";
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

/** Números fictícios, com 999. */
const NUMERO_NOVO = "+244 999 000 411";
const NUMERO_DE_B = "+244 999 000 422";
/** Os números das lojas, que são os telefones dos casos (KAM-093). */
const LOJA_A = "+244 999 000 401";
const LOJA_B = "+244 999 000 402";

interface Montagem {
  app: ReturnType<typeof rotasDoPainel>;
  contadores: ContadoresEmMemoria;
  troca: TrocaDeTelefone;
  casos: Map<string, { tenantId: string; fase: string; telefoneHmac?: string }>;
  canal: CanalEmMemoria;
  /** O canal do dono que a porta recebeu, troca a troca (KAM-216). */
  canais: boolean[];
  /** A coluna `tenants.owner_channel_wa`, por tenant, como a porta a deixa. */
  guardados: Map<string, boolean>;
  /** Os tenants que o `GET /painel/canal` pediu ao leitor da coluna. */
  lidos: string[];
  /** Se o leitor da coluna lança. */
  leitorFalha: boolean;
  sms: FakeSmsProvider;
  metricas: MetricasDoPainel;
  /** O que a `definir_dono` recebeu: `(tenant, contacto)`. */
  trocas: { tenantId: string; contactId: string }[];
  /** Os contactos pedidos ao `resolveContact`: `(tenant, numero)`. */
  contactos: { tenantId: string; numero: string }[];
  avisos: { tenantId: string; destino: DestinoDoAviso }[];
  agora: Date;
}

function montar(opcoes: { readonly avisoFalha?: boolean } = {}): Montagem {
  const m = {
    agora: INICIO,
    trocas: [],
    contactos: [],
    avisos: [],
    canais: [],
    guardados: new Map(),
    lidos: [],
    leitorFalha: false,
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
  const troca = new TrocaDeTelefone({
    relogio,
    otp,
    contacto: async ({ tenantId, telefone }: { tenantId: string; telefone: Telefone }) => {
      m.contactos.push({ tenantId, numero: telefone.hmac });
      return { contactId: `contacto-novo-de-${tenantId.slice(0, 8)}` };
    },
    trocar: async ({ tenantId, contactId, ownerChannelWa }) => {
      m.trocas.push({ tenantId, contactId });
      m.canais.push(ownerChannelWa);
      m.guardados.set(tenantId, ownerChannelWa);
      return { anterior: `dono-antigo-de-${tenantId.slice(0, 8)}` };
    },
    avisar: async ({ tenantId, destino }) => {
      m.avisos.push({ tenantId, destino });
      if (opcoes.avisoFalha === true) throw new Error("aviso_em_baixo");
    },
  });
  m.troca = troca;
  const casos = new Map<string, { tenantId: string; fase: string; telefoneHmac?: string }>([
    [CASO_A, { tenantId: TENANT_A, fase: "activo", telefoneHmac: new Telefone(LOJA_A, PEPPER).hmac }],
    [CASO_B, { tenantId: TENANT_B, fase: "activo", telefoneHmac: new Telefone(LOJA_B, PEPPER).hmac }],
  ]);
  m.casos = casos;
  m.canal = new CanalEmMemoria();
  m.app = rotasDoPainel({
    comercio: new ComercioEmMemoria(),
    canal: m.canal,
    revogacoes: new RevogacoesEmMemoria(),
    metricas: m.metricas,
    casos: { porId: async (id) => casos.get(id) ?? null },
    anelDaAssinatura: [CHAVE, null],
    relogio,
    troca: {
      troca,
      anelDoPepper: [PEPPER, null],
      contadores: m.contadores,
      canalDoDono: async (tenantId) => {
        m.lidos.push(tenantId);
        if (m.leitorFalha) throw new Error("base_em_baixo");
        return m.guardados.get(tenantId) ?? null;
      },
    },
  });
  return m;
}

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

function ultimoCodigo(m: Montagem): string {
  const codigo = /([0-9]{6})/.exec(m.sms.enviados.at(-1)?.corpo ?? "")?.[1] ?? "";
  assert.match(codigo, /^[0-9]{6}$/);
  return codigo;
}

describe("KAM-211 — a troca de telefone pelo painel", () => {
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
    // Ate ao codigo certo: nem contacto resolvido, nem porta, nem aviso.
    assert.deepEqual([m.contactos, m.trocas, m.avisos], [[], [], []]);
  });

  it("o codigo certo chama a porta com o tenant da sessao e avisa os dois destinos", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    const r = await post(m, "/painel/telefone/verificar", { codigo: ultimoCodigo(m) }, deA);
    assert.equal(r.status, 200);
    assert.deepEqual(m.trocas, [{ tenantId: TENANT_A, contactId: "contacto-novo-de-aaaaaaaa" }]);
    assert.equal(m.contactos.length, 1);
    assert.deepEqual(
      m.avisos.map((a) => a.destino),
      ["numero_antigo", "email"],
    );
    assert.ok(m.avisos.every((a) => a.tenantId === TENANT_A));
  });

  it("um codigo errado da 401 e nao toca na porta; o pedido continua vivo", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    const certo = ultimoCodigo(m);
    const errado = certo === "000000" ? "111111" : "000000";
    const r = await post(m, "/painel/telefone/verificar", { codigo: errado }, deA);
    assert.equal(r.status, 401);
    assert.deepEqual(await r.json(), { erro: "codigo" });
    assert.deepEqual(m.trocas, []);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo: certo }, deA)).status, 200);
  });

  it("o pedido gasta-se: o mesmo codigo outra vez da 401", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    const codigo = ultimoCodigo(m);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo }, deA)).status, 200);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo }, deA)).status, 401);
    assert.equal(m.trocas.length, 1);
  });

  it("sem sessao e 401, e sem a troca configurada e 503", async () => {
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO })).status, 401);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo: "123456" })).status, 401);
    assert.equal(m.sms.enviados.length, 0);
    const sem = rotasDoPainel({
      comercio: new ComercioEmMemoria(),
      canal: new CanalEmMemoria(),
      revogacoes: new RevogacoesEmMemoria(),
      casos: { porId: async () => ({ tenantId: TENANT_A, fase: "activo" }) },
      anelDaAssinatura: [CHAVE, null],
      relogio: () => m.agora,
    });
    const r = await sem.request("/painel/telefone", {
      method: "POST",
      headers: { "content-type": "application/json", cookie: deA },
      body: JSON.stringify({ telefone: NUMERO_NOVO }),
    });
    assert.equal(r.status, 503);
  });

  it("um telefone ilegivel e um corpo que nao e JSON dao 400 e nao enviam nada", async () => {
    for (const telefone of ["", "nao e telefone", 999, null]) {
      assert.equal((await post(m, "/painel/telefone", { telefone }, deA)).status, 400);
    }
    const r = await m.app.request("/painel/telefone", {
      method: "POST",
      headers: { "content-type": "text/plain", cookie: deA },
      body: NUMERO_NOVO,
    });
    assert.equal(r.status, 400);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo: 123456 }, deA)).status, 400);
    assert.equal(m.sms.enviados.length, 0);
  });

  it("o recusado pelo OTP (intervalo) da 429", async () => {
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA)).status, 200);
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA)).status, 429);
    assert.equal(m.sms.enviados.length, 1);
  });

  it("um aviso que falha sobe depois da troca, e a troca nao se desfaz", async () => {
    const falhado = montar({ avisoFalha: true });
    const sessao = cookie(TENANT_A, CASO_A, falhado);
    await post(falhado, "/painel/telefone", { telefone: NUMERO_NOVO }, sessao);
    const r = await post(falhado, "/painel/telefone/verificar", { codigo: ultimoCodigo(falhado) }, sessao);
    assert.equal(r.status, 500);
    assert.equal(falhado.trocas.length, 1);
  });

  it("antes de `activo` a troca recusa com 409 e nao manda codigo (achado 4)", async () => {
    for (const fase of ["aguarda_es", "lista_espera", "aguarda_catalogo", "aguarda_teste"]) {
      m.casos.set(CASO_A, { tenantId: TENANT_A, fase });
      const r = await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
      assert.equal(r.status, 409, fase);
      assert.equal((await post(m, "/painel/telefone/verificar", { codigo: "123456" }, deA)).status, 409, fase);
    }
    assert.equal(m.sms.enviados.length, 0);
    assert.deepEqual(m.trocas, []);
    assert.equal(FASE_DA_TROCA, "activo");
  });

  it("ha limite por rede, como na reentrada: o seguinte ao limite da 429 e nao envia (achado 3)", async () => {
    for (let n = 0; n < LIMITE_POR_REDE; n += 1) {
      const numero = `+244 999 000 ${String(500 + n)}`;
      assert.equal((await post(m, "/painel/telefone", { telefone: numero }, cookie(TENANT_A, CASO_A, m))).status, 200, numero);
    }
    const r = await post(m, "/painel/telefone", { telefone: "+244 999 000 599" }, cookie(TENANT_A, CASO_A, m));
    assert.equal(r.status, 429);
    assert.equal(m.sms.enviados.length, LIMITE_POR_REDE);
  });

  it("dois pedidos concorrentes da mesma sessao: so um envia (achado 8)", async () => {
    const [um, dois] = await Promise.all([
      post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA),
      post(m, "/painel/telefone", { telefone: "+244 999 000 499" }, deA),
    ]);
    assert.deepEqual([um.status, dois.status].sort(), [200, 429]);
    assert.equal(m.sms.enviados.length, 1);
  });

  it("um pedido expirado sai do mapa no pedido seguinte (achado 9)", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, deA);
    assert.equal(m.troca.pedidosGuardados, 1);
    m.agora = new Date(m.agora.getTime() + 3_600_000);
    await post(m, "/painel/telefone", { telefone: "+244 999 000 499" }, cookie(TENANT_A, CASO_A, m));
    assert.equal(m.troca.pedidosGuardados, 1);
  });

  it("a chave do pedido e a sessao, com o prefixo da troca", () => {
    const s = novaSessao(TENANT_A, CASO_A, INICIO);
    assert.equal(pedidoDaTroca(s), `troca:${s.sid}`);
    assert.notEqual(pedidoDaTroca(s), CASO_A);
  });

  it("as duas rotas contam-se nas metricas do painel", async () => {
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO });
    await post(m, "/painel/telefone/verificar", { codigo: "x" }, deA);
    assert.equal(m.metricas.valor("troca"), 1);
    assert.equal(m.metricas.valor("troca", "sem_sessao"), 1);
    assert.equal(m.metricas.valor("troca_verificar", "invalido"), 1);
  });
});

describe("KAM-211 — a troca isola o tenant e a sessao", () => {
  it("o tenant de B no corpo, na consulta ou num cabecalho nao muda nada: a porta recebe A", async () => {
    const m = montar();
    for (const [caminho, extra, corpoExtra] of [
      ["/painel/telefone", {}, { tenant_id: TENANT_B }],
      [`/painel/telefone?tenant_id=${TENANT_B}`, {}, {}],
      ["/painel/telefone", { "x-kamba-tenant": TENANT_B }, {}],
    ] as const) {
      const sessao = cookie(TENANT_A, CASO_A, m);
      await post(m, caminho, { telefone: NUMERO_NOVO, ...corpoExtra }, sessao, extra);
      m.agora = new Date(m.agora.getTime() + 61_000);
      const codigo = ultimoCodigo(m);
      await post(m, `/painel/telefone/verificar?tenant_id=${TENANT_B}`, { codigo, tenant_id: TENANT_B }, sessao, extra);
    }
    assert.equal(m.trocas.length, 3);
    assert.ok(m.trocas.every((t) => t.tenantId === TENANT_A));
  });

  it("a sessao de A nao verifica o pedido de B, nem com o codigo certo de B", async () => {
    const m = montar();
    const deB = cookie(TENANT_B, CASO_B, m);
    await post(m, "/painel/telefone", { telefone: NUMERO_DE_B }, deB);
    const codigoDeB = ultimoCodigo(m);
    const deA = cookie(TENANT_A, CASO_A, m);
    const r = await post(m, "/painel/telefone/verificar", { codigo: codigoDeB, tenant_id: TENANT_B }, deA);
    assert.equal(r.status, 401);
    assert.deepEqual(m.trocas, []);
    // E o de B continua vivo para B.
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo: codigoDeB }, deB)).status, 200);
    assert.deepEqual(m.trocas, [{ tenantId: TENANT_B, contactId: "contacto-novo-de-bbbbbbbb" }]);
  });

  it("outra sessao do mesmo tenant tambem nao verifica o pedido", async () => {
    const m = montar();
    const primeira = cookie(TENANT_A, CASO_A, m);
    await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, primeira);
    const codigo = ultimoCodigo(m);
    const segunda = cookie(TENANT_A, CASO_A, m);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo }, segunda)).status, 401);
    assert.deepEqual(m.trocas, []);
  });

  it("uma sessao forjada com o sid de B nao passa a assinatura", async () => {
    const m = montar();
    const forjada = `kamba_painel=${cunharSessao(novaSessao(TENANT_B, CASO_B, INICIO), new Uint8Array(32).fill(9))}`;
    assert.equal((await post(m, "/painel/telefone", { telefone: NUMERO_NOVO }, forjada)).status, 401);
    assert.equal(m.sms.enviados.length, 0);
  });
});

describe("KAM-216 — o canal do dono: a troca guarda-o e o painel mostra-o", () => {
  let m: Montagem;
  let deA: string;

  beforeEach(() => {
    m = montar();
    deA = cookie(TENANT_A, CASO_A, m);
    for (const tenant of [TENANT_A, TENANT_B]) m.canal.vistas.set(tenant, { ...SEM_CANAL, estado: "ativo" });
  });

  async function trocarPara(numero: string, sessao = deA): Promise<void> {
    // Um quarto de hora entre trocas: o `Otp` tem intervalo entre envios.
    m.agora = new Date(m.agora.getTime() + 15 * 60_000);
    assert.equal((await post(m, "/painel/telefone", { telefone: numero }, sessao)).status, 200);
    assert.equal((await post(m, "/painel/telefone/verificar", { codigo: ultimoCodigo(m) }, sessao)).status, 200);
  }

  async function canalNaPagina(sessao = deA): Promise<string | undefined> {
    const r = await m.app.request("/painel/canal", { headers: { cookie: sessao } });
    assert.equal(r.status, 200);
    return /data-canal-do-dono="([a-z]+)"/.exec(await r.text())?.[1];
  }

  it("antes de qualquer troca, o dono e o telefone do caso, que e o da loja: painel", async () => {
    assert.equal(await canalNaPagina(), "painel");
    assert.deepEqual(m.lidos, [TENANT_A]);
  });

  it("telefone diferente: a troca guarda WhatsApp, e o painel mostra-o", async () => {
    await trocarPara(NUMERO_NOVO);
    assert.deepEqual(m.canais, [true]);
    assert.equal(await canalNaPagina(), "whatsapp");
  });

  it("telefone igual ao da loja (o dono volta ao numero do registo): painel", async () => {
    await trocarPara(NUMERO_NOVO);
    await trocarPara(LOJA_A.replace("+244 ", ""));
    assert.deepEqual(m.canais, [true, false]);
    assert.equal(await canalNaPagina(), "painel");
  });

  it("o numero da loja de outro tenant nao conta: o HMAC e o do caso da sessao", async () => {
    // O dono de A troca para o numero da loja de B: e diferente do da loja de A.
    await trocarPara(LOJA_B);
    assert.deepEqual(m.canais, [true]);
  });

  it("isolamento: o canal de B nao aparece na sessao de A, nem com o tenant de B no pedido", async () => {
    m.guardados.set(TENANT_B, true);
    const r = await m.app.request(`/painel/canal?tenant_id=${TENANT_B}`, {
      headers: { cookie: deA, "x-kamba-tenant": TENANT_B, "x-tenant-id": TENANT_B },
    });
    assert.equal(r.status, 200);
    assert.match(await r.text(), /data-canal-do-dono="painel"/);
    assert.deepEqual(m.lidos, [TENANT_A]);
  });

  it("um caso sem HMAC de telefone guarda painel", async () => {
    m.casos.set(CASO_A, { tenantId: TENANT_A, fase: "activo" });
    await trocarPara(NUMERO_NOVO);
    assert.deepEqual(m.canais, [false]);
  });

  it("uma leitura da coluna que falha da painel, e o estado do canal continua a sair", async () => {
    m.guardados.set(TENANT_A, true);
    m.leitorFalha = true;
    const r = await m.app.request("/painel/canal", { headers: { cookie: deA } });
    assert.equal(r.status, 200);
    const corpo = await r.text();
    assert.match(corpo, /data-canal-do-dono="painel"/);
    assert.match(corpo, /Activo/);
  });

  it("com o canal da loja por ligar ou desligado, o WhatsApp guardado nao abre", async () => {
    m.guardados.set(TENANT_A, true);
    for (const estado of ["sem_canal", "desligado", "a_sincronizar"] as const) {
      m.canal.vistas.set(TENANT_A, { ...SEM_CANAL, estado });
      assert.equal(await canalNaPagina(), "painel", estado);
    }
  });

  it("a pagina diz o canal e nao mostra numero nenhum", async () => {
    await trocarPara(NUMERO_NOVO);
    const corpo = await (await m.app.request("/painel/canal", { headers: { cookie: deA } })).text();
    assert.doesNotMatch(corpo, /999\s*000\s*4\d\d/);
  });
});
