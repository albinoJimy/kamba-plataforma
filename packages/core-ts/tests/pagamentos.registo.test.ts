/**
 * O registo: as duas recusas do §3.1 e a regra de activacao (KAM-052,
 * criterios 2 e 3).
 *
 * O que esta bateria prova:
 *
 *     criterio 2   `ADAPTER_CANNOT_CONFIRM` para quem nao confirma, a dispensa
 *                  do `humanOnly`, e a recusa de chamar capacidade nao declarada
 *     criterio 3   `refund` e `payout` dao `NOT_SUPPORTED` em **qualquer**
 *                  adaptador, e o registo recusa-os antes de o chamar
 *
 * A metade do criterio 3 que e de **arranque** — `payouts_enabled=true` sem
 * `psp_licenciado` — esta no `pagamentos.arranque.test.ts`, com a G-4.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ADAPTER_CANNOT_CONFIRM,
  AdapterCannotConfirm,
  ETIQUETA_NAO_RECONHECIDA,
  EtiquetaNaoReconhecida,
  POLITICA_DE_PRODUCAO,
  CAPACIDADES_DO_FAKE,
  CONFORMANCE_REQUIRED,
  CONFORMIDADE_VAZIA,
  ConformanceRequired,
  HumanOnlyIncoerente,
  type Conformidade,
  type PaymentProvider,
  type ProviderCapabilities,
  ProviderError,
  RegistoDeProviders,
  activar,
  podeConfirmar,
  suporta,
} from "../src/pagamentos/index.ts";
import { capturar, capturarAsync } from "./apoio/capturar.ts";

/** Diz sempre que sim: isola a regra de activacao da suite de conformidade. */
const SEMPRE_VERDE: Conformidade = { green: () => true };

/** Um adaptador de papel: so as capacidades importam nestes ensaios. */
function adaptador(id: string, capacidades: Partial<ProviderCapabilities> = {}): PaymentProvider {
  const caps: ProviderCapabilities = { ...CAPACIDADES_DO_FAKE, ...capacidades };
  return {
    id,
    capabilities: caps,
    createCharge: async () => ({ kind: "manual", instrucoes: "" }),
    status: async () => ({ estado: "desconhecida" }),
    refund: async () => ({ ok: false, erro: "NOT_SUPPORTED" }),
    payout: async () => ({ ok: false, erro: "NOT_SUPPORTED" }),
    verifyCallback: async () => [],
    listUnacknowledged: async () => ({ eventos: [] }),
    acknowledge: async () => {},
    cancelCharge: async () => {},
  };
}

describe("pagamentos/registo: quem consegue confirmar", () => {
  it("confirma quem tem HMAC, ou consulta de estado, ou os dois", () => {
    assert.equal(podeConfirmar({ ...CAPACIDADES_DO_FAKE }), true);
    assert.equal(
      podeConfirmar({ ...CAPACIDADES_DO_FAKE, callbackAuth: "none", statusQuery: true }),
      true,
    );
    assert.equal(
      podeConfirmar({ ...CAPACIDADES_DO_FAKE, callbackAuth: "hmac", statusQuery: false }),
      true,
    );
  });

  it("nao confirma quem nao tem nenhuma das duas vias", () => {
    assert.equal(
      podeConfirmar({ ...CAPACIDADES_DO_FAKE, callbackAuth: "none", statusQuery: false }),
      false,
    );
  });
});

describe("pagamentos/registo: criterio 2 — ADAPTER_CANNOT_CONFIRM", () => {
  it("recusa `none` sem consulta de estado — o EMIS directo do §3.4", () => {
    const emis = adaptador("emis_gpo", { callbackAuth: "none", statusQuery: false });
    const erro = capturar<AdapterCannotConfirm>(() => activar(emis, SEMPRE_VERDE));
    assert.equal(erro.codigo, ADAPTER_CANNOT_CONFIRM);
    assert.equal(erro.adaptador, "emis_gpo");
  });

  /**
   * **O caso que separa a leitura do criterio 2 da dos Detalhes Tecnicos.**
   *
   * O AppyPay v2 esta em `NAO VERIFICADO (assinatura)` na matriz do §3.2, com as
   * perguntas 11–15 de `evidencia/E2` §9 por responder. Pela letra do criterio 2
   * — «`callbackAuth='none'` e `statusQuery=false`» — ele **activava-se**, porque
   * `desconhecido` nao e `none`. Pela regra dos Detalhes Tecnicos — a que esta
   * implementada — e recusado.
   *
   * Divida documental 151.
   */
  it("recusa `desconhecido` sem consulta — o AppyPay por responder do §3.4", () => {
    const appypay = adaptador("appypay", { callbackAuth: "desconhecido", statusQuery: false });
    assert.throws(() => activar(appypay, SEMPRE_VERDE), AdapterCannotConfirm);
  });

  it("aceita `desconhecido` **com** consulta de estado: a consulta e via de confirmacao", () => {
    const comConsulta = adaptador("opg", { callbackAuth: "desconhecido", statusQuery: true });
    assert.doesNotThrow(() => activar(comConsulta, SEMPRE_VERDE));
  });

  /**
   * **A dispensa nao se auto-atribui**, e foi uma revisao adversarial a mostrar
   * o caminho: qualquer adaptador com `humanOnly: true`, `callbackAuth: none` e
   * `statusQuery: false` saltava a ADAPTER_CANNOT_CONFIRM e era activado — isto
   * e, a guarda do ADR-013 desligava-se com uma linha nas capacidades do
   * adaptador que ela devia medir.
   */
  it("recusa um humanOnly que a politica nao reconhece", () => {
    const impostor = adaptador("impostor", {
      callbackAuth: "none",
      statusQuery: false,
      reconciliationQueue: false,
      humanOnly: true,
    });
    const erro = capturar<EtiquetaNaoReconhecida>(() => activar(impostor, SEMPRE_VERDE));
    assert.equal(erro.codigo, ETIQUETA_NAO_RECONHECIDA);
  });

  it("e recusa um pspLicenciado que a politica nao reconhece", () => {
    const impostor = adaptador("impostor2", { pspLicenciado: true });
    const erro = capturar<EtiquetaNaoReconhecida>(() => activar(impostor, SEMPRE_VERDE));
    assert.equal(erro.codigo, ETIQUETA_NAO_RECONHECIDA);
  });

  /** A G-2 na **declaracao** e nao so na chamada (§10.4: `payout=false`). */
  it("recusa activar um adaptador que declare saber reembolsar ou pagar", () => {
    for (const extra of [{ refund: true }, { payout: true }]) {
      assert.throws(
        () => activar(adaptador("mentiroso", extra), SEMPRE_VERDE),
        EtiquetaNaoReconhecida,
      );
    }
  });

  it("dispensa o humanOnly — o ManualProvider do §4", () => {
    const manual = adaptador("manual", {
      callbackAuth: "none",
      statusQuery: false,
      reconciliationQueue: false,
      humanOnly: true,
      metodos: ["manual", "cod"],
    });
    assert.doesNotThrow(() => activar(manual, SEMPRE_VERDE));
  });

  /**
   * A dispensa do `humanOnly` **nao e generica**, e e o acrescento deste modulo
   * a regra do bloco. Ver a nota em `registo.ts`.
   */
  it("recusa um humanOnly que tambem declare via automatica", () => {
    for (const extra of [
      { callbackAuth: "hmac" as const },
      { statusQuery: true },
      { reconciliationQueue: true },
    ]) {
      // **O id tem de ser um que a politica reconheca**, senao a recusa vem
      // antes, por ETIQUETA_NAO_RECONHECIDA — e seria outra propriedade.
      const incoerente = adaptador("manual", {
        callbackAuth: "none",
        statusQuery: false,
        reconciliationQueue: false,
        humanOnly: true,
        ...extra,
      });
      assert.throws(() => activar(incoerente, SEMPRE_VERDE), HumanOnlyIncoerente);
    }
  });
});

describe("pagamentos/registo: §3.5 — sem suite verde nao se activa", () => {
  it("recusa por omissao, porque a conformidade vazia diz nao a todos", () => {
    const erro = capturar<ConformanceRequired>(() => activar(adaptador("proxypay"), CONFORMIDADE_VAZIA));
    assert.equal(erro.codigo, CONFORMANCE_REQUIRED);
  });

  it("a ordem das recusas: quem nao confirma e recusado antes de se perguntar pela suite", () => {
    const emis = adaptador("emis_gpo", { callbackAuth: "none", statusQuery: false });
    assert.throws(() => activar(emis, CONFORMIDADE_VAZIA), AdapterCannotConfirm);
  });
});

describe("pagamentos/registo: criterio 3 — refund e payout", () => {
  const registo = new RegistoDeProviders(SEMPRE_VERDE);
  registo.activar(adaptador("fake"));

  /**
   * **Devolvem, e nao lancam.** O criterio 3 escreve «refund e payout de
   * qualquer adaptador **devolvem** NOT_SUPPORTED» e o §3.1 tipa o retorno. A
   * primeira versao lancava, e uma revisao adversarial apanhou a divergencia:
   * quem escrevesse `await registo.chamar(id, "refund")(req)` apanhava uma
   * excepcao onde o tipo promete um valor, e o `RefundResult` ficava
   * inalcancavel pelo caminho que o proprio modulo recomenda.
   */
  it("devolvem NOT_SUPPORTED, sem chamar o adaptador", async () => {
    const reembolsar = registo.chamar("fake", "refund");
    assert.deepEqual(await reembolsar({ chargeId: "c", amount: 1n }), {
      ok: false,
      erro: "NOT_SUPPORTED",
    });
    const pagar = registo.chamar("fake", "payout");
    assert.deepEqual(
      await pagar({ tenantId: "t", accountId: "a", amount: 1n, currency: "AOA" }),
      { ok: false, erro: "NOT_SUPPORTED" },
    );
  });
});

describe("pagamentos/registo: criterio 2 — capacidade nao declarada", () => {
  it("recusa `status` a quem nao declara statusQuery", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("so_hmac", { statusQuery: false }));
    const erro = capturar<ProviderError>(() => registo.chamar("so_hmac", "status"));
    assert.equal(erro.codigo, "NOT_SUPPORTED");
  });

  it("recusa a fila de reconciliacao a quem nao a declara", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("sem_fila", { reconciliationQueue: false }));
    for (const metodo of ["listUnacknowledged", "acknowledge"] as const) {
      const erro = capturar<ProviderError>(() => registo.chamar("sem_fila", metodo));
      assert.equal(erro.codigo, "NOT_SUPPORTED");
    }
  });

  it("permite o que esta declarado", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("completo"));
    for (const metodo of ["status", "listUnacknowledged", "acknowledge", "verifyCallback"] as const) {
      assert.equal(typeof registo.chamar("completo", metodo), "function");
    }
  });

  /**
   * «Declarou e nao tem» e um defeito do adaptador, nao uma capacidade nao
   * declarada — e por isso e `VALIDATION` e nao `NOT_SUPPORTED`. A diferenca
   * diz a quem depura se ha um desenho ou um bug.
   */
  it("distingue «nao declarou» de «declarou e nao implementou»", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    const mentiroso = adaptador("mentiroso", { reconciliationQueue: true });
    delete (mentiroso as { listUnacknowledged?: unknown }).listUnacknowledged;
    registo.activar(mentiroso);
    const erro = capturar<ProviderError>(() => registo.chamar("mentiroso", "listUnacknowledged"));
    assert.equal(erro.codigo, "VALIDATION");
  });

  it("recusa um adaptador desconhecido", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    const erro = capturar<ProviderError>(() => registo.chamar("nao_existe", "status"));
    assert.equal(erro.codigo, "VALIDATION");
  });
});

describe("pagamentos/registo: o psp_licenciado", () => {
  it("nenhum adaptador do catalogo o e", () => {
    assert.equal(CAPACIDADES_DO_FAKE.pspLicenciado, false);
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("fake"));
    assert.equal(registo.temPspLicenciado, false);
  });

  /**
   * **Com a politica a reconhece-lo**, que e o que torna a G-2 satisfazivel sem
   * o adaptador se declarar a si proprio licenciado. Em producao a lista esta
   * vazia e so o D8 (parecer) a abre.
   */
  it("e reconhece-o quando a politica o reconhecer", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE, {
      confirmacaoHumana: [],
      licencaBna: ["psp"],
    });
    registo.activar(adaptador("psp", { pspLicenciado: true }));
    assert.equal(registo.temPspLicenciado, true);
  });

  it("e a politica de producao nao reconhece nenhum", () => {
    assert.deepEqual([...POLITICA_DE_PRODUCAO.licencaBna], []);
    assert.deepEqual([...POLITICA_DE_PRODUCAO.confirmacaoHumana], ["manual"]);
  });
});

describe("pagamentos/registo: criterio 2 — o metodo tem de ser declarado", () => {
  /**
   * **O `capabilities.metodos` nao era lido por linha nenhuma de producao.**
   *
   * Medido por uma revisao adversarial: o `FakeProvider` declara
   * `metodos: ["referencia"]` e `createCharge` aceitava os quatro `Metodo`,
   * devolvendo uma referencia Multicaixa a um pedido `metodo: "cod"`. O §3.1
   * abre a enumeracao de `ProviderCapabilities` com «metodos suportados» e fecha
   * com «o PAY recusa usar uma capacidade nao declarada» — era esta a capacidade
   * que faltava, isto e, metade do criterio 2.
   */
  const pedido = (metodo: "referencia" | "express_push" | "manual" | "cod") => ({
    chargeId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    tenantId: "11111111-1111-4111-8111-111111111111",
    accountId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    numeroPublico: "P-0001",
    amount: 102_409n,
    currency: "AOA" as const,
    metodo,
    validUntil: "2026-10-30T12:00:00.000Z",
    customFields: {},
  });

  it("suporta() le a lista declarada", () => {
    const caps = { ...CAPACIDADES_DO_FAKE, metodos: ["referencia"] as const };
    assert.equal(suporta(caps, "referencia"), true);
    for (const metodo of ["express_push", "manual", "cod"] as const) {
      assert.equal(suporta(caps, metodo), false, metodo);
    }
  });

  it("cobrar() aceita o metodo declarado", async () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("so_referencia", { metodos: ["referencia"] }));
    const r = await registo.cobrar("so_referencia", pedido("referencia"));
    assert.equal(r.kind, "manual");
  });

  /**
   * O `cod` e o caso concreto: o ADR-016 tem-no desligado por omissao, e um
   * pedido de pagamento a entrega que receba uma referencia e um cliente a pagar
   * adiantado uma encomenda que pediu para pagar na mao.
   */
  it("cobrar() recusa os tres metodos nao declarados, com NOT_SUPPORTED", async () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("so_referencia", { metodos: ["referencia"] }));
    for (const metodo of ["express_push", "manual", "cod"] as const) {
      const erro = await capturarAsync<ProviderError>(() =>
        registo.cobrar("so_referencia", pedido(metodo)),
      );
      assert.equal(erro.codigo, "NOT_SUPPORTED", metodo);
    }
  });

  it("cobrar() recusa um adaptador desconhecido", async () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    const erro = await capturarAsync<ProviderError>(() =>
      registo.cobrar("nao_existe", pedido("referencia")),
    );
    assert.equal(erro.codigo, "VALIDATION");
  });
});

describe("pagamentos/registo: um opcional sem capacidade associada", () => {
  /**
   * O `cancelCharge` e opcional no §3.1 e **nao tem campo em
   * `ProviderCapabilities`**, pelo que nunca entra no `CAPACIDADE_EXIGIDA`. A
   * primeira versao caia no ramo final e dizia «declara cancelCharge mas nao
   * implementa cancelCharge» — uma frase que afirma que o adaptador declarou o
   * que nao declarou, e que manda quem depura procurar um bug onde ha uma
   * capacidade que o adaptador legitimamente nao tem.
   */
  it("da NOT_SUPPORTED e nao VALIDATION", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    const sem = adaptador("sem_cancelar");
    delete (sem as { cancelCharge?: unknown }).cancelCharge;
    registo.activar(sem);
    const erro = capturar<ProviderError>(() => registo.chamar("sem_cancelar", "cancelCharge"));
    assert.equal(erro.codigo, "NOT_SUPPORTED");
    // E a mensagem **nao** diz que ele declarou o que nao declarou.
    assert.ok(
      !/declara 'cancelCharge'/.test(erro.message),
      `a mensagem contradiz-se: ${erro.message}`,
    );
    assert.match(erro.message, /nao-declaracao/);
  });
});
