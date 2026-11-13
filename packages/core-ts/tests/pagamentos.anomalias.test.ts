/**
 * O motor de anomalias de pagamento (KAM-060).
 *
 * O que esta bateria prova, e o que fica para fora:
 *
 *     aqui           as oito regras caso a caso, **cada uma com um caso que a
 *                    dispara e um que nao** (criterio 1), o determinismo, a
 *                    guarda de PII, a leitura do extracto, a reconciliacao e a
 *                    sua idempotencia, e a composicao com o `ManualProvider`
 *     `services/com` a **ligacao**: o mapeamento de colunas, o contador do
 *                    `/metrics` e a rota que o serve
 *     por fazer      que a escrita **vale**. A `platform.fraud_signals` e
 *                    SELECT-only para os tres papeis (revisao `0032`), pelo que
 *                    nao ha escritor para a suite de base de dados exercitar
 *
 * ## Cada regra mede-se nas duas direccoes, e isso e o criterio 1 a letra
 *
 * «Cada uma tem um caso sintetico que a dispara e um que nao dispara». Uma
 * suite que so medisse disparos ficava verde sobre um motor que dispara sempre
 * — que num motor de fraude e pior do que um que nao dispara nunca, porque
 * ensina ops a ignorar sinais.
 *
 * ## E tres ensaios medem a **ligacao** e nao a funcao
 *
 * E a lição que este repositorio paga mais vezes: uma funcao correcta ligada ao
 * sitio errado passa todos os ensaios dela. Os tres estao marcados com
 * «LIGACAO» no nome e morrem com a composicao desfeita, nao com a funcao
 * estragada:
 *
 *     decidirConfirmacao     sem o `respeitarAccao`, o `avaliarConfirmacao`
 *                            continua perfeito e a retencao desaparece
 *     detectarAnomalias      sem o `contar`, os sinais saem iguais e a metrica
 *                            fica a zero para sempre
 *     sinaisDaReconciliacao  sem a ligacao ao `reconciliar`, a R-08 nao tem de
 *                            onde vir e a lista sai vazia com toda a convicao
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ACCAO_SEM_REGRA_DESTE_TICKET,
  ACCOES,
  ALERTA_DE_CONTAGEM,
  ALERTA_DE_ESCRITA,
  ALERTA_DE_ORFAO,
  ALERTA_DE_SINAL,
  CADEIAS_DAS_ANOMALIAS,
  CADEIAS_DE_ESCRITA,
  CHAVES_PROIBIDAS_NO_DETALHE,
  COLUNAS_DO_EXTRACTO,
  CONFIGURACAO_PROPOSTA,
  ExtractoIlegivel,
  FORCA_DA_ACCAO,
  JANELAS_PROPOSTAS,
  LIMIARES_PROPOSTOS,
  PLANO_DE_CALIBRACAO,
  PREFIXO_DO_AJUSTE,
  REEMBOLSO_POR_ABRIR,
  REGRAS,
  REGRA_POR_ID,
  SEPARADOR_DO_EXTRACTO,
  SEVERIDADE_QUE_ALERTA,
  SQL_ANOMALIAS_AJUSTES_FEITOS,
  SQL_ANOMALIAS_CASA,
  SQL_ANOMALIAS_COBRANCAS,
  SQL_ANOMALIAS_CONFIRMACOES,
  SQL_ANOMALIAS_EVENTOS,
  SQL_ANOMALIAS_RECUSAS,
  SQL_ANOMALIAS_REEMBOLSOS,
  SQL_REGISTAR_SINAL,
  SinalComPii,
  TERMINAIS_SEM_PAGAMENTO,
  VERSAO_DAS_REGRAS,
  accaoEmVigor,
  avaliar,
  avaliarConfirmacao,
  decidirConfirmacao,
  detectarAnomalias,
  digestDoLote,
  lerExtracto,
  reconciliar,
  respeitarAccao,
  semPii,
  sinaisDaReconciliacao,
} from "../src/pagamentos/index.ts";
import type {
  CasoDeReembolsoObservado,
  CobrancaObservada,
  ConfirmacaoObservada,
  EntradaDaConfirmacao,
  EventoObservado,
  Fotografia,
  IdDeRegra,
  Sinal,
} from "../src/pagamentos/index.ts";

const AGORA = "2026-11-08T12:00:00.000Z";
const TENANT = "11111111-1111-4111-8111-111111111111";
const CONTA = "22222222-2222-4222-8222-222222222222";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const DONO = "44444444-4444-4444-8444-444444444444";

/** Minutos antes de `AGORA`, em ISO. Legivel nos casos de janela. */
function haMinutos(minutos: number): string {
  return new Date(Date.parse(AGORA) - minutos * 60_000).toISOString();
}

function cobranca(campos: Partial<CobrancaObservada> = {}): CobrancaObservada {
  return {
    chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
    tenantId: TENANT,
    accountId: CONTA,
    orderId: "bbbbbbbb-0000-4000-8000-000000000001",
    estado: "paga",
    metodo: "manual",
    amountMinor: 100_000n,
    payerHmac: null,
    contactId: CONTACTO,
    referencia: "REF001",
    // Dentro de todas as janelas por omissao, para que quem mede a janela
    // passe um instante proprio e os outros nao paguem por ela.
    criadoEm: haMinutos(10),
    ...campos,
  };
}

function evento(campos: Partial<EventoObservado> = {}): EventoObservado {
  return {
    eventId: 1n,
    tenantId: TENANT,
    chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
    accountId: CONTA,
    tipoEvento: "pagamento_divergente",
    sequencia: 1,
    valorMinor: 100_000n,
    instante: haMinutos(10),
    ...campos,
  };
}

function confirmacao(
  campos: Partial<ConfirmacaoObservada> = {},
): ConfirmacaoObservada {
  return {
    chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
    tenantId: TENANT,
    contactId: CONTACTO,
    decisao: "confirma",
    instante: haMinutos(60),
    ...campos,
  };
}

function foto(campos: Partial<Fotografia> = {}): Fotografia {
  return {
    eventos: [],
    cobrancas: [],
    confirmacoes: [],
    recusas: [],
    casa: [],
    reembolsos: [],
    agora: AGORA,
    ...campos,
  };
}

/** Os sinais de uma regra, pelo `id`. */
function daRegra(sinais: readonly Sinal[], id: IdDeRegra): readonly Sinal[] {
  return sinais.filter((s) => s.regra === REGRA_POR_ID[id].regra);
}

/** Três divergências na mesma conta, dentro da hora. O caso do critério 2. */
function tresDivergencias(): readonly EventoObservado[] {
  return [
    evento({ eventId: 1n, instante: haMinutos(50) }),
    evento({ eventId: 2n, instante: haMinutos(30) }),
    evento({ eventId: 3n, instante: haMinutos(10) }),
  ];
}

describe("as regras como dados versionados (criterio 1)", () => {
  it("as oito regras existem, uma por R-NN, sem buracos", () => {
    const ids = REGRAS.map((r) => r.id);
    assert.deepEqual(ids, [
      "R-01",
      "R-02",
      "R-03",
      "R-04",
      "R-05",
      "R-06",
      "R-07",
      "R-08",
    ]);
  });

  it("cada regra tem limiar, janela e plano de calibracao", () => {
    // **As quatro superficies e nao uma.** Um limiar sem plano de calibracao e
    // uma proposta que ninguem vai calibrar, e e a caixa do DoD («limiares
    // registados como propostas a calibrar, com plano de revisao no Piloto»).
    for (const regra of REGRAS) {
      assert.equal(
        typeof LIMIARES_PROPOSTOS[regra.id],
        "number",
        `a ${regra.id} nao tem limiar`,
      );
      assert.equal(
        typeof JANELAS_PROPOSTAS[regra.id],
        "number",
        `a ${regra.id} nao tem janela`,
      );
      assert.ok(
        (PLANO_DE_CALIBRACAO[regra.id] ?? "").length > 20,
        `a ${regra.id} nao diz como se calibra`,
      );
    }
  });

  it("a accao de cada regra esta no dominio fechado da revisao 0032", () => {
    for (const regra of REGRAS) {
      assert.ok(
        (ACCOES as readonly string[]).includes(regra.accao),
        `a accao '${regra.accao}' da ${regra.id} nao esta no fraud_signals_accao_ck`,
      );
    }
  });

  it("a severidade de cada regra cabe no CHECK (1..5)", () => {
    for (const regra of REGRAS) {
      assert.ok(regra.severidade >= 1 && regra.severidade <= 5, regra.id);
    }
  });

  it("os nomes de regra sao distintos: a coluna e lida por regra", () => {
    const nomes = REGRAS.map((r) => r.regra);
    assert.equal(new Set(nomes).size, nomes.length);
  });

  it("todo o sinal leva a versao das regras no detalhe", () => {
    // Sem ela, um `fraud_signals` de ha tres semanas nao se consegue
    // reinterpretar depois de um limiar mudar.
    const sinais = avaliar(foto({ eventos: tresDivergencias() }));
    assert.equal(sinais[0]?.detalhe["versao"], VERSAO_DAS_REGRAS);
    assert.equal(sinais[0]?.detalhe["regra_id"], "R-01");
  });
});

describe("R-01 — divergencia repetida (criterio 2)", () => {
  it("dispara: tres divergencias na mesma conta em 1 h", () => {
    const sinais = daRegra(avaliar(foto({ eventos: tresDivergencias() })), "R-01");
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.detalhe["ocorrencias"], 3);
  });

  it("a severidade e >= 3, que e o que o criterio 2 escreve a letra", () => {
    const sinais = daRegra(avaliar(foto({ eventos: tresDivergencias() })), "R-01");
    assert.ok((sinais[0]?.severidade ?? 0) >= 3);
  });

  it("nao dispara: duas divergencias, uma abaixo do limiar", () => {
    const eventos = tresDivergencias().slice(0, 2);
    assert.deepEqual(daRegra(avaliar(foto({ eventos })), "R-01"), []);
  });

  it("nao dispara: tres divergencias, uma delas fora da hora", () => {
    // **A janela e que decide, e nao a contagem.** Sem este caso, um limiar de
    // tres ficava verde sobre uma conta com tres divergencias em tres meses.
    const eventos = [
      evento({ eventId: 1n, instante: haMinutos(10) }),
      evento({ eventId: 2n, instante: haMinutos(30) }),
      evento({ eventId: 3n, instante: haMinutos(90) }),
    ];
    assert.deepEqual(daRegra(avaliar(foto({ eventos })), "R-01"), []);
  });

  it("nao dispara: tres divergencias repartidas por duas contas", () => {
    const eventos = [
      evento({ eventId: 1n, accountId: CONTA }),
      evento({ eventId: 2n, accountId: CONTA }),
      evento({ eventId: 3n, accountId: "99999999-9999-4999-8999-999999999999" }),
    ];
    assert.deepEqual(daRegra(avaliar(foto({ eventos })), "R-01"), []);
  });

  it("um sinal por conta e nao um por evento", () => {
    const eventos = [...tresDivergencias(), evento({ eventId: 4n })];
    assert.equal(daRegra(avaliar(foto({ eventos })), "R-01").length, 1);
  });

  it("um instante ilegivel nao conta para a janela", () => {
    const eventos = [
      evento({ eventId: 1n, instante: haMinutos(10) }),
      evento({ eventId: 2n, instante: haMinutos(20) }),
      evento({ eventId: 3n, instante: "ontem a tarde" }),
    ];
    assert.deepEqual(daRegra(avaliar(foto({ eventos })), "R-01"), []);
  });
});

describe("R-02 — HMAC invalido em massa (criterio 2, F-05)", () => {
  const recusas = (quantas: number, minutos = 10) =>
    Array.from({ length: quantas }, () => ({
      accountId: CONTA,
      instante: haMinutos(minutos),
    }));

  it("dispara: dez recusas na mesma conta na hora", () => {
    const sinais = daRegra(
      avaliar(foto({ recusas: recusas(10), cobrancas: [cobranca()] })),
      "R-02",
    );
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.detalhe["recusas"], 10);
  });

  it("nao dispara: nove recusas, uma abaixo do limiar", () => {
    const sinais = daRegra(
      avaliar(foto({ recusas: recusas(9), cobrancas: [cobranca()] })),
      "R-02",
    );
    assert.deepEqual(sinais, []);
  });

  it("nao dispara: dez recusas fora da janela de uma hora", () => {
    const sinais = daRegra(
      avaliar(foto({ recusas: recusas(10, 200), cobrancas: [cobranca()] })),
      "R-02",
    );
    assert.deepEqual(sinais, []);
  });

  it("sem cobranca que atribua a conta a um tenant, nao se escreve sinal", () => {
    // A `payment_inbox` nao tem `tenant_id` — um callback forjado chega antes de
    // se saber de quem e. Inventar um tenant era pior do que nao escrever.
    assert.deepEqual(daRegra(avaliar(foto({ recusas: recusas(10) })), "R-02"), []);
  });
});

describe("R-03 — orfao (criterio 3)", () => {
  it("dispara: um orfao basta, e o sinal e imediato", () => {
    const eventos = [evento({ tipoEvento: "pagamento_orfao" })];
    assert.equal(daRegra(avaliar(foto({ eventos })), "R-03").length, 1);
  });

  it("nao dispara: um evento que nao e orfao", () => {
    const eventos = [evento({ tipoEvento: "pagamento_divergente" })];
    assert.deepEqual(daRegra(avaliar(foto({ eventos })), "R-03"), []);
  });

  it("a idade em horas vai no detalhe, e e o numerador da metrica", () => {
    const eventos = [
      evento({ tipoEvento: "pagamento_orfao", instante: haMinutos(60 * 30) }),
    ];
    const sinal = daRegra(avaliar(foto({ eventos })), "R-03")[0];
    assert.equal(sinal?.detalhe["idade_horas"], 30);
  });

  it("a idade arredonda para baixo: 23,9 h nao sao 24 h", () => {
    const eventos = [
      evento({ tipoEvento: "pagamento_orfao", instante: haMinutos(60 * 24 - 6) }),
    ];
    const sinal = daRegra(avaliar(foto({ eventos })), "R-03")[0];
    assert.equal(sinal?.detalhe["idade_horas"], 23);
  });
});

describe("R-04 — duplicado (criterio 4, G6)", () => {
  it("dispara: um duplicado basta", () => {
    const eventos = [evento({ tipoEvento: "pagamento_duplicado" })];
    const sinais = daRegra(avaliar(foto({ eventos })), "R-04");
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.severidade, 4);
  });

  it("nao dispara: um pagamento que nao e duplicado", () => {
    const eventos = [evento({ tipoEvento: "pagamento_orfao" })];
    assert.deepEqual(daRegra(avaliar(foto({ eventos })), "R-04"), []);
  });

  it("sem caso aberto, o sinal diz que o refund_case esta por abrir", () => {
    // O PAY abre o caso ao consumir o pedido (KAM-197), e isso e assincrono.
    // Um sinal calculado antes nao o pode supor.
    const eventos = [evento({ tipoEvento: "pagamento_duplicado" })];
    const sinal = daRegra(avaliar(foto({ eventos })), "R-04")[0];
    assert.equal(sinal?.detalhe["refund_case"], REEMBOLSO_POR_ABRIR);
  });

  const CASO_A = "cccccccc-0000-4000-8000-00000000000a";
  const CASO_B = "cccccccc-0000-4000-8000-00000000000b";
  const COBRANCA = "aaaaaaaa-0000-4000-8000-000000000001";
  const caso = (casoId: string, campos: Partial<CasoDeReembolsoObservado> = {}) => ({
    casoId,
    tenantId: TENANT,
    chargeId: COBRANCA,
    valorMinor: 100_000n,
    ...campos,
  });

  it("com o caso aberto, o sinal diz qual e (KAM-197)", () => {
    const eventos = [evento({ tipoEvento: "pagamento_duplicado" })];
    const sinal = daRegra(
      avaliar(foto({ eventos, reembolsos: [caso(CASO_A)] })),
      "R-04",
    )[0];
    assert.equal(sinal?.detalhe["refund_case"], CASO_A);
  });

  it("um caso de outra cobranca, de outro valor ou de outro tenant nao conta", () => {
    // Cada campo do casamento com o seu caso: um casamento que ignorasse um
    // deles dava um caso que nao e deste duplicado como se fosse.
    const eventos = [evento({ tipoEvento: "pagamento_duplicado" })];
    for (const [nome, outro] of [
      ["cobranca", caso(CASO_A, { chargeId: "aaaaaaaa-0000-4000-8000-000000000009" })],
      ["valor", caso(CASO_A, { valorMinor: 99_999n })],
      ["tenant", caso(CASO_A, { tenantId: "99999999-9999-4999-8999-999999999999" })],
    ] as const) {
      const sinal = daRegra(
        avaliar(foto({ eventos, reembolsos: [outro] })),
        "R-04",
      )[0];
      assert.equal(sinal?.detalhe["refund_case"], REEMBOLSO_POR_ABRIR, nome);
    }
  });

  it("dois duplicados e um caso: so um deles fica com o caso", () => {
    // **Um caso por duplicado.** Tres pagamentos da mesma cobranca sao dois
    // pedidos de reembolso; dar o mesmo caso aos dois dizia que estavam ambos
    // tratados por um so.
    const eventos = [
      evento({ eventId: 1n, tipoEvento: "pagamento_duplicado" }),
      evento({ eventId: 2n, tipoEvento: "pagamento_duplicado" }),
    ];
    const casos = daRegra(
      avaliar(foto({ eventos, reembolsos: [caso(CASO_A)] })),
      "R-04",
    ).map((s) => s.detalhe["refund_case"]);
    assert.deepEqual([...casos].sort(), [CASO_A, REEMBOLSO_POR_ABRIR].sort());
  });

  it("dois duplicados e dois casos: cada um com o seu, qualquer que seja a ordem", () => {
    // A atribuicao e por ordem total, pelo que inverter as listas da
    // fotografia nao troca os casos entre os sinais (criterio 9).
    const eventos = [
      evento({ eventId: 1n, tipoEvento: "pagamento_duplicado" }),
      evento({ eventId: 2n, tipoEvento: "pagamento_duplicado" }),
    ];
    const reembolsos = [caso(CASO_A), caso(CASO_B)];
    const normal = avaliar(foto({ eventos, reembolsos }));
    const invertida = avaliar(
      foto({ eventos: [...eventos].reverse(), reembolsos: [...reembolsos].reverse() }),
    );
    assert.deepEqual(normal, invertida);
    const porEvento = new Map(
      daRegra(normal, "R-04").map((s) => [s.detalhe["event_id"], s.detalhe["refund_case"]]),
    );
    assert.equal(porEvento.get("1"), CASO_A);
    assert.equal(porEvento.get("2"), CASO_B);
  });
});

describe("R-05 — auto-compra (criterio 5)", () => {
  const HMAC_DO_DONO = "deadbeef";

  it("dispara pelo payer_hmac: o pagador e o dono", () => {
    const sinais = daRegra(
      avaliar(
        foto({
          cobrancas: [cobranca({ payerHmac: HMAC_DO_DONO })],
          casa: [{ contactId: DONO, phoneHmac: HMAC_DO_DONO }],
        }),
      ),
      "R-05",
    );
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.detalhe["via"], "payer_hmac");
    assert.equal(sinais[0]?.accao, "reter_confirmacao");
  });

  it("dispara pelo phone_hmac: o cliente da cobranca e da casa", () => {
    // A segunda metade do criterio 5, que cobre o caminho **manual** — onde nao
    // ha `payer_hmac` nenhum porque nao houve Express.
    const sinais = daRegra(
      avaliar(
        foto({
          cobrancas: [cobranca({ contactId: DONO, payerHmac: null })],
          casa: [{ contactId: DONO, phoneHmac: HMAC_DO_DONO }],
        }),
      ),
      "R-05",
    );
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.detalhe["via"], "phone_hmac");
  });

  it("nao dispara: o HMAC do pagador nao e de ninguem da casa", () => {
    const sinais = daRegra(
      avaliar(
        foto({
          cobrancas: [cobranca({ payerHmac: "0badc0de" })],
          casa: [{ contactId: DONO, phoneHmac: HMAC_DO_DONO }],
        }),
      ),
      "R-05",
    );
    assert.deepEqual(sinais, []);
  });

  it("nao dispara: sem payer_hmac e com o cliente de fora da casa", () => {
    const sinais = daRegra(
      avaliar(
        foto({
          cobrancas: [cobranca({ payerHmac: null })],
          casa: [{ contactId: DONO, phoneHmac: HMAC_DO_DONO }],
        }),
      ),
      "R-05",
    );
    assert.deepEqual(sinais, []);
  });

  it("dois HMAC nulos nao sao a mesma pessoa", () => {
    // Com `null == null` a regra marcava toda a cobranca sem Express de um
    // tenant cujo dono nao tenha telefone registado.
    const sinais = daRegra(
      avaliar(
        foto({
          cobrancas: [cobranca({ payerHmac: null, contactId: CONTACTO })],
          casa: [],
        }),
      ),
      "R-05",
    );
    assert.deepEqual(sinais, []);
  });
});

describe("R-06 — desvio de confirmacoes manuais (criterio 6)", () => {
  /** Um tenant com cinco contactos a 1 confirmacao e um a `quantas`. */
  function populacao(quantas: number): readonly ConfirmacaoObservada[] {
    const normais = Array.from({ length: 5 }, (_, i) =>
      confirmacao({ contactId: `aaaaaaaa-0000-4000-8000-00000000000${i}` }),
    );
    const desviante = Array.from({ length: quantas }, () =>
      confirmacao({ contactId: CONTACTO }),
    );
    return [...normais, ...desviante];
  }

  it("dispara: quatro confirmacoes contra uma mediana de 1 e k = 3", () => {
    const sinais = daRegra(
      avaliar(foto({ confirmacoes: populacao(4) })),
      "R-06",
    );
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.contactId, CONTACTO);
    assert.equal(sinais[0]?.accao, "exigir_dupla");
    assert.equal(sinais[0]?.detalhe["mediana_do_tenant"], 1);
  });

  it("nao dispara: tres confirmacoes, que e exactamente k x mediana", () => {
    // O limite e **estrito** (`> corte`), e o caso existe para o prender: com
    // `>=`, um tenant cuja mediana e 1 marcava todos os contactos com 3.
    assert.deepEqual(daRegra(avaliar(foto({ confirmacoes: populacao(3) })), "R-06"), []);
  });

  it("nao dispara: so as confirmacoes que concluiram contam", () => {
    const confirmacoes = [
      ...populacao(1),
      ...Array.from({ length: 9 }, () =>
        confirmacao({ contactId: CONTACTO, decisao: "retem" }),
      ),
    ];
    assert.deepEqual(daRegra(avaliar(foto({ confirmacoes })), "R-06"), []);
  });

  it("nao dispara fora da semana", () => {
    const confirmacoes = [
      ...populacao(1),
      ...Array.from({ length: 9 }, () =>
        confirmacao({ contactId: CONTACTO, instante: haMinutos(60 * 24 * 10) }),
      ),
    ];
    assert.deepEqual(daRegra(avaliar(foto({ confirmacoes })), "R-06"), []);
  });

  it("um tenant com um contacto so nao produz desvio, e e o certo", () => {
    const confirmacoes = Array.from({ length: 40 }, () => confirmacao());
    assert.deepEqual(daRegra(avaliar(foto({ confirmacoes })), "R-06"), []);
  });

  it("a mediana de um numero par e a media dos dois do meio", () => {
    // **Mede-se com k = 1, porque e so ai que as duas formulas se separam.**
    // Com duas contagens de 1 e 9: a media dos dois do meio da mediana 5 e
    // corte 5, e o 9 dispara; o de cima dava mediana 9 e corte 9, e o 9 nao
    // dispara (`> corte` e estrito). Com o k = 3 das propostas as duas formulas
    // dao o mesmo resultado — nenhum sinal — e o ensaio nao media nada.
    const confirmacoes = [
      confirmacao({ contactId: "aaaaaaaa-0000-4000-8000-000000000001" }),
      ...Array.from({ length: 9 }, () => confirmacao({ contactId: CONTACTO })),
    ];
    const sinais = daRegra(
      avaliar(foto({ confirmacoes }), {
        limiares: { ...LIMIARES_PROPOSTOS, "R-06": 1 },
        janelas: JANELAS_PROPOSTAS,
      }),
      "R-06",
    );
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.contactId, CONTACTO);
    assert.equal(sinais[0]?.detalhe["mediana_do_tenant"], 5);
  });
});

describe("R-07 — cod sem pagamento repetido", () => {
  const cod = (estado: string) =>
    cobranca({
      chargeId: `aaaaaaaa-0000-4000-8000-00000000${Math.random().toString().slice(2, 6)}`,
      metodo: "cod",
      estado,
    });

  it("dispara: tres cobrancas cod terminadas sem pagamento", () => {
    const cobrancas = [cod("expirada"), cod("cancelada"), cod("falhada")];
    const sinais = daRegra(avaliar(foto({ cobrancas })), "R-07");
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.detalhe["cobrancas_cod_sem_pagamento"], 3);
  });

  it("nao dispara: duas, uma abaixo do limiar", () => {
    const cobrancas = [cod("expirada"), cod("cancelada")];
    assert.deepEqual(daRegra(avaliar(foto({ cobrancas })), "R-07"), []);
  });

  it("nao dispara: tres cobrancas cod que estao activas", () => {
    // `iniciada`, `emitida` e `aguarda_cliente` nao sao *no-show*: sao
    // cobrancas em curso, e contá-las fazia da regra uma contagem de vendas.
    const cobrancas = [cod("iniciada"), cod("emitida"), cod("aguarda_cliente")];
    assert.deepEqual(daRegra(avaliar(foto({ cobrancas })), "R-07"), []);
  });

  it("uma reembolsada nao e um no-show: essa recebeu dinheiro", () => {
    const cobrancas = [cod("expirada"), cod("cancelada"), cod("reembolsada")];
    assert.deepEqual(daRegra(avaliar(foto({ cobrancas })), "R-07"), []);
  });

  it("nao dispara para metodos que nao sao cod", () => {
    const cobrancas = [
      cobranca({ chargeId: "a-1", metodo: "referencia", estado: "expirada" }),
      cobranca({ chargeId: "a-2", metodo: "referencia", estado: "expirada" }),
      cobranca({ chargeId: "a-3", metodo: "referencia", estado: "expirada" }),
    ];
    assert.deepEqual(daRegra(avaliar(foto({ cobrancas })), "R-07"), []);
  });

  it("a accao e registar, e a recomendacao vai no detalhe", () => {
    // «exigir sinal por referencia» nao esta no dominio do
    // `fraud_signals_accao_ck`, e o consumo da sancao e de KAM-097.
    const cobrancas = [cod("expirada"), cod("cancelada"), cod("falhada")];
    const sinal = daRegra(avaliar(foto({ cobrancas })), "R-07")[0];
    assert.equal(sinal?.accao, "registar");
    assert.equal(sinal?.detalhe["recomendacao"], "exigir_sinal_por_referencia");
    assert.equal(sinal?.detalhe["credor_do_consumo"], "KAM-097");
  });

  it("os terminais sem pagamento sao tres, e paga nao esta neles", () => {
    assert.deepEqual([...TERMINAIS_SEM_PAGAMENTO].sort(), [
      "cancelada",
      "expirada",
      "falhada",
    ]);
  });
});

describe("o determinismo (criterio 9)", () => {
  /** Uma fotografia com as sete regras em simultâneo. */
  function fotoCompleta(): Fotografia {
    return foto({
      eventos: [
        ...tresDivergencias(),
        evento({ eventId: 10n, tipoEvento: "pagamento_orfao" }),
        evento({ eventId: 11n, tipoEvento: "pagamento_duplicado" }),
      ],
      cobrancas: [
        cobranca({ payerHmac: "deadbeef" }),
        cobranca({ chargeId: "c-1", metodo: "cod", estado: "expirada" }),
        cobranca({ chargeId: "c-2", metodo: "cod", estado: "cancelada" }),
        cobranca({ chargeId: "c-3", metodo: "cod", estado: "falhada" }),
      ],
      confirmacoes: [
        confirmacao({ contactId: "d-1" }),
        confirmacao({ contactId: "d-2" }),
        ...Array.from({ length: 4 }, () => confirmacao({ contactId: CONTACTO })),
      ],
      recusas: Array.from({ length: 12 }, () => ({
        accountId: CONTA,
        instante: haMinutos(5),
      })),
      casa: [{ contactId: DONO, phoneHmac: "deadbeef" }],
    });
  }

  it("duas execucoes produzem sinais identicos", () => {
    const primeira = avaliar(fotoCompleta());
    const segunda = avaliar(fotoCompleta());
    assert.deepEqual(primeira, segunda);
  });

  it("a ordem das linhas da fotografia nao muda a saida", () => {
    // **E a parte que importa**, e a outra nao a cobre: duas leituras da base
    // podem devolver as linhas em ordens diferentes sem nada estar errado, e um
    // `ORDER BY` sem chave total nao e estavel. Sem o `_ordenar`, este ensaio
    // morre e o de cima continua verde.
    const normal = fotoCompleta();
    const invertida: Fotografia = {
      ...normal,
      eventos: [...normal.eventos].reverse(),
      cobrancas: [...normal.cobrancas].reverse(),
      confirmacoes: [...normal.confirmacoes].reverse(),
      recusas: [...normal.recusas].reverse(),
      reembolsos: [...normal.reembolsos].reverse(),
    };
    assert.deepEqual(avaliar(normal), avaliar(invertida));
  });

  it("dez mil eventos correm em menos de 60 s e dao o mesmo duas vezes", () => {
    const eventos: EventoObservado[] = [];
    for (let i = 0; i < 10_000; i += 1) {
      eventos.push(
        evento({
          eventId: BigInt(i + 1),
          // Cem contas, cem eventos cada: e o que faz a R-01 disparar cem vezes
          // em vez de uma, e portanto o que mede a agregacao e nao so o laco.
          accountId: `conta-${i % 100}`,
          chargeId: `cobranca-${i}`,
          instante: haMinutos(i % 55),
        }),
      );
    }
    const antes = Date.now();
    const primeira = avaliar(foto({ eventos }));
    const demorou = Date.now() - antes;
    const segunda = avaliar(foto({ eventos }));
    assert.equal(primeira.length, 100);
    assert.deepEqual(primeira, segunda);
    assert.ok(demorou < 60_000, `demorou ${demorou} ms`);
  });
});

describe("a guarda de PII no detalhe (criterio 8)", () => {
  it("nenhum sinal real leva chave proibida", () => {
    const sinais = avaliar(
      foto({
        eventos: tresDivergencias(),
        cobrancas: [cobranca({ payerHmac: "deadbeef" })],
        casa: [{ contactId: DONO, phoneHmac: "deadbeef" }],
      }),
    );
    assert.ok(sinais.length > 0);
    for (const sinal of sinais) assert.equal(semPii(sinal.detalhe), null);
  });

  it("uma chave proibida e recusada, e a razao diz qual", () => {
    const razao = semPii({ telefone: "o que for" });
    assert.match(String(razao), /telefone/);
  });

  it("uma chave que **contem** a palavra proibida tambem e recusada", () => {
    assert.ok(semPii({ telefone_do_pagador: "x" }) !== null);
    assert.ok(semPii({ texto_da_mensagem: "x" }) !== null);
  });

  it("um valor com forma de telefone e recusado mesmo em chave inocente", () => {
    assert.ok(semPii({ nota: "923456789" }) !== null);
  });

  it("e o telefone escrito com espacos tambem, que e o caso que escapava", () => {
    // Sete digitos nao bastam: `923 456 789` escapava a um padrao que so olhava
    // para digitos seguidos.
    assert.ok(semPii({ nota: "923 456 789" }) !== null);
    assert.ok(semPii({ nota: "+244 923.456-789" }) !== null);
  });

  it("o contact_id **passa**, e e o que o criterio 8 escreve", () => {
    assert.equal(semPii({ contact_id: CONTACTO, charge_id: "x" }), null);
  });

  it("um numero que nao tem forma de telefone passa", () => {
    assert.equal(semPii({ ocorrencias: 3, limiar: 3 }), null);
  });

  it("a lista de chaves proibidas tem as que o criterio nomeia", () => {
    for (const chave of ["telefone", "texto", "mensagem"]) {
      assert.ok((CHAVES_PROIBIDAS_NO_DETALHE as readonly string[]).includes(chave));
    }
  });

  it("um sinal com PII levanta em vez de ser filtrado em silencio", () => {
    // Filtrar era uma regra a deixar de disparar sem ninguem saber. Mede-se
    // pela funcao que o motor usa, com um detalhe forjado.
    assert.throws(
      () => {
        const sujo = { telefone: "923456789" };
        const razao = semPii(sujo);
        if (razao !== null) throw new SinalComPii("qualquer", razao);
      },
      (erro: unknown) => erro instanceof SinalComPii,
    );
  });
});

describe("a leitura do extracto (criterio 7)", () => {
  const CABECALHO = COLUNAS_DO_EXTRACTO.join(SEPARADOR_DO_EXTRACTO);

  it("le as linhas de um CSV bem formado", () => {
    const linhas = lerExtracto(
      `${CABECALHO}\nREF001;100000;2026-11-07\nREF002;250000;2026-11-07\n`,
    );
    assert.equal(linhas.length, 2);
    assert.equal(linhas[0]?.referencia, "REF001");
    assert.equal(linhas[0]?.valorMinor, 100_000n);
  });

  it("recusa um ficheiro vazio", () => {
    assert.throws(() => lerExtracto(""), ExtractoIlegivel);
  });

  it("recusa um cabecalho errado", () => {
    assert.throws(
      () => lerExtracto("ref;valor;data\nREF001;1;2026-11-07"),
      ExtractoIlegivel,
    );
  });

  it("recusa uma linha com colunas a mais", () => {
    assert.throws(
      () => lerExtracto(`${CABECALHO}\nREF001;1;2026-11-07;extra`),
      ExtractoIlegivel,
    );
  });

  it("recusa um valor com virgula decimal, e nao o trunca", () => {
    // Um `Number("1.5")` passava e truncava em silencio. Numa reconciliacao de
    // dinheiro, um valor truncado e a classe de defeito que o `money_lint`
    // recusa.
    assert.throws(
      () => lerExtracto(`${CABECALHO}\nREF001;1.5;2026-11-07`),
      ExtractoIlegivel,
    );
  });

  it("recusa uma data que nao se le", () => {
    assert.throws(
      () => lerExtracto(`${CABECALHO}\nREF001;1;ontem`),
      ExtractoIlegivel,
    );
  });

  it("recusa uma referencia vazia", () => {
    assert.throws(
      () => lerExtracto(`${CABECALHO}\n;1;2026-11-07`),
      ExtractoIlegivel,
    );
  });

  it("aceita um valor negativo: um estorno aparece no extracto", () => {
    const linhas = lerExtracto(`${CABECALHO}\nREF001;-5000;2026-11-07`);
    assert.equal(linhas[0]?.valorMinor, -5_000n);
  });

  it("CRLF e LF dao o mesmo digest: o lote e o conteudo e nao os bytes", () => {
    const corpo = `${CABECALHO}\nREF001;100000;2026-11-07`;
    assert.equal(
      digestDoLote(lerExtracto(corpo)),
      digestDoLote(lerExtracto(corpo.replace(/\n/g, "\r\n"))),
    );
  });

  it("a ordem das linhas nao muda o digest", () => {
    const a = `${CABECALHO}\nREF001;1;2026-11-07\nREF002;2;2026-11-07`;
    const b = `${CABECALHO}\nREF002;2;2026-11-07\nREF001;1;2026-11-07`;
    assert.equal(digestDoLote(lerExtracto(a)), digestDoLote(lerExtracto(b)));
  });
});

describe("R-08 — a reconciliacao (criterio 7)", () => {
  const paga = cobranca({ chargeId: "c-1", estado: "paga", amountMinor: 100_000n });
  const referencias = { "c-1": "REF001" };

  function ajustes(
    linhas: readonly { referencia: string; valorMinor: bigint; data: string }[],
    jaAjustados: readonly string[] = [],
  ) {
    return reconciliar({
      linhas,
      cobrancas: [paga],
      referenciaPorCobranca: referencias,
      jaAjustados,
    });
  }

  it("sem diferenca nenhuma, nao propoe nada", () => {
    assert.deepEqual(
      ajustes([{ referencia: "REF001", valorMinor: 100_000n, data: "2026-11-07" }]),
      [],
    );
  });

  it("valor diferente: propoe a diferenca, com sinal", () => {
    const [ajuste] = ajustes([
      { referencia: "REF001", valorMinor: 90_000n, data: "2026-11-07" },
    ]);
    assert.equal(ajuste?.motivo, "valor_diferente");
    assert.equal(ajuste?.diferencaMinor, -10_000n);
    assert.equal(ajuste?.chargeId, "c-1");
  });

  it("extracto sem cobranca paga: propoe o valor inteiro, sem tenant", () => {
    // **Pelo motivo e nao pela posicao.** A ordem da saida e por
    // `providerEventId` (um digest), pelo que indexar `[0]` media o que o
    // digest calhasse ordenar primeiro — e a mesma linha de extracto produz
    // agora dois ajustes: o `sem_cobranca_paga` dela e o `paga_sem_extracto` da
    // cobranca que o extracto nao mencionou.
    const propostos = ajustes([
      { referencia: "DESCONHECIDA", valorMinor: 50_000n, data: "2026-11-07" },
    ]);
    const ajuste = propostos.find((a) => a.motivo === "sem_cobranca_paga");
    assert.ok(ajuste, JSON.stringify(propostos.map((a) => a.motivo)));
    assert.equal(ajuste?.tenantId, null);
    assert.equal(ajuste?.diferencaMinor, 50_000n);
  });

  it("paga sem linha no extracto: propoe o negativo", () => {
    // A direccao que nao e simetrica da outra: confirmou-se um pagamento que o
    // banco nao viu.
    const [ajuste] = ajustes([]);
    assert.equal(ajuste?.motivo, "paga_sem_extracto");
    assert.equal(ajuste?.diferencaMinor, -100_000n);
  });

  it("uma cobranca que nao esta paga nao entra na comparacao", () => {
    const resultado = reconciliar({
      linhas: [],
      cobrancas: [cobranca({ chargeId: "c-1", estado: "emitida" })],
      referenciaPorCobranca: referencias,
      jaAjustados: [],
    });
    assert.deepEqual(resultado, []);
  });

  it("um CSV repetido nao duplica ajustes", () => {
    const linhas = [
      { referencia: "REF001", valorMinor: 90_000n, data: "2026-11-07" },
    ];
    const primeira = ajustes(linhas);
    assert.equal(primeira.length, 1);
    const segunda = ajustes(
      linhas,
      primeira.map((a) => a.providerEventId),
    );
    assert.deepEqual(segunda, []);
  });

  it("o provider_event_id identifica a origem e **nao** leva a referencia", () => {
    // A asserção era `/REF001/`, e era o defeito: a `referencia` e texto que o
    // dono escreveu no CSV, e este id viaja para o `detalhe` do sinal. Agora
    // leva o **digest** da chave `(conta, referencia)` — ver o `_ajuste`.
    const propostos = ajustes([
      { referencia: "REF001", valorMinor: 90_000n, data: "2026-11-07" },
    ]);
    const ajuste = propostos.find((a) => a.motivo === "valor_diferente");
    assert.ok(ajuste);
    assert.ok(String(ajuste?.providerEventId).startsWith(`${PREFIXO_DO_AJUSTE}:`));
    assert.ok(
      !String(ajuste?.providerEventId).includes("REF001"),
      "a referencia do CSV nao entra no id",
    );
    assert.match(String(ajuste?.providerEventId), /valor_diferente$/);
  });

  it("dois extractos diferentes dao ajustes diferentes para a mesma linha", () => {
    // O lote **e** o digest e nao a data: um extracto corrigido e um lote novo,
    // e o ajuste dele nao pode ser silenciado pelo do anterior.
    const [a] = ajustes([
      { referencia: "REF001", valorMinor: 90_000n, data: "2026-11-07" },
    ]);
    const [b] = ajustes([
      { referencia: "REF001", valorMinor: 80_000n, data: "2026-11-07" },
    ]);
    assert.notEqual(a?.providerEventId, b?.providerEventId);
  });

  it("LIGACAO — os sinais da R-08 derivam dos ajustes com tenant", () => {
    const propostos = ajustes([
      { referencia: "REF001", valorMinor: 90_000n, data: "2026-11-07" },
      { referencia: "DESCONHECIDA", valorMinor: 1n, data: "2026-11-07" },
    ]);
    const sinais = sinaisDaReconciliacao(propostos);
    // Dois ajustes, **um** sinal: o que nao tem tenant fica para o caso de ops,
    // porque a coluna e `NOT NULL` com FK.
    assert.equal(propostos.length, 2);
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.regra, REGRA_POR_ID["R-08"].regra);
    assert.equal(sinais[0]?.chargeId, "c-1");
  });

  it("sem ajustes nao ha sinais da R-08", () => {
    assert.deepEqual(sinaisDaReconciliacao([]), []);
  });
});

describe("as accoes e o enforcement (criterio 5)", () => {
  function entrada(campos: Partial<EntradaDaConfirmacao> = {}): EntradaDaConfirmacao {
    return {
      amount: 100_000n,
      valorDeclarado: 100_000n,
      actorContactId: DONO,
      clienteContactId: CONTACTO,
      confirmador: {
        contactId: DONO,
        papel: "dono",
        podeSegundaAprovacao: true,
        ativo: true,
      },
      tectoDaDuplaMinor: 1_000_000n,
      janela: {
        somaDoDiaMinor: 0n,
        tectoDiarioMinor: 5_000_000n,
        confirmacoesDoContacto: 0,
        tectoDoContacto: 10,
      },
      primeiraAprovacaoDe: null,
      ...campos,
    };
  }

  const sinalDe = (accao: Sinal["accao"]): Sinal => ({
    tenantId: TENANT,
    contactId: CONTACTO,
    chargeId: null,
    regra: "qualquer",
    severidade: 3,
    accao,
    detalhe: {},
  });

  it("a escada da forca tem as cinco accoes, e reter e mais forte que a dupla", () => {
    assert.equal(Object.keys(FORCA_DA_ACCAO).length, ACCOES.length);
    assert.ok(FORCA_DA_ACCAO["reter_confirmacao"] > FORCA_DA_ACCAO["exigir_dupla"]);
    assert.ok(FORCA_DA_ACCAO["suspender_manual"] > FORCA_DA_ACCAO["reter_confirmacao"]);
  });

  it("sem sinais, a accao em vigor e registar", () => {
    assert.equal(accaoEmVigor([]), "registar");
  });

  it("a accao em vigor e a mais forte e nao a ultima", () => {
    assert.equal(
      accaoEmVigor([sinalDe("reter_confirmacao"), sinalDe("exigir_dupla")]),
      "reter_confirmacao",
    );
    assert.equal(
      accaoEmVigor([sinalDe("exigir_dupla"), sinalDe("reter_confirmacao")]),
      "reter_confirmacao",
    );
  });

  it("um reter_confirmacao transforma um confirma em retem", () => {
    const veredicto = avaliarConfirmacao(entrada());
    assert.equal(veredicto.decisao, "confirma");
    assert.equal(respeitarAccao(veredicto, "reter_confirmacao").decisao, "retem");
  });

  it("um exigir_dupla transforma um confirma em exige_segunda", () => {
    const veredicto = avaliarConfirmacao(entrada());
    assert.equal(respeitarAccao(veredicto, "exigir_dupla").decisao, "exige_segunda");
  });

  it("um registar nao muda nada, e devolve o mesmo objecto", () => {
    const veredicto = avaliarConfirmacao(entrada());
    assert.equal(respeitarAccao(veredicto, "registar"), veredicto);
  });

  it("uma rejeicao **continua** uma rejeicao, e e a propriedade que importa", () => {
    // Se um `reter_confirmacao` tornasse o `valor_nao_bate` num `retem`, um
    // atacante que recebesse «retido para analise» em vez de «o valor nao bate»
    // aprendia que acertou no valor. E a razao escrita no `manual.ts`.
    const veredicto = avaliarConfirmacao(entrada({ valorDeclarado: 99_999n }));
    assert.equal(veredicto.decisao, "rejeita");
    assert.equal(respeitarAccao(veredicto, "reter_confirmacao").decisao, "rejeita");
    assert.equal(respeitarAccao(veredicto, "suspender_manual").decisao, "rejeita");
  });

  it("um exigir_dupla nao afrouxa um retem do M-3", () => {
    const veredicto = avaliarConfirmacao(
      entrada({
        janela: {
          somaDoDiaMinor: 5_000_000n,
          tectoDiarioMinor: 5_000_000n,
          confirmacoesDoContacto: 0,
          tectoDoContacto: 10,
        },
      }),
    );
    assert.equal(veredicto.decisao, "retem");
    assert.equal(respeitarAccao(veredicto, "exigir_dupla").decisao, "retem");
  });

  it("a retencao troca o sinal pela regra da anomalia", () => {
    const retido = respeitarAccao(
      avaliarConfirmacao(entrada()),
      "reter_confirmacao",
    );
    assert.equal(retido.sinal, REGRA_POR_ID["R-05"].regra);
  });

  it("LIGACAO — a auto-compra retem a confirmacao pelo caminho inteiro", () => {
    // **E este ensaio que morre com a composicao desfeita.** O `avaliar` e o
    // `avaliarConfirmacao` continuam os dois perfeitos sem o `respeitarAccao` no
    // meio; o que desaparece e a retencao, que e o criterio 5.
    const sinais = avaliar(
      foto({
        cobrancas: [cobranca({ payerHmac: "deadbeef", contactId: CONTACTO })],
        casa: [{ contactId: DONO, phoneHmac: "deadbeef" }],
      }),
    );
    assert.equal(sinais.length, 1);
    assert.equal(sinais[0]?.accao, "reter_confirmacao");

    const livre = avaliarConfirmacao(entrada());
    assert.equal(livre.decisao, "confirma");

    const comAnomalia = decidirConfirmacao(entrada(), sinais);
    assert.equal(comAnomalia.decisao, "retem");
    assert.equal(comAnomalia.sinal, REGRA_POR_ID["R-05"].regra);
  });

  it("LIGACAO — sem sinais, a decisao composta e a do ManualProvider", () => {
    // O par do ensaio de cima: a composicao nao pode apertar quem nao tem
    // anomalia nenhuma, senao o criterio 5 ficava satisfeito por um motor que
    // retem tudo.
    assert.deepEqual(decidirConfirmacao(entrada(), []), avaliarConfirmacao(entrada()));
  });
});

describe("o job (criterios 2 e 3)", () => {
  function correr(
    fotografia: Fotografia,
    opcoes: { readonly comEscrita?: boolean; readonly comContador?: boolean } = {},
  ) {
    const alertas: { alerta: string; detalhe: Record<string, unknown> }[] = [];
    const contados: string[] = [];
    const escritos: Sinal[] = [];
    return {
      alertas,
      contados,
      escritos,
      relatorio: detectarAnomalias({
        leitura: { fotografar: async () => fotografia },
        alertar: (alerta, detalhe) => alertas.push({ alerta, detalhe }),
        ...(opcoes.comContador === false
          ? {}
          : { contar: (regra: string) => contados.push(regra) }),
        ...(opcoes.comEscrita === true
          ? {
              escrita: {
                persistir: async (sinais: readonly Sinal[]) => {
                  escritos.push(...sinais);
                  return sinais.length;
                },
              },
            }
          : {}),
      }),
    };
  }

  it("sem anomalia nenhuma, fica conforme e nao alerta", async () => {
    const corrida = correr(foto());
    const relatorio = await corrida.relatorio;
    assert.equal(relatorio.conforme, true);
    assert.deepEqual(relatorio.sinais, []);
    assert.deepEqual(corrida.alertas, []);
  });

  it("um sinal severo alerta ops", async () => {
    const corrida = correr(foto({ eventos: tresDivergencias() }));
    await corrida.relatorio;
    const alerta = corrida.alertas.find((a) => a.alerta === ALERTA_DE_SINAL);
    assert.ok(alerta, "faltou o alerta de sinal severo");
    assert.equal(alerta?.detalhe["sinais"], 1);
  });

  it("um sinal abaixo da severidade que alerta nao alerta", async () => {
    // A R-07 e severidade 2, abaixo do `SEVERIDADE_QUE_ALERTA`. Sem este par, o
    // alerta podia estar ligado a «ha sinais» em vez de «ha sinais severos».
    const cod = (chargeId: string, estado: string) =>
      cobranca({ chargeId, metodo: "cod", estado });
    const corrida = correr(
      foto({
        cobrancas: [cod("c-1", "expirada"), cod("c-2", "cancelada"), cod("c-3", "falhada")],
      }),
    );
    const relatorio = await corrida.relatorio;
    assert.equal(relatorio.sinais.length, 1);
    assert.ok((relatorio.sinais[0]?.severidade ?? 9) < SEVERIDADE_QUE_ALERTA);
    assert.equal(
      corrida.alertas.find((a) => a.alerta === ALERTA_DE_SINAL),
      undefined,
    );
  });

  it("um orfao com mais de 24 h alerta, e conta-se no relatorio", async () => {
    const corrida = correr(
      foto({
        eventos: [
          evento({ tipoEvento: "pagamento_orfao", instante: haMinutos(60 * 30) }),
        ],
      }),
    );
    const relatorio = await corrida.relatorio;
    assert.equal(relatorio.orfaosAbertos, 1);
    assert.ok(corrida.alertas.some((a) => a.alerta === ALERTA_DE_ORFAO));
  });

  it("um orfao com menos de 24 h nao alerta por idade", async () => {
    // O criterio 3 diz «orfaos abertos > 24 h e 0 ... e dispara alerta se > 0».
    const corrida = correr(
      foto({
        eventos: [
          evento({ tipoEvento: "pagamento_orfao", instante: haMinutos(60 * 2) }),
        ],
      }),
    );
    const relatorio = await corrida.relatorio;
    assert.equal(relatorio.orfaosAbertos, 0);
    assert.equal(
      corrida.alertas.find((a) => a.alerta === ALERTA_DE_ORFAO),
      undefined,
    );
  });

  it("LIGACAO — o contador recebe uma chamada por sinal", async () => {
    const corrida = correr(
      foto({
        eventos: [
          ...tresDivergencias(),
          evento({ eventId: 9n, tipoEvento: "pagamento_orfao" }),
        ],
      }),
    );
    const relatorio = await corrida.relatorio;
    assert.equal(relatorio.sinais.length, 2);
    assert.deepEqual(
      [...corrida.contados].sort(),
      relatorio.sinais.map((s) => s.regra).sort(),
    );
  });

  it("sem escritor, alerta que os sinais nao ficaram na base", async () => {
    // **A honestidade do relatorio.** `fraud_signals` e SELECT-only para os
    // tres papeis (revisao `0032`): um motor que corre e nao escreve tem de o
    // dizer, e `persistidos: null` distingue «nao escreveu» de «escreveu zero».
    const corrida = correr(foto({ eventos: tresDivergencias() }));
    const relatorio = await corrida.relatorio;
    assert.equal(relatorio.persistidos, null);
    assert.ok(corrida.alertas.some((a) => a.alerta === ALERTA_DE_ESCRITA));
  });

  it("sem sinais, nao alerta sobre a escrita que falta", async () => {
    const corrida = correr(foto());
    await corrida.relatorio;
    assert.equal(
      corrida.alertas.find((a) => a.alerta === ALERTA_DE_ESCRITA),
      undefined,
    );
  });

  it("com escritor, persiste e nao alerta sobre a escrita", async () => {
    const corrida = correr(foto({ eventos: tresDivergencias() }), {
      comEscrita: true,
    });
    const relatorio = await corrida.relatorio;
    assert.equal(relatorio.persistidos, 1);
    assert.equal(corrida.escritos.length, 1);
    assert.equal(
      corrida.alertas.find((a) => a.alerta === ALERTA_DE_ESCRITA),
      undefined,
    );
  });

  it("conforme e «nao ha anomalia» e nao «o motor correu»", async () => {
    const corrida = correr(foto({ eventos: tresDivergencias() }), {
      comEscrita: true,
    });
    assert.equal((await corrida.relatorio).conforme, false);
  });

  it("a configuracao de omissao e a proposta", async () => {
    assert.equal(CONFIGURACAO_PROPOSTA.limiares, LIMIARES_PROPOSTOS);
    assert.equal(CONFIGURACAO_PROPOSTA.janelas, JANELAS_PROPOSTAS);
  });

  it("um limiar calibrado muda o que dispara, sem tocar nas regras", async () => {
    // E o que faz dos limiares dados e nao codigo: o Piloto calibra o mapa.
    const comQuatro = avaliar(foto({ eventos: tresDivergencias() }), {
      limiares: { ...LIMIARES_PROPOSTOS, "R-01": 4 },
      janelas: JANELAS_PROPOSTAS,
    });
    assert.deepEqual(daRegra(comQuatro, "R-01"), []);
  });
});

describe("os catorze achados da revisao adversarial", () => {
  // Um ensaio por achado, com o caso que o revisor mediu. Ficam juntos e
  // nomeados pelo numero de proposito: um achado fechado sem ensaio volta na
  // auditoria seguinte e paga-se outra vez.

  it("A1 — os sinais da R-08 passam pela guarda de PII", () => {
    // O laco do `semPii` vivia **dentro** do `avaliar`, que corre a R-01 ate a
    // R-07; os da R-08 saem pelo `sinaisDaReconciliacao` e nao passavam por
    // guarda nenhuma. E levavam a `referencia` do CSV em claro no
    // `provider_event_id` — isto e, era a via por onde um telefone entrava num
    // `fraud_signals`. O proprio `semPii` do ramo recusava o sinal que o ramo
    // emitia.
    const paga = cobranca({ chargeId: "c-1", estado: "paga", referencia: "923456789" });
    const ajustes = reconciliar({
      linhas: [{ referencia: "923456789", valorMinor: 90_000n, data: "2026-11-07" }],
      cobrancas: [paga],
      referenciaPorCobranca: { "c-1": "923456789" },
      jaAjustados: [],
    });
    const sinais = sinaisDaReconciliacao(ajustes);
    assert.equal(sinais.length, 1);
    assert.equal(semPii(sinais[0]!.detalhe), null);
    // E a razao de passar: o id leva o digest da chave e nao o texto.
    assert.ok(!JSON.stringify(sinais[0]!.detalhe).includes("923456789"));
  });

  it("A2 — duas contas com a mesma referencia nao se calam uma a outra", () => {
    // A `0029` escreve que o par unico e `(account_id, referencia)`, **com** a
    // conta. Com a referencia sozinha o `Map` guardava a ultima, e uma linha
    // que batia exactamente com a primeira dava um ajuste falso no tenant da
    // segunda — 200 000 no tenant errado, medido pelo revisor.
    const a = cobranca({
      chargeId: "c-1", accountId: "a-1", tenantId: "t-1",
      amountMinor: 100_000n, referencia: "REF001",
    });
    const b = cobranca({
      chargeId: "c-2", accountId: "a-2", tenantId: "t-2",
      amountMinor: 300_000n, referencia: "REF001",
    });
    const semExtracto = reconciliar({
      linhas: [],
      cobrancas: [a, b],
      referenciaPorCobranca: { "c-1": "REF001", "c-2": "REF001" },
      jaAjustados: [],
    });
    assert.equal(semExtracto.length, 2, "as duas pagas tem de aparecer");
    assert.deepEqual(
      [...semExtracto.map((x) => x.chargeId)].sort(),
      ["c-1", "c-2"],
    );
  });

  it("A2b — uma linha ambigua vai para ops em vez de ser atribuida ao palpite", () => {
    // O par do de cima: com duas cobrancas `paga` a mesma referencia em contas
    // diferentes, o extracto **nao diz a conta** e a linha nao se adivinha.
    const a = cobranca({ chargeId: "c-1", accountId: "a-1", tenantId: "t-1", amountMinor: 100_000n });
    const b = cobranca({ chargeId: "c-2", accountId: "a-2", tenantId: "t-2", amountMinor: 300_000n });
    const ajustes = reconciliar({
      linhas: [{ referencia: "REF001", valorMinor: 100_000n, data: "2026-11-07" }],
      cobrancas: [a, b],
      referenciaPorCobranca: { "c-1": "REF001", "c-2": "REF001" },
      jaAjustados: [],
    });
    // Nenhum ajuste de `valor_diferente` sobre a cobranca errada.
    assert.equal(
      ajustes.filter((x) => x.motivo === "valor_diferente").length,
      0,
      // **Sem `JSON.stringify` sobre o ajuste:** o `diferencaMinor` e `bigint` e
      // o `stringify` rebenta nele, o que troca a falha medida por um
      // `TypeError` e esconde o que o ensaio queria dizer.
      ajustes.map((x) => x.motivo).join(", "),
    );
    assert.ok(ajustes.some((x) => x.motivo === "sem_cobranca_paga"));
  });

  it("A3 — a mesma referencia duas vezes no mesmo CSV nao duplica", () => {
    // O `jaAjustados` so olha para tras: duas linhas iguais no **mesmo** lote
    // davam dois ajustes com o mesmo `provider_event_id` e montantes
    // diferentes, escritos os dois num ledger que nao se corrige.
    const ajustes = reconciliar({
      linhas: [
        { referencia: "REF001", valorMinor: 50_000n, data: "2026-11-07" },
        { referencia: "REF001", valorMinor: 70_000n, data: "2026-11-07" },
      ],
      cobrancas: [],
      referenciaPorCobranca: {},
      jaAjustados: [],
    });
    assert.equal(new Set(ajustes.map((x) => x.providerEventId)).size, ajustes.length);
  });

  it("A4 — a janela e o limiar da R-03 e da R-04 decidem", () => {
    // As duas funcoes nao recebiam `Configuracao` nenhuma: os mapas existiam e
    // nao decidiam nada, pelo que o criterio 1 («limiar configuravel») era
    // falso para elas. E com a fotografia de 720 h, cada corrida do job
    // re-emitia trinta dias de orfaos.
    const antigos = foto({
      eventos: [
        evento({ eventId: 1n, tipoEvento: "pagamento_orfao", instante: haMinutos(60 * 700) }),
        evento({ eventId: 2n, tipoEvento: "pagamento_duplicado", instante: haMinutos(60 * 700) }),
      ],
    });
    const apertada = {
      limiares: { ...LIMIARES_PROPOSTOS, "R-03": 99, "R-04": 99 },
      janelas: { ...JANELAS_PROPOSTAS, "R-03": 1, "R-04": 1 },
    };
    assert.deepEqual(avaliar(antigos, apertada), []);
    // A sonda positiva: com as propostas, os dois disparam **dentro** da janela.
    const recentes = foto({
      eventos: [
        evento({ eventId: 1n, tipoEvento: "pagamento_orfao", instante: haMinutos(30) }),
        evento({ eventId: 2n, tipoEvento: "pagamento_duplicado", instante: haMinutos(30) }),
      ],
    });
    assert.equal(avaliar(recentes).length, 2);
  });

  it("A4b — a janela da R-05 e da R-07 decide", () => {
    const velha = cobranca({ payerHmac: "deadbeef", criadoEm: haMinutos(60 * 700) });
    assert.deepEqual(
      daRegra(
        avaliar(foto({ cobrancas: [velha], casa: [{ contactId: DONO, phoneHmac: "deadbeef" }] })),
        "R-05",
      ),
      [],
    );
    const nova = cobranca({ payerHmac: "deadbeef", criadoEm: haMinutos(30) });
    assert.equal(
      daRegra(
        avaliar(foto({ cobrancas: [nova], casa: [{ contactId: DONO, phoneHmac: "deadbeef" }] })),
        "R-05",
      ).length,
      1,
    );
  });

  it("A5 — um retem da anomalia nao leva a regra de uma que nao retem", () => {
    // O `...veredicto` preservava `regra` e `motivo` do veredicto de origem: um
    // `retem` saia com `regra: "M-5"`, que e a dupla verificacao e nunca retem.
    const veredicto = {
      decisao: "exige_segunda" as const,
      motivo: null,
      regra: "M-5" as const,
      valorBate: true,
      fase: "confirmacao" as const,
      sinal: null,
    };
    const retido = respeitarAccao(veredicto, "reter_confirmacao");
    assert.equal(retido.decisao, "retem");
    assert.equal(retido.regra, null);
    assert.equal(retido.motivo, null);
    assert.equal(retido.sinal, REGRA_POR_ID["R-05"].regra);
  });

  it("A5b — um exigir_dupla nao volta a pedir a segunda que ja foi dada", () => {
    // **Era um impasse num caminho de dinheiro:** com a `fase` em
    // `segunda_aprovacao`, a dupla ja existe, e pedi-la outra vez fazia a
    // cobranca nunca confirmar enquanto o sinal da R-06 estivesse na janela.
    const jaComDupla = {
      decisao: "confirma" as const,
      motivo: null,
      regra: null,
      valorBate: true,
      fase: "segunda_aprovacao" as const,
      sinal: null,
    };
    assert.equal(respeitarAccao(jaComDupla, "exigir_dupla").decisao, "confirma");
  });

  it("A5c — um bloquear_contacto nao produz um retem anonimo", () => {
    // Nenhuma regra **deste** ticket tem `bloquear_contacto` nem
    // `suspender_manual` — sao do KAM-097 —, pelo que a busca devolvia
    // `undefined` e o `?? veredicto.sinal` deixava `null`. Um `retem` sem regra
    // e um caso que ops nao consegue atender.
    const limpo = {
      decisao: "confirma" as const,
      motivo: null,
      regra: null,
      valorBate: true,
      fase: "confirmacao" as const,
      sinal: null,
    };
    for (const accao of ["bloquear_contacto", "suspender_manual"] as const) {
      const r = respeitarAccao(limpo, accao);
      assert.equal(r.decisao, "retem");
      assert.equal(r.sinal, ACCAO_SEM_REGRA_DESTE_TICKET, accao);
    }
  });

  it("A6 — com dois contactos activos a R-06 nao dispara, e e algebra", () => {
    // `x (2 - k) > k a` e impossivel para `k >= 2`. O ensaio existe porque a
    // nota do `_r06` dizia que o caso de dois funcionava.
    const confirmacoes = [
      confirmacao({ contactId: "aaaaaaaa-0000-4000-8000-000000000001" }),
      ...Array.from({ length: 1000 }, () => confirmacao({ contactId: CONTACTO })),
    ];
    assert.deepEqual(daRegra(avaliar(foto({ confirmacoes })), "R-06"), []);
  });

  it("A7 — a ordem da saida nao depende da ordem das recusas da R-02", () => {
    // A R-02 e a unica regra cujo sinal tem `chargeId` **e** `contactId` nulos,
    // pelo que os tres primeiros termos do `_ordenar` davam chave identica a
    // todos os sinais dela e a saida seguia a ordem da entrada. O ensaio do
    // determinismo nao o via porque usava **uma** conta so.
    const recusasDe = (conta: string) =>
      Array.from({ length: 10 }, () => ({ accountId: conta, instante: haMinutos(5) }));
    const cobrancas = [
      cobranca({ chargeId: "c-A", accountId: "conta-A", tenantId: TENANT }),
      cobranca({ chargeId: "c-B", accountId: "conta-B", tenantId: TENANT }),
    ];
    const normal = avaliar(
      foto({ cobrancas, recusas: [...recusasDe("conta-A"), ...recusasDe("conta-B")] }),
    );
    const trocada = avaliar(
      foto({ cobrancas, recusas: [...recusasDe("conta-B"), ...recusasDe("conta-A")] }),
    );
    assert.equal(daRegra(normal, "R-02").length, 2);
    assert.deepEqual(normal, trocada);
  });

  it("A8 — o semPii apanha um numero, um fixo, e um objecto aninhado", () => {
    // Tres buracos medidos: o `typeof valor !== "string") continue` saltava os
    // `number` (e o tipo do detalhe admite-os), o padrao exigia `9` a cabeca e
    // nao apanhava um fixo de Luanda, e o mesmo `continue` saltava objectos.
    assert.ok(semPii({ identificador: 923_456_789 }) !== null);
    assert.ok(semPii({ contacto_alternativo: "222123456" }) !== null);
    assert.ok(semPii({ dados: { telefone: "923456789" } }) !== null);
    assert.ok(semPii({ observacao: "o cliente reclamou" }) !== null);
    // E as sondas positivas: o que o motor escreve continua a passar.
    assert.equal(semPii({ ocorrencias: 3, limiar: 3, janela_horas: 1 }), null);
    assert.equal(semPii({ account_id: CONTA, charge_id: "c-1" }), null);
  });

  it("A10 — uma contagem que levanta nao mata a deteccao", async () => {
    // A ordem do `detectarAnomalias` foi escrita para que o alerta nao dependa
    // da escrita; uma falha de observabilidade a abortar a corrida invertia-a.
    const alertas: string[] = [];
    const relatorio = await detectarAnomalias({
      leitura: { fotografar: async () => foto({ eventos: tresDivergencias() }) },
      alertar: (alerta) => alertas.push(alerta),
      contar: () => {
        throw new Error("regra desconhecida");
      },
    });
    assert.equal(relatorio.sinais.length, 1);
    assert.ok(alertas.includes(ALERTA_DE_CONTAGEM));
    assert.ok(alertas.includes(ALERTA_DE_SINAL), "o alerta de ops tem de sair");
  });

  it("A13 — uma paga de metodo referencia sem referencia e uma diferenca", () => {
    // Era invisivel: nem ajuste, nem caso para ops, contra a letra do criterio
    // 7. Para o `cod` e para o `express_push` a ausencia e correcta.
    const semRef = cobranca({
      chargeId: "c-1",
      estado: "paga",
      // **O metodo tem de ser `referencia`**, e a fabrica poe `manual`: o
      // motivo `paga_sem_referencia` e so para o metodo que a devia ter. Sem
      // isto o ensaio media o caminho do `cod`, onde a ausencia e correcta.
      metodo: "referencia",
      referencia: null,
    });
    const ajustes = reconciliar({
      linhas: [],
      cobrancas: [semRef],
      referenciaPorCobranca: {},
      jaAjustados: [],
    });
    assert.equal(ajustes.length, 1);
    assert.equal(ajustes[0]?.motivo, "paga_sem_referencia");

    const cod = cobranca({ chargeId: "c-2", estado: "paga", metodo: "cod", referencia: null });
    assert.deepEqual(
      reconciliar({ linhas: [], cobrancas: [cod], referenciaPorCobranca: {}, jaAjustados: [] }),
      [],
    );
  });
});

describe("as cadeias de SQL", () => {
  it("as sete cadeias estao nomeadas, para a suite de base de dados as ler", () => {
    assert.equal(CADEIAS_DAS_ANOMALIAS.length, 7);
    assert.equal(new Set(CADEIAS_DAS_ANOMALIAS).size, 7);
  });

  it("nenhuma delas escreve: o motor nao escreve estado de pagamento", () => {
    // **E a caixa do DoD, imposta e nao prometida.** Se alguem acrescentar um
    // `UPDATE` a este modulo, este ensaio morre antes de o PR abrir.
    const proibidas = /\b(INSERT|UPDATE|DELETE|TRUNCATE|MERGE)\b/i;
    for (const nome of CADEIAS_DAS_ANOMALIAS) {
      const sql = SQL[nome];
      assert.ok(sql !== undefined, `${nome} nao esta no mapa deste ensaio`);
      assert.ok(!proibidas.test(sql), `${nome} escreve na base`);
      assert.match(sql, /^\s*SELECT/i, `${nome} nao e um SELECT`);
    }
  });

  it("a unica cadeia de escrita vai pela porta e nao por INSERT", () => {
    // **O par do varrimento de cima.** Aquele prova que as leituras nao
    // escrevem; este prova que a escrita **existe** e que vai pela funcao
    // `SECURITY DEFINER` — nenhum papel tem `INSERT` na `platform.fraud_signals`
    // (revisao `0032`), pelo que um `INSERT` aqui era codigo que nunca correria.
    assert.equal(CADEIAS_DE_ESCRITA.length, 1);
    assert.match(SQL_REGISTAR_SINAL, /platform\.registar_sinal_de_anomalia\(/);
    assert.ok(!/\bINSERT\b/i.test(SQL_REGISTAR_SINAL));
    // Os oito parametros da porta, pela ordem dela.
    for (let i = 1; i <= 8; i += 1) {
      assert.ok(SQL_REGISTAR_SINAL.includes(`$${i}`), `falta o $${i}`);
    }
  });

  it("o mapa deste ensaio cobre as sete, e nao seis", () => {
    // **Sem este par, o ensaio de cima passava com o mapa a meio**: um `nome`
    // sem entrada dava `undefined` e o `assert.ok` dizia-o, mas uma cadeia
    // acrescentada ao `CADEIAS_DAS_ANOMALIAS` e esquecida aqui aparecia como
    // falha do mapa e nao como cadeia por varrer. Explicita-se a igualdade.
    assert.deepEqual(Object.keys(SQL).sort(), [...CADEIAS_DAS_ANOMALIAS].sort());
  });
});

/**
 * As cadeias por nome, para o varrimento de cima.
 *
 * Literal e nao construido por reflexao sobre o modulo: um `import * as` punha
 * toda a exportacao do ficheiro neste mapa — tipos, funcoes e constantes — e o
 * varrimento passava a medir o que lhe calhasse em vez das seis cadeias.
 */
const SQL: Readonly<Record<(typeof CADEIAS_DAS_ANOMALIAS)[number], string>> = {
  SQL_ANOMALIAS_EVENTOS,
  SQL_ANOMALIAS_COBRANCAS,
  SQL_ANOMALIAS_CONFIRMACOES,
  SQL_ANOMALIAS_RECUSAS,
  SQL_ANOMALIAS_CASA,
  SQL_ANOMALIAS_AJUSTES_FEITOS,
  SQL_ANOMALIAS_REEMBOLSOS,
};
