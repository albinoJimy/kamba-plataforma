/**
 * A suite ISO do adaptador da opção B (KAM-042, critérios 1, 2 e 6).
 *
 * ## O `xfail strict`, e porque não é um `todo` do `node:test`
 *
 * O critério 6 pede: «cada [método não implementado] tem teste de isolamento
 * marcado *xfail strict* que falha quando a implementação chegar sem teste». O
 * vocabulário é do pytest, e o `node:test` não o tem: o `{ todo: true }` de um
 * teste que **passa** é reportado como *todo* e **não** falha a suite, que é o
 * contrário do que «strict» quer dizer.
 *
 * A forma que tem a semântica certa, e que está aqui, é mais simples do que uma
 * marca: **afirmar o `NOT_IMPLEMENTED`**. Enquanto o método não estiver
 * implementado, a asserção passa. No dia em que alguém o implementar e não
 * substituir este caso pelo teste de isolamento a sério, a asserção **falha** —
 * e falha com a mensagem que diz qual é o ticket dono e o que o substitui. É
 * exactamente o `xfail strict` do critério, escrito no que a casa tem.
 *
 * ## O que esta suite cobre, e o que não pode cobrir hoje
 *
 *   ISO-09            **medido e verde**: as doze operações com `ctx` sem
 *                     `tenantId` falham, e falham antes de pedirem ligação.
 *   ISO-01..08, 10    **não medidos, e não é omissão**: «operações da porta com
 *                     `ctx` de A sobre ids de B» precisa de uma operação que
 *                     leia algo, e as doze devolvem `NOT_IMPLEMENTED`. Ficam
 *                     como os `xfail strict` deste ficheiro.
 *   ISO-11..32        **fora deste ficheiro**: são a Store API, a Admin API e o
 *                     *query graph* do Medusa, e exigem um Medusa a correr. A
 *                     única medição que existe é a do KAM-041
 *                     (`spikes/medusa-d3/resultados/iso.json`, 2026-10-27), e
 *                     **o ISO-15 está vermelho lá** — um passe indevido real na
 *                     Store API.
 *   ISO-57..60        ignorados pelo critério 2, por escrito.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CtxEmFaltaError,
  METODOS_DA_PORTA,
  type ClienteSql,
  type CommerceRegistry,
  type Ctx,
} from "../src/port/index.ts";
import {
  adaptadorMedusa,
  comRegisto,
  type Dependencias,
} from "../src/adapters/medusa/index.ts";
import { MerchantEmFaltaError } from "../src/repo-base/index.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const ORDER_DE_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";

/**
 * O ticket dono de cada método. **A mesma tabela que `port-coverage.md`**, e a
 * duplicação é deliberada: um documento não falha um *build*, e o critério 6
 * pede que a cobertura da porta seja verificável e não lida.
 */
const DONO: Readonly<Record<string, string>> = {
  upsertProductDraft: "KAM-043",
  publishProduct: "KAM-043",
  getOfferView: "KAM-043",
  createOrder: "KAM-044",
  requestOwnerConfirmation: "KAM-044",
  reserveStock: "KAM-045",
  extendReservation: "KAM-045",
  commitReservation: "KAM-045",
  releaseReservation: "KAM-045",
  transition: "KAM-044",
  getOrder: "KAM-044",
  listOrders: "KAM-044",
};

/** Argumentos plausíveis por método, com **ids do tenant B** (ISO-01..08). */
const ARGUMENTOS: Readonly<Record<string, readonly unknown[]>> = {
  upsertProductDraft: [{ sku: "sku-de-b", nome: "x" }],
  publishProduct: [
    { sku: "sku-de-b", registoId: "prod_de_b" },
    { actor: { kind: "dono", id: "dono-de-b" }, em: "2026-10-30T00:00:00Z" },
  ],
  getOfferView: ["sku-de-b"],
  createOrder: [
    {
      intentKey: "i".repeat(26),
      contactId: "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c",
      linhas: [{ sku: "sku-de-b", qty: 1 }],
      entregaModo: "levantamento",
    },
  ],
  requestOwnerConfirmation: [ORDER_DE_B],
  reserveStock: [ORDER_DE_B, 48 * 60 * 60 * 1000],
  extendReservation: [ORDER_DE_B, "2026-11-01T00:00:00Z"],
  commitReservation: [ORDER_DE_B],
  releaseReservation: [ORDER_DE_B, "expirada"],
  transition: [ORDER_DE_B, "paga", 1, { causa: "payment.confirmed" }],
  getOrder: [ORDER_DE_B],
  listOrders: [{ estado: "paga" }],
};

/** Uma ligação que **explode** se alguém lhe falar. Ver o teste do ISO-09. */
const CLIENTE_PROIBIDO: ClienteSql = {
  async query() {
    throw new Error(
      "o adaptador pediu a base com um ctx que o exigirCtx devia ter recusado",
    );
  },
};

function deps(cliente: ClienteSql = CLIENTE_PROIBIDO): Dependencias {
  return {
    comTenant: async (_tenantId, trabalho) => trabalho(cliente),
  };
}

function ctx(tenantId: string = TENANT_A): Ctx {
  return {
    tenantId,
    actor: { kind: "agente", id: "grafo-vendedor" },
    traceId: "trace-iso",
  };
}

function chamar(
  porta: CommerceRegistry,
  metodo: string,
  contexto: Ctx,
): Promise<unknown> {
  const fn = (porta as unknown as Record<string, unknown>)[metodo];
  assert.equal(typeof fn, "function", `${metodo} nao existe na porta`);
  return (fn as (...a: unknown[]) => Promise<unknown>).call(
    porta,
    contexto,
    ...(ARGUMENTOS[metodo] ?? []),
  );
}

// ------------------------------------------------------------------- ISO-09

test("ISO-09: as doze operacoes sem ctx.tenantId falham, e sem tocar na base", async () => {
  const porta = adaptadorMedusa(deps());
  const semTenant = { ...ctx(), tenantId: "" };

  for (const metodo of METODOS_DA_PORTA) {
    await assert.rejects(
      () => chamar(porta, metodo, semTenant),
      CtxEmFaltaError,
      metodo,
    );
  }
  // O `CLIENTE_PROIBIDO` lança se lhe falarem. Doze rejeições com
  // `CtxEmFaltaError` — e não com o `Error` dele — provam que nenhuma das doze
  // chegou a pedir ligação.
});

test("ISO-09: um tenant que nao e UUID canonico tambem falha fechado", async () => {
  const porta = adaptadorMedusa(deps());
  for (const mau of ["", "   ", "nao-e-uuid", "' OR 1=1 --"]) {
    await assert.rejects(
      () => chamar(porta, "getOrder", { ...ctx(), tenantId: mau }),
      CtxEmFaltaError,
      mau,
    );
  }
});

// ---------------------------------------------- critério 5 no caminho real

test("criterio 5: um tenant por provisionar nao abre operacao no Registo", async () => {
  // O `comRegisto` é por onde cada implementação vai entrar. Um tenant sem
  // `medusa_merchant_id` **não** chega ao corpo do trabalho.
  let correu = false;
  const cliente: ClienteSql = {
    async query() {
      return { rows: [{ medusa_merchant_id: null, medusa_sales_channel_id: null }] };
    },
  };
  await assert.rejects(
    () =>
      comRegisto(deps(cliente), ctx(TENANT_B), async () => {
        correu = true;
      }),
    MerchantEmFaltaError,
  );
  assert.equal(correu, false);
});

test("criterio 5: com merchant provisionado, o repo nasce ligado a ele", async () => {
  const cliente: ClienteSql = {
    async query() {
      return {
        rows: [{ medusa_merchant_id: "merch_A", medusa_sales_channel_id: "sc_A" }],
      };
    },
  };
  const visto = await comRegisto(deps(cliente), ctx(TENANT_A), async (r) => ({
    tenant: r.repo.tenantId,
    merchant: r.ids.merchantId,
    actor: r.ctx.actor.kind,
  }));
  assert.deepEqual(visto, {
    tenant: TENANT_A,
    merchant: "merch_A",
    actor: "agente",
  });
});

// --------------------------------------------- ISO-01..08 e 10: xfail strict

for (const metodo of METODOS_DA_PORTA) {
  test(`ISO-01..08 (xfail strict): ${metodo} ainda nao isola nada`, async () => {
    const porta = adaptadorMedusa(deps());
    const resultado = (await chamar(porta, metodo, ctx())) as {
      tipo: string;
      erro?: string;
    };
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "NOT_IMPLEMENTED" },
      `${metodo} deixou de devolver NOT_IMPLEMENTED. ` +
        `O ticket dono e o ${DONO[metodo]}: substitui este caso pelo teste ` +
        "de isolamento a serio — ctx do tenant A sobre um id do tenant B tem " +
        "de dar TENANT_MISMATCH ou NOT_FOUND, nunca a linha de B. " +
        "E actualiza docs/com/port-coverage.md (KAM-042, criterio 6).",
    );
  });
}

test("ISO-10 (xfail strict): filtros vazios, cursor forjado e OR", async () => {
  // Os três casos do ISO-10 contra o único método que recebe filtros. Enquanto
  // o `listOrders` não estiver implementado, os três devolvem o mesmo
  // `NOT_IMPLEMENTED`; quando estiver, cada um destes tem de passar a uma
  // asserção própria — filtro vazio não lista tudo, cursor forjado é
  // `VALIDATION_ERROR`, e um `OR` no filtro não alarga o conjunto.
  const porta = adaptadorMedusa(deps());
  for (const filtro of [
    {},
    { cursor: "ZmFsc2lmaWNhZG8=" },
    { contactId: "' OR 1=1 --" },
  ]) {
    const resultado = await porta.listOrders(ctx(), filtro as never);
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "NOT_IMPLEMENTED" },
      "o listOrders foi implementado: parte este caso nos tres do ISO-10 " +
        "(KAM-044, KAM-042 criterio 2)",
    );
  }
});
