/**
 * O adaptador ProxyPay OPG v1 — Multicaixa Express por push (KAM-056, criterio 8).
 *
 * Fica atras de uma **segunda** *flag* (`proxypay_opg_enabled`, ver `index.ts`)
 * e, mesmo ligada, **nao confirma sozinho**:
 *
 * * a assinatura do callback e **NAO VERIFICADA** (`evidencia/E2` §1.2: «docs
 *   OPG nao mencionam assinatura»), pelo que `callbackAuth: 'desconhecido'`;
 * * a consulta de transaccao esta na matriz do §3.2 (CONFIRMADO, API; o E2
 *   §1.2 so a nomeia na coluna de implicacao), mas o criterio pede-a
 *   **confirmada por escrito** antes de valer como autenticacao. Ate la,
 *   `statusQuery: false`, e o `activar` do registo recusa este adaptador com
 *   `ADAPTER_CANNOT_CONFIRM` — que e a forma mecanica de «o callback e dica e
 *   nunca confirma sozinho».
 *
 * Com ou sem consulta confirmada, o `verifyCallback` **nunca** devolve evento:
 * o corpo e dica, o *worker* le dele so o id da transaccao
 * (`transaccaoDaDica`) e pergunta ao facilitador, autenticado, o estado e o
 * valor pelo `status()` (§5: «facilitadores sem assinatura: o callback e
 * apenas uma dica; o PAY executa `status()`»). Com `statusQueryConfirmado:
 * true` — decisao a registar, credor `ext:KAM-103` — o registo deixa activar
 * o adaptador e chamar o `status()`; sem ela, recusa as duas coisas.
 *
 * ## A resposta perdida (F-09)
 *
 * «Retentar com o mesmo `Idempotency-Key` ate 5 min; depois de 5 min nao
 * repetir o POST; se desconhecido, `falhada('criacao_incerta')` e nova
 * tentativa so apos 30 min.» A cache do `Idempotency-Key` no facilitador e de
 * 5 min (CONFIRMADO): um POST repetido depois disso pode criar um **segundo**
 * push no telemovel do cliente. Este adaptador guarda o instante da primeira
 * tentativa por `chargeId` e recusa repetir passada a janela, com
 * `CriacaoIncerta`. A consulta por `chargeId` que o §7.2 sugere **nao esta
 * documentada** no E2 (NAO VERIFICADO que exista; a consulta que se conhece e
 * pelo id da transaccao, que se perdeu com a resposta): e por isso que o
 * desfecho e `criacao_incerta` e nao um `status()`.
 *
 * O instante da primeira tentativa so se grava quando o pedido **pode ter
 * saido** (sucesso ou `TIMEOUT_UNKNOWN`). Uma ligacao recusada nao conta: o
 * pedido nao saiu, e bloquear 30 min por isso era recusar cobrar sem razao.
 */

import { minorDeDecimal2, minorParaDecimal2 } from "../dinheiro.ts";
import {
  type AccountSecrets,
  type ChargeResult,
  type CreateChargeReq,
  type PaymentProvider,
  type PayoutReq,
  type PayoutResult,
  type ProviderCapabilities,
  ProviderError,
  type ProviderRef,
  type ProviderStatus,
  type RawHttpCallback,
  type RefundReq,
  type RefundResult,
  type Uuid,
  type VerifiedEvent,
} from "../tipos.ts";
import { pedir, type Transporte } from "./http.ts";
import { baseSegura, type ResolverDeChave } from "./rps.ts";
import { lerJson } from "./verify.ts";

export const ID_PROXYPAY_OPG = "proxypay_opg";

/** A cache do `Idempotency-Key` no facilitador (§3.3, CONFIRMADO). */
export const JANELA_DE_IDEMPOTENCIA_OPG_MS = 5 * 60_000;
/** O pedido expira aos 30 min (CONFIRMADO). */
export const EXPIRACAO_OPG_MS = 30 * 60_000;
/** O cliente tem 90 s para aprovar (CONFIRMADO). */
export const APROVACAO_OPG_MS = 90_000;

export function capacidadesOpg(statusQueryConfirmado: boolean): ProviderCapabilities {
  return {
    metodos: ["express_push"],
    callbackAuth: "desconhecido",
    statusQuery: statusQueryConfirmado,
    reconciliationQueue: false,
    refund: false,
    payout: false,
    chargeTtl: { min: 1_800, max: 1_800 },
    idempotencyWindow: 300,
    amountFormat: "decimal2",
    refMaxLen: 0,
    settlement: "Multicaixa Express na conta da PME; a plataforma nao toca nos fundos (ADR-004).",
    humanOnly: false,
    pspLicenciado: false,
  };
}

export type ContaOpg = {
  readonly segredos: AccountSecrets;
  readonly posId: string;
  /** O URL do *webhook* desta conta (`/hooks/pay/proxypay_opg/{token}`). */
  readonly callbackUrl?: string;
};

/** O que se guarda por `chargeId`: a primeira tentativa e, se chegou, o id. */
export type TentativaOpg = {
  readonly chargeId: Uuid;
  readonly accountId: Uuid;
  readonly primeiraMs: number;
  readonly transaccaoId?: string;
};

export type TentativasOpg = {
  porCobranca(chargeId: Uuid): Promise<TentativaOpg | undefined>;
  porTransaccao(transaccaoId: string): Promise<TentativaOpg | undefined>;
  guardar(tentativa: TentativaOpg): Promise<void>;
};

export class TentativasOpgEmMemoria implements TentativasOpg {
  readonly #porCobranca = new Map<string, TentativaOpg>();

  async porCobranca(chargeId: Uuid): Promise<TentativaOpg | undefined> {
    return this.#porCobranca.get(chargeId);
  }

  async porTransaccao(transaccaoId: string): Promise<TentativaOpg | undefined> {
    return [...this.#porCobranca.values()].find((t) => t.transaccaoId === transaccaoId);
  }

  async guardar(tentativa: TentativaOpg): Promise<void> {
    this.#porCobranca.set(tentativa.chargeId, tentativa);
  }
}

/** Passou a janela do `Idempotency-Key` sem resposta: nao se repete o POST. */
export class CriacaoIncerta extends ProviderError {
  readonly motivo = "criacao_incerta";
  readonly novaTentativaDepoisDe: string;
  constructor(novaTentativaDepoisDe: string) {
    super(
      "TIMEOUT_UNKNOWN",
      "criacao_incerta: a resposta do POST perdeu-se e passou a janela de 5 min do " +
        "Idempotency-Key. Repetir pode mandar um segundo push ao cliente; nova cobranca so " +
        `depois de ${novaTentativaDepoisDe}, quando o pedido original ja expirou (F-09)`,
    );
    this.name = "CriacaoIncerta";
    this.novaTentativaDepoisDe = novaTentativaDepoisDe;
  }
}

export type OpcoesOpg = {
  readonly base: string;
  readonly transporte: Transporte;
  readonly contas: { conta(accountId: Uuid): Promise<ContaOpg | undefined> };
  readonly chaves: ResolverDeChave;
  /** O numero Express do pagador, decifrado so no envio (ADR-010). */
  readonly telemovel: (endpointRef: Uuid) => Promise<string>;
  readonly tentativas: TentativasOpg;
  /** So `true` com a consulta confirmada por escrito (criterio 8). */
  readonly statusQueryConfirmado?: boolean;
  readonly agora?: () => number;
};

export class ProxyPayOpg implements PaymentProvider {
  readonly id = ID_PROXYPAY_OPG;
  readonly capabilities: ProviderCapabilities;

  readonly #o: OpcoesOpg;
  readonly #base: string;
  readonly #agora: () => number;

  constructor(opcoes: OpcoesOpg) {
    this.#o = opcoes;
    this.#base = baseSegura(opcoes.base);
    this.#agora = opcoes.agora ?? Date.now;
    this.capabilities = capacidadesOpg(opcoes.statusQueryConfirmado === true);
  }

  async createCharge(req: CreateChargeReq): Promise<ChargeResult> {
    if (req.metodo !== "express_push") {
      throw new ProviderError("NOT_SUPPORTED", `o OPG so faz push Express, e o pedido e '${req.metodo}'`);
    }
    if (req.currency !== "AOA" || req.amount <= 0n) {
      throw new ProviderError("VALIDATION", "o OPG cobra um montante positivo em AOA");
    }
    if (req.payer === undefined) {
      throw new ProviderError("VALIDATION", "o push Express precisa do pagador (payer.endpointRef)");
    }
    const conta = await this.#conta(req.accountId);
    const agora = this.#agora();
    const anterior = await this.#o.tentativas.porCobranca(req.chargeId);
    if (anterior !== undefined && anterior.accountId !== req.accountId) {
      throw new ProviderError("VALIDATION", "o chargeId ja tem tentativa OPG noutra conta");
    }
    if (anterior !== undefined && agora - anterior.primeiraMs > EXPIRACAO_OPG_MS) {
      throw new ProviderError(
        "VALIDATION",
        "o pedido OPG deste chargeId ja expirou (30 min): uma cobranca nova leva chargeId novo (F-06)",
      );
    }
    if (anterior?.transaccaoId !== undefined) {
      return _push(anterior.transaccaoId, anterior.primeiraMs);
    }
    if (anterior !== undefined && agora - anterior.primeiraMs > JANELA_DE_IDEMPOTENCIA_OPG_MS) {
      throw new CriacaoIncerta(new Date(anterior.primeiraMs + EXPIRACAO_OPG_MS).toISOString());
    }
    const primeiraMs = anterior?.primeiraMs ?? agora;
    const token = await this.#o.chaves(conta.segredos.credenciaisRef);
    const enviar = pedir(this.#o.transporte, {
      metodo: "POST",
      url: `${this.#base}/opg/v1/transactions`,
      cabecalhos: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": req.chargeId,
      },
      corpo: JSON.stringify({
        type: "payment",
        pos_id: conta.posId,
        mobile: await this.#o.telemovel(req.payer.endpointRef),
        amount: minorParaDecimal2(req.amount),
        ...(conta.callbackUrl === undefined ? {} : { callback_url: conta.callbackUrl }),
      }),
    }, [], true);
    let resposta: Awaited<typeof enviar>;
    try {
      resposta = await enviar;
    } catch (erro) {
      if (anterior === undefined && erro instanceof ProviderError && erro.codigo === "TIMEOUT_UNKNOWN") {
        await this.#o.tentativas.guardar({ chargeId: req.chargeId, accountId: req.accountId, primeiraMs });
      }
      throw erro;
    }
    const transaccaoId = _id(lerJson(new TextEncoder().encode(resposta.corpo)));
    await this.#o.tentativas.guardar({ chargeId: req.chargeId, accountId: req.accountId, primeiraMs, transaccaoId });
    return _push(transaccaoId, primeiraMs);
  }

  async status(ref: ProviderRef): Promise<ProviderStatus> {
    if (ref.providerChargeId === undefined) return { estado: "desconhecida" };
    const tentativa = await this.#o.tentativas.porTransaccao(ref.providerChargeId);
    if (tentativa === undefined) return { estado: "desconhecida" };
    const conta = await this.#conta(tentativa.accountId);
    return estadoDaTransaccao(await this.#transaccao(conta.segredos, ref.providerChargeId));
  }

  async refund(_req: RefundReq): Promise<RefundResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  async payout(_req: PayoutReq): Promise<PayoutResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  /**
   * O callback e **dica**, e nunca produz evento: devolve sempre zero.
   *
   * O §5.1 escreve as duas saidas do `verifyCallback` — «G1 (HMAC) **ou marca
   * como dica** (sem assinatura)» — e esta e a segunda. A confirmacao, se
   * vier, vem do `status()` que o *worker* chama a seguir, com
   * `authn_method='consulta'`, e nada do corpo do callback chega ao ledger.
   * Consultar aqui dentro punha um pedido ao facilitador no caminho do 2xx, que
   * o `hooks.ts` corta aos 300 ms.
   *
   * O corpo le-se so para recusar o que nem dica e (`VALIDATION`). Nao levanta
   * `AuthError`: nao ha assinatura para falhar, e um 401 mandava o facilitador
   * reentregar uma dica que ja ficou no *inbox*.
   */
  async verifyCallback(raw: RawHttpCallback, _acct: AccountSecrets): Promise<readonly VerifiedEvent[]> {
    _id(lerJson(raw.corpo));
    return [];
  }

  /**
   * O id da transaccao que uma dica nomeia, para o *worker* chamar `status()`.
   * E o unico campo do corpo que se le, e nao autentica nada.
   */
  transaccaoDaDica(raw: RawHttpCallback): string {
    return _id(lerJson(raw.corpo));
  }

  async #transaccao(acct: AccountSecrets, transaccaoId: string): Promise<unknown> {
    const token = await this.#o.chaves(acct.credenciaisRef);
    const resposta = await pedir(
      this.#o.transporte,
      {
        metodo: "GET",
        url: `${this.#base}/opg/v1/transactions/${encodeURIComponent(transaccaoId)}`,
        cabecalhos: { Authorization: `Bearer ${token}` },
      },
      [404],
    );
    return resposta.estado === 404 ? undefined : lerJson(new TextEncoder().encode(resposta.corpo));
  }

  async #conta(accountId: Uuid): Promise<ContaOpg> {
    const conta = await this.#o.contas.conta(accountId);
    if (conta === undefined) throw new ProviderError("VALIDATION", "conta de pagamento sem configuracao OPG");
    return conta;
  }
}

function _push(transaccaoId: string, primeiraMs: number): ChargeResult {
  return {
    kind: "push",
    providerChargeId: transaccaoId,
    aprovarAte: new Date(primeiraMs + APROVACAO_OPG_MS).toISOString(),
  };
}

function _id(lido: unknown): string {
  const id = typeof lido === "object" && lido !== null ? (lido as { id?: unknown }).id : undefined;
  if (typeof id === "string" && id.length > 0 && id.length <= 64) return id;
  if (typeof id === "number" && Number.isSafeInteger(id) && id >= 0) return `${id}`;
  throw new ProviderError("VALIDATION", "a transaccao OPG nao tem id");
}

/** `accepted` -> paga, `rejected` -> falhada, o resto -> pendente (E2 §1.2). */
export function estadoDaTransaccao(lido: unknown): ProviderStatus {
  if (typeof lido !== "object" || lido === null) return { estado: "desconhecida" };
  const t = lido as { status?: unknown; amount?: unknown };
  if (t.status === "rejected") return { estado: "falhada" };
  if (t.status !== "accepted") return { estado: "pendente" };
  if (typeof t.amount !== "string") {
    throw new ProviderError("VALIDATION", "a transaccao aceite nao tem amount em texto decimal2");
  }
  // O `providerEventId` estavel e o que deixa o G7 deduplicar a confirmacao por
  // consulta. O `pos_id` da resposta nao se confere: a forma dela e NAO
  // VERIFICADA, e a consulta ja vai com o *token* da conta.
  const id = (lido as { id?: unknown }).id;
  return {
    estado: "paga",
    valor: minorDeDecimal2(t.amount),
    currency: "AOA",
    ...(typeof id === "string" || typeof id === "number" ? { providerEventId: `opg:${id}` } : {}),
  };
}

/**
 * O aviso fixo anti-*phishing* do §9, que vai em **todas** as mensagens de
 * cobranca (§3.3).
 */
export const AVISO_ANTI_PHISHING =
  "A aprovacao aparece na sua app do banco; nunca partilhe o PIN.";

export type MensagemOpg = {
  readonly texto: string;
  /** `1000-1003`: o gateway falhou, e repete-se sem custo para o cliente. */
  readonly repetir: boolean;
  /** Os `2000-2012` sem mensagem propria registam o codigo (§3.3). */
  readonly registarCodigo: boolean;
};

/** Codigos OPG -> mensagem ao cliente (§3.3, CONFIRMADO em `E2` §1.2). */
export function mensagemOpg(codigo: number): MensagemOpg {
  const com = (texto: string, repetir = false, registarCodigo = false): MensagemOpg => ({
    texto: `${texto} ${AVISO_ANTI_PHISHING}`,
    repetir,
    registarCodigo,
  });
  if (codigo >= 1000 && codigo <= 1003) return com("Nao foi possivel enviar o pedido. A tentar novamente.", true);
  switch (codigo) {
    case 2001:
      return com("O saldo nao chega para este valor.");
    case 2003:
      return com("Atingiu o limite diario do cartao.");
    case 2004:
      return com("O tempo para aprovar terminou. Quer que reenvie?");
    case 3000:
      return com("Pedido recusado por si. Posso cancelar ou tentar outro meio.");
    default:
      // A mensagem generica e **proposta**: o §3.3 manda haver uma e nao a escreve.
      return com("Nao foi possivel concluir o pagamento. Posso tentar outro meio.", false, true);
  }
}
