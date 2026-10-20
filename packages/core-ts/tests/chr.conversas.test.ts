/**
 * A conversa e o gancho de fusão (KAM-014, critério 4 e DoD «Idempotência»).
 *
 * Aqui prova-se o SQL que se manda e o que se faz com cada resposta: que a
 * janela se escreve a partir de **um** instante, que um modo desconhecido para
 * o caminho, e que o gancho de fusão distingue os dois casos — reapontar e
 * dobrar. O que só a base prova — que o `ON CONFLICT` é idempotente sob
 * concorrência, que a `UNIQUE` recusa a segunda conversa, que o gancho corre
 * dentro da transacção da fusão e que um erro dele desfaz a fusão inteira —
 * vive em `db/tests_chr/`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ConversaIlegivelError,
  JANELA_MS,
  SQL_ABRIR_CONVERSA,
  SQL_CONVERSAS_A_FUNDIR,
  SQL_DOBRAR_CONVERSA,
  SQL_REPONTAR_CONVERSA,
  abrirConversa,
  repontarConversas,
} from "../src/chr/index.ts";
import { BaseFalsa } from "./apoio/chr-base-falsa.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const CANAL = "22222222-2222-4222-8222-222222222222";
const CONTACTO_A = "33333333-3333-4333-8333-333333333333";
const CONTACTO_P = "55555555-5555-4555-8555-555555555555";
const CONVERSA = "44444444-4444-4444-8444-444444444444";
const OUTRA = "66666666-6666-4666-8666-666666666666";
const AGORA = new Date("2026-10-19T12:00:00.000Z");

const ALVO = { tenantId: TENANT, contactId: CONTACTO_A, channelId: CANAL };

describe("abrirConversa", () => {
  it("manda o `SQL_ABRIR_CONVERSA` com os cinco parametros, pela ordem", async () => {
    const bd = new BaseFalsa().responde("conversations", {
      rows: [{ id: CONVERSA, mode: "bot" }],
    });

    const conversa = await abrirConversa(bd, ALVO, AGORA);

    assert.deepEqual(conversa, { id: CONVERSA, mode: "bot" });
    assert.equal(bd.instrucoes[0]?.sql, SQL_ABRIR_CONVERSA);
    assert.deepEqual(bd.instrucoes[0]?.parametros, [
      TENANT,
      CONTACTO_A,
      CANAL,
      AGORA,
      new Date(AGORA.getTime() + JANELA_MS),
    ]);
  });

  it("a janela deriva de **um** instante, e nao de duas leituras do relogio", async () => {
    // Com dois `now()` dentro da instrucao, o `conversations_janela_ck`
    // continuava satisfeito e os dois tempos vinham de leituras diferentes.
    const bd = new BaseFalsa().responde("conversations", {
      rows: [{ id: CONVERSA, mode: "bot" }],
    });
    await abrirConversa(bd, ALVO, AGORA);
    const [, , , inicio, fim] = bd.instrucoes[0]?.parametros as [
      string,
      string,
      string,
      Date,
      Date,
    ];
    assert.equal(fim.getTime() - inicio.getTime(), JANELA_MS);
  });

  it("o `mode` **nao** aparece no `SET`: uma entrada nao muda quem tem a palavra", () => {
    // `kamba_app` nem tem `UPDATE (mode)` (revisao `0009`), e as transicoes sao
    // KAM-018. O `mode` aparece no `RETURNING` — e para o ler que o `SELECT` de
    // tabela existe —, e e por isso que a fatia e so a clausula `SET`.
    const inicio = SQL_ABRIR_CONVERSA.indexOf("DO UPDATE");
    const fim = SQL_ABRIR_CONVERSA.indexOf("RETURNING");
    const clausulaSet = SQL_ABRIR_CONVERSA.slice(inicio, fim);
    assert.ok(!clausulaSet.includes("mode"), clausulaSet);
    assert.ok(clausulaSet.includes("last_inbound_at"));
    assert.ok(clausulaSet.includes("window_expires_at"));
    assert.ok(SQL_ABRIR_CONVERSA.slice(fim).includes("mode"));
  });

  it("o `ON CONFLICT` infere a `UNIQUE` de negocio, que e o que torna isto idempotente", () => {
    assert.ok(
      SQL_ABRIR_CONVERSA.includes("ON CONFLICT (tenant_id, contact_id, channel_id)"),
    );
  });

  it("uma linha sem `id`, ou nenhuma linha, lanca", async () => {
    for (const resposta of [{ rows: [] }, { rows: [{ mode: "bot" }] }, { rows: [{ id: "" }] }]) {
      const bd = new BaseFalsa().responde("conversations", resposta);
      await assert.rejects(() => abrirConversa(bd, ALVO, AGORA), ConversaIlegivelError);
    }
  });

  it("um `mode` que o codigo nao conhece lanca, e nao e tratado como o mais parecido", async () => {
    const bd = new BaseFalsa().responde("conversations", {
      rows: [{ id: CONVERSA, mode: "silenciada" }],
    });
    await assert.rejects(
      () => abrirConversa(bd, ALVO, AGORA),
      /modo desconhecido "silenciada"/,
    );
  });
});

describe("repontarConversas", () => {
  it("sem colisao, reaponta: um `UPDATE` por conversa do absorvido", async () => {
    const bd = new BaseFalsa().responde("LEFT JOIN", {
      rows: [
        { id_de: CONVERSA, channel_id: CANAL, id_para: null },
        { id_de: OUTRA, channel_id: "outro-canal", id_para: null },
      ],
    });

    const resultado = await repontarConversas(bd, TENANT, CONTACTO_P, CONTACTO_A);

    assert.deepEqual(resultado, { repontadas: 2, dobradas: 0 });
    assert.equal(bd.instrucoes[0]?.sql, SQL_CONVERSAS_A_FUNDIR);
    assert.deepEqual(bd.instrucoes[0]?.parametros, [CONTACTO_A, TENANT, CONTACTO_P]);
    assert.equal(bd.instrucoes[1]?.sql, SQL_REPONTAR_CONVERSA);
    assert.deepEqual(bd.instrucoes[1]?.parametros, [CONTACTO_A, CONVERSA]);
    assert.equal(bd.quantas("SET contact_id"), 2);
  });

  it("com colisao, dobra os tempos na que fica e **nao** reaponta", async () => {
    // A `UNIQUE (tenant_id, contact_id, channel_id)` recusa duas conversas do
    // mesmo canal: as duas nao se juntam numa linha, e a do absorvido fica
    // pendurada na lapide. Ver a nota do modulo.
    const inbound = new Date("2026-10-18T10:00:00.000Z");
    const janela = new Date("2026-10-19T10:00:00.000Z");
    const humano = new Date("2026-10-17T10:00:00.000Z");
    const bd = new BaseFalsa().responde("LEFT JOIN", {
      rows: [
        {
          id_de: CONVERSA,
          channel_id: CANAL,
          last_inbound_at: inbound,
          window_expires_at: janela,
          last_human_activity_at: humano,
          id_para: OUTRA,
        },
      ],
    });

    const resultado = await repontarConversas(bd, TENANT, CONTACTO_P, CONTACTO_A);

    assert.deepEqual(resultado, { repontadas: 0, dobradas: 1 });
    assert.equal(bd.quantas("SET contact_id"), 0);
    assert.equal(bd.instrucoes[1]?.sql, SQL_DOBRAR_CONVERSA);
    assert.deepEqual(bd.instrucoes[1]?.parametros, [inbound, janela, humano, OUTRA]);
  });

  it("o `GREATEST` esta nas tres colunas de tempo, e so nelas", () => {
    // Com `NULL`, o `GREATEST` do PostgreSQL ignora os nulos: uma conversa sem
    // actividade humana nao apaga a actividade humana da outra.
    assert.equal((SQL_DOBRAR_CONVERSA.match(/GREATEST/g) ?? []).length, 3);
    assert.ok(!SQL_DOBRAR_CONVERSA.includes("mode"));
    assert.ok(!SQL_DOBRAR_CONVERSA.includes("contact_id"));
  });

  it("um absorvido sem conversas nenhumas nao escreve nada", async () => {
    const bd = new BaseFalsa().responde("LEFT JOIN", { rows: [] });
    assert.deepEqual(await repontarConversas(bd, TENANT, CONTACTO_P, CONTACTO_A), {
      repontadas: 0,
      dobradas: 0,
    });
    assert.equal(bd.instrucoes.length, 1);
  });

  it("tempos em texto — a forma de alguns *drivers* — sao aceites", async () => {
    const bd = new BaseFalsa().responde("LEFT JOIN", {
      rows: [
        {
          id_de: CONVERSA,
          channel_id: CANAL,
          last_inbound_at: "2026-10-18T10:00:00.000Z",
          window_expires_at: "2026-10-19T10:00:00.000Z",
          last_human_activity_at: null,
          id_para: OUTRA,
        },
      ],
    });
    await repontarConversas(bd, TENANT, CONTACTO_P, CONTACTO_A);
    assert.deepEqual(bd.instrucoes[1]?.parametros.slice(0, 3), [
      new Date("2026-10-18T10:00:00.000Z"),
      new Date("2026-10-19T10:00:00.000Z"),
      null,
    ]);
  });

  it("um tempo ilegivel lanca, e a fusao inteira e desfeita por quem chama", async () => {
    const bd = new BaseFalsa().responde("LEFT JOIN", {
      rows: [
        {
          id_de: CONVERSA,
          channel_id: CANAL,
          last_inbound_at: 42,
          window_expires_at: null,
          last_human_activity_at: null,
          id_para: OUTRA,
        },
      ],
    });
    await assert.rejects(
      () => repontarConversas(bd, TENANT, CONTACTO_P, CONTACTO_A),
      ConversaIlegivelError,
    );
  });
});
