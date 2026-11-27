/**
 * O guia pelo processo de lote (KAM-239), sem base de dados.
 *
 * O que só a base prova — o estado do guia que sobrevive a um reinício, a reserva
 * e o `meta_es` que chegam à base pelo lote como `kamba_batch` — está em
 * `packages/core-ts/tests_bd/guia.bd.test.ts`, no gate 8. Aqui mede-se o que pode
 * errar antes de haver base: a rota interna (a credencial, as oito operações e
 * mais nenhuma, o corpo que cada uma lê), o cliente que a chama, a escolha das
 * portas no arranque do `onboarding-web`, a configuração do lote e a volta do guia.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AvisosDaListaEmMemoria,
  LIMITE_POR_OMISSAO,
  ListaDeEspera,
  ListaEmMemoria,
  ListaRecusadaError,
  type Posicao,
} from "@kamba/core-ts/capacidade";
import {
  AvisosEmMemoria,
  GatesEmMemoria,
  GuiaEmMemoria,
  PassoGuiado,
  RevisaoEmMemoria,
  SQL_ABANDONAR_VENCIDOS,
  SQL_PRESOS_SEM_REVISAO,
  SQL_RECONCILIAR_META_ES,
  type GateDoEs,
  type MotivoDeFalha,
} from "@kamba/core-ts/guia";

import {
  ClienteDoLote,
  GatesPeloLote,
  ListaPeloLote,
  LoteEmFaltaEmProducaoError,
  LoteIndisponivelError,
  RevisaoPeloLote,
  portasDoGuia,
  posicaoDoJson,
} from "../src/guia_pelo_lote.ts";
import {
  CABECALHO_DO_LOTE,
  CicloDoGuia,
  OPERACOES_DO_GUIA,
  PREFIXO_DO_GUIA,
  criarAppInterna,
  posicaoEmJson,
} from "../src/lote/interno.ts";
import { ConfiguracaoDoLoteError, lerConfiguracao } from "../src/lote/processo.ts";

/** Obviamente falsa e de baixa entropia, pela razão do `INTERNO_DE_ENSAIO` do X-01. */
const CREDENCIAL = "ensaio-kam-239-credencial-do-lote";
const CASO = "0000000a-0000-4000-8000-00000000000a";
const OUTRO_TENANT = "0000000b-0000-4000-8000-00000000000b";

/** Os duplos do lado do lote, com o registo de cada chamada. */
function duplos() {
  const chamadas: { readonly operacao: string; readonly argumentos: readonly unknown[] }[] = [];
  const registar = (operacao: string, ...argumentos: unknown[]): void => {
    chamadas.push({ operacao, argumentos });
  };
  let reserva: "granted" | "lista_espera" = "granted";
  let recusa: ListaRecusadaError | null = null;
  const lista = {
    async reserve(id: string) {
      registar("reserve", id);
      if (recusa !== null) throw recusa;
      return reserva;
    },
    async release(id: string) {
      registar("release", id);
    },
    async posicao(id: string): Promise<Posicao | null> {
      registar("posicao", id);
      return { estado: "aguardando", posicao: 3, estimativa: { rotulo: "estimativa", minimoDias: 2, maximoDias: Number.POSITIVE_INFINITY } };
    },
    async validarConvite(id: string, convite: unknown) {
      registar("validarConvite", id, convite);
      return { expiraEm: new Date("2026-11-24T10:00:00.000Z") };
    },
    async recusar(id: string, convite: unknown) {
      registar("recusar", id, convite);
    },
    async desistir(id: string) {
      registar("desistir", id);
    },
  };
  const gates = {
    async marcar(id: string, gate: GateDoEs, verde: boolean, motivo: string) {
      registar("marcar", id, gate, verde, motivo);
    },
  };
  const revisao = {
    async abrir(id: string, tipo: "es_falhado", motivo: MotivoDeFalha) {
      registar("abrir", id, tipo, motivo);
    },
  };
  const app = criarAppInterna({ lista, gates, revisao, credencial: CREDENCIAL });
  return {
    app,
    chamadas,
    reservar: (r: "granted" | "lista_espera") => {
      reserva = r;
    },
    recusar: (e: ListaRecusadaError | null) => {
      recusa = e;
    },
  };
}

function pedido(app: ReturnType<typeof criarAppInterna>, operacao: string, corpo: unknown, credencial?: string) {
  return app.request(`${PREFIXO_DO_GUIA}/${operacao}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(credencial === undefined ? {} : { [CABECALHO_DO_LOTE]: credencial }) },
    body: JSON.stringify(corpo),
  });
}

/** O cliente sobre a app, sem rede: o `fetch` é o `app.request`. */
function clienteSobre(app: ReturnType<typeof criarAppInterna>, credencial = CREDENCIAL): ClienteDoLote {
  return new ClienteDoLote({
    base: "http://lote.invalid",
    credencial: async () => credencial,
    buscar: (async (url: string | URL | Request, init?: RequestInit) =>
      app.request(new URL(String(url)).pathname, init)) as typeof fetch,
  });
}

// ------------------------------------------------------------------ a credencial

test("KAM-239: sem a credencial, ou com outra, as oito operações dão 401 e nenhuma chega às portas", async () => {
  const { app, chamadas } = duplos();
  for (const operacao of OPERACOES_DO_GUIA) {
    for (const credencial of [undefined, "", "errada", `${CREDENCIAL}x`, CREDENCIAL.slice(0, -1)]) {
      const r = await pedido(app, operacao, { onboarding_id: CASO, gate: "meta_es", verde: true, motivo: "ok", convite: "c" }, credencial);
      assert.equal(r.status, 401, `${operacao} com ${String(credencial)}`);
      assert.deepEqual(await r.json(), { erro: "credencial" });
    }
  }
  assert.equal(chamadas.length, 0);
});

test("KAM-239: sem a credencial, um caminho que não existe também dá 401, e não 404", async () => {
  const { app } = duplos();
  assert.equal((await pedido(app, "apagar", { onboarding_id: CASO })).status, 401);
  assert.equal((await app.request("/metrics")).status, 401);
});

test("KAM-239: com a credencial, só as oito operações existem", async () => {
  const { app, chamadas } = duplos();
  for (const caminho of [`${PREFIXO_DO_GUIA}/apagar`, `${PREFIXO_DO_GUIA}/`, "/healthz", "/interno/outra/reservar"]) {
    const r = await app.request(caminho, {
      method: "POST",
      headers: { [CABECALHO_DO_LOTE]: CREDENCIAL, "content-type": "application/json" },
      body: JSON.stringify({ onboarding_id: CASO }),
    });
    assert.equal(r.status, 404, caminho);
  }
  // E as oito só por POST.
  const r = await app.request(`${PREFIXO_DO_GUIA}/reservar`, { headers: { [CABECALHO_DO_LOTE]: CREDENCIAL } });
  assert.equal(r.status, 404);
  assert.equal(chamadas.length, 0);
});

// ------------------------------------------------------------------ o corpo

test("KAM-239: um onboarding_id sem forma de UUID dá 400, e não chega às portas", async () => {
  const { app, chamadas } = duplos();
  for (const operacao of OPERACOES_DO_GUIA) {
    for (const id of [undefined, "", "abc", 7, `${CASO} OR 1=1`]) {
      const r = await pedido(app, operacao, { onboarding_id: id, gate: "meta_es", verde: true, motivo: "ok", motivo_falha: "x" }, CREDENCIAL);
      assert.equal(r.status, 400, `${operacao} com ${String(id)}`);
    }
  }
  assert.equal(chamadas.length, 0);
});

test("KAM-239: nenhuma operação lê um tenant do pedido — as portas recebem só o caso e os campos dela", async () => {
  const { app, chamadas } = duplos();
  const extra = { tenant_id: OUTRO_TENANT, tenantId: OUTRO_TENANT };
  const corpos: Record<string, Record<string, unknown>> = {
    reservar: {},
    libertar: {},
    posicao: {},
    convite: { convite: "convite-de-ensaio" },
    recusar: { convite: "convite-de-ensaio" },
    desistir: {},
    gate: { gate: "meta_es", verde: false, motivo: "numero_divergente" },
    revisao: { motivo: "numero_divergente" },
  };
  for (const operacao of OPERACOES_DO_GUIA) {
    const r = await pedido(app, operacao, { onboarding_id: CASO.toUpperCase(), ...extra, ...corpos[operacao] }, CREDENCIAL);
    assert.equal(r.status, 200, operacao);
  }
  assert.deepEqual(
    chamadas.map((c) => c.operacao),
    ["reserve", "release", "posicao", "validarConvite", "recusar", "desistir", "marcar", "abrir"],
  );
  for (const c of chamadas) {
    assert.equal(c.argumentos[0], CASO, `${c.operacao}: o caso, minúsculo`);
    assert.ok(!JSON.stringify(c.argumentos).includes(OUTRO_TENANT), `${c.operacao}: o tenant do corpo não passa`);
  }
  assert.deepEqual(chamadas[6]?.argumentos, [CASO, "meta_es", false, "numero_divergente"]);
  assert.deepEqual(chamadas[7]?.argumentos, [CASO, "es_falhado", "numero_divergente"]);
});

test("KAM-239: o gate só aceita os dois do guia, a cor booleana e um motivo identificador", async () => {
  const { app, chamadas } = duplos();
  for (const corpo of [
    { gate: "e2e", verde: true, motivo: "ok" },
    { gate: "catalogo_minimo", verde: true, motivo: "ok" },
    { gate: "meta_es", verde: "true", motivo: "ok" },
    { gate: "meta_es", verde: true, motivo: "Texto livre do dono" },
    { gate: "meta_es", verde: true, motivo: "" },
    { gate: "meta_es", verde: true },
  ]) {
    const r = await pedido(app, "gate", { onboarding_id: CASO, ...corpo }, CREDENCIAL);
    assert.equal(r.status, 400, JSON.stringify(corpo));
  }
  for (const motivo of ["outro", "", undefined]) {
    assert.equal((await pedido(app, "revisao", { onboarding_id: CASO, motivo }, CREDENCIAL)).status, 400);
  }
  assert.equal(chamadas.length, 0);
});

// ------------------------------------------------------------------ o cliente

test("KAM-239: o cliente e a rota, ponta a ponta: a reserva, a posição, o convite e a recusa da lista", async () => {
  const d = duplos();
  const lista = new ListaPeloLote(clienteSobre(d.app));
  assert.equal(await lista.reserve(CASO), "granted");
  d.reservar("lista_espera");
  assert.equal(await lista.reserve(CASO), "lista_espera");
  const p = await lista.posicao(CASO);
  assert.deepEqual(p, {
    estado: "aguardando",
    posicao: 3,
    estimativa: { rotulo: "estimativa", minimoDias: 2, maximoDias: Number.POSITIVE_INFINITY },
  });
  assert.equal((await lista.validarConvite(CASO, "c")).expiraEm.toISOString(), "2026-11-24T10:00:00.000Z");
  // A recusa da lista volta a ser a recusa da lista, com o motivo.
  d.recusar(new ListaRecusadaError("kyc_caducado"));
  await assert.rejects(lista.reserve(CASO), (e: unknown) => e instanceof ListaRecusadaError && e.motivo === "kyc_caducado");
  await new GatesPeloLote(clienteSobre(d.app)).marcar(CASO, "meta_pagamento", false, "desconhecido");
  await new RevisaoPeloLote(clienteSobre(d.app)).abrir(CASO, "es_falhado", "ligacao_recusada");
  assert.deepEqual(d.chamadas.at(-2)?.argumentos, [CASO, "meta_pagamento", false, "desconhecido"]);
  assert.deepEqual(d.chamadas.at(-1)?.argumentos, [CASO, "es_falhado", "ligacao_recusada"]);
});

test("KAM-239: o cliente falha fechado — credencial errada, lote em baixo ou resposta fora do contrato", async () => {
  const d = duplos();
  await assert.rejects(new ListaPeloLote(clienteSobre(d.app, "errada")).reserve(CASO), LoteIndisponivelError);
  const emBaixo = new ClienteDoLote({
    base: "http://lote.invalid",
    credencial: async () => CREDENCIAL,
    buscar: (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch,
  });
  await assert.rejects(new ListaPeloLote(emBaixo).reserve(CASO), LoteIndisponivelError);
  const torto = new ClienteDoLote({
    base: "http://lote.invalid",
    credencial: async () => CREDENCIAL,
    buscar: (async () => new Response(JSON.stringify({ resultado: "talvez" }), { status: 200 })) as typeof fetch,
  });
  await assert.rejects(new ListaPeloLote(torto).reserve(CASO), LoteIndisponivelError);
  // Um 409 sem um motivo conhecido não é uma recusa da lista.
  const conflito = new ClienteDoLote({
    base: "http://lote.invalid",
    credencial: async () => CREDENCIAL,
    buscar: (async () => new Response(JSON.stringify({ recusa: "inventado" }), { status: 409 })) as typeof fetch,
  });
  await assert.rejects(new ListaPeloLote(conflito).reserve(CASO), LoteIndisponivelError);
});

test("KAM-239: a posição em JSON e de volta é a mesma, para os cinco estados", () => {
  const posicoes: Posicao[] = [
    { estado: "aguardando", posicao: 1, estimativa: { rotulo: "estimativa", minimoDias: 0, maximoDias: 7 } },
    { estado: "convidado", expiraEm: new Date("2026-11-24T10:00:00.000Z") },
    { estado: "concluido" },
    { estado: "expirado" },
    { estado: "desistiu" },
  ];
  for (const p of posicoes) assert.deepEqual(posicaoDoJson(JSON.parse(JSON.stringify(posicaoEmJson(p)))), p);
  assert.equal(posicaoDoJson(null), null);
  assert.throws(() => posicaoDoJson({ estado: "outro" }), LoteIndisponivelError);
});

// ------------------------------------------------------------------ o guia pelo lote

test("KAM-239: o PassoGuiado sobre a lista pelo lote abre o popup e põe na lista como com a lista no processo", async () => {
  const agora = new Date("2026-11-22T10:00:00.000Z").getTime();
  const relogio = (): Date => new Date(agora);
  // Um caso em `aguarda_es`, sem telefone: o pré-voo só lê a linha.
  const fases = new Map<string, string>();
  const casoDoEnsaio = (id: string) => ({ id, tenantId: OUTRO_TENANT, fase: fases.get(id) ?? "aguarda_es", nomeNegocio: "Loja de ensaio" });
  const casos = {
    porId: async (id: string) => (fases.has(id) ? casoDoEnsaio(id) : null),
    marcarFase: async (id: string, fase: string) => {
      fases.set(id, fase);
    },
    telefoneDe: async () => ({ linha: "movel" as const }),
  };
  const outro = "0000000c-0000-4000-8000-00000000000c";
  fases.set(CASO, "aguarda_es");
  fases.set(outro, "aguarda_es");
  // Do lado do lote: a lista de verdade, com uma vaga.
  const listaDoLote = new ListaDeEspera({
    repositorio: new ListaEmMemoria(casos as never, relogio, { ...LIMITE_POR_OMISSAO, maximo: 1 }),
    aviso: new AvisosDaListaEmMemoria(),
    origem: "https://onboarding.exemplo.test",
    relogio,
  });
  const gatesDoLote = new GatesEmMemoria();
  const app = criarAppInterna({ lista: listaDoLote, gates: gatesDoLote, revisao: new RevisaoEmMemoria(), credencial: CREDENCIAL });
  const portas = portasDoGuia<never>({
    ambiente: "prod",
    lote: clienteSobre(app),
    emMemoria: () => assert.fail("em prod com o lote, nada em memória"),
  });
  assert.equal(portas.voltaNoProcesso, false);
  const guia = new PassoGuiado({
    casos: casos as never,
    repositorio: new GuiaEmMemoria(relogio),
    capacidade: portas.lista,
    ligador: { ligar: async () => ({ desfecho: "criado", tentativaId: "t-1" }) },
    gates: portas.gates,
    revisao: portas.revisao,
    pagamento: { verificar: async () => "desconhecido" },
    aviso: new AvisosEmMemoria(),
    anelDoPepper: [Buffer.alloc(32, 1), null],
    chaveDaAssinatura: Buffer.alloc(32, 2),
    origem: "https://onboarding.exemplo.test",
    configId: "config-de-ensaio",
    relogio,
  });
  const atestados = {
    versaoDaApp: "2.24.17",
    appAbertaRecentemente: true,
    numeroEmWhatsAppPessoal: false,
    cartaoInternacional: true,
    donoPresente: true,
  };
  await guia.preflight(CASO, atestados);
  await guia.preflight(outro, atestados);
  assert.equal((await guia.iniciar(CASO)).desfecho, "popup", "a vaga, pelo lote");
  assert.equal((await guia.iniciar(outro)).desfecho, "lista_espera", "a segunda, para a lista");
  assert.equal((await listaDoLote.posicao(outro))?.estado, "aguardando");
  // O meta_pagamento vai para os gates do lote, e não para um duplo do processo.
  await guia.verificarPagamento(CASO);
  assert.deepEqual(gatesDoLote.de(CASO, "meta_pagamento"), { verde: false, motivo: "desconhecido" });
});

test("KAM-239: em prod sem o lote o guia recusa montar, e fora de prod fica em memória com a volta no processo", () => {
  assert.throws(
    () => portasDoGuia<never>({ ambiente: "prod", lote: null, emMemoria: () => assert.fail("não monta em memória") }),
    LoteEmFaltaEmProducaoError,
  );
  for (const ambiente of ["dev", "staging"] as const) {
    const p = portasDoGuia({
      ambiente,
      lote: null,
      emMemoria: () => ({ lista: "memoria", gates: new GatesEmMemoria(), revisao: new RevisaoEmMemoria() }),
    });
    assert.equal(p.lista, "memoria");
    assert.equal(p.voltaNoProcesso, true);
  }
});

// ------------------------------------------------------------------ o lote

const BASE = {
  KAMBA_AMBIENTE: "prod",
  KAMBA_LOTE_DB_URL: "postgresql://lote@base.invalid/kamba",
  KAMBA_LOTE_APP_DB_URL: "postgresql://app@base.invalid/kamba",
  KAMBA_QUEUE_URL: "redis://fila.invalid:6379",
};

test("KAM-239: a rota interna só se configura com a porta, noutra porta que a das métricas, e com a origem", () => {
  assert.equal(lerConfiguracao(BASE).interno, null);
  assert.deepEqual(
    lerConfiguracao({ ...BASE, LOTE_INTERNO_PORT: "3015", ONBOARDING_ORIGEM: "https://onboarding.exemplo.test" }).interno,
    { porta: 3015, anfitriao: "127.0.0.1", origem: "https://onboarding.exemplo.test" },
  );
  assert.equal(
    lerConfiguracao({
      ...BASE,
      LOTE_INTERNO_PORT: "3015",
      LOTE_INTERNO_HOST: "onboarding-lote-interno",
      ONBOARDING_ORIGEM: "https://onboarding.exemplo.test",
    }).interno?.anfitriao,
    "onboarding-lote-interno",
  );
  for (const env of [
    { ...BASE, LOTE_INTERNO_PORT: "3015" },
    { ...BASE, LOTE_INTERNO_PORT: "3014", ONBOARDING_ORIGEM: "https://onboarding.exemplo.test" },
    { ...BASE, LOTE_PORT: "4000", LOTE_INTERNO_PORT: "4000", ONBOARDING_ORIGEM: "https://onboarding.exemplo.test" },
    { ...BASE, LOTE_INTERNO_PORT: "3015", ONBOARDING_ORIGEM: "onboarding.exemplo.test" },
    { ...BASE, LOTE_INTERNO_PORT: "3015", ONBOARDING_ORIGEM: "https://onboarding.exemplo.test/ligar" },
  ]) {
    assert.throws(() => lerConfiguracao(env), ConfiguracaoDoLoteError, JSON.stringify(env));
  }
});

test("KAM-239: a volta do guia abandona como lote os popups vencidos há 30 minutos, e corre a lista mesmo se o abandono falha", async () => {
  const agora = new Date("2026-11-22T10:00:00.000Z");
  const instrucoes: { readonly sql: string; readonly parametros: readonly unknown[] }[] = [];
  const passos: string[] = [];
  const lista = {
    expirarVencidos: async () => {
      passos.push("expirar");
      return 0;
    },
    promover: async () => {
      passos.push("promover");
      return 0;
    },
    medir: async () => {
      passos.push("medir");
    },
  };
  const abertas: string[] = [];
  const revisao = {
    abrir: async (id: string) => {
      abertas.push(id);
    },
  };
  const ciclo = new CicloDoGuia({
    lote: {
      query: async (sql: string, parametros?: readonly unknown[]) => {
        instrucoes.push({ sql, parametros: parametros ?? [] });
        return { rows: sql === SQL_ABANDONAR_VENCIDOS ? [{ onboarding_id: CASO }] : [] };
      },
    },
    lista,
    revisao,
    relogio: () => agora,
  });
  assert.deepEqual(await ciclo.correr(), { abandonados: 1, gatesReconciliados: 0, revisoesAbertas: 0, falhou: [] });
  assert.equal(instrucoes[0]?.sql, SQL_ABANDONAR_VENCIDOS);
  assert.deepEqual(instrucoes[0]?.parametros, [new Date("2026-11-22T09:30:00.000Z")]);
  assert.deepEqual(
    instrucoes.slice(1).map((i) => i.sql),
    [SQL_RECONCILIAR_META_ES, SQL_PRESOS_SEM_REVISAO],
    "a reconciliação corre depois do abandono",
  );
  assert.deepEqual(passos, ["expirar", "promover", "medir"]);
  assert.deepEqual(abertas, []);
  const partido = new CicloDoGuia({
    lote: { query: async () => Promise.reject(new Error("base em baixo")) },
    lista,
    revisao,
    relogio: () => agora,
  });
  passos.length = 0;
  assert.deepEqual(await partido.correr(), {
    abandonados: 0,
    gatesReconciliados: 0,
    revisoesAbertas: 0,
    falhou: ["abandono", "reconciliacao"],
  });
  assert.deepEqual(passos, ["expirar", "promover", "medir"]);
});

test("KAM-254: a volta reconcilia o meta_es e abre o es_falhado dos presos sem caso; uma abertura que falha não pára as outras", async () => {
  const OUTRO = "00000000-0000-4000-8000-0000000000b2";
  const abertas: string[] = [];
  const ciclo = new CicloDoGuia({
    lote: {
      query: async (sql: string) => {
        if (sql === SQL_RECONCILIAR_META_ES) return { rows: [{ onboarding_id: CASO }, { onboarding_id: OUTRO }] };
        if (sql === SQL_PRESOS_SEM_REVISAO) return { rows: [{ onboarding_id: OUTRO }, { onboarding_id: CASO }] };
        return { rows: [] };
      },
    },
    lista: { expirarVencidos: async () => 0, promover: async () => 0, medir: async () => {} },
    revisao: {
      abrir: async (id: string, tipo: string, motivo: string) => {
        assert.equal(tipo, "es_falhado");
        assert.equal(motivo, "numero_divergente");
        if (id === OUTRO) throw new Error("a fila recusou");
        abertas.push(id);
      },
    },
    relogio: () => new Date("2026-11-24T10:00:00.000Z"),
  });
  assert.deepEqual(await ciclo.correr(), {
    abandonados: 0,
    gatesReconciliados: 2,
    revisoesAbertas: 1,
    falhou: ["reconciliacao"],
  });
  assert.deepEqual(abertas, [CASO], "o segundo abre-se mesmo com o primeiro a falhar");
});
