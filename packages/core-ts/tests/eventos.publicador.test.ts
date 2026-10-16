/**
 * O laço do publicador, sem base de dados nem Redis (KAM-005).
 *
 * Aqui prova-se o que é **lógica**: o roteamento por finalidade (critério 7), a
 * escada de recuo (critério 4), os nomes de fila (critério 7), a liderança
 * (critério 5), a ordem `add` → arquivo → `publicado_at` → `COMMIT`
 * (critério 3), e que uma fila que falha deixa tudo no outbox.
 *
 * O que **não** se prova aqui, e onde se prova: o *rollback* sem lacunas e a
 * serialização por agregado são SQL (`db/tests/test_eventos_schema.py`); o
 * *kill -9*, o Redis parado e a eleição entre dois processos são
 * `db/tests_eventos/` com PostgreSQL e Valkey reais. Um laço que passa com uma
 * base falsa não prova nada sobre transacções — e é por isso que estes testes
 * não são a evidência dos critérios 1, 2, 3 e 4.
 *
 * A base falsa (`BdFalsa`) registra as instruções pela ordem em que as recebe:
 * é essa lista que torna a ordem verificável.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  ESCADA_DE_RECUO,
  type Envelope,
  FilasEmMemoria,
  LOCK_DO_PUBLICADOR,
  METRICA_ATRASO,
  METRICA_ERROS,
  METRICA_LIDER,
  METRICA_PUBLICADOS,
  Metricas,
  Publicador,
  SQL_ARQUIVAR,
  SQL_MARCAR_PUBLICADO,
  SQL_PENDENTES,
  SQL_RECUAR,
  SQL_SUBSCRICOES,
  SemLiderancaError,
  type Subscricao,
  atrasoDaTentativa,
  destinos,
  filasDe,
  lerEnvelope,
  nomeDaFila,
} from "../src/eventos/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";

function envelope(parcial: Partial<Record<string, unknown>> = {}): Envelope {
  return lerEnvelope({
    id: "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44",
    tipo: "order.created",
    versao: 1,
    tenant_id: TENANT,
    ocorrido_em: "2026-11-02T14:03:11.482Z",
    registado_em: "2026-11-02T14:03:11.610Z",
    produtor: "com@0.1.0",
    agregado: { tipo: "order", id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50", seq: 1 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P1",
    finalidades: ["transacao"],
    payload: { order_id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50" },
    ...parcial,
  });
}

function subscricao(parcial: Partial<Subscricao> = {}): Subscricao {
  return {
    consumer: "agr",
    tipo: "order.created",
    versao_max: 1,
    finalidade: "transacao",
    exige_ordem: false,
    ...parcial,
  };
}

/** Base falsa: guarda as instruções por ordem e devolve o que lhe dizem. */
class BdFalsa {
  readonly instrucoes: string[] = [];
  readonly parametros: unknown[][] = [];
  lider = true;
  pendentes: Record<string, unknown>[] = [];
  subscricoes: Subscricao[] = [];
  atraso = 0;
  /** Quando definido, a instrução cujo prefixo bate lança. */
  falhaEm: string | null = null;

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }> {
    this.instrucoes.push(etiqueta(sql));
    this.parametros.push([...parametros]);
    if (this.falhaEm !== null && etiqueta(sql) === this.falhaEm) {
      throw new Error(`falha simulada em ${this.falhaEm}`);
    }
    if (sql.includes("pg_try_advisory_lock")) {
      return { rows: [{ lider: this.lider }], rowCount: 1 };
    }
    if (sql.includes("pg_advisory_unlock")) {
      return { rows: [{ largou: true }], rowCount: 1 };
    }
    if (sql === SQL_PENDENTES) {
      return { rows: this.pendentes, rowCount: this.pendentes.length };
    }
    if (sql.includes("evt_subscricoes")) {
      return {
        rows: this.subscricoes as unknown as Record<string, unknown>[],
        rowCount: this.subscricoes.length,
      };
    }
    if (sql.includes("EXTRACT(EPOCH")) {
      return { rows: [{ atraso: this.atraso }], rowCount: 1 };
    }
    return { rows: [], rowCount: (parametros[0] as unknown[] | undefined)?.length ?? 0 };
  }
}

function etiqueta(sql: string): string {
  if (sql === SQL_PENDENTES) return "PENDENTES";
  if (sql === SQL_ARQUIVAR) return "ARQUIVAR";
  if (sql === SQL_MARCAR_PUBLICADO) return "MARCAR";
  if (sql === SQL_RECUAR) return "RECUAR";
  if (sql.includes("evt_subscricoes")) return "SUBSCRICOES";
  if (sql.includes("pg_try_advisory_lock")) return "ELEGER";
  if (sql.includes("pg_advisory_unlock")) return "LARGAR";
  if (sql.includes("EXTRACT(EPOCH")) return "ATRASO";
  if (sql.startsWith("LISTEN")) return "LISTEN";
  return sql.trim().split(/\s+/)[0] ?? sql;
}

function linha(parcial: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "1",
    event_id: "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44",
    tipo: "order.created",
    versao: 1,
    tenant_id: TENANT,
    agregado_tipo: "order",
    agregado_id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50",
    particao: 7,
    envelope: envelope(),
    tentativas: 0,
    ...parcial,
  };
}

describe("roteamento por finalidade (criterio 7)", () => {
  it("entrega a quem subscreve o tipo com uma finalidade do envelope", () => {
    const alvos = destinos(envelope(), [subscricao()]);
    assert.deepEqual(alvos.map((a) => a.consumer), ["agr"]);
  });

  it("nao entrega a quem subscreve outra finalidade", () => {
    const alvos = destinos(envelope({ finalidades: ["transacao"] }), [
      subscricao({ consumer: "ads", finalidade: "marketing" }),
    ]);
    assert.deepEqual(alvos, []);
  });

  it("nao entrega a quem subscreve outro tipo", () => {
    const alvos = destinos(envelope(), [subscricao({ tipo: "order.paid" })]);
    assert.deepEqual(alvos, []);
  });

  it("um envelope com duas finalidades chega aos dois consumidores", () => {
    const alvos = destinos(
      envelope({ finalidades: ["transacao", "analytics_agregado"] }),
      [
        subscricao({ consumer: "agr", finalidade: "transacao" }),
        subscricao({ consumer: "dat", finalidade: "analytics_agregado" }),
        subscricao({ consumer: "ads", finalidade: "marketing" }),
      ],
    );
    assert.deepEqual(alvos.map((a) => a.consumer).sort(), ["agr", "dat"]);
  });

  it("uma subscricao inactiva nunca chega ao roteamento: filtra o SQL", () => {
    // `destinos` nao conhece `activo` — nem deve: o filtro e da consulta, e e
    // la que tem de estar, ou uma subscricao desligada continuava a receber.
    assert.match(SQL_SUBSCRICOES, /WHERE activo/);
  });
});

describe("nomes de fila (criterio 7)", () => {
  it("sao `evt.<consumer>.p<0..15>`", () => {
    assert.equal(nomeDaFila("agr", 0), "evt.agr.p0");
    assert.equal(nomeDaFila("agr", 15), "evt.agr.p15");
  });

  it("sao dezasseis por consumidor, distintos", () => {
    const filas = filasDe("agr");
    assert.equal(filas.length, 16);
    assert.equal(new Set(filas).size, 16);
  });

  it("uma particao fora de 0..15 lanca, e nao dobra por modulo", () => {
    assert.throws(() => nomeDaFila("agr", 16), /fora de 0\.\.15/);
    assert.throws(() => nomeDaFila("agr", -1), /fora de 0\.\.15/);
  });

  it("um consumer que nao e um nome lanca", () => {
    assert.throws(() => nomeDaFila("AGR", 0), /nao e um nome/);
    assert.throws(() => nomeDaFila("a", 0), /nao e um nome/);
  });
});

describe("escada de recuo (criterio 4)", () => {
  it("e 1 s, 2 s, 5 s, 15 s, 30 s — nao a escada da DLQ do §6.4", () => {
    assert.deepEqual([...ESCADA_DE_RECUO], [1000, 2000, 5000, 15000, 30000]);
  });

  it("a primeira tentativa recua 1 s", () => {
    assert.equal(atrasoDaTentativa(0), 1000);
  });

  it("nao cresce depois do quinto: fica nos 30 s", () => {
    assert.equal(atrasoDaTentativa(4), 30000);
    assert.equal(atrasoDaTentativa(99), 30000);
  });

  it("o tecto cumpre o criterio 4: recuperacao em menos de 60 s", () => {
    // Com a escada do §6.4 (2 min, 10 min) o criterio 4 era impossivel: 60 s de
    // fila em baixo punham a proxima tentativa a minutos de distancia. O tecto
    // e o que torna a promessa verificavel, e e por isso que esta aqui com o
    // numero do criterio ao lado.
    assert.ok(Math.max(...ESCADA_DE_RECUO) < 60_000);
  });

  it("e monotona: subir a tentativa nunca encurta a espera", () => {
    for (let n = 1; n < 10; n += 1) {
      assert.ok(atrasoDaTentativa(n) >= atrasoDaTentativa(n - 1));
    }
  });
});

describe("lideranca (criterio 5)", () => {
  let bd: BdFalsa;
  let filas: FilasEmMemoria;
  let metricas: Metricas;

  beforeEach(() => {
    bd = new BdFalsa();
    filas = new FilasEmMemoria();
    metricas = new Metricas();
  });

  it("pede o lock com o valor do doc 06 §6.2", async () => {
    const publicador = new Publicador({ bd, filas, metricas });
    assert.equal(await publicador.eleger(), true);
    assert.deepEqual(bd.parametros[0], [LOCK_DO_PUBLICADOR]);
    assert.equal(LOCK_DO_PUBLICADOR, 7101);
  });

  it("quem fica lider escuta o canal de aviso", async () => {
    await new Publicador({ bd, filas, metricas }).eleger();
    assert.deepEqual(bd.instrucoes, ["ELEGER", "LISTEN"]);
  });

  it("quem nao fica lider nao escuta nem publica", async () => {
    bd.lider = false;
    const publicador = new Publicador({ bd, filas, metricas });
    assert.equal(await publicador.eleger(), false);
    assert.deepEqual(bd.instrucoes, ["ELEGER"]);
    assert.equal(metricas.ler()[METRICA_LIDER], 0);
    await assert.rejects(() => publicador.ciclo(), SemLiderancaError);
  });

  it("eleger duas vezes nao pede o lock duas vezes", async () => {
    const publicador = new Publicador({ bd, filas, metricas });
    await publicador.eleger();
    await publicador.eleger();
    assert.equal(bd.instrucoes.filter((i) => i === "ELEGER").length, 1);
  });

  it("a metrica de lideranca e 1 para o lider", async () => {
    const publicador = new Publicador({ bd, filas, metricas });
    await publicador.eleger();
    assert.equal(metricas.ler()[METRICA_LIDER], 1);
    await publicador.largar();
    assert.equal(metricas.ler()[METRICA_LIDER], 0);
    assert.equal(publicador.lider, false);
  });
});

describe("um ciclo", () => {
  let bd: BdFalsa;
  let filas: FilasEmMemoria;
  let metricas: Metricas;
  let publicador: Publicador;

  beforeEach(async () => {
    bd = new BdFalsa();
    filas = new FilasEmMemoria();
    metricas = new Metricas();
    publicador = new Publicador({ bd, filas, metricas, lote: 2 });
    bd.subscricoes = [subscricao()];
    await publicador.eleger();
    // As duas listas sao paralelas: esvaziar so uma desalinhava os indices, e
    // um `parametros[instrucoes.indexOf(...)]` passava a ler outra instrucao.
    bd.instrucoes.length = 0;
    bd.parametros.length = 0;
  });

  it("sem linhas pendentes nao abre nada alem da transaccao", async () => {
    const resultado = await publicador.ciclo();
    assert.deepEqual(resultado, {
      lidas: 0,
      publicadas: 0,
      jobs: 0,
      recuadas: 0,
      bloqueadas: 0,
    });
    assert.deepEqual(bd.instrucoes, ["BEGIN", "PENDENTES", "COMMIT"]);
    assert.equal(filas.chamadas, 0);
  });

  it("a ordem e `add` → arquivar → marcar → COMMIT (criterio 3)", async () => {
    bd.pendentes = [linha()];
    await publicador.ciclo();
    assert.deepEqual(bd.instrucoes, [
      "BEGIN",
      "PENDENTES",
      "SUBSCRICOES",
      "ARQUIVAR",
      "MARCAR",
      "COMMIT",
    ]);
    assert.equal(filas.contar("evt.agr.p7"), 1);
  });

  it("o `jobId` e o `event_id`, e a fila e a da particao da linha", async () => {
    bd.pendentes = [linha({ particao: 3 })];
    await publicador.ciclo();
    const jobs = [...filas.jobs().entries()];
    assert.equal(jobs.length, 1);
    assert.equal(jobs[0]?.[0], "evt.agr.p3|0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44");
  });

  it("republicar a mesma linha chama o `add` duas vezes com o mesmo jobId", async () => {
    // O que isto prova e **do publicador**: republicar usa o mesmo `jobId`. Que
    // a fila deduplique nao se prova aqui — a `FilasEmMemoria` deduplica por
    // construcao, e tomar isso por evidencia era o teste tautologico que a
    // revisao apanhou (ANALISE-20, achado 3). A medicao esta em
    // `db/tests_eventos`, contra uma fila real, pelo `LLEN` da lista de espera.
    bd.pendentes = [linha()];
    await publicador.ciclo();
    await publicador.ciclo();
    assert.equal(filas.chamadas, 2, "o publicador tentou duas vezes");
    const jobIds = [...filas.jobs().values()].map((t) => t.jobId);
    assert.deepEqual(jobIds, ["0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44"]);
  });

  it("um evento sem destino arquiva-se e marca-se publicado", async () => {
    bd.subscricoes = [subscricao({ finalidade: "marketing" })];
    bd.pendentes = [linha()];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.jobs, 0);
    assert.equal(resultado.publicadas, 1);
    assert.equal(metricas.ler()[`${METRICA_PUBLICADOS}:sem_destino`], 1);
    assert.ok(bd.instrucoes.includes("MARCAR"));
  });

  it("dois consumidores da mesma finalidade dao dois jobs", async () => {
    bd.subscricoes = [subscricao(), subscricao({ consumer: "dat" })];
    bd.pendentes = [linha()];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.jobs, 2);
    assert.equal(filas.contar("evt.agr.p7"), 1);
    assert.equal(filas.contar("evt.dat.p7"), 1);
    assert.equal(metricas.ler()[`${METRICA_PUBLICADOS}:entregue`], 2);
  });

  it("a fila a falhar reverte o lote e recua, em transaccao propria", async () => {
    bd.pendentes = [linha(), linha({ id: "2", agregado_id: "outro" })];
    filas.falha = new Error("Redis parado");
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 0);
    assert.equal(resultado.recuadas, 2);
    assert.deepEqual(bd.instrucoes, [
      "BEGIN",
      "PENDENTES",
      "SUBSCRICOES",
      "ROLLBACK",
      "RECUAR",
    ]);
    assert.equal(metricas.ler()[`${METRICA_ERROS}:fila_indisponivel`], 1);
  });

  it("o recuo leva a escada da tentativa mais alta do lote", async () => {
    bd.pendentes = [
      linha({ tentativas: 0 }),
      linha({ id: "2", tentativas: 3, agregado_id: "outro" }),
    ];
    filas.falha = new Error("Redis parado");
    await publicador.ciclo();
    const recuo = bd.parametros[bd.instrucoes.indexOf("RECUAR")];
    assert.deepEqual(recuo?.[0], ["1", "2"]);
    assert.equal(recuo?.[1], atrasoDaTentativa(3));
  });

  it("um envelope com padrao de telefone nao se publica", async () => {
    bd.pendentes = [
      linha({ envelope: { ...envelope(), payload: { recipient: "+244912345678" } } }),
    ];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 0);
    assert.equal(resultado.bloqueadas, 1, "fica no outbox");
    assert.equal(filas.contar("evt.agr.p7"), 0);
    assert.equal(metricas.ler()[`${METRICA_ERROS}:padrao_de_telefone`], 1);
  });

  it("um envelope ilegivel nao se publica", async () => {
    bd.pendentes = [linha({ envelope: { tipo: "order.created" } })];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 0);
    assert.equal(resultado.bloqueadas, 1, "fica no outbox");
    assert.equal(metricas.ler()[`${METRICA_ERROS}:envelope_invalido`], 1);
  });

  it("sem conversor para a versao do consumidor, nao se publica nem se descarta", async () => {
    bd.subscricoes = [subscricao({ versao_max: 1 })];
    bd.pendentes = [linha({ envelope: envelope({ versao: 2 }) })];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 0);
    assert.equal(resultado.bloqueadas, 1, "fica no outbox");
    assert.equal(metricas.ler()[`${METRICA_ERROS}:sem_conversor`], 1);
  });

  it("uma particao fora de 0..15 na coluna nao vai para fila nenhuma", async () => {
    bd.pendentes = [linha({ particao: 16 })];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 0);
    assert.equal(resultado.bloqueadas, 1);
    assert.equal(metricas.ler()[`${METRICA_ERROS}:destino_invalido`], 1);
  });

  it("uma linha invalida **nao** derruba as boas do lote (achado 1)", async () => {
    // A propriedade central da fase dupla: a linha ma fica de lado, as outras
    // publicam-se. Na versao de fase unica, as tres recuavam juntas e no ciclo
    // seguinte repetia-se — para sempre.
    bd.pendentes = [
      linha({ id: "1", envelope: { tipo: "order.created" }, agregado_id: "mau" }),
      linha({ id: "2", agregado_id: "bom-a" }),
      linha({ id: "3", agregado_id: "bom-b" }),
    ];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 2);
    assert.equal(resultado.bloqueadas, 1);
    assert.equal(resultado.jobs, 2);
    const marcadas = bd.parametros[bd.instrucoes.indexOf("MARCAR")]?.[0];
    assert.deepEqual(marcadas, ["2", "3"]);
    const recuadas = bd.parametros[bd.instrucoes.indexOf("RECUAR")]?.[0];
    assert.deepEqual(recuadas, ["1"]);
  });

  it("o corte arrasta o resto do agregado, e so dele (achado 1)", async () => {
    // Publicar a `seq` seguinte com a anterior para tras era perder a ordem
    // causal; parar o lote inteiro era o defeito. O corte e por agregado.
    bd.pendentes = [
      linha({ id: "1", envelope: { tipo: "order.created" }, agregado_id: "x" }),
      linha({ id: "2", agregado_id: "x" }),
      linha({ id: "3", agregado_id: "y" }),
    ];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 1);
    assert.equal(resultado.bloqueadas, 2);
    assert.deepEqual(bd.parametros[bd.instrucoes.indexOf("MARCAR")]?.[0], ["3"]);
    assert.deepEqual(bd.parametros[bd.instrucoes.indexOf("RECUAR")]?.[0], ["1", "2"]);
  });

  it("o agregado de um tenant nao bloqueia o homonimo de outro", async () => {
    bd.pendentes = [
      linha({ id: "1", envelope: { tipo: "order.created" }, agregado_id: "x" }),
      linha({
        id: "2",
        agregado_id: "x",
        tenant_id: "11111111-1111-1111-1111-111111111111",
        envelope: envelope({ tenant_id: "11111111-1111-1111-1111-111111111111" }),
      }),
    ];
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 1);
    assert.deepEqual(bd.parametros[bd.instrucoes.indexOf("MARCAR")]?.[0], ["2"]);
  });

  it("um `ROLLBACK` que tambem falha nao esconde o erro de cima", async () => {
    bd.pendentes = [linha()];
    filas.falha = new Error("Redis parado");
    bd.falhaEm = "ROLLBACK";
    const resultado = await publicador.ciclo();
    assert.equal(resultado.publicadas, 0);
    assert.equal(metricas.ler()[`${METRICA_ERROS}:fila_indisponivel`], 1);
  });

  it("a base a cair no recuo conta-se, e nada se perde", async () => {
    bd.pendentes = [linha()];
    filas.falha = new Error("Redis parado");
    bd.falhaEm = "RECUAR";
    const resultado = await publicador.ciclo();
    assert.equal(resultado.recuadas, 0);
    assert.equal(metricas.ler()[`${METRICA_ERROS}:base_indisponivel`], 1);
  });
});

describe("atraso do outbox (criterio 8)", () => {
  it("mede e publica o gauge", async () => {
    const bd = new BdFalsa();
    bd.atraso = 0.42;
    const metricas = new Metricas();
    const publicador = new Publicador({ bd, filas: new FilasEmMemoria(), metricas });
    assert.equal(await publicador.medirAtraso(), 0.42);
    assert.equal(metricas.ler()[METRICA_ATRASO], 0.42);
  });

  it("sem linhas pendentes o atraso e 0, nao «sem dados»", async () => {
    const bd = new BdFalsa();
    const metricas = new Metricas();
    const publicador = new Publicador({ bd, filas: new FilasEmMemoria(), metricas });
    await publicador.medirAtraso();
    assert.equal(metricas.ler()[METRICA_ATRASO], 0);
  });
});
