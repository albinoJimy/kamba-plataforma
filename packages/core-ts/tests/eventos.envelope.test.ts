/**
 * Envelope v1: o que se aceita e o que se recusa (KAM-005).
 *
 * O envelope de referência é o do `docs/tecnica/06` §4 — o mesmo exemplo, campo
 * por campo. Cada caso negativo parte dele e estraga **uma** coisa: um caso que
 * estrague duas não diz qual delas o validador apanhou.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  CAMPOS_DO_ENVELOPE,
  EnvelopeInvalidoError,
  FINALIDADES,
  FINALIDADES_POR_VERSAO,
  FINALIDADES_SO_NA_V2,
  FINALIDADES_V1,
  lerEnvelope,
} from "../src/eventos/index.ts";

/** O envelope do `docs/tecnica/06` §4, literal. */
const REFERENCIA = {
  id: "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44",
  tipo: "payment.confirmed",
  versao: 1,
  tenant_id: "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60",
  ocorrido_em: "2026-11-02T14:03:11.482Z",
  registado_em: "2026-11-02T14:03:11.610Z",
  produtor: "pay-core@1.4.2",
  agregado: {
    tipo: "order",
    id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50",
    seq: 3,
  },
  correlacao_id: "5a6b7c8d-1e2f-4a3b-8c9d-0e1f2a3b4c5d",
  causa_id: "0192f1c4-6a10-7a11-8b22-3c33d44e5f66",
  trace_id: "4bf92f3577b34da6a3ce929d0e0e4736",
  classe_pii: "P0",
  finalidades: ["transacao"],
  payload: {
    order_id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50",
    provider: "facilitador_x",
    referencia: "102345678",
    valor_minor: 24500000,
    currency: "AOA",
  },
};

function com(mudanca: Record<string, unknown>): Record<string, unknown> {
  return { ...REFERENCIA, ...mudanca };
}

function recusa(valor: unknown, parte: string): void {
  assert.throws(
    () => lerEnvelope(valor),
    (erro: unknown) => {
      assert.ok(erro instanceof EnvelopeInvalidoError, String(erro));
      assert.match(erro.message, new RegExp(parte));
      return true;
    },
  );
}

describe("envelope v1 — o exemplo do doc 06 §4", () => {
  it("passa, e sai com os campos todos", () => {
    const envelope = lerEnvelope(REFERENCIA);
    assert.equal(envelope.id, REFERENCIA.id);
    assert.equal(envelope.tipo, "payment.confirmed");
    assert.equal(envelope.versao, 1);
    assert.equal(envelope.agregado.seq, 3);
    assert.deepEqual([...envelope.finalidades], ["transacao"]);
    assert.equal(envelope.payload.valor_minor, 24500000);
  });

  it("passa igual em texto JSON", () => {
    assert.deepEqual(
      lerEnvelope(JSON.stringify(REFERENCIA)),
      lerEnvelope(REFERENCIA),
    );
  });

  it("os catorze campos de topo sao os que o validador conhece", () => {
    assert.deepEqual(
      [...CAMPOS_DO_ENVELOPE].sort(),
      Object.keys(REFERENCIA).sort(),
    );
  });
});

describe("envelope v1 — o que se recusa", () => {
  it("texto que nao e JSON", () => {
    recusa("{nao e json", "nao e JSON");
  });

  it("um campo de topo desconhecido, e nao ignorado", () => {
    recusa(com({ cliente_msisdn: "+244912345678" }), "cliente_msisdn");
  });

  it("um campo em falta", () => {
    const sem = { ...REFERENCIA } as Record<string, unknown>;
    delete sem.registado_em;
    recusa(sem, "registado_em");
  });

  it("`id` que nao e UUID canonico", () => {
    recusa(com({ id: "0192F1C4-7B1E-7D2A-9C3E-5A1F0B6E2D44" }), "id");
    recusa(com({ id: "nao-e-uuid" }), "id");
  });

  it("`versao` zero, negativa ou fraccionaria", () => {
    for (const versao of [0, -1, 1.5]) {
      recusa(com({ versao }), "versao");
    }
  });

  it("`tipo` que nao e `familia.verbo` em minusculas", () => {
    for (const tipo of ["Payment.Confirmed", "payment", "payment..confirmed"]) {
      recusa(com({ tipo }), "tipo");
    }
  });

  it("`agregado.seq` zero: o contador comeca em 1", () => {
    recusa(com({ agregado: { ...REFERENCIA.agregado, seq: 0 } }), "agregado.seq");
  });

  it("`finalidades` vazio: sem finalidade nao se entrega a ninguem", () => {
    recusa(com({ finalidades: [] }), "finalidades");
  });

  it("`classe_pii` P2: proibida no envelope", () => {
    recusa(com({ classe_pii: "P2" }), "P2");
  });

  it("`classe_pii` desconhecida", () => {
    recusa(com({ classe_pii: "P9" }), "classe_pii");
  });

  it("`payload` que e lista e nao objecto", () => {
    recusa(com({ payload: [1, 2] }), "payload");
  });

  it("`agregado` nulo", () => {
    recusa(com({ agregado: null }), "agregado");
  });
});

describe("envelope v1 — o que e opcional e pode ser nulo", () => {
  for (const campo of ["produtor", "correlacao_id", "causa_id", "trace_id"]) {
    it(`\`${campo}\` nulo passa`, () => {
      const envelope = lerEnvelope(com({ [campo]: null }));
      assert.equal(envelope[campo as "produtor"], null);
    });
  }
});

describe("finalidades", () => {
  /** O `enum` das finalidades do envelope, numa versão do contrato. */
  function doContrato(versao: number): string[] {
    const caminho = new URL(
      `../../../contratos/eventos/consent.recorded/v${versao}.schema.json`,
      import.meta.url,
    );
    const schema = JSON.parse(readFileSync(caminho, "utf8")) as {
      properties: { finalidades: { items: { enum: string[] } } };
    };
    return schema.properties.finalidades.items.enum;
  }

  it("as dez do dicionário §3.1, sem repetidas", () => {
    assert.equal(FINALIDADES.length, 10);
    assert.equal(new Set(FINALIDADES).size, 10);
  });

  it("são exactamente as da `v2` do contrato", () => {
    // O gate 7 compara o contrato com o dicionário, nos dois sentidos. Falta
    // o terceiro lado do triângulo, que é esta constante — e a falta não é
    // teórica: no KAM-159 a lista passou de oito para dez, os 38 contratos
    // ganharam uma `v2`, e **o teste desta lista continuou a pedir oito**.
    // Nenhum gate ligava os dois lados; o CI apanhou-o por acaso, porque o
    // número estava escrito à mão aqui.
    assert.deepEqual([...FINALIDADES].sort(), [...doContrato(2)].sort());
  });

  it("as da `v1` são exactamente as do `enum` da `v1` do contrato", () => {
    assert.deepEqual([...FINALIDADES_V1].sort(), [...doContrato(1)].sort());
  });

  it("as que só a `v2` tem são, por construção, as que a `v1` não tinha", () => {
    // Derivadas, e não escritas à mão: uma lista fixa divergiria do contrato
    // no dia em que uma `v3` acrescentasse outra finalidade, e o conversor
    // passaria a aceitar o que não consegue representar numa `v1`.
    const naV1 = new Set(doContrato(1));
    assert.deepEqual(
      [...FINALIDADES_SO_NA_V2].sort(),
      FINALIDADES.filter((f) => !naV1.has(f)).sort(),
    );
  });
});

describe("o domínio de `finalidades` é imposto pelo leitor, e pela versão", () => {
  // O docstring de `FINALIDADES` dizia «lista fechada» e **nada a fechava**:
  // o `lerEnvelope` só verificava que era um array não vazio de cadeias. Um
  // envelope `versao: 1` com `partilha_estafeta` passava aqui e era recusado
  // lá à frente pelo `v1.schema.json` — ou seja, a premissa do conversor («a
  // `v1` não as tem») não tinha guarda nenhuma deste lado.

  it("uma finalidade que não existe em domínio nenhum é recusada", () => {
    recusa(com({ finalidades: ["finalidade_que_nao_existe"] }), "nao estao no dominio");
  });

  it("uma finalidade só da `v2` é recusada num envelope `v1`", () => {
    for (const nova of FINALIDADES_SO_NA_V2) {
      recusa(com({ versao: 1, finalidades: [nova] }), "dominio da v1");
    }
  });

  it("a mesma finalidade passa num envelope `v2`", () => {
    // O controlo: sem ele, o teste anterior passaria também se o leitor
    // recusasse a finalidade em **qualquer** versão, que é o oposto do que
    // o §6.6 quer.
    for (const nova of FINALIDADES_SO_NA_V2) {
      const envelope = lerEnvelope(com({ versao: 2, finalidades: [nova] }));
      assert.deepEqual(envelope.finalidades, [nova]);
    }
  });

  it("uma versão sem domínio declarado é recusada, e não aceite em branco", () => {
    // Fail-closed: uma `v3` do envelope acrescenta a sua linha em
    // `FINALIDADES_POR_VERSAO`. Aceitá-la sem domínio era aceitar qualquer
    // finalidade por a versão ser nova.
    recusa(com({ versao: 3 }), "nao tem dominio de finalidades declarado");
  });

  it("as duas versões declaradas são as que os contratos têm", () => {
    assert.deepEqual([...FINALIDADES_POR_VERSAO.keys()].sort(), [1, 2]);
  });
});
