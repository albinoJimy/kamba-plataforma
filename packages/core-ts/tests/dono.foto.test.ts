/**
 * A foto do dono pelo painel (KAM-243), sem base: a assinatura do tipo, o
 * `media_id` determinístico, a invocação que o painel monta, a ordem
 * contexto → MED → AGR e as recusas antes do MED.
 *
 * O MED contra o PostgreSQL, com a mesma foto duas vezes e dois tenants, está em
 * `tests_bd/media.bd.test.ts` («KAM-243 — a foto do painel»).
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { AGENT_INVOCATION_V1_PATH } from "@kamba/contracts";

import type { AgentInvocation } from "../src/chr/contrato.ts";
import {
  BYTES_MAXIMOS_DA_FOTO,
  FotoDoDono,
  invocacaoDaFoto,
  LIMITES_DO_PAINEL,
  mediaIdDoPainel,
  midiaDoPedido,
  sqlNoTenant,
  tipoDaFoto,
  type ContextoDoDono,
  type FotoDoPedido,
  type PortasDaFoto,
} from "../src/dono/index.ts";
import { LIMITES_POR_OMISSAO, type PedidoDeMidia, type ResultadoDeMidia } from "../src/med/index.ts";

const esquema = JSON.parse(readFileSync(AGENT_INVOCATION_V1_PATH, "utf8"));

const TENANT = "11111111-1111-4111-8111-111111111111";
const OUTRO_TENANT = "22222222-2222-4222-8222-222222222222";
const CONTEXTO: ContextoDoDono = {
  contactId: "33333333-3333-4333-8333-333333333333",
  conversationId: "44444444-4444-4444-8444-444444444444",
  channelId: "55555555-5555-4555-8555-555555555555",
  vertical: "vendedor",
  modo: "bot",
};
const ASSET = "66666666-6666-4666-8666-666666666666";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-8[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Uns bytes com a assinatura de um JPEG: sintéticos, não são uma fotografia. */
function jpeg(semente = 1, tamanho = 64): Uint8Array {
  const bytes = new Uint8Array(tamanho).fill(semente);
  bytes.set([0xff, 0xd8, 0xff, 0xe0]);
  return bytes;
}

function png(): Uint8Array {
  const bytes = new Uint8Array(32).fill(7);
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return bytes;
}

function portas(resultado: ResultadoDeMidia = { estado: "armazenado", assetId: ASSET, referencia: `media://${ASSET}`, repetido: false }, sobre: Partial<PortasDaFoto> = {}) {
  const ordem: string[] = [];
  const pedidos: { pedido: PedidoDeMidia; foto: FotoDoPedido }[] = [];
  const invocacoes: AgentInvocation[] = [];
  const p: PortasDaFoto = {
    contexto: async () => {
      ordem.push("contexto");
      return CONTEXTO;
    },
    receber: async (pedido, foto) => {
      ordem.push("receber");
      pedidos.push({ pedido, foto });
      return resultado;
    },
    invocar: async (invocacao) => {
      ordem.push("invocar");
      invocacoes.push(invocacao);
      return { estado: 200, desfecho: "executado" };
    },
    ...sobre,
  };
  return { p, ordem, pedidos, invocacoes };
}

describe("KAM-243 — o tipo da foto pela assinatura", () => {
  it("JPEG e PNG pelos octetos iniciais, e o resto nao", () => {
    assert.equal(tipoDaFoto(jpeg()), "image/jpeg");
    assert.equal(tipoDaFoto(png()), "image/png");
    assert.equal(tipoDaFoto(new TextEncoder().encode("isto nao e uma imagem")), null);
    // GIF e WebP sao imagens, e o descodificador do AGR nao os le.
    assert.equal(tipoDaFoto(new TextEncoder().encode("GIF89a........")), null);
    assert.equal(tipoDaFoto(new TextEncoder().encode("RIFF\0\0\0\0WEBPVP8 ")), null);
    assert.equal(tipoDaFoto(new Uint8Array([0xff, 0xd8])), null);
    assert.equal(tipoDaFoto(new Uint8Array()), null);
  });

  it("o tecto e o do MED para a classe media_imagem, e o painel so aceita JPEG e PNG", () => {
    assert.equal(BYTES_MAXIMOS_DA_FOTO, LIMITES_POR_OMISSAO.media_imagem.bytesMaximos);
    assert.deepEqual([...LIMITES_DO_PAINEL.media_imagem.tipos], ["image/jpeg", "image/png"]);
    assert.equal(LIMITES_DO_PAINEL.media_audio, LIMITES_POR_OMISSAO.media_audio);
  });
});

describe("KAM-243 — o media_id de uma foto do painel", () => {
  it("e painel.{uuid}, deterministico: a mesma foto no mesmo tenant da o mesmo", () => {
    const id = mediaIdDoPainel(TENANT, jpeg());
    assert.match(id, /^painel\./);
    assert.match(id.slice("painel.".length), UUID);
    assert.equal(mediaIdDoPainel(TENANT, jpeg()), id);
  });

  it("outra foto, ou a mesma noutro tenant, da outro", () => {
    const id = mediaIdDoPainel(TENANT, jpeg(1));
    assert.notEqual(mediaIdDoPainel(TENANT, jpeg(2)), id);
    assert.notEqual(mediaIdDoPainel(OUTRO_TENANT, jpeg(1)), id);
  });

  it("nao e o resumo dos bytes: o identificador nao diz que foto e", async () => {
    const { createHash } = await import("node:crypto");
    const resumo = createHash("sha256").update(jpeg()).digest("hex");
    assert.ok(!mediaIdDoPainel(TENANT, jpeg()).replace(/-/g, "").includes(resumo.slice(0, 16)));
  });
});

describe("KAM-243 — a invocacao de uma foto do painel", () => {
  it("leva o asset_id e o type image, com a persona dono, sem message_id e com o wamid painel.{asset_id}", () => {
    const inv = invocacaoDaFoto(TENANT, CONTEXTO, ASSET);
    assert.equal(inv.asset_id, ASSET);
    assert.equal(inv.type, "image");
    assert.equal(inv.persona, "dono");
    assert.equal(inv.wamid, `painel.${ASSET}`);
    assert.equal(inv.thread_id, `${TENANT}:${CONTEXTO.contactId}`);
    assert.equal(inv.message_id, undefined);
    assert.equal(inv.botao, undefined);
  });

  it("obedece ao esquema publicado, com o dependentSchemas do asset_id", () => {
    const inv = invocacaoDaFoto(TENANT, CONTEXTO, ASSET) as unknown as Record<string, unknown>;
    for (const campo of Object.keys(inv)) assert.ok(esquema.properties[campo] !== undefined, campo);
    for (const campo of esquema.required as string[]) assert.ok(campo in inv, campo);
    assert.match(String(inv["wamid"]), new RegExp(esquema.properties.wamid.pattern));
    assert.match(String(inv["asset_id"]), new RegExp(esquema.properties.asset_id.pattern));
    const dependente = esquema.dependentSchemas.asset_id;
    for (const campo of dependente.required as string[]) assert.ok(campo in inv, campo);
    assert.equal(inv["type"], dependente.properties.type.const);
    assert.equal(inv["persona"], dependente.properties.persona.const);
  });
});

describe("KAM-243 — a FotoDoDono", () => {
  it("contexto, MED e AGR, por esta ordem, com o media_id e o wamid do painel no pedido ao MED", async () => {
    const { p, ordem, pedidos, invocacoes } = portas();
    const bytes = jpeg();
    const r = await new FotoDoDono(p).enviar(TENANT, bytes);
    assert.deepEqual(r, { enviada: true, assetId: ASSET, repetida: false, desfecho: "executado" });
    assert.deepEqual(ordem, ["contexto", "receber", "invocar"]);
    const [{ pedido, foto }] = pedidos as [{ pedido: PedidoDeMidia; foto: FotoDoPedido }];
    assert.equal(pedido.tenantId, TENANT);
    assert.equal(pedido.contactId, CONTEXTO.contactId);
    assert.equal(pedido.conversationId, CONTEXTO.conversationId);
    assert.equal(pedido.waType, "image");
    assert.equal(pedido.mediaId, mediaIdDoPainel(TENANT, bytes));
    assert.equal(pedido.wamid, pedido.mediaId);
    assert.equal(foto.tipo, "image/jpeg");
    assert.equal(foto.bytes, bytes);
    assert.equal(invocacoes[0]?.asset_id, ASSET);
    assert.equal(invocacoes[0]?.tenant_id, TENANT);
  });

  it("a mesma foto duas vezes e o mesmo media_id, e a segunda diz-se repetida", async () => {
    const { p, pedidos, invocacoes } = portas({ estado: "armazenado", assetId: ASSET, referencia: `media://${ASSET}`, repetido: true });
    const foto = new FotoDoDono(p);
    await foto.enviar(TENANT, jpeg());
    const r = await foto.enviar(TENANT, jpeg());
    assert.equal(r.enviada && r.repetida, true);
    assert.equal(pedidos[0]?.pedido.mediaId, pedidos[1]?.pedido.mediaId);
    assert.equal(invocacoes[0]?.wamid, invocacoes[1]?.wamid);
  });

  it("o que nao e imagem recusa-se antes do contexto e do MED", async () => {
    const { p, ordem } = portas();
    const r = await new FotoDoDono(p).enviar(TENANT, new TextEncoder().encode("%PDF-1.7 nao e foto"));
    assert.deepEqual(r, { enviada: false, motivo: "tipo" });
    assert.deepEqual(ordem, []);
  });

  it("acima do tecto recusa-se antes do contexto e do MED", async () => {
    const { p, ordem } = portas();
    const r = await new FotoDoDono(p).enviar(TENANT, jpeg(1, BYTES_MAXIMOS_DA_FOTO + 1));
    assert.deepEqual(r, { enviada: false, motivo: "tamanho" });
    assert.deepEqual(ordem, []);
    const noTecto = await new FotoDoDono(portas().p).enviar(TENANT, jpeg(1, BYTES_MAXIMOS_DA_FOTO));
    assert.equal(noTecto.enviada, true);
  });

  it("sem dono ou sem canal, nada se guarda nem se invoca", async () => {
    for (const motivo of ["sem_dono", "sem_canal"] as const) {
      const { p, ordem } = portas(undefined, { contexto: async () => motivo });
      const r = await new FotoDoDono(p).enviar(TENANT, jpeg());
      assert.deepEqual(r, { enviada: false, motivo });
      assert.deepEqual(ordem, []);
    }
  });

  it("o que o MED nao guardou nao vai ao AGR", async () => {
    const casos: [ResultadoDeMidia, string][] = [
      [{ estado: "rejeitado", assetId: ASSET, motivo: "tipo_nao_permitido", resposta: "x" }, "tipo"],
      [{ estado: "rejeitado", assetId: ASSET, motivo: "tamanho_excedido", resposta: "x" }, "tamanho"],
      [{ estado: "pendente", assetId: ASSET }, "a_tratar"],
      [{ estado: "falhou", assetId: ASSET, tentativas: 3 }, "falhou"],
    ];
    for (const [resultado, motivo] of casos) {
      const { p, invocacoes } = portas(resultado);
      const r = await new FotoDoDono(p).enviar(TENANT, jpeg());
      assert.deepEqual(r, { enviada: false, motivo, assetId: ASSET });
      assert.equal(invocacoes.length, 0);
    }
  });

  it("um AGR que nao aceita deixa a foto guardada e diz agr", async () => {
    for (const estado of [0, 401, 503]) {
      const { p } = portas(undefined, { invocar: async () => ({ estado, desfecho: "desconhecido" }) });
      const r = await new FotoDoDono(p).enviar(TENANT, jpeg());
      assert.deepEqual(r, { enviada: false, motivo: "agr", assetId: ASSET });
    }
  });
});

describe("KAM-243 — o MED com os bytes do pedido", () => {
  it("o cliente de midia devolve os bytes do pedido com o tipo da assinatura, e nenhum URL de fora", async () => {
    const foto: FotoDoPedido = { bytes: png(), tipo: "image/png" };
    const midia = midiaDoPedido(foto);
    const resolvida = await midia.resolver(TENANT, "painel.x");
    assert.ok(!/^https?:/.test(resolvida.url));
    assert.equal(resolvida.tamanho, foto.bytes.byteLength);
    const descarregada = await midia.descarregar(TENANT, resolvida);
    assert.equal(descarregada.bytes, foto.bytes);
    assert.equal(descarregada.contentType, "image/png");
  });

  it("cada instrucao corre na sua transaccao, com o tenant do pedido", async () => {
    const vistas: string[] = [];
    const ligacao = {
      query: async (sql: string, parametros?: readonly unknown[]) => {
        vistas.push(parametros !== undefined && parametros.length > 0 && sql.includes("set_config") ? `set:${String(parametros[0])}` : sql.trim().split(/\s+/)[0]!);
        return { rows: sql.includes("RESERVA") ? [{ asset_id: ASSET }] : [] };
      },
    };
    const bd = sqlNoTenant(ligacao, TENANT);
    const r1 = await bd.query<{ asset_id: string }>("SELECT 'RESERVA'", []);
    await bd.query("SELECT 2");
    assert.deepEqual(r1.rows, [{ asset_id: ASSET }]);
    const comecos = vistas.filter((v) => v === "BEGIN").length;
    assert.equal(comecos, 2);
    assert.equal(vistas.filter((v) => v === "COMMIT").length, 2);
    assert.ok(vistas.includes(`set:${TENANT}`));
  });
});
