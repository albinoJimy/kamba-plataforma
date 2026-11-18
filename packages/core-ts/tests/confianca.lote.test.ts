/**
 * O recálculo da confiança a correr, sem base (KAM-203).
 *
 * O que se mede aqui é a **forma** da transacção e da volta, sobre ligações
 * falsas que registam cada instrução: a ordem das duas transacções, o
 * `READ COMMITTED` como primeira instrução do lote, o que se devolve ao conjunto
 * quando algo falha, a linha `batch.run` de cada volta, e as métricas — que só
 * contam depois do `COMMIT` e não levam tenant. O que só a base prova (a subida
 * com cinco pedidos, a descida, a aprovação, o isolamento e a reentrega) está em
 * `../tests_bd/confianca.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CicloDaConfianca,
  JOB_DO_RECALCULO,
  MetricasDaConfianca,
  RecalculoDaConfianca,
  SQL_AUDITAR_RECALCULO,
  SQL_DEFINIR_NIVEL,
  SQL_FACTOS_NEGATIVOS,
  SQL_K1_COMPLETO,
  SQL_NIVEL_DO_TENANT,
  SQL_PEDIDOS_ENTREGUES,
  SQL_READ_COMMITTED,
  SQL_TENANTS_A_DESCER,
  SQL_TENANTS_A_RECALCULAR,
  SQL_TRANCAR,
} from "../src/confianca/index.ts";
import { concluirJob, correrDepois } from "../src/eventos/trabalhador_bullmq.ts";
import { Adiar } from "../src/eventos/consumo.ts";
import type { Envelope } from "../src/eventos/envelope.ts";
import type { ConjuntoSql } from "../src/revisao/sql.ts";
import { SQL_DEFINIR_CONTEXTO } from "../src/tenant_guard/index.ts";
import { SQL_SANCOES_DO_TENANT_LOTE } from "../src/trust/sql.ts";

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const AGORA = new Date("2026-11-18T12:00:00.000Z");

const NOMES = new Map<string, string>([
  [SQL_READ_COMMITTED, "READ_COMMITTED"],
  [SQL_TRANCAR, "TRANCAR"],
  [SQL_NIVEL_DO_TENANT, "NIVEL"],
  [SQL_K1_COMPLETO, "K1"],
  [SQL_PEDIDOS_ENTREGUES, "PEDIDOS"],
  [SQL_FACTOS_NEGATIVOS, "NEGATIVOS"],
  [SQL_SANCOES_DO_TENANT_LOTE, "SANCOES"],
  [SQL_DEFINIR_NIVEL, "DEFINIR"],
  [SQL_DEFINIR_CONTEXTO, "CONTEXTO"],
  [SQL_TENANTS_A_RECALCULAR, "TENANTS"],
  [SQL_TENANTS_A_DESCER, "A_DESCER"],
  [SQL_AUDITAR_RECALCULO, "AUDITAR"],
]);

type Linhas = { rows: Record<string, unknown>[]; rowCount: number };

/** A base falsa: um nível por tenant, K1 completo para quem estiver em `k1`. */
class Base {
  readonly diario: string[] = [];
  readonly parametros: { nome: string; valores: readonly unknown[] }[] = [];
  readonly niveis = new Map<string, number>();
  readonly k1 = new Set<string>();
  tenants: string[] = [];
  aDescer: string[] = [];
  /** Uma instrução que falha (pelo nome), e em que tenant. */
  falhar: { nome: string; tenant?: string } | null = null;

  responder(quem: string, sql: string, valores: readonly unknown[] = []): Linhas {
    const nome = NOMES.get(sql) ?? sql.trim().split(/\s+/)[0]!;
    this.diario.push(`${quem}:${nome}`);
    this.parametros.push({ nome, valores });
    if (this.falhar !== null && this.falhar.nome === nome && (this.falhar.tenant === undefined || valores[0] === this.falhar.tenant)) {
      throw new Error(`falha de ensaio em ${nome}`);
    }
    const t = String(valores[0] ?? "");
    const vazio = { rows: [], rowCount: 0 };
    switch (nome) {
      case "NIVEL": {
        const n = this.niveis.get(t);
        if (n === undefined) return vazio;
        const tecto = n === 0 ? "5000000" : "15000000";
        return { rows: [{ nivel: n, tecto_pedido_minor: tecto, motivo: "k1_completo", desde: AGORA }], rowCount: 1 };
      }
      case "K1":
        return { rows: [{ completo: this.k1.has(t) }], rowCount: 1 };
      case "NEGATIVOS":
        return { rows: [{ ultima_disputa_aceite: null, ultimo_sinal_alto: null }], rowCount: 1 };
      case "DEFINIR": {
        const nivel = Number(valores[1]);
        if (this.niveis.get(t) === nivel) return vazio;
        this.niveis.set(t, nivel);
        return { rows: [{ nivel }], rowCount: 1 };
      }
      case "TENANTS":
        return { rows: this.tenants.map((tenant_id) => ({ tenant_id })), rowCount: this.tenants.length };
      case "A_DESCER":
        return { rows: this.aDescer.map((tenant_id) => ({ tenant_id })), rowCount: this.aDescer.length };
      default:
        return vazio;
    }
  }
}

class Ligacao {
  libertada: Error | boolean | undefined = undefined;
  readonly quem: string;
  readonly base: Base;
  constructor(quem: string, base: Base) {
    this.quem = quem;
    this.base = base;
  }
  async query(sql: string, valores?: readonly unknown[]): Promise<Linhas> {
    return this.base.responder(this.quem, sql, valores);
  }
  release(erro?: Error | boolean): void {
    this.libertada = erro ?? true;
  }
}

class Conjunto {
  readonly ligacoes: Ligacao[] = [];
  readonly quem: string;
  readonly base: Base;
  constructor(quem: string, base: Base) {
    this.quem = quem;
    this.base = base;
  }
  async connect(): Promise<Ligacao> {
    const l = new Ligacao(this.quem, this.base);
    this.ligacoes.push(l);
    return l;
  }
  async query(sql: string, valores?: readonly unknown[]): Promise<Linhas> {
    return this.base.responder(`${this.quem}-pool`, sql, valores);
  }
}

function montar(base = new Base()) {
  const lote = new Conjunto("lote", base);
  const app = new Conjunto("app", base);
  const metricas = new MetricasDaConfianca();
  const recalculo = new RecalculoDaConfianca({
    lote: lote as unknown as ConjuntoSql,
    app: app as unknown as ConjuntoSql,
    consumidorDeTrust: "trust",
    metricas,
    relogio: () => AGORA,
  });
  return { base, lote, app, metricas, recalculo };
}

function serie(metricas: MetricasDaConfianca, linha: RegExp): number {
  const m = metricas.exposicao().split("\n").find((l) => linha.test(l));
  assert.ok(m !== undefined, `serie em falta: ${linha}`);
  return Number(m.split(" ").at(-1));
}

describe("o recálculo de um tenant: a transacção", () => {
  it("o READ COMMITTED é a primeira instrução do lote, e o lote, que escreve, confirma por último", async () => {
    const { base, recalculo } = montar();
    base.k1.add(A);
    const r = await recalculo.recalcular(A, "aprovacao");
    assert.deepEqual(r, { tenantId: A, nivel: 0, mudou: true, motivo: "k1_completo" });
    assert.deepEqual(base.diario, [
      "lote:BEGIN",
      "lote:READ_COMMITTED",
      "app:BEGIN",
      "app:CONTEXTO",
      "lote:TRANCAR",
      "lote:NIVEL",
      "lote:K1",
      "lote:SANCOES",
      "lote:DEFINIR",
      "app:COMMIT",
      "lote:COMMIT",
    ]);
    // O contexto da aplicação é o tenant, e a tranca também.
    assert.deepEqual(base.parametros.find((p) => p.nome === "CONTEXTO")?.valores, [A]);
    assert.deepEqual(base.parametros.find((p) => p.nome === "TRANCAR")?.valores, [A]);
  });

  it("a leitura dos pedidos e da independência é da aplicação, sob o tenant", async () => {
    const { base, recalculo } = montar();
    base.niveis.set(A, 0);
    await recalculo.recalcular(A, "entrega");
    assert.ok(base.diario.includes("app:PEDIDOS"), base.diario.join(" "));
    assert.ok(!base.diario.some((l) => l.startsWith("lote:PEDIDOS")));
  });

  it("uma falha desfaz as duas transacções, devolve as duas ligações com o erro e conta falhou", async () => {
    const { base, lote, app, metricas, recalculo } = montar();
    base.k1.add(A);
    base.falhar = { nome: "DEFINIR" };
    await assert.rejects(recalculo.recalcular(A, "diario"), /falha de ensaio em DEFINIR/);
    assert.deepEqual(base.diario.slice(-2), ["app:ROLLBACK", "lote:ROLLBACK"]);
    assert.ok(lote.ligacoes[0]!.libertada instanceof Error);
    assert.ok(app.ligacoes[0]!.libertada instanceof Error);
    assert.equal(serie(metricas, /origem="diario",desfecho="falhou"/), 1);
    assert.equal(serie(metricas, /motivo="k1_completo"/), 0, "uma mudança desfeita não conta");
  });

  it("um COMMIT da aplicação que falha desfaz a escrita do lote: o falhou não deixou nível", async () => {
    const { base, metricas, recalculo } = montar();
    base.k1.add(A);
    base.falhar = { nome: "COMMIT" };
    await assert.rejects(recalculo.recalcular(A, "entrega"), /falha de ensaio em COMMIT/);
    assert.deepEqual(base.diario.slice(-3), ["app:COMMIT", "app:ROLLBACK", "lote:ROLLBACK"]);
    assert.ok(!base.diario.includes("lote:COMMIT"), "o lote confirmou depois de a aplicacao falhar");
    assert.equal(serie(metricas, /origem="entrega",desfecho="falhou"/), 1);
  });

  it("a ligação do lote devolve-se mesmo quando a da aplicação não se obtém", async () => {
    const { lote, app, recalculo } = montar();
    app.connect = async () => {
      throw new Error("sem ligacao");
    };
    await assert.rejects(recalculo.recalcular(A, "diario"), /sem ligacao/);
    assert.ok(lote.ligacoes[0]!.libertada instanceof Error);
  });

  it("repetir sobre o mesmo estado não escreve, e conta sem_mudanca", async () => {
    const { base, metricas, recalculo } = montar();
    base.k1.add(A);
    assert.equal((await recalculo.recalcular(A, "entrega")).mudou, true);
    assert.equal((await recalculo.recalcular(A, "entrega")).mudou, false);
    assert.equal(base.diario.filter((l) => l === "lote:DEFINIR").length, 1);
    assert.equal(serie(metricas, /origem="entrega",desfecho="mudou"/), 1);
    assert.equal(serie(metricas, /origem="entrega",desfecho="sem_mudanca"/), 1);
    assert.equal(serie(metricas, /motivo="k1_completo"/), 1);
  });

  it("o recálculo de A só passa A à base", async () => {
    const { base, recalculo } = montar();
    base.k1.add(A);
    base.k1.add(B);
    await recalculo.recalcular(A, "diario");
    for (const p of base.parametros.filter((x) => ["TRANCAR", "NIVEL", "K1", "DEFINIR", "CONTEXTO", "SANCOES"].includes(x.nome))) {
      assert.equal(p.valores[0], A, `${p.nome} com outro tenant`);
    }
    assert.equal(base.niveis.has(B), false);
  });

  it("um nome de consumidor inválido recusa no arranque, e não no primeiro tenant", () => {
    const base = new Base();
    assert.throws(
      () =>
        new RecalculoDaConfianca({
          lote: new Conjunto("lote", base) as unknown as ConjuntoSql,
          app: new Conjunto("app", base) as unknown as ConjuntoSql,
          consumidorDeTrust: "Trust; DROP",
          metricas: new MetricasDaConfianca(),
        }),
      /consumidor de T&S invalido/,
    );
    assert.deepEqual(base.diario, []);
  });

  it("o job do comBatch tem nome, e o consumidor é o que se passou", () => {
    assert.match(JOB_DO_RECALCULO, /^[a-z][a-z0-9_]{2,62}$/);
    assert.equal(montar().recalculo.consumidorDeTrust, "trust");
  });
});

describe("a volta diária e a varredura das descidas", () => {
  it("a volta recalcula cada tenant numa transacção sua e deixa uma linha batch.run", async () => {
    const { base, lote, recalculo } = montar();
    base.tenants = [A, B];
    base.k1.add(A);
    base.k1.add(B);
    const ciclo = new CicloDaConfianca({ lote: lote as unknown as ConjuntoSql, recalculo });
    assert.deepEqual(await ciclo.correr(), { tenants: 2, mudaram: 2, falhas: 0 });
    assert.equal(lote.ligacoes.length, 2, "uma ligação, e uma transacção, por tenant");
    const auditorias = base.parametros.filter((p) => p.nome === "AUDITAR");
    assert.deepEqual(auditorias.map((p) => p.valores), [["onboarding-lote", "recalculo_diario", "recalculo_diario:2:2:0"]]);
    assert.equal(base.diario.at(-1), "lote-pool:AUDITAR", "a linha da corrida vem depois dos tenants");
    // Outra volta sobre o mesmo estado: nada muda, e a corrida fica na mesma.
    assert.deepEqual(await ciclo.correr(), { tenants: 2, mudaram: 0, falhas: 0 });
    assert.equal(base.diario.filter((l) => l === "lote:DEFINIR").length, 2);
    assert.equal(base.parametros.filter((p) => p.nome === "AUDITAR").length, 2);
  });

  it("um tenant que falha não pára os seguintes, e a linha da corrida conta-o", async () => {
    const { base, lote, metricas, recalculo } = montar();
    base.tenants = [A, B];
    base.k1.add(A);
    base.k1.add(B);
    base.falhar = { nome: "TRANCAR", tenant: A };
    const ciclo = new CicloDaConfianca({ lote: lote as unknown as ConjuntoSql, recalculo });
    assert.deepEqual(await ciclo.correr(), { tenants: 2, mudaram: 1, falhas: 1 });
    assert.equal(base.niveis.get(B), 0);
    assert.deepEqual(base.parametros.find((p) => p.nome === "AUDITAR")?.valores[2], "recalculo_diario:2:1:1");
    assert.equal(serie(metricas, /origem="diario",desfecho="falhou"/), 1);
  });

  it("uma volta que não lista os tenants, ou não audita, conta como falhou e sobe", async () => {
    const { base, lote, metricas, recalculo } = montar();
    const ciclo = new CicloDaConfianca({ lote: lote as unknown as ConjuntoSql, recalculo });
    base.falhar = { nome: "A_DESCER" };
    await assert.rejects(ciclo.descer(), /falha de ensaio em A_DESCER/);
    assert.equal(serie(metricas, /origem="descida",desfecho="falhou"/), 1);
    base.falhar = { nome: "AUDITAR" };
    await assert.rejects(ciclo.correr(), /falha de ensaio em AUDITAR/);
    assert.equal(serie(metricas, /origem="diario",desfecho="falhou"/), 1);
  });

  it("a varredura vazia não audita; com candidatos, audita uma linha sua", async () => {
    const { base, lote, recalculo } = montar();
    const ciclo = new CicloDaConfianca({ lote: lote as unknown as ConjuntoSql, recalculo });
    assert.deepEqual(await ciclo.descer(), { tenants: 0, mudaram: 0, falhas: 0 });
    assert.equal(base.parametros.filter((p) => p.nome === "AUDITAR").length, 0);
    base.aDescer = [A];
    base.niveis.set(A, 1);
    await ciclo.descer();
    assert.deepEqual(base.parametros.filter((p) => p.nome === "AUDITAR").map((p) => p.valores[1]), ["recalculo_descida"]);
  });

  it("duas voltas pedidas ao mesmo tempo são uma", async () => {
    const { base, lote, recalculo } = montar();
    base.tenants = [A];
    const ciclo = new CicloDaConfianca({ lote: lote as unknown as ConjuntoSql, recalculo });
    const [x, y] = [ciclo.correr(), ciclo.correr()];
    assert.equal(x, y);
    await x;
    assert.equal(base.diario.filter((l) => l === "lote-pool:TENANTS").length, 1);
  });

  it("o agendamento recusa menos de um segundo", () => {
    const { lote, recalculo } = montar();
    const ciclo = new CicloDaConfianca({ lote: lote as unknown as ConjuntoSql, recalculo });
    assert.throws(() => ciclo.agendar("correr", 999, () => {}, () => {}), RangeError);
    ciclo.agendar("descer", 1_000, () => {}, () => {})();
  });

  it("a volta diária lê as fases a partir de aprovado e os tenants que já têm nível", () => {
    for (const fase of ["aprovado", "provisionando", "aguarda_es", "lista_espera", "aguarda_catalogo", "aguarda_teste", "activo"]) {
      assert.match(SQL_TENANTS_A_RECALCULAR, new RegExp(`'${fase}'`));
    }
    for (const morta of ["rejeitado", "abandonado", "cancelado", "kyc_pendente", "em_revisao"]) {
      assert.doesNotMatch(SQL_TENANTS_A_RECALCULAR, new RegExp(`'${morta}'`));
    }
    assert.match(SQL_TENANTS_A_RECALCULAR, /FROM platform\.trust_level/);
  });
});

describe("as métricas do recálculo", () => {
  it("nascem a zero em todo o domínio, sem tenant nas etiquetas", () => {
    const texto = new MetricasDaConfianca().exposicao();
    const series = texto.split("\n").filter((l) => l !== "" && !l.startsWith("#"));
    assert.equal(series.length, 4 * 3 + 6);
    assert.ok(series.every((l) => l.endsWith(" 0")));
    // As etiquetas, e não a ajuda (que diz «de um tenant» em prosa).
    assert.ok(series.every((l) => !/tenant/.test(l)), series.join("\n"));
    assert.deepEqual(
      [...new Set(series.flatMap((l) => [...l.matchAll(/([a-z_]+)="/g)].map((m) => m[1])))].sort(),
      ["desfecho", "motivo", "origem"],
    );
    assert.match(texto, /^# TYPE confianca_recalculos_total counter$/m);
    assert.match(texto, /^# TYPE confianca_mudancas_total counter$/m);
  });

  it("um valor fora do domínio não abre série", () => {
    const m = new MetricasDaConfianca();
    m.recalculo("outra" as never, "mudou");
    m.mudanca(A as never);
    assert.doesNotMatch(m.exposicao(), new RegExp(A));
    assert.equal(m.exposicao(), new MetricasDaConfianca().exposicao());
  });
});

describe("o depois do consumo", () => {
  const evento = { tipo: "order.delivered", tenant_id: A } as unknown as Envelope;

  it("corre no aplicado e no duplicado, e não no adiado nem na DLQ", async () => {
    const vistos: string[] = [];
    const depois = async (e: Envelope) => void vistos.push(e.tipo);
    assert.equal(await correrDepois(depois, evento, "aplicado"), true);
    assert.equal(await correrDepois(depois, evento, "duplicado"), true);
    assert.equal(await correrDepois(depois, evento, "adiado"), false);
    assert.equal(await correrDepois(depois, evento, "dlq"), false);
    assert.equal(await correrDepois(undefined, evento, "aplicado"), false);
    assert.deepEqual(vistos, ["order.delivered", "order.delivered"]);
  });

  it("o job conclui pelo desfecho: o depois corre no aplicado e no duplicado, e o adiado e a DLQ lançam sem ele", async () => {
    const vistos: string[] = [];
    const depois = async (e: Envelope) => void vistos.push(e.tipo);
    assert.equal(await concluirJob({ desfecho: "aplicado" }, evento, depois), "aplicado");
    assert.equal(await concluirJob({ desfecho: "duplicado" }, evento, depois), "duplicado");
    await assert.rejects(concluirJob({ desfecho: "adiado", adiamento: 7 }, evento, depois), (e: unknown) => e instanceof Adiar && e.atrasoMs === 7_000);
    await assert.rejects(concluirJob({ desfecho: "dlq", erro: "x" }, evento, depois), (e: unknown) => e instanceof Error && e.name === "UnrecoverableError" && /dlq: x/.test(e.message));
    assert.deepEqual(vistos, ["order.delivered", "order.delivered"]);
    assert.equal(await concluirJob({ desfecho: "aplicado" }, evento), "aplicado", "sem depois, conclui na mesma");
    await assert.rejects(concluirJob({ desfecho: "aplicado" }, evento, async () => {
      throw new Error("base em baixo");
    }), /base em baixo/);
  });

  it("uma falha do depois sobe, para o BullMQ repetir", async () => {
    await assert.rejects(
      correrDepois(async () => {
        throw new Error("base em baixo");
      }, evento, "aplicado"),
      /base em baixo/,
    );
  });
});
