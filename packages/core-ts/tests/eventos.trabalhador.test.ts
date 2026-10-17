/**
 * A tradução entre o BullMQ e a política, sem BullMQ (KAM-006).
 *
 * O `trabalhador_bullmq.ts` é casca — mas é casca com três decisões dentro, e
 * nenhuma delas era exercitada por teste nenhum até este ficheiro existir: de
 * onde vem o `tenant_id`, o que acontece quando o arquivo não responde, e o
 * que fica guardado quando não há envelope para guardar. A *suite* com fila
 * passa por aqui, mas só pelo caminho feliz e com uma partição de cada vez.
 *
 * O que **não** se testa aqui, e porquê: `criarTrabalhadores()` abre uma
 * ligação a Redis e cria *workers*, pelo que precisa de uma fila real — isso é
 * `db/tests_eventos_consumo/`. O que se testa são as funções que a decisão
 * usa, que são puras ou só falam com a base.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { lerEnvelope } from "../src/eventos/envelope.ts";
import {
  EventoDesconhecidoError,
  SQL_ENVELOPE_DO_EVENTO,
  TenantEmFaltaError,
  envelopeDoEvento,
  tenantDoJob,
} from "../src/eventos/trabalhador_bullmq.ts";
import {
  TIPO_ILEGIVEL,
  VERSAO_ILEGIVEL,
  paraDlqSemEnvelope,
} from "../src/eventos/dlq.ts";
import { SQL_PARA_DLQ } from "../src/eventos/consultas_consumo.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const EVENTO = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44";
const CONSUMER = "agr";

function envelope(parcial: Partial<Record<string, unknown>> = {}) {
  return {
    id: EVENTO,
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
  };
}

class BdFalsa {
  readonly instrucoes: string[] = [];
  readonly parametros: unknown[][] = [];
  /** O que o arquivo devolve. Vazio ⇒ o evento não está lá. */
  arquivo: Record<string, unknown>[] = [{ envelope: envelope() }];

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }> {
    this.instrucoes.push((sql.trim().split("\n")[0] ?? "").trim());
    this.parametros.push([...parametros]);
    if (sql === SQL_ENVELOPE_DO_EVENTO) {
      return { rows: this.arquivo, rowCount: this.arquivo.length };
    }
    return { rows: [], rowCount: 1 };
  }
}

function parametros(bd: BdFalsa, prefixo: string): unknown[] {
  const indice = bd.instrucoes.findIndex((i) => i.startsWith(prefixo));
  assert.notEqual(indice, -1, `nenhuma instrução começa por ${prefixo}`);
  const linha = bd.parametros[indice];
  assert.ok(linha !== undefined, `sem parâmetros para ${prefixo}`);
  return linha;
}

describe("de onde vem o tenant_id do job", () => {
  it("do campo de topo, que é onde o publicador e o reconciliador o põem", () => {
    assert.equal(tenantDoJob({ tenant_id: TENANT, envelope: envelope() }), TENANT);
  });

  it("de dentro do envelope, para um job criado antes de o campo existir", () => {
    // Sem esta tolerância, um *job* já em fila no momento do *deploy* ia para
    // a DLQ como «sem tenant» — uma migração a partir um evento bom.
    assert.equal(tenantDoJob({ envelope: envelope() }), TENANT);
  });

  it("vazio quando não há nenhum dos dois, e vazio não é um tenant", () => {
    for (const dados of [undefined, null, {}, { envelope: null }, "texto", 7]) {
      assert.equal(tenantDoJob(dados), "", `dados: ${JSON.stringify(dados)}`);
    }
  });

  it("o campo de topo ganha ao do envelope", () => {
    const outro = "11111111-2222-4333-8444-555555555555";
    assert.equal(tenantDoJob({ tenant_id: outro, envelope: envelope() }), outro);
  });
});

describe("a leitura do envelope no arquivo", () => {
  let bd: BdFalsa;

  beforeEach(() => {
    bd = new BdFalsa();
  });

  it("põe o contexto antes de ler, e de sessão: a leitura não está em transacção", async () => {
    await envelopeDoEvento(bd, EVENTO, TENANT);
    assert.equal(bd.instrucoes[0], "SELECT set_config('app.tenant_id', $1, $2)");
    assert.deepEqual(bd.parametros[0], [TENANT, false]);
    assert.ok(bd.instrucoes[1]?.startsWith("SELECT envelope"));
  });

  it("recusa um job sem tenant antes de tocar na base", async () => {
    // Sem contexto, a RLS devolve zero linhas e isso lê-se «o arquivo não tem
    // este evento» — a mensagem errada para o problema certo.
    await assert.rejects(envelopeDoEvento(bd, EVENTO, ""), TenantEmFaltaError);
    assert.deepEqual(bd.instrucoes, [], "não pode ir à base sem contexto");
  });

  it("zero linhas é «o arquivo não tem este evento»", async () => {
    bd.arquivo = [];
    await assert.rejects(envelopeDoEvento(bd, EVENTO, TENANT), EventoDesconhecidoError);
  });

  it("devolve o envelope já validado", async () => {
    const lido = await envelopeDoEvento(bd, EVENTO, TENANT);
    assert.deepEqual(lido, lerEnvelope(envelope()));
  });
});

describe("a entrada na DLQ sem envelope", () => {
  let bd: BdFalsa;

  beforeEach(() => {
    bd = new BdFalsa();
  });

  it("escreve os oito parâmetros, com o tipo e a versão que a marcam como ilegível", async () => {
    const resultado = await paraDlqSemEnvelope({
      bd,
      consumer: CONSUMER,
      eventId: EVENTO,
      tenantId: TENANT,
      erro: "o evento não está em events_log",
      tentativas: 6,
    });
    assert.ok(resultado.abriu);
    const escritos = parametros(bd, "INSERT INTO platform.events_dlq");
    assert.equal(escritos[0], CONSUMER);
    assert.equal(escritos[1], EVENTO);
    assert.equal(escritos[2], TIPO_ILEGIVEL);
    assert.equal(escritos[3], VERSAO_ILEGIVEL);
    assert.equal(escritos[4], TENANT);
    assert.equal(escritos[7], 6);
    // O que vai no lugar do envelope diz que não é um envelope. Sem isto,
    // alguém lê a entrada e tenta reprocessá-la como se fosse um evento.
    const substituto = JSON.parse(String(escritos[5])) as Record<string, unknown>;
    assert.equal(substituto.id, EVENTO);
    assert.match(String(substituto.aviso), /não é um envelope/);
  });

  it("abre a sua própria transacção, com o contexto do tenant do job", async () => {
    await paraDlqSemEnvelope({
      bd,
      consumer: CONSUMER,
      eventId: EVENTO,
      tenantId: TENANT,
      erro: "x",
      tentativas: 6,
    });
    assert.deepEqual(bd.instrucoes, [
      "BEGIN",
      "SELECT set_config('app.tenant_id', $1, $2)",
      "INSERT INTO platform.events_dlq",
      "COMMIT",
    ]);
  });

  it("o tipo ilegível não é Sev1: não move dinheiro, e dizer que move era ruído", async () => {
    const resultado = await paraDlqSemEnvelope({
      bd,
      consumer: CONSUMER,
      eventId: EVENTO,
      tenantId: TENANT,
      erro: "x",
      tentativas: 6,
    });
    // Sev2 pela idade, como qualquer outra: o que se perdeu pode ser um
    // `payment.*`, mas não se sabe — e inventar a severidade era afirmar o
    // que não se sabe. A entrada existe, que é o que faltava.
    assert.equal(resultado.severidade, "nenhuma");
  });

  it("o tipo casa a gramática da etiqueta de evt_dlq_open", () => {
    // Se não casasse, `publicarAbertas()` rebentava com `EtiquetaInvalidaError`
    // ao chegar a esta entrada — e deixava de publicar as outras.
    assert.match(TIPO_ILEGIVEL, /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/);
  });

  it("usa a mesma instrução que o paraDlq com envelope", () => {
    assert.ok(SQL_PARA_DLQ.includes("INSERT INTO platform.events_dlq"));
    assert.ok(
      SQL_PARA_DLQ.includes(
        "ON CONFLICT (consumer, event_id) WHERE estado = 'aberta' DO NOTHING",
      ),
      "o predicado é o que faz o PostgreSQL inferir o índice parcial: sem ele, "
        + "uma entrada já resolvida engolia a falha seguinte",
    );
  });
});
