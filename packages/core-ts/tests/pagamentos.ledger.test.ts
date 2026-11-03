/**
 * A verificação diária da cadeia e a âncora externa (KAM-053, critério 6).
 *
 * O critério tem três metades, e duas delas medem-se contra a base de dados
 * (`db/tests_pagamentos/test_cadeia.py`): a fórmula do elo e a detecção de um
 * byte alterado. **A terceira é esta** — «a cabeça da cadeia é exportada
 * diariamente via `StorageProvider` (*fake* em teste)» —, e é de aplicação:
 * nenhum PostgreSQL escreve num balde.
 *
 * O que estes ensaios defendem, e que não é óbvio ao ler o módulo:
 *
 *     a âncora conta para a conformidade   um dia sem âncora é um dia em que a
 *                                          cadeia só se verifica contra ela
 *                                          própria
 *     a exportação corre mesmo com elos    deixá-la por fazer porque um elo de
 *     partidos                             ontem está partido piora o problema
 *     o JSON é canónico                    uma âncora é para **comparar** com a
 *                                          de ontem
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ALERTA_DA_CADEIA,
  ALERTA_DA_PROJECCAO,
  ALERTA_DE_LEITURA,
  PREFIXO_DA_ANCORA,
  type CabecaDaCadeia,
  type EloPartido,
  type EscritaDaAncora,
  type LeituraDoLedger,
  type ProjeccaoDivergente,
  chaveDaAncora,
  serializarAncora,
  verificarLedgerDiariamente,
} from "../src/pagamentos/index.ts";

const HASH_A = new Uint8Array(32).fill(0xaa);
const HASH_B = new Uint8Array(32).fill(0xbb);

const CABECAS: readonly CabecaDaCadeia[] = [
  {
    chargeId: "bbbbbbbb-0000-4000-8000-000000000002",
    tenantId: "9c3d1a7e-0000-4000-8000-000000000001",
    eventId: 7n,
    sequencia: 2,
    rowHash: HASH_B,
  },
  {
    chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
    tenantId: "9c3d1a7e-0000-4000-8000-000000000001",
    eventId: 3n,
    sequencia: 1,
    rowHash: HASH_A,
  },
];

/** Um armazenamento *fake* estreito: o que a porta do *job* pede, e nada mais. */
function armazenamentoFake(falhar = false) {
  const escritas: { chave: string; corpo: Uint8Array }[] = [];
  const armazenamento: EscritaDaAncora = {
    async put(chave, corpo) {
      if (falhar) throw new Error("balde indisponivel");
      escritas.push({ chave, corpo });
      return undefined;
    },
  };
  return { armazenamento, escritas };
}

function leitura(opcoes: {
  readonly elos?: readonly EloPartido[];
  readonly projeccoes?: readonly ProjeccaoDivergente[];
  readonly cabecas?: readonly CabecaDaCadeia[];
}): LeituraDoLedger {
  return {
    async elosPartidos() {
      return opcoes.elos ?? [];
    },
    async projeccoes() {
      return opcoes.projeccoes ?? [];
    },
    async cabecas() {
      return opcoes.cabecas ?? CABECAS;
    },
  };
}

const HOJE = () => new Date("2026-11-02T03:00:00.000Z");

describe("job da cadeia: o caminho conforme", () => {
  it("test_cadeia_intacta_e_ancora_escrita_da_conforme", async () => {
    const { armazenamento, escritas } = armazenamentoFake();
    const relatorio = await verificarLedgerDiariamente({
      leitura: leitura({}),
      armazenamento,
      hoje: HOJE,
    });

    assert.equal(relatorio.conforme, true);
    assert.deepEqual(relatorio.leiturasFalhadas, []);
    assert.equal(relatorio.cabecas, 2);
    assert.equal(relatorio.ancora, `${PREFIXO_DA_ANCORA}/2026-11-02.json`);
    assert.equal(escritas.length, 1);
  });

  it("test_a_chave_da_ancora_e_uma_por_dia_em_utc", () => {
    // UTC e não `Africa/Luanda` (dicionário §2): a âncora de um dia tem de ser a
    // mesma chave para quem a escreve e para quem a compara, e Luanda está a
    // UTC+1 — às 00:30 de Luanda, a data local já virou e a UTC não.
    assert.equal(
      chaveDaAncora(new Date("2026-11-02T23:59:59.000Z")),
      `${PREFIXO_DA_ANCORA}/2026-11-02.json`,
    );
    assert.equal(
      chaveDaAncora(new Date("2026-11-03T00:00:01.000Z")),
      `${PREFIXO_DA_ANCORA}/2026-11-03.json`,
    );
  });
});

describe("job da cadeia: a âncora conta para a conformidade", () => {
  it("test_sem_ancora_nao_e_conforme_mesmo_com_a_cadeia_intacta", async () => {
    // **É o ensaio mais importante deste ficheiro.** Uma cadeia de *hashes*
    // detecta adulteração de quem não a recalcula; quem tem o superutilizador
    // reescreve os elos seguintes e ela fica consistente. O que a torna uma
    // prova contra quem tem a base é a cabeça estar **fora do *host***. Um dia
    // sem âncora é um dia sem essa prova, e dizer «conforme» era mentir sobre o
    // que foi verificado.
    const { armazenamento } = armazenamentoFake(true);
    const relatorio = await verificarLedgerDiariamente({
      leitura: leitura({}),
      armazenamento,
      hoje: HOJE,
    });

    assert.equal(relatorio.elosPartidos.length, 0);
    assert.equal(relatorio.projeccoesDivergentes.length, 0);
    assert.equal(relatorio.ancora, null);
    assert.equal(relatorio.erroDaAncora, "balde indisponivel");
    assert.equal(relatorio.conforme, false);
  });

  it("test_a_ancora_escreve_se_mesmo_com_elos_partidos", async () => {
    // A exportação vem **antes** dos alertas, e corre haja o que houver: ela
    // protege os eventos de amanhã, e deixá-la por fazer porque um elo de ontem
    // está partido piora o problema em vez de o conter.
    const { armazenamento, escritas } = armazenamentoFake();
    const elos: EloPartido[] = [
      {
        chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
        eventId: 3n,
        sequencia: 1,
        falha: "row_hash nao corresponde aos campos canonicos",
      },
    ];
    const alertas: string[] = [];
    const relatorio = await verificarLedgerDiariamente({
      leitura: leitura({ elos }),
      armazenamento,
      hoje: HOJE,
      alertar: (alerta) => alertas.push(alerta),
    });

    assert.equal(escritas.length, 1, "a ancora escreve-se");
    assert.equal(relatorio.conforme, false);
    assert.deepEqual(alertas, [ALERTA_DA_CADEIA]);
  });

  it("test_uma_projeccao_divergente_alerta_e_nao_e_conforme", async () => {
    const { armazenamento } = armazenamentoFake();
    const alertas: string[] = [];
    const relatorio = await verificarLedgerDiariamente({
      leitura: leitura({
        projeccoes: [
          {
            chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
            projectado: "paga",
            reconstruido: "emitida",
          },
        ],
      }),
      armazenamento,
      hoje: HOJE,
      alertar: (alerta) => alertas.push(alerta),
    });

    assert.deepEqual(alertas, [ALERTA_DA_PROJECCAO]);
    assert.equal(relatorio.conforme, false);
  });

  it("test_uma_leitura_que_levanta_nao_aborta_o_job_nem_a_ancora", async () => {
    // **A correcção do achado 2 da revisão adversarial.**
    //
    // O `SQL_PROJECCOES_DIVERGENTES` chama o `rebuild_charge_state`, e essa
    // função **levanta** `data_corrupted` num ledger que não reproduz — que é
    // o alarme certo. Mas levantava para fora: uma cobrança corrompida abortava
    // a consulta inteira, o *job* lançava contra a sua própria docstring, e **a
    // âncora, que se escreve depois, nunca chegava a ser escrita**. Isto é, o
    // alarme de uma cadeia apagava a prova das outras.
    const { armazenamento, escritas } = armazenamentoFake();
    const alertas: string[] = [];
    const relatorio = await verificarLedgerDiariamente({
      leitura: {
        async elosPartidos() {
          return [];
        },
        async projeccoes(): Promise<readonly ProjeccaoDivergente[]> {
          throw new Error("data_corrupted: o evento 9 nao e transicao");
        },
        async cabecas() {
          return CABECAS;
        },
      },
      armazenamento,
      hoje: HOJE,
      alertar: (alerta) => alertas.push(alerta),
    });

    assert.equal(escritas.length, 1, "a ancora escreve-se mesmo assim");
    assert.equal(relatorio.ancora, `${PREFIXO_DA_ANCORA}/2026-11-02.json`);
    assert.deepEqual(
      relatorio.leiturasFalhadas.map((f) => f.leitura),
      ["projeccoes"],
    );
    assert.ok(alertas.includes(ALERTA_DE_LEITURA));
    // **Uma leitura que falhou não é uma verificação que passou.**
    assert.equal(relatorio.conforme, false);
  });

  it("test_uma_leitura_que_levanta_nao_apaga_as_outras", async () => {
    // A leitura dos elos corre e o seu resultado conta, mesmo com a das
    // projecções em baixo: o relatório diz as duas coisas em vez de uma.
    const { armazenamento } = armazenamentoFake();
    const relatorio = await verificarLedgerDiariamente({
      leitura: {
        async elosPartidos() {
          return [
            {
              chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
              eventId: 3n,
              sequencia: 1,
              falha: "row_hash nao corresponde aos campos canonicos",
            },
          ];
        },
        async projeccoes(): Promise<readonly ProjeccaoDivergente[]> {
          throw new Error("42501 permission denied");
        },
        async cabecas() {
          return CABECAS;
        },
      },
      armazenamento,
      hoje: HOJE,
    });
    assert.equal(relatorio.elosPartidos.length, 1);
    assert.equal(relatorio.leiturasFalhadas.length, 1);
    assert.equal(relatorio.cabecas, 2);
  });

  it("test_o_job_nao_lanca_e_devolve_o_relatorio", async () => {
    // Lançar perdia a parte do trabalho que correu bem, e quem chama é que
    // decide o código de saída. Um *job* nocturno que morre no primeiro elo
    // partido não exporta a âncora nem conta os restantes.
    const { armazenamento } = armazenamentoFake(true);
    const relatorio = await verificarLedgerDiariamente({
      leitura: leitura({
        elos: [
          {
            chargeId: "a",
            eventId: 1n,
            sequencia: 1,
            falha: "prev_hash nao e o row_hash do elo anterior",
          },
        ],
        projeccoes: [
          { chargeId: "a", projectado: "paga", reconstruido: "falhada" },
        ],
      }),
      armazenamento,
      hoje: HOJE,
    });
    assert.equal(relatorio.elosPartidos.length, 1);
    assert.equal(relatorio.projeccoesDivergentes.length, 1);
    assert.equal(relatorio.conforme, false);
  });
});

describe("job da cadeia: a âncora é canónica", () => {
  it("test_a_ancora_vem_ordenada_por_cobranca", () => {
    // Ordenada porque uma âncora é para **comparar** com a de ontem, e dois
    // ficheiros com as mesmas linhas por outra ordem não se comparam byte a
    // byte. As `CABECAS` deste ficheiro estão de propósito pela ordem errada.
    const texto = new TextDecoder().decode(serializarAncora(CABECAS));
    const anexo = JSON.parse(texto) as {
      versao: number;
      cabecas: { charge_id: string; row_hash: string; event_id: string }[];
    };
    assert.equal(anexo.versao, 1);
    assert.deepEqual(
      anexo.cabecas.map((c) => c.charge_id),
      [
        "aaaaaaaa-0000-4000-8000-000000000001",
        "bbbbbbbb-0000-4000-8000-000000000002",
      ],
    );
  });

  it("test_os_hashes_vem_em_hex_e_o_event_id_em_texto", () => {
    const anexo = JSON.parse(
      new TextDecoder().decode(serializarAncora(CABECAS)),
    ) as { cabecas: { row_hash: string; event_id: string }[] };

    // Hex e não base64: é o que o `encode(…, 'hex')` da base devolve, e uma
    // âncora que se compara à mão vale mais do que uma mais curta.
    assert.equal(anexo.cabecas[0]?.row_hash, "aa".repeat(32));
    assert.equal(anexo.cabecas[1]?.row_hash, "bb".repeat(32));
    // `event_id` em texto porque é `bigint`: um `JSON.stringify` de `BigInt`
    // lança, e convertê-lo a `number` perdia precisão acima de 2^53 — que é
    // exactamente o que um `GENERATED ALWAYS AS IDENTITY` de um ledger acaba
    // por atingir.
    assert.equal(anexo.cabecas[0]?.event_id, "3");
    assert.equal(typeof anexo.cabecas[0]?.event_id, "string");
  });

  it("test_a_mesma_entrada_da_o_mesmo_byte", () => {
    const primeiro = serializarAncora(CABECAS);
    const segundo = serializarAncora([...CABECAS].reverse());
    assert.deepEqual(primeiro, segundo, "a ordem da entrada nao muda a saida");
  });

  it("test_zero_cabecas_da_uma_ancora_vazia_e_valida", () => {
    // Uma base sem eventos ainda escreve a âncora do dia. O contrário fazia um
    // dia sem pagamentos parecer um dia sem verificação.
    const anexo = JSON.parse(
      new TextDecoder().decode(serializarAncora([])),
    ) as { versao: number; cabecas: unknown[] };
    assert.deepEqual(anexo, { versao: 1, cabecas: [] });
  });
});
