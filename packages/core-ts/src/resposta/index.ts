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
