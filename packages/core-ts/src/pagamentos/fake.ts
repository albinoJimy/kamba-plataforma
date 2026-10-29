/**
 * `FakeProvider`: o adaptador de referencia que passa os dez casos (KAM-052,
 * criterio 9).
 *
 * ## Porque e que vive em `src/` e nao em `tests/`
 *
 * Porque e **a prova de que o harness mede alguma coisa**, e essa prova tem de
 * ser reutilizavel. Um harness com dez casos e nenhum adaptador que os passe nao
 * esta verificado: podia estar a exigir o impossivel, ou — pior — a passar por
 * ter os casos vazios. O `FakeProvider` fecha os dois lados de uma vez: os dez
 * casos passam, e o `test_o_fake_falha_quando_se_lhe_tira_a_barreira` tira-lhe
 * cada barreira e exige que o caso correspondente **fique vermelho**. E o mesmo
 * desenho dos passos de canario dos gates 3b, 9 e 11.
 *
 * E e tambem o duplo que o KAM-045, o KAM-046 e o KAM-053 vao usar para
 * exercitar o PAY sem facilitador nenhum — tres tickets que este bloqueia.
 *
 * ## O que ele imita, e com que fidelidade
 *
 * Imita o **ProxyPay RPS v2**, que e o unico adaptador do §3.2 com evidencia
 * CONFIRMADO para a autenticacao: HMAC-SHA256 hexadecimal em `X-Signature`
 * calculado «sobre o corpo cru» (§3.3), com a chave igual a API key e
 * `amountFormat: 'decimal2'`. Nao imita a API HTTP dele — nao faz chamadas
 * nenhumas —, e isso **nao e uma lacuna deste ticket**: o adaptador verdadeiro e
 * o KAM-056, e um simulador de ProxyPay escrito aqui seria uma invencao a fingir
 * medicao, que e a razao escrita no `gate_bd.py` para o KAM-020 nao ter
 * simulador de midia.
 *
 * O que ele **nao** declara: `pspLicenciado` (nenhum adaptador do catalogo o e)
 * e `humanOnly` (tem HMAC e consulta).
 */

import { createHmac, timingSafeEqual } from "node:crypto";

import type { FalhaProgramada } from "./conformidade.ts";
import { minorDeDecimal2, minorParaDecimal2 } from "./dinheiro.ts";
import {
  AuthError,
  type AccountSecrets,
  type ChargeResult,
  type CreateChargeReq,
  type Minor,
  type PayoutReq,
  type PayoutResult,
  type PaymentProvider,
  type ProviderCapabilities,
  ProviderError,
  type ProviderPaymentPage,
  type ProviderRef,
  type ProviderStatus,
  type RawHttpCallback,
  type RefundReq,
  type RefundResult,
  type VerifiedEvent,
} from "./tipos.ts";

/** O cabecalho da assinatura, como o §3.3 o escreve. */
export const CABECALHO_DA_ASSINATURA = "x-signature";

export const CAPACIDADES_DO_FAKE: ProviderCapabilities = {
  metodos: ["referencia"],
  callbackAuth: "hmac",
  statusQuery: true,
  reconciliationQueue: true,
  refund: false,
  payout: false,
  chargeTtl: { min: 60, max: 2_592_000 },
  idempotencyWindow: 300,
  amountFormat: "decimal2",
  refMaxLen: 9,
  settlement: "Referencia compensada as 20:00; liquidacao directa na conta da PME (§10.1).",
  humanOnly: false,
  pspLicenciado: false,
};

/** O corpo de um callback, na forma que o `FakeProvider` assina. */
type CorpoDoCallback = {
  readonly provider_event_id: string;
  readonly entity_id: string;
  readonly reference_id: string;
  /** `decimal2`, como o §3.3: texto e nunca numero. */
  readonly amount: string;
  readonly fee?: string;
  readonly payment_datetime: string;
};

/**
 * Resolve uma `credenciais_ref` na chave.
 *
 * E uma funcao injectada e nao o `Secrets` do KAM-010 de propria decisao: o
 * `FakeProvider` nao tem cofre, e obriga-lo a um era trazer o arranque do cofre
 * para dentro de um duplo de testes. O adaptador verdadeiro (KAM-056) recebe o
 * `Secrets`.
 */
export type ResolverChave = (ref: string) => Buffer;

export type OpcoesDoFake = {
  readonly id?: string;
  readonly entidade?: string;
  readonly resolver: ResolverChave;
};

/** O duplo. Guarda as cobrancas que criou e os eventos que verificou. */
export class FakeProvider implements PaymentProvider {
  readonly id: string;
  readonly capabilities = CAPACIDADES_DO_FAKE;

  readonly #entidade: string;
  readonly #resolver: ResolverChave;
  /** `chargeId` → cobranca. E **isto** que torna o `createCharge` idempotente. */
  readonly #cobrancas = new Map<string, ChargeResult>();
  /**
   * `referencia` → o pagamento **que o facilitador registou**. Serve o `status()`.
   *
   * ## Escreve-se no `corpoAssinado` e **nao** no `verifyCallback`
   *
   * E a correccao de um defeito que uma revisao adversarial apanhou: a primeira
   * versao escrevia aqui dentro do `verifyCallback`, pelo que o `status()` era um
   * **memorando do proprio callback** e a concordancia do caso 10 era
   * tautologica. O caso 10 existe pela razao que ele proprio escreve — «e a
   * discordancia que denuncia um callback forjado que passou a assinatura» —, e
   * um `status()` que repete o callback nunca pode discordar dele, isto e, o caso
   * nao conseguia detectar a unica coisa para que serve.
   *
   * Agora sao **dois caminhos independentes**: o `corpoAssinado` e o momento em
   * que o facilitador *emite* o evento (e e ele que registra o pagamento), e o
   * `verifyCallback` e o momento em que nos o *recebemos*. O caso 10 passa a
   * comparar duas leituras que nao se copiam uma a outra.
   *
   * Importa alem do ensaio: o `FakeProvider` e o duplo que o KAM-045, o KAM-046
   * e o KAM-053 vao usar, pelo que a propriedade propaga-se a esses tres.
   */
  readonly #noFacilitador = new Map<string, VerifiedEvent>();
  /** Eventos nao reconhecidos, para o `listUnacknowledged`. */
  readonly #fila = new Map<string, VerifiedEvent>();
  /** Quantas cobrancas o «facilitador» criou de facto. Serve o caso 7. */
  #criacoes = 0;
  #falha: FalhaProgramada = null;

  constructor(opcoes: OpcoesDoFake) {
    this.id = opcoes.id ?? "fake";
    this.#entidade = opcoes.entidade ?? "00123";
    this.#resolver = opcoes.resolver;
  }

  /** Programa a proxima chamada ao «facilitador» para falhar assim. */
  programar(falha: FalhaProgramada): void {
    this.#falha = falha;
  }

  /** A assinatura de um corpo com uma chave, na forma do §3.3. */
  assinar(corpo: Uint8Array, chave: Buffer): string {
    return createHmac("sha256", chave).update(corpo).digest("hex");
  }

  async createCharge(req: CreateChargeReq): Promise<ChargeResult> {
    const falha = this.#falha;
    this.#falha = null;
    if (falha === "rate_limit") {
      throw new ProviderError("RATE_LIMIT", "429 do facilitador (ensaio)");
    }
    // A cobranca **cria-se antes** de a resposta se perder, que e o que torna o
    // caso 7 um caso: o facilitador recebeu e gravou, e nos nao sabemos.
    const existente = this.#cobrancas.get(req.chargeId);
    // Conta so quando a cobranca e **nova**: e esta linha que o caso 7 mede. Um
    // adaptador sem a memoria do `chargeId` contava tres.
    if (existente === undefined) this.#criacoes += 1;
    const resultado: ChargeResult =
      existente ??
      ({
        kind: "referencia",
        entidade: this.#entidade,
        // Derivada do `chargeId` e nao de um contador: duas chamadas com o
        // mesmo `chargeId` tem de dar a **mesma** referencia mesmo que a
        // primeira resposta se tenha perdido.
        referencia: _referenciaDe(req.chargeId, this.capabilities.refMaxLen),
        valor: req.amount,
        validoAte: req.validUntil,
        providerChargeId: `fake-${req.chargeId}`,
      } satisfies ChargeResult);
    this.#cobrancas.set(req.chargeId, resultado);
    if (falha === "resposta_perdida") {
      throw new ProviderError(
        "TIMEOUT_UNKNOWN",
        "a resposta do facilitador perdeu-se; a cobranca pode existir (ensaio)",
      );
    }
    return resultado;
  }

  async status(ref: ProviderRef): Promise<ProviderStatus> {
    const chave = ref.referencia ?? ref.providerChargeId ?? "";
    const evento = this.#noFacilitador.get(chave);
    if (evento === undefined) return { estado: "desconhecida" };
    return {
      estado: "paga",
      valor: evento.valor,
      currency: evento.currency,
      pagoAt: evento.ocorridoEm,
      providerEventId: evento.providerEventId,
    };
  }

  async refund(_req: RefundReq): Promise<RefundResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  async payout(_req: PayoutReq): Promise<PayoutResult> {
    return { ok: false, erro: "NOT_SUPPORTED" };
  }

  /**
   * Verifica a assinatura sobre o corpo **cru** e devolve os eventos.
   *
   * Tres propriedades que os casos 1, 4, 5, 6 e 8 medem, e que se perdem com
   * facilidade:
   *
   * * compara com `timingSafeEqual` e nao com `===`. Um `===` sobre uma
   *   assinatura vaza o prefixo correcto pelo tempo de comparacao, e num
   *   callback de pagamento isso e um oraculo de forja;
   * * aceita a chave **anterior** durante a janela de rotacao (§3.3);
   * * **nao julga a hora nem a referencia.** Um callback autentico de uma
   *   referencia desconhecida (caso 3) ou recebido depois do `valid_until`
   *   (caso 6) e verificado e devolvido. A autenticidade e uma pergunta; se o
   *   pagamento e esperado e outra, e quem a responde e o §5.
   */
  async verifyCallback(
    raw: RawHttpCallback,
    acct: AccountSecrets,
  ): Promise<readonly VerifiedEvent[]> {
    const recebida = _cabecalho(raw.cabecalhos, CABECALHO_DA_ASSINATURA);
    if (recebida === undefined) {
      throw new AuthError(`callback sem o cabecalho ${CABECALHO_DA_ASSINATURA}`);
    }
    const refs = [acct.credenciaisRef];
    if (acct.credenciaisRefAnterior !== undefined) refs.push(acct.credenciaisRefAnterior);
    const aceita = refs.some((ref) =>
      _iguais(recebida, this.assinar(raw.corpo, this.#resolver(ref))),
    );
    if (!aceita) {
      throw new AuthError(
        "a assinatura do callback nao verifica com a chave actual nem com a " +
          "anterior (docs/tecnica/04 §3.3)",
      );
    }
    const corpo = _lerCorpo(raw.corpo);
    const evento: VerifiedEvent = {
      providerEventId: corpo.provider_event_id,
      referencia: corpo.reference_id,
      valor: minorDeDecimal2(corpo.amount),
      currency: "AOA",
      authnMethod: "hmac",
      ocorridoEm: corpo.payment_datetime,
      ...(corpo.fee === undefined ? {} : { fee: minorDeDecimal2(corpo.fee) }),
    };
    // **Nao escreve no `#noFacilitador`**: ver a nota desse campo. O `status()`
    // tem de ser um segundo caminho e nao um eco deste.
    this.#fila.set(corpo.provider_event_id, evento);
    return [evento];
  }

  async listUnacknowledged(
    _acct: AccountSecrets,
    _cursor?: string,
  ): Promise<ProviderPaymentPage> {
    return { eventos: [...this.#fila.values()] };
  }

  async acknowledge(_acct: AccountSecrets, providerPaymentId: string): Promise<void> {
    this.#fila.delete(providerPaymentId);
  }

  async cancelCharge(ref: ProviderRef): Promise<void> {
    const chave = ref.referencia ?? ref.providerChargeId ?? "";
    this.#noFacilitador.delete(chave);
  }

  /**
   * Um corpo assinado, para o banco de ensaio.
   *
   * **E aqui que o «facilitador» registra o pagamento**, e nao no
   * `verifyCallback`: este e o momento em que ele emite o evento. Ver a nota do
   * `#noFacilitador`.
   */
  corpoAssinado(
    corpo: CorpoDoCallback,
    ref: string,
  ): RawHttpCallback {
    this.#noFacilitador.set(corpo.reference_id, {
      providerEventId: corpo.provider_event_id,
      referencia: corpo.reference_id,
      valor: minorDeDecimal2(corpo.amount),
      currency: "AOA",
      authnMethod: "hmac",
      ocorridoEm: corpo.payment_datetime,
    });
    const bytes = new TextEncoder().encode(JSON.stringify(corpo));
    return {
      corpo: bytes,
      cabecalhos: { [CABECALHO_DA_ASSINATURA]: this.assinar(bytes, this.#resolver(ref)) },
    };
  }

  /** Quantas cobrancas o «facilitador» criou de facto. Serve o caso 7. */
  get criacoes(): number {
    return this.#criacoes;
  }

  /** A entidade EMIS deste adaptador de ensaio. */
  get entidade(): string {
    return this.#entidade;
  }

  /** A forma `decimal2` de um montante, para o banco de ensaio escrever o corpo. */
  decimal2(valor: Minor): string {
    return minorParaDecimal2(valor);
  }
}

function _cabecalho(
  cabecalhos: Readonly<Record<string, string>>,
  nome: string,
): string | undefined {
  for (const [chave, valor] of Object.entries(cabecalhos)) {
    if (chave.toLowerCase() === nome) return valor;
  }
  return undefined;
}

/** Comparacao de tempo constante. Recusa comprimentos diferentes sem lancar. */
function _iguais(a: string, b: string): boolean {
  const ba = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  if (ba.length !== bb.length) return false;
  return timingSafeEqual(ba, bb);
}

function _lerCorpo(bytes: Uint8Array): CorpoDoCallback {
  const texto = new TextDecoder().decode(bytes);
  let lido: unknown;
  try {
    lido = JSON.parse(texto);
  } catch {
    // **Nao e `AuthError`.** A assinatura verificou: o corpo e genuino e esta
    // malformado, que e um defeito do facilitador e nao uma tentativa de forja.
    // Confundir os dois mandava investigar um ataque onde ha um bug.
    throw new ProviderError("VALIDATION", "o corpo do callback nao e JSON valido");
  }
  const corpo = lido as Partial<CorpoDoCallback>;
  for (const campo of ["provider_event_id", "reference_id", "amount", "payment_datetime"] as const) {
    if (typeof corpo[campo] !== "string") {
      throw new ProviderError("VALIDATION", `o callback nao tem '${campo}'`);
    }
  }
  return corpo as CorpoDoCallback;
}

/**
 * Uma referencia de 9 digitos derivada do `chargeId`.
 *
 * Determinista de propria decisao — ver o `createCharge`. Nao e um hash
 * criptografico porque nao precisa de ser: a referencia e publica, e o que ela
 * tem de ser e **estavel** para o mesmo `chargeId`.
 */
function _referenciaDe(chargeId: string, comprimento: number): string {
  let acumulador = 0n;
  for (const caractere of chargeId) {
    acumulador = (acumulador * 31n + BigInt(caractere.codePointAt(0) ?? 0)) % 1_000_000_000n;
  }
  return `${acumulador}`.padStart(comprimento, "0").slice(-comprimento);
}
