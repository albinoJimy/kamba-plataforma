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
 * **Quatro destes testes são canários de uma revisão adversarial**, e nenhum
 * deles existiria sem ela: a primeira versão da barreira tinha uma regra só —
 * «o SQL contém `merchant_id = $1`» — e ela partiu-a por execução em quatro
 * sítios. Os quatro estão marcados, e cada um cobre um defeito **medido**, não
 * imaginado: o predicado no `SET`, o `INSERT` legítimo recusado (e o contorno
 * por comentário), a perna de fora de um `UNION`, e o predicado dentro de um
 * literal.
 *
 * O cliente de ensaio regista as consultas por ordem e os parâmetros que lhe
 * chegaram, o que torna «o valor injectado é o `$1`» uma asserção e não uma
 * leitura do código — e torna «a consulta recusada não foi executada» uma
 * asserção também, que é a propriedade que faz disto uma barreira.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { ClienteSql } from "../src/port/index.ts";
import {
  CONTADORES,
  COLUNA_DO_FILTRO,
  FiltroEmFaltaError,
  IdentificadorInvalidoError,
  MerchantEmFaltaError,
  SQL_MERCHANT_DO_TENANT,
  TenantDesconhecidoError,
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

function repo(respostas?: readonly Readonly<Record<string, unknown>>[][]) {
  const { cliente, vistas } = clienteDeEnsaio(respostas);
  return { repo: repoBase(cliente, TENANT_A, MERCHANT_A), vistas };
}

// ------------------------------------------------------- o caminho legítimo

test("uma consulta com o predicado no WHERE passa, com alias e aspas", async () => {
  const aceitos = [
    "SELECT 1 FROM product WHERE merchant_id = $1",
    "SELECT 1 FROM product p WHERE p.merchant_id=$1",
    'SELECT 1 FROM product WHERE "merchant_id"   =    $1',
    "SELECT 1 FROM product WHERE deleted_at IS NULL AND merchant_id = $1",
    "UPDATE product SET nome = $2 WHERE merchant_id = $1 RETURNING id",
    "DELETE FROM product WHERE merchant_id = $1 AND sku = $2",
  ];
  for (const sql of aceitos) {
    const { repo: r, vistas } = repo();
    await r.noMerchant(sql, ["x"]);
    assert.equal(vistas.length, 1, sql);
    assert.equal(vistas[0]?.parametros[0], MERCHANT_A, sql);
  }
});

test("o valor injectado e o $1 e os parametros de quem chama comecam no $2", async () => {
  const { repo: r, vistas } = repo();
  await r.noMerchant(
    "SELECT 1 FROM product WHERE merchant_id = $1 AND sku = $2",
    ["sku-1"],
  );
  assert.deepEqual(vistas[0]?.parametros, [MERCHANT_A, "sku-1"]);

  await r.noTenant(
    "SELECT 1 FROM platform.offer_terms WHERE tenant_id = $1 AND sku = $2",
    ["sku-1"],
  );
  assert.deepEqual(vistas[1]?.parametros, [TENANT_A, "sku-1"]);
});

// ---------------------------------------------------------- as recusas base

test("uma consulta sem o predicado nao chega a base", async () => {
  const { repo: r, vistas } = repo();
  await assert.rejects(
    () => r.noMerchant("SELECT id, sku FROM product"),
    FiltroEmFaltaError,
  );
  // **A asserção que importa**: a consulta recusada não foi executada. Uma
  // barreira que recusa *depois* de a base responder não é uma barreira.
  assert.equal(vistas.length, 0);
});

test("sem WHERE nenhum, recusa — e di-lo", async () => {
  const { repo: r } = repo();
  await assert.rejects(
    () => r.noMerchant("SELECT * FROM product"),
    (e: unknown) => e instanceof FiltroEmFaltaError && /WHERE nenhum/.test(String(e)),
  );
});

test("o predicado com outro placeholder nao conta como filtro", async () => {
  // `$11` começa por `$1` e **não** é o `$1`. Sem a guarda de dígito, este
  // caso passava e a consulta corria com o `merchant_id` no lugar errado.
  const { repo: r } = repo();
  await assert.rejects(
    () => r.noMerchant("SELECT 1 FROM product WHERE merchant_id = $11"),
    FiltroEmFaltaError,
  );
  await assert.rejects(
    () => r.noMerchant("SELECT 1 FROM product WHERE merchant_id = $2", ["x"]),
    FiltroEmFaltaError,
  );
});

test("uma coluna que acaba em merchant_id nao satisfaz o filtro", async () => {
  // `outro_merchant_id` contém `merchant_id`. Sem a fronteira de palavra, uma
  // consulta filtrada pela coluna errada passava por filtrada.
  const { repo: r } = repo();
  await assert.rejects(
    () => r.noMerchant("SELECT 1 FROM product WHERE outro_merchant_id = $1"),
    FiltroEmFaltaError,
  );
});

test("o filtro do platform e o tenant_id, e o do Registo nao serve", async () => {
  // Os dois métodos existem separados exactamente para isto: uma consulta ao
  // `platform` filtrada por `merchant_id` passava num método único com
  // parâmetro, e punha a RLS a ser a primeira barreira em vez da segunda.
  assert.equal(COLUNA_DO_FILTRO.tenant, "tenant_id");
  assert.equal(COLUNA_DO_FILTRO.merchant, "merchant_id");

  const { repo: r } = repo();
  await assert.rejects(
    () => r.noTenant("SELECT 1 FROM product WHERE merchant_id = $1"),
    FiltroEmFaltaError,
  );
});

// --------------------------------- canários da revisão adversarial (medidos)

test("CANARIO: o predicado num SET nao e um filtro, e o UPDATE nao corre", async () => {
  // **Medido na primeira versão:** `UPDATE product SET merchant_id = $1 WHERE
  // sku = $2` executou. A regex encontrava o predicado — na cláusula `SET` — e
  // dava a consulta por filtrada: todas as linhas com aquele SKU, de qualquer
  // merchant, passavam a ser do tenant que chamou. **Escrita cruzada**, no lado
  // onde não há RLS atrás.
  const { repo: r, vistas } = repo();
  for (const sql of [
    "UPDATE product SET merchant_id = $1 WHERE sku = $2",
    "UPDATE product SET merchant_id = $1",
    "UPDATE product SET nome = $2, merchant_id = $1 WHERE merchant_id = $1",
  ]) {
    await assert.rejects(
      () => r.noMerchant(sql, ["x"]),
      (e: unknown) => e instanceof FiltroEmFaltaError && /SET/.test(String(e)),
      sql,
    );
  }
  assert.equal(vistas.length, 0);
});

test("CANARIO: um INSERT nao se verifica, constroi-se", async () => {
  // **Medido:** o `INSERT` legítimo era recusado **e** a saída de menor
  // resistência era acrescentar `-- tenant_id = $1` ao fim, o que esvaziava a
  // barreira e ensinava o contorno. Agora um `INSERT` é recusado com a
  // instrução de usar o construtor — e o comentário já não o salva.
  const { repo: r, vistas } = repo();
  await assert.rejects(
    () =>
      r.noTenant(
        "INSERT INTO platform.offer_terms (tenant_id, sku) VALUES ($1, $2)",
        ["sku"],
      ),
    (e: unknown) =>
      e instanceof FiltroEmFaltaError && /inserirNoTenant/.test(String(e)),
  );
  await assert.rejects(
    () =>
      r.noTenant(
        "INSERT INTO platform.offer_terms (tenant_id, sku) VALUES ($1, $2) " +
          "-- tenant_id = $1",
        ["sku"],
      ),
    FiltroEmFaltaError,
  );
  assert.equal(vistas.length, 0);
});

test("CANARIO: a perna de fora de um UNION levava o catalogo inteiro", async () => {
  // **Medido:** `SELECT * FROM product WHERE merchant_id = $1 UNION ALL SELECT
  // * FROM product` executou — a segunda perna sem filtro, com a primeira
  // certa, que é o pior caso porque o resultado parece plausível. Recusam-se as
  // três operações de conjunto: o filtro tem de estar em cada perna e nenhuma
  // verificação por texto o consegue afirmar.
  const { repo: r, vistas } = repo();
  for (const sql of [
    "SELECT * FROM product WHERE merchant_id = $1 UNION ALL SELECT * FROM product",
    "SELECT a FROM product WHERE merchant_id = $1 INTERSECT SELECT a FROM product",
    "SELECT a FROM product WHERE merchant_id = $1 EXCEPT SELECT a FROM product",
  ]) {
    await assert.rejects(
      () => r.noMerchant(sql),
      (e: unknown) => e instanceof FiltroEmFaltaError && /conjunto/.test(String(e)),
      sql,
    );
  }
  assert.equal(vistas.length, 0);
});

test("CANARIO: o predicado dentro de um literal ou comentario nao conta", async () => {
  // **Medido:** `SELECT * FROM product WHERE nome = 'merchant_id = $1'`
  // passava. Era caso construído e não de esquecimento, mas uma barreira que
  // conta texto dentro de literais conta a coisa errada.
  const { repo: r, vistas } = repo();
  for (const sql of [
    "SELECT * FROM product WHERE nome = 'merchant_id = $1'",
    "SELECT * FROM product WHERE nome = $2 /* merchant_id = $1 */",
    "SELECT * FROM product WHERE nome = $2 -- merchant_id = $1",
  ]) {
    await assert.rejects(() => r.noMerchant(sql, ["x"]), FiltroEmFaltaError, sql);
  }
  assert.equal(vistas.length, 0);
});

// ---------------------------------------------------------------- o inserir

test("o inserir escreve a coluna do filtro, e e o $1", async () => {
  const { repo: r, vistas } = repo();
  await r.inserirNoTenant({
    tabela: "platform.offer_terms",
    valores: { sku: "sku-1", preco_minor: 5000 },
  });
  assert.equal(
    vistas[0]?.sql,
    "INSERT INTO platform.offer_terms (tenant_id, sku, preco_minor) " +
      "VALUES ($1, $2, $3)",
  );
  assert.deepEqual(vistas[0]?.parametros, [TENANT_A, "sku-1", 5000]);
});

test("o inserir aceita o sufixo do ON CONFLICT do §6.3", async () => {
  const { repo: r, vistas } = repo();
  await r.inserirNoTenant({
    tabela: "platform.order_intents",
    valores: { intent_key: "k", draft_hash: "h" },
    sufixo: "ON CONFLICT (tenant_id, intent_key) DO NOTHING RETURNING *",
  });
  assert.match(String(vistas[0]?.sql), /ON CONFLICT \(tenant_id, intent_key\)/);
});

test("o inserir recusa dar o filtro nos valores", async () => {
  // Dar o `merchant_id` nos valores era a mesma porta que o `merchant_id` do
  // chamador: a coluna continua a ser escrita por esta casa.
  const { repo: r } = repo();
  await assert.rejects(
    () =>
      r.inserirNoMerchant({
        tabela: "product",
        valores: { merchant_id: "merch_B", sku: "x" },
      }),
    IdentificadorInvalidoError,
  );
});

test("o inserir recusa um identificador que nao e um identificador", async () => {
  const { repo: r } = repo();
  for (const tabela of ["product; DROP TABLE x", 'pro"duct', "product WHERE 1=1"]) {
    await assert.rejects(
      () => r.inserirNoMerchant({ tabela, valores: { sku: "x" } }),
      IdentificadorInvalidoError,
      tabela,
    );
  }
  await assert.rejects(
    () =>
      r.inserirNoMerchant({ tabela: "product", valores: { "sku; x": "y" } }),
    IdentificadorInvalidoError,
  );
});

// -------------------------------------------------- contador e construção

test("uma recusa conta no contador: a barreira e observavel", async () => {
  const antes = CONTADORES.filtroEmFalta.get("merchant") ?? 0;
  const { repo: r } = repo();
  await assert.rejects(() => r.noMerchant("SELECT 1"), FiltroEmFaltaError);
  assert.equal(CONTADORES.filtroEmFalta.get("merchant"), antes + 1);
});

test("o repo-base recusa nascer sem tenant canonico ou sem merchant", () => {
  const { cliente } = clienteDeEnsaio();
  assert.throws(() => repoBase(cliente, "nao-e-uuid", MERCHANT_A), TenantInvalidoError);
  assert.throws(() => repoBase(cliente, TENANT_A, ""), MerchantEmFaltaError);
});

// --------------------------------------------------- resolução do merchant

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
  // a `NULL`; sem este erro, o repo-base nascia com `merchantId` vazio e a
  // primeira consulta devolvia o catálogo de todas as lojas.
  for (const linha of [
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

test("um tenant inexistente e um erro distinto do nao provisionado", async () => {
  // O critério 1 nomeia «tenant inexistente» à parte: é um `ctx` montado contra
  // um id que ninguém criou, e não um provisionamento que falta. Com um erro
  // só, quem opera o *script* da Fase 0 não sabia qual dos dois tinha.
  const { cliente } = clienteDeEnsaio([[]]);
  await assert.rejects(
    () => idsDoRegisto(cliente, TENANT_B),
    TenantDesconhecidoError,
  );
});

test("o canal de vendas em falta nao e erro: e a segunda barreira, nao a primeira", async () => {
  const { cliente } = clienteDeEnsaio([
    [{ medusa_merchant_id: MERCHANT_A, medusa_sales_channel_id: null }],
  ]);
  const ids = await idsDoRegisto(cliente, TENANT_A);
  assert.equal(ids.merchantId, MERCHANT_A);
  assert.equal(ids.salesChannelId, null);
});
