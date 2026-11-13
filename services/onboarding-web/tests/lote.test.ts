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
  AvisoSemVia,
  ConfiguracaoDoLoteError,
  INTERVALO_POR_OMISSAO_MS,
  PORTA_POR_OMISSAO,
  PapelErradoError,
  VARIAVEIS_DO_LOTE,
  criarApp,
  escritorHumanoDeScreening,
  lerConfiguracao,
  montarProcesso,
  registarVolta,
  verificarPapeis,
} from "../src/lote/processo.ts";

const URL_LOTE = "postgresql://kamba_batch@lote.invalid:5432/kamba";
const URL_APP = "postgresql://kamba_app@app.invalid:5432/kamba";

const BASE = {
  [VARIAVEIS_DO_LOTE.ambiente]: "prod",
  [VARIAVEIS_DO_LOTE.lote]: URL_LOTE,
  [VARIAVEIS_DO_LOTE.app]: URL_APP,
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
});

test("sem a credencial de lote, ou a da app, não arranca — e o valor da outra não sai", () => {
  for (const falta of [VARIAVEIS_DO_LOTE.lote, VARIAVEIS_DO_LOTE.app, VARIAVEIS_DO_LOTE.ambiente]) {
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
  const r = spawnSync(process.execPath, [ficheiro], { env, encoding: "utf8", timeout: 30_000 });
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

test("uma escrita que falha reverte e devolve a ligação", async () => {
  const app = new ConjuntoFalso((t) => {
    if (t.trim() === SQL_GRAVAR.trim()) throw new Error("rls");
    return undefined;
  });
  await assert.rejects(escritorHumanoDeScreening(app).gravar(LINHA), /rls/);
  assert.equal(app.textos().at(-1), "ROLLBACK");
  assert.equal(app.devolvidas.length, 1);
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
    falhas,
  });
  registarVolta(log as never, volta([]));
  registarVolta(log as never, volta(["drenar", "reaplicar"]));
  assert.deepEqual(linhas, [
    ["info", { outcome: "ciclo_concluido" }],
    ["error", { outcome: "ciclo_com_falhas", error_code: "drenar,reaplicar" }],
  ]);
});
