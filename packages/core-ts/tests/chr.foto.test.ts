/**
 * A foto do dono pelo MED, do webhook à invocação (KAM-231).
 *
 * O caminho de produção é webhook → explosão → CHR → MED (`media_assets` e STO)
 * → fila `agr-inbound` → AGR. Aqui prova-se a metade TypeScript sem base nem
 * rede: o `image.id` sai da explosão só numa `image`, o CHR passa-o ao MED só
 * quando quem escreve é o dono, e a invocação leva o `asset_id` que o MED
 * devolveu — e nunca o `media_id` da Meta, os bytes ou a chave do objecto.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Chr, type ClienteDoChr, MetricasDoChr, ResolvedorDeCanal } from "../src/chr/index.ts";
import type { AgentInvocation } from "../src/chr/index.ts";
import { explodir } from "../src/entrada/explosao.ts";
import type { PedidoDeMidia, ResultadoDeMidia } from "../src/med/index.ts";
import { linhaDeCanal } from "./apoio/chr-base-falsa.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const CANAL = "22222222-2222-4222-8222-222222222222";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const CONVERSA = "44444444-4444-4444-8444-444444444444";
const ASSET = "66666666-6666-4666-8666-666666666666";
const PNID = "999000000000001";
const WABA = "999000000000002";
const MEDIA_DA_META = "999123456789";

function corpoDe(mensagem: Readonly<Record<string, unknown>>, wamid = "wamid.FOTO999"): unknown {
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
                {
                  id: wamid,
                  from: "244 999 000 001",
                  from_user_id: "AO.BSUID.DONO.999",
                  timestamp: "1763650000",
                  ...mensagem,
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

const foto = (imagem: unknown = { id: MEDIA_DA_META, mime_type: "image/jpeg" }) =>
  corpoDe({ type: "image", image: imagem });

function evento(corpo: unknown) {
  const { eventos } = explodir(corpo, "a".repeat(64));
  assert.equal(eventos.length, 1);
  return eventos[0]!;
}

/** A conversa e o papel do contacto, lidos do **texto** da instrução. */
class Base implements ClienteDoChr {
  papel = "dono";
  async query(sql: string) {
    if (sql.includes("INSERT INTO platform.conversations")) {
      return { rows: [{ id: CONVERSA, mode: "bot" }] };
    }
    if (sql.includes("FROM platform.contacts")) return { rows: [{ papel: this.papel }] };
    return { rows: [] };
  }
}

function chr(resposta: ResultadoDeMidia | Error | null) {
  const base = new Base();
  const aoAgr: AgentInvocation[] = [];
  const pedidos: PedidoDeMidia[] = [];
  const registos: unknown[] = [];
  const canalFalso: ClienteDoChr = {
    query: async (_sql, parametros = []) =>
      parametros[0] === PNID
        ? { rows: [linhaDeCanal({ tenant_id: TENANT, channel_id: CANAL })] }
        : { rows: [] },
  };
  const instancia = new Chr({
    resolvedor: new ResolvedorDeCanal(canalFalso),
    contacto: async () => ({ contactId: CONTACTO }),
    entrega: {
      agr: async (i) => {
        aoAgr.push(i);
      },
      dono: async () => undefined,
    },
    quarentena: async () => undefined,
    metricas: new MetricasDoChr(),
    registar: (campos) => registos.push(campos),
    comTenant: async (_tenant, trabalho) => trabalho(base),
    ...(resposta === null
      ? {}
      : {
          midia: async (pedido: PedidoDeMidia) => {
            pedidos.push(pedido);
            if (resposta instanceof Error) throw resposta;
            return resposta;
          },
        }),
  });
  return { instancia, base, aoAgr, pedidos, registos };
}

const armazenada: ResultadoDeMidia = {
  estado: "armazenado",
  assetId: ASSET,
  referencia: `media://${ASSET}`,
  repetido: false,
};

describe("KAM-231 — o `image.id` sai da explosao", () => {
  it("uma `image` da o `media_id` da Meta e o tipo anunciado", () => {
    const e = evento(foto());
    assert.equal(e.waType, "image");
    assert.equal(e.mediaId, MEDIA_DA_META);
    assert.equal(e.mimeAnunciado, "image/jpeg");
  });

  it("sem `id`, ou fora de forma, a mensagem segue sem `mediaId`", () => {
    for (const imagem of [{}, { id: 7 }, { id: "" }, { id: "x".repeat(65) }, null, "abc"]) {
      const e = evento(foto(imagem));
      assert.equal(e.waType, "image");
      assert.equal("mediaId" in e, false, JSON.stringify(imagem));
      assert.equal("mimeAnunciado" in e, false, JSON.stringify(imagem));
    }
  });

  it("o tipo e que manda: uma `image` colada a outro tipo nao conta", () => {
    for (const mensagem of [
      { type: "text", text: { body: "ola" }, image: { id: MEDIA_DA_META } },
      { type: "sticker", sticker: { id: MEDIA_DA_META }, image: { id: MEDIA_DA_META } },
      { type: "audio", audio: { id: MEDIA_DA_META } },
    ]) {
      assert.equal("mediaId" in evento(corpoDe(mensagem)), false, mensagem.type);
    }
  });
});

describe("KAM-231 — a foto do dono passa pelo MED e a invocacao leva o `asset_id`", () => {
  it("o dono: o MED recebe o pedido da Meta, e a invocacao leva so o `asset_id`", async () => {
    const { instancia, aoAgr, pedidos } = chr(armazenada);
    await instancia.tratar(evento(foto()));
    assert.deepEqual(pedidos, [
      {
        tenantId: TENANT,
        contactId: CONTACTO,
        conversationId: CONVERSA,
        wamid: "wamid.FOTO999",
        mediaId: MEDIA_DA_META,
        waType: "image",
        contentTypeAnunciado: "image/jpeg",
      },
    ]);
    assert.equal(aoAgr.length, 1);
    const invocacao = aoAgr[0]!;
    assert.equal(invocacao.asset_id, ASSET);
    assert.equal(invocacao.persona, "dono");
    assert.equal(invocacao.type, "image");
    // Nada da Meta nem do STO sai do CHR.
    const corpo = JSON.stringify(invocacao);
    assert.ok(!corpo.includes(MEDIA_DA_META));
    assert.ok(!corpo.includes("media://"));
    assert.ok(!corpo.includes("image/jpeg"));
  });

  it("um cliente: o MED nao e chamado, e a invocacao vai sem `asset_id`", async () => {
    const { instancia, base, aoAgr, pedidos } = chr(armazenada);
    base.papel = "cliente";
    await instancia.tratar(evento(foto()));
    assert.equal(pedidos.length, 0);
    assert.equal("asset_id" in aoAgr[0]!, false);
  });

  it("rejeitada, falhada ou por acabar: a invocacao vai sem `asset_id`", async () => {
    const respostas: ResultadoDeMidia[] = [
      { estado: "rejeitado", assetId: ASSET, motivo: "tamanho_excedido", resposta: "x" },
      { estado: "falhou", assetId: ASSET, tentativas: 3 },
      { estado: "pendente", assetId: ASSET },
    ];
    for (const resposta of respostas) {
      const { instancia, aoAgr } = chr(resposta);
      await instancia.tratar(evento(foto()));
      assert.equal("asset_id" in aoAgr[0]!, false, resposta.estado);
    }
  });

  it("sem MED montado, a foto vai ao AGR sem `asset_id`, como ate aqui", async () => {
    const { instancia, aoAgr } = chr(null);
    await instancia.tratar(evento(foto()));
    assert.equal("asset_id" in aoAgr[0]!, false);
  });

  it("uma `image` sem `id` nao chama o MED", async () => {
    const { instancia, aoAgr, pedidos } = chr(armazenada);
    await instancia.tratar(evento(foto({ mime_type: "image/jpeg" })));
    assert.equal(pedidos.length, 0);
    assert.equal("asset_id" in aoAgr[0]!, false);
  });

  it("uma falha da base no MED lanca, e o job da `wa-inbound` repete", async () => {
    const { instancia, aoAgr } = chr(new Error("base em baixo"));
    await assert.rejects(instancia.tratar(evento(foto())), /base em baixo/);
    assert.equal(aoAgr.length, 0);
  });

  it("o `media_id` da Meta nao vai ao registo", async () => {
    const { instancia, registos } = chr(armazenada);
    await instancia.tratar(evento(foto()));
    assert.ok(!JSON.stringify(registos).includes(MEDIA_DA_META));
  });
});
