/**
 * A recusa da base sobre o tecto, contada pelo `tenant_guard` (KAM-219).
 *
 * Sem base de dados: o erro é o que o `pg` entrega (`code` e `message`), e o
 * caso contra um PostgreSQL real — o `kamba_app` a escrever o tecto, e o
 * controlo do `kamba_batch` — está em `../tests_bd/confianca.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type ClienteSql,
  METRICA_TECTO_RECUSADO,
  METRICAS_DA_GUARDA,
  MetricasDaGuarda,
  SQLSTATE_PRIVILEGIO,
  comBatch,
  comTenant,
  eRecusaNoTecto,
} from "../src/tenant_guard/index.ts";

const TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4";

/** A forma do erro do `pg`: um `Error` com o SQLSTATE em `code`. */
function erroDaBase(code: string, message: string): Error & { code: string } {
  return Object.assign(new Error(message), { code });
}

const RECUSA_NO_TECTO = (): Error & { code: string } =>
  erroDaBase("42501", "permission denied for table trust_level");

class Cliente implements ClienteSql {
  readonly sql: string[] = [];
  async query(texto: string): Promise<unknown> {
    this.sql.push(texto);
    return { rows: [] };
  }
}

test("o predicado: 42501 e a tabela trust_level, e nada mais", () => {
  assert.equal(SQLSTATE_PRIVILEGIO, "42501");
  assert.equal(eRecusaNoTecto(RECUSA_NO_TECTO()), true);
  // O nome não se traduz com o `lc_messages`; a frase sim.
  assert.equal(eRecusaNoTecto(erroDaBase("42501", "permissão negada para tabela trust_level")), true);
  // Outra tabela, outro SQLSTATE, ou um nome que só começa por `trust_level`.
  assert.equal(eRecusaNoTecto(erroDaBase("42501", "permission denied for table ts_sanction")), false);
  assert.equal(eRecusaNoTecto(erroDaBase("23505", "duplicate key value violates unique constraint on trust_level")), false);
  assert.equal(eRecusaNoTecto(erroDaBase("42501", "permission denied for table trust_level_historico")), false);
  // O que não é um erro da base.
  for (const valor of [null, undefined, "42501 trust_level", 42501, { code: "42501" }, { code: 42501, message: "trust_level" }]) {
    assert.equal(eRecusaNoTecto(valor), false, String(valor));
  }
});

test("nasce a zero, conta uma vez por erro, e serve o valor", () => {
  const m = new MetricasDaGuarda();
  assert.match(m.exposicao(), new RegExp(`^# TYPE ${METRICA_TECTO_RECUSADO} counter$`, "m"));
  assert.match(m.exposicao(), new RegExp(`^${METRICA_TECTO_RECUSADO} 0$`, "m"));
  const erro = RECUSA_NO_TECTO();
  m.observar(erro);
  m.observar(erro);
  m.observar(erroDaBase("42501", "permission denied for table ts_sanction"));
  assert.equal(m.recusas(), 1);
  m.observar(RECUSA_NO_TECTO());
  assert.equal(m.recusas(), 2);
  assert.match(m.exposicao(), new RegExp(`^${METRICA_TECTO_RECUSADO} 2$`, "m"));
  // Sem etiquetas: nenhuma chaveta, logo nenhum tenant (`OBS-I`).
  assert.equal(m.exposicao().includes("{"), false);
});

test("comTenant: a recusa no tecto conta, desfaz e propaga o mesmo erro", async () => {
  const antes = METRICAS_DA_GUARDA.recusas();
  const cliente = new Cliente();
  const erro = RECUSA_NO_TECTO();
  await assert.rejects(
    comTenant(cliente, TENANT, async () => {
      throw erro;
    }),
    (e) => e === erro,
  );
  assert.equal(cliente.sql.at(-1), "ROLLBACK");
  assert.equal(METRICAS_DA_GUARDA.recusas(), antes + 1);
});

test("comBatch: a recusa no tecto conta tambem", async () => {
  const antes = METRICAS_DA_GUARDA.recusas();
  await assert.rejects(
    comBatch(new Cliente(), "ensaio_do_tecto", async () => {
      throw RECUSA_NO_TECTO();
    }),
  );
  assert.equal(METRICAS_DA_GUARDA.recusas(), antes + 1);
});

test("o comTenant dentro do comBatch (o recalculo da confianca) conta uma vez, e nao duas", async () => {
  const antes = METRICAS_DA_GUARDA.recusas();
  await assert.rejects(
    comBatch(new Cliente(), "ensaio_do_tecto", () =>
      comTenant(new Cliente(), TENANT, async () => {
        throw RECUSA_NO_TECTO();
      }),
    ),
  );
  assert.equal(METRICAS_DA_GUARDA.recusas(), antes + 1);
});

test("o controlo: sucesso, outro erro, ou 42501 sobre outra tabela, nao contam", async () => {
  const antes = METRICAS_DA_GUARDA.recusas();
  assert.equal(await comTenant(new Cliente(), TENANT, async () => "ok"), "ok");
  await assert.rejects(comTenant(new Cliente(), TENANT, async () => {
    throw erroDaBase("42501", "permission denied for table ts_sanction");
  }));
  await assert.rejects(comBatch(new Cliente(), "ensaio_do_tecto", async () => {
    throw new Error("ligacao perdida");
  }));
  assert.equal(METRICAS_DA_GUARDA.recusas(), antes);
});
