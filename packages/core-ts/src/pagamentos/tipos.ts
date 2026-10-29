/**
 * O contrato `PaymentProvider` e o vocabulario de dinheiro (KAM-052).
 *
 * E a **costura definitiva** do principio 8: a forma fixa-se agora e os
 * adaptadores engrossam por fase (`docs/tecnica/04` §3.1). O KAM-054 traz o
 * `ManualProvider`, o KAM-056 o ProxyPay e o KAM-057 avalia o AppyPay; nenhum
 * deles volta a mexer nestes tipos.
 *
 * ## `Minor` e `bigint`, e nao e uma preferencia
 *
 * O dicionario §2 fixa dinheiro em **unidade menor inteira** (`*_minor`,
 * centimos de AOA) com `currency` explicito, «nunca virgula flutuante». Em
 * TypeScript isso obriga a `bigint` e nao a `number`: um `number` e um IEEE-754
 * de 64 bits, e a partir de 2^53 centimos deixa de representar inteiros
 * consecutivos — mas o problema morde muito antes disso, porque `0.1 + 0.2`
 * tambem e um `number`. O tipo nao impede sozinho que alguem escreva
 * `Number(valor)` tres ficheiros a seguir, e por isso ha um *lint* que falha o
 * *build*: `tools/money_lint`, no gate 2.
 *
 * ## O `reconcile` do titulo do ticket **nao e um metodo**
 *
 * O ticket chama-se «Interface PaymentProvider (com `verifyCallback` e
 * `reconcile`)», e o §3.1 — que e o contrato — nao tem metodo `reconcile`
 * nenhum. A reconciliacao do §8 faz-se com **dois** metodos, e e por isso que a
 * PA-04-1 os acrescentou em par: `listUnacknowledged` le a fila do facilitador
 * e `acknowledge` apaga de lá o que ja se processou. Implementar um
 * `reconcile()` a mais era inventar um terceiro nome para o que o documento
 * descreve com dois, e e a divida documental 150.
 *
 * ## Os oito metodos, e porque quatro sao opcionais
 *
 *     createCharge        cobra. O `chargeId` e gerado por nos ANTES da chamada
 *     status              consulta autenticada do estado
 *     refund              NOT_SUPPORTED no Piloto (ADR-004)
 *     payout              NOT_SUPPORTED no Piloto (ADR-004)
 *     verifyCallback      autentica o callback cru; sem ele a regra do §5 nao
 *                         e implementavel
 *     listUnacknowledged  (opcional) a fila de reconciliacao
 *     acknowledge         (opcional) apaga da fila do facilitador
 *     cancelCharge        (opcional) cancela antes de pago
 *
 * Os quatro primeiros e o `verifyCallback` sao obrigatorios porque **todo** o
 * adaptador os tem de ter, mesmo que seja para devolver `NOT_SUPPORTED`: o
 * `ManualProvider` nao tem HMAC, mas tem de ter forma de dizer que um callback
 * nao se autentica por aqui. Os tres opcionais sao capacidades que a matriz do
 * §3.2 declara adaptador a adaptador — o ProxyPay RPS tem fila de
 * reconciliacao, o EMIS directo nao tem consulta nenhuma —, e o registo
 * **recusa chamar** uma capacidade nao declarada em vez de descobrir o
 * `undefined` em execucao.
 */

/**
 * Unidade menor inteira (centimos de AOA). **Nunca virgula flutuante**
 * (dicionario §2).
 */
export type Minor = bigint;

/** A unica moeda do dominio enquanto a plataforma for de Angola (§3.4). */
export type Moeda = "AOA";

/** Os metodos de cobranca do §3.1. */
export type Metodo = "referencia" | "express_push" | "manual" | "cod";

/** Os sete erros tipados do §3.1. */
export type ProviderErr =
  | "AUTH"
  | "RATE_LIMIT"
  | "VALIDATION"
  | "REJECTED"
  | "TIMEOUT_UNKNOWN"
  | "UNAVAILABLE"
  | "NOT_SUPPORTED";

/** UUID, por forma e nao por marca nominal: o `Uuid` do §3.1. */
export type Uuid = string;

/** Instante em UTC (dicionario §2). ISO-8601 com `Z`. */
export type Instant = string;

/**
 * Como o facilitador autentica o callback (§3.1).
 *
 * O `desconhecido` nao e o mesmo que `none`, e a diferenca decide activacoes:
 * o `none` e uma afirmacao medida (o EMIS directo **nao** assina), e o
 * `desconhecido` e a ausencia de medicao (o AppyPay esta por responder,
 * `evidencia/E2` §9 perguntas 11–15). Os dois sao igualmente incapazes de
 * confirmar sozinhos, e o registo trata-os igual — ver `registo.ts`.
 */
export type CallbackAuth = "hmac" | "none" | "desconhecido";

/** Como o facilitador escreve montantes na sua API (§3.1). */
export type AmountFormat = "decimal2" | "inteiro_kz";

/** Referencia opaca de uma cobranca no lado do facilitador. */
export type ProviderRef = {
  readonly providerId: string;
  readonly providerChargeId?: string;
  readonly referencia?: string;
};

/**
 * O caminho no cofre, **nunca o segredo** (§6.2, criterio 7).
 *
 * E a mesma forma que o `token_ref` do §3.15 e o `credenciais_ref` da coluna:
 * uma referencia opaca que o `secrets` resolve em execucao. O adaptador recebe
 * isto e nao a chave; quem resolve e o KAM-010.
 */
export type AccountSecrets = {
  readonly accountId: Uuid;
  readonly credenciaisRef: string;
  /**
   * A referencia da chave **anterior**, durante a janela de rotacao do §3.3.
   *
   * «A rotacao exige janela de duas chaves: aceitar assinatura de qualquer uma
   * durante a janela, depois revogar a anterior.» Sem esta segunda referencia a
   * rotacao era uma interrupcao de servico, e o caso 8 da suite de conformidade
   * (§3.5) nao tinha como passar.
   */
  readonly credenciaisRefAnterior?: string;
};

/** Um callback HTTP cru, **antes** de qualquer interpretacao (§3.3). */
export type RawHttpCallback = {
  /**
   * O corpo **cru**, em bytes. Nao e `string`: o HMAC do ProxyPay calcula-se
   * «sobre o corpo cru» (§3.3), e um `JSON.parse` seguido de `JSON.stringify`
   * muda os bytes sem mudar o significado — o que faz a assinatura falhar num
   * callback genuino e, pior, obriga quem depura a afrouxar a verificacao.
   */
  readonly corpo: Uint8Array;
  readonly cabecalhos: Readonly<Record<string, string>>;
};

export type CreateChargeReq = {
  /** Gerado por nos **antes** da chamada; e a chave de idempotencia (§3.1). */
  readonly chargeId: Uuid;
  readonly tenantId: Uuid;
  readonly accountId: Uuid;
  /** O `numero_publico` da encomenda — correlacao curta (§3.1). */
  readonly numeroPublico: string;
  readonly amount: Minor;
  readonly currency: Moeda;
  readonly metodo: Metodo;
  /** Calculada pelo COM (`docs/tecnica/03` §6.4). */
  readonly validUntil: Instant;
  /** `contact_endpoints.contact_id`; o adaptador decifra so no envio (ADR-010). */
  readonly payer?: { readonly endpointRef: Uuid };
  /** Sem PII, e o ProxyPay aceita ate 10 pares (§3.1, §3.3). */
  readonly customFields: Readonly<Record<string, string>>;
};

export type ChargeResult =
  | {
      readonly kind: "referencia";
      readonly entidade: string;
      readonly referencia: string;
      readonly valor: Minor;
      readonly validoAte: Instant;
      readonly providerChargeId?: string;
    }
  | { readonly kind: "push"; readonly providerChargeId: string; readonly aprovarAte: Instant }
  | { readonly kind: "manual"; readonly instrucoes: string };

/** O estado de uma cobranca no lado do facilitador. */
export type ProviderStatus = {
  readonly estado: "pendente" | "paga" | "expirada" | "falhada" | "cancelada" | "desconhecida";
  readonly valor?: Minor;
  readonly currency?: Moeda;
  readonly pagoAt?: Instant;
  readonly providerEventId?: string;
};

export type RefundReq = { readonly chargeId: Uuid; readonly amount: Minor };
export type PayoutReq = {
  readonly tenantId: Uuid;
  readonly accountId: Uuid;
  readonly amount: Minor;
  readonly currency: Moeda;
};

/**
 * O resultado de um `refund`/`payout`: **sempre** uma recusa no Piloto.
 *
 * E um tipo e nao um `never` porque o ADR-004 pode mudar com parecer (D8) e a
 * costura nao se reescreve por isso; o que nao muda e que hoje o unico habitante
 * e `NOT_SUPPORTED` — a G-2 do §10.4, imposta em `registo.ts` e provada no
 * arranque.
 */
export type RecusaNaoSuportada = { readonly ok: false; readonly erro: "NOT_SUPPORTED" };
export type RefundResult = RecusaNaoSuportada;
export type PayoutResult = RecusaNaoSuportada;

/** Um evento ja autenticado, saido do `verifyCallback`. */
export type VerifiedEvent = {
  readonly providerEventId: string;
  readonly referencia?: string;
  readonly providerChargeId?: string;
  readonly valor: Minor;
  readonly currency: Moeda;
  /** O nome canonico do §3.4: `hmac`, `manual` ou `consulta`. */
  readonly authnMethod: "hmac" | "manual" | "consulta";
  readonly ocorridoEm: Instant;
  /** `fee` do facilitador, para custo real por transaccao (§3.3). */
  readonly fee?: Minor;
};

export type ProviderPaymentPage = {
  readonly eventos: readonly VerifiedEvent[];
  readonly cursor?: string;
};

/**
 * O que um adaptador declara saber fazer (§3.1).
 *
 * «O PAY **recusa** usar uma capacidade nao declarada e **recusa** activar um
 * adaptador com `callbackAuth='none'` sem `statusQuery=true`.» As duas recusas
 * vivem em `registo.ts`; este tipo e a declaracao sobre a qual elas decidem.
 */
export type ProviderCapabilities = {
  readonly metodos: readonly Metodo[];
  readonly callbackAuth: CallbackAuth;
  readonly statusQuery: boolean;
  readonly reconciliationQueue: boolean;
  readonly refund: boolean;
  readonly payout: boolean;
  /** Em segundos. Nao e dinheiro, e por isso e `number` (§3.1). */
  readonly chargeTtl: { readonly min: number; readonly max: number };
  /** Em segundos. */
  readonly idempotencyWindow: number;
  readonly amountFormat: AmountFormat;
  readonly refMaxLen: number;
  readonly settlement: string;
  /**
   * **Extensao minima a `ProviderCapabilities`** (Detalhes Tecnicos do bloco),
   * e a decisao fica registada no PR como o bloco manda.
   *
   * Marca o adaptador cuja confirmacao e **humana e auditada** em vez de
   * criptografica: o `ManualProvider` do §4 (ADR-013). E a unica dispensa da
   * regra `ADAPTER_CANNOT_CONFIRM`, e existe porque o §4 ja desenhou uma via de
   * confirmacao mais forte do que um HMAC — duas pessoas, tecto por pedido e
   * registo em `audit_log` — que simplesmente nao e uma assinatura.
   *
   * **Nao e uma dispensa generica e nao se soma a outras:** um adaptador
   * `humanOnly` nao pode declarar `callbackAuth: 'hmac'` nem `statusQuery`, e o
   * registo recusa-o — se tem via automatica, nao e humano-only, e entao a
   * regra vale para ele. Ver `registo.ts`.
   */
  readonly humanOnly: boolean;
  /**
   * Marca o adaptador cujo operador tem **licenca do BNA** para executar
   * operacoes de pagamento (G-2, §10.4 linha C).
   *
   * Sem um adaptador assim marcado, `payouts_enabled=true` **nao arranca**: a
   * plataforma nao pode executar payouts (ADR-004), e a unica via admitida e
   * «parceiro PSP executa com conta da PME», que precisa de um parceiro
   * licenciado. Nenhum adaptador do catalogo o tem hoje.
   */
  readonly pspLicenciado: boolean;
};

/** O contrato dos oito metodos do §3.1. */
export interface PaymentProvider {
  readonly id: string;
  readonly capabilities: ProviderCapabilities;

  createCharge(req: CreateChargeReq): Promise<ChargeResult>;
  status(ref: ProviderRef): Promise<ProviderStatus>;
  refund(req: RefundReq): Promise<RefundResult>;
  payout(req: PayoutReq): Promise<PayoutResult>;

  /** Lanca `AuthError` quando a assinatura nao verifica (§3.1). */
  verifyCallback(raw: RawHttpCallback, acct: AccountSecrets): Promise<readonly VerifiedEvent[]>;
  listUnacknowledged?(acct: AccountSecrets, cursor?: string): Promise<ProviderPaymentPage>;
  acknowledge?(acct: AccountSecrets, providerPaymentId: string): Promise<void>;
  cancelCharge?(ref: ProviderRef): Promise<void>;
}

/** Os nomes dos oito metodos, para o registo decidir sobre eles por nome. */
export const METODOS_DO_CONTRATO = [
  "createCharge",
  "status",
  "refund",
  "payout",
  "verifyCallback",
  "listUnacknowledged",
  "acknowledge",
  "cancelCharge",
] as const;

export type MetodoDoContrato = (typeof METODOS_DO_CONTRATO)[number];

/** Erro de autenticacao de um callback (§3.1: «lanca AuthError»). */
export class AuthError extends Error {
  readonly codigo: ProviderErr = "AUTH";
  constructor(mensagem: string) {
    super(mensagem);
    this.name = "AuthError";
  }
}

/** Um erro tipado do adaptador, com o codigo do §3.1. */
export class ProviderError extends Error {
  readonly codigo: ProviderErr;
  constructor(codigo: ProviderErr, mensagem: string) {
    super(mensagem);
    this.name = "ProviderError";
    this.codigo = codigo;
  }
}
