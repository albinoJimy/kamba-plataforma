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
 * ## Um *job* em `failed` bloqueia o mesmo `wamid`, e isso fica dito
 *
 * O BullMQ recusa um `add` com um `jobId` que já exista — **incluindo em
 * `failed`**. Se o AGR esgotar as tentativas de um turno, qualquer re-entrega
 * do mesmo `wamid` é descartada em silêncio até o `removeOnFail` o limpar. Na
 * prática o `inbound_events.processado_at` já fecha a outra ponta (o CHR não
 * re-encaminha um evento marcado), pelo que o caminho está fechado nos dois
 * lados — e é isso que torna o caso difícil de ver no dia em que acontecer.
 * Reabrir um turno falhado é operação, não re-entrega: KAM-025 e KAM-084.
 * Achado da revisão adversarial.
 *
 * **O KAM-025 estreitou o caminho que leva ali**: o `attempts` abaixo da ao
 * *job* as seis tentativas da escada, pelo que um AGR em baixo ou em
 * contrapressao deixa de mandar o *wamid* para `failed` a primeira. O caso
 * difícil fica o que era: tentativas **esgotadas**.
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

import { TENTATIVAS_DO_AGR } from "../agr/contrato.ts";
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
        // **O `attempts` e opção do *job*, não do *worker*.** Sem ele não há
        // retentativa nenhuma: por omissão o BullMQ dá uma tentativa e manda o
        // *job* para `failed`. Faltava, e o que isso tornava falso não era
        // pouco — todo o caminho de contrapressão do AGR (KAM-025) assenta em
        // «503 e o *job* volta à fila com atraso», e o *job* não voltava: ia
        // direito para `failed`, e o `jobId` deduplica **incluindo em
        // `failed`**, pelo que o mesmo `wamid` ficava bloqueado até o
        // `removeOnFail` o despejar. Com `grafos` ainda por registar (KAM-027),
        // *toda* invocação válida dá 503 — isto é, todas as mensagens morriam
        // à primeira. Achado da revisão adversarial do KAM-025.
        attempts: TENTATIVAS_DO_AGR,
        // `custom` é a forma de o BullMQ passar a decisão do atraso ao
        // `backoffStrategy` do *worker* (`agr/shim.ts`), que é a escada do
        // consumidor de eventos. Sem isto, o `backoffStrategy` que o *shim*
        // registra nunca era chamado — e é a mesma lição que o `addLote` do
        // `eventos/filas_bullmq.ts` já tinha escrita.
        backoff: { type: "custom" },
      });
    },
    async fechar(): Promise<void> {
      await fila.close();
    },
  };
}
