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
 * - **a guarda do KAM-018 suprime** a resposta de uma conversa em modo humano;
 * - **as portas de produção do KAM-227**: o *token* do canal lido pelo
 *   `token_ref` sob a RLS, o destinatário pelo `lerEndpoints` numa ligação
 *   `kamba_identity`, e o *token* de A na linha de B que não abre;
 * - **o reenvio pela chave derivada**: uma linha `queued` da chave do turno, e
 *   uma falha da Meta na primeira tentativa, dão um envio, e um só.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { GraphFalso, Gerador as GeradorDeFixtures } from "@kamba/meta-sim";

import type { Envelope } from "../src/eventos/index.ts";
import { processar } from "../src/eventos/trabalho.ts";
import type { Identidade } from "../src/identity/index.ts";
import { cifrarToken } from "../src/onboarding/cifra.ts";
import { ClienteDaGraph, type ClienteDaMeta, type Destinatario } from "../src/outbound/index.ts";
import {
  CONSUMIDOR_DO_OUTBOUND,
  CONSUMIDOR_DO_PAINEL,
  CanalSemCredencialError,
  ESPERA_DO_REENVIO_S,
  arteDoSto,
  clienteDaGraphPorCanal,
  destinatarioPelaIdentidade,
  efeitoDoOutbound,
  efeitoDoPainel,
  envioPeloSaida,
  type DesfechoDaResposta,
} from "../src/resposta/index.ts";
import { EnvSecretProvider, nomeDaVariavel } from "../src/secrets/index.ts";
import { criarStorageFake, novaChave, type StorageProvider } from "../src/storage/index.ts";
import {
  BASE_DESCARTAVEL,
  ChavesDeTeste,
  apagarTenant,
  bsuidDeEnsaio,
  criarCanal,
  criarTenant,
  ligar,
  poolDe,
} from "./apoio.ts";

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
/** KAM-246: a linha com a chave da arte. */
const SQL_INSERIR_COM_MEDIA = sqlDoAgr("SQL_INSERIR_COM_MEDIA");

describe("a resposta do AGR contra a base", () => {
  let admin: pg.Client;
  let consumo: pg.Client;
  let produtor: pg.Client;
  let envios: pg.Pool;
  let identidades: pg.Pool;
  let identidade: Identidade;
  let graph: GraphFalso;
  const chaves = new ChavesDeTeste("k227");
  /** O ambiente do cofre dos ensaios de produção: a KEK e os criptogramas. */
  const cofreEnv: Record<string, string> = {
    KAMBA_SECRET_KEK_TOKEN_CLIENTE: `t1:${randomBytes(32).toString("base64")}`,
  };
  const KEK = cofreEnv["KAMBA_SECRET_KEK_TOKEN_CLIENTE"]!.slice(3);
  /** Falhar a próxima chamada à Meta com um código que o `Saida` não repete. */
  let falharProxima = false;
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
      if (falharProxima) {
        falharProxima = false;
        return { ok: false, codigo: 131000, estadoHttp: 500, esperar: null };
      }
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
        meta: async () => meta,
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
      "SELECT idempotency_key AS chave FROM platform.outbound_messages WHERE tenant_id = $1 AND state <> 'suppressed_by_human' ORDER BY 1",
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
    identidades = poolDe("identity", 2);
    identidade = await chaves.identidade();
    // A chave de pesquisa do HMAC tem de estar registada para o `resolveContact`
    // dos ensaios de produção. Idempotente; outra suite pode já a ter registado.
    const id = await identidades.connect();
    try {
      await identidade.iniciarRotacao(id, "k227").catch(() => {});
    } finally {
      id.release();
    }
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
    await identidades.end();
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

    it("um segundo evento sobre uma resposta já entregue pára no entregue_at e não chama o Saida", async () => {
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

  describe("no máximo uma vez, e o reenvio uma vez (KAM-015, KAM-227)", () => {
    it("uma linha do Outbound que ficou queued para a chave do turno reenvia uma vez, pela chave derivada", async () => {
      // O processo morreu entre a linha do Outbound e a rede: a linha existe,
      // `queued`, e o `Saida` responde `repetido` sem chamar a Meta.
      const c = await conversaNova("resposta-queued");
      const reply = await turno(c, "wamid.q:0");
      const canal = (
        await admin.query<{ channel_id: string }>(
          "SELECT channel_id::text AS channel_id FROM platform.conversations WHERE id = $1",
          [c.conversa],
        )
      ).rows[0]!.channel_id;
      await admin.query(
        "INSERT INTO platform.outbound_messages " +
          "(tenant_id, channel_id, contact_id, conversation_id, idempotency_key, kind, state) " +
          "VALUES ($1, $2, $3, $4, 'wamid.q:0', 'service', 'queued')",
        [c.tenant, canal, c.contacto, c.conversa],
      );
      const [envelope] = await envelopes(c.tenant);
      const antes = graph.envios;
      desfechos.length = 0;
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, envelope!)).desfecho, "aplicado");
      assert.equal(graph.envios - antes, 1, "um envio, e só pela chave derivada");
      assert.deepEqual(desfechos, ["reenviada"]);
      assert.deepEqual(await enviadas(c.tenant), ["wamid.q:0", "wamid.q:0:reenvio"]);
      assert.equal(await entregue(reply!), true);
      // Um segundo evento sobre a mesma resposta pára no entregue_at: não há terceira.
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, { ...envelope!, id: randomUUID() })).desfecho, "aplicado");
      assert.equal(graph.envios - antes, 1);
    });

    it("uma falha da Meta na primeira tentativa adia, e a segunda reenvia: um envio que saiu, e um só", async () => {
      const c = await conversaNova("resposta-falha");
      const reply = await turno(c, "wamid.f:0");
      const [envelope] = await envelopes(c.tenant);
      const antes = graph.envios;
      desfechos.length = 0;
      falharProxima = true;
      // O `Adiar` de 60 s: a fila devolveria o evento um minuto depois.
      const adiado = await consumir(CONSUMIDOR_DO_OUTBOUND, envelope!, 1);
      assert.equal(adiado.desfecho, "adiado");
      assert.equal(adiado.adiamento, ESPERA_DO_REENVIO_S);
      assert.equal(await entregue(reply!), false);
      assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, envelope!, 2)).desfecho, "aplicado");
      for (let i = 0; i < 3; i += 1) {
        assert.equal((await consumir(CONSUMIDOR_DO_OUTBOUND, envelope!, 1)).desfecho, "duplicado");
      }
      assert.equal(graph.envios - antes, 1, "a primeira falhou na Meta; a derivada saiu");
      assert.deepEqual(desfechos, ["reenviada"]);
      assert.deepEqual(await enviadas(c.tenant), ["wamid.f:0", "wamid.f:0:reenvio"]);
      assert.equal(await entregue(reply!), true);
    });
  });

  describe("as portas de produção (KAM-227)", () => {
    /** O `fetch` do cliente da Graph, ligado ao servidor falso, que guarda o cabeçalho. */
    const autorizacoes: string[] = [];
    const buscar = (async (url: string, init: RequestInit) => {
      const cabecalhos = init.headers as Record<string, string>;
      autorizacoes.push(cabecalhos["authorization"] ?? "");
      const corpo = JSON.parse(String(init.body)) as Record<string, unknown>;
      const r = graph.responder({
        metodo: "POST",
        caminho: new URL(url).pathname,
        consulta: {},
        corpo: { ...corpo, to: corpo["to"] ?? corpo["recipient"] ?? "" },
        cabecalhos: {},
      });
      return new Response(JSON.stringify(r.corpo), { status: r.estado });
    }) as unknown as typeof fetch;

    /** Guarda o criptograma do *token* de um canal no cofre e aponta o `token_ref` para ele. */
    async function tokenDoCanal(tenant: string, canal: string, token: string): Promise<string> {
      const ref = `meta_client_token/${randomBytes(16).toString("hex")}`;
      cofreEnv[nomeDaVariavel(ref)] = cifrarToken(KEK, "t1", tenant, token);
      await admin.query("UPDATE platform.tenant_channels SET token_ref = $3 WHERE tenant_id = $1 AND id = $2", [
        tenant,
        canal,
        ref,
      ]);
      return ref;
    }

    async function canalDe(c: { conversa: string }): Promise<string> {
      return (
        await admin.query<{ channel_id: string }>(
          "SELECT channel_id::text AS channel_id FROM platform.conversations WHERE id = $1",
          [c.conversa],
        )
      ).rows[0]!.channel_id;
    }

    function producao() {
      return efeitoDoOutbound(
        envioPeloSaida({
          tomar: async () => envios.connect(),
          devolver: (l, erro) => (l as pg.PoolClient).release(erro instanceof Error ? erro : undefined),
          meta: clienteDaGraphPorCanal({
            cofre: new EnvSecretProvider({ ambiente: "dev", env: cofreEnv }),
            buscar,
            base: "http://graph.ensaio",
          }),
          destinatario: destinatarioPelaIdentidade({
            identidade,
            tomar: async () => identidades.connect(),
            devolver: (l, erro) => (l as pg.PoolClient).release(erro instanceof Error ? erro : undefined),
          }),
        }),
        { aoTratar: (d, m) => desfechos.push(m === undefined ? d : (`${d}:${m}` as DesfechoDaResposta)) },
      );
    }

    /** Uma conversa cujo contacto nasceu pela identidade, com um BSUID de ensaio. */
    async function conversaComBsuid(rotulo: string): Promise<{ tenant: string; contacto: string; conversa: string }> {
      const c = await conversaNova(rotulo);
      const ligacao = await identidades.connect();
      try {
        const { contactId } = await identidade.resolveContact(ligacao, { tenantId: c.tenant, bsuid: bsuidDeEnsaio("P227") });
        await admin.query("UPDATE platform.conversations SET contact_id = $2 WHERE id = $1", [c.conversa, contactId]);
        return { ...c, contacto: contactId };
      } finally {
        ligacao.release();
      }
    }

    it("o token do canal pelo token_ref e o BSUID pela identidade: um envio, com o token certo", async () => {
      const c = await conversaComBsuid("resposta-producao");
      await tokenDoCanal(c.tenant, await canalDe(c), "token-de-ensaio-kam227-a");
      const reply = await turno(c, "wamid.prod:0");
      const [envelope] = await envelopes(c.tenant);
      const antes = graph.envios;
      desfechos.length = 0;
      autorizacoes.length = 0;
      const r = await processar({ bd: consumo, consumer: CONSUMIDOR_DO_OUTBOUND, envelope: envelope!, exigeOrdem: false, tentativa: 1 }, producao());
      assert.equal(r.desfecho, "aplicado");
      assert.deepEqual(desfechos, ["enviada"]);
      assert.equal(graph.envios - antes, 1);
      assert.deepEqual(autorizacoes, ["Bearer token-de-ensaio-kam227-a"]);
      assert.equal(await entregue(reply!), true);
    });

    it("**isolamento:** o token_ref de A na linha de B não abre sob B, e nada sai", async () => {
      const a = await conversaComBsuid("resposta-token-a");
      const b = await conversaComBsuid("resposta-token-b");
      const refDeA = await tokenDoCanal(a.tenant, await canalDe(a), "token-de-ensaio-kam227-de-a");
      await admin.query("UPDATE platform.tenant_channels SET token_ref = $3 WHERE tenant_id = $1 AND id = $2", [
        b.tenant,
        await canalDe(b),
        refDeA,
      ]);
      const reply = await turno(b, "wamid.iso2:0");
      const [envelope] = await envelopes(b.tenant);
      const antes = graph.envios;
      desfechos.length = 0;
      const r = await processar({ bd: consumo, consumer: CONSUMIDOR_DO_OUTBOUND, envelope: envelope!, exigeOrdem: false, tentativa: 1 }, producao());
      assert.equal(r.desfecho, "aplicado");
      assert.deepEqual(desfechos, ["sem_credencial:nao_abre"]);
      assert.equal(graph.envios - antes, 0);
      assert.deepEqual(await enviadas(b.tenant), [], "sem credencial, a linha do Outbound nem nasce");
      assert.equal(await entregue(reply!), false);
    });

    it("**token em falta** no cofre: sem_credencial, sem linha do Outbound, e a chave fica por gastar", async () => {
      const c = await conversaComBsuid("resposta-sem-token");
      await admin.query("UPDATE platform.tenant_channels SET token_ref = $3 WHERE tenant_id = $1 AND id = $2", [
        c.tenant,
        await canalDe(c),
        `meta_client_token/${randomBytes(16).toString("hex")}`,
      ]);
      const reply = await turno(c, "wamid.semtoken:0");
      const [envelope] = await envelopes(c.tenant);
      desfechos.length = 0;
      await processar({ bd: consumo, consumer: CONSUMIDOR_DO_OUTBOUND, envelope: envelope!, exigeOrdem: false, tentativa: 1 }, producao());
      assert.deepEqual(desfechos, ["sem_credencial:sem_segredo"]);
      assert.deepEqual(await enviadas(c.tenant), []);
      assert.equal(await entregue(reply!), false);
    });

    it("**destinatário sem BSUID nem telefone**: NO_RECIPIENT, e nada sai", async () => {
      // O contacto da `conversaNova` nasce sem endpoints: é o caso de um
      // contacto cujo telefone ficou só em HMAC (`chr/chr.ts`).
      const c = await conversaNova("resposta-sem-destino");
      await tokenDoCanal(c.tenant, await canalDe(c), "token-de-ensaio-kam227-c");
      const reply = await turno(c, "wamid.semdest:0");
      const [envelope] = await envelopes(c.tenant);
      const antes = graph.envios;
      desfechos.length = 0;
      await processar({ bd: consumo, consumer: CONSUMIDOR_DO_OUTBOUND, envelope: envelope!, exigeOrdem: false, tentativa: 1 }, producao());
      assert.deepEqual(desfechos, ["recusada:NO_RECIPIENT"]);
      assert.equal(graph.envios - antes, 0);
      assert.equal(await entregue(reply!), false);
    });

    it("a credencial lê-se como kamba_app sob a RLS: o canal de outro tenant não se vê", async () => {
      const a = await conversaComBsuid("resposta-rls-a");
      const b = await conversaComBsuid("resposta-rls-b");
      const canalDeA = await canalDe(a);
      await tokenDoCanal(a.tenant, canalDeA, "token-de-ensaio-kam227-rls");
      const numero = (
        await admin.query<{ n: string }>("SELECT phone_number_id AS n FROM platform.tenant_channels WHERE id = $1", [canalDeA])
      ).rows[0]!.n;
      const ligacao = await envios.connect();
      try {
        const ler = clienteDaGraphPorCanal({ cofre: new EnvSecretProvider({ ambiente: "dev", env: cofreEnv }) });
        await ler(ligacao, { tenantId: a.tenant, channelId: canalDeA, phoneNumberId: numero });
        await assert.rejects(
          ler(ligacao, { tenantId: b.tenant, channelId: canalDeA, phoneNumberId: numero }),
          (erro: unknown) => erro instanceof CanalSemCredencialError && erro.motivo === "sem_canal",
        );
      } finally {
        ligacao.release();
      }
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

  describe("a arte como imagem, antes do texto (KAM-246)", () => {
    const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x10, 0x4a, 0x46, 0x49, 0x46, 0, 1, 2, 3]);

    /** O que o `enfileirar` do AGR faz com imagem: a linha com a chave da arte, e o evento. */
    async function turnoComImagem(c: Conversa, chave: string, media: string): Promise<string | null> {
      await produtor.query("BEGIN");
      try {
        await produtor.query("SELECT set_config('app.tenant_id', $1, true)", [c.tenant]);
        const { rows } = await produtor.query<{ reply_id: string }>(SQL_INSERIR_COM_MEDIA, [
          c.tenant,
          chave,
          c.contacto,
          c.conversa,
          "whatsapp",
          "Pre-visualizacao. Legenda: Vestidos novos.",
          "[]",
          new Date(Date.now() - 2_000),
          media,
        ]);
        const reply = rows[0]?.reply_id ?? null;
        if (reply !== null) {
          const payload = {
            reply_id: String(reply),
            thread_id: `${c.tenant}:${c.contacto}`,
            conversation_id: c.conversa,
            contact_id: c.contacto,
            canal: "whatsapp",
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

    /** A Meta pelo HTTP do servidor falso: o cliente da Graph de verdade, com o carregamento. */
    async function comAGraphAEscuta<T>(trabalho: (efeito: ReturnType<typeof efeitoDoOutbound>, sto: StorageProvider) => Promise<T>): Promise<T> {
      const { base, fechar } = await graph.ouvir();
      const { storage: sto } = criarStorageFake();
      try {
        const efeito = efeitoDoOutbound(
          envioPeloSaida({
            tomar: async () => envios.connect(),
            devolver: (l, erro) => (l as pg.PoolClient).release(erro instanceof Error ? erro : undefined),
            meta: async () => new ClienteDaGraph({ token: "ensaio", base }),
            destinatario: async (): Promise<Destinatario> => ({ bsuid: "AO.ENSAIOENSAIOENSAIO0246", telefone: null }),
          }),
          { aoTratar: (d) => desfechos.push(d), lerArte: arteDoSto(sto) },
        );
        return await trabalho(efeito, sto);
      } finally {
        await fechar();
      }
    }

    async function guardarArte(sto: StorageProvider, tenant: string): Promise<string> {
      const chave = novaChave({ tenantId: tenant }, "arte");
      await sto.put({ tenantId: tenant }, chave, JPEG, {
        contentType: "image/jpeg",
        classe: "arte",
        retainUntil: new Date(Date.now() + 86_400_000),
      });
      return chave;
    }

    it("aprovação → pré-visualização com imagem: 1 carregamento, a imagem e o texto, e a reentrega 3× continua a dar 1", async () => {
      const c = await conversaNova("resposta-imagem");
      await comAGraphAEscuta(async (efeito, sto) => {
        const arte = await guardarArte(sto, c.tenant);
        const reply = await turnoComImagem(c, "wamid.img:0", arte);
        const [envelope] = await envelopes(c.tenant);
        assert.equal(envelope!.payload["reply_id"], reply);
        assert.equal(JSON.stringify(envelope!.payload).includes(arte), false, "a chave da arte nao vai no evento");
        const antes = { envios: graph.envios, carregamentos: graph.carregamentos };
        const correr = () => processar({ bd: consumo, consumer: CONSUMIDOR_DO_OUTBOUND, envelope: envelope!, exigeOrdem: false, tentativa: 1 }, efeito);
        assert.equal((await correr()).desfecho, "aplicado");
        for (let i = 0; i < 3; i += 1) assert.equal((await correr()).desfecho, "duplicado");
        assert.equal(graph.carregamentos - antes.carregamentos, 1, "um carregamento na Meta");
        assert.equal(graph.envios - antes.envios, 2, "a imagem e o texto, uma vez cada");
        assert.deepEqual(await enviadas(c.tenant), ["wamid.img:0", "wamid.img:0:imagem"]);
        assert.equal(await entregue(reply!), true);
        // O JPEG chegou à Meta tal e qual (sem o recodificar: o KAM-122 já o deu sem EXIF).
        const carregado = graph.registo.filter((r) => r.pedido.caminho.endsWith("/media")).at(-1)!;
        const id = (carregado.resposta.corpo as { id: string }).id;
        assert.ok(Buffer.from(graph.midia(id)!.bytes).includes(Buffer.from(JPEG)));
        // E a imagem foi pelo `id`, antes do texto.
        const mensagens = graph.registo.filter((r) => r.pedido.caminho.endsWith("/messages")).slice(-2);
        assert.deepEqual(mensagens[0]!.pedido.corpo?.["image"], { id });
        assert.equal(mensagens[1]!.pedido.corpo?.["type"], "text");
      });
    });

    it("uma chave de outro tenant na linha: a base recusa-a, e nada chega à Meta", async () => {
      const a = await conversaNova("resposta-imagem-a");
      const b = await conversaNova("resposta-imagem-b");
      await comAGraphAEscuta(async (_efeito, sto) => {
        const deB = await guardarArte(sto, b.tenant);
        const antes = { envios: graph.envios, carregamentos: graph.carregamentos };
        await assert.rejects(turnoComImagem(a, "wamid.alheia:0", deB), (erro: { code?: string }) => erro.code === "23514");
        assert.deepEqual(await envelopes(a.tenant), []);
        assert.equal(graph.carregamentos - antes.carregamentos, 0);
        assert.equal(graph.envios - antes.envios, 0);
      });
    });

    it("fora da janela do dono: 0 carregamentos e 0 envios, e a resposta não se marca", async () => {
      const c = await conversaNova("resposta-imagem-janela");
      // Os dois tempos andam juntos (`conversations_janela_ck`): a janela abriu há 25 h e fechou há 1 h.
      await admin.query(
        "UPDATE platform.conversations SET last_inbound_at = now() - interval '25 hours', " +
          "window_expires_at = now() - interval '1 hour' WHERE id = $1",
        [c.conversa],
      );
      await comAGraphAEscuta(async (efeito, sto) => {
        const arte = await guardarArte(sto, c.tenant);
        const reply = await turnoComImagem(c, "wamid.fora:0", arte);
        const [envelope] = await envelopes(c.tenant);
        const antes = { envios: graph.envios, carregamentos: graph.carregamentos };
        await processar({ bd: consumo, consumer: CONSUMIDOR_DO_OUTBOUND, envelope: envelope!, exigeOrdem: false, tentativa: 1 }, efeito);
        assert.equal(graph.carregamentos - antes.carregamentos, 0);
        assert.equal(graph.envios - antes.envios, 0);
        assert.equal(await entregue(reply!), false);
      });
    });
  });
});
