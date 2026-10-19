/**
 * A explosão do corpo do webhook em eventos de canal (KAM-013).
 *
 * «Explode `entry`/`changes`/`messages`/`statuses`» é o que o *handoff* pede, e
 * é função pura: recebe o que o `JSON.parse` devolveu e dá a lista de eventos a
 * registar e a lista a pôr em quarentena. Nada aqui toca na base nem na fila —
 * é o que permite prendê-la com testes sem Postgres e sem Redis, e é onde vive
 * a decisão do critério 8.
 *
 * ## Duas regras, e a segunda é a que torna isto honesto
 *
 * 1. **Um evento por item, quando há itens com identificador.** `messages[]` e
 *    `statuses[]` são a forma CONFIRMADA (`evidencia/E1` §5), e é daí que sai o
 *    `event_key` que o critério 4 fixa: o `wamid` para uma mensagem, e
 *    `wamid:estado` para um estado.
 * 2. **Um evento por `change`, com um resumo canónico, quando não há.** Um
 *    `account_update` não traz identificador nenhum, e a Meta re-entrega
 *    durante sete dias (`E1` §5): sem chave determinística, cada tentativa
 *    criava uma linha. O resumo é sobre `(waba_id, campo, valor)` com as
 *    chaves ordenadas, pelo que duas entregas do mesmo evento dão a mesma
 *    chave e a terceira não acrescenta nada.
 *
 * A regra 2 é também a rede da regra 1: **o nome do array dentro do campo
 * `smb_message_echoes` é NÃO VERIFICADO.** O `E1` §5 não o diz e nenhuma página
 * primária foi lida nesta execução. O `message_echoes` está aqui como
 * *proposta* e, se estiver errado, o *echo* cai na regra 2 — um evento por
 * `change`, com `kind` correcto e `event_key` determinístico. Fica mais grosso
 * e continua correcto; fixá-lo é KAM-017, que é quem lê a documentação de
 * coexistência.
 *
 * ## Nada do que sai daqui vem de fora sem tecto
 *
 * Todo o `event_key`, `waba_id` e `phone_number_id` vem do corpo, isto é, de
 * quem conseguir assinar um pedido. Os três têm limite de comprimento **igual
 * ao do `CHECK` da revisão `0008`**, e a razão é operacional e não estética:
 * uma chave de 300 caracteres fazia a inserção violar o `CHECK`, o *job*
 * falhar, e o BullMQ repetir — durante sete dias, com a Meta a re-entregar por
 * cima. O que excede o tecto não rebenta: degrada para o resumo canónico, ou
 * para a quarentena.
 */

import { createHash } from "node:crypto";

import {
  CAMPO_DAS_MENSAGENS,
  KIND_POR_CAMPO,
  type KindDeEntrada,
  type KindDeQuarentena,
  type Motivo,
  type WaType,
  waType,
} from "./contrato.ts";

/** Tecto de uma `event_key`. O mesmo do `CHECK` da revisão `0008`. */
export const EVENT_KEY_MAXIMO = 256;
/** Tecto dos identificadores da Meta. O mesmo do `CHECK` da revisão `0008`. */
export const ID_META_MAXIMO = 64;

/**
 * Até que profundidade o resumo canónico desce.
 *
 * Um corpo da Meta tem meia dúzia de níveis. O limite existe porque este
 * módulo recebe o que o `JSON.parse` devolveu de um corpo externo, e uma
 * estrutura muito funda é uma forma baixa de gastar pilha. Abaixo do limite o
 * valor entra como `"..."` — determinístico, que é o que a chave precisa.
 */
export const PROFUNDIDADE_MAXIMA = 24;

/** O prefixo do resumo canónico. Dicionário §3.12. */
export const PREFIXO_DO_RESUMO = "k_";

/** O array de *echoes* dentro do `value` — ***proposta***, NÃO VERIFICADO. */
export const ARRAY_DOS_ECHOES = "message_echoes";

/** Um evento de canal a registar em `inbound_events`. */
export interface EventoDeEntrada {
  /** Um dos doze campos de webhook. O tipo recusa `desconhecido` e `invalido`. */
  readonly kind: KindDeEntrada;
  readonly eventKey: string;
  readonly wabaId: string;
  readonly phoneNumberId: string | null;
  /** Só para `message` e `echo`; `null` nos outros. É o que vai a `wa_type`. */
  readonly waType: WaType | null;
}

/** Um evento que não se conseguiu encaminhar, a registar em `unrouted_events`. */
export interface EventoEmQuarentena {
  /** `desconhecido` ou `invalido`. O tipo recusa os doze de entrada. */
  readonly kind: KindDeQuarentena;
  readonly eventKey: string;
  readonly motivo: Motivo;
  readonly wabaId: string | null;
  readonly phoneNumberId: string | null;
}

export interface Explosao {
  readonly eventos: readonly EventoDeEntrada[];
  readonly quarentena: readonly EventoEmQuarentena[];
}

/**
 * JSON determinístico: chaves ordenadas, sem espaços, `undefined` omitido.
 *
 * O `JSON.stringify` **não** serve: a ordem das chaves é a de inserção, e duas
 * entregas do mesmo evento com as chaves noutra ordem davam resumos
 * diferentes — que é exactamente o duplicado que esta chave existe para
 * apanhar.
 */
export function canonico(valor: unknown, profundidade = 0): string {
  if (profundidade > PROFUNDIDADE_MAXIMA) return '"..."';
  if (valor === null) return "null";
  if (typeof valor === "boolean") return valor ? "true" : "false";
  if (typeof valor === "number") {
    // `NaN` e `Infinity` não existem em JSON, mas chegam aqui se alguém chamar
    // isto com um objecto que não veio de um `parse`. `null` é o que o
    // `JSON.stringify` faz, e é determinístico.
    return Number.isFinite(valor) ? JSON.stringify(valor) : "null";
  }
  if (typeof valor === "string") return JSON.stringify(valor);
  if (Array.isArray(valor)) {
    return `[${valor.map((item) => canonico(item, profundidade + 1)).join(",")}]`;
  }
  if (typeof valor === "object") {
    const registo = valor as Record<string, unknown>;
    const partes: string[] = [];
    for (const chave of Object.keys(registo).sort()) {
      const dentro = registo[chave];
      if (dentro === undefined) continue;
      partes.push(`${JSON.stringify(chave)}:${canonico(dentro, profundidade + 1)}`);
    }
    return `{${partes.join(",")}}`;
  }
  // Uma função ou um símbolo: não vem de JSON. Omite-se, como o `stringify`.
  return "null";
}

/** `k_` mais 32 hexadecimais do SHA-256 do JSON canónico dos argumentos. */
export function resumoCanonico(...partes: readonly unknown[]): string {
  const texto = canonico(partes);
  const resumo = createHash("sha256").update(texto, "utf8").digest("hex");
  return `${PREFIXO_DO_RESUMO}${resumo.slice(0, 32)}`;
}

/** O texto, se for texto não vazio dentro do tecto; senão `null`. */
function texto(valor: unknown, maximo: number): string | null {
  if (typeof valor !== "string") return null;
  if (valor === "" || valor.length > maximo) return null;
  return valor;
}

function objecto(valor: unknown): Record<string, unknown> | null {
  if (typeof valor !== "object" || valor === null || Array.isArray(valor)) return null;
  return valor as Record<string, unknown>;
}

function lista(valor: unknown): readonly unknown[] {
  return Array.isArray(valor) ? valor : [];
}

/**
 * Explode o corpo já interpretado.
 *
 * @param corpo o que o `JSON.parse` devolveu
 * @param resumoDoCorpo o SHA-256 do corpo bruto; é a `event_key` de último
 *   recurso, para que um corpo sem `entry` utilizável tenha chave
 *   determinística em vez de uma linha por re-entrega
 */
export function explodir(corpo: unknown, resumoDoCorpo: string): Explosao {
  const eventos: EventoDeEntrada[] = [];
  const quarentena: EventoEmQuarentena[] = [];

  const raiz = objecto(corpo);
  const entradas = lista(raiz?.entry);
  if (entradas.length === 0) {
    return {
      eventos: [],
      quarentena: [
        {
          kind: "desconhecido",
          eventKey: `${PREFIXO_DO_RESUMO}${resumoDoCorpo.slice(0, 32)}`,
          motivo: "corpo_sem_entry",
          wabaId: null,
          phoneNumberId: null,
        },
      ],
    };
  }

  for (const bruta of entradas) {
    const entrada = objecto(bruta);
    // `entry.id` **é** o `waba_id` (CONFIRMADO, `E1` §5: «multiplexar por
    // `entry.id` (`waba_id`)»), e é a única coluna não anulável de
    // `inbound_events`: sem ele não há onde pôr o evento, e vai para a
    // quarentena, onde a coluna é anulável.
    const wabaId = texto(entrada?.id, ID_META_MAXIMO);
    const mudancas = lista(entrada?.changes);
    if (wabaId === null || mudancas.length === 0) {
      quarentena.push({
        kind: "desconhecido",
        // O índice não entra na chave: o que a torna única é o conteúdo da
        // entrada, e duas entradas iguais no mesmo corpo são o mesmo evento.
        eventKey: resumoCanonico("entry", resumoDoCorpo, entrada ?? null),
        motivo: "corpo_sem_entry",
        wabaId: texto(entrada?.id, ID_META_MAXIMO),
        phoneNumberId: null,
      });
      continue;
    }

    for (const crua of mudancas) {
      const mudanca = objecto(crua);
      const campo = texto(mudanca?.field, ID_META_MAXIMO);
      const valor = objecto(mudanca?.value);
      const phoneNumberId = texto(
        objecto(valor?.metadata)?.phone_number_id,
        ID_META_MAXIMO,
      );

      if (campo === null) {
        quarentena.push({
          kind: "desconhecido",
          eventKey: resumoCanonico("change", wabaId, mudanca ?? null),
          motivo: "campo_desconhecido",
          wabaId,
          phoneNumberId,
        });
        continue;
      }

      if (campo === CAMPO_DAS_MENSAGENS) {
        const quantos = explodirMensagens(
          valor,
          wabaId,
          phoneNumberId,
          eventos,
        );
        if (quantos === 0) {
          // O campo é conhecido e o `value` não traz nem `messages` nem
          // `statuses`. Acontece de verdade — a Meta põe `errors` aqui — e não
          // é «campo desconhecido» nem «corpo sem entry»: é um `change` sem
          // itens que se saiba tratar. Vai para a quarentena com o seu próprio
          // motivo, para que o alerta diga a verdade a quem o ler.
          quarentena.push({
            kind: "desconhecido",
            eventKey: resumoCanonico("change", wabaId, campo, valor ?? null),
            motivo: "change_sem_itens",
            wabaId,
            phoneNumberId,
          });
        }
        continue;
      }

      const kind = KIND_POR_CAMPO[campo];
      if (kind === undefined) {
        quarentena.push({
          kind: "desconhecido",
          eventKey: resumoCanonico("change", wabaId, campo, valor ?? null),
          motivo: "campo_desconhecido",
          wabaId,
          phoneNumberId,
        });
        continue;
      }

      // Regra 1 para o `echo`, se o array estiver onde a *proposta* diz; regra
      // 2 para todos os outros, e para o `echo` quando não está.
      const itens = kind === "echo" ? lista(valor?.[ARRAY_DOS_ECHOES]) : [];
      let emitidos = 0;
      for (const item of itens) {
        const dentro = objecto(item);
        if (dentro === null) continue;
        const wamid = texto(dentro.id, EVENT_KEY_MAXIMO);
        eventos.push({
          kind,
          eventKey: wamid ?? resumoCanonico("echo", wabaId, dentro),
          wabaId,
          phoneNumberId,
          waType: waType(dentro.type),
        });
        emitidos += 1;
      }
      if (emitidos === 0) {
        eventos.push({
          kind,
          eventKey: resumoCanonico("change", wabaId, campo, valor ?? null),
          wabaId,
          phoneNumberId,
          waType: null,
        });
      }
    }
  }

  return { eventos, quarentena };
}

/** `messages[]` e `statuses[]`; devolve quantos eventos saíram. */
function explodirMensagens(
  valor: Record<string, unknown> | null,
  wabaId: string,
  phoneNumberId: string | null,
  eventos: EventoDeEntrada[],
): number {
  let quantos = 0;

  for (const bruta of lista(valor?.messages)) {
    const mensagem = objecto(bruta);
    if (mensagem === null) continue;
    const wamid = texto(mensagem.id, EVENT_KEY_MAXIMO);
    eventos.push({
      kind: "message",
      eventKey: wamid ?? resumoCanonico("message", wabaId, mensagem),
      wabaId,
      phoneNumberId,
      waType: waType(mensagem.type),
    });
    quantos += 1;
  }

  for (const bruto of lista(valor?.statuses)) {
    const estado = objecto(bruto);
    if (estado === null) continue;
    // `wamid:estado` — a letra do critério 4. Os dois juntos têm de caber no
    // tecto; se não couberem, o resumo canónico fica em vez da chave composta,
    // e continua a deduplicar o mesmo par.
    const wamid = texto(estado.id, EVENT_KEY_MAXIMO);
    const situacao = texto(estado.status, ID_META_MAXIMO);
    const composta =
      wamid !== null && situacao !== null ? `${wamid}:${situacao}` : null;
    eventos.push({
      kind: "statuses",
      eventKey:
        composta !== null && composta.length <= EVENT_KEY_MAXIMO
          ? composta
          : resumoCanonico("status", wabaId, estado),
      wabaId,
      phoneNumberId,
      waType: null,
    });
    quantos += 1;
  }

  return quantos;
}
