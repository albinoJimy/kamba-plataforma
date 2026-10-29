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
} from "../src/pagamentos/index.ts";
import { capturar } from "./apoio/capturar.ts";

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
      const incoerente = adaptador("hibrido", {
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

  it("recusa os dois com NOT_SUPPORTED, sem chamar o adaptador", () => {
    for (const metodo of ["refund", "payout"] as const) {
      const erro = capturar<ProviderError>(() => registo.chamar("fake", metodo));
      assert.equal(erro.codigo, "NOT_SUPPORTED");
    }
  });

  it("e recusa-os mesmo que um adaptador declare a capacidade", () => {
    const atrevido = new RegistoDeProviders(SEMPRE_VERDE);
    atrevido.activar(adaptador("atrevido", { refund: true, payout: true }));
    for (const metodo of ["refund", "payout"] as const) {
      const erro = capturar<ProviderError>(() => atrevido.chamar("atrevido", metodo));
      assert.equal(erro.codigo, "NOT_SUPPORTED");
    }
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

  it("e reconhece-o quando existir", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("psp", { pspLicenciado: true }));
    assert.equal(registo.temPspLicenciado, true);
  });
});
