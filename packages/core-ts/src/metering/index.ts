/**
 * A monitorização do *free tier* e do método de pagamento: o KAM-023.
 *
 * O que um serviço importa daqui é a `Metering` e a sua `Dependencias`. O
 * resto é exportado porque os testes e os tickets a jusante o consomem — o
 * `microUsdEstimado` e o `racioDoFreeTier` alimentam o KAM-081 **sem
 * recalcular** (critério 8), o `nivelAtingido` é o flanco do critério 3, e o
 * `suspeitaDePagamento` é a heurística que o KAM-101 vai calibrar.
 *
 * **Metade deste ticket não está aqui.** Os critérios 5 e 6 pedem
 * `meta_error_codes_seen` e `motivo_restricao`, que não existem em
 * `tenant_channels` e são DDL; a revisão `0013` descende da `0012` do KAM-020 e
 * entra quando ela fundir. A detecção está entregue (`Metering.suspeita`); o
 * que falta é a marca, o evento e a persistência dos códigos.
 */

export {
  FALHAS_PARA_SUSPEITA,
  FRACCAO_DE_AVISO,
  JANELA_DE_FALHAS,
  NIVEIS,
  type ClienteSql,
  type Contagem,
  type Nivel,
  type Reconciliacao,
} from "./contrato.ts";

export {
  SQL_CONTAR,
  SQL_ESTADO,
  SQL_FALHAS_RECENTES,
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
