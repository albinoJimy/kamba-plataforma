/**
 * Os reembolsos do COM: pedir e registar, **nunca** executar (KAM-050).
 *
 * «Reembolsos são sempre manuais e fora da plataforma até existir PSP» (ADR-004,
 * Contexto do bloco). O COM faz duas coisas e não faz a terceira:
 *
 * ```text
 * pedir      order.refund_requested, por aresta para reembolso_pendente ou
 *            pelas regras 3 e 4 do §6.6 (ver ../orders/late_payment.ts)
 * registar   reembolso_pendente -> reembolsada, por dono ou ops, com audit_log
 * executar   NÃO. Nenhum refund, nenhum payout: quem devolve é a PME, da conta dela
 * ```
 *
 * O «não» do terceiro é verificado por máquina e não por esta nota: o
 * `services/com/tests/orders.reembolso.test.ts` varre o `src/` do COM à procura
 * de qualquer chamada a `refund` ou `payout`, e o canário dele prova que a
 * varredura morde.
 *
 * ## O que este módulo **não** faz, e a decisão é do fundador
 *
 * **Não escreve na `platform.refund_cases`.** A tabela é do KAM-054 (revisão
 * `0032`), tem `SELECT` só para os três papéis, e o único escritor é a
 * `platform.manual_reverter` — que abre o caso **dentro** de uma reversão no
 * *ledger*. Abrir um caso sem essa reversão é a decisão que a revisão `0039`
 * (KAM-060) devolveu ao fundador por escrito: «um caso aberto por um lote, sem
 * reversão no *ledger*, é um caso que ninguém sabe fechar». O que fica por
 * decidir é quem escreve a `refund_cases` fora de uma reversão manual, e com que
 * papel. Até lá, o caso é o `order.refund_requested` e a excepção na encomenda.
 */

import { checkCeiling } from "@kamba/core-ts/ten";

import { ACTOR_AUDITADO } from "../produtos/contrato.ts";
import { SEPARADOR } from "../produtos/auditoria.ts";
import type { ClienteSql, Ctx } from "./contrato.ts";
import { SQL_AUDITAR_REEMBOLSO } from "./consultas.ts";

// -------------------------------------------------- o prazo de reclamação

/**
 * A chave do prazo de reclamação (KAM-050, critério 8), em `entitlements.limites`.
 *
 * **Configuração por tenant e sem valor por omissão.** É um tecto por pedido do
 * `registry/entitlement_keys.schema.json` — «os dias desde a entrega cabem no
 * prazo?» —, e lê-se pelo `checkCeiling` do `ten`, que devolve o mínimo entre os
 * módulos activos que a declaram. Não está no `registry/plans.yaml` e não tem
 * valor em código nenhum: o direito de desistência de 7 dias úteis é INDÍCIO e
 * espera parecer (KAM-104).
 */
export const CHAVE_DO_PRAZO = "prazo_reclamacao_dias";

const MS_POR_DIA = 24 * 60 * 60 * 1000;

/** Os dias **completos** desde a entrega. Zero no próprio dia. */
export function diasDesdeAEntrega(entregueAt: string, agora: Date): number {
  const decorrido = agora.getTime() - Date.parse(entregueAt);
  if (!Number.isFinite(decorrido) || decorrido < 0) return 0;
  return (decorrido - (decorrido % MS_POR_DIA)) / MS_POR_DIA;
}

/**
 * A reclamação ainda cabe no prazo do tenant?
 *
 * **Sem a chave declarada, cabe**, e é a diferença face aos outros tectos. Para o
 * `manual_max_minor`, «sem tecto não quer dizer sem limite» e a ausência recusa
 * (critério 2 do KAM-009). Aqui recusar seria **assumir um prazo legal** — o
 * prazo zero — que nenhum parecer fixou, e o critério 8 diz o contrário à letra:
 * «nenhum prazo legal é assumido». A disputa entra, e decide-a um humano.
 *
 * Uma encomenda sem `entregue_at` também cabe: não se mede um prazo a partir de
 * um instante que não existe.
 */
export async function dentroDoPrazo(
  cliente: ClienteSql,
  tenantId: string,
  entregueAt: string | null,
  agora: Date,
): Promise<boolean> {
  if (entregueAt === null) return true;
  const tecto = await checkCeiling(
    cliente,
    tenantId,
    CHAVE_DO_PRAZO,
    diasDesdeAEntrega(entregueAt, agora),
  );
  return tecto.cabe || tecto.motivo === "sem_entitlement";
}

/** A acção de `audit_log` do reembolso registado. A `0046` acrescenta-a. */
export const ACCAO_DO_REEMBOLSO = "order.refund_record";

/** A `entity` da linha de auditoria. O `entity_id` é o `order_id`. */
export const ENTIDADE_DO_REEMBOLSO = "orders_mirror";

/**
 * O texto que se resume em SHA-256 na linha de auditoria.
 *
 * `<accao>␟<order_id>␟<version>␟<prova_ref>`. A `version` é a de **depois** da
 * transição, e é o que liga a linha de auditoria à linha exacta do
 * `order_state_log` — uma encomenda pode, em princípio, voltar a
 * `reembolso_pendente` e ser reembolsada outra vez, e sem a versão as duas
 * linhas de auditoria eram indistinguíveis. A `prova_ref` é a referência que
 * quem regista dá (o número da transferência que a PME fez, por exemplo), e é
 * **opcional**: o critério 5 pede o registo e o actor, não a prova.
 *
 * Injectivo pela razão do `produtos/auditoria.ts`: a acção é fixa, o `order_id`
 * é um UUID e a `version` é um inteiro, pelo que todos os separadores a mais
 * estão na `prova_ref`, que é o último segmento.
 */
export function textoDoReembolso(
  orderId: string,
  version: number,
  provaRef: string | null,
): string {
  return [ACCAO_DO_REEMBOLSO, orderId, String(version), provaRef ?? ""].join(
    SEPARADOR,
  );
}

/**
 * Escreve a linha de auditoria do reembolso, na transacção de quem chama.
 *
 * Corre **depois** do CAS e do registo da transição, e na mesma transacção: um
 * reembolso registado sem a linha de auditoria era um registo sem rasto, e a
 * linha sem a transição era um rasto falso. Ver a nota do `auditar` do
 * `produtos/auditoria.ts` sobre o nível de isolamento.
 */
export async function auditarReembolso(
  cliente: ClienteSql,
  ctx: Ctx,
  orderId: string,
  version: number,
  provaRef: string | null,
): Promise<void> {
  const actorType = ACTOR_AUDITADO[ctx.actor.kind];
  await cliente.query(SQL_AUDITAR_REEMBOLSO, [
    ctx.tenantId,
    actorType,
    ctx.actor.id,
    ACCAO_DO_REEMBOLSO,
    ENTIDADE_DO_REEMBOLSO,
    orderId,
    // `turn_id` nulo: o registo de um reembolso não vem de um turno de
    // conversa, pela razão escrita no `produtos/auditoria.ts`.
    null,
    textoDoReembolso(orderId, version, provaRef),
  ]);
}
