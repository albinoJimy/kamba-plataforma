/**
 * Trust & Safety em produção contra um PostgreSQL real (KAM-200).
 *
 * **O que só aqui se prova:**
 *
 * 1. **O consumidor**, com o `consumir` do KAM-006 como `kamba_app` e o
 *    `efeitoDeTrust`: uma encomenda criada pelo próprio dono dá **um**
 *    `auto_compra` e o `aviso` automático, e a reentrega é duplicada — a marca de
 *    consumo e os sinais confirmam juntos. Um evento de outro tenant não lhe
 *    toca.
 * 2. **A escada humana pela porta do KAM-092** (critérios 8 e 9): o processo de
 *    lote montado (`montarProcesso`), com o T&S ligado à fila, suspende um
 *    tenant pela `transition_tenant` — linha no `tenant_state_log` com o revisor
 *    e um `tenant.suspended` no *outbox* —, e o recurso provido devolve-o a
 *    `ativo` com um `tenant.reactivated`.
 * 3. **As varreduras** (critérios 2 e 5): uma volta do `CicloDoTrust` deixa uma
 *    linha `batch.run` por varredura no `audit_log`, e uma mudança de NIF depois
 *    da activação (o *trigger* da `0067`) abre **um** caso `trust` — no tenant
 *    dele e em mais nenhum —, que a volta seguinte não repete.
 *
 * O que **não** se mede aqui: a forma das instruções e as recusas antes da base
 * (`../tests/trust.producao.test.ts`, *gate* 4); os *triggers* pelos dois
 * escritores e a limitação do catálogo (`db/tests/test_trust_schema.py`).
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { BASE_DESCARTAVEL, activarTenant, criarTenant, ligar } from "./apoio.ts";
import { consumir, type Envelope } from "../src/eventos/index.ts";
import type { ConjuntoSql, Revisor } from "../src/revisao/index.ts";
import { MetricasDoTrust, efeitoDeTrust } from "../src/trust/index.ts";
import { efeitosDoLote, montarProcesso } from "../../../services/onboarding-web/src/lote/processo.ts";

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
    application_name: `kamba-trust-teste:${papel}`,
    max: 6,
  });
}

let admin: pg.Client;
let lote: pg.Pool;
let app: pg.Pool;

const semRegisto = { warn: () => {}, info: () => {}, error: () => {} };

function revisor(): Revisor {
  return { id: randomUUID(), papeis: ["ts_revisor"], mfa: true, nifHmac: null, telefoneHmac: null } as Revisor;
}

/** Um tenant `ativo` com um dono (o `owner_contact_id`). */
async function tenantActivo(rotulo: string): Promise<{ tenant: string; dono: string }> {
  const tenant = await criarTenant(admin, rotulo);
  const dono = (
    await admin.query<{ contact_id: string }>(
      "INSERT INTO platform.contacts (tenant_id) VALUES ($1) RETURNING contact_id::text AS contact_id",
      [tenant],
    )
  ).rows[0]!.contact_id;
  await admin.query("UPDATE platform.tenants SET owner_contact_id = $2 WHERE id = $1", [tenant, dono]);
  await activarTenant(admin, tenant);
  return { tenant, dono };
}

function envelope(tenant: string, tipo: string, agregado: { tipo: string; id: string }, payload: Record<string, unknown>): Envelope {
  const agora = new Date().toISOString();
  return {
    id: randomUUID(),
    tipo,
    versao: 2,
    tenant_id: tenant,
    ocorrido_em: agora,
    registado_em: agora,
    produtor: "ensaio",
    agregado: { ...agregado, seq: 1 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "nenhuma" as Envelope["classe_pii"],
    finalidades: ["transacao"],
    payload,
  };
}

async function contar(sql: string, valores: readonly unknown[]): Promise<number> {
  return Number((await admin.query<{ n: string }>(sql, [...valores])).rows[0]!.n);
}

before(async () => {
  admin = await ligar("admin");
  lote = conjunto("batch");
  app = conjunto("app");
});

after(async () => {
  await Promise.allSettled([lote?.end(), app?.end()]);
  await admin?.end();
});

describe("Trust & Safety em produção contra a base", () => {
  it("o consumidor como kamba_app: a encomenda do próprio dono dá um auto_compra e o aviso, e a reentrega é duplicada", async () => {
    const { tenant, dono } = await tenantActivo("consumo");
    const outro = await tenantActivo("consumo-outro");
    const pedido = (
      await admin.query<{ id: string }>(
        "INSERT INTO platform.orders_mirror (tenant_id, contact_id, intent_key, total_minor, lines_snapshot) " +
          "VALUES ($1, $2, $3, 5000, '[]'::jsonb) RETURNING id::text AS id",
        [tenant, dono, `ik-${randomUUID().slice(0, 16)}`],
      )
    ).rows[0]!.id;
    const metricas = new MetricasDoTrust();
    const efeito = efeitoDeTrust({ contadores: metricas });
    const evento = envelope(tenant, "order.created", { tipo: "order", id: pedido }, { order_id: pedido });
    const ligacao = await app.connect();
    try {
      const opcoes = { bd: ligacao, consumer: "trust", envelope: evento, exigeOrdem: true };
      assert.equal((await consumir(opcoes, efeito)).desfecho, "aplicado");
      assert.equal((await consumir(opcoes, efeito)).desfecho, "duplicado");
    } finally {
      ligacao.release();
    }
    assert.equal(
      await contar("SELECT count(*) AS n FROM platform.ts_signal WHERE tenant_id = $1 AND tipo = 'auto_compra' AND ref_evento = $2", [tenant, pedido]),
      1,
    );
    assert.equal(
      await contar("SELECT count(*) AS n FROM platform.ts_sanction WHERE tenant_id = $1 AND passo = 'aviso' AND origem = 'automatica'", [tenant]),
      1,
      "o peso da auto-compra (35) passa o limiar do aviso (30)",
    );
    assert.equal(await contar("SELECT count(*) AS n FROM platform.ts_signal WHERE tenant_id = $1", [outro.tenant]), 0);
    assert.match(metricas.exposicao(), /^ts_sinais_total\{tipo="auto_compra"\} 1$/m);
    assert.equal(
      await contar("SELECT count(*) AS n FROM platform.events_consumed WHERE consumer = 'trust' AND event_id = $1", [evento.id]),
      1,
      "a marca que o KAM-096 le para a independencia",
    );
  });

  it("a escada humana suspende pela porta, com registo e evento, e o recurso provido reactiva", async () => {
    const { tenant } = await tenantActivo("escada");
    const p = montarProcesso({
      lote: lote as unknown as ConjuntoSql,
      app: app as unknown as ConjuntoSql,
      efeitos: efeitosDoLote(lote as unknown as ConjuntoSql, { carenciaMs: 0 }),
      log: semRegisto,
    });
    const proposta = await p.trust.proporSancao({
      tenantId: tenant,
      passo: "suspensao",
      motivoInterno: "queixas recorrentes e nao entregas",
      sinais: [],
      justificacaoDoSalto: "ensaio: salto directo para suspensao",
      chave: `ensaio.${randomUUID().slice(0, 8)}`,
    });
    assert.ok(proposta.estado !== "nao_elegivel");
    const caso = proposta.caso.id;
    // O aviso ao dono não tem via neste processo: a decisão aplica a sanção e a
    // transição, e sobe como efeito por aplicar.
    await assert.rejects(p.servico.decidir(revisor(), caso, "rejeitar", { regra: "TS-1" }), (e: unknown) => e instanceof Error && e.name === "EfeitoPorAplicarError");
    const estado = async () => (await admin.query<{ estado: string }>("SELECT estado FROM platform.tenants WHERE id = $1", [tenant])).rows[0]!.estado;
    assert.equal(await estado(), "suspenso");
    const registo = await admin.query("SELECT de, para, motivo FROM platform.tenant_state_log WHERE tenant_id = $1 ORDER BY em", [tenant]);
    assert.deepEqual(registo.rows, [{ de: "ativo", para: "suspenso", motivo: "decisao_ts" }]);
    const eventos = async () =>
      (
        await admin.query<{ tipo: string; motivo: string | null }>(
          "SELECT tipo, envelope -> 'payload' ->> 'motivo' AS motivo FROM platform.events_outbox " +
            "WHERE tenant_id = $1 AND tipo LIKE 'tenant.%' ORDER BY criado_at, tipo",
          [tenant],
        )
      ).rows;
    assert.deepEqual(await eventos(), [{ tipo: "tenant.suspended", motivo: "decisao_ts" }]);

    // O recurso do dono é o recurso do próprio caso, decidido por outro revisor.
    assert.equal((await p.trust.restricoes(tenant)).passo, "suspensao");
    const [sancao] = (
      await admin.query<{ id: string }>(
        "SELECT id::text AS id FROM platform.ts_sanction WHERE tenant_id = $1 AND passo = 'suspensao' AND recurso_de IS NULL",
        [tenant],
      )
    ).rows;
    assert.ok(sancao !== undefined, "a sanção humana não ficou gravada");
    await p.trust.pedirRecurso(tenant, sancao.id);
    await assert.rejects(p.servico.decidirRecurso(revisor(), caso, "aprovar", { regra: "TS-1" }), (e: unknown) => e instanceof Error && e.name === "EfeitoPorAplicarError");
    assert.equal(await estado(), "ativo");
    assert.deepEqual(await eventos(), [
      { tipo: "tenant.suspended", motivo: "decisao_ts" },
      { tipo: "tenant.reactivated", motivo: null },
    ]);
  });

  it("uma volta das varreduras deixa uma linha batch.run por varredura, e a mudança de NIF abre um caso, uma vez, no tenant dela", async () => {
    const mudou = await tenantActivo("conta");
    const quieto = await tenantActivo("conta-quieto");
    await admin.query("UPDATE platform.tenants SET nif = $2 WHERE id = $1", [mudou.tenant, `999${randomUUID().replace(/-/g, "").slice(0, 7)}`]);
    const p = montarProcesso({
      lote: lote as unknown as ConjuntoSql,
      app: app as unknown as ConjuntoSql,
      efeitos: efeitosDoLote(lote as unknown as ConjuntoSql, { carenciaMs: 0 }),
      log: semRegisto,
    });
    const antes = await contar("SELECT count(*) AS n FROM platform.audit_log WHERE action = 'batch.run' AND entity = 'ts_varredura'", []);
    const r = await p.cicloDoTrust.correr();
    assert.deepEqual(r.falhas, []);
    // Cinco desde o KAM-208: a purga do pseudónimo sem tenant (`pseudonimos`)
    // corre sempre; a comparação (`compradores_do_dono`) só com o interruptor
    // ligado, que aqui não está.
    assert.equal(
      await contar("SELECT count(*) AS n FROM platform.audit_log WHERE action = 'batch.run' AND entity = 'ts_varredura'", []),
      antes + 5,
    );
    const casos = (t: string) =>
      contar("SELECT count(*) AS n FROM platform.review_case WHERE tenant_id = $1 AND tipo = 'trust' AND motivo_codigo LIKE 'sancao_suspensao:conta.%'", [t]);
    assert.equal(await casos(mudou.tenant), 1);
    assert.equal(await casos(quieto.tenant), 0);
    await p.cicloDoTrust.correr();
    assert.equal(await casos(mudou.tenant), 1, "a volta seguinte não repete o caso");
    assert.match(p.metricasDoTrust.exposicao(), /varredura="mudancas_de_conta",desfecho="concluida"\} 2$/m);
  });
});
