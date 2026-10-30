/**
 * O repo-base: a injecção de `tenant_id`/`merchant_id` (KAM-042, critério 4).
 *
 * **Esta é a barreira que o ticket entrega.** No Registo da opção B não há RLS
 * atrás dela — o Medusa não é multi-tenant nativo e os seus *links* não têm FK
 * (§3.3, CONFIRMADO no KAM-041) —, pelo que uma consulta sem `merchant_id` não
 * devolve «zero linhas», devolve **as linhas de todos os tenants**. É a
 * diferença entre falhar fechado e falhar aberto, e é por isso que este
 * ficheiro afirma o que afirma.
 *
 * O cliente de ensaio regista as consultas por ordem e os parâmetros que lhe
 * chegaram, o que torna «o valor injectado é o `$1`» uma asserção e não uma
 * leitura do código.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { ClienteSql } from "../src/port/index.ts";
import {
  CONTADORES,
  COLUNA_DO_FILTRO,
  FiltroEmFaltaError,
  MerchantEmFaltaError,
  SQL_MERCHANT_DO_TENANT,
  TenantInvalidoError,
  idsDoRegisto,
  repoBase,
} from "../src/repo-base/index.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const MERCHANT_A = "merch_A";

interface Registada {
  readonly sql: string;
  readonly parametros: readonly unknown[];
}

function clienteDeEnsaio(
  respostas: readonly Readonly<Record<string, unknown>>[][] = [],
): { cliente: ClienteSql; vistas: Registada[] } {
  const vistas: Registada[] = [];
  let i = 0;
  return {
    vistas,
    cliente: {
      async query(sql, parametros = []) {
        vistas.push({ sql, parametros });
        return { rows: respostas[i++] ?? [] };
      },
    },
  };
}

test("uma consulta ao Registo sem merchant_id = $1 nao chega a base", async () => {
  const { cliente, vistas } = clienteDeEnsaio();
  const repo = repoBase(cliente, TENANT_A, MERCHANT_A);

  await assert.rejects(
    () => repo.noMerchant("SELECT id, sku FROM product"),
    FiltroEmFaltaError,
  );
  // **A asserção que importa**: a consulta recusada não foi executada. Uma
  // barreira que recusa *depois* de a base responder não é uma barreira.
  assert.equal(vistas.length, 0);
});

test("o predicado aceita-se com alias, aspas e espacamento, e so com $1", async () => {
  const aceitos = [
    "SELECT 1 FROM product WHERE merchant_id = $1",
    "SELECT 1 FROM product p WHERE p.merchant_id=$1",
    'SELECT 1 FROM product WHERE "merchant_id"   =    $1',
    "SELECT 1 FROM product WHERE deleted_at IS NULL AND merchant_id = $1",
  ];
  for (const sql of aceitos) {
    const { cliente, vistas } = clienteDeEnsaio();
    await repoBase(cliente, TENANT_A, MERCHANT_A).noMerchant(sql);
    assert.equal(vistas.length, 1, sql);
    assert.deepEqual(vistas[0]?.parametros, [MERCHANT_A], sql);
  }
});

test("o predicado com outro placeholder nao conta como filtro", async () => {
  // `$11` começa por `$1` e **não** é o `$1`. Sem a guarda de dígito, este
  // caso passava e a consulta corria com o `merchant_id` no lugar errado.
  const { cliente } = clienteDeEnsaio();
  const repo = repoBase(cliente, TENANT_A, MERCHANT_A);
  await assert.rejects(
    () => repo.noMerchant("SELECT 1 FROM product WHERE merchant_id = $11"),
    FiltroEmFaltaError,
  );
  await assert.rejects(
    () => repo.noMerchant("SELECT 1 FROM product WHERE merchant_id = $2", ["x"]),
    FiltroEmFaltaError,
  );
});

test("uma coluna que acaba em merchant_id nao satisfaz o filtro", async () => {
  // `outro_merchant_id` contém `merchant_id`. Se a fronteira de palavra não
  // existisse, uma consulta filtrada pela coluna errada passava por filtrada.
  const { cliente } = clienteDeEnsaio();
  await assert.rejects(
    () =>
      repoBase(cliente, TENANT_A, MERCHANT_A).noMerchant(
        "SELECT 1 FROM product WHERE outro_merchant_id = $1",
      ),
    FiltroEmFaltaError,
  );
});

test("o valor injectado e o $1 e os parametros de quem chama comecam no $2", async () => {
  const { cliente, vistas } = clienteDeEnsaio();
  const repo = repoBase(cliente, TENANT_A, MERCHANT_A);

  await repo.noMerchant(
    "SELECT 1 FROM product WHERE merchant_id = $1 AND sku = $2",
    ["sku-1"],
  );
  assert.deepEqual(vistas[0]?.parametros, [MERCHANT_A, "sku-1"]);

  await repo.noTenant(
    "SELECT 1 FROM platform.offer_terms WHERE tenant_id = $1 AND sku = $2",
    ["sku-1"],
  );
  assert.deepEqual(vistas[1]?.parametros, [TENANT_A, "sku-1"]);
});

test("o filtro do platform e o tenant_id, e o do Registo nao serve", async () => {
  // Os dois métodos existem separados exactamente para isto: uma consulta ao
  // `platform` filtrada por `merchant_id` passava num método único com
  // parâmetro, e punha a RLS a ser a primeira barreira em vez da segunda.
  assert.equal(COLUNA_DO_FILTRO.tenant, "tenant_id");
  assert.equal(COLUNA_DO_FILTRO.merchant, "merchant_id");

  const { cliente } = clienteDeEnsaio();
  const repo = repoBase(cliente, TENANT_A, MERCHANT_A);
  await assert.rejects(
    () => repo.noTenant("SELECT 1 FROM product WHERE merchant_id = $1"),
    FiltroEmFaltaError,
  );
});

test("uma recusa conta no contador: a barreira e observavel", async () => {
  const antes = CONTADORES.filtroEmFalta.get("merchant") ?? 0;
  const { cliente } = clienteDeEnsaio();
  await assert.rejects(
    () => repoBase(cliente, TENANT_A, MERCHANT_A).noMerchant("SELECT 1"),
    FiltroEmFaltaError,
  );
  assert.equal(CONTADORES.filtroEmFalta.get("merchant"), antes + 1);
});

test("o repo-base recusa nascer sem tenant canonico ou sem merchant", () => {
  const { cliente } = clienteDeEnsaio();
  assert.throws(() => repoBase(cliente, "nao-e-uuid", MERCHANT_A), TenantInvalidoError);
  assert.throws(() => repoBase(cliente, TENANT_A, ""), MerchantEmFaltaError);
});

test("o merchant_id le-se de platform.tenants, nunca de um argumento", async () => {
  const { cliente, vistas } = clienteDeEnsaio([
    [{ medusa_merchant_id: MERCHANT_A, medusa_sales_channel_id: "sc_A" }],
  ]);
  const ids = await idsDoRegisto(cliente, TENANT_A);
  assert.equal(ids.merchantId, MERCHANT_A);
  assert.equal(ids.salesChannelId, "sc_A");
  assert.equal(vistas[0]?.sql, SQL_MERCHANT_DO_TENANT);
  assert.deepEqual(vistas[0]?.parametros, [TENANT_A]);
});

test("um tenant sem medusa_merchant_id falha fechado", async () => {
  // **O caso que decide o critério 5.** Um tenant por provisionar tem a coluna
  // a `NULL`; sem este erro, o repo-base nascia com `merchantId: "null"` ou
  // vazio e a primeira consulta devolvia o catálogo de todas as lojas.
  for (const linha of [
    [] as Readonly<Record<string, unknown>>[],
    [{ medusa_merchant_id: null, medusa_sales_channel_id: null }],
    [{ medusa_merchant_id: "", medusa_sales_channel_id: null }],
  ]) {
    const { cliente } = clienteDeEnsaio([linha]);
    await assert.rejects(
      () => idsDoRegisto(cliente, TENANT_B),
      MerchantEmFaltaError,
    );
  }
});

test("o canal de vendas em falta nao e erro: e a segunda barreira, nao a primeira", async () => {
  const { cliente } = clienteDeEnsaio([
    [{ medusa_merchant_id: MERCHANT_A, medusa_sales_channel_id: null }],
  ]);
  const ids = await idsDoRegisto(cliente, TENANT_A);
  assert.equal(ids.merchantId, MERCHANT_A);
  assert.equal(ids.salesChannelId, null);
});
