/**
 * As reservas de stock do COM: a superfície pública do módulo (KAM-045).
 *
 * Os quatro ficheiros do bloco — `{reserve,expire,scheduler,consumers}` — mais o
 * `contrato` (vocabulário e prazos) e o `consultas` (o SQL que o *gate* 8 corre
 * contra PostgreSQL).
 *
 * **Reexporta e não reimplementa.** A mesma escolha do `../orders/index.ts`: um
 * ficheiro de entrada que acrescentasse lógica era um quinto sítio onde
 * procurá-la.
 */

export {
  ATIVA,
  ESTADOS_DA_RESERVA,
  ESTADOS_TERMINAIS,
  FOLGA_MS,
  MOTIVOS_DE_LIBERTACAO,
  PROVISORIA_MS,
  TTL_EXPRESS_MS,
  TTL_MAXIMO_MS,
  TTL_MINIMO_MS,
  TTL_OMISSAO_MS,
  VIAS_DE_COBRANCA,
  fimDaValidade,
  prazoDaReserva,
  prazoProvisorio,
  ttlAceitavel,
  type Duration,
  type EstadoDaReserva,
  type LinhaAReservar,
  type MotivoDeLibertacao,
  type Reserva,
  type ViaDeCobranca,
} from "./contrato.ts";

export {
  CONSULTAS_DAS_RESERVAS,
  SQL_ACTIVAS_POR_TENANT,
  SQL_ATRASO_DA_LIBERTACAO,
  SQL_CONFIRMAR,
  SQL_CONSUMIR,
  SQL_DEVOLVER_STOCK,
  SQL_ESTENDER,
  SQL_LER_OFERTA,
  SQL_LER_RESERVAS,
  SQL_LIBERTAR,
  SQL_LIBERTAR_UMA,
  SQL_RESERVAR,
  SQL_VENCIDAS,
} from "./consultas.ts";

export {
  TABELA_DAS_RESERVAS,
  autoridadeDeStock,
  commitReservation,
  extendReservation,
  lerReservas,
  releaseReservation,
  reserveStock,
  terminal,
  type PedidoDeReserva,
  type Reservas,
} from "./reserve.ts";

export {
  LOTE_DO_VARRIMENTO,
  atrasosDaLibertacao,
  decidir,
  percentil,
  provisoria,
  varrer,
  type Desfecho,
  type Resultado,
  type Varrimento,
  type Vencida,
} from "./expire.ts";

export {
  FILA_DA_EXPIRACAO,
  FilaDeExpiracaoEmMemoria,
  INTERVALO_DO_VARRIMENTO_MS,
  JOB_DA_RESERVA,
  JOB_DO_VARRIMENTO,
  JOB_ID_DO_VARRIMENTO,
  agendarExpiracoes,
  atrasoAte,
  jobIdDaReserva,
  trabalhoDaReserva,
  type FilaDeExpiracao,
  type TrabalhoAdiado,
} from "./scheduler.ts";

export {
  CHARGE_ISSUED,
  fixarPrazo,
  prazoDoEvento,
  type ChargeIssued,
} from "./consumers.ts";
