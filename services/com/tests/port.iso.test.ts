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
]);

/**
 * O ticket dono de cada método **ainda não implementado**. A mesma tabela que
 * `port-coverage.md`, e a duplicação é deliberada: um documento não falha um
 * *build*, e o critério 6 pede que a cobertura da porta seja verificável e não
 * lida.
 */
const DONO: Readonly<Record<string, string>> = {
  createOrder: "KAM-044",
  requestOwnerConfirmation: "KAM-044",
  reserveStock: "KAM-045",
  extendReservation: "KAM-045",
  commitReservation: "KAM-045",
  releaseReservation: "KAM-045",
  transition: "KAM-044",
  getOrder: "KAM-044",
  listOrders: "KAM-044",
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

function deps(cliente: ClienteSql = CLIENTE_PROIBIDO): Dependencias {
  return {
    comTenant: async (_tenantId, trabalho) => trabalho(cliente),
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
  // «strict» quer dizer. Os doze da porta sao exactamente os tres
  // implementados mais os nove com ticket dono, sem sobreposicao.
  assert.equal(IMPLEMENTADOS.size, 3, "o KAM-043 implementou tres");
  assert.equal(Object.keys(DONO).length, 9, "nove continuam por implementar");
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

test("ISO-10 (xfail strict): filtros vazios, cursor forjado e OR", async () => {
  // Os três casos do ISO-10 contra o único método que recebe filtros. Enquanto
  // o `listOrders` não estiver implementado, os três devolvem o mesmo
  // `NOT_IMPLEMENTED`; quando estiver, cada um destes tem de passar a uma
  // asserção própria — filtro vazio não lista tudo, cursor forjado é
  // `VALIDATION_ERROR`, e um `OR` no filtro não alarga o conjunto.
  const porta = adaptadorMedusa(deps());
  for (const filtro of [
    {},
    { cursor: "ZmFsc2lmaWNhZG8=" },
    { contactId: "' OR 1=1 --" },
  ]) {
    const resultado = await porta.listOrders(ctx(), filtro as never);
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "NOT_IMPLEMENTED" },
      "o listOrders foi implementado: parte este caso nos tres do ISO-10 " +
        "(KAM-044, KAM-042 criterio 2)",
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
