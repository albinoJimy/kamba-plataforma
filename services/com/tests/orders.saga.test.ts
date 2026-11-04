/**
 * A *saga* de `createOrder`: os quatro casos do recibo e as três recusas (KAM-046).
 *
 * ## O duplo tem a chave primária e a unicidade, e isso é a diferença
 *
 * A primeira versão deste ficheiro guionava as respostas: «ao segundo
 * `SQL_LER_INTENCAO` responde um recibo `concluida`». A revisão adversarial
 * mostrou o que isso não media — **nada no caso dependia da `intent_key` ser a
 * mesma nas duas chamadas**, pelo que o caso dos dois instantes das 14:04:59 e
 * 14:05:01 continuaria verde com a chave por janela temporal que este ticket
 * existe para substituir. Um guião prova o guião.
 *
 * Agora o duplo é uma **loja**: `Map` indexados como a base indexa — a chave
 * primária `(tenant_id, intent_key)` do `order_intents` e a
 * `orders_mirror_intent_uq` sobre `(tenant_id, intent_key)` —, com o
 * `ON CONFLICT DO NOTHING` a devolver zero linhas e o `INSERT` do espelho a
 * **levantar `23505`** quando a chave já tem encomenda. Os casos passaram a
 * depender da derivação, que é o que eles dizem medir.
 *
 * O que ela continua a não ser é uma base de dados: não tem transacções, pelo
 * que a idempotência sob concorrência mede-se contra PostgreSQL
 * (`db/tests_encomendas/test_idempotencia.py`, cinquenta ligações). A divisão é
 * esta:
 *
 * ```text
 * aqui          que decisao o modulo toma, em cada estado do recibo
 *               as tres recusas do criterio 6, e que nao escrevem NADA
 *               o anel: um recibo sob a versao anterior do segredo
 *               a espera do `em_curso` com o relogio injectado
 * gate 8        a mesma chave, cinquenta ligacoes, uma encomenda
 * ```
 *
 * O despacho das respostas é **pela constante** e não pela ordem das chamadas:
 * comparar com `SQL_LER_INTENCAO`, `SQL_PEDIDO_POR_PAGAR` e as restantes diz
 * exactamente o que se está a responder, e uma ida à base a mais no meio da saga
 * não desloca tudo o que vem depois.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { SQL_TECTO } from "@kamba/core-ts/ten";

import {
  SQL_CONCLUIR_INTENCAO,
  SQL_CONFIRMACAO_DO_DONO,
  SQL_EMITIR,
  SQL_ENCOMENDA_DA_CHAVE,
  SQL_FALHAR_INTENCAO,
  SQL_LER,
  SQL_LER_CONFIRMACAO,
  SQL_LER_INTENCAO,
  SQL_PEDIDO_POR_PAGAR,
  SQL_RETOMAR_INTENCAO,
  TABELA_DAS_INTENCOES,
  TECTO_DE_ESPERA_MS,
  cartId,
  chavesDoAnel,
  createOrder,
  draftHash,
  intentKey,
  type AbrirTransaccao,
  type Encomendas,
  type MontagemDaCriacao,
  type PedidoDeCriacao,
} from "../src/orders/index.ts";
// As duas leituras de preço são as do módulo `produtos` (KAM-043), e o
// `cart.ts` importa-as de lá: reuso e não cópia. Ver a nota daquele ficheiro.
import { SQL_COTACAO_VALIDA, SQL_TERMOS } from "../src/produtos/consultas.ts";
import { FiltroEmFaltaError, repoBase } from "../src/repo-base/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONTACTO = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";
const ACTUAL = `v2:${Buffer.alloc(32, 7).toString("base64")}`;
const ANTERIOR = `v1:${Buffer.alloc(32, 3).toString("base64")}`;
const ANEL: [string, string | null] = [ACTUAL, null];
const ANEL_RODADO: [string, string | null] = [ACTUAL, ANTERIOR];

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
  totalEsperadoMinor: BigInt(PRECO * 2),
};

/** As partes da intenção deste rascunho, para derivar as chaves à mão. */
const PARTES = {
  tenantId: TENANT,
  contactId: CONTACTO,
  draftId: RASCUNHO.draftId,
  draftVersion: RASCUNHO.draftVersion,
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

/** Um recibo de `order_intents`, na forma que a loja guarda. */
interface ReciboNaLoja {
  intent_key: string;
  draft_hash: Buffer;
  estado: "em_curso" | "concluida" | "falhada";
  order_id: string | null;
  criado_at: Date;
}

/** O que se pode guionar. O que **não** se guiona é o recibo: a loja tem-no. */
interface Guiao {
  readonly termos?: Record<string, unknown>[];
  readonly cotacao?: Record<string, unknown>[];
  readonly porPagar?: Record<string, unknown>[];
  /** O tecto do tenant, como a `platform.ten_tecto` o devolve. */
  readonly tecto?: number | null;
  /** Recibos já na loja antes da chamada. */
  readonly recibos?: readonly ReciboNaLoja[];
  /** Encomendas já na loja, por `intent_key`. */
  readonly encomendas?: readonly { intentKey: string; numero: string }[];
  readonly anel?: [string, string | null];
}

interface Observado {
  readonly consultas: string[];
  readonly inseridas: Record<string, unknown>[];
  readonly emitidos: string[];
  readonly dormidas: number[];
  transaccoes: number;
  /** Quanto o relógio injectado já andou, em milissegundos. */
  avanco: number;
  /** A loja, para o teste inspeccionar o que ficou escrito. */
  readonly intents: Map<string, ReciboNaLoja>;
  readonly orders: Map<string, Record<string, unknown>>;
  readonly porIntent: Map<string, string>;
}

const BASE_DO_RELOGIO = new Date("2026-11-04T10:00:00.000Z").getTime();

/**
 * A montagem falsa, com a loja por trás. Ver a nota do módulo.
 *
 * Cada `abrir` conta uma transacção, e é por essa contagem que se mede que a
 * *saga* é de **duas** e não de uma — a propriedade de desenho que torna o
 * `em_curso` observável.
 */
function montar(guiao: Guiao = {}): { m: MontagemDaCriacao; o: Observado } {
  const o: Observado = {
    consultas: [],
    inseridas: [],
    emitidos: [],
    dormidas: [],
    transaccoes: 0,
    avanco: 0,
    intents: new Map(),
    orders: new Map(),
    porIntent: new Map(),
  };
  let n = 0;

  for (const recibo of guiao.recibos ?? []) {
    o.intents.set(recibo.intent_key, { ...recibo });
  }
  for (const { intentKey: chave, numero } of guiao.encomendas ?? []) {
    const id = `11111111-0000-4000-8000-${String(++n).padStart(12, "0")}`;
    o.orders.set(id, {
      id,
      numero_publico: numero,
      estado: "criada",
      version: 1,
      total_minor: String(PRECO * 2),
      currency: "AOA",
      confirmacao_dono: "nao_aplicavel",
      contact_id: CONTACTO,
      origem: "pme",
      entrega_modo: "levantamento",
      expira_at: null,
      paga_at: null,
      paga_via: null,
      entregue_at: null,
      entrega_confirmada_por: null,
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
    });
    o.porIntent.set(chave, id);
    const recibo = o.intents.get(chave);
    if (recibo !== undefined && recibo.estado === "concluida") {
      recibo.order_id = id;
    }
  }

  async function noTenant(
    sql: string,
    valores: readonly unknown[] = [],
  ): Promise<readonly Record<string, unknown>[]> {
    o.consultas.push(sql);
    if (sql === SQL_LER_INTENCAO) {
      const chaves = (valores[0] ?? []) as readonly string[];
      return chaves
        .map((c) => o.intents.get(c))
        .filter((r): r is ReciboNaLoja => r !== undefined)
        .sort((a, b) => b.criado_at.getTime() - a.criado_at.getTime())
        .map((r) => ({ tenant_id: TENANT, ...r }));
    }
    if (sql === SQL_TERMOS) return guiao.termos ?? [];
    if (sql === SQL_COTACAO_VALIDA) return guiao.cotacao ?? [];
    if (sql === SQL_PEDIDO_POR_PAGAR) return guiao.porPagar ?? [];
    if (sql === SQL_LER) {
      const linha = o.orders.get(String(valores[0]));
      return linha === undefined ? [] : [linha];
    }
    if (sql === SQL_ENCOMENDA_DA_CHAVE) {
      const id = o.porIntent.get(String(valores[0]));
      const linha = id === undefined ? undefined : o.orders.get(id);
      return linha === undefined ? [] : [linha];
    }
    if (sql === SQL_CONCLUIR_INTENCAO) {
      // `WHERE … AND estado = 'em_curso'`, como a cadeia escreve.
      const recibo = o.intents.get(String(valores[0]));
      if (recibo === undefined || recibo.estado !== "em_curso") return [];
      recibo.estado = "concluida";
      recibo.order_id = String(valores[1]);
      return [{ intent_key: recibo.intent_key, estado: recibo.estado }];
    }
    if (sql === SQL_FALHAR_INTENCAO) {
      // `WHERE … AND estado = 'em_curso' AND criado_at < $3`.
      const recibo = o.intents.get(String(valores[0]));
      const limite = Date.parse(String(valores[1]));
      if (
        recibo === undefined ||
        recibo.estado !== "em_curso" ||
        recibo.criado_at.getTime() >= limite
      ) {
        return [];
      }
      recibo.estado = "falhada";
      return [{ intent_key: recibo.intent_key, criado_at: recibo.criado_at }];
    }
    if (sql === SQL_RETOMAR_INTENCAO) {
      // `WHERE … AND estado = 'falhada'`.
      const recibo = o.intents.get(String(valores[0]));
      if (recibo === undefined || recibo.estado !== "falhada") return [];
      recibo.estado = "em_curso";
      return [{ intent_key: recibo.intent_key, estado: recibo.estado }];
    }
    return [];
  }

  const abrir: AbrirTransaccao = async (trabalho) => {
    o.transaccoes += 1;
    const e: Encomendas = {
      ctx: {
        tenantId: TENANT,
        actor: { kind: "agente", id: "a-1" },
        traceId: "t-1",
      },
      repo: {
        tenantId: TENANT,
        noTenant,
        async inserirNoTenant(insercao) {
          o.inseridas.push({ tabela: insercao.tabela, ...insercao.valores });
          const chave = String(insercao.valores["intent_key"]);
          if (insercao.tabela === TABELA_DAS_INTENCOES) {
            // A chave primária `(tenant_id, intent_key)` mais o
            // `ON CONFLICT DO NOTHING`: zero linhas quando já existe.
            if (o.intents.has(chave)) return [];
            const recibo: ReciboNaLoja = {
              intent_key: chave,
              draft_hash: insercao.valores["draft_hash"] as Buffer,
              estado: "em_curso",
              order_id: null,
              criado_at: new Date(BASE_DO_RELOGIO + o.avanco),
            };
            o.intents.set(chave, recibo);
            return [{ tenant_id: TENANT, ...recibo }];
          }
          // O espelho: a `orders_mirror_intent_uq` levanta `23505`.
          if (o.porIntent.has(chave)) {
            throw Object.assign(
              new Error(
                "duplicate key value violates unique constraint " +
                  '"orders_mirror_intent_uq"',
              ),
              { code: "23505" },
            );
          }
          const id = `22222222-0000-4000-8000-${String(++n).padStart(12, "0")}`;
          const linha: Record<string, unknown> = {
            id,
            numero_publico: `K7H3Q${n}`,
            estado: "criada",
            version: 1,
            total_minor: String(insercao.valores["total_minor"]),
            currency: String(insercao.valores["currency"]),
            confirmacao_dono: String(insercao.valores["confirmacao_dono"]),
            contact_id: String(insercao.valores["contact_id"]),
            origem: String(insercao.valores["origem"]),
            entrega_modo: String(insercao.valores["entrega_modo"]),
            expira_at: null,
            paga_at: null,
            paga_via: null,
            entregue_at: null,
            entrega_confirmada_por: null,
            lines_snapshot: JSON.parse(
              String(insercao.valores["lines_snapshot"]),
            ),
          };
          o.orders.set(id, linha);
          o.porIntent.set(chave, id);
          return [linha];
        },
      },
      emitir: {
        async query(sql: string, valores: readonly unknown[] = []) {
          o.consultas.push(sql);
          if (sql === SQL_TECTO) {
            return {
              rows: [
                { tecto: guiao.tecto === undefined ? 10_000_000 : guiao.tecto },
              ],
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

  return {
    o,
    m: {
      abrir,
      anel: guiao.anel ?? ANEL,
      // O relógio anda com o `dormir`: a saída do laço de espera compara o
      // relógio com um limite, e com um relógio **fixo** ela nunca acontece —
      // medido, pendurou a suite inteira do COM.
      agora: () => new Date(BASE_DO_RELOGIO + o.avanco),
      async dormir(ms) {
        o.avanco += ms;
        o.dormidas.push(ms);
      },
    },
  };
}

/**
 * Um resultado como texto, para a mensagem de uma asserção que falha.
 *
 * **Não é `JSON.stringify`**, e a razão é por execução: o `totalMinor` é
 * `bigint` e o `JSON.stringify` **lança** `TypeError` sobre um — e a mensagem
 * avalia-se antes da asserção, pelo que nove casos falharam com o erro do
 * serializador em vez do que mediam. É a mesma armadilha que o
 * `emInteiroSeguro` do `eventos.ts` existe para fechar no payload.
 */
function comoTexto(r: unknown): string {
  return JSON.stringify(r, (_chave, valor) =>
    typeof valor === "bigint" ? `${valor}n` : valor,
  );
}

/** Os números públicos das encomendas da loja. É a asserção mais repetida. */
function encomendas(o: Observado): string[] {
  return [...o.orders.values()].map((l) => String(l["numero_publico"])).sort();
}

/** Um recibo na loja, pronto a pôr no guião. */
function recibo(
  chave: string,
  estado: ReciboNaLoja["estado"],
  minutosAtras = 0,
  hash: Buffer = draftHash(RASCUNHO),
): ReciboNaLoja {
  return {
    intent_key: chave,
    draft_hash: hash,
    estado,
    order_id: null,
    criado_at: new Date(BASE_DO_RELOGIO - minutosAtras * 60_000),
  };
}

// --------------------------------------------------- o caminho que cria

test("a saga corre em duas transacções e escreve o recibo antes do espelho", async () => {
  // **A propriedade de desenho do critério 5.** Com uma transacção só, o
  // `order_intents` nunca ficava `em_curso` e a retoma dos dois minutos
  // guardava um estado inalcançável.
  const { m, o } = montar({ termos: [termos()] });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, false);
  assert.equal(r.valor.totalMinor, BigInt(PRECO * 2));
  assert.equal(r.valor.confirmacaoDono, "nao_aplicavel");
  assert.ok(o.transaccoes >= 2, `transacções: ${o.transaccoes}`);
  assert.deepEqual(
    o.inseridas.map((i) => i["tabela"]),
    [TABELA_DAS_INTENCOES, "orders_mirror"],
  );
  const guardado = o.intents.get(intentKey(ACTUAL, PARTES));
  assert.equal(guardado?.estado, "concluida");
  assert.equal(guardado?.order_id, r.valor.orderId);
});

test("o recibo entra na tabela qualificada pelo esquema", async () => {
  // Nada neste repositório põe o `search_path`, e o `inserir` do repo-base
  // **constrói** o `INSERT` com o nome que a constante dá: sem o `platform.`, a
  // instrução morria em `42P01` no primeiro chamador real. Achado da revisão
  // adversarial.
  assert.equal(TABELA_DAS_INTENCOES, "platform.order_intents");
  const vistas: string[] = [];
  const r = repoBase(
    {
      async query(sql: string) {
        vistas.push(sql);
        return { rows: [] as Record<string, unknown>[] };
      },
    },
    TENANT,
    "merch_A",
  );
  await r.inserirNoTenant({
    tabela: TABELA_DAS_INTENCOES,
    valores: { intent_key: "X", draft_hash: Buffer.alloc(32) },
  });
  assert.match(String(vistas[0]), /INSERT INTO platform\.order_intents/);
});

test("o draft_hash do recibo é o do rascunho que se encomendou", async () => {
  // **O achado que bloqueava.** A primeira versão passava as linhas duas vezes —
  // o `rascunho.linhas`, de onde saía o *hash*, e um `itens[]` separado, de onde
  // saíam os preços — e nada confrontava os dois: uma encomenda de 5 unidades
  // ficava com o *hash* de 2, e o toque seguinte recebia-a como repetição.
  // Agora há uma fonte, e este caso afirma-o.
  const { m, o } = montar({ termos: [termos()] });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(
    o.intents.get(intentKey(ACTUAL, PARTES))?.draft_hash.toString("hex"),
    draftHash(RASCUNHO).toString("hex"),
  );
  assert.deepEqual(
    r.valor.linhas.map((l) => `${l.sku}x${l.qty}`),
    ["arroz-5kgx2"],
  );
});

test("uma linha confirmar_dono nasce `criada` com `pendente`, no próprio INSERT", async () => {
  // Critério 7: num `UPDATE` a seguir havia um instante em que a encomenda
  // estava `criada` com `nao_aplicavel`, e quem a lesse nesse instante
  // concluía que podia emitir referência.
  const { m, o } = montar({ termos: [termos({ stock_modo: "confirmar_dono" })] });
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
  const { m, o } = montar({ termos: [termos()] });
  await createOrder(m, PEDIDO);
  assert.deepEqual(o.emitidos, ["order.created"]);
  const mirror = o.inseridas.find((i) => i["tabela"] === "orders_mirror");
  assert.equal("estado" in (mirror ?? {}), false, "o INSERT não passa estado");
  assert.equal("paga_via" in (mirror ?? {}), false);
});

// ----------------------------------------- as três recusas do critério 6

/**
 * O que **toda** a recusa tem de cumprir: não cria, não emite, e **não deixa
 * recibo**.
 *
 * A terceira é a que a revisão adversarial apanhou. O `comTenant` confirma
 * quando o trabalho devolve um valor e só desfaz num `throw`, pelo que uma
 * recusa depois do `INSERT` **confirmava** um recibo `em_curso` — e o cliente
 * que aceitasse o preço novo voltava com a mesma chave, encontrava o recibo
 * recente, esperava três segundos e recebia `UPSTREAM_TIMEOUT`. O caminho do
 * critério 6 ficava fechado dois minutos depois de uma recusa legítima.
 */
function recusouSemRasto(o: Observado, onde: string): void {
  assert.deepEqual(encomendas(o), [], `${onde}: criou encomenda`);
  assert.deepEqual(o.emitidos, [], `${onde}: emitiu evento`);
  assert.equal(o.intents.size, 0, `${onde}: deixou recibo`);
  assert.deepEqual(o.inseridas, [], `${onde}: escreveu`);
}

test("o preço que mudou devolve PRICE_CHANGED e não deixa rasto nenhum", async () => {
  const { m, o } = montar({ termos: [termos({ preco_minor: PRECO + 1 })] });
  assert.deepEqual(await createOrder(m, PEDIDO), {
    tipo: "erro",
    erro: "PRICE_CHANGED",
  });
  recusouSemRasto(o, "PRICE_CHANGED");
});

test("depois de um PRICE_CHANGED, aceitar o preço novo cria à primeira", async () => {
  // **A consequência que a ordem errada tinha**, medida do lado de quem compra:
  // o cliente vê o preço novo, aceita, e volta com a **mesma** `intent_key` e o
  // **mesmo** `draft_hash` — porque nem a chave nem as linhas do rascunho
  // mudaram. Com o recibo confirmado pela recusa anterior, isto dava
  // `UPSTREAM_TIMEOUT` durante dois minutos.
  const { m, o } = montar({ termos: [termos({ preco_minor: PRECO + 1 })] });
  assert.deepEqual(await createOrder(m, PEDIDO), {
    tipo: "erro",
    erro: "PRICE_CHANGED",
  });
  const r = await createOrder(m, {
    ...PEDIDO,
    totalEsperadoMinor: BigInt((PRECO + 1) * 2),
  });
  assert.equal(r.tipo, "ok", comoTexto(r));
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, false);
  assert.equal(encomendas(o).length, 1);
});

test("a autoridade de stock a recusar devolve OUT_OF_STOCK sem rasto", async () => {
  // **A passagem do código está medida; a fonte falta** — ver a
  // `AutoridadeDeStock`. A `offer_terms` não tem coluna de quantidade e o
  // Registo não existe em `infra/compose/`: o credor é o KAM-045.
  const { m, o } = montar({ termos: [termos()] });
  assert.deepEqual(
    await createOrder({ ...m, stockDisponivel: async () => false }, PEDIDO),
    { tipo: "erro", erro: "OUT_OF_STOCK" },
  );
  recusouSemRasto(o, "OUT_OF_STOCK");
});

test("sem autoridade de stock não se recusa, e isso é consciente", async () => {
  // Recusar tudo por não haver autoridade fechava o caminho da encomenda em
  // toda a Fase 0. O que protege o cliente entretanto é o `stock_modo`.
  const { m } = montar({ termos: [termos()] });
  assert.equal((await createOrder(m, PEDIDO)).tipo, "ok");
});

test("o total acima do tecto do tenant devolve LIMIT_EXCEEDED sem rasto", async () => {
  const { m, o } = montar({ termos: [termos()], tecto: PRECO });
  assert.deepEqual(await createOrder(m, PEDIDO), {
    tipo: "erro",
    erro: "LIMIT_EXCEEDED",
  });
  recusouSemRasto(o, "LIMIT_EXCEEDED");
});

test("sem tecto declarado recusa-se: «sem tecto» não quer dizer «sem limite»", async () => {
  // O critério 2 do KAM-009. A `ten_tecto` devolve `NULL` quando nenhum módulo
  // activo declara a chave, e `null` nega.
  const { m, o } = montar({ termos: [termos()], tecto: null });
  assert.deepEqual(await createOrder(m, PEDIDO), {
    tipo: "erro",
    erro: "LIMIT_EXCEEDED",
  });
  recusouSemRasto(o, "sem tecto");
});

test("um item sob_consulta sem cotação recusa sem rasto", async () => {
  const { m, o } = montar({
    termos: [termos({ preco_tipo: "sob_consulta", preco_minor: null })],
  });
  assert.deepEqual(await createOrder(m, PEDIDO), {
    tipo: "erro",
    erro: "VALIDATION_ERROR",
  });
  recusouSemRasto(o, "sob_consulta");
});

// ------------------------------------------------------------- o cart_id

test("o cart_id correcto passa, e é o caso positivo que faltava", async () => {
  // A revisão adversarial notou que só havia o caso negativo: nenhum provava
  // que o `cart_id` **certo** passa. É o tipo de caso que o `repo-base` desta
  // casa registra como o que encontra os defeitos.
  const { m, o } = montar({ termos: [termos()] });
  const r = await createOrder(m, { ...PEDIDO, cartId: cartId(ACTUAL, PARTES) });
  assert.equal(r.tipo, "ok", comoTexto(r));
  assert.equal(encomendas(o).length, 1);
});

test("um cart_id da versão anterior do segredo continua a valer", async () => {
  // O `cartIdValido` conhece as **duas** versões do anel. A primeira versão
  // comparava com `!==` contra `anel[0]` e recusava um `cart_id` emitido antes
  // de uma rotação — e a caixa 5 do DoD afirmava o contrário do que o código
  // fazia.
  const { m, o } = montar({ termos: [termos()], anel: ANEL_RODADO });
  const r = await createOrder(m, {
    ...PEDIDO,
    cartId: cartId(ANTERIOR, PARTES),
  });
  assert.equal(r.tipo, "ok", comoTexto(r));
  assert.equal(encomendas(o).length, 1);
});

test("um cart_id que não se re-deriva é VALIDATION_ERROR sem rasto (ISO-57..60)", async () => {
  const { m, o } = montar({ termos: [termos()] });
  assert.deepEqual(
    await createOrder(m, { ...PEDIDO, cartId: "ZZZZZZZZZZZZZZZZZZZZZZZZZZ" }),
    { tipo: "erro", erro: "VALIDATION_ERROR" },
  );
  recusouSemRasto(o, "cart_id forjado");
});

test("o cart_id de outro contacto não serve a este", async () => {
  const outro = "8d2e6f4b-3c50-4b7d-9e1f-2a3b4c5d6e7f";
  const { m, o } = montar({ termos: [termos()] });
  assert.deepEqual(
    await createOrder(m, {
      ...PEDIDO,
      cartId: cartId(ACTUAL, { ...PARTES, contactId: outro }),
    }),
    { tipo: "erro", erro: "VALIDATION_ERROR" },
  );
  recusouSemRasto(o, "cart_id de outro contacto");
});

// -------------------------------------- os quatro casos de um recibo que existe

test("o mesmo draft_hash com recibo `concluida` devolve a mesma encomenda", async () => {
  // Critério 3, «e a mesma resposta». O `repeticao: true` é o que distingue a
  // repetição de uma criação, e é ele que a tool traduz em `idempotent_replay`.
  const chave = intentKey(ACTUAL, PARTES);
  const { m, o } = montar({
    termos: [termos()],
    recibos: [recibo(chave, "concluida")],
    encomendas: [{ intentKey: chave, numero: "ANTIGA" }],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok", comoTexto(r));
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, true);
  assert.equal(r.valor.numeroPublico, "ANTIGA");
  assert.deepEqual(encomendas(o), ["ANTIGA"], "uma repetição não cria");
  assert.deepEqual(o.emitidos, []);
});

test("o mesmo intent_key com draft_hash diferente dá INTENT_REUSED_WITH_DIFFERENT_CONTENT", async () => {
  const { m, o } = montar({
    termos: [termos()],
    recibos: [
      recibo(intentKey(ACTUAL, PARTES), "em_curso", 0, Buffer.alloc(32, 9)),
    ],
  });
  assert.deepEqual(await createOrder(m, PEDIDO), {
    tipo: "erro",
    erro: "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
  });
  assert.deepEqual(encomendas(o), []);
});

test("um `em_curso` recente espera e devolve a encomenda quando o recibo fecha", async () => {
  // Critério 5, terceira metade: «`em_curso` concorrente aguarda ≤ 3 s e
  // devolve a mesma resposta». O recibo fecha a meio da espera, como fecharia
  // se a saga vencedora confirmasse a fase 2.
  const chave = intentKey(ACTUAL, PARTES);
  const { m, o } = montar({
    termos: [termos()],
    recibos: [recibo(chave, "em_curso")],
    encomendas: [{ intentKey: chave, numero: "DOUTRA" }],
  });
  const dormirOriginal = m.dormir as (ms: number) => Promise<void>;
  let voltas = 0;
  const comFecho: MontagemDaCriacao = {
    ...m,
    async dormir(ms) {
      await dormirOriginal(ms);
      if (++voltas === 2) {
        const guardado = o.intents.get(chave) as ReciboNaLoja;
        guardado.estado = "concluida";
        guardado.order_id = o.porIntent.get(chave) as string;
      }
    },
  };
  const r = await createOrder(comFecho, PEDIDO);
  assert.equal(r.tipo, "ok", comoTexto(r));
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.numeroPublico, "DOUTRA");
  assert.equal(r.valor.repeticao, true);
  assert.ok(o.dormidas.length >= 2, `dormidas: ${o.dormidas.length}`);
  assert.deepEqual(encomendas(o), ["DOUTRA"], "esperou, e não criou");
});

test("a espera esgotada devolve UPSTREAM_TIMEOUT sem criar nada", async () => {
  // Criar uma segunda encomenda porque a primeira demora era duplicar
  // exactamente o que esta chave existe para impedir.
  const { m, o } = montar({
    termos: [termos()],
    recibos: [recibo(intentKey(ACTUAL, PARTES), "em_curso")],
  });
  assert.deepEqual(await createOrder(m, PEDIDO), {
    tipo: "erro",
    erro: "UPSTREAM_TIMEOUT",
  });
  assert.ok(
    o.avanco >= TECTO_DE_ESPERA_MS,
    `o tecto é ${TECTO_DE_ESPERA_MS} ms e esperou ${o.avanco}`,
  );
  assert.deepEqual(encomendas(o), []);
});

test("um `em_curso` de mais de dois minutos falha-se e retoma-se, e a saga segue", async () => {
  const { m, o } = montar({
    termos: [termos()],
    recibos: [recibo(intentKey(ACTUAL, PARTES), "em_curso", 3)],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok", comoTexto(r));
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, false);
  // **As duas instruções, por esta ordem:** `em_curso` → `falhada` → `em_curso`.
  assert.deepEqual(
    o.consultas.filter(
      (s) => s === SQL_FALHAR_INTENCAO || s === SQL_RETOMAR_INTENCAO,
    ),
    [SQL_FALHAR_INTENCAO, SQL_RETOMAR_INTENCAO],
  );
  assert.equal(encomendas(o).length, 1);
});

test("um recibo `falhada` retoma-se sem passar pelo SQL_FALHAR", async () => {
  const { m, o } = montar({
    termos: [termos()],
    recibos: [recibo(intentKey(ACTUAL, PARTES), "falhada")],
  });
  assert.equal((await createOrder(m, PEDIDO)).tipo, "ok");
  assert.equal(o.consultas.includes(SQL_FALHAR_INTENCAO), false);
  assert.ok(o.consultas.includes(SQL_RETOMAR_INTENCAO));
  assert.equal(encomendas(o).length, 1);
});

test("o 23505 da unicidade do espelho devolve a encomenda que já existe", async () => {
  // **A segunda barreira a chegar como resposta e não como avaria.** Duas sagas
  // podem correr para a mesma chave — o `criado_at` não se reescreve, pelo que um
  // recibo retomado continua a parecer velho —, e quem as separa é a
  // `orders_mirror_intent_uq`. Sem o `catch`, ela chegava como excepção: numa
  // operação de classe `money`, um 500 em vez da encomenda que existe. Achado da
  // revisão adversarial.
  const chave = intentKey(ACTUAL, PARTES);
  const { m, o } = montar({
    termos: [termos()],
    // O recibo está `falhada` (logo esta saga retoma-o e segue) **e** a chave já
    // tem encomenda: é o estado que uma corrida perdida vê.
    recibos: [recibo(chave, "falhada")],
    encomendas: [{ intentKey: chave, numero: "DOVENCEDOR" }],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok", comoTexto(r));
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.numeroPublico, "DOVENCEDOR");
  assert.equal(r.valor.repeticao, true);
  assert.deepEqual(encomendas(o), ["DOVENCEDOR"], "uma, e não duas");
});

// -------------------------------------------------------- o anel, na saga

test("com o anel rodado, um recibo sob a versão anterior não cria segunda encomenda", async () => {
  // **O segundo achado que bloqueava.** O `ON CONFLICT` desempata pela chave
  // **actual**: um recibo derivado com a versão anterior não gerava conflito
  // nenhum, a saga ganhava, e nascia uma segunda encomenda para o mesmo
  // rascunho — a unicidade da revisão `0030` não junta o que a derivação
  // separou. Medido: duas linhas em `orders_mirror`, com a propriedade contrária
  // escrita no §3.44 e no inventário de segredos.
  const antiga = intentKey(ANTERIOR, PARTES);
  const { m, o } = montar({
    termos: [termos()],
    anel: ANEL_RODADO,
    recibos: [recibo(antiga, "concluida")],
    encomendas: [{ intentKey: antiga, numero: "ANTESDAROTACAO" }],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok", comoTexto(r));
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.repeticao, true);
  assert.equal(r.valor.numeroPublico, "ANTESDAROTACAO");
  assert.deepEqual(encomendas(o), ["ANTESDAROTACAO"], "uma, e não duas");
  assert.equal(chavesDoAnel(ANEL_RODADO, PARTES).length, 2);
  assert.notEqual(antiga, intentKey(ACTUAL, PARTES));
});

test("com o anel rodado e um recibo antigo abandonado, a encomenda nasce com a chave dele", async () => {
  // A chave operativa é a **do recibo** e não a actual: senão o espelho nascia
  // com uma `intent_key` que o recibo não conhece, e as duas barreiras do
  // Contexto deixavam de falar da mesma intenção.
  const antiga = intentKey(ANTERIOR, PARTES);
  const { m, o } = montar({
    termos: [termos()],
    anel: ANEL_RODADO,
    recibos: [recibo(antiga, "em_curso", 3)],
  });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok", comoTexto(r));
  const mirror = o.inseridas.find((i) => i["tabela"] === "orders_mirror");
  assert.equal(String(mirror?.["intent_key"]), antiga);
  assert.equal(o.intents.get(antiga)?.estado, "concluida");
  // E nenhum recibo novo nasceu sob a chave actual.
  assert.equal(o.intents.has(intentKey(ACTUAL, PARTES)), false);
});

test("com uma versão só, a saga não paga a leitura do anel", async () => {
  // O caso comum, e o de sempre até à primeira rotação: o `INSERT` serializa
  // como serializava, e não há `SQL_LER_INTENCAO` nenhum no caminho que ganha.
  const { m, o } = montar({ termos: [termos()] });
  assert.equal((await createOrder(m, PEDIDO)).tipo, "ok");
  assert.equal(o.consultas.includes(SQL_LER_INTENCAO), false);
});

// ------------------------------------------------ o facto do critério 8

test("a resposta inclui o pedido por pagar, e cria de qualquer forma", async () => {
  // **Nunca bloqueia em silêncio**, que é a segunda metade do critério: a
  // encomenda nasce **e** a resposta leva o facto para o agente perguntar.
  const { m, o } = montar({
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
  assert.equal(r.valor.repeticao, false);
  assert.equal(encomendas(o).length, 1, "criou");
  assert.equal(r.valor.pedidoPorPagar?.numeroPublico, "K7H3Q9");
  assert.equal(r.valor.pedidoPorPagar?.estado, "aguarda_pagamento");
  assert.equal(r.valor.pedidoPorPagar?.totalMinor, 250_000n);
});

test("sem pedido anterior o facto é null, e não um objecto vazio", async () => {
  const { m } = montar({ termos: [termos()] });
  const r = await createOrder(m, PEDIDO);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.pedidoPorPagar, null);
});

test("o facto lê-se antes de o recibo fechar", async () => {
  const { m, o } = montar({ termos: [termos()] });
  await createOrder(m, PEDIDO);
  const doFacto = o.consultas.indexOf(SQL_PEDIDO_POR_PAGAR);
  const doConcluir = o.consultas.indexOf(SQL_CONCLUIR_INTENCAO);
  assert.ok(doFacto >= 0, "a consulta do facto não correu");
  assert.ok(
    doFacto < doConcluir,
    "o facto tem de ser lido antes de o recibo fechar, senão aponta para a " +
      "encomenda que acabámos de criar",
  );
});

// ------------------------------------------- a fronteira da janela, à letra

test("as 14:04:59 e as 14:05:01 produzem uma encomenda, e a segunda repete", async () => {
  // **O critério 3 à letra**, e agora a depender da derivação: as duas chamadas
  // correm sobre a **mesma loja**, e o que faz a segunda encontrar o recibo da
  // primeira é a `intent_key` ser a mesma — a chave não tem tempo. Com a chave do
  // documento exploratório (`hash(msisdn + sku + janela_5min)`), que dá **duas**
  // chaves nesses dois instantes, este caso ficaria vermelho: duas encomendas.
  //
  // A primeira versão deste caso montava **dois** duplos independentes e
  // guionava a resposta da segunda; a revisão adversarial mostrou que ela
  // passaria igual com a chave antiga.
  const { m, o } = montar({ termos: [termos()] });
  const as0459 = new Date("2026-11-04T14:04:59.000Z").getTime();
  const as0501 = new Date("2026-11-04T14:05:01.000Z").getTime();

  const r1 = await createOrder({ ...m, agora: () => new Date(as0459) }, PEDIDO);
  assert.equal(r1.tipo, "ok");
  if (r1.tipo !== "ok") return;
  assert.equal(r1.valor.repeticao, false);

  const r2 = await createOrder({ ...m, agora: () => new Date(as0501) }, PEDIDO);
  assert.equal(r2.tipo, "ok");
  if (r2.tipo !== "ok") return;
  assert.equal(r2.valor.repeticao, true);
  assert.equal(r2.valor.orderId, r1.valor.orderId);
  assert.equal(encomendas(o).length, 1, "uma encomenda e não duas");
});

test("um draft_id novo, no mesmo instante, cria encomenda nova", async () => {
  // A recíproca, e o critério 4: o que separa duas encomendas é o rascunho, não
  // o relógio. Sem este caso ao lado do anterior, «a chave não tem tempo» ficava
  // indistinguível de «a chave é sempre a mesma».
  const { m, o } = montar({ termos: [termos()] });
  assert.equal((await createOrder(m, PEDIDO)).tipo, "ok");
  const segundo = await createOrder(m, {
    ...PEDIDO,
    rascunho: { ...RASCUNHO, draftId: "e".repeat(64) },
  });
  assert.equal(segundo.tipo, "ok");
  if (segundo.tipo !== "ok") return;
  assert.equal(segundo.valor.repeticao, false);
  assert.equal(encomendas(o).length, 2);
});

test("uma draft_version nova cria encomenda distinta", async () => {
  const { m, o } = montar({ termos: [termos()] });
  assert.equal((await createOrder(m, PEDIDO)).tipo, "ok");
  const editado = await createOrder(m, {
    ...PEDIDO,
    rascunho: { ...RASCUNHO, draftVersion: 2 },
  });
  assert.equal(editado.tipo, "ok");
  if (editado.tipo !== "ok") return;
  assert.equal(editado.valor.repeticao, false);
  assert.equal(encomendas(o).length, 2);
});

// --------------------------------------------------------- recusas de forma

test("um rascunho sem forma recusa-se sem escrever nada", async () => {
  const { m, o } = montar({ termos: [termos()] });
  assert.deepEqual(
    await createOrder(m, {
      ...PEDIDO,
      rascunho: { ...RASCUNHO, contactId: "+244923000000" },
    }),
    { tipo: "erro", erro: "VALIDATION_ERROR" },
  );
  recusouSemRasto(o, "contactId com telefone");
});

// ------------------------------------------- a barreira do repo-base, a sério

test("as oito cadeias novas passam pelo repo-base a sério, e não por um duplo", async () => {
  // **O que este caso fecha.** Em produção estas cadeias entram na base por
  // `repo.noTenant`, que é o repo-base do KAM-042 — e ele **recusa por
  // execução** uma consulta sem `tenant_id = $1` depois do primeiro `WHERE`, com
  // `UNION`, ou com a coluna do filtro num `SET`. Os duplos deste ficheiro não
  // correm essa verificação, e a suite do *gate* 8 fala com o `pg8000`
  // directamente: uma cadeia que o repo-base recusasse só rebentava em execução,
  // no primeiro chamador real.
  //
  // O `SQL_PEDIDO_POR_PAGAR` é o que mais vale medir: tem um `JOIN` cujo `ON`
  // contém `tenant_id =` **antes** do `WHERE`, e é precisamente o padrão que a
  // regra 2 daquele ficheiro existe para apanhar.
  const vistas: string[] = [];
  const r = repoBase(
    {
      async query(sql: string) {
        vistas.push(sql);
        return { rows: [] as Record<string, unknown>[] };
      },
    },
    TENANT,
    "merch_A",
  );
  const cadeias: readonly [string, string][] = [
    ["SQL_LER_INTENCAO", SQL_LER_INTENCAO],
    ["SQL_CONCLUIR_INTENCAO", SQL_CONCLUIR_INTENCAO],
    ["SQL_FALHAR_INTENCAO", SQL_FALHAR_INTENCAO],
    ["SQL_RETOMAR_INTENCAO", SQL_RETOMAR_INTENCAO],
    ["SQL_PEDIDO_POR_PAGAR", SQL_PEDIDO_POR_PAGAR],
    ["SQL_CONFIRMACAO_DO_DONO", SQL_CONFIRMACAO_DO_DONO],
    ["SQL_LER_CONFIRMACAO", SQL_LER_CONFIRMACAO],
    ["SQL_ENCOMENDA_DA_CHAVE", SQL_ENCOMENDA_DA_CHAVE],
  ];
  for (const [nome, sql] of cadeias) {
    await r.noTenant(sql, []);
    assert.ok(
      vistas.includes(sql),
      `o repo-base recusou a ${nome}: ela não chegou à base`,
    );
  }
  assert.equal(vistas.length, cadeias.length);
});

test("o canário: a mesma consulta sem o filtro de tenant é recusada", async () => {
  // Sem isto, o caso acima ficava verde com um repo-base que aceitasse tudo.
  const r = repoBase(
    {
      async query() {
        return { rows: [] as Record<string, unknown>[] };
      },
    },
    TENANT,
    "merch_A",
  );
  await assert.rejects(
    () =>
      r.noTenant(
        SQL_PEDIDO_POR_PAGAR.replace("WHERE i.tenant_id = $1", "WHERE true"),
        [],
      ),
    FiltroEmFaltaError,
  );
});

test("cada marcador aparece uma só vez: o pg8000 da suite não repete um $n", async () => {
  // O `ConsultaDoTypeScript` de `db/tests/base.py` **recusa** um marcador
  // repetido — não há equivalente posicional para o mesmo argumento usado duas
  // vezes no `pg8000`. Uma cadeia com `$2` duas vezes passava pelo `tsc` e
  // rebentava no gate 8, longe de quem a escreveu.
  for (const [nome, sql] of [
    ["SQL_LER_INTENCAO", SQL_LER_INTENCAO],
    ["SQL_CONCLUIR_INTENCAO", SQL_CONCLUIR_INTENCAO],
    ["SQL_FALHAR_INTENCAO", SQL_FALHAR_INTENCAO],
    ["SQL_RETOMAR_INTENCAO", SQL_RETOMAR_INTENCAO],
    ["SQL_PEDIDO_POR_PAGAR", SQL_PEDIDO_POR_PAGAR],
    ["SQL_CONFIRMACAO_DO_DONO", SQL_CONFIRMACAO_DO_DONO],
    ["SQL_LER_CONFIRMACAO", SQL_LER_CONFIRMACAO],
    ["SQL_ENCOMENDA_DA_CHAVE", SQL_ENCOMENDA_DA_CHAVE],
  ] as const) {
    const marcadores = [...sql.matchAll(/\$(\d+)/g)].map((m) => m[1]);
    assert.equal(
      new Set(marcadores).size,
      marcadores.length,
      `${nome} repete um marcador: ${marcadores.join(", ")}`,
    );
    const numeros = [...new Set(marcadores)].map(Number).sort((a, b) => a - b);
    assert.deepEqual(
      numeros,
      Array.from({ length: numeros.length }, (_, i) => i + 1),
      `${nome} tem buracos na numeração: ${numeros.join(", ")}`,
    );
  }
});
