/**
 * O vocabulário do CHR (KAM-014), partilhado por quem resolve e por quem
 * consome a resolução.
 *
 * Está num só ficheiro pela razão que o `entrada/contrato.ts` já escreveu: dois
 * escritores sobre o mesmo desenho, sem um nome canónico para seguir, produzem
 * dois nomes para a mesma coisa. Os nomes aqui são os do dicionário §3.13
 * (emenda 1.20).
 *
 * ## O que este módulo **não** decide
 *
 * As transições de modo são KAM-018, o consentimento é KAM-022, o envio é
 * KAM-015 e o espelho no Chatwoot é KAM-019. O que aqui está é o que o CHR
 * **devolve** e o que ele **entrega**; quem trata o que foi entregue é de quem
 * o escrever.
 */

import type { EstadoDoCanal, EstadoDoTenant } from "../ten/estados.ts";

/**
 * O mínimo de um cliente SQL de que o CHR depende.
 *
 * `rows` é **somente de leitura**, e isso não é zelo: o CHR corre sobre três
 * ligações de três papéis, e duas delas chegam com tipos diferentes — o
 * `pg.Client` (`rows: any[]`) e o `ClienteDeIdentidade` do KAM-008
 * (`rows: readonly Readonly<Record<string, unknown>>[]`, porque o módulo de
 * identidade não deixa ninguém mexer no que leu). Um `rows` mutável aqui tornava
 * o segundo incompatível com o primeiro, e o gancho de fusão — que corre com a
 * ligação da identidade — não compilava. Medido.
 */
export interface ClienteDoChr {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ readonly rows: readonly Readonly<Record<string, unknown>>[] }>;
}

/**
 * O que a resolução de canal devolve. Dicionário §3.13.
 *
 * Os oito campos do critério 1 do KAM-014, e **só** esses oito. O `persona`
 * que `docs/tecnica/01` §7.2 põe neste contexto não está aqui: depende de
 * `contacts.papel`, que o §3.2 do dicionário nomeia e nenhuma revisão criou.
 * Está em `docs/dividas-documentais.md`.
 */
export interface ChannelContext {
  readonly tenant_id: string;
  readonly channel_id: string;
  readonly vertical: string;
  readonly plano: string;
  readonly estado_tenant: EstadoDoTenant;
  readonly estado_canal: EstadoDoCanal;
  readonly channel_mode: string;
  readonly origem: string;
}

/**
 * Quanto tempo um `ChannelContext` vive em *cache*. Critério 1: 60 s.
 *
 * Não é *proposta*: o número está no critério. O que é *proposta* é o tecto de
 * entradas, abaixo.
 */
export const TTL_MS = 60_000;

/**
 * Quantos canais a *cache* guarda antes de deitar fora o mais antigo.
 *
 * *Proposta*. A ordem de grandeza é o número de canais que um processo de
 * entrada vê numa janela de 60 s, e no Piloto são dezenas (`docs/tecnica/10`).
 * O tecto existe porque a chave vem de **fora** — é o `phone_number_id` de um
 * corpo assinado — e uma *cache* sem tecto é memória ilimitada à custa de
 * outrem, a mesma razão do `PAYLOAD_MAXIMO` da `0008`. É o mesmo mecanismo que
 * o `MAXIMO_DE_ENTRADAS` do `ten/entitlements.ts`, e calibra-se em KAM-084.
 *
 * **Um `phone_number_id` desconhecido não entra na *cache***, e isso é parte do
 * tecto: senão, um atacante que consiga assinar corpos enchia-a com chaves que
 * nunca resolvem.
 */
export const MAXIMO_DE_CANAIS = 1_000;

/** A variável que diz a fase do produto. Dicionário §3.13. */
export const VARIAVEL_DA_FASE = "KAMBA_FASE";

/** O único valor que o canon define para `KAMBA_FASE`. */
export const FASE_PILOTO = "piloto";

/**
 * As verticais de atendimento, as únicas que cabem em `tenant_channels.vertical`
 * no Piloto (dicionário §3.2).
 *
 * Constantes deste módulo, nunca entrada de fora — é o espelho exacto de
 * `VERTICAIS_DO_PILOTO` em `libs/py-core/src/kamba_core/fluxo_piloto.py`, e há
 * um teste que confronta as duas listas como texto.
 *
 * **Lista de permitidas e não lista de proibidas.** O critério 5 do KAM-014 e o
 * do KAM-003 nomeiam `vertical = 'assistente'`; uma comparação por igualdade
 * com `assistente` não via `assistente_v2`. O que não se conhece é recusado.
 */
export const VERTICAIS_DO_PILOTO = ["vendedor", "servicos"] as const;

/** A origem de canal que o ADR-011 recusa em produção do Piloto. */
export const ORIGEM_DE_PLATAFORMA = "plataforma";

/** O tipo de tenant que o ADR-011 recusa em produção do Piloto. */
export const TIPO_DE_PLATAFORMA = "platform";

/** Os modos de uma conversa. É o `CHECK` de `conversations.mode`. */
export const MODOS = ["bot", "dono", "humano", "pausada"] as const;
export type Modo = (typeof MODOS)[number];

/** O modo com que uma conversa nasce. É a omissão da coluna. */
export const MODO_POR_OMISSAO: Modo = "bot";

/** A fila onde o CHR põe o *job* do AGR. Dicionário §3.13. */
export const FILA_AGR = "agr-inbound";

/** O nome do *job* dentro da fila. Um só tipo: um turno de conversa. */
export const JOB_AGR = "turno";

/** A janela de serviço, em milissegundos. 24 h (`E1` §4, CONFIRMADO). */
export const JANELA_MS = 24 * 60 * 60 * 1_000;

/**
 * O que acontece a um evento que chega ao CHR. Lista **fechada**: é etiqueta de
 * métrica, e um identificador não entra em etiqueta nenhuma
 * (`docs/seguranca/ameacas_stride.md`, OBS-I).
 *
 * `encaminhado`       a conversa está em `bot` e o *job* foi para o AGR
 * `entregue_ao_dono`  a conversa não está em `bot`, ou é um `echo`: vai ao
 *                     dono/HND (KAM-018/KAM-019) e **nunca** ao AGR
 * `em_quarentena`     o evento não se conseguiu encaminhar: 0 *jobs*, 1 linha
 *                     em `unrouted_events`, alerta. **A razão não está aqui**:
 *                     está na etiqueta `motivo` de `chr_unrouted_total`, que é
 *                     onde a quarentena a escreve (critério 2)
 * `fluxo_b_recusado`  a guarda do ADR-011 recusou o canal (critério 5)
 * `estado_recusou`    a matriz de estados do §7.2 não autoriza
 *
 * **Dois destes juntam mais de um caso, e as duas junções são deliberadas.**
 * `entregue_ao_dono` cobre um `echo` e uma mensagem numa conversa em modo
 * `dono`/`humano`: têm o **mesmo** destino, e o que um painel precisa de saber
 * é quanto tráfego não passou pelo assistente. `em_quarentena` cobre as duas
 * razões de quarentena do CHR, porque a razão pertence à métrica da quarentena
 * — repeti-la aqui era a mesma informação em duas séries, a somar mal.
 */
export const DESFECHOS = [
  "encaminhado",
  "entregue_ao_dono",
  "em_quarentena",
  "fluxo_b_recusado",
  "estado_recusou",
] as const;
export type Desfecho = (typeof DESFECHOS)[number];

/**
 * Porque é que o CHR pôs um evento na quarentena. Dicionário §3.12.
 *
 * São **dois** dos cinco valores de `unrouted_events.motivo`; os outros três
 * são do KAM-013 e dizem respeito ao corpo, não ao encaminhamento.
 *
 * `canal_desconhecido`         o `phone_number_id` não está em
 *                              `tenant_channels` — ou o evento não trouxe
 *                              nenhum. É o critério 2.
 * `mensagem_sem_identidade`    uma `message` sem `from` **e** sem
 *                              `from_user_id`. O `E1` §3 confirma que o BSUID é
 *                              obrigatório, pelo que isto não devia acontecer —
 *                              e se acontecer não há contacto a resolver. Sem
 *                              este motivo, o `resolveContact` do KAM-008
 *                              lançava `PedidoSemIdentificadorError`, o *job*
 *                              falhava e o BullMQ repetia-o durante sete dias
 *                              sobre um corpo que nunca vai melhorar — que é o
 *                              defeito que o critério 6 do KAM-013 fecha para o
 *                              JSON inválido, aqui por outro caminho.
 */
export const MOTIVOS_DO_CHR = [
  "canal_desconhecido",
  "mensagem_sem_identidade",
] as const;
export type MotivoDoChr = (typeof MOTIVOS_DO_CHR)[number];

/**
 * O *job* que o CHR entrega ao AGR. Contrato `agent_invocation` (§3.13).
 *
 * Os sete campos do critério 6 do KAM-014, mais o `thread_id` que o mesmo
 * critério fixa e o `vertical` que o contexto do KAM-025 nomeia. **Sem
 * telefone, sem BSUID e sem `display_name`** — é o critério e é o ADR-010.
 *
 * O `wamid` **está** aqui, e carrega o número do interlocutor codificado em
 * base64 (INDÍCIO, `docs/logs.md` §2.1). Está porque o critério 6 o exige pelo
 * nome, e é por isso que não sai para *log* nenhum nem para a chave da fila:
 * ver `jobIdDe`.
 */
export interface AgentInvocation {
  readonly tenant_id: string;
  readonly contact_id: string;
  readonly conversation_id: string;
  readonly channel_id: string;
  readonly wamid: string;
  readonly type: string;
  readonly modo: Modo;
  /** `{tenant_id}:{contact_id}` — dicionário §3.1. */
  readonly thread_id: string;
  readonly vertical: string;
}

/** `thread_id` de um par (tenant, contacto). Dicionário §3.1. */
export function threadIdDe(tenantId: string, contactId: string): string {
  return `${tenantId}:${contactId}`;
}
