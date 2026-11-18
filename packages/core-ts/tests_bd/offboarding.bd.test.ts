/**
 * O off-boarding contra um PostgreSQL real, pelo código TypeScript (KAM-098).
 *
 * Corre na suite `tests_lote` do *gate* 8. O que só aqui se prova:
 *
 * 1. **O pedido** exige as duas confirmações do titular, e com só a sessão
 *    (adversarial a) nada se escreve; escreve as sete fases com os prazos D0–D30
 *    numa transacção, e repetir não abre outro. T&S só encerra um `suspenso` com
 *    uma sanção de encerramento do KAM-097, e toma um pedido vivo do titular.
 * 2. **O canal** cancela a subscrição de *webhooks* pelo guarda da saga, desliga
 *    o canal na base, e **nenhuma chamada** toca no WABA nem no número; o CHR lê
 *    `desligado` e a matriz não deixa chegar ao AGR (critério 3).
 * 3. **O cancelamento em D3** religa o canal ao estado de antes e nenhuma fase
 *    seguinte corre (adversarial b); depois do D7 já não se cancela.
 * 4. **A revogação** no D7, só com a exportação concluída: as três portas da
 *    saga, os entitlements a `false`, os canais `encerrado`, o tenant
 *    `encerrado` com **um** `tenant.closed`; um *crash* a meio retoma no passo
 *    seguinte e repetir não emite outro evento (critérios 5 e 9).
 *
 * **A limpeza segue a do KAM-092**: o `tenant_state_log` é *append-only* também
 * para o dono, e as linhas da transição para `encerrado` envenenavam as descidas
 * de uma suite com ensaios de `downgrade`. No `after`, como administrador,
 * desliga-se o gatilho, apagam-se só as linhas dos tenants deste ensaio e
 * volta-se a ligar.
 *
 * Nada aqui é um dado real.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import type pg from "pg";

import { ResolvedorDeCanal } from "../src/chr/canal.ts";
import {
  AVISO_DA_APP_BUSINESS,
  ConfirmacaoIncompletaError,
  EstadoDoTenantError,
  FaseForaDeOrdemError,
  PedidoError,
  abrirPedido,
  cancelarPedido,
  desligarCanal,
  revogar,
  verificarPendentes,
  type CanalDaMeta,
  type PortasDaRevogacao,
  type ProvasDoTitular,
} from "../src/offboarding/index.ts";
import { tenantGate } from "../src/ten/estados.ts";
import { activarTenant, criarCanal, criarTenant, ligar } from "./apoio.ts";

const MS_POR_DIA = 86_400_000;
const D0 = new Date(Date.now() - 10 * MS_POR_DIA);
const dia = (n: number) => new Date(D0.getTime() + n * MS_POR_DIA);

let admin: pg.Client;
let lote: pg.Client;
const meus: string[] = [];

/** As provas: o OTP «123456» e o token «tok» conferem, e mais nada. */
const provas: ProvasDoTitular = {
  otpConfere: async (_t, codigo) => codigo === "123456",
  ligacaoDoEmailConfere: async (_t, token) => token === "tok",
};

/** A Meta espiã: conta cada método, incluindo os que nunca se podem chamar. */
function metaEspia() {
  const chamadas: string[] = [];
  const canal: CanalDaMeta = {
    numeroDoTenant: async () => null,
    subscreverWebhooks: async (w) => void chamadas.push(`subscrever:${w}`),
    cancelarSubscricao: async (w) => void chamadas.push(`cancelar:${w}`),
    removerRota: async (p) => void chamadas.push(`remover_rota:${p}`),
    apagarWaba: async (w) => void chamadas.push(`APAGAR_WABA:${w}`),
    apagarNumero: async (p) => void chamadas.push(`APAGAR_NUMERO:${p}`),
  };
  return { canal, chamadas };
}

async function tenantAtivo(rotulo: string): Promise<{ tenant: string; pnid: string; waba: string }> {
  const tenant = await criarTenant(admin, rotulo);
  meus.push(tenant);
  await activarTenant(admin, tenant);
  const c = await criarCanal(admin, tenant);
  const { rows } = await admin.query("SELECT waba_id FROM platform.tenant_channels WHERE tenant_id = $1", [tenant]);
  return { tenant, pnid: c.phoneNumberId, waba: String(rows[0]?.waba_id) };
}

async function fases(tenant: string): Promise<Record<string, { estado: string; prazo: Date; resultado: Record<string, unknown> }>> {
  const { rows } = await admin.query(
    "SELECT fase, estado, prazo_at, resultado FROM platform.offboarding_run WHERE tenant_id = $1",
    [tenant],
  );
  return Object.fromEntries(
    rows.map((r) => [String(r.fase), { estado: String(r.estado), prazo: r.prazo_at as Date, resultado: r.resultado }]),
  );
}

async function pedidoVerificado(tenant: string): Promise<void> {
  await abrirPedido(lote, { tenantId: tenant, origem: "titular", otp: "123456", tokenDoEmail: "tok", agora: D0 }, provas);
}

/** Uma sanção `encerramento` do KAM-097, humana e com caso, como o Trust a grava. */
async function sancionar(tenant: string): Promise<string> {
  const caso = await admin.query(
    "INSERT INTO platform.review_case (tipo, tenant_id, motivo_codigo, motivo_interno, motivo_publico, " +
      "recomendacao, sla_alerta_at, sla_due_at) VALUES ('trust', $1, $2, 'ensaio do off-boarding', " +
      "'nao_foi_possivel_validar', 'rejeitar', now() + interval '19 hours', now() + interval '24 hours') " +
      "RETURNING id::text AS id",
    [tenant, `sancao_encerramento:${randomUUID().slice(0, 12)}`],
  );
  const id = String(caso.rows[0]?.id);
  const s = await admin.query(
    "INSERT INTO platform.ts_sanction (tenant_id, chave, passo, origem, motivo_interno, motivo_publico, " +
      "autor, case_id, justificacao_salto) VALUES ($1, $2, 'encerramento', 'humana', 'ensaio do off-boarding', " +
      "'loja_encerrada', $3, $4, 'ensaio do off-boarding: salto directo ao encerramento') RETURNING id::text AS id",
    [tenant, `caso:${id}`, randomUUID(), id],
  );
  return String(s.rows[0]?.id);
}

before(async () => {
  admin = await ligar("admin");
  lote = await ligar("batch");
});

after(async () => {
  // A limpeza do KAM-092: o registo de estados é imutável também para o dono.
  if (meus.length > 0) {
    await admin.query("ALTER TABLE platform.tenant_state_log DISABLE TRIGGER USER");
    try {
      await admin.query("DELETE FROM platform.tenant_state_log WHERE tenant_id = ANY($1::uuid[])", [meus]);
    } finally {
      await admin.query("ALTER TABLE platform.tenant_state_log ENABLE ALWAYS TRIGGER tenant_state_log_imutavel");
    }
    await admin.query("DELETE FROM platform.offboarding_run WHERE tenant_id = ANY($1::uuid[])", [meus]);
    await admin.query("ALTER TABLE platform.ts_sanction DISABLE TRIGGER USER");
    try {
      await admin.query("DELETE FROM platform.ts_sanction WHERE tenant_id = ANY($1::uuid[])", [meus]);
    } finally {
      // Os dois gatilhos da `ts_sanction` estao em modo de origem (`O`), e nao `ALWAYS`.
      await admin.query("ALTER TABLE platform.ts_sanction ENABLE TRIGGER ts_sanction_imutavel");
      await admin.query("ALTER TABLE platform.ts_sanction ENABLE TRIGGER ts_sanction_regras");
    }
  }
  await lote?.end();
  await admin?.end();
});

describe("o off-boarding contra a base", () => {
  it("o pedido exige as duas confirmações: só com a sessão é recusado e nada se escreve", async () => {
    const { tenant } = await tenantAtivo("off-pedido");
    for (const [otp, token, falta] of [
      [null, null, /otp, email/],
      ["123456", null, /email/],
      [null, "tok", /otp/],
      ["000000", "tok", /otp/],
    ] as const) {
      await assert.rejects(
        abrirPedido(lote, { tenantId: tenant, origem: "titular", otp, tokenDoEmail: token, agora: D0 }, provas),
        (e: Error) => e instanceof ConfirmacaoIncompletaError && falta.test(e.message),
      );
    }
    assert.deepEqual(await fases(tenant), {}, "nada se escreveu");

    // Sem a porta das provas, nem com os códigos certos.
    await assert.rejects(
      abrirPedido(lote, { tenantId: tenant, origem: "titular", otp: "123456", tokenDoEmail: "tok", agora: D0 }),
      ConfirmacaoIncompletaError,
    );
    const r = await abrirPedido(lote, { tenantId: tenant, origem: "titular", otp: "123456", tokenDoEmail: "tok", agora: D0 }, provas);
    assert.equal(r.aberto, true);
    assert.equal(r.aviso, AVISO_DA_APP_BUSINESS);
    const f = await fases(tenant);
    assert.equal(Object.keys(f).length, 7);
    assert.equal(f.verificacao?.estado, "concluida");
    assert.deepEqual(f.verificacao?.resultado.confirmacoes, ["otp", "email"]);
    for (const [fase, d] of Object.entries({ verificacao: 0, canal: 1, pendentes: 7, exportacao: 7, revogacao: 7, purga: 30, certificado: 30 })) {
      assert.equal(f[fase]?.prazo.getTime(), dia(d).getTime(), fase);
    }
    // Repetir devolve o pedido que existe, e não abre outro.
    const outra = await abrirPedido(lote, { tenantId: tenant, origem: "titular", otp: "123456", tokenDoEmail: "tok", agora: dia(1) }, provas);
    assert.equal(outra.aberto, false);
    assert.equal(outra.d0.getTime(), D0.getTime());
  });

  it("T&S só encerra um tenant suspenso com uma sanção de encerramento, e o titular não a cancela", async () => {
    const { tenant } = await tenantAtivo("off-ts");
    const sancao = await sancionar(tenant);
    await assert.rejects(
      abrirPedido(lote, { tenantId: tenant, origem: "trust_safety", decisaoRef: sancao, agora: D0 }),
      EstadoDoTenantError,
    );
    await admin.query("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = $1", [tenant]);
    for (const ref of ["sancao-ensaio", randomUUID()]) {
      await assert.rejects(
        abrirPedido(lote, { tenantId: tenant, origem: "trust_safety", decisaoRef: ref, agora: D0 }),
        ConfirmacaoIncompletaError,
        "sem uma sanção de encerramento em vigor, T&S não encerra",
      );
    }
    const r = await abrirPedido(lote, { tenantId: tenant, origem: "trust_safety", decisaoRef: sancao, agora: D0 });
    assert.equal(r.aberto, true);
    assert.equal((await fases(tenant)).verificacao?.resultado.origem, "trust_safety");
    await assert.rejects(
      cancelarPedido(lote, { tenantId: tenant, canal: metaEspia().canal, agora: dia(1) }),
      PedidoError,
    );
  });

  it("um pedido de T&S toma o pedido vivo do titular, que deixa de se poder cancelar", async () => {
    const { tenant } = await tenantAtivo("off-ts-toma");
    await pedidoVerificado(tenant);
    await admin.query("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = $1", [tenant]);
    const sancao = await sancionar(tenant);
    const r = await abrirPedido(lote, { tenantId: tenant, origem: "trust_safety", decisaoRef: sancao, agora: dia(1) });
    assert.equal(r.aberto, false);
    assert.equal(r.d0.getTime(), D0.getTime(), "o calendário é o do pedido que já corria");
    assert.equal((await fases(tenant)).verificacao?.resultado.origem, "trust_safety");
    await assert.rejects(
      cancelarPedido(lote, { tenantId: tenant, canal: metaEspia().canal, agora: dia(2) }),
      PedidoError,
    );
  });

  it("o canal: cancela a subscrição, desliga o canal, e nenhuma chamada toca no WABA nem no número; o CHR deixa de encaminhar", async () => {
    const { tenant, pnid, waba } = await tenantAtivo("off-canal");
    await pedidoVerificado(tenant);
    const meta = metaEspia();
    const r = await desligarCanal(lote, { tenantId: tenant, canal: meta.canal, agora: D0 });
    assert.equal(r.desligados, 1);
    assert.deepEqual(meta.chamadas, [`cancelar:${waba}`]);
    assert.equal(meta.chamadas.filter((c) => c.startsWith("APAGAR")).length, 0);
    const f = await fases(tenant);
    assert.equal(f.canal?.estado, "concluida");
    assert.deepEqual(f.canal?.resultado.canais, [{ id: (f.canal?.resultado.canais as { id: string }[])[0]?.id, waba_id: waba, de: "ativo" }]);
    // O CHR lê o canal desligado, e a matriz não deixa a mensagem chegar ao AGR.
    const lido = await new ResolvedorDeCanal(admin).resolver(pnid);
    assert.equal(lido.resolvido?.contexto.estado_canal, "desligado");
    assert.equal(tenantGate(lido.resolvido?.contexto.estado_tenant, "desligado", "processar_entrada").permitido, false);
    // Repetir não chama a Meta outra vez.
    assert.equal((await desligarCanal(lote, { tenantId: tenant, canal: meta.canal, agora: dia(1) })).desligados, 0);
    assert.equal(meta.chamadas.length, 1);
  });

  it("cancelado em D3: o canal volta ao que era, e nenhuma fase seguinte corre", async () => {
    const { tenant, waba } = await tenantAtivo("off-cancelar");
    await pedidoVerificado(tenant);
    const meta = metaEspia();
    await desligarCanal(lote, { tenantId: tenant, canal: meta.canal, agora: D0 });
    assert.equal((await cancelarPedido(lote, { tenantId: tenant, canal: meta.canal, agora: dia(3) })).religados, 1);
    assert.deepEqual(meta.chamadas, [`cancelar:${waba}`, `subscrever:${waba}`]);
    const { rows } = await admin.query("SELECT estado FROM platform.tenant_channels WHERE tenant_id = $1", [tenant]);
    assert.equal(rows[0]?.estado, "ativo");
    const f = await fases(tenant);
    for (const fase of ["pendentes", "exportacao", "revogacao", "purga", "certificado"]) {
      assert.equal(f[fase]?.estado, "cancelada", fase);
    }
    await assert.rejects(verificarPendentes(lote, { tenantId: tenant, agora: dia(4) }), FaseForaDeOrdemError);
    await assert.rejects(desligarCanal(lote, { tenantId: tenant, canal: meta.canal, agora: dia(4) }), FaseForaDeOrdemError);
    // Repetir o cancelamento não religa nada outra vez.
    assert.equal((await cancelarPedido(lote, { tenantId: tenant, canal: meta.canal, agora: dia(4) })).religados, 0);
    // Um pedido novo, verificado de novo, reabre-o: o calendário recomeça do D0 novo.
    const reaberto = await abrirPedido(
      lote, { tenantId: tenant, origem: "titular", otp: "123456", tokenDoEmail: "tok", agora: dia(5) }, provas);
    assert.equal(reaberto.aberto, true);
    const depois = await fases(tenant);
    assert.equal(depois.purga?.prazo.getTime(), dia(35).getTime());
    assert.equal(depois.canal?.estado, "pendente");
    assert.equal(depois.verificacao?.resultado.cancelado_at, undefined);
    assert.equal(depois.verificacao?.resultado.reaberto_de, D0.toISOString());
    // Depois do D7 já não se cancela.
    const outro = await tenantAtivo("off-tarde");
    await pedidoVerificado(outro.tenant);
    await assert.rejects(cancelarPedido(lote, { tenantId: outro.tenant, canal: meta.canal, agora: dia(7) }), PedidoError);
  });

  it("os pendentes: sem encomendas, reservas nem reembolsos abertos, a fase conclui", async () => {
    const { tenant } = await tenantAtivo("off-pendentes");
    await pedidoVerificado(tenant);
    const r = await verificarPendentes(lote, { tenantId: tenant, agora: dia(1) });
    assert.equal(r.concluida, true);
    assert.deepEqual(r.pendentes, { encomendas: 0, disputas: 0, reservas: 0, reembolsos: 0 });
    assert.equal((await fases(tenant)).pendentes?.estado, "concluida");
  });

  it("a revogação no D7: as portas da saga, os entitlements, os canais e um tenant.closed; um crash a meio retoma", async () => {
    const { tenant } = await tenantAtivo("off-revogar");
    await pedidoVerificado(tenant);
    const caso = randomUUID();
    for (const [step, ext] of [["chave_llm", "llm-ensaio"], ["canal_comercio", "medusa-ensaio"], ["inbox_e_rota", "inbox-ensaio"]]) {
      await admin.query(
        "INSERT INTO platform.provisioning_step (onboarding_id, tenant_id, step, status, attempt, external_id) " +
          "VALUES ($1, $2, $3, 'concluido', 1, $4)",
        [caso, tenant, step, ext],
      );
    }
    await admin.query("INSERT INTO platform.entitlements (tenant_id, modulo) VALUES ($1, 'vendedor')", [tenant]);
    const chamadas: string[] = [];
    let falhar = true;
    const portas: PortasDaRevogacao = {
      chaveDeLlm: { revogar: async (id) => void chamadas.push(`revogar:${id}`) },
      canalDeComercio: {
        arquivar: async (id) => {
          if (falhar) {
            falhar = false;
            throw new Error("a Medusa caiu a meio");
          }
          chamadas.push(`arquivar:${id}`);
        },
      },
      inbox: { desligar: async (id) => void chamadas.push(`desligar:${id}`) },
    };

    await assert.rejects(revogar(lote, { tenantId: tenant, portas, agora: dia(6) }), FaseForaDeOrdemError, "antes do D7");
    await assert.rejects(revogar(lote, { tenantId: tenant, portas, agora: dia(7) }), FaseForaDeOrdemError, "sem exportação");
    // A exportação é do lado Python; aqui marca-se como ele a marca.
    await admin.query("UPDATE platform.offboarding_run SET estado = 'concluida' WHERE tenant_id = $1 AND fase = 'exportacao'", [tenant]);
    await assert.rejects(revogar(lote, { tenantId: tenant, portas, agora: dia(7) }), /o canal nao foi desligado/);
    await desligarCanal(lote, { tenantId: tenant, canal: metaEspia().canal, agora: D0 });
    // Um tenant que ficou restrito: recusa **antes** de qualquer porta.
    await admin.query("UPDATE platform.tenants SET estado = 'restrito' WHERE id = $1", [tenant]);
    await assert.rejects(revogar(lote, { tenantId: tenant, portas, agora: dia(7) }), /restrito/);
    assert.deepEqual(chamadas, [], "nada revogado num tenant que não se pode encerrar");
    await admin.query("UPDATE platform.tenants SET estado = 'ativo' WHERE id = $1", [tenant]);

    await assert.rejects(revogar(lote, { tenantId: tenant, portas, agora: dia(7) }), /a Medusa caiu a meio/);
    assert.deepEqual((await fases(tenant)).revogacao?.resultado.passos, { chave_llm: "concluido" });
    const r = await revogar(lote, { tenantId: tenant, portas, agora: dia(7) });
    assert.equal(r.encerrado, true);
    assert.deepEqual(chamadas, ["revogar:llm-ensaio", "arquivar:medusa-ensaio", "desligar:inbox-ensaio"], "a chave não foi revogada duas vezes");

    const estado = await admin.query("SELECT estado FROM platform.tenants WHERE id = $1", [tenant]);
    assert.equal(estado.rows[0]?.estado, "encerrado");
    const ent = await admin.query("SELECT ativo FROM platform.entitlements WHERE tenant_id = $1", [tenant]);
    assert.deepEqual(ent.rows.map((x) => x.ativo), [false]);
    const canais = await admin.query("SELECT estado FROM platform.tenant_channels WHERE tenant_id = $1", [tenant]);
    assert.deepEqual(canais.rows.map((x) => x.estado), ["encerrado"]);
    const log = await admin.query("SELECT de, para, motivo FROM platform.tenant_state_log WHERE tenant_id = $1", [tenant]);
    assert.deepEqual(log.rows.map((x) => [x.de, x.para, x.motivo]), [["ativo", "encerrado", "pedido_do_titular"]]);
    const eventos = await admin.query(
      "SELECT envelope -> 'payload' AS payload FROM platform.events_outbox WHERE tenant_id = $1 AND tipo = 'tenant.closed'",
      [tenant],
    );
    assert.deepEqual(eventos.rows.map((x) => x.payload), [{ motivo: "pedido_do_titular" }]);
    assert.equal((await fases(tenant)).revogacao?.estado, "concluida");

    // Repetir não chama as portas nem emite outro evento.
    const outra = await revogar(lote, { tenantId: tenant, portas, agora: dia(8) });
    assert.equal(outra.encerrado, false);
    assert.equal(chamadas.length, 3);
    const depois = await admin.query("SELECT count(*)::int AS n FROM platform.events_outbox WHERE tenant_id = $1 AND tipo = 'tenant.closed'", [tenant]);
    assert.equal(depois.rows[0]?.n, 1);
  });
});
