/**
 * O recibo de abertura de um documento (KAM-090, critério 2).
 *
 * «O ecrã de aceite mostra o texto integral da versão vigente; só activa o
 * botão depois de abrir os 3 documentos.» O botão é do navegador, e um cliente
 * adulterado activa-o sem abrir nada — o caso adversarial do bloco. O que o
 * servidor pode exigir é **prova de que serviu o texto**: quando entrega uma
 * versão a um caso, entrega com ela um recibo, e o aceite exige os recibos.
 *
 * ## É um valor autenticado, e não uma linha
 *
 * O recibo é o HMAC de `(onboarding_id, document_id, sha256)` com uma chave do
 * servidor, como o convite do `../inscricao/token.ts`. Não cria estado, e por
 * isso não custa tabela: quem não abriu o documento não tem o recibo, e não o
 * consegue fabricar sem a chave. Fica preso ao **caso** (o recibo de um caso
 * não serve noutro) e ao **texto** (o recibo de uma versão não serve noutra,
 * nem a mesma versão com outro resumo).
 *
 * **O que ele não prova** é que alguém leu: prova que o servidor entregou o
 * texto integral àquele caso. É o que o critério pede, e é o mais que um
 * servidor consegue afirmar.
 *
 * O anel de duas chaves e a verificação sem sair ao primeiro acerto são os do
 * convite, pela mesma razão: rodar a chave a meio de um onboarding não pode
 * deitar fora os recibos já entregues.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

/** Separador de domínio do HMAC do recibo. Versionado. */
export const DOMINIO_DO_RECIBO = "kamba/contratos/abertura/v1";

/** Octetos de uma chave do anel. */
export const OCTETOS_DA_CHAVE = 32;

/** O que um recibo cobre. */
export interface Abertura {
  readonly onboardingId: string;
  readonly documentId: string;
  readonly sha256: Uint8Array;
}

function mensagem(abertura: Abertura): string {
  return [
    DOMINIO_DO_RECIBO,
    abertura.onboardingId.toLowerCase(),
    abertura.documentId.toLowerCase(),
    Buffer.from(abertura.sha256).toString("hex"),
  ].join("\u0000");
}

function assinar(chave: Uint8Array, abertura: Abertura): Buffer {
  return createHmac("sha256", chave).update(mensagem(abertura), "utf8").digest();
}

/** Emite o recibo, com a primeira chave do anel. */
export function emitirRecibo(chave: Uint8Array, abertura: Abertura): string {
  if (chave.length !== OCTETOS_DA_CHAVE) throw new Error("a chave do recibo tem 32 octetos");
  return assinar(chave, abertura).toString("base64url");
}

/**
 * `true` se o recibo é de uma das chaves do anel para esta abertura.
 *
 * Corre as duas chaves sempre: sair ao primeiro acerto dizia, pelo tempo, qual
 * das chaves assinou.
 */
export function reciboValido(
  recibo: unknown,
  abertura: Abertura,
  anel: readonly (Uint8Array | null)[],
): boolean {
  if (typeof recibo !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(recibo)) return false;
  const recebido = Buffer.from(recibo, "base64url");
  let acertos = 0;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DA_CHAVE) continue;
    acertos |= timingSafeEqual(assinar(chave, abertura), recebido) ? 1 : 0;
  }
  return acertos === 1;
}
