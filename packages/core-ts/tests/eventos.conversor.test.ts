/**
 * O gancho de conversão de versão (KAM-005, `docs/tecnica/06` §6.6).
 *
 * Duas coisas a provar: que o registo do processo está **vazio** — é o que o
 * ticket pede — e que vazio não quer dizer inerte.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CONVERSORES,
  ConversaoInvalidaError,
  type Envelope,
  RegistoDeConversores,
  SemConversorError,
  lerEnvelope,
} from "../src/eventos/index.ts";

function envelope(versao: number): Envelope {
  return lerEnvelope({
    id: "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44",
    tipo: "order.created",
    versao,
    tenant_id: "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60",
    ocorrido_em: "2026-11-02T14:03:11.482Z",
    registado_em: "2026-11-02T14:03:11.610Z",
    produtor: null,
    agregado: { tipo: "order", id: "o1", seq: 4 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P1",
    finalidades: ["transacao"],
    payload: { order_id: "o1" },
  });
}

describe("o registo do processo", () => {
  it("esta vazio — e o que o ticket pede («gancho vazio»)", () => {
    assert.equal(CONVERSORES.tamanho, 0);
  });
});

describe("converter", () => {
  it("v1 para um consumidor de v1: devolve o mesmo envelope", () => {
    const registo = new RegistoDeConversores();
    const original = envelope(1);
    assert.equal(registo.converter(original, 1), original);
  });

  it("v1 para um consumidor que aceita v2: devolve o mesmo (nao se sobe)", () => {
    const registo = new RegistoDeConversores();
    const original = envelope(1);
    assert.equal(registo.converter(original, 2), original);
  });

  it("v2 para um consumidor de v1 **sem** conversor lanca", () => {
    const registo = new RegistoDeConversores();
    assert.throws(() => registo.converter(envelope(2), 1), (erro: unknown) => {
      assert.ok(erro instanceof SemConversorError);
      assert.equal(erro.de, 2);
      assert.equal(erro.para, 1);
      assert.match(erro.message, /NAO e descartado/);
      return true;
    });
  });

  it("com conversor registado, converte", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({ ...e, versao: 1 }));
    assert.equal(registo.tem("order.created", 2, 1), true);
    const convertido = registo.converter(envelope(2), 1);
    assert.equal(convertido.versao, 1);
    assert.equal(convertido.id, envelope(2).id);
  });

  it("o conversor de um tipo nao serve outro", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({ ...e, versao: 1 }));
    const outro = { ...envelope(2), tipo: "order.paid" } as Envelope;
    assert.throws(() => registo.converter(outro, 1), SemConversorError);
  });
});

describe("um conversor tem de preservar `id` e `agregado.seq` (§6.6)", () => {
  it("mudar o `id` e recusado: a deduplicacao por jobId deixa de valer", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({
      ...e,
      versao: 1,
      id: "11111111-1111-1111-1111-111111111111",
    }));
    assert.throws(() => registo.converter(envelope(2), 1), (erro: unknown) => {
      assert.ok(erro instanceof ConversaoInvalidaError);
      assert.match(erro.message, /mudou o `id`/);
      return true;
    });
  });

  it("mudar o `agregado.seq` e recusado: a ordem causal quebra", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({
      ...e,
      versao: 1,
      agregado: { ...e.agregado, seq: 99 },
    }));
    assert.throws(
      () => registo.converter(envelope(2), 1),
      /mudou o `agregado.seq`/,
    );
  });

  it("devolver outra `versao` e recusado", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({ ...e, versao: 3 }));
    assert.throws(() => registo.converter(envelope(2), 1), /devolveu `versao` 3/);
  });

  it("registar para cima e recusado: converte-se para baixo", () => {
    const registo = new RegistoDeConversores();
    assert.throws(
      () => registo.registar("order.created", 1, 2, (e) => e),
      /converte-se para \*\*baixo\*\*/,
    );
  });
});
