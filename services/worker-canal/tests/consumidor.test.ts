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

import { randomBytes } from "node:crypto";

import { ChavesDeIdentidadeEmFaltaError } from "@kamba/core-ts/identity";
import { ArranqueAbortadoError } from "@kamba/core-ts/secrets";

import {
  ArranqueRecusadoError,
  SaidaSemPortasError,
  ambienteDoOutbound,
  efeitoDoConsumidor,
  exigirOrdemNosPagamentos,
  portasDoOutbound,
  type PortasDoOutbound,
} from "../src/consumidor.ts";

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

describe("o efeito do consumidor, pelo nome (KAM-224)", () => {
  const ligacaoQueNaoServe = {
    query: async () => {
      throw new Error("nao devia ser chamada");
    },
  };
  const semPortas: PortasDoOutbound = {
    meta: null,
    destinatario: null,
    tomar: async () => ligacaoQueNaoServe,
    devolver: () => {},
  };

  it("o outbound recusa arrancar sem o cliente da Meta e sem o destinatário, e nomeia os dois", () => {
    assert.throws(
      () => efeitoDoConsumidor("outbound", semPortas),
      (erro: unknown) => {
        assert.ok(erro instanceof SaidaSemPortasError);
        assert.deepEqual(erro.emFalta, ["o cliente da Meta", "o destinatario"]);
        assert.match(erro.message, /KAM-227/);
        return true;
      },
    );
  });

  it("basta faltar uma das duas para recusar", () => {
    const meta = async () => ({ enviar: async () => ({ ok: true as const, wamid: "w" }) });
    assert.throws(() => efeitoDoConsumidor("outbound", { ...semPortas, meta }), SaidaSemPortasError);
  });

  it("com as duas, o outbound tem efeito, e um evento de outro canal não toca na base", async () => {
    const efeito = efeitoDoConsumidor("outbound", {
      ...semPortas,
      meta: async () => ({ enviar: async () => ({ ok: true as const, wamid: "w" }) }),
      destinatario: async () => ({ bsuid: "AO.ENSAIOENSAIOENSAIO0001", telefone: null }),
    });
    const tenant = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
    const contacto = "2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901";
    const bd = new BdFalsa();
    await efeito(bd as never, {
      tipo: "agent.replied",
      tenant_id: tenant,
      payload: {
        reply_id: "0192f1c4-8c2d-7e3f-9a4b-5c6d7e8f9a0b",
        thread_id: `${tenant}:${contacto}`,
        conversation_id: "7a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d",
        contact_id: contacto,
        canal: "painel",
      },
    } as never);
    assert.deepEqual(bd.instrucoes, []);
  });

  it("os outros nomes ficam com o efeito do esqueleto, sem portas", async () => {
    const efeito = efeitoDoConsumidor("agr_vendedor", semPortas);
    const bd = new BdFalsa();
    await efeito(bd as never, {} as never);
    assert.deepEqual(bd.instrucoes, []);
  });
});

describe("as portas de produção do outbound, e o arranque em prod (KAM-227, critério 3)", () => {
  /** Uma chave versionada de ensaio, na forma do cofre: `<kid>:<base64 de 32 octetos>`. */
  const chave = (kid: string): string => `${kid}:${randomBytes(32).toString("base64")}`;
  const completo = (ambiente: string): Record<string, string> => ({
    KAMBA_ENV: ambiente,
    KAMBA_SECRET_KEK_TOKEN_CLIENTE: chave("t1"),
    KAMBA_SECRET_KEK_CONTACT_DEK: chave("k1"),
  });
  const ligacoes = {
    tomarIdentidade: async () => {
      throw new Error("o arranque nao abre ligacoes de identidade");
    },
    devolverIdentidade: () => {},
  };

  it("em staging, com o cofre completo, monta as duas portas sem abrir ligação nenhuma", async () => {
    const portas = await portasDoOutbound({ env: completo("staging"), ...ligacoes });
    assert.equal(typeof portas.meta, "function");
    assert.equal(typeof portas.destinatario, "function");
  });

  it("**em prod arranca**, com as chaves no ambiente do lançador (decisão do fundador, 2026-11-20)", async () => {
    // A medição do critério 3: o critério 9 do KAM-008 emendado deixa o
    // provedor de ambiente arrancar em `prod`, com as chaves lá.
    const portas = await portasDoOutbound({ env: completo("prod"), ...ligacoes });
    assert.equal(typeof portas.meta, "function");
    assert.equal(typeof portas.destinatario, "function");
  });

  it("em prod, sem a KEK das DEK de contacto (ausente, vazia ou mal formada), não arranca", async () => {
    // O fail-closed que ficou do critério 9 do KAM-008.
    for (const valor of [undefined, "", "   ", "k1:nao-e-base64"]) {
      const env = completo("prod");
      if (valor === undefined) delete env["KAMBA_SECRET_KEK_CONTACT_DEK"];
      else env["KAMBA_SECRET_KEK_CONTACT_DEK"] = valor;
      await assert.rejects(portasDoOutbound({ env, ...ligacoes }), (erro: unknown) => {
        if (!(erro instanceof ChavesDeIdentidadeEmFaltaError)) return false;
        assert.deepEqual(erro.refs, ["kek_contact_dek"]);
        return true;
      });
    }
  });

  it("em prod, o pepper do HMAC não é pedido: o outbound só lê endpoints", async () => {
    const env = completo("prod");
    assert.equal(env["KAMBA_SECRET_PEPPER_CONTACT_HMAC"], undefined);
    await portasDoOutbound({ env, ...ligacoes });
  });

  it("sem a kek_token_cliente o arranque aborta, e nomeia o segredo", async () => {
    const env = completo("prod");
    delete env["KAMBA_SECRET_KEK_TOKEN_CLIENTE"];
    await assert.rejects(portasDoOutbound({ env, ...ligacoes }), (erro: unknown) => {
      assert.ok(erro instanceof ArranqueAbortadoError);
      assert.match(erro.message, /kek_token_cliente/);
      return true;
    });
  });

  it("em dev a kek_token_cliente não é obrigatória, como no inventário", async () => {
    const env = completo("dev");
    delete env["KAMBA_SECRET_KEK_TOKEN_CLIENTE"];
    const portas = await portasDoOutbound({ env, ...ligacoes });
    assert.equal(typeof portas.meta, "function");
  });

  it("o ambiente não tem omissão: ausente ou desconhecido recusa", () => {
    assert.throws(() => ambienteDoOutbound({}), /KAMBA_ENV/);
    assert.throws(() => ambienteDoOutbound({ KAMBA_ENV: "producao" }), /KAMBA_ENV/);
    assert.equal(ambienteDoOutbound({ KAMBA_ENV: "prod" }), "prod");
  });
});
