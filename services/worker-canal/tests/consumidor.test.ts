/**
 * O arranque do consumidor recusa-se com uma subscrição de pagamento sem ordem
 * (KAM-006, critério 7).
 *
 * É a **segunda metade** do critério. A primeira é a restrição
 * `evt_subscricoes_payment_exige_ordem` da revisão 0005, que faz a base recusar
 * a configuração errada — essa tem prova em
 * `db/tests_eventos_consumo/test_consumo.py`, contra um PostgreSQL real. Esta
 * continua a valer se alguém largar a restrição, e é por isso que existem as
 * duas: uma guarda que depende da outra não é uma guarda.
 *
 * O que se exercita é a função, não o processo. Levantar o processo inteiro
 * para o ver falhar provava menos — não distinguiria «recusou por causa da
 * subscrição» de «não arrancou porque falta uma variável de ambiente» — e
 * demorava mais.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SQL_PAYMENT_SEM_ORDEM } from "@kamba/core-ts/eventos";

import { ArranqueRecusadoError, exigirOrdemNosPagamentos } from "../src/consumidor.ts";

/**
 * Base falsa: devolve as linhas que lhe dizem e guarda o que lhe perguntaram.
 *
 * O campo é declarado e atribuído à mão, e não por propriedade de parâmetro:
 * o `erasableSyntaxOnly` do `tsconfig.base.json` proíbe-a, porque é sintaxe
 * que o Node não consegue apagar ao correr TypeScript directamente.
 */
class BdFalsa {
  readonly instrucoes: string[] = [];
  readonly #linhas: Record<string, unknown>[];

  constructor(linhas: Record<string, unknown>[] = []) {
    this.#linhas = linhas;
  }

  async query(sql: string): Promise<{ rows: Record<string, unknown>[] }> {
    this.instrucoes.push(sql.trim());
    return { rows: this.#linhas };
  }
}

describe("o arranque do consumidor", () => {
  it("passa quando não há subscrições de pagamento sem ordem", async () => {
    const bd = new BdFalsa([]);
    await exigirOrdemNosPagamentos(bd);
    assert.deepEqual(bd.instrucoes, [SQL_PAYMENT_SEM_ORDEM.trim()]);
  });

  it("recusa, e nomeia a subscrição culpada", async () => {
    const bd = new BdFalsa([
      { consumer: "pagamentos", tipo: "payment.confirmed" },
      { consumer: "contabilidade", tipo: "payment.failed" },
    ]);
    await assert.rejects(exigirOrdemNosPagamentos(bd), (erro: unknown) => {
      assert.ok(erro instanceof ArranqueRecusadoError);
      // Nomear importa: a mensagem é o que alguém lê às três da manhã, e
      // «arranque recusado» sem o nome da subscrição obriga a ir procurar.
      assert.match(erro.message, /pagamentos\/payment\.confirmed/);
      assert.match(erro.message, /contabilidade\/payment\.failed/);
      assert.deepEqual(erro.subscricoes, [
        "pagamentos/payment.confirmed",
        "contabilidade/payment.failed",
      ]);
      return true;
    });
  });

  it("a mensagem diz **porquê**, e não só que recusou", async () => {
    // Sem o motivo, a resposta óbvia a um arranque recusado é desligar a
    // verificação. Com ele — aplicar «paga» antes de «aguarda_pagamento» é uma
    // transição inválida — a resposta óbvia passa a ser corrigir a subscrição.
    const bd = new BdFalsa([{ consumer: "c", tipo: "payment.confirmed" }]);
    await assert.rejects(exigirOrdemNosPagamentos(bd), /transição inválida/);
  });
});
