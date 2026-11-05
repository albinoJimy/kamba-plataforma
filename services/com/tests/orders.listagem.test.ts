/**
 * O `getOrder`, o `listOrders` e o cursor opaco (KAM-178, critérios 3 e 4).
 *
 * ## O que esta suite prova, e o que não pode provar
 *
 * Prova as **três** barreiras do ISO-10 sobre o `listOrders` — filtro vazio,
 * cursor forjado e `OR` injectado — e prova-as com uma asserção por caso, que é
 * o que o KAM-042 pedia em troca da asserção única de `xfail strict` daquele
 * método. E prova que nenhuma delas chega à base: a base de ensaio **explode**
 * se lhe falarem no caminho das recusas.
 *
 * O que não prova é a segunda barreira: a RLS `FORCE` da revisão `0030` não
 * existe em JavaScript, e mede-se em `db/tests_encomendas/test_isolamento.py`
 * com o `kamba_app` contra um PostgreSQL real. A separação é a mesma que o
 * `port.iso.test.ts` escreve: medir aqui a RLS era medir a porta duas vezes e a
 * RLS nenhuma.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LIMITE_MAXIMO,
  LIMITE_POR_OMISSAO,
  SQL_LISTAR,
  SQL_VISTA,
  TABELA_DAS_DIVERGENCIAS,
  TABELA_DO_ESPELHO,
  TABELA_DO_REGISTO,
  cartId,
  cifrarCursor,
  getOrder,
  lerCursor,
  listOrders,
  type AnelDoSegredo,
  type Leitura,
} from "../src/orders/index.ts";
import { repoBase } from "../src/repo-base/index.ts";
import type { ClienteSql, Ctx } from "../src/port/index.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CONTACTO = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";
const ORDER_DE_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";

const ACTUAL = `v2:${Buffer.alloc(32, 7).toString("base64")}`;
const ANTERIOR = `v1:${Buffer.alloc(32, 3).toString("base64")}`;
const ANEL: AnelDoSegredo = [ACTUAL, null];
const ANEL_RODADO: AnelDoSegredo = [ACTUAL, ANTERIOR];

function ctx(tenantId: string = TENANT_A): Ctx {
  return {
    tenantId,
    actor: { kind: "agente", id: "grafo-vendedor" },
    traceId: "trace-listagem",
  };
}

/** Uma linha de `orders_mirror`, na forma que a base devolve. */
function linha(i: number, tenant: string = TENANT_A) {
  return {
    id: `0000000${i}-0000-4000-8000-000000000000`,
    numero_publico: `K7H3Q${i}`,
    estado: "criada",
    version: 1,
    total_minor: String(1_250_000 * i),
    currency: "AOA",
    contact_id: CONTACTO,
    lines_snapshot: [
      {
        sku: "arroz-5kg",
        nome: "Arroz 5 kg",
        qty: i,
        preco_minor: "1250000",
        preco_tipo: "fixo",
        origem_preco: "offer_terms",
      },
    ],
    criado_at: `2026-11-0${i}T10:00:00.000Z`,
    _tenant: tenant,
  };
}

/** Uma base que filtra pelo `$1` que o repo-base lhe passa, e guarda o SQL. */
function baseDeEnsaio(linhas: readonly ReturnType<typeof linha>[]) {
  const vistos: { sql: string; parametros: readonly unknown[] }[] = [];
  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      vistos.push({ sql, parametros });
      const tenant = parametros[0];
      // **Filtra pelo argumento**, que é a forma de afirmar que o adaptador
      // passou o tenant do `ctx` e não outro: uma base que o ignorasse deixava
      // estes casos verdes sobre uma porta que não filtra nada.
      let saida = linhas.filter((l) => l._tenant === tenant);
      // **Ramifica pelo SQL e não pela posição dos argumentos**, e é uma
      // correcção que custou um caso vermelho: o `SQL_VISTA` tem o `order_id`
      // em `$2` e o `SQL_LISTAR` tem lá o `estado`, pelo que uma base que lesse
      // `parametros[1]` como estado em ambos filtrava o `getOrder` por um
      // estado que é um UUID — e devolvia zero linhas sempre.
      if (sql === SQL_VISTA) {
        saida = saida.filter((l) => l.id === parametros[1]);
        return { rows: saida.map(({ _tenant, ...resto }) => resto) };
      }
      // **Os cinco argumentos, e não três.** A primeira versão deste duplo
      // ignorava o `contactId` (`$3`) e o `id` do desempate do cursor (`$5`),
      // pelo que o filtro por contacto não tinha caminho legítimo medido e a
      // razão escrita para o `id` entrar na ordem — «duas encomendas podem
      // nascer no mesmo microssegundo» — **não podia** ser medida: o duplo não
      // olhava para o argumento. Achado da revisão adversarial.
      const estado = parametros[1];
      const contacto = parametros[2];
      const cursorAt = parametros[3];
      const cursorId = parametros[4];
      if (typeof estado === "string") {
        saida = saida.filter((l) => l.estado === estado);
      }
      if (typeof contacto === "string") {
        saida = saida.filter((l) => l.contact_id === contacto);
      }
      if (typeof cursorAt === "string") {
        // A comparação de linhas do `SQL_LISTAR`: `(criado_at, id) < ($4, $5)`.
        // Com o desempate, e não só pelo instante — é o que o cursor precisa
        // quando duas linhas nascem no mesmo microssegundo.
        const id = typeof cursorId === "string" ? cursorId : "";
        saida = saida.filter(
          (l) =>
            l.criado_at < cursorAt || (l.criado_at === cursorAt && l.id < id),
        );
      }
      saida = [...saida].sort((a, b) =>
        a.criado_at === b.criado_at
          ? a.id < b.id
            ? 1
            : -1
          : a.criado_at < b.criado_at
            ? 1
            : -1,
      );
      const limite = parametros[5];
      if (typeof limite === "number") saida = saida.slice(0, limite);
      return { rows: saida.map(({ _tenant, ...resto }) => resto) };
    },
  };
  return { cliente, vistos };
}

/** Uma base que **explode** se lhe falarem. Para as recusas sem consulta. */
const CLIENTE_PROIBIDO: ClienteSql = {
  async query() {
    throw new Error("a listagem foi a base num caminho que devia recusar antes");
  },
};

function leitura(cliente: ClienteSql, tenant = TENANT_A): Leitura {
  return { ctx: ctx(tenant), repo: repoBase(cliente, tenant, "merch") };
}

// ------------------------------------------------------- ISO-10, os três casos

test("ISO-10 (1/3): filtro vazio e VALIDATION_ERROR, e nao lista tudo", async () => {
  // **E recusa-se antes de haver consulta**: o `CLIENTE_PROIBIDO` explodiria.
  // Uma listagem sem filtro de domínio varre as encomendas inteiras de um
  // tenant por uma chamada de agente — e o consumidor desta porta é um grafo
  // que responde a um cliente, que pergunta sempre por um dos dois.
  const r = await listOrders(leitura(CLIENTE_PROIBIDO), ANEL, {});
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("ISO-10 (1/3): o cursor sozinho nao conta como filtro", async () => {
  // Paginação não é filtro: um cursor sem `estado` nem `contactId` não diz o
  // que se está a listar, e aceitá-lo era a mesma varredura com outro nome.
  const cursor = cifrarCursor(ANEL, TENANT_A, {
    criadoAt: "2026-11-03T10:00:00.000Z",
    id: linha(3).id,
  });
  const r = await listOrders(leitura(CLIENTE_PROIBIDO), ANEL, { cursor });
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("ISO-10 (2/3): um cursor forjado e VALIDATION_ERROR, e nao a primeira pagina", async () => {
  // **Servir a primeira página a quem forjou um cursor dizia-lhe «este cursor
  // vale».** Cinco formas de forjado, e a última é a que importa: um cursor
  // **legítimo de outro tenant**, que é o caso que o `tenant_id` dentro do HMAC
  // existe para fechar.
  const doOutroTenant = cifrarCursor(ANEL, TENANT_B, {
    criadoAt: "2026-11-03T10:00:00.000Z",
    id: ORDER_DE_B,
  });
  const forjados = [
    "ZmFsc2lmaWNhZG8=",
    "sem-ponto",
    "YWJj.YWJj",
    `${Buffer.from("2026-11-03T10:00:00.000Z|" + ORDER_DE_B).toString("base64url")}.${Buffer.alloc(16, 9).toString("base64url")}`,
    doOutroTenant,
  ];
  for (const cursor of forjados) {
    const r = await listOrders(leitura(CLIENTE_PROIBIDO), ANEL, {
      estado: "criada",
      cursor,
    });
    assert.deepEqual(
      r,
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      `cursor forjado aceite: ${cursor}`,
    );
  }
});

test("ISO-10 (3/3): um OR injectado num filtro e VALIDATION_ERROR", async () => {
  // Os valores são parametrizados de qualquer modo; o que estes casos provam é
  // que a **forma** os recusa antes de haver consulta — e que o `OR` não alarga
  // o conjunto, porque não chega à base.
  const injeccoes = [
    { contactId: "' OR 1=1 --" },
    { contactId: `${CONTACTO}' OR '1'='1` },
    { estado: "criada' OR 1=1 --" },
    { estado: "paga; DROP TABLE platform.orders_mirror" },
  ];
  for (const filtro of injeccoes) {
    const r = await listOrders(
      leitura(CLIENTE_PROIBIDO),
      ANEL,
      filtro as never,
    );
    assert.deepEqual(
      r,
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      JSON.stringify(filtro),
    );
  }
});

test("ISO-10: nenhuma das recusas devolve a linha de outro tenant", async () => {
  // A asserção que fecha a gama: com as linhas de B na base e um `ctx` de A, as
  // três recusas não devolvem **nada** — e a base de A não tem linhas.
  const { cliente, vistos } = baseDeEnsaio([linha(1, TENANT_B)]);
  for (const filtro of [
    {},
    { estado: "criada", cursor: "forjado" },
    { contactId: "' OR 1=1 --" },
  ]) {
    const r = await listOrders(leitura(cliente), ANEL, filtro as never);
    assert.equal(r.tipo, "erro", JSON.stringify(filtro));
  }
  assert.deepEqual(vistos, [], "nenhuma das tres recusas foi a base");
});

// ----------------------------------------------------------- o caminho legítimo

test("o listOrders devolve a pagina do tenant do ctx, e so a dele", async () => {
  const { cliente, vistos } = baseDeEnsaio([
    linha(1),
    linha(2),
    linha(3, TENANT_B),
  ]);
  const r = await listOrders(leitura(cliente), ANEL, { estado: "criada" });
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.itens.length, 2);
  // **O tenant que foi ao predicado é o do `ctx` e mais nenhum.**
  assert.deepEqual([...new Set(vistos.map((v) => v.parametros[0]))], [TENANT_A]);
  // E a `OrderView` tem a forma do §3.2, com o `totalMinor` em `bigint`.
  const primeira = r.valor.itens[0];
  assert.equal(typeof primeira?.totalMinor, "bigint");
  assert.equal(primeira?.contactId, CONTACTO);
  assert.equal(primeira?.linhas.length, 1);
});

test("o cursor pagina sem repetir nem perder linhas", async () => {
  const todas = [linha(1), linha(2), linha(3)];
  const { cliente } = baseDeEnsaio(todas);
  const primeira = await listOrders(leitura(cliente), ANEL, {
    estado: "criada",
    limite: 2,
  });
  assert.equal(primeira.tipo, "ok");
  if (primeira.tipo !== "ok") return;
  assert.equal(primeira.valor.itens.length, 2);
  assert.notEqual(primeira.valor.proximo, null, "ha mais, logo ha cursor");

  const segunda = await listOrders(leitura(cliente), ANEL, {
    estado: "criada",
    limite: 2,
    cursor: primeira.valor.proximo,
  });
  assert.equal(segunda.tipo, "ok");
  if (segunda.tipo !== "ok") return;
  assert.equal(segunda.valor.itens.length, 1);
  // **A última página não emite cursor**, e é o que distingue «acabou» de «há
  // mais»: um cursor que não leva a nada obrigava o cliente a uma chamada vazia.
  assert.equal(segunda.valor.proximo, null);

  const ids = [
    ...primeira.valor.itens.map((i) => i.orderId),
    ...segunda.valor.itens.map((i) => i.orderId),
  ];
  assert.equal(new Set(ids).size, 3, "nenhuma linha repetida");
  assert.equal(ids.length, 3, "nenhuma linha perdida");
});

test("o limite tem tecto, e um pedido acima dele recusa em vez de cortar", async () => {
  // Atender `limite: 10000` com cem linhas dizia a quem chama que o tenant só
  // tem cem encomendas.
  for (const limite of [0, -1, 1.5, LIMITE_MAXIMO + 1]) {
    const r = await listOrders(leitura(CLIENTE_PROIBIDO), ANEL, {
      estado: "criada",
      limite,
    });
    assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" }, `${limite}`);
  }
});

test("sem limite, o pedido a base pede o de omissao mais um", async () => {
  const { cliente, vistos } = baseDeEnsaio([linha(1)]);
  await listOrders(leitura(cliente), ANEL, { estado: "criada" });
  const listagem = vistos.find((v) => v.sql === SQL_LISTAR);
  assert.equal(listagem?.parametros[5], LIMITE_POR_OMISSAO + 1);
});

// ------------------------------------------------------------------- o cursor

test("o cursor fecha ida e volta, e nao se le com a chave de outro tenant", () => {
  const posicao = { criadoAt: "2026-11-03T10:00:00.000Z", id: linha(3).id };
  const cursor = cifrarCursor(ANEL, TENANT_A, posicao);
  assert.deepEqual(lerCursor(ANEL, TENANT_A, cursor), posicao);
  // **O `tenant_id` está dentro do HMAC.** Sem isso, o cursor de um tenant era
  // um cursor válido para outro — e aceitar a *posição* de outro tenant dizia a
  // quem a tivesse que aquela encomenda existe.
  assert.equal(lerCursor(ANEL, TENANT_B, cursor), null);
});

test("um cursor emitido antes da rotacao continua a valer", () => {
  // A paginação de um cliente não pode partir porque o segredo rodou: ele não
  // tem como saber que rodou. É a letra do `SecretRing` do `secrets/port.ts`.
  const posicao = { criadoAt: "2026-11-03T10:00:00.000Z", id: linha(3).id };
  const antigo = cifrarCursor([ANTERIOR, null], TENANT_A, posicao);
  assert.deepEqual(lerCursor(ANEL_RODADO, TENANT_A, antigo), posicao);
  // E com o anel **sem** a versão anterior, o mesmo cursor deixa de valer.
  assert.equal(lerCursor(ANEL, TENANT_A, antigo), null);
});

test("o cursor nao e o cart_id: o mesmo segredo nao produz o mesmo valor", () => {
  // **A comparação é com um `cart_id` a sério**, e a primeira versão deste caso
  // não derivava nenhum: ela afirmava `!cursor.includes(posicao.id)`, que passa
  // por o corpo ser base64 — e o próprio módulo diz que o corpo **é legível**
  // («é opaco, não secreto»). Media codificação, não separação de domínio.
  // Achado da revisão adversarial.
  //
  // A propriedade que a nota do módulo vende como razão para **não** haver um
  // segredo próprio para cursores é esta: a separação está no domínio e não na
  // chave, pelo que o mesmo segredo e as mesmas partes dão valores diferentes.
  const posicao = { criadoAt: "2026-11-03T10:00:00.000Z", id: linha(3).id };
  const cursor = cifrarCursor(ANEL, TENANT_A, posicao);
  const doCarrinho = cartId(ACTUAL, {
    tenantId: TENANT_A,
    contactId: CONTACTO,
    draftId: posicao.id,
    draftVersion: 1,
  });
  assert.notEqual(cursor, doCarrinho);
  assert.ok(!cursor.includes(doCarrinho), "o cursor nao contem o cart_id");
  assert.ok(!doCarrinho.includes(cursor), "o cart_id nao contem o cursor");
  // E um `cart_id` **não** se lê como cursor: a verificação do cursor recusa-o,
  // o que é a metade que importa para quem tentar passar um pelo outro.
  assert.equal(lerCursor(ANEL, TENANT_A, doCarrinho), null);

  // A assinatura é que manda: um corpo alterado não passa.
  const [corpo] = cursor.split(".");
  const outro = `${corpo}.${Buffer.alloc(16, 1).toString("base64url")}`;
  assert.equal(lerCursor(ANEL, TENANT_A, outro), null);
});

test("o filtro por contacto tem caminho legitimo, e nao devolve o de outro", async () => {
  // **O filtro por contacto não tinha caminho legítimo medido**: o duplo de
  // ensaio ignorava o `$3`. Agora honra-o, e este caso é o que o prova — com
  // duas encomendas de dois contactos do mesmo tenant.
  const OUTRO = "9d1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";
  const minhas = linha(1);
  const dele = { ...linha(2), contact_id: OUTRO };
  const { cliente, vistos } = baseDeEnsaio([minhas, dele]);
  const r = await listOrders(leitura(cliente), ANEL, { contactId: CONTACTO });
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.deepEqual(
    r.valor.itens.map((i) => i.orderId),
    [minhas.id],
  );
  // E o contacto foi ao predicado como `$3`, e não ficou pelo lado do cliente.
  const listagem = vistos.find((v) => v.sql === SQL_LISTAR);
  assert.equal(listagem?.parametros[2], CONTACTO);
});

test("o cursor desempata pelo id quando duas linhas nascem no mesmo instante", async () => {
  // **A razão escrita para o `id` entrar na ordem, medida.** Duas encomendas no
  // mesmo microssegundo: sem o desempate, a segunda página saltava uma delas ou
  // repetia-a. O `SQL_LISTAR` ordena por `(criado_at DESC, id DESC)` e compara
  // a linha inteira; é essa comparação que este caso exercita.
  const mesmo = "2026-11-02T10:00:00.000Z";
  const a = { ...linha(1), criado_at: mesmo };
  const b = { ...linha(2), criado_at: mesmo };
  const { cliente } = baseDeEnsaio([a, b]);

  const primeira = await listOrders(leitura(cliente), ANEL, {
    estado: "criada",
    limite: 1,
  });
  assert.equal(primeira.tipo, "ok");
  if (primeira.tipo !== "ok") return;
  assert.equal(primeira.valor.itens.length, 1);
  assert.notEqual(primeira.valor.proximo, null);

  const segunda = await listOrders(leitura(cliente), ANEL, {
    estado: "criada",
    limite: 1,
    cursor: primeira.valor.proximo,
  });
  assert.equal(segunda.tipo, "ok");
  if (segunda.tipo !== "ok") return;
  assert.equal(segunda.valor.itens.length, 1, "a segunda linha foi saltada");
  const ids = [
    primeira.valor.itens[0]?.orderId,
    segunda.valor.itens[0]?.orderId,
  ];
  assert.equal(new Set(ids).size, 2, "a mesma linha veio duas vezes");
  assert.deepEqual([...ids].sort(), [a.id, b.id].sort());
});

// ------------------------------------------------------------------- getOrder

test("ISO-01..08: getOrder com ctx de A sobre um id de B da NOT_FOUND", async () => {
  const { cliente, vistos } = baseDeEnsaio([linha(1, TENANT_B)]);
  const r = await getOrder(leitura(cliente), linha(1).id);
  // **`NOT_FOUND` e nao a linha de B, e nao `TENANT_MISMATCH`:** distinguir «não
  // existe» de «existe e não é tua» era um oráculo, que é exactamente a pergunta
  // que o ISO-01..08 faz.
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  assert.deepEqual([...new Set(vistos.map((v) => v.parametros[0]))], [TENANT_A]);
});

test("o getOrder le pelo SQL_VISTA e devolve a OrderView do §3.2", async () => {
  const { cliente, vistos } = baseDeEnsaio([linha(1)]);
  const r = await getOrder(leitura(cliente), linha(1).id);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.numeroPublico, "K7H3Q1");
  assert.equal(r.valor.totalMinor, 1_250_000n);
  assert.equal(r.valor.criadoAt, "2026-11-01T10:00:00.000Z");
  assert.equal(vistos[0]?.sql, SQL_VISTA);
});

test("um order_id que nao e UUID e VALIDATION_ERROR, sem ir a base", async () => {
  const r = await getOrder(leitura(CLIENTE_PROIBIDO), "' OR 1=1 --");
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

// ------------------------------------------- as tres tabelas, pelo esquema

test("as tres constantes de tabela estao qualificadas pelo esquema", () => {
  // **A correcção não estava presa por nada**, e podia regredir em silêncio:
  // todos os testes referem a constante e nunca o literal, e a suite de base de
  // dados escreve os três `INSERT` ela própria. Medido pela revisão
  // adversarial, que tirou o `platform.` e viu a bateria inteira verde.
  //
  // **O que esta asserção é, e o que não é:** é sobre o **nome**, porque o
  // `42P01` só acontece contra um PostgreSQL sem `search_path` — e isso é do
  // *gate* 8, onde as cadeias do módulo correm a sério. Uma asserção sobre o
  // nome é mais fraca do que a base, e é a que existe em JavaScript; fica dita
  // em vez de se deixar a impressão de que mede o erro.
  for (const tabela of [
    TABELA_DO_ESPELHO,
    TABELA_DO_REGISTO,
    TABELA_DAS_DIVERGENCIAS,
  ]) {
    assert.match(
      tabela,
      /^platform\./,
      `${tabela} sem esquema: o inserirNoTenant constroi o INSERT com este ` +
        "nome, nada poe o search_path, e ela morre em 42P01 (KAM-178)",
    );
  }
});
