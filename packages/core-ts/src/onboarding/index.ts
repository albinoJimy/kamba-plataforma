/**
 * `@kamba/core-ts/onboarding` — o lado servidor do Embedded Signup v4 (KAM-016).
 *
 * ```ts
 * import { GraphHttp, Onboarding, versaoDaGraph } from "@kamba/core-ts/onboarding";
 *
 * const servico = new Onboarding({
 *   sql: ligacaoDaTransaccao,
 *   graph: new GraphHttp({ base, versao: versaoDaGraph(), appId, appSecret }),
 *   cofre,
 *   vertical: "vendedor",
 * });
 *
 * const { tentativa, novo } = await servico.ligar(resultadoDoEs);
 * ```
 *
 * Só v4: ver o `docstring` do `contrato.ts`. O orquestrador da saga é KAM-091; o
 * que este módulo entrega são passos idempotentes e compensáveis.
 */

export {
  CAMPOS_DE_WEBHOOK,
  DIGITOS_DO_PIN,
  EVENTO_FINAL_DE_COEXISTENCIA,
  EsNaoEV4Error,
  FASES,
  FEATURE_TYPE_DE_COEXISTENCIA,
  JANELA_DE_ONBOARDINGS_DIAS,
  LIMITE_DE_ONBOARDINGS,
  LimiteDeOnboardingsError,
  MODOS,
  NumeroJaUsadoError,
  PRAZO_DE_ABANDONO_MIN,
  RECURSOS,
  SESSION_INFO_VERSION,
  SubscricaoIncompletaError,
  TRANSICOES,
  TransicaoInvalidaError,
  VARIAVEL_DA_VERSAO_DA_GRAPH,
  VERSAO_DA_GRAPH_POR_OMISSAO,
  VersaoDaGraphInvalidaError,
  transicaoValida,
  versaoDaGraph,
} from "./contrato.ts";
export type {
  CampoDeWebhook,
  ClienteSql,
  Cofre,
  Fase,
  Graph,
  Modo,
  Recurso,
  RecursoCriado,
  ResultadoDoEs,
  SessionInfo,
  Tentativa,
} from "./contrato.ts";

export { FAMILIA_DO_PIN, FAMILIA_DO_TOKEN, REF_DA_KEK } from "./segredos.ts";

export {
  MAXIMO_DE_TEXTO,
  MAXIMO_DO_KID,
  OCTETOS_DE_CHAVE,
  OCTETOS_DE_ETIQUETA,
  OCTETOS_DE_IV,
  TokenCifradoInvalidoError,
  VERSAO_DO_FORMATO,
  cifrarToken,
  contextoDaCifra,
  decifrarToken,
  dekDoTenant,
  kidDoCriptograma,
} from "./cifra.ts";

export {
  CAMINHO_DA_TROCA,
  GraphHttp,
  GraphRecusouError,
  caminhoDasSubscricoes,
  compararCampos,
} from "./graph.ts";
export type { Buscar, GraphHttpOpcoes } from "./graph.ts";

export {
  CONTADORES,
  GAUGES,
  METRICA_COMPENSADO,
  METRICA_FASE,
  METRICA_JANELA,
  METRICA_RECUSADO,
  METRICAS,
  MOTIVOS_DE_RECUSA,
  Metricas,
} from "./metricas.ts";
export type { Contador, Gauge, MotivoDeRecusa } from "./metricas.ts";

export { Onboarding, modoDoSessionInfo, resumoDoCode } from "./onboarding.ts";
export type { Dependencias, Resultado } from "./onboarding.ts";

export {
  SQL_ABANDONAR,
  SQL_ABRIR,
  SQL_APAGAR_CANAL,
  SQL_CONTAR_JANELA,
  SQL_CRIAR_CANAL,
  SQL_FASE,
  SQL_GUARDAR_PIN,
  SQL_LARGAR_O_PONTO,
  SQL_LIGAR_CANAL,
  SQL_LIMPAR_RECURSOS,
  SQL_PONTO_DE_SALVAGUARDA,
  SQL_RECURSOS,
  SQL_REGISTAR_RECURSO,
  SQL_REGISTAR_RECUSA,
  SQL_SOLTAR_CANAL,
  SQL_TENTATIVA,
  SQL_TRANSITAR,
  SQL_VOLTAR_AO_PONTO,
} from "./consultas.ts";
