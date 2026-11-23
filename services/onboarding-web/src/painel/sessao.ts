/**
 * A sessão do dono no painel (KAM-099, critério 1).
 *
 * «Autenticação por OTP de KAM-086 (sessão do dono, 30 dias com renovação,
 * revogável); sem palavras-passe; cada sessão fica ligada ao `tenant_id` do
 * dono, nunca a um parâmetro do pedido.»
 *
 * ## Não é a `sessao` do KAM-086, e não lhe toca
 *
 * A `sessao` do `@kamba/core-ts/inscricao` dura 24 h, não se renova, não se
 * revoga e diz **de que caso** é, não de que tenant. Alargá-la a 30 dias era
 * mudar o registo inteiro por causa do painel. Por isso o painel tem a sua
 * referência, com o seu **separador de domínio** (`kamba/painel/sessao/v1`), e
 * só se cunha **depois de o OTP ter acertado**: a partir de uma `sessao` válida
 * do registo (`GET /painel/entrar`), ou do código da reentrada
 * (`POST /painel/verificar`, KAM-190), que confere o OTP sem passar pela
 * sessão do registo. A barreira é a mesma do bilhete do KAM-086: um separador diferente
 * faz de uma `sessao` de registo um valor que este verificador recusa, e
 * vice-versa.
 *
 * ## O tenant vai **dentro** da assinatura
 *
 * `v1.<sid>.<tenant>.<dono>.<emitida>.<renovada>.<hmac>`. O tenant sai do caso
 * no momento da entrada (`Caso.tenantId`) e fica assinado: um pedido não tem
 * por onde o trocar, e as rotas não leem tenant de mais lado nenhum. O `dono` é
 * o `onboarding_id` do caso, e é o `actor.id` que o COM grava no `audit_log`.
 *
 * ## Renovação e revogação, e a ordem entre elas
 *
 *     ler       assinatura, depois prazos, e só então a lista de revogadas
 *     renovar   só sobre uma sessão que acabou de passar pelo `ler`
 *
 * A renovação **mantém o `sid` e a `emitida`**, e é isso que a impede de
 * branquear uma sessão revogada: a revogação é por `sid` (ou por tenant e
 * instante de emissão), e a renovada continua a ser a mesma sessão. Uma
 * expirada não chega a renovar-se, porque o `ler` a recusa primeiro.
 *
 * ```text
 * HIPÓTESE
 * - Hipótese: 30 dias deslizantes, com tecto absoluto de 90 dias desde a
 *   entrada no painel (que é, no máximo, 24 h depois do OTP: a `sessao` do
 *   registo de onde se cunha vale 24 h).
 * - Evidência: os 30 dias são do critério 1. O tecto não está no bloco: sem
 *   ele, uma sessão usada uma vez por mês renovava-se para sempre sem nunca
 *   voltar a provar a posse do telefone.
 * - Estado: os 90 dias são proposta.
 * - Como validar: o uso real do painel no Piloto (quantos donos voltam ao OTP).
 * ```
 */

import { createCipheriv, createDecipheriv, createHmac, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";

/** O separador de domínio. Versionado: mudá-lo invalida todas as sessões. */
export const DOMINIO_DA_SESSAO_DO_PAINEL = "kamba/painel/sessao/v1";

/** O nome do cookie. Outro nome que não o `kamba_onboarding` do KAM-086. */
export const NOME_DO_COOKIE_DO_PAINEL = "kamba_painel";

/** Validade deslizante, em segundos: **30 dias** (critério 1). */
export const VALIDADE_DO_PAINEL_S = 30 * 24 * 3600;

/** Tecto absoluto desde a entrada no painel, em segundos. ***Proposta***: 90 dias. */
export const TECTO_DO_PAINEL_S = 90 * 24 * 3600;

/**
 * A partir de que idade da última renovação se cunha outra. ***Proposta***: 1 dia.
 *
 * Renovar a cada pedido escrevia um `Set-Cookie` em todas as respostas; um dia
 * é a granularidade que basta a uma janela de trinta.
 */
export const RENOVAR_APOS_S = 24 * 3600;

/**
 * Os atributos do cookie. `Path=/` e não `/painel`: a API vive em
 * `/painel/...` e a entrada também, mas o `PATCH` é feito pela página e o
 * navegador só manda o cookie para o caminho declarado — um `Path` estreito é
 * uma barreira que não protege nada aqui e parte o `POST /painel/sair`.
 * `Max-Age` porque, ao contrário da sessão de registo, esta **tem** de
 * sobreviver ao fecho do navegador: é o critério.
 */
export const ATRIBUTOS_DO_COOKIE_DO_PAINEL = "HttpOnly; Secure; SameSite=Lax; Path=/";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** Uma sessão do painel, lida e verificada. */
export interface SessaoDoPainel {
  readonly sid: string;
  readonly tenantId: string;
  /** O `onboarding_id` do caso de quem entrou: o `actor.id` da auditoria. */
  readonly dono: string;
  /** Segundos desde a época: a entrada no painel. Não muda com a renovação. */
  readonly emitida: number;
  /** Segundos desde a época: a última renovação. */
  readonly renovada: number;
}

/**
 * As sessões revogadas. A porta, a implementação em memória e a da base.
 *
 * **Na base em `prod`** (KAM-236, decisão do fundador de 2026-11-21, D3-A): uma
 * lista de revogadas que se perde no reinício reabria as sessões que o dono
 * fechou. A `RevogacoesNaBase` grava na `platform.painel_revogacao` (revisão
 * `0084`), como `kamba_app` e sob a RLS do tenant **da sessão** — é por isso que
 * o `revogar` recebe a sessão inteira, e não só o `sid`. A em memória fica para
 * os ensaios e para `dev` sem base.
 */
export interface Revogacoes {
  /** Revoga uma sessão. */
  revogar(s: SessaoDoPainel): Promise<void>;
  /** Revoga todas as sessões de um tenant emitidas até `ate` (inclusive). */
  revogarDoTenant(tenantId: string, ate: number): Promise<void>;
  /** A sessão está revogada? */
  revogada(s: SessaoDoPainel): Promise<boolean>;
}

export class RevogacoesEmMemoria implements Revogacoes {
  readonly #sids = new Set<string>();
  readonly #porTenant = new Map<string, number>();

  async revogar(s: SessaoDoPainel): Promise<void> {
    this.#sids.add(s.sid);
  }

  async revogarDoTenant(tenantId: string, ate: number): Promise<void> {
    this.#porTenant.set(tenantId, Math.max(ate, this.#porTenant.get(tenantId) ?? 0));
  }

  async revogada(s: SessaoDoPainel): Promise<boolean> {
    if (this.#sids.has(s.sid)) return true;
    const corte = this.#porTenant.get(s.tenantId);
    return corte !== undefined && s.emitida <= corte;
  }
}

function assinar(chave: Uint8Array, texto: string): Buffer {
  return createHmac("sha256", chave).update(DOMINIO_DA_SESSAO_DO_PAINEL).update("\u0000").update(texto).digest();
}

function texto(s: SessaoDoPainel): string {
  return `v1.${s.sid}.${s.tenantId}.${s.dono}.${s.emitida}.${s.renovada}`;
}

/** A cadeia assinada de uma sessão. */
export function cunharSessao(s: SessaoDoPainel, chave: Uint8Array): string {
  if (!UUID.test(s.sid) || !UUID.test(s.tenantId) || !UUID.test(s.dono)) throw new Error("sessao do painel mal formada");
  return `${texto(s)}.${assinar(chave, texto(s)).toString("base64url")}`;
}

/** Uma sessão nova para um tenant, a começar agora. */
export function novaSessao(tenantId: string, dono: string, agora: Date): SessaoDoPainel {
  const s = Math.floor(agora.getTime() / 1000);
  return { sid: randomUUID(), tenantId: tenantId.toLowerCase(), dono: dono.toLowerCase(), emitida: s, renovada: s };
}

/**
 * Lê e verifica uma sessão, **sem** consultar as revogadas. `null` se não serve.
 *
 * A assinatura compara-se contra as duas chaves do anel, em tempo constante e
 * sem sair ao primeiro acerto — a regra do `inscricao/sessao.ts`.
 */
export function lerSessao(
  bruto: unknown,
  anel: readonly (Uint8Array | null)[],
  agora: Date,
): SessaoDoPainel | null {
  if (typeof bruto !== "string" || bruto.length === 0 || bruto.length > 240) return null;
  const partes = bruto.split(".");
  if (partes.length !== 7 || partes[0] !== "v1") return null;
  const [, sid, tenantId, dono, emitidaT, renovadaT, assinatura] = partes as [
    string, string, string, string, string, string, string,
  ];
  if (!UUID.test(sid) || !UUID.test(tenantId) || !UUID.test(dono)) return null;
  if (!/^[0-9]{1,12}$/.test(emitidaT) || !/^[0-9]{1,12}$/.test(renovadaT)) return null;
  if (!/^[A-Za-z0-9_-]{43}$/.test(assinatura)) return null;
  const s: SessaoDoPainel = { sid, tenantId, dono, emitida: Number(emitidaT), renovada: Number(renovadaT) };
  const apresentada = Buffer.from(assinatura, "base64url");
  let casou = false;
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array)) continue;
    const esperada = assinar(chave, texto(s));
    if (esperada.length === apresentada.length && timingSafeEqual(esperada, apresentada)) casou = true;
  }
  if (!casou) return null;
  const agoraS = Math.floor(agora.getTime() / 1000);
  if (s.renovada < s.emitida || s.renovada > agoraS + 60) return null;
  if (agoraS - s.renovada > VALIDADE_DO_PAINEL_S) return null;
  if (agoraS - s.emitida > TECTO_DO_PAINEL_S) return null;
  return s;
}

/**
 * A sessão renovada, ou `null` se ainda não é altura.
 *
 * **Só recebe uma sessão que acabou de passar pelo `lerSessao` e pelas
 * revogadas** — é o chamador que o garante, e é o único chamador (`./rotas.ts`).
 * O `sid` e a `emitida` ficam: ver a nota do módulo.
 */
export function renovacao(s: SessaoDoPainel, agora: Date): SessaoDoPainel | null {
  const agoraS = Math.floor(agora.getTime() / 1000);
  if (agoraS - s.renovada < RENOVAR_APOS_S) return null;
  return { ...s, renovada: agoraS };
}

/** O `Set-Cookie` de uma sessão. */
export function cabecalhoDaSessao(valor: string): string {
  return `${NOME_DO_COOKIE_DO_PAINEL}=${valor}; ${ATRIBUTOS_DO_COOKIE_DO_PAINEL}; Max-Age=${VALIDADE_DO_PAINEL_S}`;
}

/** O `Set-Cookie` que apaga a sessão. */
export function cabecalhoQueApagaASessao(): string {
  return `${NOME_DO_COOKIE_DO_PAINEL}=; ${ATRIBUTOS_DO_COOKIE_DO_PAINEL}; Max-Age=0`;
}

/** O valor do cookie do painel num cabeçalho `Cookie`, ou `null`. */
export function cookieDoPainel(cabecalho: unknown): string | null {
  if (typeof cabecalho !== "string") return null;
  for (const par of cabecalho.split(";")) {
    const corte = par.indexOf("=");
    if (corte < 0) continue;
    if (par.slice(0, corte).trim() !== NOME_DO_COOKIE_DO_PAINEL) continue;
    const valor = par.slice(corte + 1).trim();
    // Um homónimo vazio não encerra a procura: é o achado do KAM-086 no
    // `cookieDoCabecalho`, e vale igual aqui.
    if (valor !== "") return valor;
  }
  return null;
}

// ------------------------------------------------- o bilhete da reentrada (KAM-190)

/**
 * O separador de domínio do bilhete da reentrada. **Não é o `ticket` do
 * KAM-086**, e a diferença fecha um oráculo: o bilhete de um telefone que não
 * tem painel aponta para um caso que não existe, e o `/api/otp/verificar` do
 * registo responde `sem_desafio` a esse e `errou` a um verdadeiro. Com um
 * separador próprio, o bilhete do painel só serve no `POST /painel/verificar`,
 * que responde o mesmo 401 a todas as falhas.
 *
 * ## O caso vai **cifrado**, e não só assinado
 *
 * A primeira versão escrevia `b1.<caso>.<expira>.<hmac>`, e a revisão
 * adversarial mediu o oráculo que isso abria: um telefone com painel recebia
 * sempre o **mesmo** caso, e um sem painel um UUID novo a cada pedido — dois
 * pedidos por telefone diziam quem é dono, e entregavam o `onboarding_id` a
 * quem não se autenticou. Agora o caso e o prazo vão em AES-256-GCM, com IV
 * aleatório: dois bilhetes do mesmo telefone são diferentes, e nenhum mostra o
 * caso. A etiqueta do GCM é a autenticação; a chave deriva-se da do anel com
 * este separador, e nunca é a da assinatura.
 */
export const DOMINIO_DO_BILHETE_DO_PAINEL = "kamba/painel/bilhete/v2";

/**
 * Validade do bilhete, em segundos. ***Proposta***: 10 min — o dobro dos 5 min de
 * vida do código (`TTL_MINUTOS` do `inscricao/otp.ts`), para um reenvio caber.
 */
export const VALIDADE_DO_BILHETE_S = 10 * 60;

function chaveDoBilhete(chave: Uint8Array): Buffer {
  return createHmac("sha256", chave).update(DOMINIO_DO_BILHETE_DO_PAINEL).update("\u0000cifra").digest();
}

/**
 * O bilhete de um caso: `b2.<iv>.<cifra>.<etiqueta>`, em base64url. Não
 * autentica: só diz, a quem o sabe abrir, de que caso é o código.
 */
export function cunharBilhete(casoId: string, chave: Uint8Array, agora: Date): string {
  if (!UUID.test(casoId)) throw new Error("bilhete do painel mal formado");
  const iv = randomBytes(12);
  const cifra = createCipheriv("aes-256-gcm", chaveDoBilhete(chave), iv);
  const texto = `${casoId}.${Math.floor(agora.getTime() / 1000) + VALIDADE_DO_BILHETE_S}`;
  const corpo = Buffer.concat([cifra.update(texto, "utf8"), cifra.final()]);
  return `b2.${iv.toString("base64url")}.${corpo.toString("base64url")}.${cifra.getAuthTag().toString("base64url")}`;
}

/** O caso de um bilhete válido e dentro do prazo, ou `null`. Contra as duas chaves do anel. */
export function lerBilhete(bruto: unknown, anel: readonly (Uint8Array | null)[], agora: Date): string | null {
  if (typeof bruto !== "string" || bruto.length > 200) return null;
  const partes = bruto.split(".");
  if (partes.length !== 4 || partes[0] !== "b2") return null;
  const [, ivT, corpoT, etiquetaT] = partes as [string, string, string, string];
  if (!/^[A-Za-z0-9_-]{16}$/.test(ivT) || !/^[A-Za-z0-9_-]{1,120}$/.test(corpoT) || !/^[A-Za-z0-9_-]{22}$/.test(etiquetaT)) {
    return null;
  }
  for (const chave of anel) {
    if (!(chave instanceof Uint8Array)) continue;
    let texto: string;
    try {
      const decifra = createDecipheriv("aes-256-gcm", chaveDoBilhete(chave), Buffer.from(ivT, "base64url"));
      decifra.setAuthTag(Buffer.from(etiquetaT, "base64url"));
      texto = Buffer.concat([decifra.update(Buffer.from(corpoT, "base64url")), decifra.final()]).toString("utf8");
    } catch {
      continue;
    }
    const m = /^([0-9a-f-]{36})\.([0-9]{1,12})$/.exec(texto);
    if (m === null || !UUID.test(m[1] as string)) return null;
    return Number(m[2]) < Math.floor(agora.getTime() / 1000) ? null : (m[1] as string);
  }
  return null;
}
