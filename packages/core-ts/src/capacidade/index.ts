/**
 * A lista de espera do limite de onboarding da Meta (KAM-095).
 *
 * Substitui o `CapacidadeEmMemoria` do `../guia/` como `CapacityGate`: o guia
 * não muda, a capacidade é que passa a ter fila, posição e convites. Ver a
 * nota de `./contrato.ts` para o que é CONFIRMADO e o que é proposta.
 */

export {
  ESTADOS_DA_ENTRADA,
  EXPIRACOES_ATE_ABANDONO,
  FASES_ELEGIVEIS,
  LIMITE_SEM_CONFIRMACAO,
  ListaRecusadaError,
  MOTIVOS_DE_RECUSA,
  ORIGENS_DO_LIMITE,
  VALIDADE_DO_CONVITE_H,
  VALIDADE_DO_KYC_DIAS,
} from "./contrato.ts";
export type {
  AvisoDaLista,
  Campos,
  Entrada,
  EstadoDaEntrada,
  Estimativa,
  Fotografia,
  Limite,
  MotivoDeRecusa,
  OperacoesDaLista,
  OrigemDoLimite,
  Posicao,
  RepositorioDaLista,
} from "./contrato.ts";

export { ListaDeEspera, estimar, hashDoConvite } from "./lista.ts";
export type { DependenciasDaLista } from "./lista.ts";

export { AvisosDaListaEmMemoria, LIMITE_POR_OMISSAO, ListaEmMemoria } from "./memoria.ts";

export {
  DESFECHOS_DO_CONVITE,
  METRICA_CONVITES,
  METRICA_ENTRADAS,
  METRICA_ESPERA_MEDIA,
  METRICA_LIMITE_7D,
  METRICA_VAGAS_7D,
  MetricasDaLista,
} from "./metricas.ts";
export type { DesfechoDoConvite } from "./metricas.ts";

export { ListaSql } from "./sql.ts";
export type { ClienteSql, ConjuntoSql } from "./sql.ts";
