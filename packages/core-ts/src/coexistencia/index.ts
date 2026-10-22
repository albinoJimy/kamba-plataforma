/**
 * A coexistência: histórico, sincronização de 24 h, *echoes* e desligamento —
 * o KAM-017.
 *
 * O que um serviço importa daqui é o `Coexistente` e a sua `Dependencias`: é
 * ele que preenche o braço `ingestao` do `Encaminhador` que o KAM-013 deixou a
 * registar e mais nada, e é ele que o braço `gestaoDeCanal` chama para o
 * `account_update`. O resto é exportado porque os testes e os tickets a jusante
 * o consomem: o `MPS_POR_MODO` é lido pelo `limites.ts` do KAM-015, e o
 * KAM-115 vai querer os seis motivos para saber porque é que avisa o dono.
 *
 * **Três caixas ficam por marcar, e nenhuma por falta de trabalho.**
 *
 * 1. **O modo predefinido do produto** depende do relatório do `ext:KAM-100`,
 *    que não existe — não há `docs/evidencia/KAM-100.md` — e a elegibilidade de
 *    Angola continua **NÃO VERIFICADA** (risco R1). A lógica dos dois modos
 *    está cá inteira e é a mesma; o que falta é um valor por omissão, e
 *    inventá-lo era escolher pelo relatório que o havia de decidir.
 * 2. **A sincronização num número +244 real** é a mesma dependência.
 * 3. **Metade da heurística dos 10 dias** — «sem acesso ao painel» — não se
 *    mede: o painel é KAM-093 e não existe. Mede-se a outra metade, que é o
 *    *echo*.
 *
 * As três estão na secção de verificação do ticket, com a razão, e a decisão é
 * de quem escreveu os critérios.
 */

export {
  ALERTA_DE_SINCRONIZACAO_MS,
  CAMPO_DO_DESTINATARIO,
  CODIGO_SEM_HISTORICO,
  DESFECHOS_DO_ECHO,
  ESTADO_DESLIGADO,
  ESTADOS,
  ESTADOS_TERMINAIS,
  EVENTO_PARTNER_REMOVED,
  INACTIVIDADE_DO_DONO_MS,
  MOTIVOS_DE_DESLIGAMENTO,
  MPS_POR_MODO,
  mpsDoModo,
  PASSOS,
  PRAZO_DE_SINCRONIZACAO_MS,
  traduzirMotivo,
} from "./contrato.ts";
export type {
  ClienteSql,
  Coexistencia,
  Contacto,
  Conversa,
  DesfechoDoEcho,
  Emitir,
  Estado,
  ModoDoCanal,
  MotivoDeDesligamento,
  Passo,
  Relogio,
  ResultadoDaIngestao,
  ResultadoDaVarredura,
  ResultadoDoDesligamento,
  ResultadoDoEcho,
  Transitar,
} from "./contrato.ts";

export {
  CanalDesconhecidoError,
  Coexistente,
  CoexistenciaIlegivelError,
} from "./coexistencia.ts";
export type {
  CanalResolvido,
  ContactoDoSync,
  Dependencias,
  LoteDeHistorico,
} from "./coexistencia.ts";

export {
  AGREGADO_DOS_EVENTOS,
  emitirAvisoDeInactividade,
  emitirCanalActualizado,
  payloadDoAviso,
  payloadDoCanal,
  TIPO_CHANNEL_UPDATED,
  TIPO_INACTIVITY_WARNING,
  VERSAO_DOS_EVENTOS,
} from "./eventos.ts";

export {
  CORTES_DA_DURACAO,
  METRICA_DESLIGADOS,
  METRICA_DURACAO,
  METRICA_ECHOES,
  METRICA_FALHADAS,
  METRICAS_DA_COEXISTENCIA,
  MetricaDesconhecidaError,
  MetricasDaCoexistencia,
  MOTIVOS_DE_FALHA,
  SufixoInvalidoError,
} from "./metricas.ts";

export {
  SQL_ABRIR,
  SQL_ALERTAR_VENCIDAS,
  SQL_AVISAR_INACTIVOS,
  SQL_CANAL_POR_NUMERO,
  SQL_CONCLUIR,
  SQL_CONCLUIR_SEM_HISTORICO,
  SQL_DESLIGAR_CANAL,
  SQL_FALHAR_VENCIDAS,
  SQL_MARCAR_PASSO,
  SQL_MARCAR_SINCRONIZADO,
  SQL_POR_CANAL,
  SQL_REGISTAR_DESLIGAMENTO,
  SQL_REGISTAR_ECHO,
} from "./consultas.ts";
