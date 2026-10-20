/**
 * *Token bucket* por canal e por par, e o *backoff* do `130429` (KAM-015,
 * critérios 5 e 6).
 *
 * ## Dois tectos, e são de coisas diferentes
 *
 * **Por `phone_number_id`**: 15 mensagens por segundo. É *proposta*, com folga
 * sobre os **20 mps CONFIRMADOS** em coexistência (`E1` §5), e o critério 5
 * di-lo assim. Para `cloud_only` a Meta dá 80 mps e nenhum documento deste
 * repositório fixa um número — fica o mesmo 15, configurável, e dito como
 * proposta. Enviar a 15 quando se pode a 80 é deixar débito na mesa; enviar a
 * 80 quando o canal está em coexistência é `130429` garantido, e o custo do
 * segundo erro é maior.
 *
 * **Por `(tenant_id, contact_id)`**: 1 mensagem por segundo e 30 por minuto.
 * É *proposta* e **a calibrar**, porque o *pair rate limit* real da Meta é
 * **NÃO VERIFICADO** (`E1` §5, e o §8.5 do doc 01 repete-o). Não se inventa um
 * valor para ele: o que está aqui é um tecto nosso, conservador, para não
 * descobrir o dela por um erro.
 *
 * ## O relógio entra por parâmetro
 *
 * Nenhuma função aqui chama `Date.now()`. O relógio é um argumento, e isso é o
 * que torna o critério 5 mensurável: «100 envios em fila nunca excedem 15/s em
 * nenhuma janela de 1 s medida no servidor falso e drenam em ≥ 6,6 s». Com o
 * relógio por dentro, o teste media o `setTimeout` da máquina; com ele por
 * fora, mede-se a regra.
 *
 * ## O *backoff* leva *jitter*, e o `Retry-After` manda
 *
 * O critério 6 pede «*backoff* exponencial com *jitter*, 3 tentativas». O
 * *jitter* não é enfeite: sem ele, N processos que apanhem o mesmo `130429`
 * voltam todos no mesmo instante e o segundo `130429` é garantido. E quando a
 * Meta manda `Retry-After`, é esse que vale — o §16 do doc 01 manda respeitá-lo
 * e um *backoff* que o ignore está a adivinhar contra quem sabe.
 */

/** Capacidade do *token bucket* por canal, em mensagens por segundo. */
export const MPS_POR_CANAL = 15;

/** Tecto por par, em mensagens por segundo. */
export const MPS_POR_PAR = 1;

/** Tecto por par, em mensagens por minuto. */
export const POR_MINUTO_POR_PAR = 30;

/** Tentativas de um envio que apanha `130429` ou 5xx. Três, como o critério 6. */
export const TENTATIVAS = 3;

/** O atraso base do *backoff*, em milissegundos. */
export const BASE_DO_BACKOFF_MS = 250;

/**
 * Um *token bucket* que enche a uma taxa fixa.
 *
 * O estado é mutável por desenho — é um balde —, e o relógio entra em cada
 * chamada. `tirar` devolve `0` quando há *token*, ou os milissegundos a esperar
 * quando não há: devolver o tempo em vez de um booleano é o que permite a quem
 * chama escalonar em vez de rodar à espera.
 */
export class Balde {
  readonly #capacidade: number;
  readonly #porSegundo: number;
  #tokens: number;
  #ultimo: number;

  constructor(capacidade: number, porSegundo: number, agoraMs: number) {
    this.#capacidade = capacidade;
    this.#porSegundo = porSegundo;
    // Nasce **cheio**: um canal que não enviou nada no último segundo pode
    // enviar a sua rajada. Nascer vazio fazia o primeiro envio de cada canal
    // esperar por nada.
    this.#tokens = capacidade;
    this.#ultimo = agoraMs;
  }

  /** Quantos *tokens* há agora, depois de encher pelo tempo passado. */
  disponiveis(agoraMs: number): number {
    const passado = Math.max(0, agoraMs - this.#ultimo);
    this.#tokens = Math.min(this.#capacidade, this.#tokens + (passado * this.#porSegundo) / 1000);
    this.#ultimo = agoraMs;
    return this.#tokens;
  }

  /**
   * Tira um *token*. Devolve `0` se conseguiu, ou os ms a esperar se não.
   *
   * O arredondamento para cima na espera é deliberado: arredondar para baixo
   * devolvia `0` ms para uma fracção de *token* em falta, e quem chamasse
   * voltava no mesmo instante e falhava outra vez.
   */
  tirar(agoraMs: number): number {
    if (this.disponiveis(agoraMs) >= 1) {
      this.#tokens -= 1;
      return 0;
    }
    const falta = 1 - this.#tokens;
    return Math.ceil((falta / this.#porSegundo) * 1000);
  }
}

/** Uma janela deslizante de contagem, para o tecto por minuto. */
export class Janela {
  readonly #tecto: number;
  readonly #duracaoMs: number;
  readonly #instantes: number[] = [];

  constructor(tecto: number, duracaoMs: number) {
    this.#tecto = tecto;
    this.#duracaoMs = duracaoMs;
  }

  /** Tenta contar um. Devolve `0` se conseguiu, ou os ms a esperar se não. */
  contar(agoraMs: number): number {
    const limite = agoraMs - this.#duracaoMs;
    while (this.#instantes.length > 0 && (this.#instantes[0] ?? 0) <= limite) {
      this.#instantes.shift();
    }
    if (this.#instantes.length < this.#tecto) {
      this.#instantes.push(agoraMs);
      return 0;
    }
    // O mais antigo é o que liberta a vaga.
    return Math.max(1, (this.#instantes[0] ?? agoraMs) + this.#duracaoMs - agoraMs);
  }
}

/**
 * Os três tectos de um envio, num objecto.
 *
 * Um balde por canal e, por par, um balde de segundo **e** uma janela de
 * minuto. Os mapas crescem com o tráfego, e é por isso que há `esquecer`: sem
 * ele, um processo de longa duração acumula um balde por par (tenant, contacto)
 * que viu uma vez — o que o `OBS-I` chama explosão de cardinalidade, aqui em
 * memória em vez de em etiquetas.
 */
export class Limites {
  readonly #porCanal = new Map<string, Balde>();
  readonly #porPar = new Map<string, Balde>();
  readonly #porParMinuto = new Map<string, Janela>();
  readonly #mps: number;

  constructor(mpsPorCanal: number = MPS_POR_CANAL) {
    this.#mps = mpsPorCanal;
  }

  /**
   * Os milissegundos a esperar antes de poder enviar, ou `0`.
   *
   * **Consome os três tectos de uma vez quando todos têm vaga**, e não consome
   * nenhum quando algum não tem. A ordem seria um defeito: consumir o do canal
   * e descobrir depois que o par está cheio gastava um *token* de canal que
   * ninguém usou, e com 15/s isso é 6,7% do débito por cada recusa de par.
   */
  pedir(phoneNumberId: string, tenantId: string, contactId: string, agoraMs: number): number {
    const canal = this.#balde(this.#porCanal, phoneNumberId, this.#mps, agoraMs);
    const chaveDoPar = `${tenantId}:${contactId}`;
    const par = this.#balde(this.#porPar, chaveDoPar, MPS_POR_PAR, agoraMs);
    let minuto = this.#porParMinuto.get(chaveDoPar);
    if (minuto === undefined) {
      minuto = new Janela(POR_MINUTO_POR_PAR, 60_000);
      this.#porParMinuto.set(chaveDoPar, minuto);
    }

    // Verifica sem consumir.
    if (canal.disponiveis(agoraMs) < 1) return canal.tirar(agoraMs);
    if (par.disponiveis(agoraMs) < 1) return par.tirar(agoraMs);

    const esperaDoMinuto = minuto.contar(agoraMs);
    if (esperaDoMinuto > 0) return esperaDoMinuto;

    // Os três têm vaga: consome os dois baldes (a janela já contou).
    canal.tirar(agoraMs);
    par.tirar(agoraMs);
    return 0;
  }

  /** Esquece o estado de um par. Ver a nota da classe. */
  esquecer(tenantId: string, contactId: string): void {
    const chave = `${tenantId}:${contactId}`;
    this.#porPar.delete(chave);
    this.#porParMinuto.delete(chave);
  }

  /** Quantos pares estão em memória. Para a métrica e para os testes. */
  get paresEmMemoria(): number {
    return this.#porPar.size;
  }

  #balde(mapa: Map<string, Balde>, chave: string, mps: number, agoraMs: number): Balde {
    let balde = mapa.get(chave);
    if (balde === undefined) {
      balde = new Balde(mps, mps, agoraMs);
      mapa.set(chave, balde);
    }
    return balde;
  }
}

/**
 * O atraso da tentativa `numero` (1-based), em milissegundos, com *jitter*.
 *
 * `esperar` são os segundos do `Retry-After`, quando a Meta o mandou: nesse
 * caso **é ele que vale**, e o `jitter` aplica-se por cima para que N processos
 * que o receberam juntos não voltem juntos. Ignorar o `Retry-After` era
 * adivinhar contra quem sabe (`docs/tecnica/01` §16).
 *
 * `aleatorio` entra por parâmetro para o teste ser determinístico. Um
 * `Math.random()` aqui dentro tornava o *jitter* impossível de afirmar.
 */
export function atrasoMs(
  numero: number,
  esperar: number | null,
  aleatorio: number,
): number {
  const base =
    esperar !== null && esperar > 0
      ? esperar * 1000
      : BASE_DO_BACKOFF_MS * 2 ** (numero - 1);
  // *Jitter* total («full jitter»): um valor uniforme em `[base/2, base]`. A
  // metade de baixo e não `[0, base]` porque um atraso que possa ser zero não
  // é atraso nenhum, e o `130429` voltava no mesmo instante.
  return Math.round(base / 2 + (base / 2) * aleatorio);
}

/** Os códigos da Meta que valem uma nova tentativa. */
export const CODIGOS_QUE_SE_REPETEM: readonly number[] = [
  // Débito excedido (CONFIRMADO, `E1` §5). É o caso do critério 6.
  130429,
  // Erro interno da Meta. Repetir um 5xx é o que o §14 manda.
  1,
  2,
];

/**
 * `true` quando vale a pena repetir.
 *
 * **Ramifica pelo `error.code` e nunca pelo estado HTTP**, e isso está escrito
 * aqui porque é uma armadilha que o KAM-024 documentou: nenhuma fonte deste
 * repositório dá o estado HTTP do `130429`, e há relato de a Cloud API devolver
 * `400` com o código no corpo. Um cliente que ramifique por `status === 429`
 * passa os testes contra o servidor falso e **nunca repete em produção**.
 *
 * O `131049` (limite de frequência por utilizador) **não** se repete: a Meta
 * não entregou de propósito, e insistir é gastar débito para ser recusado outra
 * vez. O `131047` (janela fechada) também não — se chegou aqui, a decisão
 * falhou antes, e repetir esconde o defeito.
 */
export function vaiRepetir(codigo: number, tentativa: number): boolean {
  return tentativa < TENTATIVAS && CODIGOS_QUE_SE_REPETEM.includes(codigo);
}
