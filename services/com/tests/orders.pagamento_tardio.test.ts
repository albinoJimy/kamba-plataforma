/**
 * As quatro regras do pagamento fora do caminho normal, e o reembolso (KAM-050).
 *
 * São os «Testes Requeridos» do bloco do lado do TypeScript: «as quatro regras de
 * pagamento tardio com PAY *fake*», a «dupla chegada de `payment.confirmed`» e a
 * «estática: nenhuma chamada a `refund`/`payout` no COM». O que precisa de motor
 * — as nove arestas, a barreira do `reembolsada`, o índice parcial das reservas,
 * o domínio da excepção — vive em `db/tests_encomendas/` e corre no *gate* 8.
 *
 * ## O PAY *fake* é o envelope, e a base falsa lê o texto
 *
 * O PAY entra aqui como o que ele produz para o COM: um envelope
 * `payment.confirmed` autenticado. A base falsa é a do
 * `payments.efeito.test.ts`, alargada às reservas, e **honra o predicado** pela
 * razão escrita lá: um duplo que decida por posição de argumento fica verde com
 * a cláusula apagada da instrução. Por isso cada instrução que importa é
 * reconhecida pelo texto e o predicado dela é afirmado antes de se responder.
 *
 * O *savepoint* da re-reserva é simulado com uma fotografia do stock e das
 * reservas: `ROLLBACK TO SAVEPOINT` repõe-na, e é isso que mede que uma re-reserva
 * parcial não fica a prender stock.
 */

import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import {
  MaquinaNaBase,
  SQL_DEFINIR_TENANT,
  SQL_MARCAR_CONSUMIDO,
  SQL_ULTIMO_SEQ,
  consumir,
  validarPayload,
} from "@kamba/core-ts/eventos";
import type { Envelope } from "@kamba/core-ts/eventos";
import { SQL_TECTO } from "@kamba/core-ts/ten";

import {
  SQL_ABRIR_RERESERVA,
  SQL_AUDITAR_REEMBOLSO,
  SQL_DESFAZER_RERESERVA,
  SQL_EMITIR,
  SQL_FECHAR_RERESERVA,
  SQL_GRAFO,
  SQL_LER,
  SQL_MARCAR_EXCEPCAO,
  SQL_TRANSITAR,
} from "../src/orders/consultas.ts";
import { ramoDoPagamento } from "../src/orders/late_payment.ts";
import { textoDoReembolso } from "../src/orders/refunds.ts";
import { transition, type Encomendas } from "../src/orders/transition.ts";
import { efeitoDePagamento } from "../src/payments/efeito.ts";
import {
  SQL_CONSUMIR,
  SQL_LER_OFERTA,
  SQL_LER_RESERVAS,
  SQL_RESERVAR,
} from "../src/reservations/consultas.ts";
import { SQL_MERCHANT_DO_TENANT, repoBase } from "../src/repo-base/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const ORDEM = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50";
const EVENTO = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44";
const MERCHANT = "merch-de-ensaio";
const TOTAL = 24_500_000;
const AGORA = new Date("2026-11-10T10:00:05.000Z");

/** As vinte e uma arestas depois da `0046`, escritas à mão (não do módulo). */
const GRAFO = [
  ["criada", "aguarda_pagamento", null],
  ["criada", "cancelada", null],
  ["aguarda_pagamento", "paga", null],
  ["aguarda_pagamento", "pendente_confirmacao", null],
  ["aguarda_pagamento", "expirada", null],
  ["pendente_confirmacao", "paga", null],
  ["pendente_confirmacao", "aguarda_pagamento", null],
  ["expirada", "aguarda_pagamento", null],
  ["expirada", "cancelada", null],
  ["paga", "entregue", null],
  ["paga", "em_entrega", "COM_DELIVERY_ENABLED"],
  ["em_entrega", "entregue", "COM_DELIVERY_ENABLED"],
  ["expirada", "paga", null],
  ["paga", "reembolso_pendente", null],
  ["entregue", "em_disputa", null],
  ["em_disputa", "reembolso_pendente", null],
  ["em_disputa", "entregue", null],
  ["em_entrega", "entrega_falhada", "COM_DELIVERY_ENABLED"],
  ["entrega_falhada", "em_entrega", "COM_DELIVERY_ENABLED"],
  ["entrega_falhada", "reembolso_pendente", "COM_DELIVERY_ENABLED"],
  ["reembolso_pendente", "reembolsada", null],
].map(([de, para, flag]) => ({ de, para, flag }));

interface Reserva {
  id: string;
  line_no: number;
  sku: string;
  qty: number;
  estado: "ativa" | "consumida" | "libertada";
}

interface Inicial {
  estado: string;
  version?: number;
  excepcao?: string | null;
  reservas?: Reserva[];
  /** sku -> [stock_quantidade, stock_reservada] */
  stock?: Record<string, [number, number]>;
  entregueAt?: string | null;
  entregaConfirmadaPor?: string | null;
  /** O `prazo_reclamacao_dias` do tenant; `null` quando nenhum módulo o declara. */
  prazo?: number | null;
}

function baseFalsa(inicial: Inicial) {
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  const e = {
    estado: inicial.estado,
    version: inicial.version ?? 3,
    excepcao: inicial.excepcao ?? null,
    entregueAt: inicial.entregueAt ?? null,
    entregaConfirmadaPor: inicial.entregaConfirmadaPor ?? null,
  };
  let reservas: Reserva[] = (inicial.reservas ?? []).map((r) => ({ ...r }));
  let stock: Record<string, [number, number]> = structuredClone(
    inicial.stock ?? {},
  );
  let fotografia: { reservas: Reserva[]; stock: typeof stock } | null = null;
  let consumos = 0;
  let proximaReserva = 100;

  const linhaDaReserva = (r: Reserva) => ({
    id: r.id,
    order_id: ORDEM,
    line_no: r.line_no,
    sku: r.sku,
    qty: r.qty,
    estado: r.estado,
    motivo: r.estado === "libertada" ? "expirada" : null,
    expira_at: "2026-11-12T10:00:00.000Z",
    confirmada_at: null,
    version: 1,
  });

  const cliente = {
    async query(sql: string, valores: readonly unknown[] = []) {
      vistas.push({ sql, valores });
      const vazio = { rows: [] as Record<string, unknown>[], rowCount: 0 };

      if (sql === SQL_MERCHANT_DO_TENANT) {
        return {
          rows: [{ medusa_merchant_id: MERCHANT, medusa_sales_channel_id: null }],
          rowCount: 1,
        };
      }
      if (sql === SQL_GRAFO) return { rows: GRAFO, rowCount: GRAFO.length };
      if (/^\s*SELECT estado AS estado FROM platform\.orders_mirror\b/.test(sql)) {
        return { rows: [{ estado: e.estado }], rowCount: 1 };
      }
      if (sql === SQL_LER) {
        assert.equal(valores[0], TENANT);
        return {
          rows: [
            {
              id: ORDEM,
              numero_publico: "ABCD1234",
              estado: e.estado,
              version: e.version,
              total_minor: String(TOTAL),
              currency: "AOA",
              contact_id: "c-1",
              origem: "pme",
              entrega_modo: "levantamento",
              expira_at: "2026-11-08T10:00:00.000Z",
              paga_at: null,
              paga_via: null,
              entregue_at: e.entregueAt,
              entrega_confirmada_por: e.entregaConfirmadaPor,
              confirmacao_dono: "nao_aplicavel",
              lines_snapshot: [],
            },
          ],
          rowCount: 1,
        };
      }
      if (sql === SQL_TRANSITAR) {
        for (const pedaco of ["AND version = $3", "AND estado = $4"]) {
          assert.ok(sql.includes(pedaco), `o SQL_TRANSITAR perdeu "${pedaco}"`);
        }
        const [, id, version, de, para, , pagaVia, entregueAt, confirmadaPor] =
          valores;
        if (id !== ORDEM || version !== e.version || de !== e.estado) return vazio;
        const aresta = GRAFO.find((g) => g.de === de && g.para === para);
        assert.ok(aresta, `${String(de)} -> ${String(para)} nao esta no grafo`);
        e.estado = String(para);
        e.version += 1;
        if (entregueAt !== null) e.entregueAt = String(entregueAt);
        if (confirmadaPor !== null) e.entregaConfirmadaPor = String(confirmadaPor);
        return {
          rows: [
            {
              id: ORDEM,
              numero_publico: "ABCD1234",
              estado: e.estado,
              version: e.version,
              total_minor: String(TOTAL),
              currency: "AOA",
              expira_at: "2026-11-08T10:00:00.000Z",
              paga_via: pagaVia ?? null,
              entrega_confirmada_por: e.entregaConfirmadaPor,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql === SQL_LER_RESERVAS) {
        return { rows: reservas.map(linhaDaReserva), rowCount: reservas.length };
      }
      if (sql === SQL_RESERVAR) {
        assert.ok(
          sql.includes("stock_quantidade - stock_reservada >= $3"),
          "o SQL_RESERVAR perdeu o predicado aritmetico",
        );
        const [, sku, qty] = valores as [string, string, number];
        const s = stock[sku];
        if (s === undefined || s[0] - s[1] < qty) return vazio;
        s[1] += qty;
        return { rows: [{ sku, stock_reservada: s[1] }], rowCount: 1 };
      }
      if (sql === SQL_LER_OFERTA) {
        const sku = String(valores[1]);
        return stock[sku] === undefined ? vazio : { rows: [{ sku }], rowCount: 1 };
      }
      if (sql.startsWith("INSERT INTO platform.stock_reservations")) {
        const [, , lineNo, sku, qty] = valores as [string, string, number, string, number];
        assert.ok(
          !reservas.some((r) => r.line_no === lineNo && r.estado !== "libertada"),
          "a linha ja tem reserva viva: o indice parcial da 0046 recusava",
        );
        const r: Reserva = {
          id: `r-${proximaReserva++}`,
          line_no: lineNo,
          sku,
          qty,
          estado: "ativa",
        };
        reservas.push(r);
        return { rows: [linhaDaReserva(r)], rowCount: 1 };
      }
      if (sql === SQL_CONSUMIR) {
        assert.ok(sql.includes("estado = 'ativa'"));
        const mudadas = reservas.filter((r) => r.estado === "ativa");
        for (const r of mudadas) r.estado = "consumida";
        return { rows: mudadas.map(linhaDaReserva), rowCount: mudadas.length };
      }
      if (sql === SQL_ABRIR_RERESERVA) {
        fotografia = { reservas: structuredClone(reservas), stock: structuredClone(stock) };
        return vazio;
      }
      if (sql === SQL_DESFAZER_RERESERVA) {
        assert.ok(fotografia, "ROLLBACK TO SAVEPOINT sem SAVEPOINT");
        reservas = fotografia.reservas;
        stock = fotografia.stock;
        fotografia = null;
        return vazio;
      }
      if (sql === SQL_FECHAR_RERESERVA) {
        assert.ok(fotografia, "RELEASE SAVEPOINT sem SAVEPOINT");
        fotografia = null;
        return vazio;
      }
      if (sql === SQL_MARCAR_EXCEPCAO) {
        assert.ok(
          sql.includes("COALESCE(excepcao, $3)"),
          "a primeira excepcao tem de ficar",
        );
        e.excepcao = e.excepcao ?? String(valores[2]);
        return { rows: [{ id: ORDEM, excepcao: e.excepcao }], rowCount: 1 };
      }
      if (sql === SQL_AUDITAR_REEMBOLSO) return { rows: [{}], rowCount: 1 };
      if (sql === SQL_TECTO) {
        assert.equal(valores[1], "prazo_reclamacao_dias");
        const prazo = inicial.prazo ?? null;
        return { rows: [{ tecto: prazo === null ? null : String(prazo) }], rowCount: 1 };
      }
      if (sql === SQL_EMITIR) return { rows: [{ event_id: "evt" }], rowCount: 1 };
      if (/^\s*(BEGIN|COMMIT|ROLLBACK)\b/i.test(sql)) return vazio;
      if (sql === SQL_DEFINIR_TENANT) return { rows: [{}], rowCount: 1 };
      if (sql === SQL_MARCAR_CONSUMIDO) {
        consumos += 1;
        return { rows: [], rowCount: consumos === 1 ? 1 : 0 };
      }
      if (sql === SQL_ULTIMO_SEQ) return { rows: [{ ultimo: null }], rowCount: 1 };
      if (sql.startsWith("INSERT INTO platform.order_state_log")) {
        return { rows: [], rowCount: 1 };
      }
      throw new Error(`o duplo nao conhece esta instrucao: ${sql}`);
    },
  };

  return {
    cliente,
    vistas,
    get encomenda() {
      return e;
    },
    get reservas() {
      return reservas;
    },
    get stock() {
      return stock;
    },
  };
}

function envelope(valor = TOTAL, id = EVENTO): Envelope {
  return {
    id,
    tipo: "payment.confirmed",
    versao: 1,
    tenant_id: TENANT,
    ocorrido_em: "2026-11-10T10:00:00.000Z",
    registado_em: "2026-11-10T10:00:00.100Z",
    produtor: "pay@0.1.0",
    agregado: { tipo: "order", id: ORDEM, seq: 4 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P0",
    finalidades: ["transacao"],
    payload: {
      order_id: ORDEM,
      provider: "facilitador_x",
      referencia: "102345678",
      valor_minor: valor,
      currency: "AOA",
      autenticacao: { authn_method: "hmac", authn_ok: true },
    },
  } as Envelope;
}

const efeito = efeitoDePagamento({ consumer: "com_pagamentos", agora: () => AGORA });

function emitidos(vistas: { sql: string; valores: readonly unknown[] }[]) {
  return vistas
    .filter((v) => v.sql === SQL_EMITIR)
    .map((v) => {
      const tipo = String(v.valores[0]);
      const payload = JSON.parse(String(v.valores[5])) as Record<string, unknown>;
      // Todo o envelope que este ficheiro vê sair tem de passar o contrato.
      validarPayload(tipo, Number(v.valores[1]), payload);
      return { tipo, payload };
    });
}

function libertada(line_no: number, sku: string, qty: number): Reserva {
  return { id: `l-${line_no}`, line_no, sku, qty, estado: "libertada" };
}

// ------------------------------------------------------------------- ramos

test("o ramo decide-se pelo estado, e só a criada fica no caminho normal", () => {
  assert.equal(ramoDoPagamento("aguarda_pagamento"), "normal");
  assert.equal(ramoDoPagamento("pendente_confirmacao"), "normal");
  assert.equal(ramoDoPagamento("expirada"), "tardio");
  assert.equal(ramoDoPagamento("cancelada"), "apos_cancelamento");
  for (const estado of [
    "paga",
    "em_entrega",
    "entregue",
    "entrega_falhada",
    "em_disputa",
    "reembolso_pendente",
    "reembolsada",
  ] as const) {
    assert.equal(ramoDoPagamento(estado), "duplicado", estado);
  }
});

// ----------------------------------------------------------------- regra 1

test("regra 1: expirada com stock re-reserva, paga e consome, e emite só o order.paid", async () => {
  const base = baseFalsa({
    estado: "expirada",
    reservas: [libertada(0, "SKU-A", 2), libertada(1, "SKU-B", 1)],
    stock: { "SKU-A": [5, 0], "SKU-B": [1, 0] },
  });
  await efeito(base.cliente, envelope());

  assert.equal(base.encomenda.estado, "paga");
  assert.equal(base.encomenda.excepcao, null);
  assert.deepEqual(base.stock, { "SKU-A": [5, 2], "SKU-B": [1, 1] });
  const vivas = base.reservas.filter((r) => r.estado !== "libertada");
  assert.deepEqual(
    vivas.map((r) => [r.line_no, r.estado]),
    [
      [0, "consumida"],
      [1, "consumida"],
    ],
  );
  assert.deepEqual(emitidos(base.vistas).map((x) => x.tipo), ["order.paid"]);

  // **Reservar primeiro, depois transitar** (Detalhes Técnicos do bloco).
  const ordem = base.vistas.map((v) => v.sql);
  assert.ok(ordem.indexOf(SQL_RESERVAR) < ordem.indexOf(SQL_TRANSITAR));
  assert.ok(ordem.includes(SQL_FECHAR_RERESERVA));
});

test("regra 1: uma linha com reserva ainda activa consome-se e não se re-reserva", async () => {
  const base = baseFalsa({
    estado: "expirada",
    reservas: [{ id: "a-0", line_no: 0, sku: "SKU-A", qty: 2, estado: "ativa" }],
    stock: { "SKU-A": [2, 2] },
  });
  await efeito(base.cliente, envelope());
  assert.equal(base.encomenda.estado, "paga");
  assert.equal(base.vistas.filter((v) => v.sql === SQL_RESERVAR).length, 0);
  assert.equal(base.reservas[0]?.estado, "consumida");
});

test("regra 1: uma encomenda sem reservas (serviço) paga sem re-reserva nenhuma", async () => {
  const base = baseFalsa({ estado: "expirada" });
  await efeito(base.cliente, envelope());
  assert.equal(base.encomenda.estado, "paga");
  assert.ok(!base.vistas.some((v) => v.sql === SQL_ABRIR_RERESERVA));
});

// ----------------------------------------------------------------- regra 2

test("regra 2: sem stock paga com a excepção, emite order.exception, e não prende stock", async () => {
  const base = baseFalsa({
    estado: "expirada",
    reservas: [libertada(0, "SKU-A", 2), libertada(1, "SKU-B", 3)],
    // A primeira linha tem stock, a segunda não: a re-reserva é tudo ou nada.
    stock: { "SKU-A": [5, 0], "SKU-B": [1, 0] },
  });
  await efeito(base.cliente, envelope());

  assert.equal(base.encomenda.estado, "paga", "o dinheiro e real: a encomenda paga");
  assert.equal(base.encomenda.excepcao, "pagamento_tardio_sem_stock");
  assert.deepEqual(
    base.stock,
    { "SKU-A": [5, 0], "SKU-B": [1, 0] },
    "o savepoint desfez a linha que tinha passado",
  );
  assert.equal(base.reservas.filter((r) => r.estado !== "libertada").length, 0);
  const tipos = emitidos(base.vistas);
  assert.deepEqual(
    tipos.map((x) => x.tipo),
    ["order.paid", "order.exception"],
  );
  assert.deepEqual(tipos[1]?.payload, {
    order_id: ORDEM,
    excepcao: "pagamento_tardio_sem_stock",
    evento_pagamento_id: EVENTO,
  });
  assert.ok(base.vistas.some((v) => v.sql === SQL_DESFAZER_RERESERVA));
});

test("regra 2: um SKU apagado conta como sem stock, e não como pedido inválido", async () => {
  const base = baseFalsa({
    estado: "expirada",
    reservas: [libertada(0, "SKU-APAGADO", 1)],
    stock: {},
  });
  await efeito(base.cliente, envelope());
  assert.equal(base.encomenda.excepcao, "pagamento_tardio_sem_stock");
});

test("o pagamento tardio com valor diferente do total não paga, como no caminho normal", async () => {
  const base = baseFalsa({ estado: "expirada", stock: {} });
  await efeito(base.cliente, envelope(TOTAL - 1));
  assert.equal(base.encomenda.estado, "expirada");
  assert.deepEqual(emitidos(base.vistas).map((x) => x.tipo), ["payment.failed"]);
});

// ------------------------------------------------------------ regras 3 e 4

test("regra 3: cancelada não transita, marca a excepção e pede o reembolso do que entrou", async () => {
  const base = baseFalsa({ estado: "cancelada" });
  // Um valor que não é o total, de propósito: o que se pede de volta é o que
  // chegou, e a comparação com o total não decide nada aqui.
  await efeito(base.cliente, envelope(TOTAL - 500));

  assert.equal(base.encomenda.estado, "cancelada");
  assert.equal(base.encomenda.version, 3, "nao e transicao: a version nao sobe");
  assert.equal(base.encomenda.excepcao, "pagamento_apos_cancelamento");
  assert.ok(!base.vistas.some((v) => v.sql === SQL_TRANSITAR));
  const tipos = emitidos(base.vistas);
  assert.deepEqual(
    tipos.map((x) => x.tipo),
    ["order.exception", "order.refund_requested"],
  );
  assert.deepEqual(tipos[1]?.payload, {
    order_id: ORDEM,
    motivo: "pagamento_apos_cancelamento",
    valor_minor: TOTAL - 500,
    currency: "AOA",
  });
});

for (const estado of ["paga", "entregue", "reembolsada"] as const) {
  test(`regra 4: um segundo pagamento numa encomenda ${estado} pede reembolso e não transita`, async () => {
    const base = baseFalsa({ estado });
    await efeito(base.cliente, envelope());
    assert.equal(base.encomenda.estado, estado);
    assert.equal(base.encomenda.excepcao, "pagamento_duplicado");
    assert.deepEqual(
      emitidos(base.vistas).map((x) => [x.tipo, x.payload["motivo"] ?? x.payload["excepcao"]]),
      [
        ["order.exception", "pagamento_duplicado"],
        ["order.refund_requested", "pagamento_duplicado"],
      ],
    );
  });
}

test("regra 4 sobre uma encomenda já excepcionada mantém a primeira excepção", async () => {
  const base = baseFalsa({ estado: "paga", excepcao: "pagamento_tardio_sem_stock" });
  await efeito(base.cliente, envelope());
  assert.equal(base.encomenda.excepcao, "pagamento_tardio_sem_stock");
  // E os eventos dizem o que aconteceu desta vez: o outbox é a história.
  assert.equal(
    emitidos(base.vistas)[0]?.payload["excepcao"],
    "pagamento_duplicado",
  );
});

// ------------------------------------------------------------ idempotência

test("o mesmo payment.confirmed duas vezes dá uma excepção e um pedido de reembolso", async () => {
  // A dupla chegada dos Testes Requeridos, pelo consumo real: o recibo de
  // `events_consumed` é o que torna as regras idempotentes por evento.
  const base = baseFalsa({ estado: "cancelada" });
  const env = envelope();
  for (let i = 0; i < 2; i += 1) {
    await consumir(
      {
        bd: base.cliente,
        consumer: "com_pagamentos",
        envelope: env,
        exigeOrdem: true,
        maquina: new MaquinaNaBase("orders_mirror"),
      },
      efeito,
    );
  }
  assert.deepEqual(
    emitidos(base.vistas).map((x) => x.tipo),
    ["order.exception", "order.refund_requested"],
  );
});

test("dois pagamentos distintos numa encomenda paga dão dois pedidos de reembolso", async () => {
  const base = baseFalsa({ estado: "paga" });
  await efeito(base.cliente, envelope(TOTAL, EVENTO));
  await efeito(base.cliente, envelope(TOTAL, "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d45"));
  assert.equal(
    emitidos(base.vistas).filter((x) => x.tipo === "order.refund_requested").length,
    2,
  );
});

// ---------------------------------------------------------- arestas novas

function encomendas(base: ReturnType<typeof baseFalsa>, kind: string, id: string): Encomendas {
  return {
    ctx: {
      tenantId: TENANT,
      actor: { kind: kind as "dono", id },
      traceId: "t-1",
    },
    repo: repoBase(base.cliente, TENANT, MERCHANT),
    emitir: base.cliente,
    agora: () => AGORA,
  };
}

for (const kind of ["agente", "sistema"] as const) {
  test(`reembolsada por ${kind} é recusada antes de chegar à base`, async () => {
    const base = baseFalsa({ estado: "reembolso_pendente" });
    const r = await transition(encomendas(base, kind, "x"), {
      orderId: ORDEM,
      para: "reembolsada",
      expectedVersion: 3,
      causa: { causa: "reembolso_manual_registado" },
    });
    assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
    assert.equal(base.vistas.length, 0, "nada chegou a base");
  });
}

test("reembolsada por dono sem id é recusada", async () => {
  const base = baseFalsa({ estado: "reembolso_pendente" });
  const r = await transition(encomendas(base, "dono", "  "), {
    orderId: ORDEM,
    para: "reembolsada",
    expectedVersion: 3,
    causa: { causa: "reembolso_manual_registado" },
  });
  assert.equal(r.tipo, "erro");
});

test("reembolsada por ops grava a linha de auditoria com a versão de depois", async () => {
  const base = baseFalsa({ estado: "reembolso_pendente" });
  const r = await transition(encomendas(base, "ops", "op-7"), {
    orderId: ORDEM,
    para: "reembolsada",
    expectedVersion: 3,
    causa: { causa: "reembolso_manual_registado" },
    provaRef: "TRF-2026-0042",
  });
  assert.equal(r.tipo, "ok");
  const auditoria = base.vistas.find((v) => v.sql === SQL_AUDITAR_REEMBOLSO);
  assert.deepEqual(auditoria?.valores, [
    TENANT,
    "staff",
    "op-7",
    "order.refund_record",
    "orders_mirror",
    ORDEM,
    null,
    textoDoReembolso(ORDEM, 4, "TRF-2026-0042"),
  ]);
  assert.deepEqual(emitidos(base.vistas), [], "reembolsada nao tem evento");
});

for (const [de, motivo] of [
  ["paga", "disputa"],
  ["em_disputa", "disputa"],
] as const) {
  test(`${de} -> reembolso_pendente emite order.refund_requested com motivo ${motivo} e o total`, async () => {
    const base = baseFalsa({ estado: de });
    const r = await transition(encomendas(base, "ops", "op-7"), {
      orderId: ORDEM,
      para: "reembolso_pendente",
      expectedVersion: 3,
      causa: { causa: "decisao_de_disputa" },
    });
    assert.equal(r.tipo, "ok");
    assert.deepEqual(emitidos(base.vistas), [
      {
        tipo: "order.refund_requested",
        payload: { order_id: ORDEM, motivo, valor_minor: TOTAL, currency: "AOA" },
      },
    ]);
  });
}

test("entrega_falhada -> reembolso_pendente leva o motivo entrega_falhada (com a bandeira)", async () => {
  const base = baseFalsa({ estado: "entrega_falhada" });
  const e = { ...encomendas(base, "ops", "op-7"), bandeiras: ["COM_DELIVERY_ENABLED"] };
  const r = await transition(e, {
    orderId: ORDEM,
    para: "reembolso_pendente",
    expectedVersion: 3,
    causa: { causa: "devolucao" },
  });
  assert.equal(r.tipo, "ok");
  assert.equal(emitidos(base.vistas)[0]?.payload["motivo"], "entrega_falhada");
});

test("entrega_falhada sem a bandeira não sai, como o em_entrega", async () => {
  const base = baseFalsa({ estado: "entrega_falhada" });
  const r = await transition(encomendas(base, "ops", "op-7"), {
    orderId: ORDEM,
    para: "reembolso_pendente",
    expectedVersion: 3,
    causa: { causa: "devolucao" },
  });
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("em_disputa -> entregue não é entrega nova: não emite, não reescreve a entrega", async () => {
  const base = baseFalsa({
    estado: "em_disputa",
    entregueAt: "2026-11-01T12:00:00.000Z",
    entregaConfirmadaPor: "cliente",
  });
  const r = await transition(encomendas(base, "ops", "op-7"), {
    orderId: ORDEM,
    para: "entregue",
    expectedVersion: 3,
    causa: { causa: "decisao_de_disputa" },
    // Quem decide passa o que a encomenda já tem; a coluna mantém o dela.
    entregaConfirmadaPor: "cliente",
  });
  assert.equal(r.tipo, "ok");
  assert.deepEqual(emitidos(base.vistas), []);
  assert.equal(base.encomenda.entregueAt, "2026-11-01T12:00:00.000Z");
  const transitado = base.vistas.find((v) => v.sql === SQL_TRANSITAR);
  assert.equal(transitado?.valores[7], null, "o entregue_at vai nulo e o COALESCE mantem-no");
});

test("entregue -> em_disputa grava o registo e não emite", async () => {
  const base = baseFalsa({ estado: "entregue" });
  const r = await transition(encomendas(base, "dono", "dono-1"), {
    orderId: ORDEM,
    para: "em_disputa",
    expectedVersion: 3,
    causa: { causa: "reclamacao" },
  });
  assert.equal(r.tipo, "ok");
  assert.deepEqual(emitidos(base.vistas), []);
  assert.ok(base.vistas.some((v) => v.sql.startsWith("INSERT INTO platform.order_state_log")));
});

// ------------------------------------------------------- prazo de reclamação

for (const [prazo, diasAtras, passa] of [
  [null, 400, true],
  [7, 3, true],
  [7, 7, true],
  [7, 8, false],
] as const) {
  test(`entregue há ${diasAtras} dias com prazo ${String(prazo)}: a disputa ${passa ? "entra" : "é recusada"}`, async () => {
    const entregueAt = new Date(AGORA.getTime() - diasAtras * 86_400_000 - 1_000).toISOString();
    const base = baseFalsa({ estado: "entregue", entregueAt, prazo });
    const r = await transition(encomendas(base, "dono", "dono-1"), {
      orderId: ORDEM,
      para: "em_disputa",
      expectedVersion: 3,
      causa: { causa: "reclamacao" },
    });
    // **Sem prazo configurado, a disputa entra**: recusá-la era assumir o
    // prazo zero, e o critério 8 diz que nenhum prazo legal é assumido.
    assert.equal(r.tipo, passa ? "ok" : "erro");
  });
}

// ------------------------------------------------------------- estática

/** Os ficheiros `.ts` de `services/com/src`, recursivamente. */
function fontesDoCom(): string[] {
  const raiz = join(import.meta.dirname, "..", "src");
  const fora: string[] = [];
  const andar = (dir: string) => {
    for (const nome of readdirSync(dir)) {
      const caminho = join(dir, nome);
      if (statSync(caminho).isDirectory()) andar(caminho);
      else if (nome.endsWith(".ts")) fora.push(caminho);
    }
  };
  andar(raiz);
  return fora;
}

/**
 * Uma **chamada** a `refund` ou `payout`, em qualquer forma: método
 * (`provider.refund(`), função (`refund(`), ou com o nome numa variável
 * (`["refund"](`). Comentários e cadeias contam também, de propósito: uma
 * menção no código é onde a chamada começa, e a nota que explica porque não há
 * chamada escreve «reembolso», não `refund(`.
 */
const CHAMADA_PROIBIDA = /\b(refund|payout)\s*\(|\[\s*["'`](refund|payout)["'`]\s*\]\s*\(/i;

test("nenhum código do COM chama refund nem payout (ADR-004)", () => {
  const achados = fontesDoCom().filter((f) =>
    CHAMADA_PROIBIDA.test(readFileSync(f, "utf-8")),
  );
  assert.deepEqual(achados, [], "o COM nao move dinheiro: reembolsos sao manuais");
});

test("o canário da varredura: as três formas de chamada são apanhadas", () => {
  for (const amostra of [
    "await provider.refund(cobranca)",
    "payout (conta, valor)",
    'adaptador["refund"](x)',
  ]) {
    assert.ok(CHAMADA_PROIBIDA.test(amostra), amostra);
  }
  assert.ok(fontesDoCom().length > 20, "a varredura le o src do COM e nao uma pasta vazia");
});
