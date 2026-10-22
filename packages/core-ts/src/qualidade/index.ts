/**
 * A qualidade do canal, o estado `restrito` e a monitorização de limites: o
 * KAM-021.
 *
 * O que um serviço importa daqui é a `GestaoDeCanal` e a sua `Dependencias` — é ela
 * que preenche o braço `gestaoDeCanal` do `Encaminhador` que o KAM-013 deixou a
 * registar e mais nada. O resto é exportado porque os testes e os tickets a
 * jusante o consomem: o `accaoDaQualidade` é a tabela do critério 2 e o
 * KAM-115 vai querer saber quando um canal foi restrito; o
 * `utilizacaoDoEscalao` é o medidor do critério 7 e alimenta o KAM-083 sem
 * recalcular.
 *
 * **Uma caixa fica vazia por decisão de segurança e não por falta de
 * trabalho.** O critério 3 quer que `tenants.estado` projecte `restrito`, e a
 * revisão `0007` retirou o `UPDATE (estado)` a `kamba_app` de propósito — «o
 * sujeito da condição não pode ser quem a retira» —, com um teste a prendê-lo.
 * Devolver o privilégio reabria a escalada que a revisão adversarial do KAM-009
 * fechou. A razão está na secção de verificação do ticket, e a decisão é de
 * quem escreveu o critério.
 */

export {
  ESTADO_ACTIVO,
  ESTADO_RESTRITO,
  EVENTOS_DE_CANAL,
  FRACCAO_DE_AVISO,
  MOTIVO_DE_QUALIDADE,
  QUALIDADES,
  TECTO_POR_ESCALAO,
  traduzirQualidade,
  type Canal,
  type ClienteSql,
  type Emitir,
  type EventoDeCanal,
  type Invalidar,
  type Qualidade,
  type Transicao,
  type Utilizacao,
} from "./contrato.ts";

export {
  SQL_CANAL,
  SQL_ESCREVER_LIMITES,
  SQL_ESCREVER_QUALIDADE,
  SQL_MARCAR_TEMPLATES,
  SQL_PAUSAR_TEMPLATE,
  SQL_REGISTAR_TRANSICAO,
  SQL_REPOR,
  SQL_RESTRINGIR,
  SQL_UNICOS_FORA_DA_JANELA,
} from "./consultas.ts";

export {
  accaoDaQualidade,
  avisaDeAmarelo,
  estadoDepois,
  utilizacaoDoEscalao,
  type Accao,
} from "./decisao.ts";

export {
  CONTADORES,
  GAUGES,
  METRICAS_DA_QUALIDADE,
  METRICA_EVENTOS,
  METRICA_QUALIDADE,
  METRICA_RESTRICOES,
  METRICA_UTILIZACAO,
  MOTIVOS,
  MetricaDesconhecidaError,
  MetricasDaQualidade,
  SufixoInvalidoError,
} from "./metricas.ts";

export { GestaoDeCanal, type Dependencias } from "./qualidade.ts";
