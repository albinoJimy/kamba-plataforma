/**
 * As arestas do KAM-050, do lado do módulo: o que cada uma exige e emite.
 *
 * **As arestas não estão aqui.** São dados da `platform.order_state_graph`, que a
 * revisão `0046` acrescenta à tabela do KAM-044, e quem as impõe é o *trigger*
 * `order_transicao_valida` — pela razão escrita no `graph.ts`: uma segunda lista
 * em TypeScript podia divergir da primeira, e a que manda é a da base. O que este
 * ficheiro tem é o que **não** cabe numa linha `(de, para, flag)`:
 *
 * ```text
 * reembolso_pendente   o motivo do `order.refund_requested`, que depende de onde vem
 * reembolsada          só por dono ou ops identificado, com `audit_log` (critério 5)
 * entregue             ao voltar de `em_disputa` não é entrega nova: não emite
 * ```
 *
 * ## As nove arestas, para quem lê sem a base à mão
 *
 * ```text
 * expirada           -> paga                 pagamento tardio (regras 1 e 2, §6.6)
 * paga               -> reembolso_pendente   disputa antes da entrega
 * entregue           -> em_disputa           reclamação
 * em_disputa         -> reembolso_pendente   decisão a favor do cliente
 * em_disputa         -> entregue             decisão a favor da PME
 * em_entrega         -> entrega_falhada      sem sucesso             [bandeira]
 * entrega_falhada    -> em_entrega           nova tentativa          [bandeira]
 * entrega_falhada    -> reembolso_pendente   devolução               [bandeira]
 * reembolso_pendente -> reembolsada          reembolso manual registado
 * ```
 *
 * **Nove e não as oito do critério 1**, e a nona é a primeira das três com
 * bandeira: o critério acrescenta duas arestas que **saem** de `entrega_falhada`
 * e nenhuma que lá chegue, pelo que, à letra, o estado continuava inalcançável e
 * as duas eram linhas mortas. A `em_entrega -> entrega_falhada` é do
 * `docs/tecnica/00` §6.1 («sem sucesso»), que é o documento a que o Contexto do
 * bloco manda alinhar. As três que tocam `entrega_falhada` ficam atrás de
 * `COM_DELIVERY_ENABLED`, como o critério 6 manda.
 */

import type { ActorKind, MotivoDeReembolso, OrderState } from "./contrato.ts";

/**
 * O motivo do `order.refund_requested`, pela origem da aresta.
 *
 * `undefined` para uma origem que não chega a `reembolso_pendente` pelo grafo:
 * quem chama recusa em vez de emitir um evento com um motivo inventado.
 */
export const MOTIVO_POR_ORIGEM: Readonly<
  Partial<Record<OrderState, MotivoDeReembolso>>
> = {
  paga: "disputa",
  em_disputa: "disputa",
  entrega_falhada: "entrega_falhada",
};

/**
 * Quem pode registar um reembolso (critério 5): `dono` ou `ops`.
 *
 * Não o `agente` — um modelo de linguagem não afirma que a PME devolveu dinheiro
 * — e não o `sistema`: nenhum processo sabe que um reembolso foi feito, porque a
 * plataforma não move fundos (ADR-004). A barreira real é o
 * `order_estado_exige_log` da revisão `0046`, que recusa com `KA006`; isto está
 * aqui para que a recusa chegue como erro da porta.
 */
export const ACTORES_DO_REEMBOLSO: readonly ActorKind[] = ["dono", "ops"];

/** A causa que o registo do reembolso grava no `order_state_log`. */
export const CAUSA_DO_REEMBOLSO = "reembolso_manual_registado";

/** O estado a que só um humano identificado leva a encomenda. */
export const REEMBOLSADA: OrderState = "reembolsada";

/** O actor pode levar a encomenda a `reembolsada`? Exige `id` não vazio. */
export function actorDoReembolso(kind: ActorKind, id: string): boolean {
  return ACTORES_DO_REEMBOLSO.includes(kind) && id.trim() !== "";
}

/**
 * A ida a `entregue` é uma **entrega**, ou o fim de uma disputa a favor da PME?
 *
 * A diferença decide três coisas no `transition`: o fim de uma disputa não exige
 * `entrega_confirmada_por` novo, não reescreve o `entregue_at` da entrega que
 * houve, e não emite um segundo `order.delivered` — que um consumidor contaria
 * como outra entrega.
 */
export function eFimDeDisputa(de: OrderState, para: OrderState): boolean {
  return de === "em_disputa" && para === "entregue";
}
