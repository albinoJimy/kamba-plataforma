/**
 * O consumidor que a suite de base de dados lança, mata e relança (KAM-006).
 *
 * Não é um teste: é o programa que `db/tests_eventos_consumo/` corre contra um
 * PostgreSQL e uma fila **reais**. Faz o mesmo que o processo do serviço sem o
 * servidor HTTP — a suite lê o que precisa da base e da fila, não de `/metrics`.
 *
 * É o irmão do `publicador_runner.ts`, e as variáveis seguem a mesma forma:
 *
 *   KAMBA_CONSUMIDOR_DB_URL   ligação ao PostgreSQL (obrigatória)
 *   KAMBA_QUEUE_URL           ligação à fila (obrigatória)
 *   KAMBA_CONSUMER            o nome do consumidor (obrigatório)
 *   KAMBA_CON_ROTULO          nome do processo nas linhas que escreve
 *   KAMBA_CON_REGISTO         ficheiro das linhas JSON; vazio ⇒ não escreve
 *   KAMBA_CON_EFEITO          o que o efeito faz: `nada` (omissão), `falha`
 *                             (lança sempre — critério 2), `conta` (escreve
 *                             uma linha em `platform.evt_acoes` por consumo,
 *                             que é como o critério 1 conta os efeitos)
 *   KAMBA_CON_ESTADO          o estado que a máquina falsa devolve: um estado
 *                             da encomenda, ou `nenhum` para `null`
 *   KAMBA_CON_EXIGE_ORDEM     `0` desliga a ordem (omissão: ligada)
 *
 * O efeito é configurável porque os critérios pedem três comportamentos
 * diferentes do **mesmo** consumidor, e levantar três programas para isso era
 * triplicar o que pode divergir.
 */

import { appendFileSync } from 'node:fs';

import { Client } from 'pg';

import {
  type EstadoDaEncomenda,
  type MaquinaDeEstados,
  METRICAS,
  filasDe,
} from '@kamba/core-ts/eventos';
import { criarTrabalhadores } from '@kamba/core-ts/eventos/trabalhador_bullmq';

function exigir(nome: string): string {
  const valor = (process.env[nome] ?? '').trim();
  if (valor === '') throw new Error(`falta a variável de ambiente ${nome}`);
  return valor;
}

const ROTULO = (process.env.KAMBA_CON_ROTULO ?? 'con').trim() || 'con';
const REGISTO = (process.env.KAMBA_CON_REGISTO ?? '').trim();
const EFEITO = (process.env.KAMBA_CON_EFEITO ?? 'nada').trim();
const ESTADO = (process.env.KAMBA_CON_ESTADO ?? 'aguarda_pagamento').trim();
const EXIGE_ORDEM = (process.env.KAMBA_CON_EXIGE_ORDEM ?? '1').trim() !== '0';

/**
 * Escreve uma linha JSON no registo.
 *
 * Por ficheiro e não pelo `stdout`: o `log-lint` do gate 2 proíbe escrita
 * directa, e a suite lê o ficheiro com o processo vivo.
 */
function dizer(dados: Record<string, unknown>): void {
  if (REGISTO === '') return;
  appendFileSync(REGISTO, `${JSON.stringify({ con: ROTULO, ...dados })}\n`, 'utf8');
}

/** A máquina falsa: devolve o que a variável disser, sem tabela de encomendas. */
class MaquinaDeAmbiente implements MaquinaDeEstados {
  async estadoDe(): Promise<EstadoDaEncomenda | null> {
    return ESTADO === 'nenhum' ? null : (ESTADO as EstadoDaEncomenda);
  }
}

const bd = new Client({ connectionString: exigir('KAMBA_CONSUMIDOR_DB_URL') });
await bd.connect();

const consumer = exigir('KAMBA_CONSUMER');
let consumos = 0;

const trabalhadores = criarTrabalhadores({
  bd,
  subscricao: { consumer, exigeOrdem: EXIGE_ORDEM },
  filas: filasDe(consumer),
  maquina: new MaquinaDeAmbiente(),
  metricas: METRICAS,
  url: exigir('KAMBA_QUEUE_URL'),
  log: (dados) => dizer(dados),
  efeito: async (cliente) => {
    consumos += 1;
    if (EFEITO === 'falha') {
      throw new Error('efeito que falha sempre (KAMBA_CON_EFEITO=falha)');
    }
    if (EFEITO === 'conta') {
      // Uma linha por efeito aplicado, na **mesma transacção** que a marca de
      // consumo: é assim que o critério 1 conta «1 efeito» sem depender de um
      // contador em memória, que uma re-entrega noutro processo não veria.
      await cliente.query(
        'INSERT INTO platform.evt_acoes (idempotency_key, consumer, event_id, accao, tenant_id) '
          + "VALUES ($1, $2, $3, 'efeito', $4)",
        [`${consumer}:${consumos}:${Date.now()}`, consumer, crypto.randomUUID(), crypto.randomUUID()],
      );
    }
  },
});

dizer({ evento: 'arrancou', consumer, efeito: EFEITO, estado: ESTADO, ordem: EXIGE_ORDEM });

for (const sinal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(sinal, () => {
    dizer({ evento: 'paragem_pedida', consumos, metricas: METRICAS.ler() });
    void Promise.all(trabalhadores.map((t) => t.close()))
      .then(() => bd.end())
      .finally(() => process.exit(0));
  });
}
