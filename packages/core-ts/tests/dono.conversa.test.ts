/**
 * A `OwnerPort` do KAM-223, sem base: a invocação que o painel monta, a ordem
 * gravar → invocar, a credencial do painel e o cursor da leitura.
 *
 * As instruções correm contra o PostgreSQL em `tests_bd/dono.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { AGENT_INVOCATION_V1_PATH } from "@kamba/contracts";

import { CABECALHO_INTERNO, CAMINHO_DO_TURNO } from "../src/agr/contrato.ts";
import type { AgentInvocation } from "../src/chr/contrato.ts";
import {
  ConversaDoDono,
  invocacaoDoPainel,
  invocadorPorHttp,
  MAXIMO_DA_MENSAGEM,
  textoDaMensagem,
  type ContextoDoDono,
  type PortasDaConversa,
} from "../src/dono/index.ts";

const esquema = JSON.parse(readFileSync(AGENT_INVOCATION_V1_PATH, "utf8"));

const TENANT = "11111111-1111-4111-8111-111111111111";
const CONTEXTO: ContextoDoDono = {
  contactId: "33333333-3333-4333-8333-333333333333",
  conversationId: "44444444-4444-4444-8444-444444444444",
  channelId: "55555555-5555-4555-8555-555555555555",
  vertical: "vendedor",
  modo: "bot",
};
const MENSAGEM = "66666666-6666-4666-8666-666666666666";

function portas(sobre: Partial<PortasDaConversa> = {}) {
  const ordem: string[] = [];
  const gravadas: { tenantId: string; texto: string }[] = [];
  const invocacoes: AgentInvocation[] = [];
  const p: PortasDaConversa = {
    contexto: async () => {
      ordem.push("contexto");
      return CONTEXTO;
    },
    gravar: async ({ tenantId, texto }) => {
      ordem.push("gravar");
      gravadas.push({ tenantId, texto });
      return MENSAGEM;
    },
    invocar: async (invocacao) => {
      ordem.push("invocar");
      invocacoes.push(invocacao);
      return { estado: 200, desfecho: "executado" };
    },
    ler: async () => [],
    ...sobre,
  };
  return { p, ordem, gravadas, invocacoes };
}

describe("KAM-223 — a invocacao de um turno do painel", () => {
  it("leva o identificador e nunca o texto, com a persona dono e o thread_id do dono", () => {
    const inv = invocacaoDoPainel(TENANT, CONTEXTO, MENSAGEM);
    assert.equal(inv.message_id, MENSAGEM);
    assert.equal(inv.persona, "dono");
    assert.equal(inv.thread_id, `${TENANT}:${CONTEXTO.contactId}`);
    assert.equal(inv.vertical, "vendedor");
    assert.equal(inv.type, "text");
    assert.equal(inv.wamid, `painel.${MENSAGEM}`);
    assert.equal(inv.botao, undefined);
    assert.ok(!JSON.stringify(inv).includes("texto"));
  });

  it("obedece ao esquema publicado: campos conhecidos, e o wamid e o message_id com a forma dele", () => {
    const inv = invocacaoDoPainel(TENANT, CONTEXTO, MENSAGEM) as unknown as Record<string, unknown>;
    for (const campo of Object.keys(inv)) assert.ok(esquema.properties[campo] !== undefined, campo);
    for (const campo of esquema.required as string[]) assert.ok(campo in inv, campo);
    assert.match(String(inv["wamid"]), new RegExp(esquema.properties.wamid.pattern));
    assert.match(String(inv["message_id"]), new RegExp(esquema.properties.message_id.pattern));
  });
});

describe("KAM-223 — o texto do painel", () => {
  it("apara, recusa o vazio e o que passa do tecto, e recusa o que nao e texto", () => {
    assert.equal(textoDaMensagem("  ola  "), "ola");
    assert.equal(textoDaMensagem("x".repeat(MAXIMO_DA_MENSAGEM)), "x".repeat(MAXIMO_DA_MENSAGEM));
    for (const mau of ["", "   ", "x".repeat(MAXIMO_DA_MENSAGEM + 1), null, 1, { texto: "x" }, ["x"]]) {
      assert.equal(textoDaMensagem(mau), null, String(mau));
    }
  });
});

describe("KAM-223 — a ConversaDoDono", () => {
  it("grava antes de invocar, e a invocacao leva o identificador do que gravou", async () => {
    const m = portas();
    const r = await new ConversaDoDono(m.p).enviar(TENANT, "quanto vendi hoje?");
    assert.deepEqual(r, { enviado: true, messageId: MENSAGEM, desfecho: "executado" });
    assert.deepEqual(m.ordem, ["contexto", "gravar", "invocar"]);
    assert.deepEqual(m.gravadas, [{ tenantId: TENANT, texto: "quanto vendi hoje?" }]);
    assert.equal(m.invocacoes[0]?.message_id, MENSAGEM);
  });

  it("um texto que imita um botao vai como texto: a invocacao nao leva botao", async () => {
    const m = portas();
    await new ConversaDoDono(m.p).enviar(TENANT, "confirm:77777777-7777-4777-8777-777777777777");
    assert.equal(m.invocacoes[0]?.botao, undefined);
    assert.equal(m.invocacoes[0]?.type, "text");
  });

  it("sem dono ou sem canal, nada se grava nem se invoca", async () => {
    for (const motivo of ["sem_dono", "sem_canal"] as const) {
      const m = portas({ contexto: async () => motivo });
      assert.deepEqual(await new ConversaDoDono(m.p).enviar(TENANT, "ola"), { enviado: false, motivo });
      assert.deepEqual(m.gravadas, []);
      assert.deepEqual(m.invocacoes, []);
    }
  });

  it("um texto invalido nem le o contexto", async () => {
    const m = portas();
    assert.deepEqual(await new ConversaDoDono(m.p).enviar(TENANT, " "), { enviado: false, motivo: "texto" });
    assert.deepEqual(m.ordem, []);
  });

  it("o AGR em baixo deixa a mensagem gravada e diz qual", async () => {
    for (const estado of [0, 401, 503]) {
      const m = portas({ invocar: async () => ({ estado, desfecho: "desconhecido" }) });
      assert.deepEqual(await new ConversaDoDono(m.p).enviar(TENANT, "ola"), {
        enviado: false,
        motivo: "agr",
        messageId: MENSAGEM,
      });
    }
  });

  it("um cursor que nao e um uuid, ou que nao e desta conversa, e nao_encontrado", async () => {
    const lidos: (string | null)[] = [];
    const m = portas({
      ler: async ({ depois }) => {
        lidos.push(depois);
        return depois === null ? [] : null;
      },
    });
    const conversa = new ConversaDoDono(m.p);
    assert.equal(await conversa.ler(TENANT, "x' OR 1=1 --"), "nao_encontrado");
    assert.deepEqual(lidos, []);
    assert.equal(await conversa.ler(TENANT, MENSAGEM), "nao_encontrado");
    assert.deepEqual(await conversa.ler(TENANT, null), []);
  });
});

describe("KAM-223 — o invocador por HTTP", () => {
  it("chama o /internal/turn com a credencial do painel, lida a cada pedido", async () => {
    const chamadas: { url: string; cabecalho: string | null; corpo: unknown }[] = [];
    let credencial = "a";
    const invocar = invocadorPorHttp({
      agr: "http://agr:8000",
      credencial: () => credencial,
      buscar: (async (url: string, init: RequestInit) => {
        const cabecalhos = new Headers(init.headers);
        chamadas.push({ url, cabecalho: cabecalhos.get(CABECALHO_INTERNO), corpo: JSON.parse(String(init.body)) });
        return new Response(JSON.stringify({ outcome: "executado" }), { status: 200 });
      }) as unknown as typeof fetch,
    });
    const inv = invocacaoDoPainel(TENANT, CONTEXTO, MENSAGEM);
    assert.deepEqual(await invocar(inv), { estado: 200, desfecho: "executado" });
    credencial = "b";
    await invocar(inv);
    assert.deepEqual(chamadas.map((c) => c.cabecalho), ["a", "b"]);
    assert.equal(chamadas[0]?.url, `http://agr:8000${CAMINHO_DO_TURNO}`);
    assert.deepEqual(chamadas[0]?.corpo, inv);
  });

  it("uma falha de rede da estado 0, e nao lanca", async () => {
    const invocar = invocadorPorHttp({
      agr: "http://agr:8000",
      credencial: () => "a",
      buscar: (async () => {
        throw new TypeError("fetch failed");
      }) as unknown as typeof fetch,
    });
    assert.deepEqual(await invocar(invocacaoDoPainel(TENANT, CONTEXTO, MENSAGEM)), {
      estado: 0,
      desfecho: "desconhecido",
    });
  });
});
