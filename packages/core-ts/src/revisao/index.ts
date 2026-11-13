/**
 * Fila de revisão por excepção para T&S/T2 (KAM-089). Ver `./contrato.ts` para
 * o desenho e `./servico.ts` para o caso de uso.
 */

export * from "./contrato.ts";
export {
  AvisoAoDonoPorVia,
  AvisoSemDestinoError,
  mensagemDoAviso,
  type CorreioDoDono,
  type EmailDoAviso,
  type MensagemDoAviso,
  type OpcoesDoAvisoAoDono,
} from "./avisos.ts";
export {
  CicloDaFila,
  EfeitosPorReaplicarEmMemoria,
  LeitorDaFilaSql,
  PASSOS_DO_CICLO,
  type EfeitosPorReaplicar,
  type LeitorDaFila,
  type OpcoesDoCiclo,
  type PassoDoCiclo,
  type ResultadoDoCiclo,
  type ServicoDoCiclo,
} from "./ciclo.ts";
export {
  CasoJaDecididoError,
  CasoNaoElegivelError,
  SCORE_DE_RISCO_ALTO,
  decisaoHumanaDeScreening,
  escritorComFila,
  filaDoGuia,
  filaDoKyc,
  prioridadeDoKyc,
} from "./entradas.ts";
export { AuditoriaEmMemoria, FilaDeRevisaoEmMemoria, OnboardingsEmMemoria } from "./memoria.ts";
export {
  METRICA_CASOS,
  METRICA_DECISOES,
  METRICA_FALSOS_APROVADOS,
  METRICA_P90,
  MetricasDaRevisao,
  type Contador,
  type LinhaDaVista,
} from "./metricas.ts";
export {
  FASES_ELEGIVEIS,
  ServicoDeRevisao,
  TIPOS_QUE_BLOQUEIAM,
  baldeDaAmostra,
  chavesDeScreening,
  mascarar,
  textoParaODono,
  type DependenciasDaRevisao,
  type PedidoDeAbertura,
  type ResultadoDaAbertura,
  type ResultadoDaDecisao,
  type ResumoDoCaso,
  type VistaDoCaso,
} from "./servico.ts";
export {
  DESVIO_DE_LUANDA_MS,
  FERIADOS_POR_OMISSAO,
  calcularSla,
  diaEmLuanda,
  diaUtil,
  inicioDoDiaEmLuanda,
  percentil,
  somarTempoUtil,
  tempoUtilEntre,
  type Feriados,
} from "./sla.ts";
export {
  AuditoriaSql,
  RevisaoSql,
  SQL_ABRIR,
  SQL_ALERTAS_DEVIDOS,
  SQL_AUDITAR,
  SQL_CONTADORES,
  SQL_CONTAR_NA_FILA,
  SQL_DECISOES,
  SQL_EM_TRIAGEM,
  SQL_MARCAR_ALERTADO,
  SQL_PAGINA,
  SQL_CASOS_DO_ONBOARDING,
  SQL_CONTAR_NA_FILA_DO_TENANT,
  SQL_REFORCAR,
  SQL_POR_CHAVE,
  SQL_POR_ID,
  SQL_REGISTAR_DECISAO,
  SQL_TRANSITAR,
  SQL_TRANSITAR_COM_SLA,
  SQL_VISTA_SLA,
  type ClienteSql,
} from "./sql.ts";
