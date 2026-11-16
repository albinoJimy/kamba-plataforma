/**
 * A página `/ligar` e as rotas `/api/es/*`, pela superfície HTTP (KAM-093).
 *
 * O que só se mede aqui, e não no pacote:
 *
 *     isolamento    a sessão do dono A não vê nem retoma o caso B — e não há
 *                   parâmetro nenhum por onde o pedir
 *     adversarial   ligação de retoma forjada ⇒ 403; `FINISH` repetido 2× ⇒ 1
 *                   chamada ao GWY; `tenant_id` no corpo ignorado
 *     critério 1    a página só abre com caso `aguarda_es` **e** sessão
 *     KAM-095       a lista de espera como `CapacityGate` real do guia, e as
 *                   quatro rotas `/api/lista/*`: posição, convite de uso único,
 *                   recusa, desistência — e o convite de outro caso dá 403
 *
 * Os números são os do `packages/core-ts/tests/guia.test.ts`: `+244 9` e zeros,
 * declarados no inventário do *gate* 7.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AvisosDaListaEmMemoria,
  LIMITE_POR_OMISSAO,
  ListaDeEspera,
  ListaEmMemoria,
} from "@kamba/core-ts/capacidade";

import {
  AvisosEmMemoria,
  CapacidadeEmMemoria,
  GatesEmMemoria,
  GuiaEmMemoria,
  PassoGuiado,
  RevisaoEmMemoria,
  type LigadorDeCanal,
  type ResultadoDaLigacao,
} from "@kamba/core-ts/guia";
import {
  Actividade,
  AntiAbuso,
  CasosEmMemoria,
  ContadoresEmMemoria,
  Email,
  Nif,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  Registo,
  Telefone,
  cunharReferencia,
  lerReferencia,
} from "@kamba/core-ts/inscricao";
import type { ResultadoDoEs } from "@kamba/core-ts/onboarding";
import { FakeSmsProvider, cunharDestino } from "@kamba/core-ts/sms";

import { createApp } from "../src/app.ts";
import { LigadorPorHttp } from "../src/ligador.ts";
import { AVISO_DO_BOT, AVISO_DO_TOKEN } from "../src/pagina_guia.ts";

const PEPPER = Buffer.alloc(32, 0x5a);
const ASSINATURA = Buffer.alloc(32, 0x3c);
const OUTRA_CHAVE = Buffer.alloc(32, 0x44);
const PEPPER_DO_DESTINO = Buffer.alloc(32, 0x71);
const MOVEL = "+244900000001";
const OUTRO_MOVEL = "+244900000002";

const ATESTADOS = {
  versao_da_app: "2.24.17",
  app_aberta_recentemente: true,
  numero_em_whatsapp_pessoal: false,
  cartao_internacional: true,
  dono_presente: true,
};

const SESSION_INFO = { sessionInfoVersion: "3", extras: { featureType: "whatsapp_business_app_onboarding" } };

class LigadorFalso implements LigadorDeCanal {
  readonly chamadas: ResultadoDoEs[] = [];
  async ligar(entrada: ResultadoDoEs): Promise<ResultadoDaLigacao> {
    this.chamadas.push(entrada);
    const repetido = this.chamadas.filter((c) => c.waba_id === entrada.waba_id).length > 1;
    return { desfecho: repetido ? "repetido" : "criado", tentativaId: "t-1" };
  }
}

/**
 * Monta o serviço. Com `maximoDaLista`, o `CapacityGate` é a lista de espera
 * do KAM-095 com esse limite, e as rotas `/api/lista/*` têm onde ler; sem ele,
 * é o contador do KAM-093 e as rotas da lista respondem 404 depois da sessão.
 */
async function montar(maximoDaLista?: number) {
  let agora = new Date("2026-11-10T10:00:00.000Z").getTime();
  const relogio = (): Date => new Date(agora);
  const casos = new CasosEmMemoria(relogio);
  const contadores = new ContadoresEmMemoria();
  const sms = new FakeSmsProvider({ relogio });
  const antiabuso = new AntiAbuso({ contadores, chave: PEPPER, relogio });
  const otp = new Otp({
    repositorio: new OtpEmMemoria(),
    contadores,
    provedor: new OtpPorSmsLocal({ sms, pepperDoDestino: PEPPER_DO_DESTINO }),
    chave: PEPPER,
    relogio,
  });
  const registo = new Registo({
    repositorio: casos,
    antiabuso,
    otp,
    anelDoPepper: [PEPPER, null],
    anelDoToken: [ASSINATURA, null],
    anelDaSessao: [ASSINATURA, null],
    relogio,
  });
  const ligador = new LigadorFalso();
  const repositorio = new GuiaEmMemoria(relogio);
  const avisosDaLista = new AvisosDaListaEmMemoria();
  const lista =
    maximoDaLista === undefined
      ? undefined
      : new ListaDeEspera({
          repositorio: new ListaEmMemoria(casos, relogio, { ...LIMITE_POR_OMISSAO, maximo: maximoDaLista }),
          aviso: avisosDaLista,
          origem: "https://onboarding.exemplo.test",
          relogio,
        });
  const guia = new PassoGuiado({
    casos,
    repositorio,
    capacidade: lista ?? new CapacidadeEmMemoria({ relogio }),
    ligador,
    gates: new GatesEmMemoria(),
    revisao: new RevisaoEmMemoria(),
    pagamento: { verificar: async () => "desconhecido" },
    aviso: new AvisosEmMemoria(),
    anelDoPepper: [PEPPER, null],
    chaveDaAssinatura: ASSINATURA,
    origem: "https://onboarding.exemplo.test",
    configId: "config-de-ensaio",
    relogio,
  });
  const app = createApp(
    undefined,
    {
      registo,
      otp,
      actividade: new Actividade({ repositorio: casos, contadores, relogio }),
      antiabuso,
      anelDaAssinatura: [ASSINATURA, null],
      anelDoToken: [ASSINATURA, null],
      relogio,
    },
    {
      guia,
      lista,
      registo,
      otp,
      anelDaAssinatura: [ASSINATURA, null],
      appIdDaMeta: "app-de-ensaio",
      versaoDaGraph: "v21.0",
      relogio,
    },
  );
  let n = 0;
  async function caso(telefone = MOVEL, fase: "aguarda_es" | "kyc_pendente" = "aguarda_es") {
    n += 1;
    const { caso: c } = await casos.criar(
      {
        tenantId: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
        origem: "anuncio",
        nomeNegocio: "Loja da Esquina",
        categoriaDeclarada: "mercearia",
        nif: new Nif(`5${String(n).padStart(9, "0")}`, PEPPER),
        telefone: new Telefone(telefone, PEPPER),
        email: new Email("dono@exemplo.test"),
        dispositivoHmac: null,
        redeHmac: null,
        flags: [],
      },
      `chave-${n}`,
    );
    await casos.marcarFase(c.id, fase);
    return c;
  }
  const cookie = (id: string): string =>
    `kamba_onboarding=${cunharReferencia("sessao", id, ASSINATURA, relogio)}`;
  const retoma = (id: string, chave: Uint8Array = ASSINATURA): string =>
    encodeURIComponent(cunharReferencia("retoma", id, chave, relogio));
  async function post(caminho: string, corpo: unknown, id?: string) {
    const r = await app.request(caminho, {
      method: "POST",
      headers: { "content-type": "application/json", ...(id === undefined ? {} : { cookie: cookie(id) }) },
      body: JSON.stringify(corpo),
    });
    return { estado: r.status, corpo: (await r.json()) as Record<string, unknown> };
  }
  async function get(caminho: string, id?: string) {
    const r = await app.request(caminho, { headers: id === undefined ? {} : { cookie: cookie(id) } });
    return { estado: r.status, corpo: (await r.json()) as Record<string, unknown> };
  }
  return {
    app,
    casos,
    guia,
    lista,
    avisosDaLista,
    repositorio,
    ligador,
    sms,
    caso,
    cookie,
    retoma,
    post,
    get,
    relogio,
    avancar: (ms: number) => (agora += ms),
  };
}

describe("KAM-093 HTTP: /ligar so abre com sessao e caso aguarda_es (criterio 1)", () => {
  it("sem sessao: 403", async () => {
    const m = await montar();
    await m.caso();
    const r = await m.app.request("/ligar");
    assert.equal(r.status, 403);
  });

  it("com sessao e caso aguarda_es: 200, com o aviso do bot e o do token, e a CSP so abre a Meta", async () => {
    const m = await montar();
    const c = await m.caso();
    const r = await m.app.request("/ligar", { headers: { cookie: m.cookie(c.id) } });
    assert.equal(r.status, 200);
    const html = await r.text();
    assert.ok(html.includes(AVISO_DO_BOT));
    assert.ok(html.includes(AVISO_DO_TOKEN));
    // Nenhum campo de token, PIN ou codigo da Meta (criterio 9).
    assert.doesNotMatch(html, /name="(token|pin|codigo|password)"/i);
    const csp = r.headers.get("content-security-policy") ?? "";
    assert.match(csp, /script-src 'nonce-[0-9a-f]+' https:\/\/connect\.facebook\.net/);
    assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval|\*/);
    assert.equal(r.headers.get("referrer-policy"), "no-referrer");
  });

  it("caso noutra fase: 409; sessao de caso que nao existe: 404", async () => {
    const m = await montar();
    const c = await m.caso(MOVEL, "kyc_pendente");
    assert.equal((await m.app.request("/ligar", { headers: { cookie: m.cookie(c.id) } })).status, 409);
    const fantasma = "00000000-0000-4000-8000-0000000000ee";
    assert.equal((await m.app.request("/ligar", { headers: { cookie: m.cookie(fantasma) } })).status, 404);
  });

  it("um BILHETE no cookie nao serve de sessao", async () => {
    const m = await montar();
    const c = await m.caso();
    const bilhete = cunharReferencia("ticket", c.id, ASSINATURA, m.relogio);
    const r = await m.app.request("/ligar", { headers: { cookie: `kamba_onboarding=${bilhete}` } });
    assert.equal(r.status, 403);
  });
});

describe("KAM-093 HTTP ADVERSARIAL: ligacao de retoma forjada => 403", () => {
  it("retoma do proprio caso abre; forjada, de outra chave, de outro caso ou adulterada dao 403", async () => {
    const m = await montar();
    const a = await m.caso();
    const b = await m.caso(OUTRO_MOVEL);
    const abrir = (r: string) => m.app.request(`/ligar?r=${r}`, { headers: { cookie: m.cookie(a.id) } });
    assert.equal((await abrir(m.retoma(a.id))).status, 200);
    assert.equal((await abrir(m.retoma(a.id, OUTRA_CHAVE))).status, 403, "assinada com outra chave");
    assert.equal((await abrir(m.retoma(b.id))).status, 403, "retoma do caso B com a sessao de A");
    const boa = decodeURIComponent(m.retoma(a.id));
    const [id, segundos] = boa.split(".") as [string, string, string];
    assert.equal((await abrir(encodeURIComponent(`${id}.${segundos}.${"A".repeat(43)}`))).status, 403, "forjada");
    assert.equal((await abrir(encodeURIComponent(`${id}.${Number(segundos) + 86_400}.${boa.split(".")[2]}`))).status, 403, "prolongada");
    const sessaoComoRetoma = encodeURIComponent(cunharReferencia("sessao", a.id, ASSINATURA, m.relogio));
    assert.equal((await abrir(sessaoComoRetoma)).status, 403, "uma sessao nao serve de retoma");
  });

  it("a retoma sozinha, sem sessao, nao abre a pagina", async () => {
    const m = await montar();
    const a = await m.caso();
    assert.equal((await m.app.request(`/ligar?r=${m.retoma(a.id)}`)).status, 403);
  });

  it("os 403 sao iguais: forjado e alheio nao se distinguem pelo corpo", async () => {
    const m = await montar();
    const a = await m.caso();
    const b = await m.caso(OUTRO_MOVEL);
    const um = await (await m.app.request(`/ligar?r=${m.retoma(b.id)}`, { headers: { cookie: m.cookie(a.id) } })).text();
    const outro = await (await m.app.request(`/ligar?r=${m.retoma(a.id, OUTRA_CHAVE)}`, { headers: { cookie: m.cookie(a.id) } })).text();
    // O `nonce` muda por resposta; o resto do corpo e igual.
    const semNonce = (html: string): string => html.replace(/nonce="[0-9a-f]+"/g, 'nonce=""');
    assert.equal(semNonce(um), semNonce(outro));
  });

  it("POST /api/es/retoma: forjada 403; valida manda o OTP ao telefone REGISTADO e devolve um bilhete", async () => {
    const m = await montar();
    const a = await m.caso();
    assert.equal((await m.post("/api/es/retoma", { r: decodeURIComponent(m.retoma(a.id, OUTRA_CHAVE)) })).estado, 403);
    assert.equal(m.sms.enviados.length, 0);
    const r = await m.post("/api/es/retoma", { r: decodeURIComponent(m.retoma(a.id)), telefone: OUTRO_MOVEL });
    assert.equal(r.estado, 200);
    assert.equal(m.sms.enviados.length, 1);
    assert.equal(lerReferencia("ticket", r.corpo.referencia, [ASSINATURA, null], m.relogio), a.id);
    assert.throws(() => lerReferencia("sessao", r.corpo.referencia, [ASSINATURA, null], m.relogio));
  });
});

describe("KAM-093 HTTP: isolamento (sessao do dono A nao ve nem retoma o caso B)", () => {
  it("o corpo nunca escolhe o caso: um onboarding_id de B no corpo actua sobre A", async () => {
    const m = await montar();
    const a = await m.caso();
    const b = await m.caso(OUTRO_MOVEL);
    await m.post("/api/es/preflight", ATESTADOS, b.id);
    await m.post("/api/es/iniciar", {}, b.id);
    // A, com o id de B no corpo e na consulta, cancela... o seu proprio.
    const r = await m.post(`/api/es/cancelar?onboarding_id=${b.id}`, { onboarding_id: b.id }, a.id);
    assert.equal(r.estado, 200);
    assert.equal((await m.repositorio.ler(b.id))?.estado, "iniciado");
  });

  it("o estado que A le e o de A", async () => {
    const m = await montar();
    const a = await m.caso();
    const b = await m.caso(OUTRO_MOVEL);
    await m.post("/api/es/preflight", ATESTADOS, b.id);
    const r = await m.app.request("/api/es/estado", { headers: { cookie: m.cookie(a.id) } });
    const corpo = (await r.json()) as { estado: string; preflight: unknown };
    assert.equal(corpo.estado, "pre_voo");
    assert.equal(corpo.preflight, null);
  });

  it("sem sessao, todas as rotas /api/es dao 403", async () => {
    const m = await montar();
    await m.caso();
    for (const rota of ["preflight", "iniciar", "cancelar", "concluir", "pagamento"]) {
      assert.equal((await m.post(`/api/es/${rota}`, {})).estado, 403, rota);
    }
    assert.equal((await m.app.request("/api/es/estado")).status, 403);
  });
});

describe("KAM-093 HTTP: o fluxo, e o FINISH repetido", () => {
  it("preflight -> iniciar -> concluir; o segundo FINISH nao chama o GWY outra vez", async () => {
    const m = await montar();
    const a = await m.caso();
    const p = await m.post("/api/es/preflight", ATESTADOS, a.id);
    assert.equal(p.corpo.pode_abrir, true);
    const i = await m.post("/api/es/iniciar", {}, a.id);
    assert.equal(i.corpo.desfecho, "popup");
    const corpo = {
      code: "code-de-ensaio",
      waba_id: "waba-1",
      phone_number_id: "pnid-1",
      tenant_id: "00000000-0000-4000-8000-0000000000ff",
    };
    const um = await m.post("/api/es/concluir", corpo, a.id);
    const dois = await m.post("/api/es/concluir", corpo, a.id);
    assert.deepEqual(um.corpo, { estado: "subscrito", novo: true });
    assert.deepEqual(dois.corpo, { estado: "subscrito", novo: false });
    assert.equal(m.ligador.chamadas.length, 1);
    assert.equal(m.ligador.chamadas[0]?.tenant_id, a.tenantId, "o tenant_id vem do caso, nao do corpo");
  });

  it("iniciar sem pre-voo cumprido: 409, e o popup nao abre", async () => {
    const m = await montar();
    const a = await m.caso();
    await m.post("/api/es/preflight", { ...ATESTADOS, dono_presente: "true" }, a.id);
    const r = await m.post("/api/es/iniciar", {}, a.id);
    assert.equal(r.estado, 409);
    assert.equal(r.corpo.erro, "preflight_por_cumprir");
  });

  it("pagamento por detectar: vermelho, com a alternativa MPS", async () => {
    const m = await montar();
    const a = await m.caso();
    const r = await m.post("/api/es/pagamento", {}, a.id);
    assert.deepEqual(r.corpo, { estado: "desconhecido", verde: false, alternativa: "mps" });
  });
});

describe("KAM-093 HTTP: a retoma de ponta a ponta (achados 2, 8 e 11 da revisao)", () => {
  it("retoma -> codigo SMS -> sessao -> /ligar abre, e o caso NAO recua de aguarda_es", async () => {
    const m = await montar();
    const a = await m.caso();
    const r = await m.post("/api/es/retoma", { r: decodeURIComponent(m.retoma(a.id)) });
    assert.equal(r.estado, 200);
    const codigo = /([0-9]{6})/.exec(m.sms.enviados.at(-1)?.corpo ?? "")?.[1] ?? "";
    const v = await m.app.request("/api/otp/verificar", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia: r.corpo.referencia, codigo }),
    });
    assert.equal(((await v.json()) as { veredicto: string }).veredicto, "acertou");
    const cookie = (v.headers.get("set-cookie") ?? "").split(";")[0] ?? "";
    assert.equal((await m.casos.porId(a.id))?.fase, "aguarda_es");
    const pagina = await m.app.request(`/ligar?r=${m.retoma(a.id)}`, { headers: { cookie } });
    assert.equal(pagina.status, 200);
  });

  it("o OTP da retoma vai ao telefone REGISTADO, e nao ao que o pedido traz", async () => {
    const m = await montar();
    const a = await m.caso();
    await m.post("/api/es/retoma", { r: decodeURIComponent(m.retoma(a.id)), telefone: OUTRO_MOVEL });
    const destino = m.sms.enviados.at(-1)?.destinoHmac;
    assert.equal(destino, cunharDestino(MOVEL, PEPPER_DO_DESTINO).hmac);
    assert.notEqual(destino, cunharDestino(OUTRO_MOVEL, PEPPER_DO_DESTINO).hmac);
  });

  it("a retoma de um caso que ja nao esta no passo do ES da 403 e nao manda SMS", async () => {
    const m = await montar();
    const a = await m.caso(MOVEL, "kyc_pendente");
    const r = await m.post("/api/es/retoma", { r: decodeURIComponent(m.retoma(a.id)) });
    assert.equal(r.estado, 403);
    assert.equal(m.sms.enviados.length, 0);
  });

  it("a pagina de recusa traz o caminho da retoma, com o mesmo corpo para todas as recusas", async () => {
    const m = await montar();
    const a = await m.caso();
    const html = await (await m.app.request(`/ligar?r=${m.retoma(a.id)}`)).text();
    assert.match(html, /\/api\/es\/retoma/);
    assert.match(html, /\/api\/otp\/verificar/);
  });
});

describe("KAM-093 HTTP: autorizacao com uma sessao VALIDA (achado 10 da revisao)", () => {
  it("a sessao valida de A, com o id de B no corpo e na consulta, nunca toca no caso de B", async () => {
    const m = await montar();
    const a = await m.caso();
    const b = await m.caso(OUTRO_MOVEL);
    await m.post("/api/es/preflight", ATESTADOS, b.id);
    await m.post("/api/es/iniciar", {}, b.id);
    const antes = JSON.stringify(await m.repositorio.ler(b.id));
    const corpo = { onboarding_id: b.id, code: "c", waba_id: "w", phone_number_id: "p", ...ATESTADOS };
    for (const rota of ["preflight", "iniciar", "cancelar", "concluir", "pagamento"]) {
      await m.post(`/api/es/${rota}?onboarding_id=${b.id}`, corpo, a.id);
    }
    const estado = await m.app.request(`/api/es/estado?onboarding_id=${b.id}`, { headers: { cookie: m.cookie(a.id) } });
    assert.doesNotMatch(await estado.text(), new RegExp(b.id));
    assert.equal(JSON.stringify(await m.repositorio.ler(b.id)), antes);
    assert.equal(m.ligador.chamadas.every((c) => c.tenant_id === a.tenantId), true);
  });
});

describe("KAM-093: o LigadorPorHttp traduz os codigos do GWY", () => {
  const entrada: ResultadoDoEs = {
    tenant_id: "00000000-0000-4000-8000-000000000001",
    code: "c",
    waba_id: "w",
    phone_number_id: "p",
    session_info: SESSION_INFO,
  };
  for (const [estado, desfecho] of [
    [201, "criado"],
    [200, "repetido"],
    [429, "lista_espera"],
    [409, "recusado"],
    [400, "recusado"],
    [502, "recusado"],
  ] as const) {
    it(`${estado} => ${desfecho}`, async () => {
      let url = "";
      const ligador = new LigadorPorHttp("http://gwy:3100/", async (u, init) => {
        url = u;
        assert.equal(init.method, "POST");
        return new Response(JSON.stringify({ onboarding_id: "t-9" }), { status: estado });
      });
      const r = await ligador.ligar(entrada);
      assert.equal(url, "http://gwy:3100/internal/channels");
      assert.equal(r.desfecho, desfecho);
      assert.equal(r.tentativaId, estado === 200 || estado === 201 ? "t-9" : null);
    });
  }
});

// --------------------------------------------------------------- KAM-095

const DIA_MS = 86_400_000;

/** O convite em claro do último aviso mandado a este caso. */
function conviteDe(avisos: AvisosDaListaEmMemoria, id: string): string {
  const aviso = [...avisos.enviados].reverse().find((e) => e.onboardingId === id);
  assert.ok(aviso !== undefined, "nenhum convite foi mandado a este caso");
  const url = new URL(aviso.ligacao);
  assert.equal(url.pathname, "/ligar", "o convite abre a pagina do guia, que exige a sessao");
  const c = url.searchParams.get("convite");
  assert.ok(c !== null);
  return c;
}

describe("KAM-095 HTTP: a lista de espera como CapacityGate do guia", () => {
  it("o segundo caso espera, ve a posicao e a estimativa rotulada, e e convidado quando a vaga volta", async () => {
    const m = await montar(1);
    const a = await m.caso();
    const b = await m.caso();
    for (const id of [a.id, b.id]) await m.post("/api/es/preflight", ATESTADOS, id);
    assert.equal((await m.post("/api/es/iniciar", {}, a.id)).corpo.desfecho, "popup");
    assert.equal((await m.post("/api/es/iniciar", {}, b.id)).corpo.desfecho, "lista_espera");
    const p = await m.get("/api/lista/posicao", b.id);
    assert.equal(p.estado, 200);
    assert.deepEqual((p.corpo.posicao as Record<string, unknown>).estado, "aguardando");
    assert.equal((p.corpo.posicao as Record<string, unknown>).posicao, 1);
    assert.equal(((p.corpo.posicao as Record<string, unknown>).estimativa as Record<string, unknown>).rotulo, "estimativa");
    // A vaga de A sai da janela de 7 dias: o temporizador convida B.
    m.avancar(7 * DIA_MS + 1);
    assert.equal(await m.lista?.promover(), 1);
    const c = conviteDe(m.avisosDaLista, b.id);
    const valido = await m.post("/api/lista/convite", { c }, b.id);
    assert.equal(valido.estado, 200);
    assert.equal(valido.corpo.valido, true);
    // Conferir nao gasta: o convite so se gasta quando a vaga se da.
    assert.equal((await m.post("/api/lista/convite", { c }, b.id)).estado, 200);
    assert.equal((await m.post("/api/es/iniciar", {}, b.id)).corpo.desfecho, "popup");
    // Uso unico (adversarial b): depois de dada a vaga, a ligacao ja nao vale.
    const outra = await m.post("/api/lista/convite", { c }, b.id);
    assert.equal(outra.estado, 403);
    assert.deepEqual(outra.corpo, { erro: "token" });
  });

  it("ADVERSARIAL b: o convite de B com a sessao de A da 403, com o corpo do token forjado", async () => {
    const m = await montar(1);
    const [a, b, x] = [await m.caso(), await m.caso(), await m.caso()];
    for (const id of [x.id, a.id, b.id]) {
      await m.post("/api/es/preflight", ATESTADOS, id);
      await m.post("/api/es/iniciar", {}, id);
    }
    m.avancar(7 * DIA_MS + 1);
    await m.lista?.promover();
    const deA = conviteDe(m.avisosDaLista, a.id);
    const alheio = await m.post("/api/lista/convite", { c: deA }, b.id);
    const forjado = await m.post("/api/lista/convite", { c: "forjado" }, b.id);
    assert.equal(alheio.estado, 403);
    assert.deepEqual(alheio.corpo, forjado.corpo, "alheio e forjado nao se distinguem");
    assert.equal((await m.post("/api/lista/recusar", { c: deA }, b.id)).estado, 403);
    // O convite de A continua vivo para A.
    assert.equal((await m.post("/api/lista/convite", { c: deA }, a.id)).estado, 200);
  });

  it("isolamento: a posicao que A le e a de A, e um onboarding_id na consulta nao muda nada", async () => {
    const m = await montar(1);
    const [x, a, b] = [await m.caso(), await m.caso(), await m.caso()];
    for (const id of [x.id, a.id, b.id]) {
      await m.post("/api/es/preflight", ATESTADOS, id);
      await m.post("/api/es/iniciar", {}, id);
    }
    const deA = await m.get(`/api/lista/posicao?onboarding_id=${b.id}`, a.id);
    assert.equal((deA.corpo.posicao as Record<string, unknown>).posicao, 1);
    const deB = await m.get("/api/lista/posicao", b.id);
    assert.equal((deB.corpo.posicao as Record<string, unknown>).posicao, 2);
  });

  it("recusar passa a vaga ao seguinte; desistir sai da lista e liberta a posicao", async () => {
    const m = await montar(1);
    const [x, a, b] = [await m.caso(), await m.caso(), await m.caso()];
    for (const id of [x.id, a.id, b.id]) {
      await m.post("/api/es/preflight", ATESTADOS, id);
      await m.post("/api/es/iniciar", {}, id);
    }
    m.avancar(7 * DIA_MS + 1);
    await m.lista?.promover();
    assert.equal((await m.post("/api/lista/recusar", { c: conviteDe(m.avisosDaLista, a.id) }, a.id)).estado, 200);
    assert.equal(((await m.get("/api/lista/posicao", b.id)).corpo.posicao as Record<string, unknown>).estado, "convidado");
    assert.equal((await m.post("/api/lista/desistir", {}, a.id)).estado, 200);
    assert.equal(((await m.get("/api/lista/posicao", a.id)).corpo.posicao as Record<string, unknown>).estado, "desistiu");
  });

  it("sem sessao, as quatro dao 403; com sessao e sem lista montada, 404", async () => {
    const m = await montar();
    const a = await m.caso();
    assert.equal((await m.get("/api/lista/posicao")).estado, 403);
    for (const rota of ["/api/lista/convite", "/api/lista/recusar", "/api/lista/desistir"]) {
      assert.equal((await m.post(rota, { c: "x" })).estado, 403, rota);
      assert.equal((await m.post(rota, { c: "x" }, a.id)).estado, 404, rota);
    }
    assert.equal((await m.get("/api/lista/posicao", a.id)).estado, 404);
  });
});
