/**
 * As peças puras do contacto da encomenda (KAM-206): a regra, a escolha do
 * telefone e a máscara. Os telefones são fictícios, com 999.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ORDER_STATES } from "../src/port/index.ts";
import {
  contactoNecessario,
  ESTADOS_COM_CONTACTO,
  mascarar,
  telefoneDaEncomenda,
} from "../src/orders/contacto.ts";

const AGORA = new Date("2026-11-20T10:00:00.000Z");
const DEPOIS = new Date("2026-12-20T10:00:00.000Z");
const ANTES = new Date("2026-11-19T10:00:00.000Z");

test("a regra: so os quatro estados em que o dono age, e todos sao estados da porta", () => {
  assert.deepEqual(
    ORDER_STATES.filter((e) => contactoNecessario(e)),
    ["pendente_confirmacao", "paga", "em_entrega", "entrega_falhada"],
  );
  for (const e of ESTADOS_COM_CONTACTO) assert.ok((ORDER_STATES as readonly string[]).includes(e), e);
  for (const fora of ["criada", "aguarda_pagamento", "entregue", "em_disputa", "reembolsada", "cancelada", "expirada"]) {
    assert.equal(contactoNecessario(fora), false, fora);
  }
  assert.equal(contactoNecessario("inventado"), false);
});

test("a mascara mostra os tres ultimos digitos e nada do resto, nem o comprimento", () => {
  assert.equal(mascarar("+244 999 000 789"), "••• ••• 789");
  assert.equal(mascarar("244999000789"), "••• ••• 789");
  assert.equal(mascarar("999000789"), "••• ••• 789");
  for (const t of ["+244 999 000 789", "999000789"]) {
    const m = mascarar(t) ?? "";
    assert.doesNotMatch(m, /244|999|000/);
  }
  assert.equal(mascarar("789"), null);
  assert.equal(mascarar(""), null);
});

test("o telefone da encomenda: contacto_pedido primeiro, depois entrega, nunca pagamento_express nem expirado", () => {
  assert.equal(
    telefoneDaEncomenda(
      [
        { finalidade: "pagamento_express", telefone: "+244 999 000 111", expiraAt: DEPOIS },
        { finalidade: "entrega", telefone: "+244 999 000 222", expiraAt: DEPOIS },
        { finalidade: "contacto_pedido", telefone: "+244 999 000 333", expiraAt: DEPOIS },
      ],
      AGORA,
    ),
    "+244 999 000 333",
  );
  assert.equal(
    telefoneDaEncomenda(
      [
        { finalidade: "contacto_pedido", telefone: "+244 999 000 333", expiraAt: ANTES },
        { finalidade: "entrega", telefone: "+244 999 000 222", expiraAt: DEPOIS },
      ],
      AGORA,
    ),
    "+244 999 000 222",
  );
  assert.equal(
    telefoneDaEncomenda([{ finalidade: "pagamento_express", telefone: "+244 999 000 111", expiraAt: DEPOIS }], AGORA),
    null,
  );
  assert.equal(telefoneDaEncomenda([{ finalidade: "entrega", telefone: "+244 999 000 222", expiraAt: AGORA }], AGORA), null);
});
