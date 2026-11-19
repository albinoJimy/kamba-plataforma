/**
 * A resposta do AGR de ponta a ponta, contra o PostgreSQL e o `GraphFalso` (KAM-224).
 *
 *     AGR      INSERT agent_replies + evt_emitir('agent.replied')   (o SQL do saida.py)
 *     outbox   o envelope que a evt_emitir construiu
 *     consumo  processar() do KAM-006, consumidor outbound ou painel
 *     Saida    o Outbound do KAM-015, numa ligação própria, com o PreSendGuard
 *     Graph    o servidor falso do KAM-024, que conta as chamadas
 *
 * **O lado do AGR corre com as instruções do próprio `saida.py`**, lidas do
 * ficheiro e com os `%s` do condutor Python traduzidos para `$n`: o AGR é Python
 * e esta bateria é Node, e uma cópia do SQL aqui era uma segunda fonte que
 * podia divergir sem ninguém ver. A transacção é a mesma — `SET LOCAL` do
 * tenant, o `INSERT ... ON CONFLICT DO NOTHING RETURNING` e, se a linha nasceu,
 * a `evt_emitir`. O ensaio do lado Python, contra a mesma base, é o
 * `db/tests_agr/test_agent_replies.py`.
 *
 * O que só aqui se prova, por grupo:
 *
 * - **um turno com resposta dá 1 envio** pelo `Saida`, contado pelo Graph;
 * - **a reentrega 3× continua a dar 1**, e o turno repetido não emite;
 * - **o evento de outro tenant não chega**: o `reply_id` de A num envelope de B
 *   não encontra linha sob a RLS de B, e vai à DLQ sem enviar;
 * - **canal desconhecido vai à DLQ**, e não sai pelo WhatsApp;
 * - **turno → evento → painel**: o consumidor do painel marca a linha, e o do
 *   WhatsApp ignora-a;
 * - **a guarda do KAM-018 suprime** a resposta de uma conversa em modo humano.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { GraphFalso, Gerador as GeradorDeFixtures } from "@kamba/meta-sim";

import { processar, type Envelope } from "../src/eventos/index.ts";
import type { ClienteDaMeta, Destinatario } from "../src/outbound/index.ts";
import {
  CONSUMIDOR_DO_OUTBOUND,
  CONSUMIDOR_DO_PAINEL,
  efeitoDoOutbound,
  efeitoDoPainel,
  envioPeloSaida,
  type DesfechoDaResposta,
} from "../src/resposta/index.ts";
import { BASE_DESCARTAVEL, apagarTenant, criarCanal, criarTenant, ligar, poolDe } from "./apoio.ts";

/** Uma constante de SQL do `saida.py`, com os `%s` em `$n`. */
function sqlDoAgr(nome: string): string {
  const fonte = readFileSync(
    new URL("../../../services/agr/src/kamba_agr/saida.py", import.meta.url),
    "utf8",
  );
  const bloco = new RegExp(`^${nome}: Final = \\(\\n([\\s\\S]*?)\\n\\)`, "m").exec(fonte);
  assert.ok(bloco, `o saida.py nao tem ${nome}`);
  const partes = [...bloco[1]!.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]!);
  let n = 0;
  return partes.join("").replace(/%s/g, () => `$${++n}`);
}

const SQL_INSERIR = sqlDoAgr("SQL_INSERIR");
const SQL_EMITIR = sqlDoAgr("SQL_EMITIR");

describe("a resposta do AGR contra a base", () => {
  let admin: pg.Client;
  let consumo: pg.Client;
  let produtor: pg.Client;
  let envios: pg.Pool;
  let graph: GraphFalso;
  const tenants: string[] = [];

  interface Conversa {
    readonly tenant: string;
    readonly contacto: string;
    readonly conversa: string;
  }

  async function conversaNova(rotulo: string, modo = "bot"): Promise<Conversa> {
    const tenant = await criarTenant(admin, rotulo);
    tenants.push(tenant);
    const canal = await criarCanal(admin, tenant);
    const contacto = (
      await admin.query<{ contact_id: string }>(
        "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id::text AS contact_id",
        [tenant],
      )
    ).rows[0]!.contact_id;
    const conversa = (
      await admin.query<{ id: string }>(
        "INSERT INTO platform.conversations " +
          "(tenant_id, contact_id, channel_id, mode, last_inbound_at, window_expires_at) " +
          "VALUES ($1, $2, $3, $4, now(), now() + interval '24 hours') RETURNING id::text AS id",
        [tenant, contacto, canal.id, modo],
      )
    ).rows[0]!.id;
    return { tenant, contacto, conversa };
  }

  /** O que o `enfileirar` do AGR faz: linha e evento, numa transacção. */
  async function turno(c: Conversa, chave: string, canal = "whatsapp", botoes: unknown[] = []): Promise<string | null> {
    await produtor.query("BEGIN");
    try {
      await produtor.query("SELECT set_config('app.tenant_id', $1, true)", [c.tenant]);
      const { rows } = await produtor.query<{ reply_id: string }>(SQL_INSERIR, [
        c.tenant,
        chave,
        c.contacto,
        c.conversa,
        canal,
        "Temos em stock.",
        JSON.stringify(botoes),
        new Date(Date.now() - 2_000),
      ]);
      const reply = rows[0]?.reply_id ?? null;
      if (reply !== null) {
        const payload = {
          reply_id: String(reply),
          thread_id: `${c.tenant}:${c.contacto}`,
          conversation_id: c.conversa,
          contact_id: c.contacto,
          canal,
        };
        await produtor.query(SQL_EMITIR, ["agent.replied", c.tenant, c.conversa, JSON.stringify(payload)]);
      }
      await produtor.query("COMMIT");
      return reply === null ? null : String(reply);
    } catch (erro) {
      await produtor.query("ROLLBACK");
      throw erro;
    }
  }

  async function envelopes(tenant: string): Promise<Envelope[]> {
    const { rows } = await admin.query<{ envelope: Envelope }>(
      "SELECT envelope FROM platform.events_outbox WHERE tenant_id = $1 AND tipo = 'agent.replied' ORDER BY agregado_seq",
      [tenant],
    );
    return rows.map((r) => r.envelope);
  }

  const meta: ClienteDaMeta = {
    enviar: async (phoneNumberId, para, corpo) => {
      const resposta = graph.responder({
        metodo: "POST",
        caminho: `/v23.0/${phoneNumberId}/messages`,
        consulta: {},
        corpo: { to: para.bsuid ?? para.telefone ?? "", tipo: corpo.tipo },
        cabecalhos: {},
      });
      if (resposta.estado !== 200 || resposta.corpo instanceof Uint8Array) {
        return { ok: false, codigo: 130429, estadoHttp: resposta.estado, esperar: null };
      }
      const mensagens = resposta.corpo.messages as { id: string }[];
      return { ok: true, wamid: mensagens[0]?.id ?? "" };
    },
  };

  const desfechos: DesfechoDaResposta[] = [];
  function outbound() {
    return efeitoDoOutbound(
      envioPeloSaida({
        tomar: async () => envios.connect(),
        devolver: (l, erro) => (l as pg.PoolClient).release(erro instanceof Error ? erro : undefined),
        meta,
        // O destinatário entra por porta: só `kamba_identity` lê os endpoints.
        destinatario: async (): Promise<Destinatario> => ({ bsuid: "AO.ENSAIOENSAIOENSAIO0224", telefone: null }),
      }),
      { aoTratar: (d) => desfechos.push(d) },
    );
  }

  function consumir(consumer: string, envelope: Envelope, tentativa = 1) {
    return processar(
      { bd: consumo, consumer, envelope, exigeOrdem: false, tentativa },
      consumer === CONSUMIDOR_DO_OUTBOUND ? outbound() : efeitoDoPainel({ aoTratar: (d) => desfechos.push(d) }),
    );
  }

  async function enviadas(tenant: string): Promise<string[]> {
    const { rows } = await admin.query<{ chave: string }>(
      "SELECT idempotency_key AS chave FROM platform.outbound_messages WHERE tenant_id = $1 AND state <> 'suppressed' ORDER BY 1",
      [tenant],
    );
    return rows.map((r) => r.chave);
  }

  async function entregue(reply: string): Promise<boolean> {
    const { rows } = await admin.query<{ e: boolean }>(
      "SELECT entregue_at IS NOT NULL AS e FROM platform.agent_replies WHERE reply_id = $1",
      [reply],
    );
    return rows[0]!.e;
  }

  async function dlq(tenant: string, consumer: string): Promise<string[]> {
    const { rows } = await admin.query<{ erro: string }>(
      "SELECT erro FROM platform.events_dlq WHERE tenant_id = $1 AND consumer = $2",
      [tenant, consumer],
    );
    return rows.map((r) => r.erro);
  }

  before(async () => {
    admin = await ligar("admin");
    consumo = await ligar("app");
    produtor = await ligar("app");
    envios = poolDe("app", 2);
    const nome = await admin.query<{ base: string }>("SELECT current_database() AS base");
    assert.equal(nome.rows[0]?.base, BASE_DESCARTAVEL, "esta suite so corre contra a base descartavel do gate 8");
    graph = new GraphFalso(new GeradorDeFixtures("resposta-bd"));
  });

  after(async () => {
    for (const tenant of tenants) {
      for (const tabela of ["events_consumed", "events_dlq"]) {
        await admin.query(`DELETE FROM platform.${tabela} WHERE tenant_id = $1`, [tenant]);
      }
      await apagarTenant(admin, tenant);
    }
    await envios.end();
    await Promise.allSettled([consumo.end(), produtor.end()]);
    await admin.end();
  });

  describe("um turno, um envio (criterio 4)", () => {
    it("**um turno com resposta dá 1 envio pelo Saida, e a reentrega 3× continua a dar 1**", async () => {
      const c = await conversaNova("resposta-um");
      const reply = await turno(c, "wamid.um:0", "whatsapp", [{ id: "falar_com_humano", titulo: "Falar com um colega" }]);
      assert.ok(reply);
      const [envelope] = await envelopes(c.tenant);
      assert.ok(envelope);
      assert.equal(envelope.payload["reply_id"], reply);
      assert.equal("texto" in envelope.payload, false, "o texto nao vai no evento");

      const antes = graph.envios;
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, envelope)).desfecho, "aplicado");
      for (let i = 0; i < 3; i += 1) {
        assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, envelope)).desfecho, "duplicado");
      }
      assert.equal(graph.envios - antes, 1, "uma chamada a Meta, contada pelo servidor falso");
      assert.deepEqual(await enviadas(c.tenant), ["wamid.um:0"], "uma linha, com a chave do turno");
      assert.equal(await entregue(reply), true);
    });

    it("o turno repetido pelo shim não emite outra vez, e não envia outra vez", async () => {
      const c = await conversaNova("resposta-repetido");
      const primeira = await turno(c, "wamid.rep:0");
      const repetidas = [await turno(c, "wamid.rep:0"), await turno(c, "wamid.rep:0"), await turno(c, "wamid.rep:0")];
      assert.ok(primeira);
      assert.deepEqual(repetidas, [null, null, null]);
      const todos = await envelopes(c.tenant);
      assert.equal(todos.length, 1);
      const antes = graph.envios;
      await consumir(CONSUMIDOR_DO_OUTBOUND, todos[0]!);
      assert.equal(graph.envios - antes, 1);
    });

    it("um segundo evento sobre a mesma resposta pára na linha e na chave do Saida", async () => {
      const c = await conversaNova("resposta-segundo");
      await turno(c, "wamid.seg:0");
      const [envelope] = await envelopes(c.tenant);
      await consumir(CONSUMIDOR_DO_OUTBOUND, envelope!);
      const antes = graph.envios;
      // O mesmo conteúdo num envelope novo: o `events_consumed` não o trava.
      const outro = { ...envelope!, id: randomUUID() };
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, outro)).desfecho, "aplicado");
      assert.equal(graph.envios - antes, 0);
    });
  });

  describe("isolamento: o tenant é o do envelope", () => {
    it("o reply_id de A num envelope de B não envia nada e vai à DLQ de B", async () => {
      const a = await conversaNova("resposta-a");
      const b = await conversaNova("resposta-b");
      await turno(a, "wamid.iso:0");
      const [deA] = await envelopes(a.tenant);
      const forjado: Envelope = {
        ...deA!,
        id: randomUUID(),
        tenant_id: b.tenant,
        payload: { ...deA!.payload, thread_id: `${b.tenant}:${String(deA!.payload["contact_id"])}` },
      };
      const antes = graph.envios;
      // A primeira tentativa recua; a última abre a DLQ.
      await assert.rejects(consumir(CONSUMIDOR_DO_OUTBOUND, forjado, 1), /RespostaInexistente|sem linha/);
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, forjado, 6)).desfecho, "dlq");
      assert.equal(graph.envios - antes, 0);
      assert.deepEqual(await enviadas(a.tenant), []);
      assert.deepEqual(await enviadas(b.tenant), []);
      assert.equal((await dlq(b.tenant, CONSUMIDOR_DO_OUTBOUND)).length, 1);
      assert.equal(await entregue(String(deA!.payload["reply_id"])), false);
    });
  });

  describe("adversarial", () => {
    it("**um evento com canal desconhecido vai à DLQ**, e não sai pelo WhatsApp", async () => {
      const c = await conversaNova("resposta-canal");
      const reply = await turno(c, "wamid.canal:0");
      const [envelope] = await envelopes(c.tenant);
      const forjado: Envelope = { ...envelope!, id: randomUUID(), payload: { ...envelope!.payload, canal: "sms" } };
      const antes = graph.envios;
      const r = await consumir(CONSUMIDOR_DO_OUTBOUND, forjado, 6);
      assert.equal(r.desfecho, "dlq");
      assert.match(r.erro ?? "", /RespostaInvalidaError: .*canal desconhecido/);
      assert.equal(graph.envios - antes, 0);
      assert.equal(await entregue(reply!), false);
      assert.equal((await dlq(c.tenant, CONSUMIDOR_DO_OUTBOUND)).length, 1);
    });

    it("a guarda do KAM-018 suprime a resposta de uma conversa em modo humano", async () => {
      const c = await conversaNova("resposta-humano", "humano");
      const reply = await turno(c, "wamid.hum:0");
      const [envelope] = await envelopes(c.tenant);
      const antes = graph.envios;
      desfechos.length = 0;
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, envelope!)).desfecho, "aplicado");
      assert.equal(graph.envios - antes, 0);
      assert.deepEqual(desfechos, ["recusada"]);
      assert.equal(await entregue(reply!), false);
    });
  });

  describe("turno → evento → painel", () => {
    it("o consumidor do painel marca a resposta uma vez, e o do WhatsApp ignora-a", async () => {
      const c = await conversaNova("resposta-painel");
      const reply = await turno(c, "painel.um:0", "painel");
      const [envelope] = await envelopes(c.tenant);
      const antes = graph.envios;
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, envelope!)).desfecho, "aplicado");
      assert.equal(await entregue(reply!), false, "o consumidor do WhatsApp nao toca na do painel");
      assert.equal((await consumir(CONSUMIDOR_DO_PAINEL, envelope!)).desfecho, "aplicado");
      assert.equal(await entregue(reply!), true);
      for (let i = 0; i < 3; i += 1) {
        assert.equal((await consumir(CONSUMIDOR_DO_PAINEL, envelope!)).desfecho, "duplicado");
      }
      assert.equal(graph.envios - antes, 0);
    });

    it("o consumidor do painel ignora a resposta do WhatsApp", async () => {
      const c = await conversaNova("resposta-painel-wa");
      const reply = await turno(c, "wamid.pw:0");
      const [envelope] = await envelopes(c.tenant);
      assert.equal((await consumir(CONSUMIDOR_DO_PAINEL, envelope!)).desfecho, "aplicado");
      assert.equal(await entregue(reply!), false);
    });
  });
});
