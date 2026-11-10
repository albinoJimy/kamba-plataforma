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

import type { Relogio } from "./contrato.ts";
import { OCTETOS_DE_HMAC } from "./identificadores.ts";

/** Os três fins de uma referência. Lista fechada — ver a nota do módulo. */
export const FINS = ["ticket", "sessao", "retoma"] as const;

export type Fim = (typeof FINS)[number];

/** Separador de domínio por fim. Versionado: mudá-lo invalida as referências vivas. */
export const DOMINIOS_DE_REFERENCIA: Readonly<Record<Fim, string>> = {
  ticket: "kamba/onboarding/ticket/v1",
  sessao: "kamba/onboarding/sessao/v1",
  retoma: "kamba/onboarding/retoma/v1",
};

/** Nome do cookie de sessão. */
export const NOME_DO_COOKIE = "kamba_onboarding";

/**
 * Validade de um bilhete, em segundos. ***Proposta***: 30 minutos.
 *
 * **Um bilhete sem validade era eterno, e isso era um achado.** Ele é entregue a
 * quem submeteu o formulário — que no caminho de recuperação do critério 8 pode
 * não ser o dono do número — e o `/api/otp/reenviar` aceita-o. Sem validade,
 * quem conhecesse o NIF de um negócio guardava o bilhete **para sempre** e
 * mandava SMS ao dono dele até ao tecto de três por hora, indefinidamente,
 * destruindo de cada vez o desafio vivo da vítima. O tecto de três por hora
 * continua a ser o limite real do volume; o que esta validade fecha é a
 * **conveniência** de o fazer sem voltar a passar pelo formulário e pela prova
 * de trabalho. Achado da revisão adversarial.
 *
 * Trinta minutos é o que um dono precisa para receber um SMS, procurá-lo e
 * escrevê-lo, com folga para um reenvio. O TTL do código são cinco minutos.
 */
export const VALIDADE_DO_BILHETE_S = 1_800;

/**
 * Validade de uma sessão, em segundos. ***Proposta***: 24 horas.
 *
 * **Também ela era eterna, e também isso foi um achado.** O cookie não leva
 * `Max-Age`, pelo que a *instância* no navegador morre com ele — mas o
 * **valor** era válido para sempre, e um valor que escape (um registo, um
 * histórico, uma máquina partilhada) autenticava o caso indefinidamente, sem
 * forma de o invalidar a não ser rodar a chave e expulsar todos. Vinte e
 * quatro horas é mais do que um registo inteiro leva, e é a janela em que um
 * valor fugido ainda vale algo.
 */
export const VALIDADE_DA_SESSAO_S = 86_400;

/**
 * Validade de uma ligação de retoma, em segundos. ***Proposta***: 30 dias (KAM-093).
 *
 * **É o terceiro fim, e também não autentica ninguém.** É a ligação que vai num
 * SMS ou num e-mail ao dono quando o canal cai (`PARTNER_REMOVED`, critério 7)
 * ou quando o popup ficou a meio (critério 5): diz **de que caso** é a página, e
 * a página continua a exigir a `sessao`. Um separador próprio impede que uma
 * ligação que viajou por SMS sirva de cookie — que era o defeito do bilhete que
 * o KAM-086 fechou, pela mesma porta. Trinta dias porque o aviso de inactividade
 * sai aos dez, e o dono pode ler o SMS semanas depois.
 */
export const VALIDADE_DA_RETOMA_S = 2_592_000;

/**
 * Validade por fim, em segundos. `0` quer dizer **sem validade**, e hoje
 * **nenhum fim o usa**: a forma da referência admite-o, e dizê-lo é mais
 * honesto do que fingir que não é representável.
 */
export const VALIDADES: Readonly<Record<Fim, number>> = {
  ticket: VALIDADE_DO_BILHETE_S,
  sessao: VALIDADE_DA_SESSAO_S,
  retoma: VALIDADE_DA_RETOMA_S,
};

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

function assinar(chave: Uint8Array, fim: Fim, texto: string): Buffer {
  return createHmac("sha256", chave)
    .update(`${DOMINIOS_DE_REFERENCIA[fim]}\0`, "utf8")
    .update(texto, "utf8")
    .digest();
}

/**
 * Cunha uma referência a um caso, para este fim. `chave` é a **actual** do anel.
 *
 * A forma é `<uuid>.<segundos>.<hmac>`, e os `<segundos>` são o fim da validade.
 * **Estão dentro do texto assinado**, pelo que o cliente pode repetir a
 * referência e não pode prolongá-la — é o mesmo argumento do `emitidoEm` do
 * `./antiabuso.ts`.
 */
export function cunharReferencia(
  fim: Fim,
  onboardingId: string,
  chave: Uint8Array,
  agora: Relogio = () => new Date(),
): string {
  if (!UUID.test(onboardingId)) throw new ReferenciaInvalidaError(fim);
  if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) {
    throw new ReferenciaInvalidaError(fim);
  }
  const validade = VALIDADES[fim];
  const expira = validade === 0 ? 0 : Math.floor(agora().getTime() / 1000) + validade;
  const texto = `${onboardingId}.${expira}`;
  return `${texto}.${assinar(chave, fim, texto).toString("base64url")}`;
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
  agora: Relogio = () => new Date(),
): string {
  if (typeof bruto !== "string" || bruto.length === 0 || bruto.length > 160) {
    throw new ReferenciaInvalidaError(fim);
  }
  const partes = bruto.split(".");
  if (partes.length !== 3) throw new ReferenciaInvalidaError(fim);
  const [id, segundos, assinatura] = partes as [string, string, string];
  if (!UUID.test(id) || !/^[0-9]{1,15}$/.test(segundos) || !/^[A-Za-z0-9_-]+$/.test(assinatura)) {
    throw new ReferenciaInvalidaError(fim);
  }
  const recebida = Buffer.from(assinatura, "base64url");
  if (recebida.length !== OCTETOS_DE_HMAC) throw new ReferenciaInvalidaError(fim);
  // **A assinatura primeiro, a validade depois**, pela razão do `./token.ts`:
  // pela ordem inversa o tempo de resposta distinguia uma referência expirada —
  // que é prova de que a chave esteve certa algum dia — de uma forjada.
  let acertos = 0;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_HMAC) continue;
    acertos |= timingSafeEqual(assinar(chave, fim, `${id}.${segundos}`), recebida) ? 1 : 0;
  }
  if (acertos !== 1) throw new ReferenciaInvalidaError(fim);
  const expira = Number(segundos);
  // `isSafeInteger` e não só a comparação: quinze algarismos dão um instante
  // que o `Date` não representa, e `NaN <= agora` é **falso** — isto é, uma
  // referência com data impossível passava por não expirada. O mesmo ramo
  // existe no `./token.ts` e fecha-se da mesma maneira. Achado da revisão.
  if (!Number.isSafeInteger(expira) || expira < 0) throw new ReferenciaInvalidaError(fim);
  if (expira !== 0 && expira * 1000 <= agora().getTime()) throw new ReferenciaInvalidaError(fim);
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
    // **Um homónimo vazio não encerra a procura**, e a primeira versão
    // encerrava-a: um `kamba_onboarding=; kamba_onboarding=<sessao>` devolvia
    // `null`, pelo que quem conseguisse plantar um cookie homónimo vazio — de
    // um subdomínio, ou com outro `Path` — desautenticava quem lá estava.
    // Achado da revisão adversarial.
    if (valor !== "") return valor;
  }
  return null;
}
