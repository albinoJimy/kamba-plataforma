/**
 * O observador de produção do teste (KAM-202, critério 1), sobre um cliente de
 * duplo: o que ele faz com a linha que a base devolve. A consulta corre contra o
 * PostgreSQL em `tests_bd/activacao.bd.test.ts`.
 *
 * ```text
 * zero linhas                    os quatro factos falsos, sem conversa
 * a resposta nomeia os dois      resposta
 * so a loja, so o assistente     sem resposta
 * a frase do assistente          e a do registo do vendedor, letra a letra
 * ```
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { ASSISTENTE_DO_TESTE, ObservadorSql, SQL_FACTOS_DO_TESTE } from "../src/activacao/index.ts";
import { normalizarTexto } from "../src/activacao/smoke.ts";

const CASO = "55555555-5555-4555-8555-555555555555";
const CONVERSA = "44444444-4444-4444-8444-444444444444";
const DESDE = new Date("2026-11-20T10:00:00Z");
const ATE = new Date("2026-11-20T10:01:00Z");

function cliente(linhas: readonly Record<string, unknown>[]) {
  const pedidos: { sql: string; parametros: readonly unknown[] }[] = [];
  return {
    pedidos,
    async query<T>(sql: string, parametros: readonly unknown[] = []) {
      pedidos.push({ sql, parametros });
      return { rows: linhas as unknown as readonly T[] };
    },
  };
}

function linha(respostas: readonly string[], extra: Record<string, unknown> = {}) {
  return { conversation_id: CONVERSA, loja: "Loja da Zé", respostas, entregue: true, consentimento: true, ...extra };
}

describe("KAM-202 — o observador de produção", () => {
  it("sem «teste» na janela, os quatro factos sao falsos e nao ha conversa", async () => {
    const c = cliente([]);
    const f = await new ObservadorSql(c).factos(CASO, DESDE, ATE);
    assert.deepEqual(f, { inbound: false, resposta: false, entregue: false, consentimento: false, conversationId: null });
    assert.equal(c.pedidos.length, 1);
    assert.equal(c.pedidos[0]!.sql, SQL_FACTOS_DO_TESTE);
    assert.deepEqual(c.pedidos[0]!.parametros, [CASO, DESDE, ATE]);
  });

  it("a resposta que nomeia o assistente e a loja conta; as outras nao", async () => {
    const boa = "Olá! Sou o assistente automático de Loja da Zé. Em que posso ajudar?";
    const f = await new ObservadorSql(cliente([linha(["Um momento.", boa])])).factos(CASO, DESDE, ATE);
    assert.deepEqual(f, { inbound: true, resposta: true, entregue: true, consentimento: true, conversationId: CONVERSA });
    for (const so of [
      "Sou o assistente automatico desta loja.",
      "Bem-vindo a Loja da Zé!",
      "Sou o assistente da Loja da Zé.",
    ]) {
      const g = await new ObservadorSql(cliente([linha([so])])).factos(CASO, DESDE, ATE);
      assert.equal(g.resposta, false, so);
      assert.equal(g.inbound, true);
    }
  });

  it("sem nome da loja, nenhuma resposta identifica", async () => {
    const f = await new ObservadorSql(cliente([linha(["Sou o assistente automatico de ."], { loja: null })])).factos(
      CASO,
      DESDE,
      ATE,
    );
    assert.equal(f.resposta, false);
  });

  it("a entrega e o consentimento sao os da base, e um nulo e falso", async () => {
    const f = await new ObservadorSql(cliente([linha([], { entregue: null, consentimento: false })])).factos(CASO, DESDE, ATE);
    assert.equal(f.entregue, false);
    assert.equal(f.consentimento, false);
    assert.equal(f.resposta, false);
  });

  it("a frase do assistente e a da apresentacao do vendedor no registo", () => {
    // Mudar a frase de um lado sem o outro punha todos os testes a dar
    // `sem_resposta` — e so se via no primeiro onboarding.
    const registo = readFileSync(new URL("../../../registry/vendedor.yaml", import.meta.url), "utf8");
    const achado = /^\s*apresentacao:\s*"([^"]+)"/m.exec(registo);
    assert.ok(achado, "a apresentacao do vendedor mudou de forma");
    assert.ok(normalizarTexto(achado[1]!).includes(normalizarTexto(ASSISTENTE_DO_TESTE)));
    assert.ok(achado[1]!.includes("{loja}"), "a apresentacao deixou de nomear a loja");
  });

  it("KAM-235: a apresentacao que o AGR produz, com ou sem digitos no nome, identifica a loja", async () => {
    // A mesma fixture que o AGR tem de produzir letra a letra
    // (`services/agr/tests/test_grafos.py`, `TestLojaNaApresentacao`).
    const { casos } = JSON.parse(
      readFileSync(new URL("./fixtures/apresentacao_do_vendedor.json", import.meta.url), "utf8"),
    ) as { casos: { loja: string; frase: string }[] };
    assert.ok(casos.some((c) => /\d/.test(c.loja)), "a fixture tem de ter uma loja com digitos");
    const registo = readFileSync(new URL("../../../registry/vendedor.yaml", import.meta.url), "utf8");
    const bruta = /^\s*apresentacao:\s*"([^"]+)"/m.exec(registo)![1]!;
    for (const { loja, frase } of casos) {
      assert.equal(frase, bruta.replace("{loja}", loja), `a fixture e a do registo: ${loja}`);
      const resposta = `${frase}\nEm que posso ajudar?`;
      const f = await new ObservadorSql(cliente([linha([resposta], { loja })])).factos(CASO, DESDE, ATE);
      assert.equal(f.resposta, true, loja);
      // E a mesma frase com o nome de outra loja nao serve.
      const g = await new ObservadorSql(cliente([linha([resposta], { loja: "Outra Loja" })])).factos(CASO, DESDE, ATE);
      assert.equal(g.resposta, false, loja);
    }
  });
});
