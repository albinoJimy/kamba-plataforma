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
  AprovacaoSemConjuntoError,
  AuditoriaEmMemoria,
  CicloDaFila,
  OnboardingInexistenteError,
  SQL_APROVACAO_EM_FALTA,
  SQL_AVANCAR_CASO,
  SQL_INTERVENCAO_DO_EVENTO,
  SQL_INTERVENCAO_HUMANA,
  SQL_JA_APROVADO,
  SQL_REVISAO_PENDENTE,
  SQL_TENANT_DO_CASO,
  SQL_TRANCAR_CASO,
  RevisaoRecusadaError,
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
  it("é o trinco de transacção que **espera**, na forma de dois argumentos", () => {
    // Literal e não a constante importada: um `pg_try_advisory_xact_lock` não
    // espera, devolve falso, e a quota passava no limite com o trinco «tomado»
    // (achado 7 da revisão adversarial: o oráculo era o próprio alvo).
    assert.equal(SQL_TRINCO_DA_QUOTA, "SELECT pg_advisory_xact_lock($1::int, hashtext($2::text))");
    assert.equal(ESPACO_DO_TRINCO_DA_QUOTA, 7198);
  });

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
    fase_at: new Date("2026-11-13T08:00:00Z"),
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
      faseEm: new Date("2026-11-13T08:00:00Z"),
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
    assert.equal(await o.marcarFase("o1", "kyc_pendente"), false);
    existe = true;
    assert.equal(await o.marcarFase("o1", "rejeitado"), true);
    assert.deepEqual(consultas.at(-1)?.valores, ["o1", "rejeitado"]);
  });
});

describe("a aprovação pela porta da base (KAM-092, KAM-201)", () => {
  const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
  /** Um conjunto que responde ao tenant, à fase, ao agregador, à revisão pendente e ao evento. */
  const base = (o: {
    fase: string;
    falta?: string[];
    pendente?: boolean;
    jaAprovado?: boolean;
    doEvento?: boolean | null;
    humana?: boolean;
    avancar?: Error;
  }) =>
    conjuntoFalso((t) => {
      if (t === SQL_TENANT_DO_CASO) return { rows: [{ tenant_id: TENANT }] };
      if (t === SQL_TRANCAR_CASO) return { rows: [{ fase: o.fase }] };
      if (t === SQL_APROVACAO_EM_FALTA) return { rows: [{ falta: o.falta ?? [] }] };
      if (t === SQL_REVISAO_PENDENTE) return { rows: [{ pendente: o.pendente ?? false }] };
      if (t === SQL_JA_APROVADO) return { rows: [{ emitido: o.jaAprovado ?? false }] };
      if (t === SQL_INTERVENCAO_DO_EVENTO) return { rows: o.doEvento === undefined ? [] : [{ humana: o.doEvento }] };
      if (t === SQL_INTERVENCAO_HUMANA) return { rows: [{ humana: o.humana ?? false }] };
      if (t === SQL_AVANCAR_CASO && o.avancar !== undefined) throw o.avancar;
      return undefined;
    });
  const daLigacao = (consultas: { ligacao: string; texto: string; valores: readonly unknown[] }[]) =>
    consultas.filter((c) => c.ligacao === "ligacao-1").map((c) => [c.texto, c.valores]);

  it("aprova numa transacção com o contexto do tenant, trancando o caso antes de perguntar", async () => {
    const { conjunto, consultas, devolvidas } = base({ fase: "em_revisao", doEvento: true });
    assert.deepEqual(await new OnboardingsSql(conjunto).aprovar("o1", "aprovar", "revisor:r1"), {
      estado: "aprovado",
      intervencaoHumana: true,
    });
    assert.deepEqual(daLigacao(consultas), [
      ["BEGIN", []],
      ["SELECT set_config('app.tenant_id', $1, true)", [TENANT]],
      [SQL_TRANCAR_CASO, ["o1"]],
      [SQL_APROVACAO_EM_FALTA, ["o1"]],
      [SQL_REVISAO_PENDENTE, ["o1"]],
      [SQL_JA_APROVADO, [TENANT]],
      [SQL_AVANCAR_CASO, ["o1", "aprovar", "revisor:r1"]],
      [SQL_INTERVENCAO_DO_EVENTO, [TENANT]],
      ["COMMIT", []],
    ]);
    assert.deepEqual(devolvidas, [undefined]);
  });

  it("a intervenção humana é a do evento emitido; sem linha no outbox, cai na pergunta à revisão", async () => {
    // O evento diz `false` e a revisão diria `true`: vale o evento (achado 6).
    const doEvento = base({ fase: "em_revisao", doEvento: false, humana: true });
    assert.deepEqual(await new OnboardingsSql(doEvento.conjunto).aprovar("o1", "aprovar", "x"), {
      estado: "aprovado",
      intervencaoHumana: false,
    });
    assert.ok(!doEvento.consultas.some((c) => c.texto === SQL_INTERVENCAO_HUMANA));
    const semLinha = base({ fase: "aprovado", humana: true });
    assert.deepEqual(await new OnboardingsSql(semLinha.conjunto).aprovar("o1", "aprovar", "x"), {
      estado: "aprovado",
      intervencaoHumana: true,
    });
  });

  it("com o agregador por preencher, não avança e devolve o que falta", async () => {
    const { conjunto, consultas } = base({ fase: "kyc_pendente", falta: ["screening", "aceite"] });
    assert.deepEqual(await new OnboardingsSql(conjunto).aprovar("o1", "aprovar", "kyc:k1_ok"), {
      estado: "em_falta",
      falta: ["screening", "aceite"],
    });
    assert.ok(!consultas.some((c) => c.texto === SQL_AVANCAR_CASO));
  });

  it("um caso de revisão bloqueante por decidir também falta, depois do agregador", async () => {
    const { conjunto, consultas } = base({ fase: "kyc_pendente", pendente: true });
    assert.deepEqual(await new OnboardingsSql(conjunto).aprovar("o1", "aprovar", "kyc:k1_ok"), {
      estado: "em_falta",
      falta: ["revisao"],
    });
    assert.ok(!consultas.some((c) => c.texto === SQL_AVANCAR_CASO));
  });

  it("um tenant já aprovado com a fase escrita para trás não volta a aprovar (achado 2)", async () => {
    const { conjunto, consultas } = base({ fase: "rejeitado", jaAprovado: true });
    assert.deepEqual(await new OnboardingsSql(conjunto).aprovar("o1", "recurso_aprovado", "revisor:r2"), {
      estado: "em_falta",
      falta: ["ja_aprovado"],
    });
    assert.ok(!consultas.some((c) => c.texto === SQL_AVANCAR_CASO), "um segundo tenant.approved não sai");
  });

  it("o evento é o de quem chama, e não o da fase lida; já aprovado, repete sem perguntar ao agregador", async () => {
    const r = base({ fase: "rejeitado" });
    await new OnboardingsSql(r.conjunto).aprovar("o1", "recurso_aprovado", "revisor:r2");
    assert.deepEqual(r.consultas.find((c) => c.texto === SQL_AVANCAR_CASO)?.valores, ["o1", "recurso_aprovado", "revisor:r2"]);
    // Um `aprovar` sobre um `rejeitado` vai à base como `aprovar`, que o recusa:
    // a porta não o converte num recurso que ninguém decidiu (achado 3).
    const k = base({ fase: "rejeitado" });
    await new OnboardingsSql(k.conjunto).aprovar("o1", "aprovar", "kyc:k1_ok");
    assert.deepEqual(k.consultas.find((c) => c.texto === SQL_AVANCAR_CASO)?.valores, ["o1", "aprovar", "kyc:k1_ok"]);
    const a = base({ fase: "aprovado", falta: ["aceite"], jaAprovado: true });
    assert.equal((await new OnboardingsSql(a.conjunto).aprovar("o1", "aprovar", "kyc:k1_ok")).estado, "aprovado");
    assert.ok(!a.consultas.some((c) => c.texto === SQL_APROVACAO_EM_FALTA), "a repetição é da porta");
  });

  it("uma porta que recusa desfaz a transacção e devolve a ligação com o erro", async () => {
    const recusa = new Error("evento aprovar recusado na fase rejeitado");
    const { conjunto, consultas, devolvidas } = base({ fase: "em_revisao", avancar: recusa });
    await assert.rejects(new OnboardingsSql(conjunto).aprovar("o1", "aprovar", "x"), recusa);
    assert.equal(consultas.at(-1)?.texto, "ROLLBACK");
    assert.deepEqual(devolvidas, [recusa]);
  });

  it("sem conjunto de ligações — ou com um cliente cujo connect não empresta nada —, ou sem caso, recusa", async () => {
    const solto = { query: async () => ({ rows: [] }) };
    await assert.rejects(new OnboardingsSql(solto).aprovar("o1", "aprovar", "x"), AprovacaoSemConjuntoError);
    // Um `pg.Client` também tem `connect`, e resolve sem ligação (achado 9).
    const cliente = {
      query: async () => ({ rows: [{ tenant_id: TENANT }] }),
      connect: async () => undefined,
    };
    await assert.rejects(
      new OnboardingsSql(cliente as unknown as ConjuntoSql).aprovar("o1", "aprovar", "x"),
      AprovacaoSemConjuntoError,
    );
    const { conjunto, consultas } = conjuntoFalso();
    await assert.rejects(new OnboardingsSql(conjunto).aprovar("o9", "aprovar", "x"), OnboardingInexistenteError);
    assert.deepEqual(consultas.map((c) => c.ligacao), ["conjunto"]);
  });
});

describe("a reaplicação não passa fome nem desfaz a fase", () => {
  it("um efeito que volta a falhar é remarcado, e vai para o fim da fila", async () => {
    const marcadas: string[] = [];
    const ciclo = new CicloDaFila({
      servico: {
        drenarTriagem: async () => 0,
        alertarSla: async () => 0,
        reaplicarEfeitos: async (id: string) => {
          if (id === "falha") throw new Error("aviso sem via");
          if (id === "fechado") throw new RevisaoRecusadaError("estado_invalido");
        },
        amostrar: async () => null,
      },
      leitor: { vista: async () => [], contadores: async () => [] },
      efeitos: {
        marcar: async (id) => void marcadas.push(id),
        pendentes: async () => ["falha", "sai", "fechado"],
        resolver: async () => {},
      },
    });
    const r = await ciclo.correr();
    assert.deepEqual(marcadas, ["falha"], "só o que voltou a falhar se remarca");
    assert.equal(r.porReaplicar, 1);
    assert.equal(r.reaplicados, 1);
  });

  it("reaplicar um pedir_info só reescreve a fase se ela não mudou depois da decisão", async () => {
    for (const [mudou, esperado] of [
      [true, "rejeitado"],
      [false, "kyc_pendente"],
    ] as const) {
      const m = montarRevisao();
      const o = m.onboarding();
      const r = await m.abrir(o);
      assert.ok(r.estado !== "nao_elegivel");
      const casoId = r.caso.id;
      await m.servico.decidir({ id: "rev-1", papeis: ["ts_revisor"], mfa: true, nifHmac: null, telefoneHmac: null }, casoId, "pedir_info");
      // A fase muda depois da decisão (o KYC voltou a decidir e rejeitou), e o
      // instante da mudança vem na porta, como o `fase_at` da base o dá.
      m.avancar(60_000);
      const actual = m.onboardings.casos.get(o.id)!;
      m.onboardings.casos.set(o.id, {
        ...actual,
        // Sem mudança: a fase de antes do pedido, com um instante anterior à
        // decisão — a do efeito que falhou e que a reaplicação tem de aplicar.
        fase: mudou ? "rejeitado" : "em_revisao",
        faseEm: mudou ? m.agora() : new Date(0),
      });
      await m.servico.reaplicarEfeitos(casoId);
      assert.equal(m.onboardings.casos.get(o.id)!.fase, esperado, `mudou=${mudou}`);
    }
  });
});
