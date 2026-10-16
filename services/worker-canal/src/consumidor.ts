/**
 * O processo do consumidor de eventos (KAM-006).
 *
 * É o terceiro processo do `worker-canal`, ao lado do `server.ts` e do
 * `publicador.ts`, e a razão de ser um processo e não um módulo do servidor é a
 * mesma do publicador: escala com réplicas, não com concorrência por fila.
 *
 * ## O que faz, por esta ordem
 *
 * 1. **Verifica o arranque** (critério 7): se houver uma subscrição de
 *    `payment.*` com `exige_ordem = false`, **não arranca**. A restrição
 *    `evt_subscricoes_payment_exige_ordem` da revisão 0005 faz a configuração
 *    errada ser recusada pela base; esta verificação é a outra metade, e
 *    continua a valer se alguém largar a restrição.
 * 2. Levanta um *worker* por partição da sua subscrição (16 filas, §6.5).
 * 3. Corre o **reconciliador** a cada cinco minutos, com o seu próprio *lock*
 *    consultivo (§6.5), e publica a métrica `evt_dlq_open` na mesma passagem —
 *    é a ligação de operação que lê a DLQ, e não a de consumo.
 * 4. Serve `/metrics`, como o publicador, na sua porta.
 *
 * ## O efeito, e porque este processo não tem nenhum
 *
 * Um consumidor sem efeito de negócio não serve para nada — e, hoje, não há
 * efeito nenhum para aplicar: as verticais que consomem eventos são o KAM-038,
 * e o core de comércio é o KAM-041. Este processo traz o **esqueleto** com um
 * efeito que só regista, e é por isso que o `KAMBA_CONSUMER` é obrigatório mas
 * o efeito é fixo. Quem acrescentar uma vertical troca o efeito e mais nada.
 */

import { serve } from '@hono/node-server';
import { healthz } from '@kamba/core-ts';
import { instalar } from '@kamba/core-ts/logger';
import { Hono } from 'hono';
import { Client } from 'pg';

import { SERVICE, VERSION } from './meta.ts';
import {
  INTERVALO_POR_OMISSAO,
  LOCK_DO_RECONCILIADOR,
  METRICAS,
  SQL_ELEGER,
  SQL_LARGAR,
  SQL_PAYMENT_SEM_ORDEM,
  esperar,
  filasDe,
  publicarAbertas,
  reporUmaVez,
} from '@kamba/core-ts/eventos';
import { FilasBullmq } from '@kamba/core-ts/eventos/filas_bullmq';
import { criarTrabalhadores } from '@kamba/core-ts/eventos/trabalhador_bullmq';

const log = instalar(SERVICE);

/** A porta do `/metrics` deste processo. A do publicador é a 3011. */
export const PORTA_POR_OMISSAO = 3012;

const VARIAVEL_DA_BASE = 'KAMBA_CONSUMIDOR_DB_URL';
const VARIAVEL_DA_FILA = 'KAMBA_QUEUE_URL';
const VARIAVEL_DO_CONSUMER = 'KAMBA_CONSUMER';
const VARIAVEL_DA_PORTA = 'CONSUMIDOR_PORT';

function exigir(nome: string): string {
  const valor = process.env[nome];
  if (valor === undefined || valor.trim() === '') {
    throw new Error(`falta a variável de ambiente ${nome}`);
  }
  return valor;
}

function porta(): number {
  const bruto = process.env[VARIAVEL_DA_PORTA];
  if (bruto === undefined || bruto.trim() === '') return PORTA_POR_OMISSAO;
  const valor = Number(bruto);
  if (!Number.isInteger(valor) || valor < 1 || valor > 65_535) {
    throw new Error(`${VARIAVEL_DA_PORTA} inválida: ${bruto}`);
  }
  return valor;
}

export class ArranqueRecusadoError extends Error {
  readonly subscricoes: readonly string[];

  constructor(subscricoes: readonly string[]) {
    super(
      'arranque recusado: há subscrições de pagamento sem ordem — ' +
        `${subscricoes.join(', ')}. Aplicar «paga» antes de «aguarda_pagamento» é ` +
        'uma transição inválida, e sem ordem ela é possível (KAM-006, critério 7)',
    );
    this.name = 'ArranqueRecusadoError';
    this.subscricoes = subscricoes;
  }
}

/**
 * Recusa o arranque com uma subscrição de pagamento sem ordem.
 *
 * Exportada para ser exercitada sem levantar o processo: é o critério 7, e um
 * teste que levantasse o processo inteiro para o ver falhar provava menos e
 * demorava mais.
 */
export async function exigirOrdemNosPagamentos(bd: {
  query(sql: string, parametros?: readonly unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
}): Promise<void> {
  const { rows } = await bd.query(SQL_PAYMENT_SEM_ORDEM);
  if (rows.length === 0) return;
  throw new ArranqueRecusadoError(
    rows.map((linha) => `${String(linha.consumer)}/${String(linha.tipo)}`),
  );
}

export function criarApp(): Hono {
  const app = new Hono();
  app.get('/healthz', (c) => c.json(healthz(SERVICE, VERSION)));
  app.get('/metrics', (c) =>
    c.text(METRICAS.exposicao(), 200, {
      'content-type': 'text/plain; version=0.0.4; charset=utf-8',
    }),
  );
  return app;
}

async function principal(): Promise<void> {
  const consumer = exigir(VARIAVEL_DO_CONSUMER);
  const urlDaBase = exigir(VARIAVEL_DA_BASE);
  const urlDaFila = exigir(VARIAVEL_DA_FILA);

  const bd = new Client({ connectionString: urlDaBase });
  await bd.connect();
  await exigirOrdemNosPagamentos(bd);

  const trabalhadores = criarTrabalhadores({
    bd,
    subscricao: { consumer, exigeOrdem: true },
    filas: filasDe(consumer),
    // O efeito do esqueleto: regista e mais nada. Ver a docstring.
    efeito: async () => {},
    metricas: METRICAS,
    url: urlDaFila,
    // O `log` da biblioteca tem *allowlist* de campos (`docs/tecnica/08`
    // §7.3): `consumer`, `fila` e `event_id` **não** estão nela, e um campo
    // fora dela é erro de compilação — que é como deve ser, porque um
    // `event_id` num registo é um identificador a mais. Fica o desfecho, e o
    // detalhe vive na base (`events_consumed`, `events_dlq`).
    log: (dados) => log.info({ outcome: `consumo_${String(dados.desfecho)}` }),
  });
  log.info({ outcome: 'service_started' });

  const filas = new FilasBullmq({ url: urlDaFila });
  const paragem = new AbortController();
  for (const sinal of ['SIGTERM', 'SIGINT'] as const) {
    process.on(sinal, () => paragem.abort());
  }

  const servidor = serve({ fetch: criarApp().fetch, port: porta() });

  // O reconciliador, com o **seu** lock: amarrá-lo ao do publicador fazia uma
  // réplica em espera para publicar ficar em espera para repor.
  const operacao = new Client({ connectionString: urlDaBase });
  await operacao.connect();
  try {
    while (!paragem.signal.aborted) {
      const { rows } = await operacao.query(SQL_ELEGER, [LOCK_DO_RECONCILIADOR]);
      if (rows[0]?.lider === true) {
        await reporUmaVez({ bd: operacao, filas });
        await publicarAbertas(operacao, METRICAS);
      }
      await esperar(INTERVALO_POR_OMISSAO, paragem.signal);
    }
  } finally {
    await operacao.query(SQL_LARGAR, [LOCK_DO_RECONCILIADOR]).catch(() => {});
    await Promise.all(trabalhadores.map((t) => t.close()));
    await filas.fechar();
    await operacao.end().catch(() => {});
    await bd.end().catch(() => {});
    servidor.close();
  }
}

if (import.meta.main) {
  await principal();
}
