/**
 * A fila de revisão por unidade (KAM-089): o SLA em dias úteis de Luanda, os
 * feriados, o percentil, a máscara, o balde da amostra e as métricas.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DESVIO_DE_LUANDA_MS,
  FERIADOS_POR_OMISSAO,
  METRICA_P90,
  MetricasDaRevisao,
  TRANSICOES,
  baldeDaAmostra,
  calcularSla,
  diaEmLuanda,
  diaUtil,
  inicioDoDiaEmLuanda,
  mascarar,
  percentil,
  somarTempoUtil,
  tempoUtilEntre,
  type Feriados,
} from "../src/revisao/index.ts";

const SEM_FERIADOS: Feriados = { fixos: [], datas: [] };
const H = 3_600_000;
const DIA = 24 * H;
/** Luanda é UTC+1: `l("2026-11-13T10:00")` é sexta às 10:00 em Luanda. */
const l = (local: string) => new Date(new Date(`${local}:00Z`).getTime() - DESVIO_DE_LUANDA_MS);

describe("o dia de Luanda", () => {
  it("as 23:30 UTC ja e o dia seguinte em Luanda", () => {
    assert.equal(diaEmLuanda(new Date("2026-11-13T23:30:00Z")), "2026-11-14");
    assert.equal(diaEmLuanda(new Date("2026-11-13T22:59:59Z")), "2026-11-13");
  });

  it("o desvio fixo concorda com o Intl em Africa/Luanda, em Janeiro e em Julho", () => {
    const f = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Luanda", year: "numeric", month: "2-digit", day: "2-digit" });
    for (const i of ["2026-01-15T23:10:00Z", "2026-07-15T23:10:00Z", "2026-03-29T00:30:00Z", "2026-10-25T23:30:00Z"]) {
      assert.equal(diaEmLuanda(new Date(i)), f.format(new Date(i)), i);
    }
  });

  it("a meia-noite de Luanda e as 23:00 UTC do dia anterior", () => {
    assert.equal(inicioDoDiaEmLuanda(new Date("2026-11-13T09:00:00Z")).toISOString(), "2026-11-12T23:00:00.000Z");
  });
});

describe("dias uteis e feriados (criterio 2)", () => {
  it("sabado e domingo nao sao uteis; segunda e", () => {
    assert.equal(diaUtil("2026-11-14", SEM_FERIADOS), false);
    assert.equal(diaUtil("2026-11-15", SEM_FERIADOS), false);
    assert.equal(diaUtil("2026-11-16", SEM_FERIADOS), true);
  });

  it("um feriado fixo e um movel, pela tabela configuravel", () => {
    const f: Feriados = { fixos: ["11-11"], datas: ["2026-02-17"] };
    assert.equal(diaUtil("2026-11-11", f), false);
    assert.equal(diaUtil("2027-11-11", f), false);
    assert.equal(diaUtil("2026-02-17", f), false);
    assert.equal(diaUtil("2027-02-17", f), true, "o movel so vale no ano dele");
    assert.equal(diaUtil("2026-11-11", SEM_FERIADOS), true);
  });

  it("a tabela por omissao tem o 11 de Novembro (NAO VERIFICADA, mas presente)", () => {
    assert.ok(FERIADOS_POR_OMISSAO.fixos.includes("11-11"));
  });

  it("sexta 15:00 mais um dia util e segunda 15:00", () => {
    assert.equal(somarTempoUtil(l("2026-11-13T15:00"), DIA, SEM_FERIADOS).getTime(), l("2026-11-16T15:00").getTime());
  });

  it("sabado 10:00 mais um dia util e terca 00:00 (o tempo so corre segunda)", () => {
    assert.equal(somarTempoUtil(l("2026-11-14T10:00"), DIA, SEM_FERIADOS).getTime(), l("2026-11-17T00:00").getTime());
  });

  it("uma terca 09:00 com a quarta feriado vence quinta 09:00", () => {
    const f: Feriados = { fixos: [], datas: ["2026-11-11"] };
    assert.equal(somarTempoUtil(l("2026-11-10T09:00"), DIA, f).getTime(), l("2026-11-12T09:00").getTime());
  });

  it("o alerta dos 80% de um caso aberto sexta 15:00 e segunda 10:12", () => {
    const sla = calcularSla(l("2026-11-13T15:00"), SEM_FERIADOS, 1, 0.8);
    assert.equal(sla.slaAlertaAt.getTime(), l("2026-11-16T10:12").getTime());
    assert.equal(sla.slaDueAt.getTime(), l("2026-11-16T15:00").getTime());
  });

  it("o tempo util entre sexta 15:00 e segunda 15:00 e exactamente um dia", () => {
    assert.equal(tempoUtilEntre(l("2026-11-13T15:00"), l("2026-11-16T15:00"), SEM_FERIADOS), DIA);
    assert.equal(tempoUtilEntre(l("2026-11-14T08:00"), l("2026-11-15T20:00"), SEM_FERIADOS), 0, "o fim-de-semana nao conta");
    assert.equal(tempoUtilEntre(l("2026-11-16T15:00"), l("2026-11-13T15:00"), SEM_FERIADOS), 0);
  });

  it("uma tabela sem dias uteis e erro, nao ciclo infinito", () => {
    const tudo: Feriados = { fixos: [], datas: [] };
    const semana = { ...tudo, fixos: Array.from({ length: 12 }, (_, m) => Array.from({ length: 31 }, (_, d) => `${String(m + 1).padStart(2, "0")}-${String(d + 1).padStart(2, "0")}`)).flat() };
    assert.throws(() => somarTempoUtil(l("2026-11-13T15:00"), DIA, semana), RangeError);
  });

  it("um tempo negativo recusa", () => {
    assert.throws(() => somarTempoUtil(SEMPRE, -1, SEM_FERIADOS), RangeError);
  });
});

const SEMPRE = new Date("2026-11-13T09:00:00Z");

describe("o percentil", () => {
  it("nearest rank: o p90 de 1..10 e 9 e o de 1..20 e 18", () => {
    assert.equal(percentil([10, 1, 2, 3, 4, 5, 6, 7, 8, 9], 0.9), 9);
    assert.equal(percentil(Array.from({ length: 20 }, (_, i) => i + 1), 0.9), 18);
    assert.equal(percentil([7], 0.9), 7);
    assert.equal(percentil([], 0.9), null);
  });
});

describe("a mascara (criterio 6)", () => {
  it("mostra os tres ultimos e tapa o resto", () => {
    assert.equal(mascarar("5417038261"), "*******261");
    assert.equal(mascarar("004512345LA041"), "***********041");
    assert.equal(mascarar("923 456 789"), "******789");
  });

  it("um valor de tres ou menos tapa-se inteiro", () => {
    assert.equal(mascarar("123"), "***");
    assert.equal(mascarar("12"), "**");
  });
});

describe("o balde da amostra (criterio 7)", () => {
  it("e deterministico e, em 10 000 identificadores, perto de uniforme", () => {
    assert.equal(baldeDaAmostra("a1b2"), baldeDaAmostra("A1B2"));
    let abaixo = 0;
    for (let i = 0; i < 10_000; i++) if (baldeDaAmostra(`00000000-0000-4000-8000-${String(i).padStart(12, "0")}`) < 0.2) abaixo++;
    assert.ok(abaixo > 1_800 && abaixo < 2_200, `${abaixo} em 10 000`);
  });
});

describe("a maquina de estados", () => {
  it("decidido_final nao sai, e decidido so vai a recurso", () => {
    assert.deepEqual(TRANSICOES.decidido_final, []);
    assert.deepEqual(TRANSICOES.decidido, ["recurso_aberto"]);
    assert.deepEqual(TRANSICOES.em_triagem_automatica, ["aberto"]);
  });
});

describe("as metricas (criterio 2 e 8)", () => {
  it("o p90 e do tempo util: um caso de sexta a segunda conta um dia, nao tres", () => {
    const m = new MetricasDaRevisao();
    const vista = Array.from({ length: 10 }, (_, i) => ({
      tipo: "kyc" as const,
      estado: "decidido" as const,
      filaEm: l("2026-11-13T15:00"),
      primeiraDecisaoEm: new Date(l("2026-11-16T15:00").getTime() - (9 - i) * H),
    }));
    m.actualizar(vista, [], SEM_FERIADOS);
    assert.equal(m.p90, (DIA - H) / 1000);
    assert.equal(m.casos("kyc", "decidido"), 10);
    assert.match(m.exposicao(), new RegExp(`^${METRICA_P90} ${(DIA - H) / 1000}$`, "m"));
  });

  it("sem decisoes, o p90 sai NaN e nao zero", () => {
    const m = new MetricasDaRevisao();
    m.actualizar([{ tipo: "kyc", estado: "aberto", filaEm: SEMPRE, primeiraDecisaoEm: null }], [], SEM_FERIADOS);
    assert.match(m.exposicao(), new RegExp(`^${METRICA_P90} NaN$`, "m"));
  });

  it("a taxa de falsos aprovados vem das auditorias decididas", () => {
    const m = new MetricasDaRevisao();
    m.actualizar([], [
      { tipo: "auditoria", motivo: "amostra", decisao: "aprovar", n: 9 },
      { tipo: "auditoria", motivo: "amostra", decisao: "rejeitar", n: 1 },
      { tipo: "auditoria", motivo: "amostra", decisao: null, n: 5 },
      { tipo: "kyc", motivo: "kyc_k1", decisao: "rejeitar", n: 4 },
    ], SEM_FERIADOS);
    assert.equal(m.falsosAprovados, 0.1);
    assert.match(m.exposicao(), /^review_decisoes\{tipo="auditoria",decisao="sem_decisao"\} 5$/m);
    assert.match(m.exposicao(), /^review_decisoes\{tipo="kyc",decisao="rejeitar"\} 4$/m);
  });

  it("as series existem todas a zero, e nenhuma etiqueta leva caso ou tenant", () => {
    const e = new MetricasDaRevisao().exposicao();
    assert.match(e, /^review_casos\{tipo="trust",estado="recurso_aberto"\} 0$/m);
    assert.doesNotMatch(e, /tenant|onboarding|case_id/);
  });
});
