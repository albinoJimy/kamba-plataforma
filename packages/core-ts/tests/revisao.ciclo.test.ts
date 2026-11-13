/**
 * O *job* da fila (KAM-196, critério 6): drenar, alertar, reaplicar e medir.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import {
  CicloDaFila,
  LeitorDaFilaSql,
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
