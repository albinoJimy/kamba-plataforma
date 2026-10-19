/**
 * A fila `agr-inbound`: o que o CHR põe nela e com que chave (KAM-014).
 *
 * Vive nesta biblioteca e não no serviço pela mesma razão que o
 * `entrada/trabalhador.ts`: o `services/worker-canal` não tem o BullMQ nas suas
 * dependências, e não deve ter — o que ele faz é montar portas, e a porta da
 * fila é desta biblioteca. Quem consome a fila é o AGR (KAM-025), que é Python.
 *
 * ## A idempotência é a chave, e é por isso que a chave é um resumo
 *
 * `jobId = sha256({tenant_id}:{wamid})`. Com ele, a repetição do mesmo `wamid`
 * — a re-entrega de sete dias da Meta, ou o `recuperado` do `registo.ts` do
 * KAM-013 — não cria um segundo *job*: o BullMQ recusa um `jobId` que já
 * existe, enquanto ele estiver na janela de `removeOnComplete`. É o primeiro dos
 * dois níveis, e o segundo é do AGR, que tem de ser idempotente por `turn_id`
 * (as garantias do BullMQ são **NÃO VERIFICADO**, `evidencia/E4` §2.10).
 *
 * **Não é o `wamid` em claro**, e a razão não é estética: o `wamid` leva o
 * número do interlocutor codificado em base64 (INDÍCIO, `docs/logs.md` §2.1), e
 * uma chave de *job* é lida por quem opera a fila, aparece em painéis e numa
 * listagem de Redis. O resumo é determinístico e opaco, e o `tenant_id` entra
 * nele para que dois tenants não possam adivinhar a chave um do outro.
 *
 * ## `removeOnComplete` e a janela da idempotência, dita em vez de assumida
 *
 * O `jobId` só deduplica enquanto o *job* existir. Com `removeOnComplete` a
 * `JOBS_GUARDADOS`, a janela é «os últimos N turnos da plataforma» e não um
 * prazo — num pico, encurta. É o mesmo limite que o `jobId = sha256(corpo)` do
 * GWY tem, e é por isso que a dedup **que conta** está na base
 * (`UNIQUE (kind, event_key)` em `inbound_events`, já escrita antes do CHR
 * correr): se este *job* se repetir, o AGR recebe o mesmo turno duas vezes e
 * tem de o tratar uma só.
 */

import { Queue } from "bullmq";

import { LIGACAO_QUE_ESPERA, opcoesDaUrl } from "../eventos/filas_bullmq.ts";
import type { AgentInvocation } from "./contrato.ts";
import { FILA_AGR, JOB_AGR } from "./contrato.ts";
import { jobIdDe } from "./invocacao.ts";

/**
 * Quantos *jobs* concluídos ficam na fila. *Proposta*.
 *
 * O mesmo número que o GWY usa no `wa-inbound` (`10000`), e pela mesma razão: é
 * a janela em que o `jobId` deduplica. Calibra-se em KAM-084, com o perfil de
 * carga real.
 */
export const JOBS_GUARDADOS = 10_000;

/** Quantos *jobs* falhados ficam, para diagnóstico. *Proposta*. */
export const FALHADOS_GUARDADOS = 1_000;

/** A porta de saída do CHR para o AGR. */
export interface FilaDoAgr {
  publicar(invocacao: AgentInvocation): Promise<void>;
  fechar(): Promise<void>;
}

/**
 * A fila do AGR sobre um Redis/Valkey.
 *
 * `LIGACAO_QUE_ESPERA` é a mesma política do resto da biblioteca: com a fila em
 * baixo, a publicação **rejeita** em vez de ficar pendurada para sempre — e um
 * `publicar` que rejeita faz o *job* de entrada falhar e o BullMQ repeti-lo,
 * que é o comportamento certo (o evento fica registado e sem `processado_at`, e
 * a entrega seguinte trata-o como `recuperado`).
 */
export function criarFilaDoAgr(url: string): FilaDoAgr {
  const fila = new Queue(FILA_AGR, {
    connection: { ...opcoesDaUrl(url), ...LIGACAO_QUE_ESPERA },
  });
  // Sem ouvinte de `error`, um erro de ligação do cliente `ioredis` é uma
  // excepção não tratada que derruba o processo. É a mesma linha do
  // `entrada/trabalhador.ts`, e pela mesma razão.
  fila.on("error", () => {});

  return {
    async publicar(invocacao: AgentInvocation): Promise<void> {
      await fila.add(JOB_AGR, invocacao, {
        jobId: jobIdDe(invocacao.tenant_id, invocacao.wamid),
        removeOnComplete: JOBS_GUARDADOS,
        removeOnFail: FALHADOS_GUARDADOS,
      });
    },
    async fechar(): Promise<void> {
      await fila.close();
    },
  };
}
