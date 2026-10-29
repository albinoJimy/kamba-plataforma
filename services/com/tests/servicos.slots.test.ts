/**
 * O `slot_id` opaco do critério 2 (KAM-047).
 *
 * O que aqui se prova são as três propriedades que a forma do token tem de ter,
 * e cada uma paga uma linha do ticket: determinístico (critério 4),
 * infalsificável (o guardrail de `docs/tecnica/02` §8.2) e auto-descritivo (a
 * assinatura `holdSlot(ctx, slotId)` do bloco).
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { test } from "node:test";

import {
  SegredoEmFaltaError,
  VERSAO_DO_SLOT,
  derivarSlotId,
  lerSlotId,
  type Slot,
} from "../src/servicos/index.ts";

const SEGREDO = randomBytes(32);
const OUTRO_SEGREDO = randomBytes(32);
const TENANT_A = "11111111-1111-4111-8111-111111111111";
const TENANT_B = "22222222-2222-4222-8222-222222222222";

const SLOT: Slot = {
  serviceId: "33333333-3333-4333-8333-333333333333",
  resourceId: "44444444-4444-4444-8444-444444444444",
  inicioAt: "2026-11-02T09:00:00.000Z",
  fimAt: "2026-11-02T09:30:00.000Z",
};

test("o slot_id e deterministico: o mesmo slot da sempre o mesmo", () => {
  // A propriedade que o critério 4 exige. Sem ela, dois `getAvailability`
  // davam dois identificadores para o mesmo horário e a idempotência por
  // `(contact_id, slot_id)` deixava de existir por construção.
  assert.equal(
    derivarSlotId(SEGREDO, TENANT_A, SLOT),
    derivarSlotId(SEGREDO, TENANT_A, SLOT),
  );
});

test("o slot_id e opaco: nao e nenhum dos campos em claro", () => {
  const slotId = derivarSlotId(SEGREDO, TENANT_A, SLOT);
  for (const campo of [SLOT.serviceId, SLOT.resourceId, TENANT_A]) {
    assert.ok(
      !slotId.includes(campo),
      `o slot_id nao pode conter ${campo} em claro`,
    );
  }
});

test("o slot_id de um tenant nao verifica noutro", () => {
  // O `tenant_id` **não** está no corpo do token: entra no segredo derivado.
  // Esta asserção é o que prova que a separação existe mesmo assim.
  const slotId = derivarSlotId(SEGREDO, TENANT_A, SLOT);
  assert.deepEqual(lerSlotId(SEGREDO, TENANT_A, slotId), SLOT);
  assert.equal(lerSlotId(SEGREDO, TENANT_B, slotId), null);
});

test("um slot_id assinado com outro segredo nao verifica", () => {
  const slotId = derivarSlotId(OUTRO_SEGREDO, TENANT_A, SLOT);
  assert.equal(lerSlotId(SEGREDO, TENANT_A, slotId), null);
});

test("o corpo adulterado nao verifica, mesmo com a assinatura original", () => {
  // O caso que distingue um token assinado de um token codificado: mexer na
  // hora e manter a assinatura. Sem isto, o modelo construía um horário.
  const slotId = derivarSlotId(SEGREDO, TENANT_A, SLOT);
  const [corpo, assinatura] = slotId.split(".");
  assert.ok(corpo !== undefined && assinatura !== undefined);
  const adulterado = Buffer.from(
    Buffer.from(corpo, "base64url").toString("utf8").replace("09:00", "10:00"),
    "utf8",
  ).toString("base64url");
  assert.equal(lerSlotId(SEGREDO, TENANT_A, `${adulterado}.${assinatura}`), null);
});

test("um slot_id fabricado do nada nao verifica", () => {
  const corpo = Buffer.from(
    `${VERSAO_DO_SLOT}|${SLOT.serviceId}|${SLOT.resourceId}|${SLOT.inicioAt}|${SLOT.fimAt}`,
    "utf8",
  ).toString("base64url");
  assert.equal(lerSlotId(SEGREDO, TENANT_A, `${corpo}.AAAAAAAAAAAAAAAAAAAAAA`), null);
});

test("nenhuma forma malformada lanca: recusam-se todas sem rebentar", () => {
  // O `timingSafeEqual` rebenta com comprimentos diferentes, e o comprimento é
  // escolhido por quem chama: se a comparação fosse feita antes de normalizar o
  // tamanho, um `slot_id` de um carácter derrubava o processo. Onze formas.
  const malformados: unknown[] = [
    "",
    ".",
    "..",
    "a.b",
    "a",
    "x".repeat(600),
    "YQ==.AAAAAAAAAAAAAAAAAAAAAA",
    null,
    undefined,
    42,
    { toString: () => "explode" },
  ];
  for (const valor of malformados) {
    assert.equal(
      lerSlotId(SEGREDO, TENANT_A, valor),
      null,
      `devia recusar sem lancar: ${JSON.stringify(String(valor)).slice(0, 40)}`,
    );
  }
});

test("um segredo curto ou ausente e recusado, e nao silenciado", () => {
  // Um HMAC com chave vazia é um HMAC válido: aceitá-lo era aceitar qualquer
  // `slot_id` de quem souber que o cofre está vazio.
  for (const segredo of [Buffer.alloc(0), Buffer.alloc(31)]) {
    assert.throws(
      () => derivarSlotId(segredo, TENANT_A, SLOT),
      SegredoEmFaltaError,
    );
    assert.throws(
      () => lerSlotId(segredo, TENANT_A, "a.b"),
      SegredoEmFaltaError,
    );
  }
});

test("um slot com intervalo invertido e recusado mesmo bem assinado", () => {
  // A assinatura garante que o corpo é nosso; isto garante que é coerente. Sem
  // a verificação, um defeito nosso chegava à base como erro de integridade em
  // vez de `VALIDATION_ERROR` legível.
  const invertido: Slot = { ...SLOT, inicioAt: SLOT.fimAt, fimAt: SLOT.inicioAt };
  const slotId = derivarSlotId(SEGREDO, TENANT_A, invertido);
  assert.equal(lerSlotId(SEGREDO, TENANT_A, slotId), null);
});

test("dois servicos no mesmo recurso e hora dao slot_id diferentes", () => {
  // Sem o `service_id` no corpo do token, confirmar um marcava o outro.
  const outro: Slot = {
    ...SLOT,
    serviceId: "55555555-5555-4555-8555-555555555555",
  };
  assert.notEqual(
    derivarSlotId(SEGREDO, TENANT_A, SLOT),
    derivarSlotId(SEGREDO, TENANT_A, outro),
  );
});
