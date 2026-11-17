/**
 * As duas leituras do painel do KAM-190, sobre o COM: o estado do canal e uma
 * oferta só.
 *
 *   vistaDoCanal   tenant_channels + sincronização + trust_level + avisos de T&S
 *   obterOferta    o preço anterior do `PATCH` do painel, sem a lista
 *
 * ## A base de ensaio filtra pelo **texto** da consulta
 *
 * Pela razão do `produtos.painel.test.ts`: uma base que decidisse pelo argumento
 * ficava verde com o `tenant_id = $1` apagado. Aqui ela só devolve as linhas do
 * tenant de `$1` se o texto tiver o predicado, e só filtra pelo `origem = 'pme'`
 * se o texto o tiver. A ordem, o `LIMIT`, as colunas e os privilégios do
 * `kamba_app` medem-se contra o motor, em `db/tests/test_canal_do_painel.py`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { SQL_SANCOES_DO_TENANT_APP } from "@kamba/core-ts/trust";

import type { ClienteSql, Ctx } from "../src/port/index.ts";
import { comRegisto, operacoesDoCom, type Dependencias } from "../src/adapters/medusa/index.ts";
import {
  SQL_CANAL_DO_PAINEL,
  SQL_NIVEL_DO_TENANT,
  SQL_SINCRONIZACAO_DO_CANAL,
  clienteDoTenant,
  estadoNoPainel,
  vistaDoCanal,
} from "../src/canal/vista.ts";
import { obterOferta } from "../src/produtos/index.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CANAL_A = "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0a";

type Linha = Record<string, unknown> & { tenant_id: string };

interface Tabelas {
  canais: Linha[];
  sincronizacoes: Linha[];
  niveis: Linha[];
  sancoes: Linha[];
  ofertas: Linha[];
}

function tabelas(extra: Partial<Tabelas> = {}): Tabelas {
  return {
    canais: [
      { tenant_id: TENANT_A, channel_id: CANAL_A, estado: "restrito", quality_rating: "amarelo", messaging_limit: "TIER_250", origem: "pme" },
      { tenant_id: TENANT_B, channel_id: "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0b", estado: "ativo", quality_rating: "verde", messaging_limit: "TIER_1K", origem: "pme" },
    ],
    sincronizacoes: [{ tenant_id: TENANT_A, channel_id: CANAL_A, estado: "sincronizado" }],
    niveis: [
      { tenant_id: TENANT_A, nivel: 1, tecto_pedido_minor: "5000000", currency: "AOA" },
      { tenant_id: TENANT_B, nivel: 0, tecto_pedido_minor: "100", currency: "AOA" },
    ],
    sancoes: [
      sancao(TENANT_A, "s1", "aviso", "conduta_em_analise", "2026-11-01T10:00:00Z"),
      sancao(TENANT_A, "s2", "limitacao", "actividade_limitada", "2026-11-05T10:00:00Z"),
      sancao(TENANT_B, "s3", "suspensao", "loja_suspensa", "2026-11-06T10:00:00Z"),
    ],
    ofertas: [],
    ...extra,
  };
}

function sancao(tenant: string, id: string, passo: string, motivo: string, em: string): Linha {
  return {
    tenant_id: tenant,
    id,
    chave: `chave-${id}`,
    passo,
    origem: "automatica",
    motivo_publico: motivo,
    recurso_de: null,
    recurso_estado: null,
    em: new Date(em),
  };
}

/** Uma base que serve as quatro consultas **pelo texto**, e regista o que leu. */
function base(t: Tabelas): { cliente: ClienteSql; lidas: string[] } {
  const lidas: string[] = [];
  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql.includes("platform.tenants")) {
        return { rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }] };
      }
      const doTenant = (linhas: Linha[]): Linha[] =>
        /tenant_id\s*=\s*\$1/.test(sql) ? linhas.filter((l) => l.tenant_id === parametros[0]) : linhas;
      let linhas: Linha[];
      if (sql === SQL_CANAL_DO_PAINEL) {
        lidas.push("canal");
        linhas = doTenant(t.canais).filter((l) => !/origem = 'pme'/.test(sql) || l["origem"] === "pme");
      } else if (sql === SQL_SINCRONIZACAO_DO_CANAL) {
        lidas.push("sincronizacao");
        linhas = doTenant(t.sincronizacoes).filter((l) => l["channel_id"] === parametros[1]);
      } else if (sql === SQL_NIVEL_DO_TENANT) {
        lidas.push("nivel");
        linhas = doTenant(t.niveis);
      } else if (sql === SQL_SANCOES_DO_TENANT_APP) {
        lidas.push("sancoes");
        linhas = doTenant(t.sancoes);
      } else if (sql.includes("platform.offer_terms")) {
        lidas.push("oferta");
        linhas = doTenant(t.ofertas).filter((l) => !/sku\s*=\s*\$2/.test(sql) || l["sku"] === parametros[1]);
      } else {
        throw new Error(`consulta inesperada: ${sql.slice(0, 60)}`);
      }
      return { rows: linhas.map(({ tenant_id: _t, ...resto }) => resto) };
    },
  };
  return { cliente, lidas };
}

function deps(cliente: ClienteSql): Dependencias {
  return { comTenant: async (_t, trabalho) => trabalho(cliente), anel: [`v1:${Buffer.alloc(32, 7).toString("base64")}`, null] };
}

function ctx(tenant = TENANT_A): Ctx {
  return { tenantId: tenant, actor: { kind: "dono", id: "dono-1" }, traceId: "trace-canal" };
}

// -------------------------------------------------------------- o canal

test("KAM-190: a vista do canal junta as quatro fontes, so do tenant do ctx", async () => {
  const { cliente, lidas } = base(tabelas());
  const r = await comRegisto(deps(cliente), ctx(), (reg) => vistaDoCanal(reg));
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.deepEqual(r.valor, {
    estado: "ativo",
    restrito: true,
    qualidade: "amarelo",
    escalao: "TIER_250",
    nivel: 1,
    tectoPedidoMinor: 5_000_000n,
    currency: "AOA",
    // Do mais recente para o mais antigo, e nunca o motivo interno.
    avisos: ["actividade_limitada", "conduta_em_analise"],
  });
  assert.deepEqual(lidas, ["canal", "sincronizacao", "nivel", "sancoes"]);
});

test("KAM-190: o tenant B ve o dele, e A nunca ve o de B", async () => {
  const { cliente } = base(tabelas());
  const r = await comRegisto(deps(cliente), ctx(TENANT_B), (reg) => vistaDoCanal(reg));
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.qualidade, "verde");
  assert.deepEqual(r.valor.avisos, ["loja_suspensa"]);
  assert.equal(r.valor.tectoPedidoMinor, 100n);
});

test("KAM-190: sem canal, sem nivel e sem sancoes, a vista e sem_canal e vazia", async () => {
  const { cliente, lidas } = base(tabelas({ canais: [], niveis: [], sancoes: [] }));
  const r = await comRegisto(deps(cliente), ctx(), (reg) => vistaDoCanal(reg));
  assert.deepEqual(r, {
    tipo: "ok",
    valor: { estado: "sem_canal", restrito: false, qualidade: null, escalao: null, nivel: null, tectoPedidoMinor: null, currency: null, avisos: [] },
  });
  // Sem canal, a sincronizacao nao se pergunta.
  assert.deepEqual(lidas, ["canal", "nivel", "sancoes"]);
});

test("KAM-190: um canal da plataforma (Fluxo B) nao e o numero do dono", async () => {
  const { cliente } = base(tabelas({ canais: [{ tenant_id: TENANT_A, channel_id: CANAL_A, estado: "ativo", quality_rating: "verde", messaging_limit: null, origem: "plataforma" }] }));
  const r = await comRegisto(deps(cliente), ctx(), (reg) => vistaDoCanal(reg));
  assert.equal(r.tipo === "ok" && r.valor.estado, "sem_canal");
});

test("KAM-190: um recurso provido tira a sancao dos avisos", async () => {
  const provido = { ...sancao(TENANT_A, "r1", "aviso", "recurso_aceite", "2026-11-07T10:00:00Z"), recurso_de: "s2", recurso_estado: "provido" };
  const { cliente } = base(tabelas({ sancoes: [...tabelas().sancoes, provido] }));
  const r = await comRegisto(deps(cliente), ctx(), (reg) => vistaDoCanal(reg));
  assert.deepEqual(r.tipo === "ok" && r.valor.avisos, ["conduta_em_analise"]);
});

test("KAM-190: pelas operacoes, o channel-view nao pede o merchant do Medusa", async () => {
  // Um tenant em `aguarda_es` pode ainda nao ter loja no Medusa, e e o que mais
  // precisa da pagina do canal. O `comRegisto` levantava `MerchantEmFaltaError`.
  const { cliente } = base(tabelas());
  const semMerchant: ClienteSql = {
    async query(sql: string, parametros?: readonly unknown[]) {
      if (sql.includes("platform.tenants")) throw new Error("a leitura do canal foi ao merchant");
      return cliente.query(sql, parametros);
    },
  };
  const r = await operacoesDoCom(deps(semMerchant)).vistaDoCanal(ctx());
  assert.equal(r.tipo, "ok");
  assert.equal(r.tipo === "ok" && r.valor.escalao, "TIER_250");
});

test("KAM-190: suspenso e encerrado sao desligados e restritos, para a pagina nao oferecer religar", async () => {
  for (const estado of ["suspenso", "encerrado"]) {
    const { cliente } = base(tabelas({ canais: [{ tenant_id: TENANT_A, channel_id: CANAL_A, estado, quality_rating: null, messaging_limit: null, origem: "pme" }] }));
    const r = await comRegisto(deps(cliente), ctx(), (reg) => vistaDoCanal(reg));
    assert.equal(r.tipo === "ok" && r.valor.estado, "desligado", estado);
    assert.equal(r.tipo === "ok" && r.valor.restrito, true, estado);
  }
});

test("KAM-190: a tabela dos quatro estados do painel", () => {
  const casos: [string | null, string | null, string][] = [
    [null, null, "sem_canal"],
    ["desligado", null, "desligado"],
    ["suspenso", "a_sincronizar", "desligado"],
    ["encerrado", null, "desligado"],
    ["pendente", null, "a_sincronizar"],
    ["ativo", "a_sincronizar", "a_sincronizar"],
    ["restrito", "a_sincronizar", "a_sincronizar"],
    ["ativo", "sincronizado", "ativo"],
    ["ativo", "falhado", "ativo"],
    ["restrito", null, "ativo"],
  ];
  for (const [canal, sinc, esperado] of casos) {
    assert.equal(estadoNoPainel(canal, sinc), esperado, `${canal}/${sinc}`);
  }
});

test("KAM-190: o cliente dos avisos so le o tenant do ctx, e outro tenant levanta", async () => {
  const { cliente } = base(tabelas());
  await comRegisto(deps(cliente), ctx(), async (reg) => {
    const c = clienteDoTenant(reg);
    const r = await c.query(SQL_SANCOES_DO_TENANT_APP, [TENANT_A]);
    assert.equal(r.rows.length, 2);
    await assert.rejects(() => c.query(SQL_SANCOES_DO_TENANT_APP, [TENANT_B]), /so le o tenant do ctx/);
  });
});

test("KAM-190: as tres consultas do canal tem o tenant_id = $1 que o repo-base exige, e nenhuma escreve", () => {
  for (const sql of [SQL_CANAL_DO_PAINEL, SQL_SINCRONIZACAO_DO_CANAL, SQL_NIVEL_DO_TENANT]) {
    assert.match(sql, /WHERE tenant_id = \$1/);
    assert.match(sql, /^\s*SELECT/);
    assert.doesNotMatch(sql, /\$\{/);
  }
  // O `trust_level` so pelas quatro colunas que o `kamba_app` le (§3.75).
  assert.doesNotMatch(SQL_NIVEL_DO_TENANT, /motivo|actor|versao_config/);
});

// -------------------------------------------------------- uma oferta so

function oferta(tenant: string, sku: string, estado = "publicado"): Linha {
  return {
    tenant_id: tenant,
    sku,
    nome: `Produto ${sku}`,
    preco_tipo: "fixo",
    preco_minor: "1250000",
    currency: "AOA",
    preco_valido_ate: null,
    stock_modo: "indicativo",
    stock_quantidade: "3",
    stock_reservada: "0",
    stock_verificado_at: null,
    estado,
    versao: "2026-11-02T11:00:00.000001Z",
  };
}

test("KAM-190: obterOferta devolve a do tenant do ctx, e a de B e NOT_FOUND", async () => {
  const { cliente } = base(tabelas({ ofertas: [oferta(TENANT_A, "arroz"), oferta(TENANT_B, "so-de-b")] }));
  const r = await comRegisto(deps(cliente), ctx(), (reg) => obterOferta(reg, "arroz"));
  assert.equal(r.tipo, "ok");
  if (r.tipo === "ok") {
    assert.equal(r.valor.precoMinor, 1_250_000n);
    assert.equal(r.valor.versao, "2026-11-02T11:00:00.000001Z");
  }
  const deB = await comRegisto(deps(cliente), ctx(), (reg) => obterOferta(reg, "so-de-b"));
  assert.deepEqual(deB, { tipo: "erro", erro: "NOT_FOUND" });
});

test("KAM-190: obterOferta de uma arquivada e NOT_FOUND, e um sku vazio e VALIDATION_ERROR sem ir a base", async () => {
  const { cliente, lidas } = base(tabelas({ ofertas: [oferta(TENANT_A, "velha", "arquivado")] }));
  assert.deepEqual(await comRegisto(deps(cliente), ctx(), (reg) => obterOferta(reg, "velha")), { tipo: "erro", erro: "NOT_FOUND" });
  lidas.length = 0;
  assert.deepEqual(await comRegisto(deps(cliente), ctx(), (reg) => obterOferta(reg, "  ")), { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(lidas, []);
});
