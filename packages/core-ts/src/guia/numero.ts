/**
 * O número ligado é o do dono? (KAM-093, critério 4.)
 *
 * «Após `code`, o número devolvido (`display_phone_number`) tem de coincidir,
 * normalizado, com o telefone provado por OTP.»
 *
 * ## Compara-se por HMAC, e não por texto
 *
 * O caso guarda o `telefoneHmac` e **não** o número: o `RepositorioDeCasos` só
 * devolve o telefone em claro por uma operação, e a nota do `ComHmac` conta os
 * sítios onde ele se revela. Aqui não é preciso: normaliza-se o número que a
 * Meta devolveu, calcula-se o HMAC com o anel do *pepper* e compara-se em
 * tempo constante com o do caso — o `hmacCorresponde` da inscrição, que já
 * procura com as duas chaves do anel. Uma rotação do *pepper* entre o OTP e o
 * ES não faz o número legítimo parecer alheio.
 *
 * ## O que não se normaliza é divergência, e não erro
 *
 * O `display_phone_number` vem formatado pela Meta («+244 9.. ... ...», com
 * espaços e `+`, como o `tools/meta-sim/src/captura.ts` anota). O
 * `normalizarTelefone` da inscrição lê essa forma; o que ele **recusa** — um
 * indicativo que não é +244, texto vazio, algarismos de outro alfabeto — é um
 * número que não pode ser o que o dono provou, porque esse passou pelo mesmo
 * normalizador. Responde-se `false` e não se lança: quem chama tem de bloquear,
 * e um `throw` era uma forma de o esquecer.
 */

import {
  DOMINIOS,
  IdentificadorInvalidoError,
  hmacCorresponde,
  normalizarTelefone,
} from "../inscricao/identificadores.ts";

export function numeroCoincide(
  displayPhoneNumber: unknown,
  telefoneHmacDoCaso: string,
  anelDoPepper: readonly (Uint8Array | null)[],
): boolean {
  let e164: string;
  try {
    e164 = normalizarTelefone(displayPhoneNumber);
  } catch (erro) {
    if (erro instanceof IdentificadorInvalidoError) return false;
    throw erro;
  }
  return hmacCorresponde(telefoneHmacDoCaso, DOMINIOS.telefone, e164, anelDoPepper);
}
