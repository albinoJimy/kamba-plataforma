/**
 * A activação no processo de lote contra a base (KAM-202, critérios 1 e 2).
 *
 * Corre a montagem **real** do lote (`montarProcesso` do
 * `services/onboarding-web/src/lote/processo.ts`, com os dois conjuntos) e o
 * adaptador real da página do dono (`testeDaActivacao`, sobre o `kamba_app`):
 *
 * ```text
 * catalogo minimo   cinco publicados e permitidos: o lote grava o gate e o caso
 *                   sai de aguarda_catalogo
 * a pagina          abre a tentativa pela ligacao da aplicacao
 * o teste           o «teste» de um corpo de webhook da o sinal (explosao), o CHR
 *                   grava-o com as instrucoes dele, e com a resposta, a entrega e
 *                   o consentimento o lote fecha ok, marca o e2e e o is_test, e o
 *                   activar e chamado — e recusa, porque os outros quatro gates
 *                   sao de outros tickets
 * sem entrega       depois da janela, o lote fecha `falhou` com `sem_entrega`
 * ```
 *
 * **O que não se mede aqui, e onde se mede.** Chegar a `activo` pede a sequência
 * inteira do KAM-092 (KYC, aprovação, saga, ES), e mede-se em
 * `db/tests/test_eventos_do_tenant.py`; o `activar` com os seis gates sobre os
 * duplos em `tests/activacao.test.ts`. O `delivered_at` e o `consent_event` são
 * semeados pelo administrador: em produção, hoje, ninguém os escreve (credor no
 * bloco do KAM-202), e é por isso que o observador falha fechado.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { readFileSync } from "node:fs";

import { Gerador, estado as estadoDoSimulador, interlocutorDe } from "@kamba/meta-sim";

import { BASE_DESCARTAVEL, criarCanal, ligar } from "./apoio.ts";
import { ObservadorSql } from "../src/activacao/index.ts";
import { ResolvedorDeCanal, SQL_ABRIR_CONVERSA, SQL_MARCAR_TESTE_RECEBIDO } from "../src/chr/index.ts";
import { ConsentGate, resumoDoTexto } from "../src/consentimento/index.ts";
import { sha256Hex, tratarCorpo, type Encaminhador } from "../src/entrada/index.ts";
import { explodir } from "../src/entrada/explosao.ts";
import { estagioDosStatuses } from "../src/outbound/index.ts";
import { conteudoSha256, politicaCorrente } from "../src/screening/index.ts";
import type { ConjuntoSql } from "../src/revisao/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { efeitosDoLote, montarProcesso } from "../../../services/onboarding-web/src/lote/processo.ts";
import { testeDaActivacao } from "../../../services/onboarding-web/src/painel/teste.ts";

const T = new Date("2026-11-20T10:00:00.000Z");
const LOJA = "Loja Kamba de Ensaio";
const CATEGORIA = "moda";
const NOMES = ["Camisola azul", "Saia de linho", "Vestido curto", "Casaco longo", "Blusa branca"];

function exigir(nome: string): string {
  const valor = process.env[nome] ?? "";
  if (valor === "") throw new Error(`a variável de ambiente ${nome} não está definida`);
  return valor;
}

function conjunto(papel: "batch" | "app"): pg.Pool {
  const base = exigir("KAMBA_DB_NAME");
  if (base !== BASE_DESCARTAVEL) throw new Error(`KAMBA_DB_NAME não é ${BASE_DESCARTAVEL}`);
  return new pg.Pool({
    host: process.env.KAMBA_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.KAMBA_DB_PORT ?? "5432"),
    database: base,
    user: papel === "batch" ? "kamba_batch" : "kamba_app",
    password: exigir(papel === "batch" ? "KAMBA_SECRET_DB_BATCH_PASSWORD" : "KAMBA_SECRET_DB_APP_PASSWORD"),
    application_name: `kamba-activacao-teste:${papel}`,
    max: 6,
  });
}

let admin: pg.Client;
let lote: pg.Pool;
let app: pg.Pool;
let agora = T;
const relogio = (): Date => agora;
const tenants: string[] = [];

function processo() {
  return montarProcesso({
    lote: lote as unknown as ConjuntoSql,
    app: app as unknown as ConjuntoSql,
    efeitos: efeitosDoLote(lote as unknown as ConjuntoSql, { carenciaMs: 0 }),
    log: { warn: () => {} },
    relogio,
  });
}

/** Um caso na `fase`, com o tenant que o KAM-092 já teria provisionado. */
async function caso(fase: string): Promise<[string, string]> {
  const r = await admin.query<{ id: string; tenant_id: string }>(
    `INSERT INTO platform.onboarding_case
       (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac)
     VALUES ($1, 'convite', 'Loja de ensaio', $2, $3, $4, $3, $5)
     RETURNING id::text AS id, tenant_id::text AS tenant_id`,
    [fase, CATEGORIA, randomBytes(40), randomBytes(32), randomBytes(32)],
  );
  const [onb, tenant] = [r.rows[0]!.id, r.rows[0]!.tenant_id];
  await admin.query("INSERT INTO platform.tenants (id, tipo, nome) VALUES ($1, 'pme', $2)", [tenant, LOJA]);
  tenants.push(tenant);
  return [onb, tenant];
}

/** Cinco produtos publicados, confirmados pelo dono e com a decisão `permitida` do conteúdo de agora. */
async function catalogo(tenant: string): Promise<void> {
  const versao = politicaCorrente().versao;
  await admin.query(
    `INSERT INTO platform.screening_decision (tenant_id, sujeito_tipo, sujeito_ref, decisao, regras,
       versao_politica, origem, conteudo_sha256)
     VALUES ($1, 'categoria', $2, 'permitida', ARRAY[]::text[], $3, 'regra', $4)`,
    [tenant, CATEGORIA, versao, randomBytes(32)],
  );
  for (const [i, nome] of NOMES.entries()) {
    const sku = `sku-${String.fromCharCode(97 + i)}`;
    // Pelo administrador, que e o dono da tabela: as sementes ficam de fora do
    // *trigger* da publicacao segura (ver a revisao).
    await admin.query(
      `INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, estado)
       VALUES ($1, $2, $3, 'fixo', 100000, 'publicado')`,
      [tenant, sku, nome],
    );
    const ingestao = await admin.query<{ id: string }>(
      `INSERT INTO platform.catalog_ingestions (tenant_id, media_ref, estado, extraido, sku)
       VALUES ($1, $2, 'rascunho', $3, $4) RETURNING id`,
      [tenant, `t/${tenant}/catalogo/2026/11/${randomUUID()}`, JSON.stringify({ categoria: { valor: "roupa" } }), sku],
    );
    await admin.query(
      `UPDATE platform.catalog_ingestions SET estado = 'publicada', confirmado_at = now(),
         confirmado_por = 'mensagem de ensaio' WHERE id = $1`,
      [ingestao.rows[0]!.id],
    );
    await admin.query(
      `INSERT INTO platform.screening_decision (tenant_id, sujeito_tipo, sujeito_ref, decisao, regras,
         versao_politica, origem, conteudo_sha256)
       VALUES ($1, 'produto', $2, 'permitida', ARRAY[]::text[], $3, 'regra', $4)`,
      [tenant, sku, versao, Buffer.from(conteudoSha256({ categoria_declarada: CATEGORIA, textos: [nome] }))],
    );
  }
}

/** O corpo da Meta de um «teste», como o simulador o manda. */
function corpoDoTeste(phoneNumberId: string): unknown {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "999000000000021",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: "244 999 000 000", phone_number_id: phoneNumberId },
              messages: [
                { id: `wamid.HBgLOTk5.${randomUUID()}`, from: "244 999 000 777", timestamp: "1763632800", type: "text", text: { body: "Teste" } },
              ],
            },
          },
        ],
      },
    ],
  };
}

/**
 * O «teste» a entrar: a explosão dá o sinal, e o CHR abre a conversa e grava o
 * instante com as instruções dele, pela ligação da aplicação. Devolve a conversa
 * e o contacto.
 */
async function chegaOTeste(tenant: string, em: Date): Promise<{ conversa: string; contacto: string }> {
  const canal = await criarCanal(admin, tenant);
  const { eventos } = explodir(corpoDoTeste(canal.phoneNumberId), "c".repeat(64));
  assert.equal(eventos.length, 1);
  assert.equal(eventos[0]!.eTeste, true, "o corpo do teste da o sinal");
  const contacto = (
    await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id::text AS contact_id",
      [tenant],
    )
  ).rows[0]!.contact_id;
  const ligacao = await app.connect();
  try {
    const conversa = await comTenant(ligacao, tenant, async () => {
      const aberta = await ligacao.query<{ id: string }>(SQL_ABRIR_CONVERSA, [
        tenant,
        contacto,
        canal.id,
        em,
        new Date(em.getTime() + 86_400_000),
      ]);
      const id = aberta.rows[0]!.id;
      await ligacao.query(SQL_MARCAR_TESTE_RECEBIDO, [tenant, id, em]);
      return id;
    });
    return { conversa, contacto };
  } finally {
    ligacao.release();
  }
}

async function responde(tenant: string, contacto: string, conversa: string, em: Date, texto: string) {
  await admin.query(
    `INSERT INTO platform.agent_replies (tenant_id, chave, contact_id, conversation_id, canal, texto, criado_at)
     VALUES ($1, $2, $3, $4, 'whatsapp', $5, $6)`,
    [tenant, `r-${randomUUID()}`, contacto, conversa, texto, em],
  );
}

async function entregue(tenant: string, contacto: string, conversa: string, em: Date) {
  const canal = (
    await admin.query<{ channel_id: string }>("SELECT channel_id::text AS channel_id FROM platform.conversations WHERE id = $1", [conversa])
  ).rows[0]!.channel_id;
  await admin.query(
    `INSERT INTO platform.outbound_messages (tenant_id, channel_id, contact_id, conversation_id, idempotency_key,
       kind, state, wamid, delivered_at)
     VALUES ($1, $2, $3, $4, $5, 'service', 'delivered', $6, $7)`,
    [tenant, canal, contacto, conversa, `ik-${randomUUID()}`, `wamid.HBgLOTk5.saida.${randomUUID()}`, em],
  );
}

async function consentiu(tenant: string, contacto: string, em: Date) {
  await admin.query(
    `INSERT INTO platform.consent_event (tenant_id, contact_id, purpose, text_version, accepted, canal,
       evidence_hash, registado_em)
     VALUES ($1, $2, 'atendimento', 'v1', true, 'whatsapp', $3, $4)`,
    [tenant, contacto, randomBytes(32), em],
  );
}

async function linha<T>(sql: string, valores: readonly unknown[]): Promise<T | undefined> {
  return (await admin.query(sql, valores as unknown[])).rows[0] as T | undefined;
}

// ------------------------------------------------- KAM-235: os factos em produção

const SIMULADOR = new Gerador("kam-235-bd");
const CLIENTE_DO_TESTE = interlocutorDe(SIMULADOR);
const VERSAO_DO_AVISO = "kam235-v1";
let resolvedorBd: pg.Client;

/** A apresentação do vendedor do registo, com o nome da loja: o que o AGR envia (KAM-235). */
function apresentacaoDe(loja: string): string {
  const registo = readFileSync(new URL("../../../registry/vendedor.yaml", import.meta.url), "utf8");
  return /^\s*apresentacao:\s*"([^"]+)"/m.exec(registo)![1]!.replace("{loja}", loja);
}

/** Um instante de agora, ao segundo, menos `ms`: o `delivered_at` é o `now()` da base. */
function haPouco(ms: number): Date {
  return new Date(Math.floor(Date.now() / 1000) * 1000 - ms);
}

/** A resposta que saiu e espera pelos *statuses*: a linha que o `Saida.enviar` deixa em `sent`. */
async function saiu(tenant: string, contacto: string, conversa: string): Promise<string> {
  const canal = (
    await admin.query<{ channel_id: string }>("SELECT channel_id::text AS channel_id FROM platform.conversations WHERE id = $1", [conversa])
  ).rows[0]!.channel_id;
  const wamid = `wamid.HBgLOTk5.kam235.${randomUUID()}`;
  await admin.query(
    `INSERT INTO platform.outbound_messages (tenant_id, channel_id, contact_id, conversation_id, idempotency_key,
       kind, state, wamid)
     VALUES ($1, $2, $3, $4, $5, 'service', 'sent', $6)`,
    [tenant, canal, contacto, conversa, `ik-${randomUUID()}`, wamid],
  );
  return wamid;
}

/** O canal da conversa: o `id` e o `phone_number_id`. */
async function canalDa(conversa: string): Promise<{ id: string; pnid: string }> {
  return (
    await admin.query<{ id: string; pnid: string }>(
      `SELECT c.id::text AS id, c.phone_number_id AS pnid FROM platform.conversations v
         JOIN platform.tenant_channels c ON c.id = v.channel_id WHERE v.id = $1`,
      [conversa],
    )
  ).rows[0]!;
}

/** O corpo da Meta com o estado da resposta, pelo simulador do KAM-024. */
function corpoDoEstado(phoneNumberId: string, wamid: string, e: "delivered" | "read"): unknown {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "waba-kam235-ensaio",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { phone_number_id: phoneNumberId },
              statuses: [estadoDoSimulador(SIMULADOR, { wamid, estado: e, recipienteId: CLIENTE_DO_TESTE.waId! })],
            },
          },
        ],
      },
    ],
  };
}

/** Um `ClienteSql` que corre cada instrução numa transacção com o contexto do tenant. */
function comContexto(ligacao: pg.PoolClient, tenant: string) {
  return {
    query: <T,>(texto: string, valores?: readonly unknown[]) =>
      comTenant(ligacao, tenant, async () => {
        const r = await ligacao.query(texto, valores === undefined ? [] : [...valores]);
        return { rows: r.rows as readonly T[] };
      }),
  };
}

/**
 * O corpo a entrar como no processo de entrada do `worker-canal`: o
 * `tratarCorpo` pela ligação da aplicação, e o braço `outbound` no estágio dos
 * `statuses`, com o tenant pelo resolvedor de canal (`kamba_resolver`) e o
 * `Saida.ingerir` sob o contexto dele. É a montagem do `entrada.ts`.
 */
async function entraOCorpo(corpo: unknown) {
  const ligacao = await app.connect();
  try {
    const resolvedor = new ResolvedorDeCanal(resolvedorBd);
    const estagio = estagioDosStatuses({
      tenantDe: async (pnid) => (await resolvedor.resolver(pnid)).resolvido?.contexto.tenant_id ?? null,
      comTenant: (tenant, trabalho) => comTenant(ligacao, tenant, () => trabalho(ligacao)),
    });
    const desfechos: string[] = [];
    const encaminhador: Encaminhador = {
      chr: async () => assert.fail("um statuses nao vai ao CHR"),
      outbound: async (evento) => {
        desfechos.push(await estagio(evento));
      },
      ingestao: async () => {},
      gestaoDeCanal: async () => {},
    };
    const bytes = Buffer.from(JSON.stringify(corpo), "utf8");
    const r = await tratarCorpo(
      ligacao,
      { corpo: bytes.toString("base64"), recebidoEm: 0 },
      encaminhador,
      sha256Hex(new Uint8Array(bytes)),
    );
    return { ...r, desfechos };
  } finally {
    ligacao.release();
  }
}

/** O `ConsentGate` montado, sobre a ligação da aplicação: o «Continuar» do aviso. */
async function continuaNoAviso(tenant: string, contacto: string, conversa: string): Promise<boolean> {
  const ligacao = await app.connect();
  try {
    const canal = await canalDa(conversa);
    const gate = new ConsentGate({ bd: comContexto(ligacao, tenant), enviar: async () => null });
    const r = await gate.tratar({
      tenantId: tenant,
      contactId: contacto,
      conversationId: conversa,
      channelId: canal.id,
      phoneNumberId: canal.pnid,
      wamid: `wamid.HBgLOTk5.botao.${randomUUID()}`,
      hora: new Date().toISOString(),
      entrada: { tipo: "botao", id: "continuar" },
    });
    return r.registou;
  } finally {
    ligacao.release();
  }
}

describe("a activação no lote contra a base", () => {
  before(async () => {
    admin = await ligar("admin");
    resolvedorBd = await ligar("resolver");
    lote = conjunto("batch");
    app = conjunto("app");
    // KAM-235: o texto do aviso de 1.º contacto, publicado como a operação o
    // publica, para o `ConsentGate` montado ter o que mostrar.
    const aviso = "Ensaio KAM-235: aviso de primeiro contacto.";
    await admin.query(
      `INSERT INTO platform.consent_texts (version, purpose, texto, hash, vigente_desde)
       VALUES ($1, 'transacao', $2, $3, '2026-01-01T00:00:00Z') ON CONFLICT DO NOTHING`,
      [VERSAO_DO_AVISO, aviso, Buffer.from(resumoDoTexto(aviso))],
    );
  });

  after(async () => {
    // As tentativas e os gates têm FK para o caso; o resto do tenant fica (a base
    // é descartável), como nas outras suites do lote.
    for (const tenant of tenants) {
      await admin.query("DELETE FROM platform.onboarding_smoke WHERE tenant_id = $1", [tenant]);
      await admin.query("DELETE FROM platform.onboarding_gate WHERE tenant_id = $1", [tenant]);
    }
    await admin.query("DELETE FROM platform.consent_texts WHERE version = $1", [VERSAO_DO_AVISO]);
    await resolvedorBd.end();
    await admin.end();
    await lote.end();
    await app.end();
  });

  it("KAM-202: o lote conta o catalogo minimo, grava o gate e tira o caso de aguarda_catalogo", async () => {
    agora = T;
    const [onb, tenant] = await caso("aguarda_catalogo");
    await catalogo(tenant);
    const r = await processo().cicloDaActivacao.correr();
    assert.ok(r.catalogos >= 1);
    assert.deepEqual(await linha("SELECT fase FROM platform.onboarding_case WHERE id = $1", [onb]), { fase: "aguarda_teste" });
    assert.deepEqual(
      await linha("SELECT ok, evidencia_ref FROM platform.onboarding_gate WHERE onboarding_id = $1 AND gate = 'catalogo_minimo'", [onb]),
      { ok: true, evidencia_ref: "elegiveis:5/5" },
    );
  });

  it("KAM-202: com quatro elegiveis o gate fica vermelho e o caso nao avanca", async () => {
    agora = T;
    const [onb, tenant] = await caso("aguarda_catalogo");
    await catalogo(tenant);
    // Um nome mudado depois da decisão: o conteúdo de agora não tem decisão.
    await admin.query("UPDATE platform.offer_terms SET nome = 'Camisola de outra cor' WHERE tenant_id = $1 AND sku = 'sku-a'", [tenant]);
    await processo().cicloDaActivacao.correr();
    assert.deepEqual(await linha("SELECT fase FROM platform.onboarding_case WHERE id = $1", [onb]), { fase: "aguarda_catalogo" });
    assert.deepEqual(
      await linha("SELECT ok FROM platform.onboarding_gate WHERE onboarding_id = $1 AND gate = 'catalogo_minimo'", [onb]),
      { ok: false },
    );
  });

  it("KAM-202: a pagina abre a tentativa pela ligacao da aplicacao, e o lote fecha-a ok com os quatro factos", async () => {
    agora = T;
    const [onb, tenant] = await caso("aguarda_teste");
    const aberta = await testeDaActivacao(app as unknown as ConjuntoSql, relogio).iniciar(onb, tenant);
    assert.equal(aberta.expiraEm.toISOString(), new Date(T.getTime() + 60_000).toISOString());
    assert.deepEqual(await linha("SELECT resultado FROM platform.onboarding_smoke WHERE onboarding_id = $1", [onb]), {
      resultado: "pendente",
    });

    const { conversa, contacto } = await chegaOTeste(tenant, new Date(T.getTime() + 5_000));
    await consentiu(tenant, contacto, new Date(T.getTime() + 8_000));
    await responde(tenant, contacto, conversa, new Date(T.getTime() + 10_000), `Ola! Sou o assistente automatico de ${LOJA}.`);
    await entregue(tenant, contacto, conversa, new Date(T.getTime() + 12_000));

    agora = new Date(T.getTime() + 20_000);
    const r = await processo().cicloDaActivacao.correr();
    assert.ok(r.testes >= 1);
    assert.deepEqual(await linha("SELECT resultado, causa FROM platform.onboarding_smoke WHERE onboarding_id = $1", [onb]), {
      resultado: "ok",
      causa: null,
    });
    assert.deepEqual(
      await linha("SELECT ok FROM platform.onboarding_gate WHERE onboarding_id = $1 AND gate = 'e2e'", [onb]),
      { ok: true },
    );
    assert.deepEqual(await linha("SELECT is_test FROM platform.conversations WHERE id = $1", [conversa]), { is_test: true });
    // O `activar` correu e recusou: os outros quatro gates são de outros tickets.
    // A recusa não desfez o teste, e o caso continua à espera deles.
    assert.ok(r.recusadas >= 1);
    assert.deepEqual(await linha("SELECT fase FROM platform.onboarding_case WHERE id = $1", [onb]), { fase: "aguarda_teste" });
  });

  it("KAM-202: sem entrega, o lote fecha a tentativa falhada com sem_entrega depois da janela", async () => {
    agora = T;
    const [onb, tenant] = await caso("aguarda_teste");
    await testeDaActivacao(app as unknown as ConjuntoSql, relogio).iniciar(onb, tenant);
    const { conversa, contacto } = await chegaOTeste(tenant, new Date(T.getTime() + 5_000));
    await consentiu(tenant, contacto, new Date(T.getTime() + 8_000));
    await responde(tenant, contacto, conversa, new Date(T.getTime() + 10_000), `Sou o assistente automatico de ${LOJA}.`);

    // Dentro da janela, ainda não é falha.
    agora = new Date(T.getTime() + 30_000);
    await processo().cicloDaActivacao.correr();
    assert.deepEqual(await linha("SELECT resultado FROM platform.onboarding_smoke WHERE onboarding_id = $1", [onb]), {
      resultado: "pendente",
    });

    agora = new Date(T.getTime() + 61_000);
    await processo().cicloDaActivacao.correr();
    assert.deepEqual(await linha("SELECT resultado, causa FROM platform.onboarding_smoke WHERE onboarding_id = $1", [onb]), {
      resultado: "falhou",
      causa: "sem_entrega",
    });
    assert.deepEqual(
      await linha("SELECT ok FROM platform.onboarding_gate WHERE onboarding_id = $1 AND gate = 'e2e'", [onb]),
      { ok: false },
    );
  });
  it("KAM-235: o delivered do simulador escreve o delivered_at pelo estagio, uma vez, e o observador da entregue", async () => {
    const t = haPouco(5_000);
    agora = t;
    const [onb, tenant] = await caso("aguarda_teste");
    const { conversa, contacto } = await chegaOTeste(tenant, new Date(t.getTime() + 1_000));
    const wamid = await saiu(tenant, contacto, conversa);
    const { pnid } = await canalDa(conversa);
    const ate = new Date(t.getTime() + 60_000);
    const entregue = async (): Promise<boolean> => {
      const ligacao = await app.connect();
      try {
        return (await new ObservadorSql(comContexto(ligacao, tenant)).factos(onb, t, ate)).entregue;
      } finally {
        ligacao.release();
      }
    };
    assert.equal(await entregue(), false, "sem statuses, sem entrega");

    const r = await entraOCorpo(corpoDoEstado(pnid, wamid, "delivered"));
    assert.equal(r.registados, 1);
    assert.deepEqual(r.desfechos, ["avancou"]);
    const escrita = await linha<{ state: string; delivered_at: Date | null; pricing: { category?: string } | null }>(
      "SELECT state, delivered_at, pricing FROM platform.outbound_messages WHERE tenant_id = $1 AND wamid = $2",
      [tenant, wamid],
    );
    assert.equal(escrita?.state, "delivered");
    assert.ok(escrita?.delivered_at instanceof Date, "o delivered_at escreveu-se");
    assert.equal(escrita?.pricing?.category, "service");

    // A reentrega do mesmo `wamid:delivered` e duplicada, e o `read` nao muda o
    // instante da entrega: o primeiro fica.
    const outra = await entraOCorpo(corpoDoEstado(pnid, wamid, "delivered"));
    assert.equal(outra.duplicados, 1);
    assert.deepEqual(outra.desfechos, []);
    assert.deepEqual((await entraOCorpo(corpoDoEstado(pnid, wamid, "read"))).desfechos, ["avancou"]);
    const depois = await linha<{ state: string; delivered_at: Date }>(
      "SELECT state, delivered_at FROM platform.outbound_messages WHERE tenant_id = $1 AND wamid = $2",
      [tenant, wamid],
    );
    assert.equal(depois?.state, "read");
    assert.equal(depois?.delivered_at.getTime(), escrita?.delivered_at?.getTime());
    assert.equal(await entregue(), true);
  });

  it("KAM-235: ponta a ponta com o simulador, o ConsentGate montado e o lote fecha ok", async () => {
    const t = haPouco(5_000);
    agora = t;
    const [onb, tenant] = await caso("aguarda_teste");
    await testeDaActivacao(app as unknown as ConjuntoSql, relogio).iniciar(onb, tenant);
    const { conversa, contacto } = await chegaOTeste(tenant, new Date(t.getTime() + 1_000));
    assert.equal(await continuaNoAviso(tenant, contacto, conversa), true, "o gate registou o consentimento");
    await responde(tenant, contacto, conversa, new Date(t.getTime() + 2_000), `${apresentacaoDe(LOJA)}\nEm que posso ajudar?`);
    const wamid = await saiu(tenant, contacto, conversa);
    const { pnid } = await canalDa(conversa);
    assert.deepEqual((await entraOCorpo(corpoDoEstado(pnid, wamid, "delivered"))).desfechos, ["avancou"]);

    agora = new Date(t.getTime() + 50_000);
    await processo().cicloDaActivacao.correr();
    assert.deepEqual(await linha("SELECT resultado, causa FROM platform.onboarding_smoke WHERE onboarding_id = $1", [onb]), {
      resultado: "ok",
      causa: null,
    });
  });

  it("KAM-235: ponta a ponta com o simulador e sem o ConsentGate, o lote fecha falhou com sem_consentimento", async () => {
    const t = haPouco(5_000);
    agora = t;
    const [onb, tenant] = await caso("aguarda_teste");
    await testeDaActivacao(app as unknown as ConjuntoSql, relogio).iniciar(onb, tenant);
    const { conversa, contacto } = await chegaOTeste(tenant, new Date(t.getTime() + 1_000));
    await responde(tenant, contacto, conversa, new Date(t.getTime() + 2_000), `${apresentacaoDe(LOJA)}\nEm que posso ajudar?`);
    const wamid = await saiu(tenant, contacto, conversa);
    const { pnid } = await canalDa(conversa);
    assert.deepEqual((await entraOCorpo(corpoDoEstado(pnid, wamid, "delivered"))).desfechos, ["avancou"]);

    agora = new Date(t.getTime() + 61_000);
    await processo().cicloDaActivacao.correr();
    assert.deepEqual(await linha("SELECT resultado, causa FROM platform.onboarding_smoke WHERE onboarding_id = $1", [onb]), {
      resultado: "falhou",
      causa: "sem_consentimento",
    });
  });
});
