/**
 * A API interna do COM — `POST /internal/...` (KAM-178, critérios 2, 3 e 4).
 *
 * A forma é a do `/internal/turn` e `/internal/resume` do AGR (KAM-025):
 * credencial no cabeçalho, comparação em **tempo constante**, autenticação
 * **antes** de se ler o corpo, e o segredo no inventário. «Mínima» é o
 * adjectivo, e cumpre-se: sete rotas, nenhuma de administração, nenhuma que
 * exista «para depois». A `/healthz` fica onde estava e **não** leva credencial
 * — é a sonda do *rolling deploy*, e uma sonda que precisa de segredo é uma
 * sonda que falha no dia em que o segredo roda.
 *
 * ## O `agr_internal_token` **não** se reaproveita
 *
 * Uma credencial por serviço, porque quem a tem alcança tudo o que o serviço
 * serve. O `com_internal_token` é entrada nova no `ops/secrets-inventory.yaml`,
 * com os três ambientes obrigatórios pela mesma razão que a do AGR: uma rota que
 * corre sem credencial em `dev` é uma rota que alguém esquece de proteger em
 * `prod`, e o que o impede é o `Secrets.arrancar`.
 *
 * ## Dois cabeçalhos, e não um
 *
 * ```text
 * x-kamba-interno   prova «vem de dentro da rede»        (§3.24)
 * x-kamba-tenant    prova «e este tenant»                (§3.39)
 * ```
 *
 * A distinção é a que o §3.32 escreveu para o `x-kamba-hnd-bot`, e os dois são
 * necessários: o primeiro sozinho dava a quem o tivesse o acesso a **todos** os
 * tenants. O `lint_arch medusa` tem uma sentinela que exige o `x-kamba-tenant`
 * em qualquer rota `/internal/*` do COM — **estava verde sobre zero rotas**, e
 * este ficheiro é o primeiro objecto dela.
 *
 * ## *Fail-closed* é o desenho, e tem três portas
 *
 * ```text
 * sem credencial, ou errada      401, sem ler o corpo
 * sem x-kamba-tenant utilizavel  400, e o `exigirCtx` da porta e que decide
 * corpo que nao valida           400
 * ```
 *
 * Nenhuma delas responde `200` com um corpo que pareça legítimo, que é a letra
 * do ISO-09: «um `ctx` sem tenant não é uma recusa de domínio que o grafo deva
 * mostrar a um cliente — é um erro de quem montou a chamada». Por isso o `ctx`
 * **não se completa com valores de omissão**: um `actor` em falta é 400 e não
 * `{kind: "sistema"}`.
 *
 * ## O código canónico vai no corpo, e o estado HTTP é para quem opera
 *
 * O consumidor é o executor da ToolLayer, que precisa do `error_code` do §3.27
 * para o `ToolResult` — e um estado HTTP não o carrega sem perda: `409` serviria
 * `PRICE_CHANGED`, `OUT_OF_STOCK` e `INTENT_REUSED_WITH_DIFFERENT_CONTENT`, e o
 * grafo trata os três de maneiras diferentes (§6.5). Por isso **o corpo leva
 * sempre o nome do código** e o estado vem de uma tabela fixa, para que um
 * painel e um proxy vejam a diferença entre uma recusa de negócio e um cofre em
 * baixo.
 *
 * O `NOT_IMPLEMENTED` traduz-se para **501**, que é o que o §3.39 manda: ele
 * «pára na API interna do COM», e nenhuma tool o devolve a um cliente.
 */

import { timingSafeEqual } from "node:crypto";
import { Hono } from "hono";
import type { Logger } from "@kamba/core-ts/logger";

import {
  CtxEmFaltaError,
  eUuid,
  type Ctx,
  type Erro,
  type OrderFilter,
  type OrderState,
} from "../port/index.ts";
import type { OperacoesDoCom } from "../adapters/medusa/index.ts";
import { exposicao, TIPO_DE_CONTEUDO } from "../metricas.ts";
import type {
  ErroDaCriacao,
  PedidoDeCriacao,
  RascunhoDoCarrinho,
} from "../orders/index.ts";

/** O cabeçalho que leva a credencial interna. Dicionário §3.24. */
export const CABECALHO_INTERNO = "x-kamba-interno";

/** O cabeçalho que diz de quem é o pedido. Dicionário §3.39. */
export const CABECALHO_TENANT = "x-kamba-tenant";

/** O `id` do segredo no inventário (`ops/secrets-inventory.yaml`). */
export const SEGREDO_DA_API = "com_internal_token";

/**
 * O tecto do corpo, em octetos.
 *
 * **Mede depois de ler, e isso é uma limitação e não um descuido** — a mesma
 * que o `api_interna.py` do AGR escreve: o corpo já chegou quando este tecto se
 * aplica, e o que ele impede é o `JSON.parse` de um corpo grande. Quem impede a
 * leitura é o proxy de entrada (**KAM-076**). Oito KiB é a forma do
 * `CORPO_MAXIMO` daquele ficheiro, e os pedidos daqui têm no máximo vinte linhas
 * de carrinho.
 */
export const CORPO_MAXIMO = 8 * 1024;

/** As sete rotas, pela ordem em que a cadeia grafo → TLS → COM as toca. */
export const ROTAS = [
  "/internal/offer-view",
  "/internal/propose-cart",
  "/internal/create-order",
  "/internal/get-order",
  "/internal/list-orders",
  "/internal/transition",
  "/internal/request-owner-confirmation",
] as const;

/**
 * O estado HTTP de cada código. **Para quem opera**, não para quem decide: o
 * código canónico vai sempre no corpo. Ver a nota do módulo.
 */
export const ESTADO_POR_ERRO: Readonly<Record<Erro | ErroDaCriacao, number>> = {
  NOT_IMPLEMENTED: 501,
  NOT_FOUND: 404,
  VALIDATION_ERROR: 400,
  TENANT_MISMATCH: 403,
  PRICE_CHANGED: 409,
  OUT_OF_STOCK: 409,
  INTENT_REUSED_WITH_DIFFERENT_CONTENT: 409,
  LIMIT_EXCEEDED: 429,
  UPSTREAM_TIMEOUT: 504,
  UPSTREAM_DOWN: 503,
};

/** O estado de um conflito de CAS. «Relê e reavalia» é exactamente um 409. */
export const ESTADO_DO_CONFLITO = 409;

/** O que a API interna precisa que lhe dêem. */
export interface DependenciasDaApi {
  readonly operacoes: OperacoesDoCom;
  /**
   * A credencial, já lida do cofre.
   *
   * **Um valor e não um anel**, pela razão que o inventário escreve para o
   * `agr_internal_token`: a comparação é em tempo constante contra **um** valor,
   * e um anel obrigava a comparar contra dois — o que duplica a superfície de um
   * segredo que roda sem corte de serviço, porque quem chama repete o pedido.
   */
  readonly credencial: string;
  readonly log?: Logger;
}

/** A credencial apresentada é a nossa? Em tempo constante. */
function credencialValida(apresentada: string | undefined, nossa: string): boolean {
  if (typeof apresentada !== "string" || apresentada.length === 0) return false;
  const a = Buffer.from(apresentada, "utf8");
  const b = Buffer.from(nossa, "utf8");
  // O `timingSafeEqual` **levanta** com comprimentos diferentes, e por isso o
  // comprimento compara-se primeiro. Isso vaza o comprimento do segredo e mais
  // nada — é a mesma propriedade do `hmac.compare_digest` do AGR, que também
  // sai cedo nesse caso.
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/** Os quatro `kind` do §3.39. A lista vive na porta; aqui só se confronta. */
const ACTORES = ["agente", "dono", "sistema", "ops"] as const;

/**
 * O `ctx` do pedido, ou `null`.
 *
 * O `tenantId` vem do **cabeçalho** e os outros dois do corpo, e não é
 * arbitrário: o tenant é o que o chamador autenticado afirma na fronteira do
 * pedido — é o que o `lint_arch` exige e o que um proxy pode registar sem abrir
 * o corpo —, e o `actor` e o `traceId` são do turno que o produziu. Nenhum vem
 * do texto do cliente, que é a regra do §6.1 e do ADR-015.
 *
 * Devolve `null` em vez de completar o que falta. Ver a nota do módulo.
 */
function ctxDoPedido(
  tenantHeader: string | undefined,
  corpo: Record<string, unknown>,
): Ctx | null {
  if (!eUuid(tenantHeader)) return null;
  const actor = corpo["actor"];
  if (typeof actor !== "object" || actor === null) return null;
  const kind = (actor as Record<string, unknown>)["kind"];
  const id = (actor as Record<string, unknown>)["id"];
  if (typeof kind !== "string" || !(ACTORES as readonly string[]).includes(kind)) {
    return null;
  }
  if (typeof id !== "string" || id.length === 0) return null;
  const traceId = corpo["trace_id"];
  if (typeof traceId !== "string" || traceId.length === 0) return null;
  return {
    tenantId: tenantHeader.toLowerCase(),
    actor: { kind: kind as Ctx["actor"]["kind"], id },
    traceId,
  };
}

/** O rascunho do carrinho que o corpo descreve, ou `null`. */
function rascunhoDoCorpo(
  corpo: Record<string, unknown>,
): RascunhoDoCarrinho | null {
  const contactId = corpo["contact_id"];
  const draftId = corpo["draft_id"];
  const draftVersion = corpo["draft_version"];
  const entregaModo = corpo["entrega_modo"];
  const linhas = corpo["linhas"];
  if (!eUuid(contactId)) return null;
  if (typeof draftId !== "string" || draftId.length === 0) return null;
  if (!Number.isInteger(draftVersion) || (draftVersion as number) < 1) return null;
  if (entregaModo !== "levantamento" && entregaModo !== "entrega") return null;
  if (!Array.isArray(linhas) || linhas.length === 0) return null;

  const resolvidas: { sku: string; qty: number }[] = [];
  for (const item of linhas) {
    if (typeof item !== "object" || item === null) return null;
    const sku = (item as Record<string, unknown>)["sku"];
    const qty = (item as Record<string, unknown>)["qty"];
    if (typeof sku !== "string" || sku.length === 0) return null;
    if (!Number.isInteger(qty) || (qty as number) < 1) return null;
    resolvidas.push({ sku, qty: qty as number });
  }
  return {
    contactId: contactId.toLowerCase(),
    draftId,
    draftVersion: draftVersion as number,
    entregaModo,
    linhas: resolvidas,
  };
}

/**
 * Um inteiro em unidade menor, de um corpo JSON. **Cadeia ou número inteiro.**
 *
 * O `total_minor` é `bigint` na porta e não cabe num `number` do JSON acima de
 * 2^53 cêntimos — e o `JSON.parse` arredonda-o em silêncio. Por isso a forma
 * canónica no corpo é uma **cadeia de dígitos**; um `number` aceita-se só se for
 * inteiro e seguro, para que quem chama de um cliente simples não tenha de o
 * codificar.
 */
function emMinor(valor: unknown): bigint | null {
  if (typeof valor === "string" && /^[0-9]+$/.test(valor)) return BigInt(valor);
  if (typeof valor === "number" && Number.isSafeInteger(valor) && valor >= 0) {
    return BigInt(valor);
  }
  return null;
}

/**
 * Uma resposta JSON com o estado que lhe pertence.
 *
 * **Não é o `c.json` do Hono**, e a razão é de tipos e não de gosto: aquele
 * método fecha o estado numa união de literais, e os estados desta API vêm de
 * uma tabela (`ESTADO_POR_ERRO`) — um `number` não é atribuível à união, e o
 * caminho para o ser era um `as` por cada resposta. Uma `Response` é o que o
 * Hono devolve de qualquer modo.
 */
function json(corpo: unknown, estado: number): Response {
  return new Response(JSON.stringify(corpo), {
    status: estado,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

/** Um `bigint` sai para JSON como cadeia de dígitos, e nunca como `number`. */
function semBigInt(valor: unknown): unknown {
  if (typeof valor === "bigint") return valor.toString();
  if (Array.isArray(valor)) return valor.map(semBigInt);
  if (valor !== null && typeof valor === "object") {
    return Object.fromEntries(
      Object.entries(valor as Record<string, unknown>).map(([k, v]) => [
        k,
        semBigInt(v),
      ]),
    );
  }
  return valor;
}

/** O filtro do `listOrders` que o corpo descreve. A validação é do módulo. */
function filtroDoCorpo(corpo: Record<string, unknown>): OrderFilter {
  const filtro: {
    estado?: OrderState;
    contactId?: string;
    cursor?: string | null;
    limite?: number;
  } = {};
  if (typeof corpo["estado"] === "string") {
    filtro.estado = corpo["estado"] as OrderState;
  }
  if (typeof corpo["contact_id"] === "string") {
    filtro.contactId = corpo["contact_id"];
  }
  if (typeof corpo["cursor"] === "string") filtro.cursor = corpo["cursor"];
  if (typeof corpo["limite"] === "number") filtro.limite = corpo["limite"];
  return filtro;
}

/**
 * A API interna, montada sobre as operações do COM.
 *
 * Devolve um `Hono` para o `app.ts` montar. Não escuta nada e não lê o cofre:
 * quem o faz é o `server.ts`, pela razão de sempre — quem monta é que sabe de
 * onde vêm as coisas.
 */
export function apiInterna(deps: DependenciasDaApi): Hono {
  const api = new Hono();

  /**
   * A autenticação, **antes** de o corpo ser lido.
   *
   * Um `app.use` e não uma linha em cada rota: sete rotas e sete verificações
   * era a oitava a nascer sem ela. O `/metrics` não passa por aqui — ver a nota
   * da rota.
   */
  api.use("/internal/*", async (c, next) => {
    if (!credencialValida(c.req.header(CABECALHO_INTERNO), deps.credencial)) {
      // **401 e não 403**, que é o número que o critério do KAM-025 escreve, e
      // sem corpo nenhum: dizer «falta o cabeçalho» ou «o cabeçalho está
      // errado» a quem não tem credencial era um oráculo.
      deps.log?.warn({ outcome: "api_interna_nao_autorizada" });
      return json({ error: "unauthorized" }, 401);
    }
    return next();
  });

  for (const rota of ROTAS) {
    api.post(rota, async (c) => {
      const texto = await c.req.text();
      if (texto.length > CORPO_MAXIMO) {
        return json({ error: "payload_too_large" }, 413);
      }
      let corpo: Record<string, unknown>;
      try {
        const lido: unknown = texto.length === 0 ? {} : JSON.parse(texto);
        if (typeof lido !== "object" || lido === null || Array.isArray(lido)) {
          return json({ error: "bad_request" }, 400);
        }
        corpo = lido as Record<string, unknown>;
      } catch {
        return json({ error: "bad_request" }, 400);
      }

      const ctx = ctxDoPedido(c.req.header(CABECALHO_TENANT), corpo);
      if (ctx === null) {
        // *Fail-closed*: sem `ctx` utilizável não se chama operação nenhuma, e a
        // resposta não se parece com uma legítima (ISO-09).
        deps.log?.warn({ outcome: "api_interna_sem_ctx" });
        return json({ error: "ctx" }, 400);
      }

      try {
        return await despachar(rota, ctx, corpo, deps);
      } catch (excepcao) {
        if (excepcao instanceof CtxEmFaltaError) {
          // A segunda barreira do mesmo facto: o `exigirCtx` da porta lança, e
          // isso é 400 e não 500. Chegar aqui quer dizer que o `ctxDoPedido`
          // aceitou algo que a porta recusa — as duas verificações não têm de
          // concordar por acaso, e a que manda é a da porta.
          deps.log?.warn({ outcome: "api_interna_ctx_recusado" });
          return json({ error: "ctx" }, 400);
        }
        throw excepcao;
      }
    });
  }

  return api;
}

/** A resposta de um `Resultado` da porta, com o código canónico no corpo. */
function responder(
  resultado:
    | { readonly tipo: "ok"; readonly valor: unknown }
    | { readonly tipo: "conflito"; readonly valor: unknown }
    | { readonly tipo: "erro"; readonly erro: Erro | ErroDaCriacao },
): Response {
  if (resultado.tipo === "ok") {
    return json({ tipo: "ok", valor: semBigInt(resultado.valor) }, 200);
  }
  if (resultado.tipo === "conflito") {
    return json(
      { tipo: "conflito", valor: semBigInt(resultado.valor) },
      ESTADO_DO_CONFLITO,
    );
  }
  return json(
    { tipo: "erro", erro: resultado.erro },
    ESTADO_POR_ERRO[resultado.erro],
  );
}

/** As sete rotas, uma a uma. O despacho é por igualdade e não por padrão. */
async function despachar(
  rota: (typeof ROTAS)[number],
  ctx: Ctx,
  corpo: Record<string, unknown>,
  deps: DependenciasDaApi,
): Promise<Response> {
  const { porta } = deps.operacoes;

  if (rota === "/internal/offer-view") {
    const sku = corpo["sku"];
    if (typeof sku !== "string" || sku.length === 0) {
      return json({ tipo: "erro", erro: "VALIDATION_ERROR" }, 400);
    }
    return responder(await porta.getOfferView(ctx, sku));
  }

  if (rota === "/internal/propose-cart") {
    const rascunho = rascunhoDoCorpo(corpo);
    if (rascunho === null) {
      return json({ tipo: "erro", erro: "VALIDATION_ERROR" }, 400);
    }
    const resultado = await deps.operacoes.proposeCart(ctx, rascunho);
    if (resultado.tipo === "erro") return responder(resultado);
    // O `draftHash` é um `Buffer` e **não sai**: é estado interno da saga, e um
    // *hash* de rascunho na resposta de uma tool `read` era um valor que o
    // modelo podia citar sem o entender.
    const { cartId, totalMinor, currency, linhas, exigeConfirmacaoDoDono } =
      resultado.valor;
    return responder({
      tipo: "ok",
      valor: {
        cart_id: cartId,
        total_minor: totalMinor,
        currency,
        exige_confirmacao_do_dono: exigeConfirmacaoDoDono,
        linhas,
      },
    });
  }

  if (rota === "/internal/create-order") {
    const rascunho = rascunhoDoCorpo(corpo);
    const total = emMinor(corpo["total_esperado_minor"]);
    if (rascunho === null || total === null) {
      return json({ tipo: "erro", erro: "VALIDATION_ERROR" }, 400);
    }
    const cartId = corpo["cart_id"];
    const pedido: PedidoDeCriacao = {
      rascunho,
      totalEsperadoMinor: total,
      ...(typeof cartId === "string" && cartId.length > 0 ? { cartId } : {}),
    };
    return responder(await deps.operacoes.createOrder(ctx, pedido));
  }

  if (rota === "/internal/get-order") {
    const orderId = corpo["order_id"];
    if (typeof orderId !== "string") {
      return json({ tipo: "erro", erro: "VALIDATION_ERROR" }, 400);
    }
    return responder(await porta.getOrder(ctx, orderId));
  }

  if (rota === "/internal/list-orders") {
    return responder(await porta.listOrders(ctx, filtroDoCorpo(corpo)));
  }

  if (rota === "/internal/transition") {
    const orderId = corpo["order_id"];
    const para = corpo["para"];
    const version = corpo["expected_version"];
    const causa = corpo["causa"];
    if (
      typeof orderId !== "string" ||
      typeof para !== "string" ||
      !Number.isInteger(version) ||
      typeof causa !== "string" ||
      causa.length === 0
    ) {
      return json({ tipo: "erro", erro: "VALIDATION_ERROR" }, 400);
    }
    const eventoId = corpo["evento_id"];
    return responder(
      await porta.transition(ctx, orderId, para as OrderState, version as number, {
        causa,
        eventoId: typeof eventoId === "string" ? eventoId : null,
      }),
    );
  }

  const orderId = corpo["order_id"];
  if (typeof orderId !== "string") {
    return json({ tipo: "erro", erro: "VALIDATION_ERROR" }, 400);
  }
  return responder(await porta.requestOwnerConfirmation(ctx, orderId));
}

/**
 * O `GET /metrics`, em formato Prometheus (critério 8).
 *
 * **Fora do `/internal/*` e por isso sem credencial**, e é uma escolha com
 * razão: o *scraper* do Prometheus não tem segredo nosso, e as duas séries que
 * saem daqui são contagens por filtro — sem `tenant_id`, sem `sku`, sem
 * identificador nenhum (`OBS-I`).
 *
 * **O que isto não é:** uma barreira de rede. O `infra/compose/docker-compose.dev.yml`
 * publica a porta do COM em `127.0.0.1:${COM_PORT:-3002}`, pelo que em `dev`
 * qualquer processo da máquina de quem desenvolve alcança este `/metrics` — e
 * com ele o `/internal/*`, que por isso **tem** credencial. A aplicação na rede
 * é o **KAM-076**, como para o AGR, e fica dito em vez de ficar por dizer.
 *
 * Vive neste ficheiro e não no `app.ts` porque é a mesma superfície HTTP
 * interna, e separá-la dava dois sítios onde se monta uma rota do COM.
 */
export function rotaDasMetricas(): Hono {
  const api = new Hono();
  api.get(
    "/metrics",
    () =>
      new Response(exposicao(), {
        status: 200,
        headers: { "content-type": TIPO_DE_CONTEUDO },
      }),
  );
  return api;
}
