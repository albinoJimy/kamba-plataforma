/**
 * O texto do cliente do WhatsApp na fonte persistida (KAM-232).
 *
 * O caminho de produção é webhook → explosão → CHR → `agent_messages` e fila
 * `agr-inbound` → AGR. Aqui prova-se a metade TypeScript, de ponta a ponta e
 * sem base: um corpo da Meta com uma mensagem `text` sai do `Chr.tratar` com
 * **uma** instrução de gravação, e a invocação que sai é **exactamente** a de
 * `fixtures/invocacao_do_whatsapp.json` — o mesmo ficheiro que o
 * `services/agr/tests/test_mensagens.py` (`TestDoWhatsAppAoCheckpoint`) passa ao
 * `ler_invocacao` e leva até ao *checkpoint*. A gravação contra a base, com a
 * reentrega, é o `tests_bd/chr.bd.test.ts`.
 *
 * E as ausências: o texto nunca vai na invocação, nem no registo, nem na
 * quarentena; e uma mensagem que não vai ao AGR não grava texto nenhum.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  Chr,
  type ClienteDoChr,
  DOMINIO_DO_MESSAGE_ID,
  type EntregaDoChr,
  MetricasDoChr,
  ResolvedorDeCanal,
  SQL_GRAVAR_MENSAGEM_DO_WHATSAPP,
  jobIdDe,
  messageIdDe,
} from "../src/chr/index.ts";
import type { AgentInvocation } from "../src/chr/index.ts";
import { TEXTO_MAXIMO, explodir } from "../src/entrada/explosao.ts";
import { linhaDeCanal } from "./apoio/chr-base-falsa.ts";

const FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/invocacao_do_whatsapp.json", import.meta.url), "utf8"),
) as { readonly texto: string; readonly corpo: Readonly<Record<string, unknown>> };
const ALVO = FIXTURE.corpo;
const TEXTO = FIXTURE.texto;
const PAN = "4111111111111111";

const PNID = "999000000000001";
const WABA = "999000000000002";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// ------------------------------------------------------------------ o corpo

function corpoDe(mensagem: Readonly<Record<string, unknown>>, wamid = String(ALVO["wamid"])): unknown {
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
                  from: "244 999 000 002",
                  from_user_id: "AO.BSUID.CLIENTE.999",
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

const texto = (body: unknown, wamid?: string) => corpoDe({ type: "text", text: { body } }, wamid);

function evento(corpo: unknown) {
  const { eventos } = explodir(corpo, "a".repeat(64));
  assert.equal(eventos.length, 1);
  return eventos[0]!;
}

// --------------------------------------------------------------- o CHR falso

/**
 * A conversa, o papel e a `agent_messages`, com a `PRIMARY KEY` e o `ON
 * CONFLICT` lidos do **texto** da instrução: sem o `ON CONFLICT`, uma segunda
 * gravação do mesmo `message_id` lança, como a base.
 */
class Base implements ClienteDoChr {
  readonly mensagens = new Map<string, readonly unknown[]>();
  readonly gravacoes: { readonly sql: string; readonly parametros: readonly unknown[] }[] = [];
  modo = "bot";

  async query(sql: string, parametros: readonly unknown[] = []) {
    if (sql.includes("INSERT INTO platform.conversations")) {
      return { rows: [{ id: ALVO["conversation_id"], mode: this.modo }] };
    }
    if (sql.includes("platform.agent_messages")) {
      this.gravacoes.push({ sql, parametros });
      const id = String(parametros[0]);
      if (this.mensagens.has(id)) {
        if (!/ON CONFLICT \(message_id\) DO NOTHING/.test(sql)) {
          throw new Error("duplicate key value violates unique constraint agent_messages_pkey");
        }
        return { rows: [] };
      }
      this.mensagens.set(id, parametros);
      return { rows: [] };
    }
    return { rows: [] };
  }
}

class Entrega implements EntregaDoChr {
  readonly aoAgr: AgentInvocation[] = [];
  readonly aoDono: unknown[] = [];
  falha: Error | null = null;
  async agr(invocacao: AgentInvocation): Promise<void> {
    if (this.falha !== null) throw this.falha;
    this.aoAgr.push(invocacao);
  }
  async dono(entrega: unknown): Promise<void> {
    this.aoDono.push(entrega);
  }
}

function chr(canal: Readonly<Record<string, unknown>> = {}) {
  const entrega = new Entrega();
  const base = new Base();
  const registos: unknown[] = [];
  const quarentena: unknown[] = [];
  const ordem: string[] = [];
  const canalFalso: ClienteDoChr = {
    query: async (_sql, parametros = []) =>
      parametros[0] === PNID
        ? {
            rows: [
              linhaDeCanal({ tenant_id: ALVO["tenant_id"], channel_id: ALVO["channel_id"], ...canal }),
            ],
          }
        : { rows: [] },
  };
  const instancia = new Chr({
    resolvedor: new ResolvedorDeCanal(canalFalso),
    contacto: async () => ({ contactId: String(ALVO["contact_id"]) }),
    entrega: {
      agr: async (i) => {
        ordem.push("agr");
        await entrega.agr(i);
      },
      dono: async (e) => {
        ordem.push("dono");
        await entrega.dono(e);
      },
    },
    quarentena: async (e, motivo) => {
      quarentena.push({ e, motivo });
    },
    metricas: new MetricasDoChr(),
    registar: (campos) => registos.push(campos),
    comTenant: async (tenant, trabalho) => {
      ordem.push(`tx:${tenant}`);
      return trabalho(base);
    },
  });
  return { instancia, entrega, base, registos, quarentena, ordem };
}

// ------------------------------------------------------------------ explosao

describe("KAM-232 — o `text.body` sai da explosao", () => {
  it("uma mensagem `text` da o texto, aparado", () => {
    assert.equal(evento(texto(TEXTO)).texto, TEXTO);
    assert.equal(evento(texto(`  ${TEXTO}\n`)).texto, TEXTO);
    assert.equal(evento(texto("x".repeat(TEXTO_MAXIMO))).texto, "x".repeat(TEXTO_MAXIMO));
  });

  it("acima do tecto e cortado, em pontos de codigo, e nao largado", () => {
    assert.equal(evento(texto("x".repeat(TEXTO_MAXIMO + 1))).texto, "x".repeat(TEXTO_MAXIMO));
    // Um emoji sao duas unidades UTF-16 e um ponto de codigo, como o `char_length`.
    const emoji = "\u{1F600}";
    assert.equal(evento(texto(emoji.repeat(TEXTO_MAXIMO))).texto, emoji.repeat(TEXTO_MAXIMO));
    assert.equal(Array.from(evento(texto(emoji.repeat(TEXTO_MAXIMO + 5))).texto ?? "").length, TEXTO_MAXIMO);
  });

  it("o U+0000 sai, porque a base o recusa num `text`", () => {
    assert.equal(evento(texto("o\u0000la")).texto, "ola");
    assert.equal("texto" in evento(texto("\u0000 \u0000")), false);
  });

  it("vazio, so espacos ou fora de forma: sem texto, e a mensagem segue", () => {
    for (const body of ["", "   \n\t", 7, null, ["a"], { body: "a" }]) {
      const e = evento(texto(body));
      assert.equal(e.waType, "text");
      assert.equal("texto" in e, false, `body ${JSON.stringify(body).slice(0, 40)}`);
    }
    assert.equal("texto" in evento(corpoDe({ type: "text" })), false);
  });

  it("o tipo e que manda: um `text` colado a outro tipo nao conta", () => {
    for (const mensagem of [
      { type: "image", image: { id: "1" }, text: { body: TEXTO } },
      { type: "interactive", interactive: { type: "button_reply", button_reply: { id: "x" } }, text: { body: TEXTO } },
      { type: "button", button: { payload: "x", text: TEXTO } },
    ]) {
      assert.equal("texto" in evento(corpoDe(mensagem)), false);
    }
  });

  it("um `echo` e um `statuses` nunca tem texto", () => {
    const { eventos } = explodir(
      {
        object: "whatsapp_business_account",
        entry: [
          {
            id: WABA,
            changes: [
              {
                field: "smb_message_echoes",
                value: {
                  metadata: { phone_number_id: PNID },
                  message_echoes: [{ id: "wamid.eco", to: "244 999 000 003", type: "text", text: { body: TEXTO } }],
                },
              },
              {
                field: "messages",
                value: { metadata: { phone_number_id: PNID }, statuses: [{ id: "wamid.s", status: "sent" }] },
              },
            ],
          },
        ],
      },
      "a".repeat(64),
    );
    assert.ok(eventos.length >= 2);
    for (const e of eventos) assert.equal("texto" in e, false, e.kind);
  });
});

// ------------------------------------------------------------- o identificador

describe("KAM-232 — o `message_id` e deterministico e opaco", () => {
  const tenant = String(ALVO["tenant_id"]);
  const wamid = String(ALVO["wamid"]);

  it("e o da fixture, e um uuid canonico com a versao 8 e a variante RFC 9562", () => {
    const id = messageIdDe(tenant, wamid);
    assert.equal(id, ALVO["message_id"]);
    assert.match(id, UUID);
    assert.equal(id[14], "8");
    assert.ok("89ab".includes(id[19]!));
  });

  it("o mesmo `wamid` no mesmo tenant da sempre o mesmo, e outro tenant ou outro `wamid` nao", () => {
    assert.equal(messageIdDe(tenant, wamid), messageIdDe(tenant, wamid));
    assert.notEqual(messageIdDe(tenant, wamid), messageIdDe("22222222-2222-4222-8222-222222222222", wamid));
    assert.notEqual(messageIdDe(tenant, wamid), messageIdDe(tenant, `${wamid}x`));
  });

  it("nao se deduz do `jobId` da mesma mensagem, nem leva o `wamid`", () => {
    const id = messageIdDe(tenant, wamid).replaceAll("-", "");
    assert.ok(!jobIdDe(tenant, wamid).includes(id.slice(0, 12)));
    assert.ok(!id.includes(wamid));
    assert.equal(DOMINIO_DO_MESSAGE_ID, "agent_messages");
  });
});

// ---------------------------------------------------------- de ponta a ponta

describe("KAM-232 — webhook → explosao → CHR → `agent_messages` e `agent_invocation`", () => {
  it("grava o texto uma vez e entrega o corpo exacto da fixture, sem o texto", async () => {
    const { instancia, entrega, base } = chr();
    const resultado = await instancia.tratar(evento(texto(TEXTO)));
    assert.equal(resultado.desfecho, "encaminhado");
    assert.equal(entrega.aoAgr.length, 1);
    assert.deepEqual({ ...entrega.aoAgr[0] }, ALVO);
    assert.ok(!JSON.stringify(entrega.aoAgr[0]).includes(PAN));
    assert.ok(!JSON.stringify(entrega.aoAgr[0]).includes("cartao"));

    const [gravacao] = base.gravacoes;
    assert.equal(base.gravacoes.length, 1);
    assert.equal(gravacao!.sql, SQL_GRAVAR_MENSAGEM_DO_WHATSAPP);
    assert.deepEqual(gravacao!.parametros, [
      ALVO["message_id"],
      ALVO["tenant_id"],
      ALVO["contact_id"],
      ALVO["conversation_id"],
      TEXTO,
    ]);
    assert.match(gravacao!.sql, /'whatsapp'/);
  });

  it("grava antes de entregar, na transaccao do tenant do canal", async () => {
    const { instancia, ordem } = chr();
    await instancia.tratar(evento(texto(TEXTO)));
    const tx = `tx:${String(ALVO["tenant_id"])}`;
    assert.deepEqual(ordem, [tx, tx, "agr"]);
  });

  it("a reentrega 3x: o mesmo `message_id`, uma linha, e tres invocacoes iguais (a fila deduplica)", async () => {
    const { instancia, entrega, base } = chr();
    for (let n = 0; n < 3; n += 1) await instancia.tratar(evento(texto(TEXTO)));
    assert.equal(base.mensagens.size, 1);
    assert.equal(base.gravacoes.length, 3);
    assert.equal(new Set(entrega.aoAgr.map((i) => i.message_id)).size, 1);
    assert.deepEqual(entrega.aoAgr[2], entrega.aoAgr[0]);
  });

  it("uma entrega que falha deixa a linha, e a repeticao do job nao grava outra", async () => {
    const { instancia, entrega, base } = chr();
    entrega.falha = new Error("agr-inbound em baixo");
    await assert.rejects(instancia.tratar(evento(texto(TEXTO))), /agr-inbound em baixo/);
    assert.equal(base.mensagens.size, 1);
    entrega.falha = null;
    await instancia.tratar(evento(texto(TEXTO)));
    assert.equal(base.mensagens.size, 1);
    assert.equal(entrega.aoAgr[0]?.message_id, ALVO["message_id"]);
  });

  it("duas mensagens diferentes sao duas linhas, com identificadores diferentes", async () => {
    const { instancia, entrega, base } = chr();
    await instancia.tratar(evento(texto("primeira", "wamid.HBgLOTk5.um")));
    await instancia.tratar(evento(texto("segunda", "wamid.HBgLOTk5.dois")));
    assert.equal(base.mensagens.size, 2);
    assert.notEqual(entrega.aoAgr[0]?.message_id, entrega.aoAgr[1]?.message_id);
  });

  it("o texto nao vai ao registo nem a quarentena num turno encaminhado", async () => {
    const { instancia, registos, quarentena } = chr();
    await instancia.tratar(evento(texto(TEXTO)));
    const visto = JSON.stringify({ registos, quarentena });
    assert.ok(!visto.includes(PAN));
    assert.ok(!visto.includes("cartao"));
  });

  it("um texto de um interlocutor sem identidade vai a quarentena sem o texto", async () => {
    const { instancia, base, quarentena } = chr();
    const resultado = await instancia.tratar(
      evento(corpoDe({ type: "text", text: { body: TEXTO }, from: undefined, from_user_id: undefined })),
    );
    assert.equal(resultado.desfecho, "em_quarentena");
    assert.equal(base.gravacoes.length, 0);
    assert.equal(quarentena.length, 1);
    // O evento que chega a porta da quarentena ja nao tem o texto.
    assert.ok(!JSON.stringify(quarentena).includes(PAN));
    assert.ok(!JSON.stringify(quarentena).includes("cartao"));
  });
});

describe("KAM-232 — uma mensagem que nao vai ao AGR nao grava texto", () => {
  it("fora do modo `bot`: vai ao dono, e nada na `agent_messages`", async () => {
    for (const modo of ["humano", "dono", "pausada"]) {
      const { instancia, entrega, base } = chr();
      base.modo = modo;
      const resultado = await instancia.tratar(evento(texto(TEXTO)));
      assert.equal(resultado.desfecho, "entregue_ao_dono", modo);
      assert.equal(base.gravacoes.length, 0, modo);
      assert.equal(entrega.aoAgr.length, 0, modo);
    }
  });

  it("com a matriz a negar o processamento: nada na `agent_messages`", async () => {
    for (const estado_tenant of ["onboarding", "suspenso", "encerrado"]) {
      const { instancia, base, entrega } = chr({ estado_tenant });
      const resultado = await instancia.tratar(evento(texto(TEXTO)));
      assert.notEqual(resultado.desfecho, "encaminhado", estado_tenant);
      assert.equal(base.gravacoes.length, 0, estado_tenant);
      assert.equal(entrega.aoAgr.length, 0, estado_tenant);
    }
  });

  it("uma mensagem que nao e `text` vai ao AGR sem `message_id`", async () => {
    for (const mensagem of [
      { type: "image", image: { id: "1", mime_type: "image/jpeg" } },
      { type: "audio", audio: { id: "1", voice: true } },
      { type: "location", location: { latitude: -8.8, longitude: 13.2 } },
    ]) {
      const { instancia, base, entrega } = chr();
      await instancia.tratar(evento(corpoDe(mensagem)));
      assert.equal(base.gravacoes.length, 0, mensagem.type);
      assert.equal("message_id" in entrega.aoAgr[0]!, false, mensagem.type);
    }
  });
});
