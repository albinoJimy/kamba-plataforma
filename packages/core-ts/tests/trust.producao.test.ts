/**
 * Trust & Safety em produção (KAM-200): as métricas, a contagem no serviço, a
 * transição do tenant pela porta do KAM-092 e o ciclo das varreduras.
 *
 * O que só a base prova — a porta verdadeira, o `tenant_state_log`, o evento no
 * *outbox*, os *triggers* da `0069` — está em `../tests_bd/trust.bd.test.ts`
 * (suite `tests_lote` do *gate* 8). Aqui mede-se a forma: que instruções saem,
 * por que ordem, com que argumentos, e o que se recusa antes de chegar à base.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { ConjuntoSql } from "../src/revisao/sql.ts";
import {
  ACTOR_DAS_VARREDURAS,
  CicloDoTrust,
  EstadoDosTenantsEmMemoria,
  EstadoDosTenantsSql,
  JUSTIFICACAO_DA_MUDANCA_DE_CONTA,
  MOTIVO_DO_RECURSO_PROVIDO,
  MOTIVO_DO_TRUST,
  MetricasDoTrust,
  PASSOS,
  RepositorioDeTrustEmMemoria,
  SQL_AUDITAR_VARREDURA,
  SQL_ENCERRAMENTOS_POR_FECHAR,
  SQL_ESTADO_DO_TENANT,
  SQL_FOTOS_REPETIDAS,
  SQL_MUDANCAS_DE_CONTA_SEM_CASO,
  SQL_NAO_ENTREGUES,
  SQL_TRUST_DE_ONDE_VEIO,
  SQL_TRUST_EMITIR,
  SQL_TRUST_SUSPENSAO_E_DO_TRUST,
  SQL_TRUST_TRANSITAR,
  ServicoDeTrust,
  TIPOS_DE_SINAL,
  TransicaoDeOutroEstadoError,
  VARREDURAS,
  type FilaDoTrust,
} from "../src/trust/index.ts";

type Resposta = { rows: Record<string, unknown>[] };
type Tratador = (texto: string, valores: readonly unknown[]) => Resposta | undefined;

/** Um `pg.Pool` que regista cada consulta, com a ligação que a correu. */
class ConjuntoFalso implements ConjuntoSql {
  readonly consultas: { ligacao: string; texto: string; valores: readonly unknown[] }[] = [];
  readonly devolvidas: (Error | boolean | undefined)[] = [];
  #n = 0;
  readonly tratar: Tratador;
  constructor(tratar: Tratador = () => undefined) {
    this.tratar = tratar;
  }

  async query<T = Record<string, unknown>>(texto: string, valores: readonly unknown[] = []) {
    this.consultas.push({ ligacao: "conjunto", texto, valores });
    return (this.tratar(texto, valores) ?? { rows: [] }) as unknown as { readonly rows: readonly T[] };
  }

  async connect() {
    const nome = `ligacao-${++this.#n}`;
    const self = this;
    return {
      async query<T = Record<string, unknown>>(texto: string, valores: readonly unknown[] = []) {
        self.consultas.push({ ligacao: nome, texto, valores });
        return (self.tratar(texto, valores) ?? { rows: [] }) as unknown as { readonly rows: readonly T[] };
      },
      release(erro?: Error | boolean) {
        self.devolvidas.push(erro);
      },
    };
  }

  com(texto: string) {
    return this.consultas.filter((c) => c.texto === texto);
  }
}

const T = "11111111-1111-4111-8111-111111111111";

// ------------------------------------------------------------------ métricas

describe("as métricas de T&S", () => {
  it("nascem a zero em todo o domínio, e um valor fora dele não abre série", () => {
    const m = new MetricasDoTrust();
    const corpo = m.exposicao();
    for (const t of TIPOS_DE_SINAL) assert.match(corpo, new RegExp(`^ts_sinais_total\\{tipo="${t}"\\} 0$`, "m"));
    for (const p of PASSOS) {
      for (const o of ["automatica", "humana"]) {
        assert.match(corpo, new RegExp(`^ts_sancoes_total\\{passo="${p}",origem="${o}"\\} 0$`, "m"));
      }
    }
    for (const v of VARREDURAS) assert.match(corpo, new RegExp(`^ts_varreduras_total\\{varredura="${v}",desfecho="falhou"\\} 0$`, "m"));
    m.sinal("auto_compra");
    m.sancao("suspensao", "humana");
    m.varredura("fotos", "concluida");
    m.sinal("inventado" as never);
    const depois = m.exposicao();
    assert.match(depois, /^ts_sinais_total\{tipo="auto_compra"\} 1$/m);
    assert.match(depois, /^ts_sancoes_total\{passo="suspensao",origem="humana"\} 1$/m);
    assert.match(depois, /^ts_varreduras_total\{varredura="fotos",desfecho="concluida"\} 1$/m);
    assert.doesNotMatch(depois, /inventado/);
    // OBS-I: nenhuma etiqueta é um identificador.
    assert.doesNotMatch(depois, /tenant|[0-9a-f]{8}-[0-9a-f]{4}/);
  });

  it("o serviço conta o que é novo: o sinal repetido e a escada repetida não contam", async () => {
    const m = new MetricasDoTrust();
    const agora = new Date("2026-11-17T10:00:00Z");
    const s = new ServicoDeTrust({ repositorio: new RepositorioDeTrustEmMemoria(() => agora), relogio: () => agora, contadores: m });
    const sinal = { tenantId: T, tipo: "auto_compra" as const, refEvento: "22222222-2222-4222-8222-222222222222", detalhe: {}, ocorridoEm: agora };
    await s.sinalizar(sinal);
    await s.sinalizar(sinal);
    await s.sinalizar({ ...sinal, tipo: "burla_provavel", refEvento: T });
    const corpo = m.exposicao();
    assert.match(corpo, /^ts_sinais_total\{tipo="auto_compra"\} 1$/m);
    assert.match(corpo, /^ts_sinais_total\{tipo="burla_provavel"\} 1$/m);
    // 35 + 35 = 70: o aviso com o primeiro sinal, e a limitação com o segundo.
    assert.match(corpo, /^ts_sancoes_total\{passo="aviso",origem="automatica"\} 1$/m);
    assert.match(corpo, /^ts_sancoes_total\{passo="limitacao",origem="automatica"\} 1$/m);
  });
});

// ------------------------------------------------- a transição pela porta

function porta(o: { estado: string; doTrust?: boolean; mudou?: boolean; veio?: string }) {
  return new ConjuntoFalso((texto) => {
    if (texto === SQL_ESTADO_DO_TENANT) return { rows: [{ estado: o.estado }] };
    if (texto === SQL_TRUST_SUSPENSAO_E_DO_TRUST) return { rows: [{ do_trust: o.doTrust ?? true }] };
    if (texto === SQL_TRUST_TRANSITAR) return { rows: [{ mudou: o.mudou ?? true }] };
    if (texto === SQL_TRUST_DE_ONDE_VEIO) return { rows: [{ de: o.veio ?? o.estado }] };
    if (texto === SQL_TRUST_EMITIR) return { rows: [{ event_id: "e" }] };
    return undefined;
  });
}

describe("a transição do tenant pela porta do KAM-092 (critério 8)", () => {
  it("a suspensão passa pelo transition_tenant e emite tenant.suspended na mesma transacção", async () => {
    const c = porta({ estado: "ativo" });
    assert.equal(await new EstadoDosTenantsSql(c).transitar(T, ["ativo", "restrito"], "suspenso", "rev-1"), true);
    assert.deepEqual(c.com(SQL_TRUST_TRANSITAR)[0]?.valores, [T, "suspenso", MOTIVO_DO_TRUST, "rev-1"]);
    assert.deepEqual(c.com(SQL_TRUST_EMITIR)[0]?.valores, ["tenant.suspended", T, JSON.stringify({ motivo: MOTIVO_DO_TRUST })]);
    const textos = c.consultas.map((x) => x.texto);
    assert.equal(textos[0], "BEGIN");
    assert.equal(textos.at(-1), "COMMIT");
    assert.ok(new Set(c.consultas.map((x) => x.ligacao)).size === 1, "tudo numa ligação dedicada");
    assert.deepEqual(c.devolvidas, [undefined]);
  });

  it("o encerramento emite tenant.closed, e o regresso a ativo emite tenant.reactivated sem motivo", async () => {
    const e = porta({ estado: "suspenso" });
    await new EstadoDosTenantsSql(e).transitar(T, ["suspenso"], "encerrado", "sistema:1.0.0");
    assert.equal(e.com(SQL_TRUST_EMITIR)[0]?.valores[0], "tenant.closed");
    const a = porta({ estado: "suspenso" });
    await new EstadoDosTenantsSql(a).transitar(T, ["suspenso"], "ativo", "rev-2");
    assert.deepEqual(a.com(SQL_TRUST_TRANSITAR)[0]?.valores, [T, "ativo", MOTIVO_DO_RECURSO_PROVIDO, "rev-2"]);
    assert.deepEqual(a.com(SQL_TRUST_EMITIR)[0]?.valores, ["tenant.reactivated", T, "{}"]);
  });

  it("fora dos estados de partida não transita nem emite", async () => {
    const c = porta({ estado: "onboarding" });
    assert.equal(await new EstadoDosTenantsSql(c).transitar(T, ["ativo", "restrito"], "suspenso", "rev"), false);
    assert.equal(c.com(SQL_TRUST_TRANSITAR).length, 0);
    assert.equal(c.com(SQL_TRUST_EMITIR).length, 0);
  });

  it("um recurso de T&S não levanta a suspensão da régua de cobrança", async () => {
    const c = porta({ estado: "suspenso", doTrust: false });
    assert.equal(await new EstadoDosTenantsSql(c).transitar(T, ["suspenso"], "ativo", "rev"), false);
    assert.deepEqual(c.com(SQL_TRUST_SUSPENSAO_E_DO_TRUST)[0]?.valores, [T, MOTIVO_DO_TRUST]);
    assert.equal(c.com(SQL_TRUST_TRANSITAR).length, 0);
  });

  it("a porta repetida (já no destino) não emite", async () => {
    const c = porta({ estado: "ativo", mudou: false });
    assert.equal(await new EstadoDosTenantsSql(c).transitar(T, ["ativo"], "suspenso", "rev"), false);
    assert.equal(c.com(SQL_TRUST_EMITIR).length, 0);
  });

  it("vinda de um estado que não se pediu, desfaz-se e devolve a ligação com o erro", async () => {
    const c = porta({ estado: "ativo", veio: "restrito" });
    await assert.rejects(new EstadoDosTenantsSql(c).transitar(T, ["ativo"], "suspenso", "rev"), TransicaoDeOutroEstadoError);
    assert.equal(c.consultas.at(-1)?.texto, "ROLLBACK");
    assert.equal(c.com(SQL_TRUST_EMITIR).length, 0);
    assert.ok(c.devolvidas[0] instanceof Error);
  });

  it("um destino que não é desta escada recusa-se antes da base", async () => {
    const c = porta({ estado: "ativo" });
    await assert.rejects(new EstadoDosTenantsSql(c).transitar(T, ["ativo"], "restrito", "rev"), RangeError);
    assert.equal(c.consultas.length, 0);
  });
});

// ------------------------------------------------------------ as varreduras

const SINAL = "33333333-3333-4333-8333-333333333333";

function ciclo(o: { falhaNas?: string; mudanca?: boolean } = {}) {
  const agora = new Date("2026-11-17T10:00:00Z");
  const lote = new ConjuntoFalso((texto) => {
    if (o.falhaNas !== undefined && texto === o.falhaNas) throw new Error("base em baixo");
    if (texto === SQL_MUDANCAS_DE_CONTA_SEM_CASO && o.mudanca === true) {
      return { rows: [{ id: SINAL, tenant_id: T, ref_evento: SINAL, ocorrido_em: agora }] };
    }
    return undefined;
  });
  const propostas: Parameters<FilaDoTrust["abrir"]>[0][] = [];
  const fila: FilaDoTrust = {
    abrir: async (p) => {
      propostas.push(p);
      return { estado: "aberto", caso: { id: "c" } as never, repetido: false };
    },
    abrirRecurso: async () => {
      throw new Error("nao usado");
    },
  };
  const metricas = new MetricasDoTrust();
  const servico = new ServicoDeTrust({
    repositorio: new RepositorioDeTrustEmMemoria(() => agora),
    tenants: new EstadoDosTenantsEmMemoria(),
    fila,
    relogio: () => agora,
    contadores: metricas,
  });
  return { lote, propostas, metricas, c: new CicloDoTrust({ lote, servico, metricas, relogio: () => agora }) };
}

describe("o ciclo das varreduras no lote (critério 2)", () => {
  it("corre as quatro, e cada corrida deixa uma linha batch.run com o nome dela", async () => {
    const { lote, c, metricas } = ciclo();
    const r = await c.correr();
    assert.deepEqual(r.falhas, []);
    assert.deepEqual(Object.keys(r.feitas).sort(), [...VARREDURAS].sort());
    const auditorias = lote.com(SQL_AUDITAR_VARREDURA);
    assert.deepEqual(
      auditorias.map((a) => a.valores),
      VARREDURAS.map((v) => [ACTOR_DAS_VARREDURAS, v, `${v}:0`]),
    );
    for (const v of VARREDURAS) assert.match(metricas.exposicao(), new RegExp(`varredura="${v}",desfecho="concluida"\\} 1$`, "m"));
  });

  it("a varredura e a sua auditoria correm na mesma transacção, numa ligação dedicada", async () => {
    const { lote, c } = ciclo();
    await c.correr();
    const varrer = lote.com(SQL_NAO_ENTREGUES)[0];
    assert.ok(varrer !== undefined && varrer.ligacao !== "conjunto");
    const naLigacao = lote.consultas.filter((x) => x.ligacao === varrer.ligacao).map((x) => x.texto);
    assert.deepEqual(naLigacao, ["BEGIN", SQL_NAO_ENTREGUES, SQL_AUDITAR_VARREDURA, "COMMIT"]);
  });

  it("uma que falha não pára as outras, e diz-se pelo nome", async () => {
    const { lote, c, metricas } = ciclo({ falhaNas: SQL_FOTOS_REPETIDAS });
    const r = await c.correr();
    assert.deepEqual(r.falhas, ["fotos"]);
    assert.ok(lote.com(SQL_ENCERRAMENTOS_POR_FECHAR).length === 1, "as encerradas correram depois");
    assert.match(metricas.exposicao(), /varredura="fotos",desfecho="falhou"\} 1$/m);
    assert.ok(!lote.com(SQL_AUDITAR_VARREDURA).some((a) => a.valores[1] === "fotos"), "a corrida que falhou não fica auditada");
  });

  it("uma mudança de conta sem caso abre uma proposta de suspensão, com o sinal e a justificação", async () => {
    const { c, propostas } = ciclo({ mudanca: true });
    const r = await c.correr();
    assert.equal(r.feitas.mudancas_de_conta, 1);
    assert.equal(propostas.length, 1);
    const p = propostas[0]!;
    assert.equal(p.tipo, "trust");
    assert.equal(p.tenantId, T);
    assert.equal(p.motivoCodigo, `sancao_suspensao:conta.${SINAL}`);
    assert.deepEqual(p.evidencias[0], { tipo: "ts_signal", ref: SINAL });
    assert.match(String(p.evidencias[1]?.ref), new RegExp(JUSTIFICACAO_DA_MUDANCA_DE_CONTA.slice(0, 20)));
  });

  it("duas voltas pedidas ao mesmo tempo são uma", async () => {
    const { lote, c } = ciclo();
    await Promise.all([c.correr(), c.correr()]);
    assert.equal(lote.com(SQL_NAO_ENTREGUES).length, 1);
  });
});
