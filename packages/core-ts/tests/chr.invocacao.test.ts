/**
 * O *job* que o CHR entrega ao AGR (KAM-014, critério 6).
 *
 * O que aqui se prova é o que o critério pede, campo a campo: os sete nomes, o
 * `thread_id`, **e as três ausências** — sem telefone, sem BSUID, sem
 * `display_name`. E prova-se contra o **esquema publicado**, nos dois sentidos:
 * um campo que o esquema exija e o código não escreva, ou o contrário, falha
 * aqui.
 *
 * A validação é estrutural e não por validador de JSON Schema, como no
 * `schemas.test.ts` do pacote de contratos e pela mesma razão: o pacote não
 * traz um validador, e o que se quer guardar é que o esquema e o código não
 * divergiram.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { AGENT_INVOCATION_V1_PATH } from "@kamba/contracts";

import { jobIdDe, montarInvocacao } from "../src/chr/index.ts";
import { InvocacaoIncompletaError } from "../src/chr/invocacao.ts";
import { linhaDeCanal } from "./apoio/chr-base-falsa.ts";
import { canalDaLinha } from "../src/chr/index.ts";

const esquema = JSON.parse(readFileSync(AGENT_INVOCATION_V1_PATH, "utf8"));

const TENANT = "11111111-1111-4111-8111-111111111111";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const CONVERSA = "44444444-4444-4444-8444-444444444444";

type Pedido = Parameters<typeof montarInvocacao>[0];

function invocacao(troca: Partial<Pedido> = {}) {
  return montarInvocacao({
    contexto: canalDaLinha(linhaDeCanal({ tenant_id: TENANT })).contexto,
    contactId: CONTACTO,
    conversationId: CONVERSA,
    wamid: "wamid.HBgLMjQ0OTIz",
    type: "text",
    modo: "bot",
    ...troca,
  });
}

describe("o contrato agent_invocation", () => {
  it("o esquema exige exactamente os campos que o codigo escreve", () => {
    assert.deepEqual(
      [...esquema.required].sort(),
      Object.keys(invocacao()).sort(),
    );
  });

  it("o esquema fecha-se a campos novos", () => {
    // `additionalProperties: false` e o que torna este contrato uma garantia
    // sobre o que **nao** esta la: sem ele, um telefone acrescentado por
    // engano passava a validacao.
    assert.equal(esquema.additionalProperties, false);
  });

  it("os sete campos do criterio estao no esquema, pelo nome", () => {
    for (const campo of [
      "tenant_id",
      "contact_id",
      "conversation_id",
      "channel_id",
      "wamid",
      "type",
      "modo",
    ]) {
      assert.ok(esquema.properties[campo] !== undefined, campo);
      assert.ok([...esquema.required].includes(campo), campo);
    }
  });

  it("nao ha telefone, BSUID nem display_name no esquema", () => {
    const texto = JSON.stringify(Object.keys(esquema.properties));
    for (const proibido of ["phone", "telefone", "msisdn", "bsuid", "user_id", "display_name"]) {
      assert.ok(!texto.includes(proibido), proibido);
    }
  });

  it("o dominio de `modo` e o de `conversations.mode`", async () => {
    const { MODOS } = await import("../src/chr/index.ts");
    assert.deepEqual([...esquema.properties.modo.enum].sort(), [...MODOS].sort());
  });

  it("o dominio de `type` e a lista fechada de `wa_type`, com `outro`", async () => {
    const { WA_TYPES } = await import("../src/entrada/index.ts");
    assert.deepEqual(
      [...esquema.properties.type.enum].sort(),
      [...WA_TYPES, "outro"].sort(),
    );
  });

  it("o padrao do `thread_id` e `{uuid}:{uuid}` e recusa um telefone", () => {
    const padrao = new RegExp(esquema.properties.thread_id.pattern);
    assert.ok(padrao.test(`${TENANT}:${CONTACTO}`));
    assert.ok(!padrao.test(`${TENANT}:244923000000`));
    assert.ok(!padrao.test(TENANT));
  });

  it("o padrao do `wamid` aceita um wamid e o resumo canonico do KAM-013", () => {
    const padrao = new RegExp(esquema.properties.wamid.pattern);
    assert.ok(padrao.test("wamid.HBgLMjQ0OTIzMDAwMDAwFQIAERgSN0"));
    assert.ok(padrao.test("k_0123456789abcdef0123456789abcdef"));
    assert.ok(!padrao.test(""));
  });
});

describe("montarInvocacao", () => {
  it("o `thread_id` e `{tenant_id}:{contact_id}`", () => {
    assert.equal(invocacao().thread_id, `${TENANT}:${CONTACTO}`);
  });

  it("o `channel_id` e o do canal, e nao o `phone_number_id`", () => {
    // O identificador da Meta nao sai do CHR: quem o tem e o resolvedor, e
    // quem recebe o *job* nao precisa dele para nada.
    const montada = invocacao();
    assert.equal(montada.channel_id, linhaDeCanal().channel_id);
    assert.ok(!JSON.stringify(montada).includes("pnid"));
  });

  it("o `vertical` vem do contexto, que e o que o AgentRegistry usa", () => {
    assert.equal(invocacao().vertical, "vendedor");
  });

  it("nao ha por onde passar um telefone: os argumentos nao o aceitam", () => {
    // E a forma de o ADR-010 ser verdade por construcao e nao por revisao. O
    // que esta afirmacao prende e que nenhuma chave do *job* leva dado
    // pessoal, agora e depois de alguem lhe acrescentar um campo.
    const chaves = Object.keys(invocacao());
    assert.deepEqual(chaves.filter((c) => /phone|telefone|bsuid|nome|name/.test(c)), []);
  });

  it("um `contact_id`, `conversation_id` ou `wamid` vazio lanca", () => {
    assert.throws(() => invocacao({ contactId: "" }), InvocacaoIncompletaError);
    assert.throws(() => invocacao({ conversationId: "" }), InvocacaoIncompletaError);
    assert.throws(() => invocacao({ wamid: "" }), InvocacaoIncompletaError);
  });
});

describe("jobIdDe", () => {
  it("e determinístico: o mesmo par da a mesma chave", () => {
    assert.equal(jobIdDe(TENANT, "wamid.AAA"), jobIdDe(TENANT, "wamid.AAA"));
  });

  it("**nao** leva o `wamid` em claro", () => {
    // O `wamid` leva o numero do interlocutor em base64 (docs/logs.md §2.1), e
    // uma chave de *job* e lida por quem opera a fila.
    const chave = jobIdDe(TENANT, "wamid.HBgLMjQ0OTIzMDAwMDAw");
    assert.ok(!chave.includes("wamid"));
    assert.ok(!chave.includes("MjQ0OTIz"));
    assert.match(chave, /^[0-9a-f]{64}$/);
  });

  it("o `tenant_id` entra na chave: dois tenants nao colidem", () => {
    const outro = "55555555-5555-4555-8555-555555555555";
    assert.notEqual(jobIdDe(TENANT, "wamid.AAA"), jobIdDe(outro, "wamid.AAA"));
  });

  it("dois `wamid` diferentes dao chaves diferentes", () => {
    assert.notEqual(jobIdDe(TENANT, "wamid.AAA"), jobIdDe(TENANT, "wamid.BBB"));
  });
});
