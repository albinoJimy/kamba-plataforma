/**
 * O consumidor do PAY que abre a `refund_cases` ao ler `order.refund_requested`
 * (KAM-197).
 *
 * ## A decisão que isto executa
 *
 * O fundador decidiu a 2026-11-12, opção (b): **o PAY abre o caso de reembolso
 * ao consumir o pedido, com o papel dele, e a tabela tem um só dono.** O COM
 * emite o `order.refund_requested` (regras 3 e 4 do KAM-050, e as três arestas
 * para `reembolso_pendente`) e não escreve na `refund_cases`.
 *
 * ## Porque vive em `services/com/src/payments/`
 *
 * Não há `services/pay/`. O código do PAY vive em `@kamba/core-ts/pagamentos`
 * (a biblioteca) e os processos dele vivem aqui: o consumidor de `payment.*` do
 * KAM-055 e a composição do motor de anomalias do KAM-060. Este é mais um, e o
 * que o separa do COM não é a pasta — é a **ligação**: corre com o papel do
 * PAY, que é o único com `EXECUTE` na porta da revisão `0050`.
 *
 * ## O que este ficheiro decide, e o que deixa à base
 *
 * Decide a **forma**: o tipo, o contrato, a coerência entre o envelope e o
 * `payload`. Deixa à porta `platform.abrir_caso_de_reembolso` tudo o que é
 * barreira — o motivo contra a lista fechada, a encomenda no tenant, a moeda e
 * a repetição —, porque uma barreira só em TypeScript é uma convenção: quem
 * chamasse a porta por outro caminho passava-a.
 *
 * **Não move dinheiro e não toca no *ledger*.** A porta abre o caso sem
 * reversão (ADR-004): a PME devolve a partir da conta dela, e o caso é o
 * registo disso.
 *
 * ## A idempotência tem duas camadas, e a segunda é a da base
 *
 * O `consumir` grava o recibo em `events_consumed` na mesma transacção, pelo
 * que uma reentrega do mesmo envelope sai como `duplicado` antes de chegar
 * aqui. A porta guarda o `id` do envelope em `pedido_evento_id`, com índice
 * único: o mesmo pedido devolve o mesmo caso mesmo por um caminho que não passe
 * pelo recibo.
 */

import { validarPayload } from "@kamba/core-ts/eventos";
import type { ClienteSql, Efeito, Envelope } from "@kamba/core-ts/eventos";

/** O único tipo que este consumidor aplica. */
export const TIPO_DO_PEDIDO = "order.refund_requested";

/**
 * A chamada à porta da revisão `0050`.
 *
 * Os seis argumentos pela ordem da assinatura: tenant, encomenda, motivo,
 * valor, moeda e o `id` do envelope. O `id` do envelope é o sexto e não o
 * primeiro de propósito — é o que dá a idempotência, e trocá-lo com o
 * `order_id` (os dois são UUID) abria um caso por encomenda em vez de um por
 * pedido. O `db/tests_pagamentos/test_reembolsos_do_pay.py` corre este texto.
 */
export const SQL_ABRIR_CASO_DE_REEMBOLSO = `
  SELECT platform.abrir_caso_de_reembolso($1, $2, $3, $4, $5, $6) AS caso
`;

/** O pedido não é coerente com o envelope que o trouxe, ou não é um pedido. */
export class PedidoDeReembolsoRecusadoError extends Error {
  override readonly name = "PedidoDeReembolsoRecusadoError";

  constructor(envelope: Envelope, razao: string) {
    super(
      `o ${envelope.tipo} ${envelope.id} nao abre caso de reembolso: ${razao}`,
    );
  }
}

/**
 * O `valor_minor` do pedido, como inteiro seguro, ou **levanta**.
 *
 * O envelope chega por `JSON.parse`, pelo que o valor já é um `number`. Um
 * fraccionário, um negativo ou uma cadeia não são unidade menor de dinheiro, e
 * a porta recusava-os com uma mensagem de tipo; aqui recusa-se com a razão.
 * O zero passa: o contrato admite-o (`minimum: 0`), e quem o recusa é o
 * `refund_cases_valor_ck` da base, que é a regra.
 */
export function valorDoPedido(envelope: Envelope): number {
  const bruto = envelope.payload["valor_minor"];
  if (typeof bruto !== "number" || !Number.isSafeInteger(bruto) || bruto < 0) {
    throw new PedidoDeReembolsoRecusadoError(
      envelope,
      `valor_minor ${String(bruto)} nao e um inteiro de unidade menor`,
    );
  }
  return bruto;
}

/**
 * O efeito: abre o caso, uma vez por pedido.
 *
 * Devolve-se como `Efeito` para o `consumir` do KAM-006 o correr dentro da
 * transacção dele, depois do `SET LOCAL app.tenant_id` — é esse contexto que a
 * porta lê, porque o `DEFINER` dá privilégio e não dá isolamento.
 */
export function efeitoDeReembolso(): Efeito {
  return async function abrirCaso(
    bd: ClienteSql,
    envelope: Envelope,
  ): Promise<void> {
    if (envelope.tipo !== TIPO_DO_PEDIDO) {
      // Fail-closed. A subscrição deste consumidor é um tipo só; outro a chegar
      // aqui é configuração errada, e abrir um caso por ele era pedir um
      // reembolso que ninguém pediu.
      throw new PedidoDeReembolsoRecusadoError(envelope, "tipo inesperado");
    }
    validarPayload(envelope.tipo, envelope.versao, envelope.payload);

    const orderId = envelope.payload["order_id"];
    if (
      envelope.agregado.tipo !== "order" ||
      typeof orderId !== "string" ||
      orderId !== envelope.agregado.id
    ) {
      throw new PedidoDeReembolsoRecusadoError(
        envelope,
        `o agregado ${envelope.agregado.tipo} ${envelope.agregado.id} nao e a ` +
          `encomenda do payload (${String(orderId)})`,
      );
    }

    await bd.query(SQL_ABRIR_CASO_DE_REEMBOLSO, [
      envelope.tenant_id,
      orderId,
      String(envelope.payload["motivo"]),
      valorDoPedido(envelope),
      String(envelope.payload["currency"]),
      envelope.id,
    ]);
  };
}
