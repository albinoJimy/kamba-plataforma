/**
 * A verificação de arranque do consumidor de pagamentos (KAM-055, critério 4).
 *
 * «O consumidor está registado com `exige_ordem=true`» tem **três** metades, e
 * nenhuma é uma linha escrita à mão num `INSERT` de migração:
 *
 * * do lado da base, a restrição `evt_subscricoes_payment_exige_ordem` da
 *   revisão `0005` **recusa** a configuração errada, e isso corre no *gate* 8;
 * * a invariante global (`exigirOrdemNosPagamentos`), que é a guarda que o
 *   KAM-006 escreveu — e aquele bloco fechou o seu critério 7 com estas duas,
 *   com a razão «uma guarda que depende da outra não é uma guarda»;
 * * a subscrição **deste** consumidor (`exigirSubscricaoComOrdem`), que é nova:
 *   a global passa com zero subscrições, pelo que um processo cuja linha
 *   ninguém inseriu ficava vivo, verde e **surdo**, porque o publicador só
 *   entrega a uma subscrição activa.
 *
 * Tudo aqui é exercitado **sem levantar o processo**, pela razão que o
 * `worker-canal` escreveu para a guarda dele: um teste que levantasse o
 * processo inteiro para o ver falhar provava menos e demorava mais. O ponto de
 * entrada — `./payments/consumidor.ts` — não tem decisões e está nos
 * `excluidos` do `ci/thresholds.yaml`, com a razão escrita lá.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { CAUSAS_QUE_PAGAM } from "../src/orders/contrato.ts";
import {
  ArranqueSemOrdemError,
  PORTA_POR_OMISSAO,
  PortaInvalidaError,
  SQL_A_MINHA_SUBSCRICAO,
  SubscricaoEmFaltaError,
  TABELA_DO_ESTADO,
  VARIAVEL_DA_PORTA,
  VariavelEmFaltaError,
  criarApp,
  exigir,
  exigirOrdemNosPagamentos,
  exigirSubscricaoComOrdem,
  porta,
} from "../src/payments/arranque.ts";
import { LAG } from "../src/payments/metricas.ts";

const CONSUMER = "com_pagamentos";

/** Base falsa que devolve as linhas que lhe derem, e guarda o que recebeu. */
function baseFalsa(linhas: Record<string, unknown>[]) {
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  return {
    vistas,
    async query(sql: string, valores: readonly unknown[] = []) {
      vistas.push({ sql, valores });
      return { rows: linhas };
    },
  };
}

function subscricao(parciais: Record<string, unknown> = {}) {
  return { tipo: "payment.confirmed", exige_ordem: true, activo: true, ...parciais };
}

/** As duas linhas que um arranque bom tem. */
function asDuas(parciais: Record<string, unknown> = {}) {
  return CAUSAS_QUE_PAGAM.map((tipo) => subscricao({ tipo, ...parciais }));
}

test("a máquina de estados lê a orders_mirror, e não uma tabela inventada", () => {
  // O nome entra por argumento na `MaquinaNaBase`, e é este o que o consumidor
  // dá. Um teste sobre uma constante parece pouco, e é o que prende a réplica
  // que o consumidor consulta ao espelho da encomenda do §5.4.
  assert.equal(TABELA_DO_ESTADO, "orders_mirror");
});

test("o arranque passa com as duas subscrições activas e com ordem", async () => {
  const bd = baseFalsa(asDuas());
  await exigirSubscricaoComOrdem(bd, CONSUMER, CAUSAS_QUE_PAGAM);
  assert.equal(bd.vistas.length, 1, "uma leitura e não uma por tipo");
  assert.equal(bd.vistas[0]?.sql, SQL_A_MINHA_SUBSCRICAO);
  assert.deepEqual(bd.vistas[0]?.valores, [CONSUMER, [...CAUSAS_QUE_PAGAM]]);
});

test("sem linha nenhuma, o arranque é recusado", async () => {
  await assert.rejects(
    () => exigirSubscricaoComOrdem(baseFalsa([]), CONSUMER, CAUSAS_QUE_PAGAM),
    (erro: unknown) => {
      assert.ok(erro instanceof SubscricaoEmFaltaError);
      assert.match(erro.message, /não tem linha para payment\.confirmed/);
      return true;
    },
  );
});

test("com uma das duas em falta, o arranque é recusado", async () => {
  // **O caso que uma leitura por tipo esconderia.** Subscrever o
  // `payment.confirmed` e esquecer o `payment.manual_confirmed` deixava o
  // caminho do `ManualProvider` — que é o do Piloto — sem consumidor, e o
  // processo arrancava a servir metade.
  const bd = baseFalsa([subscricao({ tipo: "payment.confirmed" })]);
  await assert.rejects(
    () => exigirSubscricaoComOrdem(bd, CONSUMER, CAUSAS_QUE_PAGAM),
    (erro: unknown) => {
      assert.ok(erro instanceof SubscricaoEmFaltaError);
      assert.match(erro.message, /não tem linha para payment\.manual_confirmed/);
      return true;
    },
  );
});

test("com a subscrição inactiva, o arranque é recusado", async () => {
  await assert.rejects(
    () =>
      exigirSubscricaoComOrdem(
        baseFalsa(asDuas({ activo: false })),
        CONSUMER,
        CAUSAS_QUE_PAGAM,
      ),
    (erro: unknown) => {
      assert.ok(erro instanceof SubscricaoEmFaltaError);
      assert.match(erro.message, /está inactiva/);
      return true;
    },
  );
});

test("com exige_ordem falso, o arranque é recusado e nomeia a restrição", async () => {
  // Este caso a base **já recusa** (a `evt_subscricoes_payment_exige_ordem` da
  // revisão `0005`), pelo que encontrá-lo em execução é sinal de que a
  // restrição caiu. A mensagem di-lo, para que quem a lê saiba onde procurar —
  // e é a razão de esta verificação não ser redundante com a da base.
  await assert.rejects(
    () =>
      exigirSubscricaoComOrdem(
        baseFalsa(asDuas({ exige_ordem: false })),
        CONSUMER,
        CAUSAS_QUE_PAGAM,
      ),
    (erro: unknown) => {
      assert.ok(erro instanceof SubscricaoEmFaltaError);
      assert.match(erro.message, /evt_subscricoes_payment_exige_ordem/);
      return true;
    },
  );
});

test("a guarda global passa sem subscrições sem ordem, e recusa com uma", async () => {
  // A sonda positiva primeiro: sem ela, o caso de baixo podia estar a passar
  // porque a consulta não devolve nada nunca.
  await exigirOrdemNosPagamentos(baseFalsa([]));
  await assert.rejects(
    () =>
      exigirOrdemNosPagamentos(
        baseFalsa([{ consumer: "outro", tipo: "payment.confirmed" }]),
      ),
    (erro: unknown) => {
      assert.ok(erro instanceof ArranqueSemOrdemError);
      assert.deepEqual(erro.subscricoes, ["outro/payment.confirmed"]);
      return true;
    },
  );
});

test("a guarda global e a desta subscrição não se substituem", async () => {
  // Zero subscrições: a global diz «tudo bem» e a desta diz «não há». É a
  // propriedade que justifica as duas, escrita como ensaio e não como nota.
  await exigirOrdemNosPagamentos(baseFalsa([]));
  await assert.rejects(
    () => exigirSubscricaoComOrdem(baseFalsa([]), CONSUMER, CAUSAS_QUE_PAGAM),
    SubscricaoEmFaltaError,
  );
});

// ------------------------------------------------- o ambiente do processo

test("uma variável ausente, vazia ou só com espaços é recusada", () => {
  assert.equal(exigir("X", { X: "valor" }), "valor");
  for (const ambiente of [{}, { X: "" }, { X: "   " }]) {
    assert.throws(() => exigir("X", ambiente), VariavelEmFaltaError);
  }
});

test("a porta vem do ambiente, e o que não é porta é recusado", () => {
  assert.equal(porta({}), PORTA_POR_OMISSAO);
  assert.equal(porta({ [VARIAVEL_DA_PORTA]: "" }), PORTA_POR_OMISSAO);
  assert.equal(porta({ [VARIAVEL_DA_PORTA]: "3100" }), 3100);
  // **Recusa em vez de cair na omissão.** Um `3O13` com a letra O é um erro de
  // quem configurou, e servir na 3013 escondia-o: o colector raspava a porta
  // errada e ninguém via.
  for (const bruto of ["3O13", "0", "-1", "65536", "3.5", "muitos"]) {
    assert.throws(
      () => porta({ [VARIAVEL_DA_PORTA]: bruto }),
      PortaInvalidaError,
      `${bruto} devia ser recusado`,
    );
  }
});

test("o /healthz e o /metrics respondem, e o lag sai na exposição", async () => {
  const app = criarApp();

  const saude = await app.request("/healthz");
  assert.equal(saude.status, 200);
  const corpo = (await saude.json()) as Record<string, unknown>;
  assert.equal(corpo["service"], "com");

  LAG.observar(2);
  const metricas = await app.request("/metrics");
  assert.equal(metricas.status, 200);
  assert.match(
    metricas.headers.get("content-type") ?? "",
    /text\/plain; version=0\.0\.4/,
  );
  const texto = await metricas.text();
  // As duas exposições concatenadas: a do consumo (biblioteca) e a deste
  // ticket. Sem a primeira, o `/metrics` deste processo não dizia nada sobre
  // os desfechos do consumo; sem a segunda, não dizia nada sobre o atraso.
  assert.match(texto, /evt_consumed_total/);
  assert.match(texto, /com_payment_to_paid_seconds_bucket\{le="5"\}/);
});
