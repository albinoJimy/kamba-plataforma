/**
 * A porta `CommerceRegistry` — o contrato, e nada mais (KAM-042).
 *
 * **Esta é a costura do PA-03-1: trocar de Registo não altera agentes, PAY nem
 * EVT.** Por isso este ficheiro não importa nada do Medusa, não abre ligação e
 * não sabe que opção está activa. Quem sabe é o adaptador, e é essa ignorância
 * que faz da porta uma porta.
 *
 * **Os doze métodos, e não onze.** O objectivo do bloco KAM-042 e o §3.38 do
 * dicionário dizem «onze métodos»; o `../docs/tecnica/03` §3.2, que é a fonte
 * do contrato, lista **doze**, e o critério de aceitação nomeia os doze um a
 * um. A contagem errada corrige-se nos dois sítios no PR deste ticket; fica
 * aqui registada porque uma contagem que anda em três documentos é o modo de
 * falha que o conjunto já pagou quatro vezes.
 *
 * **O `ctx` não é um parâmetro de conveniência.** Vem sempre do estado do
 * agente ou da sessão autenticada, nunca do texto do cliente, e um método sem
 * `ctx.tenantId` **falha** em vez de assumir. O `exigirCtx` lança, e a razão é a
 * mesma que o `servicos/contrato.ts` escreveu antes: um `ctx` sem tenant não é
 * uma recusa de domínio que o grafo deva mostrar a um cliente — é um erro de
 * quem montou a chamada, e silenciá-lo num código de retorno deixava a operação
 * correr sem isolamento com a cara de um «não encontrei».
 *
 * O que **não** está aqui, de propósito: preço e stock (KAM-043), a máquina de
 * estados e o `orders_mirror` (KAM-044), as reservas (KAM-045), o
 * `propose_cart` (KAM-046). A porta nomeia-os; a implementação é deles, e até
 * chegar cada método devolve `NOT_IMPLEMENTED` com o ticket dono escrito em
 * `docs/com/port-coverage.md`.
 */

/** O mínimo de um cliente SQL de que a porta e os adaptadores precisam. */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ readonly rows: readonly Readonly<Record<string, unknown>>[] }>;
}

/**
 * Transacção com `app.tenant_id` definido.
 *
 * A mesma forma do `ComTenant` de `servicos/contrato.ts`, e pela mesma razão:
 * **não recebe o cliente**, para ser atribuível ao `comTenant` de
 * `@kamba/core-ts/tenant_guard` depois de ligado a uma ligação. Quem monta o
 * adaptador decide de onde vem a ligação; o adaptador nunca a escolhe.
 */
export type ComTenant = <T>(
  tenantId: string,
  trabalho: (cliente: ClienteSql) => Promise<T>,
) => Promise<T>;

/** Quem está a chamar. `../docs/tecnica/03` §3.2 e Detalhes Técnicos do bloco. */
export const ACTOR_KINDS = ["agente", "dono", "sistema", "ops"] as const;
export type ActorKind = (typeof ACTOR_KINDS)[number];

export interface Actor {
  readonly kind: ActorKind;
  readonly id: string;
}

/**
 * O contexto, obrigatório em todas as doze chamadas.
 *
 * O `traceId` é **obrigatório** no §3.2 do `../docs/tecnica/03`
 * (`traceId: string`), e é obrigatório aqui. É a diferença face ao `Ctx` do
 * módulo `servicos`, onde é opcional: ali o envelope do evento aceita `null`,
 * aqui a porta é a fronteira de uma *saga* de várias escritas (§6.3) e uma
 * correlação em falta tira a quem reconcilia o único fio que liga a intenção à
 * encomenda.
 */
export interface Ctx {
  readonly tenantId: string;
  readonly actor: Actor;
  readonly traceId: string;
}

/**
 * Os códigos de erro da porta. Lista **fechada**.
 *
 * Quatro dos cinco são os do §3.27 do dicionário — a lista fechada de
 * `tool_audit.error_code` —, e importam-se de lá pelo nome em vez de serem
 * redeclarados com significado novo. O quinto é o `NOT_IMPLEMENTED`, que é
 * nome **novo** e entra no dicionário §3.39 marcado como *proposta*: nenhum
 * dos treze existentes serve, porque todos descrevem uma recusa sobre dados e
 * este descreve a ausência da implementação.
 *
 * O `NOT_IMPLEMENTED` **não** é um `tool_audit.error_code`: uma tool nunca o
 * devolve a um cliente. Pára na API interna do COM, que o traduz para 501.
 */
export const ERROS = [
  "NOT_IMPLEMENTED",
  "NOT_FOUND",
  "TENANT_MISMATCH",
  "VALIDATION_ERROR",
  "UPSTREAM_DOWN",
] as const;
export type Erro = (typeof ERROS)[number];

/**
 * O resultado de uma operação, como união discriminada.
 *
 * A mesma escolha do módulo `servicos`, e vale a pena repetir a razão: uma
 * recusa de domínio é uma **resposta** e não uma excepção, porque o grafo tem
 * de a poder mostrar ao cliente. Um `throw` obrigava cada chamador a distinguir
 * «este tenant não tem este SKU» de «a ligação caiu» pelo nome de uma classe.
 */
export type Resultado<T> =
  | { readonly tipo: "ok"; readonly valor: T }
  | { readonly tipo: "erro"; readonly erro: Erro };

export function ok<T>(valor: T): Resultado<T> {
  return { tipo: "ok", valor };
}

export function erro<T>(codigo: Erro): Resultado<T> {
  return { tipo: "erro", erro: codigo };
}

/** Atalho para o `NOT_IMPLEMENTED`, que hoje é o que os doze devolvem. */
export function naoImplementado<T>(): Resultado<T> {
  return { tipo: "erro", erro: "NOT_IMPLEMENTED" };
}

// --------------------------------------------------------------- vocabulário
//
// Os tipos abaixo são a **forma** dos argumentos e das respostas, não o modelo
// de dados. O modelo vive no esquema `platform` (`../docs/tecnica/03` §5.4) e
// as tabelas são dos tickets que as criam. Aqui está o que atravessa a porta,
// e está em aberto o que esses tickets ainda vão fixar — por isso os campos
// são os que o §3.2 nomeia, e nem um a mais.

/** Os três modos de preço (`offer_terms.preco_tipo`, dicionário §3.3). */
export const PRECO_MODOS = ["fixo", "a_partir_de", "sob_consulta"] as const;
export type PrecoModo = (typeof PRECO_MODOS)[number];

/** Os três modos de stock (`offer_terms.stock_modo`). */
export const STOCK_MODOS = ["garantido", "indicativo", "confirmar_dono"] as const;
export type StockModo = (typeof STOCK_MODOS)[number];

/** Os nove estados de uma encomenda (`orders_mirror.estado`, §6.1). */
export const ORDER_STATES = [
  "criada",
  "aguarda_pagamento",
  "pendente_confirmacao",
  "paga",
  "em_entrega",
  "entregue",
  "expirada",
  "cancelada",
  "reembolso_pendente",
] as const;
export type OrderState = (typeof ORDER_STATES)[number];

/** Os três motivos de libertação de reserva (§3.2). */
export const MOTIVOS_DE_LIBERTACAO = [
  "expirada",
  "cancelada",
  "recusada_dono",
] as const;
export type MotivoDeLibertacao = (typeof MOTIVOS_DE_LIBERTACAO)[number];

/**
 * Um rascunho de produto. **Rascunho, nunca publicado** (§3.2).
 *
 * Os campos são os de `offer_terms` e de `commerce.products`; o conjunto
 * completo é do KAM-043 e do KAM-049, que o estreitam ou alargam contra o
 * perfil de completude do §8.3. Aqui está o que a assinatura precisa para
 * existir.
 */
export interface ProductDraft {
  readonly sku: string;
  readonly nome: string;
  readonly descricao?: string | null;
  readonly categoria?: string | null;
  readonly atributos?: Readonly<Record<string, unknown>>;
}

/** A referência opaca de um produto no Registo activo. */
export interface ProductRef {
  readonly sku: string;
  /** O id no Registo. `null` enquanto o Registo não o tiver atribuído. */
  readonly registoId: string | null;
}

/**
 * A confirmação do dono exigida por `publishProduct`.
 *
 * **Não é um booleano**, e a diferença é o produto: um `true` não se audita. O
 * `actor` que confirmou e o instante ficam, porque a publicação de um produto
 * é o acto que põe um preço à frente de um cliente.
 */
export interface OwnerConfirmation {
  readonly actor: Actor;
  readonly em: string;
}

/** O que o agente pode dizer sobre uma oferta (§7.1). */
export interface OfferView {
  readonly sku: string;
  readonly precoModo: PrecoModo;
  /** Já formatado para apresentação, ou `null` em `sob_consulta`. */
  readonly precoDisplay: string | null;
  readonly stockModo: StockModo;
  readonly disponibilidade: string;
  readonly atualizadoAt: string;
}

/**
 * A intenção de encomenda. A idempotência é por `(tenantId, intentKey)` (§6.3).
 *
 * **Nenhuma linha leva preço**, e é regra da porta e não omissão: «nenhuma
 * operação aceita um preço do chamador — o preço vem de `offer_terms`/Registo,
 * ou de uma `price_quote` do dono» (§3.2, regra 4).
 */
export interface OrderIntent {
  readonly intentKey: string;
  readonly contactId: string;
  readonly linhas: readonly {
    readonly sku: string;
    readonly qty: number;
  }[];
  readonly entregaModo: "levantamento" | "entrega";
}

export interface OrderRef {
  readonly orderId: string;
  readonly numeroPublico: string;
  readonly estado: OrderState;
  readonly version: number;
}

export interface Reservation {
  readonly reservationId: string;
  readonly sku: string;
  readonly qty: number;
  readonly expiraAt: string;
}

/** A causa de uma transição, para o `order_state_log` (§5.4). */
export interface Cause {
  readonly causa: string;
  readonly eventoId?: string | null;
}

export interface OrderView extends OrderRef {
  readonly contactId: string;
  readonly totalMinor: number;
  readonly currency: string;
  readonly linhas: readonly Readonly<Record<string, unknown>>[];
  readonly criadoAt: string;
}

export interface OrderFilter {
  readonly estado?: OrderState;
  readonly contactId?: string;
  /** Cursor opaco. Um cursor forjado é `VALIDATION_ERROR` (ISO-10). */
  readonly cursor?: string | null;
  readonly limite?: number;
}

export interface Page<T> {
  readonly itens: readonly T[];
  readonly proximo: string | null;
}

/** Uma duração em milissegundos. O TTL da reserva está em [24 h, 72 h] (§6.4). */
export type Duration = number;

// -------------------------------------------------------------------- a porta

/**
 * A porta `CommerceRegistry` — os doze métodos do `../docs/tecnica/03` §3.2.
 *
 * Todos recebem `ctx`. Todos devolvem `Resultado`, incluindo os que o §3.2
 * escreve como `Promise<void>`: um `void` não distingue «fiz» de «não está
 * implementado», e é exactamente a distinção que o critério 6 deste ticket
 * exige que a porta saiba fazer.
 */
export interface CommerceRegistry {
  // ------------------------------------------------------------- catálogo
  upsertProductDraft(ctx: Ctx, d: ProductDraft): Promise<Resultado<ProductRef>>;
  publishProduct(
    ctx: Ctx,
    ref: ProductRef,
    c: OwnerConfirmation,
  ): Promise<Resultado<void>>;
  getOfferView(ctx: Ctx, sku: string): Promise<Resultado<OfferView>>;

  // ------------------------------------------------------------ encomendas
  createOrder(ctx: Ctx, i: OrderIntent): Promise<Resultado<OrderRef>>;
  requestOwnerConfirmation(ctx: Ctx, orderId: string): Promise<Resultado<void>>;
  reserveStock(
    ctx: Ctx,
    orderId: string,
    ttl: Duration,
  ): Promise<Resultado<readonly Reservation[]>>;
  extendReservation(
    ctx: Ctx,
    orderId: string,
    until: string,
  ): Promise<Resultado<void>>;
  commitReservation(ctx: Ctx, orderId: string): Promise<Resultado<void>>;
  releaseReservation(
    ctx: Ctx,
    orderId: string,
    motivo: MotivoDeLibertacao,
  ): Promise<Resultado<void>>;
  transition(
    ctx: Ctx,
    orderId: string,
    to: OrderState,
    expectedVersion: number,
    causa: Cause,
  ): Promise<Resultado<OrderRef>>;

  // ---------------------------------------------------------------- leitura
  getOrder(ctx: Ctx, orderId: string): Promise<Resultado<OrderView>>;
  listOrders(ctx: Ctx, f: OrderFilter): Promise<Resultado<Page<OrderView>>>;
}

/** Os nomes dos doze métodos, por ordem. A contagem está presa num teste. */
export const METODOS_DA_PORTA = [
  "upsertProductDraft",
  "publishProduct",
  "getOfferView",
  "createOrder",
  "requestOwnerConfirmation",
  "reserveStock",
  "extendReservation",
  "commitReservation",
  "releaseReservation",
  "transition",
  "getOrder",
  "listOrders",
] as const;
export type MetodoDaPorta = (typeof METODOS_DA_PORTA)[number];

// --------------------------------------------------------- `ctx` fail-closed

/** Pediu-se uma operação sem contexto utilizável. Falha fechada (critério 1). */
export class CtxEmFaltaError extends Error {
  override readonly name = "CtxEmFaltaError";
  constructor(campo: string) {
    super(
      `a porta CommerceRegistry exige ctx.${campo}: sem ele a consulta corria ` +
        "sem filtro de tenant e a resposta parecia legitima " +
        "(KAM-042, criterio 1, ISO-09)",
    );
  }
}

const UUID_CANONICO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** O `traceId`: não é UUID por contrato, mas não pode ser vazio nem absurdo. */
const TRACE_ID_MAXIMO = 128;

/** Verdadeiro para a forma canónica de um UUID. */
export function eUuid(valor: unknown): valor is string {
  return typeof valor === "string" && UUID_CANONICO.test(valor.toLowerCase());
}

/**
 * O `ctx` validado, ou lança.
 *
 * Verifica as **três** partes, e as três são barreiras distintas:
 *
 *   tenantId    sem ele não há isolamento (ISO-09)
 *   actor.kind  um `kind` fora dos quatro é um chamador que ninguém desenhou,
 *               e aceitá-lo deixava o `order_state_log` com um `actor_kind`
 *               que nenhuma consulta de auditoria sabe interpretar
 *   traceId     sem ele a reconciliação do §10.3 perde o fio da *saga*
 *
 * **Lança, não devolve `VALIDATION_ERROR`.** Ver o comentário do topo.
 */
export function exigirCtx(ctx: Ctx): {
  tenantId: string;
  actor: Actor;
  traceId: string;
} {
  const tenantId = String(ctx?.tenantId ?? "").toLowerCase();
  if (!UUID_CANONICO.test(tenantId)) throw new CtxEmFaltaError("tenantId");

  const kind = ctx?.actor?.kind as ActorKind | undefined;
  if (kind === undefined || !ACTOR_KINDS.includes(kind)) {
    throw new CtxEmFaltaError("actor.kind");
  }
  const actorId = String(ctx.actor?.id ?? "");
  if (actorId.length === 0) throw new CtxEmFaltaError("actor.id");

  const traceId = String(ctx?.traceId ?? "");
  if (traceId.length === 0 || traceId.length > TRACE_ID_MAXIMO) {
    throw new CtxEmFaltaError("traceId");
  }

  return { tenantId, actor: { kind, id: actorId }, traceId };
}
