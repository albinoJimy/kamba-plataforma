/**
 * Os identificadores sintéticos de um corpo da Meta (KAM-024).
 *
 * Todos saem do gerador determinístico, e nenhum é real. Três têm forma que
 * importa e por isso não se inventa:
 *
 * - **`wamid`** — a Meta escreve `wamid.<base64url>`, e o que vai no base64
 *   **inclui o número do interlocutor** (INDÍCIO, `docs/logs.md` §2.1). O
 *   simulador reproduz essa forma de propósito: se gerasse um `wamid` opaco, as
 *   *fixtures* não exercitavam o caminho que o `idOpaco` do KAM-068 existe para
 *   fechar, e um defeito de privacidade passava pelas *fixtures* sem aparecer.
 *   O número que lá vai é do intervalo fictício.
 * - **`waba_id` e `phone_number_id`** — identificadores opacos e curtos da Meta
 *   (`E1` §5). O `CHECK` da revisão `0008` limita-os a 64 caracteres, e o
 *   simulador fica muito abaixo.
 * - **`user_id` (BSUID)** — único por par portfólio–utilizador (CONFIRMADO,
 *   `E1` §3). A forma `AO.<alfanuméricos>` é a que o `bsuidDeEnsaio` de
 *   `packages/core-ts/tests_bd/apoio.ts` já usa; herda-se.
 */

import { ALGARISMOS, INDICATIVO_FICTICIO } from "./numeros.ts";
import type { Gerador } from "./semente.ts";

const DIGITOS = "0123456789";
const ALFANUMERICOS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

/** Um telefone do intervalo fictício, em E.164 sem `+`. */
export function telefone(g: Gerador): string {
  // O primeiro algarismo não é zero: um número com zero à cabeça não tem a
  // forma de um móvel, e o que se quer é forma real com valor fictício.
  const primeiro = String(1 + g.inteiro(9));
  return INDICATIVO_FICTICIO + primeiro + g.texto(ALGARISMOS - 1, DIGITOS);
}

/** Um `waba_id`: quinze algarismos, como os que a Meta atribui. */
export function wabaId(g: Gerador): string {
  return "10" + g.texto(13, DIGITOS);
}

/** Um `phone_number_id`: quinze algarismos, de outro prefixo. */
export function phoneNumberId(g: Gerador): string {
  return "12" + g.texto(13, DIGITOS);
}

/** Um BSUID, na forma `AO.` + alfanuméricos (`E1` §3). */
export function bsuid(g: Gerador): string {
  return `AO.${g.texto(24, ALFANUMERICOS)}`;
}

/**
 * Um `wamid` com a forma da Meta: `wamid.` + base64url de bytes que **incluem**
 * o telefone.
 *
 * O base64 é calculado sem `=` de preenchimento e sem `+`/`/`, que é a forma
 * que a Meta usa. O conteúdo é `<telefone>|<16 hex>`: o telefone para que a
 * *fixture* exercite o caminho do `idOpaco`, e o resto para a unicidade.
 */
export function wamid(g: Gerador, numero: string): string {
  const miolo = `${numero}|${g.texto(16, "0123456789abcdef")}`;
  const base64 = Buffer.from(miolo, "utf8")
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `wamid.${base64}`;
}

/** O nome de exibição de um contacto. Nunca o nome de uma pessoa real. */
export function nomeDeExibicao(g: Gerador): string {
  // Nomes de **negócio** fictícios, não de pessoa singular: é o que um
  // `profile.name` traz num corpo de PME, e o que o inventário de colunas
  // chama «nome do negocio, nao de pessoa singular».
  const primeiros = ["Loja", "Mercearia", "Boutique", "Padaria", "Farmacia", "Quiosque"];
  const segundos = ["Ensaio", "Exemplo", "Fixture", "Amostra", "Sintetica", "Modelo"];
  return `${g.escolher(primeiros)} ${g.escolher(segundos)} ${g.texto(3, DIGITOS)}`;
}

/** O conjunto de identificadores de um canal de ensaio. */
export interface Canal {
  readonly wabaId: string;
  readonly phoneNumberId: string;
  /** O número do negócio, como a Meta o mostra em `metadata`. */
  readonly displayPhoneNumber: string;
}

/** Um canal de ensaio, estável para uma semente. */
export function canalDe(g: Gerador): Canal {
  return {
    wabaId: wabaId(g),
    phoneNumberId: phoneNumberId(g),
    displayPhoneNumber: telefone(g),
  };
}

/** O conjunto de identificadores de um interlocutor de ensaio. */
export interface Interlocutor {
  /** `wa_id`/`from`: o telefone. Pode faltar quando há *username* (`E1` §3). */
  readonly waId: string;
  /** `user_id`/`from_user_id`: o BSUID. */
  readonly userId: string;
  readonly nome: string;
}

/** Um interlocutor de ensaio, estável para uma semente. */
export function interlocutorDe(g: Gerador): Interlocutor {
  return { waId: telefone(g), userId: bsuid(g), nome: nomeDeExibicao(g) };
}
