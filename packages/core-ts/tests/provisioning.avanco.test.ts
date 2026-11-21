/**
 * O varrimento do provisionamento (KAM-215): a forma da volta — a releitura sob
 * tranca, o salto de um candidato velho, as falhas — sobre uma base falsa. O
 * predicado em si (a saga, o canal, o tenant) mede-se contra o PostgreSQL em
 * `tests_bd/provisionamento.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ACTOR_DO_AVANCO,
  AvancoComFalhasError,
  PASSOS_ANTES_DO_ES,
  SQL_AVANCAR_CASO,
  SQL_CASOS_POR_AVANCAR,
  SQL_TRANCAR_CASO,
  varrerProvisionamentos,
} from "../src/provisioning/index.ts";

const T = "22222222-2222-4222-8222-222222222222";
const CASO = "11111111-1111-4111-8111-111111111111";

type Linha = { onboarding_id: string; tenant_id: string; fase: string; evento: string };

/** Uma base falsa: a lista devolve `lista()`, a releitura de um caso devolve `relido(id)`. */
function base(o: { lista: () => Linha[]; relido: (id: string) => Linha[]; avancar?: () => void }) {
  const consultas: { ligacao: number; sql: string; valores: readonly unknown[] }[] = [];
  const devolvidas: (boolean | Error | undefined)[] = [];
  let n = 0;
  const responder = (sql: string, valores: readonly unknown[]) => {
    if (sql === SQL_CASOS_POR_AVANCAR) return { rows: valores[2] === null ? o.lista() : o.relido(String(valores[2])) };
    if (sql === SQL_AVANCAR_CASO) o.avancar?.();
    return { rows: [] };
  };
  return {
    consultas,
    devolvidas,
    query: async (sql: string, valores: readonly unknown[] = []) => {
      consultas.push({ ligacao: 0, sql, valores });
      return responder(sql, valores);
    },
    connect: async () => {
      const id = ++n;
      return {
        query: async (sql: string, valores: readonly unknown[] = []) => {
          consultas.push({ ligacao: id, sql, valores });
          return responder(sql, valores);
        },
        release: (erro?: boolean | Error) => void devolvidas.push(erro),
      };
    },
  };
}

describe("KAM-215 — o varrimento do provisionamento", () => {
  it("lista todos, tranca o caso, relê o predicado só dele e chama a porta com o actor do lote", async () => {
    let pronto = true;
    const linha = { onboarding_id: CASO, tenant_id: T, fase: "aguarda_es", evento: "es_concluido" };
    const bd = base({ lista: () => (pronto ? [linha] : []), relido: () => (pronto ? [linha] : []), avancar: () => (pronto = false) });
    assert.equal(await varrerProvisionamentos({ lote: bd, limite: 50 }), 1);
    assert.deepEqual(bd.consultas[0]?.valores, [PASSOS_ANTES_DO_ES, 50, null]);
    const tx = bd.consultas.filter((c) => c.ligacao === 1).map((c) => c.sql);
    const tranca = tx.indexOf(SQL_TRANCAR_CASO);
    const releitura = tx.indexOf(SQL_CASOS_POR_AVANCAR);
    const porta = tx.indexOf(SQL_AVANCAR_CASO);
    assert.ok(tranca >= 0 && tranca < releitura && releitura < porta, tx.join(" | "));
    assert.deepEqual(bd.consultas.find((c) => c.sql === SQL_CASOS_POR_AVANCAR && c.ligacao === 1)?.valores, [PASSOS_ANTES_DO_ES, 1, CASO]);
    assert.deepEqual(bd.consultas.find((c) => c.sql === SQL_AVANCAR_CASO)?.valores, [CASO, "es_concluido", ACTOR_DO_AVANCO]);
    assert.deepEqual(bd.devolvidas, [false]);
  });

  it("um candidato que já não é o lido (outra réplica avançou, ou um passo foi compensado) salta-se sem falha", async () => {
    const lido = { onboarding_id: CASO, tenant_id: T, fase: "provisionando", evento: "saga_concluida" };
    for (const relido of [[], [{ ...lido, fase: "aguarda_es", evento: "es_concluido" }]]) {
      let voltas = 0;
      const bd = base({ lista: () => (voltas++ === 0 ? [lido] : []), relido: () => relido });
      assert.equal(await varrerProvisionamentos({ lote: bd, limite: 10 }), 0);
      assert.equal(bd.consultas.filter((c) => c.sql === SQL_AVANCAR_CASO).length, 0, "a porta não é chamada");
    }
  });

  it("uma porta que recusa avança os outros, destrói a ligação e lança no fim com as contagens", async () => {
    const outro = "33333333-3333-4333-8333-333333333333";
    const linhas = [
      { onboarding_id: CASO, tenant_id: T, fase: "aguarda_es", evento: "es_concluido" },
      { onboarding_id: outro, tenant_id: T, fase: "aprovado", evento: "saga_iniciada" },
    ];
    const feitos = new Set<string>();
    const bd = base({
      lista: () => linhas.filter((l) => !feitos.has(l.onboarding_id)),
      relido: (id) => linhas.filter((l) => l.onboarding_id === id && !feitos.has(id)),
    });
    const connect = bd.connect;
    let tentativasDoQueFalha = 0;
    bd.connect = async () => {
      const l = await connect();
      return {
        ...l,
        query: async (sql: string, valores: readonly unknown[] = []) => {
          if (sql === SQL_AVANCAR_CASO && valores[0] === CASO) {
            tentativasDoQueFalha++;
            throw new Error("23514");
          }
          if (sql === SQL_AVANCAR_CASO) feitos.add(String(valores[0]));
          return l.query(sql, valores);
        },
      };
    };
    await assert.rejects(varrerProvisionamentos({ lote: bd, limite: 10 }), (e: unknown) => {
      assert.ok(e instanceof AvancoComFalhasError);
      assert.equal(e.avancados, 1);
      assert.equal(e.falhados, 1);
      assert.ok(!e.message.includes(CASO) && !e.message.includes(T), "nem o caso nem o tenant na mensagem");
      return true;
    });
    assert.ok(bd.devolvidas.includes(true), "a ligação que falhou destrói-se");
    assert.equal(tentativasDoQueFalha, 1, "o que falhou não se repete na volta");
  });

  it("os passos da saga e o canal amarram o tenant do caso (o kamba_batch não tem RLS)", () => {
    assert.equal(SQL_CASOS_POR_AVANCAR.match(/p\.tenant_id = c\.tenant_id/g)?.length, 2);
    assert.match(SQL_CASOS_POR_AVANCAR, /ch\.tenant_id = c\.tenant_id/);
  });
});
