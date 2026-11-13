/**
 * O que o processo de lote do onboarding (KAM-198) acrescentou à fila de
 * revisão, sem base de dados: o trinco da quota entre processos no adaptador
 * SQL e no serviço, e o adaptador SQL dos onboardings.
 *
 * Que o trinco **segura** a quota contra vinte processos ao mesmo tempo só uma
 * base real o prova, e prova-o em `tests_bd/lote.bd.test.ts`. Aqui mede-se a
 * forma: a transacção, a chave, a ligação emprestada e devolvida, e que o
 * serviço passa por ele na abertura e na drenagem.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AuditoriaEmMemoria,
  ESPACO_DO_TRINCO_DA_QUOTA,
  FilaDeRevisaoEmMemoria,
  LIMIARES_POR_OMISSAO,
  OnboardingsSql,
  RevisaoSql,
  SQL_CONTAR_NA_FILA,
  SQL_MARCAR_FASE,
  SQL_ONBOARDING_POR_ID,
  SQL_ONBOARDING_POR_TENANT,
  SQL_TRINCO_DA_QUOTA,
  ServicoDeRevisao,
  TrincoSemConjuntoError,
  type ConjuntoSql,
  type RepositorioDeRevisao,
} from "../src/revisao/index.ts";
import { SEXTA, montarRevisao } from "./apoio/revisao.ts";

/** Um serviço sobre o repositório dado e os onboardings do duplo. */
function servicoCom(m: ReturnType<typeof montarRevisao>, repositorio: RepositorioDeRevisao, quota = 20): ServicoDeRevisao {
  return new ServicoDeRevisao({
    repositorio,
    onboardings: m.onboardings,
    auditoria: new AuditoriaEmMemoria(),
    aviso: { avisar: async () => {} },
    alerta: () => {},
    cifra: { cifrar: async (b) => b, decifrar: async (b) => b },
    dados: { ler: async () => null },
    documentos: { url: async () => "" },
    screening: { gravar: async () => {} },
    relogio: () => SEXTA,
    limiares: { ...LIMIARES_POR_OMISSAO, quotaPorOrigemPorDia: quota },
  });
}

type Resposta = { rows: Record<string, unknown>[] };

/** Um `pg.Pool` falso: regista as consultas pela ligação que as correu. */
function conjuntoFalso(tratar: (texto: string, valores: readonly unknown[]) => Resposta | undefined = () => undefined) {
  const consultas: { ligacao: string; texto: string; valores: readonly unknown[] }[] = [];
  const devolvidas: (Error | boolean | undefined)[] = [];
  let n = 0;
  const responder = (ligacao: string) =>
    async <T>(texto: string, valores: readonly unknown[] = []) => {
      consultas.push({ ligacao, texto, valores });
      return (tratar(texto, valores) ?? { rows: [] }) as unknown as { readonly rows: readonly T[] };
    };
  const conjunto: ConjuntoSql = {
    query: responder("conjunto"),
    async connect() {
      const nome = `ligacao-${++n}`;
      return { query: responder(nome), release: (erro?: Error | boolean) => void devolvidas.push(erro) };
    },
  };
  return { conjunto, consultas, devolvidas };
}

describe("o trinco da quota no adaptador SQL", () => {
  it("sem conjunto de ligações, recusa em vez de abrir um BEGIN partilhado", async () => {
    const { conjunto, consultas } = conjuntoFalso();
    await assert.rejects(new RevisaoSql(conjunto).emTrinco("o:aa", async () => 1), TrincoSemConjuntoError);
    assert.deepEqual(consultas, []);
  });

  it("tranca a chave numa transacção de uma ligação emprestada, e o trabalho corre nela", async () => {
    const { conjunto, consultas, devolvidas } = conjuntoFalso((t) =>
      t === SQL_CONTAR_NA_FILA ? { rows: [{ n: 4 }] } : undefined,
    );
    const r = await new RevisaoSql(conjunto, { conjunto }).emTrinco("o:abcd", (repo) =>
      repo.contarNaFilaDesde("abcd", new Date(0)),
    );
    assert.equal(r, 4);
    assert.deepEqual(
      consultas.map((c) => [c.ligacao, c.texto]),
      [
        ["ligacao-1", "BEGIN"],
        ["ligacao-1", SQL_TRINCO_DA_QUOTA],
        ["ligacao-1", SQL_CONTAR_NA_FILA],
        ["ligacao-1", "COMMIT"],
      ],
    );
    assert.deepEqual(consultas[1]!.valores, [ESPACO_DO_TRINCO_DA_QUOTA, "o:abcd"]);
    assert.deepEqual(devolvidas, [undefined]);
  });

  it("um trabalho que falha reverte, devolve a ligação e deixa passar o erro", async () => {
    const { conjunto, consultas, devolvidas } = conjuntoFalso();
    await assert.rejects(
      new RevisaoSql(conjunto, { conjunto }).emTrinco("t:x", async () => {
        throw new Error("falhou");
      }),
      /falhou/,
    );
    assert.deepEqual(
      consultas.map((c) => c.texto),
      ["BEGIN", SQL_TRINCO_DA_QUOTA, "ROLLBACK"],
    );
    assert.deepEqual(devolvidas, [undefined]);
  });

  it("uma ligação que nem reverte não volta ao conjunto como boa", async () => {
    const { conjunto, devolvidas } = conjuntoFalso((t) => {
      if (t === "ROLLBACK") throw new Error("ligacao morta");
      if (t === SQL_TRINCO_DA_QUOTA) throw new Error("trinco");
      return undefined;
    });
    await assert.rejects(new RevisaoSql(conjunto, { conjunto }).emTrinco("t:x", async () => 1), /trinco/);
    assert.equal(devolvidas.length, 1);
    assert.ok(devolvidas[0] instanceof Error, "a ligação devolve-se com o erro, e o pg descarta-a");
  });
});

describe("o serviço passa pelo trinco entre processos", () => {
  /** O repositório em memória com um `emTrinco` que regista as chaves. */
  function comTrinco(repositorio: FilaDeRevisaoEmMemoria) {
    const chaves: string[] = [];
    const dentro: string[] = [];
    const embrulhado: RepositorioDeRevisao = new Proxy(repositorio, {
      get(alvo, nome) {
        if (nome === "emTrinco") {
          return async <T>(chave: string, trabalho: (r: RepositorioDeRevisao) => Promise<T>) => {
            chaves.push(chave);
            // O trabalho recebe **outro** objecto: o que ele usar fora dele é o
            // repositório errado, e o registo mostra-o.
            const espiao = new Proxy(alvo, {
              get(a, n) {
                const v = Reflect.get(a, n, a) as unknown;
                return typeof v === "function"
                  ? (...args: unknown[]) => {
                      dentro.push(String(n));
                      return (v as (...x: unknown[]) => unknown).apply(a, args);
                    }
                  : v;
              },
            });
            return trabalho(espiao);
          };
        }
        const v = Reflect.get(alvo, nome, alvo) as unknown;
        return typeof v === "function" ? (v as (...x: unknown[]) => unknown).bind(alvo) : v;
      },
    });
    return { embrulhado, chaves, dentro };
  }

  it("a abertura conta e escreve dentro do trinco da origem", async () => {
    const m = montarRevisao();
    const o = m.onboarding({ redeHmac: "ab12" });
    const { embrulhado, chaves, dentro } = comTrinco(m.repositorio);
    const servico = servicoCom(m, embrulhado);
    const r = await servico.abrir({
      tipo: "kyc",
      tenantId: o.tenantId,
      onboardingId: o.id,
      motivoCodigo: "k1:x",
      motivoInterno: "x",
      motivoPublico: "nao_foi_possivel_validar",
      evidencias: [],
      recomendacao: null,
      prioridade: 5,
    });
    assert.equal(r.estado, "aberto");
    assert.deepEqual(chaves, ["o:ab12"]);
    assert.deepEqual(dentro, ["contarNaFilaDesde", "abrir"]);
  });

  it("a drenagem da triagem conta e transita dentro do trinco da mesma chave", async () => {
    const m = montarRevisao({ limiares: { quotaPorOrigemPorDia: 1 } });
    const o = m.onboarding({ redeHmac: "cd34" });
    const abrir = (i: number) =>
      m.servico.abrir({
        tipo: "kyc",
        tenantId: o.tenantId,
        onboardingId: o.id,
        motivoCodigo: `k1:${i}`,
        motivoInterno: "x",
        motivoPublico: "nao_foi_possivel_validar",
        evidencias: [],
        recomendacao: null,
        prioridade: 5,
      });
    await abrir(1);
    assert.equal((await abrir(2)).estado, "em_triagem_automatica");
    const { embrulhado, chaves, dentro } = comTrinco(m.repositorio);
    const servico = servicoCom(m, embrulhado, 1);
    assert.equal(await servico.drenarTriagem(), 0, "a quota de hoje está cheia");
    assert.deepEqual(chaves, ["o:cd34"]);
    assert.deepEqual(dentro, ["contarNaFilaDesde"]);
  });
});

describe("os onboardings sobre a onboarding_case", () => {
  const linha = {
    id: "o1",
    tenant_id: "t1",
    fase: "em_revisao",
    ip_prefix_hash: Uint8Array.from([0xab, 0x01]),
    device_hash: null,
    nif_hmac: Uint8Array.from([0x0f]),
    phone_hmac: Uint8Array.from([0xff, 0x00]),
  };

  it("lê pelo id e pelo tenant, com os hashes em hexadecimal", async () => {
    const { conjunto, consultas } = conjuntoFalso((t) =>
      t === SQL_ONBOARDING_POR_ID || t === SQL_ONBOARDING_POR_TENANT ? { rows: [linha] } : undefined,
    );
    const o = new OnboardingsSql(conjunto);
    const esperado = {
      id: "o1",
      tenantId: "t1",
      fase: "em_revisao",
      redeHmac: "ab01",
      dispositivoHmac: null,
      nifHmac: "0f",
      telefoneHmac: "ff00",
    };
    assert.deepEqual(await o.porId("o1"), esperado);
    assert.deepEqual(await o.porTenant("t1"), esperado);
    assert.deepEqual(
      consultas.map((c) => [c.texto, c.valores]),
      [
        [SQL_ONBOARDING_POR_ID, ["o1"]],
        [SQL_ONBOARDING_POR_TENANT, ["t1"]],
      ],
    );
  });

  it("um onboarding que não existe é null, e a fase muda só se a linha existir", async () => {
    let existe = false;
    const { conjunto, consultas } = conjuntoFalso((t) =>
      t === SQL_MARCAR_FASE && existe ? { rows: [{ id: "o1" }] } : undefined,
    );
    const o = new OnboardingsSql(conjunto);
    assert.equal(await o.porId("o9"), null);
    assert.equal(await o.porTenant("t9"), null);
    assert.equal(await o.marcarFase("o1", "aprovado"), false);
    existe = true;
    assert.equal(await o.marcarFase("o1", "rejeitado"), true);
    assert.deepEqual(consultas.at(-1)?.valores, ["o1", "rejeitado"]);
  });
});
