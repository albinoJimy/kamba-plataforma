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
  "valor_mais_um_centimo_da_divergencia",
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
    // **O adaptador que verifica HMAC a serio e ignora a conta.** Nenhuma
    // mutacao de assinatura o apanha; o que o apanha e o callback cruzado do
    // caso 1. Foi o segundo defeito que a revisao adversarial construiu.
    ["chaveGlobal", "assinatura_adulterada_rejeita"],
    ["valorPorFloat", "valor_mais_um_centimo_da_divergencia"],
    ["descartaOrfao", "referencia_desconhecida_e_orfao"],
    ["eventIdPorContador", "callback_duplicado_dez_vezes_um_efeito"],
    ["criaSempre", "criacao_com_resposta_perdida_e_idempotente"],
    ["semJanelaDeRotacao", "rotacao_de_chave"],
    ["rateLimitGenerico", "rate_limit_429"],
    // Uma fraqueza pode matar mais do que um caso, e esta mata dois: sem o
    // instante do evento ninguem pode comparar com o `valid_until` (caso 6) e a
    // ordem passa a depender de quem chegou primeiro (caso 5).
    ["instanteDaChegada", "callback_fora_de_ordem"],
    ["instanteDaChegada", "pagamento_depois_de_valid_until"],
    ["statusDiscordante", "status_concorda_com_o_callback"],
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
      (r) => r.caso === "valor_mais_um_centimo_da_divergencia",
    );
    assert.ok(resultado !== undefined);
    assert.equal(resultado.ok, false);
    assert.match(resultado.detalhe, /diferenca face a cobranca/);
  });

  it("uma fraqueza nao estraga os casos que nao sao dela", async () => {
    const veredicto = await correr(bancoDeEnsaio({ semJanelaDeRotacao: true }));
    const vermelhos = veredicto.resultados.filter((r) => !r.ok).map((r) => r.caso);
    assert.deepEqual(vermelhos, ["rotacao_de_chave"]);
  });

  /**
   * **Todos os dez casos tem canario.**
   *
   * A primeira versao tinha cinco, e os casos 3, 5, 6, 7 e 10 nao tinham
   * nenhum — isto e, metade da suite estava sujeita ao argumento que o proprio
   * ficheiro escreve contra ela. Apanhado pela revisao adversarial, que o
   * cruzou com a cobertura: as linhas nao cobertas de `conformidade.ts` eram
   * **exactamente** os ramos de falha dos casos sem canario.
   *
   * Este ensaio e o que impede a regressao: um caso novo sem canario falha
   * aqui.
   */
  it("os dez casos tem canario", () => {
    const cobertos = new Set(CANARIOS.map(([, caso]) => caso));
    const sem = CASOS.filter((c) => !cobertos.has(c));
    assert.deepEqual(
      sem,
      [],
      `casos sem canario: ${sem.join(", ")} — um caso sem controlo positivo ` +
        "pode estar verde por nao medir nada",
    );
  });
});

describe("pagamentos/conformidade: os dois adaptadores que a revisao construiu", () => {
  /**
   * **O defeito que esta suite existe para apanhar, e que ela deixava passar.**
   *
   * Uma revisao adversarial independente escreveu dois adaptadores obviamente
   * defeituosos e mediu que os **dois** passavam os dez casos e eram activados:
   *
   *   A  `verifyCallback` nao verifica assinatura nenhuma — exige so um campo
   *      `sig` nao vazio — e o `adulterar` do seu banco esvazia esse campo
   *   B  verifica HMAC a serio e **ignora o `acct`**, com um conjunto global de
   *      chaves
   *
   * O A passava porque o unico caso que media autenticidade recebia a mutacao
   * **de quem estava a ser medido**. O B passava porque nenhum dos dez casos
   * usava duas contas. Em producao, o A confirma um pagamento de 999 999,99 Kz
   * a quem conheca o `webhook_token`, e o B aceita o callback da PME A entregue
   * no `webhook_token` da PME B — contra o §3.3, «uma chave por conta de PME e
   * nunca partilhada».
   *
   * Os dois ficam aqui como ensaio permanente, e nao so como nota no PR: um
   * defeito que voltou a passar e um defeito que ninguem notou.
   */
  it("o que nao verifica assinatura nenhuma fica vermelho", async () => {
    const veredicto = await correr(bancoDeEnsaio({ semVerificarAssinatura: true }));
    assert.equal(veredicto.verde, false);
    const caso1 = veredicto.resultados.find((r) => r.caso === "assinatura_adulterada_rejeita");
    assert.equal(caso1?.ok, false);
  });

  it("o que verifica HMAC e ignora a conta fica vermelho", async () => {
    const veredicto = await correr(bancoDeEnsaio({ chaveGlobal: true }));
    assert.equal(veredicto.verde, false);
    const caso1 = veredicto.resultados.find((r) => r.caso === "assinatura_adulterada_rejeita");
    assert.equal(caso1?.ok, false);
    assert.match(caso1?.detalhe ?? "", /OUTRA conta/);
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
