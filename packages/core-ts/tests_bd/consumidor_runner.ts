/**
 * O consumidor que a suite de base de dados lança, mata e relança (KAM-006).
 *
 * Não é um teste: é o programa que `db/tests_eventos_consumo/` corre contra um
 * PostgreSQL e uma fila **reais**. Faz o mesmo que o processo do serviço sem o
 * servidor HTTP e sem o reconciliador — a suite lê o que precisa da base e da
 * fila, não de `/metrics`, e a reposição tem o seu próprio programa
 * (`reconciliador_runner.ts`), porque o critério 8 se prova sem consumidor
 * nenhum a correr.
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
 *   KAMBA_CON_ESCADA          a escada de recuo, em milissegundos, separada por
 *                             vírgulas. É o **relógio acelerado** que os
 *                             «Testes Requeridos» do ticket pedem: com a escada
 *                             de produção (1 s, 5 s, 30 s, 2 min, 10 min) cada
 *                             teste que esgota as seis tentativas esperava
 *                             756 s. Os valores da escada real provam-se no
 *                             `eventos.consumo.test.ts` e no espelho em Python;
 *                             o que a suite com fila prova é a **contagem**
 *
 * Os `import` são **relativos** e não por `@kamba/core-ts`: o pacote exporta
 * `./dist`, e este programa corre sobre a árvore de fontes, sem compilação.
 * Foi o que o publicador fez, pela mesma razão.
 */

import { appendFileSync } from 'node:fs';

import { Client } from 'pg';

import { chaveDaAccao } from '../src/eventos/accoes.ts';
import type { Envelope } from '../src/eventos/envelope.ts';
import type { EstadoDaEncomenda, MaquinaDeEstados } from '../src/eventos/estados.ts';
import { filasDe } from '../src/eventos/particao.ts';
import { METRICAS } from '../src/eventos/metricas.ts';
import { criarTrabalhadores } from '../src/eventos/trabalhador_bullmq.ts';

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

/** A escada do ambiente, ou `undefined` para a de produção. */
function escadaDoAmbiente(): readonly number[] | undefined {
  const bruto = (process.env.KAMBA_CON_ESCADA ?? '').trim();
  if (bruto === '') return undefined;
  const degraus = bruto.split(',').map((parte) => Number(parte.trim()));
  if (degraus.length === 0 || degraus.some((n) => !Number.isInteger(n) || n < 0)) {
    throw new Error(`KAMBA_CON_ESCADA inválida: ${JSON.stringify(bruto)}`);
  }
  return degraus;
}

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

const urlDaBase = exigir('KAMBA_CONSUMIDOR_DB_URL');
const consumer = exigir('KAMBA_CONSUMER');
const escada = escadaDoAmbiente();

const consumo = criarTrabalhadores({
  // Uma ligação por fila, como o serviço: a transacção do consumo é da fila.
  ligar: async () => {
    const cliente = new Client({ connectionString: urlDaBase });
    await cliente.connect();
    return cliente;
  },
  subscricao: { consumer, exigeOrdem: EXIGE_ORDEM },
  filas: filasDe(consumer),
  maquina: new MaquinaDeAmbiente(),
  metricas: METRICAS,
  url: exigir('KAMBA_QUEUE_URL'),
  log: (dados) => dizer(dados),
  ...(escada === undefined ? {} : { escada }),
  efeito: async (cliente, envelope: Envelope) => {
    if (EFEITO === 'falha') {
      throw new Error('efeito que falha sempre (KAMBA_CON_EFEITO=falha)');
    }
    if (EFEITO === 'conta') {
      // Uma linha por efeito aplicado, na **mesma transacção** que a marca de
      // consumo: é assim que o critério 1 conta «1 efeito» sem depender de um
      // contador em memória, que uma re-entrega noutro processo não veria.
      //
      // A chave é a do §6.3 (`consumer:event_id:acção`) e não uma corrida: com
      // uma chave aleatória, um efeito repetido escrevia **duas** linhas e o
      // teste do critério 1 contava 2 — mas com a chave real ele rebenta na
      // unicidade, que é a propriedade que se quer ter. O `tenant_id` vem do
      // envelope porque a RLS o exige: o contexto da transacção é esse.
      await cliente.query(
        'INSERT INTO platform.evt_acoes (idempotency_key, consumer, event_id, accao, tenant_id) '
          + "VALUES ($1, $2, $3, 'efeito', $4)",
        [
          chaveDaAccao(consumer, envelope.id, 'efeito'),
          consumer,
          envelope.id,
          envelope.tenant_id,
        ],
      );
    }
  },
});

dizer({
  evento: 'arrancou',
  consumer,
  efeito: EFEITO,
  estado: ESTADO,
  ordem: EXIGE_ORDEM,
  filas: consumo.trabalhadores.length,
  escada: escada ?? 'producao',
});

for (const sinal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(sinal, () => {
    dizer({ evento: 'paragem_pedida', metricas: METRICAS.ler() });
    void consumo.fechar().finally(() => process.exit(0));
  });
}
