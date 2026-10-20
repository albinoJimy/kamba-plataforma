/**
 * A saída de canal: o `ChannelAdapter` do KAM-015.
 *
 * O que o serviço importa daqui é a `Saida` e as quatro portas que ela precisa.
 * O resto é exportado porque os testes e os tickets a jusante o consomem — o
 * `decidir` é a tabela do §8.2 e o KAM-018 vai querer chamá-lo, o `ingerir` é a
 * monotonia e o `microUsdDe` é o custo.
 */

export {
  CATEGORIAS,
  CATEGORIAS_DE_TEMPLATE,
  CATEGORIAS_DO_PILOTO,
  ESTADOS,
  ESTADOS_DE_TEMPLATE,
  FREE_TIER_DE_SERVICE,
  IDIOMA_BASE,
  MAXIMO_DE_BOTOES,
  MAXIMO_DE_LINHAS,
  MOTIVOS_DE_RECUSA,
  ORDEM_DOS_ESTADOS,
  QUALIDADES,
  TERMINAIS,
  WINDOW_CLOSED,
  type Categoria,
  type CategoriaDeTemplate,
  type ClienteDaMeta,
  type ClienteSql,
  type Corpo,
  type CorpoDeBotoes,
  type CorpoDeLista,
  type CorpoDeTemplate,
  type CorpoLivre,
  type Destinatario,
  type Estado,
  type EstadoDeTemplate,
  type EstadoDoFreeTier,
  type MotivoDeRecusa,
  type ObterDestinatario,
  type Pedido,
  type PreSendGuard,
  type Pricing,
  type Qualidade,
  type RespostaDaMeta,
  type Resultado,
  type Template,
} from "./contrato.ts";

export {
  EFECTIVAS_EM,
  MICRO_USD_POR_CATEGORIA,
  MICRO_USD_POR_USD,
  ZONA,
  categoriaDesconhecida,
  microUsdDe,
  paraMostrar,
} from "./tarifas.ts";

export {
  categoriaDe,
  decidir,
  formaInvalida,
  janelaAberta,
  type Decisao,
  type Janela,
} from "./decisao.ts";

export { avancar, ingerir, terminal, type FreeTier, type Ingestao, type Transicao } from "./estados.ts";

export {
  BASE_DO_BACKOFF_MS,
  Balde,
  CODIGOS_QUE_SE_REPETEM,
  Janela as JanelaDeContagem,
  Limites,
  MPS_POR_CANAL,
  MPS_POR_PAR,
  POR_MINUTO_POR_PAR,
  TENTATIVAS,
  atrasoMs,
  vaiRepetir,
} from "./limites.ts";

export {
  ANFITRIAO_DA_GRAPH,
  CODIGO_SEM_CODIGO,
  ClienteDaGraph,
  ESPERA_MAXIMA_MS,
  VERSAO_DA_GRAPH,
  corpoDaMeta,
  type Configuracao,
} from "./cliente.ts";

export {
  CONTADORES,
  GAUGES,
  METRICAS_DA_SAIDA,
  METRICA_CUSTO,
  METRICA_DURACAO,
  METRICA_ENVIADAS,
  METRICA_JANELA_FECHADA,
  METRICA_TRAVADAS,
  MetricaDesconhecidaError,
  MetricasDaSaida,
  ORIGENS_DA_TRAVAGEM,
  type OrigemDaTravagem,
  SufixoInvalidoError,
} from "./metricas.ts";

export {
  SQL_AVANCAR_ESTADO,
  SQL_BLOQUEAR_TEMPLATE,
  SQL_CUSTO_DO_TENANT,
  SQL_ENFILEIRAR,
  SQL_ESTADO_DO_TEMPLATE,
  SQL_JANELA,
  SQL_MARCAR_ENVIADA,
  SQL_MARCAR_FALHADA,
  SQL_POR_CHAVE,
  SQL_POR_WAMID,
  SQL_TEMPLATE,
} from "./consultas.ts";

export { Saida, SemGuardaError, VARIAVEL_DO_AMBIENTE, type Dependencias } from "./adapter.ts";
