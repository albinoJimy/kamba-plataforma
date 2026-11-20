/**
 * A mudança de telefone do dono (KAM-118, critério 4), com a prova de posse
 * do KAM-223 (decisão 3 do fundador de 2026-11-19, opção C).
 *
 * «Com o OTP do número antigo, a troca é imediata. Sem ele, fica pendente 72 h
 * (*proposta*), com aviso ao número antigo e ao e-mail, e o antigo pode
 * cancelar. O estado pendente tem de sobreviver a um reinício.»
 *
 * ## Quem tem o papel, em cada instante
 *
 *     pedir (novo)        OTP ao número novo; a troca fica `pedida`
 *     verificar (novo)    o OTP acerta → `pendente` durante 72 h, e avisa o
 *                         número antigo e o e-mail; **o papel não muda**
 *     pedir (antigo)      OTP ao número que o dono diz ser o antigo
 *     verificar (antigo)  o OTP acerta **e** o número é o do dono actual → o
 *                         papel muda já, pela `platform.definir_dono`
 *     concluir            passadas as 72 h, o papel muda sem o antigo
 *     cancelar            qualquer sessão do tenant, antes de mudar
 *
 * **O papel só se move por esta porta, e só depois de uma de duas provas**: o
 * OTP do número antigo, ou as 72 h passadas com aviso. Até lá, o número novo é
 * `cliente` como qualquer desconhecido, e o antigo continua dono. É o que fecha
 * o *cookie* roubado (achado 5 da revisão do KAM-211): a sessão do painel e o OTP
 * do número novo, sozinhos, só abrem uma espera que o dono legítimo vê e cancela.
 *
 * ## A espera só protege com o aviso entregue
 *
 * Os avisos são os ganchos do KAM-115 (`DESTINOS_DO_AVISO`), e o KAM-115 não tem
 * canal: hoje a espera não avisa ninguém, e quem tiver o *cookie* e esperar as
 * 72 h fica com o papel. O dono legítimo que entre no painel vê a troca pendente
 * e cancela-a; é o que a espera dá sem o aviso. Fica escrito no bloco do ticket.
 *
 * ## O que sobrevive a um reinício
 *
 * Tudo o que decide: a troca, o estado, o prazo, e o desafio do OTP de cada
 * número (`RepositorioDaTroca`, revisão `0077`). Nada fica em memória do
 * processo. O telefone em claro **não** se guarda: só o HMAC, e quem verifica
 * escreve o número outra vez ao lado do código — é com ele que o contacto se
 * resolve, depois da prova.
 *
 * ## Duas réplicas, o mesmo pedido
 *
 * Uma troca viva por tenant (índice único parcial na base), e cada passo é uma
 * troca de estado condicional: duas réplicas que concluam a mesma troca dão uma
 * mudança de papel e uma recusa. O desafio do OTP é **da troca e do telefone**
 * (a chave leva o `changeId`, qual dos números é, e o HMAC do telefone a que o
 * código foi enviado), pelo que o código de uma troca não verifica outra, e o
 * código enviado a um número não verifica outro.
 *
 * **O HMAC do telefone na chave não é enfeite** (achado 1 da revisão
 * adversarial). Sem ele, quem tivesse o *cookie* pedia o código do «antigo» ao
 * seu próprio segundo número, e logo a seguir pedia-o ao número do dono: o
 * segundo envio recusava por intervalo antes de gravar o desafio, mas o HMAC do
 * antigo já era o do dono — e o código do segundo número verificava como sendo
 * do dono. A troca fazia-se já, sem as 72 h. Com o telefone na chave, a chave do
 * código que o atacante recebeu não é a do número do dono, e não se lê.
 *
 * ## Os avisos são ganchos
 *
 * Um aviso que falha não desfaz nada: a troca já está gravada, e desfazê-la por
 * o e-mail estar em baixo deixava o dono sem saber em que estado ficou. A falha
 * sobe a quem chama, depois.
 */

import { randomUUID } from "node:crypto";

import type { Telefone } from "../inscricao/identificadores.ts";
import type { RecusaDeEnvio, ResultadoDeEnvio, Veredicto } from "../inscricao/otp.ts";
import { canalDoDono } from "./persona.ts";

/**
 * Quanto tempo a troca fica pendente sem o OTP do número antigo. ***Proposta***
 * (72 h, decisão 3 do fundador); calibra-se no fim do Piloto.
 */
export const ESPERA_DA_TROCA_MS = 72 * 3_600_000;

/**
 * Quanto tempo uma troca `pedida` espera pelo OTP do número novo. ***Proposta***:
 * mais do que o prazo do código (`TTL_MINUTOS` do `Otp`), para o código vencer
 * primeiro. Uma `pedida` vencida não conta como troca viva.
 */
export const PRAZO_DO_PEDIDO_MS = 15 * 60_000;

/** Os estados de uma troca. O `CHECK` da `owner_phone_changes.estado`. */
export const ESTADOS_DA_TROCA = ["pedida", "pendente", "feita", "cancelada", "expirada"] as const;
export type EstadoDaTroca = (typeof ESTADOS_DA_TROCA)[number];

/** Os dois números de uma troca: o que o dono quer, e o que ele tem. */
export const NUMEROS_DA_TROCA = ["novo", "antigo"] as const;
export type NumeroDaTroca = (typeof NUMEROS_DA_TROCA)[number];

/** O desafio de um número numa troca: a troca, qual dos números, e o telefone. */
export interface AlvoDoDesafio {
  readonly tenantId: string;
  readonly changeId: string;
  readonly numero: NumeroDaTroca;
  /** O HMAC do telefone a que o código vai (a chave actual do anel). */
  readonly telefoneHmac: string;
}

/**
 * Quantos hexadecimais do HMAC do telefone entram na chave: 16, isto é, 64 bits.
 * Chegam para ligar o código ao telefone — o atacante precisava de um número cujo
 * HMAC (com o *pepper* que não tem) colidisse nos 64 bits —, e a chave cabe nos
 * 128 caracteres da chave de idempotência do envio do SMS, que deriva dela.
 */
export const HEX_DO_TELEFONE_NA_CHAVE = 16;

/**
 * A chave do desafio do OTP: `troca:{changeId}:{numero}:{16 hex do HMAC}`. Entra
 * no HMAC do código, e é o que a base guarda: um código só verifica o telefone a
 * que foi enviado.
 */
export function chaveDoDesafio(alvo: AlvoDoDesafio): string {
  return `troca:${alvo.changeId}:${alvo.numero}:${alvo.telefoneHmac.slice(0, HEX_DO_TELEFONE_NA_CHAVE)}`;
}

/** O OTP do KAM-086, pela forma que a troca usa: com o desafio guardado na troca. */
export interface OtpDaTroca {
  enviar(alvo: AlvoDoDesafio, telefone: Telefone): Promise<ResultadoDeEnvio>;
  verificar(alvo: AlvoDoDesafio, codigo: string): Promise<Veredicto>;
}

/** O contacto de um número, no tenant do dono. É o `resolveContact` do KAM-008. */
export interface ContactoDoNumero {
  (pedido: { readonly tenantId: string; readonly telefone: Telefone }): Promise<{
    readonly contactId: string;
  }>;
}

/**
 * A troca na base: `platform.definir_dono(contacto, 'troca_de_telefone')`,
 * chamada como `kamba_identity` com o tenant no `app.tenant_id`. Devolve o
 * contacto que deixou de ser dono, ou `null` se não havia nenhum. Fica para o
 * provisionamento e para os ensaios; a troca usa o `concluir` do repositório,
 * que faz a mesma chamada na transacção da troca.
 */
export interface TrocaNaBase {
  (pedido: {
    readonly tenantId: string;
    readonly contactId: string;
    readonly ownerChannelWa: boolean;
  }): Promise<{
    readonly anterior: string | null;
  }>;
}

/** Para onde vai o aviso de que o telefone do dono vai mudar, ou mudou. */
export const DESTINOS_DO_AVISO = ["numero_antigo", "email"] as const;
export type DestinoDoAviso = (typeof DESTINOS_DO_AVISO)[number];

/** O momento do aviso: a espera abriu, a troca fez-se, ou cancelou-se. */
export const MOMENTOS_DO_AVISO = ["pendente", "feita", "cancelada"] as const;
export type MomentoDoAviso = (typeof MOMENTOS_DO_AVISO)[number];

/** O gancho do KAM-115. Recebe o tenant, o destino e o momento, **nunca** o número. */
export interface AvisoDaTroca {
  (pedido: {
    readonly tenantId: string;
    readonly destino: DestinoDoAviso;
    readonly momento: MomentoDoAviso;
  }): Promise<void>;
}

/** Uma troca, como a base a guarda. **Sem telefone em claro.** */
export interface TrocaGuardada {
  readonly changeId: string;
  readonly tenantId: string;
  /** A sessão que a pediu (`troca:{sid}`): só ela verifica o número novo. */
  readonly pedido: string;
  /** O HMAC do número novo (`pepper_onboarding_ident`, a chave actual do anel). */
  readonly telefoneHmac: string;
  readonly estado: EstadoDaTroca;
  /** `pedida`: até quando espera pelo código. `pendente`: quando a troca se faz sem o antigo. */
  readonly prazo: Date;
  /** O contacto do número novo, resolvido depois da prova. */
  readonly contactId: string | null;
  /** O HMAC do número que o dono disse ser o antigo, enquanto o código dele corre. */
  readonly antigoHmac: string | null;
  /**
   * O canal do dono novo (`canalDoDono`, KAM-216), que o `concluir` escreve em
   * `tenants.owner_channel_wa` com o papel. Calcula-se no `pedir`, que é onde
   * o número está em claro com os HMAC do anel inteiro; o número que o código
   * prova é esse, porque a chave do desafio leva o HMAC dele.
   */
  readonly ownerChannelWa: boolean;
}

/** O que a troca tem de saber sobre o dono que perde o papel. */
export class AnteriorDiferenteError extends Error {
  override readonly name = "AnteriorDiferenteError";
  constructor() {
    super("o numero provado nao e o do dono actual; a troca nao se faz");
  }
}

/**
 * A persistência da troca (revisão `0077`, `platform.owner_phone_changes`).
 *
 * Cada mudança de estado é condicional ao estado de onde parte: é isso que faz
 * duas réplicas sobre a mesma troca darem uma mudança e uma recusa.
 */
export interface RepositorioDaTroca {
  /**
   * Abre uma troca `pedida`. As `pedida` vencidas do tenant e a da mesma sessão
   * deixam de contar primeiro; devolve `null` se o tenant já tem uma viva.
   */
  abrir(pedido: {
    readonly tenantId: string;
    readonly pedido: string;
    readonly telefoneHmac: string;
    readonly ownerChannelWa: boolean;
    readonly prazo: Date;
    readonly agora: Date;
  }): Promise<string | null>;
  /** A troca viva do tenant: `pendente`, ou `pedida` dentro do prazo. */
  viva(tenantId: string, agora: Date): Promise<TrocaGuardada | null>;
  /** Uma `pedida` cujo código não chegou a sair deixa de contar. */
  desistir(tenantId: string, changeId: string): Promise<void>;
  /** `pedida` → `pendente`, com o contacto novo e o prazo das 72 h. */
  pender(pedido: {
    readonly tenantId: string;
    readonly changeId: string;
    readonly contactId: string;
    readonly prazo: Date;
  }): Promise<boolean>;
  /** Anota o HMAC do número antigo de uma `pendente`, para o código dele. */
  anotarAntigo(tenantId: string, changeId: string, antigoHmac: string): Promise<boolean>;
  /**
   * `pendente` → `feita` **e** a `definir_dono` do contacto novo, numa
   * transacção só. Com `exigirAnterior`, o dono que perde o papel tem de ser
   * esse, senão nada muda (`AnteriorDiferenteError`). Sem ele, só depois do
   * prazo. Devolve `null` se a troca já não estava `pendente` (outra réplica
   * ganhou, ou foi cancelada) ou se o prazo ainda não passou.
   */
  concluir(pedido: {
    readonly tenantId: string;
    readonly changeId: string;
    readonly agora: Date;
    readonly exigirAnterior?: string;
  }): Promise<{ readonly contactId: string; readonly anterior: string | null } | null>;
  /** A troca viva do tenant → `cancelada`. */
  cancelar(tenantId: string, agora: Date): Promise<boolean>;
}

/** Recusas do pedido de um código. */
export type RecusaDoPedido = RecusaDeEnvio | "ocupado" | "sem_troca" | "numero";

/** O resultado de pedir um código. */
export type ResultadoDoPedido =
  | { readonly enviado: true; readonly expiraEm: Date }
  | { readonly enviado: false; readonly recusa: RecusaDoPedido };

/** O desfecho de uma verificação. */
export type DesfechoDaTroca =
  | { readonly estado: "pendente"; readonly prazo: Date }
  | { readonly estado: "feita"; readonly contactId: string; readonly anterior: string | null }
  | {
      readonly estado: "recusada";
      readonly veredicto: Exclude<Veredicto, "acertou"> | "sem_pedido" | "numero" | "antigo_diferente" | "cedo";
    };

/** O que o painel mostra da troca viva. Sem número nenhum. */
export interface VistaDaTroca {
  readonly estado: "pedida" | "pendente";
  readonly prazo: Date;
}

/** Os HMAC de um telefone conferem com o guardado? O anel inteiro procura. */
function confere(telefone: Telefone, guardado: string | null): boolean {
  return guardado !== null && telefone.hmacs.includes(guardado);
}

/** A troca de telefone do dono. Uma instância por processo; o estado está na base. */
export class TrocaDeTelefone {
  readonly #otp: OtpDaTroca;
  readonly #contacto: ContactoDoNumero;
  readonly #repositorio: RepositorioDaTroca;
  readonly #avisar: AvisoDaTroca;
  readonly #relogio: () => Date;
  readonly #espera: number;

  constructor(portas: {
    readonly otp: OtpDaTroca;
    readonly contacto: ContactoDoNumero;
    readonly repositorio: RepositorioDaTroca;
    readonly avisar: AvisoDaTroca;
    readonly relogio?: () => Date;
    readonly esperaMs?: number;
  }) {
    this.#otp = portas.otp;
    this.#contacto = portas.contacto;
    this.#repositorio = portas.repositorio;
    this.#avisar = portas.avisar;
    this.#relogio = portas.relogio ?? ((): Date => new Date());
    this.#espera = portas.esperaMs ?? ESPERA_DA_TROCA_MS;
  }

  /** A troca viva do tenant, para o painel. */
  async estado(tenantId: string): Promise<VistaDaTroca | null> {
    const viva = await this.#repositorio.viva(tenantId, this.#relogio());
    if (viva === null || (viva.estado !== "pedida" && viva.estado !== "pendente")) return null;
    return { estado: viva.estado, prazo: viva.prazo };
  }

  /**
   * Pede um código. `novo`: abre a troca e manda-o ao número novo. `antigo`:
   * só numa troca `pendente`, e manda-o ao número que o dono diz ser o seu — se
   * não for, o código chega a quem tem esse número e a verificação recusa.
   *
   * **O `tenantId` vem da sessão do painel**, nunca do pedido. O
   * `hmacDoNumeroDaLoja` também: é o `phone_hmac` do caso da sessão, e `null`
   * dá painel (KAM-216). Só conta no `novo`.
   */
  async pedir(
    pedido: string,
    tenantId: string,
    telefone: Telefone,
    hmacDoNumeroDaLoja: string | null,
    numero: NumeroDaTroca = "novo",
  ): Promise<ResultadoDoPedido> {
    const agora = this.#relogio();
    if (numero === "antigo") {
      const viva = await this.#repositorio.viva(tenantId, agora);
      if (viva === null || viva.estado !== "pendente") return { enviado: false, recusa: "sem_troca" };
      // O número antigo não pode ser o novo: um código ao mesmo número provava a
      // mesma posse duas vezes.
      if (confere(telefone, viva.telefoneHmac)) return { enviado: false, recusa: "numero" };
      if (!(await this.#repositorio.anotarAntigo(tenantId, viva.changeId, telefone.hmac))) {
        return { enviado: false, recusa: "sem_troca" };
      }
      return this.#otp.enviar({ tenantId, changeId: viva.changeId, numero, telefoneHmac: telefone.hmac }, telefone);
    }
    const changeId = await this.#repositorio.abrir({
      tenantId,
      pedido,
      telefoneHmac: telefone.hmac,
      ownerChannelWa: canalDoDono({ telefoneDoDono: telefone, hmacDoNumeroDaLoja }).owner_channel_wa,
      prazo: new Date(agora.getTime() + PRAZO_DO_PEDIDO_MS),
      agora,
    });
    if (changeId === null) return { enviado: false, recusa: "ocupado" };
    let envio: ResultadoDeEnvio;
    try {
      envio = await this.#otp.enviar({ tenantId, changeId, numero, telefoneHmac: telefone.hmac }, telefone);
    } catch (erro) {
      await this.#repositorio.desistir(tenantId, changeId);
      throw erro;
    }
    if (!envio.enviado) await this.#repositorio.desistir(tenantId, changeId);
    return envio;
  }

  /**
   * Verifica um código. O número vem outra vez com ele, porque só o HMAC dele
   * está guardado.
   *
   * `novo`: só a sessão que pediu; o código certo põe a troca `pendente` e
   * avisa. `antigo`: qualquer sessão do tenant; o código certo **e** o número a
   * ser o do dono actual fazem a troca já.
   */
  async verificar(
    pedido: string,
    tenantId: string,
    telefone: Telefone,
    codigo: string,
    numero: NumeroDaTroca = "novo",
  ): Promise<DesfechoDaTroca> {
    const agora = this.#relogio();
    const viva = await this.#repositorio.viva(tenantId, agora);
    if (numero === "novo") {
      // Uma troca de outra sessão é tratada como inexistente: dizer «existe mas
      // não é tua» era um oráculo sobre o que os outros pedem.
      if (viva === null || viva.estado !== "pedida" || viva.pedido !== pedido) {
        return { estado: "recusada", veredicto: "sem_pedido" };
      }
      if (!confere(telefone, viva.telefoneHmac)) return { estado: "recusada", veredicto: "numero" };
      const veredicto = await this.#otp.verificar(
        { tenantId, changeId: viva.changeId, numero, telefoneHmac: telefone.hmac },
        codigo,
      );
      if (veredicto !== "acertou") {
        if (veredicto !== "errou") await this.#repositorio.desistir(tenantId, viva.changeId);
        return { estado: "recusada", veredicto };
      }
      const { contactId } = await this.#contacto({ tenantId, telefone });
      const prazo = new Date(agora.getTime() + this.#espera);
      if (!(await this.#repositorio.pender({ tenantId, changeId: viva.changeId, contactId, prazo }))) {
        return { estado: "recusada", veredicto: "sem_pedido" };
      }
      await this.#avisarTodos(tenantId, "pendente");
      return { estado: "pendente", prazo };
    }

    if (viva === null || viva.estado !== "pendente") return { estado: "recusada", veredicto: "sem_pedido" };
    if (!confere(telefone, viva.antigoHmac)) return { estado: "recusada", veredicto: "numero" };
    const veredicto = await this.#otp.verificar(
        { tenantId, changeId: viva.changeId, numero, telefoneHmac: telefone.hmac },
        codigo,
      );
    if (veredicto !== "acertou") return { estado: "recusada", veredicto };
    // A posse está provada; falta saber se o número é o do dono. O contacto
    // resolve-se só agora, depois da prova, como o do número novo.
    const { contactId: antigo } = await this.#contacto({ tenantId, telefone });
    let feita: Awaited<ReturnType<RepositorioDaTroca["concluir"]>>;
    try {
      feita = await this.#repositorio.concluir({ tenantId, changeId: viva.changeId, agora, exigirAnterior: antigo });
    } catch (erro) {
      if (erro instanceof AnteriorDiferenteError) return { estado: "recusada", veredicto: "antigo_diferente" };
      throw erro;
    }
    if (feita === null) return { estado: "recusada", veredicto: "sem_pedido" };
    await this.#avisarTodos(tenantId, "feita");
    return { estado: "feita", contactId: feita.contactId, anterior: feita.anterior };
  }

  /** Faz a troca `pendente` cujas 72 h já passaram. */
  async concluir(tenantId: string): Promise<DesfechoDaTroca> {
    const agora = this.#relogio();
    const viva = await this.#repositorio.viva(tenantId, agora);
    if (viva === null || viva.estado !== "pendente") return { estado: "recusada", veredicto: "sem_pedido" };
    if (viva.prazo.getTime() > agora.getTime()) return { estado: "recusada", veredicto: "cedo" };
    const feita = await this.#repositorio.concluir({ tenantId, changeId: viva.changeId, agora });
    if (feita === null) return { estado: "recusada", veredicto: "sem_pedido" };
    await this.#avisarTodos(tenantId, "feita");
    return { estado: "feita", contactId: feita.contactId, anterior: feita.anterior };
  }

  /** Cancela a troca viva do tenant. Qualquer sessão do tenant o pode fazer. */
  async cancelar(tenantId: string): Promise<boolean> {
    const cancelada = await this.#repositorio.cancelar(tenantId, this.#relogio());
    if (cancelada) await this.#avisarTodos(tenantId, "cancelada");
    return cancelada;
  }

  async #avisarTodos(tenantId: string, momento: MomentoDoAviso): Promise<void> {
    for (const destino of DESTINOS_DO_AVISO) {
      await this.#avisar({ tenantId, destino, momento });
    }
  }
}

/**
 * As trocas em memória. **Só para ensaios**: um processo que reinicia perde-as,
 * que é o defeito que a revisão `0077` fecha. Segue as mesmas transições
 * condicionais da base, para que os ensaios da regra C meçam a regra e não o
 * duplo.
 */
export class TrocasEmMemoria implements RepositorioDaTroca {
  readonly #trocas = new Map<string, TrocaGuardada>();
  readonly #definirDono: TrocaNaBase;

  /** `definirDono` é a porta que move o papel (`definir_dono`), em memória ou não. */
  constructor(definirDono: TrocaNaBase) {
    this.#definirDono = definirDono;
  }

  /** Todas, para as asserções. */
  get todas(): readonly TrocaGuardada[] {
    return [...this.#trocas.values()];
  }

  #mudar(changeId: string, de: readonly EstadoDaTroca[], muda: Partial<TrocaGuardada>): boolean {
    const actual = this.#trocas.get(changeId);
    if (actual === undefined || !de.includes(actual.estado)) return false;
    this.#trocas.set(changeId, { ...actual, ...muda });
    return true;
  }

  #vivaDe(tenantId: string, agora: Date): TrocaGuardada | null {
    for (const t of this.#trocas.values()) {
      if (t.tenantId !== tenantId) continue;
      if (t.estado === "pendente") return t;
      if (t.estado === "pedida" && t.prazo.getTime() > agora.getTime()) return t;
    }
    return null;
  }

  async abrir(p: Parameters<RepositorioDaTroca["abrir"]>[0]): Promise<string | null> {
    for (const t of this.#trocas.values()) {
      if (t.tenantId === p.tenantId && t.estado === "pedida" && (t.prazo <= p.agora || t.pedido === p.pedido)) {
        this.#mudar(t.changeId, ["pedida"], { estado: "expirada" });
      }
    }
    if (this.#vivaDe(p.tenantId, p.agora) !== null) return null;
    const changeId = randomUUID();
    this.#trocas.set(changeId, {
      changeId,
      tenantId: p.tenantId,
      pedido: p.pedido,
      telefoneHmac: p.telefoneHmac,
      estado: "pedida",
      prazo: p.prazo,
      contactId: null,
      antigoHmac: null,
      ownerChannelWa: p.ownerChannelWa,
    });
    return changeId;
  }

  async viva(tenantId: string, agora: Date): Promise<TrocaGuardada | null> {
    return this.#vivaDe(tenantId, agora);
  }

  async desistir(tenantId: string, changeId: string): Promise<void> {
    if (this.#trocas.get(changeId)?.tenantId === tenantId) this.#mudar(changeId, ["pedida"], { estado: "expirada" });
  }

  async pender(p: Parameters<RepositorioDaTroca["pender"]>[0]): Promise<boolean> {
    if (this.#trocas.get(p.changeId)?.tenantId !== p.tenantId) return false;
    return this.#mudar(p.changeId, ["pedida"], { estado: "pendente", contactId: p.contactId, prazo: p.prazo });
  }

  async anotarAntigo(tenantId: string, changeId: string, antigoHmac: string): Promise<boolean> {
    if (this.#trocas.get(changeId)?.tenantId !== tenantId) return false;
    return this.#mudar(changeId, ["pendente"], { antigoHmac });
  }

  async concluir(p: Parameters<RepositorioDaTroca["concluir"]>[0]): Promise<{ contactId: string; anterior: string | null } | null> {
    const t = this.#trocas.get(p.changeId);
    if (t === undefined || t.tenantId !== p.tenantId || t.estado !== "pendente" || t.contactId === null) return null;
    if (p.exigirAnterior === undefined && t.prazo.getTime() > p.agora.getTime()) return null;
    // A ordem da base: a troca muda de estado, a porta move o papel, e uma
    // recusa desfaz as duas — aqui à mão, porque em memória não há transacção.
    if (!this.#mudar(p.changeId, ["pendente"], { estado: "feita" })) return null;
    try {
      const { tenantId } = p;
      const { contactId, ownerChannelWa } = t;
      const { anterior } = await this.#definirDono({ tenantId, contactId, ownerChannelWa });
      if (p.exigirAnterior !== undefined && anterior !== p.exigirAnterior) {
        // Em memória o canal antigo não se repõe: a porta dos ensaios só
        // regista o papel, e a base desfaz os dois com a transacção.
        if (anterior !== null) await this.#definirDono({ tenantId, contactId: anterior, ownerChannelWa });
        throw new AnteriorDiferenteError();
      }
      return { contactId: t.contactId, anterior };
    } catch (erro) {
      this.#trocas.set(p.changeId, t);
      throw erro;
    }
  }

  async cancelar(tenantId: string, agora: Date): Promise<boolean> {
    const viva = this.#vivaDe(tenantId, agora);
    return viva !== null && this.#mudar(viva.changeId, ["pedida", "pendente"], { estado: "cancelada" });
  }
}

/** Um `RepositorioDeOtp` por chave, pela forma que o `Otp` do KAM-086 usa. */
interface OtpPorChave {
  enviar(chave: string, telefone: Telefone): Promise<ResultadoDeEnvio>;
  verificar(chave: string, codigo: unknown): Promise<Veredicto>;
}

/**
 * O `OtpDaTroca` sobre um `Otp` que guarda os desafios por chave — o
 * `OtpEmMemoria` dos ensaios. A chave é a `chaveDoDesafio`.
 */
export function otpDaTrocaPorChave(otp: OtpPorChave): OtpDaTroca {
  return {
    enviar: (alvo, telefone) => otp.enviar(chaveDoDesafio(alvo), telefone),
    verificar: (alvo, codigo) => otp.verificar(chaveDoDesafio(alvo), codigo),
  };
}

