/**
 * A casca do *shim* da fila do AGR: o `Worker` do BullMQ (KAM-025).
 *
 * Só isto. A decisão — o que se faz com cada estado HTTP do AGR — vive em
 * `shim.ts` e testa-se sem fila nenhuma; aqui traduz-se entre o BullMQ e essa
 * decisão. A divisão é a de `chr/fila.ts` contra `chr/invocacao.ts`, e está
 * declarada em `ci/thresholds.yaml`: casca sobre o BullMQ sai da medição do
 * *gate* 4 porque quem a exercita de verdade é uma fila real, que não produz
 * cobertura V8 — e o precedente é o `eventos/trabalhador_bullmq.ts`.
 *
 * O que se reutiliza é tudo o que custou a aprender: a `LIGACAO_QUE_ESPERA` (o
 * BullMQ recusa um `Worker` com `maxRetriesPerRequest` diferente de `null`), o
 * cliente `ioredis` construído à mão e passado como instância (o `require`
 * dinâmico falha em ESM), o ouvinte de `error` que impede uma queda da fila de
 * derrubar o processo, e o `aoFalhar` — **sem ele, um *job* que falha não deixa
 * linha nenhuma**, que é a lição medida na *suite* `tests_entrada`.
 */

import { UnrecoverableError, Worker } from "bullmq";
import { Redis } from "ioredis";

import { FILA_AGR } from "../chr/contrato.ts";
import { LIGACAO_QUE_ESPERA, opcoesDaUrl } from "../eventos/filas_bullmq.ts";
import { CONCORRENCIA, TRANCA_DO_JOB_MS } from "./contrato.ts";
import { AJUSTES_DO_SHIM, type OpcoesDoShim, chamarOTurno } from "./shim.ts";

export interface ShimDoAgr {
  readonly trabalhador: Worker;
  fechar(): Promise<void>;
}

/** Cria o *shim* da fila do AGR e devolve-o com o seu `fechar()`. */
export function criarShimDoAgr(opcoes: OpcoesDoShim): ShimDoAgr {
  const fila = opcoes.fila ?? FILA_AGR;
  const ligacao = new Redis({ ...opcoesDaUrl(opcoes.url), ...LIGACAO_QUE_ESPERA });
  // Sem isto, um erro de ligação num cliente `ioredis` sem ouvinte de `error`
  // é uma excepção não tratada que derruba o processo — e derrubar o *shim*
  // quando a fila cai deixa o CHR a enfileirar para ninguém.
  ligacao.on("error", () => {});

  const trabalhador = new Worker(
    fila,
    async (job) => {
      if (typeof job.data !== "object" || job.data === null) {
        // Um *job* sem corpo de objecto não veio do CHR. Nenhuma retentativa
        // lhe acrescenta um; e tratá-lo como corpo vazio punha o AGR a recusar
        // seis vezes o que se sabia à primeira.
        throw new UnrecoverableError(
          `um job da fila ${fila} nao traz um objecto: nao veio do CHR (KAM-014)`,
        );
      }
      const { desfecho, estado } = await chamarOTurno(opcoes, job.data);
      opcoes.aoTratar?.(desfecho, estado);
    },
    {
      connection: ligacao,
      concurrency: opcoes.concorrencia ?? CONCORRENCIA,
      lockDuration: TRANCA_DO_JOB_MS,
      settings: AJUSTES_DO_SHIM,
    },
  );
  trabalhador.on("error", () => {});
  if (opcoes.aoFalhar) {
    trabalhador.on("failed", (job, erro) => {
      opcoes.aoFalhar?.(erro, job?.attemptsMade ?? 0);
    });
  }

  return {
    trabalhador,
    async fechar(): Promise<void> {
      await trabalhador.close();
      ligacao.disconnect();
    },
  };
}
