/**
 * O HND: a passagem a humano (KAM-019).
 *
 * O que o serviço importa daqui é a `Handoff` e as três portas que ela precisa
 * — a base, o provedor de atendimento e a fila do espelho. O resto é exportado
 * porque os testes e os tickets a jusante o consomem: o `estadoDe` é o
 * mapeamento que faltava entre os dois vocabulários, o `avaliar` é a
 * autenticação dos *callbacks* que o critério 5 pede, e o `lerAcontecimento` é
 * a fronteira que recusa os três tipos que não tratamos.
 */

export {
  ACONTECIMENTOS,
  DIRECCOES,
  ESTADOS,
  OUTCOMES,
  PROVEDORES,
  ProvedorIndisponivelError,
  SemPrivilegioError,
  type Acontecimento,
  type AberturaNoProvedor,
  type ArquivoDoProvedor,
  type ClienteDoProvedor,
  type DesfechoDoArquivo,
  type ContaCriada,
  type ProvisionadorDoProvedor,
  type ClienteSql,
  type ContaDeAtendimento,
  type Direccao,
  type EstadoDeHandoff,
  type HandoffAberto,
  type HandoffProvider,
  type HumanEvent,
  type LinhaDeHandoff,
  type MirrorMessage,
  type Outcome,
  type PedidoDeHandoff,
  type Provedor,
} from "./contrato.ts";

export {
  ESTADOS_QUE_FECHAM,
  ESTADOS_SEM_OUTCOME,
  ESTADO_POR_OUTCOME,
  concluido,
  estadoDe,
  outcomeDoProvedor,
} from "./estados.ts";

export {
  ESTADO_DE_RECUSA,
  MOTIVOS_DE_RECUSA,
  avaliar,
  segredoConfere,
  type MotivoDeRecusa,
  type Veredicto,
} from "./assinatura.ts";

export {
  ATRIBUTO_DO_HANDOFF,
  EVENTO_DO_PROVEDOR,
  identificadorDoAgente,
  lerAcontecimento,
  type Corpo,
} from "./eventos.ts";

export {
  CONTADORES,
  GAUGES,
  METRICAS_DO_HND,
  METRICA_HANDOFFS,
  METRICA_PENDENTES,
  METRICA_RECUSAS,
  MetricaDesconhecidaError,
  MetricasDoHnd,
  SufixoInvalidoError,
} from "./metricas.ts";

export {
  SQL_ABRIR_HANDOFF,
  SQL_CONTA,
  SQL_FECHAR,
  SQL_FORA_DO_SLA,
  SQL_GUARDAR_CONTA,
  SQL_HANDOFF_POR_ID,
  SQL_MARCAR_ABERTA,
  SQL_MARCAR_DEGRADADA,
  SQL_MARCAR_RESOLVER,
  SQL_THREAD_DA_PASSAGEM,
} from "./consultas.ts";

export {
  CABECALHO_DO_BOT,
  CAMINHO_DA_RETOMA,
  CorpoDaRetomaRecusadoError,
  DESFECHOS_DA_RETOMA,
  ESPERA_DA_RETOMA_MS,
  ESPERA_POR_OMISSAO_MS,
  MINIMO_DA_TENTATIVA_MS,
  ORCAMENTO_DA_RETOMA_MS,
  RetomaIndisponivelError,
  RetomaNaoAutorizadaError,
  RetomaRecusadaError,
  TECTO_DA_ESPERA_MS,
  TENTATIVAS_DA_RETOMA,
  clienteDaRetoma,
  esperaDoRetryAfter,
  tenantDoThread,
  threadDe,
  type DesfechoDaRetoma,
  type OpcoesDaRetoma,
  type PedidoDeRetoma,
} from "./retoma.ts";

export { Handoff, type Dependencias, type FilaDoEspelho } from "./provedor.ts";
export { arquivarContaDoTenant } from "./arquivo.ts";

export {
  TEMPLATE_PROPOSTO,
  responderAoCliente,
  type AvisarPainel,
  type AvisoDeJanelaFechada,
  type DesfechoDaResposta,
  type DestinoDaResposta,
} from "./resposta.ts";

export {
  ArquivoDoChatwoot,
  BASE_POR_OMISSAO,
  ClienteDoChatwoot,
  ESTADO_DA_CONTA_ARQUIVADA,
  ProvisionadorDoChatwoot,
  PAPEL_DO_UTILIZADOR,
  ESPERA_MAXIMA_MS,
  RespostaInesperadaError,
  TIPO_DE_BOT,
  TIPO_DE_INBOX,
  type Configuracao,
  type ConfiguracaoDoArquivo,
  type ConfiguracaoDoProvisionamento,
  type Transporte,
} from "./chatwoot.ts";
