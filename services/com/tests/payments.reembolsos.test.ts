/**
 * O consumidor do PAY que abre a `refund_cases` (KAM-197).
 *
 * ## O duplo da base **lê a instrução**, e isso não é zelo
 *
 * É a lição do KAM-179 que o `payments.efeito.test.ts` já escreve: um duplo que
 * decida pela posição dos argumentos fica verde com a instrução errada. Aqui a
 * coisa que importa é que a abertura vá **pela porta** — nenhum papel tem
 * `INSERT` na `refund_cases` — e que o `id` do envelope vá para o **sexto**
 * parâmetro, que é o da idempotência. O duplo lê o texto, recusa um `INSERT` e
 * recusa qualquer instrução que toque no *ledger*.
 *
 * ## E não há PostgreSQL aqui
 *
 * As barreiras da porta (motivo, encomenda no tenant, moeda, repetição) e o
 * «sem linha nova no ledger» medem-se contra a base em
 * `db/tests_pagamentos/test_reembolsos_do_pay.py`, com o texto deste módulo.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  SQL_DEFINIR_TENANT,
  SQL_MARCAR_CONSUMIDO,
  consumir,
} from "@kamba/core-ts/eventos";
import type { Envelope } from "@kamba/core-ts/eventos";

import {
  PedidoDeReembolsoRecusadoError,
  SQL_ABRIR_CASO_DE_REEMBOLSO,
  TIPO_DO_PEDIDO,
  efeitoDeReembolso,
  valorDoPedido,
} from "../src/payments/reembolsos.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const ORDEM = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50";
const EVENTO = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44";
const CONSUMER = "pay_reembolsos";

function pedido(
  payload: Record<string, unknown> = {},
  parciais: Partial<Envelope> = {},
): Envelope {
  return {
    id: EVENTO,
    tipo: TIPO_DO_PEDIDO,
    versao: 1,
    tenant_id: TENANT,
    ocorrido_em: "2026-11-13T10:00:00.000Z",
    registado_em: "2026-11-13T10:00:00.100Z",
    produtor: "com@0.1.0",
    agregado: { tipo: "order", id: ORDEM, seq: 5 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P0",
    finalidades: ["transacao"],
    payload: {
      order_id: ORDEM,
      motivo: "pagamento_duplicado",
      valor_minor: 24_500_000,
      currency: "AOA",
      ...payload,
    },
    ...parciais,
  } as Envelope;
}

/**
 * A base falsa. Responde à porta **só** se o texto for a chamada da função com
 * os seis marcadores, guarda o que lhe chega, e simula o recibo de consumo
 * (`events_consumed`) para o ensaio das dez entregas.
 */
function baseFalsa() {
  const aberturas: (readonly unknown[])[] = [];
  const instrucoes: string[] = [];
  const consumidos = new Set<string>();
  const cliente = {
    async query(sql: string, valores: readonly unknown[] = []) {
      instrucoes.push(sql);
      assert.ok(
        !/payment_events|append_payment_event|payment_charges/.test(sql),
        `o consumidor de reembolsos tocou no ledger ou na cobranca: ${sql}`,
      );
      assert.ok(!/\bINSERT\s+INTO\s+platform\.refund_cases/i.test(sql),
        "a refund_cases nao tem INSERT para papel nenhum: abre-se pela porta");
      if (/^\s*(BEGIN|COMMIT|ROLLBACK)\b/i.test(sql)) {
        return { rows: [], rowCount: null };
      }
      if (sql === SQL_DEFINIR_TENANT) return { rows: [], rowCount: 1 };
      if (sql === SQL_MARCAR_CONSUMIDO) {
        const chave = `${String(valores[0])}/${String(valores[1])}`;
        if (consumidos.has(chave)) return { rows: [], rowCount: 0 };
        consumidos.add(chave);
        return { rows: [], rowCount: 1 };
      }
      if (/platform\.abrir_caso_de_reembolso\(/.test(sql)) {
        assert.match(
          sql,
          /abrir_caso_de_reembolso\(\$1, \$2, \$3, \$4, \$5, \$6\)/,
          "os seis parametros da porta, pela ordem da assinatura",
        );
        aberturas.push([...valores]);
        return { rows: [{ caso: "caso-1" }], rowCount: 1 };
      }
      throw new Error(`instrucao nao reconhecida pelo duplo: ${sql}`);
    },
  };
  return { cliente, aberturas, instrucoes };
}

test("abre o caso pela porta, com o id do envelope no sexto parametro", async () => {
  const base = baseFalsa();
  await efeitoDeReembolso()(base.cliente, pedido());
  assert.deepEqual(base.aberturas, [
    [TENANT, ORDEM, "pagamento_duplicado", 24_500_000, "AOA", EVENTO],
  ]);
});

test("os quatro motivos chegam a porta como vieram", async () => {
  // A porta e que fecha o dominio (lista fechada). O efeito nao traduz nem
  // escolhe: um mapa aqui era uma segunda fonte para o mesmo dominio.
  for (const motivo of [
    "pagamento_apos_cancelamento",
    "pagamento_duplicado",
    "disputa",
    "entrega_falhada",
  ]) {
    const base = baseFalsa();
    await efeitoDeReembolso()(base.cliente, pedido({ motivo }));
    assert.equal(base.aberturas[0]?.[2], motivo);
  }
});

test("a v2 do contrato tambem abre: o payload e o mesmo", async () => {
  const base = baseFalsa();
  await efeitoDeReembolso()(base.cliente, pedido({}, { versao: 2 }));
  assert.equal(base.aberturas.length, 1);
});

test("duplicados x10 pelo consumir: um caso", async () => {
  // A primeira camada da idempotencia, a do recibo. A segunda (o indice unico
  // da porta) mede-se contra a base.
  const base = baseFalsa();
  const desfechos: string[] = [];
  for (let i = 0; i < 10; i += 1) {
    const { desfecho } = await consumir(
      {
        bd: base.cliente,
        consumer: CONSUMER,
        envelope: pedido(),
        exigeOrdem: false,
      },
      efeitoDeReembolso(),
    );
    desfechos.push(desfecho);
  }
  assert.equal(base.aberturas.length, 1);
  assert.deepEqual(desfechos, ["aplicado", ...Array(9).fill("duplicado")]);
});

test("outro tipo e recusado, e nao abre caso", async () => {
  const base = baseFalsa();
  await assert.rejects(
    efeitoDeReembolso()(base.cliente, pedido({}, { tipo: "order.exception" })),
    PedidoDeReembolsoRecusadoError,
  );
  assert.equal(base.aberturas.length, 0);
});

test("um payload fora do contrato e recusado antes da porta", async () => {
  const base = baseFalsa();
  await assert.rejects(
    efeitoDeReembolso()(base.cliente, pedido({ charge_id: "x" })),
    /charge_id/,
  );
  assert.equal(base.aberturas.length, 0);
});

test("um payload que fala de outra encomenda e recusado", async () => {
  // A ordem e a idempotencia do envelope sao do agregado. Abrir o caso na
  // encomenda do payload era abrir um caso que nenhum agregado ordenou.
  const base = baseFalsa();
  await assert.rejects(
    efeitoDeReembolso()(
      base.cliente,
      pedido({ order_id: "11111111-1111-4111-8111-111111111111" }),
    ),
    PedidoDeReembolsoRecusadoError,
  );
  await assert.rejects(
    efeitoDeReembolso()(
      base.cliente,
      pedido({}, { agregado: { tipo: "payment_charge", id: ORDEM, seq: 1 } }),
    ),
    PedidoDeReembolsoRecusadoError,
  );
  assert.equal(base.aberturas.length, 0);
});

test("o valor tem de ser um inteiro de unidade menor", () => {
  for (const mau of [1.5, -1, "100", Number.MAX_SAFE_INTEGER + 2, null]) {
    assert.throws(
      () => valorDoPedido(pedido({ valor_minor: mau })),
      PedidoDeReembolsoRecusadoError,
      String(mau),
    );
  }
  // O zero passa aqui: quem o recusa e o `refund_cases_valor_ck` da base.
  assert.equal(valorDoPedido(pedido({ valor_minor: 0 })), 0);
  assert.equal(valorDoPedido(pedido({ valor_minor: 7 })), 7);
});

test("a chamada e uma funcao e nao um INSERT", () => {
  assert.match(SQL_ABRIR_CASO_DE_REEMBOLSO, /platform\.abrir_caso_de_reembolso\(/);
  assert.ok(!/\bINSERT\b/i.test(SQL_ABRIR_CASO_DE_REEMBOLSO));
});
