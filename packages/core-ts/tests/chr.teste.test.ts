/**
 * O sinal do teste ponta a ponta, do webhook à conversa (KAM-202, critério 1).
 *
 * ```text
 * explosao   um texto que e a palavra do teste da `eTeste: true`; tudo o resto
 *            nao tem o campo, e o corpo nao sai no evento
 * CHR        com `eTeste`, grava o instante em `teste_recebido_at`, na mesma
 *            transaccao que abre a conversa e com o mesmo relogio; sem ele, nao
 *            escreve nada a mais
 * ```
 *
 * A instrução e o privilégio provam-se contra a base em
 * `packages/core-ts/tests_bd/activacao.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  Chr,
  type ClienteDoChr,
  type EntregaDoChr,
  MetricasDoChr,
  ResolvedorDeCanal,
  SQL_MARCAR_TESTE_RECEBIDO,
} from "../src/chr/index.ts";
import type { AgentInvocation } from "../src/chr/index.ts";
import { explodir } from "../src/entrada/explosao.ts";
import { linhaDeCanal } from "./apoio/chr-base-falsa.ts";

const PNID = "999000000000011";
const WABA = "999000000000012";
const TENANT = "11111111-1111-4111-8111-111111111111";
const CANAL = "22222222-2222-4222-8222-222222222222";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const CONVERSA = "44444444-4444-4444-8444-444444444444";
const AGORA = new Date("2026-11-20T10:00:00.000Z");

function corpoDe(mensagem: Readonly<Record<string, unknown>>): unknown {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: WABA,
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: "244 999 000 000", phone_number_id: PNID },
              messages: [
                { id: "wamid.HBgLOTk5.sinal", from: "244 999 000 002", timestamp: "1763460000", ...mensagem },
              ],
            },
          },
        ],
      },
    ],
  };
}

function texto(body: unknown): unknown {
  return corpoDe({ type: "text", text: { body } });
}

function evento(corpo: unknown) {
  const { eventos } = explodir(corpo, "b".repeat(64));
  assert.equal(eventos.length, 1);
  return eventos[0]!;
}

class CanalFalso implements ClienteDoChr {
  async query(_sql: string, parametros: readonly unknown[] = []) {
    return parametros[0] === PNID
      ? { rows: [linhaDeCanal({ tenant_id: TENANT, channel_id: CANAL })] }
      : { rows: [] };
  }
}

/** A conversa, o papel e o sinal. Regista cada instrução pela ordem, com a transacção. */
class Base implements ClienteDoChr {
  readonly feitas: { sql: string; parametros: readonly unknown[]; transaccao: number }[] = [];
  transaccao = 0;
  async query(sql: string, parametros: readonly unknown[] = []) {
    this.feitas.push({ sql, parametros, transaccao: this.transaccao });
    if (sql.includes("INSERT INTO platform.conversations")) return { rows: [{ id: CONVERSA, mode: "bot" }] };
    if (/SELECT\s+papel/i.test(sql)) return { rows: [{ papel: "cliente" }] };
    return { rows: [] };
  }
}

class Entrega implements EntregaDoChr {
  readonly aoAgr: AgentInvocation[] = [];
  async agr(invocacao: AgentInvocation): Promise<void> {
    this.aoAgr.push(invocacao);
  }
  async dono(): Promise<void> {}
}

function chr() {
  const base = new Base();
  const instancia = new Chr({
    resolvedor: new ResolvedorDeCanal(new CanalFalso()),
    contacto: async () => ({ contactId: CONTACTO }),
    entrega: new Entrega(),
    quarentena: async () => {},
    metricas: new MetricasDoChr(),
    comTenant: async (_tenant, trabalho) => {
      base.transaccao += 1;
      return trabalho(base);
    },
    agora: () => AGORA,
  });
  return { instancia, base };
}

describe("KAM-202 — o sinal do teste sai da explosao", () => {
  it("a palavra do teste, com caixa, acentos, espacos e pontuacao a volta, da `eTeste`", () => {
    for (const body of ["teste", "Teste", "TESTE", "  teste  ", "teste!", "«Teste».", "tésté"]) {
      const e = evento(texto(body));
      assert.equal(e.eTeste, true, JSON.stringify(body));
      // KAM-232: o corpo de uma `text` segue no `texto`, para o CHR o gravar na
      // fonte persistida; fora desse campo continua a nao entrar no evento.
      const { eTeste: _sinal, texto: corpo, ...resto } = e;
      assert.equal(typeof corpo, "string", JSON.stringify(body));
      assert.ok(!JSON.stringify(resto).toLowerCase().includes("test"), "o corpo so entra no `texto`");
    }
  });

  it("outro texto, outro tipo, ou um corpo que nao e texto nao tem o campo", () => {
    for (const corpo of [
      texto("testes"),
      texto("e um teste"),
      texto(""),
      texto(7),
      texto(null),
      corpoDe({ type: "text", text: "teste" }),
      corpoDe({ type: "image", image: { caption: "teste" } }),
      corpoDe({ type: "interactive", interactive: { type: "button_reply", button_reply: { id: "teste", title: "teste" } } }),
      // Um texto com o tipo errado: o tipo e que manda.
      corpoDe({ type: "button", text: { body: "teste" } }),
    ]) {
      assert.equal("eTeste" in evento(corpo), false);
    }
  });
});

describe("KAM-202 — o CHR grava o instante do teste na conversa", () => {
  it("com `eTeste`, a conversa ganha o instante, na transaccao que a abre e com o mesmo relogio", async () => {
    const { instancia, base } = chr();
    const r = await instancia.tratar(evento(texto("teste")));
    assert.equal(r.desfecho, "encaminhado");
    const abrir = base.feitas.find((f) => f.sql.includes("INSERT INTO platform.conversations"));
    const sinal = base.feitas.filter((f) => f.sql === SQL_MARCAR_TESTE_RECEBIDO);
    assert.ok(abrir !== undefined);
    assert.equal(sinal.length, 1);
    assert.deepEqual(sinal[0]!.parametros, [TENANT, CONVERSA, AGORA]);
    assert.equal(sinal[0]!.transaccao, abrir.transaccao);
    // E o instante e o mesmo da janela: o `last_inbound_at` da conversa.
    assert.deepEqual(abrir.parametros[3], AGORA);
  });

  it("sem `eTeste`, nenhuma instrucao a mais", async () => {
    const { instancia, base } = chr();
    await instancia.tratar(evento(texto("ola, quero uma camisola")));
    assert.equal(base.feitas.filter((f) => f.sql === SQL_MARCAR_TESTE_RECEBIDO).length, 0);
  });

  it("a instrucao so escreve o instante, e e da conversa do tenant", () => {
    assert.match(SQL_MARCAR_TESTE_RECEBIDO, /SET\s+teste_recebido_at\s*=\s*\$3\s+WHERE\s+tenant_id\s*=\s*\$1\s+AND\s+id\s*=\s*\$2/);
  });
});
