/**
 * O nome novo de um produto publicado repete o screening antes de se escrever
 * (KAM-202, critério 5), pelo `upsertProductDraft` da porta.
 *
 * ```text
 * publicado com nome novo        screen do nome novo, gravado ANTES do UPDATE
 * publicado com o mesmo nome     sem screen
 * rascunho com nome novo         sem screen: nao esta visivel
 * a base falha ao ler            UPSTREAM_DOWN, e nada se escreve
 * a base tira-o de publicado     o catalog.product_changed sai com `rascunho`
 * ```
 *
 * Quem decide se o nome novo continua publicado é a base (o *trigger*
 * `offer_terms_publicacao_segura`), e isso mede-se contra o PostgreSQL em
 * `db/tests/test_publicacao_segura_schema.py`. Aqui mede-se a ordem: a decisão
 * existe antes da escrita, que é o que deixa o *trigger* encontrá-la.
 *
 * As consultas reconhecem-se pela constante, como no `publicacao.test.ts`: uma
 * consulta nova que a montagem fizesse sem ser uma delas cai no `throw` do fim.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { conteudoSha256, SQL_DECISOES, SQL_GRAVAR } from "@kamba/core-ts/screening";

import { operacoesDoCom } from "../src/adapters/medusa/index.ts";
import type { ClienteSql, ComTenant, Ctx, ProductDraft } from "../src/port/index.ts";
import { SQL_ACTUALIZAR_TERMOS } from "../src/produtos/consultas.ts";
import {
  SQL_CATEGORIA_DO_TENANT,
  SQL_OFERTA_ANTES_DO_RASCUNHO,
  SUJEITO_DO_PRODUTO,
} from "../src/screening/index.ts";

const TENANT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const SKU = "camisola-01";
const NOME = "Camisola de malha";
const NOVO = "Camisola de malha grossa";
const CTX: Ctx = { tenantId: TENANT, actor: { kind: "agente", id: "grafo-dono" }, traceId: "t-202" };
const ANEL = [`v1:${Buffer.alloc(32, 7).toString("base64")}`, null] as const;

interface Opcoes {
  readonly estado?: "rascunho" | "publicado";
  /** O `estado` que o `UPDATE` devolve: o *trigger* pode tê-lo mudado. */
  readonly estadoDepois?: "rascunho" | "publicado";
  readonly falhaAoLer?: boolean;
}

function base(opcoes: Opcoes = {}) {
  const ordem: string[] = [];
  const gravadas: { tipo: string; ref: string; sha: Buffer }[] = [];
  const eventos: string[] = [];
  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql === SQL_OFERTA_ANTES_DO_RASCUNHO) {
        if (opcoes.falhaAoLer) throw new Error("ligacao caiu");
        assert.deepEqual(parametros, [TENANT, SKU]);
        ordem.push("ler");
        return { rows: [{ nome: NOME, estado: opcoes.estado ?? "publicado" }] };
      }
      if (sql === SQL_CATEGORIA_DO_TENANT) return { rows: [{ sujeito_ref: "moda" }] };
      if (sql === SQL_DECISOES) return { rows: [] };
      if (sql === SQL_GRAVAR) {
        ordem.push("decisao");
        gravadas.push({
          tipo: String(parametros[2]),
          ref: String(parametros[3]),
          sha: Buffer.from(parametros[8] as Uint8Array),
        });
        return { rows: [] };
      }
      if (sql.includes("platform.tenants")) {
        return { rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }] };
      }
      if (sql.includes("audit_append")) return { rows: [{}] };
      if (sql.includes("evt_emitir")) {
        eventos.push(JSON.stringify(parametros));
        return { rows: [{ event_id: `evt-${eventos.length}` }] };
      }
      if (sql.trim() === SQL_ACTUALIZAR_TERMOS.trim() || sql.includes(SQL_ACTUALIZAR_TERMOS.trim())) {
        ordem.push("escrever");
        // O `estado` só volta se o `RETURNING` o pedir: o duplo lê o texto da
        // instrução, para que tirar a coluna do `RETURNING` ponha o último
        // ensaio vermelho.
        const devolveEstado = /RETURNING[^;]*\bestado\b/.test(sql);
        return {
          rows: [{ sku: SKU, preco_tipo: "fixo", preco_minor: "100000", currency: "AOA", stock_modo: "indicativo",
            atualizado_at: "x",
            ...(devolveEstado ? { estado: opcoes.estadoDepois ?? opcoes.estado ?? "publicado" } : {}) }],
        };
      }
      if (sql.includes("platform.offer_terms") && /FOR UPDATE/.test(sql)) {
        return {
          rows: [{
            sku: SKU, nome: NOME, preco_tipo: "fixo", preco_minor: "100000", currency: "AOA",
            preco_atualizado_at: null, preco_valido_ate: null, stock_modo: "indicativo",
            stock_verificado_at: null, estado: opcoes.estado ?? "publicado", categoria_restrita: null,
            atualizado_at: "2026-11-20T09:00:00.000Z",
          }],
        };
      }
      throw new Error(`consulta inesperada: ${sql}`);
    },
  };
  const comTenant: ComTenant = async (tenantId, trabalho) => {
    assert.equal(tenantId, TENANT);
    return trabalho(cliente);
  };
  return { comTenant, ordem, gravadas, eventos };
}

function rascunho(nome: string): ProductDraft {
  return { sku: SKU, nome, atributos: { preco_tipo: "fixo", preco_minor: "100000" } } as unknown as ProductDraft;
}

function upsert(b: ReturnType<typeof base>, nome: string) {
  return operacoesDoCom({ comTenant: b.comTenant, anel: ANEL }).porta.upsertProductDraft(CTX, rascunho(nome));
}

test("KAM-202: o nome novo de um publicado passa pelo screen antes da escrita", async () => {
  const b = base();
  const r = await upsert(b, NOVO);
  assert.equal(r.tipo, "ok");
  assert.deepEqual(b.ordem, ["ler", "decisao", "escrever"]);
  assert.equal(b.gravadas.length, 1);
  assert.equal(b.gravadas[0]!.tipo, SUJEITO_DO_PRODUTO);
  assert.equal(b.gravadas[0]!.ref, SKU);
  // A chave é a do `assertPublishable` de um `sku`: a categoria do tenant e o nome NOVO.
  assert.deepEqual(
    b.gravadas[0]!.sha,
    Buffer.from(conteudoSha256({ categoria_declarada: "moda", textos: [NOVO] })),
  );
});

test("KAM-202: o mesmo nome num publicado nao repete o screen", async () => {
  const b = base();
  assert.equal((await upsert(b, NOME)).tipo, "ok");
  assert.deepEqual(b.gravadas, []);
});

test("KAM-202: um rascunho com nome novo nao passa pelo screen, porque nao esta visivel", async () => {
  const b = base({ estado: "rascunho" });
  assert.equal((await upsert(b, NOVO)).tipo, "ok");
  assert.deepEqual(b.gravadas, []);
  assert.deepEqual(b.ordem, ["ler", "escrever"]);
});

test("KAM-202: a base em baixo ao ler da UPSTREAM_DOWN e nada se escreve", async () => {
  const b = base({ falhaAoLer: true });
  assert.deepEqual(await upsert(b, NOVO), { tipo: "erro", erro: "UPSTREAM_DOWN" });
  assert.deepEqual(b.ordem, []);
  assert.deepEqual(b.eventos, []);
});

test("KAM-202: tirado de publicado pela base, o product_changed sai com o estado de depois", async () => {
  const b = base({ estadoDepois: "rascunho" });
  assert.equal((await upsert(b, NOVO)).tipo, "ok");
  const doProduto = b.eventos.filter((e) => e.includes("catalog.product_changed"));
  assert.equal(doProduto.length, 1);
  assert.match(doProduto[0]!, /rascunho/);
  assert.doesNotMatch(doProduto[0]!, /publicado/);
});

test("KAM-202: um rascunho que o modulo recusa nao passa pelo screen nem grava decisao", async () => {
  const b = base();
  const invalido = {
    sku: SKU,
    nome: NOVO,
    atributos: { preco_tipo: "sob_consulta", preco_minor: "100000" },
  } as unknown as ProductDraft;
  const r = await operacoesDoCom({ comTenant: b.comTenant, anel: ANEL }).porta.upsertProductDraft(CTX, invalido);
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(b.gravadas, []);
});
