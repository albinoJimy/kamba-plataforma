/**
 * Guarda de PII: os dois padrões do `evt_emitir` (KAM-005 CA6).
 *
 * As cadeias deste ficheiro são as mesmas que a suite do gate 8 corre contra o
 * PostgreSQL (`db/tests/test_eventos_schema.TestParidadeDoGuardaDePii` lê-as
 * de `tests/fixtures/eventos_pii.json`). Duas implementações do mesmo predicado
 * só se mantêm honestas se houver uma máquina a confrontá-las — e a fixture é
 * o sítio onde as duas se encontram.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  E164_ENTRE_ASPAS,
  PadraoDeTelefoneError,
  TELEFONE_AO,
  exigirSemTelefone,
  padraoDeTelefoneEm,
} from "../src/eventos/index.ts";

interface Fixture {
  readonly nota: string;
  readonly apanhados: readonly string[];
  readonly passam: readonly string[];
}

const FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/eventos_pii.json", import.meta.url), "utf8"),
) as Fixture;

describe("guarda de PII — o que e apanhado", () => {
  for (const cadeia of FIXTURE.apanhados) {
    it(JSON.stringify(cadeia), () => {
      assert.notEqual(padraoDeTelefoneEm(cadeia), null);
    });
  }
});

describe("guarda de PII — o que passa", () => {
  for (const cadeia of FIXTURE.passam) {
    it(JSON.stringify(cadeia), () => {
      assert.equal(padraoDeTelefoneEm(cadeia), null);
    });
  }
});

describe("guarda de PII — os padroes sao os do SQL", () => {
  it("o primeiro e `\\+?244 ?9[0-9]{8}`", () => {
    assert.equal(TELEFONE_AO.source, "\\+?244 ?9[0-9]{8}");
  });

  it('o segundo e `"\\+[0-9]{9,15}"`', () => {
    assert.equal(E164_ENTRE_ASPAS.source, '"\\+[0-9]{9,15}"');
  });

  it("nao sao ancorados: procuram em qualquer posicao, como o `~`", () => {
    assert.equal(TELEFONE_AO.flags, "");
    assert.ok(padraoDeTelefoneEm("lixo antes 244912345678 lixo depois"));
  });
});

describe("exigirSemTelefone", () => {
  it("serializa o objecto, como o `::text` do SQL", () => {
    assert.throws(
      () => exigirSemTelefone({ recipient: "+244912345678" }, "payload"),
      PadraoDeTelefoneError,
    );
  });

  it("nao poe o valor na mensagem: o valor e PII P2", () => {
    try {
      exigirSemTelefone({ recipient: "+244912345678" }, "payload");
      assert.fail("devia ter lancado");
    } catch (erro) {
      assert.ok(erro instanceof PadraoDeTelefoneError);
      assert.doesNotMatch(erro.message, /244912345678/);
      assert.match(erro.message, /payload/);
      assert.equal(erro.padrao, TELEFONE_AO.source);
    }
  });

  it("um payload sem telefone passa", () => {
    exigirSemTelefone(
      { order_id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50", valor_minor: 1 },
      "payload",
    );
  });

  it("`undefined` passa: nao ha texto onde procurar", () => {
    exigirSemTelefone(undefined, "payload");
  });
});
