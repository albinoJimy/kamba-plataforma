/**
 * O contrato da porta `CommerceRegistry` (KAM-042, critério 1).
 *
 * **O que isto prova e o que não prova.** Não prova isolamento nenhum: o
 * isolamento no Registo é do repo-base (`repo-base.test.ts`) e, no `platform`,
 * da RLS, que só se prova contra um PostgreSQL verdadeiro. O que se prova aqui
 * é a **forma do contrato** — que os doze métodos são doze, que os domínios são
 * fechados, e que um `ctx` incompleto falha **antes** de qualquer outra coisa.
 *
 * A última parte é a que importa: o `exigirCtx` corre fora de qualquer
 * transacção, pelo que o ISO-09 não depende de haver base de dados. Se um dia
 * alguém o mover para dentro do `comTenant`, este ficheiro deixa de passar.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACTOR_KINDS,
  CtxEmFaltaError,
  ERROS,
  METODOS_DA_PORTA,
  MOTIVOS_DE_LIBERTACAO,
  ORDER_STATES,
  PRECO_MODOS,
  STOCK_MODOS,
  erro,
  eUuid,
  exigirCtx,
  naoImplementado,
  ok,
  type Ctx,
} from "../src/port/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";

function ctxValido(): Ctx {
  return {
    tenantId: TENANT,
    actor: { kind: "agente", id: "grafo-vendedor" },
    traceId: "trace-1",
  };
}

test("a porta tem doze metodos, e sao os do docs/tecnica/03 §3.2", () => {
  // **Doze, e não onze.** A contagem está aqui para que a divergência entre o
  // objectivo do bloco («11 métodos») e o critério de aceitação (que nomeia
  // doze) não possa ser resolvida em silêncio por quem lê um dos dois.
  assert.equal(METODOS_DA_PORTA.length, 12);
  assert.deepEqual(
    [...METODOS_DA_PORTA],
    [
      "upsertProductDraft",
      "publishProduct",
      "getOfferView",
      "createOrder",
      "requestOwnerConfirmation",
      "reserveStock",
      "extendReservation",
      "commitReservation",
      "releaseReservation",
      "transition",
      "getOrder",
      "listOrders",
    ],
  );
});

test("os dominios fechados sao os do dicionario", () => {
  assert.deepEqual([...ACTOR_KINDS], ["agente", "dono", "sistema", "ops"]);
  assert.deepEqual([...PRECO_MODOS], ["fixo", "a_partir_de", "sob_consulta"]);
  assert.deepEqual(
    [...STOCK_MODOS],
    ["garantido", "indicativo", "confirmar_dono"],
  );
  assert.deepEqual(
    [...MOTIVOS_DE_LIBERTACAO],
    ["expirada", "cancelada", "recusada_dono"],
  );
  // Os nove estados do §6.1. As duas transições «extensão proposta» do §6.1
  // não acrescentam estados — acrescentam arestas —, pelo que a lista é a
  // mesma do `CHECK` de `orders_mirror`.
  assert.equal(ORDER_STATES.length, 9);
  assert.ok(ORDER_STATES.includes("reembolso_pendente"));
});

test("NOT_IMPLEMENTED esta na lista fechada de erros, e e o unico nome novo", () => {
  assert.ok(ERROS.includes("NOT_IMPLEMENTED"));
  // Os outros quatro são nomes que o dicionário §3.27 já fecha como valores de
  // `tool_audit.error_code`; importam-se pelo nome em vez de serem
  // redeclarados com significado novo.
  for (const existente of [
    "NOT_FOUND",
    "TENANT_MISMATCH",
    "VALIDATION_ERROR",
    "UPSTREAM_DOWN",
  ] as const) {
    assert.ok(ERROS.includes(existente), existente);
  }
  assert.equal(ERROS.length, 5);
});

test("ISO-09: sem ctx.tenantId lanca, e lanca antes de tudo o resto", () => {
  // O `ctx` abaixo tem **tudo** menos o tenant. Se a verificação do tenant não
  // fosse a primeira, este caso passava por ser um `ctx` quase completo.
  assert.throws(
    () => exigirCtx({ ...ctxValido(), tenantId: "" }),
    (e: unknown) => e instanceof CtxEmFaltaError && /tenantId/.test(String(e)),
  );
  assert.throws(
    () => exigirCtx({ ...ctxValido(), tenantId: "nao-e-um-uuid" }),
    CtxEmFaltaError,
  );
  // `undefined` e `null` não são excepções à regra: um `ctx` montado a partir
  // de um estado de grafo incompleto chega assim e não com uma cadeia vazia.
  assert.throws(
    () => exigirCtx({ ...ctxValido(), tenantId: undefined as never }),
    CtxEmFaltaError,
  );
});

test("o ctx exige actor valido e traceId, e nao so o tenant", () => {
  assert.throws(
    () => exigirCtx({ ...ctxValido(), actor: { kind: "root" as never, id: "x" } }),
    (e: unknown) => e instanceof CtxEmFaltaError && /actor\.kind/.test(String(e)),
  );
  assert.throws(
    () => exigirCtx({ ...ctxValido(), actor: { kind: "ops", id: "" } }),
    (e: unknown) => e instanceof CtxEmFaltaError && /actor\.id/.test(String(e)),
  );
  assert.throws(
    () => exigirCtx({ ...ctxValido(), traceId: "" }),
    (e: unknown) => e instanceof CtxEmFaltaError && /traceId/.test(String(e)),
  );
  // Um `traceId` absurdamente longo é entrada não validada a caminho de uma
  // coluna de *log*; recusa-se aqui e não no `INSERT`.
  assert.throws(
    () => exigirCtx({ ...ctxValido(), traceId: "t".repeat(129) }),
    CtxEmFaltaError,
  );
});

test("um ctx valido normaliza o tenant e devolve as tres partes", () => {
  const validado = exigirCtx({
    ...ctxValido(),
    tenantId: TENANT.toUpperCase(),
  });
  assert.equal(validado.tenantId, TENANT);
  assert.equal(validado.actor.kind, "agente");
  assert.equal(validado.traceId, "trace-1");
});

test("os construtores de Resultado discriminam, e nao lancam", () => {
  assert.deepEqual(ok(7), { tipo: "ok", valor: 7 });
  assert.deepEqual(erro("NOT_FOUND"), { tipo: "erro", erro: "NOT_FOUND" });
  assert.deepEqual(naoImplementado(), {
    tipo: "erro",
    erro: "NOT_IMPLEMENTED",
  });
});

test("eUuid aceita a forma canonica em qualquer caixa e recusa o resto", () => {
  assert.ok(eUuid(TENANT));
  assert.ok(eUuid(TENANT.toUpperCase()));
  assert.ok(!eUuid("11111111111141118111111111111111"));
  assert.ok(!eUuid(42));
  assert.ok(!eUuid(null));
});
