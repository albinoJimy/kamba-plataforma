/**
 * O estágio dos `statuses` (KAM-235, critério 1), sobre duplos: o que ele lê do
 * corpo da Meta e o que passa ao `Saida.ingerir`. A escrita do `delivered_at`
 * contra o PostgreSQL está em `tests_bd/activacao.bd.test.ts`.
 *
 * ```text
 * a explosao            wamid, status e pricing; nem recipient_id nem BSUID
 * o pricing             sem billable ou sem category, null; um failed sem pricing
 * o estagio             os quatro status da Meta, pelo tenant do canal, sob o
 *                       contexto dele; os outros tres desfechos nao escrevem
 * uma falha             sobe, para o job repetir
 * ```
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Gerador, canalDe, estado, interlocutorDe } from "@kamba/meta-sim";

import { explodir } from "../src/entrada/explosao.ts";
import type { EventoDeEntrada } from "../src/entrada/explosao.ts";
import {
  ESTADOS_DA_META,
  estagioDosStatuses,
  saidaQueSoIngere,
} from "../src/outbound/estagio.ts";
import type { ClienteSql, Pricing } from "../src/outbound/contrato.ts";

const g = new Gerador("kam-235");
const CANAL = canalDe(g);
const QUEM = interlocutorDe(g);
const TENANT = "11111111-1111-4111-8111-111111111111";
const WAMID = "wamid.HBgLOTk5.kam235.saida";

function corpo(item: Record<string, unknown>) {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: CANAL.wabaId,
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: CANAL.displayPhoneNumber, phone_number_id: CANAL.phoneNumberId },
              statuses: [item],
            },
          },
        ],
      },
    ],
  };
}

function eventoDe(item: Record<string, unknown>): EventoDeEntrada {
  const { eventos } = explodir(corpo(item), "e".repeat(64));
  assert.equal(eventos.length, 1);
  return eventos[0]!;
}

const BD: ClienteSql = {
  async query() {
    throw new Error("o duplo do estagio nao vai a base");
  },
};

/** O estágio com duplos: regista o tenant, o contexto e o que chegou ao `ingerir`. */
function montar(opcoes: { tenant?: string | null; avancou?: boolean; falha?: Error } = {}) {
  const chamadas: unknown[][] = [];
  const contextos: string[] = [];
  const estagio = estagioDosStatuses({
    tenantDe: async (pnid) => (pnid === CANAL.phoneNumberId ? (opcoes.tenant === undefined ? TENANT : opcoes.tenant) : null),
    comTenant: async (tenant, trabalho) => {
      contextos.push(tenant);
      return trabalho(BD);
    },
    saidaDe: (bd) => ({
      async ingerir(...args: Parameters<ReturnType<typeof saidaQueSoIngere>["ingerir"]>) {
        assert.equal(bd, BD, "o ingerir corre na ligacao do comTenant");
        chamadas.push(args);
        if (opcoes.falha !== undefined) throw opcoes.falha;
        return { avancou: opcoes.avancou ?? true, microUsd: 0, entregou: false };
      },
    }),
  });
  return { estagio, chamadas, contextos };
}

describe("KAM-235 — o estado da mensagem sai da explosão sem telefone", () => {
  it("um statuses do simulador traz wamid, status e pricing, e mais nada do interlocutor", () => {
    const evento = eventoDe(
      estado(g, { wamid: WAMID, estado: "delivered", recipienteId: QUEM.waId, recipienteUserId: "AO.ENSAIO.KAM235" }),
    );
    assert.equal(evento.kind, "statuses");
    assert.equal(evento.eventKey, `${WAMID}:delivered`);
    assert.deepEqual(evento.estado, {
      wamid: WAMID,
      estado: "delivered",
      pricing: { billable: true, pricing_model: "CBP", type: "service", category: "service" },
    });
    assert.equal(evento.interlocutor, null);
    const tudo = JSON.stringify(evento);
    assert.ok(!tudo.includes(QUEM.waId!), "o recipient_id nao sai da explosao");
    assert.ok(!tudo.includes("AO.ENSAIO.KAM235"), "o recipient_user_id nao sai da explosao");
  });

  it("um failed sem pricing, e um pricing sem billable ou sem category, dao pricing null", () => {
    assert.equal(eventoDe(estado(g, { wamid: WAMID, estado: "failed", recipienteId: QUEM.waId! })).estado?.pricing, null);
    for (const pricing of [{ category: "service" }, { billable: "sim", category: "service" }, { billable: true }]) {
      const item = { id: WAMID, status: "delivered", pricing };
      assert.equal(eventoDe(item).estado?.pricing, null, JSON.stringify(pricing));
    }
  });

  it("sem id ou sem status, o evento nao traz estado", () => {
    assert.equal(eventoDe({ status: "delivered" }).estado, undefined);
    assert.equal(eventoDe({ id: WAMID }).estado, undefined);
  });
});

describe("KAM-235 — o estágio dos statuses", () => {
  it("os quatro status da Meta chegam ao ingerir, com o tenant do canal e sob o contexto dele", async () => {
    assert.deepEqual([...ESTADOS_DA_META], ["sent", "delivered", "read", "failed"]);
    for (const e of ["sent", "delivered", "read", "failed"] as const) {
      const { estagio, chamadas, contextos } = montar();
      const desfecho = await estagio(eventoDe(estado(g, { wamid: WAMID, estado: e, recipienteId: QUEM.waId! })));
      assert.equal(desfecho, "avancou", e);
      assert.deepEqual(contextos, [TENANT]);
      assert.equal(chamadas.length, 1);
      const [tenant, wamid, recebido, pricing, pnid] = chamadas[0]!;
      assert.deepEqual([tenant, wamid, recebido, pnid], [TENANT, WAMID, e, CANAL.phoneNumberId]);
      assert.equal(pricing === null, e === "failed", e);
    }
  });

  it("o pricing do statuses vai ao ingerir tal como saiu da explosao", async () => {
    const { estagio, chamadas } = montar();
    await estagio(eventoDe(estado(g, { wamid: WAMID, estado: "read", categoria: "utility", recipienteId: QUEM.waId! })));
    const pricing = chamadas[0]![3] as Pricing;
    assert.deepEqual(pricing, { billable: true, pricing_model: "CBP", type: "regular", category: "utility" });
  });

  it("um estado que nao avanca da nao_avancou", async () => {
    const { estagio } = montar({ avancou: false });
    assert.equal(await estagio(eventoDe({ id: WAMID, status: "delivered" })), "nao_avancou");
  });

  it("os tres desfechos que nao escrevem nao chamam o ingerir", async () => {
    const casos: [EventoDeEntrada, ReturnType<typeof montar>, string][] = [];
    const semEstado = montar();
    casos.push([eventoDe({ status: "delivered" }), semEstado, "sem_estado"]);
    const desconhecido = montar();
    casos.push([eventoDe({ id: WAMID, status: "deleted" }), desconhecido, "estado_desconhecido"]);
    const nosso = montar();
    casos.push([eventoDe({ id: WAMID, status: "suppressed_by_human" }), nosso, "estado_desconhecido"]);
    const semCanal = montar({ tenant: null });
    casos.push([eventoDe({ id: WAMID, status: "delivered" }), semCanal, "canal_desconhecido"]);
    for (const [evento, m, esperado] of casos) {
      assert.equal(await m.estagio(evento), esperado);
      assert.equal(m.chamadas.length, 0, esperado);
    }
    const semPnid: EventoDeEntrada = { ...eventoDe({ id: WAMID, status: "delivered" }), phoneNumberId: null };
    const m = montar();
    assert.equal(await m.estagio(semPnid), "sem_estado");
    assert.equal(m.chamadas.length, 0);
  });

  it("uma falha da base sobe, para o job repetir", async () => {
    const { estagio } = montar({ falha: new Error("ligacao perdida") });
    await assert.rejects(estagio(eventoDe({ id: WAMID, status: "delivered" })), /ligacao perdida/);
  });
});
