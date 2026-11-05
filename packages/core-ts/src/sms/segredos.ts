/**
 * Os segredos do SMS, lidos do cofre, com anel de duas chaves (KAM-116,
 * critério 7).
 *
 * «Credenciais e segredo do recibo no cofre (`SecretProvider`, KAM-010), com
 * anel de duas chaves para rotação; nenhum segredo em código ou imagem.»
 *
 * Três segredos, e cada um está no inventário (`ops/secrets-inventory.yaml`):
 *
 *     sms_agregador_credencial   a credencial de API do agregador
 *     sms_recibo_segredo         o segredo com que o agregador assina recibos
 *     pepper_sms_destino         a chave do HMAC do destino (`destino.ts`)
 *
 * **Os três `id` vivem no `refs.ts` e não aqui**, e a razão está lá: uma
 * referência de segredo tem por força a forma que o `scan_secrets` apanha, e a
 * dispensa de `ci/secrets-allow.yaml` fica num ficheiro sem lógica nenhuma — de
 * modo que **este**, que é onde um valor de segredo passa pelas mãos do código,
 * continua inteiramente varrido. É o desenho do `../onboarding/segredos.ts`.
 *
 * ## Os três têm anel, e os três por razões diferentes
 *
 * A **credencial** tem anel porque uma rotação de credencial sem janela é um
 * corte de serviço: durante a troca, o agregador pode já ter a nova e nós ainda
 * a antiga, ou o contrário. Quem envia tenta a actual e, no `PROVIDER_DOWN` ou
 * no 401, a anterior — e isso é do adaptador, que sabe o que o agregador
 * devolve.
 *
 * O **segredo do recibo** tem anel pela razão que o KAM-013 escreveu para a
 * Meta: durante uma rotação chegam corpos assinados com o segredo antigo, e
 * recusá-los dava 401 a tráfego legítimo. O `../entrada/assinatura.ts` aceita
 * os dois do anel, e o `recibo.ts` passa-lho tal como vem.
 *
 * O **pepper do destino** tem anel para que um HMAC escrito antes de uma
 * rotação continue a ser reconhecível depois dela — é o que o
 * `destinoCorresponde` faz, e é o que mantém legível o relatório de entrega do
 * critério 2 ao longo de uma rotação.
 *
 * ## O que este ficheiro não faz
 *
 * Não lê o ambiente directamente e não tem valor por omissão nenhum. Recebe um
 * `SecretProvider` e pede-lhe as referências: é o cofre que decide de onde vêm
 * os valores (`docs/adr/ADR-L002-injeccao-de-segredos.md`), e um valor por
 * omissão aqui era um segredo em código — exactamente o que o critério 7
 * proíbe. Um segredo em falta levanta `SecretAusenteError`, com o nome do
 * segredo e **nunca** o valor.
 */

import type { SecretProvider, SecretRingTuple } from "../secrets/port.ts";
import { OCTETOS_DE_HMAC } from "./destino.ts";
import { REF_CREDENCIAL, REF_PEPPER, REF_RECIBO } from "./refs.ts";

/** Levantado quando o valor do *pepper* não tem a forma de uma chave. */
export class PepperMalFormadoError extends Error {
  override readonly name = "PepperMalFormadoError";
  readonly versao: "actual" | "anterior";

  constructor(versao: "actual" | "anterior", octetos: number) {
    // Octetos e nao valor: a mensagem de um segredo mal formado e exactamente
    // onde um segredo mal formado nao pode aparecer.
    super(
      `${REF_PEPPER} (${versao}) tem ${octetos} octetos depois de base64; ` +
        `esperava ${OCTETOS_DE_HMAC}`,
    );
    this.versao = versao;
  }
}

const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

/**
 * Descodifica uma chave de 32 octetos de base64, ou levanta.
 *
 * O `Buffer.from(x, "base64")` do Node **não levanta** com texto inválido:
 * ignora o que não cabe no alfabeto e devolve o que conseguiu. Um *pepper*
 * trocado por uma frase devolvia uma chave curta, e o HMAC saía com uma chave
 * que ninguém escolheu. Daí a verificação do alfabeto **e** do comprimento.
 */
function chaveDeBase64(valor: string, versao: "actual" | "anterior"): Uint8Array {
  const limpo = valor.trim();
  if (!BASE64.test(limpo)) throw new PepperMalFormadoError(versao, 0);
  const bytes = Buffer.from(limpo, "base64");
  if (bytes.length !== OCTETOS_DE_HMAC) throw new PepperMalFormadoError(versao, bytes.length);
  return bytes;
}

/** O anel do *pepper* do destino: a actual primeiro, a anterior ou `null`. */
export async function anelDoPepper(
  segredos: SecretProvider,
): Promise<readonly [Uint8Array, Uint8Array | null]> {
  const [actual, anterior] = await segredos.getRing(REF_PEPPER); // kamba:secrets-inventory dinamico a constante REF_PEPPER deste ficheiro e o dono do nome em codigo
  return [
    chaveDeBase64(actual, "actual"),
    anterior === null ? null : chaveDeBase64(anterior, "anterior"),
  ];
}

/** O anel do segredo do recibo, na forma que o `recibo.ts` consome. */
export async function anelDoRecibo(segredos: SecretProvider): Promise<SecretRingTuple> {
  return segredos.getRing(REF_RECIBO); // kamba:secrets-inventory dinamico a constante REF_RECIBO deste ficheiro e o dono do nome em codigo
}

/** O anel da credencial do agregador. */
export async function anelDaCredencial(segredos: SecretProvider): Promise<SecretRingTuple> {
  return segredos.getRing(REF_CREDENCIAL); // kamba:secrets-inventory dinamico a constante REF_CREDENCIAL deste ficheiro e o dono do nome em codigo
}
