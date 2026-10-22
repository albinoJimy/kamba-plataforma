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

/**
 * O campo que, dentro de um *echo*, traz o destinatário — ***proposta***, NÃO
 * VERIFICADO.
 *
 * **Fixado pelo KAM-017**, que é o que a nota abaixo lhe atribuía. Vive aqui e
 * não no `coexistencia/contrato.ts` pela razão que o `ARRAY_DOS_ECHOES` já
 * tinha: é a explosão que lê o corpo, e o simulador do KAM-024 importa estes
 * dois nomes **deste** módulo para que o dia em que a Meta os desminta mude um
 * sítio e não três.
 */
export const CAMPO_DO_DESTINATARIO = "to";

/**
 * Quem está do outro lado de uma mensagem, como a Meta o identifica.
 *
 * **Não é persistido por este módulo, e é por isso que existe.** O
 * `inbound_events` guarda o mínimo para dizer «este evento já passou por aqui»
 * e **não** guarda identidade nenhuma (revisão `0008`): no momento em que é
 * escrito, o tenant ainda não existe. Mas o CHR (KAM-014) tem de resolver o
 * contacto, e para isso precisa do BSUID e do telefone que vieram **neste**
 * corpo — relê-los implicava guardar o corpo ou voltar a pedi-lo à Meta.
 *
 * Os dois campos são os de `docs/tecnica/01` §6.1 (CONFIRMADO, `E1` §3): em
 * `messages[]`, o BSUID é `from_user_id` e o telefone é `from`. **Qualquer um
 * dos dois pode faltar** — o `wa_id`/`from` é omitido quando o utilizador
 * adoptou *username* e não há contacto recente —, e é essa a razão de ser do
 * BSUID. Vêm de uma fonte autenticada (o corpo cuja assinatura o GWY
 * conferiu), que é o que o `resolveContact` do KAM-008 exige.
 *
 * O `parent_user_id` **não** entra: o KAM-008 não o recebe e o limite está
 * escrito em `docs/identidade.md` §4.
 */
export interface Interlocutor {
  /** `from_user_id` numa mensagem (`user_id` em `contacts[]`). */
  readonly bsuid: string | null;
  /** `from` numa mensagem (`wa_id` em `contacts[]`), em E.164. */
  readonly telefone: string | null;
}

/** Um evento de canal a registar em `inbound_events`. */
export interface EventoDeEntrada {
  /** Um dos doze campos de webhook. O tipo recusa `desconhecido` e `invalido`. */
  readonly kind: KindDeEntrada;
  readonly eventKey: string;
  readonly wabaId: string;
  readonly phoneNumberId: string | null;
  /** Só para `message` e `echo`; `null` nos outros. É o que vai a `wa_type`. */
  readonly waType: WaType | null;
  /**
   * Para `message` e para `echo`; `null` nos outros.
   *
   * **Até ao KAM-017 era `null` também no `echo`**, e a nota dizia que fixar o
   * campo era trabalho dele. Está fixado: num `echo` o interlocutor é o
   * **destinatário** (`CAMPO_DO_DESTINATARIO`), porque quem escreveu foi o
   * dono — e sem ele um *echo* não tem contacto, logo não tem conversa, logo a
   * célula `bot→dono` que o KAM-018 pôs na tabela ficava sem detector. O que
   * se segue é a nota original, que continua a valer para o que **não** se
   * fixou (o `bsuid`, que num `echo` seria o do dono e não o do interlocutor):
   *
   * Num `echo` quem escreveu foi o dono, e o nome do campo que traz o
   * destinatário dentro de `smb_message_echoes` é **NÃO VERIFICADO** (`E1` §5
   * não o diz) — o mesmo limite que já põe `ARRAY_DOS_ECHOES` como *proposta*.
   * Inventar aqui um `to` que talvez não exista era pôr o CHR a resolver
   * contactos a partir de um campo que ninguém leu; o `echo` vai ao dono
   * (KAM-018), que não precisa de identidade resolvida, e fixar o campo é
   * KAM-017.
   */
  readonly interlocutor: Interlocutor | null;
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
          // **KAM-017 fixou o campo**, que era o que a nota de
          // `EventoDeEntrada.interlocutor` lhe atribuia. Num `echo` quem
          // escreveu foi o dono, pelo que o interlocutor e o **destinatario** —
          // o `to` —, e nao o `from` de uma `message`. Continua ***proposta*,
          // NAO VERIFICADO**: o `E1` §5 nao descreve a forma de
          // `smb_message_echoes`, e o nome e o que o simulador do KAM-024 ja
          // emite, para que os dois lados da proposta digam o mesmo.
          //
          // **Nao ha `bsuid` num `echo`**, e nao se inventa um: o `from_user_id`
          // identifica quem *envia*, e quem envia um `echo` e o dono. Um BSUID
          // do dono posto no lugar do interlocutor fazia o KAM-008 resolver o
          // contacto errado — e so se descobria no dia em que a conversa do
          // dono consigo proprio aparecesse no painel de um cliente.
          interlocutor: {
            bsuid: null,
            telefone: texto(dentro[CAMPO_DO_DESTINATARIO], ID_META_MAXIMO),
          },
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
          interlocutor: null,
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
      // **O unico sitio onde o interlocutor sai.** `from_user_id` e o BSUID e
      // `from` e o telefone (`docs/tecnica/01` §6.1, CONFIRMADO); qualquer um
      // dos dois pode faltar, e os tectos sao os dos identificadores da Meta —
      // um valor absurdamente longo vindo do corpo nao passa para o CHR.
      interlocutor: {
        bsuid: texto(mensagem.from_user_id, ID_META_MAXIMO),
        telefone: texto(mensagem.from, ID_META_MAXIMO),
      },
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
      // Um `statuses` vai ao *stage* de *outbound* (KAM-015) e nunca ao CHR:
      // nao ha contacto a resolver.
      interlocutor: null,
    });
    quantos += 1;
  }

  return quantos;
}
