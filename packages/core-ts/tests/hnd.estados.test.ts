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
 * 3. **De um estado concluído não se fecha outra vez**, e é essa lista que vai
 *    ao predicado do `UPDATE`: é a base que faz do duplicado um *no-op*.
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
  it("de waiting e de degraded, e de mais nenhum", () => {
    // E esta lista que vai ao `WHERE status = ANY(...)`: e a base que faz do
    // `resolved` duplicado um *no-op*, nao uma verificacao em codigo.
    assert.deepEqual([...ESTADOS_QUE_FECHAM], ["waiting", "degraded"]);
    for (const estado of ESTADOS) {
      const podeFechar = ESTADOS_QUE_FECHAM.includes(estado);
      assert.equal(podeFechar, !concluido(estado), estado);
    }
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
