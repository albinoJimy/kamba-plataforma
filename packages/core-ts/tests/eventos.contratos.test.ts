/**
 * A validação de payload do produtor (KAM-007, critério 6).
 *
 * Corre contra o catálogo **real** — os trinta e oito contratos gerados — e
 * não contra um catálogo de teste. Um validador que passe sobre um catálogo
 * inventado não diz nada sobre o que vai acontecer quando o COM emitir o
 * primeiro `order.created`.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  PayloadInvalidoError,
  TipoDesconhecidoError,
  VersaoDesconhecidaError,
  tiposComContrato,
  validarPayload,
} from "../src/eventos/contratos.ts";

/** Um payload mínimo de `order.paid`: os quatro obrigatórios do contrato. */
const ORDER_PAID = {
  order_id: "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50",
  valor_minor: 24500000,
  currency: "AOA",
  paga_via: "provider_autenticado",
};

describe("validarPayload", () => {
  it("aceita um payload que respeita o contrato", () => {
    validarPayload("order.paid", 1, ORDER_PAID);
  });

  it("recusa um tipo sem contrato, e diz onde o contrato nasce", () => {
    assert.throws(
      () => validarPayload("order.inventado", 1, {}),
      (erro: unknown) => {
        assert.ok(erro instanceof TipoDesconhecidoError);
        assert.match(erro.message, /contratos\/eventos/);
        return true;
      },
    );
  });

  it("aceita qualquer versão publicada, e não só a primeira", () => {
    // Desde o KAM-159 há duas. O `validarPayload` pergunta ao catálogo quais
    // são as publicadas em vez de assumir a `v1` — que é o que o §6.6 quer
    // dizer com «o `v<N>` fica como estava»: não deixa de ser válido por
    // nascer um `v<N+1>`.
    validarPayload("order.paid", 1, ORDER_PAID);
    validarPayload("order.paid", 2, ORDER_PAID);
  });

  it("recusa uma versão que não existe, e diz as que existem", () => {
    assert.throws(
      () => validarPayload("order.paid", 3, ORDER_PAID),
      (erro: unknown) => {
        assert.ok(erro instanceof VersaoDesconhecidaError);
        assert.match(erro.message, /v1, v2/);
        return true;
      },
    );
  });

  it("recusa um campo a mais — é o `additionalProperties: false` do contrato", () => {
    assert.throws(
      () => validarPayload("order.paid", 1, { ...ORDER_PAID, telefone: "x" }),
      (erro: unknown) => {
        assert.ok(erro instanceof PayloadInvalidoError);
        assert.deepEqual(erro.aMais, ["telefone"]);
        return true;
      },
    );
  });

  it("recusa um campo em falta — é o `required` do contrato", () => {
    const semMoeda: Record<string, unknown> = { ...ORDER_PAID };
    delete semMoeda.currency;
    assert.throws(
      () => validarPayload("order.paid", 1, semMoeda),
      (erro: unknown) => {
        assert.ok(erro instanceof PayloadInvalidoError);
        assert.deepEqual(erro.emFalta, ["currency"]);
        return true;
      },
    );
  });

  it("recusa o que não é um objecto", () => {
    for (const mau of [null, [], "texto", 7]) {
      assert.throws(() => validarPayload("order.paid", 1, mau), PayloadInvalidoError);
    }
  });

  it("aceita um payload vazio onde o contrato não pede nada", () => {
    // `tenant.activated` não tem campos: o envelope já diz tudo.
    validarPayload("tenant.activated", 1, {});
  });

  it("**não** verifica tipos, e isso está dito na docstring", () => {
    // Um `valor_minor` em texto passa aqui. Quem o apanha é o compilador, com
    // o tipo gerado — e as duas metades juntas é que são a validação. Este
    // teste existe para que o limite seja uma decisão registada e não uma
    // surpresa de quem leu «validarPayload» e assumiu JSON Schema completo.
    validarPayload("order.paid", 1, { ...ORDER_PAID, valor_minor: "24500000" });
  });
});

describe("o catálogo que o validador lê", () => {
  it("tem os trinta e oito tipos", () => {
    assert.equal(tiposComContrato().length, 38);
  });

  it("todos os exemplos do repositório passam no validador, em todas as versões", () => {
    // O exemplo de cada contrato é, por construção, um payload mínimo válido.
    // Se o validador recusasse algum, estaria a ser mais severo do que o
    // contrato — que é tão defeito como ser mais permissivo.
    //
    // **Em todas as versões**, e não só na `v1`: desde o KAM-159 há 76
    // contratos em 38 pastas, e a versão que um produtor novo escreve é a
    // última. Validar só a primeira deixava a mais recente por verificar
    // deste lado.
    let validados = 0;
    for (const tipo of tiposComContrato()) {
      for (const versao of versoesNoDisco(tipo)) {
        assert.doesNotThrow(() => {
          validarPayload(tipo, versao, exemploDe(tipo, versao));
        }, `${tipo} v${versao}`);
        validados += 1;
      }
    }
    assert.equal(validados, 76);
  });
});

/** As versões de um tipo, lidas da pasta — não do catálogo que se verifica. */
function versoesNoDisco(tipo: string): number[] {
  const pasta = new URL(`../../../contratos/eventos/${tipo}/`, import.meta.url);
  const versoes = readdirSync(pasta)
    .map((nome) => /^v([1-9][0-9]*)\.schema\.json$/.exec(nome)?.[1])
    .filter((n): n is string => n !== undefined)
    .map(Number)
    .sort((a, b) => a - b);
  assert.ok(versoes.length > 0, `${tipo}: pasta sem nenhum v<N>.schema.json`);
  return versoes;
}

function exemploDe(tipo: string, versao: number): unknown {
  // A `v1` mantém o nome histórico `exemplo.json`; da segunda em diante é
  // `exemplo.v<N>.json`. Um exemplo por pasta deixou de chegar no dia em que
  // o mesmo ficheiro teria de dizer `versao: 1` e `versao: 2` ao mesmo tempo.
  const nome = versao === 1 ? "exemplo.json" : `exemplo.v${versao}.json`;
  const caminho = new URL(
    `../../../contratos/eventos/${tipo}/${nome}`,
    import.meta.url,
  );
  const texto = readFileSync(caminho, "utf8");
  return (JSON.parse(texto) as { payload?: unknown }).payload ?? {};
}
