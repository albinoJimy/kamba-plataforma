/**
 * O *job* da fila (KAM-196, critério 6): drenar, alertar, reaplicar e medir.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import {
  CicloDaFila,
  EfeitoPorAplicarError,
  LeitorDaFilaSql,
  ServicoDeRevisao,
  METRICA_CASOS,
  METRICA_P90,
  SQL_CONTADORES,
  SQL_VISTA_SLA,
  type ClienteSql,
  type Contador,
  type LeitorDaFila,
  type LinhaDaVista,
  type ServicoDoCiclo,
} from "../src/revisao/index.ts";

import { SEXTA, montarRevisao, revisor } from "./apoio/revisao.ts";

const H = 3_600_000;

/** Um leitor que lê a fila em memória: um caso por linha, a primeira decisão do registo. */
function leitorDaMemoria(m: ReturnType<typeof montarRevisao>): LeitorDaFila {
  return {
    async vista(): Promise<readonly LinhaDaVista[]> {
      return [...m.repositorio.casos.values()]
        .filter((c) => c.estado !== "em_triagem_automatica")
        .map((c) => ({
          tipo: c.tipo,
          estado: c.estado,
          filaEm: c.filaEm,
          primeiraDecisaoEm: m.repositorio.registo.find((d) => d.casoId === c.id)?.em ?? null,
        }));
    },
    async contadores(): Promise<readonly Contador[]> {
      return [];
    },
  };
}

/** O servico do apoio, por delegacao: um duplo pode trocar um metodo sem perder os campos privados. */
function delegado(m: ReturnType<typeof montarRevisao>): ServicoDoCiclo {
  return {
    drenarTriagem: (l) => m.servico.drenarTriagem(l),
    alertarSla: () => m.servico.alertarSla(),
    reaplicarEfeitos: (id) => m.servico.reaplicarEfeitos(id),
    amostrar: (o, t) => m.servico.amostrar(o, t),
  };
}

describe("ciclo da fila (criterio 6)", () => {
  it("uma volta drena a triagem de ontem, da o alerta dos 80% e mede", async () => {
    const m = montarRevisao({ agora: SEXTA, limiares: { quotaPorOrigemPorDia: 1 } });
    const rede = "a".repeat(64);
    const a = m.onboarding({ redeHmac: rede });
    const b = m.onboarding({ redeHmac: rede });
    assert.equal((await m.abrir(a)).estado, "aberto");
    assert.equal((await m.abrir(b)).estado, "em_triagem_automatica");
    const ciclo = new CicloDaFila({ servico: m.servico, leitor: leitorDaMemoria(m) });

    // Segunda 09:00 de Luanda: o caso de sexta passou os 80% e a quota de hoje
    // deixa entrar o de ontem.
    m.definir(new Date("2026-11-16T08:00:00Z"));
    const r = await ciclo.correr();
    assert.equal(r.entraram, 1);
    assert.equal(r.alertas, 1);
    assert.deepEqual(r.falhas, []);
    assert.equal(m.alertas.filter((x) => x.motivo === "sla_80").length, 1);
    assert.match(ciclo.metricas.exposicao(), new RegExp(`${METRICA_CASOS}\\{tipo="kyc",estado="aberto"\\} 2`));

    // A segunda volta nao alerta outra vez nem drena o que ja entrou.
    const r2 = await ciclo.correr();
    assert.equal(r2.entraram, 0);
    assert.equal(r2.alertas, 0);
  });

  it("reaplica o efeito que falhou, e larga o caso que afinal nao fechou", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const o = m.onboarding();
    const aberto = await m.abrir(o);
    assert.ok(aberto.estado === "aberto");
    await m.servico.decidir(revisor(), aberto.caso.id, "aprovar");
    // O aviso «falhou» na decisão: a consola marca o caso.
    const ciclo = new CicloDaFila({ servico: m.servico, leitor: leitorDaMemoria(m) });
    await ciclo.efeitoFalhou(aberto.caso.id);
    const pendente = await m.abrir(m.onboarding());
    assert.ok(pendente.estado === "aberto");
    await ciclo.efeitoFalhou(pendente.caso.id);
    await ciclo.efeitoFalhou(randomUUID());

    const avisosAntes = m.avisos.length;
    const r = await ciclo.correr();
    assert.equal(r.reaplicados, 1);
    assert.equal(r.porReaplicar, 0);
    assert.equal(m.avisos.length, avisosAntes + 1, "o aviso volta a sair");
    assert.deepEqual(await ciclo.efeitos.pendentes(10), [], "o pendente e o inexistente saem da lista");
  });

  it("um efeito que volta a falhar fica para a volta seguinte, e a volta diz que passo falhou", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const aberto = await m.abrir(m.onboarding());
    assert.ok(aberto.estado === "aberto");
    await m.servico.decidir(revisor(), aberto.caso.id, "aprovar");
    const falso = delegado(m);
    let tentativas = 0;
    falso.reaplicarEfeitos = async () => {
      tentativas++;
      throw new Error("sms em baixo");
    };
    falso.alertarSla = async () => {
      throw new Error("alerta em baixo");
    };
    const ciclo = new CicloDaFila({ servico: falso, leitor: leitorDaMemoria(m) });
    await ciclo.efeitoFalhou(aberto.caso.id);
    const r = await ciclo.correr();
    assert.deepEqual(r.falhas, ["alertar", "reaplicar"]);
    assert.equal(r.porReaplicar, 1);
    assert.deepEqual(await ciclo.efeitos.pendentes(10), [aberto.caso.id]);
    // O drenar e o medir correram mesmo assim.
    assert.match(ciclo.metricas.exposicao(), new RegExp(`${METRICA_CASOS}\\{tipo="kyc",estado="decidido"\\} 1`));
    await ciclo.correr();
    assert.equal(tentativas, 2);
  });

  it("duas voltas pedidas ao mesmo tempo sao uma", async () => {
    const m = montarRevisao({ agora: SEXTA });
    let drenagens = 0;
    const falso = delegado(m);
    falso.drenarTriagem = async () => {
      drenagens++;
      await new Promise((r) => setTimeout(r, 10));
      return 0;
    };
    const ciclo = new CicloDaFila({ servico: falso, leitor: leitorDaMemoria(m) });
    const [x, y] = await Promise.all([ciclo.correr(), ciclo.correr()]);
    assert.equal(drenagens, 1);
    assert.equal(x, y);
  });

  it("o gancho da aprovacao automatica amostra dentro das semanas e fora da quota", async () => {
    const m = montarRevisao({ agora: SEXTA, inicioDaAmostragem: new Date(SEXTA.getTime() - 24 * H) });
    const ciclo = new CicloDaFila({ servico: m.servico, leitor: leitorDaMemoria(m) });
    let amostrados = 0;
    for (let i = 0; i < 200; i++) {
      const r = await ciclo.aprovacaoAutomatica(randomUUID(), randomUUID());
      if (r !== null) {
        assert.equal(r.estado, "aberto");
        if (r.estado === "aberto") assert.equal(r.caso.tipo, "auditoria");
        amostrados++;
      }
    }
    assert.ok(amostrados > 10 && amostrados < 80, String(amostrados));
  });

  it("o agendamento recusa um intervalo abaixo de um segundo e para quando se pede", () => {
    const m = montarRevisao();
    const ciclo = new CicloDaFila({ servico: m.servico, leitor: leitorDaMemoria(m) });
    assert.throws(() => ciclo.agendar(10, () => {}), RangeError);
    const parar = ciclo.agendar(60_000, () => {});
    parar();
  });

  it("o leitor sobre a base usa as duas consultas da 0048 e converte as linhas", async () => {
    const pedidos: string[] = [];
    const cliente: ClienteSql = {
      async query<T>(texto: string): Promise<{ rows: readonly T[] }> {
        pedidos.push(texto);
        if (texto === SQL_VISTA_SLA) {
          return {
            rows: [
              { tipo: "kyc", estado: "decidido", fila_at: "2026-11-13T09:00:00Z", primeira_decisao_at: "2026-11-13T10:00:00Z" },
            ] as unknown as T[],
          };
        }
        return { rows: [{ tipo: "auditoria", motivo: "amostra", decisao: "rejeitar", n: "3" }] as unknown as T[] };
      },
    };
    const leitor = new LeitorDaFilaSql(cliente);
    const vista = await leitor.vista();
    const contadores = await leitor.contadores();
    assert.deepEqual(pedidos, [SQL_VISTA_SLA, SQL_CONTADORES]);
    assert.equal(vista[0]!.primeiraDecisaoEm!.toISOString(), "2026-11-13T10:00:00.000Z");
    assert.equal(contadores[0]!.n, 3);
    const m = montarRevisao();
    const ciclo = new CicloDaFila({ servico: m.servico, leitor });
    await ciclo.correr();
    assert.match(ciclo.metricas.exposicao(), new RegExp(`${METRICA_P90} 3600`));
  });
});

// ------------------------------------------------- os achados da revisao adversarial

/** O servico sobre os duplos do apoio, com um aviso que falha quando se pede. */
function comAvisoQueFalha(m: ReturnType<typeof montarRevisao>) {
  const estado = { falhar: true, avisos: [] as { aviso: string; motivo: string | null }[] };
  const servico = new ServicoDeRevisao({
    repositorio: m.repositorio,
    onboardings: m.onboardings,
    auditoria: m.auditoria,
    aviso: {
      async avisar(p) {
        if (estado.falhar) throw new Error("agregador em baixo");
        estado.avisos.push({ aviso: p.aviso, motivo: p.motivoPublico });
      },
    },
    alerta: () => {},
    cifra: { cifrar: async (b) => b, decifrar: async (b) => b },
    dados: { ler: async () => null },
    documentos: { url: async () => "x" },
    screening: { gravar: async () => {} },
    relogio: () => m.agora(),
  });
  const ciclo = new CicloDaFila({ servico, leitor: leitorDaMemoria(m) });
  return { servico, ciclo, estado };
}

/** O efeito por aplicar que a consola marcaria. */
async function marcarSeFalhar(ciclo: CicloDaFila, p: Promise<unknown>): Promise<void> {
  try {
    await p;
  } catch (erro) {
    assert.ok(erro instanceof EfeitoPorAplicarError, String(erro));
    await ciclo.efeitoFalhou(erro.casoId);
  }
}

describe("ciclo: os achados da revisao adversarial", () => {
  it("(1) o aviso de um pedir_info que falhou volta a sair, com o caso ainda pendente", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const { servico, ciclo, estado } = comAvisoQueFalha(m);
    const o = m.onboarding();
    const c = await m.abrir(o);
    assert.ok(c.estado === "aberto");
    await marcarSeFalhar(ciclo, servico.decidir(revisor(), c.caso.id, "pedir_info"));
    assert.deepEqual(await ciclo.efeitos.pendentes(10), [c.caso.id]);
    estado.falhar = false;
    const r = await ciclo.correr();
    assert.equal(r.reaplicados, 1);
    assert.deepEqual(estado.avisos, [{ aviso: "pedir_info", motivo: "informacao_em_falta" }]);
    assert.equal(m.repositorio.casos.get(c.caso.id)!.estado, "em_analise", "o caso continua pendente");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "kyc_pendente");
  });

  it("(2) reaplicar um caso cujo onboarding outro caso aprovou depois nao manda segundo aprovado", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const { servico, ciclo, estado } = comAvisoQueFalha(m);
    const o = m.onboarding();
    const a = await m.abrir(o);
    const b = await m.abrir(o, { tipo: "duplicado", motivoCodigo: "duplicado" });
    assert.ok(a.estado === "aberto" && b.estado === "aberto");
    // A aprova com B pendente: não aprova o onboarding, nem avisa. Simula-se
    // a falha do efeito marcando-o à mão.
    await servico.decidir(revisor(), a.caso.id, "aprovar");
    await ciclo.efeitoFalhou(a.caso.id);
    m.avancar(60_000);
    estado.falhar = false;
    await servico.decidir(revisor(), b.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
    assert.deepEqual(estado.avisos, [{ aviso: "aprovado", motivo: null }]);
    await ciclo.correr();
    assert.deepEqual(estado.avisos, [{ aviso: "aprovado", motivo: null }], "B ja avisou; reaplicar A nao repete");
  });

  it("(2) e o controlo: o caso que aprovou, e cujo aviso falhou, reenvia-o", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const { servico, ciclo, estado } = comAvisoQueFalha(m);
    const o = m.onboarding();
    const a = await m.abrir(o);
    assert.ok(a.estado === "aberto");
    await marcarSeFalhar(ciclo, servico.decidir(revisor(), a.caso.id, "aprovar"));
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
    estado.falhar = false;
    await ciclo.correr();
    assert.deepEqual(estado.avisos, [{ aviso: "aprovado", motivo: null }]);
  });

  it("(M15) reaplicar nao aprova um onboarding que a decisao original nao aprovava", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const { servico, ciclo, estado } = comAvisoQueFalha(m);
    estado.falhar = false;
    const o = m.onboarding({ fase: "kyc_pendente" });
    const c = await m.abrir(o, { tipo: "categoria", motivoCodigo: "screening:x", evidencias: [] });
    assert.ok(c.estado === "aberto");
    await servico.decidir(revisor(), c.caso.id, "aprovar");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "kyc_pendente");
    await ciclo.efeitoFalhou(c.caso.id);
    await ciclo.correr();
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "kyc_pendente", "uma categoria nao aprova com o KYC por decidir");
    assert.deepEqual(estado.avisos, []);
  });

  it("(3) um recurso aberto nao se reaplica: o dono nao recebe outra vez o rejeitado", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const { servico, ciclo, estado } = comAvisoQueFalha(m);
    estado.falhar = false;
    const c = await m.abrir(m.onboarding());
    assert.ok(c.estado === "aberto");
    await servico.decidir(revisor(), c.caso.id, "rejeitar");
    await servico.abrirRecurso(c.caso.id);
    const antes = estado.avisos.length;
    await ciclo.efeitoFalhou(c.caso.id);
    const r = await ciclo.correr();
    assert.equal(r.reaplicados, 0);
    assert.equal(estado.avisos.length, antes);
    assert.deepEqual(await ciclo.efeitos.pendentes(10), []);
  });

  it("(3) um erro antes de a decisao ficar registada nao e um efeito por aplicar", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const c = await m.abrir(m.onboarding());
    assert.ok(c.estado === "aberto");
    const original = m.repositorio.registarDecisao.bind(m.repositorio);
    m.repositorio.registarDecisao = async () => {
      throw new Error("base em baixo");
    };
    await assert.rejects(m.servico.decidir(revisor(), c.caso.id, "rejeitar"), (e: unknown) => !(e instanceof EfeitoPorAplicarError));
    m.repositorio.registarDecisao = original;
  });

  it("(M18) um drenar que falha nao para o alertar, o reaplicar nem o medir", async () => {
    const m = montarRevisao({ agora: SEXTA });
    const falso = delegado(m);
    falso.drenarTriagem = async () => {
      throw new Error("triagem em baixo");
    };
    let alertou = false;
    falso.alertarSla = async () => {
      alertou = true;
      return 0;
    };
    await m.abrir(m.onboarding());
    const ciclo = new CicloDaFila({ servico: falso, leitor: leitorDaMemoria(m) });
    const r = await ciclo.correr();
    assert.deepEqual(r.falhas, ["drenar"]);
    assert.ok(alertou);
    assert.match(ciclo.metricas.exposicao(), new RegExp(`${METRICA_CASOS}\\{tipo="kyc",estado="aberto"\\} 1`));
  });
});
