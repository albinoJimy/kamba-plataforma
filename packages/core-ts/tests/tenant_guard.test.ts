/**
 * `tenant_guard`: o helper de transacção, sem base de dados (KAM-004).
 *
 * A prova contra um PostgreSQL real está no gate 6, que exercita a implementação
 * em Python; esta bateria é o espelho de `libs/py-core/tests/test_tenant_guard.py`
 * e verifica que a versão TypeScript recusa as mesmas coisas pela mesma ordem.
 *
 * Este módulo está no estrato `critico` de `ci/thresholds.yaml` (90%).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CONTADORES,
  type ClienteSql,
  Contadores,
  ContextoEmFaltaError,
  JobSemNomeError,
  LigacaoEmUsoError,
  METRICA_BATCH,
  METRICA_SEM_CONTEXTO,
  PoolRecusadoError,
  SQL_DEFINIR_CONTEXTO,
  TenantInvalidoError,
  VARIAVEL,
  comBatch,
  comTenant,
  normalizarTenant,
} from "../src/tenant_guard/index.ts";

const TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4";

type Chamada = readonly [string, readonly unknown[]];

class ClienteFalso implements ClienteSql {
  readonly chamadas: Chamada[] = [];
  falharEm: string | null = null;

  async query(sql: string, parametros: readonly unknown[] = []): Promise<unknown> {
    this.chamadas.push([sql, parametros]);
    if (this.falharEm !== null && sql === this.falharEm) {
      throw new Error("ligacao perdida");
    }
    return { rows: [] };
  }

  sql(): string[] {
    return this.chamadas.map(([texto]) => texto);
  }
}

test("normalizarTenant aceita a forma canonica em qualquer caixa", () => {
  assert.equal(normalizarTenant(TENANT), TENANT);
  assert.equal(normalizarTenant(TENANT.toUpperCase()), TENANT);
});

test("sem tenant lanca ContextoEmFaltaError e conta", () => {
  CONTADORES.repor();
  for (const valor of [null, undefined, ""]) {
    assert.throws(() => normalizarTenant(valor), ContextoEmFaltaError);
  }
  assert.equal(CONTADORES.ler()[METRICA_SEM_CONTEXTO], 3);
});

test("recusa o que nao e um UUID canonico", () => {
  CONTADORES.repor();
  const invalidos: unknown[] = [
    "nao-e-um-uuid",
    TENANT.replaceAll("-", ""),
    `{${TENANT}}`,
    `${TENANT} `,
    ` ${TENANT}`,
    "' OR '1'='1",
    42,
    ["x"],
    { tenant: TENANT },
  ];
  for (const valor of invalidos) {
    assert.throws(() => normalizarTenant(valor), TenantInvalidoError);
  }
  assert.equal(CONTADORES.ler()[METRICA_SEM_CONTEXTO], undefined);
});

test("a mensagem de tenant invalido nao repete o valor recebido", () => {
  const segredo = "mensagem-privada-de-um-cliente-123";
  assert.throws(
    () => normalizarTenant(segredo),
    (erro: unknown) => {
      assert.ok(erro instanceof TenantInvalidoError);
      assert.ok(!erro.message.includes(segredo));
      assert.ok(erro.message.includes(String(segredo.length)));
      return true;
    },
  );
});

test("comTenant: BEGIN, contexto, trabalho, COMMIT — por esta ordem", async () => {
  const cliente = new ClienteFalso();
  const resultado = await comTenant(cliente, TENANT, async (c) => {
    await c.query("SELECT 1");
    return "feito";
  });
  assert.equal(resultado, "feito");
  assert.deepEqual(cliente.chamadas, [
    ["BEGIN", []],
    [SQL_DEFINIR_CONTEXTO, [TENANT]],
    ["SELECT 1", []],
    ["COMMIT", []],
  ]);
});

test("o contexto e local a transaccao e o tenant vai como parametro", () => {
  assert.ok(SQL_DEFINIR_CONTEXTO.includes(`set_config('${VARIAVEL}', $1, true)`));
  assert.ok(!SQL_DEFINIR_CONTEXTO.includes("false"));
  assert.ok(!SQL_DEFINIR_CONTEXTO.includes(TENANT));
});

test("comTenant: um erro no trabalho desfaz e propaga", async () => {
  const cliente = new ClienteFalso();
  await assert.rejects(
    comTenant(cliente, TENANT, async () => {
      throw new RangeError("falhou");
    }),
    RangeError,
  );
  assert.deepEqual(cliente.sql(), ["BEGIN", SQL_DEFINIR_CONTEXTO, "ROLLBACK"]);
});

test("comTenant: falha ao definir o contexto desfaz sem correr o trabalho", async () => {
  const cliente = new ClienteFalso();
  cliente.falharEm = SQL_DEFINIR_CONTEXTO;
  let correu = false;
  await assert.rejects(
    comTenant(cliente, TENANT, async () => {
      correu = true;
    }),
    /ligacao perdida/,
  );
  assert.equal(correu, false);
  assert.deepEqual(cliente.sql(), ["BEGIN", SQL_DEFINIR_CONTEXTO, "ROLLBACK"]);
});

test("comTenant: falha no COMMIT desfaz e propaga", async () => {
  const cliente = new ClienteFalso();
  cliente.falharEm = "COMMIT";
  await assert.rejects(comTenant(cliente, TENANT, async () => "x"), /ligacao perdida/);
  assert.deepEqual(cliente.sql().slice(-2), ["COMMIT", "ROLLBACK"]);
});

test("comTenant: sem tenant ou com tenant invalido nao toca no cliente", async () => {
  CONTADORES.repor();
  for (const [valor, tipo] of [
    [null, ContextoEmFaltaError],
    ["", ContextoEmFaltaError],
    ["nao-e-uuid", TenantInvalidoError],
  ] as const) {
    const cliente = new ClienteFalso();
    await assert.rejects(
      comTenant(cliente, valor, async () => {
        assert.fail("nao devia entrar");
      }),
      tipo,
    );
    assert.deepEqual(cliente.chamadas, []);
  }
  assert.equal(CONTADORES.ler()[METRICA_SEM_CONTEXTO], 2);
});

test("comTenant: duas transaccoes definem o contexto duas vezes", async () => {
  const cliente = new ClienteFalso();
  const outro = "11111111-2222-4333-8444-555555555555";
  await comTenant(cliente, TENANT, async () => undefined);
  await comTenant(cliente, outro, async () => undefined);
  const definidos = cliente.chamadas
    .filter(([sql]) => sql === SQL_DEFINIR_CONTEXTO)
    .map(([, parametros]) => parametros[0]);
  assert.deepEqual(definidos, [TENANT, outro]);
});

test("comBatch: nao define contexto e conta o job", async () => {
  CONTADORES.repor();
  const cliente = new ClienteFalso();
  await comBatch(cliente, "retencao_mensal", async (c) => {
    await c.query("SELECT 1");
  });
  assert.deepEqual(cliente.sql(), ["BEGIN", "SELECT 1", "COMMIT"]);
  assert.deepEqual(CONTADORES.ler(), { [`${METRICA_BATCH}:retencao_mensal`]: 1 });
});

test("comBatch: sem nome de job nao ha transaccao", async () => {
  CONTADORES.repor();
  const invalidos: unknown[] = [
    "", null, undefined, "X", "ab", "Com Espaco", "com-hifen", "9inicio", 7,
    "a".repeat(64),
  ];
  for (const job of invalidos) {
    const cliente = new ClienteFalso();
    await assert.rejects(
      comBatch(cliente, job, async () => {
        assert.fail("nao devia entrar");
      }),
      JobSemNomeError,
    );
    assert.deepEqual(cliente.chamadas, []);
  }
  assert.deepEqual(CONTADORES.ler(), {});
});

test("comBatch: um erro desfaz", async () => {
  const cliente = new ClienteFalso();
  await assert.rejects(
    comBatch(cliente, "faturacao", async () => {
      throw new Error("x");
    }),
  );
  assert.deepEqual(cliente.sql(), ["BEGIN", "ROLLBACK"]);
});

test("Contadores: ler devolve uma copia, repor limpa", () => {
  const contadores = new Contadores();
  contadores.incrementar("x");
  contadores.incrementar("x");
  const copia = contadores.ler();
  copia.x = 99;
  assert.deepEqual(contadores.ler(), { x: 2 });
  contadores.repor();
  assert.deepEqual(contadores.ler(), {});
});

test("um pool e recusado antes de qualquer consulta", async () => {
  // Um pool tambem tem `query`, e cada chamada pode ir a uma ligacao diferente:
  // o BEGIN numa, o contexto noutra, a consulta numa terceira, sem contexto.
  for (const forma of [{ totalCount: 4 }, { idleCount: 0 }, { waitingCount: 0 }]) {
    const pool = Object.assign(new ClienteFalso(), forma);
    await assert.rejects(
      comTenant(pool, TENANT, async () => {
        assert.fail("nao devia entrar");
      }),
      PoolRecusadoError,
    );
    await assert.rejects(
      comBatch(pool, "retencao_mensal", async () => {
        assert.fail("nao devia entrar");
      }),
      PoolRecusadoError,
    );
    assert.deepEqual(pool.chamadas, []);
  }
});

test("se o ROLLBACK tambem falhar, propaga-se o erro original", async () => {
  class FalhaNoRollback extends ClienteFalso {
    override async query(sql: string, parametros: readonly unknown[] = []): Promise<unknown> {
      this.chamadas.push([sql, parametros]);
      if (sql === "ROLLBACK") {
        throw new Error("nao foi possivel desfazer");
      }
      return { rows: [] };
    }
  }
  const cliente = new FalhaNoRollback();
  await assert.rejects(
    comTenant(cliente, TENANT, async () => {
      throw new RangeError("a causa verdadeira");
    }),
    /a causa verdadeira/,
  );
  assert.deepEqual(cliente.sql(), ["BEGIN", SQL_DEFINIR_CONTEXTO, "ROLLBACK"]);
});

test("os nomes dos erros sao os das classes", () => {
  assert.equal(new PoolRecusadoError().name, "PoolRecusadoError");
  assert.equal(new ContextoEmFaltaError().name, "ContextoEmFaltaError");
  assert.equal(new TenantInvalidoError("string", 3).name, "TenantInvalidoError");
  assert.equal(new JobSemNomeError().name, "JobSemNomeError");
  assert.equal(new LigacaoEmUsoError().name, "LigacaoEmUsoError");
});

// --- Reentrancia e cliente partilhado: o achado 1 da revisao do KAM-004 ---
//
// Contra um PostgreSQL real, dois `comTenant` concorrentes no mesmo cliente
// partilhavam uma so transaccao e o pedido de A lia as linhas de B.

const OUTRO = "11111111-2222-4333-8444-555555555555";

test("dois comTenant concorrentes no mesmo cliente: o segundo e recusado", async () => {
  const cliente = new ClienteFalso();
  const resultados = await Promise.allSettled([
    comTenant(cliente, TENANT, async (c) => {
      await c.query("consulta do pedido A");
      return "a";
    }),
    comTenant(cliente, OUTRO, async (c) => {
      await c.query("consulta do pedido B");
      return "b";
    }),
  ]);
  assert.equal(resultados[0].status, "fulfilled");
  assert.equal(resultados[1].status, "rejected");
  assert.ok((resultados[1] as PromiseRejectedResult).reason instanceof LigacaoEmUsoError);
  // O segundo nao chegou a ligacao: um so BEGIN, um so contexto, e so a consulta de A.
  assert.deepEqual(cliente.chamadas, [
    ["BEGIN", []],
    [SQL_DEFINIR_CONTEXTO, [TENANT]],
    ["consulta do pedido A", []],
    ["COMMIT", []],
  ]);
});

test("comTenant e comBatch aninhados no mesmo cliente sao recusados", async () => {
  const combinacoes = [
    ["comTenant", "comTenant"],
    ["comTenant", "comBatch"],
    ["comBatch", "comTenant"],
    ["comBatch", "comBatch"],
  ] as const;
  const abrir = (
    qual: "comTenant" | "comBatch",
    cliente: ClienteSql,
    trabalho: (c: ClienteSql) => Promise<unknown>,
  ) =>
    qual === "comTenant"
      ? comTenant(cliente, TENANT, trabalho)
      : comBatch(cliente, "retencao_mensal", trabalho);

  for (const [fora, dentro] of combinacoes) {
    const cliente = new ClienteFalso();
    await assert.rejects(
      abrir(fora, cliente, async (c) => {
        await abrir(dentro, c, async () => {
          assert.fail("a segunda transaccao nao podia abrir");
        });
      }),
      LigacaoEmUsoError,
      `${fora} > ${dentro}`,
    );
    // A de fora desfez-se, e a de dentro nao abriu transaccao nenhuma.
    assert.equal(cliente.sql().filter((s) => s === "BEGIN").length, 1);
    assert.equal(cliente.sql().at(-1), "ROLLBACK");
    assert.ok(!cliente.sql().includes("COMMIT"));
  }
});

test("o cliente fica livre depois de sair, com ou sem erro", async () => {
  const cliente = new ClienteFalso();
  await comTenant(cliente, TENANT, async () => undefined);
  await assert.rejects(
    comTenant(cliente, TENANT, async () => {
      throw new Error("falhou a meio");
    }),
    /falhou a meio/,
  );
  cliente.falharEm = "BEGIN";
  await assert.rejects(comTenant(cliente, TENANT, async () => undefined), /ligacao perdida/);
  cliente.falharEm = null;
  await comTenant(cliente, OUTRO, async () => undefined);
  assert.equal(cliente.sql().filter((s) => s === "COMMIT").length, 2);
});

test("clientes diferentes nao se bloqueiam", async () => {
  const a = new ClienteFalso();
  const b = new ClienteFalso();
  await comTenant(a, TENANT, async () => {
    await comTenant(b, OUTRO, async () => undefined);
  });
  assert.ok(a.sql().includes("COMMIT"));
  assert.ok(b.sql().includes("COMMIT"));
});

test("um tenant que nao e texto nao tem o toString chamado", () => {
  let chamado = false;
  const armadilha = {
    toString() {
      chamado = true;
      throw new Error("efeito lateral de quem chamou");
    },
  };
  assert.throws(() => normalizarTenant(armadilha), TenantInvalidoError);
  assert.throws(() => normalizarTenant(Object.create(null)), TenantInvalidoError);
  assert.equal(chamado, false);
});
