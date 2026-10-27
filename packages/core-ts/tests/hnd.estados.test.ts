/**
 * Os dois vocabulários do handoff, e a ponte entre eles (KAM-019).
 *
 * A assinatura do `docs/tecnica/01` §11.1 dá ao `close` um
 * `outcome ∈ {resolved, timeout, cancelled}`; a tabela que o bloco manda criar
 * tem `status ∈ {waiting, resumed, timeout, cancelled, degraded}`. **Duas das
 * três chamam-se igual e uma não**, e é exactamente isso que torna a tradução
 * perigosa: um `as` funcionava em dois casos e mentia no terceiro.
 *
 * O que estes testes prendem, por ordem de importância:
 *
 * 1. **A partição é total.** Os cinco estados são exactamente os três que um
 *    desfecho escreve mais os dois que nenhum escreve. Um estado novo que
 *    apareça falha aqui, e é isso que obriga quem o acrescentar a decidir de
 *    que lado fica — em vez de o deixar sem tradução e descobri-lo quando um
 *    `close` não gravar nada.
 * 2. **O `resolved` dá `resumed`.** É a única que muda de nome.
 * 3. **De `waiting` não se fecha deste lado**, e é essa lista que vai ao
 *    predicado do `UPDATE`: é a base que faz do duplicado um *no-op*. A emenda
 *    1.42 do dicionário (§3.32) tirou-lhe o `waiting`, e o teste que o afirma
 *    está escrito como propriedade da fronteira e não como cópia da constante —
 *    ver o bloco «de onde se pode fechar».
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ESTADOS,
  ESTADOS_QUE_FECHAM,
  ESTADOS_SEM_OUTCOME,
  ESTADO_POR_OUTCOME,
  OUTCOMES,
  concluido,
  estadoDe,
  outcomeDoProvedor,
} from "../src/hnd/index.ts";

describe("os dois vocabularios", () => {
  it("sao cinco estados e tres desfechos", () => {
    assert.deepEqual([...ESTADOS], [
      "waiting",
      "resumed",
      "timeout",
      "cancelled",
      "degraded",
    ]);
    assert.deepEqual([...OUTCOMES], ["resolved", "timeout", "cancelled"]);
  });

  it("**o resolved da resumed, e e a unica que muda de nome**", () => {
    assert.equal(estadoDe("resolved"), "resumed");
    assert.equal(estadoDe("timeout"), "timeout");
    assert.equal(estadoDe("cancelled"), "cancelled");
  });

  it("**a particao e total**: cada estado ou e desfecho ou esta na lista dos que nao sao", () => {
    // E o teste que obriga quem acrescentar um estado a decidir de que lado
    // fica. Sem ele, um estado novo ficava sem traducao e o defeito aparecia no
    // dia em que um `close` nao gravasse nada.
    const escritos = new Set(Object.values(ESTADO_POR_OUTCOME));
    const semDesfecho = new Set(ESTADOS_SEM_OUTCOME);
    for (const estado of ESTADOS) {
      assert.ok(
        escritos.has(estado) !== semDesfecho.has(estado),
        `${estado} tem de estar em exactamente um dos dois lados`,
      );
    }
    assert.equal(escritos.size + semDesfecho.size, ESTADOS.length);
  });

  it("nenhum desfecho escreve waiting nem degraded", () => {
    // `waiting` e onde uma passagem nasce e `degraded` e onde fica quando o
    // provedor nao respondeu: nenhum dos dois e uma conclusao.
    const escritos = Object.values(ESTADO_POR_OUTCOME);
    assert.ok(!escritos.includes("waiting"));
    assert.ok(!escritos.includes("degraded"));
  });

  it("o mapeamento cobre os tres desfechos e mais nenhum", () => {
    assert.deepEqual(Object.keys(ESTADO_POR_OUTCOME).sort(), [...OUTCOMES].sort());
  });
});

describe("de onde se pode fechar", () => {
  it("**de degraded, e de mais nenhum** — o waiting e do AGR", () => {
    // E esta lista que vai ao `WHERE status = ANY(...)`: e a base que faz do
    // fecho duplicado um *no-op*, nao uma verificacao em codigo.
    assert.deepEqual([...ESTADOS_QUE_FECHAM], ["degraded"]);
  });

  it("**o waiting nao esta na lista, e e a fronteira da emenda 1.42**", () => {
    // Nao e a mesma assercao do teste de cima com outras palavras. Aquele diz o
    // **valor** da constante; este diz a **propriedade** que a emenda 1.42
    // (§3.32) fixou, e e ela que explica porque e que o valor e aquele: a
    // `platform.handoffs` tinha dois escritores para a saida de `waiting` e o
    // deste lado corria primeiro, pelo que o compare-and-set do AGR nao casava
    // linha nenhuma e o `Command(resume=...)` nunca corria — o `interrupt()` do
    // `handoff_wait` ficava pendente para sempre, no caminho feliz, todas as
    // vezes (ANALISE-35, achado 1).
    //
    // Um dia alguem vai querer «so para o timeout» ou «so para o cancelled»: os
    // tres desfechos retomam o grafo, e e por isso que a lista nao tem o
    // `waiting` para nenhum deles.
    assert.ok(
      !ESTADOS_QUE_FECHAM.includes("waiting"),
      "sair de waiting e do AGR, por /internal/resume: dicionario §3.32",
    );
  });

  it("os tres estados concluidos tambem nao fecham", () => {
    // Uma passagem ja concluida nao se volta a concluir. Com o `waiting` fora
    // da lista a antiga igualdade `podeFechar === !concluido(estado)` deixou de
    // valer — `waiting` nao e concluido **e** nao fecha —, pelo que o que se
    // afirma e a implicacao que sobrevive, e a outra metade fica no teste de
    // cima.
    for (const estado of ESTADOS) {
      if (concluido(estado)) {
        assert.ok(!ESTADOS_QUE_FECHAM.includes(estado), estado);
      }
    }
    assert.ok(ESTADOS_QUE_FECHAM.every((estado) => !concluido(estado)));
  });

  it("os tres concluidos sao concluidos, e os dois abertos nao", () => {
    for (const estado of ["resumed", "timeout", "cancelled"]) {
      assert.ok(concluido(estado), estado);
    }
    assert.ok(!concluido("waiting"));
    assert.ok(!concluido("degraded"));
  });

  it("um estado que nao e dos cinco **nao** conta como concluido", () => {
    // Importa porque o `concluido` recebe texto que vem da base: um valor
    // estranho tem de dar `false` e nao `true`, senao um estado desconhecido
    // fazia o handoff parecer fechado e ninguem voltava a olhar para ele.
    assert.ok(!concluido("snoozed"));
    assert.ok(!concluido(""));
    assert.ok(!concluido("RESUMED"));
  });
});

describe("o vocabulario de estados do provedor", () => {
  it("so o resolved dele e um desfecho nosso", () => {
    assert.equal(outcomeDoProvedor("resolved"), "resolved");
  });

  it("**o snoozed nao fecha nada**, e isso e deliberado", () => {
    // O provedor tem `open|resolved|pending|snoozed` (`docs/tecnica/01` §11.3).
    // Tratar uma soneca do agente como fecho era deixar o cliente sem resposta
    // e marcar a passagem como atendida.
    assert.equal(outcomeDoProvedor("snoozed"), null);
    assert.equal(outcomeDoProvedor("open"), null);
    assert.equal(outcomeDoProvedor("pending"), null);
  });

  it("um estado que ele invente tambem nao", () => {
    assert.equal(outcomeDoProvedor("arquivada"), null);
    assert.equal(outcomeDoProvedor(""), null);
  });
});
