/**
 * Os cinco eventos de encomenda, pelo outbox (critério 8).
 *
 * O envelope **constrói-se em SQL** (`platform.evt_emitir`), como em todos os
 * produtores deste repositório: não há construtor de envelope em TypeScript, de
 * propósito, para não haver duas fontes para a mesma forma (KAM-005, ADR-009).
 * A emissão corre **na transacção de quem chama** — a transição e o evento
 * entram ou não entram juntos, que é o que faz do outbox um outbox e não um
 * segundo sistema a precisar de reconciliação.
 *
 * `validarPayload` corre **antes** do SQL: o `evt_emitir` não valida contra o
 * catálogo de contratos (aceita qualquer `p_tipo`, incluindo um que não exista),
 * e um payload errado entrava no outbox e só falhava no consumidor, do outro
 * lado da fila.
 *
 * ## Nenhum payload leva PII, e o contrato impõe-o
 *
 * Os cinco contratos têm `additionalProperties: false`, pelo que o conjunto de
 * campos é fechado por máquina e não por revisão. O `order.created` leva
 * `contact_id` — que é um identificador pseudonimizado e **não** um telefone
 * (ADR-010; o telefone vive cifrado em `contact_endpoints`) —, e os cinco
 * exemplos publicados declaram `classe_pii: "P0"`. Nenhum leva nome, morada,
 * texto de mensagem ou `msisdn`: os sete nomes que o *lint* do §7.3 proíbe não
 * aparecem em contrato nenhum.
 *
 * ## O `lines_snapshot` **projecta-se** e não se despeja
 *
 * O `payload.linhas` do `order.created` fecha cada item em `{sku, qty,
 * preco_minor}` com `additionalProperties: false`. O `lines_snapshot` da coluna
 * tem mais — `nome`, `preco_tipo`, `origem_preco` (§5.4) —, e despejá-lo tal e
 * qual era um envelope recusado pelo `validarPayload`. Projecta-se, e o `nome`
 * fica de fora também por uma segunda razão: é texto que o dono escreveu, e um
 * evento não é sítio para texto livre.
 */

import { validarPayload } from "@kamba/core-ts/eventos";

import {
  AGREGADO_ORDER,
  CLASSE_PII_ENCOMENDA,
  FINALIDADES_ENCOMENDA,
  TIPO_CANCELLED,
  TIPO_CREATED,
  TIPO_DELIVERED,
  TIPO_EXPIRED,
  TIPO_PAID,
  VERSAO_CANCELLED,
  VERSAO_CREATED,
  VERSAO_DELIVERED,
  VERSAO_EXPIRED,
  VERSAO_PAID,
  type ClienteSql,
  type LinhaDaEncomenda,
} from "./contrato.ts";
import { SQL_EMITIR } from "./consultas.ts";

/** O que se emite, já pronto para o `evt_emitir`. */
interface Emissao {
  readonly tipo: string;
  readonly versao: number;
  readonly orderId: string;
  readonly payload: Readonly<Record<string, unknown>>;
}

/**
 * Um `bigint` como `number`, ou lança.
 *
 * A mesma função do `produtos/eventos.ts`, e pela mesma razão: o
 * `JSON.stringify` **lança** `TypeError` sobre um `bigint` e os contratos
 * declaram os campos de dinheiro `integer`. A conversão é segura porque o
 * `Number.MAX_SAFE_INTEGER` são ~90 mil bilhões de kwanzas — mas «é seguro na
 * prática» não é uma propriedade, pelo que se verifica.
 */
function emInteiroSeguro(valor: bigint, onde: string): number {
  if (valor > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new RangeError(
      `${onde} acima de Number.MAX_SAFE_INTEGER (${valor}): o contrato do ` +
        "evento declara o campo `integer` e o JSON.stringify lanca sobre um " +
        "bigint, pelo que o payload tem de o converter — e a conversao perdia " +
        "precisao em silencio acima deste tecto (KAM-044)",
    );
  }
  return Number(valor);
}

/** As linhas do `lines_snapshot` projectadas para o payload. Ver a nota acima. */
export function linhasDoPayload(
  linhas: readonly LinhaDaEncomenda[],
): readonly Record<string, unknown>[] {
  return linhas.map((linha) => ({
    sku: linha.sku,
    qty: linha.qty,
    preco_minor: emInteiroSeguro(linha.precoMinor, `preco_minor de ${linha.sku}`),
  }));
}

/** O payload de `order.created`. */
export function payloadDeCriada(
  orderId: string,
  contactId: string,
  numeroPublico: string,
  origem: string,
  totalMinor: bigint,
  currency: string,
  entregaModo: string,
  linhas: readonly LinhaDaEncomenda[],
  expiraAt: string | null,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    order_id: orderId,
    contact_id: contactId,
    numero_publico: numeroPublico,
    origem,
    total_minor: emInteiroSeguro(totalMinor, `total_minor de ${orderId}`),
    currency,
    entrega_modo: entregaModo,
    linhas: linhasDoPayload(linhas),
  };
  // **Ausente e não nulo** quando a encomenda ainda não tem reserva: o contrato
  // tem `expira_at` em `properties` e não em `required`, e um `null` afirmava um
  // instante cujo valor é nulo em vez de não haver instante. É a mesma distinção
  // que o `preco_minor` do `catalog.price_changed` faz no KAM-043.
  if (expiraAt !== null) payload["expira_at"] = expiraAt;
  return payload;
}

/**
 * O payload de `order.paid`.
 *
 * O campo é `valor_minor` e **não** `total_minor`, que é o nome do
 * `order.created`: é o contrato publicado que o diz, e os dois nomes estão no
 * dicionário §3.5. Escrever `total_minor` aqui era um envelope recusado.
 */
export function payloadDePaga(
  orderId: string,
  valorMinor: bigint,
  currency: string,
  pagaVia: string,
): Record<string, unknown> {
  return {
    order_id: orderId,
    valor_minor: emInteiroSeguro(valorMinor, `valor_minor de ${orderId}`),
    currency,
    paga_via: pagaVia,
  };
}

/**
 * O payload de `order.expired`.
 *
 * O `expira_at` é **obrigatório** no contrato, e é por isso que expirar uma
 * encomenda sem `expira_at` na linha é um erro deste módulo e não um envelope
 * inválido descoberto no consumidor.
 */
export function payloadDeExpirada(
  orderId: string,
  expiraAt: string,
): Record<string, unknown> {
  return { order_id: orderId, expira_at: expiraAt };
}

/**
 * O payload de `order.cancelled`.
 *
 * O campo é `motivo` e a coluna do registo chama-se `causa`: é a tradução que o
 * dicionário §3.5 fixa por escrito («o `motivo` é o nome de evento para a razão
 * de uma transição: a coluna do registo de estados chama-lhe causa, e em evento
 * esse nome colidia com `causa_id`, que é outra coisa»).
 */
export function payloadDeCancelada(
  orderId: string,
  motivo: string,
): Record<string, unknown> {
  return { order_id: orderId, motivo };
}

/** O payload de `order.delivered`. */
export function payloadDeEntregue(
  orderId: string,
  entregaConfirmadaPor: string,
): Record<string, unknown> {
  return { order_id: orderId, entrega_confirmada_por: entregaConfirmadaPor };
}

/**
 * Emite um evento e devolve o `event_id`.
 *
 * O `agregado.tipo` é `order` nos cinco (é `const` em todos os contratos) e o
 * `agregado.id` é o `order_id`: é por esse par que o `evt_agregado_seq` dá a
 * sequência, pelo que a linhagem de uma encomenda é a dela e de mais nenhuma.
 */
export async function emitir(
  cliente: ClienteSql,
  tenantId: string,
  emissao: Emissao,
): Promise<string> {
  validarPayload(emissao.tipo, emissao.versao, emissao.payload);
  const { rows } = await cliente.query(SQL_EMITIR, [
    emissao.tipo,
    emissao.versao,
    tenantId,
    AGREGADO_ORDER,
    emissao.orderId,
    JSON.stringify(emissao.payload),
    CLASSE_PII_ENCOMENDA,
    [...FINALIDADES_ENCOMENDA],
  ]);
  const id = rows[0]?.["event_id"];
  if (typeof id !== "string") {
    throw new Error(
      `platform.evt_emitir nao devolveu um event_id para ${emissao.tipo}: a ` +
        "transicao ficou escrita e o evento nao, o que e exactamente o que o " +
        "outbox existe para impedir (KAM-044, criterio 2)",
    );
  }
  return id;
}

/** O tipo e a versão de cada um dos cinco, para quem emite. */
export const EMISSOES = {
  criada: { tipo: TIPO_CREATED, versao: VERSAO_CREATED },
  paga: { tipo: TIPO_PAID, versao: VERSAO_PAID },
  expirada: { tipo: TIPO_EXPIRED, versao: VERSAO_EXPIRED },
  cancelada: { tipo: TIPO_CANCELLED, versao: VERSAO_CANCELLED },
  entregue: { tipo: TIPO_DELIVERED, versao: VERSAO_DELIVERED },
} as const;
