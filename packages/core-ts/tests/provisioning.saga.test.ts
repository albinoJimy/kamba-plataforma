/**
 * A máquina de estados da saga de provisioning (KAM-091).
 *
 * **O que só aqui se prova**, e o que aqui **não** se prova:
 *
 * 1. **Quantas vezes cada recurso foi criado.** Os critérios 1 e 4 têm a forma
 *    «entregar o evento N× produz uma coisa só», e a asserção que os prova é um
 *    contador — o `InventarioFalso.criadas`. Contra um Chatwoot real contavam-se
 *    as contas que ficam lá; os duplos aqui contam a chamada, que é o mesmo
 *    predicado e não precisa dos serviços a correr.
 * 2. **A ordem inversa da compensação** (critério 3), com as linhas devolvidas
 *    **embaralhadas** pelo armazém — ver a nota do `passosDoCaso`.
 * 3. **O *backoff* e o tecto de três tentativas** (critério 5), por números
 *    pedidos ao `dormir` e por contagem de chamadas ao *ensure*.
 * 4. **As esperas não gastam tentativa** (critério 6).
 *
 * O que **não** se prova aqui, e é preciso dizê-lo: nada sobre o Chatwoot, o
 * LiteLLM ou o Medusa. Não há serviço `medusa` em compose nenhum e o
 * `CommerceRegistry` não tem método de canal (ver `src/provisioning/contrato.ts`);
 * o que estes ensaios medem é a saga. A idempotência contra um `UNIQUE` real e a
 * RLS são da *suite* de base de dados, e nenhuma asserção daqui as substitui —
 * um armazém falso devolve o que se lhe mandou devolver.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  AguardaEntradaError,
  BACKOFF_BASE_MS,
  PASSOS,
  Saga,
  TENTATIVAS,
  atrasoDaTentativa,
  codigoDoErro,
  montarPassos,
  ordemInversa,
  type Desfecho,
  type LinhaDePasso,
  type Passo,
} from "../src/provisioning/index.ts";
import { CASO, NUMERO, TENANT, WABA, montar } from "./apoio/provisioning-falsos.ts";

type Montagem = ReturnType<typeof montar>;

function sagaDe(m: Montagem): Saga {
  return new Saga(m.dependencias as never);
}

describe("a saga corre os oito passos", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  it("conclui os oito passos pela ordem do `docs/tecnica/10` §5.2", async () => {
    const desfecho = await sagaDe(m).correr(CASO);

    assert.equal(desfecho.estado, "concluida");
    assert.equal(desfecho.primeiraTentativa, true);
    for (const passo of PASSOS) {
      assert.equal(m.armazem.estadoDe(passo), "concluido", `o passo ${passo} nao concluiu`);
    }
    // A ordem **medida**, e não assumida: as escritas de `concluido` saem na
    // ordem de `PASSOS`.
    const concluidos = m.armazem.escritas
      .filter((e) => e.startsWith("concluido:"))
      .map((e) => e.slice("concluido:".length));
    assert.deepEqual(concluidos, [...PASSOS]);
  });

  it("os oito passos sao os do bloco, e a lista nao muda sem alguem o decidir", () => {
    assert.deepEqual(
      [...PASSOS],
      [
        "tenant_e_caso",
        "chave_llm",
        "canal_comercio",
        "conta_atendimento",
        "entitlements",
        "espera_es",
        "inbox_e_rota",
        "teste_ponta_a_ponta",
      ],
    );
  });
});

describe("criterio 1 — entregar `tenant.approved` 2x nao duplica nada", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  /**
   * **A asserção central do critério 1.** Quatro contadores, e os quatro a 1.
   *
   * Os `entitlements` contam à parte porque a porta promete idempotência por
   * `(tenant_id, modulo)` — é um `ON CONFLICT DO UPDATE` e correr duas vezes é
   * legítimo; o que se afirma dele é que os limites ficam os mesmos, não que a
   * chamada não se repete.
   */
  it("duas passagens dao 1 conta, 1 chave, 1 canal e 1 conjunto de entitlements", async () => {
    const saga = sagaDe(m);
    const primeira = await saga.correr(CASO);
    const segunda = await saga.correr(CASO);

    assert.equal(primeira.estado, "concluida");
    assert.equal(segunda.estado, "concluida");

    assert.equal(m.chaveDeLlm.inventario.criadas, 1, "criou duas chaves LiteLLM");
    assert.equal(m.comercio.inventario.criadas, 1, "criou dois canais de comercio");
    assert.equal(m.inbox.inventario.criadas, 1, "criou duas inboxes");
    // A conta de atendimento é caixa preta (KAM-019): o que se mede é que a
    // porta **não foi chamada** na segunda passagem, porque o passo já estava
    // `concluido`. Uma segunda chamada não criaria uma segunda conta — o
    // `ensureAccount` procura antes de criar —, mas seria uma ida ao Chatwoot
    // por nada, e é isso que o «re-executar a saga» do critério tem de evitar.
    assert.equal(m.handoff.chamadas, 1, "chamou o provedor de atendimento duas vezes");
    assert.equal(m.entitlements.garantidos.get(TENANT), 1);
  });

  it("a terceira passagem tambem nao cria nada, e nao e por acaso da segunda", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);
    await saga.correr(CASO);
    await saga.correr(CASO);
    assert.equal(m.chaveDeLlm.inventario.criadas, 1);
    assert.equal(m.comercio.inventario.criadas, 1);
    assert.equal(m.handoff.chamadas, 1);
  });

  /**
   * O caminho legítimo ao lado do canário: **um tenant diferente cria recursos
   * próprios.**
   *
   * Sem este ensaio, uma saga que nunca criasse nada passava os dois acima. É a
   * mesma razão pela qual o critério 7 tem o seu caminho legítimo medido.
   */
  it("um segundo tenant cria os seus proprios recursos", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);
    await saga.correr({
      ...CASO,
      onboardingId: "88888888-8888-4888-8888-888888888888",
      tenantId: "22222222-2222-4222-8222-222222222222",
    });
    assert.equal(m.chaveDeLlm.inventario.criadas, 2);
    assert.equal(m.comercio.inventario.criadas, 2);
  });
});

describe("criterio 3 — a compensacao corre em ordem inversa e so dos `done`", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  /**
   * **A falha é injectada no passo 4**, como o critério manda, e a compensação
   * tem de desfazer 3, 2, 1 **por essa ordem**.
   */
  it("falha no passo 4 compensa 3, 2, 1 por essa ordem", async () => {
    // O passo 4 falha sempre: o duplo do handoff levanta.
    m.handoff.ensureAccount = async () => {
      throw new Error("chatwoot_indisponivel");
    };
    const saga = sagaDe(m);
    const desfecho = await saga.correr(CASO);
    assert.equal(desfecho.estado, "escalada");
    assert.equal(desfecho.passo, "conta_atendimento");

    await saga.compensar(CASO, "passo_4");

    const compensados = m.armazem.escritas
      .filter((e) => e.startsWith("compensado:"))
      .map((e) => e.slice("compensado:".length));
    assert.deepEqual(
      compensados,
      ["canal_comercio", "chave_llm", "tenant_e_caso"],
      "a compensacao nao correu na ordem inversa dos passos `done`",
    );
  });

  /**
   * **«Só os `done`», e o filtro é do `saga.ts`.**
   *
   * O armazém devolve **todas** as linhas, em qualquer estado — ver a nota do
   * `passosDoCaso`. Logo esta asserção mede o `filter` do `compensar` e não o
   * de um duplo: se ele desaparecer, o passo 4 (que ficou `escalado`) entra na
   * compensação e o `contasApagadas` deixa de estar vazio.
   *
   * A primeira versão deste ensaio media o duplo, e foi um ensaio de mutação
   * que o mostrou — a mutação que tirava o filtro ao `saga.ts` **sobreviveu**.
   */
  it("o passo 4, que falhou, nao e compensado — so os `done` sao", async () => {
    m.handoff.ensureAccount = async () => {
      throw new Error("chatwoot_indisponivel");
    };
    const saga = sagaDe(m);
    await saga.correr(CASO);
    const executadas = await saga.compensar(CASO, "passo_4");

    assert.equal(m.armazem.estadoDe("conta_atendimento"), "escalado");
    assert.deepEqual(m.contasApagadas, [], "apagou uma conta que nunca ficou `done`");
    assert.deepEqual(
      executadas.filter((a) => a.recurso === "conta_atendimento"),
      [],
      "declarou uma compensacao para um passo que nao esta `concluido`",
    );
    // E o armazém de facto trouxe a linha do passo 4: sem isto, o ensaio
    // passava porque não havia nada para filtrar.
    const todas = await m.armazem.passosDoCaso(CASO.onboardingId);
    assert.ok(
      todas.some((l) => l.step === "conta_atendimento" && l.status === "escalado"),
      "o armazem nao devolveu a linha do passo escalado: o filtro nao foi exercido",
    );
  });

  it("as compensacoes dos passos 1, 2 e 3 chegam as portas certas", async () => {
    m.handoff.ensureAccount = async () => {
      throw new Error("chatwoot_indisponivel");
    };
    const saga = sagaDe(m);
    await saga.correr(CASO);
    await saga.compensar(CASO, "passo_4");

    // passo 2: a chave revoga-se (é nossa).
    assert.equal(m.chaveDeLlm.revogadas.length, 1);
    // passo 3: o canal **arquiva-se**, e só se apaga porque está vazio.
    assert.equal(m.comercio.arquivados.length, 1);
    assert.equal(m.comercio.apagados.length, 1);
    // passo 1: o caso marca-se `cancelado`, **sem apagar histórico**.
    assert.deepEqual(m.registoDoCaso.cancelados, [CASO.onboardingId]);
  });

  it("um canal com encomendas arquiva-se e **nao** se apaga", async () => {
    m.comercio.estaVazio = false;
    m.handoff.ensureAccount = async () => {
      throw new Error("chatwoot_indisponivel");
    };
    const saga = sagaDe(m);
    await saga.correr(CASO);
    await saga.compensar(CASO, "passo_4");

    assert.equal(m.comercio.arquivados.length, 1);
    assert.deepEqual(m.comercio.apagados, [], "apagou um canal que nao estava vazio");
  });

  /**
   * A ordem inversa, medida **sem a saga**, com as linhas à entrada
   * embaralhadas.
   *
   * O `ordemInversa` é puro e exportado por isso: se ele depender da ordem de
   * chegada, este ensaio fica vermelho, e um ensaio que só corresse a saga
   * inteira não distinguia «ordena» de «a consulta devolveu ordenado».
   */
  it("`ordemInversa` ordena por `PASSOS` e nao pela ordem de chegada", () => {
    const linha = (step: Passo): LinhaDePasso => ({
      onboarding_id: CASO.onboardingId,
      tenant_id: TENANT,
      step,
      status: "concluido",
      attempt: 1,
      external_id: null,
      error_code: null,
    });
    const embaralhadas = [linha("chave_llm"), linha("tenant_e_caso"), linha("canal_comercio")];
    assert.deepEqual(
      ordemInversa(embaralhadas).map((l) => l.step),
      ["canal_comercio", "chave_llm", "tenant_e_caso"],
    );
  });
});

describe("criterio 5 — backoff 1-3 e sem retry infinito", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  /** A primeira metade: os números. Pura, sem relógio nem fila. */
  it("o atraso e exponencial e a primeira tentativa nao espera", () => {
    assert.equal(atrasoDaTentativa(1), 0);
    assert.equal(atrasoDaTentativa(2), BACKOFF_BASE_MS);
    assert.equal(atrasoDaTentativa(3), BACKOFF_BASE_MS * 2);
    // Exponencial e **não** linear: a 4.ª seria 4× a base. Um `base * (n-1)`
    // passava as três linhas acima se a base fosse 1000 e a 3.ª fosse 2000 por
    // coincidência — não passa esta.
    assert.equal(atrasoDaTentativa(4), BACKOFF_BASE_MS * 4);
  });

  /**
   * A segunda metade, e é a que faz o critério: **três chamadas ao *ensure*, e
   * não quatro.**
   */
  it("tres falhas escalam e o *ensure* e chamado exactamente tres vezes", async () => {
    let chamadas = 0;
    m.handoff.ensureAccount = async () => {
      chamadas += 1;
      throw new Error("chatwoot_indisponivel");
    };
    const desfecho = await sagaDe(m).correr(CASO);

    assert.equal(desfecho.estado, "escalada");
    assert.equal(chamadas, TENTATIVAS, "o tecto de tentativas nao e tres");
    assert.equal(m.armazem.estadoDe("conta_atendimento"), "escalado");
    assert.equal(m.armazem.tentativaDe("conta_atendimento"), TENTATIVAS);
  });

  it("os atrasos pedidos sao 0, 1x e 2x a base — e nada depois", async () => {
    m.handoff.ensureAccount = async () => {
      throw new Error("chatwoot_indisponivel");
    };
    await sagaDe(m).correr(CASO);
    // Os cinco primeiros passos passam à primeira (atraso 0 cada), e o passo 4
    // é o quarto: os seus três atrasos são os três últimos pedidos.
    const doPasso4 = m.dormidas.slice(-3);
    assert.deepEqual(doPasso4, [0, BACKOFF_BASE_MS, BACKOFF_BASE_MS * 2]);
  });

  /**
   * **Um passo escalado não se volta a tentar numa entrega seguinte do evento.**
   *
   * É aqui que o «sem retry infinito» se ganha ou perde: o `tenant.approved`
   * entrega-se *at-least-once*, e uma saga que reabrisse um passo escalado
   * tinha tecto de três **por entrega** — isto é, nenhum.
   */
  it("uma segunda entrega do evento nao reabre um passo escalado", async () => {
    let chamadas = 0;
    m.handoff.ensureAccount = async () => {
      chamadas += 1;
      throw new Error("chatwoot_indisponivel");
    };
    const saga = sagaDe(m);
    await saga.correr(CASO);
    assert.equal(chamadas, TENTATIVAS);

    const segunda = await saga.correr(CASO);
    assert.equal(segunda.estado, "escalada");
    assert.equal(chamadas, TENTATIVAS, "a segunda entrega do evento deu uma quarta tentativa");
  });

  it("uma falha que resolve a segunda tentativa conclui, e nao escala", async () => {
    let chamadas = 0;
    const real = m.handoff.ensureAccount.bind(m.handoff);
    m.handoff.ensureAccount = async () => {
      chamadas += 1;
      if (chamadas === 1) throw new Error("chatwoot_indisponivel");
      return real();
    };
    const desfecho = await sagaDe(m).correr(CASO);
    assert.equal(desfecho.estado, "concluida");
    assert.equal(desfecho.primeiraTentativa, false, "disse que passou a primeira e nao passou");
    assert.equal(m.armazem.estadoDe("conta_atendimento"), "concluido");
  });
});

describe("criterio 6 — os passos 6-8 sao esperas e nao falhas", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  it("sem numero do ES o passo 6 fica `aguarda_es` e nao gasta tentativa", async () => {
    m.canalDoCliente.numero = null;
    const desfecho = await sagaDe(m).correr(CASO);

    assert.equal(desfecho.estado, "aguarda");
    assert.equal(desfecho.passo, "espera_es");
    assert.equal(m.armazem.esperaDe("espera_es"), "aguarda_es");
    // **Zero**: o `marcarEspera` repõe o `attempt`. O que isso protege **não** é
    // a escalada por esperas repetidas — essa nunca acontece, porque o
    // `AguardaEntradaError` é apanhado antes do ramo da escalada (medido pela
    // revisão adversarial, que achou a justificação falsa) — e sim o caso
    // misto: um passo que espera e **depois** falha a sério precisa das três
    // tentativas inteiras.
    assert.equal(m.armazem.tentativaDe("espera_es"), 0);
    assert.equal(m.armazem.estadoDe("espera_es"), "em_curso");
  });

  it("tres passagens em espera nao escalam o caso", async () => {
    m.canalDoCliente.numero = null;
    const saga = sagaDe(m);
    await saga.correr(CASO);
    await saga.correr(CASO);
    const terceira = await saga.correr(CASO);
    assert.equal(terceira.estado, "aguarda");
    assert.notEqual(m.armazem.estadoDe("espera_es"), "escalado");
  });

  it("quando o numero chega, a espera destrava e a saga conclui", async () => {
    m.canalDoCliente.numero = null;
    const saga = sagaDe(m);
    assert.equal((await saga.correr(CASO)).estado, "aguarda");

    m.canalDoCliente.numero = NUMERO;
    const depois = await saga.correr(CASO);
    assert.equal(depois.estado, "concluida");
    assert.deepEqual(m.canalDoCliente.subscritos, [WABA]);
  });

  /**
   * **O caso misto, que é o que a reposição do `attempt` protege de facto.**
   *
   * Um passo que espera e **depois** falha a sério tem de ter as três
   * tentativas inteiras. Sem a reposição, as esperas anteriores gastavam-lhe o
   * tecto e o caso escalava à primeira falha real — e nada media isto: a
   * asserção que existia media o número de esperas, que nunca escala.
   */
  it("um passo que espera e depois falha tem as tres tentativas inteiras", async () => {
    const m = montar();
    m.teste.valor = null;
    const saga = sagaDe(m);
    // Duas passagens em espera.
    await saga.correr(CASO);
    await saga.correr(CASO);
    assert.equal(m.armazem.tentativaDe("teste_ponta_a_ponta"), 0);

    // Agora o teste corre e dá vermelho: falha a sério.
    m.teste.valor = false;
    const desfecho = await saga.correr(CASO);

    assert.equal(desfecho.estado, "escalada");
    assert.equal(
      m.armazem.tentativaDe("teste_ponta_a_ponta"),
      3,
      "as esperas anteriores gastaram tentativas ao passo",
    );
  });

  it("o passo 8 com o teste por correr aguarda; com o teste vermelho, falha", async () => {
    m.teste.valor = null;
    const saga = sagaDe(m);
    const aguarda = await saga.correr(CASO);
    assert.equal(aguarda.estado, "aguarda");
    assert.equal(m.armazem.esperaDe("teste_ponta_a_ponta"), "aguarda_teste");

    // **`false` é falha e gasta tentativa**, ao contrário de `null`. Tratar as
    // duas como espera deixava um caso pendurado para sempre sem ninguém saber
    // porquê.
    const outra = montar();
    outra.teste.valor = false;
    const desfecho = await sagaDe(outra).correr(CASO);
    assert.equal(desfecho.estado, "escalada");
    assert.equal(outra.armazem.erroDe("teste_ponta_a_ponta"), "teste_ponta_a_ponta_falhou");
  });
});

describe("o `error_code` nao leva segredos", () => {
  /**
   * A DoD deste ticket diz «nada de chaves em logs, *traces* ou
   * `provisioning_step`». O esboço do `docs/tecnica/10` §5.2 escrevia
   * `markFailed(row.id, String(e))`, e o `String(e)` de um erro de terceiros
   * traz o corpo da resposta — que da Platform API do Chatwoot ou do LiteLLM
   * pode trazer a chave. É por isso que o `codigoDoErro` existe.
   */
  it("um erro com corpo de resposta nao chega ao `error_code`", () => {
    const erro = new Error('{"error":"invalid key sk-abcdef0123456789"}');
    assert.equal(codigoDoErro(erro), "erro_opaco");
  });

  it("uma classe de erro passa, porque e um nome e nao um corpo", () => {
    class ProvedorIndisponivelError extends Error {
      override name = "ProvedorIndisponivelError";
    }
    assert.equal(codigoDoErro(new ProvedorIndisponivelError("sk-segredo")), "ProvedorIndisponivelError");
  });

  it("um identificador curto em `snake_case` passa, que e a forma dos nossos `throw`", () => {
    assert.equal(codigoDoErro(new Error("teste_ponta_a_ponta_falhou")), "teste_ponta_a_ponta_falhou");
  });

  /**
   * **Um `name` que levanta não pode fazer o `codigoDoErro` levantar.**
   *
   * O `name` pode ser um *getter* — um erro reempacotado por um SDK, ou atrás
   * de um `Proxy`. Com a leitura nua, a função levantava **dentro do `catch`**
   * do `#correrPasso`, antes do `marcarFalhado`: o passo ficava `em_curso` com
   * o `attempt` já incrementado e **sem estado terminal**, a excepção subia, e
   * o consumidor repetia o *job* — a única saída do tecto de três tentativas
   * que o critério 5 fecha. Foi a revisão adversarial que o mediu.
   */
  it("um `name` que levanta nao faz o `codigoDoErro` levantar", () => {
    const erro = new Error("x");
    Object.defineProperty(erro, "name", {
      get() {
        throw new TypeError("sem nome");
      },
    });
    assert.equal(codigoDoErro(erro), "erro_opaco");
  });

  it("e a saga nao perde o estado terminal com um erro desses", async () => {
    const m = montar();
    m.handoff.ensureAccount = async () => {
      const erro = new Error("x");
      Object.defineProperty(erro, "name", {
        get() {
          throw new TypeError("sem nome");
        },
      });
      throw erro;
    };
    const desfecho = await sagaDe(m).correr(CASO);
    assert.equal(desfecho.estado, "escalada", "a excepcao escapou e a saga nao escalou");
    assert.equal(m.armazem.estadoDe("conta_atendimento"), "escalado");
  });

  /** O mesmo para a mensagem: um `message` que levanta também não derruba nada. */
  it("uma `message` que levanta tambem nao derruba o `codigoDoErro`", () => {
    const erro = new Error("x");
    Object.defineProperty(erro, "name", { value: "um nome com espacos" });
    Object.defineProperty(erro, "message", {
      get() {
        throw new TypeError("sem mensagem");
      },
    });
    assert.equal(codigoDoErro(erro), "erro_opaco");
  });

  it("o que nao e `Error` nao vira texto", () => {
    assert.equal(codigoDoErro({ chave: "sk-abcdef" }), "erro_nao_error");
    assert.equal(codigoDoErro("sk-abcdef0123456789"), "erro_nao_error");
  });

  it("o `error_code` gravado por uma falha de terceiros e opaco", async () => {
    const m = montar();
    m.handoff.ensureAccount = async () => {
      throw new Error('{"error":"invalid key sk-abcdef0123456789"}');
    };
    await sagaDe(m).correr(CASO);
    const codigo = m.armazem.erroDe("conta_atendimento");
    assert.equal(codigo, "erro_opaco");
    assert.ok(!String(codigo).includes("sk-"), "o `error_code` levou a chave");
  });
});

describe("as chaves naturais sao as do criterio 2", () => {
  /**
   * **As oito chaves do critério 2, afirmadas uma a uma.**
   *
   * O `chaveDe` de cada passo existia com a nota «só para registo e ensaio» e
   * **não era usado por nenhum dos dois** — oito *closures* a declarar as
   * chaves sem nada a verificá-las, como a revisão adversarial notou. Esta
   * tabela é o ensaio que faltava: é ela que torna o critério 2 («passos e
   * chaves») uma afirmação medida em vez de um comentário.
   */
  it("cada passo declara a chave natural que o criterio 2 lhe da", () => {
    const m = montar();
    const passos = montarPassos(m.dependencias as never);
    const esperadas: Readonly<Record<string, string>> = {
      tenant_e_caso: CASO.onboardingId,
      chave_llm: `tenant-${TENANT}`,
      canal_comercio: TENANT,
      conta_atendimento: TENANT,
      entitlements: `${TENANT}:modulo`,
      espera_es: TENANT,
      inbox_e_rota: TENANT,
      teste_ponta_a_ponta: CASO.onboardingId,
    };
    for (const nome of PASSOS) {
      const passo = passos.get(nome);
      assert.ok(passo !== undefined, `${nome} sem definicao`);
      assert.equal(passo.chaveDe(CASO), esperadas[nome], `a chave de ${nome}`);
    }
  });

  it("a chave da chave virtual e o alias `tenant-<uuid>`", async () => {
    const m = montar();
    await sagaDe(m).correr(CASO);
    // O `external_id` que ficou é o que o inventário emitiu para o alias; a
    // chave de procura é o alias, e é por isso que a segunda passagem o encontra.
    assert.equal(m.chaveDeLlm.inventario.quantos, 1);
    const consulta = m.sql.consultas.find((c) => c.texto.includes("litellm_key_id"));
    assert.ok(consulta !== undefined, "nao guardou o `litellm_key_id`");
    assert.deepEqual(consulta.valores, [TENANT, "tenant-" + TENANT + "-1"]);
  });

  /**
   * A rota vai pela porta `RotaDoCanal` e **não** por consulta deste módulo.
   *
   * Este ensaio afirmava sobre o texto de um `INSERT` em
   * `platform.tenant_channels` que a revisão adversarial mostrou estar errado de
   * três formas contra a revisão `0001` — `channel_mode` e `token_ref` são
   * `NOT NULL` sem DEFAULT e estavam omitidas, e o `estado` era `'onboarding'`,
   * que não está no `tenant_channels_estado_ck`. O duplo da base só registra o
   * texto, pelo que a consulta nunca era executada e nada o apanhava.
   */
  it("a rota do CHR vai pela porta, com os quatro campos que ela exige", async () => {
    const m = montar();
    await sagaDe(m).correr(CASO);
    assert.deepEqual(m.rota.garantidas, [
      { tenantId: TENANT, phoneNumberId: NUMERO, wabaId: WABA, vertical: CASO.vertical },
    ]);
    assert.deepEqual(
      m.sql.consultas.filter((c) => c.texto.includes("tenant_channels")),
      [],
      "a saga voltou a escrever `tenant_channels` por consulta propria",
    );
  });

  /**
   * **O `wabaId` nunca chega vazio à rota**, e é o segundo defeito que a revisão
   * apanhou: `tenant_channels.waba_id` é `NOT NULL`, e o passo 7 verificava só o
   * número. Com o passo 6 já `concluido` e o WABA entretanto ilegível, a rota
   * recebia um nulo.
   */
  /**
   * **O cenário tem de ser o do defeito, e a primeira versão deste ensaio não
   * era.** Punha `waba = null` desde o início — e aí a saga pára no **passo 6**,
   * que também verifica o WABA, pelo que o passo 7 nunca corria: a asserção
   * «não gravou rota» passava por não ter chegado lá. Um ensaio de mutação
   * mostrou-o: tirar a verificação do passo 7 deixava-o verde.
   *
   * O cenário real é o do achado: o passo 6 **já está `concluido`** de uma
   * passagem anterior e o WABA deixa de se ler **depois** disso. Para o montar,
   * a primeira passagem deixa o passo 7 em `falhado` (duas falhas, não três — à
   * terceira escalava e ficava terminal), e só então o WABA desaparece.
   */
  /**
   * **A guarda mede-se no passo, não pela saga.** A primeira versão deste
   * ensaio punha `waba = null` e corria a saga inteira — mas aí ela pára no
   * **passo 6**, que também verifica o WABA, pelo que o passo 7 nunca corria e
   * a asserção «não gravou rota» passava por não ter chegado lá. Um ensaio de
   * mutação mostrou-o: tirar a verificação ao passo 7 deixava-o verde.
   *
   * Pela saga, o cenário precisa de o WABA mudar **entre** o passo 6 e o 7, que
   * é um facto do mundo exterior e não um estado que a saga saiba produzir. A
   * granularidade certa de uma guarda é a função que a tem: chama-se o `ensure`
   * do passo 7 directamente, com o WABA nulo.
   */
  it("o `ensure` do passo 7 aguarda quando o WABA nao se le", async () => {
    const m = montar();
    m.canalDoCliente.waba = null;
    const passo = montarPassos(m.dependencias as never).get("inbox_e_rota");
    assert.ok(passo !== undefined);

    await assert.rejects(() => passo.ensure(CASO), AguardaEntradaError);
    assert.deepEqual(m.rota.garantidas, [], "gravou uma rota com `waba_id` nulo");
  });

  it("e com o WABA legivel o mesmo `ensure` grava a rota — o caminho legitimo", async () => {
    const m = montar();
    const passo = montarPassos(m.dependencias as never).get("inbox_e_rota");
    assert.ok(passo !== undefined);

    await passo.ensure(CASO);
    assert.deepEqual(m.rota.garantidas, [
      { tenantId: TENANT, phoneNumberId: NUMERO, wabaId: WABA, vertical: CASO.vertical },
    ]);
  });

  it("o `ensure` do passo 7 aguarda quando o numero nao se le", async () => {
    const m = montar();
    m.canalDoCliente.numero = null;
    const passo = montarPassos(m.dependencias as never).get("inbox_e_rota");
    assert.ok(passo !== undefined);
    await assert.rejects(() => passo.ensure(CASO), AguardaEntradaError);
  });

  it("e com o WABA legivel o passo 7 grava a rota — o caminho legitimo ao lado", async () => {
    const m = montar();
    assert.equal((await sagaDe(m).correr(CASO)).estado, "concluida");
    assert.equal(m.rota.garantidas.length, 1);
    assert.equal(m.rota.garantidas[0]?.wabaId, WABA);
  });

  it("o `tenant_id` do passo 1 e o pre-alocado, e o `nome` e o do negocio", async () => {
    const m = montar();
    await sagaDe(m).correr(CASO);
    const tenant = m.sql.consultas.find((c) => c.texto.includes("platform.tenants"));
    assert.ok(tenant !== undefined);
    assert.equal(tenant.valores[0], TENANT);
    // **O nome do negócio, não a vertical.** A primeira versão passava
    // `caso.vertical` e o tenant ficava chamado «vendedor» — passava o CHECK
    // `btrim(nome) <> ''` e nada acusava.
    assert.equal(tenant.valores[1], CASO.nomeDoNegocio);
    assert.notEqual(tenant.valores[1], CASO.vertical);
  });
});

describe("as escritas correm sob `app.tenant_id` e exigem linha", () => {
  /**
   * **O modo de falha mais perigoso do ticket**, e era real: a base tem RLS
   * `FORCE` nas tabelas com `tenant_id` e nenhuma consulta deste módulo punha
   * o contexto, nem olhava para o resultado. Sem contexto, um `UPDATE` afecta
   * zero linhas e **não levanta** — a saga marcava o passo `concluido` sobre
   * uma base que não foi escrita. Encontrado pela revisão adversarial.
   */
  it("cada escrita vem precedida de `set_config('app.tenant_id')` na mesma transaccao", async () => {
    const m = montar();
    await sagaDe(m).correr(CASO);

    const seq = m.sql.consultas.map((c) => c.texto.trim());
    const escritas = seq
      .map((texto, i) => ({ texto, i }))
      .filter(
        ({ texto }) =>
          !["BEGIN", "COMMIT", "ROLLBACK"].includes(texto) &&
          !texto.includes("set_config('app.tenant_id'"),
      );
    assert.equal(escritas.length, 4, "esperava quatro escritas (passos 1, 2, 3 e 4)");
    for (const { i } of escritas) {
      // Imediatamente antes: o `set_config`; e antes dele, o `BEGIN`.
      assert.ok(
        seq[i - 1]?.includes("set_config('app.tenant_id'"),
        `a escrita ${i} nao corre sob contexto de tenant`,
      );
      assert.equal(seq[i - 2], "BEGIN", `a escrita ${i} nao esta numa transaccao`);
    }
  });

  it("o contexto que se define e o `tenant_id` do caso", async () => {
    const m = montar();
    await sagaDe(m).correr(CASO);
    const contextos = m.sql.consultas
      .filter((c) => c.texto.includes("set_config('app.tenant_id'"))
      .map((c) => c.valores[0]);
    assert.ok(contextos.length >= 4);
    assert.deepEqual([...new Set(contextos)], [TENANT]);
  });

  /**
   * **Zero linhas é um erro, não um `concluido`.** É a asserção que distingue
   * «escreveu» de «declarou que escreveu».
   */
  it("sem contexto honrado, a escrita nao da linha e o passo NAO fica `concluido`", async () => {
    const m = montar();
    m.sql.honraOContexto = false;
    const desfecho = await sagaDe(m).correr(CASO);

    assert.equal(desfecho.estado, "escalada");
    assert.equal(desfecho.passo, "tenant_e_caso");
    assert.notEqual(m.armazem.estadoDe("tenant_e_caso"), "concluido");
    assert.equal(m.armazem.erroDe("tenant_e_caso"), "EscritaSemLinhasError");
  });

  it("e com o contexto honrado os oito passos concluem — o caminho legitimo", async () => {
    const m = montar();
    assert.equal((await sagaDe(m).correr(CASO)).estado, "concluida");
  });
});

describe("o `Logger` em modo estrito aceita as linhas da saga", () => {
  /**
   * Nenhum ensaio injectava um `Logger`, pelo que o `log?.excepcao` era um
   * *no-op* e a metade «logs» da DoD não tinha medição executada. Pior: em modo
   * estrito — que é o do CI — um campo fora da lista branca ou um valor fora de
   * forma **levanta**, e a chamada está dentro do `catch` do `#correrPasso`,
   * **depois** do `marcarEscalado`: uma rejeição fazia a excepção escapar e a
   * escalada deixava de devolver `{estado: "escalada"}`.
   */
  it("a escalada escreve uma linha aceite, e devolve `escalada`", async () => {
    const m = montar();
    m.handoff.ensureAccount = async () => {
      throw new Error("chatwoot_indisponivel");
    };
    const desfecho = await sagaDe(m).correr(CASO);

    assert.equal(desfecho.estado, "escalada", "o logger estrito fez a escalada levantar");
    const linha = m.linhasDeLog.find((l) => String(l.outcome).startsWith("saga_escalada"));
    assert.ok(linha !== undefined, "a escalada nao escreveu linha nenhuma");
    assert.equal(linha.outcome, "saga_escalada_conta_atendimento");
    assert.equal(linha.tenant_id, TENANT);
    // O *logger* acrescenta a classe ao codigo: `<codigo>:<Classe>`. O que a
    // **coluna** guarda e so o codigo, e e esse que o ensaio abaixo mede.
    assert.equal(linha.error_code, "chatwoot_indisponivel:Error");
    assert.equal(m.armazem.erroDe("conta_atendimento"), "chatwoot_indisponivel");
  });

  /**
   * **E com um erro cujo `name` é hostil, a linha continua a ser aceite e a
   * escalada continua a devolver `escalada`.** É a conjunção dos dois achados: o
   * `error_code` passa a ser `erro_opaco` e o modo estrito não levanta.
   */
  it("um erro com `name` hostil nao rebenta o logger estrito nem vaza", async () => {
    const m = montar();
    m.handoff.ensureAccount = async () => {
      const e = new Error("x");
      e.name = "VALOR-HOSTIL-DE-ENSAIO-NAO-E-SEGREDO";
      throw e;
    };
    const desfecho = await sagaDe(m).correr(CASO);

    assert.equal(desfecho.estado, "escalada");
    assert.equal(m.armazem.erroDe("conta_atendimento"), "erro_opaco");
    const linha = m.linhasDeLog.find((l) => String(l.outcome).startsWith("saga_escalada"));
    assert.equal(linha?.error_code, "erro_opaco:Error");
    const tudo = JSON.stringify(m.linhasDeLog);
    assert.ok(
      !tudo.includes("VALOR-HOSTIL"),
      "o valor hostil do `name` chegou a uma linha de log",
    );
  });

  it("a compensacao que falha escreve uma linha aceite e devolve o que executou", async () => {
    const m = montar();
    const saga = sagaDe(m);
    await saga.correr(CASO);
    m.chaveDeLlm.revogar = async () => {
      throw new Error("litellm_indisponivel");
    };
    const executadas = await saga.compensar(CASO, "ensaio");

    const linha = m.linhasDeLog.find((l) => l.outcome === "compensacao_falhou");
    assert.ok(linha !== undefined, "a compensacao falhada nao escreveu linha");
    assert.ok(
      String(linha.error_code).startsWith("compensacao_falhou_chave_llm"),
      `error_code inesperado: ${String(linha.error_code)}`,
    );
    // O que já tinha corrido antes da falha não se perde.
    assert.ok(executadas.length > 0);
  });
});

describe("a metrica da primeira tentativa", () => {
  it("conta `sim` quando os oito passam a primeira", async () => {
    const m = montar();
    const saga = sagaDe(m);
    await saga.correr(CASO);
    assert.equal(saga.metricas.valor('saga_first_attempt_total{passou="sim"}'), 1);
    assert.equal(saga.metricas.valor('saga_first_attempt_total{passou="nao"}'), -1);
  });

  it("conta `nao` quando um passo precisou de segunda tentativa", async () => {
    const m = montar();
    let chamadas = 0;
    const real = m.handoff.ensureAccount.bind(m.handoff);
    m.handoff.ensureAccount = async () => {
      chamadas += 1;
      if (chamadas === 1) throw new Error("chatwoot_indisponivel");
      return real();
    };
    const saga = sagaDe(m);
    await saga.correr(CASO);
    assert.equal(saga.metricas.valor('saga_first_attempt_total{passou="nao"}'), 1);
    assert.equal(saga.metricas.valor('saga_first_attempt_total{passou="sim"}'), -1);
  });

  /**
   * **A duração por passo, que o critério 9 pede por palavras.**
   *
   * A série existia no `metricas.ts` e **ninguém a escrevia**: o
   * `Metricas.medir` não era chamado em sítio nenhum, e a `exposicao()` de uma
   * saga completa não tinha linha nenhuma de `saga_step_duration_ms`. O
   * critério estava satisfeito pelo nome da série e por mais nada — foi a
   * revisão adversarial que o apanhou.
   *
   * O relógio do duplo avança 7 ms por leitura, pelo que a duração medida é
   * determinística e distinguível de zero: «mediu zero» e «não mediu» são
   * coisas diferentes, e é a razão de o `valor()` devolver `-1` para o que
   * nunca foi escrito.
   */
  it("mede a duracao de cada um dos oito passos", async () => {
    const m = montar();
    const saga = sagaDe(m);
    await saga.correr(CASO);

    for (const passo of PASSOS) {
      const valor = saga.metricas.valor(`saga_step_duration_ms{step="${passo}"}`);
      assert.notEqual(valor, -1, `a duracao do passo ${passo} nao foi medida`);
      assert.ok(valor > 0, `a duracao do passo ${passo} e ${valor}`);
    }
    assert.ok(
      saga.metricas.exposicao().includes("saga_step_duration_ms{step=\"chave_llm\"}"),
      "a serie nao sai na exposicao do Prometheus",
    );
  });

  it("nenhuma metrica aceita uma etiqueta de tenant", async () => {
    const m = montar();
    const saga = sagaDe(m);
    assert.throws(
      () => saga.metricas.contar("saga_step_failures_total", TENANT),
      /nao e um valor de step/,
    );
  });
});
