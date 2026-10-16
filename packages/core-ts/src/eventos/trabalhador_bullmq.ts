/**
 * O trabalhador da fila, sobre BullMQ (KAM-006).
 *
 * É casca, de propósito: a decisão toda — marcar, verificar a ordem, aplicar,
 * adiar, abrir a DLQ — está no `trabalho.ts`, que se testa sem fila nenhuma.
 * Aqui só se traduz entre o BullMQ e essa decisão.
 *
 * ## A tradução, e as duas coisas que ela tem de acertar
 *
 * 1. **A contagem de tentativas vem do *job*** (`job.attemptsMade`), e não de
 *    um contador nosso: com duas réplicas do consumidor, um contador próprio
 *    contava metade cada uma e o evento ia para a DLQ ao dobro das tentativas —
 *    ou nunca ia.
 * 2. **Um `adiado` tem de voltar a ser tentado.** O BullMQ só repete um *job*
 *    que **lança**; devolver um resultado é dizer-lhe que correu bem. Por isso
 *    o `adiado` relança, com o atraso em milissegundos — e é aí que o
 *    `Adiar.atrasoMs` paga: a escada deste módulo está em milissegundos e o
 *    `Adiar` em segundos, e um `× 1000` esquecido queimava as seis tentativas
 *    num instante.
 *
 * ## A concorrência é 1, e isso é a ordem
 *
 * Uma fila por partição, `concurrency: 1` por fila (§6.5). A ordem só vale
 * dentro da partição, e dois *jobs* da mesma partição em paralelo perdiam-na.
 * Escala-se com mais *workers* por fila — não com mais concorrência por fila.
 */

import { Worker, UnrecoverableError } from 'bullmq';
import { Redis } from 'ioredis';

import { Adiar, atrasoDaTentativaDoConsumidor } from './consumo.ts';
import type { Efeito } from './consumo.ts';
import type { Envelope } from './envelope.ts';
import { lerEnvelope } from './envelope.ts';
import type { MaquinaDeEstados } from './estados.ts';
import { LIGACAO_QUE_FALHA_DEPRESSA, opcoesDaUrl } from './filas_bullmq.ts';
import type { Metricas } from './metricas.ts';
import type { ClienteSql } from './publicador.ts';
import { type DesfechoDoTrabalho, processar } from './trabalho.ts';

/** O que o trabalhador precisa de saber sobre a subscrição que serve. */
export interface Subscricao {
  readonly consumer: string;
  readonly exigeOrdem: boolean;
}

export interface OpcoesDoTrabalhador {
  /** A ligação à base. Uma por trabalhador: a transacção é dele. */
  readonly bd: ClienteSql;
  readonly subscricao: Subscricao;
  /** As filas que este trabalhador serve (as 16 partições, ou um subconjunto). */
  readonly filas: readonly string[];
  readonly efeito: Efeito;
  readonly maquina?: MaquinaDeEstados;
  readonly metricas?: Metricas;
  readonly url: string;
  readonly log?: (dados: Record<string, unknown>) => void;
}

/**
 * O envelope de um *job*.
 *
 * O publicador põe `{event_id, consumer, ...}` nos dados e o `jobId` é o
 * `event_id`. O envelope **completo** vem na base, não na fila: a fila pode
 * perder, duplicar e reordenar, e o que ela traz é um ponteiro. Ler o envelope
 * do `events_log` é o que faz a reposição do reconciliador funcionar com os
 * mesmos dados de uma entrega normal.
 */
export const SQL_ENVELOPE_DO_EVENTO = `
  SELECT envelope FROM platform.events_log WHERE event_id = $1
`;

export class EventoDesconhecidoError extends Error {
  readonly eventId: string;

  constructor(eventId: string) {
    super(
      `o evento ${eventId} não está em events_log: a fila trouxe um ponteiro ` +
        'para um evento que o arquivo não tem',
    );
    this.name = 'EventoDesconhecidoError';
    this.eventId = eventId;
  }
}

/** Lê o envelope do arquivo. O `jobId` é o `event_id`. */
export async function envelopeDoEvento(
  bd: ClienteSql,
  eventId: string,
): Promise<Envelope> {
  const { rows } = await bd.query(SQL_ENVELOPE_DO_EVENTO, [eventId]);
  const linha = rows[0];
  if (linha === undefined) throw new EventoDesconhecidoError(eventId);
  return lerEnvelope(linha.envelope);
}

/**
 * Cria os *workers*, um por fila, e devolve-os.
 *
 * Quem os fecha é quem os criou: este módulo não instala tratadores de sinal.
 */
export function criarTrabalhadores(opcoes: OpcoesDoTrabalhador): Worker[] {
  const { bd, subscricao, filas, efeito, maquina, metricas, url, log } = opcoes;
  const ligacao = new Redis({ ...opcoesDaUrl(url), ...LIGACAO_QUE_FALHA_DEPRESSA });
  // Sem isto, um erro de ligação num cliente `ioredis` sem ouvinte de `error`
  // derruba o processo — e derrubar o consumidor quando a fila cai é o oposto
  // do que o critério 8 pede (o reconciliador repõe o que se perdeu).
  ligacao.on('error', () => {});

  return filas.map((fila) =>
    new Worker(
      fila,
      async (job) => {
        const eventId = job.id ?? String(job.data?.event_id ?? '');
        const envelope = await envelopeDoEvento(bd, eventId);
        // `attemptsMade` conta as que **já** falharam; esta é a seguinte.
        const tentativa = job.attemptsMade + 1;
        const resultado = await processar(
          {
            bd,
            consumer: subscricao.consumer,
            envelope,
            exigeOrdem: subscricao.exigeOrdem,
            tentativa,
            ...(maquina === undefined ? {} : { maquina }),
            ...(metricas === undefined ? {} : { metricas }),
          },
          efeito,
        );
        log?.({
          evento: 'consumo',
          fila,
          event_id: eventId,
          tentativa,
          desfecho: resultado.desfecho,
        });
        if (resultado.desfecho === 'adiado') {
          // Relança para o BullMQ repetir. O atraso vai em milissegundos.
          const erro = new Adiar(resultado.adiamento ?? 5);
          await job.moveToDelayed(Date.now() + erro.atrasoMs, job.token);
          throw erro;
        }
        if (resultado.desfecho === 'dlq') {
          // A entrada já está aberta; repetir não ajuda. `UnrecoverableError`
          // diz ao BullMQ para não gastar as tentativas que sobram.
          throw new UnrecoverableError(`dlq: ${resultado.erro ?? 'sem motivo'}`);
        }
        return resultado.desfecho satisfies DesfechoDoTrabalho;
      },
      {
        connection: ligacao,
        // A ordem vale dentro da partição, e uma fila é uma partição (§6.5).
        concurrency: 1,
        settings: {
          // A escada do §6.4, e não a do publicador. O BullMQ chama isto com o
          // número de tentativas já feitas.
          backoffStrategy: (tentativasFeitas: number) =>
            atrasoDaTentativaDoConsumidor(Math.max(tentativasFeitas, 1)),
        },
      },
    ),
  );
}
