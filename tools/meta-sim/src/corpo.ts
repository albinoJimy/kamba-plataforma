/**
 * A montagem do corpo e a sua **serialização** (KAM-024, critérios 1 e 4).
 *
 * Um corpo da Meta é `{ object, entry[] }`, cada `entry` tem o `waba_id` em
 * `entry.id` e uma lista de `changes`, e cada `change` é um par `field`/`value`.
 * Montar isto num módulo à parte dos construtores de campo é o que permite ter
 * um corpo com três `changes` de campos diferentes, ou dois `entry` de WABAs
 * diferentes no mesmo POST, sem tocar em nenhum construtor.
 *
 * ## Porque é que a serialização é um assunto deste módulo, e não um detalhe
 *
 * A assinatura da Meta é o HMAC do **corpo bruto**, byte a byte. Quem valide
 * sobre o objecto re-serializado — `JSON.stringify(await c.req.json())` — passa
 * nos testes todos e **recusa tráfego real**, porque os bytes que a Meta assinou
 * não são os que o `JSON.stringify` de Node produz. É um defeito que não se vê
 * com uma *fixture* só, e vê-se logo com duas:
 *
 * - `serializar(valor, "compacto")` e `serializar(valor, "espacado")` dão o
 *   **mesmo JSON** e **bytes diferentes**;
 * - a assinatura de um não serve para o outro.
 *
 * É esse par que o critério 4 transforma em prova: o GWY aceita o corpo que foi
 * assinado, e dá 401 ao outro — não porque o JSON seja inválido, mas porque os
 * bytes mudaram. Um GWY que normalize antes de verificar passa o primeiro caso e
 * falha o segundo, que é exactamente o que se quer apanhar.
 *
 * ## `entry.time`
 *
 * **INDÍCIO**: as páginas lidas mostram `time` em alguns corpos e não o
 * descrevem como garantido. O simulador põe-no (é o que se vê no tráfego) e o
 * `explodir` do KAM-013 não o lê — a chave de deduplicação é o `wamid`, não o
 * tempo —, pelo que incluí-lo não cria dependência nenhuma. Quem precisar de um
 * corpo sem `time` passa `comTempo: false`.
 */

import { valorDe, type Campo, type Opcoes as OpcoesDeCampo } from "./campos.ts";
import type { Canal } from "./identificadores.ts";
import type { Gerador } from "./semente.ts";

/** O `object` de um corpo de WABA. É sempre este valor. */
export const OBJECTO = "whatsapp_business_account";

/** Um `change`: o par `field`/`value`. */
export interface Mudanca {
  readonly field: string;
  readonly value: Record<string, unknown>;
}

/** Uma `entry`: o WABA e as suas mudanças. */
export interface Entrada {
  readonly id: string;
  readonly time?: number;
  readonly changes: readonly Mudanca[];
}

/** Um corpo inteiro, como a Meta o faz POST. */
export interface Corpo {
  readonly object: string;
  readonly entry: readonly Entrada[];
}

/** Um pedido de `change` ao montador: o campo e as opções do seu construtor. */
export interface PedidoDeMudanca {
  readonly campo: Campo;
  readonly opcoes: OpcoesDeCampo;
}

/** Um `change` montado a partir de um pedido. */
export function mudanca(g: Gerador, pedido: PedidoDeMudanca): Mudanca {
  return { field: pedido.campo, value: valorDe(g, pedido.campo, pedido.opcoes) };
}

/** Opções da montagem de um corpo. */
export interface OpcoesDoCorpo {
  /** O WABA de todas as mudanças, quando não se der `entradas`. */
  readonly canal: Canal;
  readonly mudancas: readonly PedidoDeMudanca[];
  /** `false` omite o `entry.time`. */
  readonly comTempo?: boolean;
  /** O instante de `entry.time`, em segundos. Por omissão, do gerador. */
  readonly tempo?: number;
}

/**
 * O instante de `entry.time`. Base fixa, como o das mensagens: o critério 1 pede
 * bytes idênticos para a mesma semente, e um `Date.now()` aqui bastava para os
 * tornar diferentes a cada execução.
 */
const BASE_DO_TEMPO = 1_790_812_800;

/** Um corpo com um `entry`, do canal dado, com as mudanças pedidas. */
export function corpo(g: Gerador, opcoes: OpcoesDoCorpo): Corpo {
  const changes = opcoes.mudancas.map((pedido) => mudanca(g, pedido));
  const comTempo = opcoes.comTempo ?? true;
  const entrada: Entrada = {
    id: opcoes.canal.wabaId,
    ...(comTempo
      ? { time: opcoes.tempo ?? BASE_DO_TEMPO + g.inteiro(30 * 24 * 60 * 60) }
      : {}),
    changes,
  };
  return { object: OBJECTO, entry: [entrada] };
}

/**
 * Um corpo com **vários `entry`**, de WABAs diferentes, num só POST.
 *
 * É o caso do critério 3 («corpo com N `entry`/`changes` misturados») e o que
 * obriga o GWY a multiplexar por `entry.id` em vez de assumir um WABA por
 * pedido. Um simulador que só produzisse um `entry` deixava esse caminho sem
 * *fixture*, e ele existe de verdade: a Meta agrupa.
 */
export function corpoMisturado(
  g: Gerador,
  partes: readonly OpcoesDoCorpo[],
): Corpo {
  return {
    object: OBJECTO,
    entry: partes.flatMap((parte) => corpo(g, parte).entry),
  };
}

/**
 * Os dois modos de serialização.
 *
 * `compacto` é o que a Meta manda. `espacado` é o **mesmo JSON** com indentação
 * — mesmas chaves, mesmos valores, mesma ordem, bytes diferentes. Ter os dois é
 * o que torna a ida e volta uma prova de que o GWY assina o corpo bruto.
 */
export const MODOS = ["compacto", "espacado"] as const;
export type Modo = (typeof MODOS)[number];

/** Os bytes de um corpo, no modo pedido. */
export function serializar(valor: unknown, modo: Modo = "compacto"): Uint8Array {
  const texto = modo === "compacto" ? JSON.stringify(valor) : JSON.stringify(valor, null, 2);
  return new Uint8Array(Buffer.from(texto, "utf8"));
}

/**
 * Os mesmos bytes com **um** alterado, sem mudar o comprimento.
 *
 * Serve o caso negativo do critério 4 pelo lado do corpo (o `assinarMal` serve-o
 * pelo lado da assinatura, e os dois têm de dar 401 pela mesma razão). Troca-se
 * um algarismo dentro de um `timestamp`, que é um sítio onde a troca mantém o
 * JSON válido: o que se quer provar é que o GWY recusa um corpo **bem formado**
 * que não bate com a assinatura, e não que recusa lixo.
 */
export function mudarUmByte(bytes: Uint8Array): Uint8Array {
  const copia = new Uint8Array(bytes);
  const zero = "0".charCodeAt(0);
  const nove = "9".charCodeAt(0);
  for (let i = 0; i < copia.length; i += 1) {
    const b = copia[i] as number;
    if (b >= zero && b <= nove) {
      copia[i] = b === nove ? zero : b + 1;
      return copia;
    }
  }
  // Um corpo sem um único algarismo não existe entre os que este módulo produz
  // (o `entry.id` é todo de algarismos), mas o ramo não fica a devolver os bytes
  // intactos: um «mudarUmByte» que não muda nada fazia o teste negativo passar
  // a verde sem testar nada.
  throw new Error(
    "mudarUmByte: o corpo nao tem nenhum algarismo para trocar, e devolver os " +
      "bytes intactos tornava o caso negativo do criterio 4 vacuo",
  );
}

/** O texto de um corpo, no modo pedido. Para escrever *fixtures* em ficheiro. */
export function texto(valor: unknown, modo: Modo = "compacto"): string {
  return Buffer.from(serializar(valor, modo)).toString("utf8");
}
