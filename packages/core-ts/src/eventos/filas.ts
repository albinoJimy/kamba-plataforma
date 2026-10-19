/**
 * A porta das filas (KAM-005).
 *
 * O publicador não conhece o BullMQ: conhece esta interface. Três razões, e
 * nenhuma é gosto por abstracções:
 *
 * 1. **As garantias do BullMQ estão NÃO VERIFICADO** (`evidencia/E4` §2.10, e a
 *    nota do PR). Um desenho que o tenha como detalhe substituível é o que
 *    torna a decisão reversível — o próprio E4 nomeia o DBOS como o próximo
 *    passo natural, e a D12 (Redis ou Valkey) continua aberta.
 * 2. Os testes do laço — recuo, lote, roteamento — correm com uma fila falsa,
 *    sem Redis. Os que precisam de Redis a sério são os do gate (*kill -9*,
 *    Redis parado), e esses usam a implementação real.
 * 3. O `add` com `jobId` é o contrato que absorve duplicados. Escrito aqui, uma
 *    vez, em vez de espalhado pelo laço.
 *
 * A implementação sobre BullMQ está em `filas_bullmq.ts`.
 */

/** Um *job* a entregar. O `jobId` é o `event_id`: é o que deduplica. */
export interface Trabalho {
  /** `event_id` do envelope. Igual em cada republicação do mesmo evento. */
  readonly jobId: string;
  /** Nome do *job* dentro da fila: o `tipo` do evento. */
  readonly nome: string;
  /** O envelope, já convertido para a versão que o consumidor declara. */
  readonly dados: unknown;
}

/**
 * Política de repetição **do consumidor**, não do publicador (§6.2).
 *
 * `tentativas` é o `attempts` do BullMQ. O `atraso` é o **primeiro degrau** da
 * escada do consumidor (§6.4) — não a base de um recuo exponencial: o recuo é
 * `custom` e vem do `backoffStrategy` do *worker*, onde a escada inteira vive
 * (`trabalhador_bullmq.ts`). O recuo do **outbox** é outro
 * (`atrasoDaTentativa`), e os dois não se confundem: este é o que o consumidor
 * usa quando o seu tratador falha; o outro é o que o publicador usa quando a
 * fila não aceita.
 */
export interface Repeticao {
  readonly tentativas: number;
  readonly atraso: number;
}

/** 6 tentativas; o primeiro degrau da escada é 1 s (`docs/tecnica/06` §6.4). */
export const REPETICAO: Repeticao = { tentativas: 6, atraso: 1000 };

/** O que o publicador precisa de uma fila. */
export interface Filas {
  /**
   * Põe **todos** os *jobs* na fila `nome`, de uma vez.
   *
   * Em lote, e não um a um, e a razão é medida: com um `add` por *job*, um
   * ciclo de 200 linhas fazia 200 idas ao Redis, e a 50 eventos/s o publicador
   * não acompanhava — o p95 do atraso ficou em **9,0 s** contra o 1 s do
   * critério 8 (medido em `db/tests_eventos_carga`). Em lote é uma ida por
   * fila.
   *
   * Tem de ser **idempotente por `jobId`**: chamar duas vezes com o mesmo
   * `jobId` deixa um *job*, não dois. É isso que torna a republicação depois de
   * um *kill -9* inofensiva.
   */
  addLote(nome: string, trabalhos: readonly Trabalho[]): Promise<void>;
  /**
   * Quantos *jobs* estão por fazer na fila `nome`.
   *
   * Acrescentado pelo KAM-013, e não por simetria: o critério 7 manda
   * descartar estados não facturáveis «sob saturação (fila > 10.000 *jobs*)»,
   * e quem decide isso é o GWY — que sem este número não sabe se está
   * saturado. O KAM-005 não precisava dele porque o publicador varre o
   * *outbox* e a profundidade do que já saiu não muda nada do que ele faz.
   *
   * Conta o que **ainda não correu**: à espera, adiado e a correr. Os
   * concluídos ficam na fila por `removeOnComplete` e contá-los dava um número
   * que cresce com o tráfego bem tratado — o oposto de um sinal de saturação.
   */
  profundidade(nome: string): Promise<number>;
  /** Fecha as ligações. Chamado no encerramento. */
  fechar(): Promise<void>;
}

/** Fila em memória, para os testes do laço. Guarda por `(fila, jobId)`. */
export class FilasEmMemoria implements Filas {
  readonly #jobs = new Map<string, Trabalho>();
  /** Quantas vezes o `addLote` foi chamado, incluindo os repetidos. */
  chamadas = 0;
  /** Quando definido, `add` lança isto. Para provar o recuo. */
  falha: Error | null = null;

  async addLote(nome: string, trabalhos: readonly Trabalho[]): Promise<void> {
    this.chamadas += 1;
    if (this.falha !== null) throw this.falha;
    for (const trabalho of trabalhos) {
      const chave = `${nome}|${trabalho.jobId}`;
      if (!this.#jobs.has(chave)) this.#jobs.set(chave, trabalho);
    }
  }

  /**
   * Em memória não há estados: o que entrou está por fazer.
   *
   * Serve os testes do GWY que provam o *shedding* sem Redis — e para isso o
   * número tem de poder ser **forçado**, porque o que se quer provar é a
   * decisão a partir de uma profundidade, não a contagem.
   */
  async profundidade(nome: string): Promise<number> {
    return this.profundidadeForcada ?? this.contar(nome);
  }

  /** Quando definido, é o que `profundidade` devolve. Para provar a saturação. */
  profundidadeForcada: number | null = null;

  async fechar(): Promise<void> {
    /* nada a fechar */
  }

  /** Os *jobs* distintos, por `(fila, jobId)`. */
  jobs(): Map<string, Trabalho> {
    return new Map(this.#jobs);
  }

  /** Quantos *jobs* distintos ficaram na fila `nome`. */
  contar(nome: string): number {
    return [...this.#jobs.keys()].filter((c) => c.startsWith(`${nome}|`)).length;
  }

  repor(): void {
    this.#jobs.clear();
    this.chamadas = 0;
    this.falha = null;
    this.profundidadeForcada = null;
  }
}
