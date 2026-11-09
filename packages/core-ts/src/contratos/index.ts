/**
 * O aceite contratual versionado (KAM-090): versões, recibos de abertura,
 * aceite e prova. O gate de activação é da base (revisão `0040`), e não está
 * aqui de propósito — uma segunda leitora da mesma pergunta em TypeScript era
 * a forma de as duas divergirem.
 */

export {
  TIPOS,
  TIPOS_A_ABRIR,
  type Tipo,
  type Documento,
  type CamposDaEvidencia,
  VersaoInvalidaError,
  versaoValida,
  compararVersoes,
  canonizar,
  sha256DoConteudo,
  vigente,
  evidencia,
} from "./versoes.ts";
export {
  DOMINIO_DO_RECIBO,
  OCTETOS_DA_CHAVE,
  type Abertura,
  emitirRecibo,
  reciboValido,
} from "./recibos.ts";
export {
  OTP_ACERTOU,
  MOTIVOS,
  type Motivo,
  type VerificacaoDeOtp,
  type VerificadorDeOtp,
  type LeitorDeDocumentos,
  type LinhaDeAceite,
  type EscritorDeAceites,
  type PortasDoAceite,
  type PedidoDeAceite,
  type ResultadoDoAceite,
  aceitar,
  hashDoPrefixoDeIp,
} from "./aceite.ts";
export {
  type LinhaDaProva,
  type ProvaExportada,
  ProvaInconsistenteError,
  exportarProva,
} from "./prova.ts";
export {
  type ClienteSql,
  SQL_PUBLICADOS,
  SQL_ACEITE,
  SQL_PROVA,
  LeitorSql,
  EscritorSql,
  lerProva,
} from "./sql.ts";
