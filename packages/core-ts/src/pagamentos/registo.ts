/**
 * O registo de adaptadores e as duas recusas do §3.1 (KAM-052, criterios 2 e 3).
 *
 * O §3.1 fecha com uma frase que e, na pratica, dois mecanismos:
 *
 *   «O PAY **recusa** usar uma capacidade nao declarada e **recusa** activar um
 *    adaptador com `callbackAuth='none'` sem `statusQuery=true`.»
 *
 * ## A regra de activacao, e a divergencia dentro do proprio bloco
 *
 * O bloco do ticket escreve a regra **duas vezes e de duas formas**, e as duas
 * nao dao o mesmo resultado:
 *
 *   criterio 2          «`callbackAuth='none'` e `statusQuery=false`»
 *   Detalhes Tecnicos   `callbackAuth !== 'hmac' && !statusQuery`
 *
 * A diferenca e o `desconhecido`. Um adaptador que declara
 * `callbackAuth: 'desconhecido'` passa a leitura do criterio 2 — nao e `'none'`
 * — e falha a dos Detalhes Tecnicos. **E implementada a segunda**, por tres
 * razoes medidas e nao por preferencia:
 *
 * 1. **Ha um adaptador real nessa casa.** O AppyPay v2 esta em `NAO VERIFICADO
 *    (assinatura, *retries*, idempotencia)` na matriz do §3.2, e as perguntas
 *    11–15 de `evidencia/E2` §9 estao por responder. Com a leitura do criterio 2
 *    ele activava-se sem via de confirmacao nenhuma.
 * 2. **O §3.4 ja manda tratar o desconhecido como `none`**, por escrito, para o
 *    EMIS directo: «se imposto por um banco, tratar como `callbackAuth='none'`
 *    sem `statusQuery` ⇒ o adaptador **nao pode confirmar `paga` sozinho**».
 * 3. **Fail closed e o principio 1 do §2** deste documento: duvida ⇒ nao
 *    confirma. `desconhecido` e a propria definicao de duvida.
 *
 * A divergencia fica registada na divida documental 151 em vez de ser escolhida
 * em silencio. O que ela custa a quem le o criterio 2 a letra: nada — o
 * conjunto que esta regra recusa **contem** o que aquele recusa.
 *
 * ## Porque e uma funcao e nao um `if` no sitio onde se activa
 *
 * Porque a recusa tem de ser a mesma nos tres sitios que activam: o arranque do
 * servico, a mudanca de `payment_accounts.provider` de uma PME (§10.2: «a
 * passagem ao facilitador e uma troca de `payment_account.provider`») e a suite
 * de conformidade. Tres copias da regra divergem, e esta e uma regra em que
 * divergir significa confirmar um pagamento que ninguem autenticou.
 */

import {
  type MetodoDoContrato,
  type PaymentProvider,
  type ProviderCapabilities,
  ProviderError,
} from "./tipos.ts";

/** O codigo que o criterio 2 nomeia. */
export const ADAPTER_CANNOT_CONFIRM = "ADAPTER_CANNOT_CONFIRM";
/** Um adaptador sem a suite de conformidade verde nao e activavel (§3.5). */
export const CONFORMANCE_REQUIRED = "CONFORMANCE_REQUIRED";
/** Um `humanOnly` que tambem declara via automatica (ver `_coerencia`). */
export const HUMAN_ONLY_INCOERENTE = "HUMAN_ONLY_INCOERENTE";

export type CodigoDeRecusa =
  | typeof ADAPTER_CANNOT_CONFIRM
  | typeof CONFORMANCE_REQUIRED
  | typeof HUMAN_ONLY_INCOERENTE;

export class AdapterCannotConfirm extends Error {
  readonly codigo = ADAPTER_CANNOT_CONFIRM;
  readonly adaptador: string;
  constructor(adaptador: string, mensagem: string) {
    super(mensagem);
    this.name = "AdapterCannotConfirm";
    this.adaptador = adaptador;
  }
}

export class ConformanceRequired extends Error {
  readonly codigo = CONFORMANCE_REQUIRED;
  readonly adaptador: string;
  constructor(adaptador: string, mensagem: string) {
    super(mensagem);
    this.name = "ConformanceRequired";
    this.adaptador = adaptador;
  }
}

export class HumanOnlyIncoerente extends Error {
  readonly codigo = HUMAN_ONLY_INCOERENTE;
  readonly adaptador: string;
  constructor(adaptador: string, mensagem: string) {
    super(mensagem);
    this.name = "HumanOnlyIncoerente";
    this.adaptador = adaptador;
  }
}

/**
 * «Este adaptador consegue confirmar um pagamento por si?»
 *
 * Confirma quem tem **assinatura** no callback (`hmac`) ou **consulta
 * autenticada** de estado (`statusQuery`). As duas vias sao as do §5: um
 * callback autenticado, ou uma consulta que concorda com ele.
 */
export function podeConfirmar(capacidades: ProviderCapabilities): boolean {
  return capacidades.callbackAuth === "hmac" || capacidades.statusQuery;
}

/**
 * Um `humanOnly` nao pode declarar via automatica nenhuma.
 *
 * **Nao esta no bloco, e entra porque sem isto a dispensa era generica.** O
 * `humanOnly` dispensa da `ADAPTER_CANNOT_CONFIRM` por o §4 ter desenhado uma
 * via de confirmacao mais forte — duas pessoas, tecto por pedido, `audit_log`.
 * Um adaptador que declarasse `humanOnly: true` **e** `statusQuery: true`
 * estava a usar a dispensa para nao ser medido pela regra que ja cumpria, e um
 * que declarasse `humanOnly: true` com `callbackAuth: 'hmac'` tinha uma
 * assinatura que ninguem obrigava a verificar. Em qualquer dos dois casos a
 * etiqueta deixa de descrever o adaptador, e e a etiqueta que dispensa.
 *
 * O `ManualProvider` do §4 cumpre: `callbackAuth: 'none'`, `statusQuery: false`,
 * `reconciliationQueue: false` — a matriz do §3.2 escreve-lhe «n/a» nas tres
 * colunas.
 */
function _coerencia(adaptador: PaymentProvider): void {
  const c = adaptador.capabilities;
  if (!c.humanOnly) return;
  const automaticas: string[] = [];
  if (c.callbackAuth !== "none") automaticas.push(`callbackAuth='${c.callbackAuth}'`);
  if (c.statusQuery) automaticas.push("statusQuery=true");
  if (c.reconciliationQueue) automaticas.push("reconciliationQueue=true");
  if (automaticas.length > 0) {
    throw new HumanOnlyIncoerente(
      adaptador.id,
      `o adaptador '${adaptador.id}' declara humanOnly e tambem ${automaticas.join(", ")}: ` +
        "um adaptador com via automatica nao e humano-only, e a regra " +
        "ADAPTER_CANNOT_CONFIRM vale para ele",
    );
  }
}

/**
 * O oraculo «a suite de conformidade deste adaptador esta verde?» (§3.5).
 *
 * E uma porta e nao uma leitura de ficheiro: quem sabe o veredicto e o CI, e
 * neste ticket o unico habitante e o `FakeProvider`, que passa os dez casos no
 * gate 4. O KAM-054 e o KAM-056 ligam os seus.
 */
export type Conformidade = {
  green(idDoAdaptador: string): boolean;
};

/** Nenhum adaptador tem a suite verde: a omissao e recusar (fail closed). */
export const CONFORMIDADE_VAZIA: Conformidade = { green: () => false };

/**
 * A regra de activacao do bloco, inteira e num sitio so.
 *
 * Lanca em vez de devolver um booleano porque o chamador e o **arranque**: um
 * `false` ignorado era um servico a correr com um adaptador que nao confirma, e
 * e o caso que a G-2 e o ADR-013 existem para impedir.
 */
export function activar(adaptador: PaymentProvider, conformidade: Conformidade): void {
  _coerencia(adaptador);
  const c = adaptador.capabilities;
  if (!c.humanOnly && c.callbackAuth !== "hmac" && !c.statusQuery) {
    throw new AdapterCannotConfirm(
      adaptador.id,
      `o adaptador '${adaptador.id}' nao pode confirmar um pagamento: ` +
        `callbackAuth='${c.callbackAuth}' (nao e 'hmac') e statusQuery=false. ` +
        "Sem assinatura no callback nem consulta autenticada de estado, um " +
        "pagamento so se confirmaria por uma afirmacao nao autenticada " +
        "(ADR-013, docs/tecnica/04 §5). Adaptadores de confirmacao humana " +
        "auditada declaram humanOnly.",
    );
  }
  if (!conformidade.green(adaptador.id)) {
    throw new ConformanceRequired(
      adaptador.id,
      `o adaptador '${adaptador.id}' nao tem a suite de conformidade verde ` +
        "(docs/tecnica/04 §3.5): «Um adaptador sem a suite verde nao e " +
        "activavel em producao.»",
    );
  }
}

/**
 * Que capacidade e que cada metodo opcional exige para poder ser chamado.
 *
 * Os cinco metodos obrigatorios nao estao aqui: existem sempre. O `refund` e o
 * `payout` **tambem nao**, e a razao e a G-2 — nao se recusam por capacidade
 * nao declarada, recusam-se **sempre**, com `NOT_SUPPORTED`, e e o
 * `chamar` abaixo que o garante antes de chegar ao adaptador.
 */
const CAPACIDADE_EXIGIDA: Partial<Record<MetodoDoContrato, keyof ProviderCapabilities>> = {
  status: "statusQuery",
  listUnacknowledged: "reconciliationQueue",
  acknowledge: "reconciliationQueue",
};

/** O registo. Um adaptador so entra por `activar`. */
export class RegistoDeProviders {
  readonly #porId = new Map<string, PaymentProvider>();
  readonly #conformidade: Conformidade;

  constructor(conformidade: Conformidade = CONFORMIDADE_VAZIA) {
    this.#conformidade = conformidade;
  }

  /** Corre a regra de activacao e, se ela passar, registra. */
  activar(adaptador: PaymentProvider): void {
    activar(adaptador, this.#conformidade);
    this.#porId.set(adaptador.id, adaptador);
  }

  get(id: string): PaymentProvider | undefined {
    return this.#porId.get(id);
  }

  get ids(): readonly string[] {
    return [...this.#porId.keys()];
  }

  /** O adaptador marcado `psp_licenciado`, se houver (G-2). */
  get temPspLicenciado(): boolean {
    return [...this.#porId.values()].some((a) => a.capabilities.pspLicenciado);
  }

  /**
   * «Recusa chamar uma capacidade nao declarada» — a segunda recusa do §3.1.
   *
   * Duas coisas que a assinatura esconde e que importam:
   *
   * * o `refund` e o `payout` sao recusados **aqui**, com `NOT_SUPPORTED`, e o
   *   adaptador nunca e chamado. E a G-2 a morder no registo e nao em cada
   *   adaptador: um adaptador novo que se esquecesse de devolver
   *   `NOT_SUPPORTED` nao abria caminho nenhum;
   * * um metodo opcional **ausente** com a capacidade declarada e um defeito do
   *   adaptador, nao uma capacidade nao declarada, e por isso levanta
   *   `VALIDATION` e nao `NOT_SUPPORTED`. A diferenca importa para quem depura:
   *   «nao suportado» e uma resposta de desenho, «declarou e nao tem» e um bug.
   */
  chamar<N extends MetodoDoContrato>(id: string, metodo: N): PaymentProvider[N] {
    const adaptador = this.#porId.get(id);
    if (adaptador === undefined) {
      throw new ProviderError("VALIDATION", `adaptador desconhecido: '${id}'`);
    }
    if (metodo === "refund" || metodo === "payout") {
      throw new ProviderError(
        "NOT_SUPPORTED",
        `'${metodo}' nao e suportado (ADR-004, G-2): a plataforma nao detem ` +
          "fundos. Reembolso e processo manual (refund_cases, G-6) e payout " +
          "e executado pela PME a partir da conta dela.",
      );
    }
    const exigida = CAPACIDADE_EXIGIDA[metodo];
    if (exigida !== undefined && adaptador.capabilities[exigida] !== true) {
      throw new ProviderError(
        "NOT_SUPPORTED",
        `o adaptador '${id}' nao declara '${exigida}', pelo que '${metodo}' ` +
          "nao pode ser chamado (docs/tecnica/04 §3.1: o PAY recusa usar uma " +
          "capacidade nao declarada)",
      );
    }
    const funcao = adaptador[metodo];
    if (typeof funcao !== "function") {
      throw new ProviderError(
        "VALIDATION",
        `o adaptador '${id}' declara '${exigida ?? metodo}' mas nao implementa ` +
          `'${metodo}'`,
      );
    }
    return funcao.bind(adaptador) as PaymentProvider[N];
  }
}
