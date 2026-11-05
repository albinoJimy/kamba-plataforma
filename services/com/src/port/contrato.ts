/**
 * A porta `CommerceRegistry` — o contrato, e nada mais (KAM-042).
 *
 * **Esta é a costura do PA-03-1: trocar de Registo não altera agentes, PAY nem
 * EVT.** Por isso este ficheiro não importa nada do Medusa, não abre ligação e
 * não sabe que opção está activa. Quem sabe é o adaptador, e é essa ignorância
 * que faz da porta uma porta.
 *
 * **Os doze métodos, e não onze.** O objectivo do bloco KAM-042 e o §3.38 do
 * dicionário dizem «onze métodos»; o `docs/tecnica/03` §3.2, que é a fonte
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
 *
 * **Desde o KAM-178 são sete os ligados e cinco os que esperam**, e os cinco
 * **não são todos do KAM-045**: quatro são as reservas, que são um ticket de
 * implementação, e o quinto é o `createOrder`, cujo credor é uma **decisão**
 * sobre o `OrderIntent` desta página — a *saga* existe e serve-se pela API
 * interna. A distinção está escrita no método, e apagá-la aqui era desfazer o
 * que o ticket pagou para dizer.
 *
 * Os `ERROS` passaram de cinco a dez e o `Resultado` ganhou um terceiro caso
 * para o conflito de CAS — ver as notas de cada um, e o
 * `docs/com/port-coverage.md` §2 para o estado de cada método.
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

/** Quem está a chamar. `docs/tecnica/03` §3.2 e Detalhes Técnicos do bloco. */
export const ACTOR_KINDS = ["agente", "dono", "sistema", "ops"] as const;
export type ActorKind = (typeof ACTOR_KINDS)[number];

export interface Actor {
  readonly kind: ActorKind;
  readonly id: string;
}

/**
 * O contexto, obrigatório em todas as doze chamadas.
 *
 * O `traceId` é **obrigatório** no §3.2 do `docs/tecnica/03`
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
 * Os códigos de erro da porta. Lista **fechada**, e **dez** desde o KAM-178.
 *
 * Nove dos dez são os do §3.27 do dicionário — a lista fechada de
 * `tool_audit.error_code`, treze desde a emenda 1.47 —, e importam-se de lá
 * pelo nome em vez de serem redeclarados com significado novo. O décimo é o
 * `NOT_IMPLEMENTED`, que é nome **novo** e entra no dicionário §3.39 marcado
 * como *proposta*: nenhum dos treze existentes serve, porque todos descrevem
 * uma recusa sobre dados e este descreve a ausência da implementação.
 *
 * ## Eram cinco e são dez, e o alargamento **cumpre** a regra acima
 *
 * Os cinco nunca foram o universo dos erros da porta: eram o **subconjunto** de
 * que os doze métodos precisavam no dia em que os doze devolviam todos
 * `NOT_IMPLEMENTED`. Os nove que o `ERROS_DA_CRIACAO` do `../orders/create_order.ts`
 * fecha — e que o §3.44 declara como `OrdersModule.erro` — são **todos** nomes
 * do §3.27, pelo que alargar a lista a eles é exactamente o que a frase acima
 * manda fazer: importar de lá pelo nome. Nenhum nome novo entra no dicionário
 * por causa deste alargamento.
 *
 * O que muda com ele é a lista aqui e a **contagem** que o
 * `../../tests/port.contrato.test.ts` pina. É para isso que a contagem existe: quem
 * a mexe vem ler porquê. Decisão do **orquestrador** a 2026-11-04, emenda de
 * nível L5 ao §3.39 — toca o dicionário e não é escolha de canon, porque segue
 * a regra que o §3.39 já escreve.
 *
 * **E a terceira saída está excluída por evidência e não por gosto:** traduzir
 * um `PRICE_CHANGED` para `VALIDATION_ERROR` no adaptador diz a quem viu o preço
 * mudar que o pedido dele não serve. O KAM-044 e o KAM-046 recusaram-na os dois,
 * por escrito e independentemente, cada um no seu ficheiro.
 *
 * O `NOT_IMPLEMENTED` **não** é um `tool_audit.error_code`: uma tool nunca o
 * devolve a um cliente. Pára na API interna do COM, que o traduz para 501.
 */
export const ERROS = [
  "NOT_IMPLEMENTED",
  "NOT_FOUND",
  "VALIDATION_ERROR",
  "TENANT_MISMATCH",
  "PRICE_CHANGED",
  "OUT_OF_STOCK",
  "LIMIT_EXCEEDED",
  "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
  "UPSTREAM_TIMEOUT",
  "UPSTREAM_DOWN",
] as const;
export type Erro = (typeof ERROS)[number];

/**
 * O resultado de uma operação que **não** tem CAS: dois casos, como sempre.
 *
 * A mesma escolha do módulo `servicos`, e vale a pena repetir a razão: uma
 * recusa de domínio é uma **resposta** e não uma excepção, porque o grafo tem
 * de a poder mostrar ao cliente. Um `throw` obrigava cada chamador a distinguir
 * «este tenant não tem este SKU» de «a ligação caiu» pelo nome de uma classe.
 */
export type ResultadoFinal<T> =
  | { readonly tipo: "ok"; readonly valor: T }
  | { readonly tipo: "erro"; readonly erro: Erro };

/**
 * Uma transição perdeu o *compare-and-set*. **Traz a releitura.**
 *
 * «Relê e reavalia (nunca forças)» — §6.2 do `docs/tecnica/03`, e o critério 2
 * do KAM-044 à letra: das vinte concorrentes, uma vence e dezanove «releem e
 * reavaliam». O `valor` é o estado **relido**, para que quem chama reavalie sem
 * segunda viagem.
 */
export type Conflito<T> = { readonly tipo: "conflito"; readonly valor: T };

/**
 * O resultado de uma operação da porta: **três** casos desde o KAM-178.
 *
 * ## O terceiro caso é só para o conflito de CAS, e não uma tríade genérica
 *
 * A razão é de **categoria** e não de conveniência. Um conflito de CAS não é
 * uma recusa sobre dados: é «relê e reavalia», e nenhum dos dez `ERROS`
 * consegue dizer isso — «todos descrevem uma recusa sobre dados», como o
 * comentário do `NOT_IMPLEMENTED` avisa para o seu próprio caso. Codificá-lo
 * como erro era o mesmo erro de categoria.
 *
 * Por isso o caso novo é **exactamente** o que os módulos já têm (a união de
 * três do `../orders/transition.ts` e do `../orders/owner_confirmation.ts`) e
 * nada mais: uma tríade genérica mudava a semântica dos doze métodos sem
 * necessidade, e as operações sem CAS continuam a devolver duas formas
 * (`ResultadoFinal`).
 *
 * **O limite, que fica dito:** num `Resultado<void>` o `conflito` não leva
 * informação de releitura, porque o `void` não tem nenhuma para levar. É uma
 * propriedade da assinatura do `requestOwnerConfirmation` no §3.2 — que é
 * `Promise<void>` — e não do caso novo; quem precisar do subestado relido lê-o
 * com o `getOrder`. Alargar aquela assinatura era alargar o contrato dos doze
 * por um método.
 */
export type Resultado<T> = ResultadoFinal<T> | Conflito<T>;

export function ok<T>(valor: T): ResultadoFinal<T> {
  return { tipo: "ok", valor };
}

export function erro<T>(codigo: Erro): ResultadoFinal<T> {
  return { tipo: "erro", erro: codigo };
}

/** O conflito de CAS, com a releitura. Ver o `Conflito`. */
export function conflito<T>(valor: T): Conflito<T> {
  return { tipo: "conflito", valor };
}

/**
 * Atalho para o `NOT_IMPLEMENTED`. Hoje é o que **cinco** métodos devolvem: os
 * quatro das reservas (KAM-045) e o `createOrder`, por uma razão de outra
 * natureza — ver o método, e o `docs/com/port-coverage.md` §2.
 */
export function naoImplementado<T>(): ResultadoFinal<T> {
  return { tipo: "erro", erro: "NOT_IMPLEMENTED" };
}

// --------------------------------------------------------------- vocabulário
//
// Os tipos abaixo são a **forma** dos argumentos e das respostas, não o modelo
// de dados. O modelo vive no esquema `platform` (`docs/tecnica/03` §5.4) e
// as tabelas são dos tickets que as criam. Aqui está o que atravessa a porta,
// e está em aberto o que esses tickets ainda vão fixar — por isso os campos
// são os que o §3.2 nomeia, e nem um a mais.

/**
 * Os três modos de preço. O nome canónico é **`preco_tipo`**, não `preco_modo`.
 *
 * **E é uma divergência resolvida, não uma escolha.** O `docs/tecnica/03` §3.2
 * escreve `precoModo` no retorno de `getOfferView`, e o critério 2 do KAM-043
 * repete-o; o dicionário §3.3 fixa `preco_tipo` e põe `preco_modo` na coluna
 * «Substitui» desde a emenda 1.12. O dicionário é a fonte 4 e o
 * `docs/tecnica/03` é a 9, pelo que ganha o dicionário — e é exactamente o que
 * a emenda 1.45 decidiu para o KAM-047, cujo bloco também escrevia
 * `preco_modo`. O `servicos/contrato.ts` já usa `precoTipo` ao lado.
 */
export const PRECO_TIPOS = ["fixo", "a_partir_de", "sob_consulta"] as const;
export type PrecoTipo = (typeof PRECO_TIPOS)[number];

/** Os três modos de stock (`offer_terms.stock_modo`). */
export const STOCK_MODOS = ["garantido", "indicativo", "confirmar_dono"] as const;
export type StockModo = (typeof STOCK_MODOS)[number];

/**
 * Os **doze** estados de uma encomenda, pela ordem do dicionário §3.3.
 *
 * **A fonte é o `docs/tecnica/00` §6.1 e não o `docs/tecnica/03` §6.1**, e a
 * diferença não é de estilo: o dicionário §3.3 marca a máquina do `03` como
 * «Máquina incompleta», e ela tem nove — falta-lhe o `entrega_falhada`, o
 * `em_disputa` e o `reembolsada`. Com nove, o KAM-050 («pagamento tardio,
 * disputa, entrega falhada, reembolso») não conseguia chamar
 * `transition(ctx, id, "em_disputa", …)` sem alterar o tipo da porta — isto é, a
 * costura do PA-03-1 partia-se num ticket que depende do KAM-044 e não numa
 * troca de Registo, que é precisamente o que ela existe para impedir.
 *
 * O `CHECK` de `orders_mirror` não existe ainda: a tabela é do **KAM-044**.
 * Quando ele nascer, é desta lista que sai.
 */
export const ORDER_STATES = [
  "criada",
  "aguarda_pagamento",
  "pendente_confirmacao",
  "paga",
  "expirada",
  "em_entrega",
  "entrega_falhada",
  "entregue",
  "em_disputa",
  "reembolso_pendente",
  "reembolsada",
  "cancelada",
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
  readonly precoTipo: PrecoTipo;
  /**
   * Já formatado para apresentação, **com o modo**.
   *
   * **Corrigido pelo KAM-043.** Esta linha dizia «ou `null` em `sob_consulta`»,
   * e era uma previsão e não um contrato: o KAM-042 não implementou o
   * `getOfferView` e escreveu que «a implementação é deles». O critério 2 do
   * KAM-043 enumera as três formas e põe «preço sob consulta» entre elas, como
   * valor deste campo — e a outra metade do critério continua verdadeira,
   * porque esse texto não tem dígito nenhum.
   *
   * O tipo mantém o `| null`: o adaptador do KAM-043 nunca o devolve, e outro,
   * contra outro Registo, pode não ter display para dar. Quem consome trata-o.
   */
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
  /**
   * O total em unidade menor. **`bigint`, e não `number`.**
   *
   * `packages/core-ts/src/pagamentos/tipos.ts` declara `type Minor = bigint`, e
   * o KAM-052 escreveu um *lint* inteiro para isto — que **não morde aqui**,
   * porque as `RAIZES` do `tools/money_lint` são
   * `packages/core-ts/src/pagamentos` e o `services/com` está fora delas. É a
   * fronteira por onde o `bigint` do PAY entra na porta, e um `number` perdia
   * precisão acima de 2^53 cêntimos sem avisar.
   */
  readonly totalMinor: bigint;
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
 * A porta `CommerceRegistry` — os doze métodos do `docs/tecnica/03` §3.2.
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
