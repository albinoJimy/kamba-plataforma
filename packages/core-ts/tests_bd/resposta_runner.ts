/**
 * O consumidor `outbound` que a suite com fila lança (KAM-227, critério 4).
 *
 * Não é um teste: é o programa que `db/tests_eventos_consumo/test_resposta.py`
 * corre contra um PostgreSQL e uma fila **reais**. É o irmão do
 * `consumidor_runner.ts`, com o efeito de produção da resposta do AGR no lugar
 * do efeito de ensaio:
 *
 *     fila evt.outbound.p<n>  →  consumir() do KAM-006  →  efeitoDoOutbound
 *       →  envioPeloSaida (o Saida do KAM-015, numa ligação kamba_app própria)
 *       →  o cliente da Meta deste programa, que **conta** e responde 200
 *
 * O cliente da Meta e o destinatário são os duplos, e de propósito: o que esta
 * suite prova é o caminho pela **fila** — a reentrega pelo BullMQ e o tenant do
 * envelope —, e as duas portas de produção têm prova própria contra a base
 * (`tests_bd/resposta.bd.test.ts`, grupo «as portas de produção»). O cliente
 * escreve uma linha `envio` por chamada à Meta, com o tenant e o
 * `phone_number_id` do canal do pedido, e é por elas que a suite conta.
 *
 *   KAMBA_CONSUMIDOR_DB_URL   ligação `kamba_app` (obrigatória)
 *   KAMBA_QUEUE_URL           ligação à fila (obrigatória)
 *   KAMBA_CON_REGISTO         ficheiro das linhas JSON
 *   KAMBA_CON_ESCADA          a escada acelerada, em milissegundos
 *
 * Os `import` são relativos, pela razão do `consumidor_runner.ts`.
 */

import { appendFileSync } from 'node:fs';

import pg, { Client } from 'pg';

import { filasDe } from '../src/eventos/particao.ts';
import { METRICAS } from '../src/eventos/metricas.ts';
import { criarTrabalhadores } from '../src/eventos/trabalhador_bullmq.ts';
import { CONSUMIDOR_DO_OUTBOUND, efeitoDoOutbound, envioPeloSaida } from '../src/resposta/index.ts';

function exigir(nome: string): string {
  const valor = (process.env[nome] ?? '').trim();
  if (valor === '') throw new Error(`falta a variável de ambiente ${nome}`);
  return valor;
}

const REGISTO = (process.env.KAMBA_CON_REGISTO ?? '').trim();

/** Uma linha JSON no registo. Por ficheiro, pela razão do `consumidor_runner.ts`. */
function dizer(dados: Record<string, unknown>): void {
  if (REGISTO === '') return;
  appendFileSync(REGISTO, `${JSON.stringify({ con: 'resposta', ...dados })}\n`, 'utf8');
}

function escadaDoAmbiente(): readonly number[] | undefined {
  const bruto = (process.env.KAMBA_CON_ESCADA ?? '').trim();
  if (bruto === '') return undefined;
  return bruto.split(',').map((parte) => Number(parte.trim()));
}

const urlDaBase = exigir('KAMBA_CONSUMIDOR_DB_URL');
const envios = new pg.Pool({ connectionString: urlDaBase, max: 2 });
let wamids = 0;
const escada = escadaDoAmbiente();

const consumo = criarTrabalhadores({
  ligar: async () => {
    const cliente = new Client({ connectionString: urlDaBase });
    await cliente.connect();
    return cliente;
  },
  subscricao: { consumer: CONSUMIDOR_DO_OUTBOUND, exigeOrdem: false },
  filas: filasDe(CONSUMIDOR_DO_OUTBOUND),
  metricas: METRICAS,
  url: exigir('KAMBA_QUEUE_URL'),
  log: (dados) => dizer(dados),
  ...(escada === undefined ? {} : { escada }),
  efeito: efeitoDoOutbound(
    envioPeloSaida({
      tomar: async () => envios.connect(),
      devolver: (l, erro) => (l as pg.PoolClient).release(erro instanceof Error ? erro : undefined),
      // O cliente do canal do pedido: conta cada chamada à Meta com o tenant
      // e o número do canal, que é o que a suite compara.
      meta: async (_ligacao, canal) => ({
        enviar: async (phoneNumberId) => {
          wamids += 1;
          dizer({ evento: 'envio', tenant_id: canal.tenantId, phone_number_id: phoneNumberId });
          return { ok: true, wamid: `wamid.ENSAIO227${String(wamids)}` };
        },
      }),
      destinatario: async () => ({ bsuid: 'AO.ENSAIOENSAIOENSAIO0227', telefone: null }),
    }),
    { aoTratar: (desfecho, motivo) => dizer({ evento: 'resposta', desfecho, motivo: motivo ?? null }) },
  ),
});

dizer({ evento: 'arrancou', consumer: CONSUMIDOR_DO_OUTBOUND, filas: consumo.trabalhadores.length });

for (const sinal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(sinal, () => {
    void consumo
      .fechar()
      .then(() => envios.end())
      .finally(() => process.exit(0));
  });
}
