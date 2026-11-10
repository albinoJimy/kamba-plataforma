/**
 * As duas operações do painel do dono (KAM-099), sobre o módulo `produtos`.
 *
 *   listarOfertas    a lista do critério 2, só do tenant do `ctx`
 *   alterarOferta    preço e stock com CAS sobre o `atualizado_at`
 *
 * ## A base de ensaio **executa o predicado pelo texto**, e não pelo argumento
 *
 * O CAS é o `AND atualizado_at = $5::timestamptz` do `SQL_ALTERAR_OFERTA`. Uma
 * base falsa que decidisse o conflito comparando o argumento com a versão, sem
 * olhar para a instrução, ficava verde com o predicado **apagado** — que é o
 * defeito que esta casa já apanhou num ensaio citado como prova de uma barreira.
 * Por isso a base desta bateria só recusa a escrita quando o texto do `UPDATE`
 * **tem** o predicado; sem ele, escreve, como o PostgreSQL escreveria. O mesmo
 * vale para o tenant: a base filtra pelo `tenant_id = $1` só se ele estiver no
 * texto.
 *
 * O relógio da base avança um microssegundo por escrita, que é o que o
 * `clock_timestamp()` dá: duas escritas nunca deixam a mesma versão. A prova de
 * que é o `clock_timestamp()` e não o `now()` que o faz é do motor, e está no
 * `db/tests_produtos/test_painel.py`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { ClienteSql, Ctx } from "../src/port/index.ts";
import { comRegisto, type Dependencias } from "../src/adapters/medusa/index.ts";
import {
  LIMITE_DO_PAINEL,
  SQL_ALTERAR_OFERTA,
  TIPO_PRICE_CHANGED,
  TIPO_PRODUCT_CHANGED,
  TIPO_STOCK_ADJUSTED,
  alterarOferta,
  getOfferView,
  listarOfertas,
  type AlteracaoDeOferta,
} from "../src/produtos/index.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const SKU = "arroz-5kg";
const VERSAO_INICIAL = "2026-11-02T11:00:00.000001Z";

interface Linha {
  tenant_id: string;
  sku: string;
  nome: string;
  preco_tipo: string;
  preco_minor: string | null;
  currency: string;
  preco_valido_ate: string | null;
  stock_modo: string;
  stock_quantidade: string | null;
  stock_reservada: string;
  stock_verificado_at: string | null;
  estado: string;
  versao: string;
}

interface Visto {
  readonly escritas: string[];
  readonly auditorias: unknown[][];
  readonly eventos: string[];
}

/** O microssegundo seguinte de uma versão. É o `clock_timestamp()` da base. */
function seguinte(versao: string): string {
  const [segundos, micro] = versao.slice(0, -1).split(".");
  const n = Number(micro) + 1;
  return `${segundos}.${String(n).padStart(6, "0")}Z`;
}

function linha(tenant: string, sku: string, extra: Partial<Linha> = {}): Linha {
  return {
    tenant_id: tenant,
    sku,
    nome: `Produto ${sku}`,
    preco_tipo: "fixo",
    preco_minor: "1250000",
    currency: "AOA",
    preco_valido_ate: null,
    stock_modo: "indicativo",
    stock_quantidade: "12",
    stock_reservada: "2",
    stock_verificado_at: "2026-11-02T11:00:00.000Z",
    estado: "publicado",
    versao: VERSAO_INICIAL,
    ...extra,
  };
}

/**
 * Uma base com as linhas dadas, que honra o tenant e o CAS **pelo texto**.
 *
 * `antesDoUpdate` deixa um caso mexer na linha entre a leitura trancada e a
 * escrita — é a «outra escrita que chegou entretanto».
 */
function base(
  linhas: Linha[],
  antesDoUpdate?: (l: Linha) => void,
): { cliente: ClienteSql; visto: Visto } {
  const visto: Visto = { escritas: [], auditorias: [], eventos: [] };
  const doTenant = (sql: string, parametros: readonly unknown[]): Linha[] =>
    /tenant_id\s*=\s*\$1/.test(sql)
      ? linhas.filter((l) => l.tenant_id === parametros[0])
      : linhas;

  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql.includes("platform.tenants")) {
        return { rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }] };
      }
      if (sql.includes("audit_append")) {
        visto.auditorias.push([...parametros]);
        return { rows: [{}] };
      }
      if (sql.includes("evt_emitir")) {
        visto.eventos.push(String(parametros[0]));
        return { rows: [{ event_id: `evt-${visto.eventos.length}` }] };
      }
      if (!sql.includes("platform.offer_terms")) return { rows: [] };

      const candidatas = doTenant(sql, parametros).filter(
        (l) => !/sku\s*=\s*\$2/.test(sql) || l.sku === parametros[1],
      );

      if (/^\s*UPDATE/i.test(sql)) {
        const alvo = candidatas[0];
        if (alvo === undefined) return { rows: [] };
        antesDoUpdate?.(alvo);
        if (/atualizado_at\s*=\s*\$5::timestamptz/.test(sql) && alvo.versao !== parametros[4]) {
          return { rows: [] };
        }
        if (/estado\s*<>\s*'arquivado'/.test(sql) && alvo.estado === "arquivado") {
          return { rows: [] };
        }
        if (sql.includes("preco_tipo = $3")) {
          alvo.preco_tipo = String(parametros[2]);
          alvo.preco_minor = parametros[3] === null ? null : String(parametros[3]);
        }
        alvo.versao = seguinte(alvo.versao);
        visto.escritas.push(sql.includes("preco_tipo = $3") ? "preco" : "stock");
        return { rows: [{ sku: alvo.sku }] };
      }

      const vistas = candidatas
        .filter((l) => !/estado\s*<>\s*'arquivado'/.test(sql) || l.estado !== "arquivado")
        .map((l) => ({ ...l, atualizado_at: l.versao }));
      if (/LIMIT \$2/.test(sql)) return { rows: vistas.slice(0, Number(parametros[1])) };
      return { rows: vistas };
    },
  };
  return { cliente, visto };
}

const ANEL: readonly [string, string | null] = [`v1:${Buffer.alloc(32, 7).toString("base64")}`, null];

function deps(cliente: ClienteSql): Dependencias {
  return { comTenant: async (_t, trabalho) => trabalho(cliente), anel: ANEL };
}

function ctx(tenant = TENANT_A): Ctx {
  return { tenantId: tenant, actor: { kind: "dono", id: "dono-1" }, traceId: "trace-painel" };
}

function alteracao(extra: Partial<AlteracaoDeOferta> = {}): AlteracaoDeOferta {
  return { sku: SKU, precoTipo: "fixo", precoMinor: 1_500_000n, versao: VERSAO_INICIAL, ...extra };
}

// ------------------------------------------------------------------- a lista

test("KAM-099 criterio 2: a lista traz modo, preco, stock da 0033 e a versao", async () => {
  const { cliente } = base([linha(TENANT_A, SKU)]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) => listarOfertas(reg));
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.truncada, false);
  const [oferta] = r.valor.itens;
  assert.equal(oferta?.precoTipo, "fixo");
  assert.equal(oferta?.precoMinor, 1_250_000n);
  assert.equal(oferta?.stockQuantidade, 12);
  assert.equal(oferta?.stockReservada, 2);
  assert.equal(oferta?.versao, VERSAO_INICIAL);
});

test("KAM-099 isolamento: a lista do tenant A nao traz linhas de B", async () => {
  const { cliente } = base([linha(TENANT_A, SKU), linha(TENANT_B, "so-de-b")]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) => listarOfertas(reg));
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.deepEqual(r.valor.itens.map((o) => o.sku), [SKU]);
});

test("KAM-099: acima do tecto a lista diz truncada, e nao corta em silencio", async () => {
  const muitas = Array.from({ length: LIMITE_DO_PAINEL + 3 }, (_, i) => linha(TENANT_A, `sku-${i}`));
  const { cliente } = base(muitas);
  const r = await comRegisto(deps(cliente), ctx(), (reg) => listarOfertas(reg));
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.itens.length, LIMITE_DO_PAINEL);
  assert.equal(r.valor.truncada, true);
});

// --------------------------------------------------------------- a escrita

test("KAM-099 criterio 3: gravar o preco audita, emite catalog.price_changed e move a versao", async () => {
  const { cliente, visto } = base([linha(TENANT_A, SKU)]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) => alterarOferta(reg, alteracao()));
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.precoMinor, 1_500_000n);
  assert.notEqual(r.valor.versao, VERSAO_INICIAL);
  assert.deepEqual(visto.escritas, ["preco"]);
  assert.equal(visto.auditorias.length, 1);
  // O actor da linha de auditoria é o dono, e a acção é a do preço.
  assert.equal(visto.auditorias[0]?.[1], "owner");
  assert.equal(visto.auditorias[0]?.[2], "dono-1");
  assert.ok(visto.eventos.includes(TIPO_PRICE_CHANGED));
  // **Nenhum evento de produto**: o painel não muda o produto, muda o preço.
  assert.ok(!visto.eventos.includes(TIPO_PRODUCT_CHANGED));
});

test("KAM-099 criterio 3: o stock passa pelo ajustarStock, com auditoria e stock.adjusted", async () => {
  const { cliente, visto } = base([linha(TENANT_A, SKU)]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) =>
    alterarOferta(reg, alteracao({ precoMinor: 1_250_000n, stock: 7 })),
  );
  assert.equal(r.tipo, "ok");
  // O CAS correu (a versão é dele) e o ajuste também; o preço não mudou e não
  // há `catalog.price_changed`.
  assert.deepEqual(visto.escritas, ["preco", "stock"]);
  assert.ok(visto.eventos.includes(TIPO_STOCK_ADJUSTED));
  assert.ok(!visto.eventos.includes(TIPO_PRICE_CHANGED));
});

test("KAM-099 conflito: com a versao velha a resposta e conflito com a releitura, sem auditar", async () => {
  const { cliente, visto } = base([linha(TENANT_A, SKU, { versao: "2026-11-02T11:00:00.000009Z" })]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) => alterarOferta(reg, alteracao()));
  assert.equal(r.tipo, "conflito");
  if (r.tipo !== "conflito") return;
  assert.equal(r.valor.versao, "2026-11-02T11:00:00.000009Z");
  assert.equal(r.valor.precoMinor, 1_250_000n, "o preco nao mudou");
  assert.deepEqual(visto.escritas, []);
  assert.deepEqual(visto.auditorias, []);
  assert.deepEqual(visto.eventos, []);
});

test("KAM-099 conflito: uma escrita entre a leitura e o UPDATE perde-se para o predicado, nao para o if", async () => {
  // A versão do pedido casa a da leitura trancada; outra escrita move-a antes
  // do `UPDATE`. Só o predicado no texto da instrução apanha isto: o módulo já
  // passou pela comparação dele. Apagar o `AND atualizado_at = $5` do
  // `SQL_ALTERAR_OFERTA` põe este caso vermelho.
  const { cliente, visto } = base([linha(TENANT_A, SKU)], (l) => {
    l.versao = seguinte(l.versao);
  });
  const r = await comRegisto(deps(cliente), ctx(), (reg) => alterarOferta(reg, alteracao()));
  assert.equal(r.tipo, "conflito");
  assert.deepEqual(visto.auditorias, []);
  assert.deepEqual(visto.eventos, []);
});

test("KAM-099 conflito: o predicado do CAS esta no texto da instrucao", () => {
  assert.match(SQL_ALTERAR_OFERTA, /AND atualizado_at = \$5::timestamptz/);
  assert.match(SQL_ALTERAR_OFERTA, /atualizado_at = clock_timestamp\(\)/);
});

test("KAM-099: repetir o mesmo pedido com a versao nova nao grava, nao audita e nao emite", async () => {
  const { cliente, visto } = base([linha(TENANT_A, SKU)]);
  const primeira = await comRegisto(deps(cliente), ctx(), (reg) => alterarOferta(reg, alteracao()));
  assert.equal(primeira.tipo, "ok");
  if (primeira.tipo !== "ok") return;
  const escritas = visto.escritas.length;
  const auditorias = visto.auditorias.length;
  const segunda = await comRegisto(deps(cliente), ctx(), (reg) =>
    alterarOferta(reg, alteracao({ versao: primeira.valor.versao })),
  );
  assert.equal(segunda.tipo, "ok");
  assert.equal(visto.escritas.length, escritas);
  assert.equal(visto.auditorias.length, auditorias);
});

test("KAM-099: sem nada a mudar e com a versao velha, a resposta e conflito e nao ok", async () => {
  const { cliente } = base([linha(TENANT_A, SKU, { versao: "2026-11-02T11:00:00.000009Z" })]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) =>
    alterarOferta(reg, alteracao({ precoMinor: 1_250_000n })),
  );
  assert.equal(r.tipo, "conflito");
});

// ------------------------------------------------------------- isolamento

test("KAM-099 isolamento: o tenant A nao grava o sku de B, e a resposta e NOT_FOUND", async () => {
  const deB = linha(TENANT_B, "so-de-b");
  const { cliente, visto } = base([linha(TENANT_A, SKU), deB]);
  const r = await comRegisto(deps(cliente), ctx(TENANT_A), (reg) =>
    alterarOferta(reg, alteracao({ sku: "so-de-b" })),
  );
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  assert.equal(deB.preco_minor, "1250000");
  assert.deepEqual(visto.escritas, []);
});

test("KAM-099: uma oferta arquivada nao se edita, e responde NOT_FOUND", async () => {
  const { cliente, visto } = base([linha(TENANT_A, SKU, { estado: "arquivado" })]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) => alterarOferta(reg, alteracao()));
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  assert.deepEqual(visto.escritas, []);
});

// ------------------------------------------------------------- a validação

test("KAM-099 criterio 5: precos e stocks invalidos sao VALIDATION_ERROR sem ir a base", async () => {
  const invalidas: Partial<AlteracaoDeOferta>[] = [
    { precoMinor: -1n },
    { precoTipo: "sob_consulta", precoMinor: 100n },
    { precoTipo: "fixo", precoMinor: null },
    { precoTipo: "outro" as AlteracaoDeOferta["precoTipo"] },
    { stock: -1 },
    { stock: 1.5 },
    { versao: "ontem" },
    { versao: "2026-11-02T11:00:00.000Z" },
    { sku: "  " },
  ];
  for (const extra of invalidas) {
    const { cliente, visto } = base([linha(TENANT_A, SKU)]);
    const r = await comRegisto(deps(cliente), ctx(), (reg) => alterarOferta(reg, alteracao(extra)));
    assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" }, JSON.stringify(extra, (_k, v) => (typeof v === "bigint" ? `${v}n` : v)));
    assert.deepEqual(visto.escritas, []);
  }
});

test("KAM-099: sob consulta grava-se sem preco", async () => {
  const { cliente } = base([linha(TENANT_A, SKU)]);
  const r = await comRegisto(deps(cliente), ctx(), (reg) =>
    alterarOferta(reg, alteracao({ precoTipo: "sob_consulta", precoMinor: null })),
  );
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.precoTipo, "sob_consulta");
  assert.equal(r.valor.precoMinor, null);
});

// ------------------------------------------------------- critério 4: o *fact*

test("KAM-099 criterio 4: o preco gravado no painel e o que o getOfferView da a seguir", async () => {
  const { cliente } = base([linha(TENANT_A, SKU)]);
  const antes = await comRegisto(deps(cliente), ctx(), (reg) => getOfferView(reg, SKU, new Date("2026-11-10T09:00:00Z")));
  assert.equal(antes.tipo === "ok" ? antes.valor.precoDisplay?.replace(/\s/g, " ") : null, "12 500 Kz");
  await comRegisto(deps(cliente), ctx(), (reg) => alterarOferta(reg, alteracao({ precoMinor: 1_500_000n })));
  const depois = await comRegisto(deps(cliente), ctx(), (reg) => getOfferView(reg, SKU, new Date("2026-11-10T09:00:00Z")));
  assert.equal(depois.tipo === "ok" ? depois.valor.precoDisplay?.replace(/\s/g, " ") : null, "15 000 Kz");
});
