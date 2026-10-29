/**
 * `Minor` ↔ `decimal2`/`inteiro_kz`, e a prova de que a travessia e exacta
 * (KAM-052, «Testes Requeridos»: unit, conversao).
 *
 * O teste que importa e o `test_o_caminho_por_number_perderia_este_centimo`: ele
 * **mede** que a travessia obvia esta errada, em vez de confiar na frase do
 * cabecalho do modulo. Sem ele, a regra «nunca virgula flutuante» era uma
 * afirmacao sobre o mundo sem evidencia local — que e exactamente o que este
 * repositorio chama NAO VERIFICADO.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CASAS_DO_DECIMAL2,
  MINOR_POR_KZ,
  ValorDeDinheiroInvalido,
  minorDeDecimal2,
  minorDeFormato,
  minorDeInteiroKz,
  minorParaDecimal2,
  minorParaFormato,
  minorParaInteiroKz,
} from "../src/pagamentos/index.ts";

describe("pagamentos/dinheiro: decimal2", () => {
  it("le duas casas, uma casa e nenhuma", () => {
    assert.equal(minorDeDecimal2("1234.57"), 123_457n);
    // Uma casa e a dos **centimos**: 1234,5 Kz sao 123450 centimos.
    assert.equal(minorDeDecimal2("1234.5"), 123_450n);
    assert.equal(minorDeDecimal2("1234"), 123_400n);
    assert.equal(minorDeDecimal2("0"), 0n);
    assert.equal(minorDeDecimal2("0.01"), 1n);
  });

  it("escreve de volta a mesma cadeia", () => {
    for (const texto of ["1234.57", "0.01", "99999999.99", "7.00"]) {
      assert.equal(minorParaDecimal2(minorDeDecimal2(texto)), texto);
    }
  });

  it("enche o centimo a esquerda e nao a direita", () => {
    // 1234,05 e nao 1234,50: o bug classico de `padEnd` no sentido inverso.
    assert.equal(minorParaDecimal2(123_405n), "1234.05");
  });

  it("recusa tres casas em vez de truncar", () => {
    assert.throws(() => minorDeDecimal2("1234.567"), ValorDeDinheiroInvalido);
  });

  it("recusa o que nao e um valor", () => {
    for (const texto of ["", " 1234", "1234 ", "1.2.3", "abc", "-1", "1e3", "1,57", "+1"]) {
      assert.throws(() => minorDeDecimal2(texto), ValorDeDinheiroInvalido, texto);
    }
  });

  /**
   * O tecto do §3.3: o ProxyPay aceita referencias ate 99.999.999,99 Kz.
   *
   * Sao 9.999.999.999 centimos — abaixo de `Number.MAX_SAFE_INTEGER`, pelo que
   * **um** valor ainda caberia num `number`. O que nao cabe e a soma de alguns
   * deles, e e por isso que o tipo e `bigint` e nao «`number` com cuidado».
   */
  it("aceita o maior valor que o facilitador aceita", () => {
    assert.equal(minorDeDecimal2("99999999.99"), 9_999_999_999n);
  });

  /**
   * O valor da encomenda inteira, nao o do centimo.
   *
   * `1024.09` e o primeiro valor acima de 1.000 Kz em que o caminho por
   * `number` trunca para menos (ver o ensaio ao fundo). Entra aqui para que a
   * travessia exacta esteja fixada **no valor que o outro caminho estraga**, e
   * nao so em valores que ambos acertam.
   */
  it("converte exacto o valor em que o caminho por number falha", () => {
    assert.equal(minorDeDecimal2("1024.09"), 102_409n);
    assert.equal(minorParaDecimal2(102_409n), "1024.09");
  });
});

describe("pagamentos/dinheiro: inteiro_kz", () => {
  it("multiplica por cem", () => {
    assert.equal(minorDeInteiroKz("1234"), 123_400n);
    assert.equal(minorParaInteiroKz(123_400n), "1234");
  });

  it("recusa um ponto, porque a unidade ficaria ambigua", () => {
    assert.throws(() => minorDeInteiroKz("1234.57"), ValorDeDinheiroInvalido);
  });

  it("recusa escrever um valor com centimos, em vez de arredondar", () => {
    assert.throws(() => minorParaInteiroKz(123_457n), ValorDeDinheiroInvalido);
  });
});

describe("pagamentos/dinheiro: o despacho por amountFormat", () => {
  it("segue o formato declarado pelo adaptador", () => {
    assert.equal(minorDeFormato("1234.57", "decimal2"), 123_457n);
    assert.equal(minorDeFormato("1234", "inteiro_kz"), 123_400n);
    assert.equal(minorParaFormato(123_457n, "decimal2"), "1234.57");
    assert.equal(minorParaFormato(123_400n, "inteiro_kz"), "1234");
  });
});

describe("pagamentos/dinheiro: negativos", () => {
  it("recusa formatar um negativo, porque o ledger corrige por compensacao", () => {
    assert.throws(() => minorParaDecimal2(-1n), ValorDeDinheiroInvalido);
    assert.throws(() => minorParaInteiroKz(-100n), ValorDeDinheiroInvalido);
  });
});

describe("pagamentos/dinheiro: a razao de nao ser `number`", () => {
  /**
   * **A medicao, e nao a afirmacao.** E a primeira versao deste ensaio estava
   * errada, o que e a razao de ele existir.
   *
   * Afirmava que `parseFloat("1234.57") * 100` dava `123456.99999999999`. **Da
   * 123457 exacto**, e o ensaio ficou vermelho na primeira execucao — o
   * argumento do modulo estava certo e o exemplo era inventado. Os valores
   * abaixo foram **procurados por varrimento** (todos os `kz.cc` de 0 a 60.000)
   * e sao os que de facto falham em Node 24.21.0.
   *
   * Se um dia o motor passar a converter todos estes exactos, este ensaio fica
   * vermelho e quem o ler descobre que a razao escrita no modulo mudou — o que
   * e melhor do que um comentario a envelhecer em silencio.
   */
  it("o caminho por number perde um centimo", () => {
    // O que uma encomenda real custa, e o primeiro acima de 1.000 Kz a falhar.
    const porFloat = Number.parseFloat("1024.09") * 100;
    assert.notEqual(porFloat, 102_409);
    // Com `Math.trunc` cobra-se 1024,08 Kz por uma encomenda de 1024,09 Kz.
    assert.equal(BigInt(Math.trunc(porFloat)), 102_408n);
    // E o nosso caminho nao o perde.
    assert.equal(minorDeDecimal2("1024.09"), 102_409n);
  });

  it("e falha nos dois sentidos, para cima e para baixo", () => {
    assert.notEqual(Number.parseFloat("2.01") * 100, 201);
    assert.notEqual(Number.parseFloat("0.07") * 100, 7);
    assert.equal(minorDeDecimal2("2.01"), 201n);
    assert.equal(minorDeDecimal2("0.07"), 7n);
  });

  /**
   * E o `Math.round` nao e o remedio: a soma continua a derivar.
   *
   * E a razao pela qual o tipo e `bigint` e nao «`number` com um
   * arredondamento»: um ledger soma, e e na soma que o erro se acumula sem
   * ninguem o conseguir reconciliar contra um extracto.
   */
  it("o arredondamento nao salva a soma", () => {
    assert.notEqual(0.1 + 0.2, 0.3);
    assert.equal(1n + 2n, 3n);
  });

  it("as constantes sao as do dominio", () => {
    assert.equal(MINOR_POR_KZ, 100n);
    assert.equal(CASAS_DO_DECIMAL2, 2);
  });
});
