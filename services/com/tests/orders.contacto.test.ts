/**
 * As peças puras do contacto da encomenda (KAM-206): a regra, a escolha do
 * telefone e a máscara. Os telefones são fictícios, com 999.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ORDER_STATES, type Ctx, type ResultadoFinal } from "../src/port/index.ts";
import {
  ACCAO_DO_CONTACTO,
  ENTIDADE_DO_CONTACTO,
  contactoDaEncomenda,
  contactoNecessario,
  ESTADOS_COM_CONTACTO,
  mascarar,
  SQL_AUDITAR_CONTACTO,
  telefoneDaEncomenda,
  textoDaAuditoria,
  type EncomendaDoContacto,
  type MontagemDoContacto,
  type TelefoneDoContacto,
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

// ------------------------------------------------------------ a operação

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ORDEM = "0000000a-0000-4000-8000-0000000000d1";
const CONTACTO = "0000000c-0000-4000-8000-0000000000c1";
const CTX_DONO: Ctx = { tenantId: TENANT, actor: { kind: "dono", id: "caso-a" }, traceId: "t" };

interface Registo {
  readonly passos: string[];
  readonly auditorias: (readonly unknown[])[];
}

function montagem(
  estado: string,
  telefones: readonly TelefoneDoContacto[] | null = [
    { finalidade: "contacto_pedido", telefone: "+244 999 000 789", expiraAt: DEPOIS },
  ],
  lida: ResultadoFinal<EncomendaDoContacto> | null = null,
): { m: MontagemDoContacto; r: Registo } {
  const r: Registo = { passos: [], auditorias: [] };
  const m: MontagemDoContacto = {
    async lerEncomenda(ctx, orderId) {
      r.passos.push(`ler:${ctx.tenantId}:${orderId}`);
      return lida ?? { tipo: "ok", valor: { orderId, estado, contactId: CONTACTO } };
    },
    contactos: {
      async telefones(tenantId, contactId, antes) {
        r.passos.push(`identidade:${tenantId}:${contactId}`);
        await antes({
          async query(sql: string, parametros: readonly unknown[] = []) {
            r.passos.push("auditar");
            assert.equal(sql, SQL_AUDITAR_CONTACTO);
            r.auditorias.push(parametros);
            return { rows: [] };
          },
        });
        r.passos.push("decifrar");
        return telefones;
      },
    },
    agora: () => AGORA,
  };
  return { m, r };
}

test("a operacao: le a encomenda, audita na transaccao da identidade antes de decifrar, e devolve so a mascara", async () => {
  const { m, r } = montagem("paga");
  const resultado = await contactoDaEncomenda(m, CTX_DONO, ORDEM);
  assert.deepEqual(resultado, { tipo: "ok", valor: { orderId: ORDEM, telefoneMascarado: "••• ••• 789" } });
  assert.deepEqual(r.passos, [`ler:${TENANT}:${ORDEM}`, `identidade:${TENANT}:${CONTACTO}`, "auditar", "decifrar"]);
  assert.deepEqual(r.auditorias, [[TENANT, "caso-a", ORDEM, Buffer.from(textoDaAuditoria(ORDEM, "paga"), "utf8")]]);
  assert.equal(textoDaAuditoria(ORDEM, "paga"), `order.contact_view\x1f${ORDEM}\x1fpaga`);
  // Adversarial: nem o telefone em claro, nem os seus digitos de cabeca, saem da operacao.
  assert.doesNotMatch(JSON.stringify(resultado), /244|999 000/);
  assert.doesNotMatch(JSON.stringify(r.auditorias), /999|789/);
});

test("a operacao: fora da regra e NOT_FOUND, sem auditoria e sem decifra", async () => {
  for (const estado of ["aguarda_pagamento", "entregue", "em_disputa", "cancelada"]) {
    const { m, r } = montagem(estado);
    assert.deepEqual(await contactoDaEncomenda(m, CTX_DONO, ORDEM), { tipo: "erro", erro: "NOT_FOUND" }, estado);
    assert.deepEqual(r.passos, [`ler:${TENANT}:${ORDEM}`], estado);
  }
});

test("a operacao: a encomenda de outro tenant, uma que nao existe e um id mal formado dao o mesmo NOT_FOUND", async () => {
  for (const erroDaLeitura of ["NOT_FOUND", "TENANT_MISMATCH", "VALIDATION_ERROR"] as const) {
    const { m, r } = montagem("paga", undefined, { tipo: "erro", erro: erroDaLeitura });
    assert.deepEqual(await contactoDaEncomenda(m, CTX_DONO, ORDEM), { tipo: "erro", erro: "NOT_FOUND" }, erroDaLeitura);
    assert.ok(!r.passos.includes("auditar"));
  }
  const { m, r } = montagem("paga");
  assert.deepEqual(await contactoDaEncomenda(m, CTX_DONO, "nao-e-uuid"), { tipo: "erro", erro: "NOT_FOUND" });
  assert.deepEqual(r.passos, []);
});

test("a operacao: so o dono; o agente, o sistema e ops recebem NOT_FOUND sem nada correr", async () => {
  for (const kind of ["agente", "sistema", "ops"] as const) {
    const { m, r } = montagem("paga");
    const ctx: Ctx = { ...CTX_DONO, actor: { kind, id: "x" } };
    assert.deepEqual(await contactoDaEncomenda(m, ctx, ORDEM), { tipo: "erro", erro: "NOT_FOUND" }, kind);
    assert.deepEqual(r.passos, [], kind);
  }
});

test("a operacao: sem a identidade e UPSTREAM_DOWN; contacto apagado e sem telefone dao mascara nula", async () => {
  const { m } = montagem("paga");
  assert.deepEqual(await contactoDaEncomenda({ ...m, contactos: null }, CTX_DONO, ORDEM), { tipo: "erro", erro: "UPSTREAM_DOWN" });
  const apagado = montagem("paga", null);
  assert.deepEqual(await contactoDaEncomenda(apagado.m, CTX_DONO, ORDEM), {
    tipo: "ok",
    valor: { orderId: ORDEM, telefoneMascarado: null },
  });
  const soPagamento = montagem("entrega_falhada", [
    { finalidade: "pagamento_express", telefone: "+244 999 000 111", expiraAt: DEPOIS },
  ]);
  assert.deepEqual(await contactoDaEncomenda(soPagamento.m, CTX_DONO, ORDEM), {
    tipo: "ok",
    valor: { orderId: ORDEM, telefoneMascarado: null },
  });
});

test("a operacao: se a auditoria falha, a decifra nao corre e o erro sobe", async () => {
  const { m, r } = montagem("paga");
  const contactos = m.contactos!;
  const falhada: MontagemDoContacto = {
    ...m,
    contactos: {
      async telefones(tenantId, contactId, antes) {
        return contactos.telefones(tenantId, contactId, async () => {
          await antes({ async query() { throw new Error("audit_append recusado"); } });
        });
      },
    },
  };
  await assert.rejects(contactoDaEncomenda(falhada, CTX_DONO, ORDEM), /audit_append recusado/);
  assert.ok(!r.passos.includes("decifrar"));
});

test("o SQL da auditoria leva a accao e a entidade por extenso, iguais as constantes", () => {
  const esperado = ["'owner', $2", `'${ACCAO_DO_CONTACTO}'`, `'${ENTIDADE_DO_CONTACTO}'`, "$3, NULL"].join(", ");
  assert.ok(SQL_AUDITAR_CONTACTO.includes(esperado), SQL_AUDITAR_CONTACTO);
  assert.doesNotMatch(SQL_AUDITAR_CONTACTO, /\$\{/);
});
