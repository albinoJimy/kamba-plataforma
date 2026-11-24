/**
 * A resposta do AGR, do lado de quem a entrega (KAM-224).
 *
 * O AGR grava a resposta de um turno na `platform.agent_replies` e emite o
 * `agent.replied` na mesma transacção (`services/agr/src/kamba_agr/saida.py`).
 * Este módulo é o outro lado: dois consumidores do mesmo tipo, um por canal.
 *
 *     outbound   worker-canal          canal whatsapp   o `Saida` do KAM-015
 *     painel     onboarding-lote       canal painel     a linha fica entregue
 *
 * **O evento não leva o texto.** O lint de PII do *gate* 7 recusa um campo
 * `texto` num *payload* (`docs/tecnica/06` §7.1), e uma resposta a um cliente
 * pode levar o nome dele. O consumidor lê a linha pelo `reply_id`, **sob a RLS do
 * tenant do envelope**: um evento cujo `reply_id` é de outro tenant não encontra
 * linha nenhuma, e não chega a enviar.
 */

/** O tipo do evento. Dicionário §3.5 e §3.80. */
export const TIPO_DA_RESPOSTA = "agent.replied";

/** Os dois consumidores. São o `events_consumed.consumer` e o prefixo das filas. */
export const CONSUMIDOR_DO_OUTBOUND = "outbound";
export const CONSUMIDOR_DO_PAINEL = "painel";

/** Os tipos que os dois subscrevem (`registry/outbound.yaml`, `registry/painel.yaml`). */
export const TIPOS_CONSUMIDOS = [TIPO_DA_RESPOSTA] as const;

/**
 * Os dois canais. Iguais ao `CANAIS` do `saida.py` do AGR e da revisão
 * `*_resposta_do_agr.py`.
 */
export const CANAIS_DA_RESPOSTA = ["whatsapp", "painel"] as const;
export type CanalDaResposta = (typeof CANAIS_DA_RESPOSTA)[number];

/** O *payload* do `agent.replied`, v1 e v2. */
export interface PayloadDaResposta {
  readonly replyId: string;
  readonly threadId: string;
  readonly conversationId: string;
  readonly contactId: string;
  readonly canal: CanalDaResposta;
}

/** Um botão como o `Corpo` do Outbound o quer. O título resolve-o o AGR. */
export interface BotaoDaResposta {
  readonly id: string;
  readonly titulo: string;
}

/**
 * O *template* de uma resposta (KAM-221, revisão `0076`): o nome e os
 * **valores** dos parâmetros, pela ordem, já resolvidos pelo AGR.
 */
export interface TemplateDaResposta {
  readonly nome: string;
  readonly parametros: readonly string[];
}

/** A linha da `agent_replies` que o consumidor do WhatsApp lê. */
export interface RespostaParaEnviar {
  readonly replyId: string;
  readonly chave: string;
  readonly contactId: string;
  readonly conversationId: string;
  readonly channelId: string;
  readonly phoneNumberId: string;
  readonly texto: string;
  readonly botoes: readonly BotaoDaResposta[];
  /** `null` numa resposta de texto livre. Quem escolhe é o AGR, nunca o consumidor. */
  readonly template: TemplateDaResposta | null;
  /**
   * A chave do STO da imagem que sai antes do texto (KAM-246), ou `null`. É a
   * chave e nunca um URL; o consumidor confere-a antes de a ler (`arte.ts`).
   */
  readonly mediaRef: string | null;
  readonly turnoIniciadoEm: Date | null;
  readonly entregueEm: Date | null;
}

/**
 * O evento não tem a forma do contrato. Não há tentativa que o resolva.
 *
 * O consumo do KAM-006 só manda direito à DLQ o `ForaDeOrdem` e o
 * `EstadoIncompativel`, que são de máquina de estados; um erro destes recua pela
 * escada e, esgotadas as seis tentativas, abre a DLQ com o nome dele. **O evento
 * não se aplica em nenhuma** — que é o que importa: um canal desconhecido não
 * cai no WhatsApp por omissão.
 */
export class RespostaInvalidaError extends Error {
  constructor(motivo: string) {
    super(`agent.replied invalido: ${motivo}`);
    this.name = "RespostaInvalidaError";
  }
}

/**
 * O `reply_id` do evento não tem linha **neste tenant**.
 *
 * Acontece com um evento forjado ou de outro tenant (a RLS não deixa ver a
 * linha alheia), ou com a linha e o evento desencontrados. Recua e vai à DLQ: o
 * que não acontece é enviar sem a linha.
 */
export class RespostaInexistenteError extends Error {
  constructor() {
    super("agent.replied sem linha na agent_replies deste tenant");
    this.name = "RespostaInexistenteError";
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function uuid(payload: Record<string, unknown>, campo: string): string {
  const valor = payload[campo];
  if (typeof valor !== "string" || !UUID.test(valor)) {
    throw new RespostaInvalidaError(`${campo} nao e um uuid`);
  }
  return valor;
}

/**
 * Lê o *payload* do `agent.replied`, com o tenant do **envelope**.
 *
 * O `thread_id` tem de ser `{tenant_id}:{contact_id}` do envelope e do próprio
 * *payload*: um `thread_id` de outro tenant num evento deste é um evento que não
 * se aplica.
 */
export function lerResposta(tenantId: string, bruto: unknown): PayloadDaResposta {
  if (bruto === null || typeof bruto !== "object" || Array.isArray(bruto)) {
    throw new RespostaInvalidaError("payload nao e um objecto");
  }
  const payload = bruto as Record<string, unknown>;
  const canal = payload["canal"];
  if (!(CANAIS_DA_RESPOSTA as readonly unknown[]).includes(canal)) {
    throw new RespostaInvalidaError("canal desconhecido");
  }
  const replyId = uuid(payload, "reply_id");
  const conversationId = uuid(payload, "conversation_id");
  const contactId = uuid(payload, "contact_id");
  const threadId = payload["thread_id"];
  if (threadId !== `${tenantId}:${contactId}`) {
    throw new RespostaInvalidaError("thread_id nao e o do tenant e do contacto");
  }
  return {
    replyId,
    threadId,
    conversationId,
    contactId,
    canal: canal as CanalDaResposta,
  };
}

/** Os botões da linha (`jsonb`), na forma do `Corpo` do Outbound. */
/**
 * O *template* da linha, ou `null`. Um parâmetro que não seja texto não vira
 * texto aqui: a forma é da `0076` e do AGR, e uma linha fora dela é defeito.
 */
export function templateDaLinha(nome: unknown, parametros: unknown): TemplateDaResposta | null {
  const lista = parametros ?? [];
  if (!Array.isArray(lista) || !lista.every((p) => typeof p === "string")) {
    throw new RespostaInvalidaError("template_parametros nao e uma lista de texto");
  }
  if (nome === null || nome === undefined) {
    if (lista.length > 0) throw new RespostaInvalidaError("parametros sem template");
    return null;
  }
  if (typeof nome !== "string" || nome === "") {
    throw new RespostaInvalidaError("template_nome sem forma");
  }
  return { nome, parametros: lista as string[] };
}

export function botoesDaLinha(bruto: unknown): readonly BotaoDaResposta[] {
  const lista = typeof bruto === "string" ? (JSON.parse(bruto) as unknown) : bruto;
  if (!Array.isArray(lista)) throw new RespostaInvalidaError("botoes nao e uma lista");
  return lista.map((b) => {
    const par = b as Record<string, unknown> | null;
    const id = par?.["id"];
    const titulo = par?.["titulo"];
    if (typeof id !== "string" || id === "" || typeof titulo !== "string" || titulo === "") {
      throw new RespostaInvalidaError("botao sem id ou sem titulo");
    }
    return { id, titulo };
  });
}
