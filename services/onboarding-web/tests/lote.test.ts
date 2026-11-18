/**
 * O processo de lote do onboarding (KAM-198), sem base de dados.
 *
 * O que só uma base real prova — o ciclo contra a `0048`, o trinco da quota
 * entre dois processos, a lista de efeitos que sobrevive a um reinício — está em
 * `db/tests_lote/`, no gate 8. Aqui mede-se o que pode errar antes de haver
 * base: a configuração e o arranque, a verificação dos papéis, o escritor do
 * screening, o aviso sem via, as rotas e a forma como o processo compõe a fila.
 */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  AvisoSemDestinoError,
  ESPACO_DO_TRINCO_DA_QUOTA,
  METRICA_CASOS,
  METRICA_DECISOES,
  METRICA_FALSOS_APROVADOS,
  METRICA_P90,
  MetricasDaRevisao,
  SQL_ABRIR,
  SQL_TRINCO_DA_QUOTA,
  baldeDaAmostra,
  type ConjuntoSql,
  type EfeitosPorReaplicar,
  type ResultadoDoCiclo,
} from "@kamba/core-ts/revisao";
import { SQL_DECISOES, SQL_GRAVAR } from "@kamba/core-ts/screening";
import {
  AvisoDeSancaoSemDestinoError,
  INTERVALO_DO_TRUST_POR_OMISSAO_MS,
  MetricasDoTrust,
  SQL_GRAVAR_SANCAO,
  TIPOS_CONSUMIDOS,
} from "@kamba/core-ts/trust";
import {
  MetricasDaConfianca,
  SQL_DEFINIR_NIVEL,
  SQL_K1_COMPLETO,
  SQL_TRANCAR,
  type OrigemDoRecalculo,
} from "@kamba/core-ts/confianca";

import {
  AvisoDeSancaoSemVia,
  AvisoSemVia,
  ConfiguracaoDoLoteError,
  consumidorDoTrust,
  registarVoltaDoTrust,
  arrancar,
  opcoesDoConjunto,
  INTERVALO_POR_OMISSAO_MS,
  PORTA_POR_OMISSAO,
  PapelErradoError,
  VARIAVEIS_DO_LOTE,
  criarApp,
  escritorHumanoDeScreening,
  lerConfiguracao,
  montarProcesso,
  registarVolta,
  registarVoltaDaConfianca,
  verificarPapeis,
  OnboardingsQueRecalculam,
  SUBSCRICAO_DO_TRUST,
  depoisDoTrust,
} from "../src/lote/processo.ts";

const URL_LOTE = "postgresql://kamba_batch@lote.invalid:5432/kamba";
const URL_APP = "postgresql://kamba_app@app.invalid:5432/kamba";
const URL_FILA = "redis://fila.invalid:6379";

const BASE = {
  [VARIAVEIS_DO_LOTE.ambiente]: "prod",
  [VARIAVEIS_DO_LOTE.lote]: URL_LOTE,
  [VARIAVEIS_DO_LOTE.app]: URL_APP,
  [VARIAVEIS_DO_LOTE.fila]: URL_FILA,
};

// --------------------------------------------------------------- um duplo de pg

type Resposta = { rows: Record<string, unknown>[] };
type Tratador = (texto: string, valores: readonly unknown[]) => Resposta | undefined;

/** Um `pg.Pool` que regista cada consulta, com a ligação que a correu. */
class ConjuntoFalso implements ConjuntoSql {
  readonly consultas: { ligacao: string; texto: string; valores: readonly unknown[] }[] = [];
  readonly devolvidas: (Error | boolean | undefined)[] = [];
  #n = 0;

  readonly tratar: Tratador;

  constructor(tratar: Tratador = () => undefined) {
    this.tratar = tratar;
  }

  async query<T = Record<string, unknown>>(texto: string, valores: readonly unknown[] = []) {
    this.consultas.push({ ligacao: "conjunto", texto, valores });
    return (this.tratar(texto, valores) ?? { rows: [] }) as unknown as { readonly rows: readonly T[] };
  }

  async connect() {
    const nome = `ligacao-${++this.#n}`;
    const self = this;
    return {
      async query<T = Record<string, unknown>>(texto: string, valores: readonly unknown[] = []) {
        self.consultas.push({ ligacao: nome, texto, valores });
        return (self.tratar(texto, valores) ?? { rows: [] }) as unknown as { readonly rows: readonly T[] };
      },
      release(erro?: Error | boolean) {
        self.devolvidas.push(erro);
      },
    };
  }

  textos(): string[] {
    return this.consultas.map((c) => c.texto.trim());
  }
}

const efeitosVazios = (): EfeitosPorReaplicar => ({
  marcar: async () => {},
  pendentes: async () => [],
  resolver: async () => {},
});

const semRegisto = { warn: () => {}, info: () => {}, error: () => {} };

// ------------------------------------------------------- configuração e arranque

test("lerConfiguracao arranca em prod com as duas credenciais e as omissões", () => {
  const c = lerConfiguracao(BASE);
  assert.equal(c.ambiente, "prod");
  assert.equal(c.urlDoLote, URL_LOTE);
  assert.equal(c.urlDaApp, URL_APP);
  assert.equal(c.porta, PORTA_POR_OMISSAO);
  assert.equal(c.intervaloMs, INTERVALO_POR_OMISSAO_MS);
  assert.equal(c.inicioDaAmostragem, null);
  assert.equal(c.urlDaFila, URL_FILA);
  assert.equal(c.intervaloDoTrustMs, INTERVALO_DO_TRUST_POR_OMISSAO_MS);
});

test("sem a credencial de lote, ou a da app, não arranca — e o valor da outra não sai", () => {
  for (const falta of [VARIAVEIS_DO_LOTE.lote, VARIAVEIS_DO_LOTE.app, VARIAVEIS_DO_LOTE.ambiente, VARIAVEIS_DO_LOTE.fila]) {
    for (const valor of [undefined, "", "   "]) {
      const env = { ...BASE, [falta]: valor };
      assert.throws(
        () => lerConfiguracao(env),
        (e: unknown) =>
          e instanceof ConfiguracaoDoLoteError &&
          e.variavel === falta &&
          !e.message.includes(".invalid") &&
          !e.message.includes("postgresql://"),
        `${falta}=${JSON.stringify(valor)}`,
      );
    }
  }
});

test("um ambiente fora da lista não arranca", () => {
  assert.throws(() => lerConfiguracao({ ...BASE, KAMBA_AMBIENTE: "producao" }), ConfiguracaoDoLoteError);
});

test("porta, intervalo e dia da amostragem inválidos recusam-se", () => {
  const maus: [string, string][] = [
    [VARIAVEIS_DO_LOTE.porta, "0"],
    [VARIAVEIS_DO_LOTE.porta, "70000"],
    [VARIAVEIS_DO_LOTE.porta, "3014.5"],
    [VARIAVEIS_DO_LOTE.intervalo, "999"],
    [VARIAVEIS_DO_LOTE.intervalo, "abc"],
    [VARIAVEIS_DO_LOTE.intervaloDoTrust, "999"],
    [VARIAVEIS_DO_LOTE.intervaloDoTrust, "1h"],
    [VARIAVEIS_DO_LOTE.amostragem, "2026-02-30"],
    [VARIAVEIS_DO_LOTE.amostragem, "2026-11-13T00:00:00Z"],
    [VARIAVEIS_DO_LOTE.amostragem, "13/11/2026"],
  ];
  for (const [nome, valor] of maus) {
    assert.throws(
      () => lerConfiguracao({ ...BASE, [nome]: valor }),
      (e: unknown) => e instanceof ConfiguracaoDoLoteError && e.variavel === nome,
      `${nome}=${valor}`,
    );
  }
  const c = lerConfiguracao({
    ...BASE,
    [VARIAVEIS_DO_LOTE.porta]: "3999",
    [VARIAVEIS_DO_LOTE.intervalo]: "1000",
    [VARIAVEIS_DO_LOTE.amostragem]: "2026-11-02",
  });
  assert.equal(c.porta, 3999);
  assert.equal(c.intervaloMs, 1000);
  assert.equal(c.inicioDaAmostragem?.toISOString(), "2026-11-02T00:00:00.000Z");
});

test("o processo, sem as credenciais de lote, sai com código 1 em prod e não abre a porta", () => {
  const ficheiro = fileURLToPath(new URL("../src/lote.ts", import.meta.url));
  const env: Record<string, string> = { PATH: process.env.PATH ?? "", KAMBA_AMBIENTE: "prod", LOTE_PORT: "3999" };
  // Dois minutos e não trinta segundos: só carregar o processo leva ~40 s numa
  // montagem do Windows, e com os ficheiros de ensaio em paralelo mais (achado 8
  // da revisão adversarial). Um processo que pendure falha aqui com estado nulo.
  const r = spawnSync(process.execPath, [ficheiro], { env, encoding: "utf8", timeout: 120_000 });
  assert.equal(r.status, 1, r.stderr);
  const saida = `${r.stdout}${r.stderr}`;
  assert.match(saida, /arranque_falhou/);
  assert.match(saida, /ConfiguracaoDoLoteError/);
  assert.doesNotMatch(saida, /service_started/);
});

// -------------------------------------------------------------------- os papéis

test("verificarPapeis aceita kamba_batch e kamba_app e recusa as trocas, sem dizer o papel obtido", async () => {
  const comPapel = (papel: string) => new ConjuntoFalso(() => ({ rows: [{ papel }] }));
  await verificarPapeis(comPapel("kamba_batch"), comPapel("kamba_app"));
  for (const [lote, app, variavel] of [
    ["postgres", "kamba_app", VARIAVEIS_DO_LOTE.lote],
    ["kamba_app", "kamba_app", VARIAVEIS_DO_LOTE.lote],
    ["kamba_batch", "kamba_batch", VARIAVEIS_DO_LOTE.app],
    ["kamba_batch", "postgres", VARIAVEIS_DO_LOTE.app],
  ] as const) {
    await assert.rejects(
      verificarPapeis(comPapel(lote), comPapel(app)),
      (e: unknown) =>
        e instanceof PapelErradoError && e.message.startsWith(variavel) && !e.message.includes("postgres "),
      `${lote}/${app}`,
    );
  }
  await assert.rejects(verificarPapeis(new ConjuntoFalso(), comPapel("kamba_app")), PapelErradoError);
});

// ---------------------------------------------------------- o aviso e o resto

test("o aviso ao dono não tem via neste processo: levanta, e o efeito fica por aplicar", async () => {
  for (const via of ["sms", "email"] as const) {
    await assert.rejects(
      new AvisoSemVia().avisar({ onboardingId: "o", via, aviso: "aprovado", motivoPublico: null }),
      (e: unknown) => e instanceof AvisoSemDestinoError && e.via === via,
    );
  }
});

// --------------------------------------------------- o escritor do screening

const LINHA = {
  tenantId: "11111111-1111-4111-8111-111111111111",
  onboardingId: null,
  sujeitoTipo: "categoria" as const,
  sujeitoRef: "alimentar",
  decisao: "permitida" as const,
  regras: ["revisao_humana"],
  versaoPolitica: "1.0.0+ensaio",
  origem: "humano" as const,
  conteudoSha256: new Uint8Array(32).fill(7),
};

test("o screening grava como kamba_app dentro do comTenant do tenant da linha", async () => {
  const app = new ConjuntoFalso();
  await escritorHumanoDeScreening(app).gravar(LINHA);
  const textos = app.textos();
  assert.deepEqual(
    [textos[0], textos.at(-1)],
    ["BEGIN", "COMMIT"],
    "a leitura e a escrita correm numa transacção",
  );
  const contexto = app.consultas.find((c) => c.texto.includes("app.tenant_id"));
  assert.deepEqual(contexto?.valores, [LINHA.tenantId]);
  assert.ok(textos.includes(SQL_DECISOES.trim()));
  assert.ok(textos.includes(SQL_GRAVAR.trim()));
  assert.ok(app.consultas.every((c) => c.ligacao === "ligacao-1"), "uma ligação dedicada, e nunca o conjunto");
  assert.deepEqual(app.devolvidas, [undefined]);
});

test("o screening é idempotente: a mesma decisão humana não se repete, uma diferente grava", async () => {
  for (const [ultima, grava] of [
    [{ decisao: "permitida", origem: "humano" }, false],
    [{ decisao: "bloqueada", origem: "humano" }, true],
    [{ decisao: "permitida", origem: "regra" }, true],
    [null, true],
  ] as const) {
    const app = new ConjuntoFalso((t) =>
      t.trim() === SQL_DECISOES.trim() && ultima !== null
        ? { rows: [{ decisao: "condicional", origem: "regra" }, ultima] }
        : undefined,
    );
    await escritorHumanoDeScreening(app).gravar(LINHA);
    assert.equal(app.textos().includes(SQL_GRAVAR.trim()), grava, JSON.stringify(ultima));
  }
});

test("uma escrita que falha reverte e devolve a ligação com o erro, para o pg a descartar", async () => {
  const app = new ConjuntoFalso((t) => {
    if (t.trim() === SQL_GRAVAR.trim()) throw new Error("rls");
    return undefined;
  });
  await assert.rejects(escritorHumanoDeScreening(app).gravar(LINHA), /rls/);
  assert.equal(app.textos().at(-1), "ROLLBACK");
  assert.equal(app.devolvidas.length, 1);
  assert.ok(app.devolvidas[0] instanceof Error, "uma ligação de uma transacção falhada não volta ao conjunto como boa");
});

// ------------------------------------------------------------ a composição

test("o gancho do KAM-092 abre a auditoria pelo trinco da quota, numa transacção do lote", async () => {
  const hoje = new Date("2026-11-13T10:00:00Z");
  // Um onboarding que cai na amostra (balde < 0,2), procurado de forma determinística.
  let onboardingId = "";
  for (let i = 0; ; i++) {
    onboardingId = `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
    if (baldeDaAmostra(onboardingId) < 0.2) break;
  }
  const tenantId = "22222222-2222-4222-8222-222222222222";
  const lote = new ConjuntoFalso((t, v) =>
    t === SQL_ABRIR
      ? {
          rows: [
            {
              id: "33333333-3333-4333-8333-333333333333",
              tipo: v[0],
              onboarding_id: v[1],
              tenant_id: v[2],
              motivo_codigo: v[3],
              motivo_interno: v[4],
              motivo_publico: v[5],
              evidencias: v[6],
              recomendacao: v[7],
              estado: v[8],
              prioridade: v[9],
              fila_at: v[10],
              sla_alerta_at: v[11],
              sla_due_at: v[12],
              sla_alertado_at: null,
              criado_at: hoje,
            },
          ],
        }
      : undefined,
  );
  const p = montarProcesso({
    lote,
    app: new ConjuntoFalso(),
    efeitos: efeitosVazios(),
    log: semRegisto,
    inicioDaAmostragem: new Date("2026-11-02T00:00:00Z"),
    relogio: () => hoje,
  });
  const r = await p.aprovacaoAutomatica(onboardingId, tenantId);
  assert.equal(r?.estado, "aberto");
  const naLigacao = lote.consultas.filter((c) => c.ligacao === "ligacao-1");
  assert.deepEqual(
    naLigacao.map((c) => c.texto),
    ["BEGIN", SQL_TRINCO_DA_QUOTA, SQL_ABRIR, "COMMIT"],
  );
  assert.deepEqual(naLigacao[1]?.valores, [ESPACO_DO_TRINCO_DA_QUOTA, `sem_quota:${tenantId}`]);
  assert.equal(naLigacao[2]?.valores[0], "auditoria");
  assert.equal(naLigacao[2]?.valores[3], `amostra:${onboardingId}`);
  assert.deepEqual(lote.devolvidas, [undefined]);

  // Sem início da amostragem, o gancho existe e não abre nada.
  const semInicio = montarProcesso({ lote: new ConjuntoFalso(), app: new ConjuntoFalso(), efeitos: efeitosVazios(), log: semRegisto });
  assert.equal(await semInicio.aprovacaoAutomatica(onboardingId, tenantId), null);
});

test("o ciclo do processo corre os quatro passos sobre o lote e lê os efeitos da porta dada", async () => {
  const pedidos: string[] = [];
  const efeitos: EfeitosPorReaplicar = {
    marcar: async () => {},
    pendentes: async () => {
      pedidos.push("pendentes");
      return [];
    },
    resolver: async () => {},
  };
  const lote = new ConjuntoFalso();
  const p = montarProcesso({ lote, app: new ConjuntoFalso(), efeitos, log: semRegisto });
  const r = await p.ciclo.correr();
  assert.deepEqual(r.falhas, []);
  assert.deepEqual(pedidos, ["pendentes"]);
  assert.ok(lote.textos().some((t) => t.includes("FROM platform.v_review_sla")));
  assert.ok(lote.textos().some((t) => t.includes("estado = 'em_triagem_automatica' ORDER BY")));
});

// ---------------------------------------------------------- HTTP e registo

test("/healthz e /metrics: as quatro séries, da instância que o ciclo recalcula", async () => {
  const metricas = new MetricasDaRevisao();
  const app = criarApp(metricas);
  assert.equal((await app.request("/healthz")).status, 200);
  metricas.actualizar(
    [{ tipo: "kyc", estado: "aberto", filaEm: new Date(), primeiraDecisaoEm: null }],
    [{ tipo: "kyc", motivo: "k1", decisao: null, n: 1 }],
    { fixos: [], datas: [] },
  );
  const r = await app.request("/metrics");
  assert.equal(r.status, 200);
  assert.match(r.headers.get("content-type") ?? "", /^text\/plain; version=0\.0\.4/);
  const corpo = await r.text();
  for (const nome of [METRICA_P90, METRICA_CASOS, METRICA_DECISOES, METRICA_FALSOS_APROVADOS]) {
    assert.match(corpo, new RegExp(`^# TYPE ${nome} gauge$`, "m"));
  }
  assert.match(corpo, /^review_casos\{tipo="kyc",estado="aberto"\} 1$/m);
  assert.equal((await criarApp().request("/metrics")).status, 200);
  assert.equal((await app.request("/equipa/casos")).status, 404, "o lote não serve a consola");
});

test("registarVolta diz os passos que falharam pelo nome, e nada mais", () => {
  const linhas: unknown[] = [];
  const log = { info: (c: unknown) => linhas.push(["info", c]), error: (c: unknown) => linhas.push(["error", c]) };
  const volta = (falhas: ResultadoDoCiclo["falhas"]): ResultadoDoCiclo => ({
    entraram: 0,
    alertas: 0,
    reaplicados: 0,
    porReaplicar: 0,
    aprovados: 0,
    falhas,
  });
  registarVolta(log as never, volta([]));
  registarVolta(log as never, volta(["drenar", "reaplicar"]));
  assert.deepEqual(linhas, [
    ["info", { outcome: "ciclo_concluido" }],
    ["error", { outcome: "ciclo_com_falhas", error_code: "drenar,reaplicar" }],
  ]);
});

// ---------------------------------------------------------------- o arranque

test("arrancar verifica os papéis antes de montar, e com um papel trocado não devolve processo", async () => {
  const comPapel = (papel: string) => new ConjuntoFalso((t) => (t.includes("current_user") ? { rows: [{ papel }] } : undefined));
  const trocado = comPapel("kamba_app");
  await assert.rejects(
    arrancar({ lote: trocado, app: comPapel("kamba_app"), log: semRegisto, inicioDaAmostragem: null }),
    PapelErradoError,
  );
  assert.deepEqual(trocado.textos(), ["SELECT current_user::text AS papel"], "nada correu depois da recusa");
});

test("arrancar serve as métricas do ciclo do processo, e não uma instância vazia", async () => {
  const lote = new ConjuntoFalso((t) => (t.includes("current_user") ? { rows: [{ papel: "kamba_batch" }] } : undefined));
  const app = new ConjuntoFalso((t) => (t.includes("current_user") ? { rows: [{ papel: "kamba_app" }] } : undefined));
  const { processo, app: http } = await arrancar({ lote, app, log: semRegisto, inicioDaAmostragem: null });
  processo.ciclo.metricas.actualizar(
    [{ tipo: "trust", estado: "escalado", filaEm: new Date(), primeiraDecisaoEm: null }],
    [],
    { fixos: [], datas: [] },
  );
  const corpo = await (await http.request("/metrics")).text();
  assert.match(corpo, /^review_casos\{tipo="trust",estado="escalado"\} 1$/m);
  // A lista de efeitos do processo é a da base: a volta lê-a com a carência.
  await processo.ciclo.correr();
  const pedido = lote.consultas.find((c) => c.texto.includes("efeito_pendente_at IS NOT NULL"));
  assert.ok(pedido !== undefined, "o ciclo não leu a lista da base");
  assert.equal(pedido.valores[1], 120, "a carência por omissão são dois minutos");
});

test("o serviço do processo marca os efeitos na mesma lista que o ciclo reaplica", async () => {
  const marcas: string[] = [];
  const efeitos: EfeitosPorReaplicar = {
    marcar: async (id) => void marcas.push(id),
    pendentes: async () => [],
    resolver: async () => {},
  };
  const caso = "44444444-4444-4444-8444-444444444444";
  const tenant = "55555555-5555-4555-8555-555555555555";
  const agora = new Date("2026-11-13T10:00:00Z");
  const linhaDoCaso = {
    // Um caso `saga` e nao `trust`: desde o KAM-097, rejeitar um `trust` aplica uma
    // sancao, pede a regra e precisa de T&S ligado; o que se mede aqui e a marca.
    id: caso, tipo: "saga", onboarding_id: null, tenant_id: tenant, motivo_codigo: "saga:x",
    motivo_interno: "x", motivo_publico: "nao_foi_possivel_validar", evidencias: [], recomendacao: null,
    estado: "aberto", prioridade: 5, fila_at: agora, sla_alerta_at: agora, sla_due_at: agora,
    sla_alertado_at: null, criado_at: agora,
  };
  const lote = new ConjuntoFalso((t) => {
    if (t.includes("FROM platform.review_case WHERE id = $1")) return { rows: [linhaDoCaso] };
    if (t.startsWith("UPDATE platform.review_case SET estado")) return { rows: [{ id: caso }] };
    if (t.includes("INSERT INTO platform.review_decision_log")) {
      return { rows: [{ id: "d", case_id: caso, revisor_id: "r", decisao: "rejeitar", instancia: "primeira", regra: null, nota_enc: null, em: agora }] };
    }
    return undefined;
  });
  const p = montarProcesso({ lote, app: new ConjuntoFalso(), efeitos, log: semRegisto, relogio: () => agora });
  const revisor = { id: "66666666-6666-4666-8666-666666666666", papeis: ["ts_revisor" as const], mfa: true, nifHmac: null, telefoneHmac: null };
  await p.servico.decidir(revisor, caso, "rejeitar");
  assert.deepEqual(marcas, [caso], "o serviço do processo não tem a porta `efeitos`");
});

test("cada ligação tem limites de tempo, para uma espera presa não congelar o ciclo", () => {
  for (const papel of ["lote", "app"] as const) {
    const o = opcoesDoConjunto("postgresql://x@y.invalid/z", papel);
    assert.equal(o.connectionString, "postgresql://x@y.invalid/z");
    assert.ok(o.statement_timeout > 0 && o.statement_timeout <= 60_000);
    assert.ok(o.lock_timeout > 0 && o.lock_timeout <= o.statement_timeout);
    assert.ok(o.idle_in_transaction_session_timeout > 0);
  }
  assert.equal(opcoesDoConjunto("u", "lote").max, 4);
  // KAM-203: o recálculo da confiança toma uma ligação de cada conjunto por
  // tenant, e o da aplicação deixou de servir só o screening.
  assert.equal(opcoesDoConjunto("u", "app").max, 4);
});

// ------------------------------------------------------------ Trust & Safety (KAM-200)

test("o T&S está ligado à fila: rejeitar um caso trust grava a sanção no lote, e o aviso sem via fica por reaplicar", async () => {
  const marcas: string[] = [];
  const efeitos: EfeitosPorReaplicar = {
    marcar: async (id) => void marcas.push(id),
    pendentes: async () => [],
    resolver: async () => {},
  };
  const caso = "77777777-7777-4777-8777-777777777777";
  const tenant = "88888888-8888-4888-8888-888888888888";
  const agora = new Date("2026-11-17T10:00:00Z");
  const linhaDoCaso = {
    id: caso, tipo: "trust", onboarding_id: null, tenant_id: tenant, motivo_codigo: "sancao_limitacao:p1",
    motivo_interno: "queixas", motivo_publico: "nao_foi_possivel_validar",
    evidencias: [{ tipo: "ts_proposta", ref: JSON.stringify({ passo: "limitacao", justificacao: null }) }],
    recomendacao: "rejeitar", estado: "aberto", prioridade: 3, fila_at: agora, sla_alerta_at: agora,
    sla_due_at: agora, sla_alertado_at: null, criado_at: agora,
  };
  const lote = new ConjuntoFalso((t) => {
    if (t.includes("FROM platform.review_case WHERE id = $1")) return { rows: [linhaDoCaso] };
    if (t.startsWith("UPDATE platform.review_case SET estado")) return { rows: [{ id: caso }] };
    if (t.includes("INSERT INTO platform.review_decision_log")) {
      return { rows: [{ id: "d", case_id: caso, revisor_id: "r", decisao: "rejeitar", instancia: "primeira", regra: "R1", nota_enc: null, em: agora }] };
    }
    if (t === SQL_GRAVAR_SANCAO) return { rows: [{ id: "99999999-9999-4999-8999-999999999999", em: agora }] };
    return undefined;
  });
  const p = montarProcesso({ lote, app: new ConjuntoFalso(), efeitos, log: semRegisto, relogio: () => agora });
  const revisor = { id: "66666666-6666-4666-8666-666666666666", papeis: ["ts_revisor" as const], mfa: true, nifHmac: null, telefoneHmac: null };
  // A sanção grava-se, e o aviso — o último efeito — falha sem via: a decisão
  // sobe como efeito por aplicar, com a causa, e o caso fica marcado.
  await assert.rejects(
    p.servico.decidir(revisor, caso, "rejeitar", { regra: "R1" }),
    (e: unknown) => e instanceof Error && e.name === "EfeitoPorAplicarError" && e.cause instanceof AvisoDeSancaoSemDestinoError,
  );
  const sancao = lote.consultas.find((c) => c.texto === SQL_GRAVAR_SANCAO);
  assert.ok(sancao !== undefined, "a decisao nao chegou ao T&S: o `trust` das dependencias da fila nao esta ligado");
  assert.deepEqual(sancao.valores.slice(0, 4), [tenant, `caso:${caso}`, "limitacao", "humana"]);
  assert.deepEqual(marcas, [caso], "o aviso sem via deixa o efeito por reaplicar");
  assert.match(p.metricasDoTrust.exposicao(), /^ts_sancoes_total\{passo="limitacao",origem="humana"\} 1$/m);
});

test("o aviso de uma sanção não tem via neste processo: levanta", async () => {
  await assert.rejects(
    new AvisoDeSancaoSemVia().avisar({ tenantId: "t", motivo: "loja_suspensa" }),
    AvisoDeSancaoSemDestinoError,
  );
});

test("o consumidor de T&S: as dezasseis filas do trust, por ordem, com a máquina das encomendas e as métricas do processo", async () => {
  let pedido: Parameters<NonNullable<Parameters<typeof consumidorDoTrust>[0]["criar"]>>[0] | undefined;
  const metricasDoTrust = new MetricasDoTrust();
  consumidorDoTrust({
    urlDaApp: URL_APP,
    urlDaFila: URL_FILA,
    metricasDoTrust,
    recalculo: { recalcular: async () => ({ tenantId: "", nivel: null, mudou: false, motivo: null }) },
    log: semRegisto,
    criar: (o) => {
      pedido = o;
      return { fechar: async () => {} } as never;
    },
  });
  assert.ok(pedido !== undefined);
  assert.deepEqual(pedido.subscricao, { consumer: "trust", exigeOrdem: true });
  assert.equal(pedido.subscricao, SUBSCRICAO_DO_TRUST, "a subscricao e a do processo, e nao uma copia");
  assert.deepEqual(pedido.filas, Array.from({ length: 16 }, (_, i) => `evt.trust.p${i}`));
  assert.equal(pedido.url, URL_FILA);
  assert.equal(TIPOS_CONSUMIDOS.length, 7);
  // **A máquina é a das encomendas da réplica**, e não a da omissão
  // (`platform.orders`, que não existe): com a outra, cada `payment.*` dava
  // erro de relação até à DLQ (achado 1 da segunda revisão adversarial).
  const lidas: string[] = [];
  const leitor = {
    query: async (sql: string) => {
      lidas.push(sql);
      return { rows: [{ estado: "paga" }] };
    },
  };
  assert.ok(pedido.maquina !== undefined, "sem maquina, o consumir lanca nos payment.*");
  assert.equal(await pedido.maquina.estadoDe("order", "o-1", leitor), "paga");
  assert.match(lidas[0] ?? "", /FROM platform\.orders_mirror WHERE/);
  // **E o efeito é o de T&S**: um `screening.violation_detected` grava um sinal
  // pela ligação do consumo, e não é um efeito vazio.
  const escritas: string[] = [];
  const bd = {
    query: async (sql: string) => {
      escritas.push(sql);
      return { rows: /INSERT INTO platform\.ts_signal/.test(sql) ? [{ id: "s-1" }] : [], rowCount: 1 };
    },
  };
  await pedido.efeito(bd, {
    id: "e-1",
    tipo: "screening.violation_detected",
    versao: 2,
    tenant_id: "99999999-9999-4999-8999-999999999999",
    ocorrido_em: new Date().toISOString(),
    payload: { sku: "sku-1", versao_politica: "1.0.0" },
  } as never);
  assert.ok(escritas.some((s) => /INSERT INTO platform\.ts_signal/.test(s)), "o efeito do consumidor nao grava sinais");
});

test("/metrics serve as séries de T&S da instância do processo", async () => {
  const metricasDoTrust = new MetricasDoTrust();
  metricasDoTrust.sancao("suspensao", "humana");
  const corpo = await (await criarApp(new MetricasDaRevisao(), metricasDoTrust).request("/metrics")).text();
  assert.match(corpo, /^# TYPE ts_sinais_total counter$/m);
  assert.match(corpo, /^ts_sancoes_total\{passo="suspensao",origem="humana"\} 1$/m);
  assert.match(corpo, /^# TYPE ts_varreduras_total counter$/m);
});

test("registarVoltaDoTrust diz as varreduras que falharam pelo nome, e nada mais", () => {
  const linhas: unknown[] = [];
  const log = { info: (c: unknown) => linhas.push(["info", c]), error: (c: unknown) => linhas.push(["error", c]) };
  registarVoltaDoTrust(log as never, { feitas: {}, falhas: [] });
  registarVoltaDoTrust(log as never, { feitas: {}, falhas: ["fotos", "encerramentos"] });
  assert.deepEqual(linhas, [
    ["info", { outcome: "trust_varreduras_concluidas" }],
    ["error", { outcome: "trust_varreduras_com_falhas", error_code: "fotos,encerramentos" }],
  ]);
});

// ------------------------------------------------- a confiança gradual (KAM-203)

const TENANT_DA_CONFIANCA = "99999999-9999-4999-8999-999999999999";
const CASO_DA_CONFIANCA = "88888888-8888-4888-8888-888888888888";

/**
 * Uma base falsa para a aprovação pela porta e o recálculo a seguir: o caso
 * existe, o agregador diz `falta` (vazio aprova), e o tenant tem K1 e nenhum
 * nível. Devolve os dois conjuntos.
 */
function baseDaAprovacao(falta: string[]) {
  const tratar: Tratador = (texto, valores) => {
    if (/AS tenant_id FROM platform\.onboarding_case WHERE id = \$1/.test(texto)) return { rows: [{ tenant_id: TENANT_DA_CONFIANCA }] };
    if (/FOR UPDATE/.test(texto)) return { rows: [{ fase: "em_revisao" }] };
    if (/aprovacao_em_falta\(\$1\) AS falta/.test(texto)) return { rows: [{ falta }] };
    if (/AS pendente/.test(texto)) return { rows: [{ pendente: false }] };
    if (/evento_emitido/.test(texto)) return { rows: [{ emitido: false }] };
    if (/advance_case/.test(texto)) return { rows: [{ fase: "aprovado" }] };
    if (/intervencao_humana/.test(texto)) return { rows: [{ humana: false }] };
    if (/SELECT id, tenant_id, fase, fase_at/.test(texto) && valores[0] === CASO_DA_CONFIANCA) {
      return {
        rows: [
          {
            id: CASO_DA_CONFIANCA,
            tenant_id: TENANT_DA_CONFIANCA,
            fase: "aprovado",
            fase_at: new Date(),
            ip_prefix_hash: null,
            device_hash: null,
            nif_hmac: new Uint8Array(32),
            phone_hmac: new Uint8Array(32),
          },
        ],
      };
    }
    if (texto === SQL_K1_COMPLETO) return { rows: [{ completo: true }] };
    if (texto === SQL_DEFINIR_NIVEL) return { rows: [{ nivel: valores[1] }] };
    return undefined;
  };
  return { lote: new ConjuntoFalso(tratar), app: new ConjuntoFalso(tratar) };
}

test("a aprovação pela porta recalcula o tenant a seguir: nasce no nível 0, como kamba_batch", async () => {
  const { lote, app } = baseDaAprovacao([]);
  const metricasDaConfianca = new MetricasDaConfianca();
  const p = montarProcesso({ lote, app, efeitos: efeitosVazios(), log: semRegisto, metricasDaConfianca });
  const r = await p.aprovacaoDoKyc.aprovar(CASO_DA_CONFIANCA, TENANT_DA_CONFIANCA);
  assert.equal(r.estado, "aprovado");
  const definir = lote.consultas.filter((c) => c.texto === SQL_DEFINIR_NIVEL);
  assert.equal(definir.length, 1, "a aprovacao nao recalculou");
  assert.deepEqual(definir[0]!.valores.slice(0, 4), [TENANT_DA_CONFIANCA, 0, "5000000", "k1_completo"]);
  // A tranca e a escrita são da mesma ligação do lote, e não do conjunto solto.
  const tranca = lote.consultas.find((c) => c.texto === SQL_TRANCAR);
  assert.ok(tranca !== undefined && tranca.ligacao !== "conjunto");
  assert.equal(tranca.ligacao, definir[0]!.ligacao);
  assert.match(metricasDaConfianca.exposicao(), /^confianca_recalculos_total\{origem="aprovacao",desfecho="mudou"\} 1$/m);
});

test("uma aprovação por preencher não recalcula nada", async () => {
  const { lote, app } = baseDaAprovacao(["aceite"]);
  const p = montarProcesso({ lote, app, efeitos: efeitosVazios(), log: semRegisto });
  assert.equal((await p.aprovacaoDoKyc.aprovar(CASO_DA_CONFIANCA, TENANT_DA_CONFIANCA)).estado, "em_falta");
  assert.equal(lote.consultas.filter((c) => c.texto === SQL_TRANCAR).length, 0);
});

test("um recálculo que falha depois da aprovação não a faz parecer recusada: regista-se e conta", async () => {
  const { lote, app } = baseDaAprovacao([]);
  const original = lote.tratar;
  const falhada = new ConjuntoFalso((texto, valores) => {
    if (texto === SQL_TRANCAR) throw new Error("tranca presa");
    return original(texto, valores);
  });
  const avisos: unknown[] = [];
  const metricasDaConfianca = new MetricasDaConfianca();
  const p = montarProcesso({
    lote: falhada,
    app,
    efeitos: efeitosVazios(),
    log: { warn: (c?: object) => void avisos.push(c) },
    metricasDaConfianca,
  });
  assert.equal((await p.aprovacaoDoKyc.aprovar(CASO_DA_CONFIANCA, TENANT_DA_CONFIANCA)).estado, "aprovado");
  assert.deepEqual(avisos, [{ outcome: "confianca_aprovacao_falhou" }]);
  assert.match(metricasDaConfianca.exposicao(), /^confianca_recalculos_total\{origem="aprovacao",desfecho="falhou"\} 1$/m);
});

test("o aoAprovar dos onboardings só corre no aprovado, com o caso aprovado", async () => {
  const vistos: string[] = [];
  const { lote } = baseDaAprovacao(["kyc"]);
  const o = new OnboardingsQueRecalculam(lote, async (id) => void vistos.push(id));
  assert.equal((await o.aprovar(CASO_DA_CONFIANCA, "aprovar", "ensaio")).estado, "em_falta");
  assert.equal(vistos.length, 0, "uma aprovacao por preencher nao chama o aoAprovar");
  const aprova = new OnboardingsQueRecalculam(baseDaAprovacao([]).lote, async (id) => void vistos.push(id));
  assert.equal((await aprova.aprovar(CASO_DA_CONFIANCA, "aprovar", "ensaio")).estado, "aprovado");
  assert.deepEqual(vistos, [CASO_DA_CONFIANCA]);
});

test("o recálculo lê a independência com o consumidor da subscrição do processo, e não com um literal", () => {
  const p = montarProcesso({ lote: new ConjuntoFalso(), app: new ConjuntoFalso(), efeitos: efeitosVazios(), log: semRegisto });
  assert.equal(p.recalculo.consumidorDeTrust, SUBSCRICAO_DO_TRUST.consumer);
});

test("o depois do consumidor de T&S recalcula o tenant do order.delivered, e só dele", async () => {
  const pedidos: [string, OrigemDoRecalculo][] = [];
  const depois = depoisDoTrust({
    recalcular: async (t, origem) => {
      pedidos.push([t, origem]);
      return { tenantId: t, nivel: 0, mudou: false, motivo: null };
    },
  });
  for (const tipo of TIPOS_CONSUMIDOS) {
    await depois({ tipo, tenant_id: TENANT_DA_CONFIANCA } as never);
  }
  assert.deepEqual(pedidos, [[TENANT_DA_CONFIANCA, "entrega"]]);
  // Uma falha sobe, para o BullMQ repetir.
  const falha = depoisDoTrust({
    recalcular: async () => {
      throw new Error("base em baixo");
    },
  });
  await assert.rejects(falha({ tipo: "order.delivered", tenant_id: TENANT_DA_CONFIANCA } as never), /base em baixo/);
});

test("o consumidor de T&S passa o depois ao trabalhador, ligado ao recálculo do processo", async () => {
  let pedido: Parameters<NonNullable<Parameters<typeof consumidorDoTrust>[0]["criar"]>>[0] | undefined;
  const pedidos: string[] = [];
  consumidorDoTrust({
    urlDaApp: URL_APP,
    urlDaFila: URL_FILA,
    metricasDoTrust: new MetricasDoTrust(),
    recalculo: {
      recalcular: async (t) => {
        pedidos.push(t);
        return { tenantId: t, nivel: 0, mudou: false, motivo: null };
      },
    },
    log: semRegisto,
    criar: (o) => {
      pedido = o;
      return { fechar: async () => {} } as never;
    },
  });
  assert.ok(pedido?.depois !== undefined, "sem depois, o order.delivered nao recalcula ninguem");
  await pedido.depois({ tipo: "order.delivered", tenant_id: TENANT_DA_CONFIANCA } as never);
  assert.deepEqual(pedidos, [TENANT_DA_CONFIANCA]);
});

test("/metrics serve as séries da confiança da instância do processo, a zero desde o arranque", async () => {
  const p = montarProcesso({ lote: new ConjuntoFalso(), app: new ConjuntoFalso(), efeitos: efeitosVazios(), log: semRegisto });
  p.metricasDaConfianca.mudanca("historico_independente");
  const corpo = await (await criarApp(new MetricasDaRevisao(), new MetricasDoTrust(), p.metricasDaConfianca).request("/metrics")).text();
  assert.match(corpo, /^# TYPE confianca_recalculos_total counter$/m);
  assert.match(corpo, /^confianca_recalculos_total\{origem="diario",desfecho="mudou"\} 0$/m);
  assert.match(corpo, /^confianca_mudancas_total\{motivo="historico_independente"\} 1$/m);
  assert.doesNotMatch(corpo, new RegExp(TENANT_DA_CONFIANCA));
});

test("arrancar serve as métricas da confiança do processo, e não uma instância vazia", async () => {
  const papel = (nome: string) => new ConjuntoFalso((texto) => (/current_user/.test(texto) ? { rows: [{ papel: nome }] } : undefined));
  const { processo, app } = await arrancar({ lote: papel("kamba_batch"), app: papel("kamba_app"), log: semRegisto, inicioDaAmostragem: null });
  processo.metricasDaConfianca.recalculo("descida", "mudou");
  const corpo = await (await app.request("/metrics")).text();
  assert.match(corpo, /^confianca_recalculos_total\{origem="descida",desfecho="mudou"\} 1$/m);
});

test("registarVoltaDaConfianca diz se houve falhas, em números e nunca com tenant", () => {
  const linhas: unknown[] = [];
  const log = { info: (c: unknown) => linhas.push(["info", c]), error: (c: unknown) => linhas.push(["error", c]) };
  registarVoltaDaConfianca(log, "diaria", { tenants: 3, mudaram: 1, falhas: 0 });
  registarVoltaDaConfianca(log, "descida", { tenants: 2, mudaram: 0, falhas: 1 });
  assert.deepEqual(linhas, [
    ["info", { outcome: "confianca_diaria_concluida" }],
    ["error", { outcome: "confianca_descida_com_falhas", error_code: "recalculo_falhou" }],
  ]);
});
