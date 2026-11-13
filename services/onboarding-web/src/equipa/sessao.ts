/**
 * A identidade da equipa e a sessão da consola da fila de revisão (KAM-196,
 * critério 2).
 *
 * ## Duas coisas, e só a segunda é nossa
 *
 * **Quem é a pessoa, e se provou o segundo factor**, é do IdP da equipa — e o
 * IdP **não está escolhido**: a escolha e as contas de staff são do fundador
 * (critério 1), porque acrescentam um subprocessador e uma conta. O que este
 * ficheiro fixa é a **porta** que esse IdP vai cumprir (`IdentidadeDaEquipa`) e
 * o que a consola faz com a resposta. Nos ensaios a porta é cumprida por um IdP
 * falso, e esse duplo **só existe nos ensaios** (DoD): o `server.ts` não monta a
 * consola sem um IdP verdadeiro.
 *
 * **A sessão da consola** é nossa. Cunha-se depois de o IdP dizer quem é a
 * pessoa **com** MFA, e não é a sessão do painel do dono (KAM-099): tem o seu
 * **separador de domínio** (`kamba/equipa/sessao/v1`) e o seu cookie
 * (`kamba_equipa`). Assinadas com a mesma chave, uma sessão do painel posta no
 * cookie da equipa — ou o contrário — não verifica, porque o HMAC leva o
 * separador. É a barreira do bilhete do KAM-086 e da sessão do painel.
 *
 * ## O que vai na sessão, e o que se relê a cada pedido
 *
 * `v1.<sid>.<conta>.<mfa>.<emitida>.<hmac>`. A sessão diz **quem** e **como se
 * autenticou** (a MFA é um facto da autenticação, não da conta), e mais nada.
 * Os **papéis** e os HMAC de NIF e telefone lêem-se da porta **a cada pedido**
 * (`conta`): tirar o papel a alguém, ou desactivar a conta, fecha a consola no
 * pedido seguinte, e não ao fim da sessão.
 *
 * ```text
 * HIPÓTESE
 * - Hipótese: uma sessão de equipa vale 8 h desde a entrada, sem renovação.
 * - Evidência: nenhuma no bloco; é um turno de trabalho. Sem renovação, o
 *   segundo factor volta a provar-se pelo menos uma vez por turno.
 * - Estado: proposta.
 * - Como validar: com o IdP escolhido, alinhar com a política de sessão dele.
 * ```
 */

import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";

import type { Revisor } from "@kamba/core-ts/revisao";

/** O separador de domínio. Versionado: mudá-lo invalida todas as sessões. */
export const DOMINIO_DA_SESSAO_DA_EQUIPA = "kamba/equipa/sessao/v1";

/** O nome do cookie. Nem o `kamba_onboarding` do registo, nem o `kamba_painel` do dono. */
export const NOME_DO_COOKIE_DA_EQUIPA = "kamba_equipa";

/** Validade desde a entrada, em segundos. ***Proposta***: 8 h, sem renovação. */
export const VALIDADE_DA_EQUIPA_S = 8 * 3600;

/**
 * Os atributos do cookie. `SameSite=Strict`: a consola não tem nenhuma entrada
 * a partir de outro sítio que precise do cookie — o regresso do IdP traz a
 * prova na consulta e **cunha** a sessão, não a lê. `Path=/equipa`: o cookie não
 * vai para as rotas do dono. Sem `Max-Age`: morre com o navegador, e o prazo
 * dentro da assinatura é o que conta.
 */
export const ATRIBUTOS_DO_COOKIE_DA_EQUIPA = "HttpOnly; Secure; SameSite=Strict; Path=/equipa";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** O que o IdP diz de uma autenticação. */
export interface Autenticacao {
  /** O identificador da conta no IdP. UUID: vai para `review_decision_log.revisor_id`. */
  readonly id: string;
  /** O segundo factor foi provado **nesta** autenticação. */
  readonly mfa: boolean;
}

/** A conta, como o IdP a tem agora. Sem a MFA, que é da autenticação. */
export type ContaDaEquipa = Omit<Revisor, "mfa">;

/**
 * A porta da identidade da equipa. O IdP que o fundador escolher cumpre-a; nos
 * ensaios, um IdP falso.
 */
export interface IdentidadeDaEquipa {
  /**
   * Troca a prova com que o IdP devolveu o navegador (o `code` de um OIDC, por
   * exemplo) pela autenticação. `null` se a prova não serve. Uma prova serve
   * **uma vez**: é o IdP que o garante.
   */
  autenticar(prova: string): Promise<Autenticacao | null>;
  /** A conta, lida agora. `null` se não existe ou está desactivada. */
  conta(id: string): Promise<ContaDaEquipa | null>;
}

/** Uma sessão da consola, lida e verificada. */
export interface SessaoDaEquipa {
  readonly sid: string;
  readonly conta: string;
  readonly mfa: boolean;
  /** Segundos desde a época. */
  readonly emitida: number;
}

/** As sessões revogadas pelo `POST /equipa/sair`. Em memória, como o resto do `onboarding-web`. */
export interface RevogacoesDaEquipa {
  revogar(sid: string): Promise<void>;
  revogada(sid: string): Promise<boolean>;
}

export class RevogacoesDaEquipaEmMemoria implements RevogacoesDaEquipa {
  readonly #sids = new Set<string>();

  async revogar(sid: string): Promise<void> {
    this.#sids.add(sid);
  }

  async revogada(sid: string): Promise<boolean> {
    return this.#sids.has(sid);
  }
}

function texto(s: SessaoDaEquipa): string {
  return `v1.${s.sid}.${s.conta}.${s.mfa ? 1 : 0}.${s.emitida}`;
}

function assinar(chave: Uint8Array, t: string): Buffer {
  return createHmac("sha256", chave).update(DOMINIO_DA_SESSAO_DA_EQUIPA).update("\u0000").update(t).digest();
}

/** Uma sessão nova, a começar agora. */
export function novaSessaoDaEquipa(a: Autenticacao, agora: Date): SessaoDaEquipa {
  return { sid: randomUUID(), conta: a.id.toLowerCase(), mfa: a.mfa, emitida: Math.floor(agora.getTime() / 1000) };
}

/** A cadeia assinada de uma sessão. */
export function cunharSessaoDaEquipa(s: SessaoDaEquipa, chave: Uint8Array): string {
  if (!UUID.test(s.sid) || !UUID.test(s.conta)) throw new Error("sessao da equipa mal formada");
  return `${texto(s)}.${assinar(chave, texto(s)).toString("base64url")}`;
}

/**
 * Lê e verifica uma sessão, **sem** consultar as revogadas. `null` se não serve.
 * Compara contra as duas chaves do anel, em tempo constante e sem sair ao
 * primeiro acerto, como o `../painel/sessao.ts`.
 */
export function lerSessaoDaEquipa(bruto: unknown, anel: readonly (Uint8Array | null)[], agora: Date): SessaoDaEquipa | null {
  if (typeof bruto !== "string" || bruto.length === 0 || bruto.length > 200) return null;
  const partes = bruto.split(".");
  if (partes.length !== 6 || partes[0] !== "v1") return null;
  const [, sid, conta, mfa, emitidaT, assinatura] = partes as [string, string, string, string, string, string];
  if (!UUID.test(sid) || !UUID.test(conta) || (mfa !== "0" && mfa !== "1")) return null;
  if (!/^[0-9]{1,12}$/.test(emitidaT) || !/^[A-Za-z0-9_-]{43}$/.test(assinatura)) return null;
  const s: SessaoDaEquipa = { sid, conta, mfa: mfa === "1", emitida: Number(emitidaT) };
  const apresentada = Buffer.from(assinatura, "base64url");
  let casou = false;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array)) continue;
    const esperada = assinar(chave, texto(s));
    if (esperada.length === apresentada.length && timingSafeEqual(esperada, apresentada)) casou = true;
  }
  if (!casou) return null;
  const agoraS = Math.floor(agora.getTime() / 1000);
  if (s.emitida > agoraS + 60 || agoraS - s.emitida > VALIDADE_DA_EQUIPA_S) return null;
  return s;
}

/** O `Set-Cookie` de uma sessão. */
export function cabecalhoDaSessaoDaEquipa(valor: string): string {
  return `${NOME_DO_COOKIE_DA_EQUIPA}=${valor}; ${ATRIBUTOS_DO_COOKIE_DA_EQUIPA}`;
}

/** O `Set-Cookie` que apaga a sessão. */
export function cabecalhoQueApagaASessaoDaEquipa(): string {
  return `${NOME_DO_COOKIE_DA_EQUIPA}=; ${ATRIBUTOS_DO_COOKIE_DA_EQUIPA}; Max-Age=0`;
}

/** O valor do cookie da equipa num cabeçalho `Cookie`, ou `null`. Um homónimo vazio não encerra a procura. */
export function cookieDaEquipa(cabecalho: unknown): string | null {
  if (typeof cabecalho !== "string") return null;
  for (const par of cabecalho.split(";")) {
    const corte = par.indexOf("=");
    if (corte < 0) continue;
    if (par.slice(0, corte).trim() !== NOME_DO_COOKIE_DA_EQUIPA) continue;
    const valor = par.slice(corte + 1).trim();
    if (valor !== "") return valor;
  }
  return null;
}
