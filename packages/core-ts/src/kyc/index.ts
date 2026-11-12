/**
 * KYC K1 automático (KAM-087). Ver `./contrato.ts` para o desenho e
 * `./servico.ts` para o caso de uso.
 */

export * from "./contrato.ts";
export { AntivirusClamd, AntivirusIndisponivelError, PEDACO, veredictoDe } from "./antivirus.ts";
export { CifraAesGcm } from "./cifra.ts";
export {
  FORMAS_POR_OMISSAO,
  OcrLocal,
  ROTULOS,
  camposDasLinhas,
  dataDoCalendario,
  normalizarNome,
  validarCampos,
  type Formas,
  type Validado,
} from "./extracao.ts";
export { EDITORES, detectarFormato, dhash, hamming, softwareDeEdicao, softwareDoJpeg } from "./forense.ts";
export { CasosEmMemoria, FilaEmMemoria, VerificacoesEmMemoria, type CasoEmMemoria } from "./memoria.ts";
export {
  ASSINATURA_PNG,
  FicheiroInvalidoError,
  codificarPngCinzento,
  descodificarPng,
  ferramentaDoXmp,
  type PngLido,
} from "./png.ts";
export {
  FAMILIAS,
  MOTIVOS_PUBLICOS,
  TEXTO_DO_MOTIVO,
  actividadeCoerente,
  avaliar,
  ibanValido,
  jaroWinkler,
  motivoPublico,
  similaridadeDeNomes,
  type Avaliacao,
  type DocumentoLido,
  type EntradaDasRegras,
  type MotivoPublico,
} from "./regras.ts";
export {
  CLASSE_DO_DOCUMENTO,
  DIAS_DO_TECTO_NO_STO,
  FASES_PURGAVEIS,
  FASES_QUE_RECEBEM,
  RasterizadorLocal,
  ServicoKyc,
  dataEmLuanda,
  type AuditoriaDeAcesso,
  type CasosMortos,
  type Decidido,
  type DependenciasDoKyc,
  type MotivoDaRecusa,
  type Recebido,
} from "./servico.ts";
export {
  CasosMortosSql,
  SQL_CUSTO_DO_CASO,
  SQL_DECIDIR,
  SQL_DO_CASO,
  SQL_ESQUECER,
  SQL_INSERIR,
  SQL_MORTOS_ATE,
  SQL_PHASH_NOUTRO_CASO,
  SQL_POR_SHA,
  VerificacoesSql,
  type ClienteSql,
} from "./sql.ts";
export { ARGUMENTOS, MotorTesseract, linhasDoTsv, type Executor } from "./tesseract.ts";
export {
  ALIAS_DE_VISAO,
  AMBITO_DE_ONBOARDING,
  FINALIDADE_DE_VISAO,
  GATE_QUE_RECUSA,
  INSTRUCAO,
  OcrDeVisao,
  type DecisaoDeTransferencia,
  type GateDeTransferencia,
  type OpcoesDeVisao,
  type RespostaHttp,
  type Transporte,
} from "./visao.ts";
