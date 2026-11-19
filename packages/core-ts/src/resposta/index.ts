/**
 * A resposta do AGR, do lado de quem a entrega (KAM-224). Ver `./contrato.ts`.
 */

export * from "./contrato.ts";
export * from "./sql.ts";
export {
  CONSUMIDORES_DA_RESPOSTA,
  DESFECHOS_DA_RESPOSTA,
  ESTADOS_QUE_SAIRAM,
  MOTIVOS_DE_FALHA,
  ReenvioAdiadoError,
  SUFIXO_DO_REENVIO,
  chaveDoReenvio,
  efeitoDoOutbound,
  efeitoDoPainel,
  pedidoDaResposta,
  respostaParaEnviar,
  type DesfechoDaResposta,
  type EnviarResposta,
  type OpcoesDoEfeito,
} from "./efeito.ts";
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
  SEM_DESTINATARIO,
  destinatarioPelaIdentidade,
  escolherDestinatario,
  type LeitorDeEndpoints,
  type OpcoesDoDestinatario,
} from "./destinatario.ts";
