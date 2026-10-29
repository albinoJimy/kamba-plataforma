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
  type ChargeResult,
  type CreateChargeReq,
  type Metodo,
  type MetodoDoContrato,
  type PaymentProvider,
  type ProviderCapabilities,
  ProviderError,
  type RecusaNaoSuportada,
} from "./tipos.ts";

/**
 * Os adaptadores a quem o criterio 2 reconhece confirmacao humana auditada.
 *
 * **Lista fechada, e nao um booleano que o adaptador se atribui.** O criterio
 * escreve a excepcao com um **nome** — «excepto adaptadores so de confirmacao
 * humana (`ManualProvider`)» —, e a primeira versao deste modulo leu-a como uma
 * propriedade que o proprio adaptador declara. Uma revisao adversarial mostrou o
 * que isso abre: qualquer adaptador com `humanOnly: true`, `callbackAuth:
 * 'none'` e `statusQuery: false` salta a `ADAPTER_CANNOT_CONFIRM` e e activado —
 * isto e, a guarda do ADR-013 desliga-se com uma linha nas capacidades do
 * adaptador que ela devia medir.
 *
 * O `manual` e o `ManualProvider` do §4, que o **KAM-054** entrega. Esta aqui
 * antes de existir de propria decisao: a lista e o contrato, e um adaptador que
 * nao esteja nela nao usa a dispensa.
 */
export const ADAPTADORES_DE_CONFIRMACAO_HUMANA: readonly string[] = ["manual"];

/**
 * Os adaptadores cujo operador tem licenca do BNA (G-2).
 *
 * **Vazia**, e pela mesma razao da lista acima: a primeira versao lia
 * `capabilities.pspLicenciado`, que o adaptador se atribui, pelo que a guarda
 * que impede o arranque com `payouts_enabled=true` era satisfeita por uma linha
 * no adaptador guardado. O §10.4 linha C exige um parceiro **licenciado**, e uma
 * licenca nao e uma propriedade que o software declare sobre si.
 *
 * Nenhum adaptador do catalogo do §3.2 esta aqui, e nenhum pode estar sem D8
 * (parecer) — pelo que `payouts_enabled=true` recusa sempre. E o pretendido.
 */
export const ADAPTADORES_COM_LICENCA_BNA: readonly string[] = [];

/**
 * As duas listas que dispensam, como parametro do registo.
 *
 * **Porque e um parametro e nao so a constante:** a constante e a politica de
 * **producao** e a omissao; passar outra e uma decisao visivel no sitio onde o
 * servico arranca, que e codigo em revisao. E o oposto de a etiqueta vir do
 * adaptador — ali a dispensa viajava dentro da coisa guardada, aqui esta no
 * chamador. E a mesma forma que o `verificarG4` usa para a lista da G-4.
 */
export type PoliticaDeActivacao = {
  readonly confirmacaoHumana: readonly string[];
  readonly licencaBna: readonly string[];
};

/** A politica de producao: o `ManualProvider` e nenhum PSP licenciado. */
export const POLITICA_DE_PRODUCAO: PoliticaDeActivacao = {
  confirmacaoHumana: ADAPTADORES_DE_CONFIRMACAO_HUMANA,
  licencaBna: ADAPTADORES_COM_LICENCA_BNA,
};

/** O codigo que o criterio 2 nomeia. */
export const ADAPTER_CANNOT_CONFIRM = "ADAPTER_CANNOT_CONFIRM";
/** Um adaptador sem a suite de conformidade verde nao e activavel (§3.5). */
export const CONFORMANCE_REQUIRED = "CONFORMANCE_REQUIRED";
/** Um `humanOnly` que tambem declara via automatica (ver `_coerencia`). */
export const HUMAN_ONLY_INCOERENTE = "HUMAN_ONLY_INCOERENTE";
/** Uma etiqueta que dispensa, posta por um adaptador que a lista nao reconhece. */
export const ETIQUETA_NAO_RECONHECIDA = "ETIQUETA_NAO_RECONHECIDA";

export type CodigoDeRecusa =
  | typeof ADAPTER_CANNOT_CONFIRM
  | typeof CONFORMANCE_REQUIRED
  | typeof HUMAN_ONLY_INCOERENTE
  | typeof ETIQUETA_NAO_RECONHECIDA;

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

export class EtiquetaNaoReconhecida extends Error {
  readonly codigo = ETIQUETA_NAO_RECONHECIDA;
  readonly adaptador: string;
  constructor(adaptador: string, mensagem: string) {
    super(mensagem);
    this.name = "EtiquetaNaoReconhecida";
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
function _coerencia(adaptador: PaymentProvider, politica: PoliticaDeActivacao): void {
  const c = adaptador.capabilities;
  // **A etiqueta nao se atribui.** Ver `PoliticaDeActivacao`: um adaptador que
  // ponha uma destas a `true` sem estar na lista esta a dispensar-se a si
  // proprio de uma guarda.
  if (c.humanOnly && !politica.confirmacaoHumana.includes(adaptador.id)) {
    throw new EtiquetaNaoReconhecida(
      adaptador.id,
      `o adaptador '${adaptador.id}' declara humanOnly e nao esta em ` +
        "ADAPTADORES_DE_CONFIRMACAO_HUMANA. O criterio 2 escreve a excepcao com " +
        "um nome («excepto adaptadores so de confirmacao humana, " +
        "ManualProvider»), e uma dispensa que o proprio adaptador se atribui " +
        "desliga a guarda do ADR-013 com uma linha nas capacidades que ela " +
        `devia medir. Reconhecidos: ${politica.confirmacaoHumana.join(", ") || "nenhum"}.`,
    );
  }
  if (c.pspLicenciado && !politica.licencaBna.includes(adaptador.id)) {
    throw new EtiquetaNaoReconhecida(
      adaptador.id,
      `o adaptador '${adaptador.id}' declara pspLicenciado e nao esta em ` +
        "ADAPTADORES_COM_LICENCA_BNA. Uma licenca do BNA nao e uma propriedade " +
        "que o software declare sobre si (§10.4, linha C), e esta etiqueta e o " +
        "que permite `payouts_enabled=true`. A lista esta vazia e so D8 a abre.",
    );
  }
  // **A G-2 na declaracao, e nao so na chamada.** O §10.4 tem dois mecanismos —
  // «`capabilities.payout=false`» **e** «chamada devolve `NOT_SUPPORTED`» — e a
  // primeira versao impunha so o segundo. Um adaptador que declare saber
  // reembolsar poe uma afirmacao falsa na superficie que a plataforma usa para
  // escolher adaptador por tenant (§3.2) e nos relatorios.
  const promete: string[] = [];
  if (c.refund) promete.push("refund=true");
  if (c.payout) promete.push("payout=true");
  if (promete.length > 0) {
    throw new EtiquetaNaoReconhecida(
      adaptador.id,
      `o adaptador '${adaptador.id}' declara ${promete.join(" e ")}: a G-2 do ` +
        "§10.4 exige `capabilities.payout=false`, e a plataforma nao detem " +
        "fundos (ADR-004). O reembolso e processo manual (G-6) e o payout e " +
        "executado pela PME a partir da conta dela.",
    );
  }
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
export function activar(
  adaptador: PaymentProvider,
  conformidade: Conformidade,
  politica: PoliticaDeActivacao = POLITICA_DE_PRODUCAO,
): void {
  _coerencia(adaptador, politica);
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

/**
 * «Este adaptador declara saber cobrar por este metodo?» — a primeira entrada da
 * lista do §3.1.
 *
 * **O `capabilities.metodos` nao era lido por linha nenhuma de producao**, e foi
 * uma revisao adversarial que o mediu: o `FakeProvider` declara
 * `metodos: ['referencia']` e aceitava `createCharge` com os quatro `Metodo`,
 * devolvendo uma referencia Multicaixa a um pedido `metodo: 'cod'`. O §3.1 abre a
 * enumeracao de `ProviderCapabilities` com «**metodos suportados**» e fecha com
 * «o PAY **recusa** usar uma capacidade nao declarada» — e esta era a capacidade
 * que faltava, isto e, metade do criterio 2.
 *
 * O `cod` e o caso concreto: o ADR-016 tem-no desligado por omissao, e um pedido
 * de pagamento a entrega que receba uma referencia e um cliente a pagar
 * adiantado uma encomenda que pediu para pagar na mao.
 */
export function suporta(capacidades: ProviderCapabilities, metodo: Metodo): boolean {
  return capacidades.metodos.includes(metodo);
}

/** O registo. Um adaptador so entra por `activar`. */
export class RegistoDeProviders {
  readonly #porId = new Map<string, PaymentProvider>();
  readonly #conformidade: Conformidade;
  readonly #politica: PoliticaDeActivacao;

  constructor(
    conformidade: Conformidade = CONFORMIDADE_VAZIA,
    politica: PoliticaDeActivacao = POLITICA_DE_PRODUCAO,
  ) {
    this.#conformidade = conformidade;
    this.#politica = politica;
  }

  /** Corre a regra de activacao e, se ela passar, registra. */
  activar(adaptador: PaymentProvider): void {
    activar(adaptador, this.#conformidade, this.#politica);
    this.#porId.set(adaptador.id, adaptador);
  }

  get(id: string): PaymentProvider | undefined {
    return this.#porId.get(id);
  }

  get ids(): readonly string[] {
    return [...this.#porId.keys()];
  }

  /**
   * Ha um adaptador registado **com licenca do BNA** (G-2)?
   *
   * Le a lista fechada e **nao** a declaracao do adaptador: ver
   * `ADAPTADORES_COM_LICENCA_BNA`. A conjuncao e deliberada — tem de estar
   * registado (isto e, ter passado a activacao) **e** estar na lista.
   */
  get temPspLicenciado(): boolean {
    return [...this.#porId.keys()].some((id) => this.#politica.licencaBna.includes(id));
  }

  /**
   * «Recusa chamar uma capacidade nao declarada» — a segunda recusa do §3.1.
   *
   * Tres coisas que a assinatura esconde e que importam:
   *
   * * o `refund` e o `payout` **devolvem** `NOT_SUPPORTED` em vez de lancar, e o
   *   adaptador nunca e chamado. E a G-2 a morder no registo e nao em cada
   *   adaptador. A primeira versao **lancava**, e uma revisao adversarial
   *   apanhou a divergencia: o criterio 3 escreve «`refund` e `payout` de
   *   qualquer adaptador **devolvem** `NOT_SUPPORTED`» e o §3.1 tipa o retorno
   *   (`RefundResult`), pelo que quem escrevesse
   *   `await registo.chamar(id, 'refund')(req)` apanhava uma excepcao onde o
   *   tipo promete um valor — e o `RefundResult` ficava inalcancavel pelo
   *   caminho que este modulo recomenda;
   * * uma **capacidade nao declarada** da `NOT_SUPPORTED`, e isso inclui agora os
   *   metodos opcionais que nao tem campo em `ProviderCapabilities`
   *   (`cancelCharge`): ausente e, por desenho, nao suportado;
   * * «declarou e nao implementou» da `VALIDATION`, porque e um bug e nao um
   *   desenho. A diferenca importa para quem depura — e a primeira versao dizia
   *   `declara 'cancelCharge' mas nao implementa 'cancelCharge'` sobre um metodo
   *   que o adaptador **nao** tinha declarado, que e uma frase que se contradiz.
   */
  chamar<N extends MetodoDoContrato>(id: string, metodo: N): PaymentProvider[N] {
    const adaptador = this.#porId.get(id);
    if (adaptador === undefined) {
      throw new ProviderError("VALIDATION", `adaptador desconhecido: '${id}'`);
    }
    if (metodo === "refund" || metodo === "payout") {
      const recusa: RecusaNaoSuportada = { ok: false, erro: "NOT_SUPPORTED" };
      // O `as unknown as` e inevitavel e fica dito: o `N` generico nao estreita
      // para `'refund' | 'payout'` dentro do ramo, pelo que o compilador nao
      // sabe que o retorno esperado e `Promise<RecusaNaoSuportada>`. A
      // alternativa era tipar `chamar` com sobrecargas por metodo, que e muito
      // aparato para a unica assinatura que o registo nao delega.
      return (async () => recusa) as unknown as PaymentProvider[N];
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
      // Sem capacidade associada, a ausencia **e** a nao-declaracao.
      if (exigida === undefined) {
        throw new ProviderError(
          "NOT_SUPPORTED",
          `o adaptador '${id}' nao implementa '${metodo}', que e opcional no ` +
            "docs/tecnica/04 §3.1 e nao tem campo em ProviderCapabilities: a " +
            "ausencia e a nao-declaracao",
        );
      }
      throw new ProviderError(
        "VALIDATION",
        `o adaptador '${id}' declara '${exigida}' mas nao implementa '${metodo}'`,
      );
    }
    return funcao.bind(adaptador) as PaymentProvider[N];
  }

  /**
   * `createCharge` com o metodo confrontado contra `capabilities.metodos`.
   *
   * E o caminho que fecha a primeira entrada da lista do §3.1 — ver `suporta`
   * para a medicao que mostrou que ela nao era lida. Quem chama `chamar(id,
   * 'createCharge')` recebe a funcao crua e **nao** passa por aqui; este metodo
   * existe para que o caminho recomendado seja o que verifica.
   */
  async cobrar(id: string, req: CreateChargeReq): Promise<ChargeResult> {
    const adaptador = this.#porId.get(id);
    if (adaptador === undefined) {
      throw new ProviderError("VALIDATION", `adaptador desconhecido: '${id}'`);
    }
    if (!suporta(adaptador.capabilities, req.metodo)) {
      throw new ProviderError(
        "NOT_SUPPORTED",
        `o adaptador '${id}' nao declara o metodo '${req.metodo}' ` +
          `(declara: ${adaptador.capabilities.metodos.join(", ")}). O ` +
          "docs/tecnica/04 §3.1 poe «metodos suportados» na primeira linha de " +
          "ProviderCapabilities, e o PAY recusa usar uma capacidade nao " +
          "declarada: sem isto, um pedido 'cod' recebia uma referencia " +
          "Multicaixa, isto e, um cliente a pagar adiantado uma encomenda que " +
          "pediu para pagar na mao (ADR-016)",
      );
    }
    return adaptador.createCharge(req);
  }
}
