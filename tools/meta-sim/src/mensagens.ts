/**
 * Os tipos de mensagem de entrada, como a Meta os entrega (KAM-024, critério 1).
 *
 * A lista é a de `docs/tecnica/01` §5.4, que é a mesma do `WA_TYPES` de
 * `@kamba/core-ts/entrada` — e importa-se de lá em vez de se reescrever: o
 * §3.12 do dicionário explica porque é que essa lista **não** entra no canon
 * (nenhuma superfície do *gate* 3b lê TypeScript), e por isso o módulo é a
 * única fonte. Um teste confronta as duas listas.
 *
 * ## O que cada corpo tem, e o que deliberadamente não tem
 *
 * Cada construtor produz o **item** de `messages[]`, não o corpo inteiro: a
 * montagem em `entry`/`changes` é do `corpo.ts`, e separá-las é o que permite
 * ter um corpo com três mensagens, ou com uma mensagem e dois estados, sem
 * reescrever nenhum dos dois.
 *
 * Nenhum item traz URL de mídia. A Meta entrega um `id` de mídia e a URL
 * obtém-se por um GET autenticado que **expira** (`docs/tecnica/01` §5.4), pelo
 * que uma *fixture* com URL seria uma *fixture* de uma coisa que não existe. O
 * download é KAM-020, contra o servidor Graph falso deste ticket.
 *
 * O `timestamp` é um segundo em texto, como a Meta o manda — e vem do gerador,
 * não do relógio: o critério 1 pede bytes idênticos para a mesma semente, e um
 * `Date.now()` aqui tornava isso impossível.
 */

import { WA_TYPES } from "@kamba/core-ts/entrada";

import { CODIGOS_PROPOSTOS } from "./codigos.ts";
import type { Interlocutor } from "./identificadores.ts";
import { wamid } from "./identificadores.ts";
import type { Gerador } from "./semente.ts";

/** Os dez tipos de `messages[]`. A lista é a do `core-ts`. */
export const TIPOS = WA_TYPES;
export type Tipo = (typeof TIPOS)[number];

/** As duas variantes de `interactive`, que são tipos próprios no critério 1. */
export const VARIANTES_INTERACTIVAS = ["button_reply", "list_reply"] as const;
export type VarianteInteractiva = (typeof VARIANTES_INTERACTIVAS)[number];

/**
 * O instante de uma *fixture*, em segundos, como texto.
 *
 * A base é fixa e vem da semente: 2026-10-01T00:00:00Z mais um deslocamento
 * determinístico de até trinta dias. Fixa porque o critério 1 pede bytes
 * idênticos; 2026-10-01 porque é a data em que as *service messages* passaram a
 * ser pagas (`E1` §1), e uma *fixture* datada antes disso descrevia um mundo com
 * outro preço.
 */
export const BASE_DO_TEMPO = 1_790_812_800;

export function instante(g: Gerador): string {
  return String(BASE_DO_TEMPO + g.inteiro(30 * 24 * 60 * 60));
}

/** O que um item de `messages[]` leva sempre. */
function comum(
  g: Gerador,
  quem: Interlocutor,
  tipo: string,
  comWaId: boolean,
): Record<string, unknown> {
  const numero = quem.waId;
  return {
    // A ordem das chaves é a ordem em que a Meta as escreve, e é fixa: é o que
    // torna o `JSON.stringify` determinístico sem precisar de ordenar chaves.
    ...(comWaId ? { from: numero } : {}),
    from_user_id: quem.userId,
    id: wamid(g, numero),
    timestamp: instante(g),
    type: tipo,
  };
}

/** Opções de um item: se traz `wa_id`, e com que texto. */
export interface Opcoes {
  /**
   * `false` omite o `from`.
   *
   * É o caso que o `E1` §3 confirma: o `wa_id` é omitido se o utilizador adoptou
   * *username* e não há contacto recente. O critério 3 pede-o pelo nome
   * («`wa_id` omitido (apenas BSUID/`username`)»), e é o caso em que o CHR tem
   * de resolver o contacto só pelo BSUID.
   */
  readonly comWaId?: boolean;
  /** O texto, para os tipos que o levam. Por omissão, um texto sintético. */
  readonly texto?: string;
  /**
   * A variante de `interactive`. Por omissão, `button_reply`.
   *
   * É parâmetro e não detalhe porque o critério 1 nomeia as **duas** variantes:
   * sem isto, um `tipos: ["interactive"]` dava sempre `button_reply` e a
   * cobertura de `list_reply` era um zero disfarçado de 100%.
   */
  readonly variante?: VarianteInteractiva;
}

const TEXTOS = [
  "Bom dia, tem disponivel?",
  "Qual e o preco?",
  "Quero encomendar dois",
  "Obrigado",
  "A que horas abrem?",
];

/** Um item de `messages[]` do tipo pedido. */
export function mensagem(
  g: Gerador,
  quem: Interlocutor,
  tipo: Tipo,
  opcoes: Opcoes = {},
): Record<string, unknown> {
  const comWaId = opcoes.comWaId ?? true;
  const base = comum(g, quem, tipo, comWaId);
  switch (tipo) {
    case "text":
      return { ...base, text: { body: opcoes.texto ?? g.escolher(TEXTOS) } };
    case "audio":
      // `voice: true` é a nota de voz, que é o caso que interessa ao STT
      // (`docs/tecnica/02` §11). Sem URL: ver a nota do módulo.
      return {
        ...base,
        audio: { id: g.texto(24, "0123456789"), mime_type: "audio/ogg; codecs=opus", voice: true },
      };
    case "image":
      return {
        ...base,
        image: { id: g.texto(24, "0123456789"), mime_type: "image/jpeg", sha256: g.texto(64, "0123456789abcdef") },
      };
    case "document":
      return {
        ...base,
        document: {
          id: g.texto(24, "0123456789"),
          mime_type: "application/pdf",
          filename: `comprovativo-${g.texto(6, "0123456789")}.pdf`,
          sha256: g.texto(64, "0123456789abcdef"),
        },
      };
    case "location":
      // Coordenadas arredondadas à zona, que é o que o dicionário §3.6 manda:
      // exactas só no pedido de entrega, e isso é Clusters.
      return {
        ...base,
        location: { latitude: -8.8 - g.inteiro(20) / 100, longitude: 13.2 + g.inteiro(20) / 100 },
      };
    case "interactive":
      return interactiva(g, quem, opcoes.variante ?? "button_reply", opcoes);
    case "order":
      // Fora do Piloto (`01` §4.5): registar e responder com fluxo próprio. A
      // *fixture* existe para provar que o registo acontece.
      return {
        ...base,
        order: {
          catalog_id: g.texto(16, "0123456789"),
          product_items: [
            {
              product_retailer_id: `sku-${g.texto(6, "0123456789")}`,
              quantity: 1 + g.inteiro(3),
              // O preço vem no corpo e **não se confia nele**: os números são
              // só de tools (ADR-007). A *fixture* tem-no porque a Meta o manda.
              item_price: 1000 + g.inteiro(9000),
              currency: "AOA",
            },
          ],
        },
      };
    case "reaction":
      return { ...base, reaction: { message_id: wamid(g, quem.waId), emoji: "\u{1F44D}" } };
    case "sticker":
      return {
        ...base,
        sticker: { id: g.texto(24, "0123456789"), mime_type: "image/webp", animated: false },
      };
    case "unsupported":
      // A Meta manda `errors[]` dentro do item quando o tipo não é suportado.
      return {
        ...base,
        errors: [
          {
            code: CODIGOS_PROPOSTOS.tipoNaoSuportado,
            title: "Unsupported message type",
            message: "Message type is not currently supported.",
          },
        ],
      };
  }
}

/** Um item `interactive` da variante pedida. */
export function interactiva(
  g: Gerador,
  quem: Interlocutor,
  variante: VarianteInteractiva,
  opcoes: Opcoes = {},
): Record<string, unknown> {
  const base = comum(g, quem, "interactive", opcoes.comWaId ?? true);
  // **O `id` é o que o AGR usa, nunca o `title`.** É a regra do §5.4 («o AGR
  // confia no `id` que emitiu, não no título»), e a *fixture* existe também
  // para a poder violar num teste: um `title` mentiroso com um `id` certo tem
  // de dar o mesmo resultado.
  const identificador =
    variante === "button_reply"
      ? `confirm:${g.texto(8, "0123456789abcdef")}`
      : `linha:${g.texto(8, "0123456789abcdef")}`;
  return {
    ...base,
    interactive: {
      type: variante,
      [variante]: { id: identificador, title: opcoes.texto ?? "Confirmar" },
    },
  };
}

/** O bloco `contacts[]` que acompanha `messages[]`. */
export function contacto(quem: Interlocutor, comWaId = true): Record<string, unknown> {
  return {
    profile: { name: quem.nome },
    user_id: quem.userId,
    ...(comWaId ? { wa_id: quem.waId } : {}),
  };
}
