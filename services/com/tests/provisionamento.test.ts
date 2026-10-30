/**
 * O provisionamento de um tenant no Registo (KAM-042, critério 5).
 *
 * **O que isto prova:** a ordem das operações, a idempotência, e que os ids
 * só se escrevem em `platform.tenants` **depois** de existirem no Registo.
 * **O que não prova:** nada sobre o Medusa — o `RegistoAdmin` aqui é um duplo,
 * e a implementação contra a Admin API não existe (ver o cabeçalho de
 * `provisionamento.ts` e as três razões que lá estão).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { ClienteSql } from "../src/port/index.ts";
import { MerchantEmFaltaError } from "../src/repo-base/index.ts";
import {
  SQL_FIXAR_IDS,
  TenantDesconhecidoError,
  provisionarTenant,
  type RegistoAdmin,
} from "../src/adapters/medusa/provisionamento.ts";

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function adminDeEnsaio(): { admin: RegistoAdmin; passos: string[] } {
  const passos: string[] = [];
  return {
    passos,
    admin: {
      async criarMerchant(t) {
        passos.push(`merchant:${t}`);
        return "merch_1";
      },
      async criarSalesChannel(t) {
        passos.push(`canal:${t}`);
        return "sc_1";
      },
      async criarStockLocation(t) {
        passos.push(`local:${t}`);
        return "sl_1";
      },
      async ligar(m, c, l) {
        passos.push(`ligar:${m}/${c}/${l}`);
      },
    },
  };
}

/** Um cliente que responde por SQL, para que a ordem não seja posicional. */
function clientePor(
  mapa: (sql: string) => Readonly<Record<string, unknown>>[],
): { cliente: ClienteSql; vistas: string[] } {
  const vistas: string[] = [];
  return {
    vistas,
    cliente: {
      async query(sql) {
        vistas.push(sql);
        return { rows: mapa(sql) };
      },
    },
  };
}

const comTenant = (cliente: ClienteSql) =>
  async <T>(_t: string, trabalho: (c: ClienteSql) => Promise<T>) =>
    trabalho(cliente);

test("provisiona pela ordem que sobrevive a uma falha a meio", async () => {
  const { admin, passos } = adminDeEnsaio();
  const { cliente, vistas } = clientePor((sql) => {
    if (sql.startsWith("SELECT nome")) return [{ nome: "Loja da Ana" }];
    if (sql.startsWith("SELECT medusa_merchant_id")) {
      return [{ medusa_merchant_id: null, medusa_sales_channel_id: null }];
    }
    return [{ medusa_merchant_id: "merch_1", medusa_sales_channel_id: "sc_1" }];
  });

  const r = await provisionarTenant(
    { comTenant: comTenant(cliente), admin },
    TENANT,
  );

  assert.equal(r.criou, true);
  assert.equal(r.merchantId, "merch_1");
  assert.equal(r.salesChannelId, "sc_1");
  assert.equal(r.stockLocationId, "sl_1");

  // As três criações e a ligação, por esta ordem.
  assert.deepEqual(passos, [
    `merchant:${TENANT}`,
    `canal:${TENANT}`,
    `local:${TENANT}`,
    "ligar:merch_1/sc_1/sl_1",
  ]);
  // **A escrita em `platform.tenants` é a última.** Escrita antes, o repo-base
  // passava a filtrar por um `merchant_id` que ainda não existe — e uma
  // consulta assim devolve zero linhas, indistinguível de «esta loja não tem
  // produtos».
  assert.equal(vistas.at(-1), SQL_FIXAR_IDS);
});

test("um tenant ja provisionado nao toca no Registo", async () => {
  const { admin, passos } = adminDeEnsaio();
  const { cliente, vistas } = clientePor((sql) =>
    sql.startsWith("SELECT nome")
      ? [{ nome: "Loja da Ana" }]
      : [{ medusa_merchant_id: "merch_ja", medusa_sales_channel_id: "sc_ja" }],
  );

  const r = await provisionarTenant(
    { comTenant: comTenant(cliente), admin },
    TENANT,
  );
  assert.equal(r.criou, false);
  assert.equal(r.merchantId, "merch_ja");
  assert.deepEqual(passos, []);
  assert.ok(!vistas.includes(SQL_FIXAR_IDS));
});

test("um provisionamento a meio devolve-se, nao se completa em silencio", async () => {
  // `merchant_id` preenchido e canal vazio: ficou a meio. Completá-lo aqui
  // escondia a razão por que ficou.
  const { admin, passos } = adminDeEnsaio();
  const { cliente } = clientePor((sql) =>
    sql.startsWith("SELECT nome")
      ? [{ nome: "Loja da Ana" }]
      : [{ medusa_merchant_id: "merch_ja", medusa_sales_channel_id: null }],
  );
  const r = await provisionarTenant(
    { comTenant: comTenant(cliente), admin },
    TENANT,
  );
  assert.equal(r.criou, false);
  assert.equal(r.salesChannelId, "");
  assert.deepEqual(passos, []);
});

test("o UPDATE so preenche o que esta vazio, e uma corrida perdida falha", async () => {
  assert.match(SQL_FIXAR_IDS, /medusa_merchant_id IS NULL/);
  assert.match(SQL_FIXAR_IDS, /medusa_sales_channel_id IS NULL/);
  assert.match(SQL_FIXAR_IDS, /deleted_at IS NULL/);

  const { admin } = adminDeEnsaio();
  const { cliente } = clientePor((sql) => {
    if (sql.startsWith("SELECT nome")) return [{ nome: "Loja da Ana" }];
    if (sql.startsWith("SELECT medusa_merchant_id")) {
      return [{ medusa_merchant_id: null, medusa_sales_channel_id: null }];
    }
    return []; // o `RETURNING` vazio: outra corrida ganhou
  });
  await assert.rejects(
    () => provisionarTenant({ comTenant: comTenant(cliente), admin }, TENANT),
    MerchantEmFaltaError,
  );
});

test("um tenant inexistente ou apagado nao se provisiona", async () => {
  const { admin, passos } = adminDeEnsaio();
  const { cliente } = clientePor(() => []);
  await assert.rejects(
    () => provisionarTenant({ comTenant: comTenant(cliente), admin }, TENANT),
    TenantDesconhecidoError,
  );
  assert.deepEqual(passos, []);

  await assert.rejects(
    () => provisionarTenant({ comTenant: comTenant(cliente), admin }, "x"),
    TenantDesconhecidoError,
  );
});
