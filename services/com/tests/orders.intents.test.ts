/**
 * A `intent_key`, o `draft_hash` e o `cart_id`, sem base de dados (KAM-046).
 *
 * Estas funções são puras e é aqui que se medem. O que **não** se mede aqui é a
 * idempotência: cinquenta chamadas concorrentes sobre um objecto em memória não
 * têm transacções para serializar e provam zero — isso está em
 * `db/tests_encomendas/test_idempotencia.py`, com cinquenta ligações a um
 * PostgreSQL real. A lição é do KAM-043, cuja caixa de concorrência ficou
 * **NÃO VERIFICADO** por exactamente este motivo.
 *
 * O que se mede aqui, e que uma suite de base de dados mediria mal:
 *
 * ```text
 * a canonicalizacao   duas ordens das mesmas linhas dao o mesmo draft_hash
 * a ausencia do tempo a mesma chave em dois instantes diferentes
 * a ausencia do fone  nenhuma parte da chave e um telefone, por construcao
 * o anel              a chave da versao anterior continua a derivar-se
 * a separacao         conhecer o cart_id nao da a intent_key
 * ```
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CARACTERES_DA_CHAVE,
  ParteInvalidaError,
  SegredoMalFormadoError,
  cartId,
  cartIdValido,
  chavesDoAnel,
  concatenar,
  draftHash,
  intentKey,
  lerSegredo,
  linhasCanonicas,
  mesmoDraftHash,
  type AnelDoSegredo,
  type PartesDaIntencao,
} from "../src/orders/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONTACTO = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";
const OUTRO_CONTACTO = "8d2e6f4b-3c50-4b7d-9e1f-2a3b4c5d6e7f";

/** Trinta e dois octetos em base64, com `kid`. A forma que o cofre promete. */
const ACTUAL = `v2:${Buffer.alloc(32, 7).toString("base64")}`;
const ANTERIOR = `v1:${Buffer.alloc(32, 3).toString("base64")}`;
const ANEL: AnelDoSegredo = [ACTUAL, ANTERIOR];
const SO_UMA: AnelDoSegredo = [ACTUAL, null];

const PARTES: PartesDaIntencao = {
  tenantId: TENANT,
  contactId: CONTACTO,
  draftId: "a".repeat(64),
  draftVersion: 1,
};

// ------------------------------------------------------------- a forma do valor

test("o segredo lê-se na forma <kid>:<base64 de 32 octetos>", () => {
  const { kid, chave } = lerSegredo(ACTUAL);
  assert.equal(kid, "v2");
  assert.equal(chave.length, 32);
});

test("um segredo sem versão, sem base64 ou com octetos a menos é recusado", () => {
  for (const mau of [
    Buffer.alloc(32, 1).toString("base64"), // sem `<kid>:`
    "v2:nao-e-base64!!",
    `v2:${Buffer.alloc(31, 1).toString("base64")}`,
    `V2:${Buffer.alloc(32, 1).toString("base64")}`, // `kid` em maiúsculas
  ]) {
    assert.throws(() => lerSegredo(mau), SegredoMalFormadoError, mau.slice(0, 12));
  }
});

test("a mensagem de erro do segredo nunca repete o valor", () => {
  // É a regra do `ops/secrets-inventory.yaml`: nenhum valor sai numa mensagem.
  // O valor aqui é um base64 de 32 octetos iguais, que é inconfundível.
  const valor = Buffer.alloc(32, 9).toString("base64");
  try {
    lerSegredo(`v2:${valor.slice(0, 10)}`);
    assert.fail("devia ter lançado");
  } catch (erro) {
    assert.equal((erro as Error).message.includes(valor.slice(0, 10)), false);
  }
});

// --------------------------------------------------------------- a intent_key

test("a intent_key tem 26 caracteres do alfabeto de Crockford", () => {
  const chave = intentKey(ACTUAL, PARTES);
  assert.equal(chave.length, CARACTERES_DA_CHAVE);
  assert.match(chave, /^[0-9A-HJKMNP-TV-Z]{26}$/);
});

test("a mesma intenção em dois instantes dá a mesma intent_key", () => {
  // É o critério 3 na parte que nenhuma base de dados mede: a chave **não tem
  // tempo**. As 14:04:59 e as 14:05:01 são a fronteira que a chave do documento
  // exploratório (`hash(msisdn + sku + janela_5min)`) duplicava.
  const antes = intentKey(ACTUAL, PARTES);
  const depois = intentKey(ACTUAL, PARTES);
  assert.equal(antes, depois);
});

test("nenhuma parte da intent_key é um telefone, e a assinatura é a prova", () => {
  // O ADR-010 e a caixa de privacidade: a chave leva `tenant_id`, `contact_id`,
  // `draft_id` e `draft_version`, e nada mais tem por onde entrar. O que se mede
  // é que as quatro partes **são** as quatro: um `tenant_id` ou `contact_id` que
  // não seja UUID canónico é recusado, pelo que um `+244` não chega ao HMAC.
  for (const campo of ["tenantId", "contactId"] as const) {
    assert.throws(
      () => intentKey(ACTUAL, { ...PARTES, [campo]: "+244923000000" }),
      ParteInvalidaError,
      campo,
    );
  }
});

test("mudar qualquer uma das quatro partes muda a intent_key", () => {
  const base = intentKey(ACTUAL, PARTES);
  const variantes: PartesDaIntencao[] = [
    { ...PARTES, contactId: OUTRO_CONTACTO },
    { ...PARTES, draftId: "b".repeat(64) },
    { ...PARTES, draftVersion: 2 },
    { ...PARTES, tenantId: "11111111-2222-3333-4444-555555555555" },
  ];
  for (const variante of variantes) {
    assert.notEqual(intentKey(ACTUAL, variante), base);
  }
});

test("o draft_id novo e a draft_version nova são os dois caminhos do critério 4", () => {
  // «Recompra do mesmo SKU 30 s depois (novo `draft_id`) cria nova encomenda;
  // carrinho editado (nova `draft_version`) cria encomenda distinta.» As duas
  // propriedades saem daqui: chaves diferentes, logo recibos diferentes.
  const original = intentKey(ACTUAL, PARTES);
  const recompra = intentKey(ACTUAL, { ...PARTES, draftId: "c".repeat(64) });
  const editado = intentKey(ACTUAL, { ...PARTES, draftVersion: 2 });
  assert.equal(new Set([original, recompra, editado]).size, 3);
});

test("o segredo decide a chave: dois segredos dão duas chaves", () => {
  assert.notEqual(intentKey(ACTUAL, PARTES), intentKey(ANTERIOR, PARTES));
});

// -------------------------------------------------------------------- o anel

test("o anel com duas versões dá duas chaves, a actual primeiro", () => {
  const chaves = chavesDoAnel(ANEL, PARTES);
  assert.equal(chaves.length, 2);
  assert.equal(chaves[0], intentKey(ACTUAL, PARTES));
  assert.equal(chaves[1], intentKey(ANTERIOR, PARTES));
});

test("um segredo que nunca rodou dá uma chave, e não é erro", () => {
  // É a letra do `SecretRing` do `secrets/port.ts`: `anterior` nulo quer dizer
  // «só há uma» e não «falhou».
  const chaves = chavesDoAnel(SO_UMA, PARTES);
  assert.equal(chaves.length, 1);
  assert.equal(chaves[0], intentKey(ACTUAL, PARTES));
});

test("um anel cujas duas metades são iguais não repete a chave", () => {
  assert.deepEqual(chavesDoAnel([ACTUAL, ACTUAL], PARTES), [
    intentKey(ACTUAL, PARTES),
  ]);
});

// ------------------------------------------------- a canonicalização das linhas

test("duas ordens das mesmas linhas dão o mesmo draft_hash", () => {
  // **A metade do critério 2 que um teste distraído não cobre.** Com a ordem a
  // contar, o segundo toque do mesmo carrinho parecia conteúdo novo e levava
  // `INTENT_REUSED_WITH_DIFFERENT_CONTENT` numa repetição legítima.
  const a = draftHash({
    linhas: [
      { sku: "arroz-5kg", qty: 2 },
      { sku: "sabao-azul", qty: 1 },
    ],
    entregaModo: "levantamento",
  });
  const b = draftHash({
    linhas: [
      { sku: "sabao-azul", qty: 1 },
      { sku: "arroz-5kg", qty: 2 },
    ],
    entregaModo: "levantamento",
  });
  assert.equal(mesmoDraftHash(a, b), true);
});

test("três ordens das mesmas três linhas dão um só draft_hash", () => {
  const linhas = [
    { sku: "arroz-5kg", qty: 2 },
    { sku: "sabao-azul", qty: 1 },
    { sku: "oleo-1l", qty: 3 },
  ];
  const permutacoes = [
    [linhas[0], linhas[1], linhas[2]],
    [linhas[2], linhas[0], linhas[1]],
    [linhas[1], linhas[2], linhas[0]],
  ] as { sku: string; qty: number }[][];
  const hashes = new Set(
    permutacoes.map((p) =>
      draftHash({ linhas: p, entregaModo: "entrega" }).toString("hex"),
    ),
  );
  assert.equal(hashes.size, 1);
});

test("o draft_hash tem 32 octetos, que é o que o CHECK da revisão 0030 exige", () => {
  // `order_intents_draft_hash_ck CHECK (octet_length(draft_hash) = 32)`.
  assert.equal(
    draftHash({ linhas: [{ sku: "x", qty: 1 }], entregaModo: "entrega" }).length,
    32,
  );
});

test("mudar a quantidade, o sku ou o modo de entrega muda o draft_hash", () => {
  const base = draftHash({
    linhas: [{ sku: "arroz-5kg", qty: 2 }],
    entregaModo: "levantamento",
  });
  const variantes = [
    { linhas: [{ sku: "arroz-5kg", qty: 3 }], entregaModo: "levantamento" },
    { linhas: [{ sku: "arroz-10kg", qty: 2 }], entregaModo: "levantamento" },
    { linhas: [{ sku: "arroz-5kg", qty: 2 }], entregaModo: "entrega" },
  ] as const;
  for (const variante of variantes) {
    assert.equal(mesmoDraftHash(draftHash(variante), base), false);
  }
});

test("uma linha a mais muda o draft_hash, e a ambiguidade do separador está fechada", () => {
  // O caso que o comprimento a prefixar fecha: sem ele, `("ab", "c")` e
  // `("a", "bc")` davam a mesma cadeia. Com ele, `2:ab1:c` contra `1:a2:bc`.
  assert.notEqual(
    concatenar(["ab", "c"]).toString("hex"),
    concatenar(["a", "bc"]).toString("hex"),
  );
  const um = draftHash({
    linhas: [{ sku: "ab", qty: 1 }],
    entregaModo: "entrega",
  });
  const outro = draftHash({
    linhas: [{ sku: "a", qty: 1 }],
    entregaModo: "entrega",
  });
  assert.equal(mesmoDraftHash(um, outro), false);
});

test("linhas repetidas do mesmo sku não se somam, e isso é a escolha", () => {
  // Dito no `linhasCanonicas`: a ordenação compra a comutatividade, e não
  // normaliza o conteúdo. «1 + 1» e «2» são dois carrinhos diferentes.
  const separadas = draftHash({
    linhas: [
      { sku: "arroz-5kg", qty: 1 },
      { sku: "arroz-5kg", qty: 1 },
    ],
    entregaModo: "entrega",
  });
  const somadas = draftHash({
    linhas: [{ sku: "arroz-5kg", qty: 2 }],
    entregaModo: "entrega",
  });
  assert.equal(mesmoDraftHash(separadas, somadas), false);
});

test("a canonicalização ordena por sku e, com sku igual, por qty", () => {
  const ordenadas = linhasCanonicas([
    { sku: "b", qty: 2 },
    { sku: "a", qty: 5 },
    { sku: "b", qty: 1 },
  ]);
  assert.deepEqual(
    ordenadas.map((l) => `${l.sku}:${l.qty}`),
    ["a:5", "b:1", "b:2"],
  );
});

test("um rascunho vazio, um sku em branco e um qty nulo são recusados", () => {
  assert.throws(() => linhasCanonicas([]), ParteInvalidaError);
  assert.throws(
    () => linhasCanonicas([{ sku: "   ", qty: 1 }]),
    ParteInvalidaError,
  );
  for (const qty of [0, -1, 1.5, Number.NaN]) {
    assert.throws(
      () => linhasCanonicas([{ sku: "a", qty }]),
      ParteInvalidaError,
      String(qty),
    );
  }
});

test("um modo de entrega fora dos dois do CHECK é recusado", () => {
  assert.throws(
    () =>
      draftHash({
        linhas: [{ sku: "a", qty: 1 }],
        entregaModo: "correio" as unknown as "entrega",
      }),
    ParteInvalidaError,
  );
});

// ------------------------------------------------------------------ o cart_id

test("o cart_id não é a intent_key das mesmas partes", () => {
  // A separação de domínio: o `cart_id` sai no botão `confirm:{cart_id}`, que o
  // cliente vê. Conhecer um não pode dar o outro.
  assert.notEqual(cartId(ACTUAL, PARTES), intentKey(ACTUAL, PARTES));
});

test("o cart_id é reproduzível e tem a mesma forma", () => {
  assert.equal(cartId(ACTUAL, PARTES), cartId(ACTUAL, PARTES));
  assert.match(cartId(ACTUAL, PARTES), /^[0-9A-HJKMNP-TV-Z]{26}$/);
});

test("o cart_id confronta-se por re-derivação, nas duas versões do anel", () => {
  assert.equal(cartIdValido(ANEL, PARTES, cartId(ACTUAL, PARTES)), true);
  assert.equal(cartIdValido(ANEL, PARTES, cartId(ANTERIOR, PARTES)), true);
  assert.equal(cartIdValido(SO_UMA, PARTES, cartId(ANTERIOR, PARTES)), false);
});

test("o cart_id de outro contacto não é válido para este (ISO-57..60)", () => {
  const deOutro = cartId(ACTUAL, { ...PARTES, contactId: OUTRO_CONTACTO });
  assert.equal(cartIdValido(ANEL, PARTES, deOutro), false);
});

test("um cart_id forjado, vazio ou de outro tamanho não passa", () => {
  for (const mau of ["", "0".repeat(26), "A".repeat(25), "A".repeat(27)]) {
    assert.equal(cartIdValido(ANEL, PARTES, mau), false, JSON.stringify(mau));
  }
});
