/**
 * O adaptador ProxyPay RPS v2 — referencias Multicaixa (KAM-056).
 *
 * E o facilitador que a arquitectura prefere (§3.2): callback com HMAC e fila
 * de reconciliacao. Implementa a `PaymentProvider` do KAM-052 sem lhe mexer nos
 * tipos, e fica atras de `proxypay_enabled=false` (ver `index.ts` deste
 * directorio) ate haver contrato (D4, KAM-103).
 *
 * ## O mapeamento, e o estado de cada peca
 *
 *     createCharge   POST /reference_ids -> PUT /references/{id}    CONFIRMADO
 *     status         GET /payments?n=100, filtrado pela referencia  ver abaixo
 *     verifyCallback X-Signature, HMAC-SHA256 do corpo cru          CONFIRMADO
 *     listUnack...   GET /payments?n=100                            CONFIRMADO
 *     acknowledge    DELETE /payments/{id}                          CONFIRMADO
 *     cancelCharge   DELETE /references/{id}                        NAO VERIFICADO
 *     refund/payout  NOT_SUPPORTED (ADR-004)
 *
 * Os CONFIRMADO sao de `evidencia/E2` §1.2; as formas dos corpos que o E2 nao
 * fixa estao listadas no `verify.ts`, e falham fechadas.
 *
 * ## A idempotencia do `createCharge`, e porque precisa de memoria
 *
 * O `PUT /references/{id}` e idempotente **pelo id** (CONFIRMADO). Mas o id
 * vem do `POST /reference_ids`, e um segundo `createCharge` com o mesmo
 * `chargeId` que pedisse outro id criava uma segunda referencia pagavel — duas
 * referencias Multicaixa para a mesma encomenda, e a Multicaixa nao admite
 * devolucao (§1.4). Por isso o id **reserva-se** em `ReferenciasEmitidas`
 * antes do `PUT`, e uma repeticao reutiliza-o:
 *
 *     resposta do POST perdida   nada reservado; repetir pede outro id, e o
 *                                primeiro nunca foi referencia (nao houve PUT)
 *     resposta do PUT perdida    id reservado; repetir faz o MESMO PUT
 *
 * A porta e a costura para a base: em producao a reserva vive na
 * `payment_charges` (o `referencia` da cobranca), e quem a escreve e o servico
 * `pay`, que nao existe nesta arvore (divida 148). A `ReferenciasEmMemoria` e a
 * implementacao dos ensaios.
 *
 * ## O `status()` le a fila, e o limite disso
 *
 * O E2 nao documenta consulta por referencia; a consulta autenticada que existe
 * e a fila `GET /payments` (§3.2: «consulta de estado: fila»). O `status()` le-a
 * e procura a referencia **e** o `chargeId` nos `custom_fields`. Isto responde
 * «paga» enquanto o pagamento nao foi reconhecido — e so se reconhece **depois**
 * do *commit* no ledger (§8 regra a), a partir do qual quem sabe e o ledger.
 *
 * Fora da fila a resposta e `desconhecida`, e **nao** `pendente` nem
 * `expirada`: a fila nao distingue «ainda nao pago» de «pago e ja reconhecido»,
 * e afirmar um dos dois era afirmar um facto que a consulta nao mediu.
 *
 * **E a fila nao tem cursor** (NAO VERIFICADO que tenha): o `GET /payments?n=100`
 * devolve sempre os cem mais antigos por reconhecer. Cem orfaos a cabeca — que a
 * regra b do §8 proibe apagar — tapam o resto da fila ao `status()` e ao *job*.
 * O *job* detecta-o e di-lo (`filaBloqueada`); destapa-o ops, que e quem pode
 * decidir sobre um pagamento que nao e nosso.
 */

import { minorParaDecimal2 } from "../dinheiro.ts";
import {
  type AccountSecrets,
  type ChargeResult,
  type CreateChargeReq,
  type Instant,
  type Minor,
  type PaymentProvider,
  type PayoutReq,
  type PayoutResult,
  type ProviderCapabilities,
  ProviderError,
  type ProviderPaymentPage,
  type ProviderRef,
  type ProviderStatus,
  type RawHttpCallback,
  type RefundReq,
  type RefundResult,
  type Uuid,
  type VerifiedEvent,
} from "../tipos.ts";
import { pedir, type Transporte } from "./http.ts";
import {
  chaveUtilizavel,
  eventoDoPagamento,
  exigirAssinatura,
  idDoPagamento,
  lerJson,
  lerPagamentoRps,
  type PagamentoRps,
} from "./verify.ts";

export const ID_PROXYPAY_RPS = "proxypay_rps";

/** Os limites do `amount` do API (§3.3, CONFIRMADO): 0,01 a 99.999.999,99. */
export const AMOUNT_MINIMO_RPS: Minor = 1n;
export const AMOUNT_MAXIMO_RPS: Minor = 9_999_999_999n;

/** Quantos pagamentos pede cada leitura da fila (§8: `GET /payments?n=100`). */
export const PAGINA_DA_FILA = 100;

/**
 * As capacidades do RPS (Detalhes Tecnicos: «RPS `callbackAuth='hmac'`,
 * `statusQuery=true`, `reconciliationQueue=true`, `amountFormat='decimal2'`»).
 *
 * O `chargeTtl` e o `refMaxLen` sao **proposta**: o E2 nao fixa a validade
 * maxima de uma referencia nem o comprimento do id (o plugin WooCommerce usa
 * 24 h por configuracao, INDICIO). O `idempotencyWindow` e o `chargeTtl.max`
 * porque o `PUT` e idempotente pelo id durante toda a vida da referencia.
 */
export const CAPACIDADES_RPS: ProviderCapabilities = {
  metodos: ["referencia"],
  callbackAuth: "hmac",
  statusQuery: true,
  reconciliationQueue: true,
  refund: false,
  payout: false,
  chargeTtl: { min: 300, max: 2_592_000 },
  idempotencyWindow: 2_592_000,
  amountFormat: "decimal2",
  refMaxLen: 9,
  settlement:
    "Referencia Multicaixa paga na conta da PME pelo banco dela; a plataforma nao toca nos fundos (ADR-004, §10.1).",
  humanOnly: false,
  pspLicenciado: false,
};

/** A configuracao de uma conta ProxyPay de uma PME. */
export type ContaProxyPay = {
  readonly segredos: AccountSecrets;
  /** A entidade EMIS da PME: vai na mensagem ao cliente e no G2. */
  readonly entidade: string;
};

export type ContasProxyPay = {
  conta(accountId: Uuid): Promise<ContaProxyPay | undefined>;
};

/** Uma referencia que pedimos ao facilitador para uma cobranca nossa. */
export type ReferenciaEmitida = {
  readonly chargeId: Uuid;
  readonly accountId: Uuid;
  readonly referencia: string;
  readonly validoAte: Instant;
  /**
   * O montante com que a referencia foi emitida. Uma repeticao com outro
   * montante recusa: o `PUT` pelo mesmo id **reescrevia** a referencia ja dada
   * ao cliente.
   */
  readonly valor: Minor;
};

/** A memoria do `chargeId` -> referencia. Ver o cabecalho deste ficheiro. */
export type ReferenciasEmitidas = {
  porCobranca(chargeId: Uuid): Promise<ReferenciaEmitida | undefined>;
  /** Todas, de todas as contas: o mesmo numero pode existir em duas entidades. */
  porReferencia(referencia: string): Promise<readonly ReferenciaEmitida[]>;
  /**
   * Reserva se o `chargeId` estiver livre, e devolve **a que ficou**. Dois
   * `createCharge` concorrentes com o mesmo `chargeId` acabam no mesmo id.
   */
  reservar(nova: ReferenciaEmitida): Promise<ReferenciaEmitida>;
};

/** A implementacao dos ensaios. Em producao e a `payment_charges`. */
export class ReferenciasEmMemoria implements ReferenciasEmitidas {
  readonly #porCobranca = new Map<string, ReferenciaEmitida>();

  async porCobranca(chargeId: Uuid): Promise<ReferenciaEmitida | undefined> {
    return this.#porCobranca.get(chargeId);
  }

  async porReferencia(referencia: string): Promise<readonly ReferenciaEmitida[]> {
    return [...this.#porCobranca.values()].filter((r) => r.referencia === referencia);
  }

  async reservar(nova: ReferenciaEmitida): Promise<ReferenciaEmitida> {
    const existente = this.#porCobranca.get(nova.chargeId);
    if (existente !== undefined) return existente;
    this.#porCobranca.set(nova.chargeId, nova);
    return nova;
  }
}

/**
 * Resolve uma `credenciais_ref` na chave. Em producao e o `Secrets.get` do
 * KAM-010; a chave **nunca** sai daqui para um registo ou uma mensagem.
 */
export type ResolverDeChave = (ref: string) => Promise<string>;

export type OpcoesRps = {
  /** `https://api.proxypay.co.ao` ou `https://api.sandbox.proxypay.co.ao` (CONFIRMADO). */
  readonly base: string;
  readonly transporte: Transporte;
  readonly contas: ContasProxyPay;
  readonly chaves: ResolverDeChave;
  readonly referencias: ReferenciasEmitidas;
  readonly agora?: () => number;
};

/**
 * O `Accept` da versao 2 do RPS. **INDICIO** (documentacao do fornecedor lida
 * de memoria de integracoes publicas, nao no E2); confirma-se no *sandbox*.
 */
const ACEITA_V2 = "application/vnd.proxypay.v2+json";

export class ProxyPayRps implements PaymentProvider {
  readonly id = ID_PROXYPAY_RPS;
  readonly capabilities = CAPACIDADES_RPS;

  readonly #base: string;
  readonly #transporte: Transporte;
  readonly #contas: ContasProxyPay;
  readonly #chaves: ResolverDeChave;
  readonly #referencias: ReferenciasEmitidas;
  readonly #agora: () => number;

  constructor(opcoes: OpcoesRps) {
    this.#base = baseSegura(opcoes.base);
    this.#transporte = opcoes.transporte;
    this.#contas = opcoes.contas;
    this.#chaves = opcoes.chaves;
    this.#referencias = opcoes.referencias;
    this.#agora = opcoes.agora ?? Date.now;
  }

  /**
   * Criterio 1: `POST /reference_ids` e `PUT /references/{id}` com `amount` em
   * `decimal2`, `end_datetime = valid_until` e `custom_fields = {charge}`.
   */
  async createCharge(req: CreateChargeReq): Promise<ChargeResult> {
    if (req.metodo !== "referencia") {
      throw new ProviderError("NOT_SUPPORTED", `o RPS so emite referencias, e o pedido e '${req.metodo}'`);
    }
    if (req.currency !== "AOA") {
      throw new ProviderError("VALIDATION", "o RPS so cobra em AOA");
    }
    if (req.amount < AMOUNT_MINIMO_RPS || req.amount > AMOUNT_MAXIMO_RPS) {
      throw new ProviderError(
        "VALIDATION",
        "o montante esta fora de 0,01..99.999.999,99 Kz, que e o intervalo do API (§3.3)",
      );
    }
    const camposExtra = Object.keys(req.customFields).filter((k) => k !== "charge");
    if (camposExtra.length > 0 || (req.customFields.charge ?? req.chargeId) !== req.chargeId) {
      throw new ProviderError(
        "VALIDATION",
        "o RPS so envia `custom_fields = {charge: chargeId}`: os campos sao copiados para o " +
          "pagamento e lidos por quem gere a conta da PME, e qualquer outro e um sitio por " +
          "onde PII sai sem ninguem a ver (criterio 1)",
      );
    }
    const validoAte = Date.parse(req.validUntil);
    if (Number.isNaN(validoAte) || validoAte <= this.#agora()) {
      throw new ProviderError("VALIDATION", "o valid_until nao e um instante futuro");
    }
    const conta = await this.#conta(req.accountId);
    const chave = _chaveOuRecusa(await this.#chaves(conta.segredos.credenciaisRef));

    let reservada = await this.#referencias.porCobranca(req.chargeId);
    if (reservada !== undefined) _mesmoPedido(reservada, req, validoAte);
    if (reservada === undefined) {
      const resposta = await pedir(this.#transporte, {
        metodo: "POST",
        url: `${this.#base}/reference_ids`,
        cabecalhos: _cabecalhos(chave),
      });
      reservada = await this.#referencias.reservar({
        chargeId: req.chargeId,
        accountId: req.accountId,
        referencia: _idDaReferencia(resposta.corpo, this.capabilities.refMaxLen),
        validoAte: new Date(validoAte).toISOString(),
        valor: req.amount,
      });
      // Dois `createCharge` concorrentes: o que perdeu a reserva fica com a do
      // outro, e tem de ser o mesmo pedido.
      _mesmoPedido(reservada, req, validoAte);
    }
    await pedir(this.#transporte, {
      metodo: "PUT",
      url: `${this.#base}/references/${encodeURIComponent(reservada.referencia)}`,
      cabecalhos: { ..._cabecalhos(chave), "Content-Type": "application/json" },
      corpo: JSON.stringify({
        amount: minorParaDecimal2(req.amount),
        end_datetime: reservada.validoAte,
        custom_fields: { charge: req.chargeId },
      }),
    });
    return {
      kind: "referencia",
      entidade: conta.entidade,
      referencia: reservada.referencia,
      valor: req.amount,
      validoAte: reservada.validoAte,
      // O `charge` que viaja nos `custom_fields` e devolta no pagamento: e a
      // correlacao do lado do facilitador, e desambigua o mesmo numero de
      // referencia em duas entidades.
      providerChargeId: req.chargeId,
    };
  }

  async status(ref: ProviderRef): Promise<ProviderStatus> {
    const emitida = await this.#emitida(ref);
    if (emitida === undefined) return { estado: "desconhecida" };
    const conta = await this.#conta(emitida.accountId);
    const pagamentos = await this.#lerFila(conta.segredos);
    // **O `charge` e obrigatorio.** Nos enviamo-lo sempre, e o E2 §1.2 da como
    // CONFIRMADO que passa para o pagamento: um pagamento a mesma referencia
    // sem ele e de outra integracao da PME (o `PUT` aceita ids escolhidos por
    // quem o faz), e dizer `paga` sobre ele era confirmar a nossa cobranca com o
    // dinheiro dela.
    const pago = pagamentos.find(
      (p) => p.referencia === emitida.referencia && p.chargeId === emitida.chargeId,
    );
    if (pago !== undefined) {
      return {
        estado: "paga",
        valor: pago.valor,
        currency: "AOA",
        pagoAt: pago.ocorridoEm,
        providerEventId: eventoDoPagamento(pago, "consulta").providerEventId,
      };
    }
    return { estado: "desconhecida" };
  }

  async refund(_req: RefundReq): Promise<RefundResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  async payout(_req: PayoutReq): Promise<PayoutResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  /**
   * Criterio 2. A assinatura verifica-se com a chave corrente **ou** a
   * anterior, sobre os bytes crus, **antes** de o corpo ser lido.
   *
   * Nao julga a hora nem a referencia: um pagamento autentico depois do
   * `valid_until`, ou de uma referencia que nao e nossa, verifica-se e
   * devolve-se. A pergunta «e esperado?» e do §5 (G3, G6), e um adaptador que a
   * respondesse aqui descartava o pagamento de um cliente.
   *
   * **Sem janela de ±5 min** (criterio 6): o RPS nao assina *timestamp*
   * nenhum, e o §5 diz que a defesa de *replay* e o G7 — reentregar um corpo
   * valido da o mesmo `providerEventId`, e a unicidade da base absorve-o.
   */
  async verifyCallback(raw: RawHttpCallback, acct: AccountSecrets): Promise<readonly VerifiedEvent[]> {
    // As duas idas ao cofre em paralelo: o `hooks.ts` corta o `verifyCallback`
    // aos 300 ms. **E a anterior nao pode derrubar a corrente**: se o cofre ja a
    // revogou e a conta ainda a aponta, o callback assinado com a corrente
    // continua a verificar — senao a rotacao perdia callbacks genuinos (F-16 ao
    // contrario). A corrente, se falhar, sobe: sem ela nao ha verificacao.
    const [corrente, anterior] = await Promise.all([
      this.#chaves(acct.credenciaisRef),
      acct.credenciaisRefAnterior === undefined
        ? Promise.resolve(undefined)
        : this.#chaves(acct.credenciaisRefAnterior).catch(() => undefined),
    ]);
    const chaves = anterior === undefined ? [corrente] : [corrente, anterior];
    exigirAssinatura(raw.corpo, raw.cabecalhos, chaves);
    return [eventoDoPagamento(lerPagamentoRps(lerJson(raw.corpo)), "hmac")];
  }

  async listUnacknowledged(acct: AccountSecrets, _cursor?: string): Promise<ProviderPaymentPage> {
    const pagamentos = await this.#lerFila(acct);
    return { eventos: pagamentos.map((p) => eventoDoPagamento(p, "consulta")) };
  }

  /**
   * Os pagamentos da fila, completos — o `job` de reconciliacao precisa do
   * `chargeId` e da entidade, que o `VerifiedEvent` nao leva.
   */
  async pagamentosPorReconhecer(acct: AccountSecrets): Promise<readonly PagamentoRps[]> {
    return this.#lerFila(acct);
  }

  /**
   * `DELETE /payments/{id}`. Um 404 e sucesso: o pagamento ja nao esta na
   * fila, que e o que se pedia — e e o que acontece quando a resposta de um
   * `DELETE` anterior se perdeu.
   *
   * **Nao decide se pode reconhecer.** Quem decide e o `reconcile.ts`, depois
   * do *commit* e so para cobrancas nossas (§8, regras a e b).
   */
  async acknowledge(acct: AccountSecrets, providerPaymentId: string): Promise<void> {
    const id = providerPaymentId.startsWith("rps:") ? idDoPagamento(providerPaymentId) : providerPaymentId;
    const chave = _chaveOuRecusa(await this.#chaves(acct.credenciaisRef));
    await pedir(
      this.#transporte,
      { metodo: "DELETE", url: `${this.#base}/payments/${encodeURIComponent(id)}`, cabecalhos: _cabecalhos(chave) },
      [404],
    );
  }

  /**
   * `DELETE /references/{id}`: a rota e **NAO VERIFICADA** (o E2 so lista o
   * `PUT`). A expiracao nao depende dela — o `end_datetime` ja faz o
   * facilitador recusar o pagamento depois do `valid_until` —, e por isso um
   * cancelamento que falhe nao deixa a referencia pagavel para sempre.
   *
   * **Um 404 e erro, e nao «ja cancelada»**: numa rota por confirmar, o 404 de
   * «rota desconhecida» e indistinguivel do de «referencia desconhecida», e
   * le-lo como sucesso dava todos os cancelamentos por feitos com a referencia
   * ainda pagavel.
   */
  async cancelCharge(ref: ProviderRef): Promise<void> {
    const emitida = await this.#emitida(ref);
    if (emitida === undefined) {
      throw new ProviderError("VALIDATION", "referencia que nao foi emitida por nos");
    }
    const conta = await this.#conta(emitida.accountId);
    const chave = _chaveOuRecusa(await this.#chaves(conta.segredos.credenciaisRef));
    await pedir(
      this.#transporte,
      {
        metodo: "DELETE",
        url: `${this.#base}/references/${encodeURIComponent(emitida.referencia)}`,
        cabecalhos: _cabecalhos(chave),
      },
    );
  }

  async #lerFila(acct: AccountSecrets): Promise<readonly PagamentoRps[]> {
    const chave = _chaveOuRecusa(await this.#chaves(acct.credenciaisRef));
    const resposta = await pedir(this.#transporte, {
      metodo: "GET",
      url: `${this.#base}/payments?n=${PAGINA_DA_FILA}`,
      cabecalhos: _cabecalhos(chave),
    });
    const lido = lerJson(new TextEncoder().encode(resposta.corpo));
    // A fila e uma lista JSON. NAO VERIFICADO no E2; um envelope falha fechado.
    if (!Array.isArray(lido)) {
      throw new ProviderError("VALIDATION", "a fila GET /payments nao devolveu uma lista");
    }
    return lido.map(lerPagamentoRps);
  }

  async #conta(accountId: Uuid): Promise<ContaProxyPay> {
    const conta = await this.#contas.conta(accountId);
    if (conta === undefined) {
      throw new ProviderError("VALIDATION", "conta de pagamento sem configuracao ProxyPay");
    }
    return conta;
  }

  /**
   * A referencia emitida a que um `ProviderRef` se refere.
   *
   * Pelo `providerChargeId` primeiro, que e o `chargeId` e e unico. So pela
   * `referencia` quando ela nao for ambigua: o mesmo numero pode existir em
   * duas entidades, e escolher uma das duas era consultar a conta errada.
   */
  async #emitida(ref: ProviderRef): Promise<ReferenciaEmitida | undefined> {
    if (ref.providerChargeId !== undefined) {
      const porCobranca = await this.#referencias.porCobranca(ref.providerChargeId);
      if (ref.referencia === undefined || porCobranca?.referencia === ref.referencia) return porCobranca;
      return undefined;
    }
    if (ref.referencia === undefined) return undefined;
    const candidatas = await this.#referencias.porReferencia(ref.referencia);
    if (candidatas.length > 1) {
      throw new ProviderError(
        "VALIDATION",
        "a referencia existe em mais do que uma conta: a consulta precisa do providerChargeId",
      );
    }
    return candidatas[0];
  }
}

/**
 * HTTPS, ou HTTP so para o anel local. O servidor falso dos ensaios corre em
 * `127.0.0.1`; qualquer outro `http://` levava a chave da PME em claro.
 */
export function baseSegura(base: string): string {
  const url = new URL(base);
  const local = url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) {
    throw new ProviderError("VALIDATION", "a base do facilitador tem de ser HTTPS (CONFIRMADO, E2 §1.2)");
  }
  return base.replace(/\/+$/, "");
}

/** Uma chave vazia nao autentica nada: e configuracao errada, e recusa. */
function _chaveOuRecusa(chave: string): string {
  if (!chaveUtilizavel(chave)) {
    throw new ProviderError("VALIDATION", "a credenciais_ref da conta resolveu numa chave vazia");
  }
  return chave;
}

/** Uma repeticao do `createCharge` tem de ser o mesmo pedido. */
function _mesmoPedido(reservada: ReferenciaEmitida, req: CreateChargeReq, validoAteMs: number): void {
  if (reservada.accountId !== req.accountId) {
    throw new ProviderError("VALIDATION", "o chargeId ja tem referencia noutra conta");
  }
  if (reservada.valor !== req.amount || Date.parse(reservada.validoAte) !== validoAteMs) {
    throw new ProviderError(
      "VALIDATION",
      "o chargeId ja tem referencia com outro montante ou outro valid_until: repetir o PUT " +
        "reescrevia a referencia que o cliente ja tem, e uma cobranca nova leva chargeId novo",
    );
  }
}

function _cabecalhos(chave: string): Record<string, string> {
  return { Authorization: `Token ${chave}`, Accept: ACEITA_V2 };
}

/**
 * O id que o `POST /reference_ids` devolve. **NAO VERIFICADO** se vem como
 * numero JSON, texto JSON ou objecto `{id}`: aceita-se o numero e o texto, que
 * sao as duas formas de «o corpo e o id», e o objecto, que e a do instrumento
 * do KAM-103. Qualquer outra falha fechada, e tambem um id mais comprido do que
 * o `refMaxLen` declarado — que e proposta e se confirma no *sandbox*.
 */
function _idDaReferencia(corpo: string, maximo: number): string {
  const lido = lerJson(new TextEncoder().encode(corpo));
  const candidato = typeof lido === "object" && lido !== null && !Array.isArray(lido) ? (lido as { id?: unknown }).id : lido;
  const texto =
    typeof candidato === "string"
      ? candidato
      : typeof candidato === "number" && Number.isSafeInteger(candidato) && candidato >= 0
        ? `${candidato}`
        : "";
  if (/^[0-9]+$/.test(texto) && texto.length <= maximo) return texto;
  throw new ProviderError("VALIDATION", "o POST /reference_ids nao devolveu um id de referencia");
}
