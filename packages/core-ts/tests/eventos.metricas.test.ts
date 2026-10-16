/**
 * As três métricas do critério 8, e a regra que as protege (KAM-005, ADR-018).
 *
 * A regra é `OBS-I` de `docs/seguranca/ameacas_stride.md`: nenhum identificador
 * em etiqueta de métrica. O *lint* de cardinalidade é o KAM-080 e não existe;
 * aqui a defesa é a lista fechada de sufixos, e é isto que a prova.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DESFECHOS,
  EtiquetaInvalidaError,
  METRICA_ATRASO,
  METRICA_ERROS,
  METRICA_LIDER,
  METRICA_PUBLICADOS,
  MOTIVOS,
  Metricas,
} from "../src/eventos/index.ts";

describe("os nomes sao os do criterio 8", () => {
  it("evt_outbox_lag_seconds, evt_publish_total, evt_publish_errors_total", () => {
    assert.equal(METRICA_ATRASO, "evt_outbox_lag_seconds");
    assert.equal(METRICA_PUBLICADOS, "evt_publish_total");
    assert.equal(METRICA_ERROS, "evt_publish_errors_total");
  });
});

describe("contadores e gauges", () => {
  it("contar soma", () => {
    const m = new Metricas();
    m.contar(METRICA_PUBLICADOS, "entregue");
    m.contar(METRICA_PUBLICADOS, "entregue", 4);
    assert.equal(m.ler()[`${METRICA_PUBLICADOS}:entregue`], 5);
  });

  it("medir fixa", () => {
    const m = new Metricas();
    m.medir(METRICA_ATRASO, 3);
    m.medir(METRICA_ATRASO, 1.5);
    assert.equal(m.ler()[METRICA_ATRASO], 1.5);
  });

  it("repor limpa os dois", () => {
    const m = new Metricas();
    m.contar(METRICA_ERROS, "sem_conversor");
    m.medir(METRICA_ATRASO, 9);
    m.repor();
    assert.deepEqual(m.ler(), {});
  });
});

describe("nenhum identificador em etiqueta (OBS-I)", () => {
  it("um sufixo fora da lista fechada lanca", () => {
    const m = new Metricas();
    for (const proibido of [
      "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60",
      "agr",
      "order",
    ]) {
      assert.throws(
        () => m.contar(METRICA_PUBLICADOS, proibido),
        EtiquetaInvalidaError,
      );
    }
  });

  it("os sufixos de erro sao os motivos, e so esses", () => {
    const m = new Metricas();
    for (const motivo of MOTIVOS) m.contar(METRICA_ERROS, motivo);
    assert.throws(() => m.contar(METRICA_ERROS, "entregue"), EtiquetaInvalidaError);
    assert.equal(Object.keys(m.ler()).length, MOTIVOS.length);
  });

  it("os sufixos de publicacao sao os desfechos, e so esses", () => {
    const m = new Metricas();
    for (const desfecho of DESFECHOS) m.contar(METRICA_PUBLICADOS, desfecho);
    assert.throws(
      () => m.contar(METRICA_PUBLICADOS, "sem_conversor"),
      EtiquetaInvalidaError,
    );
  });
});

describe("exposicao no formato do Prometheus", () => {
  it("declara as quatro metricas com HELP e TYPE", () => {
    const texto = new Metricas().exposicao();
    for (const nome of [
      METRICA_ATRASO,
      METRICA_PUBLICADOS,
      METRICA_ERROS,
      METRICA_LIDER,
    ]) {
      assert.match(texto, new RegExp(`^# HELP ${nome} `, "m"));
      assert.match(texto, new RegExp(`^# TYPE ${nome} (counter|gauge)$`, "m"));
    }
  });

  it("os dois contadores aparecem a zero antes do primeiro evento", () => {
    const texto = new Metricas().exposicao();
    assert.match(texto, new RegExp(`^${METRICA_PUBLICADOS} 0$`, "m"));
    assert.match(texto, new RegExp(`^${METRICA_ERROS} 0$`, "m"));
  });

  it("o sufixo passa a etiqueta `desfecho` ou `motivo`", () => {
    const m = new Metricas();
    m.contar(METRICA_PUBLICADOS, "entregue", 3);
    m.contar(METRICA_ERROS, "sem_conversor");
    m.medir(METRICA_ATRASO, 0.5);
    const texto = m.exposicao();
    assert.match(texto, /^evt_publish_total\{desfecho="entregue"\} 3$/m);
    assert.match(texto, /^evt_publish_errors_total\{motivo="sem_conversor"\} 1$/m);
    assert.match(texto, /^evt_outbox_lag_seconds 0\.5$/m);
  });

  it("termina com uma nova linha, como o formato exige", () => {
    assert.ok(new Metricas().exposicao().endsWith("\n"));
  });
});
