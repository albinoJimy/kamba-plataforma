/**
 * O recálculo da confiança gradual a correr, contra um PostgreSQL real (KAM-203).
 *
 * **O que só aqui se prova**, pelos Testes Requeridos do bloco:
 *
 * 1. **O processo sobe e desce.** A volta diária do processo de lote, montado
 *    pelo `services/onboarding-web/src/lote/processo.ts` com o `kamba_batch` e o
 *    `kamba_app` verdadeiros, dá o nível 0 a um tenant com K1, sobe-o com cinco
 *    pedidos elegíveis de cinco compradores, e a varredura das descidas desce-o
 *    com uma disputa aceite. Reexecutar a volta não escreve outra linha
 *    `trust.tecto` — e cada volta deixa a sua `batch.run`.
 * 2. **A sanção chega à base sem esperar pelo dia seguinte.** Quatro queixas
 *    pela escada automática de T&S dão a `limitacao`, e a varredura das descidas
 *    — que corre a cada volta do processo — desce o tenant com o motivo
 *    `sancao`.
 * 3. **A aprovação deixa o tenant no nível 0.** O `k1_ok` aprova pela porta
 *    (`platform.advance_case`, que emite o `tenant.approved`) e o recálculo corre
 *    a seguir, como `kamba_batch`.
 * 4. **O `order.delivered` repetido** recalcula duas vezes e escreve uma.
 * 5. **Isolamento**: o recálculo de A nunca escreve o nível de B — nem o faz
 *    nascer, nem o desce.
 *
 * As encomendas semeiam-se **pelo caminho legítimo** (CAS e registo, numa
 * transacção que confirma, com o recibo de consumo do `order.paid` pelo
 * consumidor `trust`): é esse recibo que dá a independência, e o *trigger*
 * diferido da `0030` recusava o atalho. O relógio do processo da subida está
 * vinte dias à frente, para que a janela anti-fraude (14 dias) tenha fechado
 * sobre pedidos entregues agora.
 *
 * Nada aqui é um dado real: os NIF e telefones são *bytes* aleatórios, e nenhum
 * valor em claro entra em coluna nenhuma.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { BASE_DESCARTAVEL, aceitarVigentes, activarTenant, criarTenant, ligar } from "./apoio.ts";
import type { ConjuntoSql } from "../src/revisao/index.ts";
import {
  depoisDoTrust,
  efeitosDoLote,
  montarProcesso,
} from "../../../services/onboarding-web/src/lote/processo.ts";

const DIA = 86_400_000;

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
    application_name: `kamba-confianca-teste:${papel}`,
    max: 6,
  });
}

let admin: pg.Client;
let lote: pg.Pool;
let app: pg.Pool;

const semRegisto = { warn: () => {}, info: () => {}, error: () => {} };

function processo(o: { readonly diasAFrente?: number } = {}) {
  const dias = o.diasAFrente ?? 0;
  return montarProcesso({
    lote: lote as unknown as ConjuntoSql,
    app: app as unknown as ConjuntoSql,
    efeitos: efeitosDoLote(lote as unknown as ConjuntoSql, { carenciaMs: 0 }),
    log: semRegisto,
    ...(dias === 0 ? {} : { relogio: () => new Date(Date.now() + dias * DIA) }),
  });
}

/** Um caso de onboarding do tenant, como administrador, na fase dada. */
async function caso(tenant: string, fase: string): Promise<string> {
  const id = randomUUID();
  await admin.query(
    `INSERT INTO platform.onboarding_case
       (id, tenant_id, fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac, ip_prefix_hash)
     VALUES ($1, $2, $3, 'convite', 'Loja de ensaio', 'alimentar', $4, $5, $4, $6, $7)`,
    [id, tenant, fase, randomBytes(40), randomBytes(32), randomBytes(32), randomBytes(32)],
  );
  return id;
}

async function k1(onb: string, tenant: string): Promise<void> {
  await admin.query(
    `INSERT INTO platform.kyc_check (onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, resultado, versao_regras)
     VALUES ($1, $2, 'bi', $3, $4, 'k1_ok', '1.0.0')`,
    [onb, tenant, `t/${tenant}/kyc_documento/2026/11/${randomUUID()}`, randomBytes(32)],
  );
}

/** Um tenant `ativo`, com caso `activo` e o K1 completo. */
async function tenantComK1(rotulo: string): Promise<string> {
  const tenant = await criarTenant(admin, `confianca-${rotulo}`);
  await activarTenant(admin, tenant);
  await k1(await caso(tenant, "activo"), tenant);
  return tenant;
}

async function contacto(tenant: string): Promise<string> {
  return (
    await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id::text AS contact_id",
      [tenant],
    )
  ).rows[0]!.contact_id;
}

/** O `order.paid` no arquivo e consumido pelo `trust`: a marca da independência, e o evento da `paga`. */
async function paidConsumidoPeloTrust(tenant: string, pedido: string): Promise<string> {
  const evento = randomUUID();
  await admin.query(
    `INSERT INTO platform.events_log (event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, agregado_seq,
       ocorrido_em, registado_em, classe_pii, envelope)
     VALUES ($1, 'order.paid', 1, $2, 'order', $3, 1, now(), now(), 'P0', '{}')`,
    [evento, tenant, pedido],
  );
  await admin.query(
    `INSERT INTO platform.events_consumed (consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq)
     VALUES ('trust', $1, $2, 'order', $3, 1)`,
    [evento, tenant, pedido],
  );
  return evento;
}

/** Uma transição pelo caminho do módulo: CAS e registo, numa transacção que confirma. */
async function transitar(
  tenant: string,
  pedido: string,
  de: string,
  para: string,
  versao: number,
  causa: string,
  eventoId: string | null = null,
): Promise<number> {
  await admin.query("BEGIN");
  try {
    const r = await admin.query<{ version: number }>(
      `UPDATE platform.orders_mirror
          SET estado = $1, version = version + 1, atualizado_at = now(),
              paga_at = CASE WHEN $1 = 'paga' THEN now() ELSE paga_at END,
              paga_via = CASE WHEN $1 = 'paga' THEN 'provider_autenticado' ELSE paga_via END,
              entregue_at = CASE WHEN $1 = 'entregue' THEN now() ELSE entregue_at END,
              entrega_confirmada_por = CASE WHEN $1 = 'entregue' THEN 'cliente' ELSE entrega_confirmada_por END,
              expira_at = COALESCE(expira_at, now() + interval '48 hours')
        WHERE tenant_id = $2 AND id = $3 AND version = $4 AND estado = $5
       RETURNING version`,
      [para, tenant, pedido, versao, de],
    );
    const nova = r.rows[0]?.version;
    if (nova === undefined) throw new Error(`a semente nao transitou ${de} -> ${para}`);
    await admin.query(
      `INSERT INTO platform.order_state_log (tenant_id, order_id, de, para, version, causa, evento_id, actor_kind, actor_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'ops-1')`,
      [tenant, pedido, de, para, nova, causa, eventoId, para === "paga" ? "sistema" : "ops"],
    );
    await admin.query("COMMIT");
    return Number(nova);
  } catch (erro) {
    await admin.query("ROLLBACK");
    throw erro;
  }
}

/** Uma encomenda de 12 000 Kz entregue com confirmação do cliente. Devolve `[id, versão]`. */
async function entregue(tenant: string, comprador: string): Promise<[string, number]> {
  const pedido = (
    await admin.query<{ id: string }>(
      "INSERT INTO platform.orders_mirror (tenant_id, contact_id, intent_key, total_minor, lines_snapshot) " +
        "VALUES ($1, $2, $3, 1200000, '[]'::jsonb) RETURNING id::text AS id",
      [tenant, comprador, `ik-${randomUUID().slice(0, 16)}`],
    )
  ).rows[0]!.id;
  let v = await transitar(tenant, pedido, "criada", "aguarda_pagamento", 1, "charge.issued");
  v = await transitar(tenant, pedido, "aguarda_pagamento", "paga", v, "payment.confirmed", await paidConsumidoPeloTrust(tenant, pedido));
  v = await transitar(tenant, pedido, "paga", "entregue", v, "levantamento");
  return [pedido, v];
}

async function nivel(tenant: string): Promise<{ nivel: number; motivo: string } | null> {
  const l = (await admin.query<{ nivel: number; motivo: string }>(
    "SELECT nivel, motivo FROM platform.trust_level WHERE tenant_id = $1",
    [tenant],
  )).rows[0];
  return l === undefined ? null : { nivel: Number(l.nivel), motivo: l.motivo };
}

async function contar(sql: string, valores: readonly unknown[] = []): Promise<number> {
  return Number((await admin.query<{ n: string }>(sql, [...valores])).rows[0]!.n);
}

const linhasDoTecto = (tenant: string) =>
  contar("SELECT count(*) AS n FROM platform.audit_log WHERE tenant_id = $1 AND action = 'trust.tecto'", [tenant]);

const corridas = (entidade: string) =>
  contar(
    "SELECT count(*) AS n FROM platform.audit_log WHERE tenant_id IS NULL AND action = 'batch.run' " +
      "AND entity = 'trust_level' AND entity_id = $1",
    [entidade],
  );

before(async () => {
  admin = await ligar("admin");
  lote = conjunto("batch");
  app = conjunto("app");
});

after(async () => {
  await Promise.allSettled([lote?.end(), app?.end()]);
  await admin?.end();
});

describe("a confiança gradual a correr contra a base", () => {
  it("a volta diária dá o nível 0, sobe com cinco pedidos elegíveis, a disputa aceite desce, e reexecutar não escreve", async () => {
    const tenant = await tenantComK1("sobe");
    const outro = await tenantComK1("outro");
    // O relógio vinte dias à frente: os pedidos entregues agora passaram a
    // janela anti-fraude de 14 dias e estão dentro da móvel de 30.
    const p = processo({ diasAFrente: 20 });
    const metricas = p.metricasDaConfianca;
    const antes = await corridas("recalculo_diario");

    await p.cicloDaConfianca.correr();
    assert.deepEqual(await nivel(tenant), { nivel: 0, motivo: "k1_completo" });
    assert.equal(await corridas("recalculo_diario"), antes + 1, "cada volta deixa uma batch.run");

    const pedidos: [string, number][] = [];
    for (let i = 0; i < 5; i++) pedidos.push(await entregue(tenant, await contacto(tenant)));
    await p.cicloDaConfianca.correr();
    assert.deepEqual(await nivel(tenant), { nivel: 1, motivo: "historico_independente" });
    assert.equal(await linhasDoTecto(tenant), 2, "o nascimento e a subida");
    assert.match(metricas.exposicao(), /^confianca_mudancas_total\{motivo="historico_independente"\} [1-9]/m);

    // Reexecutar: a corrida fica, e o nível não se reescreve.
    await p.cicloDaConfianca.correr();
    assert.equal(await linhasDoTecto(tenant), 2);
    assert.equal(await corridas("recalculo_diario"), antes + 3);

    // A disputa aceite contra o dono, pelo grafo: entregue → em_disputa → reembolso_pendente.
    const [pedido, v] = pedidos[0]!;
    const v2 = await transitar(tenant, pedido, "entregue", "em_disputa", v, "reclamacao");
    await transitar(tenant, pedido, "em_disputa", "reembolso_pendente", v2, "disputa_aceite");
    const descidas = await corridas("recalculo_descida");
    const r = await p.cicloDaConfianca.descer();
    assert.ok(r.mudaram >= 1, JSON.stringify(r));
    assert.deepEqual(await nivel(tenant), { nivel: 0, motivo: "disputa_aceite" });
    assert.equal(await linhasDoTecto(tenant), 3);
    assert.equal(await corridas("recalculo_descida"), descidas + 1, "a varredura com candidatos audita");
    // Uma descida não se reverte sem nova elegibilidade: os quatro pedidos que
    // restam são anteriores ao facto negativo.
    await p.cicloDaConfianca.correr();
    assert.deepEqual(await nivel(tenant), { nivel: 0, motivo: "disputa_aceite" });
    assert.equal(await linhasDoTecto(tenant), 3);
    // E a varredura vazia já não tem este tenant, nem audita.
    const depois = await corridas("recalculo_descida");
    await p.cicloDaConfianca.descer();
    assert.equal(await corridas("recalculo_descida"), depois);
    // O outro tenant nasceu na volta e nunca subiu.
    assert.deepEqual(await nivel(outro), { nivel: 0, motivo: "k1_completo" });
  });

  it("uma limitacao da escada automática desce o tenant na varredura seguinte, sem esperar pelo dia", async () => {
    const tenant = await tenantComK1("sancao");
    const p = processo();
    const metricas = p.metricasDaConfianca;
    // O tenant no nível 1, escrito pelo lote como o recálculo o escreve.
    await lote.query(
      `INSERT INTO platform.trust_level (tenant_id, nivel, tecto_pedido_minor, motivo, actor, versao_config)
       VALUES ($1, 1, 15000000, 'historico_independente', 'sistema:2026-11-16.1', '2026-11-16.1')`,
      [tenant],
    );
    // Quatro queixas (peso 20, severidade média): o aviso aos ~40 e a limitação
    // aos ~80. Nenhuma é um sinal alto, pelo que a descida é pela sanção.
    for (let i = 0; i < 4; i++) {
      await p.trust.sinalizar({ tenantId: tenant, tipo: "queixa_recorrente", refEvento: randomUUID(), detalhe: {}, ocorridoEm: new Date() });
    }
    assert.equal((await p.trust.restricoes(tenant)).tectoNoNivelZero, true, "a escada não chegou à limitacao");
    assert.deepEqual(await nivel(tenant), { nivel: 1, motivo: "historico_independente" }, "a sanção ainda não chegou à base");
    await p.cicloDaConfianca.descer();
    assert.deepEqual(await nivel(tenant), { nivel: 0, motivo: "sancao" });
    assert.match(metricas.exposicao(), /^confianca_recalculos_total\{origem="descida",desfecho="mudou"\} 1$/m);
    assert.match(metricas.exposicao(), /^confianca_mudancas_total\{motivo="sancao"\} 1$/m);
  });

  it("um k1_ok aprova pela porta e o tenant fica no nível 0, como kamba_batch", async () => {
    const tenant = await criarTenant(admin, "confianca-aprova");
    const onb = await caso(tenant, "kyc_pendente");
    await k1(onb, tenant);
    await admin.query(
      `INSERT INTO platform.screening_decision (tenant_id, onboarding_id, sujeito_tipo, sujeito_ref, decisao,
         regras, versao_politica, origem, conteudo_sha256)
       VALUES ($1, $2, 'categoria', 'alimentar', 'permitida', ARRAY['alimentar'], '1.0.0+ensaio', 'regra', $3)`,
      [tenant, onb, randomBytes(32)],
    );
    await aceitarVigentes(admin, tenant);
    assert.equal(await nivel(tenant), null);
    const p = processo();
    assert.equal((await p.aprovacaoDoKyc.aprovar(onb, tenant)).estado, "aprovado");
    assert.equal(
      await contar("SELECT count(*) AS n FROM platform.events_outbox WHERE tenant_id = $1 AND tipo = 'tenant.approved'", [tenant]),
      1,
    );
    assert.deepEqual(await nivel(tenant), { nivel: 0, motivo: "k1_completo" });
    const actor = (
      await admin.query<{ actor_id: string }>(
        "SELECT actor_id FROM platform.audit_log WHERE tenant_id = $1 AND action = 'trust.tecto'",
        [tenant],
      )
    ).rows.map((l) => l.actor_id);
    assert.deepEqual(actor, ["sistema:2026-11-16.1"]);
  });

  it("o order.delivered repetido recalcula duas vezes e escreve uma", async () => {
    const tenant = await tenantComK1("entrega");
    const p = processo();
    const metricas = p.metricasDaConfianca;
    const depois = depoisDoTrust(p.recalculo);
    const evento = { tipo: "order.delivered", tenant_id: tenant } as Parameters<typeof depois>[0];
    await depois(evento);
    await depois(evento);
    assert.deepEqual(await nivel(tenant), { nivel: 0, motivo: "k1_completo" });
    assert.equal(await linhasDoTecto(tenant), 1);
    assert.match(metricas.exposicao(), /^confianca_recalculos_total\{origem="entrega",desfecho="mudou"\} 1$/m);
    assert.match(metricas.exposicao(), /^confianca_recalculos_total\{origem="entrega",desfecho="sem_mudanca"\} 1$/m);
  });

  it("o recálculo de A nunca escreve o nível de B: nem o faz nascer, nem o desce", async () => {
    const a = await tenantComK1("isolamento-a");
    const b = await tenantComK1("isolamento-b");
    const p = processo();
    await lote.query(
      `INSERT INTO platform.trust_level (tenant_id, nivel, tecto_pedido_minor, motivo, actor, versao_config)
       VALUES ($1, 1, 15000000, 'historico_independente', 'sistema:2026-11-16.1', '2026-11-16.1')`,
      [b],
    );
    // Um sinal alto em B, que o desceria no seu próprio recálculo.
    await p.trust.sinalizar({ tenantId: b, tipo: "mudanca_de_conta", refEvento: randomUUID(), detalhe: {}, ocorridoEm: new Date() });
    const r = await p.recalculo.recalcular(a, "entrega");
    assert.equal(r.tenantId, a);
    assert.deepEqual(await nivel(a), { nivel: 0, motivo: "k1_completo" });
    assert.deepEqual(await nivel(b), { nivel: 1, motivo: "historico_independente" });
    assert.equal(await linhasDoTecto(b), 1, "só o nascimento de B pelo ensaio");
  });
});
