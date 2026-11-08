/**
 * A referência autenticada de um caso: o bilhete antes do OTP e a sessão depois
 * dele (KAM-086, módulo `sessao`).
 *
 * «`sessao` (cookie `httpOnly`, `SameSite=Lax`, ligado ao `onboarding_id`).»
 *
 * ## Porque é que o `onboarding_id` não anda nu
 *
 * Ele é o nome da linha, e é o que a RLS do adaptador vai usar como
 * `app.onboarding_id`. Um identificador que o cliente escolhe é um identificador
 * que o cliente troca pelo do vizinho — e o teste de isolamento do DoD («sessão
 * do caso A com o id do caso B ⇒ 404») só é passável se houver alguma coisa que
 * prenda o id a nós. Essa coisa é um HMAC.
 *
 * ## Os dois fins têm separadores de domínio diferentes, e isso é a barreira
 *
 * Há dois momentos em que o servidor devolve uma referência ao mesmo caso:
 *
 *     ticket   depois do `POST /api/registo`, para o cliente poder submeter o
 *              código. **Não autentica ninguém**: só diz de que caso é o código
 *     sessao   depois de o OTP acertar. **Autentica**: é o cookie
 *
 * Se os dois fossem a mesma cadeia, quem recebesse um bilhete punha-o no cookie
 * e ficava autenticado sem nunca ter provado posse do telefone — e no caminho de
 * recuperação do critério 8 o bilhete é entregue a **quem submeteu o
 * formulário**, que pode não ser o dono do número. Os dois separadores de
 * domínio fazem de um bilhete um valor que o verificador de sessão recusa, e
 * **essa recusa é a própria prova de posse ter de acontecer**.
 *
 * ## O anel, e o que ele custa
 *
 * Duas chaves, a actual e a anterior, pela razão do `./token.ts`: uma rotação não
 * pode expulsar quem está a meio do registo. A comparação é em tempo constante e
 * **sem sair ao primeiro acerto**.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

import { OCTETOS_DE_HMAC } from "./identificadores.ts";

/** Os dois fins de uma referência. Lista fechada — ver a nota do módulo. */
export const FINS = ["ticket", "sessao"] as const;

export type Fim = (typeof FINS)[number];

/** Separador de domínio por fim. Versionado: mudá-lo invalida as referências vivas. */
export const DOMINIOS_DE_REFERENCIA: Readonly<Record<Fim, string>> = {
  ticket: "kamba/onboarding/ticket/v1",
  sessao: "kamba/onboarding/sessao/v1",
};

/** Nome do cookie de sessão. */
export const NOME_DO_COOKIE = "kamba_onboarding";

/**
 * Os atributos do cookie, pela ordem em que saem.
 *
 * `HttpOnly` porque nenhum JavaScript da página precisa de o ler — e o que não
 * precisa de ler não deve poder. `SameSite=Lax` porque é o que o bloco escreve:
 * o registo é navegação de topo, e `Strict` partia o regresso de uma ligação
 * externa (um convite num e-mail, que é a origem `contabilista`). `Secure`
 * porque o serviço corre atrás de TLS; `Path=/` porque o caso vale para toda a
 * aplicação. **Sem `Max-Age`**: um cookie de sessão morre com o navegador, e um
 * registo a meio não é coisa para sobreviver semanas numa máquina partilhada.
 */
export const ATRIBUTOS_DO_COOKIE = "HttpOnly; Secure; SameSite=Lax; Path=/";

/** A forma de um UUID canónico. A mesma do `../logger/politica.ts`. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** Levantado quando uma referência não serve. **Nunca leva a referência.** */
export class ReferenciaInvalidaError extends Error {
  override readonly name = "ReferenciaInvalidaError";
  readonly fim: Fim;

  constructor(fim: Fim) {
    super(`referencia de ${fim} recusada`);
    this.fim = fim;
  }
}

function assinar(chave: Uint8Array, fim: Fim, id: string): Buffer {
  return createHmac("sha256", chave)
    .update(`${DOMINIOS_DE_REFERENCIA[fim]}\0`, "utf8")
    .update(id, "utf8")
    .digest();
}

/** Cunha uma referência a um caso, para este fim. `chave` é a **actual** do anel. */
export function cunharReferencia(fim: Fim, onboardingId: string, chave: Uint8Array): string {
  if (!UUID.test(onboardingId)) throw new ReferenciaInvalidaError(fim);
  if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) {
    throw new ReferenciaInvalidaError(fim);
  }
  return `${onboardingId}.${assinar(chave, fim, onboardingId).toString("base64url")}`;
}

/**
 * Lê uma referência e devolve o `onboarding_id`, ou lança.
 *
 * **O `id` sai de dentro da referência e nunca de um parâmetro ao lado.** É esta
 * linha que faz o teste de isolamento do DoD passar: não há como pedir o caso B
 * com a referência do caso A, porque a referência é a única fonte do id.
 */
export function lerReferencia(
  fim: Fim,
  bruto: unknown,
  anel: readonly (Uint8Array | null)[],
): string {
  if (typeof bruto !== "string" || bruto.length === 0 || bruto.length > 128) {
    throw new ReferenciaInvalidaError(fim);
  }
  const partes = bruto.split(".");
  if (partes.length !== 2) throw new ReferenciaInvalidaError(fim);
  const [id, assinatura] = partes as [string, string];
  if (!UUID.test(id) || !/^[A-Za-z0-9_-]+$/.test(assinatura)) {
    throw new ReferenciaInvalidaError(fim);
  }
  const recebida = Buffer.from(assinatura, "base64url");
  if (recebida.length !== OCTETOS_DE_HMAC) throw new ReferenciaInvalidaError(fim);
  let acertos = 0;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) continue;
    acertos |= timingSafeEqual(assinar(chave, fim, id), recebida) ? 1 : 0;
  }
  if (acertos !== 1) throw new ReferenciaInvalidaError(fim);
  return id;
}

/** O valor de `Set-Cookie` para uma sessão. */
export function cabecalhoDoCookie(referencia: string): string {
  return `${NOME_DO_COOKIE}=${referencia}; ${ATRIBUTOS_DO_COOKIE}`;
}

/** O valor de `Set-Cookie` que apaga a sessão. */
export function cabecalhoQueApaga(): string {
  return `${NOME_DO_COOKIE}=; ${ATRIBUTOS_DO_COOKIE}; Max-Age=0`;
}

/**
 * O valor do cookie `kamba_onboarding` num cabeçalho `Cookie`, ou `null`.
 *
 * Um leitor próprio e não uma biblioteca: o que se precisa é de um nome exacto
 * num cabeçalho, e trazer um analisador de cookies para isso era uma dependência
 * nova num serviço que o bloco manda ter CSP estrita e superfície mínima. A
 * forma do valor é verificada pelo `lerReferencia`, que é onde ela importa.
 */
export function cookieDoCabecalho(cabecalho: unknown): string | null {
  if (typeof cabecalho !== "string") return null;
  for (const par of cabecalho.split(";")) {
    const corte = par.indexOf("=");
    if (corte < 0) continue;
    if (par.slice(0, corte).trim() !== NOME_DO_COOKIE) continue;
    const valor = par.slice(corte + 1).trim();
    return valor === "" ? null : valor;
  }
  return null;
}
