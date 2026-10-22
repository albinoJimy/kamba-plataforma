/**
 * O consentimento no 1.º contacto (KAM-022).
 *
 * O desenho está em `docs/consentimento.md`. O que sai daqui é o que outro
 * módulo precisa: a barreira (`ConsentGate`), a matriz e as funções puras que a
 * compõem — para quem as queira testar ou reutilizar sem base de dados —, o SQL
 * (para a *suite* do *gate* 8 correr **estas** cadeias e não cópias delas), e as
 * métricas.
 *
 * **O `prova.ts` sai inteiro de propósito.** O `evidence_hash` tem de ser
 * reprodutível por quem audita, e uma função de resumo que só existisse dentro
 * de uma classe privada era uma promessa de reprodutibilidade sem forma de a
 * cumprir.
 */

export {
  ACCOES,
  AVISOS_ANTES_DO_HUMANO,
  BOTOES,
  ESTADOS,
  FINALIDADES,
  FINALIDADE_DE_MARKETING,
  FINALIDADE_DO_AVISO,
  FINALIDADE_DO_HUMANO,
  PREFIXO_DO_AVISO,
  type Accao,
  type BotaoDoAviso,
  type ClienteSql,
  type CorpoDoAviso,
  type Decisao,
  type Dependencias,
  type DestinoDoAviso,
  type Emitir,
  type Entrada,
  type EnviarAviso,
  type EstadoDoConsentimento,
  type Finalidade,
  type MudarModo,
  type TextoVigente,
} from "./contrato.ts";

export {
  SQL_AVISOS_ENVIADOS,
  SQL_ESTADO,
  SQL_NOME_DA_LOJA,
  SQL_REGISTAR,
  SQL_TEXTO_VIGENTE,
} from "./consultas.ts";

export {
  LINHAS,
  accaoDoAviso,
  autorizaAgr,
  botaoDaLinha,
  enviaMensagem,
  estadoDoConsentimento,
  linhaDaEntrada,
  type Linha,
} from "./decisao.ts";

export { PALAVRAS_DE_PARAR, eParar, normalizar } from "./parar.ts";

export {
  MARCADOR_DA_LOJA,
  SEPARADOR,
  preencher,
  provaDeConsentimento,
  resumoDoTexto,
  type CamposDaProva,
} from "./prova.ts";

export {
  CONTADORES,
  GAUGES,
  METRICAS_DO_CONSENTIMENTO,
  METRICA_ACEITES,
  METRICA_AVISOS,
  METRICA_BARRADAS,
  METRICA_OPTOUT,
  METRICA_RACIO,
  MetricaDesconhecidaError,
  MetricasDoConsentimento,
  SufixoInvalidoError,
} from "./metricas.ts";

export { ConsentGate, type Mensagem, type Resultado } from "./consentimento.ts";
