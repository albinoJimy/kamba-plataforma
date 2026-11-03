/**
 * O vocabulário do módulo `orders` — tipos, domínios fechados e constantes.
 *
 * Os estados **não se redeclaram aqui**: são os doze `ORDER_STATES` da porta
 * (`../port/contrato.ts`), que o KAM-042 já fixou a partir do dicionário §3.3 e
 * do `docs/tecnica/00` §6.1, e que a revisão `0030` escreveu no
 * `orders_mirror_estado_ck`. Uma segunda lista aqui era uma segunda fonte para
 * a mesma coisa.
 *
 * ## O grafo **não** está neste ficheiro, e é de propósito
 *
 * O critério 1 diz que as transições são **dados** (`order_state_graph`), e o
 * `graph.ts` lê-as da base. Escrevê-las aqui dava duas listas que podem
 * divergir — e a que manda é a da base, porque é o *trigger* `BEFORE UPDATE`
 * que recusa o que não está lá. O que este módulo tem são os **nomes** das
 * causas e dos eventos, que não vivem em tabela nenhuma.
 */

import type { ActorKind, Ctx, OrderState } from "../port/contrato.ts";

/**
 * O cliente SQL mínimo, e a forma é a do `ten` e não a do `produtos`.
 *
 * **Leva o `rowCount`**, que o `produtos/contrato.ts` não leva, e a razão é
 * concreta: este módulo passa o mesmo cliente ao `checkCeiling` de
 * `@kamba/core-ts/ten` (a guarda do `pendente_confirmacao`), e o `ClienteSql`
 * declarado lá tem `rows` **e** `rowCount`. Com a forma mais estreita, o
 * `tsc` recusa a passagem — medido no *gate* 2, `TS2345`. O `pg` devolve as
 * duas, pelo que a forma larga é a verdadeira; a estreita era uma omissão que
 * só não doía enquanto ninguém atravessasse a fronteira.
 */
export interface ClienteSql {
  query(
    sql: string,
    valores?: readonly unknown[],
  ): Promise<{
    rows: Record<string, unknown>[];
    rowCount: number | null;
  }>;
}

// ------------------------------------------------------------------- eventos

/**
 * Os **cinco** tipos de evento deste módulo, e o sexto que o critério 8 pede e
 * que o catálogo publicado não tem.
 *
 * O critério 8 enumera seis: `order.created`, `order.paid`, `order.expired`,
 * `order.cancelled`, `order.delivered` e `order.reconciliation_issue`. Dos
 * seis, **cinco** têm contrato em `contratos/eventos/` e estão nos trinta e oito
 * tipos que o dicionário §3.5 fixa. O sexto **não existe**: não tem contrato,
 * não está no §3.5 e não está no `docs/tecnica/06` §5 — só no §12 do
 * `docs/tecnica/03`, que é exactamente o documento que a dívida documental 37
 * descreve como «um segundo catálogo de eventos, paralelo ao do
 * `docs/tecnica/06` §5, e discorda dele em nomes e em payloads».
 *
 * Resolve-se a favor do dicionário (fonte 4) contra o bloco (fonte 8) e contra
 * o §12 (fonte 9), que é a mesma escolha que o `produtos/eventos.ts` do KAM-043
 * e o `servicos/eventos.ts` do KAM-047 fizeram, pela mesma razão e com a mesma
 * dívida citada. E a razão não é só a ordem das fontes: emitir
 * `order.reconciliation_issue` levantava `TipoDesconhecidoError` no
 * `validarPayload` da linha de emissão, antes de o *gate* 7 chegar a ver o
 * envelope — e, se passasse, parava no publicador, que faz falhar de forma
 * visível uma versão que não conhece (`docs/tecnica/06` §6.6).
 *
 * **O que fica no lugar dele, e não é menos:** a divergência é registada em
 * `platform.order_reconciliation_issues` (revisão `0030`), que são os *Detalhes
 * Técnicos* do bloco à letra e é o que a métrica «divergências abertas > 5 min
 * = 0» lê. O que não sai é o **evento**, e quem o quiser tem de acrescentar um
 * trigésimo-nono contrato ao catálogo e emendar a contagem do §3.5 — que é
 * alteração do dicionário e não deste módulo.
 */
export const TIPO_CREATED = "order.created";
export const TIPO_PAID = "order.paid";
export const TIPO_EXPIRED = "order.expired";
export const TIPO_CANCELLED = "order.cancelled";
export const TIPO_DELIVERED = "order.delivered";

/** As versões emitidas. `v1` nos cinco, como em todos os produtores. */
export const VERSAO_CREATED = 1;
export const VERSAO_PAID = 1;
export const VERSAO_EXPIRED = 1;
export const VERSAO_CANCELLED = 1;
export const VERSAO_DELIVERED = 1;

/** O `agregado.tipo` dos cinco contratos: `order` (é `const` em todos). */
export const AGREGADO_ORDER = "order";

/** A classe de PII dos cinco exemplos publicados: `P0`. */
export const CLASSE_PII_ENCOMENDA = "P0";

/** As finalidades dos cinco exemplos publicados. */
export const FINALIDADES_ENCOMENDA = ["transacao"] as const;

/**
 * Os estados que **emitem** evento neste ticket, e os que não emitem.
 *
 * O §6.2 dá um evento a quase toda a transição, e a maioria desses eventos não
 * é deste ticket nem tem contrato: `order.reserved` e `charge.requested`
 * (KAM-045 e KAM-055), `order.manual_confirmation_requested` e
 * `order.manual_confirmation_rejected` (KAM-054, e sem contrato publicado),
 * `order.dispatched` (Clusters). O critério 8 nomeia cinco com contrato, e são
 * estes quatro destinos mais o `order.created` do nascimento.
 *
 * Uma transição para um estado que não está neste mapa **grava o registo e não
 * emite**: é o que `pendente_confirmacao`, `aguarda_pagamento` e `em_entrega`
 * fazem hoje, e o credor de cada evento está escrito acima.
 */
export const EVENTO_POR_ESTADO: Readonly<Partial<Record<OrderState, string>>> = {
  paga: TIPO_PAID,
  expirada: TIPO_EXPIRED,
  cancelada: TIPO_CANCELLED,
  entregue: TIPO_DELIVERED,
};

// -------------------------------------------------------------------- causas

/**
 * As **duas** causas que levam a `paga`, e são os dois eventos distintos do §12.
 *
 * O critério 3 fecha a via: `paga` só com `causa.evento_id` de evento
 * autenticado do PAY e actor `sistema`. A barreira real é o *trigger* diferido
 * `order_estado_exige_log` da revisão `0030` — esta lista é a mesma regra do
 * lado do módulo, para que a recusa chegue com um erro da porta em vez de um
 * `KA006` do PostgreSQL.
 */
export const CAUSAS_QUE_PAGAM = [
  "payment.confirmed",
  "payment.manual_confirmed",
] as const;
export type CausaQuePaga = (typeof CAUSAS_QUE_PAGAM)[number];

/** A `paga_via` que cada causa autenticada determina (§6.2). */
export const VIA_POR_CAUSA: Readonly<Record<CausaQuePaga, string>> = {
  "payment.confirmed": "provider_autenticado",
  "payment.manual_confirmed": "manual_auditado",
};

/**
 * O actor que o critério 3 exige para `paga`.
 *
 * «actor `agente` ou `dono` sem evento é recusado» — e com evento também: a
 * confirmação manual auditada é registada pelo PAY e entra aqui como
 * `payment.manual_confirmed` emitido pelo **sistema**. Quem declara «recebi» é
 * o dono, e essa declaração leva a encomenda a `pendente_confirmacao`, não a
 * `paga`.
 */
export const ACTOR_DO_PAGAMENTO: ActorKind = "sistema";

/**
 * A chave de entitlement que guarda o `pendente_confirmacao` (§6.2).
 *
 * «`total_minor <= limite_manual` do tenant», e o `limite_manual` é o
 * `manual_max_minor` que o §5.2 daquele documento escreve no exemplo do
 * registo. **Lê-se por `platform.ten_tecto`** — a função da revisão `0007` que
 * o `checkCeiling` do `packages/core-ts/src/ten` chama —, e não de
 * `entitlements.limites` directamente: o tecto efectivo é o **mínimo** entre os
 * módulos activos que declaram a chave, e uma leitura directa perdia essa
 * regra. O `registry/entitlement_keys.schema.json` classifica-a como
 * `tecto_por_pedido` e `consumivel: false`, que é o que distingue
 * `checkCeiling` de `consumeLimit`.
 */
export const CHAVE_DO_TECTO_MANUAL = "manual_max_minor";

/**
 * A causa que a reconciliação grava (§10.3, última frase).
 *
 * **Fica declarada e sem chamador neste ticket**, e isso é dito em vez de a
 * constante sair: o §10.3 manda que «todas as correcções» a gravem, e as
 * correcções que sobram tocam todas o Registo — passam pela porta e são do
 * KAM-045 e do KAM-046 (ver o `reconcile.ts`). O que a usa hoje é o
 * `test_reconciliacao`, que mede a causa na linha de registo e mede que a
 * reconciliação **não** alcança `paga` com ela.
 */
export const CAUSA_DA_RECONCILIACAO = "reconciliacao";

// ------------------------------------------------------- SQLSTATE da revisão

/** `KA003`: transição fora do grafo, bandeira desligada, ou `version` errada. */
export const SQLSTATE_TRANSICAO = "KA003";
/** `KA004`: `lines_snapshot`, `total_minor` ou `currency` depois de `criada`. */
export const SQLSTATE_SNAPSHOT = "KA004";
/** `KA005`: mudou de estado sem gravar `order_state_log` na mesma transacção. */
export const SQLSTATE_REGISTO = "KA005";
/** `KA006`: `paga` sem evento autenticado do PAY com actor `sistema`. */
export const SQLSTATE_AUTENTICIDADE = "KA006";
/** `KA007`: `pendente_confirmacao` acima do tecto manual, ou sem entitlement. */
export const SQLSTATE_TECTO_MANUAL = "KA007";
/** `23505`: violação de unicidade. É o `numero_publico` e o `intent_key`. */
export const SQLSTATE_UNICIDADE = "23505";
/** `23514`: violação de `CHECK`. É o `total_minor >= 0` e os domínios. */
export const SQLSTATE_CHECK = "23514";
/** `23503`: violação de FK. É a FK **composta** do contacto (ISO-58). */
export const SQLSTATE_FK = "23503";

// --------------------------------------------------------------------- tipos

/** Uma linha do `order_state_graph`, como a base a tem. */
export interface Transicao {
  readonly de: OrderState;
  readonly para: OrderState;
  /** `null` quando está sempre activa; o nome da bandeira quando não. */
  readonly flag: string | null;
}

/** A causa de uma transição, com o actor que a porta já valida. */
export interface CausaDaTransicao {
  readonly causa: string;
  readonly eventoId?: string | null;
}

/** O que a transição devolve: o suficiente para reler e reavaliar. */
export interface EstadoDaEncomenda {
  readonly orderId: string;
  readonly numeroPublico: string;
  readonly estado: OrderState;
  readonly version: number;
  readonly totalMinor: bigint;
  readonly currency: string;
  readonly expiraAt: string | null;
  readonly pagaVia: string | null;
  readonly entregaConfirmadaPor: string | null;
}

/** Uma linha do `lines_snapshot` (§5.4). Quem a escreve é o KAM-046. */
export interface LinhaDaEncomenda {
  readonly sku: string;
  readonly nome: string;
  readonly qty: number;
  readonly precoMinor: bigint;
  readonly precoTipo: string;
  readonly origemPreco: string;
}

/** O que `registar` precisa para criar o espelho de uma encomenda. */
export interface EspelhoNovo {
  readonly intentKey: string;
  readonly contactId: string;
  readonly totalMinor: bigint;
  readonly currency: string;
  readonly entregaModo: "levantamento" | "entrega";
  readonly linhas: readonly LinhaDaEncomenda[];
  readonly confirmacaoDono?: string;
  readonly medusaOrderId?: string | null;
  readonly origem?: "pme" | "plataforma";
}

/** O que o `ctx` garante a quem escreve. Reexportado para não importar a porta. */
export type { ActorKind, Ctx, OrderState };
