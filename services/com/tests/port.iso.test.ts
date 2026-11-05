/**
 * A suite ISO do adaptador da opção B (KAM-042, critérios 1, 2 e 6).
 *
 * ## O `xfail strict`, e porque não é um `todo` do `node:test`
 *
 * O critério 6 pede: «cada [método não implementado] tem teste de isolamento
 * marcado *xfail strict* que falha quando a implementação chegar sem teste». O
 * vocabulário é do pytest, e o `node:test` não o tem: o `{ todo: true }` de um
 * teste que **passa** é reportado como *todo* e **não** falha a suite, que é o
 * contrário do que «strict» quer dizer.
 *
 * A forma que tem a semântica certa, e que está aqui, é mais simples do que uma
 * marca: **afirmar o `NOT_IMPLEMENTED`**. Enquanto o método não estiver
 * implementado, a asserção passa. No dia em que alguém o implementar e não
 * substituir este caso pelo teste de isolamento a sério, a asserção **falha** —
 * e falha com a mensagem que diz qual é o ticket dono e o que o substitui. É
 * exactamente o `xfail strict` do critério, escrito no que a casa tem.
 *
 * ## O que esta suite cobre, e o que não pode cobrir hoje
 *
 *   ISO-09            **medido e verde**: as doze operações com `ctx` sem
 *                     `tenantId` falham, e falham antes de pedirem ligação.
 *   ISO-01..08, 10    **não medidos, e não é omissão**: «operações da porta com
 *                     `ctx` de A sobre ids de B» precisa de uma operação que
 *                     leia algo, e as doze devolvem `NOT_IMPLEMENTED`. Ficam
 *                     como os `xfail strict` deste ficheiro.
 *   ISO-11..32        **fora deste ficheiro**: são a Store API, a Admin API e o
 *                     *query graph* do Medusa, e exigem um Medusa a correr. A
 *                     única medição que existe é a do KAM-041
 *                     (`spikes/medusa-d3/resultados/iso.json`, 2026-10-27), e
 *                     **o ISO-15 está vermelho lá** — um passe indevido real na
 *                     Store API.
 *   ISO-57..60        ignorados pelo critério 2, por escrito.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CtxEmFaltaError,
  METODOS_DA_PORTA,
  type ClienteSql,
  type CommerceRegistry,
  type Ctx,
} from "../src/port/index.ts";
import {
  adaptadorMedusa,
  comRegisto,
  type Dependencias,
} from "../src/adapters/medusa/index.ts";
import {
  MerchantEmFaltaError,
  TenantDesconhecidoError,
} from "../src/repo-base/index.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const ORDER_DE_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";
const CONTACTO_DE_B = "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c";

/**
 * Os três métodos que o **KAM-043** implementou, e que já não são
 * `NOT_IMPLEMENTED`.
 *
 * **Esta lista é o que substitui as três asserções de `xfail strict`.** O
 * critério 6 do KAM-042 pede que cada método não implementado tenha um caso que
 * «falha quando a implementação chegar sem teste»; os três chegaram **com**
 * teste, e os testes estão em `TestOIsolamentoDosTresDoKam043` abaixo. A
 * asserção que os cobria passa a cobrir os nove que restam, e o `METODOS_DA_PORTA`
 * menos esta lista é o que ela percorre — para que o dia em que o KAM-044
 * implementar o `createOrder` sem o tirar daqui continue a falhar.
 */
const IMPLEMENTADOS = new Set<string>([
  "upsertProductDraft",
  "publishProduct",
  "getOfferView",
  // Os quatro que o KAM-178 ligou: o fluxo do dono, a primitiva de transição e
  // as duas leituras. Ver o `docs/com/port-coverage.md` §2.
  "requestOwnerConfirmation",
  "transition",
  "getOrder",
  "listOrders",
  // **As quatro das reservas, ligadas pelo KAM-045.** Entram aqui **e** levam o
  // teste de isolamento a sério em `TestOIsolamentoDasQuatroDoKam045`, que é a
  // troca que o critério 6 do KAM-042 pede por cada `xfail strict` que
  // desaparece. Sem a entrada nesta lista, aquele caso desaparecia sem ninguém
  // notar — é o que o próprio texto da asserção avisa.
  "reserveStock",
  "extendReservation",
  "commitReservation",
  "releaseReservation",
]);

/**
 * O ticket dono de cada método **ainda não implementado**. A mesma tabela que
 * `port-coverage.md`, e a duplicação é deliberada: um documento não falha um
 * *build*, e o critério 6 pede que a cobertura da porta seja verificável e não
 * lida.
 */
const DONO: Readonly<Record<string, string>> = {
  // **O credor deste não é um ticket de implementação: é uma decisão.** A *saga*
  // do §6.3 existe e serve-se pela API interna; o que não se consegue ligar é o
  // método, porque o `OrderIntent` do §3.2 não tem `draftId`, `draftVersion` nem
  // `totalEsperadoMinor` — e o terceiro contradiz a regra 4 do §3.2 («nenhuma
  // operação aceita um preço do chamador»), escrita na nota do próprio tipo.
  // Ligá-lo pede um **terceiro** movimento no §3.39, e a decisão de 2026-11-04
  // autoriza dois. Ver a verificação do bloco KAM-178.
  createOrder: "KAM-178",
  // As quatro das reservas saíram desta tabela com o **KAM-045**, que as ligou:
  // estão no `IMPLEMENTADOS` acima e o isolamento delas está medido em
  // `TestOIsolamentoDasQuatroDoKam045`. A partição do `METODOS_DA_PORTA` entre
  // esta tabela e aquela lista é verificada por asserção, pelo que tirá-las de
  // um lado sem as pôr no outro faz a suite falhar.
};

/** Argumentos plausíveis por método, com **ids do tenant B** (ISO-01..08). */
const ARGUMENTOS: Readonly<Record<string, readonly unknown[]>> = {
  upsertProductDraft: [{ sku: "sku-de-b", nome: "x" }],
  publishProduct: [
    { sku: "sku-de-b", registoId: "prod_de_b" },
    { actor: { kind: "dono", id: "dono-de-b" }, em: "2026-10-30T00:00:00Z" },
  ],
  getOfferView: ["sku-de-b"],
  createOrder: [
    {
      intentKey: "i".repeat(26),
      contactId: "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c",
      linhas: [{ sku: "sku-de-b", qty: 1 }],
      entregaModo: "levantamento",
    },
  ],
  requestOwnerConfirmation: [ORDER_DE_B],
  reserveStock: [ORDER_DE_B, 48 * 60 * 60 * 1000],
  extendReservation: [ORDER_DE_B, "2026-11-01T00:00:00Z"],
  commitReservation: [ORDER_DE_B],
  releaseReservation: [ORDER_DE_B, "expirada"],
  transition: [ORDER_DE_B, "paga", 1, { causa: "payment.confirmed" }],
  getOrder: [ORDER_DE_B],
  listOrders: [{ estado: "paga" }],
};

/** Uma ligação que **explode** se alguém lhe falar. Ver o teste do ISO-09. */
const CLIENTE_PROIBIDO: ClienteSql = {
  async query() {
    throw new Error(
      "o adaptador pediu a base com um ctx que o exigirCtx devia ter recusado",
    );
  },
};

/** O anel do `segredo_intents`, que o adaptador exige desde o KAM-178. */
const ANEL: readonly [string, string | null] = [
  `v1:${Buffer.alloc(32, 7).toString("base64")}`,
  null,
];

function deps(cliente: ClienteSql = CLIENTE_PROIBIDO): Dependencias {
  return {
    comTenant: async (_tenantId, trabalho) => trabalho(cliente),
    anel: ANEL,
  };
}

function ctx(tenantId: string = TENANT_A): Ctx {
  return {
    tenantId,
    actor: { kind: "agente", id: "grafo-vendedor" },
    traceId: "trace-iso",
  };
}

function chamar(
  porta: CommerceRegistry,
  metodo: string,
  contexto: Ctx,
): Promise<unknown> {
  const fn = (porta as unknown as Record<string, unknown>)[metodo];
  assert.equal(typeof fn, "function", `${metodo} nao existe na porta`);
  return (fn as (...a: unknown[]) => Promise<unknown>).call(
    porta,
    contexto,
    ...(ARGUMENTOS[metodo] ?? []),
  );
}

// ------------------------------------------------------------------- ISO-09

test("ISO-09: as doze operacoes sem ctx.tenantId falham, e sem tocar na base", async () => {
  const porta = adaptadorMedusa(deps());
  const semTenant = { ...ctx(), tenantId: "" };

  for (const metodo of METODOS_DA_PORTA) {
    await assert.rejects(
      () => chamar(porta, metodo, semTenant),
      CtxEmFaltaError,
      metodo,
    );
  }
  // O `CLIENTE_PROIBIDO` lança se lhe falarem. Doze rejeições com
  // `CtxEmFaltaError` — e não com o `Error` dele — provam que nenhuma das doze
  // chegou a pedir ligação.
});

test("ISO-09: um tenant que nao e UUID canonico tambem falha fechado", async () => {
  const porta = adaptadorMedusa(deps());
  for (const mau of ["", "   ", "nao-e-uuid", "' OR 1=1 --"]) {
    await assert.rejects(
      () => chamar(porta, "getOrder", { ...ctx(), tenantId: mau }),
      CtxEmFaltaError,
      mau,
    );
  }
});

// ---------------------------------------------- critério 5 no caminho real

test("criterio 5: um tenant por provisionar nao abre operacao no Registo", async () => {
  // O `comRegisto` é por onde cada implementação vai entrar. Um tenant sem
  // `medusa_merchant_id` **não** chega ao corpo do trabalho.
  let correu = false;
  const cliente: ClienteSql = {
    async query() {
      return { rows: [{ medusa_merchant_id: null, medusa_sales_channel_id: null }] };
    },
  };
  await assert.rejects(
    () =>
      comRegisto(deps(cliente), ctx(TENANT_B), async () => {
        correu = true;
      }),
    MerchantEmFaltaError,
  );
  assert.equal(correu, false);
});

test("criterio 1: um tenant bem formado e inexistente falha fechado", async () => {
  // **A lacuna que a revisao adversarial nomeou.** O criterio 1 pede «chamada
  // sem `ctx.tenantId` **ou com tenant inexistente** falha fechada», e sao duas
  // coisas: a primeira e do `exigirCtx` e vale nos doze metodos; a segunda
  // precisa de ir a base, e por isso vive no `comRegisto`. **Nenhum dos doze
  // metodos chama o `comRegisto` hoje** — com um tenant bem formado e
  // inexistente, a resposta de qualquer um deles e `NOT_IMPLEMENTED` e nao uma
  // recusa por tenant. E isto que a fecha no caminho onde ela existe, e a
  // metade que falta esta escrita na verificacao do bloco.
  let correu = false;
  const cliente: ClienteSql = {
    async query() {
      return { rows: [] };
    },
  };
  await assert.rejects(
    () =>
      comRegisto(deps(cliente), ctx(TENANT_B), async () => {
        correu = true;
      }),
    TenantDesconhecidoError,
  );
  assert.equal(correu, false);
});

test("criterio 5: com merchant provisionado, o repo nasce ligado a ele", async () => {
  const cliente: ClienteSql = {
    async query() {
      return {
        rows: [{ medusa_merchant_id: "merch_A", medusa_sales_channel_id: "sc_A" }],
      };
    },
  };
  const visto = await comRegisto(deps(cliente), ctx(TENANT_A), async (r) => ({
    tenant: r.repo.tenantId,
    merchant: r.ids.merchantId,
    actor: r.ctx.actor.kind,
    // **O `ClienteSql` cru nao esta no `Registo`**, e a revisao adversarial
    // mostrou porque: com ele ao lado do `repo`, o KAM-043 escrevia
    // `r.cliente.query("SELECT * FROM product")` — sem filtro, sem recusa, sem
    // contador — e a frase «nao ha caminho» era a unica barreira.
    temClienteCru: "cliente" in r,
  }));
  assert.deepEqual(visto, {
    tenant: TENANT_A,
    merchant: "merch_A",
    actor: "agente",
    temClienteCru: false,
  });
});

// --------------------------------------------- ISO-01..08 e 10: xfail strict

test("a particao entre implementados e por implementar cobre os doze", () => {
  // **Sem isto, a lista acima podia crescer sem ninguem notar** e os casos de
  // `xfail strict` desapareciam um a um em silencio — que e o contrario do que
  // «strict» quer dizer. Os doze da porta sao exactamente os implementados
  // mais os que tem ticket dono, sem sobreposicao.
  //
  // **A contagem e presa de proposito: quem a mexe vem ler porque.** Era `7` e
  // `5` depois do KAM-178; passa a `11` e `1` com o KAM-045, que ligou as
  // quatro das reservas — e a troca que o criterio 6 do KAM-042 pede por cada
  // `xfail strict` que desaparece esta paga pelo
  // `ISO-01..08: as quatro reservas do KAM-045 passam o tenant do ctx`.
  assert.equal(
    IMPLEMENTADOS.size,
    11,
    "tres do KAM-043, quatro do KAM-178 e quatro do KAM-045",
  );
  assert.equal(
    Object.keys(DONO).length,
    1,
    "so o createOrder, e o credor dele e uma decisao e nao um ticket",
  );
  for (const metodo of METODOS_DA_PORTA) {
    assert.equal(
      IMPLEMENTADOS.has(metodo) !== (metodo in DONO),
      true,
      `${metodo} esta nas duas listas ou em nenhuma`,
    );
  }
  assert.equal(
    IMPLEMENTADOS.size + Object.keys(DONO).length,
    METODOS_DA_PORTA.length,
    "a particao tem de cobrir os doze metodos da porta",
  );
});

for (const metodo of METODOS_DA_PORTA.filter((m) => !IMPLEMENTADOS.has(m))) {
  test(`ISO-01..08 (xfail strict): ${metodo} ainda nao isola nada`, async () => {
    const porta = adaptadorMedusa(deps());
    const resultado = (await chamar(porta, metodo, ctx())) as {
      tipo: string;
      erro?: string;
    };
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "NOT_IMPLEMENTED" },
      `${metodo} deixou de devolver NOT_IMPLEMENTED. ` +
        `O ticket dono e o ${DONO[metodo]}: substitui este caso pelo teste ` +
        "de isolamento a serio — ctx do tenant A sobre um id do tenant B tem " +
        "de dar TENANT_MISMATCH ou NOT_FOUND, nunca a linha de B. " +
        "E actualiza docs/com/port-coverage.md (KAM-042, criterio 6). " +
        "Acrescenta-o ao IMPLEMENTADOS deste ficheiro, senao este caso " +
        "desaparece sem ninguem notar.",
    );
  });
}

test("ISO-10: os tres casos, agora medidos pela porta (KAM-178)", async () => {
  // **Era um caso de `xfail strict` e passou a três asserções**, que é
  // exactamente o que o critério 6 do KAM-042 pede em troca: «substitui este
  // caso pelo teste de isolamento a sério». Os três estão medidos um a um em
  // `orders.listagem.test.ts`, com uma base de ensaio que explode se lhe
  // falarem; aqui mede-se que **a porta** os devolve, que é a outra metade.
  //
  // O `CLIENTE_PROIBIDO` continua a ser o cliente: nenhum dos três chega à base.
  const porta = adaptadorMedusa(deps());
  for (const filtro of [
    {},
    { estado: "criada", cursor: "ZmFsc2lmaWNhZG8=" },
    { contactId: "' OR 1=1 --" },
  ]) {
    const resultado = await porta.listOrders(ctx(), filtro as never);
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      JSON.stringify(filtro),
    );
  }
});

test("ISO-01..08: as quatro operacoes do KAM-178 passam o tenant do ctx", async () => {
  // **A asserção que importa não é o resultado: é o tenant que foi ao
  // predicado.** Com o `ctx` de A sobre ids de B, o único `tenant_id` que a base
  // vê é o de A — e por isso a resposta nunca pode ser a linha de B.
  const tenantsVistos: unknown[] = [];
  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql.includes("platform.tenants")) {
        return {
          rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }],
        };
      }
      tenantsVistos.push(parametros[0]);
      return { rows: [] };
    },
  };
  const porta = adaptadorMedusa(deps(cliente));

  // As quatro, com ids do tenant B e o `ctx` de A. Nenhuma devolve uma linha —
  // a base de A não tem nenhuma — e nenhuma pediu pelo tenant de B.
  assert.deepEqual(await porta.getOrder(ctx(TENANT_A), ORDER_DE_B), {
    tipo: "erro",
    erro: "NOT_FOUND",
  });
  const pagina = await porta.listOrders(ctx(TENANT_A), { contactId: CONTACTO_DE_B });
  assert.equal(pagina.tipo, "ok");
  if (pagina.tipo === "ok") assert.deepEqual([...pagina.valor.itens], []);
  assert.deepEqual(
    await porta.requestOwnerConfirmation(ctx(TENANT_A), ORDER_DE_B),
    { tipo: "erro", erro: "NOT_FOUND" },
  );
  const transitada = await porta.transition(
    ctx(TENANT_A),
    ORDER_DE_B,
    "cancelada",
    1,
    { causa: "dono_recusa" },
  );
  assert.deepEqual(transitada, { tipo: "erro", erro: "NOT_FOUND" });

  assert.deepEqual(
    [...new Set(tenantsVistos)],
    [TENANT_A],
    "uma consulta saiu com um tenant que nao e o do ctx",
  );
});

test("ISO-01..08: as quatro reservas do KAM-045 passam o tenant do ctx", async () => {
  // **Isto é o que substitui os quatro `xfail strict`**, e é o que o critério 6
  // do KAM-042 pede em troca deles: «ctx do tenant A sobre um id do tenant B
  // tem de dar `TENANT_MISMATCH` ou `NOT_FOUND`, nunca a linha de B».
  //
  // A asserção que importa é a última: o único `tenant_id` que chegou ao
  // predicado é o de A. As quatro respondem `NOT_FOUND` porque a encomenda de B
  // não existe na vista de A — e **nenhuma** devolve `ok`, que é a parte que o
  // `commitReservation` e o `releaseReservation` só garantem por lerem a
  // encomenda antes de mexer nas reservas (ver os comentários no adaptador).
  const tenantsVistos: unknown[] = [];
  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql.includes("platform.tenants")) {
        return {
          rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }],
        };
      }
      tenantsVistos.push(parametros[0]);
      return { rows: [] };
    },
  };
  const porta = adaptadorMedusa(deps(cliente));

  assert.deepEqual(
    await porta.reserveStock(ctx(TENANT_A), ORDER_DE_B, 48 * 60 * 60 * 1000),
    { tipo: "erro", erro: "NOT_FOUND" },
  );
  assert.deepEqual(
    await porta.extendReservation(
      ctx(TENANT_A),
      ORDER_DE_B,
      "2026-11-08T10:00:00.000Z",
    ),
    { tipo: "erro", erro: "NOT_FOUND" },
  );
  assert.deepEqual(
    await porta.commitReservation(ctx(TENANT_A), ORDER_DE_B),
    { tipo: "erro", erro: "NOT_FOUND" },
    "e **não** `ok`: «não havia nada a consumir» e «isso não é teu» são duas " +
      "coisas diferentes, e a segunda é NOT_FOUND",
  );
  assert.deepEqual(
    await porta.releaseReservation(ctx(TENANT_A), ORDER_DE_B, "cancelada"),
    { tipo: "erro", erro: "NOT_FOUND" },
  );

  assert.deepEqual(
    [...new Set(tenantsVistos)],
    [TENANT_A],
    "uma consulta das reservas saiu com um tenant que nao e o do ctx",
  );
});

/**
 * Um cliente que **devolve uma encomenda**, para as reservas chegarem ao SQL.
 *
 * **Achado da revisão adversarial:** o caso de cima devolve `{rows: []}` para
 * tudo, pelo que as quatro saem em `NOT_FOUND` no `lerEncomenda` e o SQL das
 * reservas **nunca é emitido** — a asserção do tenant observava uma consulta só,
 * a da encomenda. Com uma encomenda em mão, as quatro passam desse guarda e o
 * filtro de tenant das consultas das reservas fica medido.
 */
function clienteComEncomenda(estado: string) {
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql.includes("platform.tenants")) {
        return {
          rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }],
        };
      }
      vistas.push({ sql, valores: parametros });
      // A oferta responde ao predicado aritmético, senão o `reserveStock` sai
      // em `OUT_OF_STOCK`/`NOT_FOUND` e **nunca chega a inserir** a reserva —
      // e então o caso do prazo não media nada.
      if (sql.includes("UPDATE platform.offer_terms")) {
        return {
          rows: [
            {
              sku: "sku-de-b",
              stock_modo: "garantido",
              stock_quantidade: 10,
              stock_reservada: 1,
            },
          ],
        };
      }
      if (sql.includes("INSERT INTO platform.stock_reservations")) {
        return {
          rows: [
            {
              id: "0d0d0d0d-0d0d-4d0d-8d0d-0d0d0d0d0d0d",
              order_id: ORDER_DE_B,
              line_no: 0,
              sku: "sku-de-b",
              qty: 1,
              estado: "ativa",
              motivo: null,
              expira_at: "2026-11-07T10:00:00.000Z",
              confirmada_at: null,
              version: 1,
            },
          ],
        };
      }
      if (sql.includes("FROM platform.orders_mirror")) {
        return {
          rows: [
            {
              id: ORDER_DE_B,
              numero_publico: "ABCD1234",
              estado,
              version: 1,
              total_minor: "1000",
              currency: "AOA",
              contact_id: CONTACTO_DE_B,
              origem: "pme",
              entrega_modo: "levantamento",
              expira_at: null,
              paga_at: null,
              paga_via: null,
              entregue_at: null,
              entrega_confirmada_por: null,
              confirmacao_dono: "nao_aplicavel",
              lines_snapshot: [{ sku: "sku-de-b", qty: 1 }],
            },
          ],
        };
      }
      return { rows: [] };
    },
  };
  return { cliente, vistas };
}

test("ISO-01..08: as consultas das reservas levam o tenant do ctx, e correm", async () => {
  // O par do caso de cima, e o que lhe faltava: aqui as quatro **chegam** ao
  // SQL das reservas, pelo que o filtro de tenant delas é observado.
  const { cliente, vistas } = clienteComEncomenda("aguarda_pagamento");
  const porta = adaptadorMedusa(deps(cliente));

  await porta.reserveStock(ctx(TENANT_A), ORDER_DE_B, 48 * 60 * 60 * 1000);
  await porta.commitReservation(ctx(TENANT_A), ORDER_DE_B);
  await porta.releaseReservation(ctx(TENANT_A), ORDER_DE_B, "cancelada");
  await porta.extendReservation(
    ctx(TENANT_A),
    ORDER_DE_B,
    "2026-11-08T10:00:00.000Z",
  );

  const dasReservas = vistas.filter(
    (v) =>
      v.sql.includes("platform.stock_reservations") ||
      v.sql.includes("platform.offer_terms"),
  );
  assert.ok(
    dasReservas.length > 0,
    "as consultas das reservas têm de ter corrido: sem isto a asserção " +
      "seguinte não mede nada, que era o defeito do caso anterior",
  );
  assert.deepEqual(
    [...new Set(dasReservas.map((v) => v.valores[0]))],
    [TENANT_A],
    "uma consulta das reservas saiu com um tenant que nao e o do ctx",
  );
});

test("KAM-045 critério 2: a reserva pela porta usa o ttl, e não dois minutos", async () => {
  // **Achado 7 da revisão adversarial.** O módulo nasce provisório por omissão
  // (dois minutos, à espera do `charge.issued`), e com a omissão o `ttl` que
  // este método recebe era **silenciosamente descartado** — toda a reserva
  // feita pela porta durava dois minutos e a fórmula do critério 2 nunca corria
  // por aqui. Um argumento que a operação aceita e ignora é pior do que um que
  // ela não tem.
  const { cliente, vistas } = clienteComEncomenda("criada");
  const porta = adaptadorMedusa(deps(cliente));
  const antes = Date.now();
  await porta.reserveStock(ctx(TENANT_A), ORDER_DE_B, 48 * 60 * 60 * 1000);

  const insercao = vistas.find((v) =>
    v.sql.includes("platform.stock_reservations"),
  );
  assert.ok(insercao, "a reserva chegou a ser inserida");
  const prazo = insercao.valores
    .map((valor) => (typeof valor === "string" ? Date.parse(valor) : NaN))
    .find((instante) => !Number.isNaN(instante));
  assert.ok(prazo !== undefined, "a inserção leva um `expira_at`");
  // 48 h mais a folga de 15 min, não os 2 min da provisória. A margem é
  // generosa de propósito: o que se mede é a ordem de grandeza certa, não o
  // relógio.
  assert.ok(
    prazo - antes > 40 * 60 * 60 * 1000,
    `o prazo veio do ttl e não da janela provisória (deu ${prazo - antes} ms)`,
  );
});

test("KAM-045 critério 7: o extendReservation só passa em aguarda_pagamento", async () => {
  // **A primeira das três condições do critério 7**, que vive no adaptador
  // porque é ele que tem o estado da encomenda em mão. A revisão adversarial
  // mostrou que não havia ensaio nenhum: apagar o bloco do adaptador deixava
  // tudo verde, e a tabela de verificação citava um caso que sai em
  // `NOT_FOUND` antes de ler o estado.
  for (const estado of ["criada", "paga", "expirada", "cancelada"]) {
    const { cliente } = clienteComEncomenda(estado);
    const porta = adaptadorMedusa(deps(cliente));
    assert.deepEqual(
      await porta.extendReservation(
        ctx(TENANT_A),
        ORDER_DE_B,
        "2026-11-08T10:00:00.000Z",
      ),
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      `uma encomenda em ${estado} não prolonga reserva nenhuma`,
    );
  }
});

test("criterio 3: as oito ligadas continuam a falhar fechado sem ctx", async () => {
  // O ISO-09 já as cobre no caso de cima, e este mede o que a ligação podia ter
  // partido: com o corpo do método a abrir transacção, o `exigirCtx` tem de
  // continuar a correr **antes** dela. O `CLIENTE_PROIBIDO` prova-o.
  //
  // **Oito e não quatro desde o KAM-045**: as quatro das reservas abrem
  // transacção como as outras, pelo que correm o mesmo risco e pagam o mesmo
  // ensaio.
  const porta = adaptadorMedusa(deps());
  const semTenant = { ...ctx(), tenantId: "" };
  for (const metodo of [
    "requestOwnerConfirmation",
    "transition",
    "getOrder",
    "listOrders",
    "reserveStock",
    "extendReservation",
    "commitReservation",
    "releaseReservation",
  ]) {
    await assert.rejects(
      () => chamar(porta, metodo, semTenant),
      CtxEmFaltaError,
      metodo,
    );
  }
});

// ------------------------- ISO-01..08 e ISO-33..38 para os três do KAM-043

/**
 * O isolamento dos três métodos que o KAM-043 implementou.
 *
 * **Isto é o que substitui as três asserções de `xfail strict`**, e o que o
 * critério 6 do KAM-042 pede em troca delas: «ctx do tenant A sobre um id do
 * tenant B tem de dar `TENANT_MISMATCH` ou `NOT_FOUND`, nunca a linha de B».
 *
 * ## O que esta base de ensaio simula, e o que não pode simular
 *
 * A barreira que estes casos medem é a **primeira** — a porta e o repo-base, que
 * injectam o `tenant_id` do `ctx` no predicado. Mede-se aqui porque é código, e
 * mede-se com uma base de ensaio que responde pelo `tenant_id` que **recebeu
 * como argumento**: é a forma de afirmar que o adaptador passou o do `ctx` e não
 * outro. Uma base que ignorasse o argumento deixava estes casos verdes sobre uma
 * porta que não filtrava nada.
 *
 * A **segunda** barreira — a RLS `FORCE` da revisão `0028` — não se mede aqui e
 * não é omissão: uma política de PostgreSQL não existe em JavaScript. Mede-se em
 * `db/tests_produtos/test_isolamento.py`, com `kamba_app` (`NOBYPASSRLS`) contra
 * um PostgreSQL real, que é onde ela pode falhar. É a mesma separação que o
 * `spikes/medusa-d3/iso.py` escreve por extenso: «se este bloco fosse pela
 * porta, media a porta duas vezes e a RLS nenhuma».
 *
 * A **colisão de SKU entre tenants** (ISO-33..38) tem as duas metades: aqui
 * prova-se que o mesmo texto de `sku` com dois `ctx` diferentes não devolve a
 * linha do outro; na base prova-se que a chave `(tenant_id, sku)` deixa as duas
 * linhas existirem ao mesmo tempo.
 */

/** O SKU que **existe nos dois tenants**, com conteúdo diferente. É o ISO-33..38. */
const SKU_PARTILHADO = "arroz-5kg";

interface LinhaDeOferta {
  readonly tenant: string;
  readonly nome: string;
}

/** As ofertas de ensaio: o mesmo `sku`, duas linhas, dois tenants. */
const OFERTAS: readonly LinhaDeOferta[] = [
  { tenant: TENANT_A, nome: "arroz de A" },
  { tenant: TENANT_B, nome: "arroz de B" },
];

/** Um tenant que **não tem** este SKU. Serve o caso «existe em B e não em A». */
const TENANT_SEM_NADA = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

/**
 * Uma base que **filtra pelo argumento**, e guarda os tenants que lhe pediram.
 *
 * O repo-base passa sempre o `tenant_id` como `$1` — é ele que o põe lá, e
 * recusa a consulta que não o nomeie. Esta base devolve a linha cujo tenant é
 * igual a esse argumento, pelo que uma resposta com a linha de B só é possível
 * se o adaptador tiver passado o tenant de B.
 */
function baseDeEnsaio(): {
  cliente: ClienteSql;
  tenantsVistos: unknown[];
} {
  const tenantsVistos: unknown[] = [];
  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql.includes("platform.tenants")) {
        // Os dois tenants estão provisionados: sem isto o `comRegisto` falhava
        // com `MerchantEmFaltaError` e estes casos ficavam verdes **sem
        // chegarem à consulta** — a falha certa pela razão errada.
        return {
          rows: [
            { medusa_merchant_id: "merch", medusa_sales_channel_id: null },
          ],
        };
      }
      if (sql.includes("platform.offer_terms")) {
        const tenant = parametros[0];
        tenantsVistos.push(tenant);
        const linha = OFERTAS.find((o) => o.tenant === tenant);
        if (linha === undefined) return { rows: [] };
        return {
          rows: [
            {
              sku: SKU_PARTILHADO,
              nome: linha.nome,
              preco_tipo: "fixo",
              preco_minor: "1250000",
              currency: "AOA",
              preco_atualizado_at: "2026-11-01T00:00:00.000Z",
              preco_valido_ate: null,
              stock_modo: "garantido",
              stock_verificado_at: "2026-11-01T00:00:00.000Z",
              estado: "publicado",
              categoria_restrita: null,
              atualizado_at: "2026-11-01T00:00:00.000Z",
            },
          ],
        };
      }
      return { rows: [] };
    },
  };
  return { cliente, tenantsVistos };
}

test("ISO-01..08: getOfferView com ctx de A devolve a oferta de A, nunca a de B", async () => {
  const { cliente, tenantsVistos } = baseDeEnsaio();
  const porta = adaptadorMedusa(deps(cliente));

  const deA = await porta.getOfferView(ctx(TENANT_A), SKU_PARTILHADO);
  assert.equal(deA.tipo, "ok");
  // **A asserção que importa não é o `ok`: é o tenant que foi ao predicado.**
  // Com o `ctx` de A, o único `tenant_id` que a base viu é o de A.
  assert.deepEqual([...new Set(tenantsVistos)], [TENANT_A]);

  const deB = await porta.getOfferView(ctx(TENANT_B), SKU_PARTILHADO);
  assert.equal(deB.tipo, "ok");
  assert.deepEqual([...new Set(tenantsVistos)], [TENANT_A, TENANT_B]);

  // E as duas respostas são da oferta de cada um, com o **mesmo** `sku`: é a
  // colisão de SKU entre tenants (ISO-33..38) a não ser um problema.
  if (deA.tipo === "ok" && deB.tipo === "ok") {
    assert.equal(deA.valor.sku, SKU_PARTILHADO);
    assert.equal(deB.valor.sku, SKU_PARTILHADO);
  }
});

test("ISO-01..08: getOfferView de um tenant sem a oferta da NOT_FOUND", async () => {
  const { cliente } = baseDeEnsaio();
  const porta = adaptadorMedusa(deps(cliente));
  const resultado = await porta.getOfferView(
    ctx(TENANT_SEM_NADA),
    SKU_PARTILHADO,
  );
  // **`NOT_FOUND` e nao uma vista vazia.** Uma `OfferView` com campos vazios era
  // lida pelo agente como «um produto sem preco», que e precisamente o que o
  // preco opaco nao quer dizer.
  assert.deepEqual(resultado, { tipo: "erro", erro: "NOT_FOUND" });
});

test("ISO-01..08: publishProduct com ctx de outro tenant nao publica a linha alheia", async () => {
  const { cliente, tenantsVistos } = baseDeEnsaio();
  const porta = adaptadorMedusa(deps(cliente));
  const confirmacao = {
    actor: { kind: "dono", id: "msg-do-dono" },
    em: "2026-11-01T10:00:00Z",
  } as const;

  // O tenant C não tem a oferta; com o `ctx` dele, a publicação não encontra
  // nada — e nunca vê a linha de A nem a de B.
  const resultado = await porta.publishProduct(
    ctx(TENANT_SEM_NADA),
    { sku: SKU_PARTILHADO, registoId: null },
    confirmacao,
  );
  assert.deepEqual(resultado, { tipo: "erro", erro: "NOT_FOUND" });
  assert.deepEqual([...new Set(tenantsVistos)], [TENANT_SEM_NADA]);
});

test("criterio 4: publishProduct sem OwnerConfirmation valida falha, e nao toca na base", async () => {
  // O `CLIENTE_PROIBIDO` explode se lhe falarem: a recusa tem de acontecer
  // **antes** de haver consulta. Três formas de inválida, e a terceira é a que
  // importa — um `agente` a dar a confirmação que existe para o travar.
  const porta = adaptadorMedusa(deps());
  const ref = { sku: SKU_PARTILHADO, registoId: null };
  const invalidas = [
    { actor: { kind: "dono", id: "" }, em: "2026-11-01T10:00:00Z" },
    { actor: { kind: "dono", id: "m1" }, em: "nao-e-uma-hora" },
    { actor: { kind: "agente", id: "grafo" }, em: "2026-11-01T10:00:00Z" },
  ] as const;

  for (const confirmacao of invalidas) {
    const resultado = await porta.publishProduct(
      ctx(),
      ref,
      confirmacao as never,
    );
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      JSON.stringify(confirmacao),
    );
  }
});

test("criterio 4: upsertProductDraft sem preco_tipo nos atributos falha fechado", async () => {
  // E falha **sem tocar na base**: o `CLIENTE_PROIBIDO` explodiria. Assumir
  // `sob_consulta` punha «preco sob consulta» num produto que o dono queria
  // publicar com preco, e o dono so descobria quando um cliente perguntasse.
  const porta = adaptadorMedusa(deps());
  const resultado = await porta.upsertProductDraft(ctx(), {
    sku: "sku-novo",
    nome: "um produto",
  });
  assert.deepEqual(resultado, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("criterio 1 (KAM-042): com os tres implementados, um tenant inexistente falha fechado pela porta", async () => {
  // **A metade do critério 1 do KAM-042 que estava por fechar.** O bloco dele
  // diz: «"tenant inexistente falha fechada" mede-se contra a base, vive no
  // `comRegisto` (`TenantDesconhecidoError`) e **nenhum dos doze métodos chama o
  // `comRegisto`** — com um tenant bem formado e inexistente, a resposta de
  // qualquer um deles é `NOT_IMPLEMENTED`». Os três do KAM-043 passam a chamá-lo,
  // e por isso a segunda metade passa a ser observável **pela porta**.
  //
  // A caixa continua a ser do KAM-042 e **não se marca aqui**. O que este caso
  // entrega é a evidência de que ela é fechável, e com que teste.
  const cliente: ClienteSql = {
    async query() {
      return { rows: [] };
    },
  };
  const porta = adaptadorMedusa(deps(cliente));
  const bemFormadoEInexistente = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

  for (const chamada of [
    () => porta.getOfferView(ctx(bemFormadoEInexistente), SKU_PARTILHADO),
    () =>
      porta.publishProduct(
        ctx(bemFormadoEInexistente),
        { sku: SKU_PARTILHADO, registoId: null },
        { actor: { kind: "dono", id: "m1" }, em: "2026-11-01T10:00:00Z" },
      ),
    () =>
      porta.upsertProductDraft(ctx(bemFormadoEInexistente), {
        sku: "s",
        nome: "n",
        atributos: { preco_tipo: "sob_consulta" },
      }),
  ]) {
    await assert.rejects(chamada, TenantDesconhecidoError);
  }
});
