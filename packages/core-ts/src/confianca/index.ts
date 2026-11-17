/**
 * Confiança gradual: tectos de valor por histórico (KAM-096).
 *
 * Os níveis 0/1/2 de cada tenant, o tecto por pedido de cada um, a
 * elegibilidade dos pedidos que fazem subir, as descidas automáticas e a
 * guarda que o caminho de cobrança chama. Os valores são todos *proposta* e
 * vêm da configuração versionada (`./config.ts`). A barreira na base é o
 * *trigger* `payment_charges_dentro_do_tecto` (revisão da confiança gradual).
 */

export {
  CONFIGURACAO_DA_CONFIANCA,
  ConfiguracaoInvalidaError,
  NIVEIS_DE_CONFIANCA,
  ORIGENS_DO_VALOR,
  tabelaDeLimites,
  validarConfiguracao,
} from "./config.ts";
export type {
  ConfiguracaoDaConfianca,
  ConfiguracaoDoNivel,
  LinhaDeLimite,
  NivelDeConfianca,
  OrigemDoValor,
  PatamaresDeHistorico,
  ValorConfigurado,
} from "./config.ts";

export {
  MOTIVOS_DE_EXCLUSAO,
  avaliarPedido,
  contar,
  cumpreSubida,
  diaEmLuanda,
  fimDaJanelaAntiFraude,
  inicioDaLeitura,
} from "./elegibilidade.ts";
export type { Avaliacao, Contagem, MotivoDeExclusao, PedidoCandidato } from "./elegibilidade.ts";

export {
  MOTIVOS_DO_NIVEL,
  ServicoDeConfianca,
  actorDoSistema,
  decidirNivel,
  marcoDaElegibilidade,
} from "./niveis.ts";
export type {
  Decisao,
  DependenciasDaConfianca,
  FactosDoTenant,
  LeitorDeIndependencia,
  LeitorDeRestricoes,
  MotivoDoNivel,
  NivelGravado,
  PedidoLido,
  RepositorioDeConfianca,
  ResultadoDoRecalculo,
} from "./niveis.ts";

export {
  ForaDoTectoDeConfiancaError,
  GuardaDeConfianca,
  MENSAGEM_ACIMA_DO_TECTO,
  MOTIVOS_FORA_DO_TECTO,
  tectoEfectivoManual,
} from "./guard.ts";
export type { GuardaDoTecto, LeitorDoTecto, MotivoForaDoTecto } from "./guard.ts";

export {
  CADEIAS_DA_CONFIANCA,
  LeitorDoTectoSql,
  RepositorioDeConfiancaSql,
  SQL_DEFINIR_NIVEL,
  SQL_FACTOS_NEGATIVOS,
  SQL_K1_COMPLETO,
  SQL_NIVEL_DO_TENANT,
  SQL_PEDIDOS_ENTREGUES,
  SQL_TECTO_DO_TENANT,
  SQL_TRANCAR,
} from "./sql.ts";
export type { ClienteSql } from "./sql.ts";
