/**
 * A DLQ, as acções externas e a reposição, sem base de dados (KAM-006).
 *
 * Aqui prova-se a **decisão**: a severidade pelo tipo (critério 5), o `once`
 * que não repete e que adia o que não sabe (critério 9), o fecho que distingue
 * «fechei» de «já estava fechada» (critério 6), e a reposição que agrupa por
 * fila e não re-enfileira para quem não devia receber (critério 8).
 *
 * O que **não** se prova aqui: que a DLQ tem uma entrada por
 * `(consumer, event_id)` é uma restrição `UNIQUE` e prova-se contra PostgreSQL;
 * que a reposição recupera depois de um `FLUSHALL` é `db/tests_eventos_consumo/`
 * com Valkey real. Os dois aprovadores são a ferramenta de operação, e a prova
 * está na suite dela.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  Adiar,
  CARENCIA_POR_OMISSAO,
  type Envelope,
  EtiquetaInvalidaError,
  FilasEmMemoria,
  HORAS_ATE_ALERTAR,
  JANELA_POR_OMISSAO,
  LOCK_DO_RECONCILIADOR,
  LOTE_POR_OMISSAO,
  MAXIMO_DE_TIPOS,
  METRICA_CONSUMIDOS,
  METRICA_DLQ_ABERTAS,
  Metricas,
  SQL_ABRIR_ACCAO,
  SQL_A_REPOR,
  SQL_FECHAR_ACCAO,
  SQL_FECHAR_DLQ,
  SQL_LER_ACCAO,
  SQL_PARA_DLQ,
  SQL_PARTICAO,
  abertas,
  chaveDaAccao,
  eSev1,
  fechar,
  lerEnvelope,
  once,
  paraDlq,
  publicarAbertas,
  reporUmaVez,
  severidade,
} from "../src/eventos/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONSUMER = "agr";
const EVENTO = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44";

function envelope(parcial: Partial<Record<string, unknown>> = {}): Envelope {
  return lerEnvelope({
    id: EVENTO,
    tipo: "payment.confirmed",
    versao: 1,
    tenant_id: TENANT,
    ocorrido_em: "2026-11-02T14:03:11.482Z",
    registado_em: "2026-11-02T14:03:11.610Z",
    produtor: "pay@0.1.0",
    agregado: { tipo: "order", id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50", seq: 2 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P1",
    finalidades: ["transacao"],
    payload: { order_id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50" },
    ...parcial,
  });
}

class BdFalsa {
  readonly instrucoes: string[] = [];
  readonly parametros: unknown[][] = [];
  abriuDlq = 1;
  fechou = 1;
  abertas: Record<string, unknown>[] = [];
  abriuAccao = 1;
  accao: { estado: string; resultado: unknown } | null = null;
  aRepor: Record<string, unknown>[] = [];
  particao = 3;

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }> {
    this.instrucoes.push(sql.trim().split("\n")[0].trim());
    this.parametros.push([...parametros]);
    if (sql === SQL_PARA_DLQ) {
      // Sem `RETURNING`: o que conta e a contagem de linhas.
      return { rows: [], rowCount: this.abriuDlq };
    }
    if (sql === SQL_FECHAR_DLQ) return { rows: [], rowCount: this.fechou };
    if (sql === SQL_ABRIR_ACCAO) return { rows: [], rowCount: this.abriuAccao };
    if (sql === SQL_LER_ACCAO) {
      return { rows: this.accao === null ? [] : [{ ...this.accao }], rowCount: 1 };
    }
    if (sql === SQL_FECHAR_ACCAO) return { rows: [], rowCount: 1 };
    if (sql === SQL_A_REPOR) return { rows: this.aRepor, rowCount: this.aRepor.length };
    if (sql === SQL_PARTICAO) {
      return { rows: [{ particao: this.particao }], rowCount: 1 };
    }
    if (sql.includes("estado = 'aberta'")) {
      return { rows: this.abertas, rowCount: this.abertas.length };
    }
    return { rows: [], rowCount: 0 };
  }
}

describe("a severidade de uma entrada da DLQ", () => {
  it("payment.* é Sev1 pela família inteira", () => {
    assert.ok(eSev1("payment.confirmed"));
    assert.ok(eSev1("payment.manual_confirmed"));
    assert.ok(eSev1("payment.inventado_amanha"));
  });

  it("order.paid é Sev1 pelo nome: é o evento que diz que o dinheiro chegou", () => {
    assert.ok(eSev1("order.paid"));
  });

  it("os outros não são Sev1", () => {
    assert.ok(!eSev1("order.created"));
    assert.ok(!eSev1("channel.inactivity_warning"));
  });

  it("Sev1 não espera pela idade: dez segundos já são um cliente à espera", () => {
    assert.equal(severidade("payment.confirmed", 0), "sev1");
  });

  it("os outros só alertam depois de uma hora aberta", () => {
    assert.equal(severidade("order.created", 0), "nenhuma");
    assert.equal(severidade("order.created", HORAS_ATE_ALERTAR - 0.1), "nenhuma");
    assert.equal(severidade("order.created", HORAS_ATE_ALERTAR), "sev2");
  });
});

describe("paraDlq()", () => {
  let bd: BdFalsa;

  beforeEach(() => {
    bd = new BdFalsa();
  });

  it("escreve os oito parâmetros do DDL, com o envelope em JSON", async () => {
    const env = envelope();
    const resultado = await paraDlq({
      bd,
      consumer: CONSUMER,
      envelope: env,
      erro: "fora_de_ordem",
      tentativas: 6,
    });
    assert.ok(resultado.abriu);
    assert.equal(resultado.severidade, "sev1");
    const indice = bd.instrucoes.findIndex((i) => i.startsWith("INSERT INTO platform.events_dlq"));
    assert.deepEqual(bd.parametros[indice], [
      CONSUMER,
      env.id,
      env.tipo,
      env.versao,
      env.tenant_id,
      JSON.stringify(env),
      "fora_de_ordem",
      6,
    ]);
  });

  it("diz que não abriu quando a entrada já existia", async () => {
    bd.abriuDlq = 0;
    const resultado = await paraDlq({
      bd,
      consumer: CONSUMER,
      envelope: envelope(),
      erro: "x",
      tentativas: 6,
    });
    assert.ok(!resultado.abriu);
  });

  it("não lê a tabela: quem consome tem só INSERT na DLQ", async () => {
    // O `id` da DLQ é sequencial, e um papel sujeito a RLS que o lesse media o
    // volume de falhas do vizinho. O `evt_dlq_open` é publicado pelo processo,
    // pela ligação de operação.
    await paraDlq({ bd, consumer: CONSUMER, envelope: envelope(), erro: "x", tentativas: 1 });
    assert.deepEqual(
      bd.instrucoes.filter((i) => i.startsWith("SELECT")),
      [],
      "nenhuma leitura: nem RETURNING, nem a contagem das abertas",
    );
  });
});

describe("evt_dlq_open{tipo}", () => {
  it("espelha a tabela, e esquece o tipo que deixou de ter entradas", async () => {
    const bd = new BdFalsa();
    const metricas = new Metricas();
    bd.abertas = [
      { tipo: "payment.confirmed", quantas: 2, mais_antiga: "2026-11-02T10:00:00Z" },
      { tipo: "order.created", quantas: 1, mais_antiga: "2026-11-02T11:00:00Z" },
    ];
    await publicarAbertas(bd, metricas);
    assert.equal(metricas.ler()[`${METRICA_DLQ_ABERTAS}:payment.confirmed`], 2);
    assert.equal(metricas.ler()[`${METRICA_DLQ_ABERTAS}:order.created`], 1);

    // O `payment.confirmed` foi reprocessado: a série tem de desaparecer, e não
    // ficar no último valor. Um alerta que nunca se desliga é um alerta que se
    // ignora.
    bd.abertas = [{ tipo: "order.created", quantas: 1, mais_antiga: "2026-11-02T11:00:00Z" }];
    await publicarAbertas(bd, metricas);
    assert.equal(metricas.ler()[`${METRICA_DLQ_ABERTAS}:payment.confirmed`], undefined);
    assert.equal(metricas.ler()[`${METRICA_DLQ_ABERTAS}:order.created`], 1);
  });

  it("expõe a etiqueta `tipo` no formato do Prometheus", async () => {
    const bd = new BdFalsa();
    const metricas = new Metricas();
    bd.abertas = [{ tipo: "payment.confirmed", quantas: 3, mais_antiga: "2026-11-02T10:00:00Z" }];
    await publicarAbertas(bd, metricas);
    assert.match(metricas.exposicao(), /evt_dlq_open\{tipo="payment\.confirmed"\} 3/);
  });

  it("recusa um valor que não é um tipo de evento", () => {
    const metricas = new Metricas();
    // Um identificador não casa `familia.verbo`, e é essa a guarda.
    assert.throws(
      () => metricas.medirPorTipo(METRICA_DLQ_ABERTAS, TENANT, 1),
      EtiquetaInvalidaError,
    );
  });

  it("recusa a métrica errada: só o evt_dlq_open tem etiqueta por tipo", () => {
    const metricas = new Metricas();
    assert.throws(
      () => metricas.medirPorTipo(METRICA_CONSUMIDOS, "order.created", 1),
      EtiquetaInvalidaError,
    );
  });

  it("tem tecto: uma métrica que cresce sem fim deixa de ser observabilidade", () => {
    const metricas = new Metricas();
    for (let i = 0; i < MAXIMO_DE_TIPOS; i += 1) {
      metricas.medirPorTipo(METRICA_DLQ_ABERTAS, `familia${i}.verbo`, 1);
    }
    assert.throws(
      () => metricas.medirPorTipo(METRICA_DLQ_ABERTAS, "umaquemais.verbo", 1),
      RangeError,
    );
    // Actualizar uma série que já existe continua a valer acima do tecto.
    metricas.medirPorTipo(METRICA_DLQ_ABERTAS, "familia0.verbo", 9);
    assert.equal(metricas.ler()[`${METRICA_DLQ_ABERTAS}:familia0.verbo`], 9);
  });
});

describe("fechar() uma entrada", () => {
  it("devolve true quando fechou", async () => {
    const bd = new BdFalsa();
    assert.ok(await fechar(bd, 1, "reprocessada", "alguem"));
  });

  it("devolve false quando já estava fechada — e isso não é sucesso", async () => {
    const bd = new BdFalsa();
    bd.fechou = 0;
    assert.ok(!(await fechar(bd, 1, "descartada", "alguem")));
  });

  it("lê as abertas com a contagem e a mais antiga", async () => {
    const bd = new BdFalsa();
    bd.abertas = [{ tipo: "order.created", quantas: "4", mais_antiga: "2026-11-02T10:00:00Z" }];
    const linhas = await abertas(bd);
    assert.equal(linhas[0].quantas, 4);
    assert.ok(linhas[0].maisAntiga instanceof Date);
  });
});

describe("once(): o efeito externo que não se repete", () => {
  let bd: BdFalsa;

  beforeEach(() => {
    bd = new BdFalsa();
  });

  const opcoes = {
    get bd() {
      return bd;
    },
    consumer: CONSUMER,
    eventId: EVENTO,
    tenantId: TENANT,
    accao: "enviar_whatsapp",
  };

  it("a chave é consumer:event_id:acção, como o §6.3 manda", () => {
    assert.equal(
      chaveDaAccao(CONSUMER, EVENTO, "enviar_whatsapp"),
      `${CONSUMER}:${EVENTO}:enviar_whatsapp`,
    );
  });

  it("recusa um nome de acção que não é um nome", () => {
    assert.throws(() => chaveDaAccao(CONSUMER, EVENTO, "Enviar WhatsApp"));
    assert.throws(() => chaveDaAccao(CONSUMER, EVENTO, ""));
  });

  it("corre o efeito uma vez e guarda o resultado", async () => {
    let vezes = 0;
    const resultado = await once(opcoes, async () => {
      vezes += 1;
      return { mensagem: "wamid.X" };
    });
    assert.ok(resultado.executou);
    assert.deepEqual(resultado.resultado, { mensagem: "wamid.X" });
    assert.equal(vezes, 1);
    const indice = bd.instrucoes.findIndex((i) => i.startsWith("UPDATE platform.evt_acoes"));
    assert.equal(bd.parametros[indice][1], "feita");
  });

  it("na segunda chamada não corre, e devolve o resultado guardado", async () => {
    bd.abriuAccao = 0;
    bd.accao = { estado: "feita", resultado: { mensagem: "wamid.X" } };
    let vezes = 0;
    const resultado = await once(opcoes, async () => {
      vezes += 1;
      return { mensagem: "outra" };
    });
    assert.ok(!resultado.executou);
    assert.deepEqual(resultado.resultado, { mensagem: "wamid.X" });
    assert.equal(vezes, 0, "o efeito externo não se repete");
  });

  it("adia quando encontra a acção em curso: não se sabe se o efeito aconteceu", async () => {
    bd.abriuAccao = 0;
    bd.accao = { estado: "em_curso", resultado: null };
    await assert.rejects(
      once(opcoes, async () => ({ mensagem: "x" })),
      Adiar,
    );
  });

  it("não repete uma acção que falhou de forma definitiva", async () => {
    bd.abriuAccao = 0;
    bd.accao = { estado: "falhada", resultado: { erro: "404" } };
    let vezes = 0;
    const resultado = await once(opcoes, async () => {
      vezes += 1;
      return { mensagem: "x" };
    });
    assert.ok(!resultado.executou);
    assert.equal(vezes, 0);
  });

  it("marca falhada e propaga quando o efeito lança", async () => {
    await assert.rejects(
      once(opcoes, async () => {
        throw new Error("o terceiro devolveu 500");
      }),
      /500/,
    );
    const indice = bd.instrucoes.findIndex((i) => i.startsWith("UPDATE platform.evt_acoes"));
    assert.equal(bd.parametros[indice][1], "falhada");
    // Sem isto, a chave ficava `em_curso` para sempre e todas as re-entregas
    // adiavam: o efeito nunca acontecia e ninguém sabia porquê.
    assert.match(String(bd.parametros[indice][2]), /500/);
  });
});

describe("o reconciliador", () => {
  it("tem um lock diferente do publicador: são trabalhos com ritmos diferentes", () => {
    assert.equal(LOCK_DO_RECONCILIADOR, 7102);
  });

  it("os valores por omissão são os do §6.5", () => {
    assert.equal(JANELA_POR_OMISSAO, 24 * 60 * 60);
    assert.equal(CARENCIA_POR_OMISSAO, 10 * 60);
  });

  it("não faz nada quando não há nada perdido", async () => {
    const bd = new BdFalsa();
    const filas = new FilasEmMemoria();
    const resultado = await reporUmaVez({ bd, filas });
    assert.deepEqual(resultado, { encontradas: 0, repostos: 0, filas: 0 });
    assert.equal(filas.chamadas, 0, "sem nada perdido, nao se toca na fila");
  });

  it("passa a janela, a carência e o lote como parâmetros, para o relógio se acelerar", async () => {
    const bd = new BdFalsa();
    await reporUmaVez({ bd, filas: new FilasEmMemoria(), janela: 60, carencia: 0, lote: 7 });
    const indice = bd.instrucoes.findIndex((i) => i.startsWith("SELECT l.event_id"));
    assert.deepEqual(bd.parametros[indice], [60, 0, 7]);
  });

  it("usa os valores do documento quando não lhe dizem outros", async () => {
    const bd = new BdFalsa();
    await reporUmaVez({ bd, filas: new FilasEmMemoria() });
    const indice = bd.instrucoes.findIndex((i) => i.startsWith("SELECT l.event_id"));
    assert.deepEqual(bd.parametros[indice], [
      JANELA_POR_OMISSAO,
      CARENCIA_POR_OMISSAO,
      LOTE_POR_OMISSAO,
    ]);
  });

  it("re-enfileira com o event_id por jobId, agrupado por fila", async () => {
    const bd = new BdFalsa();
    const filas = new FilasEmMemoria();
    bd.aRepor = [
      { event_id: EVENTO, tipo: "order.created", tenant_id: TENANT, agregado_id: "a", consumer: CONSUMER },
      { event_id: "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d45", tipo: "order.created", tenant_id: TENANT, agregado_id: "b", consumer: CONSUMER },
    ];
    const resultado = await reporUmaVez({ bd, filas });
    assert.equal(resultado.encontradas, 2);
    assert.equal(resultado.repostos, 2);
    assert.equal(resultado.filas, 1, "a mesma partição é uma fila só");
    assert.equal(filas.chamadas, 1, "um addLote por fila, e não um add por evento");
    assert.equal(filas.contar(`evt.${CONSUMER}.p3`), 2);
    assert.deepEqual(
      [...filas.jobs().values()].map((t) => t.jobId).sort(),
      bd.aRepor.map((l) => String(l.event_id)).sort(),
    );
  });

  it("a partição vem da base, com a conta do evt_emitir", async () => {
    const bd = new BdFalsa();
    bd.particao = 11;
    bd.aRepor = [
      { event_id: EVENTO, tipo: "order.created", tenant_id: TENANT, agregado_id: "a", consumer: CONSUMER },
    ];
    await reporUmaVez({ bd, filas: new FilasEmMemoria() });
    const indice = bd.instrucoes.findIndex((i) => i.startsWith("SELECT (hashtextextended"));
    assert.ok(indice >= 0, "a partição recalcula-se na base e não em TypeScript");
    assert.deepEqual(bd.parametros[indice], [TENANT, "a"]);
  });
});
