/**
 * O corte em slots do critério 2 (KAM-047).
 *
 * «`getAvailability(ctx, servico, intervalo)` devolve no máximo **10** opções
 * (limite de linhas de lista interactiva da Meta, CONFIRMADO, E1 §7), cada uma
 * com `slot_id` opaco e instante UTC; a apresentação em `Africa/Luanda` é da
 * camada de renderização.»
 *
 * O corte é uma função pura, e é aqui que se prova: sem base de dados, sem
 * relógio real, e com cada regra do ficheiro a ter o seu caso.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { test } from "node:test";

import {
  MAXIMO_DE_OPCOES,
  opcoesComSlotId,
  slotsLivres,
  lerSlotId,
  type Janela,
  type Ocupacao,
} from "../src/servicos/index.ts";

const SEGREDO = randomBytes(32);
const TENANT = "11111111-1111-4111-8111-111111111111";
const RECURSO = "44444444-4444-4444-8444-444444444444";
const OUTRO_RECURSO = "55555555-5555-4555-8555-555555555555";
const SERVICO = "33333333-3333-4333-8333-333333333333";

const PASSADO = new Date("2026-11-02T00:00:00.000Z");

function janela(abre: string, fecha: string, recurso = RECURSO): Janela {
  return {
    resourceId: recurso,
    abreAt: new Date(abre),
    fechaAt: new Date(fecha),
  };
}

function ocupado(inicio: string, fim: string, recurso = RECURSO): Ocupacao {
  return {
    resourceId: recurso,
    inicioAt: new Date(inicio),
    fimAt: new Date(fim),
  };
}

test("uma janela de uma hora com servico de 30 min da dois slots", () => {
  const slots = slotsLivres(
    [janela("2026-11-02T09:00:00Z", "2026-11-02T10:00:00Z")],
    [],
    30,
    PASSADO,
  );
  assert.deepEqual(
    slots.map((s) => s.inicioAt),
    ["2026-11-02T09:00:00.000Z", "2026-11-02T09:30:00.000Z"],
  );
});

test("a grelha alinha-se a abertura e nao a hora redonda", () => {
  // Um recurso que abre às 9h05 oferece 9h05 e 9h35. Alinhar ao relógio
  // descartava os primeiros 25 minutos de cada janela sem o dizer a ninguém.
  const slots = slotsLivres(
    [janela("2026-11-02T09:05:00Z", "2026-11-02T10:05:00Z")],
    [],
    30,
    PASSADO,
  );
  assert.deepEqual(
    slots.map((s) => s.inicioAt),
    ["2026-11-02T09:05:00.000Z", "2026-11-02T09:35:00.000Z"],
  );
});

test("um slot que nao cabe inteiro na janela nao e oferecido", () => {
  // Janela de uma hora, serviço de 45 minutos: **um** slot, não dois. O segundo
  // acabava depois de o recurso fechar.
  const slots = slotsLivres(
    [janela("2026-11-02T09:00:00Z", "2026-11-02T10:00:00Z")],
    [],
    45,
    PASSADO,
  );
  assert.equal(slots.length, 1);
  assert.equal(slots[0]?.fimAt, "2026-11-02T09:45:00.000Z");
});

test("uma marcacao activa tira o slot que lhe toca, e so esse", () => {
  const slots = slotsLivres(
    [janela("2026-11-02T09:00:00Z", "2026-11-02T11:00:00Z")],
    [ocupado("2026-11-02T09:30:00Z", "2026-11-02T10:00:00Z")],
    30,
    PASSADO,
  );
  assert.deepEqual(
    slots.map((s) => s.inicioAt),
    [
      "2026-11-02T09:00:00.000Z",
      "2026-11-02T10:00:00.000Z",
      "2026-11-02T10:30:00.000Z",
    ],
  );
});

test("adjacente nao e sobreposto: o slot que comeca quando a marcacao acaba e oferecido", () => {
  // A mesma semântica `[)` da restrição de exclusão. Com `[]` não havia grelha
  // de horas possível.
  const slots = slotsLivres(
    [janela("2026-11-02T09:00:00Z", "2026-11-02T10:00:00Z")],
    [ocupado("2026-11-02T08:30:00Z", "2026-11-02T09:00:00Z")],
    30,
    PASSADO,
  );
  assert.equal(slots.length, 2);
  assert.equal(slots[0]?.inicioAt, "2026-11-02T09:00:00.000Z");
});

test("a ocupacao de um recurso nao esconde horas de outro", () => {
  // O defeito que uma primeira versão deste ficheiro tinha: comparar um slot de
  // um recurso com a ocupação de outro escondia metade das horas de uma PME com
  // dois profissionais.
  const slots = slotsLivres(
    [
      janela("2026-11-02T09:00:00Z", "2026-11-02T09:30:00Z"),
      janela("2026-11-02T09:00:00Z", "2026-11-02T09:30:00Z", OUTRO_RECURSO),
    ],
    [ocupado("2026-11-02T09:00:00Z", "2026-11-02T09:30:00Z")],
    30,
    PASSADO,
  );
  assert.deepEqual(
    slots.map((s) => s.resourceId),
    [OUTRO_RECURSO],
  );
});

test("um slot no passado nao e oferecido", () => {
  const agora = new Date("2026-11-02T09:40:00Z");
  const slots = slotsLivres(
    [janela("2026-11-02T09:00:00Z", "2026-11-02T11:00:00Z")],
    [],
    30,
    agora,
  );
  assert.deepEqual(
    slots.map((s) => s.inicioAt),
    ["2026-11-02T10:00:00.000Z", "2026-11-02T10:30:00.000Z"],
  );
});

test("o corte e dez, e depois de ordenar por instante", () => {
  // «Dez» é CONFIRMADO (E1 §7) e não proposta. O corte é no fim, e não durante
  // a varredura por recurso: o cliente quer as dez **mais próximas**, venham do
  // recurso que vierem.
  const slots = slotsLivres(
    [
      janela("2026-11-02T14:00:00Z", "2026-11-02T20:00:00Z"),
      janela("2026-11-02T09:00:00Z", "2026-11-02T12:00:00Z", OUTRO_RECURSO),
    ],
    [],
    30,
    PASSADO,
  );
  assert.equal(slots.length, MAXIMO_DE_OPCOES);
  assert.equal(slots[0]?.inicioAt, "2026-11-02T09:00:00.000Z");
  assert.equal(
    slots[0]?.resourceId,
    OUTRO_RECURSO,
    "a primeira opcao e a mais proxima, mesmo vindo do segundo recurso da lista",
  );
  // E a ordem é estritamente crescente, sem repetições.
  const instantes = slots.map((s) => Date.parse(s.inicioAt));
  for (let i = 1; i < instantes.length; i += 1) {
    assert.ok((instantes[i] ?? 0) >= (instantes[i - 1] ?? 0));
  }
});

test("a ordem e deterministica entre recursos a mesma hora", () => {
  // Sem o `resourceId` a desempatar, a lista de dez deixava de ser
  // determinística para os mesmos dados — e um teste de contrato ficava
  // impossível de escrever.
  const entrada: Janela[] = [
    janela("2026-11-02T09:00:00Z", "2026-11-02T09:30:00Z", OUTRO_RECURSO),
    janela("2026-11-02T09:00:00Z", "2026-11-02T09:30:00Z"),
  ];
  const primeira = slotsLivres(entrada, [], 30, PASSADO);
  const segunda = slotsLivres([...entrada].reverse(), [], 30, PASSADO);
  assert.deepEqual(
    primeira.map((s) => s.resourceId),
    segunda.map((s) => s.resourceId),
  );
  assert.ok((primeira[0]?.resourceId ?? "") < (primeira[1]?.resourceId ?? ""));
});

test("uma duracao nao positiva e um defeito e lanca", () => {
  for (const duracao of [0, -30, 1.5, Number.NaN]) {
    assert.throws(
      () => slotsLivres([janela("2026-11-02T09:00:00Z", "2026-11-02T10:00:00Z")], [], duracao, PASSADO),
      RangeError,
    );
  }
});

test("as opcoes saem com slot_id que verifica e com o servico dentro", () => {
  const slots = slotsLivres(
    [janela("2026-11-02T09:00:00Z", "2026-11-02T09:30:00Z")],
    [],
    30,
    PASSADO,
  );
  const opcoes = opcoesComSlotId(SEGREDO, TENANT, SERVICO, slots);
  assert.equal(opcoes.length, 1);
  const opcao = opcoes[0];
  assert.ok(opcao !== undefined);
  assert.equal(opcao.serviceId, SERVICO);
  // O instante sai em UTC com `Z`: a apresentação em `Africa/Luanda` é de quem
  // renderiza, e este módulo nunca formata uma hora para um humano.
  assert.ok(opcao.inicioAt.endsWith("Z"));
  assert.deepEqual(lerSlotId(SEGREDO, TENANT, opcao.slotId), {
    serviceId: SERVICO,
    resourceId: RECURSO,
    inicioAt: opcao.inicioAt,
    fimAt: opcao.fimAt,
  });
});
