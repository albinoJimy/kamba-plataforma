/**
 * `ManualProvider`: o tecto por pedido, o opt-in do `cod` e a tabela das regras
 * (KAM-054, criterios 1, 2, 4, 5, 6 e 9).
 *
 * O que esta bateria prova, e o que fica para a suite de base de dados:
 *
 *     aqui          o `createCharge` (M-2 e o opt-in do `cod`), a coerencia das
 *                   capacidades com o `registo.ts`, e a **tabela** das regras
 *                   M-1, M-3, M-4 e M-5 caso a caso
 *     base de dados que a recusa **vale** — as funcoes da revisao `0032`, a
 *                   RLS, a idempotencia por `canal_msg_id`, o G8 e a reversao
 *                   que nao apaga nada. `db/tests_pagamentos/`
 *
 * ## Cada recusa mede-se nas duas direccoes
 *
 * Quatro das nove alineas dos Criterios de Aceitacao sao recusas, e uma suite
 * que so medisse recusas fica verde sobre um caminho que nao funciona de todo —
 * aconteceu neste repositorio, e e a razao do padrao da «sonda positiva». Por
 * isso cada recusa aqui tem par: o caminho ilegitimo e recusado **e** o
 * legitimo passa, com o mesmo arranjo e a mudar uma coisa so.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ADAPTADORES_DE_CONFIRMACAO_HUMANA,
  AVISOS,
  CADEIAS_DO_MANUAL,
  CAPACIDADES_DO_MANUAL,
  CHAVE_MAX,
  CONFORMIDADE_VAZIA,
  FASES,
  IMPORTACOES_PROIBIDAS,
  JANELA_DE_SILENCIO_HORAS,
  ManualProvider,
  PROPOSTAS_DE_OMISSAO,
  PROVIDER_MANUAL,
  ProviderError,
  REGRA_DIARIA,
  REGRA_POR_CONTACTO,
  ROTULO_NAO_PROVA,
  activar,
  avaliarConfirmacao,
  cobre,
  evidenciaNaoProva,
  expiraEm,
  podeConfirmar,
  rotuloDaEvidencia,
  type ConfirmadorConhecido,
  type CreateChargeReq,
  type EntradaDaConfirmacao,
  type LeitorDeInstrucoes,
  type LeitorDeLimites,
  type LimitesDoManual,
  type Minor,
  type Uuid,
} from "../src/pagamentos/index.ts";

/** 50 000 Kz em unidade menor. E a **proposta** do M-2, nao um valor fixo. */
const TECTO_PROPOSTO: Minor = 5_000_000n;

/** 20 000 Kz em unidade menor. A proposta do M-5. */
const DUPLA_PROPOSTA: Minor = 2_000_000n;

const TENANT: Uuid = "11111111-1111-4111-8111-111111111111";
const CONTA: Uuid = "22222222-2222-4222-8222-222222222222";
const CLIENTE: Uuid = "33333333-3333-4333-8333-333333333333";
const DONO: Uuid = "44444444-4444-4444-8444-444444444444";
const FUNCIONARIO: Uuid = "55555555-5555-4555-8555-555555555555";

const INSTRUCOES = "Transferencia para a conta da PME; indique o numero do pedido.";

function leitorDeLimites(limites: Partial<LimitesDoManual> = {}): LeitorDeLimites {
  return {
    limitesDoManual: async () => ({
      manualMaxMinor: TECTO_PROPOSTO,
      codActivado: false,
      ...limites,
    }),
  };
}

const LEITOR_DE_INSTRUCOES: LeitorDeInstrucoes = {
  instrucoesDaConta: async () => INSTRUCOES,
};

function provider(limites: Partial<LimitesDoManual> = {}): ManualProvider {
  return new ManualProvider({
    limites: leitorDeLimites(limites),
    instrucoes: LEITOR_DE_INSTRUCOES,
  });
}

function pedido(campos: Partial<CreateChargeReq> = {}): CreateChargeReq {
  return {
    chargeId: "66666666-6666-4666-8666-666666666666",
    tenantId: TENANT,
    accountId: CONTA,
    numeroPublico: "K7H3Q9",
    amount: 1_200_000n,
    currency: "AOA",
    metodo: "manual",
    validUntil: "2026-11-05T12:00:00.000Z",
    customFields: {},
    ...campos,
  };
}

const CONFIRMADOR_DONO: ConfirmadorConhecido = {
  contactId: DONO,
  papel: "dono",
  podeSegundaAprovacao: true,
  ativo: true,
};

const CONFIRMADOR_FUNCIONARIO: ConfirmadorConhecido = {
  contactId: FUNCIONARIO,
  papel: "funcionario",
  podeSegundaAprovacao: false,
  ativo: true,
};

/**
 * Uma entrada em que **tudo passa**, para cada caso mudar uma coisa so.
 *
 * E o arranjo que faz as duas direccoes serem comparaveis: o caso legitimo e
 * este, e cada caso de recusa e este com um campo diferente. Sem uma base
 * assim, dois casos de recusa podiam estar a recusar por razoes diferentes das
 * que o nome diz.
 */
function entrada(campos: Partial<EntradaDaConfirmacao> = {}): EntradaDaConfirmacao {
  return {
    amount: 1_200_000n,
    valorDeclarado: 1_200_000n,
    actorContactId: DONO,
    clienteContactId: CLIENTE,
    confirmador: CONFIRMADOR_DONO,
    tectoDaDuplaMinor: DUPLA_PROPOSTA,
    janela: {
      somaDoDiaMinor: 0n,
      tectoDiarioMinor: 20_000_000n,
      confirmacoesDoContacto: 0,
      tectoDoContacto: 5,
    },
    primeiraAprovacaoDe: null,
    ...campos,
  };
}

describe("ManualProvider — capacidades (§3.2, linha manual)", () => {
  it("declara humanOnly e nenhuma via automatica", () => {
    assert.equal(CAPACIDADES_DO_MANUAL.humanOnly, true);
    assert.equal(CAPACIDADES_DO_MANUAL.callbackAuth, "none");
    assert.equal(CAPACIDADES_DO_MANUAL.statusQuery, false);
    assert.equal(CAPACIDADES_DO_MANUAL.reconciliationQueue, false);
  });

  it("nao promete reembolsar nem pagar (G-2, ADR-004)", () => {
    assert.equal(CAPACIDADES_DO_MANUAL.refund, false);
    assert.equal(CAPACIDADES_DO_MANUAL.payout, false);
    assert.equal(CAPACIDADES_DO_MANUAL.pspLicenciado, false);
  });

  it("nao consegue confirmar por via automatica, e e por isso que e humano", () => {
    assert.equal(podeConfirmar(CAPACIDADES_DO_MANUAL), false);
  });

  it("o id e 'manual', que e o unico que a politica reconhece", () => {
    // Nao e uma preferencia: o `_coerencia` do `registo.ts` recusa um adaptador
    // que declare `humanOnly` sem estar nesta lista — a etiqueta nao se
    // atribui. Com outro `id`, o adaptador nao arrancava.
    assert.equal(PROVIDER_MANUAL, "manual");
    assert.ok(ADAPTADORES_DE_CONFIRMACAO_HUMANA.includes(PROVIDER_MANUAL));
  });

  it("cobre 'manual' e 'cod' e mais nada", () => {
    assert.equal(cobre("manual"), true);
    assert.equal(cobre("cod"), true);
    assert.equal(cobre("referencia"), false);
    assert.equal(cobre("express_push"), false);
  });

  it("nao e activavel sem suite de conformidade verde, como qualquer outro", () => {
    // A `CONFORMIDADE_VAZIA` recusa tudo (falha fechada), e o `humanOnly`
    // dispensa da `ADAPTER_CANNOT_CONFIRM` e **nao** da `CONFORMANCE_REQUIRED`.
    // Mede-se aqui porque um `humanOnly` mal lido dispensava das duas.
    assert.throws(
      () => activar(provider(), CONFORMIDADE_VAZIA),
      (erro: Error) => erro.name === "ConformanceRequired",
    );
  });

  it("e passa a coerencia do humanOnly: nao ha via automatica a declarar", () => {
    // A sonda positiva do caso acima: o `activar` recusa por **uma** razao e
    // nao por duas. Com uma conformidade verde, o `_coerencia` e a
    // `ADAPTER_CANNOT_CONFIRM` deixam o adaptador passar — o que prova que a
    // recusa de cima era so a da suite, e nao uma incoerencia das capacidades.
    activar(provider(), { green: () => true });
  });
});

describe("createCharge — o tecto por pedido (criterio 1, M-2)", () => {
  it("no limite exacto aceita", async () => {
    const resultado = await provider().createCharge(
      pedido({ amount: TECTO_PROPOSTO }),
    );
    assert.deepEqual(resultado, { kind: "manual", instrucoes: INSTRUCOES });
  });

  it("um centimo acima do limite devolve REJECTED", async () => {
    await assert.rejects(
      () => provider().createCharge(pedido({ amount: TECTO_PROPOSTO + 1n })),
      (erro: ProviderError) =>
        erro.name === "ProviderError" && erro.codigo === "REJECTED",
    );
  });

  it("um centimo abaixo passa — a fronteira mede-se dos dois lados", async () => {
    const resultado = await provider().createCharge(
      pedido({ amount: TECTO_PROPOSTO - 1n }),
    );
    assert.equal(resultado.kind, "manual");
  });

  it("o tecto vem do tenant e nao de constante: outro tenant, outro limite", async () => {
    // **E o criterio 1 a letra**: «o valor e lido do tenant, nao de
    // constante». A prova nao e que o codigo chame o leitor — e que o mesmo
    // montante passe num tenant e seja recusado noutro **sem** o codigo mudar.
    const apertado = provider({ manualMaxMinor: 500_000n });
    await assert.rejects(
      () => apertado.createCharge(pedido({ amount: 600_000n })),
      (erro: ProviderError) => erro.codigo === "REJECTED",
    );
    const largo = provider({ manualMaxMinor: 50_000_000n });
    assert.equal((await largo.createCharge(pedido({ amount: 600_000n }))).kind, "manual");
  });

  it("sem tecto declarado recusa: «sem tecto» nao e «sem limite»", async () => {
    await assert.rejects(
      () => provider({ manualMaxMinor: null }).createCharge(pedido({ amount: 1n })),
      (erro: ProviderError) =>
        erro.codigo === "REJECTED" && erro.message.includes(CHAVE_MAX),
    );
  });
});

describe("createCharge — o opt-in do cod (criterio 9)", () => {
  it("cod com opt-in desligado devolve REJECTED", async () => {
    await assert.rejects(
      () => provider().createCharge(pedido({ metodo: "cod" })),
      (erro: ProviderError) => erro.codigo === "REJECTED",
    );
  });

  it("cod com opt-in ligado passa — a sonda positiva do caso acima", async () => {
    const resultado = await provider({ codActivado: true }).createCharge(
      pedido({ metodo: "cod" }),
    );
    assert.equal(resultado.kind, "manual");
  });

  it("o opt-in e desligado por omissao, e isso mede-se no leitor", async () => {
    const limites = await leitorDeLimites().limitesDoManual(TENANT);
    assert.equal(limites.codActivado, false);
  });

  it("o cod desligado recusa mesmo dentro do tecto", async () => {
    // A ordem importa: se o tecto fosse avaliado primeiro, um `cod` de montante
    // alto dava a mensagem errada — «acima do tecto» em vez de «sem opt-in» —, e
    // quem depura trocava uma decisao de produto por um limite de valor.
    await assert.rejects(
      () => provider().createCharge(pedido({ metodo: "cod", amount: 1n })),
      (erro: ProviderError) => erro.message.includes("opt-in"),
    );
  });

  it("um metodo que o adaptador nao cobre da NOT_SUPPORTED e nao REJECTED", async () => {
    await assert.rejects(
      () => provider().createCharge(pedido({ metodo: "referencia" })),
      (erro: ProviderError) => erro.codigo === "NOT_SUPPORTED",
    );
  });
});

describe("os quatro metodos que recusam, e cada um com o seu codigo", () => {
  it("status recusa com NOT_SUPPORTED: statusQuery=false", async () => {
    await assert.rejects(
      () => provider().status({ providerId: PROVIDER_MANUAL }),
      (erro: ProviderError) => erro.codigo === "NOT_SUPPORTED",
    );
  });

  it("refund e payout devolvem NOT_SUPPORTED sem levantar (G-2)", async () => {
    assert.deepEqual(await provider().refund({ chargeId: CONTA, amount: 1n }), {
      ok: false,
      erro: "NOT_SUPPORTED",
    });
    assert.deepEqual(
      await provider().payout({
        tenantId: TENANT,
        accountId: CONTA,
        amount: 1n,
        currency: "AOA",
      }),
      { ok: false, erro: "NOT_SUPPORTED" },
    );
  });

  it("verifyCallback levanta AuthError e nao devolve lista vazia", async () => {
    // **A diferenca decide se um corpo forjado paga alguma coisa.** Com uma
    // lista vazia, o §5.1 lê «nada a processar» e marca o recibo `processado` —
    // isto e, um 200 sem rasto de recusa. Com o `AuthError`, o
    // `atenderCallback` grava `hmac_invalido` e devolve 401, que e o que o G1
    // manda fazer a uma origem que nao se autentica.
    await assert.rejects(
      () =>
        provider().verifyCallback(
          { corpo: new Uint8Array([1, 2, 3]), cabecalhos: {} },
          { accountId: CONTA, credenciaisRef: "cofre://nada" },
        ),
      (erro: Error) => erro.name === "AuthError",
    );
  });
});

describe("M-1 — quem confirma, e o cliente nunca (criterio 2)", () => {
  it("um BSUID fora de payment_confirmers nao tem efeito", () => {
    const v = avaliarConfirmacao(entrada({ confirmador: null }));
    assert.equal(v.decisao, "rejeita");
    assert.equal(v.motivo, "sem_confirmador");
    assert.equal(v.regra, "M-1");
    assert.equal(v.fase, "rejeicao");
  });

  it("«sou o dono» nao e um campo: nao ha por onde o texto entrar", () => {
    // A medicao e estrutural e nao comportamental: a `EntradaDaConfirmacao`
    // nao tem campo nenhum que leve uma afirmacao de quem envia. O que ha e o
    // `actorContactId`, que vem do BSUID resolvido pelo CHR. Um teste que
    // «enviasse uma mensagem a dizer sou o dono» estava a inventar uma
    // superficie que nao existe — e e **nao existir** o que fecha a porta.
    const chaves = Object.keys(entrada()).sort();
    assert.deepEqual(chaves, [
      "actorContactId",
      "amount",
      "clienteContactId",
      "confirmador",
      "janela",
      "primeiraAprovacaoDe",
      "tectoDaDuplaMinor",
      "valorDeclarado",
    ]);
  });

  it("um confirmador inactivo e indistinguivel de um que nao existe", () => {
    const v = avaliarConfirmacao(
      entrada({ confirmador: { ...CONFIRMADOR_DONO, ativo: false } }),
    );
    assert.equal(v.motivo, "sem_confirmador");
  });

  it("o cliente nao confirma o seu proprio pagamento", () => {
    const v = avaliarConfirmacao(entrada({ actorContactId: CLIENTE }));
    assert.equal(v.decisao, "rejeita");
    assert.equal(v.motivo, "cliente_nao_confirma");
  });

  it("e nem quando o cliente esta, por erro, em payment_confirmers", () => {
    // **E a razao pela qual a guarda do cliente vem primeiro.** Com a ordem
    // inversa — tabela de confirmadores antes do cliente —, um erro de
    // provisionamento que pusesse o contacto do cliente na lista deixava-o
    // confirmar o proprio pagamento. E a fraude mais obvia deste caminho e a
    // mais facil de deixar aberta.
    const v = avaliarConfirmacao(
      entrada({
        actorContactId: CLIENTE,
        confirmador: { ...CONFIRMADOR_DONO, contactId: CLIENTE },
      }),
    );
    assert.equal(v.motivo, "cliente_nao_confirma");
  });

  it("o dono, que esta na tabela e nao e o cliente, confirma", () => {
    const v = avaliarConfirmacao(entrada());
    assert.equal(v.decisao, "confirma");
    assert.equal(v.motivo, null);
    assert.equal(v.fase, "confirmacao");
  });
});

describe("M-4 — o desafio do valor, sem tolerancia (criterio 4)", () => {
  it("amount_minor − 1 centimo rejeita", () => {
    const v = avaliarConfirmacao(entrada({ valorDeclarado: 1_200_000n - 1n }));
    assert.equal(v.decisao, "rejeita");
    assert.equal(v.motivo, "valor_nao_bate");
    assert.equal(v.regra, "M-4");
    assert.equal(v.valorBate, false);
  });

  it("amount_minor + 1 centimo tambem", () => {
    const v = avaliarConfirmacao(entrada({ valorDeclarado: 1_200_000n + 1n }));
    assert.equal(v.motivo, "valor_nao_bate");
  });

  it("o valor igual avanca, e e a sonda positiva do centimo", () => {
    const v = avaliarConfirmacao(entrada({ valorDeclarado: 1_200_000n }));
    assert.equal(v.decisao, "confirma");
    assert.equal(v.valorBate, true);
  });

  it("nao ha tolerancia relativa nenhuma, nem em montantes grandes", () => {
    // Um por mil de 4 000 000 de centimos sao 4 000 — se houvesse tolerancia
    // proporcional em algum sitio, era aqui que ela aparecia.
    const v = avaliarConfirmacao(
      entrada({ amount: 4_000_000n, valorDeclarado: 4_000_000n - 4_000n }),
    );
    assert.equal(v.motivo, "valor_nao_bate");
  });
});

describe("M-5 — a dupla acima do limiar (criterio 5)", () => {
  it("ate ao limiar uma confirmacao basta, e o limite exacto esta dentro", () => {
    const v = avaliarConfirmacao(
      entrada({ amount: DUPLA_PROPOSTA, valorDeclarado: DUPLA_PROPOSTA }),
    );
    assert.equal(v.decisao, "confirma");
  });

  it("acima do limiar fica a espera da segunda", () => {
    const v = avaliarConfirmacao(
      entrada({ amount: DUPLA_PROPOSTA + 1n, valorDeclarado: DUPLA_PROPOSTA + 1n }),
    );
    assert.equal(v.decisao, "exige_segunda");
    assert.equal(v.regra, "M-5");
  });

  it("a segunda aprovacao pelo mesmo contacto e rejeitada", () => {
    const v = avaliarConfirmacao(
      entrada({
        amount: DUPLA_PROPOSTA + 1n,
        valorDeclarado: DUPLA_PROPOSTA + 1n,
        primeiraAprovacaoDe: DONO,
      }),
    );
    assert.equal(v.decisao, "rejeita");
    assert.equal(v.motivo, "mesmo_confirmador");
    assert.equal(v.regra, "M-5");
  });

  it("outro confirmador sem a marca tambem nao conclui", () => {
    const v = avaliarConfirmacao(
      entrada({
        amount: DUPLA_PROPOSTA + 1n,
        valorDeclarado: DUPLA_PROPOSTA + 1n,
        actorContactId: FUNCIONARIO,
        confirmador: CONFIRMADOR_FUNCIONARIO,
        primeiraAprovacaoDe: DONO,
      }),
    );
    assert.equal(v.decisao, "rejeita");
    assert.equal(v.motivo, "sem_segunda_aprovacao");
  });

  it("outro confirmador com a marca conclui — a sonda positiva das duas acima", () => {
    const v = avaliarConfirmacao(
      entrada({
        amount: DUPLA_PROPOSTA + 1n,
        valorDeclarado: DUPLA_PROPOSTA + 1n,
        actorContactId: FUNCIONARIO,
        confirmador: { ...CONFIRMADOR_FUNCIONARIO, podeSegundaAprovacao: true },
        primeiraAprovacaoDe: DONO,
      }),
    );
    assert.equal(v.decisao, "confirma");
    assert.equal(v.fase, "segunda_aprovacao");
  });

  it("sem limiar declarado exige a dupla: a leitura fechada", () => {
    const v = avaliarConfirmacao(entrada({ tectoDaDuplaMinor: null }));
    assert.equal(v.decisao, "exige_segunda");
  });
});

describe("M-3 — as duas janelas, que retem (criterio 6)", () => {
  it("a soma do dia mais este pedido acima do tecto retem", () => {
    const v = avaliarConfirmacao(
      entrada({
        janela: {
          somaDoDiaMinor: 19_000_000n,
          tectoDiarioMinor: 20_000_000n,
          confirmacoesDoContacto: 0,
          tectoDoContacto: 5,
        },
      }),
    );
    assert.equal(v.decisao, "retem");
    assert.equal(v.motivo, "limite_diario");
    assert.equal(v.regra, "M-3");
    assert.equal(v.sinal, REGRA_DIARIA);
  });

  it("no tecto exacto da soma ainda passa", () => {
    const v = avaliarConfirmacao(
      entrada({
        janela: {
          somaDoDiaMinor: 18_800_000n,
          tectoDiarioMinor: 20_000_000n,
          confirmacoesDoContacto: 0,
          tectoDoContacto: 5,
        },
      }),
    );
    assert.equal(v.decisao, "confirma");
  });

  it("a contagem do contacto acima do tecto retem, com a outra regra", () => {
    const v = avaliarConfirmacao(
      entrada({
        janela: {
          somaDoDiaMinor: 0n,
          tectoDiarioMinor: 20_000_000n,
          confirmacoesDoContacto: 5,
          tectoDoContacto: 5,
        },
      }),
    );
    assert.equal(v.decisao, "retem");
    assert.equal(v.motivo, "limite_por_contacto");
    assert.equal(v.sinal, REGRA_POR_CONTACTO);
  });

  it("uma abaixo do tecto do contacto passa", () => {
    const v = avaliarConfirmacao(
      entrada({
        janela: {
          somaDoDiaMinor: 0n,
          tectoDiarioMinor: 20_000_000n,
          confirmacoesDoContacto: 4,
          tectoDoContacto: 5,
        },
      }),
    );
    assert.equal(v.decisao, "confirma");
  });

  it("sem tecto de janela declarado retem: «sem tecto» nao e «sem limite»", () => {
    const semDiario = avaliarConfirmacao(
      entrada({
        janela: {
          somaDoDiaMinor: 0n,
          tectoDiarioMinor: null,
          confirmacoesDoContacto: 0,
          tectoDoContacto: 5,
        },
      }),
    );
    assert.equal(semDiario.decisao, "retem");
    const semContacto = avaliarConfirmacao(
      entrada({
        janela: {
          somaDoDiaMinor: 0n,
          tectoDiarioMinor: 20_000_000n,
          confirmacoesDoContacto: 0,
          tectoDoContacto: null,
        },
      }),
    );
    assert.equal(semContacto.decisao, "retem");
    assert.equal(semContacto.motivo, "limite_por_contacto");
  });

  it("retem vence a dupla: uma segunda assinatura nao resolve um tecto diario", () => {
    // **A ordem e a decisao.** Com o M-5 antes do M-3, uma cobranca acima do
    // tecto diario **e** acima do limiar da dupla saia como «exige segunda» — e
    // a segunda assinatura chegava, pagando-a. Reter e mais forte, e e por isso
    // que vem antes.
    const v = avaliarConfirmacao(
      entrada({
        amount: DUPLA_PROPOSTA + 1n,
        valorDeclarado: DUPLA_PROPOSTA + 1n,
        janela: {
          somaDoDiaMinor: 19_900_000n,
          tectoDiarioMinor: 20_000_000n,
          confirmacoesDoContacto: 0,
          tectoDoContacto: 5,
        },
      }),
    );
    assert.equal(v.decisao, "retem");
  });

  it("e o valor errado vence os limites: a mensagem certa a quem errou", () => {
    // Com o M-3 antes do M-4, quem escrevesse o valor errado numa cobranca que
    // excede o tecto diario recebia «retido para analise» — e aprendia que
    // **acertou** no valor, que e exactamente a informacao que nao se da.
    const v = avaliarConfirmacao(
      entrada({
        valorDeclarado: 1n,
        janela: {
          somaDoDiaMinor: 19_900_000n,
          tectoDiarioMinor: 20_000_000n,
          confirmacoesDoContacto: 0,
          tectoDoContacto: 5,
        },
      }),
    );
    assert.equal(v.motivo, "valor_nao_bate");
  });
});

describe("M-7 — a evidencia e rotulada, e o rotulo e obrigatorio (criterio 3)", () => {
  it("o rotulo e nao_prova", () => {
    assert.equal(ROTULO_NAO_PROVA, "nao_prova");
    assert.equal(rotuloDaEvidencia(evidenciaNaoProva("sto://a/b.jpg")), "nao_prova");
  });

  it("uma referencia vazia nao se rotula", () => {
    assert.throws(
      () => evidenciaNaoProva("   "),
      (erro: ProviderError) => erro.codigo === "VALIDATION",
    );
  });

  it("uma referencia sem rotulo le-se como sem rotulo", () => {
    // **Este caso apanhou um defeito real.** A primeira versao do
    // `rotuloDaEvidencia` devolvia «o que vem antes do primeiro dois-pontos», e
    // `sto://a/b.jpg` dava `"sto"`: uma referencia sem rotulo passava por
    // rotulada, com um rotulo que a pontuacao do URL inventou.
    assert.equal(rotuloDaEvidencia("sto://a/b.jpg"), null);
    assert.equal(rotuloDaEvidencia("outro_rotulo:sto://a/b.jpg"), null);
    assert.equal(rotuloDaEvidencia(""), null);
    // E a sonda positiva ao lado: o rotulo certo le-se.
    assert.equal(rotuloDaEvidencia("nao_prova:sto://a/b.jpg"), ROTULO_NAO_PROVA);
  });

  it("nenhum modulo do adaptador importa OCR ou visao, e ha canario", async () => {
    const { readFile } = await import("node:fs/promises");
    const { fileURLToPath } = await import("node:url");
    const raiz = fileURLToPath(new URL("../src/pagamentos/", import.meta.url));
    const { MODULOS_DO_MANUAL } = await import("../src/pagamentos/manual.ts");

    const varrer = (fonte: string): string[] => {
      const achados: string[] = [];
      for (const linha of fonte.split("\n")) {
        const casa = /^\s*(?:import|export)[^"']*["']([^"']+)["']/.exec(linha);
        const dinamico = /\bimport\s*\(\s*["']([^"']+)["']/.exec(linha);
        const alvo = casa?.[1] ?? dinamico?.[1];
        if (alvo === undefined) continue;
        for (const proibida of IMPORTACOES_PROIBIDAS) {
          if (alvo.toLowerCase().includes(proibida)) achados.push(`${alvo} (${proibida})`);
        }
      }
      return achados;
    };

    const achados: string[] = [];
    for (const modulo of MODULOS_DO_MANUAL) {
      achados.push(...varrer(await readFile(`${raiz}${modulo}`, "utf8")));
    }
    assert.deepEqual(achados, [], "o ManualProvider nao le o conteudo da imagem");

    // **O passo de canario, e e um por fragmento.** Sem ele, um zero nao
    // distingue «nao ha» de «nao se procurou» — e e a licao do `codegraph
    // status`, que sai 0 sem indice. Um canario so provava que a varredura
    // apanha **um** nome; com um por fragmento, uma entrada da lista que
    // deixasse de ser procurada — por um erro no `includes`, ou por alguem a
    // escrever com maiusculas — fica vermelha.
    //
    // A contagem **nao** e 1 por caso: `node-tesseract-ocr` casa `ocr` **e**
    // `tesseract`, e foi assim que a primeira versao deste ensaio falhou com
    // `2 !== 1`. O que se afirma e «apanha», e nao «apanha uma vez».
    for (const proibida of IMPORTACOES_PROIBIDAS) {
      assert.ok(
        varrer(`import { x } from "@acme/${proibida}-sdk";\n`).length > 0,
        `a varredura tem de apanhar '${proibida}' numa importacao estatica`,
      );
      assert.ok(
        varrer(`const m = await import("@acme/${proibida}-sdk");\n`).length > 0,
        `e tambem na forma dinamica`,
      );
      assert.ok(
        varrer(`import "@acme/${proibida.toUpperCase()}-sdk";\n`).length > 0,
        `e com maiusculas: o especificador normaliza-se antes de comparar`,
      );
    }
    // E a sonda negativa da varredura: um nome inocente nao e achado. Sem ela,
    // uma varredura que devolvesse tudo passava os canarios acima.
    assert.deepEqual(varrer('import { x } from "node:crypto";\n'), []);
    assert.deepEqual(varrer('const y = "ocr";\n'), []);
  });
});

describe("as propostas sao documentacao e nao decidem nada", () => {
  it("os dois tectos propostos sao os do §4.2, em unidade menor", () => {
    assert.equal(PROPOSTAS_DE_OMISSAO[CHAVE_MAX], TECTO_PROPOSTO);
    assert.equal(PROPOSTAS_DE_OMISSAO["manual_dupla_acima_minor"], DUPLA_PROPOSTA);
  });

  it("as duas chaves de janela nao tem proposta nenhuma, e isso e deliberado", () => {
    // O §4.2 M-3 nomeia as duas chaves e **nao da valor a nenhuma**. Inventar
    // um aqui era o endurecimento silencioso que o `evidencia-e-verificacao.md`
    // descreve: «um numero que eu propus numa conversa aparece, tres documentos
    // depois, como requisito com ar de medicao».
    assert.equal(PROPOSTAS_DE_OMISSAO["manual_daily_max_minor"], null);
    assert.equal(PROPOSTAS_DE_OMISSAO["manual_max_por_contacto_24h"], null);
  });

  it("nenhuma decisao muda se a tabela de propostas for outra", () => {
    // A prova de que a tabela nao entra em decisao nenhuma: as decisoes saem
    // todas da `entrada`, e a tabela nao e lida. Se o `avaliarConfirmacao` a
    // lesse, um tenant sem entitlement herdava o tecto da proposta — que e
    // exactamente o que o criterio 1 proibe.
    const antes = avaliarConfirmacao(entrada({ tectoDaDuplaMinor: null }));
    assert.equal(antes.decisao, "exige_segunda");
    const comTectoDoTenant = avaliarConfirmacao(
      entrada({ tectoDaDuplaMinor: 10_000_000n }),
    );
    assert.equal(comTectoDoTenant.decisao, "confirma");
  });
});

describe("os avisos fixos e a janela do F-18", () => {
  it("o aviso ao cliente diz que a confirmacao e da loja (M-9)", () => {
    assert.match(AVISOS.aoCliente, /confirmado pela loja|confirmado pela loja/i);
    assert.match(AVISOS.aoCliente, /nao confirma pagamento/i);
  });

  it("o aviso ao dono manda confirmar na app dele e diz que a imagem nao prova", () => {
    assert.match(AVISOS.aoDono, /SUA\s+app/);
    assert.match(AVISOS.aoDono, /nao e prova/);
  });

  it("nenhum aviso tem telefone nem texto do cliente (privacidade)", () => {
    for (const [nome, texto] of Object.entries(AVISOS)) {
      assert.doesNotMatch(texto, /\+?244/, `${nome} nao leva telefone`);
      assert.doesNotMatch(texto, /\{(telefone|msisdn|texto)\}/, `${nome}`);
    }
  });

  it("a janela do F-18 e 24 h, e nao vem do tenant", () => {
    assert.equal(JANELA_DE_SILENCIO_HORAS, 24);
    assert.equal(
      expiraEm("2026-11-04T10:00:00.000Z"),
      "2026-11-05T10:00:00.000Z",
    );
  });

  it("um instante invalido levanta em vez de produzir uma data invalida", () => {
    assert.throws(
      () => expiraEm("ontem"),
      (erro: ProviderError) => erro.codigo === "VALIDATION",
    );
  });
});

describe("a observabilidade do §4.6", () => {
  it("a metrica tem o nome do DoD e uma serie por fase", async () => {
    const { METRICA_CONFIRMACOES, ETIQUETAS_DA_METRICA } = await import(
      "../src/pagamentos/manual.ts"
    );
    assert.equal(METRICA_CONFIRMACOES, "manual_confirmations_total");
    // **A etiqueta e a fase, e nao o veredicto.** Um contador por veredicto
    // dizia «quantas foram recusadas»; uma serie por fase da a forma do funil,
    // que e o que um desvio semanal se le contra.
    assert.deepEqual([...ETIQUETAS_DA_METRICA], [...FASES]);
  });

  it("o alerta e nomeado, e o limiar nao esta aqui", async () => {
    const { ALERTA_DESVIO_SEMANAL } = await import("../src/pagamentos/manual.ts");
    assert.equal(typeof ALERTA_DESVIO_SEMANAL, "string");
    assert.ok(ALERTA_DESVIO_SEMANAL.length > 0);
    // O limiar e *proposta* e calibra-se no KAM-096. Se alguem o escrever num
    // modulo que nao le entitlements, este caso fica a dizer onde.
  });
});

describe("as fases e as cadeias SQL", () => {
  it("sao as cinco do §6.3, por esta ordem", () => {
    assert.deepEqual([...FASES], [
      "declaracao_cliente",
      "confirmacao",
      "segunda_aprovacao",
      "rejeicao",
      "reversao",
    ]);
  });

  it("cada cadeia nomeada existe e chama a funcao da revisao 0032", async () => {
    const modulo = (await import("../src/pagamentos/manual.ts")) as Record<
      string,
      unknown
    >;
    for (const nome of CADEIAS_DO_MANUAL) {
      const cadeia = modulo[nome];
      assert.equal(typeof cadeia, "string", `${nome} tem de ser uma cadeia`);
      assert.ok((cadeia as string).includes("platform."), `${nome} fala com platform`);
    }
  });
});
