/**
 * O `kid` de uma versão de segredo, lido do próprio valor (KAM-205).
 *
 * ## O defeito que isto fecha
 *
 * O `EnvSecretProvider` e o `DopplerSecretProvider` só vêem duas variáveis —
 * `KAMBA_SECRET_<X>` e `KAMBA_SECRET_<X>_ANTERIOR` — e o `versions()` deles
 * devolvia os rótulos **posicionais** `actual` e `anterior`. Um rótulo
 * posicional muda de valor numa rotação: o que era `actual` passa a ser a chave
 * nova. Quem guardou o rótulo ao lado de um dado — o criptograma dos *tokens* de
 * cliente (KAM-016) — deixou de o conseguir abrir depois de rodar a KEK.
 *
 * ## A regra
 *
 * Uma versão traz o `kid` **dentro do valor**, na forma `<kid>:<base64 de 32
 * octetos>` que o `identity/chaves.ts` (KAM-008) e o `segredo_intents` (KAM-051)
 * já usam. O `kid` vai com o valor quando o operador o move de `KAMBA_SECRET_X`
 * para `KAMBA_SECRET_X_ANTERIOR`, e é por isso que é estável: não há segunda
 * variável que possa ficar para trás.
 *
 * Um valor **sem** essa forma não tem identidade que um provedor de ambiente
 * consiga ler, e continua a receber o rótulo posicional. É o caso de todos os
 * segredos com `kid: false` no inventário (o App Secret, as senhas de base de
 * dados): nenhum consumidor guarda o `kid` deles, e para eles o rótulo é
 * inofensivo. **Para quem guarda o `kid`, um rótulo posicional é recusado** — é
 * o que o `onboarding` faz antes de cifrar.
 *
 * ## Porque é que a forma é estrita
 *
 * Só conta como `<kid>:<valor>` o texto cujo resto seja base64 de exactamente
 * 32 octetos. Com uma forma solta, uma senha `utilizador:segredo` daria o `kid`
 * `utilizador` — um pedaço do valor a sair por `versions()`, que é uma superfície
 * que se regista. Com a forma estrita, um valor que não é uma chave nossa nunca
 * é partido.
 *
 * **Nenhum erro deste ficheiro leva o valor**: nomeia a referência e o `kid`.
 */

import { Buffer } from "node:buffer";

/** Os rótulos posicionais que um provedor de ambiente dá a um valor sem `kid`. */
export const ROTULOS_POSICIONAIS = ["actual", "anterior"] as const;

/** Octetos da chave que segue o `kid`: AES-256 e HMAC-SHA256. */
export const OCTETOS_DA_CHAVE_VERSIONADA = 32;

/** A forma do `kid`: a mesma do `identity/chaves.ts` e do `keyring/anel.ts`. */
const KID = /^[a-z0-9][a-z0-9_.-]{0,62}$/;
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

/** Duas versões vivas com o mesmo `kid`: tudo o que o guarda fica ambíguo. */
export class KidRepetidoNoCofreError extends Error {
  override readonly name = "KidRepetidoNoCofreError";
  readonly ref: string;
  readonly kid: string;

  constructor(ref: string, kid: string) {
    super(`a versão actual e a anterior de ${ref} têm o mesmo kid ${kid}`);
    this.ref = ref;
    this.kid = kid;
  }
}

/** `true` se `rotulo` é um dos rótulos posicionais, e portanto não é estável. */
export function rotuloPosicional(rotulo: string): boolean {
  return (ROTULOS_POSICIONAIS as readonly string[]).includes(rotulo);
}

/**
 * Separa `<kid>:<base64>`. Devolve `null` quando o valor não tem essa forma.
 *
 * Um `kid` igual a um rótulo posicional também dá `null`: `actual:<chave>`
 * tornava indistinguível uma versão estável de uma posição, e é exactamente essa
 * confusão que o KAM-205 fecha.
 */
export function separarKid(valor: string): { readonly kid: string; readonly chave: string } | null {
  const corte = valor.indexOf(":");
  if (corte === -1) return null;
  const kid = valor.slice(0, corte);
  const chave = valor.slice(corte + 1);
  if (!KID.test(kid) || rotuloPosicional(kid)) return null;
  if (!BASE64.test(chave) || chave.length % 4 !== 0) return null;
  if (Buffer.from(chave, "base64").byteLength !== OCTETOS_DA_CHAVE_VERSIONADA) return null;
  return { kid, chave };
}

/** O `kid` que o valor traz, ou `null`. */
export function kidDoValor(valor: string): string | null {
  return separarKid(valor)?.kid ?? null;
}

/** A chave sem o `kid`: o texto depois de `<kid>:`, ou o valor inteiro se não o tiver. */
export function chaveDoValor(valor: string): string {
  return separarKid(valor)?.chave ?? valor;
}

/**
 * Os identificadores de `[actual, anterior]`, pela ordem do contrato.
 *
 * Cada posição dá o `kid` do seu valor; só um valor sem `kid` cai no rótulo da
 * posição. Duas versões com o mesmo `kid` são recusadas, como no
 * `identity/chaves.ts`.
 */
export function kidsDasVersoes(
  ref: string,
  actual: string,
  anterior: string | null,
): readonly string[] {
  const kids = [kidDoValor(actual) ?? ROTULOS_POSICIONAIS[0]];
  if (anterior !== null) {
    const kid = kidDoValor(anterior) ?? ROTULOS_POSICIONAIS[1];
    if (kid === kids[0]) throw new KidRepetidoNoCofreError(ref, kid);
    kids.push(kid);
  }
  return kids;
}
