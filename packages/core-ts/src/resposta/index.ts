/**
 * A resposta do AGR, do lado de quem a entrega (KAM-224). Ver `./contrato.ts`.
 */

export * from "./contrato.ts";
export * from "./sql.ts";
export {
  CONSUMIDORES_DA_RESPOSTA,
  DESFECHOS_DA_RESPOSTA,
  efeitoDoOutbound,
  efeitoDoPainel,
  pedidoDaResposta,
  respostaParaEnviar,
  type DesfechoDaResposta,
  type EnviarResposta,
  type OpcoesDoEfeito,
} from "./efeito.ts";
export {
  SQL_CONTEXTO_DE_SESSAO,
  SQL_LIMPAR_CONTEXTO,
  envioPeloSaida,
  type LigacaoDoEnvio,
  type OpcoesDoEnvio,
} from "./envio.ts";
