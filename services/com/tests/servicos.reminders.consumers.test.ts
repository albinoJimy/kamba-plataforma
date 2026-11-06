/**
 * `booking.created` agenda o lembrete (KAM-048, critério 1, primeira seta).
 *
 * **O que isto prova:** que o consumidor lê a marcação **como ela está agora** e
 * não como o payload a descreve, que o agendamento resultante é o da política, e
 * que um estado que mudou entre a emissão e o consumo não produz *job* nenhum.
 *
 * **O que não prova:** que alguém subscreve `booking.created` no COM. Não
 * subscreve: o consumidor genérico com recibo em `platform.events_consumed` é do
 * KAM-006 e o anfitrião do *worker* de fila é decisão de arquitectura com credor
 * escrito (KAM-071), exactamente como o KAM-045 deixou o dele. O que está medido
 * é a função que esse consumidor vai chamar.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { SQL_MARCACAO } from "../src/servicos/consultas.ts";
import {
  FilaDeLembretesEmMemoria,
  MetricasDoLembrete,
  METRICA_AGENDADOS,
  agendarDoBookingCreated,
  jobIdDoLembrete,
} from "../src/servicos/reminders/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const BOOKING = "55555555-5555-4555-8555-555555555555";
const INICIO = "2026-11-10T09:00:00.000Z";
/** 48 h antes do início. */
const AGORA = new Date("2026-11-08T09:00:00.000Z");

function ensaio(linha: Record<string, unknown> | null) {
  const sqls: string[] = [];
  const fila = new FilaDeLembretesEmMemoria();
  const metricas = new MetricasDoLembrete();
  return {
    sqls,
    fila,
    metricas,
    deps: {
      comTenant: async <T>(
        tenantId: string,
        trabalho: (cliente: {
          query: (
            sql: string,
            p?: readonly unknown[],
          ) => Promise<{ rows: readonly Readonly<Record<string, unknown>>[] }>;
        }) => Promise<T>,
      ): Promise<T> => {
        assert.equal(tenantId, TENANT);
        return trabalho({
          async query(sql: string) {
            sqls.push(sql);
            return { rows: linha === null ? [] : [linha] };
          },
        });
      },
      fila,
      metricas,
      agora: () => AGORA,
    },
  };
}

test("uma marcacao confirmada agenda um job para 24 h antes do inicio", async () => {
  const e = ensaio({ booking_id: BOOKING, inicio_at: INICIO, estado: "confirmada" });
  const decisao = await agendarDoBookingCreated(e.deps, TENANT, {
    booking_id: BOOKING,
  });

  assert.equal(decisao.agenda, true);
  assert.deepEqual(e.sqls, [SQL_MARCACAO]);
  assert.equal(e.fila.contar(), 1);
  assert.ok(e.fila.adiados().has(jobIdDoLembrete(BOOKING, INICIO)));
  assert.equal(
    [...e.fila.adiados().values()][0]?.atrasoMs,
    24 * 60 * 60 * 1_000,
  );
  assert.equal(e.metricas.ler(METRICA_AGENDADOS, "agendado"), 1);
});

test("um cancelamento entre a emissao e o consumo nao agenda nada", async () => {
  // **A razao de se ler a base e nao o payload.** O payload do
  // `booking.created` esta certo sobre o passado; a base esta certa agora.
  const e = ensaio({ booking_id: BOOKING, inicio_at: INICIO, estado: "cancelada" });
  const decisao = await agendarDoBookingCreated(e.deps, TENANT, {
    booking_id: BOOKING,
  });

  assert.equal(decisao.agenda, false);
  assert.equal(decisao.agenda === false ? decisao.motivo : null, "nao_confirmada");
  assert.equal(e.fila.contar(), 0);
  assert.equal(e.metricas.ler(METRICA_AGENDADOS, "nao_confirmada"), 1);
});

test("uma remarcacao entre a emissao e o consumo agenda a hora NOVA", async () => {
  // O payload nao traz o `inicio_at` por isto mesmo: se o trouxesse e fosse
  // usado, o *job* ficava agendado para a hora antiga e o disparo teria de o
  // recusar — uma volta de fila gasta por cada marcacao que mudou.
  const novoInicio = "2026-11-12T15:00:00.000Z";
  const e = ensaio({
    booking_id: BOOKING,
    inicio_at: novoInicio,
    estado: "confirmada",
  });
  await agendarDoBookingCreated(e.deps, TENANT, { booking_id: BOOKING });

  assert.ok(e.fila.adiados().has(jobIdDoLembrete(BOOKING, novoInicio)));
  assert.ok(!e.fila.adiados().has(jobIdDoLembrete(BOOKING, INICIO)));
});

test("um booking_id que a base nao tem nao agenda, e nao levanta", async () => {
  const e = ensaio(null);
  const decisao = await agendarDoBookingCreated(e.deps, TENANT, {
    booking_id: BOOKING,
  });
  assert.equal(decisao.agenda, false);
  assert.equal(e.fila.contar(), 0);
});

test("um timestamptz como Date chega a fila na mesma forma que o disparo compara", async () => {
  // O `pg` devolve `Date`. Sem a normalizacao, o `inicioAt` do `jobId` era
  // `Thu Nov 10 2026 ...` e o do payload do lembrete era o ISO — duas cadeias
  // para o mesmo instante, e nenhum lembrete saia.
  const e = ensaio({
    booking_id: BOOKING,
    inicio_at: new Date(INICIO),
    estado: "confirmada",
  });
  await agendarDoBookingCreated(e.deps, TENANT, { booking_id: BOOKING });
  assert.ok(e.fila.adiados().has(jobIdDoLembrete(BOOKING, INICIO)));
  assert.equal([...e.fila.adiados().values()][0]?.dados.inicioAt, INICIO);
});

test("duas entregas do mesmo booking.created deixam um job", async () => {
  // O EVT entrega «pelo menos uma vez», pelo que a segunda entrega e o caso
  // normal. A desduplicacao e por `jobId` e nao por recibo de consumo — o
  // recibo e do KAM-006 e nao esta aqui.
  const e = ensaio({ booking_id: BOOKING, inicio_at: INICIO, estado: "confirmada" });
  await agendarDoBookingCreated(e.deps, TENANT, { booking_id: BOOKING });
  await agendarDoBookingCreated(e.deps, TENANT, { booking_id: BOOKING });
  assert.equal(e.fila.chamadas, 2);
  assert.equal(e.fila.contar(), 1);
});
