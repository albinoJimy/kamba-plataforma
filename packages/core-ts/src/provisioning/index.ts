/**
 * `@kamba/core-ts/provisioning` — a saga que provisiona um tenant aprovado
 * (KAM-091).
 *
 * ```ts
 * import { Saga, reconciliar } from "@kamba/core-ts/provisioning";
 *
 * const saga = new Saga({ armazem, sql, chaveDeLlm, comercio, handoff, ... });
 * const desfecho = await saga.correr(caso);          // oito passos, idempotente
 * // `escalada` e o estado que dispara a compensacao: ao 3.o falhanco o passo
 * // fica terminal. `aguarda` **nao** compensa — o dono ainda pode agir.
 * if (desfecho.estado === "escalada") await saga.compensar(caso, desfecho.passo ?? "");
 * ```
 *
 * O gatilho é o `tenant.approved` (ADR-009; o canon §3.5 fixa **este** nome
 * como «gatilho do provisioning»). O consumidor idempotente por `event_id` e os
 * eventos `tenant.provisioned`/`tenant.activated` são do **KAM-092**; o que
 * este módulo entrega é a máquina de estados, a compensação em ordem inversa e
 * a reconciliação.
 *
 * **O que aqui não tem implementação, com credor nomeado** — ver a nota do
 * `contrato.ts`: o canal de comércio (D3 / KAM-042, e não há serviço `medusa`
 * em compose nenhum), a `onboarding_case` (KAM-086, com DDL no bloco), a
 * `review_case` (KAM-089) e o apagar da conta de atendimento (KAM-019, cuja
 * porta não tem essa operação). Os ensaios deste módulo provam a máquina de
 * estados contra inventários em memória e **não** provam nada sobre o Chatwoot,
 * o LiteLLM ou o Medusa a correr.
 */

export {
  CLASSES_DE_DIVERGENCIA,
  ACCOES_POR_RECURSO,
  ESPERAS,
  ESPERA_DO_PASSO,
  ESTADOS_DE_PASSO,
  ETIQUETA_DA_SAGA,
  PASSOS,
  PASSOS_DE_ESPERA,
  RECURSOS,
  RECURSOS_DO_CLIENTE,
  TIPOS_DESTRUTIVOS,
  TIPOS_DE_ACCAO,
  AguardaEntradaError,
  RecursoDoClienteError,
  AccaoIncoerenteError,
  type AccaoDeCompensacao,
  type ArmazemDePassos,
  type CanalDoCliente,
  type Caso,
  type ChaveDeLlm,
  type ClasseDeDivergencia,
  type ClienteSql,
  type Divergencia,
  type Entitlements,
  type Espera,
  type EstadoDePasso,
  type InboxDeAtendimento,
  type Inventario,
  type InventarioExterno,
  type LeitorDeCasos,
  type LinhaDePasso,
  type Passo,
  type RecursoInventariado,
  type RefExterna,
  type RegistoDeCanalDeComercio,
  type PassoDeEspera,
  type RegistoDoCaso,
  type RotaDoCanal,
  type RelatorioDeReconciliacao,
  type Recurso,
  type TesteDeCanal,
  type TipoDeAccao,
} from "./contrato.ts";

export {
  accoesDoCanalDoCliente,
  executarNoCanalDoCliente,
  coerente,
  permitida,
  verificar,
} from "./compensacao.ts";

export {
  SQL_GARANTIR_TENANT,
  SQL_GUARDAR_CANAL_COMERCIO,
  SQL_GUARDAR_CHAVE_LLM,
  SQL_GUARDAR_CONTA_ATENDIMENTO,
  aliasDoTenant,
  montarPassos,
  type DefinicaoDePasso,
} from "./passos.ts";

export {
  BACKOFF_BASE_MS,
  TENTATIVAS,
  Saga,
  atrasoDaTentativa,
  codigoDoErro,
  ordemInversa,
  type Desfecho,
} from "./saga.ts";

export {
  HORAS_PARA_COMPENSAR,
  classificar,
  compensavel,
  reconciliar,
  type EsperadoDoTenant,
} from "./reconciliacao.ts";

export {
  CONTADORES,
  GAUGES,
  METRICAS,
  METRICA_COMPENSADO,
  METRICA_DURACAO,
  METRICA_ESCALADO,
  METRICA_FALHAS,
  METRICA_ORFAOS,
  METRICA_PRIMEIRA_TENTATIVA,
  Metricas,
  PASSOU,
} from "./metricas.ts";
