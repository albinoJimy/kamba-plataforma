/**
 * A assinatura dos webhooks da Meta (KAM-013).
 *
 * `X-Hub-Signature-256: sha256=<HMAC-SHA256 do corpo bruto com o App Secret>`
 * — **CONFIRMADO**, fonte primária (`evidencia/E1` §5,
 * `DOC/webhooks/create-webhook-endpoint`, Jun 17, 2026). Validar e responder
 * 200; senão 4xx.
 *
 * ## Está em `core-ts` e não no `gwy`, e a razão não é arrumação
 *
 * O mesmo cálculo volta em dois sítios já nomeados no backlog: o KAM-056
 * (*callbacks* HMAC do ProxyPay) e o KAM-072 (rotação de chaves Meta,
 * facilitador e HMAC), que dependem os dois deste ticket. Uma segunda
 * implementação de uma comparação em tempo constante é a classe de duplicação
 * que se paga com um defeito de segurança, não com ruído.
 *
 * ## Quatro coisas que este módulo faz de propósito
 *
 * 1. **A assinatura é sobre os bytes recebidos, antes de `JSON.parse`.** É a
 *    letra do critério 2 do ticket, e o teste que a prende é o do corpo
 *    re-serializado: `{"a":1}` e `{ "a": 1 }` têm o mesmo significado, o mesmo
 *    `JSON.parse` e assinaturas **diferentes**. Por isso a função recebe
 *    `Uint8Array` e nunca texto — um `string` aqui seria um convite a assinar o
 *    que o `JSON.stringify` devolveu em vez do que chegou.
 * 2. **Aceita o segredo actual ou o anterior** (*ring*). A Meta re-entrega
 *    durante sete dias (`E1` §5): durante uma rotação chegam corpos assinados
 *    com o segredo antigo, e recusá-los dava 401 a tráfego legítimo com a
 *    repetição a durar uma semana. O `anterior` pode ser `null` — nunca houve
 *    rotação — e isso **não é erro**, é «só há uma» (`secrets/port.ts`).
 * 3. **Compara em tempo constante, e sem sair ao primeiro acerto.** O
 *    `timingSafeEqual` é por candidato, e o resultado acumula-se num `OR`
 *    bit-a-bit: um `return` dentro do ciclo dizia pelo tempo de resposta
 *    *qual* dos dois segredos acertou, que é informação sobre o estado da
 *    rotação que não precisa de sair.
 * 4. **A forma do cabeçalho valida-se antes da comparação.** O
 *    `timingSafeEqual` do Node **lança** se os dois buffers tiverem
 *    comprimentos diferentes, e um cabeçalho de atacante tem o comprimento que
 *    ele quiser. O comprimento de um resumo SHA-256 não é segredo — são sempre
 *    32 bytes —, pelo que recusar pela forma não revela nada.
 */

import { createHash, createHmac, timingSafeEqual } from "node:crypto";

/** O cabeçalho onde a Meta põe a assinatura. Minúsculas: é como o Hono o lê. */
export const CABECALHO_DA_ASSINATURA = "x-hub-signature-256";

/** O prefixo obrigatório do valor do cabeçalho. */
export const PREFIXO_DA_ASSINATURA = "sha256=";

/** Um resumo SHA-256 em hexadecimais tem 64 caracteres; em bytes, 32. */
export const RESUMO_BYTES = 32;
const RESUMO_HEX = /^[0-9a-f]{64}$/;

/** O resumo SHA-256 dos bytes, em hexadecimais minúsculos. É o `jobId`. */
export function sha256Hex(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

/**
 * Os 32 bytes do cabeçalho, ou `null` se ele não tiver a forma de uma.
 *
 * Exportada porque é o que distingue «não assinou» de «assinou mal», e o
 * critério 2 trata as duas da mesma maneira (401) mas o registo não: um
 * cabeçalho ausente é um pedido que não vem da Meta, e um cabeçalho malformado
 * em volume é sondagem.
 */
export function resumoDoCabecalho(cabecalho: string | undefined): Buffer | null {
  if (typeof cabecalho !== "string") return null;
  // Sem `trim()` e sem tolerância de maiúsculas: a Meta escreve
  // `sha256=<hex minúsculo>`, e aceitar variantes é aceitar mais superfície do
  // que a fonte primária descreve.
  if (!cabecalho.startsWith(PREFIXO_DA_ASSINATURA)) return null;
  const hex = cabecalho.slice(PREFIXO_DA_ASSINATURA.length);
  if (!RESUMO_HEX.test(hex)) return null;
  return Buffer.from(hex, "hex");
}

/** O HMAC-SHA256 do corpo com um segredo, em bytes. */
function hmac(bytes: Uint8Array, segredo: string): Buffer {
  return createHmac("sha256", segredo).update(bytes).digest();
}

/**
 * O corpo está assinado com algum dos segredos do anel?
 *
 * `anel` é `[actual, anterior]`, como o `Secrets.getRing` devolve. Um segredo
 * `null` ou vazio **nunca** valida: um anel mal configurado recusa tudo, em vez
 * de aceitar tudo — é a direcção certa para falhar.
 *
 * @param corpo os bytes **recebidos**, antes de qualquer `parse`
 * @param cabecalho o valor de `X-Hub-Signature-256`, tal como chegou
 * @param anel `[actual, anterior]`; o `anterior` pode ser `null`
 */
export function assinaturaValida(
  corpo: Uint8Array,
  cabecalho: string | undefined,
  anel: readonly (string | null)[],
): boolean {
  const recebido = resumoDoCabecalho(cabecalho);
  if (recebido === null) return false;

  // O acumulador é um número e não um `boolean`: um `||` em JavaScript
  // curto-circuita, e curto-circuitar é precisamente o que o ponto 3 da
  // docstring não quer.
  let acertos = 0;
  for (const segredo of anel) {
    if (typeof segredo !== "string" || segredo === "") continue;
    const esperado = hmac(corpo, segredo);
    // Os dois têm 32 bytes — o `esperado` por construção, o `recebido` porque
    // o `resumoDoCabecalho` só devolve 64 hexadecimais —, pelo que o
    // `timingSafeEqual` não lança.
    acertos |= timingSafeEqual(esperado, recebido) ? 1 : 0;
  }
  return acertos === 1;
}
