/**
 * `@kamba/core-ts/chr` — o ChannelResolver (KAM-014).
 *
 * `phone_number_id` → tenant, canal, contacto e modo da conversa. É o único
 * sítio onde o `tenant_id` nasce para o estado do grafo (`docs/tecnica/01`
 * §7.2): tudo o que vem depois recebe-o do `ChannelContext` e nada o produz de
 * outra forma.
 *
 * ```ts
 * import { Chr, ResolvedorDeCanal, verificarArranque } from "@kamba/core-ts/chr";
 *
 * await verificarArranque(resolver, process.env);      // ADR-011, antes de aceitar trabalho
 * const resolvedor = new ResolvedorDeCanal(resolver);  // ligacao de kamba_resolver
 * const chr = new Chr({ resolvedor, app, contacto, entrega, quarentena, metricas, comTenant });
 * const resultado = await chr.tratar(evento);
 * ```
 *
 * As três ligações são de três papéis diferentes (`kamba_resolver`,
 * `kamba_identity`, `kamba_app`) e nenhuma faz o trabalho de outra. O desenho
 * está em `docs/chr.md`.
 */

export { CanalIlegivelError, ResolvedorDeCanal, canalDaLinha } from "./canal.ts";
export type { CanalResolvido, LeituraDoCanal } from "./canal.ts";

export { Chr } from "./chr.ts";
export type {
  ComTenant,
  EntregaDoChr,
  Quarentena,
  Registo,
  ResolucaoDeContacto,
  ResultadoDoChr,
} from "./chr.ts";

export {
  SQL_ABRIR_CONVERSA,
  SQL_CANAL,
  SQL_CONVERSAS_A_FUNDIR,
  SQL_DOBRAR_CONVERSA,
  SQL_GUARDA_FLUXO_B,
  SQL_REPONTAR_CONVERSA,
  SQL_VISIBILIDADE,
} from "./consultas.ts";

export {
  DESFECHOS,
  FASE_PILOTO,
  FILA_AGR,
  JANELA_MS,
  JOB_AGR,
  MAXIMO_DE_CANAIS,
  MODOS,
  MODO_POR_OMISSAO,
  MOTIVOS_DO_CHR,
  ORIGEM_DE_PLATAFORMA,
  TIPO_DE_PLATAFORMA,
  TTL_MS,
  VARIAVEL_DA_FASE,
  VERTICAIS_DO_PILOTO,
  threadIdDe,
} from "./contrato.ts";
export type {
  AgentInvocation,
  ChannelContext,
  ClienteDoChr,
  Desfecho,
  Modo,
  MotivoDoChr,
} from "./contrato.ts";

export {
  ConversaIlegivelError,
  abrirConversa,
  repontarConversas,
} from "./conversas.ts";
export type { Conversa, ResultadoDaFusao } from "./conversas.ts";

export {
  FaseNaoDefinidaError,
  FluxoBNoPilotoError,
  GuardaCegaError,
  exigirFaseDoPiloto,
  recusaDoFluxoB,
  verificarArranque,
} from "./fluxo_b.ts";
export type { ContagemDoFluxoB } from "./fluxo_b.ts";

export {
  AGREGADO_CONTACT_MERGED,
  SQL_EMITIR_CONTACT_MERGED,
  TIPO_CONTACT_MERGED,
  VERSAO_CONTACT_MERGED,
  emitirContactMerged,
  payloadDaFusao,
} from "./eventos.ts";
export type { EventoDeFusao } from "./eventos.ts";

export { InvocacaoIncompletaError, jobIdDe, montarInvocacao } from "./invocacao.ts";

// A fila do AGR **nao** se re-exporta aqui: importa o `bullmq`, e quem so
// precisa da decisao (os testes unitarios, a suite de isolamento) nao deve
// arrastar um cliente de Redis. E o precedente do `./eventos/filas_bullmq`, que
// tem subpath proprio pela mesma razao. Importa-se por
// `@kamba/core-ts/chr/fila`.

export {
  CONTADORES,
  GAUGES,
  METRICAS_DO_CHR,
  METRICA_ACERTOS,
  METRICA_DURACAO,
  METRICA_EM_QUARENTENA,
  METRICA_RESOLUCOES,
  MetricaDesconhecidaError,
  MetricasDoChr,
  SufixoInvalidoError,
} from "./metricas.ts";
export type { Contador, Gauge } from "./metricas.ts";
