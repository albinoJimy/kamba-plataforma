/**
 * O processo de entrada do `worker-canal` (KAM-013).
 *
 * A decisão — explodir, registar, encaminhar, pôr em quarentena — é de
 * `@kamba/core-ts/entrada` e está provada lá. Aqui prova-se a **montagem**: que
 * o encaminhador do esqueleto recebe o que devia receber, que o `/metrics`
 * responde e que a sonda continua a responder.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { sha256Hex, tratarCorpo } from "@kamba/core-ts/entrada";
import type { ClienteSql } from "@kamba/core-ts/entrada";

import { EncaminhadorQueSoRegista, PORTA_POR_OMISSAO, criarApp } from "../src/entrada.ts";
import { SERVICE } from "../src/meta.ts";

const WABA = "109876543210987";

/** A base reduzida a «aceita e devolve um id novo». A dedup prova-se em core-ts. */
class BaseQueAceita implements ClienteSql {
  conta = 0;

  async query(sql: string): Promise<{ rows: Record<string, unknown>[] }> {
    if (sql.includes("INSERT INTO platform.inbound_events")) {
      this.conta += 1;
      return { rows: [{ id: `id-${this.conta}` }] };
    }
    return { rows: [] };
  }
}

function trabalhoDe(corpo: unknown) {
  const bytes = Buffer.from(JSON.stringify(corpo), "utf8");
  return {
    trabalho: { corpo: bytes.toString("base64"), recebidoEm: 0 },
    resumo: sha256Hex(new Uint8Array(bytes)),
  };
}

function mudanca(field: string, value: unknown): unknown {
  return { entry: [{ id: WABA, changes: [{ field, value }] }] };
}

describe("o encaminhador do esqueleto", () => {
  it("recebe uma mensagem pelo chr", async () => {
    const encaminhador = new EncaminhadorQueSoRegista();
    const { trabalho, resumo } = trabalhoDe(
      mudanca("messages", { messages: [{ id: "wamid.A", type: "text" }] }),
    );
    const resultado = await tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo);
    assert.deepEqual(resultado.destinos, ["chr"]);
    assert.equal(encaminhador.entregues.length, 1);
    assert.equal(encaminhador.entregues[0]?.kind, "message");
  });

  it("um estado chega pelo outbound e o historico pela ingestao", async () => {
    for (const [corpo, destino, kind] of [
      [
        mudanca("messages", { statuses: [{ id: "wamid.A", status: "read" }] }),
        "outbound",
        "statuses",
      ],
      [mudanca("history", { threads: [] }), "ingestao", "history"],
      [mudanca("account_update", { event: "PARTNER_ADDED" }), "gestao_de_canal", "account_update"],
    ] as const) {
      const encaminhador = new EncaminhadorQueSoRegista();
      const { trabalho, resumo } = trabalhoDe(corpo);
      const resultado = await tratarCorpo(new BaseQueAceita(), trabalho, encaminhador, resumo);
      assert.deepEqual(resultado.destinos, [destino], kind);
      assert.equal(encaminhador.entregues[0]?.kind, kind);
    }
  });

  it("nao entrega nada de um corpo que vai a quarentena", async () => {
    const encaminhador = new EncaminhadorQueSoRegista();
    const resultado = await tratarCorpo(
      new BaseQueAceita(),
      { corpo: Buffer.from("{nao e json", "utf8").toString("base64"), recebidoEm: 0 },
      encaminhador,
      "c".repeat(64),
    );
    assert.equal(resultado.emQuarentena, 1);
    assert.deepEqual(encaminhador.entregues, []);
  });
});

describe("as rotas do processo de entrada", () => {
  it("a sonda responde com o contrato do servico", async () => {
    const resposta = await criarApp().request("/healthz");
    assert.equal(resposta.status, 200);
    const corpo = (await resposta.json()) as { status: string; service: string };
    assert.equal(corpo.status, "ok");
    assert.equal(corpo.service, SERVICE);
  });

  it("o /metrics expoe as metricas DESTE processo, nao as do GWY", async () => {
    // Achado da revisão adversarial: servia-se aqui o `METRICAS` do GWY, que
    // este processo não incrementa — saíam `gwy_sig_fail 0` e
    // `inbound_queue_depth -1` permanentes (o segundo ao lado do valor real do
    // GWY, onde um alerta o lê e não dispara) e do trabalho que ele faz de
    // verdade não saía nada.
    const resposta = await criarApp().request("/metrics");
    assert.equal(resposta.status, 200);
    const texto = await resposta.text();
    for (const nome of [
      "inbound_events_total",
      "inbound_unrouted_total",
      "inbound_job_failed_total",
    ]) {
      assert.match(texto, new RegExp(`^# TYPE ${nome} counter$`, "m"), nome);
    }
    for (const nome of ["gwy_requests_total", "gwy_sig_fail", "inbound_queue_depth"]) {
      assert.equal(texto.includes(nome), false, `${nome} nao e deste processo`);
    }
  });

  it("a porta e a quarta do servico, distinta das do publicador e do consumidor", async () => {
    // 3011 é o publicador, 3012 o consumidor. Duas iguais faziam o segundo
    // processo morrer a arrancar, com `EADDRINUSE`.
    assert.equal(PORTA_POR_OMISSAO, 3013);
  });

  it("uma rota desconhecida nao responde 200", async () => {
    for (const caminho of ["/", "/wa/webhook", "/admin"]) {
      assert.notEqual((await criarApp().request(caminho)).status, 200, caminho);
    }
  });
});
