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
 *    **embaralhadas** pelo armazém — ver a nota do `passosConcluidos`.
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
  BACKOFF_BASE_MS,
  PASSOS,
  Saga,
  TENTATIVAS,
  atrasoDaTentativa,
  codigoDoErro,
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
    // **Zero**: o `marcarEspera` repõe o `attempt`. Se ficasse, três noites com
    // o dono por agir escalavam o caso para operações.
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

  it("a rota do CHR chaveia pelo `phone_number_id`", async () => {
    const m = montar();
    await sagaDe(m).correr(CASO);
    const rota = m.sql.consultas.find((c) => c.texto.includes("tenant_channels"));
    assert.ok(rota !== undefined, "nao gravou a rota");
    assert.deepEqual(rota.valores, [TENANT, NUMERO, WABA, CASO.vertical]);
    assert.ok(
      rota.texto.includes("ON CONFLICT (phone_number_id)"),
      "o `ON CONFLICT` da rota nao e pelo `phone_number_id` sozinho",
    );
  });

  it("o `tenant_id` do passo 1 e o pre-alocado, e nao um gerado", async () => {
    const m = montar();
    await sagaDe(m).correr(CASO);
    const tenant = m.sql.consultas.find((c) => c.texto.includes("platform.tenants"));
    assert.ok(tenant !== undefined);
    assert.equal(tenant.valores[0], TENANT);
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

  it("nenhuma metrica aceita uma etiqueta de tenant", async () => {
    const m = montar();
    const saga = sagaDe(m);
    assert.throws(
      () => saga.metricas.contar("saga_step_failures_total", TENANT),
      /nao e um valor de step/,
    );
  });
});
