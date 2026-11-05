/**
 * O critério 7: **a compensação nunca apaga o WABA nem o número do cliente**
 * (KAM-091; evidência E1).
 *
 * ## Isto é uma propriedade de negócio
 *
 * A PME autenticou-se na Meta; o WABA e o número são **dela** e continuam dela
 * se nos despedir. Uma saga que falhasse a meio e «limpasse» o que criou não
 * pode levar o número do cliente com ela — o cliente perdia o canal por um
 * defeito nosso.
 *
 * O ticket pede «um ensaio que **falhe** se alguém puser lá um `DELETE` do
 * número». Para que esse ensaio seja possível, o erro tem de ser **escrevível**:
 * é por isso que a `CanalDoCliente` tem `apagarWaba` e `apagarNumero` e que o
 * duplo os conta. Uma porta sem esses métodos provava só que não se pode chamar
 * o que não existe — e bastava alguém acrescentá-los para a prova desaparecer.
 *
 * ## Os dois lados, na mesma montagem
 *
 * «Um canário de recusa sem o caminho legítimo ao lado não prova nada»: uma
 * função que recusasse **tudo** passava qualquer canário. Por isso cada secção
 * aqui mede os dois lados:
 *
 * - o **caminho legítimo**: a compensação do passo 6 cancela a subscrição e
 *   remove a rota, e isso acontece de facto (contadores a 1);
 * - a **recusa**: uma acção destrutiva sobre `waba` ou `phone_number` levanta
 *   `RecursoDoClienteError`, e os contadores destrutivos ficam a **zero**.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  ACCOES_POR_RECURSO,
  AccaoIncoerenteError,
  PASSOS,
  RECURSOS,
  RECURSOS_DO_CLIENTE,
  RecursoDoClienteError,
  Saga,
  TIPOS_DESTRUTIVOS,
  TIPOS_DE_ACCAO,
  accoesDoCanalDoCliente,
  coerente,
  executarNoCanalDoCliente,
  montarPassos,
  permitida,
  verificar,
  type AccaoDeCompensacao,
  type Passo,
  type Recurso,
  type TipoDeAccao,
} from "../src/provisioning/index.ts";
import { CASO, CanalDoClienteFalso, NUMERO, WABA, montar } from "./apoio/provisioning-falsos.ts";

type Montagem = ReturnType<typeof montar>;

function sagaDe(m: Montagem): Saga {
  return new Saga(m.dependencias as never);
}

describe("o predicado, medido sozinho e nas duas direccoes", () => {
  /**
   * **Proibida é a conjunção de duas coisas**: recurso do cliente **e** tipo
   * destrutivo. Nenhuma sozinha decide, e é isso que esta tabela mede — um
   * predicado que só olhasse para o recurso recusava `cancelar_subscricao` no
   * WABA, que é precisamente o que o critério manda fazer.
   */
  it("so recusa a conjuncao: recurso do cliente E tipo destrutivo", () => {
    const casos: readonly { accao: AccaoDeCompensacao; esperado: boolean }[] = [
      // recurso do cliente + destrutivo → recusa
      { accao: { tipo: "apagar", recurso: "phone_number", ref: NUMERO }, esperado: false },
      { accao: { tipo: "apagar", recurso: "waba", ref: WABA }, esperado: false },
      { accao: { tipo: "revogar", recurso: "waba", ref: WABA }, esperado: false },
      { accao: { tipo: "revogar", recurso: "phone_number", ref: NUMERO }, esperado: false },
      // recurso do cliente + não destrutivo → **permite**
      { accao: { tipo: "cancelar_subscricao", recurso: "waba", ref: WABA }, esperado: true },
      { accao: { tipo: "remover_rota", recurso: "phone_number", ref: NUMERO }, esperado: true },
      // recurso nosso + destrutivo → **permite**
      { accao: { tipo: "revogar", recurso: "chave_llm", ref: "k" }, esperado: true },
      { accao: { tipo: "apagar", recurso: "conta_atendimento", ref: "c" }, esperado: true },
      { accao: { tipo: "apagar", recurso: "canal_comercio", ref: "ch" }, esperado: true },
    ];
    for (const { accao, esperado } of casos) {
      assert.equal(
        permitida(accao),
        esperado,
        `${accao.tipo} sobre ${accao.recurso} deu ${!esperado}`,
      );
    }
  });

  it("os recursos do cliente sao o WABA e o numero, e mais nenhum", () => {
    assert.deepEqual([...RECURSOS_DO_CLIENTE], ["waba", "phone_number"]);
  });

  /**
   * `cancelar_subscricao` e `remover_rota` **não** podem entrar nos destrutivos:
   * se entrassem, o critério 7 proibia as duas acções que ele próprio manda
   * fazer, e a compensação do passo 6 passava a não fazer nada.
   */
  it("os tipos destrutivos nao incluem as duas accoes legitimas", () => {
    assert.deepEqual([...TIPOS_DESTRUTIVOS], ["apagar", "revogar"]);
    assert.ok(!TIPOS_DESTRUTIVOS.includes("cancelar_subscricao"));
    assert.ok(!TIPOS_DESTRUTIVOS.includes("remover_rota"));
  });

  /**
   * **A varredura exaustiva**: todos os tipos × todos os recursos do cliente.
   *
   * Um tipo de acção novo acrescentado ao `TIPOS_DE_ACCAO` sem se decidir se é
   * destrutivo cai aqui — porque este ensaio afirma sobre a tabela inteira e não
   * sobre uma lista de casos que alguém se lembrou de escrever.
   */
  it("nenhum tipo destrutivo passa sobre nenhum recurso do cliente", () => {
    for (const recurso of RECURSOS_DO_CLIENTE) {
      for (const tipo of TIPOS_DE_ACCAO) {
        const accao: AccaoDeCompensacao = { tipo, recurso, ref: "x" };
        const destrutivo = TIPOS_DESTRUTIVOS.includes(tipo);
        assert.equal(
          permitida(accao),
          !destrutivo,
          `${tipo} sobre ${recurso}: destrutivo=${destrutivo} mas permitida=${permitida(accao)}`,
        );
      }
    }
  });

  it("`verificar` levanta `RecursoDoClienteError` e nomeia o passo", () => {
    assert.throws(
      () => verificar({ tipo: "apagar", recurso: "phone_number", ref: NUMERO }, "espera_es"),
      (erro: unknown) => {
        assert.ok(erro instanceof RecursoDoClienteError);
        assert.equal(erro.passo, "espera_es");
        assert.match(erro.message, /recurso do cliente \(E1\)/);
        return true;
      },
    );
  });

  it("`verificar` nao levanta no caminho legitimo", () => {
    verificar({ tipo: "cancelar_subscricao", recurso: "waba", ref: WABA }, "espera_es");
    // A rota e **nossa** (`rota_chr`), nao o numero. Ver a nota do
    // `accoesDoCanalDoCliente`: declarar `remover_rota` sobre o `phone_number`
    // removia a rota duas vezes, por dois nomes.
    verificar({ tipo: "remover_rota", recurso: "rota_chr", ref: NUMERO }, "inbox_e_rota");
  });

  /**
   * **Sobre o numero do cliente nao ha operacao legitima nenhuma.** E a forma
   * mais forte de dizer o criterio 7: a lista de tipos do `phone_number` e
   * vazia, logo qualquer accao sobre ele e incoerente.
   */
  it("nenhuma accao sobre o numero do cliente e permitida-e-coerente", () => {
    for (const tipo of TIPOS_DE_ACCAO) {
      assert.throws(
        () => verificar({ tipo, recurso: "phone_number", ref: NUMERO }, "espera_es"),
        `${tipo} sobre o numero do cliente passou`,
      );
    }
  });
});

describe("a coerencia entre o tipo declarado e o recurso", () => {
  /**
   * **A declaração tem de ser a verdade sobre o que aconteceu**, e é a premissa
   * do critério 7. Antes da revisão adversarial, o executor despachava pelo
   * `recurso` e ignorava o `tipo` em seis dos nove casos: um
   * `{tipo: "apagar", recurso: "inbox"}` passava o guarda (a *inbox* não é do
   * cliente) e chamava `desligar`. A compensação fazia uma coisa e declarava
   * outra, e a métrica, que conta pelo recurso, não distinguia as duas.
   */
  it("cada recurso aceita so os tipos que lhe pertencem", () => {
    for (const recurso of RECURSOS) {
      const permitidos = ACCOES_POR_RECURSO[recurso];
      assert.ok(permitidos !== undefined, `${recurso} fora do mapa`);
      // O `phone_number` e o unico com lista **vazia**, e e de proposito.
      assert.equal(
        permitidos.length === 0,
        recurso === "phone_number",
        `${recurso}: lista vazia inesperada`,
      );
      for (const tipo of TIPOS_DE_ACCAO) {
        const accao: AccaoDeCompensacao = { tipo, recurso, ref: "x" };
        assert.equal(
          coerente(accao),
          permitidos.includes(tipo),
          `${tipo} sobre ${recurso}`,
        );
      }
    }
  });

  it("um `apagar` sobre a inbox e incoerente, e levanta", () => {
    assert.throws(
      () => verificar({ tipo: "apagar", recurso: "inbox", ref: "i" }, "inbox_e_rota"),
      AccaoIncoerenteError,
    );
  });

  it("o `desactivar` da inbox e coerente, e nao levanta", () => {
    verificar({ tipo: "desactivar", recurso: "inbox", ref: "i" }, "inbox_e_rota");
  });

  /**
   * A ordem das duas perguntas importa para a razão que se lê: um
   * `{apagar, phone_number}` é incoerente **e** é um recurso do cliente, e o que
   * manda é a segunda.
   */
  it("sobre o numero, a razao que levanta e a do recurso do cliente", () => {
    assert.throws(
      () => verificar({ tipo: "apagar", recurso: "phone_number", ref: NUMERO }, "espera_es"),
      RecursoDoClienteError,
    );
  });
});

describe("as duas accoes do passo 6 — e so essas duas", () => {
  it("e `cancelar_subscricao` no WABA, e e a unica sobre o que e do cliente", () => {
    assert.deepEqual(accoesDoCanalDoCliente(WABA), [
      { tipo: "cancelar_subscricao", recurso: "waba", ref: WABA },
    ]);
  });

  /**
   * **E a produção chama-a.** Sem esta asserção o ensaio acima mede uma função
   * morta — era o caso antes da revisão adversarial: o `accoesDoCanalDoCliente`
   * existia, tinha este ensaio, e nenhum código de produção o invocava, pelo
   * que acrescentar uma terceira acção à lista real do `passos.ts` deixava-o
   * verde.
   */
  it("e a compensacao do passo 6 da saga devolve exactamente essa lista", async () => {
    const m = montar();
    const saga = sagaDe(m);
    await saga.correr(CASO);
    const executadas = await saga.compensar(CASO, "ensaio");
    const doCanal = executadas.filter(
      (a: AccaoDeCompensacao) => a.recurso === "waba" || a.recurso === "phone_number",
    );
    assert.deepEqual(doCanal, [...accoesDoCanalDoCliente(WABA)]);
  });

  it("o caminho legitimo cancela a subscricao e nao apaga nada", async () => {
    const canal = new CanalDoClienteFalso();
    for (const accao of accoesDoCanalDoCliente(WABA)) {
      await executarNoCanalDoCliente(canal, accao, "espera_es");
    }
    assert.deepEqual(canal.subscricoesCanceladas, [WABA]);
    assert.equal(canal.wabasApagados, 0);
    assert.equal(canal.numerosApagados, 0);
    // **A Meta nunca e chamada para remover a rota**: a rota e a nossa linha de
    // `tenant_channels`, e sai pela porta `RotaDoCanal`.
    assert.deepEqual(canal.rotasRemovidas, []);
  });

  /**
   * **O canário.** Um `DELETE` do número posto na compensação é recusado, e o
   * contador do duplo confirma que a porta destrutiva **não** foi tocada.
   */
  it("um `apagar` do numero e recusado e a porta destrutiva nao e tocada", async () => {
    const canal = new CanalDoClienteFalso();
    await assert.rejects(
      () =>
        executarNoCanalDoCliente(
          canal,
          { tipo: "apagar", recurso: "phone_number", ref: NUMERO },
          "espera_es",
        ),
      RecursoDoClienteError,
    );
    assert.equal(canal.numerosApagados, 0, "a porta `apagarNumero` foi chamada");
  });

  it("um `apagar` do WABA e recusado da mesma forma", async () => {
    const canal = new CanalDoClienteFalso();
    await assert.rejects(
      () =>
        executarNoCanalDoCliente(
          canal,
          { tipo: "apagar", recurso: "waba", ref: WABA },
          "espera_es",
        ),
      RecursoDoClienteError,
    );
    assert.equal(canal.wabasApagados, 0);
  });
});

describe("a saga inteira: a compensacao nunca toca no que e do cliente", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  /**
   * **A propriedade medida sobre a saga toda, e não sobre um passo.**
   *
   * A saga conclui os oito passos e depois compensa tudo. Se **qualquer**
   * compensação — a do passo 6, a do 7 ou a de um passo que alguém acrescente em
   * 2027 — pedir a destruição do WABA ou do número, os dois contadores deixam de
   * ser zero e este ensaio fica vermelho.
   */
  it("compensar os oito passos deixa o WABA e o numero intactos", async () => {
    const saga = sagaDe(m);
    assert.equal((await saga.correr(CASO)).estado, "concluida");

    await saga.compensar(CASO, "ensaio");

    assert.equal(m.canalDoCliente.wabasApagados, 0, "a compensacao apagou o WABA do cliente");
    assert.equal(m.canalDoCliente.numerosApagados, 0, "a compensacao apagou o numero do cliente");
  });

  /**
   * E o caminho legítimo **aconteceu**: sem esta asserção, uma compensação que
   * não fizesse nada passava o ensaio acima.
   */
  it("e a compensacao fez de facto as duas accoes legitimas", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);
    await saga.compensar(CASO, "ensaio");

    assert.deepEqual(
      m.canalDoCliente.subscricoesCanceladas,
      [WABA],
      "a compensacao do passo 6 nao cancelou a subscricao de webhooks",
    );
    // **A rota removida uma vez, e pela porta certa.** Antes era removida duas
    // vezes — `phone_number` no passo 6 e `rota_chr` no passo 7, as duas a cair
    // no `removerRota` da Meta —, e a `saga_compensado_total` contava-a a
    // dobrar. O ensaio usava `includes`, que e verdade com uma ou com cinco.
    assert.deepEqual(m.rota.removidas, [NUMERO]);
    assert.deepEqual(m.canalDoCliente.rotasRemovidas, []);
    // E os oito passos ficaram `compensado`, ou sem acção a fazer.
    assert.equal(m.armazem.estadoDe("espera_es"), "compensado");
    assert.equal(m.armazem.estadoDe("inbox_e_rota"), "compensado");
  });

  /**
   * **O ensaio que o ticket pede por palavras: «falha se alguém puser lá um
   * `DELETE` do número».**
   *
   * Em vez de esperar que alguém o ponha, põe-se aqui: injecta-se no passo 6
   * uma compensação que pede o `apagar` do número — exactamente o defeito que o
   * critério 7 existe para impedir — e afirma-se que a saga o **recusa** e que a
   * porta destrutiva fica a zero.
   *
   * Isto mede o guarda em execução, que é o que protege a propriedade contra um
   * ticket futuro. Se o `compensacao.ts` deixar de verificar, este ensaio fica
   * vermelho **e** o `numerosApagados` passa a 1.
   */
  /**
   * **A recusa medida pela saga, com o defeito injectado num passo.**
   *
   * Este ensaio chamava `executarNoCanalDoCliente` directamente, apesar do
   * título dizer «pela saga» — isto é, nunca tocava no `Saga.#executar`, e a
   * revisão adversarial mostrou que o `verificar` que está lá era um **mutante
   * sobrevivente**: apagá-lo deixava as quatro *suites* verdes, porque o único
   * ramo que podia executar uma acção proibida volta a verificar dentro do
   * `executarNoCanalDoCliente`.
   *
   * Agora injecta-se a acção proibida na `compensar` de um passo — que é por
   * onde um ticket futuro a escreveria — e corre-se `saga.compensar`. Apagar o
   * `verificar` do `#executar` põe isto vermelho: a acção chega ao
   * `case "phone_number"` e o `numerosApagados` sobe.
   */
  it("uma accao proibida declarada por um passo e recusada dentro da saga", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);

    // O defeito: o passo 6 passa a declarar o `apagar` do número do cliente.
    const passos = montarPassos(m.dependencias as never);
    const passo6 = passos.get("espera_es");
    assert.ok(passo6 !== undefined);
    const comDefeito = {
      ...passo6,
      compensar: async () => [
        { tipo: "apagar", recurso: "phone_number", ref: NUMERO } as const,
      ],
    };
    const sagaComDefeito = new Saga({
      ...(m.dependencias as Record<string, unknown>),
      passos: new Map([...passos, ["espera_es", comDefeito]]),
    } as never);

    const executadas = await sagaComDefeito.compensar(CASO, "ensaio");

    // A compensação **para** no passo defeituoso e nunca chama a porta
    // destrutiva. O que já tinha corrido (os passos 7 e 8, que vêm antes na
    // ordem inversa) fica feito.
    assert.equal(m.canalDoCliente.numerosApagados, 0, "a saga apagou o numero do cliente");
    assert.deepEqual(
      executadas.filter((a: AccaoDeCompensacao) => a.recurso === "phone_number"),
      [],
      "a accao proibida entrou na lista de executadas",
    );
    // E a linha de log diz que a compensação falhou nesse passo.
    assert.ok(
      m.linhasDeLog.some((l) => l.outcome === "compensacao_falhou"),
      "a recusa nao foi registada",
    );
  });

  /**
   * **O `verificar` do `#executar` só se mede com um recurso sem segunda
   * fechadura.**
   *
   * Uma acção proibida sobre `waba`/`phone_number` não o mede: esse ramo volta
   * a verificar dentro do `executarNoCanalDoCliente`, pelo que apagar o
   * `verificar` do `#executar` não muda nada — a mutação **sobreviveu** duas
   * vezes por esta razão. O que o mede é um recurso cujo ramo **não** tem
   * segunda fechadura: a `inbox`, que o `#executar` despacha directamente para
   * `desligar`. Com o guarda, `{apagar, inbox}` é incoerente e levanta; sem
   * ele, a *inbox* é desligada e o contador do duplo sobe.
   */
  it("uma accao incoerente sobre a inbox e recusada dentro da saga", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);

    const passos = montarPassos(m.dependencias as never);
    const passo7 = passos.get("inbox_e_rota");
    assert.ok(passo7 !== undefined);
    const comDefeito = {
      ...passo7,
      compensar: async () => [{ tipo: "apagar", recurso: "inbox", ref: "inbox-7" } as const],
    };
    const sagaComDefeito = new Saga({
      ...(m.dependencias as Record<string, unknown>),
      passos: new Map([...passos, ["inbox_e_rota", comDefeito]]),
    } as never);

    await sagaComDefeito.compensar(CASO, "ensaio");

    assert.deepEqual(
      m.inbox.desligadas,
      [],
      "a saga desligou a inbox a partir de uma accao declarada `apagar`",
    );
  });

  it("e a accao coerente sobre a inbox corre — o caminho legitimo ao lado", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);
    await saga.compensar(CASO, "ensaio");
    assert.deepEqual(m.inbox.desligadas, ["inbox-1"]);
  });

  it("e sem o defeito a mesma compensacao corre inteira — o caminho legitimo", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);
    const executadas = await saga.compensar(CASO, "ensaio");
    assert.ok(executadas.length >= 6, "a compensacao nao correu os passos todos");
    assert.equal(m.canalDoCliente.numerosApagados, 0);
    assert.deepEqual(m.canalDoCliente.subscricoesCanceladas, [WABA]);
  });

  /**
   * Nenhum dos oito passos declara, hoje, uma acção destrutiva sobre um recurso
   * do cliente.
   *
   * Afirma sobre as **declarações** e não sobre o efeito: é a asserção que um
   * ticket futuro encontra vermelha ao acrescentar `{tipo: "apagar", recurso:
   * "phone_number"}` à compensação de qualquer passo, mesmo que o guarda em
   * execução nunca chegue a ser chamado porque esse passo não ficou `done`.
   */
  it("nenhum passo declara uma accao destrutiva sobre o WABA ou o numero", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);
    const todas = await m.armazem.passosDoCaso(CASO.onboardingId);
    assert.equal(
      todas.filter((l) => l.status === "concluido").length,
      PASSOS.length,
      "nao concluiu os oito passos",
    );

    const executadas = await saga.compensar(CASO, "ensaio");
    const proibidas = executadas.filter(
      (a: AccaoDeCompensacao) =>
        (RECURSOS_DO_CLIENTE as readonly Recurso[]).includes(a.recurso) &&
        (TIPOS_DESTRUTIVOS as readonly TipoDeAccao[]).includes(a.tipo),
    );
    assert.deepEqual(proibidas, [], "um passo declarou uma accao destrutiva sobre o cliente");
    assert.ok(executadas.length > 0, "a compensacao nao executou accao nenhuma");
  });
});

describe("o passo 1 nunca apaga o tenant — so marca `cancelado`", () => {
  /**
   * `docs/tecnica/10` §5.2, passo 1: «marcar `cancelado`; **sem apagar
   * histórico**». Um tenant apagado levava consigo o `audit_log` do onboarding,
   * e o que se purga e quando é do KAM-098 (off-boarding) e não de uma
   * compensação de saga.
   */
  it("a compensacao do passo 1 marca o caso e nao emite nenhum `apagar`", async () => {
    const m = montar();
    const saga = sagaDe(m);
    await saga.correr(CASO);
    const executadas = await saga.compensar(CASO, "ensaio");

    assert.deepEqual(m.registoDoCaso.cancelados, [CASO.onboardingId]);
    const sobreTenant = executadas.filter((a: AccaoDeCompensacao) => a.recurso === "tenant");
    assert.deepEqual(
      sobreTenant.map((a: AccaoDeCompensacao) => a.tipo),
      ["marcar_cancelado"],
      "a compensacao do passo 1 emitiu algo que nao e `marcar_cancelado`",
    );
  });
});
