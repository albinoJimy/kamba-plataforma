/**
 * O gancho de conversão de versão (KAM-005, `docs/tecnica/06` §6.6).
 *
 * Duas coisas a provar: que o registo do processo está **vazio** — é o que o
 * ticket pede — e que vazio não quer dizer inerte.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CONVERSORES,
  ConversaoInvalidaError,
  type Envelope,
  FINALIDADES_SO_NA_V2,
  descerFinalidades,
  RegistoDeConversores,
  SemConversorError,
  lerEnvelope,
} from "../src/eventos/index.ts";

function envelope(versao: number): Envelope {
  return lerEnvelope({
    id: "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44",
    tipo: "order.created",
    versao,
    tenant_id: "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60",
    ocorrido_em: "2026-11-02T14:03:11.482Z",
    registado_em: "2026-11-02T14:03:11.610Z",
    produtor: null,
    agregado: { tipo: "order", id: "o1", seq: 4 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P1",
    finalidades: ["transacao"],
    payload: { order_id: "o1" },
  });
}

describe("o registo do processo", () => {
  it("esta vazio — e o que o ticket pede («gancho vazio»)", () => {
    assert.equal(CONVERSORES.tamanho, 0);
  });
});

describe("converter", () => {
  it("v1 para um consumidor de v1: devolve o mesmo envelope", () => {
    const registo = new RegistoDeConversores();
    const original = envelope(1);
    assert.equal(registo.converter(original, 1), original);
  });

  it("v1 para um consumidor que aceita v2: devolve o mesmo (nao se sobe)", () => {
    const registo = new RegistoDeConversores();
    const original = envelope(1);
    assert.equal(registo.converter(original, 2), original);
  });

  it("v2 para um consumidor de v1 **sem** conversor lanca", () => {
    const registo = new RegistoDeConversores();
    assert.throws(() => registo.converter(envelope(2), 1), (erro: unknown) => {
      assert.ok(erro instanceof SemConversorError);
      assert.equal(erro.de, 2);
      assert.equal(erro.para, 1);
      assert.match(erro.message, /NAO e descartado/);
      return true;
    });
  });

  it("com conversor registado, converte", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({ ...e, versao: 1 }));
    assert.equal(registo.tem("order.created", 2, 1), true);
    const convertido = registo.converter(envelope(2), 1);
    assert.equal(convertido.versao, 1);
    assert.equal(convertido.id, envelope(2).id);
  });

  it("o conversor de um tipo nao serve outro", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({ ...e, versao: 1 }));
    const outro = { ...envelope(2), tipo: "order.paid" } as Envelope;
    assert.throws(() => registo.converter(outro, 1), SemConversorError);
  });
});

describe("um conversor tem de preservar `id` e `agregado.seq` (§6.6)", () => {
  it("mudar o `id` e recusado: a deduplicacao por jobId deixa de valer", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({
      ...e,
      versao: 1,
      id: "11111111-1111-1111-1111-111111111111",
    }));
    assert.throws(() => registo.converter(envelope(2), 1), (erro: unknown) => {
      assert.ok(erro instanceof ConversaoInvalidaError);
      assert.match(erro.message, /mudou o `id`/);
      return true;
    });
  });

  it("mudar o `agregado.seq` e recusado: a ordem causal quebra", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({
      ...e,
      versao: 1,
      agregado: { ...e.agregado, seq: 99 },
    }));
    assert.throws(
      () => registo.converter(envelope(2), 1),
      /mudou o `agregado.seq`/,
    );
  });

  it("devolver outra `versao` e recusado", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, (e) => ({ ...e, versao: 3 }));
    assert.throws(() => registo.converter(envelope(2), 1), /devolveu `versao` 3/);
  });

  it("registar para cima e recusado: converte-se para baixo", () => {
    const registo = new RegistoDeConversores();
    assert.throws(
      () => registo.registar("order.created", 1, 2, (e) => e),
      /converte-se para \*\*baixo\*\*/,
    );
  });
});

describe("descerFinalidades (KAM-159)", () => {
  function comFinalidades(finalidades: string[], versao = 2): Envelope {
    const base = envelope(versao);
    return { ...base, finalidades: finalidades as Envelope["finalidades"] };
  }

  it("desce uma v2 que nao usa as duas finalidades novas", () => {
    const descido = descerFinalidades(comFinalidades(["transacao", "marketing"]));
    assert.equal(descido.versao, 1);
    assert.deepEqual(descido.finalidades, ["transacao", "marketing"]);
  });

  it("preserva o id e o agregado.seq", () => {
    const antes = comFinalidades(["transacao"]);
    const depois = descerFinalidades(antes);
    assert.equal(depois.id, antes.id);
    assert.equal(depois.agregado.seq, antes.agregado.seq);
  });

  it("RECUSA uma finalidade que nao existe em dominio nenhum", () => {
    // A primeira versao comparava com a lista das **duas novas**, e por isso
    // deixava passar tudo o resto: uma cadeia inventada descia a `v1` sem uma
    // queixa e produzia um envelope que nenhum dos 38 `v1.schema.json`
    // aceita. Uma lista de excepcoes so conhece as excepcoes de que alguem se
    // lembrou; um dominio conhece tudo o que nao e ele.
    assert.throws(
      () => descerFinalidades(comFinalidades(["finalidade_que_nao_existe"])),
      (erro: unknown) => {
        assert.ok(erro instanceof ConversaoInvalidaError);
        assert.match(erro.message, /finalidade_que_nao_existe/);
        return true;
      },
    );
  });

  it("RECUSA um envelope sem finalidades", () => {
    // `minItems: 1` no contrato. Um envelope sem finalidades nao chega a
    // subscricao nenhuma, e descia como se fosse valido.
    assert.throws(
      () => descerFinalidades(comFinalidades([])),
      (erro: unknown) => {
        assert.ok(erro instanceof ConversaoInvalidaError);
        assert.match(erro.message, /ao menos uma/);
        return true;
      },
    );
  });

  it("RECUSA um envelope que nao e v2", () => {
    // A funcao esta exportada no `index.ts` e nao e so chamada pelo registo:
    // quem a chamar a mao com uma `v1` recebia uma `v1` de volta, e com uma
    // `v3` recebia uma `v1` sem ninguem ter traduzido nada.
    for (const versao of [1, 3]) {
      assert.throws(
        () => descerFinalidades({ ...comFinalidades(["transacao"]), versao }),
        (erro: unknown) => {
          assert.ok(erro instanceof ConversaoInvalidaError);
          assert.match(erro.message, /desce da v2/);
          return true;
        },
      );
    }
  });

  it("RECUSA quando o envelope usa uma finalidade que a v1 nao tem", () => {
    // A tentacao e deita-la fora e entregar o resto. E a coisa errada: as
    // finalidades sao o que o publicador compara com a subscricao, pelo que
    // apagar uma muda **quem recebe o evento**.
    for (const nova of FINALIDADES_SO_NA_V2) {
      assert.throws(
        () => descerFinalidades(comFinalidades(["transacao", nova])),
        (erro: unknown) => {
          assert.ok(erro instanceof ConversaoInvalidaError);
          assert.match(erro.message, new RegExp(nova));
          assert.match(erro.message, /mudaria quem recebe o evento/);
          return true;
        },
      );
    }
  });

  it("o registo do processo continua vazio: nada emite v2 ainda", () => {
    assert.equal(CONVERSORES.tamanho, 0);
    assert.equal(CONVERSORES.tem("order.created", 2, 1), false);
  });

  it("registado a mao, o salto 2 -> 1 passa a existir", () => {
    const registo = new RegistoDeConversores();
    registo.registar("order.created", 2, 1, descerFinalidades);
    const descido = registo.converter(comFinalidades(["transacao"]), 1);
    assert.equal(descido.versao, 1);
  });
});
