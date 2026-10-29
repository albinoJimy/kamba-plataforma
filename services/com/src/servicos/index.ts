/**
 * Módulo `servicos` do COM — a agenda da vertical Serviços (KAM-047).
 *
 *     contrato.ts         o vocabulário: tipos, domínios fechados, constantes
 *     consultas.ts        as cadeias SQL, confrontadas pelo gate 8
 *     slots.ts            o `slot_id` opaco e assinado do critério 2
 *     disponibilidade.ts  o corte em slots (função pura)
 *     eventos.ts          `booking.created` pelo outbox
 *     servicos.ts         as sete operações ctx-first
 *
 * A superfície é a `ServicosModule`, consumida pela TLS. O esquema é da revisão
 * `0025`; a RLS `FORCE` e a restricão de exclusão GiST vivem lá, e **é lá que a
 * sobreposição é impossível** — não aqui.
 */

export {
  AGREGADO_BOOKING,
  CHAVE_DE_LIMITE,
  CLASSE_PII_BOOKING_CREATED,
  CtxEmFaltaError,
  ERROS,
  ESTADOS,
  ESTADOS_ACTIVOS,
  FINALIDADES_BOOKING_CREATED,
  CLASSE_PII_BOOKING_CANCELLED,
  HOLDS_POR_VARRIMENTO,
  HORIZONTE_DE_DIAS,
  MAXIMO_DE_OPCOES,
  MODULO,
  PRECO_TIPOS,
  TIPO_BOOKING_CANCELLED,
  TIPO_BOOKING_CREATED,
  TTL_DO_HOLD_MS,
  VARRIMENTOS_POR_PEDIDO,
  VERSAO_BOOKING_CANCELLED,
  VERSAO_BOOKING_CREATED,
  erro,
  eUuid,
  exigirCtx,
  ok,
  type ClienteSql,
  type ComTenant,
  type Confirmacao,
  type Ctx,
  type Dependencias,
  type Erro,
  type Estado,
  type EmitirBookingCancelled,
  type EmitirBookingCreated,
  type Marcacao,
  type Opcao,
  type PrecoTipo,
  type Resultado,
  type Servico,
  type ServicosModule,
} from "./contrato.ts";

export {
  SQLSTATE_SOBREPOSICAO,
  SQLSTATE_UNICIDADE,
  SQL_CANCELAR,
  SQL_CONFIRMAR_HOLD,
  SQL_CRIAR_HOLD,
  SQL_EMITIR_BOOKING_CREATED,
  SQL_EXPIRAR_HOLDS,
  SQL_GRELHA,
  SQL_LISTAR_SERVICOS,
  SQL_MARCACAO,
  SQL_MARCACAO_DO_SLOT,
  SQL_MARCACAO_POR_HOLD,
  MOTIVOS_DE_CANCELAMENTO,
  SQL_OCUPADO,
  SQL_REMARCAR,
  SQL_SERVICO,
  SQL_SLOT_OFERECIVEL,
  SQL_TRANCAR_RECURSO,
  type MotivoDeCancelamento,
} from "./consultas.ts";

export {
  MAXIMO_DO_SLOT_ID,
  SegredoEmFaltaError,
  SlotDemasiadoLongoError,
  VERSAO_DO_SLOT,
  derivarSlotId,
  lerSlotId,
  type Slot,
} from "./slots.ts";

export {
  opcoesComSlotId,
  slotsLivres,
  type Janela,
  type Ocupacao,
} from "./disponibilidade.ts";

export {
  emitirBookingCancelled,
  emitirBookingCreated,
  payloadDaMarcacao,
} from "./eventos.ts";

export { criarServicosModule, type Opcoes } from "./servicos.ts";
