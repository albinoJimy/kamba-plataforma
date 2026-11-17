/**
 * A régua de cobrança contra um PostgreSQL real, pelo código TypeScript (KAM-058).
 *
 * **O que só aqui se prova.** O `pagamentos.regua.test.ts` mede o calendário e a
 * ordem do motor contra uma base falsa, que responde ao `transition_tenant` com
 * uma cópia das arestas — e uma cópia não prova a função. Aqui corre o
 * `correrRegua` verdadeiro, com o `kamba_batch` verdadeiro, sobre a revisão da
 * régua e a `0058`:
 *
 * 1. **O ciclo completo** D+0 → D+10 → regularização (testes requeridos), com
 *    cinco voltas por dia: três passos e só três (o `UNIQUE (billing_cycle_id,
 *    passo)` e o trinco), uma transição `ativo → suspenso` no
 *    `tenant_state_log`, **um** `tenant.suspended` no *outbox*, o CHR a ler
 *    `suspenso` e a matriz a recusar o AGR (critério 2), e o pagamento no D+11 a
 *    repor `ativo` com um `tenant.reactivated` (critério 3).
 * 2. **O pagamento no D+9** cancela o passo pendente pelo *ledger* verdadeiro (o
 *    gatilho `payment_charges_ciclo_pago` da `0055` põe o ciclo em `paga`).
 * 3. **Um tenant `restrito`** não é suspenso nem levantado (critério 7).
 * 4. **A reposição de vinte** tenants pagos cabe numa volta, e a volta dura
 *    menos do que o intervalo: é o que põe o p95 do critério 3 abaixo de 60 s.
 *
 * As sementes são as do KAM-059, pelas cadeias do `billing.ts`, como
 * administrador. O D+0 é o dia de **hoje** em Luanda e o relógio do motor é
 * injectado a partir dele: a validade de 72 h da cobrança é medida pela base em
 * tempo real, e uma data fixa no ensaio deixava de valer no dia em que passasse
 * (a lição da *fixture* do `canon_lint` que venceu a 2026-11-10).
 *
 * Nada aqui é um dado real.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { ResolvedorDeCanal } from "../src/chr/canal.ts";
import {
  MOTIVO_DA_SUSPENSAO,
  MOTIVO_NO_EVENTO,
  SQL_BILLING_ABRIR_CICLO,
  SQL_BILLING_CICLO_EMITIDO,
  SQL_BILLING_COBRANCA,
  SQL_BILLING_CONTEXTO,
  SQL_BILLING_EMITIR,
  INTERVALO_DA_REGUA_MS,
  correrRegua,
  dataEmLuanda,
  listaDeOps,
} from "../src/pagamentos/index.ts";
import { tenantGate } from "../src/ten/estados.ts";
import { activarTenant, criarCanal, criarTenant, ligar } from "./apoio.ts";

const VALOR = "1500000";
const MS_POR_DIA = 86_400_000;

let admin: pg.Client;
let lote: pg.Client;
let conta: string;
/** O dia 0 dos ciclos de ensaio: hoje, em Luanda. */
const INICIO = dataEmLuanda(new Date());
const FIM = new Date(Date.parse(`${INICIO}T00:00:00Z`) + 30 * MS_POR_DIA).toISOString().slice(0, 10);

/** 10:00 em Luanda do dia `d` do ciclo. */
function dia(d: number): Date {
  return new Date(Date.parse(`${INICIO}T09:00:00Z`) + d * MS_POR_DIA);
}

type Semente = { tenant: string; subscricao: string; ciclo: string; cobranca: string; pnid: string };

async function semear(rotulo: string, estado: "ativo" | "restrito" = "ativo"): Promise<Semente> {
  const tenant = await criarTenant(admin, rotulo);
  await activarTenant(admin, tenant);
  if (estado !== "ativo") await admin.query("UPDATE platform.tenants SET estado = $2 WHERE id = $1", [tenant, estado]);
  const { phoneNumberId } = await criarCanal(admin, tenant);
  const sub = await admin.query(
    "INSERT INTO platform.subscriptions (tenant_id, plano) VALUES ($1, 'plano_da_regua') RETURNING id::text AS id",
    [tenant],
  );
  const subscricao = String(sub.rows[0]?.id);
  const cobranca = randomUUID();
  await admin.query("BEGIN");
  try {
    await admin.query(SQL_BILLING_CONTEXTO, [tenant]);
    const c = await admin.query(SQL_BILLING_ABRIR_CICLO, [subscricao, tenant, INICIO, FIM, VALOR]);
    const ciclo = String(c.rows[0]?.id);
    const validade = new Date(Date.now() + 72 * 3_600_000).toISOString();
    const r = await admin.query(SQL_BILLING_COBRANCA, [cobranca, tenant, ciclo, conta, "manual", null, VALOR, validade]);
    assert.equal(r.rows.length, 1, "a cobranca do ciclo nao entrou");
    await admin.query(SQL_BILLING_EMITIR, [cobranca, conta, VALOR]);
    await admin.query(SQL_BILLING_CICLO_EMITIDO, [ciclo]);
    await admin.query("COMMIT");
    return { tenant, subscricao, ciclo, cobranca, pnid: phoneNumberId };
  } catch (erro) {
    await admin.query("ROLLBACK");
    throw erro;
  }
}

/** O pagamento autenticado pelo *ledger*, como o *worker* do facilitador o escreveria. */
async function pagar(s: Semente): Promise<void> {
  await admin.query("BEGIN");
  try {
    await admin.query(SQL_BILLING_CONTEXTO, [s.tenant]);
    await admin.query(
      "SELECT * FROM platform.append_payment_event(p_charge_id => $1, " +
        "p_tipo_evento => 'pagamento_confirmado', p_account_id => $2, p_valor_minor => $3, " +
        "p_authn_method => 'hmac', p_authn_ok => true, p_decisao => 'aceite', " +
        "p_actor_kind => 'provider', p_provider_event_id => $4)",
      [s.cobranca, conta, VALOR, `evt-regua-${randomUUID()}`],
    );
    await admin.query("COMMIT");
  } catch (erro) {
    await admin.query("ROLLBACK");
    throw erro;
  }
}

async function estadoDo(tenant: string): Promise<string> {
  return String((await admin.query("SELECT estado FROM platform.tenants WHERE id = $1", [tenant])).rows[0]?.estado);
}

async function passosDo(ciclo: string): Promise<string[][]> {
  const { rows } = await admin.query(
    "SELECT passo, resultado, coalesce(canal, '-') AS canal FROM platform.billing_dunning_steps " +
      "WHERE billing_cycle_id = $1 ORDER BY executado_at",
    [ciclo],
  );
  return rows.map((r) => [String(r.passo), String(r.resultado), String(r.canal)]);
}

async function eventosDo(tenant: string): Promise<{ tipo: string; payload: Record<string, unknown> }[]> {
  const { rows } = await admin.query(
    "SELECT tipo, envelope FROM platform.events_outbox WHERE tenant_id = $1 AND tipo LIKE 'tenant.%' ORDER BY agregado_seq",
    [tenant],
  );
  return rows.map((r) => ({
    tipo: String(r.tipo),
    payload: ((typeof r.envelope === "string" ? JSON.parse(r.envelope) : r.envelope) as { payload: Record<string, unknown> })
      .payload,
  }));
}

/** Uma volta do motor; as falhas de **outros** tenants não são deste ensaio. */
async function volta(agora: Date, meus: readonly string[]) {
  const r = await correrRegua(lote, { agora });
  assert.deepEqual(
    r.falhas.filter((f) => meus.includes(f.tenantId)),
    [],
  );
  return r;
}

before(async () => {
  admin = await ligar("admin");
  lote = await ligar("batch");
  conta = randomUUID();
  await admin.query(
    "INSERT INTO platform.payment_accounts (id, beneficiary_kind, tenant_id, provider, estado, webhook_token) " +
      "VALUES ($1, 'plataforma_receita_propria', NULL, 'manual', 'ativo', $2)",
    [conta, randomUUID().replace(/-/g, "")],
  );
});

after(async () => {
  await lote?.end();
  await admin?.end();
});

describe("a régua de cobrança contra a base", () => {
  it("onze dias pelo motor verdadeiro: três passos, uma suspensão com registo e evento, o CHR recusa, e o pagamento repõe", async (t) => {
    const s = await semear("regua-ciclo");
    const t0 = performance.now();
    for (let d = 0; d <= 10; d += 1) {
      for (let i = 0; i < 5; i += 1) await volta(dia(d), [s.tenant]);
    }
    const ms = performance.now() - t0;
    t.diagnostic(`[KAM-058] onze dias, cinco voltas por dia, contra a base: ${Math.round(ms)} ms`);

    assert.deepEqual(await passosDo(s.ciclo), [
      ["lembrete", "notificado", "ops"],
      ["aviso", "notificado", "ops"],
      ["suspensao", "suspenso", "ops"],
    ]);
    assert.equal(await estadoDo(s.tenant), "suspenso");
    const registo = await admin.query(
      "SELECT de, para, motivo FROM platform.tenant_state_log WHERE tenant_id = $1 ORDER BY em",
      [s.tenant],
    );
    assert.deepEqual(
      registo.rows.filter((r) => r.motivo === MOTIVO_DA_SUSPENSAO).map((r) => [r.de, r.para]),
      [["ativo", "suspenso"]],
    );
    assert.deepEqual(await eventosDo(s.tenant), [{ tipo: "tenant.suspended", payload: { motivo: MOTIVO_NO_EVENTO } }]);
    // Critério 2: a transição no `audit_log`, pela porta da `0006`, na cadeia do tenant.
    const auditoria = await admin.query(
      "SELECT actor_type, actor_id, action, entity, entity_id FROM platform.audit_log " +
        "WHERE tenant_id = $1 AND action = 'batch.run' ORDER BY criado_at",
      [s.tenant],
    );
    assert.deepEqual(
      auditoria.rows.map((r) => [r.actor_type, r.actor_id, r.action, r.entity, r.entity_id]),
      [["system", "kamba_batch:regua_de_cobranca", "batch.run", "tenant", s.tenant]],
    );
    const sub = await admin.query("SELECT estado FROM platform.subscriptions WHERE id = $1", [s.subscricao]);
    assert.equal(sub.rows[0]?.estado, "suspensa");

    // Critério 2: o CHR lê `suspenso` da base e a matriz não deixa chegar ao AGR.
    const lido = await new ResolvedorDeCanal(admin).resolver(s.pnid);
    assert.equal(lido.resolvido?.contexto.estado_tenant, "suspenso");
    const gate = tenantGate(lido.resolvido?.contexto.estado_tenant, lido.resolvido?.contexto.estado_canal, "processar_entrada");
    assert.equal(gate.permitido, false);

    // A lista diária de ops do D+10 tem a tarefa da suspensão.
    const tarefas = (await listaDeOps(lote, dia(10))).filter((t) => t.tenantId === s.tenant);
    assert.deepEqual(tarefas.map((t) => t.passo), ["suspensao"]);

    // Critério 3: o pagamento no D+11 repõe na volta seguinte.
    await pagar(s);
    const r = await volta(dia(11), [s.tenant]);
    assert.ok(r.repostos.includes(s.tenant));
    assert.equal(await estadoDo(s.tenant), "ativo");
    assert.deepEqual(
      (await eventosDo(s.tenant)).map((e) => e.tipo),
      ["tenant.suspended", "tenant.reactivated"],
    );
    const depois = await admin.query("SELECT estado FROM platform.subscriptions WHERE id = $1", [s.subscricao]);
    assert.equal(depois.rows[0]?.estado, "ativa");
    for (let i = 0; i < 4; i += 1) await volta(dia(11), [s.tenant]);
    assert.equal((await eventosDo(s.tenant)).length, 2, "repetir a volta nao emite outra vez");
  });

  it("o UNIQUE (billing_cycle_id, passo) recusa um passo repetido escrito à mão pelo lote", async () => {
    const s = await semear("regua-unico");
    await volta(dia(3), [s.tenant]);
    await assert.rejects(
      () =>
        lote.query(
          "INSERT INTO platform.billing_dunning_steps (tenant_id, billing_cycle_id, passo, executado_at, resultado, canal, config_versao) " +
            "VALUES ($1, $2, 'lembrete', now(), 'notificado', 'ops', 'x')",
          [s.tenant, s.ciclo],
        ),
      /billing_dunning_steps_passo_uq/,
    );
    await assert.rejects(
      () => lote.query("UPDATE platform.billing_dunning_steps SET resultado = 'cancelado' WHERE billing_cycle_id = $1", [s.ciclo]),
      /permission denied/,
    );
  });

  it("o pagamento no D+9 cancela o passo pendente e o tenant não é suspenso", async () => {
    const s = await semear("regua-d9");
    for (let d = 0; d <= 8; d += 1) await volta(dia(d), [s.tenant]);
    await pagar(s);
    for (let d = 9; d <= 11; d += 1) await volta(dia(d), [s.tenant]);
    assert.deepEqual(await passosDo(s.ciclo), [
      ["lembrete", "notificado", "ops"],
      ["aviso", "notificado", "ops"],
      ["suspensao", "cancelado", "-"],
    ]);
    assert.equal(await estadoDo(s.tenant), "ativo");
    assert.deepEqual(await eventosDo(s.tenant), []);
    const sub = await admin.query("SELECT estado FROM platform.subscriptions WHERE id = $1", [s.subscricao]);
    assert.equal(sub.rows[0]?.estado, "ativa");
  });

  it("um tenant restrito não é suspenso nem sai do restrito", async () => {
    const s = await semear("regua-restrito", "restrito");
    for (let d = 0; d <= 11; d += 1) await volta(dia(d), [s.tenant]);
    assert.equal(await estadoDo(s.tenant), "restrito");
    assert.deepEqual(
      (await passosDo(s.ciclo)).map((p) => p[0]),
      ["lembrete", "aviso"],
      "a suspensao adia: nada se grava enquanto o tenant estiver restrito",
    );
    assert.deepEqual(await eventosDo(s.tenant), []);
  });

  it("vinte tenants pagos repõem-se numa volta, e a volta dura menos do que o intervalo", async (t) => {
    const sementes: Semente[] = [];
    for (let i = 0; i < 20; i += 1) sementes.push(await semear(`regua-p95-${i}`));
    const meus = sementes.map((s) => s.tenant);
    await volta(dia(7), meus);
    await volta(dia(10), meus);
    for (const s of sementes) assert.equal(await estadoDo(s.tenant), "suspenso");
    for (const s of sementes) await pagar(s);
    const t0 = performance.now();
    const r = await volta(dia(11), meus);
    const ms = performance.now() - t0;
    t.diagnostic(`[KAM-058] reposicao: vinte tenants numa volta de ${Math.round(ms)} ms (intervalo ${INTERVALO_DA_REGUA_MS} ms)`);
    for (const s of sementes) assert.ok(r.repostos.includes(s.tenant), s.tenant);
    assert.ok(ms + INTERVALO_DA_REGUA_MS <= 60_000, `volta de ${ms} ms`);
  });
});
