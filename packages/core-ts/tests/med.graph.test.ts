/**
 * O `ClienteDeMidia` de producao e o *token* do canal pela conversa (KAM-231).
 *
 * Sem rede: o `fetch` e uma porta, e aqui e um duplo que guarda os pedidos e
 * responde o que cada caso precisa. O cofre e o `EnvSecretProvider` do Piloto
 * sobre um ambiente de ensaio, e o criptograma e o do `cifrarToken` do KAM-016
 * — o mesmo caminho que o processo percorre.
 *
 * O que estes ensaios prendem:
 *
 * 1. as duas etapas, com o *token* so no cabecalho de autorizacao;
 * 2. `4xx` e definitivo, `5xx`/`429`/`408`/rede/tempo esgotado repete-se — e
 *    o `pipeline.ts` faz mesmo as tres tentativas sobre este cliente;
 * 3. o *token* nunca segue para um anfitriao fora da lista, nem por `http`,
 *    nem por um redireccionamento;
 * 4. o tecto de bytes, anunciado, declarado e contado;
 * 5. nenhuma mensagem de erro leva o *token*, o URL ou o `media_id`;
 * 6. o *token* e o do canal **da conversa**, lido com o tenant no predicado.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { describe, it } from "node:test";

import {
  ANFITRIOES_DA_DESCARGA,
  ClienteDeMidiaDaGraph,
  LIMITES_POR_OMISSAO,
  Med,
  MidiaIndisponivelError,
  MidiaInesperadaError,
  SQL_TOKEN_REF_DA_CONVERSA,
  TENTATIVAS,
  tectoDosLimites,
  tokenDaConversa,
  type Buscar,
  type ClienteSql,
} from "../src/med/index.ts";
import { cifrarToken } from "../src/onboarding/cifra.ts";
import { EnvSecretProvider, nomeDaVariavel } from "../src/secrets/index.ts";
import { criarStorageFake } from "../src/storage/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const OUTRO = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b";
const CONVERSA = "5c6d7e8f-9a0b-4c1d-8e2f-3a4b5c6d7e8f";
const MEDIA_ID = "990011223344556";
/** Um *token* de ensaio: nao e de conta nenhuma, e nao tem a forma de um da Meta. */
const TOKEN = ["ensaio", "graph"].join("-");
const URL_DA_MIDIA = `https://${ANFITRIOES_DA_DESCARGA[0]}/whatsapp_business/attachments/?mid=${MEDIA_ID}&ext=1&hash=ensaio`;
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4]);

interface Pedido {
  readonly url: string;
  readonly autorizacao: string | undefined;
  readonly redirect: RequestInit["redirect"];
}

/** Um `fetch` que responde pela ordem de uma lista, e guarda os pedidos. */
function buscarCom(...respostas: (Response | Error)[]): { buscar: Buscar; pedidos: Pedido[] } {
  const pedidos: Pedido[] = [];
  const buscar: Buscar = async (url, init) => {
    const cabecalhos = init.headers as Record<string, string>;
    pedidos.push({ url, autorizacao: cabecalhos["authorization"], redirect: init.redirect });
    const proxima = respostas.shift();
    if (proxima === undefined) throw new Error("o ensaio nao previu este pedido");
    if (proxima instanceof Error) throw proxima;
    return proxima;
  };
  return { buscar, pedidos };
}

function jsonDaResolucao(extra: Record<string, unknown> = {}): Response {
  return new Response(
    JSON.stringify({
      messaging_product: "whatsapp",
      url: URL_DA_MIDIA,
      mime_type: "image/jpeg",
      sha256: "ensaio",
      file_size: JPEG.byteLength,
      id: MEDIA_ID,
      ...extra,
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}

function bytes(corpo: Uint8Array, cabecalhos: Record<string, string> = { "content-type": "image/jpeg" }): Response {
  return new Response(corpo, { status: 200, headers: cabecalhos });
}

function cliente(buscar: Buscar, extra: { bytesMaximos?: number; esperaMaximaMs?: number } = {}) {
  return new ClienteDeMidiaDaGraph({ token: async () => TOKEN, buscar, base: "http://graph.ensaio", ...extra });
}

/** Nenhuma mensagem leva o *token*, o URL nem o `media_id`. */
function semSegredos(erro: unknown): boolean {
  assert.ok(erro instanceof Error);
  for (const segredo of [TOKEN, URL_DA_MIDIA, MEDIA_ID, ANFITRIOES_DA_DESCARGA[0]!]) {
    assert.equal(erro.message.includes(segredo), false, `a mensagem leva ${segredo}`);
  }
  return true;
}

describe("o ClienteDeMidiaDaGraph (KAM-231)", () => {
  it("resolve e descarrega, com o token so no cabecalho, e o content-type da resposta", async () => {
    const { buscar, pedidos } = buscarCom(jsonDaResolucao(), bytes(JPEG, { "content-type": "image/png" }));
    const c = cliente(buscar);
    const resolvida = await c.resolver(TENANT, MEDIA_ID);
    assert.equal(resolvida.url, URL_DA_MIDIA);
    assert.equal(resolvida.contentType, "image/jpeg");
    assert.equal(resolvida.tamanho, JPEG.byteLength);
    const descarregada = await c.descarregar(TENANT, resolvida);
    assert.deepEqual([...descarregada.bytes], [...JPEG]);
    // O da resposta da descarga, e nao o anunciado pelo `resolver`.
    assert.equal(descarregada.contentType, "image/png");

    assert.equal(pedidos.length, 2);
    assert.match(pedidos[0]!.url, new RegExp(`^http://graph\\.ensaio/v[0-9.]+/${MEDIA_ID}$`));
    assert.equal(pedidos[1]!.url, URL_DA_MIDIA);
    for (const p of pedidos) {
      assert.equal(p.autorizacao, `Bearer ${TOKEN}`);
      // Um redireccionamento nao se segue: era sair da lista pela porta das traseiras.
      assert.equal(p.redirect, "manual");
    }
  });

  it("um 4xx e definitivo (MidiaInesperadaError), nas duas etapas, e sem segredos na mensagem", async () => {
    for (const estado of [400, 401, 403, 404]) {
      const { buscar } = buscarCom(new Response("{}", { status: estado }));
      await assert.rejects(cliente(buscar).resolver(TENANT, MEDIA_ID), (e: unknown) =>
        e instanceof MidiaInesperadaError && semSegredos(e),
      );
      const d = buscarCom(new Response("x", { status: estado }));
      await assert.rejects(
        cliente(d.buscar).descarregar(TENANT, { url: URL_DA_MIDIA, contentType: "image/jpeg" }),
        (e: unknown) => e instanceof MidiaInesperadaError && semSegredos(e),
      );
    }
  });

  it("um 5xx, um 429, um 408, a rede e o tempo esgotado passam com o tempo (MidiaIndisponivelError)", async () => {
    for (const resposta of [
      new Response("", { status: 500 }),
      new Response("", { status: 503 }),
      new Response("", { status: 429 }),
      new Response("", { status: 408 }),
      new TypeError(`fetch failed ${URL_DA_MIDIA} Bearer ${TOKEN}`),
    ]) {
      const { buscar } = buscarCom(resposta);
      await assert.rejects(cliente(buscar).resolver(TENANT, MEDIA_ID), (e: unknown) =>
        e instanceof MidiaIndisponivelError && semSegredos(e),
      );
    }
    // O tempo esgotado: um `fetch` que so acaba quando o sinal aborta.
    const pendurado: Buscar = (_url, init) =>
      new Promise((_resolver, rejeitar) => {
        init.signal?.addEventListener("abort", () => rejeitar(new Error(`aborted ${URL_DA_MIDIA}`)));
      });
    await assert.rejects(cliente(pendurado, { esperaMaximaMs: 20 }).resolver(TENANT, MEDIA_ID), (e: unknown) =>
      e instanceof MidiaIndisponivelError && semSegredos(e),
    );
  });

  it("um 3xx nao se segue, e e definitivo", async () => {
    const { buscar, pedidos } = buscarCom(
      new Response(null, { status: 302, headers: { location: "https://atacante.example/x" } }),
    );
    await assert.rejects(
      cliente(buscar).descarregar(TENANT, { url: URL_DA_MIDIA, contentType: "image/jpeg" }),
      (e: unknown) => e instanceof MidiaInesperadaError,
    );
    assert.equal(pedidos.length, 1);
  });

  it("**o token nunca vai para fora da lista**: outro anfitriao, http, credenciais, porta, sufixo", async () => {
    const anfitriao = ANFITRIOES_DA_DESCARGA[0]!;
    for (const url of [
      "https://atacante.example/midia",
      `http://${anfitriao}/midia`,
      `https://utilizador:senha@${anfitriao}/midia`,
      `https://${anfitriao}:8443/midia`,
      `https://${anfitriao}.atacante.example/midia`,
      `https://atacante${anfitriao}/midia`,
      "nao e um url",
    ]) {
      // No `resolver`: o URL vem da resposta da Graph, e e recusado antes de pedir.
      const r = buscarCom(jsonDaResolucao({ url }));
      await assert.rejects(cliente(r.buscar).resolver(TENANT, MEDIA_ID), (e: unknown) =>
        e instanceof MidiaInesperadaError && semSegredos(e),
      );
      // No `descarregar` directo: nenhum pedido sai.
      const d = buscarCom();
      await assert.rejects(
        cliente(d.buscar).descarregar(TENANT, { url, contentType: "image/jpeg" }),
        (e: unknown) => e instanceof MidiaInesperadaError,
      );
      assert.equal(d.pedidos.length, 0, url);
    }
  });

  it("um media_id que nao cabe num caminho e recusado sem pedido", async () => {
    for (const mediaId of ["../me", "1/2", "a?b=c", "%2e%2e", ""]) {
      const { buscar, pedidos } = buscarCom();
      await assert.rejects(cliente(buscar).resolver(TENANT, mediaId), (e: unknown) => e instanceof MidiaInesperadaError);
      assert.equal(pedidos.length, 0);
    }
  });

  it("uma resolucao 200 que nao e JSON, ou sem url, e definitiva", async () => {
    for (const resposta of [
      new Response("<html>", { status: 200 }),
      new Response(JSON.stringify({ mime_type: "image/jpeg" }), { status: 200 }),
    ]) {
      const { buscar } = buscarCom(resposta);
      await assert.rejects(cliente(buscar).resolver(TENANT, MEDIA_ID), (e: unknown) => e instanceof MidiaInesperadaError);
    }
  });

  it("o tecto de bytes: o anunciado recusa sem pedir, o declarado e o contado recusam a meio", async () => {
    assert.equal(tectoDosLimites(), LIMITES_POR_OMISSAO.media_documento.bytesMaximos);
    const tecto = 16;

    const anunciado = buscarCom();
    await assert.rejects(
      cliente(anunciado.buscar, { bytesMaximos: tecto }).descarregar(TENANT, {
        url: URL_DA_MIDIA,
        contentType: "image/jpeg",
        tamanho: tecto + 1,
      }),
      (e: unknown) => e instanceof MidiaInesperadaError,
    );
    assert.equal(anunciado.pedidos.length, 0);

    const declarado = buscarCom(bytes(new Uint8Array(4), { "content-type": "image/jpeg", "content-length": "17" }));
    await assert.rejects(
      cliente(declarado.buscar, { bytesMaximos: tecto }).descarregar(TENANT, { url: URL_DA_MIDIA, contentType: "image/jpeg" }),
      (e: unknown) => e instanceof MidiaInesperadaError,
    );

    // Sem `content-length`, e um corpo que mente: conta-se a medida que chega.
    let partes = 0;
    const fluxo = new ReadableStream<Uint8Array>({
      pull(controlo) {
        partes += 1;
        controlo.enqueue(new Uint8Array(8));
        if (partes > 100) controlo.close();
      },
    });
    const contado = buscarCom(new Response(fluxo, { status: 200, headers: { "content-type": "image/jpeg" } }));
    await assert.rejects(
      cliente(contado.buscar, { bytesMaximos: tecto }).descarregar(TENANT, { url: URL_DA_MIDIA, contentType: "image/jpeg" }),
      (e: unknown) => e instanceof MidiaInesperadaError,
    );
    assert.ok(partes < 10, `leu ${partes} partes depois do tecto`);

    // No tecto exacto passa.
    const exacto = buscarCom(bytes(new Uint8Array(tecto)));
    const ok = await cliente(exacto.buscar, { bytesMaximos: tecto }).descarregar(TENANT, {
      url: URL_DA_MIDIA,
      contentType: "image/jpeg",
    });
    assert.equal(ok.bytes.byteLength, tecto);
  });

  it("o pipeline repete o 5xx tres vezes sobre este cliente, e um 4xx nenhuma", async () => {
    const linhas: { asset_id: string }[] = [{ asset_id: "a-1" }];
    const bd: ClienteSql = {
      async query<T>(texto: string) {
        if (texto.includes("INSERT INTO")) return { rows: linhas as unknown as readonly T[] };
        if (texto.includes("UPDATE")) return { rows: linhas as unknown as readonly T[] };
        return { rows: [] };
      },
    };
    const pedido = {
      tenantId: TENANT,
      contactId: "c-1",
      conversationId: CONVERSA,
      wamid: "wamid.ENSAIO231",
      mediaId: MEDIA_ID,
      waType: "image",
    };
    const avisos: unknown[] = [];
    const tresFalhas = buscarCom(...Array.from({ length: TENTATIVAS }, () => new Response("", { status: 502 })));
    const med = new Med({
      bd,
      armazenamento: criarStorageFake().storage,
      midia: cliente(tresFalhas.buscar),
      avisarAgr: async (a) => {
        avisos.push(a);
      },
      dormir: async () => {},
    });
    const resultado = await med.receber(pedido);
    assert.equal(resultado.estado, "falhou");
    assert.equal(tresFalhas.pedidos.length, TENTATIVAS);
    assert.equal(avisos.length, 1);

    const umQuatro = buscarCom(new Response("", { status: 404 }));
    const med2 = new Med({
      bd,
      armazenamento: criarStorageFake().storage,
      midia: cliente(umQuatro.buscar),
      avisarAgr: async () => {},
      dormir: async () => {},
    });
    await assert.rejects(med2.receber(pedido), (e: unknown) => e instanceof MidiaInesperadaError);
    assert.equal(umQuatro.pedidos.length, 1);
  });
});

/** Um canal no cofre: a KEK, e o criptograma do *token* sob uma referencia cunhada. */
function cofreCom(tenantDoCriptograma = TENANT) {
  const kek = randomBytes(32).toString("base64");
  const ref = `meta_client_token/${randomBytes(16).toString("hex")}`;
  const env: Record<string, string> = {
    KAMBA_SECRET_KEK_TOKEN_CLIENTE: `t1:${kek}`,
    [nomeDaVariavel(ref)]: cifrarToken(kek, "t1", tenantDoCriptograma, TOKEN),
  };
  return { cofre: new EnvSecretProvider({ ambiente: "staging", env }), ref, env };
}

/**
 * A base, que so responde ao `SQL_TOKEN_REF_DA_CONVERSA` — e **le o predicado
 * no texto**: sem o `c.tenant_id = $1` e o `c.id = $2` escritos, a conversa de
 * outro tenant casava.
 */
class BaseDaConversa implements ClienteSql {
  readonly parametros: (readonly unknown[])[] = [];
  readonly #conversas: { tenant: string; id: string; ref: string }[];

  constructor(conversas: { tenant: string; id: string; ref: string }[]) {
    this.#conversas = conversas;
  }

  async query<T>(texto: string, valores: readonly unknown[] = []): Promise<{ rows: readonly T[] }> {
    if (texto !== SQL_TOKEN_REF_DA_CONVERSA) return { rows: [] };
    this.parametros.push(valores);
    const [tenant, id] = valores as string[];
    const porTenant = /c\.tenant_id = \$1/.test(texto);
    const porId = /c\.id = \$2/.test(texto);
    const rows = this.#conversas
      .filter((c) => (!porTenant || c.tenant === tenant) && (!porId || c.id === id))
      .map((c) => ({ token_ref: c.ref }));
    return { rows: rows as unknown as T[] };
  }
}

describe("tokenDaConversa (KAM-231)", () => {
  it("le o token_ref da conversa com o tenant e a conversa do pedido, e abre o criptograma", async () => {
    const { cofre, ref } = cofreCom();
    const bd = new BaseDaConversa([{ tenant: TENANT, id: CONVERSA, ref }]);
    assert.equal(await tokenDaConversa({ cofre, bd, conversationId: CONVERSA })(TENANT), TOKEN);
    assert.deepEqual(bd.parametros, [[TENANT, CONVERSA]]);
    // A juncao leva o tenant dos dois lados: um canal de outro tenant nao casa.
    assert.match(SQL_TOKEN_REF_DA_CONVERSA, /tc\.tenant_id = c\.tenant_id AND tc\.id = c\.channel_id/);
  });

  it("uma conversa que nao e do pedido nao serve: sem_canal", async () => {
    const { cofre, ref } = cofreCom();
    for (const conversa of [
      { tenant: OUTRO, id: CONVERSA, ref },
      { tenant: TENANT, id: "0b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e", ref },
    ]) {
      await assert.rejects(
        tokenDaConversa({ cofre, bd: new BaseDaConversa([conversa]), conversationId: CONVERSA })(TENANT),
        (e: unknown) => e instanceof MidiaInesperadaError && /sem_canal/.test(e.message),
      );
    }
  });

  it("sem o segredo no cofre: sem_segredo, e a mensagem nao leva a referencia", async () => {
    const { env, ref } = cofreCom();
    delete env[nomeDaVariavel(ref)];
    const cofre = new EnvSecretProvider({ ambiente: "staging", env });
    await assert.rejects(
      tokenDaConversa({ cofre, bd: new BaseDaConversa([{ tenant: TENANT, id: CONVERSA, ref }]), conversationId: CONVERSA })(TENANT),
      (e: unknown) => e instanceof MidiaInesperadaError && /sem_segredo/.test(e.message) && !e.message.includes(ref),
    );
  });

  it("um criptograma de outro tenant nao abre: nao_abre, e o token nao aparece", async () => {
    const { cofre, ref } = cofreCom(OUTRO);
    await assert.rejects(
      tokenDaConversa({ cofre, bd: new BaseDaConversa([{ tenant: TENANT, id: CONVERSA, ref }]), conversationId: CONVERSA })(TENANT),
      (e: unknown) => e instanceof MidiaInesperadaError && /nao_abre/.test(e.message) && !e.message.includes(TOKEN),
    );
  });

  it("a KEK em falta e do processo: sobe o erro do cofre, e nao um motivo do canal", async () => {
    const { env, ref } = cofreCom();
    delete env["KAMBA_SECRET_KEK_TOKEN_CLIENTE"];
    const cofre = new EnvSecretProvider({ ambiente: "staging", env });
    await assert.rejects(
      tokenDaConversa({ cofre, bd: new BaseDaConversa([{ tenant: TENANT, id: CONVERSA, ref }]), conversationId: CONVERSA })(TENANT),
      (e: unknown) => !(e instanceof MidiaInesperadaError),
    );
  });
});
