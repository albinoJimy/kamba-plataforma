/**
 * A idempotência do `PATCH /painel/produtos/:id` contra a base (KAM-240): a
 * `IdempotenciaNaBase` sobre a `platform.painel_idempotencia`, como `kamba_app`.
 *
 * ```text
 * dois processos  dez pedidos com a mesma chave, de dois pools, correm o PATCH
 *                 uma vez; o controlo, em memoria, corre-o duas
 * reinicio        um pool novo devolve a resposta guardada sem correr nada
 * reutilizada     a mesma chave com outro conteudo da reutilizada; noutro
 *                 tenant e outra chave
 * sem guardar     um 5xx e uma sessao revogada nao ficam; o pedido que esperava
 *                 pela tranca corre ele, depois; o kamba_app nao apaga
 * vencida         uma chave vencida por purgar reaproveita-se
 * ligacao         a ligacao de quem tem a tranca cai, e o outro corre; o PATCH
 *                 do primeiro nao e cancelado (o que trava a segunda gravacao
 *                 e a versao no COM)
 * ```
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { BASE_DESCARTAVEL } from "./apoio.ts";
import type { PoolDaInscricao } from "../src/inscricao/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { Idempotencia, type Guardada } from "../../../services/onboarding-web/src/painel/idempotencia.ts";
import { IdempotenciaNaBase } from "../../../services/onboarding-web/src/painel/idempotencia_sql.ts";

function exigir(nome: string): string {
  const valor = process.env[nome] ?? "";
  if (valor === "") throw new Error(`a variável de ambiente ${nome} não está definida`);
  return valor;
}

function configuracao(papel: "app" | "admin", nome = "app"): pg.ClientConfig {
  const base = exigir("KAMBA_DB_NAME");
  if (base !== BASE_DESCARTAVEL) throw new Error(`KAMBA_DB_NAME não é ${BASE_DESCARTAVEL}`);
  return {
    host: process.env.KAMBA_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.KAMBA_DB_PORT ?? "5432"),
    database: base,
    user: papel === "app" ? "kamba_app" : exigir("POSTGRES_USER"),
    password: exigir(papel === "app" ? "KAMBA_SECRET_DB_APP_PASSWORD" : "POSTGRES_PASSWORD"),
    application_name: `kamba-idempotencia-teste:${nome}`,
  };
}

let admin: pg.Client;
const pools: pg.Pool[] = [];
const tenants: string[] = [];

/** Um processo do `onboarding-web`: a idempotência sobre um *pool* seu. */
function processo(nome = "app"): IdempotenciaNaBase {
  const pool = new pg.Pool({ ...configuracao("app", nome), max: 4 });
  // A ligação que o ensaio da morte termina emite `error` no cliente emprestado:
  // sem ouvinte, era uma excepção por tratar (a mesma regra do `poolDe`).
  pool.on("error", () => undefined);
  pool.on("connect", (cliente) => cliente.on("error", () => undefined));
  pools.push(pool);
  return new IdempotenciaNaBase(pool as unknown as PoolDaInscricao);
}

function tenant(): string {
  const t = randomUUID();
  tenants.push(t);
  return t;
}

function chave(): string {
  return `kam-240-${randomUUID()}`;
}

const esperar = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/** Um PATCH falso que conta as gravações e demora, para que os pedidos se cruzem. */
function patch(resposta: Guardada, demora = 150): { fazer: () => Promise<Guardada>; vezes: () => number } {
  let n = 0;
  return {
    fazer: async () => {
      n += 1;
      await esperar(demora);
      return resposta;
    },
    vezes: () => n,
  };
}

const GRAVADO: Guardada = { estado: 200, corpo: { versao: "7", oferta: { sku: "SKU-1", precoMinor: "150000" } } };

async function linhas(tenantId: string): Promise<number> {
  const r = await admin.query("SELECT 1 FROM platform.painel_idempotencia WHERE tenant_id = $1", [tenantId]);
  return r.rowCount ?? 0;
}

before(async () => {
  admin = new pg.Client(configuracao("admin", "admin"));
  await admin.connect();
});

after(async () => {
  // O administrador é o dono da tabela: o `kamba_app` não apaga chaves.
  await admin.query("DELETE FROM platform.painel_idempotencia WHERE tenant_id = ANY ($1::uuid[])", [tenants]);
  for (const pool of pools) await pool.end().catch(() => undefined);
  await admin.end();
});

describe("a idempotência do painel na base (KAM-240)", () => {
  it("KAM-240: dez pedidos com a mesma chave de dois processos gravam uma vez; em memória, duas", async (t) => {
    const [a, b] = [processo(), processo()];
    const t = tenant();
    const k = chave();
    const p = patch(GRAVADO);
    const desfechos = await Promise.all(
      Array.from({ length: 10 }, (_, i) => (i % 2 === 0 ? a : b).uma(t, k, "SKU-1\u0000{}", p.fazer)),
    );
    assert.equal(p.vezes(), 1, "o PATCH corre uma vez");
    assert.equal(desfechos.filter((d) => d.tipo === "nova").length, 1);
    for (const d of desfechos) {
      assert.notEqual(d.tipo, "reutilizada");
      if (d.tipo !== "reutilizada") assert.deepEqual(d.resposta, { estado: 200, corpo: GRAVADO.corpo });
    }
    assert.equal(await linhas(t), 1);

    // O controlo: a mesma corrida sobre dois mapas em memória, um por processo.
    const [ma, mb] = [new Idempotencia(), new Idempotencia()];
    const q = patch(GRAVADO);
    await Promise.all(Array.from({ length: 10 }, (_, i) => (i % 2 === 0 ? ma : mb).uma(t, k, "SKU-1\u0000{}", q.fazer)));
    assert.equal(q.vezes(), 2, "em memória, cada processo grava a sua");
    t.diagnostic(`[KAM-240] dois processos: na base ${p.vezes()} gravacao(oes), em memoria ${q.vezes()}`);
  });

  it("KAM-240: a repetição depois de um reinício devolve a resposta guardada sem correr nada", async () => {
    const t = tenant();
    const k = chave();
    const p = patch(GRAVADO, 0);
    assert.equal((await processo().uma(t, k, "SKU-1\u0000{}", p.fazer)).tipo, "nova");
    const depois = await processo().uma(t, k, "SKU-1\u0000{}", p.fazer);
    assert.equal(p.vezes(), 1);
    assert.deepEqual(depois, { tipo: "repetida", resposta: { estado: 200, corpo: GRAVADO.corpo } });
    // O corpo volta com as chaves na ordem em que saiu (`json`, e não `jsonb`).
    if (depois.tipo === "repetida") {
      assert.deepEqual(Object.keys(depois.resposta.corpo as object), ["versao", "oferta"]);
    }
  });

  it("KAM-240: a mesma chave com outro conteúdo dá reutilizada, e noutro tenant é outra chave", async () => {
    const [ta, tb] = [tenant(), tenant()];
    const k = chave();
    const p = patch(GRAVADO, 0);
    const a = processo();
    assert.equal((await a.uma(ta, k, "SKU-1\u0000{\"precoMinor\":1}", p.fazer)).tipo, "nova");
    assert.deepEqual(await processo().uma(ta, k, "SKU-1\u0000{\"precoMinor\":2}", p.fazer), { tipo: "reutilizada" });
    assert.equal(p.vezes(), 1);
    // B com a mesma cadeia corre o seu, e a resposta de A nunca lhe chega.
    const outro = patch({ estado: 409, corpo: { erro: "conflito" } }, 0);
    assert.deepEqual(await a.uma(tb, k, "SKU-1\u0000{\"precoMinor\":1}", outro.fazer), {
      tipo: "nova",
      resposta: { estado: 409, corpo: { erro: "conflito" } },
    });
    assert.equal(outro.vezes(), 1);
    // E o kamba_app com o contexto de B não vê a linha de A.
    const pool = new pg.Pool({ ...configuracao("app"), max: 1 });
    pools.push(pool);
    const cliente = await pool.connect();
    try {
      const vistas = await comTenant(cliente, tb, async (tx) =>
        (await tx.query("SELECT tenant_id FROM platform.painel_idempotencia WHERE chave = $1", [k])) as pg.QueryResult,
      );
      assert.deepEqual(vistas.rows.map((l) => l["tenant_id"]), [tb]);
    } finally {
      cliente.release();
    }
  });

  it("KAM-240: um 5xx e uma sessão revogada não ficam, o pedido que esperava corre ele, e o kamba_app não apaga", async () => {
    const t = tenant();
    const k = chave();
    const a = processo();
    // O segundo só arranca quando o primeiro já tem a tranca (está dentro do
    // PATCH), e o PATCH dele só pode correr depois de o primeiro acabar.
    let dentro!: () => void;
    const entrou = new Promise<void>((r) => (dentro = r));
    let fimDoPrimeiro = 0;
    let inicioDoSegundo = 0;
    const primeiro = a.uma(t, k, "x", async () => {
      dentro();
      await esperar(300);
      fimDoPrimeiro = Date.now();
      return { estado: 503, corpo: { erro: "indisponivel" } };
    });
    await entrou;
    const segundo = await processo().uma(t, k, "x", async () => {
      inicioDoSegundo = Date.now();
      return GRAVADO;
    });
    const p1 = await primeiro;
    assert.equal(p1.tipo === "nova" && p1.resposta.estado, 503);
    assert.equal(segundo.tipo, "nova", "o 503 não ficou, e o segundo correu o seu");
    assert.ok(inicioDoSegundo >= fimDoPrimeiro, "o segundo esperou pela tranca até o primeiro desfazer");

    const k2 = chave();
    const revogada = patch({ estado: 401, corpo: { erro: "sessao" }, guardar: false }, 0);
    await a.uma(t, k2, "x", revogada.fazer);
    await a.uma(t, k2, "x", revogada.fazer);
    assert.equal(revogada.vezes(), 2, "a sessão revogada não fica");

    const pool = new pg.Pool({ ...configuracao("app"), max: 1 });
    pools.push(pool);
    const cliente = await pool.connect();
    try {
      await assert.rejects(
        comTenant(cliente, t, (tx) => tx.query("DELETE FROM platform.painel_idempotencia WHERE tenant_id = $1", [t])),
        (e: { code?: string }) => e.code === "42501",
      );
    } finally {
      cliente.release();
    }
  });

  it("KAM-240: uma chave vencida e por purgar reaproveita-se com outro conteúdo", async () => {
    const t = tenant();
    const k = chave();
    const a = processo();
    await a.uma(t, k, "antes", patch(GRAVADO, 0).fazer);
    await admin.query(
      "UPDATE platform.painel_idempotencia SET criado_at = now() - interval '2 days', expira_at = now() - interval '1 day' WHERE tenant_id = $1",
      [t],
    );
    const outro = patch({ estado: 404, corpo: { erro: "nao_encontrado" } }, 0);
    assert.equal((await a.uma(t, k, "depois", outro.fazer)).tipo, "nova");
    assert.deepEqual(await processo().uma(t, k, "depois", outro.fazer), {
      tipo: "repetida",
      resposta: { estado: 404, corpo: { erro: "nao_encontrado" } },
    });
    assert.equal(outro.vezes(), 1);
  });

  it("KAM-240: a ligação de quem tem a tranca cai a meio, e o outro corre; o PATCH do primeiro não é cancelado", async () => {
    const t = tenant();
    const k = chave();
    const morre = processo("morre");
    const fica = processo("fica");
    let dentro!: () => void;
    const entrou = new Promise<void>((r) => (dentro = r));
    let primeiroAcabou = false;
    const primeiro = morre.uma(t, k, "x", async () => {
      dentro();
      await esperar(2_000);
      primeiroAcabou = true;
      return GRAVADO;
    });
    await entrou;
    const p = patch(GRAVADO, 0);
    const segundo = fica.uma(t, k, "x", p.fazer);
    await esperar(100);
    assert.equal(p.vezes(), 0, "o segundo espera pela tranca");
    await admin.query(
      "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'kamba-idempotencia-teste:morre'",
    );
    assert.equal((await segundo).tipo, "nova");
    assert.equal(p.vezes(), 1);
    await assert.rejects(primeiro);
    // O limite, medido: o PATCH do primeiro correu até ao fim depois de a tranca
    // cair. No painel quem trava a segunda gravação é a versão do pedido no COM.
    assert.equal(primeiroAcabou, true);
  });
});
