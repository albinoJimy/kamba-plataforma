/**
 * O processo do consumidor de eventos (KAM-006).
 *
 * É o terceiro processo do `worker-canal`, ao lado do `server.ts` e do
 * `publicador.ts`, e a razão de ser um processo e não um módulo do servidor é a
 * mesma do publicador: escala com réplicas, não com concorrência por fila.
 *
 * ## O que faz, por esta ordem
 *
 * 0. **Liga-se duas vezes, com dois papéis.** O consumo é `kamba_app`, sob
 *    RLS; o reconciliador e o *gauge* da DLQ são `kamba_batch`, que vê todos os
 *    tenants. Ver `VARIAVEL_DA_OPERACAO`.
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
 * ## O efeito, escolhido pelo nome do consumidor
 *
 * Até ao KAM-224 o processo trazia só o **esqueleto**, com um efeito que
 * registava e mais nada. Hoje o `KAMBA_CONSUMER` escolhe-o (`efeitoDoConsumidor`):
 *
 * - `outbound` — a resposta do AGR de canal `whatsapp` (`agent.replied`), pelo
 *   `Saida` do KAM-015 (`@kamba/core-ts/resposta`), com as duas portas de
 *   produção do KAM-227 (`portasDoOutbound`): o cliente da Graph de cada canal,
 *   pelo `token_ref` e pela `kek_token_cliente`, e o destinatário pela
 *   identidade do KAM-008, numa terceira ligação, `kamba_identity`.
 * - qualquer outro — o esqueleto, que regista e mais nada.
 *
 * ## O arranque do `outbound` em `prod`, medido
 *
 * As portas montam-se **antes** de levantar *workers*, e cada uma recusa o que
 * não deve servir: o `Secrets.arrancar` recusa sem a `kek_token_cliente`, e o
 * `Identidade.arrancar` recusa, com `KAMBA_ENV=prod`, sem a KEK das DEK de
 * contacto (`ChavesDeIdentidadeEmFaltaError`). As chaves vêm do ambiente que o
 * lançador do cofre enche (ADR-L002): é a decisão do fundador de 2026-11-20, que
 * fechou a contradição 2 do `docs/identidade.md` §8 e emendou o critério 9 do
 * KAM-008. Com o cofre completo, **arranca em `prod`**.
 */

import { serve } from '@hono/node-server';
import { healthz } from '@kamba/core-ts';
import { instalar } from '@kamba/core-ts/logger';
import { Hono } from 'hono';
import pg, { Client } from 'pg';

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
import type { Efeito } from '@kamba/core-ts/eventos';
import { FilasBullmq } from '@kamba/core-ts/eventos/filas_bullmq';
import { criarTrabalhadores } from '@kamba/core-ts/eventos/trabalhador_bullmq';
import { EnvKeyProvider, Identidade, type ClienteDeIdentidade } from '@kamba/core-ts/identity';
import { REF_DA_KEK } from '@kamba/core-ts/onboarding';
import type { ObterDestinatario } from '@kamba/core-ts/outbound';
import {
  CONSUMIDOR_DO_OUTBOUND,
  clienteDaGraphPorCanal,
  destinatarioPelaIdentidade,
  efeitoDoOutbound,
  envioPeloSaida,
  type ClienteDoCanal,
  type DesfechoDaResposta,
  type LigacaoDoEnvio,
} from '@kamba/core-ts/resposta';
import { EnvSecretProvider, Secrets, isAmbiente, type Ambiente } from '@kamba/core-ts/secrets';

const log = instalar(SERVICE);

/** A porta do `/metrics` deste processo. A do publicador é a 3011. */
export const PORTA_POR_OMISSAO = 3012;

const VARIAVEL_DA_BASE = 'KAMBA_CONSUMIDOR_DB_URL';
/**
 * A ligação de **operação**, que é outro papel.
 *
 * O consumo corre como `kamba_app`: tem `INSERT` em `events_consumed` e na DLQ,
 * está sujeito à RLS e vê só o tenant do evento que tem em mão. O
 * reconciliador e o *gauge* da DLQ são outra coisa — leem `evt_subscricoes`, o
 * arquivo e a DLQ **de todos os tenants** para descobrir o que se perdeu —, e
 * isso é trabalho de `kamba_batch`, que tem `BYPASSRLS` e é auditado
 * (`docs/tecnica/08` §3.3). Dar à ligação do consumo os privilégios da
 * operação era dar ao caminho do dinheiro a visão de toda a plataforma.
 */
const VARIAVEL_DA_OPERACAO = 'KAMBA_CONSUMIDOR_OPS_DB_URL';
const VARIAVEL_DA_FILA = 'KAMBA_QUEUE_URL';
/**
 * A ligação da **identidade de contacto**, só do `outbound` (KAM-227).
 *
 * `kamba_identity` é o único papel de serviço com `SELECT` na
 * `contact_endpoints` e na `contact_deks`: é por ela que se lê o BSUID ou o
 * telefone de quem recebe a resposta. O consumo (`kamba_app`) não os vê.
 */
const VARIAVEL_DA_IDENTIDADE = 'KAMBA_CONSUMIDOR_IDENTITY_DB_URL';
/** O ambiente do cofre e das chaves de identidade. Sem omissão para o `outbound`. */
const VARIAVEL_DO_AMBIENTE = 'KAMBA_ENV';
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
 * O consumidor `outbound` sem o cliente da Meta ou sem o destinatário.
 *
 * Arrancar sem eles era consumir as respostas e recusá-las todas — ou pior,
 * enviá-las sem destinatário. Sai antes de levantar *workers*, e os eventos
 * esperam nas filas (KAM-224). Desde o KAM-227 o processo monta as duas de
 * produção (`portasDoOutbound`), e esta recusa fica como a guarda da ligação:
 * um `outbound` montado sem elas não chega a consumir.
 */
export class SaidaSemPortasError extends Error {
  readonly emFalta: readonly string[];

  constructor(emFalta: readonly string[]) {
    super(
      `o consumidor ${CONSUMIDOR_DO_OUTBOUND} precisa de ${emFalta.join(' e ')}: ` +
        'sem eles nenhuma resposta do AGR sai pelo WhatsApp (as de producao: portasDoOutbound, KAM-227)',
    );
    this.name = 'SaidaSemPortasError';
    this.emFalta = emFalta;
  }
}

/** As portas que o `outbound` precisa. Uma `null` é uma porta por ligar. */
export interface PortasDoOutbound {
  readonly meta: ClienteDoCanal | null;
  readonly destinatario: ObterDestinatario | null;
  /** Toma uma ligação `kamba_app` própria para o `Saida`. */
  readonly tomar: () => Promise<LigacaoDoEnvio>;
  readonly devolver: (ligacao: LigacaoDoEnvio, erro?: unknown) => Promise<void> | void;
  readonly aoTratar?: (desfecho: DesfechoDaResposta, motivo?: string) => void;
}

/**
 * O efeito do consumidor, pelo nome. Exportada para se ensaiar sem processo.
 *
 * O `outbound` monta o `Saida` (`envioPeloSaida`) e recusa sem as duas portas;
 * os outros nomes ficam com o efeito do esqueleto.
 */
export function efeitoDoConsumidor(consumer: string, portas: PortasDoOutbound): Efeito {
  if (consumer !== CONSUMIDOR_DO_OUTBOUND) return async () => {};
  const emFalta = [
    ...(portas.meta === null ? ['o cliente da Meta'] : []),
    ...(portas.destinatario === null ? ['o destinatario'] : []),
  ];
  if (portas.meta === null || portas.destinatario === null) {
    throw new SaidaSemPortasError(emFalta);
  }
  return efeitoDoOutbound(
    envioPeloSaida({
      tomar: portas.tomar,
      devolver: portas.devolver,
      meta: portas.meta,
      destinatario: portas.destinatario,
    }),
    portas.aoTratar === undefined ? {} : { aoTratar: portas.aoTratar },
  );
}

/** As duas portas de produção do `outbound`, e o que fechar no fim. */
export interface PortasDeProducao {
  readonly meta: ClienteDoCanal;
  readonly destinatario: ObterDestinatario;
}

/** O que o `portasDoOutbound` pede ao processo: o ambiente e a ligação de identidade. */
export interface ArranqueDoOutbound {
  readonly env: Readonly<Record<string, string | undefined>>;
  /** Toma uma ligação `kamba_identity`. Em produção, de um *pool* pequeno. */
  readonly tomarIdentidade: () => Promise<ClienteDeIdentidade>;
  readonly devolverIdentidade: (ligacao: ClienteDeIdentidade, erro?: unknown) => Promise<void> | void;
}

/** O ambiente declarado para o `outbound`. Um valor desconhecido não vale `dev`. */
export function ambienteDoOutbound(env: Readonly<Record<string, string | undefined>>): Ambiente {
  const declarado = (env[VARIAVEL_DO_AMBIENTE] ?? '').trim();
  if (!isAmbiente(declarado)) {
    throw new Error(`${VARIAVEL_DO_AMBIENTE} tem de ser dev, staging ou prod para o ${CONSUMIDOR_DO_OUTBOUND}`);
  }
  return declarado;
}

/**
 * Monta as duas portas de produção do `outbound` (KAM-227), ou recusa.
 *
 * Exportada para se medir o arranque sem levantar o processo: é o critério 3, e
 * as recusas são as do cofre e da identidade, não deste ficheiro.
 *
 * @throws {ArranqueAbortadoError} sem a `kek_token_cliente` no cofre.
 * @throws {ChavesDeIdentidadeEmFaltaError} em `prod`, sem a `kek_contact_dek`.
 */
export async function portasDoOutbound(a: ArranqueDoOutbound): Promise<PortasDeProducao> {
  const ambiente = ambienteDoOutbound(a.env);
  const provider = new EnvSecretProvider({ ambiente, env: a.env });
  const cofre = await Secrets.arrancar({
    servico: 'worker-canal-consumidor',
    provider,
    // Obrigatória onde o inventário a declara obrigatória (`staging`, `prod`).
    // Em `dev` o processo arranca sem ela, e cada envio sobe o erro do cofre.
    obrigatorios: ambiente === 'dev' ? [] : [REF_DA_KEK],
  });
  const identidade = await Identidade.arrancar({
    chaves: new EnvKeyProvider({ ambiente, env: a.env }),
    env: a.env,
    // Só o `lerEndpoints`: o *pepper* do HMAC não chega a este processo.
    soLeEndpoints: true,
  });
  return {
    meta: clienteDaGraphPorCanal({ cofre }),
    destinatario: destinatarioPelaIdentidade({
      identidade,
      tomar: a.tomarIdentidade,
      devolver: a.devolverIdentidade,
    }),
  };
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
  const urlDaOperacao = exigir(VARIAVEL_DA_OPERACAO);
  const urlDaFila = exigir(VARIAVEL_DA_FILA);

  // A verificação de arranque lê `evt_subscricoes`, que `kamba_app` não vê:
  // é leitura de operação, e corre na ligação de operação.
  const operacao = new Client({ connectionString: urlDaOperacao });
  await operacao.connect();
  await exigirOrdemNosPagamentos(operacao);

  // O `Saida` corre numa ligação própria, e não na do consumo: ver a nota do
  // `efeito.ts` de `@kamba/core-ts/resposta`. Um conjunto pequeno, tomado por
  // envio. As duas portas de produção montam-se **antes** de levantar
  // *workers*, e recusam aqui: ver «O arranque do `outbound` em `prod`».
  const envios = new pg.Pool({ connectionString: urlDaBase, max: 4 });
  envios.on('error', () => log.warn({ outcome: 'ligacao_do_envio_caiu' }));
  let identidades: pg.Pool | null = null;
  let producao: PortasDeProducao | null = null;
  if (consumer === CONSUMIDOR_DO_OUTBOUND) {
    const pool = new pg.Pool({ connectionString: exigir(VARIAVEL_DA_IDENTIDADE), max: 2 });
    pool.on('error', () => log.warn({ outcome: 'ligacao_da_identidade_caiu' }));
    identidades = pool;
    producao = await portasDoOutbound({
      env: process.env,
      tomarIdentidade: async () => pool.connect(),
      devolverIdentidade: (ligacao, erro) =>
        (ligacao as pg.PoolClient).release(erro instanceof Error ? erro : undefined),
    });
  }
  const efeito = efeitoDoConsumidor(consumer, {
    meta: producao?.meta ?? null,
    destinatario: producao?.destinatario ?? null,
    tomar: async () => envios.connect(),
    devolver: (ligacao, erro) => (ligacao as pg.PoolClient).release(erro instanceof Error ? erro : undefined),
    // O motivo não vai ao registo: o `outcome` tem gramática fechada, e o
    // desfecho chega para a métrica. O detalhe vive na `outbound_messages`.
    aoTratar: (desfecho) => log.info({ outcome: `resposta_${desfecho}` }),
  });

  const consumo = criarTrabalhadores({
    // Uma ligação por fila, aberta à primeira entrega: a transacção do consumo
    // é da fila, e dezasseis filas numa sessão intercalavam `BEGIN`/`COMMIT`.
    ligar: async () => {
      const cliente = new Client({ connectionString: urlDaBase });
      await cliente.connect();
      return cliente;
    },
    // O `outbound` corre com a ordem da sua subscricao (`false`, revisao
    // `*_resposta_do_agr.py`); o esqueleto mantem a exigida.
    subscricao: { consumer, exigeOrdem: consumer !== CONSUMIDOR_DO_OUTBOUND },
    filas: filasDe(consumer),
    // Pelo nome do consumidor: ver a docstring.
    efeito,
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
  // réplica em espera para publicar ficar em espera para repor. Corre na
  // ligação de operação, que já está aberta desde a verificação de arranque.
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
    // `fechar()` fecha os *workers* **e** as ligações que cada fila abriu.
    await consumo.fechar();
    await filas.fechar();
    await operacao.end().catch(() => {});
    await envios.end().catch(() => {});
    await identidades?.end().catch(() => {});
    servidor.close();
  }
}

if (import.meta.main) {
  await principal();
}
