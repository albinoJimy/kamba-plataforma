/**
 * As métricas do CHR (KAM-014, DoD «Custo e observabilidade»).
 *
 * O que aqui se prova é o que a revisão adversarial do KAM-013 ensinou a provar
 * sobre métricas: que as listas são **fechadas** (um identificador não entra em
 * etiqueta nenhuma), que a exposição mostra as quatro mesmo sem dados, e que o
 * `-1` de um *gauge* não se confunde com zero.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  CONTADORES,
  DESFECHOS,
  GAUGES,
  METRICA_ACERTOS,
  METRICA_DURACAO,
  METRICA_EM_QUARENTENA,
  METRICA_RESOLUCOES,
  MOTIVOS_DO_CHR,
  MetricaDesconhecidaError,
  MetricasDoChr,
  SufixoInvalidoError,
} from "../src/chr/index.ts";
import { MOTIVOS } from "../src/entrada/index.ts";

describe("os nomes", () => {
  it("as quatro do DoD e da emenda 1.20, e nenhuma mais", () => {
    assert.deepEqual([...CONTADORES, ...GAUGES].sort(), [
      "chr_cache_hit_ratio",
      "chr_resolve_ms",
      "chr_resolve_total",
      "chr_unrouted_total",
    ]);
  });

  it("os motivos do CHR sao um subconjunto do dominio da coluna", () => {
    // Se divergirem, o CHR escreve um `motivo` que o `CHECK` da `0008` recusa,
    // e a quarentena falha **na insercao** — isto e, o evento nao deixa linha
    // nenhuma. A suite `db/tests_chr` prende as duas listas ao PostgreSQL.
    for (const motivo of MOTIVOS_DO_CHR) {
      assert.ok((MOTIVOS as readonly string[]).includes(motivo), motivo);
    }
  });

  it("os cinco desfechos sao os da emenda 1.20", () => {
    assert.deepEqual([...DESFECHOS], [
      "encaminhado",
      "entregue_ao_dono",
      "em_quarentena",
      "fluxo_b_recusado",
      "estado_recusou",
    ]);
  });
});

describe("MetricasDoChr", () => {
  let m: MetricasDoChr;
  beforeEach(() => {
    m = new MetricasDoChr();
  });

  it("um nome que nao esta na lista lanca", () => {
    assert.throws(() => m.contar("chr_qualquer_coisa"), MetricaDesconhecidaError);
    assert.throws(() => m.contar(METRICA_DURACAO), MetricaDesconhecidaError);
  });

  it("um sufixo fora da lista fechada lanca, e a mensagem diz porque", () => {
    assert.throws(
      () => m.contar(METRICA_RESOLUCOES, "pnid-12345"),
      (erro: unknown) => {
        assert.ok(erro instanceof SufixoInvalidoError);
        assert.match(erro.message, /nao entram em metricas/);
        return true;
      },
    );
    assert.throws(
      () => m.contar(METRICA_EM_QUARENTENA, "json_invalido"),
      SufixoInvalidoError,
      "um motivo do KAM-013 nao e um motivo do CHR",
    );
  });

  it("cada desfecho e cada motivo sao aceites", () => {
    for (const desfecho of DESFECHOS) m.contar(METRICA_RESOLUCOES, desfecho);
    for (const motivo of MOTIVOS_DO_CHR) m.contar(METRICA_EM_QUARENTENA, motivo);
    const lido = m.ler();
    assert.equal(lido[`${METRICA_RESOLUCOES}:encaminhado`], 1);
    assert.equal(lido[`${METRICA_EM_QUARENTENA}:canal_desconhecido`], 1);
  });

  it("o racio e acertos sobre total, e e a classe que o calcula", () => {
    // O racio vive dentro da classe e nao em quem chama: um *gauge* que dois
    // sitios escrevem com contas diferentes e a licao do `gwy_enqueue_ms`.
    m.resolucao(3, false);
    assert.equal(m.ler()[METRICA_ACERTOS], 0);
    m.resolucao(1, true);
    assert.equal(m.ler()[METRICA_ACERTOS], 0.5);
    m.resolucao(1, true);
    assert.equal(m.ler()[METRICA_ACERTOS], 2 / 3);
    assert.equal(m.ler()[METRICA_DURACAO], 1);
  });

  it("um valor nao finito nao substitui o anterior", () => {
    // Um `NaN` no formato de exposicao faz o Prometheus descartar a recolha
    // **toda**, e perdiam-se as outras tres por causa desta.
    m.medir(METRICA_DURACAO, 7);
    m.medir(METRICA_DURACAO, Number.NaN);
    m.medir(METRICA_DURACAO, Number.POSITIVE_INFINITY);
    assert.equal(m.ler()[METRICA_DURACAO], 7);
  });

  it("a exposicao mostra as quatro, com os gauges a -1 e os contadores a 0", () => {
    const linhas = m.exposicao().trimEnd().split("\n");
    assert.deepEqual(
      linhas.filter((l) => !l.startsWith("#")),
      [
        "chr_resolve_total 0",
        "chr_unrouted_total 0",
        "chr_resolve_ms -1",
        "chr_cache_hit_ratio -1",
      ],
    );
    // O `-1` diz «ainda nao houve resolucao nenhuma» sem se confundir com zero,
    // que para um racio de acertos e uma resposta legitima e muito diferente.
    m.resolucao(5, false);
    assert.ok(m.exposicao().includes("chr_cache_hit_ratio 0"));
  });

  it("a exposicao tem HELP e TYPE para as quatro", () => {
    const texto = m.exposicao();
    for (const nome of [...CONTADORES, ...GAUGES]) {
      assert.ok(texto.includes(`# HELP ${nome} `), nome);
      assert.ok(texto.includes(`# TYPE ${nome} `), nome);
    }
  });

  it("com etiquetas, cada serie sai com a sua, por ordem", () => {
    m.contar(METRICA_RESOLUCOES, "encaminhado", 2);
    m.contar(METRICA_RESOLUCOES, "fluxo_b_recusado");
    m.contar(METRICA_EM_QUARENTENA, "canal_desconhecido", 3);
    const texto = m.exposicao();
    assert.ok(texto.includes('chr_resolve_total{desfecho="encaminhado"} 2'));
    assert.ok(texto.includes('chr_resolve_total{desfecho="fluxo_b_recusado"} 1'));
    assert.ok(texto.includes('chr_unrouted_total{motivo="canal_desconhecido"} 3'));
  });

  it("nenhuma etiqueta e um identificador, e isso e a lista fechada", () => {
    // `docs/seguranca/ameacas_stride.md`, OBS-I. As duas listas tem cinco e
    // dois valores e nao crescem com o trafego.
    assert.equal(DESFECHOS.length, 5);
    assert.equal(MOTIVOS_DO_CHR.length, 2);
    for (const valor of [...DESFECHOS, ...MOTIVOS_DO_CHR]) {
      assert.match(valor, /^[a-z][a-z0-9_]*$/);
    }
  });

  it("`repor` esvazia tambem os contadores do racio", () => {
    m.resolucao(9, true);
    m.repor();
    assert.deepEqual(m.ler(), {});
    m.resolucao(1, false);
    assert.equal(m.ler()[METRICA_ACERTOS], 0);
  });
});
