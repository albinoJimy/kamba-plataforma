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
 * 4. **O preço anómalo** (KAM-209): a volta lê as ofertas de todos os tenants
 *    como `kamba_batch`, e 19 referências não avaliam e 20 avaliam; 1% e 100×
 *    da mediana ficam dentro, e um cêntimo para fora sinaliza. Doze SKUs
 *    anómalos são um sinal e nenhuma sanção; uma loja sozinha não fixa a
 *    mediana. O `kamba_app`, com o contexto de um tenant, não vê as ofertas dos
 *    outros, e o sinal diz só a contagem.
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
import { comTenant } from "../src/tenant_guard/index.ts";
import { FONTE_DAS_REFERENCIAS, MetricasDoTrust, SQL_OFERTAS_COM_PRECO, VARREDURAS, efeitoDeTrust } from "../src/trust/index.ts";
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
    assert.equal(
      await contar("SELECT count(*) AS n FROM platform.audit_log WHERE action = 'batch.run' AND entity = 'ts_varredura'", []),
      antes + VARREDURAS.length,
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

// ------------------------------------------------------- preço anómalo (KAM-209)

/**
 * `n` ofertas semeadas pelo dono da tabela: publicadas e de preço fixo, salvo
 * se o `como` disser outra coisa.
 */
async function publicadas(
  tenant: string,
  prefixo: string,
  n: number,
  preco: number | null,
  categoria: string | null,
  como: { readonly estado?: string; readonly tipo?: string; readonly apagada?: boolean } = {},
): Promise<void> {
  await admin.query(
    "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, estado, categoria, deleted_at) " +
      "SELECT $1, $2 || g, 'produto ' || g, $6, $3, $7, $4, CASE WHEN $8 THEN now() END FROM generate_series(1, $5) g",
    [tenant, prefixo, preco, categoria, n, como.tipo ?? "fixo", como.estado ?? "publicado", como.apagada ?? false],
  );
}

/** Três lojas novas com `n` referências repartidas entre elas, ao mesmo preço. */
async function tresLojas(rotulo: string, n: number, preco: number, categoria: string): Promise<string[]> {
  const lojas = [await criarTenant(admin, `${rotulo}-1`), await criarTenant(admin, `${rotulo}-2`), await criarTenant(admin, `${rotulo}-3`)];
  const porLoja = [Math.ceil(n / 3), Math.ceil((n - Math.ceil(n / 3)) / 2)];
  const partes = [porLoja[0]!, porLoja[1]!, n - porLoja[0]! - porLoja[1]!];
  for (const [i, loja] of lojas.entries()) await publicadas(loja, "ref-", partes[i]!, preco, categoria);
  return lojas;
}

async function sinaisDePreco(tenant: string): Promise<Record<string, unknown>[]> {
  return (
    await admin.query<{ detalhe: Record<string, unknown> }>(
      "SELECT detalhe FROM platform.ts_signal WHERE tenant_id = $1 AND tipo = 'preco_anomalo' ORDER BY criado_at",
      [tenant],
    )
  ).rows.map((l) => l.detalhe);
}

async function sancoes(tenant: string): Promise<number> {
  return contar("SELECT count(*) AS n FROM platform.ts_sanction WHERE tenant_id = $1", [tenant]);
}

function processo() {
  return montarProcesso({
    lote: lote as unknown as ConjuntoSql,
    app: app as unknown as ConjuntoSql,
    efeitos: efeitosDoLote(lote as unknown as ConjuntoSql, { carenciaMs: 0 }),
    log: semRegisto,
  });
}

describe("o preço anómalo contra a base (KAM-209)", () => {
  it("19 referências de outras lojas não avaliam; a 20.ª avalia, e o sinal diz só a contagem", async () => {
    const alvo = await criarTenant(admin, "preco-alvo");
    await publicadas(alvo, "alvo-", 1, 1, "electronica");
    // As do próprio tenant nunca contam: vinte do alvo a 100 000 não lhe fazem referência.
    await publicadas(alvo, "proprio-", 20, 100_000, "electronica");
    const lojas = await tresLojas("preco-ref", 19, 100_000, "electronica");
    const p = processo();
    assert.deepEqual((await p.cicloDoTrust.correr()).falhas, []);
    assert.deepEqual(await sinaisDePreco(alvo), []);

    await publicadas(lojas[0]!, "mais-", 1, 100_000, "electronica");
    await p.cicloDoTrust.correr();
    const sinais = await sinaisDePreco(alvo);
    assert.deepEqual(sinais, [{ contagem: 1, fonte: FONTE_DAS_REFERENCIAS, versao_politica: "1.0.0" }]);
    // As lojas das referências não ficam sinalizadas, nem nomeadas no sinal.
    for (const loja of lojas) assert.deepEqual(await sinaisDePreco(loja), []);
    assert.doesNotMatch(JSON.stringify(sinais), new RegExp(lojas.join("|")));

    // A volta seguinte, na mesma janela, não grava outra vez.
    await p.cicloDoTrust.correr();
    assert.equal((await sinaisDePreco(alvo)).length, 1);
  });

  it("1% e 100× da mediana ficam dentro; um cêntimo para fora sinaliza", async () => {
    await tresLojas("fronteira-ref", 20, 100_000, "beleza");
    const casos: readonly [number, boolean][] = [
      [1_000, false],
      [999, true],
      [10_000_000, false],
      [10_000_001, true],
    ];
    const alvos: [string, boolean][] = [];
    for (const [preco, anomalo] of casos) {
      const alvo = await criarTenant(admin, `fronteira-${preco}`);
      await publicadas(alvo, "a-", 1, preco, "beleza");
      alvos.push([alvo, anomalo]);
    }
    await processo().cicloDoTrust.correr();
    for (const [alvo, anomalo] of alvos) assert.equal((await sinaisDePreco(alvo)).length, anomalo ? 1 : 0);
  });

  it("doze SKUs anómalos são um sinal, e não dão aviso nem limitação só por preço", async () => {
    const alvo = await criarTenant(admin, "doze-alvo");
    await tresLojas("doze-ref", 21, 100_000, "material_construcao");
    await publicadas(alvo, "anomalo-", 12, 1, "material_construcao");
    const p = processo();
    await p.cicloDoTrust.correr();
    await p.cicloDoTrust.correr();
    assert.deepEqual(await sinaisDePreco(alvo), [{ contagem: 12, fonte: FONTE_DAS_REFERENCIAS, versao_politica: "1.0.0" }]);
    assert.equal(await sancoes(alvo), 0, "nem o aviso nem a limitação");
  });

  it("uma loja com 20 ofertas a 1 Kz não fixa a mediana, e a volta conta a oferta que não avaliou", async () => {
    const alvo = await criarTenant(admin, "uma-loja-alvo");
    const concorrente = await criarTenant(admin, "uma-loja-concorrente");
    await publicadas(concorrente, "barato-", 20, 100, "servicos");
    await publicadas(alvo, "normal-", 1, 100_000, "servicos");
    const p = processo();
    const r = await p.cicloDoTrust.correr();
    assert.deepEqual(await sinaisDePreco(alvo), []);
    assert.ok((r.naoAvaliadas?.poucasLojas ?? 0) >= 1);
    assert.match(p.metricasDoTrust.exposicao(), /^ts_ofertas_nao_avaliadas\{motivo="poucas_lojas"\} [1-9]\d*$/m);
  });

  it("as ofertas sem categoria e as da `outra` não se avaliam, e a volta conta as sem categoria", async () => {
    const alvo = await criarTenant(admin, "sem-categoria");
    await tresLojas("outra-ref", 20, 100_000, "outra");
    await publicadas(alvo, "outra-", 1, 1, "outra");
    const p = processo();
    const antes = (await p.cicloDoTrust.correr()).naoAvaliadas?.semCategoria;
    assert.ok(antes !== undefined);
    // Contam as publicadas sem categoria, e só elas: nem o rascunho, nem a apagada.
    await publicadas(alvo, "antiga-", 2, 1, null);
    await publicadas(alvo, "rascunho-", 1, 1, null, { estado: "rascunho" });
    await publicadas(alvo, "apagada-", 1, 1, null, { apagada: true });
    const r = await p.cicloDoTrust.correr();
    assert.equal(r.naoAvaliadas?.semCategoria, antes + 2);
    assert.match(p.metricasDoTrust.exposicao(), new RegExp(`^ts_ofertas_nao_avaliadas\\{motivo="sem_categoria"\\} ${antes + 2}$`, "m"));
    assert.deepEqual(await sinaisDePreco(alvo), []);
  });

  it("só as publicadas, não apagadas e de preço fixo são referência; o `a_partir_de` avalia-se", async () => {
    const normal = await criarTenant(admin, "predicados-normal");
    const apartir = await criarTenant(admin, "predicados-apartir");
    const lojas = await tresLojas("predicados-ref", 20, 100_000, "restauracao");
    // Trinta de cada forma que **não** é referência, a 1: se alguma contasse,
    // a mediana caía para 1 e a oferta normal passava a anómala.
    const b = lojas[0]!;
    await publicadas(b, "rascunho-", 30, 1, "restauracao", { estado: "rascunho" });
    await publicadas(b, "arquivada-", 30, 1, "restauracao", { estado: "arquivado" });
    await publicadas(b, "apagada-", 30, 1, "restauracao", { apagada: true });
    await publicadas(b, "apartir-", 30, 1, "restauracao", { tipo: "a_partir_de" });
    await publicadas(b, "consulta-", 30, null, "restauracao", { tipo: "sob_consulta" });
    // Uma loja com a oferta normal e um rascunho anómalo (que não se avalia).
    await publicadas(normal, "normal-", 1, 100_000, "restauracao");
    await publicadas(normal, "rascunho-", 1, 1, "restauracao", { estado: "rascunho" });
    // E uma com um `a_partir_de` anómalo, que se avalia.
    await publicadas(apartir, "apartir-", 1, 1, "restauracao", { tipo: "a_partir_de" });
    await processo().cicloDoTrust.correr();
    assert.deepEqual(await sinaisDePreco(normal), []);
    assert.equal((await sinaisDePreco(apartir)).length, 1);
  });

  it("a mediana atravessa tenants só pelo kamba_batch: o kamba_app vê as ofertas do seu tenant e mais nenhuma", async () => {
    const a = await criarTenant(admin, "iso-a");
    const b = await criarTenant(admin, "iso-b");
    await publicadas(a, "iso-", 2, 100_000, "mercearia");
    await publicadas(b, "iso-", 3, 100_000, "mercearia");
    const ligacao = await app.connect();
    try {
      const vistas = await comTenant(ligacao, a, async () => (await ligacao.query<Record<string, unknown>>(SQL_OFERTAS_COM_PRECO)).rows);
      assert.ok(vistas.length >= 2);
      assert.ok(vistas.every((l) => l["tenant_id"] === a), "o kamba_app só vê o seu tenant");
    } finally {
      ligacao.release();
    }
    const doLote = (await lote.query<Record<string, unknown>>(SQL_OFERTAS_COM_PRECO)).rows.filter((l) =>
      String(l["sku"]).startsWith("iso-"),
    );
    assert.deepEqual(new Set(doLote.map((l) => l["tenant_id"])), new Set([a, b]));
  });
});
