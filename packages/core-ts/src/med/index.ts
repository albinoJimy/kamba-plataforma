/**
 * O MED: recepção de mídia (KAM-020).
 *
 * O que o resto da plataforma vê é o `Med` e os tipos do `contrato.ts`. **Os
 * detalhes da Meta não saem daqui**: quem precisa de mídia pede `urlInterna`,
 * e o que guarda é a referência `media://{assetId}` — nunca a chave do objecto,
 * nunca o URL da Meta.
 *
 * **Este módulo não exporta nada de `pay/` nem de `com/`**, e não importa nada
 * de lá: uma imagem pode ser um comprovativo de pagamento e **nunca é prova**
 * (ADR-013, critério 8).
 */

export {
  CLASSES,
  ESTADOS,
  MOTIVOS_DE_REJEICAO,
  MidiaIndisponivelError,
  MidiaInesperadaError,
} from "./contrato.ts";
export type {
  AvisarAgr,
  Classe,
  ClienteDeMidia,
  ClienteSql,
  EstadoDeMidia,
  LinhaDeMidia,
  MidiaDescarregada,
  MidiaResolvida,
  MotivoDeRejeicao,
  OnTranscribed,
  PedidoDeMidia,
  ResultadoDeMidia,
} from "./contrato.ts";

export {
  CLASSE_POR_WA_TYPE,
  LIMITES_POR_OMISSAO,
  RESPOSTAS,
  classeDe,
  normalizar,
  recusar,
} from "./classes.ts";
export type { LimiteDaClasse } from "./classes.ts";

export {
  SQL_FORA_DA_RETENCAO,
  SQL_MARCAR_ARMAZENADO,
  SQL_MARCAR_DESFECHO,
  SQL_POR_ASSET,
  SQL_POR_ORIGEM,
  SQL_RESERVAR,
} from "./consultas.ts";

export {
  CONTADORES,
  GAUGES,
  METRICAS_DO_MED,
  METRICA_BYTES,
  METRICA_DESCARGA_MS,
  METRICA_REJEICOES,
  MetricaDesconhecidaError,
  MetricasDoMed,
  SufixoInvalidoError,
} from "./metricas.ts";

export {
  ESPERA_INICIAL_MS,
  FACTOR_DE_ESPERA,
  Med,
  PREFIXO_INTERNO,
  RETENCAO_DE_AUDIO_MS,
  TENTATIVAS,
  TTL_DA_URL_INTERNA_S,
} from "./pipeline.ts";
export type { Dependencias } from "./pipeline.ts";
