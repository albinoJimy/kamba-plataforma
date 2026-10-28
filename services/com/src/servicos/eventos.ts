/**
 * Emissão de `booking.created` pelo outbox (KAM-047, critério 4).
 *
 * O envelope **constrói-se em SQL** (`platform.evt_emitir`), como em todos os
 * produtores deste repositório: não há construtor de envelope em TypeScript, de
 * propósito, para não haver duas fontes para a mesma forma (KAM-005, ADR-009).
 *
 * A emissão corre **na transacção de quem chama** — por isso a porta recebe o
 * cliente e não o abre. A marcação e o evento entram ou não entram juntos; é
 * isso que faz do outbox um outbox e não um segundo sistema a precisar de
 * reconciliação.
 *
 * ## O payload é o do contrato publicado, e não o do bloco
 *
 * O critério 4 escreve «payload: `booking_id`, `servico`, `inicio`». O contrato
 * `contratos/eventos/booking.created/v1.schema.json`, já fundido pelo KAM-007,
 * **exige** `booking_id`, `contact_id`, `service_id`, `inicio_at` e `fim_at`, e
 * conhece também o `resource_id` (em `properties`, não em `required`), com
 * `additionalProperties: false`. Manda o contrato: `servico` e `inicio` não são
 * nomes canónicos (o dicionário §3.3 fixa `service_id`, `inicio_at`, `fim_at`),
 * e emitir com eles produzia um envelope que o próprio gate 7 recusa. A
 * divergência fica em `docs/dividas-documentais.md`.
 *
 * ## «Sem PII» quer dizer sem telefone, e não sem contacto
 *
 * O mesmo critério diz «sem PII», e o contrato **obriga** a `contact_id`. Não é
 * contradição: `contact_id` é a referência pseudonimizada que o ADR-010 manda
 * usar precisamente para não haver telefone em evento nenhum. O que fica de fora
 * é o telefone, o nome e a morada — e o `evt_emitir` recusa um payload com
 * padrão de telefone, pelo que a regra tem quem a imponha e não só quem a
 * escreva.
 *
 * `validarPayload` corre **antes** do SQL: o `evt_emitir` não valida contra o
 * catálogo de contratos, e um payload errado entrava no outbox e só falhava no
 * consumidor, do outro lado da fila.
 */

import { validarPayload } from "@kamba/core-ts/eventos";

import {
  AGREGADO_BOOKING,
  CLASSE_PII_BOOKING_CANCELLED,
  CLASSE_PII_BOOKING_CREATED,
  FINALIDADES_BOOKING_CREATED,
  TIPO_BOOKING_CANCELLED,
  TIPO_BOOKING_CREATED,
  VERSAO_BOOKING_CANCELLED,
  VERSAO_BOOKING_CREATED,
  type ClienteSql,
  type Marcacao,
} from "./contrato.ts";
import {
  SQL_EMITIR_BOOKING_CREATED,
  type MotivoDeCancelamento,
} from "./consultas.ts";

/**
 * O payload de `booking.created` v1.
 *
 * **Seis campos**, e não cinco: os cinco que o `required` do contrato exige
 * (`booking_id`, `contact_id`, `service_id`, `inicio_at`, `fim_at`) mais o
 * `resource_id`, que o schema tem em `properties` e **não** em `required`. Vai
 * porque o consumidor do lembrete (KAM-048) precisa de saber com quem é a
 * marcação, e porque `additionalProperties: false` só proíbe o que o schema não
 * conhece. A primeira versão desta nota dizia «cinco campos, e nada mais» e
 * devolvia seis — a revisão adversarial apanhou a contradição.
 */
export function payloadDaMarcacao(marcacao: Marcacao): Record<string, string> {
  return {
    booking_id: marcacao.bookingId,
    contact_id: marcacao.contactId,
    service_id: marcacao.serviceId,
    resource_id: marcacao.resourceId,
    inicio_at: marcacao.inicioAt,
    fim_at: marcacao.fimAt,
  };
}

/**
 * Emite `booking.created` e devolve o `event_id`.
 *
 * O `agregado_id` é o `booking_id` e o `agregado_tipo` é `booking`, que é o
 * `const` do contrato: é por esse par que o `evt_agregado_seq` dá a sequência, e
 * usar o `hold_id` fazia a mesma marcação ter duas linhagens de eventos — a do
 * hold e a da confirmação.
 */
export async function emitirBookingCreated(
  cliente: ClienteSql,
  tenantId: string,
  marcacao: Marcacao,
): Promise<string> {
  const payload = payloadDaMarcacao(marcacao);
  validarPayload(TIPO_BOOKING_CREATED, VERSAO_BOOKING_CREATED, payload);
  const { rows } = await cliente.query(SQL_EMITIR_BOOKING_CREATED, [
    TIPO_BOOKING_CREATED,
    VERSAO_BOOKING_CREATED,
    tenantId,
    AGREGADO_BOOKING,
    marcacao.bookingId,
    JSON.stringify(payload),
    CLASSE_PII_BOOKING_CREATED,
    [...FINALIDADES_BOOKING_CREATED],
  ]);
  const id = rows[0]?.["event_id"];
  if (typeof id !== "string") {
    throw new Error(
      "platform.evt_emitir nao devolveu um event_id para booking.created: " +
        "a marcacao ficou escrita e o evento nao, o que e exactamente o que o " +
        "outbox existe para impedir (KAM-005)",
    );
  }
  return id;
}

/**
 * Emite `booking.cancelled` e devolve o `event_id`.
 *
 * **O critério 5 não pede evento**, e esta função existe à mesma por uma razão
 * que a revisão adversarial tornou concreta: o KAM-048 agenda o lembrete a
 * partir do `booking.created` e, sem um evento de cancelamento, continua a
 * achar que a marcação existe — e envia um *template utility* **pago** a
 * lembrar uma marcação que o cliente cancelou. O contrato v1 já está publicado
 * e o `expirar_holds` da revisão `0025` já o emite para os holds vencidos; o
 * que faltava era o caminho do cliente.
 *
 * O `motivo` vem do domínio fechado de `consultas.ts`, e não é texto livre: o
 * consumidor tem de poder distinguir «o hold venceu» de «o cliente cancelou»
 * sem comparar prosa.
 */
export async function emitirBookingCancelled(
  cliente: ClienteSql,
  tenantId: string,
  bookingId: string,
  motivo: MotivoDeCancelamento,
): Promise<string> {
  const payload = { booking_id: bookingId, motivo };
  validarPayload(TIPO_BOOKING_CANCELLED, VERSAO_BOOKING_CANCELLED, payload);
  const { rows } = await cliente.query(SQL_EMITIR_BOOKING_CREATED, [
    TIPO_BOOKING_CANCELLED,
    VERSAO_BOOKING_CANCELLED,
    tenantId,
    AGREGADO_BOOKING,
    bookingId,
    JSON.stringify(payload),
    CLASSE_PII_BOOKING_CANCELLED,
    [...FINALIDADES_BOOKING_CREATED],
  ]);
  const id = rows[0]?.["event_id"];
  if (typeof id !== "string") {
    throw new Error(
      "platform.evt_emitir nao devolveu um event_id para booking.cancelled",
    );
  }
  return id;
}
