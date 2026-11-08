/**
 * Os segredos da inscrição, lidos do cofre, com anel de duas chaves (KAM-086).
 *
 * Dois segredos, os dois no inventário (`ops/secrets-inventory.yaml`,
 * `introduzido_por: KAM-086`), e os dois `id` vivem no `./refs.ts` — ver a nota
 * de lá. A forma deste ficheiro é a do `../sms/segredos.ts`, e as duas
 * verificações que ele faz não são zelo:
 *
 * ## Porque é que o alfabeto se verifica, e não só o comprimento
 *
 * O `Buffer.from(x, "base64")` do Node **não levanta** com texto inválido:
 * ignora o que não cabe no alfabeto e devolve o que conseguiu. Um *pepper*
 * trocado por uma frase devolvia uma chave curta, e o HMAC saía com uma chave
 * que ninguém escolheu — e, pior, saía **determinístico**, pelo que os HMAC
 * continuavam a casar entre si e nada acusava. A lição é do KAM-116 e aplica-se
 * igual.
 *
 * E o alfabeto é **base64 padrão**, com `base64url` recusado, pela razão que o
 * inventário escreve para a `pepper_sms_destino`: o Node aceita os dois e
 * devolve os mesmos octetos, e o mesmo segredo escrito de duas maneiras era o
 * mesmo segredo com duas grafias — logo duas entradas de cofre que ninguém
 * consegue comparar.
 *
 * ## Os dois têm anel, por razões diferentes
 *
 * O ***pepper*** tem anel para que um HMAC escrito antes de uma rotação continue
 * reconhecível depois dela: é o que o `hmacCorresponde` do
 * `./identificadores.ts` faz, e é o que mantém o índice único de `nif_hmac` a
 * ver os duplicados que já lá estavam.
 *
 * A ***assinatura*** tem anel porque um convite impresso num anúncio ou mandado
 * por um contabilista vive semanas, e um dono a meio do registo não pode ser
 * expulso por uma rotação. O `./token.ts` e o `./sessao.ts` aceitam as duas
 * chaves, em tempo constante e sem sair ao primeiro acerto.
 *
 * ## O que este ficheiro não faz
 *
 * Não lê o ambiente e **não tem valor por omissão nenhum**. Recebe um
 * `SecretProvider` e pede-lhe as referências: é o cofre que decide de onde vêm
 * os valores (`docs/adr/ADR-L002-injeccao-de-segredos.md`), e um valor por
 * omissão aqui era um segredo em código. Um segredo em falta levanta
 * `SecretAusenteError`, com o nome e **nunca** o valor.
 */

import type { SecretRingTuple } from "../secrets/port.ts";

import { OCTETOS_DE_HMAC } from "./identificadores.ts";
import { REF_ASSINATURA, REF_PEPPER } from "./refs.ts";

/** Um anel de duas chaves: a actual primeiro, a anterior ou `null`. */
export type Anel = readonly [Uint8Array, Uint8Array | null];

/**
 * O que estas funções precisam de saber ler. **Mais estreito do que a
 * `SecretProvider`, e de propósito.**
 *
 * Quem arranca um serviço não tem uma `SecretProvider` na mão: tem o `Secrets`
 * do `../secrets/arranque.ts`, que é o objecto que **já provou** que os
 * segredos obrigatórios existem e que mantém o último valor conhecido durante
 * a janela de tolerância. Ele tem `get` e `getRing` e **não** tem `nome` nem
 * `health` — não é um provedor, é quem fala com um. Exigir a porta inteira aqui
 * obrigava o arranque a passar o provedor nu, e então as três regras do
 * `Secrets.arrancar` deixavam de valer para estas leituras.
 */
export interface LeitorDeAnel {
  getRing(ref: string): Promise<SecretRingTuple>;
}

/** Levantado quando o valor de um segredo não tem a forma de uma chave. */
export class ChaveMalFormadaError extends Error {
  override readonly name = "ChaveMalFormadaError";
  readonly referencia: string;
  readonly versao: "actual" | "anterior";

  constructor(referencia: string, versao: "actual" | "anterior", octetos: number) {
    // Octetos e nao valor: a mensagem de um segredo mal formado e exactamente
    // onde um segredo mal formado nao pode aparecer.
    super(
      `${referencia} (${versao}) tem ${octetos} octetos depois de base64; ` +
        `esperava ${OCTETOS_DE_HMAC}`,
    );
    this.referencia = referencia;
    this.versao = versao;
  }
}

const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

function chaveDeBase64(
  valor: string,
  referencia: string,
  versao: "actual" | "anterior",
): Uint8Array {
  const limpo = valor.trim();
  if (!BASE64.test(limpo)) throw new ChaveMalFormadaError(referencia, versao, 0);
  const bytes = Buffer.from(limpo, "base64");
  if (bytes.length !== OCTETOS_DE_HMAC) {
    throw new ChaveMalFormadaError(referencia, versao, bytes.length);
  }
  return bytes;
}

async function anel(segredos: LeitorDeAnel, referencia: string): Promise<Anel> {
  const [actual, anterior] = await segredos.getRing(referencia); // kamba:secrets-inventory dinamico as constantes de ./refs.ts sao as donas dos nomes em codigo
  return [
    chaveDeBase64(actual, referencia, "actual"),
    anterior === null ? null : chaveDeBase64(anterior, referencia, "anterior"),
  ];
}

/** O anel do *pepper* dos identificadores. Ver `./identificadores.ts`. */
export async function anelDoPepper(segredos: LeitorDeAnel): Promise<Anel> {
  return anel(segredos, REF_PEPPER);
}

/** O anel da chave de assinatura. Ver `./token.ts` e `./sessao.ts`. */
export async function anelDaAssinatura(segredos: LeitorDeAnel): Promise<Anel> {
  return anel(segredos, REF_ASSINATURA);
}
