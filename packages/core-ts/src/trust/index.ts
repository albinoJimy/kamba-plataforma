/**
 * Trust & Safety: sinais de burla, auto-compra e escada de sanções (KAM-097).
 * Ver `./contrato.ts` para o desenho, `./regras.ts` para as regras puras e
 * `./servico.ts` para o caso de uso.
 */

export * from "./contrato.ts";
export * from "./regras.ts";
export {
  AvisoDeSancaoPorSms,
  AvisoDeSancaoSemDestinoError,
  MODELO_DO_MOTIVO,
  telefoneDoDonoPelaFila,
  type TelefoneDoDono,
} from "./avisos.ts";
export {
  CONSUMIDOR_DE_TRUST,
  MOTIVO_DE_RECLAMACAO,
  TIPOS_CONSUMIDOS,
  efeitoDeTrust,
  refDaJanela,
  sinaisDoEvento,
  varrerFotos,
  varrerNaoEntregas,
  type OpcoesDoTrust,
} from "./efeito.ts";
export {
  DESFECHOS_DA_VARREDURA,
  METRICA_SANCOES,
  METRICA_SINAIS,
  METRICA_VARREDURAS,
  MetricasDoTrust,
  VARREDURAS,
  type ContadoresDoTrust,
  type DesfechoDaVarredura,
  type Varredura,
} from "./metricas.ts";
export {
  ACTOR_DAS_VARREDURAS,
  CicloDoTrust,
  INTERVALO_DO_TRUST_POR_OMISSAO_MS,
  SQL_AUDITAR_VARREDURA,
  type OpcoesDoCicloDoTrust,
  type ResultadoDoCicloDoTrust,
} from "./lote.ts";
export { EstadoDosTenantsEmMemoria, RecusaDaBaseError, RepositorioDeTrustEmMemoria } from "./memoria.ts";
export {
  ServicoDeTrust,
  emVigor,
  propostaDoCaso,
  type DecisaoParaTrust,
  type DependenciasDoTrust,
  type EfeitosDeTrust,
  type FilaDoTrust,
} from "./servico.ts";
export {
  EstadoDosTenantsSql,
  RepositorioDeTrustSql,
  SQL_COMPRADORES_PAGOS,
  SQL_CONTACTOS_DO_DONO,
  SQL_ENCERRAMENTOS_POR_FECHAR,
  SQL_ESTADO_DO_TENANT,
  SQL_FOTOS_REPETIDAS,
  SQL_GRAVAR_SANCAO,
  SQL_GRAVAR_SINAL,
  SQL_INDEPENDENCIA,
  SQL_NAO_ENTREGUES,
  SQL_PEDIDO_E_COMPRADOR,
  SQL_PEDIDOS_MANUAIS,
  SQL_QUEIXAS,
  SQL_SANCOES_DO_TENANT_APP,
  SQL_SANCOES_DO_TENANT_LOTE,
  SQL_SINAIS_DO_TENANT,
  SQL_SINAL_POR_CHAVE,
  SQL_TENANT_E_TECTO,
  SQL_TRUST_DE_ONDE_VEIO,
  SQL_TRUST_EMITIR,
  SQL_TRUST_SUSPENSAO_E_DO_TRUST,
  SQL_TRUST_TRANSITAR,
  EVENTO_DA_TRANSICAO,
  MOTIVO_DO_RECURSO_PROVIDO,
  MOTIVO_DO_TRUST,
  TransicaoDeOutroEstadoError,
  type ModoDoRepositorio,
} from "./sql.ts";
