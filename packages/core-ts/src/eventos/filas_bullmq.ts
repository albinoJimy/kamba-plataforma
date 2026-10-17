/**
 * A porta das filas sobre BullMQ (KAM-005).
 *
 * BullMQ 6.3.11 (MIT), declarado em `ci/supply-chain/licencas.yaml`, com
 * `ioredis` 5.11.1 (MIT) como cliente — a linha 5.x, que é a que o BullMQ
 * tem como *peer* (`>=5.0.0`) e a que tem tipos estáveis com o
 * `exactOptionalPropertyTypes` deste repositório. É o único ficheiro do repositório que
 * importa os dois: o publicador conhece a interface `Filas` e mais nada (ver
 * `filas.ts`).
 *
 * ## O cliente constrói-se aqui, e não se deixa ao BullMQ
 *
 * O BullMQ 6 tem o `ioredis` como **peer** e carrega-o por `require` dinâmico
 * quando lhe passamos opções de ligação. Num ambiente ESM — e este é, o
 * `package.json` tem `"type": "module"` — esse `require` falha, e o erro é
 * `BullMQ could not load the optional 'ioredis' package`, lançado dentro do
 * `new Queue(...)`. Medido no gate: toda a publicação falhava com a fila viva.
 * A própria mensagem diz o que fazer, e é o que se faz aqui: construir o
 * cliente e passar a **instância**.
 *
 * Uma instância para todas as filas, e não uma por fila: são 16 por consumidor,
 * e 16 ligações por consumidor ao Redis é desperdício sem contrapartida — o
 * `add` é um comando, não uma subscrição.
 *
 * ## O que se leu da documentação, e o que continua NÃO VERIFICADO
 *
 * O `evidencia/E4` §2.10 diz, e continua a dizer: «Garantias: a literatura
 * habitual é at-least-once com *jobs* stalled re-entregues, mas **não li a
 * documentação nesta sessão**: NÃO VERIFICADO». Nesta execução também não se
 * leu, e o estado **não muda** — ler o que o BullMQ afirma sobre si mesmo daria
 * INDÍCIO, não CONFIRMADO. O que se faz é o que o §6 manda: assumir o pior
 * caso. As quatro afirmações e o que cada uma implica estão em
 * `docs/eventos.md` §8.
 */

import { Queue } from "bullmq";
// A exportação **nomeada**, e não a de omissão: com `verbatimModuleSyntax`
// este repositório não inventa um `default` construível (`TS2351`, medido
// no gate 2).
import { Redis } from "ioredis";

import type { Filas, Trabalho } from "./filas.ts";
import { REPETICAO } from "./filas.ts";

/**
 * Quantos *jobs* concluídos e falhados se mantêm por fila.
 *
 * *Proposta*, a calibrar: é a janela em que o `jobId` ainda absorve um
 * duplicado, e é memória do Redis. 10 000 concluídos por fila, 16 filas por
 * consumidor — a conta cresce com os consumidores, e o sítio onde se mede é a
 * carga do KAM-006.
 */
export const MANTER_CONCLUIDOS = 10_000;
export const MANTER_FALHADOS = 10_000;

/**
 * O que obriga o cliente a **falhar** quando a fila está em baixo.
 *
 * Isto é uma correcção a um defeito medido, e não configuração de gosto. Por
 * omissão o `ioredis` tem a *fila offline* ligada: com o Redis em baixo, um
 * `add` **não falha** — fica guardado em memória à espera de a ligação voltar,
 * e a promessa nunca resolve. Medido no gate: com a fila parada 60 s, o
 * publicador ficava pendurado no primeiro `add`, o ciclo nunca lançava, e por
 * isso `tentativas` ficava a **0** e `proxima_tentativa_at` nunca era adiada —
 * isto é, o recuo do critério 4 não acontecia, e o sintoma em produção seria um
 * publicador vivo, sem erros, a não publicar nada.
 *
 * O desenho precisa do contrário: o `add` falha, o lote reverte, as linhas
 * recuam, e o ciclo seguinte tenta outra vez. O *outbox* é a verdade, e só o é
 * se a falha chegar até ele.
 *
 *     enableOfflineQueue: false   um comando com a ligação em baixo rejeita
 *     maxRetriesPerRequest: 1     uma repetição, não as vinte da omissão
 *     connectTimeout              não ficar à espera do primeiro `connect`
 *     retryStrategy               religa, mas sem desistir: a fila volta
 *
 * É mais uma consequência de «assumir o pior caso» (`evidencia/E4` §2.10): a
 * omissão do cliente **esconde** a indisponibilidade, e esconder é o que não
 * se pode.
 */
export const LIGACAO_QUE_FALHA_DEPRESSA = {
  enableOfflineQueue: false,
  maxRetriesPerRequest: 1,
  connectTimeout: 5_000,
  // Religa sempre, com espera limitada: a fila parada volta, e quando voltar o
  // publicador tem de a encontrar sem ser reiniciado (critério 4).
  retryStrategy: (tentativas: number) => Math.min(tentativas * 200, 2_000),
};

/**
 * A ligação de quem **consome**, que é o oposto da de cima — e tem de ser.
 *
 * O BullMQ **recusa-se** a criar um `Worker` sobre uma ligação com
 * `maxRetriesPerRequest` diferente de `null`: «Your redis options
 * maxRetriesPerRequest must be null». Não é uma preferência dele; é o que um
 * *worker* precisa. Ele fica bloqueado num `BRPOPLPUSH` à espera do próximo
 * *job*, e uma leitura que desiste ao fim de N tentativas transforma uma
 * reconexão numa paragem de consumo.
 *
 * As duas exigências são opostas porque os dois lados querem coisas opostas:
 *
 *     publicador   o `add` tem de **falhar** com a fila em baixo, para o
 *                  outbox recuar e tentar outra vez. O outbox é a verdade, e
 *                  só o é se a falha chegar até ele (KAM-005, critério 4).
 *     consumidor   a leitura tem de **esperar**. Não há nada para recuar: o
 *                  que ele perderia ao desistir não volta por si, e a rede
 *                  para o que se perde é o reconciliador (§6.5).
 *
 * Aprendeu-se à custa de dezanove testes vermelhos no gate 8, todos com a
 * mesma linha no registo do processo: o consumidor morria ao arrancar.
 */
export const LIGACAO_QUE_ESPERA = {
  // `null`, e não um número: é o que o BullMQ exige de um `Worker`.
  maxRetriesPerRequest: null,
  connectTimeout: 5_000,
  retryStrategy: (tentativas: number) => Math.min(tentativas * 200, 2_000),
};

/**
 * Quanto tempo um `addLote` pode levar antes de se declarar a fila indisponível.
 *
 * **Isto é o que torna o critério 4 possível, e é a terceira correcção ao mesmo
 * problema.** Com o Redis em baixo, nenhuma das duas primeiras chega:
 *
 * 1. a *fila offline* do `ioredis` desligada (`LIGACAO_QUE_FALHA_DEPRESSA`) faz
 *    um **comando** rejeitar — mas o `add` do BullMQ não chega a mandar comando
 *    nenhum: espera primeiro que o cliente esteja pronto;
 * 2. o `connectTimeout` limita **cada tentativa** de ligação, e o
 *    `retryStrategy` manda tentar outra vez — o que é o certo (a fila volta) e
 *    não ajuda nada a quem está a aguardar.
 *
 * Medido no gate, com o contentor da fila parado: o publicador ficava pendurado
 * no primeiro `add` — a escrever `getaddrinfo ENOTFOUND` em ciclo, porque o
 * nome do contentor deixa de resolver — e nunca lançava. `tentativas` ficava a
 * **0**, `proxima_tentativa_at` nunca era adiada, e o sintoma em produção seria
 * um publicador vivo, sem erros registados, a não publicar nada.
 *
 * Com o limite, o `add` falha, o lote reverte, as linhas recuam e o ciclo
 * seguinte tenta outra vez — que é o desenho. Cinco segundos é **proposta**:
 * três ordens de magnitude acima de um `add` saudável (um comando ao Redis) e
 * bem abaixo do tecto de 30 s do recuo, para que um ciclo de 200 linhas não
 * consuma a janela de recuperação.
 *
 * Um `add` que estoure o limite **pode ainda assim chegar** mais tarde: a
 * promessa não se cancela. Não é problema — a entrega é *at-least-once* por
 * desenho, e o `jobId = event_id` absorve o duplicado.
 */
export const TEMPO_MAXIMO_DO_ADD = 5_000;

/** O `add` não respondeu no tempo dado. Conta como fila indisponível. */
export class FilaLentaError extends Error {
  constructor(fila: string, ms: number) {
    super(
      `a fila ${fila} nao aceitou o job em ${ms} ms: trata-se como ` +
        "indisponivel, o lote reverte e as linhas recuam",
    );
    this.name = "FilaLentaError";
  }
}

async function comLimite<T>(
  promessa: Promise<T>,
  fila: string,
  ms = TEMPO_MAXIMO_DO_ADD,
): Promise<T> {
  let temporizador: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promessa,
      new Promise<never>((_, rejeitar) => {
        temporizador = setTimeout(() => rejeitar(new FilaLentaError(fila, ms)), ms);
      }),
    ]);
  } finally {
    if (temporizador !== undefined) clearTimeout(temporizador);
  }
}

/**
 * `redis://[utilizador:senha@]anfitriao[:porta][/base]` em opções.
 *
 * A URL desdobra-se aqui, e não se passa ao cliente: o construtor do `ioredis`
 * 6 aceita `(url)` ou `(opcoes)`, mas não `(url, opcoes)` — e são as opções que
 * levam o `enableOfflineQueue: false` de que o critério 4 depende. Desdobrar é
 * o que permite ter os dois.
 */
export function opcoesDaUrl(url: string) {
  const endereco = new URL(url);
  const base = endereco.pathname.replace(/^\//, "");
  return {
    host: endereco.hostname,
    ...(endereco.port === "" ? {} : { port: Number(endereco.port) }),
    ...(endereco.username === "" ? {} : { username: endereco.username }),
    ...(endereco.password === "" ? {} : { password: endereco.password }),
    ...(base === "" ? {} : { db: Number(base) }),
  };
}

/** Ligação ao Redis-compatível. `url` é `redis://anfitriao:porta`. */
export interface LigacaoDaFila {
  readonly url?: string;
  readonly host?: string;
  readonly port?: number;
  readonly username?: string;
  readonly password?: string;
  readonly db?: number;
}

/**
 * Filas BullMQ, criadas à medida que são usadas, sobre uma só ligação.
 *
 * São 16 por consumidor, e os consumidores vêm das subscrições: criar todas ao
 * arrancar obrigava a saber a lista, que é configuração em base de dados.
 */
export class FilasBullmq implements Filas {
  readonly #filas = new Map<string, Queue>();
  readonly #cliente: Redis;

  constructor(ligacao: LigacaoDaFila) {
    const { url, ...resto } = ligacao;
    this.#cliente = new Redis({
      ...resto,
      ...(url === undefined ? {} : opcoesDaUrl(url)),
      ...LIGACAO_QUE_FALHA_DEPRESSA,
    });
    // Sem isto, um erro de ligação num cliente `ioredis` sem ouvinte de `error`
    // é uma excepção não tratada que derruba o processo — e derrubar o
    // publicador quando a fila cai é o oposto do que o critério 4 pede. O erro
    // chega a quem importa pelo `add`, que rejeita.
    this.#cliente.on("error", () => {});
  }

  #fila(nome: string): Queue {
    let fila = this.#filas.get(nome);
    if (fila === undefined) {
      fila = new Queue(nome, { connection: this.#cliente });
      this.#filas.set(nome, fila);
    }
    return fila;
  }

  async addLote(nome: string, trabalhos: readonly Trabalho[]): Promise<void> {
    if (trabalhos.length === 0) return;
    // `addBulk`, e não um `add` por *job*: é **uma** ida ao Redis por fila, em
    // vez de uma por *job*. Com 200 linhas por ciclo a diferença não é de
    // elegância — é a diferença entre acompanhar 50 eventos/s e não acompanhar
    // (critério 8, medido).
    await comLimite(
      this.#fila(nome).addBulk(
        trabalhos.map((trabalho) => ({
          name: trabalho.nome,
          data: trabalho.dados,
          opts: {
            jobId: trabalho.jobId,
            attempts: REPETICAO.tentativas,
            // `custom`, e nao `exponential`: e assim que o BullMQ passa a
            // decisao do atraso ao `backoffStrategy` do *worker*, onde vive a
            // escada do §6.4 (1 s, 5 s, 30 s, 2 min, 10 min). Com o
            // `exponential` que aqui estava, o recuo real era 1 s, 2 s, 4 s,
            // 8 s, 16 s — a contagem de tentativas certa e os intervalos
            // errados, que e a pior combinacao porque passa despercebida. O
            // `REPETICAO.atraso` fica a ser o primeiro degrau da escada, e o
            // teste `test_o_job_pede_a_escada_do_consumidor` prende os dois.
            backoff: { type: "custom" },
            removeOnComplete: { count: MANTER_CONCLUIDOS },
            removeOnFail: { count: MANTER_FALHADOS },
          },
        })),
      ),
      nome,
    );
  }

  async fechar(): Promise<void> {
    const abertas = [...this.#filas.values()];
    this.#filas.clear();
    await Promise.all(abertas.map((fila) => fila.close()));
    this.#cliente.disconnect();
  }

  /** Quantas filas estão abertas. Para o teste e para a métrica de recursos. */
  get abertas(): number {
    return this.#filas.size;
  }
}
