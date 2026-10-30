/**
 * O inventário de números de forma real (KAM-024, critério 7).
 *
 * Estes testes provam que o inventário é um **raquete** e não uma isenção: que
 * falha nos quatro sentidos em que uma pasta permitida não falharia. É a parte
 * que decide se a caixa do critério 7 se pode marcar, e por isso cada sentido
 * tem o seu teste.
 *
 * O confronto contra o repositório real **não** está aqui: é o `meta-sim
 * varrer` que o faz, no gate 7, porque é lá que ele tem o repositório inteiro à
 * frente. Aqui prova-se a regra; lá aplica-se.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { INVENTARIO, confrontar, frase, totalDeclarado, type Entrada } from "../src/inventario.ts";

const UM: readonly Entrada[] = [
  {
    ficheiro: "a/b.ts",
    ocorrencias: 2,
    razao: "um controlo positivo do detector de PII, que sem isto nao dispara",
  },
];

describe("o inventario falha nos quatro sentidos", () => {
  it("um ficheiro com numero e sem entrada: nao_declarado", () => {
    // É o sentido que importa mais: é o que uma pasta permitida deixava passar.
    const d = confrontar([{ ficheiro: "c/d.ts", ocorrencias: 1 }], UM);
    assert.equal(d.filter((x) => x.tipo === "nao_declarado").length, 1);
    assert.match(frase(d.find((x) => x.tipo === "nao_declarado")!), /nenhuma entrada no inventario/);
  });

  it("um numero a mais num ficheiro JA declarado: a_mais", () => {
    // O segundo sentido que a pasta permitida deixava passar: dentro de um
    // ficheiro já tolerado, um número novo não se via.
    const d = confrontar([{ ficheiro: "a/b.ts", ocorrencias: 3 }], UM);
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "a_mais");
    assert.match(frase(d[0]!), /3 numero\(s\) e o inventario declara 2/);
  });

  it("um numero a menos: a_menos, para o inventario nao envelhecer", () => {
    const d = confrontar([{ ficheiro: "a/b.ts", ocorrencias: 1 }], UM);
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "a_menos");
    assert.match(frase(d[0]!), /baixe a contagem/);
  });

  it("uma entrada sem medicao: entrada_morta", () => {
    const d = confrontar([], UM);
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "entrada_morta");
  });

  it("uma razao curta e um defeito do inventario", () => {
    // Uma entrada sem razão é uma isenção disfarçada de inventário.
    const d = confrontar(
      [{ ficheiro: "a/b.ts", ocorrencias: 2 }],
      [{ ficheiro: "a/b.ts", ocorrencias: 2, razao: "e um teste" }],
    );
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "sem_razao");
  });

  it("a contagem certa com a razao certa nao diverge", () => {
    assert.deepEqual(confrontar([{ ficheiro: "a/b.ts", ocorrencias: 2 }], UM), []);
  });
});

describe("o inventario deste repositorio", () => {
  it("cada entrada diz porque e que o numero esta la", () => {
    for (const entrada of INVENTARIO) {
      assert.ok(
        entrada.razao.trim().length >= 30,
        `${entrada.ficheiro}: a razao tem ${entrada.razao.trim().length} caracteres`,
      );
    }
  });

  it("nao ha ficheiros repetidos", () => {
    const vistos = new Set(INVENTARIO.map((e) => e.ficheiro));
    assert.equal(vistos.size, INVENTARIO.length);
  });

  it("os caminhos sao relativos e com barra, nao com contrabarra", () => {
    // Um inventário com `\\` numa máquina e `/` na outra dava «não declarado»
    // para tudo, no sítio onde ninguém olha.
    for (const entrada of INVENTARIO) {
      assert.ok(!entrada.ficheiro.includes("\\"), entrada.ficheiro);
      assert.ok(!entrada.ficheiro.startsWith("/"), entrada.ficheiro);
      assert.ok(!entrada.ficheiro.includes(".."), entrada.ficheiro);
    }
  });

  it("o total declarado e o que a medicao diz", () => {
    // 89 ocorrências em 24 ficheiros na medição de 2026-10-20, menos as 3 que o
    // KAM-024 passou para o intervalo fictício em
    // `services/gwy/tests/webhook.test.ts`: **86**.
    //
    // **88 desde o KAM-115**, e as duas que entram dizem para que servem: são
    // nomes de loja do varrimento de 200 avisos do critério 5 daquele ticket. O
    // aviso ao dono mascara corridas de sete ou mais dígitos no nome da loja
    // porque «Loja do Zé 923 456 789» é um nome plausível em Luanda — e sem
    // números de **forma** real o teste provava que a máscara apanha números
    // que não se parecem com telefones, que é o contrário do que ela existe
    // para fazer.
    //
    // **Este número sobe com o inventário e é isso que o torna um raquete**: a
    // contagem num sítio só obriga quem acrescenta um ficheiro a dizê-lo aqui
    // também, e é o que distingue isto de uma pasta isenta — que cresceria em
    // silêncio.
    // **94 em 26 ficheiros desde o KAM-112**, e as tres que entram sao das
    // docstrings do detector de PII daquele ticket: duas das dez formas de
    // telefone que o criterio 2 enumera — o `+244` junto e o `00244` — tem a
    // forma que este scan procura, e tinham de ter, porque um exemplo que nao
    // casasse o padrao que ilustra enganava quem o lesse. A terceira esta no
    // comentario do ensaio que explica porque e que um `\d{9}` deslizante
    // conta janelas de nove digitos **dentro** de um numero com prefixo.
    //
    // **E este gate apanhou-as antes de mim**, que e o que ele existe para
    // fazer: o KAM-112 abriu PR com os tres numeros por declarar e o gate 7
    // ficou vermelho. Uma pasta `tests/` isenta — a tentacao que o
    // `inventario.ts` recusa por extenso — tinha deixado passar os tres.
    assert.equal(totalDeclarado(), 94);
    assert.equal(INVENTARIO.length, 26);
  });

  it("nenhuma entrada e de uma pasta inteira", () => {
    // O inventário é por **ficheiro**. Uma entrada que fosse uma pasta era a
    // isenção que isto existe para não ser.
    for (const entrada of INVENTARIO) {
      assert.ok(/\.[a-z]+$/.test(entrada.ficheiro), `${entrada.ficheiro} nao parece um ficheiro`);
    }
  });
});
