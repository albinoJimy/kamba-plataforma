/**
 * A reposição, como programa, para a suite do gate (KAM-006, critério 8).
 *
 * Não é um teste: é o que `db/tests_eventos_consumo/` lança depois de limpar a
 * fila, para verificar que o que o Redis perdeu volta a ser enfileirado. Corre
 * **sem consumidor**, e isso é deliberado: o critério 8 fala de eventos
 * publicados sem consumo nem DLQ, e um consumidor a correr ao lado consumia-os
 * antes de se poder olhar para a fila.
 *
 *   KAMBA_CONSUMIDOR_OPS_DB_URL  ligação ao PostgreSQL como `kamba_batch`
 *                                (obrigatória). É `BYPASSRLS`: a consulta do
 *                                §6.5 procura o que se perdeu em **todos** os
 *                                tenants, e é por isso que não corre com o
 *                                papel do consumo
 *   KAMBA_QUEUE_URL              ligação à fila (obrigatória)
 *   KAMBA_RECON_REGISTO          ficheiro das linhas JSON; vazio ⇒ não escreve
 *   KAMBA_RECON_CARENCIA         segundos de idade mínima (omissão: os 600 do
 *                                §6.5). A suite põe `0` — é o relógio acelerado
 *                                que os «Testes Requeridos» pedem, e sem ele
 *                                cada verificação esperava dez minutos reais
 *   KAMBA_RECON_JANELA           segundos de janela de procura (omissão: 24 h)
 *   KAMBA_RECON_INTERVALO        ms entre passagens (omissão: os 5 min do §6.5)
 *   KAMBA_RECON_UMA_VEZ          `1` ⇒ uma passagem e termina. É o que a suite
 *                                usa: esperar por um ciclo de cinco minutos
 *                                para ver uma reposição que já aconteceu era
 *                                medir o temporizador, não a reposição
 *
 * **Sem *lock* consultivo.** O serviço elege um líder (`SQL_ELEGER`) porque há
 * réplicas; aqui há um processo, lançado pelo teste, e o *lock* só acrescentava
 * um modo de falha — um teste a falhar porque outro processo da mesma suite
 * tinha o 7102 na mão. A eleição tem prova própria no KAM-005 (critério 5).
 */

import { appendFileSync } from 'node:fs';

import { Client } from 'pg';

import { FilasBullmq } from '../src/eventos/filas_bullmq.ts';
import {
  CARENCIA_POR_OMISSAO,
  INTERVALO_POR_OMISSAO,
  JANELA_POR_OMISSAO,
  reporUmaVez,
} from '../src/eventos/reconciliador.ts';

const REGISTO = (process.env.KAMBA_RECON_REGISTO ?? '').trim();
const UMA_VEZ = (process.env.KAMBA_RECON_UMA_VEZ ?? '').trim() === '1';

function exigir(nome: string): string {
  const valor = (process.env[nome] ?? '').trim();
  if (valor === '') throw new Error(`falta a variável de ambiente ${nome}`);
  return valor;
}

/** Um inteiro do ambiente, ou a omissão. `0` é um valor, não uma ausência. */
function numero(nome: string, omissao: number): number {
  const bruto = (process.env[nome] ?? '').trim();
  if (bruto === '') return omissao;
  const valor = Number(bruto);
  if (!Number.isInteger(valor) || valor < 0) {
    throw new Error(`${nome} inválida: ${JSON.stringify(bruto)}`);
  }
  return valor;
}

/** Uma linha JSON por passagem, num ficheiro — pela razão do publicador. */
function dizer(dados: Record<string, unknown>): void {
  if (REGISTO === '') return;
  appendFileSync(REGISTO, `${JSON.stringify({ recon: true, ...dados })}\n`, 'utf8');
}

const urlDaFila = exigir('KAMBA_QUEUE_URL');
const bd = new Client({ connectionString: exigir('KAMBA_CONSUMIDOR_OPS_DB_URL') });
await bd.connect();
const filas = new FilasBullmq({ url: urlDaFila });

const janela = numero('KAMBA_RECON_JANELA', JANELA_POR_OMISSAO);
const carencia = numero('KAMBA_RECON_CARENCIA', CARENCIA_POR_OMISSAO);
const intervalo = numero('KAMBA_RECON_INTERVALO', INTERVALO_POR_OMISSAO);

dizer({ evento: 'arrancou', janela, carencia, uma_vez: UMA_VEZ });

let aParar = false;
for (const sinal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(sinal, () => {
    aParar = true;
  });
}

async function fechar(): Promise<void> {
  await filas.fechar();
  await bd.end().catch(() => {});
}

do {
  const resultado = await reporUmaVez({
    bd,
    filas,
    janela,
    carencia,
    log: (dados) => dizer(dados),
  });
  dizer({ evento: 'passagem', ...resultado });
  if (UMA_VEZ) break;
  await new Promise((resolver) => setTimeout(resolver, intervalo));
} while (!aParar);

dizer({ evento: 'terminou' });
await fechar();
