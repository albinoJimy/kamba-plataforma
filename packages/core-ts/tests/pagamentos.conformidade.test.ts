/**
 * A suite de conformidade do §3.5 e o `FakeProvider` (KAM-052, criterio 9).
 *
 * «O *harness* expoe os 10 casos obrigatorios de `../docs/tecnica/04` §3.5 como
 * testes parametrizaveis por adaptador e um `FakeProvider` passa todos.»
 *
 * Tres ensaios, e o terceiro e o que da substancia aos dois primeiros:
 *
 *     1. sao dez, e sao os dez do documento
 *     2. o `FakeProvider` passa-os
 *     3. **tirando uma barreira ao `FakeProvider`, o caso dela fica vermelho**
 *
 * Sem o terceiro, dez casos verdes podiam estar verdes por nao medirem nada — e
 * e precisamente o modo de falha que o passo de canario dos gates 3b, 9 e 11
 * existe para fechar. Um harness nao verificado e pior do que nenhum, porque
 * fecha a caixa.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CASOS, type Caso, correr, relatorio } from "../src/pagamentos/index.ts";
import { type Fraquezas, bancoDeEnsaio } from "./pagamentos.banco.ts";

/** Os dez casos, transcritos do §3.5 pela ordem em que o documento os escreve. */
const DO_DOCUMENTO: readonly Caso[] = [
  "assinatura_adulterada_rejeita",
  "valor_mais_um_centimo_sobrevive_exacto",
  "referencia_desconhecida_e_orfao",
  "callback_duplicado_dez_vezes_um_efeito",
  "callback_fora_de_ordem",
  "pagamento_depois_de_valid_until",
  "criacao_com_resposta_perdida_e_idempotente",
  "rotacao_de_chave",
  "rate_limit_429",
  "status_concorda_com_o_callback",
];

describe("pagamentos/conformidade: sao os dez casos do §3.5", () => {
  it("sao dez, contados", () => {
    assert.equal(CASOS.length, 10);
  });

  it("e sao os dez do documento, pela ordem dele", () => {
    assert.deepEqual([...CASOS], [...DO_DOCUMENTO]);
  });
});

describe("pagamentos/conformidade: criterio 9 — o FakeProvider passa todos", () => {
  it("os dez casos passam", async () => {
    const veredicto = await correr(bancoDeEnsaio());
    assert.equal(veredicto.verde, true, relatorio(veredicto));
    assert.equal(veredicto.resultados.length, 10);
    assert.equal(veredicto.adaptador, "fake");
  });

  it("e o relatorio di-lo numa linha", async () => {
    const veredicto = await correr(bancoDeEnsaio());
    assert.equal(relatorio(veredicto), "fake: os 10 casos passam");
  });

  /** O harness e determinista: corre duas vezes e da o mesmo. */
  it("duas execucoes dao o mesmo veredicto", async () => {
    const uma = await correr(bancoDeEnsaio());
    const outra = await correr(bancoDeEnsaio());
    assert.deepEqual(uma.resultados, outra.resultados);
  });
});

describe("pagamentos/conformidade: o canario — o harness morde", () => {
  /**
   * Cada fraqueza mata **o seu** caso.
   *
   * O que esta tabela prova, e que nenhum dos dois ensaios de cima prova: que o
   * caso 1 mede a assinatura e nao outra coisa, que o caso 2 mede a exactidao do
   * valor, e assim por diante. Uma fraqueza que matasse o caso errado — ou
   * nenhum — apareceria aqui.
   */
  const CANARIOS: readonly [keyof Fraquezas, Caso][] = [
    ["semVerificarAssinatura", "assinatura_adulterada_rejeita"],
    ["valorPorFloat", "valor_mais_um_centimo_sobrevive_exacto"],
    ["eventIdPorContador", "callback_duplicado_dez_vezes_um_efeito"],
    ["semJanelaDeRotacao", "rotacao_de_chave"],
    ["rateLimitGenerico", "rate_limit_429"],
  ];

  for (const [fraqueza, caso] of CANARIOS) {
    it(`sem '${fraqueza}', o caso '${caso}' fica vermelho`, async () => {
      const veredicto = await correr(bancoDeEnsaio({ [fraqueza]: true }));
      assert.equal(veredicto.verde, false, `a fraqueza '${fraqueza}' nao foi apanhada`);
      const resultado = veredicto.resultados.find((r) => r.caso === caso);
      assert.ok(resultado !== undefined);
      assert.equal(resultado.ok, false, `o caso '${caso}' passou com a barreira tirada`);
      assert.ok(resultado.detalhe.length > 0, "uma falha sem detalhe nao diz o que fazer");
    });
  }

  /**
   * E o `valorPorFloat` falha **com o valor de ensaio do caso 2**.
   *
   * **Este canario mudou o caso 2, e a ordem importa.** A primeira versao do
   * caso usava `123457n` (1234,57 Kz) por o `.57` parecer o tipo de fraccao que
   * um `float` estraga; o canario correu, o caso passou com a barreira tirada, e
   * o que isso provou foi que o caso nao media nada. O valor passou a `102409n`
   * (1024,09 Kz), que e o primeiro acima de 1.000 Kz em que
   * `Math.trunc(parseFloat(t) * 100)` perde um centimo.
   *
   * E o argumento a favor do canario: sem ele, o criterio 9 ficava marcado com
   * dez casos verdes e um deles vazio.
   */
  it("o valorPorFloat perde o centimo por truncatura, e o caso 2 ve", async () => {
    const veredicto = await correr(bancoDeEnsaio({ valorPorFloat: true }));
    const resultado = veredicto.resultados.find(
      (r) => r.caso === "valor_mais_um_centimo_sobrevive_exacto",
    );
    assert.ok(resultado !== undefined);
    assert.equal(resultado.ok, false);
    assert.match(resultado.detalhe, /nao sobreviveu exacto/);
  });

  it("uma fraqueza nao estraga os casos que nao sao dela", async () => {
    const veredicto = await correr(bancoDeEnsaio({ semJanelaDeRotacao: true }));
    const vermelhos = veredicto.resultados.filter((r) => !r.ok).map((r) => r.caso);
    assert.deepEqual(vermelhos, ["rotacao_de_chave"]);
  });
});

describe("pagamentos/conformidade: o harness nao deixa uma excepcao subir", () => {
  /**
   * Um caso que **levanta** conta como falha com o erro no detalhe. Um harness
   * que deixasse a excepcao subir dava «a suite rebentou» em vez de «o caso 7
   * falhou assim», e e a segunda que diz o que fazer.
   */
  it("um banco que levanta da falha com detalhe, nao rebenta", async () => {
    const banco = bancoDeEnsaio();
    const quebrado = {
      ...banco,
      callback: async () => {
        throw new Error("o banco de ensaio rebentou");
      },
    };
    const veredicto = await correr(quebrado);
    assert.equal(veredicto.verde, false);
    // Os casos que nao usam `callback` continuam a correr.
    const comDetalhe = veredicto.resultados.filter((r) => !r.ok && r.detalhe.includes("rebentou"));
    assert.ok(comDetalhe.length > 0);
    assert.equal(veredicto.resultados.length, 10);
  });
});
