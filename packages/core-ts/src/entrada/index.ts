/**
 * `@kamba/core-ts/entrada` — a entrada de canal (KAM-013).
 *
 * O que o GWY e o *worker* de canal partilham: a assinatura dos webhooks da
 * Meta, o vocabulário da fila e das classes de evento, e a explosão do corpo em
 * eventos. Os dois serviços importam daqui e não um do outro.
 *
 * ```ts
 * import { assinaturaValida, sha256Hex, explodir, FILA_ENTRADA } from "@kamba/core-ts/entrada";
 * ```
 *
 * Os tratadores de cada destino **não** estão aqui: a resolução de tenant é
 * KAM-014, o envio é KAM-015, a subscrição dos campos é KAM-016 e a
 * coexistência é KAM-017. Este módulo diz o que chegou e para onde vai; quem o
 * trata é de quem o escrever.
 */

export {
  CABECALHO_DA_ASSINATURA,
  PREFIXO_DA_ASSINATURA,
  RESUMO_BYTES,
  assinaturaValida,
  resumoDoCabecalho,
  sha256Hex,
} from "./assinatura.ts";

export {
  CAMPO_DAS_MENSAGENS,
  DESTINOS,
  DESTINO_POR_KIND,
  FILA_ENTRADA,
  JOB_ENTRADA,
  KINDS,
  KINDS_DE_ENTRADA,
  KINDS_DE_QUARENTENA,
  KIND_POR_CAMPO,
  MOTIVOS,
  WA_TYPES,
  destinoDe,
  waType,
} from "./contrato.ts";
export type {
  Destino,
  Kind,
  KindDeEntrada,
  KindDeQuarentena,
  Motivo,
  TrabalhoDeEntrada,
  WaType,
} from "./contrato.ts";

export {
  ARRAY_DOS_ECHOES,
  CAMPO_DO_DESTINATARIO,
  EVENT_KEY_MAXIMO,
  ID_META_MAXIMO,
  PREFIXO_DO_RESUMO,
  PROFUNDIDADE_MAXIMA,
  canonico,
  explodir,
  resumoCanonico,
} from "./explosao.ts";
export type {
  EventoDeEntrada,
  EventoEmQuarentena,
  Explosao,
  Interlocutor,
} from "./explosao.ts";

export {
  SQL_MARCAR_ENCAMINHADO,
  SQL_POR_ENCAMINHAR,
  SQL_QUARENTENA,
  SQL_REGISTAR,
} from "./consultas.ts";

export {
  EVENTOS_MAXIMOS_POR_CORPO,
  PAYLOAD_MAXIMO,
  encaminhar,
  porEmQuarentena,
  registarEvento,
  tratarCorpo,
} from "./registo.ts";
export type {
  ClienteSql,
  Desfecho,
  Encaminhador,
  Registo,
  Resultado,
} from "./registo.ts";

export {
  CONTADORES,
  DESFECHOS_DA_ENTRADA,
  GAUGES,
  METRICAS,
  METRICAS_DO_WORKER,
  METRICA_EM_QUARENTENA,
  METRICA_ENTRADAS,
  METRICA_FALHAS,
  MetricasDoWorker,
  SufixoInvalidoError,
  METRICA_ASSINATURA_FALHOU,
  METRICA_DESCARTADOS,
  METRICA_ENFILEIRAMENTO_MS,
  METRICA_PEDIDOS,
  METRICA_PROFUNDIDADE,
  MetricaDesconhecidaError,
  MetricasDaEntrada,
} from "./metricas.ts";
export type { Contador, DesfechoDaEntrada, Gauge } from "./metricas.ts";

export {
  AJUSTES_DO_TRABALHADOR,
  CONCORRENCIA,
  TrabalhoInvalidoError,
  criarTrabalhadorDeEntrada,
  lerTrabalho,
} from "./trabalhador.ts";
export type {
  OpcoesDoTrabalhadorDeEntrada,
  TrabalhadorDeEntrada,
} from "./trabalhador.ts";
