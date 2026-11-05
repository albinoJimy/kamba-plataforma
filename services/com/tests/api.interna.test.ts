/**
 * A API interna do COM: credencial, `ctx` e *fail-closed* (KAM-178, critério 2).
 *
 * ## O que esta suite prova
 *
 * As três portas do *fail-closed*, uma asserção por cada, e todas **sem** chegar
 * a operação nenhuma — as operações de ensaio contam quantas vezes foram
 * chamadas, e o que os casos de recusa afirmam é **zero**:
 *
 * ```text
 * credencial ausente, errada, ou de outro servico   401, sem ler o corpo
 * x-kamba-tenant ausente, nao-UUID, ou ctx a meio   400, sem chamar a porta
 * corpo que nao valida                              400
 * ```
 *
 * E prova a tradução que o §3.39 fixa: o `NOT_IMPLEMENTED` «pára na API interna
 * do COM, que o traduz para **501**», e o conflito de CAS sai como **409** com o
 * `tipo: "conflito"` — e não como um dos dez `ERROS`, que é o segundo movimento
 * da decisão de 2026-11-04.
 *
 * ## A credencial de «outro serviço» é um caso e não uma variante
 *
 * O critério pede «credencial ausente, errada e **de outro serviço**», e os três
 * são a mesma resposta por desenho: o `agr_internal_token` é um valor válido
 * noutro serviço e **não** aqui, e é exactamente por isso que o inventário tem
 * duas entradas. Se o COM aceitasse o do AGR, quem tivesse a credencial do
 * runtime criava encomendas.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { createApp } from "../src/app.ts";
import { FiltroEmFaltaError, repoBase } from "../src/repo-base/index.ts";
import {
  CABECALHO_INTERNO,
  CABECALHO_TENANT,
  CORPO_MAXIMO,
  ESTADO_POR_ERRO,
  ROTAS,
  type DependenciasDaApi,
} from "../src/api/interna.ts";
import { TIPO_DE_CONTEUDO } from "../src/metricas.ts";
import type { OperacoesDoCom } from "../src/adapters/medusa/index.ts";
import {
  conflito,
  erro,
  naoImplementado,
  ok,
  type CommerceRegistry,
  type Ctx,
} from "../src/port/index.ts";

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const CONTACTO = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";
const ORDER = "0000000a-0000-4000-8000-000000000000";

const CREDENCIAL = "a-credencial-do-com";
/** A do AGR. **Válida noutro serviço e inválida aqui** — ver a nota do módulo. */
const CREDENCIAL_DO_AGR = "a-credencial-do-agr";

/** Quantas vezes cada operação foi chamada. Os casos de recusa afirmam zero. */
interface Chamadas {
  readonly contagem: Map<string, number>;
}

function operacoesDeEnsaio(): { operacoes: OperacoesDoCom; chamadas: Chamadas } {
  const contagem = new Map<string, number>();
  const contar = (nome: string) => {
    contagem.set(nome, (contagem.get(nome) ?? 0) + 1);
  };
  const porta = {
    async getOfferView(_ctx: Ctx, sku: string) {
      contar("getOfferView");
      return ok({
        sku,
        precoTipo: "fixo" as const,
        precoDisplay: "12 500 Kz",
        stockModo: "garantido" as const,
        disponibilidade: "disponivel",
        atualizadoAt: "2026-11-04T10:00:00.000Z",
      });
    },
    async getOrder(_ctx: Ctx, orderId: string) {
      contar("getOrder");
      return ok({
        orderId,
        numeroPublico: "K7H3Q1",
        estado: "criada" as const,
        version: 1,
        contactId: CONTACTO,
        // **`bigint`**: a resposta sai com o total como cadeia de dígitos, e é
        // isso que este caso mede mais abaixo.
        totalMinor: 9_007_199_254_740_993n,
        currency: "AOA",
        linhas: [],
        criadoAt: "2026-11-04T10:00:00.000Z",
      });
    },
    async listOrders() {
      contar("listOrders");
      return ok({ itens: [], proximo: null });
    },
    async transition(_ctx: Ctx, orderId: string) {
      contar("transition");
      // O terceiro caso do `Resultado`: «relê e reavalia».
      return conflito({
        orderId,
        numeroPublico: "K7H3Q1",
        estado: "paga" as const,
        version: 7,
      });
    },
    async requestOwnerConfirmation() {
      contar("requestOwnerConfirmation");
      return ok(undefined);
    },
    async createOrder() {
      contar("createOrder");
      return naoImplementado();
    },
    async upsertProductDraft() {
      contar("upsertProductDraft");
      return erro("NOT_FOUND");
    },
    async publishProduct() {
      contar("publishProduct");
      return ok(undefined);
    },
    async reserveStock() {
      return naoImplementado();
    },
    async extendReservation() {
      return naoImplementado();
    },
    async commitReservation() {
      return naoImplementado();
    },
    async releaseReservation() {
      return naoImplementado();
    },
  } as unknown as CommerceRegistry;

  const operacoes: OperacoesDoCom = {
    porta,
    async proposeCart() {
      contar("proposeCart");
      return ok({
        cartId: "C7H3Q9ABCDEFGHJKMNPQRSTVWX",
        totalMinor: 2_500_000n,
        currency: "AOA",
        linhas: [],
        exigeConfirmacaoDoDono: false,
        draftHash: Buffer.alloc(32, 1),
      });
    },
    async createOrder() {
      contar("createOrderDaSaga");
      return {
        tipo: "ok" as const,
        valor: {
          orderId: ORDER,
          numeroPublico: "K7H3Q1",
          estado: "criada" as const,
          version: 1,
          totalMinor: 2_500_000n,
          currency: "AOA",
          confirmacaoDono: "nao_aplicavel" as const,
          linhas: [],
          repeticao: false,
          pedidoPorPagar: null,
        },
      };
    },
  };
  return { operacoes, chamadas: { contagem } };
}

function app(deps?: Partial<DependenciasDaApi>) {
  const { operacoes, chamadas } = operacoesDeEnsaio();
  const aplicacao = createApp(undefined, {
    operacoes,
    credencial: CREDENCIAL,
    ...deps,
  });
  return { aplicacao, chamadas };
}

/** Um `POST` com os dois cabeçalhos, salvo o que o caso quiser omitir. */
function pedido(
  rota: string,
  corpo: unknown,
  cabecalhos: Record<string, string>,
): Request {
  return new Request(`http://127.0.0.1${rota}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...cabecalhos },
    body: JSON.stringify(corpo),
  });
}

const CTX_DO_CORPO = {
  actor: { kind: "agente", id: "grafo-vendedor" },
  trace_id: "trace-1",
};

const BONS = {
  [CABECALHO_INTERNO]: CREDENCIAL,
  [CABECALHO_TENANT]: TENANT,
};

// ------------------------------------------------------------------- a credencial

test("criterio 2: as sete rotas sem credencial dao 401, e nenhuma operacao corre", async () => {
  const { aplicacao, chamadas } = app();
  for (const rota of ROTAS) {
    const r = await aplicacao.fetch(
      pedido(rota, CTX_DO_CORPO, { [CABECALHO_TENANT]: TENANT }),
    );
    assert.equal(r.status, 401, rota);
    assert.deepEqual(await r.json(), { error: "unauthorized" });
  }
  assert.equal(chamadas.contagem.size, 0, "uma operacao correu sem credencial");
});

test("criterio 2: credencial errada, vazia e de outro servico dao 401", async () => {
  const { aplicacao, chamadas } = app();
  const maus = ["", "errada", CREDENCIAL_DO_AGR, `${CREDENCIAL}x`, CREDENCIAL.slice(0, -1)];
  for (const credencial of maus) {
    const r = await aplicacao.fetch(
      pedido("/internal/get-order", { ...CTX_DO_CORPO, order_id: ORDER }, {
        ...BONS,
        [CABECALHO_INTERNO]: credencial,
      }),
    );
    assert.equal(r.status, 401, JSON.stringify(credencial));
  }
  assert.equal(chamadas.contagem.size, 0);
});

// --------------------------------------------------------------- o `ctx`

test("criterio 2: sem x-kamba-tenant utilizavel e 400 fail-closed, e a porta nao e chamada", async () => {
  const { aplicacao, chamadas } = app();
  const maus: (string | undefined)[] = [
    undefined,
    "",
    "   ",
    "nao-e-uuid",
    "' OR 1=1 --",
    // Um UUID sem a forma canónica: o `eUuid` da porta recusa-o, e recusá-lo
    // aqui é a primeira das duas barreiras do mesmo facto.
    "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa",
  ];
  for (const tenant of maus) {
    const cabecalhos: Record<string, string> = {
      [CABECALHO_INTERNO]: CREDENCIAL,
    };
    if (tenant !== undefined) cabecalhos[CABECALHO_TENANT] = tenant;
    const r = await aplicacao.fetch(
      pedido("/internal/get-order", { ...CTX_DO_CORPO, order_id: ORDER }, cabecalhos),
    );
    assert.equal(r.status, 400, JSON.stringify(tenant));
    assert.deepEqual(await r.json(), { error: "ctx" });
  }
  assert.equal(chamadas.contagem.size, 0, "a porta foi chamada sem ctx");
});

test("criterio 2: um ctx a meio no corpo e 400, e nao se completa por omissao", async () => {
  // **Um `actor` em falta é 400 e não `{kind: \"sistema\"}`**: completar o `ctx`
  // dava ao pedido de uma conversa o actor que o §6.2 reserva ao PAY.
  const { aplicacao, chamadas } = app();
  const corpos = [
    { order_id: ORDER },
    { order_id: ORDER, trace_id: "t" },
    { order_id: ORDER, actor: { kind: "agente", id: "g" } },
    { order_id: ORDER, actor: { kind: "root", id: "g" }, trace_id: "t" },
    { order_id: ORDER, actor: { kind: "agente", id: "" }, trace_id: "t" },
    { order_id: ORDER, actor: "agente", trace_id: "t" },
  ];
  for (const corpo of corpos) {
    const r = await aplicacao.fetch(pedido("/internal/get-order", corpo, BONS));
    assert.equal(r.status, 400, JSON.stringify(corpo));
    assert.deepEqual(await r.json(), { error: "ctx" });
  }
  assert.equal(chamadas.contagem.size, 0);
});

test("um corpo que nao e JSON, ou nao e objecto, e 400", async () => {
  const { aplicacao, chamadas } = app();
  for (const bruto of ["nao-e-json", "[1,2,3]", '"uma cadeia"', "null"]) {
    const r = await aplicacao.fetch(
      new Request("http://127.0.0.1/internal/get-order", {
        method: "POST",
        headers: { ...BONS, "content-type": "application/json" },
        body: bruto,
      }),
    );
    assert.equal(r.status, 400, bruto);
  }
  assert.equal(chamadas.contagem.size, 0);
});

test("um corpo acima do tecto e 413, e nao chega ao JSON.parse", async () => {
  const { aplicacao, chamadas } = app();
  const r = await aplicacao.fetch(
    new Request("http://127.0.0.1/internal/get-order", {
      method: "POST",
      headers: { ...BONS, "content-type": "application/json" },
      body: `{"x":"${"a".repeat(9 * 1024)}"}`,
    }),
  );
  assert.equal(r.status, 413);
  assert.equal(chamadas.contagem.size, 0);
});

// ------------------------------------------------------- os codigos e os estados

test("o NOT_IMPLEMENTED da 501 e o codigo vai no corpo (§3.39)", async () => {
  // **Medido na rota e não no mapa**, que é a diferença entre um caso e uma
  // tautologia: a primeira versão deste caso afirmava
  // `ESTADO_POR_ERRO.NOT_IMPLEMENTED === 501` e mais nada — comparava a tabela
  // consigo mesma e não media tradução nenhuma.
  //
  // O método de ensaio devolve `naoImplementado()`, que é o que os quatro do
  // KAM-045 devolvem hoje, e a asserção é a resposta HTTP: **501**, com o nome
  // do código no corpo. O §3.39 di-lo por extenso: aquele código «pára na API
  // interna do COM, que o traduz para 501».
  const { operacoes } = operacoesDeEnsaio();
  const porta = operacoes.porta as unknown as Record<string, unknown>;
  porta["getOfferView"] = async () => naoImplementado();
  const aplicacao = createApp(undefined, { operacoes, credencial: CREDENCIAL });

  const r = await aplicacao.fetch(
    pedido("/internal/offer-view", { ...CTX_DO_CORPO, sku: "arroz-5kg" }, BONS),
  );
  assert.equal(r.status, 501);
  assert.deepEqual(await r.json(), {
    tipo: "erro",
    erro: "NOT_IMPLEMENTED",
  });
  assert.equal(ESTADO_POR_ERRO.NOT_IMPLEMENTED, 501);
});

test("cada um dos dez codigos sai com o estado da tabela, e o nome no corpo", async () => {
  // **A tabela inteira exercitada pela rota**, e não só a entrada do
  // `NOT_IMPLEMENTED`: o consumidor é o executor da ToolLayer, que precisa do
  // nome para o `ToolResult` (§6.5 trata os três 409 de maneiras diferentes), e
  // o estado é para quem opera. Um código sem entrada na tabela daria
  // `undefined` no estado, que o `Response` recusa — pelo que este caso também
  // afirma que a tabela cobre os dez.
  for (const [codigo, estado] of Object.entries(ESTADO_POR_ERRO)) {
    const { operacoes } = operacoesDeEnsaio();
    const porta = operacoes.porta as unknown as Record<string, unknown>;
    porta["getOrder"] = async () => ({ tipo: "erro" as const, erro: codigo });
    const aplicacao = createApp(undefined, { operacoes, credencial: CREDENCIAL });
    const r = await aplicacao.fetch(
      pedido("/internal/get-order", { ...CTX_DO_CORPO, order_id: ORDER }, BONS),
    );
    assert.equal(r.status, estado, codigo);
    assert.deepEqual(await r.json(), { tipo: "erro", erro: codigo }, codigo);
  }
});

test("o conflito de CAS sai como 409 com tipo conflito, e nao como um erro", async () => {
  // **O segundo movimento da decisão de 2026-11-04, visto de fora.** Antes
  // dela, o `transition` traduzia o conflito para `VALIDATION_ERROR` — isto é,
  // dizia a quem perdeu a corrida que o pedido dele não serve.
  const { aplicacao } = app();
  const r = await aplicacao.fetch(
    pedido(
      "/internal/transition",
      {
        ...CTX_DO_CORPO,
        order_id: ORDER,
        para: "paga",
        expected_version: 3,
        causa: "payment.confirmed",
        evento_id: "e1",
      },
      BONS,
    ),
  );
  assert.equal(r.status, 409);
  const corpo = (await r.json()) as { tipo: string; valor: { version: number } };
  assert.equal(corpo.tipo, "conflito");
  // E **traz a releitura**, que é o que permite reavaliar sem segunda viagem.
  assert.equal(corpo.valor.version, 7);
});

test("um bigint sai como cadeia de digitos, e nao como number", async () => {
  // Acima de 2^53 cêntimos o `JSON.parse` de quem lê arredondava em silêncio, e
  // é a fronteira por onde o `bigint` do PAY entra na porta.
  const { aplicacao } = app();
  const r = await aplicacao.fetch(
    pedido("/internal/get-order", { ...CTX_DO_CORPO, order_id: ORDER }, BONS),
  );
  assert.equal(r.status, 200);
  const texto = await r.text();
  assert.ok(
    texto.includes('"totalMinor":"9007199254740993"'),
    `o total nao saiu como cadeia: ${texto}`,
  );
});

test("o propose-cart recusa um rascunho sem identidade, sem chamar o modulo", async () => {
  const { aplicacao, chamadas } = app();
  const incompletos = [
    { contact_id: CONTACTO },
    { contact_id: CONTACTO, draft_id: "d1" },
    { contact_id: CONTACTO, draft_id: "d1", draft_version: 0, entrega_modo: "levantamento", linhas: [{ sku: "s", qty: 1 }] },
    { contact_id: CONTACTO, draft_id: "d1", draft_version: 1, entrega_modo: "aviao", linhas: [{ sku: "s", qty: 1 }] },
    { contact_id: CONTACTO, draft_id: "d1", draft_version: 1, entrega_modo: "levantamento", linhas: [] },
    { contact_id: CONTACTO, draft_id: "d1", draft_version: 1, entrega_modo: "levantamento", linhas: [{ sku: "s", qty: 0 }] },
    { contact_id: "nao-e-uuid", draft_id: "d1", draft_version: 1, entrega_modo: "levantamento", linhas: [{ sku: "s", qty: 1 }] },
  ];
  for (const corpo of incompletos) {
    const r = await aplicacao.fetch(
      pedido("/internal/propose-cart", { ...CTX_DO_CORPO, ...corpo }, BONS),
    );
    assert.equal(r.status, 400, JSON.stringify(corpo));
    assert.deepEqual(await r.json(), {
      tipo: "erro",
      erro: "VALIDATION_ERROR",
    });
  }
  assert.equal(chamadas.contagem.get("proposeCart"), undefined);
});

test("o propose-cart nao devolve o draft_hash", async () => {
  // Um *hash* de rascunho na resposta de uma tool `read` era um valor que o
  // modelo podia citar sem o entender, e é estado interno da *saga*.
  const { aplicacao } = app();
  const r = await aplicacao.fetch(
    pedido(
      "/internal/propose-cart",
      {
        ...CTX_DO_CORPO,
        contact_id: CONTACTO,
        draft_id: "d1",
        draft_version: 1,
        entrega_modo: "levantamento",
        linhas: [{ sku: "arroz-5kg", qty: 2 }],
      },
      BONS,
    ),
  );
  assert.equal(r.status, 200);
  const texto = await r.text();
  assert.ok(!texto.includes("draftHash"), texto);
  assert.ok(!texto.includes("draft_hash"), texto);
  assert.ok(texto.includes('"total_minor":"2500000"'), texto);
});

// ------------------------------------------------------------------ as outras rotas

test("o create-order sem cart_id e 400, e a saga nao corre", async () => {
  // **O `cart_id` é obrigatório nesta rota desde a revisão adversarial.** O
  // `cartIdValido` do `create_order.ts` — a comparação em tempo constante que
  // liga o botão `confirm:{cart_id}` ao rascunho — só corre se o pedido o
  // trouxer: omiti-lo saltava a barreira **sem recusa**, e a superfície nova
  // deixava optar por não a ter. O caso anterior mandava exactamente esse corpo
  // e afirmava **200** — codificava o contorno como aceitável.
  const { aplicacao, chamadas } = app();
  const base = {
    ...CTX_DO_CORPO,
    contact_id: CONTACTO,
    draft_id: "d1",
    draft_version: 1,
    entrega_modo: "levantamento",
    linhas: [{ sku: "arroz-5kg", qty: 1 }],
    total_esperado_minor: "2500000",
  };
  for (const cartId of [undefined, "", 42, null]) {
    const corpo =
      cartId === undefined ? base : { ...base, cart_id: cartId as never };
    const r = await aplicacao.fetch(pedido("/internal/create-order", corpo, BONS));
    assert.equal(r.status, 400, JSON.stringify(cartId));
    assert.deepEqual(await r.json(), { tipo: "erro", erro: "VALIDATION_ERROR" });
  }
  assert.equal(chamadas.contagem.get("createOrderDaSaga"), undefined);

  // E o caminho legítimo, **sem o qual os quatro de cima não dizem nada**: com
  // `cart_id`, a saga corre.
  const r = await aplicacao.fetch(
    pedido(
      "/internal/create-order",
      { ...base, cart_id: "C7H3Q9ABCDEFGHJKMNPQRSTVWX" },
      BONS,
    ),
  );
  assert.equal(r.status, 200);
  assert.equal(chamadas.contagem.get("createOrderDaSaga"), 1);
});

test("um corpo com caracteres multi-octeto conta em octetos e nao em UTF-16", async () => {
  // O `CORPO_MAXIMO` diz «em octetos» e o `String.length` conta unidades
  // UTF-16: 8192 caracteres de três octetos são ~24 KiB a entrar no
  // `JSON.parse`, que é o que o tecto diz impedir. O caso que o media usava
  // ASCII, onde as duas contagens coincidem. Achado da revisão adversarial.
  const { aplicacao, chamadas } = app();
  const tresOctetos = "\u4e00".repeat(3 * 1024); // 3072 caracteres, 9216 octetos
  assert.ok(tresOctetos.length < CORPO_MAXIMO, "o caso deixou de medir o UTF-16");
  assert.ok(Buffer.byteLength(tresOctetos, "utf8") > CORPO_MAXIMO);
  const r = await aplicacao.fetch(
    new Request("http://127.0.0.1/internal/get-order", {
      method: "POST",
      headers: { ...BONS, "content-type": "application/json" },
      body: `{"x":"${tresOctetos}"}`,
    }),
  );
  assert.equal(r.status, 413);
  assert.equal(chamadas.contagem.size, 0);
});

test("um GET numa rota /internal/* nao e servido, e nao devolve 200", async () => {
  // As sete rotas são `POST`. Um `GET` que respondesse era uma superfície que
  // ninguém desenhou — e um `GET` é o que um *crawler* tenta primeiro.
  const { aplicacao } = app();
  for (const rota of ROTAS) {
    const r = await aplicacao.fetch(
      new Request(`http://127.0.0.1${rota}`, { method: "GET", headers: BONS }),
    );
    assert.notEqual(r.status, 200, rota);
  }
});

test("sem a API montada, o /internal/* responde 503 e nao 404", async () => {
  // Um 404 dizia «essa rota não existe» — e ela existe, só não está montada,
  // que é um defeito de arranque e não um pedido errado.
  const aplicacao = createApp();
  for (const rota of ROTAS) {
    const r = await aplicacao.fetch(pedido(rota, CTX_DO_CORPO, BONS));
    assert.equal(r.status, 503, rota);
  }
});

// ------------------------------------------------------------------- /metrics

test("criterio 8: o /metrics serve as duas metricas, sem credencial e em texto", async () => {
  // **Os contadores sobem primeiro, e isso é o que torna a asserção do `OBS-I`
  // falsificável.** A primeira versão deste caso corria sobre uma população
  // vazia: o `!corpo.includes(TENANT)` passava mesmo que a exposição ganhasse
  // uma etiqueta de tenant, porque não havia série nenhuma com valor. Achado da
  // revisão adversarial.
  //
  // Faz-se subir pelo caminho real — uma consulta sem filtro é recusada pelo
  // `repoBase` e incrementa o `com_repo_filtro_em_falta_total`, e uma com filtro
  // incrementa o `com_repo_consultas_total` —, e não chamando o contador à mão:
  // o que se quer medir é que o que o repo-base conta é o que a rota serve.
  const repo = repoBase(
    { async query() { return { rows: [] }; } },
    TENANT,
    "merch",
  );
  await assert.rejects(() => repo.noTenant("SELECT 1", []), FiltroEmFaltaError);
  await repo.noTenant("SELECT 1 WHERE tenant_id = $1", []);

  const { aplicacao } = app();
  const r = await aplicacao.fetch(
    new Request("http://127.0.0.1/metrics", { method: "GET" }),
  );
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("content-type"), TIPO_DE_CONTEUDO);
  const corpo = await r.text();
  for (const nome of [
    "com_repo_filtro_em_falta_total",
    "com_repo_consultas_total",
  ]) {
    assert.ok(corpo.includes(`# TYPE ${nome} counter`), nome);
    assert.ok(corpo.includes(`${nome}{filtro="tenant"}`), nome);
    assert.ok(corpo.includes(`${nome}{filtro="merchant"}`), nome);
  }
  // **As duas séries do `tenant` têm valor**, pelo que a asserção de baixo corre
  // sobre uma população que existe. Lê-se o número do corpo e não do contador,
  // que é o ponto: é a exposição que se mede.
  for (const nome of [
    "com_repo_filtro_em_falta_total",
    "com_repo_consultas_total",
  ]) {
    const achado = new RegExp(`${nome}\\{filtro="tenant"\\} (\\d+)`).exec(corpo);
    assert.ok(achado !== null, nome);
    assert.ok(Number(achado?.[1]) > 0, `${nome} ficou a zero: ${achado?.[1]}`);
  }
  // **Nenhum identificador em etiqueta** (`OBS-I`): a única etiqueta é o filtro.
  assert.ok(!corpo.includes(TENANT), "um tenant_id saiu numa etiqueta");
});

test("o /healthz continua sem credencial", async () => {
  const { aplicacao } = app();
  const r = await aplicacao.fetch(
    new Request("http://127.0.0.1/healthz", { method: "GET" }),
  );
  assert.equal(r.status, 200);
});
