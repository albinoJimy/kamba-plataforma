/**
 * O consumo idempotente, a máquina de estados e a política (KAM-006).
 *
 * Aqui prova-se o que é **lógica**: a ordem das instruções na transacção, o
 * duplicado que não faz nada, o `Adiar` contra o `ForaDeOrdem`, a escada de
 * seis tentativas, e que uma transição inválida **nunca** se aplica.
 *
 * O que **não** se prova aqui, e onde se prova: que a marca e o efeito estão
 * mesmo na mesma transacção é SQL, e prova-se em `db/tests_eventos_consumo/`
 * com um PostgreSQL real (um `ROLLBACK` sobre uma base falsa é uma lista de
 * cadeias, não um *rollback*). A reposição depois de limpar o Redis também é
 * lá. Um laço que passa com uma base falsa não prova transacções — e é por isso
 * que estes testes não são a evidência dos critérios 1 a 4.
 *
 * A base falsa registra as instruções pela ordem em que as recebe: é essa lista
 * que torna a ordem verificável, e é o mesmo padrão do
 * `eventos.publicador.test.ts`.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  ADIAMENTO_POR_OMISSAO,
  Adiar,
  ESCADA_DO_CONSUMIDOR,
  ESTADOS_DA_ENCOMENDA,
  ESTADO_PRETENDIDO,
  type Envelope,
  EstadoDesconhecidoError,
  ForaDeOrdem,
  METRICA_CONSUMIDOS,
  METRICA_RETENTATIVAS,
  type EstadoDaEncomenda,
  type MaquinaDeEstados,
  Metricas,
  REPETICAO,
  SQL_MARCAR_CONSUMIDO,
  SQL_PARA_DLQ,
  SQL_ULTIMO_SEQ,
  TENTATIVAS,
  TRANSICOES,
  atrasoDaTentativaDoConsumidor,
  consumir,
  eEstado,
  lerEnvelope,
  podeTransitar,
} from "../src/eventos/index.ts";
import { processar } from "../src/eventos/trabalho.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONSUMER = "agr";

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

/** Base falsa: guarda as instruções por ordem e devolve o que lhe dizem. */
class BdFalsa {
  readonly instrucoes: string[] = [];
  readonly parametros: unknown[][] = [];
  /** Linhas escritas pelo `INSERT ... ON CONFLICT`: 0 significa duplicado. */
  marcou = 1;
  ultimoSeq: number | null = null;
  abriuDlq = 1;
  abertas: Record<string, unknown>[] = [];
  /** Quando definido, a instrução cujo prefixo bate lança. */
  falhaEm: string | null = null;

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }> {
    const limpo = (sql.trim().split("\n")[0] ?? "").trim();
    this.instrucoes.push(limpo);
    this.parametros.push([...parametros]);
    if (this.falhaEm !== null && limpo.startsWith(this.falhaEm)) {
      throw new Error(`falha simulada em ${limpo}`);
    }
    if (sql === SQL_MARCAR_CONSUMIDO) {
      return { rows: [], rowCount: this.marcou };
    }
    if (sql === SQL_ULTIMO_SEQ) {
      return { rows: [{ ultimo: this.ultimoSeq }], rowCount: 1 };
    }
    if (sql === SQL_PARA_DLQ) {
      return { rows: [], rowCount: this.abriuDlq };
    }
    if (sql.includes("estado = 'aberta'")) {
      return { rows: this.abertas, rowCount: this.abertas.length };
    }
    return { rows: [], rowCount: 0 };
  }
}

/** Máquina que devolve o estado que lhe disserem, e conta as perguntas. */
class MaquinaFalsa implements MaquinaDeEstados {
  perguntas = 0;
  readonly #estado: string | null;

  constructor(estado: string | null) {
    this.#estado = estado;
  }

  async estadoDe(): Promise<EstadoDaEncomenda | null> {
    this.perguntas += 1;
    return this.#estado as EstadoDaEncomenda | null;
  }
}

/**
 * O parâmetro `n` da instrução cujo prefixo bate, ou falha o teste.
 *
 * Com `noUncheckedIndexedAccess`, `bd.parametros[i][n]` é `unknown | undefined`
 * e o compilador recusa. Um `!` calava-o; isto diz **qual** foi a instrução que
 * não apareceu, que é o que interessa quando um teste quebra.
 */
function parametro(bd: BdFalsa, prefixo: string, n: number): unknown {
  const indice = bd.instrucoes.findIndex((i) => i.startsWith(prefixo));
  assert.notEqual(indice, -1, `nenhuma instrução começa por ${prefixo}`);
  const linha = bd.parametros[indice];
  assert.ok(linha !== undefined, `sem parâmetros para ${prefixo}`);
  return linha[n];
}


describe("a máquina de estados do §6.1", () => {
  it("tem os doze estados do diagrama", () => {
    assert.equal(ESTADOS_DA_ENCOMENDA.length, 12);
    assert.ok(eEstado("aguarda_pagamento"));
    assert.ok(!eEstado("pago"));
  });

  it("deixa aguarda_pagamento → paga, que é a transição do ADR-013", () => {
    assert.ok(podeTransitar("aguarda_pagamento", "paga"));
  });

  it("recusa criada → paga: o paga só por evento autenticado sobre referência emitida", () => {
    assert.ok(!podeTransitar("criada", "paga"));
  });

  it("deixa expirada → paga, porque o pagamento tardio existe no Multicaixa", () => {
    assert.ok(podeTransitar("expirada", "paga"));
  });

  it("não deixa sair de cancelada nem de reembolsada", () => {
    assert.deepEqual(TRANSICOES.cancelada, []);
    assert.deepEqual(TRANSICOES.reembolsada, []);
  });

  it("lança num estado que não é do diagrama, em vez de devolver false", () => {
    // `false` aqui era indistinguível de «a transição não existe», e a
    // diferença decide entre adiar e DLQ.
    assert.throws(() => podeTransitar("inventado", "paga"), EstadoDesconhecidoError);
    assert.throws(() => podeTransitar("paga", "inventado"), EstadoDesconhecidoError);
  });

  it("todo o destino declarado é um estado conhecido", () => {
    for (const [de, paras] of Object.entries(TRANSICOES)) {
      assert.ok(eEstado(de), de);
      for (const para of paras) assert.ok(eEstado(para), `${de} -> ${para}`);
    }
  });

  it("os tipos com estado pretendido são os que mexem na encomenda", () => {
    assert.equal(ESTADO_PRETENDIDO["payment.confirmed"], "paga");
    assert.equal(ESTADO_PRETENDIDO["payment.manual_confirmed"], "paga");
    assert.equal(ESTADO_PRETENDIDO["order.created"], undefined);
  });
});

describe("a escada do consumidor", () => {
  it("é a do §6.4: 1 s, 5 s, 30 s, 2 min, 10 min", () => {
    assert.deepEqual([...ESCADA_DO_CONSUMIDOR], [1_000, 5_000, 30_000, 120_000, 600_000]);
  });

  it("tem uma entrada por retentativa, e o total são as seis do critério 2", () => {
    assert.equal(TENTATIVAS, 6);
    assert.equal(ESCADA_DO_CONSUMIDOR.length, TENTATIVAS - 1);
  });

  it("é o mesmo número que o `add` pede à fila", () => {
    // Dois números iguais escritos em dois ficheiros divergem; este teste é o
    // que os prende.
    assert.equal(REPETICAO.tentativas, TENTATIVAS);
  });

  it("não cresce acima do último degrau", () => {
    assert.equal(atrasoDaTentativaDoConsumidor(5), 600_000);
    assert.equal(atrasoDaTentativaDoConsumidor(9), 600_000);
  });

  it("recusa uma tentativa que não é um inteiro positivo", () => {
    assert.throws(() => atrasoDaTentativaDoConsumidor(0), RangeError);
    assert.throws(() => atrasoDaTentativaDoConsumidor(1.5), RangeError);
  });
});

describe("consumir()", () => {
  let bd: BdFalsa;
  let metricas: Metricas;

  beforeEach(() => {
    bd = new BdFalsa();
    metricas = new Metricas();
  });

  it("marca, aplica e fecha — por esta ordem", async () => {
    const feitos: string[] = [];
    const resultado = await consumir(
      { bd, consumer: CONSUMER, envelope: envelope(), exigeOrdem: false, metricas },
      async () => {
        feitos.push("efeito");
      },
    );
    assert.equal(resultado.desfecho, "aplicado");
    assert.deepEqual(bd.instrucoes, [
      "BEGIN",
      "INSERT INTO platform.events_consumed",
      "COMMIT",
    ]);
    assert.deepEqual(feitos, ["efeito"]);
    assert.equal(metricas.ler()[`${METRICA_CONSUMIDOS}:aplicado`], 1);
  });

  it("o efeito corre entre a marca e o COMMIT, e não fora da transacção", async () => {
    await consumir(
      { bd, consumer: CONSUMER, envelope: envelope(), exigeOrdem: false },
      async (cliente) => {
        await cliente.query("UPDATE platform.orders SET estado = $1", ["paga"]);
      },
    );
    assert.deepEqual(bd.instrucoes, [
      "BEGIN",
      "INSERT INTO platform.events_consumed",
      "UPDATE platform.orders SET estado = $1",
      "COMMIT",
    ]);
  });

  it("um duplicado fecha sem efeito nenhum", async () => {
    bd.marcou = 0;
    let correu = false;
    const resultado = await consumir(
      { bd, consumer: CONSUMER, envelope: envelope(), exigeOrdem: false, metricas },
      async () => {
        correu = true;
      },
    );
    assert.equal(resultado.desfecho, "duplicado");
    assert.ok(!correu, "o efeito não pode correr num duplicado");
    assert.deepEqual(bd.instrucoes, [
      "BEGIN",
      "INSERT INTO platform.events_consumed",
      "COMMIT",
    ]);
    assert.equal(metricas.ler()[`${METRICA_CONSUMIDOS}:duplicado`], 1);
  });

  it("os parâmetros da marca são os seis do DDL, com o tenant do envelope", async () => {
    const env = envelope();
    await consumir(
      { bd, consumer: CONSUMER, envelope: env, exigeOrdem: false },
      async () => {},
    );
    assert.deepEqual(bd.parametros[1], [
      CONSUMER,
      env.id,
      env.tenant_id,
      env.agregado.tipo,
      env.agregado.id,
      env.agregado.seq,
    ]);
  });

  it("sem exigir ordem, não lê o último seq nem pergunta à máquina", async () => {
    const maquina = new MaquinaFalsa("criada");
    await consumir(
      { bd, consumer: CONSUMER, envelope: envelope(), exigeOrdem: false, maquina },
      async () => {},
    );
    assert.ok(!bd.instrucoes.some((i) => i.startsWith("SELECT max(agregado_seq)")));
    assert.equal(maquina.perguntas, 0);
  });

  it("exclui o próprio evento ao ler o último seq", async () => {
    const env = envelope({ tipo: "payment.confirmed" });
    const maquina = new MaquinaFalsa("aguarda_pagamento");
    await consumir(
      { bd, consumer: CONSUMER, envelope: env, exigeOrdem: true, maquina },
      async () => {},
    );
    const indice = bd.instrucoes.findIndex((i) => i.startsWith("SELECT max(agregado_seq)"));
    assert.ok(indice > 0);
    assert.deepEqual(bd.parametros[indice], [
      CONSUMER,
      env.agregado.tipo,
      env.agregado.id,
      env.id,
    ]);
  });

  it("adia quando o agregado ainda não existe neste consumidor", async () => {
    const maquina = new MaquinaFalsa(null);
    await assert.rejects(
      consumir(
        {
          bd,
          consumer: CONSUMER,
          envelope: envelope({ tipo: "payment.confirmed" }),
          exigeOrdem: true,
          maquina,
          metricas,
        },
        async () => {},
      ),
      (erro: unknown) => {
        assert.ok(erro instanceof Adiar);
        assert.equal(erro.segundos, ADIAMENTO_POR_OMISSAO);
        return true;
      },
    );
    assert.ok(bd.instrucoes.includes("ROLLBACK"));
    assert.equal(metricas.ler()[`${METRICA_RETENTATIVAS}:adiado`], 1);
  });

  it("adia um payment.confirmed antes de aguarda_pagamento, e não aplica nada", async () => {
    const maquina = new MaquinaFalsa("criada");
    let correu = false;
    await assert.rejects(
      consumir(
        {
          bd,
          consumer: CONSUMER,
          envelope: envelope({ tipo: "payment.confirmed" }),
          exigeOrdem: true,
          maquina,
        },
        async () => {
          correu = true;
        },
      ),
      Adiar,
    );
    assert.ok(!correu, "a transição inválida não pode aplicar-se");
    assert.ok(bd.instrucoes.includes("ROLLBACK"));
  });

  it("é fora_de_ordem quando o seq vem atrasado E a transição é inválida", async () => {
    bd.ultimoSeq = 7;
    const maquina = new MaquinaFalsa("paga");
    await assert.rejects(
      consumir(
        {
          bd,
          consumer: CONSUMER,
          envelope: envelope({
            tipo: "payment.confirmed",
            agregado: { tipo: "order", id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50", seq: 3 },
          }),
          exigeOrdem: true,
          maquina,
        },
        async () => {},
      ),
      (erro: unknown) => {
        assert.ok(erro instanceof ForaDeOrdem);
        assert.match(erro.message, /fora_de_ordem/);
        return true;
      },
    );
  });

  it("um erro do efeito faz ROLLBACK e propaga-se", async () => {
    await assert.rejects(
      consumir(
        { bd, consumer: CONSUMER, envelope: envelope(), exigeOrdem: false },
        async () => {
          throw new Error("o efeito falhou");
        },
      ),
      /o efeito falhou/,
    );
    assert.deepEqual(bd.instrucoes, [
      "BEGIN",
      "INSERT INTO platform.events_consumed",
      "ROLLBACK",
    ]);
  });

  it("recusa exigir ordem sobre um tipo com estado pretendido sem máquina", async () => {
    await assert.rejects(
      consumir(
        {
          bd,
          consumer: CONSUMER,
          envelope: envelope({ tipo: "payment.confirmed" }),
          exigeOrdem: true,
        },
        async () => {},
      ),
      /máquina de estados/,
    );
  });
});

describe("processar(): a política das seis tentativas", () => {
  let bd: BdFalsa;
  let metricas: Metricas;

  beforeEach(() => {
    bd = new BdFalsa();
    metricas = new Metricas();
  });

  const base = (extra: Record<string, unknown> = {}) => ({
    bd,
    consumer: CONSUMER,
    envelope: envelope({ tipo: "payment.confirmed" }),
    exigeOrdem: true,
    metricas,
    tentativa: 1,
    ...extra,
  });

  it("devolve aplicado quando corre bem", async () => {
    const resultado = await processar(
      { ...base(), maquina: new MaquinaFalsa("aguarda_pagamento") },
      async () => {},
    );
    assert.equal(resultado.desfecho, "aplicado");
  });

  it("adia nas cinco primeiras tentativas, sem tocar na DLQ", async () => {
    for (const tentativa of [1, 2, 3, 4, 5]) {
      const resultado = await processar(
        { ...base({ tentativa }), maquina: new MaquinaFalsa("criada") },
        async () => {},
      );
      assert.equal(resultado.desfecho, "adiado");
      assert.equal(resultado.adiamento, ADIAMENTO_POR_OMISSAO);
    }
    assert.ok(!bd.instrucoes.some((i) => i.startsWith("INSERT INTO platform.events_dlq")));
  });

  it("na sexta tentativa abre a DLQ, e não aplica a transição", async () => {
    const resultado = await processar(
      { ...base({ tentativa: TENTATIVAS }), maquina: new MaquinaFalsa("criada") },
      async () => {
        throw new Error("o efeito nunca devia correr");
      },
    );
    assert.equal(resultado.desfecho, "dlq");
    assert.match(resultado.erro ?? "", /adiado_sem_resolver/);
    assert.ok(bd.instrucoes.some((i) => i.startsWith("INSERT INTO platform.events_dlq")));
  });

  it("fora_de_ordem vai directo à DLQ, na primeira tentativa", async () => {
    bd.ultimoSeq = 9;
    const resultado = await processar(
      {
        ...base({
          envelope: envelope({
            tipo: "payment.confirmed",
            agregado: { tipo: "order", id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50", seq: 2 },
          }),
        }),
        maquina: new MaquinaFalsa("paga"),
      },
      async () => {},
    );
    assert.equal(resultado.desfecho, "dlq");
    assert.equal(resultado.erro, ForaDeOrdem.CODIGO);
    // O erro que vai para a coluna é exactamente o código do critério 4.
    assert.equal(
      parametro(bd, "INSERT INTO platform.events_dlq", 6),
      ForaDeOrdem.CODIGO,
    );
  });

  it("um erro técnico relança enquanto houver tentativas", async () => {
    await assert.rejects(
      processar({ ...base({ tentativa: 2 }), maquina: new MaquinaFalsa("aguarda_pagamento") }, async () => {
        throw new Error("a rede caiu");
      }),
      /a rede caiu/,
    );
    assert.equal(metricas.ler()[`${METRICA_RETENTATIVAS}:erro`], 1);
    assert.ok(!bd.instrucoes.some((i) => i.startsWith("INSERT INTO platform.events_dlq")));
  });

  it("um erro técnico na última tentativa vai para a DLQ com a mensagem", async () => {
    const resultado = await processar(
      { ...base({ tentativa: TENTATIVAS }), maquina: new MaquinaFalsa("aguarda_pagamento") },
      async () => {
        throw new Error("a rede caiu");
      },
    );
    assert.equal(resultado.desfecho, "dlq");
    assert.match(resultado.erro ?? "", /a rede caiu/);
  });

  it("um duplicado não conta tentativa nem toca na DLQ", async () => {
    bd.marcou = 0;
    const resultado = await processar(
      { ...base({ tentativa: TENTATIVAS }), maquina: new MaquinaFalsa("criada") },
      async () => {},
    );
    assert.equal(resultado.desfecho, "duplicado");
  });

  it("recusa uma tentativa que não é um inteiro positivo", async () => {
    await assert.rejects(
      processar({ ...base({ tentativa: 0 }) }, async () => {}),
      RangeError,
    );
  });
});
