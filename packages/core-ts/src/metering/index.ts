/**
 * A monitorização do *free tier* e do método de pagamento: o KAM-023.
 *
 * O que um serviço importa daqui é a `Metering` e a sua `Dependencias`. O
 * resto é exportado porque os testes e os tickets a jusante o consomem — o
 * `microUsdEstimado` e o `racioDoFreeTier` alimentam o KAM-081 **sem
 * recalcular** (critério 8), o `nivelAtingido` é o flanco do critério 3, e o
 * `suspeitaDePagamento` é a heurística que o KAM-101 vai calibrar.
 *
 * **O ticket entregou-se em duas metades, e a segunda esperou por uma
 * revisão.** Os critérios 5 e 6 pedem `motivo_restricao` e
 * `meta_error_codes_seen`, que não existiam: são DDL, e a revisão `0013`
 * descende da `0012` do KAM-020 — as revisões de base encaixam uma na anterior
 * e vão em série. A metade de código entrou primeiro, sem esperar; a
 * `marcarRestricao` e a `levantarRestricao` entraram quando a `0012` chegou a
 * `main`.
 */

export {
  AGREGADO_CHANNEL_UPDATED,
  FALHAS_PARA_SUSPEITA,
  FRACCAO_DE_AVISO,
  JANELA_DE_FALHAS,
  MOTIVOS_DE_RESTRICAO,
  NIVEIS,
  TECTO_DE_CODIGOS,
  TIPO_CHANNEL_UPDATED,
  VERSAO_CHANNEL_UPDATED,
  type ClienteSql,
  type Contagem,
  type MotivoDeRestricao,
  type Nivel,
  type Reconciliacao,
  type Restricao,
} from "./contrato.ts";

export {
  SQL_CONTAR,
  SQL_EMITIR_CHANNEL_UPDATED,
  SQL_ESTADO,
  SQL_FALHAS_RECENTES,
  SQL_LEVANTAR_RESTRICAO,
  SQL_MARCAR_RESTRICAO,
  SQL_RECONCILIAR,
} from "./consultas.ts";

export {
  AVISO_EM,
  divergencia,
  microUsdEstimado,
  nivelAtingido,
  racioDoFreeTier,
  suspeitaDePagamento,
  type Janela,
} from "./custo.ts";

export {
  CONTADORES,
  GAUGES,
  METRICAS_DO_FREE_TIER,
  METRICA_ALERTAS,
  METRICA_ESTIMATIVA,
  METRICA_RACIO,
  METRICA_SUSPEITAS,
  MetricaDesconhecidaError,
  MetricasDoFreeTier,
  SufixoInvalidoError,
} from "./metricas.ts";

export { Metering, type Dependencias } from "./metering.ts";
