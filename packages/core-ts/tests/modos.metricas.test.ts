/**
 * As métricas dos modos da conversa (KAM-018, DoD «Custo e observabilidade»).
 *
 * O que aqui se prova é o que a revisão adversarial do KAM-013 ensinou a provar
 * sobre métricas: que as listas são **fechadas** — um identificador não entra em
 * etiqueta nenhuma (`docs/seguranca/ameacas_stride.md`, OBS-I) —, que a
 * exposição mostra as três mesmo sem dados, e que o nome que o DoD pede e que
 * **não** entra não entra mesmo.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { GATILHOS } from "../src/modos/index.ts";
import {
  CONTADORES,
  METRICA_REJEITADAS,
  METRICA_SUPRIMIDAS,
  METRICA_TRANSICOES,
  MOTIVOS_DE_SUPRESSAO,
  MetricaDesconhecidaError,
  MetricasDosModos,
  SufixoInvalidoError,
} from "../src/modos/index.ts";

describe("os nomes", () => {
  it("as tres, e nenhuma mais", () => {
    assert.deepEqual([...CONTADORES].sort(), [
      "conv_mode_rejected_total",
      "conv_mode_transitions_total",
      "reply_suppressed_total",
    ]);
  });

  it("o `echo_latency_ms` do DoD **nao** esta aqui, e e decisao", () => {
    // Fica de fora com o critério 8: pede ≥ 30 *echoes* reais de *staging* com
    // números +244 (L6/R6, KAM-100). Uma métrica declarada e sempre a zero diz
    // «a latência do *echo* é nula» quando o que se passa é que ninguém a mede.
    assert.ok(!(CONTADORES as readonly string[]).includes("echo_latency_ms"));
  });

  it("os tres motivos de supressao, pela ordem em que estao escritos", () => {
    assert.deepEqual([...MOTIVOS_DE_SUPRESSAO], [
      "modo",
      "actividade_humana",
      "sem_turno",
    ]);
  });
});

describe("MetricasDosModos", () => {
  let m: MetricasDosModos;
  beforeEach(() => {
    m = new MetricasDosModos();
  });

  it("conta por etiqueta, e soma na repeticao", () => {
    m.contar(METRICA_TRANSICOES, "opt_out");
    m.contar(METRICA_TRANSICOES, "opt_out");
    m.contar(METRICA_TRANSICOES, "echo_do_dono", 3);
    assert.deepEqual(m.ler(), {
      "conv_mode_transitions_total:opt_out": 2,
      "conv_mode_transitions_total:echo_do_dono": 3,
    });
  });

  it("um nome fora da lista fechada levanta", () => {
    assert.throws(() => m.contar("echo_latency_ms"), MetricaDesconhecidaError);
    assert.throws(() => m.contar("conv_mode_total"), MetricaDesconhecidaError);
  });

  it("um sufixo fora da lista fechada levanta, e a mensagem diz porque", () => {
    // **É isto que impede um identificador de entrar numa etiqueta**, e o caso
    // real não é um nome inventado: é um `tenant_id`.
    assert.throws(
      () => m.contar(METRICA_TRANSICOES, "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"),
      SufixoInvalidoError,
    );
    assert.throws(() => m.contar(METRICA_SUPRIMIDAS, "echo_do_dono"), SufixoInvalidoError);
    assert.throws(() => m.contar(METRICA_REJEITADAS, "modo"), SufixoInvalidoError);
    assert.throws(
      () => m.contar(METRICA_TRANSICOES, "qualquer"),
      /nao esta na lista fechada/,
    );
  });

  it("os oito gatilhos sao sufixos validos nas duas metricas que os levam", () => {
    for (const gatilho of GATILHOS) {
      m.contar(METRICA_TRANSICOES, gatilho);
      m.contar(METRICA_REJEITADAS, gatilho);
    }
    assert.equal(Object.keys(m.ler()).length, 2 * GATILHOS.length);
  });

  it("sem sufixo tambem conta, e sai sem etiqueta", () => {
    m.contar(METRICA_SUPRIMIDAS);
    assert.deepEqual(m.ler(), { reply_suppressed_total: 1 });
    assert.match(m.exposicao(), /^reply_suppressed_total 1$/m);
  });

  it("o `repor` esvazia", () => {
    m.contar(METRICA_TRANSICOES, "opt_out");
    m.repor();
    assert.deepEqual(m.ler(), {});
  });
});

describe("a exposicao no formato do Prometheus", () => {
  let m: MetricasDosModos;
  beforeEach(() => {
    m = new MetricasDosModos();
  });

  it("as tres aparecem a zero mesmo sem dados", () => {
    // Um painel que mostre «sem dados» não distingue «nenhuma supressão» de «o
    // processo não arrancou». É a escolha do `chr/metricas.ts`.
    const texto = m.exposicao();
    for (const nome of CONTADORES) {
      assert.match(texto, new RegExp(`^# TYPE ${nome} counter$`, "m"));
      assert.match(texto, new RegExp(`^${nome} 0$`, "m"));
    }
  });

  it("cada serie sai com a etiqueta da sua metrica", () => {
    m.contar(METRICA_TRANSICOES, "opt_out", 2);
    m.contar(METRICA_REJEITADAS, "comando_bot");
    m.contar(METRICA_SUPRIMIDAS, "actividade_humana", 5);
    const texto = m.exposicao();
    assert.match(texto, /^conv_mode_transitions_total\{gatilho="opt_out"\} 2$/m);
    assert.match(texto, /^conv_mode_rejected_total\{gatilho="comando_bot"\} 1$/m);
    assert.match(texto, /^reply_suppressed_total\{motivo="actividade_humana"\} 5$/m);
  });

  it("as series de uma metrica nao colhem as de outra com prefixo parecido", () => {
    // `conv_mode_transitions_total` e `conv_mode_rejected_total` partilham o
    // prefixo `conv_mode_`: o filtro é por `nome` exacto ou `nome:`, e não por
    // `startsWith(nome)` solto.
    m.contar(METRICA_TRANSICOES, "opt_out");
    const texto = m.exposicao();
    const linhas = texto.split("\n").filter((l) => l.startsWith("conv_mode_rejected_total"));
    assert.deepEqual(linhas, ["conv_mode_rejected_total 0"]);
  });

  it("a ajuda de cada metrica diz o que ela e, e nomeia o contador que deve ficar a zero", () => {
    const texto = m.exposicao();
    assert.match(texto, /^# HELP conv_mode_transitions_total .*§10\.2/m);
    assert.match(texto, /^# HELP conv_mode_rejected_total .*gatilho mal ligado/m);
    assert.match(texto, /^# HELP reply_suppressed_total .*sem_turno > 0 e defeito/m);
  });

  it("termina com uma linha nova, e so uma", () => {
    assert.ok(m.exposicao().endsWith("\n"));
    assert.ok(!m.exposicao().endsWith("\n\n"));
  });
});
