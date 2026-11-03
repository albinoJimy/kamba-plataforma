/**
 * O módulo `orders` sem base de dados: o grafo, os payloads e a `transition`.
 *
 * «Unit: grafo de estados, derivação de `numero_publico`, regras de
 * reconciliação» — os Testes Requeridos do bloco. Dois dos três estão aqui; a
 * derivação do `numero_publico` **não**, e a razão é que ela não existe em
 * TypeScript: é `platform.order_numero_publico()`, e mede-se contra o motor em
 * `db/tests_encomendas/test_invariantes.py` (dez mil gerações, o alfabeto de
 * Crockford e os trinta e dois símbolos). Reimplementá-la aqui para a poder
 * medir aqui era criar uma segunda fonte para o número que o PAY mostra ao
 * cliente.
 *
 * O que está aqui é o que não precisa de PostgreSQL: o predicado do grafo sobre
 * uma lista de transições, a forma dos cinco payloads contra os contratos
 * publicados, e as decisões que a `transition` toma **antes** de chegar à base.
 * O que precisa — os três *triggers*, o CAS sob concorrência, a RLS, o registo
 * *append-only* — está em `db/tests_encomendas/`, contra um PostgreSQL real.
 *
 * **O cliente falso não é uma base falsa.** Ele devolve as linhas que o teste
 * lhe der e grava o SQL que recebeu: serve para medir *que decisão* o módulo
 * toma e *que texto* envia, nunca para afirmar que o texto funciona. Essa
 * afirmação é do gate 8, que corre as mesmas constantes contra o motor.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { validarPayload } from "@kamba/core-ts/eventos";

import {
  EMISSOES,
  SQL_TRANSITAR,
  TABELA_DAS_DIVERGENCIAS,
  aplicar,
  pagamentoAutenticado,
  payloadDeCancelada,
  payloadDeCriada,
  payloadDeEntregue,
  payloadDeExpirada,
  payloadDePaga,
  reconciliar,
  transicaoPermitida,
  transition,
  type Encomendas,
  type Fotografia,
  type LinhaDaEncomenda,
  type Transicao,
} from "../src/orders/index.ts";

/** As doze do núcleo, como a revisão `0030` as semeia. */
const NUCLEO: readonly Transicao[] = [
  { de: "criada", para: "aguarda_pagamento", flag: null },
  { de: "criada", para: "cancelada", flag: null },
  { de: "aguarda_pagamento", para: "paga", flag: null },
  { de: "aguarda_pagamento", para: "pendente_confirmacao", flag: null },
  { de: "aguarda_pagamento", para: "expirada", flag: null },
  { de: "pendente_confirmacao", para: "paga", flag: null },
  { de: "pendente_confirmacao", para: "aguarda_pagamento", flag: null },
  { de: "expirada", para: "aguarda_pagamento", flag: null },
  { de: "expirada", para: "cancelada", flag: null },
  { de: "paga", para: "entregue", flag: null },
  { de: "paga", para: "em_entrega", flag: "COM_DELIVERY_ENABLED" },
  { de: "em_entrega", para: "entregue", flag: "COM_DELIVERY_ENABLED" },
];

const LINHAS: readonly LinhaDaEncomenda[] = [
  {
    sku: "arroz-5kg",
    nome: "Arroz 5 kg",
    qty: 1,
    precoMinor: 1_250_000n,
    precoTipo: "fixo",
    origemPreco: "offer_terms",
  },
];

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const ENCOMENDA = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50";
const CONTACTO = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";

/** O cliente falso: devolve o que se lhe der e guarda o que recebeu. */
function clienteFalso(respostas: Record<string, unknown>[][] = []) {
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  let n = 0;
  return {
    vistas,
    cliente: {
      async query(sql: string, valores: readonly unknown[] = []) {
        vistas.push({ sql, valores });
        const rows = respostas[n++] ?? [];
        // O `rowCount` vai porque o `ClienteSql` o declara — e declara-o porque
        // o `checkCeiling` do `ten` o exige. Ver a nota do `contrato.ts`.
        return { rows, rowCount: rows.length };
      },
    },
  };
}

/** O `Encomendas` falso, com o `repo` e a porta estreita separados. */
function encomendas(
  respostasDoRepo: Record<string, unknown>[][],
  respostasDaPorta: Record<string, unknown>[][] = [[{ de: "criada", para: "aguarda_pagamento", flag: null }]],
  actorKind: "agente" | "dono" | "sistema" | "ops" = "ops",
): { e: Encomendas; repo: ReturnType<typeof clienteFalso>; porta: ReturnType<typeof clienteFalso> } {
  const repo = clienteFalso(respostasDoRepo);
  const porta = clienteFalso(respostasDaPorta);
  const inseridos: Record<string, unknown>[] = [];
  return {
    repo,
    porta,
    e: {
      ctx: { tenantId: TENANT, actor: { kind: actorKind, id: "a-1" }, traceId: "t-1" },
      repo: {
        tenantId: TENANT,
        async noTenant(sql: string, valores: readonly unknown[] = []) {
          const { rows } = await repo.cliente.query(sql, valores);
          return rows;
        },
        async inserirNoTenant(insercao) {
          inseridos.push({ ...insercao.valores });
          return [];
        },
      },
      emitir: porta.cliente,
      agora: () => new Date("2026-11-03T10:00:00.000Z"),
    },
  };
}

// ------------------------------------------------------------------- o grafo

test("o predicado do grafo aceita as doze do núcleo", () => {
  for (const t of NUCLEO) {
    const ligadas = t.flag === null ? [] : [t.flag];
    assert.equal(
      transicaoPermitida(NUCLEO, t.de, t.para, ligadas),
      true,
      `${t.de} -> ${t.para}`,
    );
  }
});

test("as duas da bandeira não passam com ela desligada", () => {
  assert.equal(transicaoPermitida(NUCLEO, "paga", "em_entrega", []), false);
  assert.equal(transicaoPermitida(NUCLEO, "em_entrega", "entregue", []), false);
});

test("um par que não está no grafo não passa, com bandeira ou sem ela", () => {
  // Os quatro estados do KAM-050 não são destino de nada no núcleo.
  for (const para of ["em_disputa", "entrega_falhada", "reembolsada"] as const) {
    assert.equal(transicaoPermitida(NUCLEO, "paga", para, []), false);
    assert.equal(
      transicaoPermitida(NUCLEO, "paga", para, ["COM_DELIVERY_ENABLED"]),
      false,
      "a bandeira liga as linhas que existem, não cria linhas",
    );
  }
});

test("o pagamento tardio e a disputa não estão no núcleo (são KAM-050)", () => {
  assert.equal(transicaoPermitida(NUCLEO, "expirada", "paga", []), false);
  assert.equal(transicaoPermitida(NUCLEO, "paga", "reembolso_pendente", []), false);
  assert.equal(transicaoPermitida(NUCLEO, "entregue", "reembolso_pendente", []), false);
});

// ----------------------------------------------------------------- payloads

test("os cinco payloads passam o `validarPayload` dos contratos publicados", () => {
  const casos: [string, number, Record<string, unknown>][] = [
    [
      EMISSOES.criada.tipo,
      EMISSOES.criada.versao,
      payloadDeCriada(
        ENCOMENDA,
        CONTACTO,
        "K7H3Q9",
        "pme",
        1_250_000n,
        "AOA",
        "levantamento",
        LINHAS,
        null,
      ),
    ],
    [
      EMISSOES.paga.tipo,
      EMISSOES.paga.versao,
      payloadDePaga(ENCOMENDA, 1_250_000n, "AOA", "provider_autenticado"),
    ],
    [
      EMISSOES.expirada.tipo,
      EMISSOES.expirada.versao,
      payloadDeExpirada(ENCOMENDA, "2026-11-04T14:03:11.482Z"),
    ],
    [EMISSOES.cancelada.tipo, EMISSOES.cancelada.versao, payloadDeCancelada(ENCOMENDA, "ttl")],
    [
      EMISSOES.entregue.tipo,
      EMISSOES.entregue.versao,
      payloadDeEntregue(ENCOMENDA, "cliente"),
    ],
  ];
  for (const [tipo, versao, payload] of casos) {
    validarPayload(tipo, versao, payload);
  }
});

test("o `order.created` projecta as linhas e não despeja o snapshot", () => {
  const payload = payloadDeCriada(
    ENCOMENDA,
    CONTACTO,
    "K7H3Q9",
    "pme",
    1_250_000n,
    "AOA",
    "levantamento",
    LINHAS,
    null,
  );
  assert.deepEqual(payload["linhas"], [
    { sku: "arroz-5kg", qty: 1, preco_minor: 1_250_000 },
  ]);
  // O `nome` fica de fora: é texto que o dono escreveu, e o contrato tem
  // `additionalProperties: false` — despejar o snapshot era um envelope
  // recusado.
  assert.equal(JSON.stringify(payload).includes("Arroz"), false);
});

test("o `expira_at` vai ausente e não nulo quando não há reserva", () => {
  const payload = payloadDeCriada(
    ENCOMENDA,
    CONTACTO,
    "K7H3Q9",
    "pme",
    1n,
    "AOA",
    "levantamento",
    LINHAS,
    null,
  );
  assert.equal("expira_at" in payload, false);
});

test("um valor acima do inteiro seguro lança em vez de perder precisão", () => {
  assert.throws(
    () => payloadDePaga(ENCOMENDA, 2n ** 60n, "AOA", "provider_autenticado"),
    RangeError,
  );
});

// -------------------------------------------------------------- a transição

test("`paga` exige actor `sistema`, causa do PAY e `evento_id`", () => {
  const ctx = { tenantId: TENANT, actor: { kind: "sistema" as const, id: "s" }, traceId: "t" };
  assert.equal(
    pagamentoAutenticado(ctx, { causa: "payment.confirmed", eventoId: "ev-1" }),
    true,
  );
  assert.equal(
    pagamentoAutenticado(ctx, { causa: "payment.confirmed", eventoId: null }),
    false,
    "sem evento é recusado — é o critério 3 à letra",
  );
  assert.equal(
    pagamentoAutenticado(ctx, { causa: "reconciliacao", eventoId: "ev-1" }),
    false,
    "nem a reconciliação: o espelho não se auto-autoriza",
  );
  assert.equal(
    pagamentoAutenticado(
      { ...ctx, actor: { kind: "dono", id: "d" } },
      { causa: "payment.confirmed", eventoId: "ev-1" },
    ),
    false,
    "actor `dono`, mesmo com evento: quem fala pelo PAY é o sistema",
  );
});

test("uma transição para `paga` por `dono` é recusada antes de chegar à base", async () => {
  const { e, repo } = encomendas([], [], "dono");
  const r = await transition(e, {
    orderId: ENCOMENDA,
    para: "paga",
    expectedVersion: 1,
    causa: { causa: "dono_declara" },
  });
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(repo.vistas, [], "nem a leitura chegou a sair");
});

test("uma versão antiga devolve `conflito` com o estado relido, e não erro", async () => {
  // **O actor é `sistema`**, e não é detalhe: o destino é `paga`, e com um actor
  // `ops` a recusa vinha do critério 3 — `VALIDATION_ERROR` antes de a leitura
  // sair — e o ensaio media a guarda do pagamento em vez do conflito de versão.
  // Medido no *gate* 4, que o apanhou vermelho.
  const { e } = encomendas(
    [
      [
        {
          id: ENCOMENDA,
          numero_publico: "K7H3Q9",
          estado: "aguarda_pagamento",
          version: 5,
          total_minor: "1250000",
          currency: "AOA",
          expira_at: null,
          paga_via: null,
          entrega_confirmada_por: null,
        },
      ],
    ],
    [],
    "sistema",
  );
  const r = await transition(e, {
    orderId: ENCOMENDA,
    para: "paga",
    expectedVersion: 1,
    causa: { causa: "payment.confirmed", eventoId: "ev-1" },
  });
  assert.equal(r.tipo, "conflito");
  if (r.tipo !== "conflito") return;
  assert.equal(r.estado.version, 5);
  assert.equal(r.estado.estado, "aguarda_pagamento");
});

test("o CAS sem linhas relê e devolve `conflito` (nunca força)", async () => {
  const linha = {
    id: ENCOMENDA,
    numero_publico: "K7H3Q9",
    estado: "criada",
    version: 1,
    total_minor: "1250000",
    currency: "AOA",
    expira_at: null,
    paga_via: null,
    entrega_confirmada_por: null,
  };
  const { e, repo } = encomendas([
    [linha], // SQL_LER
    [], // SQL_TRANSITAR: zero linhas, outra ganhou
    [{ ...linha, estado: "aguarda_pagamento", version: 2 }], // a releitura
  ]);
  const r = await transition(e, {
    orderId: ENCOMENDA,
    para: "aguarda_pagamento",
    expectedVersion: 1,
    causa: { causa: "charge.issued" },
  });
  assert.equal(r.tipo, "conflito");
  if (r.tipo !== "conflito") return;
  assert.equal(r.estado.version, 2);
  // Três idas ao repo e **não** quatro: ler, tentar, reler. Uma quarta era
  // uma segunda tentativa, que é o que o §6.2 chama «forçar».
  assert.equal(repo.vistas.length, 3);
  assert.equal(repo.vistas[1]?.sql, SQL_TRANSITAR);
});

test("`entregue` sem quem confirmou é recusado antes da base", async () => {
  const { e, repo } = encomendas([]);
  const r = await transition(e, {
    orderId: ENCOMENDA,
    para: "entregue",
    expectedVersion: 1,
    causa: { causa: "levantamento" },
  });
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(repo.vistas, []);
});

test("`pendente_confirmacao` lê o tecto manual do entitlement, e recusa sem ele", async () => {
  const linha = {
    id: ENCOMENDA,
    numero_publico: "K7H3Q9",
    estado: "aguarda_pagamento",
    version: 2,
    total_minor: "1250000",
    currency: "AOA",
    expira_at: null,
    paga_via: null,
    entrega_confirmada_por: null,
  };
  // A porta estreita responde ao `SQL_TECTO` do `ten`: `tecto` nulo é «nenhum
  // módulo activo declara a chave», e isso **recusa** — «sem tecto» não quer
  // dizer «sem limite» (critério 2 do KAM-009).
  const semTecto = encomendas([[linha]], [[{ tecto: null }]], "dono");
  assert.deepEqual(
    await transition(semTecto.e, {
      orderId: ENCOMENDA,
      para: "pendente_confirmacao",
      expectedVersion: 2,
      causa: { causa: "dono_declara" },
    }),
    { tipo: "erro", erro: "VALIDATION_ERROR" },
  );

  // Com tecto acima do total, passa — e o grafo é consultado depois do tecto.
  const comTecto = encomendas(
    [[linha], [{ ...linha, estado: "pendente_confirmacao", version: 3 }]],
    [
      [{ tecto: "5000000" }],
      [{ de: "aguarda_pagamento", para: "pendente_confirmacao", flag: null }],
    ],
    "dono",
  );
  const r = await transition(comTecto.e, {
    orderId: ENCOMENDA,
    para: "pendente_confirmacao",
    expectedVersion: 2,
    causa: { causa: "dono_declara" },
  });
  assert.equal(r.tipo, "ok");

  // E com o total acima do tecto, recusa.
  const acima = encomendas(
    [[{ ...linha, total_minor: "9000000" }]],
    [[{ tecto: "5000000" }]],
    "dono",
  );
  assert.deepEqual(
    await transition(acima.e, {
      orderId: ENCOMENDA,
      para: "pendente_confirmacao",
      expectedVersion: 2,
      causa: { causa: "dono_declara" },
    }),
    { tipo: "erro", erro: "VALIDATION_ERROR" },
  );
});

test("uma encomenda que não existe dá `NOT_FOUND`", async () => {
  const { e } = encomendas([[]]);
  const r = await transition(e, {
    orderId: ENCOMENDA,
    para: "cancelada",
    expectedVersion: 1,
    causa: { causa: "cliente_cancela" },
  });
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
});

test("um `orderId` que não é UUID não chega à base", async () => {
  const { e, repo } = encomendas([]);
  const r = await transition(e, {
    orderId: "nao-e-uuid",
    para: "cancelada",
    expectedVersion: 1,
    causa: { causa: "cliente_cancela" },
  });
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(repo.vistas, []);
});

// ---------------------------------------------------------- a reconciliação

/** Uma fotografia em que as duas pontas concordam. */
function fotografiaConsistente(): Fotografia {
  return {
    registo: [
      {
        intentKey: "ik-1",
        registoId: "ord_1",
        estado: "aguarda_pagamento",
        totalMinor: 1_250_000n,
        // **Com preço**: sem ele, a regra 3 não via a divergência que é só de
        // dinheiro. Ver a nota do `EncomendaNoRegisto`.
        linhas: [{ sku: "arroz-5kg", qty: 1, precoMinor: 1_250_000n }],
      },
    ],
    espelho: [
      {
        orderId: ENCOMENDA,
        intentKey: "ik-1",
        medusaOrderId: "ord_1",
        estado: "aguarda_pagamento",
        version: 2,
        totalMinor: 1_250_000n,
        linhas: LINHAS,
      },
    ],
    reservas: [{ orderId: ENCOMENDA, sku: "arroz-5kg" }],
  };
}

test("duas pontas que concordam não dão divergência nenhuma", () => {
  assert.deepEqual(reconciliar(fotografiaConsistente()), []);
});

test("regra 1: encomenda no Registo sem linha no espelho", () => {
  const foto = { ...fotografiaConsistente(), espelho: [], reservas: [] };
  const divergencias = reconciliar(foto);
  assert.equal(divergencias.length, 1);
  assert.equal(divergencias[0]?.tipo, "orfao_no_registo");
  assert.equal(divergencias[0]?.orderId, null, "o espelho ainda não tem linha");
});

test("regra 2: espelho com id do Registo que o Registo não tem", () => {
  const base = fotografiaConsistente();
  const foto: Fotografia = { ...base, registo: [] };
  const tipos = reconciliar(foto).map((d) => d.tipo);
  assert.ok(tipos.includes("espelho_sem_encomenda"));
  const critica = reconciliar(foto).find((d) => d.tipo === "espelho_sem_encomenda");
  assert.equal(critica?.detalhe["critico"], true, "alerta crítico e não correcção");
});

test("regra 3: total ou linhas divergentes — vence o `lines_snapshot`", () => {
  const base = fotografiaConsistente();
  const foto: Fotografia = {
    ...base,
    registo: [{ ...base.registo[0]!, totalMinor: 999n }],
  };
  const divergencia = reconciliar(foto).find((d) => d.tipo === "divergencia_de_linhas");
  assert.equal(divergencia?.detalhe["vence"], "lines_snapshot");
  assert.equal(divergencia?.detalhe["total_no_espelho"], "1250000");
});

test("regra 3 também morde quando só as linhas divergem", () => {
  const base = fotografiaConsistente();
  const foto: Fotografia = {
    ...base,
    registo: [
      {
        ...base.registo[0]!,
        linhas: [{ sku: "arroz-5kg", qty: 7, precoMinor: 1_250_000n }],
      },
    ],
  };
  const tipos = reconciliar(foto).map((d) => d.tipo);
  assert.ok(
    tipos.includes("divergencia_de_linhas"),
    "o total igual com as linhas diferentes é o caso que uma comparação só de totais deixa passar",
  );
});

test("regra 3 morde quando só o preço difere e o total coincide", () => {
  // **O achado 9 da revisão adversarial.** Duas linhas com o mesmo `sku` e a
  // mesma `qty`, preços unitários diferentes e um total que coincide passavam
  // sem divergência — e a regra 3 é a que decide **em dinheiro** a favor do
  // `lines_snapshot`.
  const base = fotografiaConsistente();
  const foto: Fotografia = {
    ...base,
    registo: [
      {
        ...base.registo[0]!,
        linhas: [{ sku: "arroz-5kg", qty: 1, precoMinor: 999_999n }],
      },
    ],
  };
  assert.equal(
    reconciliar(foto).some((d) => d.tipo === "divergencia_de_linhas"),
    true,
    "o total é o mesmo e o preço da linha não: é divergência de linhas",
  );
});

test("regra 4 não dá falso positivo em `pendente_confirmacao`", () => {
  // **O achado 8 da revisão adversarial**, e era uma inconsistência com a
  // própria revisão `0030`: o índice parcial da expiração diz que **dois**
  // estados têm reserva viva, e o grafo tem `pendente_confirmacao →
  // aguarda_pagamento`. Com um estado só, toda encomenda em
  // `pendente_confirmacao` com reserva produzia uma divergência — contra uma
  // métrica que é «abertas > 5 min = 0».
  const base = fotografiaConsistente();
  const foto: Fotografia = {
    ...base,
    registo: [{ ...base.registo[0]!, estado: "pendente_confirmacao" }],
    espelho: [{ ...base.espelho[0]!, estado: "pendente_confirmacao" }],
  };
  assert.deepEqual(
    reconciliar(foto).filter((d) => d.tipo === "reserva_sem_encomenda"),
    [],
  );
});

test("regra 4: reserva sem encomenda em `aguarda_pagamento`, e o inverso", () => {
  const base = fotografiaConsistente();
  const semReserva: Fotografia = { ...base, reservas: [] };
  assert.equal(
    reconciliar(semReserva).find((d) => d.tipo === "reserva_sem_encomenda")?.detalhe[
      "sentido"
    ],
    "estado_sem_reserva",
    "«ou vice-versa» é metade da regra, e é a metade que se deixa cair",
  );

  const paga: Fotografia = {
    ...base,
    registo: [{ ...base.registo[0]!, estado: "paga" }],
    espelho: [{ ...base.espelho[0]!, estado: "paga" }],
  };
  assert.equal(
    reconciliar(paga).find((d) => d.tipo === "reserva_sem_encomenda")?.detalhe[
      "sentido"
    ],
    "reserva_sem_estado",
  );
});

test("regra 5: estado divergente — vence `orders_mirror`", () => {
  const base = fotografiaConsistente();
  const foto: Fotografia = {
    ...base,
    registo: [{ ...base.registo[0]!, estado: "cancelada" }],
  };
  const divergencia = reconciliar(foto).find((d) => d.tipo === "estado_divergente");
  assert.equal(divergencia?.detalhe["vence"], "orders_mirror");
  assert.equal(divergencia?.detalhe["estado_no_espelho"], "aguarda_pagamento");
});

test("o Registo sem estado projectado não dá divergência de estado", () => {
  const base = fotografiaConsistente();
  const foto: Fotografia = { ...base, registo: [{ ...base.registo[0]!, estado: null }] };
  assert.equal(
    reconciliar(foto).some((d) => d.tipo === "estado_divergente"),
    false,
    "«o Registo não projecta nada» não é «o Registo discorda»",
  );
});

test("`aplicar` abre uma linha por divergência, e não corrige nada", async () => {
  // **O achado 2 da revisão adversarial**: `grep aplicar` nos ensaios devolvia
  // zero, pelo que o ramo morto do `corrigir` não era visível de lado nenhum.
  // O que `aplicar` faz hoje é abrir a divergência — e nenhuma das cinco regras
  // tem correcção local, com o credor de cada uma escrito no módulo.
  const base = fotografiaConsistente();
  const foto: Fotografia = { ...base, espelho: [], reservas: [] };
  const divergencias = reconciliar(foto);
  assert.equal(divergencias.length, 1);

  const inseridos: Record<string, unknown>[] = [];
  const e: Encomendas = {
    ctx: { tenantId: TENANT, actor: { kind: "sistema", id: "s" }, traceId: "t" },
    repo: {
      tenantId: TENANT,
      async noTenant() {
        throw new Error("o `aplicar` nao le nem actualiza nada");
      },
      async inserirNoTenant(insercao) {
        inseridos.push({ tabela: insercao.tabela, ...insercao.valores });
        return [{ id: "issue-1" }];
      },
    },
    emitir: {
      async query() {
        throw new Error("o `aplicar` nao chama funcao nenhuma");
      },
    },
  };

  const feitas = await aplicar(e, divergencias);
  assert.deepEqual(
    feitas.map((f) => f.issueId),
    ["issue-1"],
  );
  assert.equal(inseridos.length, 1);
  assert.equal(inseridos[0]?.["tabela"], TABELA_DAS_DIVERGENCIAS);
  assert.equal(inseridos[0]?.["tipo"], "orfao_no_registo");
  assert.equal(inseridos[0]?.["order_id"], null);
});

test("nenhum `detalhe` de divergência leva dado pessoal", () => {
  const base = fotografiaConsistente();
  const foto: Fotografia = {
    ...base,
    registo: [{ ...base.registo[0]!, estado: "cancelada", totalMinor: 1n }],
    espelho: [{ ...base.espelho[0]!, medusaOrderId: "ord_fantasma" }],
    reservas: [],
  };
  const proibidos = ["telefone", "nome", "morada", "texto", "email", "msisdn", "bsuid"];
  for (const divergencia of reconciliar(foto)) {
    for (const chave of Object.keys(divergencia.detalhe)) {
      for (const proibido of proibidos) {
        assert.equal(
          chave.includes(proibido),
          false,
          `${divergencia.tipo}.${chave}`,
        );
      }
    }
  }
});
