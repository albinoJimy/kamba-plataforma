/**
 * Monotonia de estados, custo e tarifas (KAM-015, critérios 3 e 4).
 *
 * O critério 3 tem três frases e as três estão aqui: «`delivered` seguido de
 * `sent` mantém `delivered`; `failed` é terminal; duplicados do mesmo estado
 * são *no-op*».
 *
 * ## O caso que um teste com estados em ordem não apanha
 *
 * A Meta entrega os `statuses` **sem ordem garantida** (CONFIRMADO, `E1` §5).
 * Logo o `read` pode chegar **antes** do `delivered`. Nesse caso:
 *
 * - o `read` tem de somar custo, porque ler implica ter sido entregue;
 * - o `delivered` que chegue depois **não** pode somar outra vez.
 *
 * É por isso que a entrega se conta ao **atravessar** o `delivered` e não ao
 * chegar a ele, e é a asserção que distingue uma implementação que percebeu
 * isso de uma que comparou com `=== "delivered"`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ESTADOS,
  MICRO_USD_POR_CATEGORIA,
  MICRO_USD_POR_USD,
  TERMINAIS,
  avancar,
  categoriaDesconhecida,
  ingerir,
  microUsdDe,
  paraMostrar,
  terminal,
  type Estado,
  type Pricing,
} from "@kamba/core-ts/outbound";

/** Um `pricing` de serviço facturável, como a Meta o manda. */
function pricing(troca: Partial<Pricing> = {}): Pricing {
  return {
    billable: true,
    pricing_model: "CBP",
    type: "service",
    category: "service",
    ...troca,
  };
}

describe("monotonia (criterio 3)", () => {
  it("delivered seguido de sent mantem delivered — a letra do criterio", () => {
    const transicao = avancar("delivered", "sent");
    assert.deepEqual(transicao, { estado: "delivered", avancou: false, entregou: false });
  });

  it("read seguido de delivered mantem read", () => {
    assert.equal(avancar("read", "delivered").estado, "read");
    assert.equal(avancar("read", "delivered").avancou, false);
  });

  it("queued avanca para sent, delivered e read", () => {
    for (const destino of ["sent", "delivered", "read"] as const) {
      assert.equal(avancar("queued", destino).estado, destino);
      assert.equal(avancar("queued", destino).avancou, true);
    }
  });

  it("duplicados do mesmo estado sao no-op, nos seis estados", () => {
    for (const estado of ESTADOS) {
      const transicao = avancar(estado, estado);
      assert.equal(transicao.avancou, false, estado);
      assert.equal(transicao.estado, estado);
      assert.equal(transicao.entregou, false, `${estado} duplicado nao pode cobrar`);
    }
  });

  it("failed e terminal: de la nao se sai para nenhum dos seis", () => {
    for (const destino of ESTADOS) {
      assert.equal(avancar("failed", destino).estado, "failed", destino);
      assert.equal(avancar("failed", destino).avancou, false, destino);
    }
  });

  it("suppressed_by_human tambem e terminal", () => {
    assert.deepEqual(TERMINAIS, ["failed", "suppressed_by_human"]);
    for (const destino of ESTADOS) {
      assert.equal(avancar("suppressed_by_human", destino).avancou, false, destino);
    }
    assert.ok(terminal("failed") && terminal("suppressed_by_human"));
    assert.ok(!terminal("queued") && !terminal("read"));
  });

  it("de um nao-terminal vai-se para um terminal, e isso avanca", () => {
    // Uma entrega pode falhar depois de ser anunciada, e o `failed` tem de
    // morder — e por isso que os terminais **nao** se comparam por indice.
    for (const de of ["queued", "sent", "delivered", "read"] as const) {
      assert.equal(avancar(de, "failed").estado, "failed", de);
      assert.equal(avancar(de, "failed").avancou, true, de);
      // E **nao** conta como entrega: um `failed` e o contrario de uma entrega.
      assert.equal(avancar(de, "failed").entregou, false, de);
    }
  });

  it("um terminal nao vai para o outro terminal", () => {
    // Comparar por indice daria «suppressed_by_human (5) e depois de failed
    // (4)», que nao e verdade nenhuma.
    assert.equal(avancar("failed", "suppressed_by_human").avancou, false);
    assert.equal(avancar("suppressed_by_human", "failed").avancou, false);
  });
});

describe("a entrega conta-se ao atravessar o delivered", () => {
  it("queued -> delivered entrega", () => {
    assert.equal(avancar("queued", "delivered").entregou, true);
  });

  it("sent -> delivered entrega", () => {
    assert.equal(avancar("sent", "delivered").entregou, true);
  });

  it("**sent -> read entrega**, porque atravessa o delivered", () => {
    // A Meta nao garante ordem: o `read` pode chegar primeiro. Com um
    // `=== "delivered"` em vez do atravessamento, esta mensagem **nunca**
    // somava custo.
    assert.equal(avancar("sent", "read").entregou, true);
  });

  it("delivered -> read NAO entrega outra vez", () => {
    // E a mesma mensagem entregue. Com uma comparacao ingenua, somava duas
    // vezes.
    assert.equal(avancar("delivered", "read").entregou, false);
  });

  it("queued -> read entrega uma vez, e o delivered seguinte zero", () => {
    // A sequencia fora de ordem, inteira: o custo soma **uma** vez.
    assert.equal(avancar("queued", "read").entregou, true);
    assert.equal(avancar("read", "delivered").entregou, false);
  });

  it("queued -> sent nao entrega: a cobranca e na entrega, nao no envio", () => {
    // CONFIRMADO, `E1` §1. Um `sent` leva `pricing` porque a Meta o manda, e
    // contar nele era cobrar uma mensagem que ainda pode falhar.
    assert.equal(avancar("queued", "sent").entregou, false);
  });
});

describe("as tarifas (criterio 4)", () => {
  it("sao micro-dolares inteiros, e as quatro batem com o E1 §1", () => {
    assert.equal(MICRO_USD_POR_CATEGORIA.service, 4_000);
    assert.equal(MICRO_USD_POR_CATEGORIA.utility, 4_000);
    assert.equal(MICRO_USD_POR_CATEGORIA.authentication, 4_000);
    assert.equal(MICRO_USD_POR_CATEGORIA.marketing, 22_500);
    for (const valor of Object.values(MICRO_USD_POR_CATEGORIA)) {
      assert.ok(Number.isInteger(valor), `${valor} nao e inteiro`);
    }
  });

  it("mil service dao exactamente 4 USD, e e isso que o inteiro compra", () => {
    // Em `float64`, somar `0.004` mil vezes **nao** da `4.00`. E a razao de o
    // §2 proibir virgula flutuante em dinheiro, e porque e que o leitor de YAML
    // recusou a primeira versao de `config/meta_rates.yaml`.
    let flutuante = 0;
    let inteiro = 0;
    for (let i = 0; i < 1000; i += 1) {
      flutuante += 0.004;
      inteiro += MICRO_USD_POR_CATEGORIA.service;
    }
    assert.equal(inteiro, 4 * MICRO_USD_POR_USD, "o inteiro e exacto");
    assert.notEqual(flutuante, 4, "o flutuante nao e — e e o ponto");
  });

  it("o marketing e cerca de 5,6x a utility, como o §4.5 cita", () => {
    const razao = MICRO_USD_POR_CATEGORIA.marketing / MICRO_USD_POR_CATEGORIA.utility;
    assert.ok(Math.abs(razao - 5.6) < 0.1, String(razao));
  });

  it("um pricing nao facturavel custa zero", () => {
    assert.equal(microUsdDe(pricing({ billable: false })), 0);
    assert.equal(microUsdDe(null), 0);
  });

  it("uma categoria desconhecida custa zero e **faz barulho**", () => {
    // Duas perguntas diferentes: «quanto custou» responde 0 para nao inventar,
    // e «sei o que isto e» e a que tem de alertar. Inventar um numero para uma
    // categoria nova era o defeito pior dos dois.
    const estranho = pricing({ category: "conversa_nova_da_meta" });
    assert.equal(microUsdDe(estranho), 0);
    assert.ok(categoriaDesconhecida(estranho));
    assert.ok(!categoriaDesconhecida(pricing()));
    assert.ok(!categoriaDesconhecida(pricing({ billable: false, category: "x" })));
  });

  it("paraMostrar converte uma vez, no fim", () => {
    assert.equal(paraMostrar(2_000_000), "2.00");
    assert.equal(paraMostrar(4_000), "0.00");
    assert.equal(paraMostrar(22_500), "0.02");
  });
});

describe("ingestao com free tier (criterio 4)", () => {
  const DENTRO = { usadas: 10, tecto: 1000 };
  const FORA = { usadas: 1000, tecto: 1000 };

  it("um service dentro do free tier nao custa", () => {
    const resultado = ingerir("sent", "delivered", pricing(), DENTRO);
    assert.equal(resultado.entregou, true);
    assert.equal(resultado.microUsd, 0);
    assert.equal(resultado.dentroDoFreeTier, true);
  });

  it("um service **acima** do free tier custa 4 000 — a letra do criterio", () => {
    const resultado = ingerir("sent", "delivered", pricing(), FORA);
    assert.equal(resultado.microUsd, 4_000);
    assert.equal(resultado.dentroDoFreeTier, false);
  });

  it("uma utility custa mesmo dentro do contador: o free tier e so de service", () => {
    // CONFIRMADO, `E1` §1: «gratis ate 1.000» e das *service messages*. Uma
    // `utility` dentro da janela e paga desde 2026-10-01, e e por isso que a
    // verificacao olha para a **categoria do pricing** e nao so para a
    // contagem.
    const resultado = ingerir("sent", "delivered", pricing({ category: "utility" }), DENTRO);
    assert.equal(resultado.microUsd, 4_000);
    assert.equal(resultado.dentroDoFreeTier, false);
  });

  it("sem saber o free tier, **conta-se**", () => {
    // A leitura conservadora: subestimar o custo e pior do que sobrestimar,
    // porque uma factura maior do que o painel e uma surpresa e o contrario e
    // uma folga. Quem mantem o contador e o KAM-023.
    const resultado = ingerir("sent", "delivered", pricing(), null);
    assert.equal(resultado.microUsd, 4_000);
  });

  it("uma transicao que nao avanca nao custa nada", () => {
    const resultado = ingerir("delivered", "sent", pricing(), FORA);
    assert.equal(resultado.avancou, false);
    assert.equal(resultado.microUsd, 0);
  });

  it("um delivered repetido nao custa segunda vez", () => {
    assert.equal(ingerir("delivered", "delivered", pricing(), FORA).microUsd, 0);
  });

  it("um failed nao custa", () => {
    const resultado = ingerir("sent", "failed", pricing(), FORA);
    assert.equal(resultado.avancou, true);
    assert.equal(resultado.microUsd, 0);
  });

  it("a sequencia fora de ordem soma uma vez, e so uma", () => {
    // `read` primeiro, `delivered` depois — e o que a Meta faz.
    const primeiro = ingerir("sent", "read", pricing(), FORA);
    const segundo = ingerir("read", "delivered", pricing(), FORA);
    assert.equal(primeiro.microUsd + segundo.microUsd, 4_000);
  });

  it("um pricing de categoria desconhecida avanca e nao custa", () => {
    const resultado = ingerir(
      "sent",
      "delivered",
      pricing({ category: "categoria_nova" }),
      FORA,
    );
    assert.equal(resultado.avancou, true);
    assert.equal(resultado.microUsd, 0);
    assert.equal(resultado.categoriaDesconhecida, true);
  });
});
