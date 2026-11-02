/**
 * Os critérios 2 e 3 do KAM-043, medidos sem base de dados.
 *
 * «Unit: `precoDisplay` por modo; validade de preço; semântica de
 * `stock_modo`» — os três que os Testes Requeridos do bloco pedem.
 *
 * Sem base de dados porque o que estes critérios afirmam é uma correspondência
 * entre o estado de uma linha e o texto que o agente pode dizer, e isso não
 * precisa de PostgreSQL. O que precisa — o `CHECK`, a RLS, a auditoria, os
 * eventos — está em `db/tests_produtos/`, contra um PostgreSQL real.
 *
 * **O relógio entra por argumento em todos os casos de validade.** É o que
 * permite escrever a fronteira como igualdade exacta em vez de dormir, e é a
 * razão pela qual o `contrato.ts` declara o `Relogio`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AVISOS,
  DISPONIBILIDADE,
  PREFIXO_A_PARTIR_DE,
  SEPARADOR_DE_MILHARES,
  STOCK_POR_CONFIRMAR_MS,
  SUFIXO_DA_MOEDA,
  TEXTO_SOB_CONSULTA,
  avisosDaOferta,
  formatarMinor,
  precoDisplay,
  precoTipoEfectivo,
  precoVencido,
  stockPorConfirmar,
  vistaDaOferta,
  type TermosDaOferta,
} from "../src/produtos/index.ts";

const AGORA = new Date("2026-11-02T12:00:00.000Z");

/** Uma oferta com preço fixo de 12 500 Kz e stock garantido. */
function oferta(parcial: Partial<TermosDaOferta> = {}): TermosDaOferta {
  return {
    sku: "arroz-5kg",
    nome: "Arroz 5 kg",
    precoTipo: "fixo",
    precoMinor: 1_250_000n,
    currency: "AOA",
    precoAtualizadoAt: "2026-11-01T00:00:00.000Z",
    precoValidoAte: null,
    stockModo: "garantido",
    stockVerificadoAt: "2026-11-02T11:00:00.000Z",
    estado: "publicado",
    categoriaRestrita: null,
    atualizadoAt: "2026-11-02T11:00:00.000Z",
    ...parcial,
  };
}

// ----------------------------------------------- critério 2: o precoDisplay

test("criterio 2: as tres formas de precoDisplay, a letra do criterio", () => {
  // «12 500 Kz», «a partir de 12 500 Kz», «preço sob consulta» — os três
  // literais do critério, com o espaço fino inquebrável como separador.
  const E = SEPARADOR_DE_MILHARES;
  assert.equal(precoDisplay("fixo", 1_250_000n), `12${E}500${E}Kz`);
  assert.equal(
    precoDisplay("a_partir_de", 1_250_000n),
    `a partir de 12${E}500${E}Kz`,
  );
  assert.equal(precoDisplay("sob_consulta", null), "preço sob consulta");
});

test("criterio 2: sob_consulta nunca devolve numero", () => {
  // A outra metade do critério, e a que o validador de citação (KAM-032) usa: o
  // texto do `sob_consulta` **não tem dígito nenhum**. É isto que torna a
  // escolha de devolver texto em vez de `null` compatível com o critério.
  const display = precoDisplay("sob_consulta", null);
  assert.equal(/[0-9]/.test(String(display)), false);
  assert.equal(display, TEXTO_SOB_CONSULTA);

  // E nem com um `preco_minor` à frente: a base torna o par impossível, e se
  // alguém o construir em código o modo continua a mandar.
  assert.equal(precoDisplay("sob_consulta", 999n), TEXTO_SOB_CONSULTA);
});

test("criterio 2: a_partir_de nunca sai como preco final", () => {
  // O prefixo é obrigatório e não decorativo: é por ele que o validador
  // distingue «a partir de X» de «X». Um `a_partir_de` cujo display fosse igual
  // ao de um `fixo` era o defeito que o §7.1 regra 1 nomeia.
  const fixo = String(precoDisplay("fixo", 1_250_000n));
  const minimo = String(precoDisplay("a_partir_de", 1_250_000n));
  assert.notEqual(fixo, minimo);
  assert.equal(minimo.startsWith(PREFIXO_A_PARTIR_DE), true);
  assert.equal(minimo.endsWith(fixo), true);
});

test("criterio 1: um a_partir_de ou fixo sem preco lanca, e nao finge", () => {
  // O `offer_terms_preco_ck` da revisão `0028` torna o par impossível na base,
  // **nos dois sentidos**. Em código, devolver `null` em silêncio fazia um
  // `fixo` passar por `sob_consulta` e o agente dizer «preço sob consulta»
  // sobre um produto com preço publicado.
  for (const tipo of ["fixo", "a_partir_de"] as const) {
    assert.throws(() => precoDisplay(tipo, null), TypeError, tipo);
  }
});

test("o dinheiro e bigint, e os milhares agrupam-se da direita", () => {
  const E = SEPARADOR_DE_MILHARES;
  assert.equal(formatarMinor(0n), `0${E}Kz`);
  assert.equal(formatarMinor(100n), `1${E}Kz`);
  assert.equal(formatarMinor(99_900n), `999${E}Kz`);
  assert.equal(formatarMinor(100_000n), `1${E}000${E}Kz`);
  assert.equal(formatarMinor(123_456_789_000n), `1${E}234${E}567${E}890${E}Kz`);
  // Os cêntimos só aparecem se não forem zero, e com **vírgula** decimal.
  assert.equal(formatarMinor(1_250_050n), `12${E}500,50${E}Kz`);
  assert.equal(formatarMinor(5n), `0,05${E}Kz`);
  // O sufixo é `Kz` e não `AOA`: o código ISO é da coluna `currency`.
  assert.equal(formatarMinor(100n).endsWith(SUFIXO_DA_MOEDA), true);
});

test("acima de 2^53 centimos o bigint nao perde precisao", () => {
  // A fronteira pela qual `packages/core-ts/src/pagamentos/tipos.ts` declara
  // `Minor = bigint`: com `number`, este valor e o seguinte eram iguais.
  const acima = 9_007_199_254_740_993n; // 2^53 + 1
  assert.notEqual(formatarMinor(acima), formatarMinor(acima - 1n));
});

test("um preco negativo lanca: a base recusa-o, e um calculo nao o inventa", () => {
  assert.throws(() => formatarMinor(-1n), RangeError);
});

// ------------------------------------------ critério 3: a validade do preço

test("criterio 3: preco com preco_valido_ate ultrapassado le-se como a_partir_de", () => {
  const vencido = oferta({ precoValidoAte: "2026-11-01T00:00:00.000Z" });
  assert.equal(precoTipoEfectivo(vencido, AGORA), "a_partir_de");
  // **A coluna não muda**: o que o dono escolheu continua escrito. É a leitura
  // que muda, e é por isso que o `precoTipo` do objecto continua `fixo`.
  assert.equal(vencido.precoTipo, "fixo");
  // E o display sai com o prefixo, que é o que o critério quer dizer com «é
  // tratado como `a_partir_de`».
  const vista = vistaDaOferta(vencido, AGORA);
  assert.equal(vista.precoTipo, "a_partir_de");
  assert.equal(String(vista.precoDisplay).startsWith(PREFIXO_A_PARTIR_DE), true);
});

test("criterio 3: a fronteira da validade e exacta, e o instante igual conta como vencido", () => {
  const limite = "2026-11-02T12:00:00.000Z"; // === AGORA
  const naLinha = oferta({ precoValidoAte: limite });
  // **Igual conta como vencido.** Um preço «válido até às 12:00» não é válido
  // às 12:00:00.000 — e a escolha tinha de ser escrita, porque um `<` e um
  // `<=` dão respostas diferentes exactamente uma vez por preço.
  assert.equal(precoVencido(naLinha, AGORA), true);
  const umMsAntes = new Date(AGORA.getTime() - 1);
  assert.equal(precoVencido(naLinha, umMsAntes), false);
  assert.equal(precoTipoEfectivo(naLinha, umMsAntes), "fixo");
});

test("criterio 3: um preco sem prazo nao vence, que e o caso comum", () => {
  const semPrazo = oferta({ precoValidoAte: null });
  assert.equal(precoVencido(semPrazo, AGORA), false);
  assert.equal(precoTipoEfectivo(semPrazo, AGORA), "fixo");
});

test("um sob_consulta vencido continua sob_consulta, e nao ganha minimo", () => {
  // Promovê-lo a `a_partir_de` dava um mínimo a um produto que nunca teve
  // preço — e a base garante `preco_minor` nulo, pelo que o `precoDisplay`
  // rebentava. A regra do §7.1 é sobre preços que existem.
  const semPreco = oferta({
    precoTipo: "sob_consulta",
    precoMinor: null,
    precoValidoAte: "2026-01-01T00:00:00.000Z",
  });
  assert.equal(precoTipoEfectivo(semPreco, AGORA), "sob_consulta");
  assert.equal(precoVencido(semPreco, AGORA), false);
  assert.equal(vistaDaOferta(semPreco, AGORA).precoDisplay, TEXTO_SOB_CONSULTA);
});

test("um a_partir_de vencido leva o aviso, mesmo sem o modo mudar", () => {
  // O caso que uma implementação que derivasse o aviso da mudança de modo
  // deixava em silêncio: o modo já era `a_partir_de`, logo não «muda» — e o
  // critério 3 manda marcar pedido de confirmação ao dono de qualquer modo.
  const vencido = oferta({
    precoTipo: "a_partir_de",
    precoValidoAte: "2026-10-01T00:00:00.000Z",
  });
  assert.equal(precoTipoEfectivo(vencido, AGORA), "a_partir_de");
  assert.equal(avisosDaOferta(vencido, AGORA).includes("preco_vencido"), true);
});

// ------------------------------------------- critério 3: a semântica do stock

test("criterio 3: os tres stock_modo dizem o que o §7.3 manda dizer", () => {
  assert.equal(DISPONIBILIDADE.garantido, "em stock");
  assert.equal(DISPONIBILIDADE.indicativo, "disponível, a confirmar");
  assert.equal(DISPONIBILIDADE.confirmar_dono, "a confirmar com a loja");

  for (const modo of ["garantido", "indicativo", "confirmar_dono"] as const) {
    const vista = vistaDaOferta(oferta({ stockModo: modo }), AGORA);
    assert.equal(vista.stockModo, modo);
    assert.equal(vista.disponibilidade, DISPONIBILIDADE[modo]);
  }
});

test("criterio 3: indicativo com stock_verificado_at acima de 24 h avisa", () => {
  const limite = STOCK_POR_CONFIRMAR_MS;
  const base = { stockModo: "indicativo" } as const;

  // Exactamente 24 h **não** avisa; 24 h e um milissegundo avisa. A fronteira é
  // `>` e não `>=`, que é a letra do §7.3 («aviso se > 24 h»).
  const naLinha = oferta({
    ...base,
    stockVerificadoAt: new Date(AGORA.getTime() - limite).toISOString(),
  });
  assert.equal(stockPorConfirmar(naLinha, AGORA), false);

  const passou = oferta({
    ...base,
    stockVerificadoAt: new Date(AGORA.getTime() - limite - 1).toISOString(),
  });
  assert.equal(stockPorConfirmar(passou, AGORA), true);
  assert.equal(
    avisosDaOferta(passou, AGORA).includes("stock_por_confirmar"),
    true,
  );
  // E a disponibilidade continua a ser a do modo: o aviso acrescenta-se, não
  // substitui o texto.
  assert.equal(
    vistaDaOferta(passou, AGORA).disponibilidade,
    DISPONIBILIDADE.indicativo,
  );
});

test("nunca conferido conta como por confirmar", () => {
  // Tratá-lo como fresco por falta de data era o erro na direcção errada: uma
  // oferta cujo stock ninguém verificou é mais incerta do que uma verificada há
  // 25 h.
  const nunca = oferta({ stockModo: "indicativo", stockVerificadoAt: null });
  assert.equal(stockPorConfirmar(nunca, AGORA), true);
});

test("o aviso de stock so se aplica ao indicativo", () => {
  // No `garantido` o sistema é a verdade; no `confirmar_dono` a confirmação é
  // obrigatória de qualquer modo, e o aviso próprio dele é outro.
  for (const modo of ["garantido", "confirmar_dono"] as const) {
    const velho = oferta({
      stockModo: modo,
      stockVerificadoAt: "2020-01-01T00:00:00.000Z",
    });
    assert.equal(stockPorConfirmar(velho, AGORA), false, modo);
    assert.equal(
      avisosDaOferta(velho, AGORA).includes("stock_por_confirmar"),
      false,
      modo,
    );
  }
});

test("confirmar_dono leva sempre o aviso da confirmacao", () => {
  const critico = oferta({ stockModo: "confirmar_dono" });
  assert.deepEqual(avisosDaOferta(critico, AGORA), [
    "confirmacao_dono_necessaria",
  ]);
});

// ----------------------------------------------------------------- os avisos

test("os avisos saem pela ordem da constante, e nao pela ordem do calculo", () => {
  // Uma lista cuja ordem depende da implementação obrigava cada teste a ordenar
  // antes de comparar, e o primeiro que se esquecesse ficava intermitente.
  const tudoMal = oferta({
    precoValidoAte: "2026-01-01T00:00:00.000Z",
    stockModo: "confirmar_dono",
    stockVerificadoAt: null,
  });
  const avisos = avisosDaOferta(tudoMal, AGORA);
  // O `stock_por_confirmar` não entra: o modo é `confirmar_dono`, não
  // `indicativo`.
  assert.deepEqual(avisos, ["preco_vencido", "confirmacao_dono_necessaria"]);
  // E a ordem é a de `AVISOS`.
  const posicoes = avisos.map((a) => AVISOS.indexOf(a));
  assert.deepEqual(posicoes, [...posicoes].sort((x, y) => x - y));
});

test("uma oferta sa nao leva aviso nenhum", () => {
  assert.deepEqual(avisosDaOferta(oferta(), AGORA), []);
});

test("a disponibilidade nao muda com o preco: sob_consulta pode estar em stock", () => {
  // «preço sob consulta» é o `precoDisplay` e não a disponibilidade. Pôr o texto
  // do preço neste campo escondia que o produto está em stock.
  const semPreco = oferta({
    precoTipo: "sob_consulta",
    precoMinor: null,
    stockModo: "garantido",
  });
  const vista = vistaDaOferta(semPreco, AGORA);
  assert.equal(vista.precoDisplay, TEXTO_SOB_CONSULTA);
  assert.equal(vista.disponibilidade, "em stock");
});

test("criterio 2: a vista tem os seis campos do contrato, mais os avisos", () => {
  const vista = vistaDaOferta(oferta(), AGORA);
  assert.deepEqual(Object.keys(vista).sort(), [
    "atualizadoAt",
    "avisos",
    "disponibilidade",
    "precoDisplay",
    "precoTipo",
    "sku",
    "stockModo",
  ]);
  // O `atualizadoAt` é a coluna `atualizado_at` e não um `greatest` dos dois
  // instantes anuláveis do §5.4 — ver a razão na revisão `0028`.
  assert.equal(vista.atualizadoAt, oferta().atualizadoAt);
});
