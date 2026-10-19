/**
 * As métricas da entrada de canal (KAM-013, DoD «Custo e observabilidade»).
 *
 * O que estes testes prendem: os cinco nomes, que nenhum leva etiqueta, que um
 * nome fora das listas fechadas **levanta** em vez de criar uma série nova, e
 * que a exposição não se parte com um valor que não é um número.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CONTADORES,
  GAUGES,
  METRICA_ASSINATURA_FALHOU,
  METRICA_DESCARTADOS,
  METRICA_ENFILEIRAMENTO_MS,
  METRICA_PEDIDOS,
  METRICA_PROFUNDIDADE,
  MetricaDesconhecidaError,
  MetricasDaEntrada,
} from "../src/entrada/metricas.ts";

describe("metricas da entrada", () => {
  it("os cinco nomes sao os do dicionario §3.12", () => {
    assert.deepEqual([...CONTADORES], [
      "gwy_requests_total",
      "gwy_sig_fail",
      "gwy_shed_total",
    ]);
    assert.deepEqual([...GAUGES], ["gwy_enqueue_ms", "inbound_queue_depth"]);
  });

  it("conta e le", () => {
    const m = new MetricasDaEntrada();
    m.contar(METRICA_PEDIDOS);
    m.contar(METRICA_PEDIDOS, 4);
    m.contar(METRICA_ASSINATURA_FALHOU);
    assert.deepEqual(m.ler(), { gwy_requests_total: 5, gwy_sig_fail: 1 });
  });

  it("mede gauges", () => {
    const m = new MetricasDaEntrada();
    m.medir(METRICA_ENFILEIRAMENTO_MS, 12);
    m.medir(METRICA_ENFILEIRAMENTO_MS, 7);
    m.medir(METRICA_PROFUNDIDADE, 0);
    assert.deepEqual(m.ler(), { gwy_enqueue_ms: 7, inbound_queue_depth: 0 });
  });

  it("um nome fora das listas fechadas levanta", () => {
    const m = new MetricasDaEntrada();
    // O `as never` é o que um `as any` em JavaScript sem tipos faria chegar
    // aqui: o tipo fecha a lista em compilação, e isto fecha-a em execução.
    assert.throws(
      () => m.contar("gwy_qualquer_coisa" as never),
      MetricaDesconhecidaError,
    );
    assert.throws(() => m.medir("inbound_fila" as never, 1), MetricaDesconhecidaError);
    // E um gauge não se conta nem um contador se mede.
    assert.throws(() => m.contar(METRICA_PROFUNDIDADE as never), MetricaDesconhecidaError);
    assert.throws(() => m.medir(METRICA_PEDIDOS as never, 1), MetricaDesconhecidaError);
  });

  it("um valor que nao e numero finito nao substitui o anterior", () => {
    // Um `NaN` no formato de exposição faz o Prometheus descartar a recolha
    // **toda**, e perderiam-se as outras quatro por causa desta.
    const m = new MetricasDaEntrada();
    m.medir(METRICA_PROFUNDIDADE, 42);
    m.medir(METRICA_PROFUNDIDADE, Number.NaN);
    m.medir(METRICA_PROFUNDIDADE, Number.POSITIVE_INFINITY);
    assert.equal(m.ler().inbound_queue_depth, 42);
  });
});

describe("exposicao das metricas da entrada", () => {
  it("as cinco aparecem sempre, com HELP e TYPE", () => {
    const texto = new MetricasDaEntrada().exposicao();
    for (const nome of [...CONTADORES, ...GAUGES]) {
      assert.match(texto, new RegExp(`^# HELP ${nome} `, "m"), nome);
      assert.match(texto, new RegExp(`^# TYPE ${nome} (counter|gauge)$`, "m"), nome);
    }
  });

  it("os contadores comecam a zero e os gauges a -1", () => {
    // Zero e «não medido» são coisas diferentes para a profundidade de uma
    // fila: zero é uma resposta legítima, e `-1` diz «ainda não se leu».
    const texto = new MetricasDaEntrada().exposicao();
    assert.match(texto, /^gwy_requests_total 0$/m);
    assert.match(texto, /^gwy_sig_fail 0$/m);
    assert.match(texto, /^gwy_shed_total 0$/m);
    assert.match(texto, /^gwy_enqueue_ms -1$/m);
    assert.match(texto, /^inbound_queue_depth -1$/m);
  });

  it("nenhuma linha leva etiquetas", () => {
    // `docs/seguranca/ameacas_stride.md`, OBS-I: identificadores em etiquetas
    // explodem a cardinalidade e re-identificam. Aqui não há etiqueta nenhuma,
    // e é por isso que não há gramática a impor.
    const m = new MetricasDaEntrada();
    m.contar(METRICA_PEDIDOS, 3);
    m.contar(METRICA_DESCARTADOS);
    m.medir(METRICA_PROFUNDIDADE, 11);
    for (const linha of m.exposicao().trim().split("\n")) {
      if (linha.startsWith("#")) continue;
      assert.equal(linha.includes("{"), false, linha);
    }
  });

  it("acaba com um salto de linha", () => {
    assert.ok(new MetricasDaEntrada().exposicao().endsWith("\n"));
  });

  it("repor esquece tudo", () => {
    const m = new MetricasDaEntrada();
    m.contar(METRICA_PEDIDOS);
    m.medir(METRICA_PROFUNDIDADE, 9);
    m.repor();
    assert.deepEqual(m.ler(), {});
  });
});
