/**
 * A resposta do AGR, do lado de quem a entrega (KAM-224). Ver `./contrato.ts`.
 */

export * from "./contrato.ts";
export * from "./sql.ts";
export {
  CONSUMIDORES_DA_RESPOSTA,
  DESFECHOS_DA_RESPOSTA,
  ESTADOS_QUE_SAIRAM,
  CODIGOS_AMBIGUOS,
  ESPERA_DO_REENVIO_S,
  MOTIVOS_DE_FALHA,
  ArteSemLeitorError,
  ReenvioAdiadoError,
  SUFIXO_DA_IMAGEM,
  SUFIXO_DO_REENVIO,
  chaveDaImagem,
  chaveDoReenvio,
  decidirEnvio,
  eAmbiguo,
  efeitoDoOutbound,
  efeitoDoPainel,
  pedidoDaImagem,
  pedidoDaResposta,
  respostaParaEnviar,
  type DesfechoDaResposta,
  type EnviarResposta,
  type EstadoDoEnvio,
  type OpcoesDoEfeito,
} from "./efeito.ts";
export {
  ArteRecusadaError,
  CLASSE_DA_ARTE,
  MOTIVOS_DA_ARTE_RECUSADA,
  arteDoSto,
  chaveDaArte,
  exigirJpeg,
  type LerArte,
  type MotivoDaArteRecusada,
} from "./arte.ts";
export {
  comTenantPorInstrucao,
  envioPeloSaida,
  type LigacaoDoEnvio,
  type OpcoesDoEnvio,
} from "./envio.ts";
export {
  CanalSemCredencialError,
  MOTIVOS_SEM_CREDENCIAL,
  SQL_TOKEN_REF_DO_CANAL,
  clienteDaGraphPorCanal,
  type CanalDoEnvio,
  type ClienteDoCanal,
  type CofreDeLeitura,
  type MotivoSemCredencial,
  type OpcoesDaCredencial,
} from "./credencial.ts";
export {
  FINALIDADE_DA_RESPOSTA,
  SEM_DESTINATARIO,
  destinatarioPelaIdentidade,
  escolherDestinatario,
  type LeitorDeEndpoints,
  type OpcoesDoDestinatario,
} from "./destinatario.ts";
