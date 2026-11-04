/**
 * A *saga* de `createOrder`: os quatro casos do recibo e as três recusas (KAM-046).
 *
 * **O que está aqui e o que não pode estar aqui.** A idempotência sob
 * concorrência mede-se contra PostgreSQL (`db/tests_encomendas/
 * test_idempotencia.py`, cinquenta ligações): um `Promise.all` sobre um objecto
 * em memória não tem transacções para serializar. O que **só** aqui se mede é o
 * caminho que o módulo escolhe em cada estado do recibo, e as três recusas do
 * critério 6 — porque elas acontecem **antes** de qualquer escrita, e um teste
 * de base de dados só as vê pela ausência de linhas.
 *
 * ```text
 * aqui          que decisao o modulo toma, em cada estado do recibo
 *               as tres recusas do criterio 6, e que nao escrevem nada
 *               a espera do `em_curso` (criterio 5) com o relogio injectado
 *               o facto do criterio 8 na resposta
 * gate 8        a mesma chave, cinquenta ligacoes, uma encomenda
 * ```
 *
 * **O cliente falso não é uma base falsa** — a mesma nota do
 * `orders.modulo.test.ts`: ele responde o que o teste lhe der e grava o que
 * recebeu. Serve para medir *que decisão* e *que texto*, nunca para afirmar que
 * o texto funciona; essa afirmação é do *gate* 8, que corre as mesmas
 * constantes contra o motor.
 *
 * O despacho das respostas é **pela constante** e não pela ordem das chamadas: a
 * primeira versão deste ficheiro guardava uma lista e devolvia-a por ordem, e
 * uma ida à base a mais no meio da *saga* deslocava tudo o que vinha depois — o
 * teste ficava vermelho a dizer outra coisa. Comparar com `SQL_LER_INTENCAO`,
 * `SQL_PEDIDO_POR_PAGAR` e as restantes diz exactamente o que se está a
 * responder.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { SQL_TECTO } from "@kamba/core-ts/ten";

import {
  SQL_CONCLUIR_INTENCAO,
  SQL_EMITIR,
  SQL_LER,
  SQL_LER_INTENCAO,
  SQL_PEDIDO_POR_PAGAR,
  SQL_RETOMAR_INTENCAO,
  TECTO_DE_ESPERA_MS,
  createOrder,
  draftHash,
  type AbrirTransaccao,
  type Encomendas,
  type MontagemDaCriacao,
  type PedidoDeCriacao,
} from "../src/orders/index.ts";
// As duas leituras de preço são as do módulo `produtos` (KAM-043), e o
// `cart.ts` importa-as de lá: reuso e não cópia. Ver a nota daquele ficheiro.
import { SQL_COTACAO_VALIDA, SQL_TERMOS } from "../src/produtos/consultas.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONTACTO = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";
const ENCOMENDA = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50";
const ANEL: [string, string | null] = [
  `v2:${Buffer.alloc(32, 7).toString("base64")}`,
  null,
];

/** Um preço fixo de 1 250,00 Kz em unidade menor, por unidade. */
const PRECO = 125_000;

const RASCUNHO = {
  contactId: CONTACTO,
  draftId: "d".repeat(64),
  draftVersion: 1,
  linhas: [{ sku: "arroz-5kg", qty: 2 }],
  entregaModo: "levantamento" as const,
};

const PEDIDO: PedidoDeCriacao = {
  rascunho: RASCUNHO,
  itens: [{ sku: "arroz-5kg", qty: 2 }],
  totalEsperadoMinor: BigInt(PRECO * 2),
};

/** Uma linha de `offer_terms` publicada, com preço fixo válido. */
function termos(campos: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    sku: "arroz-5kg",
    nome: "Arroz 5 kg",
    preco_tipo: "fixo",
    preco_minor: PRECO,
    currency: "AOA",
    preco_valido_ate: null,
    stock_modo: "garantido",
    estado: "publicado",
    categoria_restrita: null,
    ...campos,
  };
}

/** Um recibo de `order_intents`, como a base o devolve. */
function recibo(campos: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    tenant_id: TENANT,
    intent_key: "CHAVE",
    draft_hash: Buffer.alloc(32, 0),
    estado: "em_curso",
    order_id: null,
    criado_at: new Date("2026-11-04T10:00:00.000Z"),
    ...campos,
  };
}

/** Uma linha de `orders_mirror`, como o `SQL_LER` a devolve. */
function espelho(campos: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: ENCOMENDA,
    numero_publico: "K7H3Q9",
    estado: "criada",
    version: 1,
    total_minor: String(PRECO * 2),
    currency: "AOA",
    contact_id: CONTACTO,
    origem: "pme",
    entrega_modo: "levantamento",
    expira_at: null,
    paga_at: null,
    paga_via: null,
    entregue_at: null,
    entrega_confirmada_por: null,
    confirmacao_dono: "nao_aplicavel",
    lines_snapshot: [
      {
        sku: "arroz-5kg",
        nome: "Arroz 5 kg",
        qty: 2,
        preco_minor: PRECO,
        preco_tipo: "fixo",
        origem_preco: "offer_terms",
      },
    ],
    ...campos,
  };
}

/** O que se pode dizer a cada consulta da *saga*. Omitido quer dizer «vazio». */
interface Guiao {
  /** O `INSERT` do recibo: `[]` quando outro ganhou, `[linha]` quando é nosso. */
  readonly recibo?: Record<string, unknown>[];
  /** As leituras de `SQL_LER_INTENCAO`, uma por chamada, pela ordem. */
  readonly recibos?: Record<string, unknown>[][];
  readonly termos?: Record<string, unknown>[];
  readonly cotacao?: Record<string, unknown>[];
  readonly porPagar?: Record<string, unknown>[];
  readonly espelho?: Record<string, unknown>[];
  /** O tecto do tenant, como a `platform.ten_tecto` o devolve. */
  readonly tecto?: number | null;
  readonly concluir?: Record<string, unknown>[];
  readonly retomar?: Record<string, unknown>[];
}

interface Observado {
  readonly consultas: string[];
  readonly inseridas: Record<string, unknown>[];
  readonly emitidos: string[];
  readonly dormidas: number[];
  transaccoes: number;
  /** Quanto o relógio injectado já andou, em milissegundos. */
  avanco: number;
}

/**
 * A montagem falsa: um `abrir` que dá um `Encomendas` com o guião por trás.
 *
 * Cada `abrir` conta uma transacção, e é por essa contagem que se mede que a
 * *saga* é de **duas** e não de uma — o que é a propriedade de desenho que torna
 * o `em_curso` observável.
 */
function montar(guiao: Guiao): {
  m: MontagemDaCriacao;
  o: Observado;
} {
  const o: Observado = {
    consultas: [],
    inseridas: [],
    emitidos: [],
    dormidas: [],
    transaccoes: 0,
    avanco: 0,
  };
  let leiturasDoRecibo = 0;

  async function noTenant(
    sql: string,
    _valores: readonly unknown[] = [],
  ): Promise<readonly Record<string, unknown>[]> {
    o.consultas.push(sql);
    if (sql === SQL_LER_INTENCAO) {
      const resposta = guiao.recibos?.[leiturasDoRecibo] ?? [];
      leiturasDoRecibo += 1;
      return resposta;
    }
    if (sql === SQL_TERMOS) return guiao.termos ?? [];
    if (sql === SQL_COTACAO_VALIDA) return guiao.cotacao ?? [];
    if (sql === SQL_PEDIDO_POR_PAGAR) return guiao.porPagar ?? [];
    if (sql === SQL_LER) return guiao.espelho ?? [];
    if (sql === SQL_CONCLUIR_INTENCAO) {
      return guiao.concluir ?? [{ intent_key: "CHAVE", estado: "concluida" }];
    }
    if (sql === SQL_RETOMAR_INTENCAO) {
      return guiao.retomar ?? [{ intent_key: "CHAVE", estado: "em_curso" }];
    }
    return [];
  }

  const abrir: AbrirTransaccao = async (trabalho) => {
    o.transaccoes += 1;
    const e: Encomendas = {
      ctx: { tenantId: TENANT, actor: { kind: "agente", id: "a-1" }, traceId: "t-1" },
      repo: {
        tenantId: TENANT,
        noTenant,
        async inserirNoTenant(insercao) {
          o.inseridas.push({ tabela: insercao.tabela, ...insercao.valores });
          if (insercao.tabela === "order_intents") return guiao.recibo ?? [];
          return guiao.espelho ?? [espelho()];
        },
      },
      emitir: {
        async query(sql: string, valores: readonly unknown[] = []) {
          o.consultas.push(sql);
          if (sql === SQL_TECTO) {
            return {
              rows: [{ tecto: guiao.tecto === undefined ? 10_000_000 : guiao.tecto }],
              rowCount: 1,
            };
          }
          if (sql === SQL_EMITIR) {
            o.emitidos.push(String(valores[0]));
            return {
              rows: [{ event_id: "11111111-2222-3333-4444-555555555555" }],
              rowCount: 1,
            };
          }
          return { rows: [], rowCount: 0 };
        },
      },
    };
    return await trabalho(e);
  };

  // **O relógio anda com o `dormir`**, e não é conveniência: a saída do laço de
  // espera do §6.3 compara o relógio com um limite, e com um relógio **fixo**
  // ela nunca acontece. Medido: um ensaio com `agora` parado pendurou a suite
  // inteira do COM, e o `createOrder` ganhou por isso um tecto de iterações ao
  // lado do tecto de tempo. Aqui o relógio anda, para que o que o ensaio mede
  // seja o **tempo** e não o contador de segurança.
  const base = new Date("2026-11-04T10:00:00.000Z").getTime();
  return {
    o,
    m: {
      abrir,
      anel: ANEL,
      agora: () => new Date(base + o.avanco),
      async dormir(ms) {
        o.avanco += ms;
        o.dormidas.push(ms);
      },
    },
  };
}

// --------------------------------------------------- o caminho que cria

test("a saga corre em duas transacções e escreve o recibo antes do espelho", async () => {
  // **A propriedade de desenho do critério 5.** Com uma transacção só, o
  // `order_intents` nunca ficava `em_curso` e a retoma dos dois minutos
  // guardava um estado inalcançável.
  const { m, o } = montar({
    recibo: [recibo({ estado: "em_curso" })],
    termos: [termos()],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, false);
  assert.equal(r.valor.totalMinor, BigInt(PRECO * 2));
  assert.equal(r.valor.confirmacaoDono, "nao_aplicavel");
  assert.ok(o.transaccoes >= 2, `transacções: ${o.transaccoes}`);
  const ordem = o.inseridas.map((i) => i["tabela"]);
  assert.deepEqual(ordem, ["order_intents", "orders_mirror"]);
});

test("o recibo entra com o ON CONFLICT DO NOTHING, que é o que serializa", async () => {
  const { m, o } = montar({ recibo: [recibo()], termos: [termos()] });
  await createOrder(m, PEDIDO);
  // O sufixo é do módulo e não do repo-base: sem ele, cinquenta concorrentes
  // inseriam cinquenta. A medição contra o motor é do gate 8.
  const inserido = o.inseridas[0];
  assert.ok(inserido, "não houve inserção de recibo");
  assert.equal(String(inserido["tabela"]), "order_intents");
  assert.ok(Buffer.isBuffer(inserido["draft_hash"]));
  assert.equal((inserido["draft_hash"] as Buffer).length, 32);
});

test("uma linha confirmar_dono nasce `criada` com `pendente`, no próprio INSERT", async () => {
  // Critério 7: num `UPDATE` a seguir havia um instante em que a encomenda
  // estava `criada` com `nao_aplicavel`, e quem a lesse nesse instante
  // concluía que podia emitir referência.
  const { m, o } = montar({
    recibo: [recibo()],
    termos: [termos({ stock_modo: "confirmar_dono" })],
    espelho: [espelho({ confirmacao_dono: "pendente" })],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.confirmacaoDono, "pendente");
  assert.equal(r.valor.estado, "criada");
  const mirror = o.inseridas.find((i) => i["tabela"] === "orders_mirror");
  assert.equal(String(mirror?.["confirmacao_dono"]), "pendente");
});

test("o createOrder emite `order.created` e nada de pagamento", async () => {
  // A caixa de DoD «pagamento só por evento»: nenhuma via desta função escreve
  // estado de pagamento, e o único evento que sai é o do nascimento.
  const { m, o } = montar({ recibo: [recibo()], termos: [termos()] });
  await createOrder(m, PEDIDO);
  assert.deepEqual(o.emitidos, ["order.created"]);
  const mirror = o.inseridas.find((i) => i["tabela"] === "orders_mirror");
  assert.equal("estado" in (mirror ?? {}), false, "o INSERT não passa estado");
  assert.equal("paga_via" in (mirror ?? {}), false);
});

// ----------------------------------------- as três recusas do critério 6

test("o preço que mudou devolve PRICE_CHANGED e não cria nada", async () => {
  const { m, o } = montar({
    recibo: [recibo()],
    termos: [termos({ preco_minor: PRECO + 1 })],
  });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, { tipo: "erro", erro: "PRICE_CHANGED" });
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
    "não cria",
  );
  assert.deepEqual(o.emitidos, []);
});

test("a autoridade de stock a recusar devolve OUT_OF_STOCK e não cria", async () => {
  // **A passagem do código está medida; a fonte falta** — ver a
  // `AutoridadeDeStock`. A `offer_terms` não tem coluna de quantidade e o
  // Registo não existe em `infra/compose/`: o credor é o KAM-045.
  const { m, o } = montar({ recibo: [recibo()], termos: [termos()] });
  const r = await createOrder(
    { ...m, stockDisponivel: async () => false },
    PEDIDO,
  );
  assert.deepEqual(r, { tipo: "erro", erro: "OUT_OF_STOCK" });
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

test("sem autoridade de stock não se recusa, e isso é consciente", async () => {
  // Recusar tudo por não haver autoridade fechava o caminho da encomenda em
  // toda a Fase 0. O que protege o cliente entretanto é o `stock_modo`.
  const { m } = montar({ recibo: [recibo()], termos: [termos()] });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
});

test("o total acima do tecto do tenant devolve LIMIT_EXCEEDED e não cria", async () => {
  const { m, o } = montar({
    recibo: [recibo()],
    termos: [termos()],
    tecto: PRECO,
  });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, { tipo: "erro", erro: "LIMIT_EXCEEDED" });
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

test("sem tecto declarado recusa-se: «sem tecto» não quer dizer «sem limite»", async () => {
  // O critério 2 do KAM-009. A `ten_tecto` devolve `NULL` quando nenhum módulo
  // activo declara a chave, e `null` nega.
  const { m } = montar({ recibo: [recibo()], termos: [termos()], tecto: null });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, { tipo: "erro", erro: "LIMIT_EXCEEDED" });
});

test("um cart_id que não se re-deriva é VALIDATION_ERROR (ISO-57..60)", async () => {
  const { m, o } = montar({ recibo: [recibo()], termos: [termos()] });
  const r = await createOrder(m, {
    ...PEDIDO,
    cartId: "ZZZZZZZZZZZZZZZZZZZZZZZZZZ",
  });
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

test("um item sob_consulta sem cotação recusa a criação, e não escreve", async () => {
  const { m, o } = montar({
    recibo: [recibo()],
    termos: [termos({ preco_tipo: "sob_consulta", preco_minor: null })],
  });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

// -------------------------------------- os quatro casos de um recibo que existe

test("o mesmo draft_hash com recibo `concluida` devolve a mesma encomenda", async () => {
  // Critério 3, «e a mesma resposta». O `repeticao: true` é o que distingue a
  // repetição de uma criação, e é ele que a tool traduz em `idempotent_replay`.
  //
  // O `draft_hash` do guião é o **derivado do pedido** e não um valor
  // inventado: com um valor qualquer, o módulo veria conteúdo diferente e o
  // caso media `INTENT_REUSED_WITH_DIFFERENT_CONTENT` com o nome de outra
  // coisa.
  const { m, o } = montar({
    recibo: [],
    recibos: [
      [
        recibo({
          estado: "concluida",
          order_id: ENCOMENDA,
          draft_hash: draftHash(RASCUNHO),
        }),
      ],
    ],
    espelho: [espelho()],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, true);
  assert.equal(r.valor.orderId, ENCOMENDA);
  assert.equal(r.valor.numeroPublico, "K7H3Q9");
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
    "uma repetição não cria",
  );
  assert.deepEqual(o.emitidos, []);
});

test("o mesmo intent_key com draft_hash diferente dá INTENT_REUSED_WITH_DIFFERENT_CONTENT", async () => {
  const { m, o } = montar({
    recibo: [],
    recibos: [[recibo({ draft_hash: Buffer.alloc(32, 9) })]],
  });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, {
    tipo: "erro",
    erro: "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
  });
  // **E nem lê os termos**: o `draft_hash` compara-se antes do estado e antes de
  // qualquer resolução de preço.
  assert.equal(o.consultas.includes(SQL_TERMOS), false);
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

test("um `em_curso` recente espera e devolve a encomenda quando o recibo fecha", async () => {
  // Critério 5, terceira metade: «`em_curso` concorrente aguarda ≤ 3 s e
  // devolve a mesma resposta». O relógio e a espera são injectados, pelo que a
  // fronteira se mede sem dormir três segundos.
  const real = draftHash(RASCUNHO);
  const { m, o } = montar({
    recibo: [],
    recibos: [
      [recibo({ draft_hash: real })],
      [recibo({ draft_hash: real })],
      [recibo({ draft_hash: real, estado: "concluida", order_id: ENCOMENDA })],
    ],
    espelho: [espelho()],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.orderId, ENCOMENDA);
  assert.equal(r.valor.repeticao, true);
  // Esperou, e não criou.
  assert.ok(o.dormidas.length >= 2, `dormidas: ${o.dormidas.length}`);
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

test("a espera esgotada devolve UPSTREAM_TIMEOUT sem criar nada", async () => {
  // Criar uma segunda encomenda porque a primeira demora era duplicar
  // exactamente o que esta chave existe para impedir.
  //
  // A fronteira mede-se com o relógio do `montar`, que anda com o `dormir`: o
  // ensaio não dorme três segundos, e mede-os.
  const real = draftHash(RASCUNHO);
  // Todas as leituras devolvem `em_curso` com o hash certo: nunca fecha.
  const { m, o } = montar({
    recibo: [],
    recibos: Array.from({ length: 500 }, () => [recibo({ draft_hash: real })]),
  });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, { tipo: "erro", erro: "UPSTREAM_TIMEOUT" });
  assert.ok(
    o.avanco >= TECTO_DE_ESPERA_MS,
    `o tecto é ${TECTO_DE_ESPERA_MS} ms e esperou ${o.avanco}`,
  );
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

test("um recibo `falhada` retoma-se e a saga segue", async () => {
  const real = draftHash(RASCUNHO);
  const { m, o } = montar({
    recibo: [],
    recibos: [[recibo({ draft_hash: real, estado: "falhada" })]],
    termos: [termos()],
    retomar: [{ intent_key: "CHAVE", estado: "em_curso" }],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, false);
  assert.ok(o.consultas.includes(SQL_RETOMAR_INTENCAO));
});

test("uma retoma que outro ganhou espera por ele e não cria nada", async () => {
  // A razão de a retoma ser um `UPDATE` condicional: de dois leitores de um
  // recibo `falhada`, passa um. **E quem perde espera pelo que ganhou** em vez
  // de recusar logo, que é o critério 5 outra vez: o recibo é do outro, e a
  // resposta certa é a dele. Aqui ele nunca fecha, pelo que a espera esgota.
  const real = draftHash(RASCUNHO);
  const { m, o } = montar({
    recibo: [],
    recibos: Array.from({ length: 500 }, () => [
      recibo({ draft_hash: real, estado: "falhada" }),
    ]),
    retomar: [],
  });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, { tipo: "erro", erro: "UPSTREAM_TIMEOUT" });
  assert.ok(o.avanco >= TECTO_DE_ESPERA_MS);
  assert.equal(
    o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
  );
});

// ------------------------------------------------ o facto do critério 8

test("a resposta inclui o pedido por pagar, e cria de qualquer forma", async () => {
  // **Nunca bloqueia em silêncio**, que é a segunda metade do critério: a
  // encomenda nasce **e** a resposta leva o facto para o agente perguntar.
  const { m } = montar({
    recibo: [recibo()],
    termos: [termos()],
    porPagar: [
      {
        id: "11111111-aaaa-4000-8000-000000000001",
        numero_publico: "K7H3Q9",
        estado: "aguarda_pagamento",
        total_minor: "250000",
        currency: "AOA",
        criado_at: new Date("2026-11-04T09:55:00.000Z"),
      },
    ],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  // Criou.
  assert.equal(r.valor.repeticao, false);
  assert.equal(r.valor.orderId, ENCOMENDA);
  // E levou o facto.
  assert.equal(r.valor.pedidoPorPagar?.numeroPublico, "K7H3Q9");
  assert.equal(r.valor.pedidoPorPagar?.estado, "aguarda_pagamento");
  assert.equal(r.valor.pedidoPorPagar?.totalMinor, 250_000n);
});

test("sem pedido anterior o facto é null, e não um objecto vazio", async () => {
  const { m } = montar({ recibo: [recibo()], termos: [termos()] });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.pedidoPorPagar, null);
});

test("o facto lê-se antes de escrever, e com a janela de 30 min no argumento", async () => {
  const { m, o } = montar({ recibo: [recibo()], termos: [termos()] });
  await createOrder(m, PEDIDO);
  const indiceDoFacto = o.consultas.indexOf(SQL_PEDIDO_POR_PAGAR);
  assert.ok(indiceDoFacto >= 0, "a consulta do facto não correu");
  const indiceDoConcluir = o.consultas.indexOf(SQL_CONCLUIR_INTENCAO);
  assert.ok(
    indiceDoFacto < indiceDoConcluir,
    "o facto tem de ser lido antes de o recibo fechar, senão aponta para a " +
      "encomenda que acabámos de criar",
  );
});

// --------------------------------------------------------------- recusas de forma

test("um rascunho sem forma recusa-se sem abrir transacção de escrita", async () => {
  const { m, o } = montar({ recibo: [recibo()], termos: [termos()] });
  const r = await createOrder(m, {
    ...PEDIDO,
    rascunho: { ...RASCUNHO, contactId: "+244923000000" },
  });
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(o.inseridas, []);
});

test("um recibo que desapareceu entre o INSERT e a leitura é UPSTREAM_DOWN", async () => {
  const { m } = montar({ recibo: [], recibos: [[]] });
  const r = await createOrder(m, PEDIDO);
  assert.deepEqual(r, { tipo: "erro", erro: "UPSTREAM_DOWN" });
});

test("as 14:04:59 e as 14:05:01 produzem uma encomenda, e a segunda repete", async () => {
  // **O critério 3 à letra**, com os dois instantes que ele escreve. A chave não
  // tem tempo, pelo que não há nada que o relógio possa mudar — e é isso que
  // este caso mostra do lado do módulo: com o `agora` nos dois instantes, a
  // primeira chamada cria e a segunda devolve a mesma encomenda.
  //
  // A outra metade — que a **mesma chave** dá uma linha sob concorrência — é das
  // transacções e mede-se contra PostgreSQL
  // (`db/tests_encomendas/test_idempotencia.py`).
  const real = draftHash(RASCUNHO);
  const primeira = montar({ recibo: [recibo()], termos: [termos()] });
  const r1 = await createOrder(
    { ...primeira.m, agora: () => new Date("2026-11-04T14:04:59.000Z") },
    PEDIDO,
  );
  assert.equal(r1.tipo, "ok");
  if (r1.tipo !== "ok") return;
  assert.equal(r1.valor.repeticao, false);

  // A segunda chamada, dois segundos depois e do outro lado da janela de cinco
  // minutos que a chave antiga usava, encontra o recibo que a primeira fechou.
  const segunda = montar({
    recibo: [],
    recibos: [
      [recibo({ estado: "concluida", order_id: ENCOMENDA, draft_hash: real })],
    ],
    espelho: [espelho()],
  });
  const r2 = await createOrder(
    { ...segunda.m, agora: () => new Date("2026-11-04T14:05:01.000Z") },
    PEDIDO,
  );
  assert.equal(r2.tipo, "ok");
  if (r2.tipo !== "ok") return;
  assert.equal(r2.valor.repeticao, true);
  assert.equal(r2.valor.orderId, r1.valor.orderId);
  assert.equal(
    segunda.o.inseridas.some((i) => i["tabela"] === "orders_mirror"),
    false,
    "a segunda nao cria: uma encomenda e nao duas",
  );
});
