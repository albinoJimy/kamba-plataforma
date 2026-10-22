/**
 * `@kamba/core-ts/modos` — os modos da conversa e o silenciamento do bot
 * (KAM-018).
 *
 * Quem tem a palavra numa conversa (`bot`, `dono`, `humano`, `pausada`), quem a
 * pode passar a quem, e a verificação pré-envio que impede o assistente de
 * interromper uma pessoa.
 *
 * ```ts
 * import { MaquinaDeModos, criarGuarda } from "@kamba/core-ts/modos";
 *
 * const comTenantDaApp: ComTenant = (t, trabalho) => comTenant(bd, t, () => trabalho(bd));
 * const modos = new MaquinaDeModos({ comTenant: comTenantDaApp });
 *
 * // A porta 2 do KAM-015, que ate aqui era `null`:
 * const saida = new Saida({ ..., guarda: criarGuarda({ comTenant: comTenantDaGuarda }) });
 *
 * // A porta 3 do KAM-022, que a `0015` deixou por ligar:
 * const gate = new ConsentGate({ ..., modo: modos.portaDoConsentGate() });
 *
 * await modos.disparar({ tenantId, conversationId }, "handoff_resolvido");
 * await modos.onOptOut({ tenantId, contactId });
 * await modos.pausarPorInactividade(tenantId);   // o *job* das 24 h
 * ```
 *
 * **Duas ligações e não uma**, e vale a pena dizer porquê: o `comTenant` do
 * `tenant_guard` recusa dois usos concorrentes da mesma ligação
 * (`LigacaoEmUsoError`), e a guarda corre **dentro** de um envio que pode estar
 * a correr ao mesmo tempo que uma transição. Quem monta o processo dá à máquina
 * e à guarda ligações diferentes do mesmo papel (`kamba_app`); o *lock* da
 * conversa é de base de dados e serializa-as de qualquer maneira.
 *
 * O desenho está em `docs/modos-conversa.md`, e a tabela de transições em
 * `docs/tecnica/01` §10.2.
 */

export {
  GATILHOS,
  MODOS,
  MODO_PARA_CHANNEL_MODE,
  MODO_POR_OMISSAO,
  AGREGADO_MODE_CHANGED,
  SEM_HUMANO_MS,
  SILENCIO_DO_DONO_MS,
  TIPO_MODE_CHANGED,
  VERSAO_MODE_CHANGED,
} from "./contrato.ts";
export type {
  ClienteSql,
  ComTenant,
  EmitirModoMudado,
  EstadoDaConversa,
  Gatilho,
  Modo,
  Resposta,
  ResultadoDaMudanca,
} from "./contrato.ts";

export {
  SQL_CONTACTO_DA_CONVERSA,
  SQL_CONVERSAS_DO_CONTACTO,
  SQL_CONVERSA_PARA_MODO,
  SQL_EMITIR_MODE_CHANGED,
  SQL_MUDAR_MODO,
  SQL_PAUSAR_POR_INACTIVIDADE,
  SQL_REGISTAR_ACTIVIDADE_HUMANA,
  SQL_SUPRIMIR_ENVIO,
  SQL_TRANCAR_CONVERSA,
} from "./consultas.ts";

export {
  TABELA,
  celulasQueTransitam,
  origensDe,
  silencioExpirou,
  transitar,
} from "./transicoes.ts";
export type { Celula } from "./transicoes.ts";

export {
  ConversaDesconhecidaError,
  ConversaIlegivelError,
  GATILHOS_DE_ACTIVIDADE_HUMANA,
  MaquinaDeModos,
} from "./modos.ts";
export type { Dependencias, ResultadoDaInactividade } from "./modos.ts";

export { avaliar, criarGuarda, registoDaSupressao } from "./guarda.ts";
export type { DecisaoDaGuarda, DependenciasDaGuarda } from "./guarda.ts";

export { emitirModoMudado, payloadDoModo } from "./eventos.ts";

export {
  CONTADORES,
  METRICAS_DOS_MODOS,
  METRICA_REJEITADAS,
  METRICA_SUPRIMIDAS,
  METRICA_TRANSICOES,
  MOTIVOS_DE_SUPRESSAO,
  MetricaDesconhecidaError,
  MetricasDosModos,
  SufixoInvalidoError,
} from "./metricas.ts";
export type { Contador, MotivoDeSupressao } from "./metricas.ts";
