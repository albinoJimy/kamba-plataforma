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
 * O critério 6 pede «*backoff* exponencial com *jitter*, 3 tentativas» — três
 * **repetições**, quatro chamadas, pela razão escrita na constante
 * `REPETICOES`. O *jitter* não é enfeite: sem ele, N processos que apanhem o
 * mesmo `130429` voltam todos no mesmo instante e o segundo `130429` é
 * garantido. E quando a
 * Meta manda `Retry-After`, é esse que vale — o §16 do doc 01 manda respeitá-lo
 * e um *backoff* que o ignore está a adivinhar contra quem sabe.
 */

/** Capacidade do *token bucket* por canal, em mensagens por segundo. */
export const MPS_POR_CANAL = 15;

/** Tecto por par, em mensagens por segundo. */
export const MPS_POR_PAR = 1;

/** Tecto por par, em mensagens por minuto. */
export const POR_MINUTO_POR_PAR = 30;

/**
 * **Repetições** de um envio que apanha `130429` ou 5xx. Três, como o critério 6.
 *
 * Três *repetições* e não três *chamadas*, e a diferença é o que torna o
 * critério cumprível à letra. Ele diz «`130429` do servidor falso **3× seguida
 * de 200** ... **3 tentativas**»: com três chamadas no total, os três `130429`
 * esgotam-nas e o `200` nunca chega — a frase contradiz-se. Com três
 * repetições depois da primeira chamada são quatro chamadas e a sequência
 * encaixa: 429, 429, 429, 200.
 *
 * Entre duas leituras de um critério, a que o torna possível de cumprir é a
 * pretendida. A primeira versão deste módulo tinha três chamadas, e isso
 * deixava a caixa por marcar com o código a dizer que estava feita.
 */
export const REPETICOES = 3;

/** Chamadas no total: a primeira, mais as `REPETICOES`. */
export const TENTATIVAS = REPETICOES + 1;

/** O atraso base do *backoff*, em milissegundos. */
export const BASE_DO_BACKOFF_MS = 250;

/**
 * Quantos pares `(tenant, contacto)` cabem em memória.
 *
 * O mapa por par cresce com o tráfego: um *worker* de longa duração acumula um
 * `Balde` **e** uma `Janela` por cada par que já viu. O `esquecer` existe para
 * isso e **nunca é chamado em produção** — era a limitação que a nota da classe
 * declarava e ninguém fechava (achado da revisão adversarial), e uma limitação
 * declarada que nada impõe é um vazamento com documentação.
 *
 * Dez mil é o mesmo tecto que o `chr/canal.ts` usa para a sua *cache*, e a
 * política de despejo é a mesma: **o mais antigo a entrar**, que é o primeiro da
 * ordem de iteração de um `Map`. Não é LRU, e a diferença não se mede — um par
 * despejado volta a nascer cheio, que é o que um contacto que não fala há muito
 * merece.
 */
export const MAXIMO_DE_PARES = 10_000;

/**
 * A espera máxima que um envio aguenta antes de ser recusado, em ms.
 *
 * **Esperar não é sempre melhor do que recusar.** O tecto por minuto do par
 * (30/min) pode pedir até 60 s, e dormir um minuto dentro de uma chamada de
 * envio prende o chamador, o *job* e a ligação à base por causa de um tecto
 * nosso. Acima disto devolve-se `RATE_LIMITED`, que é o motivo que o
 * `MOTIVOS_DE_RECUSA` já declarava e que **nada devolvia** — um valor morto numa
 * lista fechada, que a revisão adversarial apanhou.
 *
 * Cinco segundos: mais do que qualquer espera do balde por segundo (67 ms no
 * canal, 1 s no par) e menos do que a do tecto por minuto. É *proposta*, e
 * calibra-se com o primeiro painel de débito real.
 */
export const ESPERA_MAXIMA_DE_DEBITO_MS = 5_000;

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

  constructor(capacidade: number, porSegundo: number, agoraMs: number, cheio = false) {
    this.#capacidade = capacidade;
    this.#porSegundo = porSegundo;
    // **Nasce vazio, e isso foi uma correccao medida.**
    //
    // A primeira versao nascia cheia, com a razao «um canal parado pode enviar
    // a sua rajada». O teste do criterio 5 recusou-a, e com razao: com quinze
    // fichas a partida saem quinze mensagens em `t=0`, a primeira ficha nova
    // chega a `t=67ms`, e a janela deslizante que termina em 67 ms ve
    // **dezasseis**. O criterio diz «nunca excedem 15/s em **nenhuma** janela
    // de 1 s», e uma janela que apanhe a rajada mais o primeiro
    // reabastecimento excede.
    //
    // E a aritmetica do proprio criterio diz qual das duas leituras e a
    // pretendida: «drenam em >= 6,6 s» sao 100/15 = 6,67 s, que so se obtem com
    // o balde **vazio** a partida. Com ele cheio seriam 85/15 = 5,67 s. O
    // numero do criterio e a prova de que nao ha rajada de graca.
    //
    // O custo e real e fica dito: o primeiro envio de cada canal espera 67 ms.
    // Contra um terceiro que conta — e que responde `130429` — e o lado certo
    // para errar.
    this.#tokens = cheio ? capacidade : 0;
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
  readonly #maximoDePares: number;

  constructor(mpsPorCanal: number = MPS_POR_CANAL, maximoDePares: number = MAXIMO_DE_PARES) {
    this.#mps = mpsPorCanal;
    this.#maximoDePares = maximoDePares;
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
    const canal = this.#balde(this.#porCanal, phoneNumberId, this.#mps, agoraMs, false);
    const chaveDoPar = `${tenantId}:${contactId}`;
    const par = this.#balde(this.#porPar, chaveDoPar, MPS_POR_PAR, agoraMs, true);
    let minuto = this.#porParMinuto.get(chaveDoPar);
    if (minuto === undefined) {
      minuto = new Janela(POR_MINUTO_POR_PAR, 60_000);
      this.#porParMinuto.set(chaveDoPar, minuto);
      this.#despejarPares();
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

  /**
   * Despeja pares até caber no tecto. O mais antigo a entrar sai primeiro.
   *
   * Chamado quando um par novo nasce, que é o único momento em que o mapa
   * cresce. Despeja os **dois** mapas pela mesma chave: deixar a `Janela` de um
   * par cujo `Balde` já saiu era trocar um vazamento por outro mais pequeno.
   */
  #despejarPares(): void {
    while (this.#porPar.size > this.#maximoDePares) {
      const primeira = this.#porPar.keys().next();
      if (primeira.done) return;
      this.#porPar.delete(primeira.value);
      this.#porParMinuto.delete(primeira.value);
    }
  }

  /** Quantos pares estão em memória. Para a métrica e para os testes. */
  get paresEmMemoria(): number {
    return this.#porPar.size;
  }

  /**
   * O balde de uma chave, criado na primeira vez que se vê.
   *
   * **`cheio` difere entre os dois tectos, e e o que cada um protege que o
   * decide.**
   *
   * O do **canal** nasce vazio: protege o debito da Meta, que conta numa janela
   * deslizante, e uma rajada inicial fazia a janela que a apanha exceder os 15
   * (medido — ver a nota do `Balde`).
   *
   * O do **par** nasce cheio: protege uma pessoa de uma rajada, e a primeira
   * mensagem a alguem nao e rajada nenhuma. Com capacidade 1 e vazio a
   * partida, **toda** a primeira mensagem a cada contacto esperava um segundo —
   * medido, e deu 100 s para 100 contactos diferentes num teste que devia dar
   * 6,7 s. Era transformar um tecto contra inundacao num atraso universal.
   */
  #balde(
    mapa: Map<string, Balde>,
    chave: string,
    mps: number,
    agoraMs: number,
    cheio: boolean,
  ): Balde {
    let balde = mapa.get(chave);
    if (balde === undefined) {
      balde = new Balde(mps, mps, agoraMs, cheio);
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
