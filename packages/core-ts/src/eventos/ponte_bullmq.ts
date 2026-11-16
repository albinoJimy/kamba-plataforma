/**
 * A ponte fila → consumidor Python: a **casca** BullMQ (KAM-194).
 *
 * Só isto. A decisão — o corpo da entrega e o que se faz com cada estado HTTP —
 * vive em `ponte.ts` e testa-se sem fila nenhuma; aqui traduz-se entre o BullMQ
 * e essa decisão. A divisão é a de `agr/trabalhador.ts` contra `agr/shim.ts`.
 *
 * **Não abre ligação à base e não importa nada do `pg`**: a marca em
 * `events_consumed`, a ordem e a DLQ são do lado Python. Um teste lê o texto
 * deste ficheiro e falha se ele importar o `pg` ou SQL.
 *
 * O que se reutiliza é tudo o que custou a aprender: a `LIGACAO_QUE_ESPERA` (o
 * BullMQ recusa um `Worker` com `maxRetriesPerRequest` diferente de `null`), o
 * cliente `ioredis` construído à mão e passado como instância (o `require`
 * dinâmico falha em ESM), o ouvinte de `error` que impede uma queda da fila de
 * derrubar o processo, e o `aoFalhar` — **sem ele, um *job* que falha não deixa
 * linha nenhuma**, que é a lição medida na *suite* `tests_entrada`.
 *
 * ## Um *worker* por fila, concorrência 1
 *
 * Dezasseis filas por consumidor, e cada uma é uma partição: a ordem só vale
 * dentro dela (`docs/tecnica/06` §6.5), e é o lado Python que pode exigi-la.
 * Uma ligação ao Redis partilhada por todos, como no `trabalhador_bullmq.ts`:
 * aqui nem há transacções a intercalar, e o BullMQ duplica-a para o bloqueio
 * de cada *worker*.
 */

import { Worker } from "bullmq";
import { Redis } from "ioredis";

import { LIGACAO_QUE_ESPERA, opcoesDaUrl } from "./filas_bullmq.ts";
import {
  AJUSTES_DA_PONTE,
  CONCORRENCIA_DA_PONTE,
  type OpcoesDaChamada,
  TRANCA_DA_PONTE_MS,
  chamarOConsumidor,
  corpoDaEntrega,
  filasDaPonte,
  largarAoFalhar,
} from "./ponte.ts";
import type { DesfechoDaPonte } from "./metricas_ponte.ts";

export interface OpcoesDaPonte extends OpcoesDaChamada {
  /** `redis://anfitriao:porta`. */
  readonly url: string;
  /** Os consumidores cujas dezasseis partições esta ponte serve. */
  readonly consumidores: readonly string[];
  /**
   * Por omissão `CONCORRENCIA_DA_PONTE` (1). Acima de 1 a ordem dentro da
   * partição perde-se: só para um consumidor que não a exige.
   */
  readonly concorrencia?: number;
  /** Chamado por cada *job* entregue, com o desfecho e o estado HTTP. */
  readonly aoTratar?: (outcome: DesfechoDaPonte, estado: number) => void;
  /**
   * Chamado quando um *job* falha, com o erro e o número de tentativas feitas.
   *
   * **Sem isto, um *job* que falha não deixa linha nenhuma**: o BullMQ não
   * escreve nada por si quando ninguém ouve o acontecimento `failed`.
   */
  readonly aoFalhar?: (erro: unknown, tentativas: number) => void;
}

export interface Ponte {
  readonly trabalhadores: readonly Worker[];
  /** Fecha os *workers* e, depois, a ligação ao Redis. */
  fechar(): Promise<void>;
}

/** Cria a ponte e devolve-a com o seu `fechar()`. Recusa consumidores maus no arranque. */
export function criarPonte(opcoes: OpcoesDaPonte): Ponte {
  // Antes de abrir o que quer que seja: um nome mau não chega a ligar ao Redis.
  const filas = filasDaPonte(opcoes.consumidores);
  const ligacao = new Redis({ ...opcoesDaUrl(opcoes.url), ...LIGACAO_QUE_ESPERA });
  // Sem isto, um erro de ligação num cliente `ioredis` sem ouvinte de `error`
  // é uma excepção não tratada que derruba o processo — e derrubar a ponte
  // quando a fila cai deixa o publicador a enfileirar para ninguém.
  ligacao.on("error", () => {});

  const trabalhadores = filas.map((fila) => {
    const trabalhador = new Worker(
      fila,
      async (job) => {
        const { outcome, estado } = await chamarOConsumidor(opcoes, corpoDaEntrega(job));
        opcoes.aoTratar?.(outcome, estado);
      },
      {
        connection: ligacao,
        concurrency: opcoes.concorrencia ?? CONCORRENCIA_DA_PONTE,
        lockDuration: TRANCA_DA_PONTE_MS,
        settings: AJUSTES_DA_PONTE,
      },
    );
    trabalhador.on("error", () => {});
    trabalhador.on("failed", (job, erro) => {
      opcoes.aoFalhar?.(erro, job?.attemptsMade ?? 0);
      // A rede do reconciliador: ver `largarAoFalhar`. Uma remoção que falhe
      // não muda nada — o *job* fica onde estava, que era o comportamento de
      // antes.
      if (job && largarAoFalhar(erro, job.attemptsMade, job.opts.attempts)) {
        void job.remove().catch(() => {});
      }
    });
    return trabalhador;
  });

  return {
    trabalhadores,
    async fechar(): Promise<void> {
      // Os *workers* primeiro: fechar a ligação debaixo de um *job* a correr
      // deixava-o sem tranca, e o BullMQ entregava-o outra vez.
      await Promise.all(trabalhadores.map((t) => t.close()));
      ligacao.disconnect();
    },
  };
}
