/**
 * O passo guiado do Embedded Signup v4 — o KAM-093.
 *
 * O que um serviço importa daqui é o `PassoGuiado` e a sua `Dependencias`; o
 * `onboarding-web` serve-o na página `/ligar`. As portas e os duplos são
 * exportados porque as três tabelas que o bloco nomeia não existem — ver a
 * nota do `./contrato.ts` — e os adaptadores SQL vão encaixar nelas.
 */

export {
  DETALHES,
  ESTADOS_DO_GUIA,
  GuiaRecusadoError,
  ITENS_DO_PREFLIGHT,
  JANELA_DE_ONBOARDINGS_DIAS,
  LIMITE_DE_ONBOARDINGS,
  MENSAGENS_AO_DONO,
  MOTIVOS_DE_FALHA,
  MOTIVOS_QUE_PRENDEM,
  PRAZO_DE_ABANDONO_MIN,
  TIPO_DO_ITEM,
  TRANSICOES_DO_GUIA,
  VERSAO_MINIMA_DA_APP,
  transicaoDoGuiaValida,
} from "./contrato.ts";
export type {
  Atestados,
  AvisoDoGuia,
  CapacityGate,
  Detalhe,
  DetectorDePagamento,
  EstadoDoGuia,
  EstadoDoPagamento,
  EstadoGuardado,
  FilaDeRevisao,
  GateDoEs,
  GatesDoOnboarding,
  ItemAvaliado,
  ItemDoPreflight,
  LigadorDeCanal,
  MensagemAoDono,
  MotivoDeFalha,
  Preflight,
  RepositorioDoGuia,
  ResultadoDaLigacao,
  Rota,
  Screening,
  TipoDeItem,
} from "./contrato.ts";

export { PassoGuiado } from "./guia.ts";
export type {
  Conclusao,
  ConfiguracaoDoPopup,
  Dependencias,
  Finish,
  Inicio,
  SinalDeSincronizacao,
  VerificacaoDoPagamento,
} from "./guia.ts";

export {
  AvisosEmMemoria,
  CapacidadeEmMemoria,
  GatesEmMemoria,
  GuiaEmMemoria,
  RevisaoEmMemoria,
} from "./memoria.ts";

export { numeroCoincide } from "./numero.ts";
export { avaliarPreflight, lerVersao, normalizarNome, versaoPeloMenos } from "./preflight.ts";
export type { Factos } from "./preflight.ts";
export { aplicarWebhook, sinaisDoWebhook } from "./sinais.ts";
export type { Aplicacao, Sinal } from "./sinais.ts";
