/**
 * Lembretes de marcação e *template utility* (KAM-048).
 *
 *     contrato.ts    o vocabulário: tipos, domínios fechados, constantes
 *     consultas.ts   as duas cadeias SQL próprias, confrontadas pelo gate 8
 *     consumers.ts   `booking.created` → agenda (a primeira seta do critério 1)
 *     schedule.ts    quando o lembrete dispara (funções puras, sem fila)
 *     template.ts    o corpo e os parâmetros, **só de factos da marcação**
 *     deliver.ts     os portões e o envio pelo Outbound
 *     metricas.ts    os três contadores
 *
 * O que este ticket **liga** em vez de escrever — contrato do evento, decisão de
 * janela, portão do *template*, idempotência e gate de consentimento — está
 * listado com a fonte de cada um na nota do `contrato.ts`. Vale a pena lê-la
 * antes de acrescentar aqui uma peça que já existe noutro módulo.
 */

export {
  ANTECEDENCIA_MS,
  CAMPOS_DE_FACTO,
  ETIQUETA_DA_ORDEM,
  FINALIDADE_DO_LEMBRETE,
  FUSO_DE_APRESENTACAO,
  IDIOMA_DO_LEMBRETE,
  MINIMO_PARA_ENVIO_MS,
  MOTIVOS_DE_BLOQUEIO,
  PARAMETROS_DO_LEMBRETE,
  PROVENIENCIA,
  TEMPLATE_DO_LEMBRETE,
  TIPO_BOOKING_REMINDER_DUE,
  VERSAO_BOOKING_REMINDER_DUE,
  type AvisarDono,
  type AvisoDeTemplateBloqueado,
  type BookingReminderDue,
  type CampoDeFacto,
  type ClienteSql,
  type DesfechoDoLembrete,
  type DestinoDoLembrete,
  type FactosDaMarcacao,
  type MotivoDeBloqueio,
  type PortaDeSaida,
} from "./contrato.ts";

export { PADRAO_DE_LEMBRETE, SQL_DESTINO, SQL_LEMBRETES_DO_TENANT } from "./consultas.ts";

export {
  BOOKING_CREATED,
  agendarDoBookingCreated,
  type BookingCreated,
  type Dependencias as DependenciasDoAgendamento,
} from "./consumers.ts";

export {
  ESTADO_QUE_LEMBRA,
  FILA_DOS_LEMBRETES,
  FilaDeLembretesEmMemoria,
  JOB_DO_LEMBRETE,
  MOTIVOS_DE_NAO_AGENDAR,
  agendamentoDaMarcacao,
  agendarLembrete,
  atrasoAte,
  instanteDoLembrete,
  jobIdDoLembrete,
  type Agendamento,
  type FilaDeLembretes,
  type MotivoDeNaoAgendar,
  type TrabalhoDoLembrete,
} from "./schedule.ts";

export {
  CAMPOS_LIDOS,
  CORPO_DO_TEMPLATE,
  InicioInvalidoError,
  LINGUA_DA_FORMATACAO,
  dataDeLuanda,
  horaDeLuanda,
  parametrosDoLembrete,
  provenienciaCoerente,
  textoDoLembrete,
} from "./template.ts";

export {
  RECUSAS_DE_TEMPLATE,
  chaveDoLembrete,
  entregarLembrete,
  type Dependencias,
  type LeituraDoLembrete,
} from "./deliver.ts";

export {
  CANAIS_DO_LEMBRETE,
  CONTADORES,
  DESFECHOS_DO_AGENDAMENTO,
  METRICA_AGENDADOS,
  METRICA_ENVIADOS,
  METRICA_TRAVADOS,
  MOTIVOS_TRAVADOS,
  MetricaDesconhecidaError,
  MetricasDoLembrete,
  SufixoInvalidoError,
  type CanalDoLembrete,
  type Contador,
} from "./metricas.ts";
