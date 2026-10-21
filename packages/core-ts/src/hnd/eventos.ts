/**
 * A leitura dos *callbacks* do provedor para `HumanEvent` (KAM-019).
 *
 * O provedor manda cinco acontecimentos (`docs/tecnica/01` §11.3:
 * `conversation_created`, `conversation_status_changed`, `conversation_updated`,
 * `message_created`, `message_updated`) e o critério 5 aceita **dois**. Este
 * ficheiro é a fronteira: traduz os dois e **recusa** os outros três.
 *
 * ## Recusar e não ignorar
 *
 * Um acontecimento que não se sabe tratar devolve `tipo_desconhecido` e um 401,
 * e não um 200 silencioso. A diferença aparece no dia em que o provedor
 * acrescenta um tipo que nos devia interessar: com 200, ele pára de reenviar e
 * nós nunca sabemos; com 401, fica no registo dele e na nossa métrica. É a
 * mesma razão que o KAM-013 escreveu para o `motivo` da quarentena — o que não
 * se consegue encaminhar deixa linha.
 *
 * ## O que **não** se lê do corpo
 *
 * Nada que identifique a pessoa do lado do cliente. O corpo do provedor traz a
 * conta de contacto dele, e nós só queremos: que conversa é (`external_id`),
 * que passagem é (`handoff_id`, do atributo da conversa), o que o agente
 * escreveu, o estado novo, e o identificador opaco do agente. O ADR-010 proíbe
 * o resto, e não lê-lo é mais forte do que lê-lo e descartá-lo.
 */

import {
  ACONTECIMENTOS,
  type Acontecimento,
  type HumanEvent,
} from "./contrato.ts";

/** O nome que o provedor dá a cada acontecimento que aceitamos. */
export const EVENTO_DO_PROVEDOR: Readonly<Record<string, Acontecimento>> = {
  message_created: "mensagem_de_agente",
  conversation_status_changed: "estado_mudou",
};

/**
 * O atributo da conversa onde o `handoff_id` vive, do lado do provedor.
 *
 * É por aqui que o `openHandoff` «procura a conversa por atributo `handoffId`,
 * senão cria» (critério 4). O nome é o do critério — `handoffId`, em
 * *camelCase* — e **não** o `handoff_id` da nossa coluna: é um campo de um
 * terceiro e segue a convenção dele, como o `wa_type` do dicionário §3.12 fez
 * com o vocabulário da Meta.
 */
export const ATRIBUTO_DO_HANDOFF = "handoffId";

/** O corpo de um *callback*, como ele chega: JSON já descodificado. */
export type Corpo = Readonly<Record<string, unknown>>;

function texto(valor: unknown): string | null {
  return typeof valor === "string" && valor.length > 0 ? valor : null;
}

function objecto(valor: unknown): Corpo | null {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor)
    ? (valor as Corpo)
    : null;
}

/**
 * Lê um *callback* e devolve o `HumanEvent`, ou `null` se não é dos dois.
 *
 * `null` e não uma excepção: «este acontecimento não é para nós» é uma resposta
 * normal — o provedor manda cinco tipos e nós queremos dois —, e uma excepção
 * para o caso normal obriga quem chama a usar `try/catch` como fluxo de
 * controlo.
 *
 * **Uma mensagem que não é de agente também devolve `null`.** O
 * `message_created` chega para **todas** as mensagens da conversa, incluindo as
 * que nós próprios espelhámos: tratar o nosso espelho como resposta humana era
 * reenviar ao cliente o que ele acabou de nos mandar, e era um ciclo. O campo
 * que decide é o `message_type` do provedor: só `outgoing` é do agente.
 */
export function lerAcontecimento(corpo: Corpo): HumanEvent | null {
  const nome = texto(corpo["event"]);
  if (nome === null) return null;
  const acontecimento = EVENTO_DO_PROVEDOR[nome];
  if (acontecimento === undefined) return null;

  const conversa = objecto(corpo["conversation"]) ?? {};
  const atributos = objecto(conversa["custom_attributes"]) ?? {};
  const handoffId = texto(atributos[ATRIBUTO_DO_HANDOFF]);
  const externalId = texto(conversa["id"]) ?? String(conversa["id"] ?? "");
  if (handoffId === null || externalId.length === 0) return null;

  if (acontecimento === "mensagem_de_agente") {
    // So o que vem do agente. Ver a nota da funcao: o `incoming` e o eco do
    // nosso proprio espelho, e trata-lo como resposta era um ciclo.
    if (texto(corpo["message_type"]) !== "outgoing") return null;
    return {
      acontecimento,
      externalId,
      handoffId,
      texto: texto(corpo["content"]),
      // O identificador da mensagem no provedor: e dele que a chave de
      // idempotencia do envio da resposta deriva. O provedor manda-o como
      // numero.
      mensagemId: texto(corpo["id"]) ?? (typeof corpo["id"] === "number" ? String(corpo["id"]) : null),
      estado: null,
      resolver: identificadorDoAgente(corpo),
    };
  }

  return {
    acontecimento,
    externalId,
    handoffId,
    texto: null,
    // Um `estado_mudou` nao e uma mensagem: nao tem identificador de mensagem.
    mensagemId: null,
    estado: texto(conversa["status"]) ?? texto(corpo["status"]),
    resolver: identificadorDoAgente(corpo),
  };
}

/**
 * O identificador opaco do agente, se o corpo o trouxer.
 *
 * **Só o `id`**, nunca o `name` nem o `email` que o provedor também manda no
 * mesmo objecto. O `handoffs.resolver` é o primeiro dado pessoal de um
 * trabalhador da PME no nosso esquema, e o que se guarda é o mínimo que
 * responde «quem retomou» — o resto fica do lado do provedor, que é quem tem
 * razão para o ter.
 */
export function identificadorDoAgente(corpo: Corpo): string | null {
  const remetente = objecto(corpo["sender"]) ?? objecto(corpo["assignee"]);
  if (remetente === null) return null;
  const id = remetente["id"];
  if (typeof id === "number") return String(id);
  return texto(id);
}

/** Os acontecimentos que aceitamos, para quem precise de iterar. */
export { ACONTECIMENTOS };
