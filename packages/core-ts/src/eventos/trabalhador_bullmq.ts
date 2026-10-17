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
 *    o `adiado` relança o próprio `Adiar`, e o atraso sai do
 *    `backoffStrategy`, que recebe o erro: para um `Adiar` devolve o
 *    `atrasoMs` dele, e para tudo o mais o degrau da escada. É aí que o
 *    `Adiar.atrasoMs` paga — a escada está em milissegundos e o `Adiar` em
 *    segundos, e um `× 1000` esquecido queimava as seis tentativas num
 *    instante.
 *
 * 3. **A escada só se aplica se o *job* a pedir.** O BullMQ só chama o
 *    `backoffStrategy` quando as opções do *job* dizem `backoff: {type:
 *    'custom'}` — e é o **publicador** que cria o *job*. Com o `exponential`
 *    que lá estava, a escada deste módulo nunca era consultada e o recuo real
 *    era 1 s, 2 s, 4 s, 8 s, 16 s: o critério 2 ficava satisfeito na contagem e
 *    errado nos intervalos. Está em `filas_bullmq.ts`, e os dois ficheiros
 *    estão presos pelo teste `test_o_job_pede_a_escada_do_consumidor`.
 *
 * ## A concorrência é 1, e isso é a ordem
 *
 * Uma fila por partição, `concurrency: 1` por fila (§6.5). A ordem só vale
 * dentro da partição, e dois *jobs* da mesma partição em paralelo perdiam-na.
 * Escala-se com mais *workers* por fila — não com mais concorrência por fila.
 *
 * ## Uma ligação por fila, e não uma para todas
 *
 * `concurrency: 1` limita cada fila, **não** o processo: dezasseis filas são
 * dezasseis *jobs* ao mesmo tempo. Com uma ligação partilhada, os `BEGIN` e
 * `COMMIT` de dezasseis transacções intercalavam-se na mesma sessão — um
 * `COMMIT` de uma fila fechava a transacção de outra, e a marca de consumo de
 * um evento ficava confirmada com o efeito de outro. Por isso a opção é
 * `ligar()`, uma fábrica, e cada fila abre a sua à primeira entrega (e não ao
 * arranque: uma réplica que sirva quatro filas não abre dezasseis sessões).
 *
 * ## O contexto de tenant, e de onde ele vem
 *
 * O consumidor é `kamba_app`, que é `NOBYPASSRLS`, e `events_log` tem RLS: ler
 * o envelope sem contexto devolve **zero linhas**, e zero linhas lê-se «o
 * arquivo não tem este evento». Por isso o *job* traz o `tenant_id` e é com ele
 * que se põe o contexto antes da leitura. É um ponteiro da fila, não uma
 * autoridade: se o `tenant_id` do *job* não for o do evento, a leitura não vê
 * nada e falha fechada — e dentro da transacção o contexto é reposto a partir
 * do **envelope** (`consumo.ts`), que é o arquivo a dizer de quem o evento é.
 */

import { Worker, UnrecoverableError } from 'bullmq';
import { Redis } from 'ioredis';

import {
  ADIAMENTO_POR_OMISSAO,
  Adiar,
  TENTATIVAS,
  atrasoDaTentativaDoConsumidor,
} from './consumo.ts';
import type { Efeito } from './consumo.ts';
import { SQL_DEFINIR_TENANT } from './consultas_consumo.ts';
import { paraDlqSemEnvelope } from './dlq.ts';
import type { Envelope } from './envelope.ts';
import { lerEnvelope } from './envelope.ts';
import type { MaquinaDeEstados } from './estados.ts';
import { LIGACAO_QUE_FALHA_DEPRESSA, opcoesDaUrl } from './filas_bullmq.ts';
import type { Metricas } from './metricas.ts';
import type { ClienteSql } from './publicador.ts';
import {
  type DesfechoDoTrabalho,
  type ResultadoDoTrabalho,
  processar,
} from './trabalho.ts';

/** O que o trabalhador precisa de saber sobre a subscrição que serve. */
export interface Subscricao {
  readonly consumer: string;
  readonly exigeOrdem: boolean;
}

/** Uma ligação que o trabalhador abre e, no fim, fecha. */
export interface LigacaoDoTrabalhador extends ClienteSql {
  end(): Promise<void>;
}

export interface OpcoesDoTrabalhador {
  /**
   * Abre uma ligação nova. Chamada **uma vez por fila**, à primeira entrega.
   *
   * Uma fábrica e não uma ligação: a transacção do consumo é da fila, e
   * dezasseis filas numa sessão intercalavam `BEGIN`/`COMMIT`. Ver a docstring
   * do módulo.
   */
  readonly ligar: () => Promise<LigacaoDoTrabalhador>;
  readonly subscricao: Subscricao;
  /** As filas que este trabalhador serve (as 16 partições, ou um subconjunto). */
  readonly filas: readonly string[];
  readonly efeito: Efeito;
  readonly maquina?: MaquinaDeEstados;
  readonly metricas?: Metricas;
  readonly url: string;
  readonly log?: (dados: Record<string, unknown>) => void;
  /**
   * A escada de recuo. Por omissão a do §6.4.
   *
   * Só se passa para **acelerar o relógio** numa suite: é o que os «Testes
   * Requeridos» do KAM-006 pedem, e sem isto provar «6 tentativas depois DLQ»
   * custava 756 s de espera real por teste. Os valores da escada de produção
   * provam-se noutro lado (`TestEscada`, nos dois idiomas).
   */
  readonly escada?: readonly number[];
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

export class TenantEmFaltaError extends Error {
  readonly eventId: string;

  constructor(eventId: string) {
    super(
      `o job do evento ${eventId} não traz tenant_id: sem ele não há contexto ` +
        'para a RLS, e o arquivo responde zero linhas como se o evento não existisse',
    );
    this.name = 'TenantEmFaltaError';
    this.eventId = eventId;
  }
}

/**
 * Lê o envelope do arquivo, com o contexto de tenant posto.
 *
 * O `jobId` é o `event_id`; o `tenantId` vem do *job*. O contexto é de **sessão**
 * (`is_local = false`) e não de transacção, porque esta leitura corre fora de
 * qualquer transacção — e a ligação é de uma fila só, com um *job* de cada vez,
 * pelo que não há outro consumo a ver o contexto desta. Dentro da transacção, o
 * `consumir()` repõe-no a partir do envelope.
 */
export async function envelopeDoEvento(
  bd: ClienteSql,
  eventId: string,
  tenantId: string,
): Promise<Envelope> {
  if (tenantId === '') throw new TenantEmFaltaError(eventId);
  await bd.query(SQL_DEFINIR_TENANT, [tenantId, false]);
  const { rows } = await bd.query(SQL_ENVELOPE_DO_EVENTO, [eventId]);
  const linha = rows[0];
  if (linha === undefined) throw new EventoDesconhecidoError(eventId);
  return lerEnvelope(linha.envelope);
}

/** O `tenant_id` que o *job* traz, do publicador ou do reconciliador. */
export function tenantDoJob(dados: unknown): string {
  if (typeof dados !== 'object' || dados === null) return '';
  const registo = dados as Record<string, unknown>;
  const directo = registo.tenant_id;
  if (typeof directo === 'string') return directo;
  // O publicador põe o envelope convertido nos dados; o `tenant_id` dele é a
  // mesma coisa. Aceitam-se os dois para que um *job* já em fila, criado antes
  // de o campo existir, continue a ser consumido em vez de ir para a DLQ.
  const envelope = registo.envelope;
  if (typeof envelope === 'object' && envelope !== null) {
    const dentro = (envelope as Record<string, unknown>).tenant_id;
    if (typeof dentro === 'string') return dentro;
  }
  return '';
}

/** Os *workers* e o que os fecha, com as ligações que abriram. */
export interface Trabalhadores {
  readonly trabalhadores: readonly Worker[];
  /** Fecha os *workers* e as ligações que cada fila abriu. */
  fechar(): Promise<void>;
}

/**
 * Cria os *workers*, um por fila, e devolve-os com o seu `fechar()`.
 *
 * Quem os fecha é quem os criou: este módulo não instala tratadores de sinal.
 * O `fechar()` existe porque as ligações são abertas aqui — uma por fila — e
 * quem as não fechasse deixava sessões penduradas no PostgreSQL a cada
 * reinício.
 */
export function criarTrabalhadores(opcoes: OpcoesDoTrabalhador): Trabalhadores {
  const { ligar, subscricao, filas, efeito, maquina, metricas, url, log, escada } = opcoes;
  const ligacao = new Redis({ ...opcoesDaUrl(url), ...LIGACAO_QUE_FALHA_DEPRESSA });
  // Sem isto, um erro de ligação num cliente `ioredis` sem ouvinte de `error`
  // derruba o processo — e derrubar o consumidor quando a fila cai é o oposto
  // do que o critério 8 pede (o reconciliador repõe o que se perdeu).
  ligacao.on('error', () => {});

  const abertas: Promise<LigacaoDoTrabalhador>[] = [];

  const trabalhadores = filas.map((fila) => {
    // A ligação desta fila, aberta à primeira entrega e reutilizada. O que se
    // guarda é a **promessa** e não a ligação: duas entregas quase simultâneas
    // na mesma fila não acontecem (`concurrency: 1`), mas guardar a promessa
    // torna isso irrelevante em vez de depender dele.
    let minha: Promise<LigacaoDoTrabalhador> | undefined;
    const ligacaoDaFila = (): Promise<LigacaoDoTrabalhador> => {
      if (minha === undefined) {
        minha = ligar();
        abertas.push(minha);
      }
      return minha;
    };

    /**
     * Larga a ligação desta fila, para a entrega seguinte abrir outra.
     *
     * O `pg.Client` **não religa**: depois de uma queda da base ou de um
     * *failover*, fica em erro permanente e toda a consulta devolve «Client
     * has encountered a connection error and is not queryable». Com a
     * promessa memoizada para sempre, a partição morria até ao reinício do
     * processo — dezasseis sessões a poderem morrer uma a uma, com o
     * `/healthz` a dizer que está tudo bem.
     */
    const largarLigacao = (): void => {
      const morta = minha;
      minha = undefined;
      if (morta !== undefined) {
        void morta.then((cliente) => cliente.end()).catch(() => {});
      }
    };

    return new Worker(
      fila,
      async (job) => {
        const bd = await ligacaoDaFila();
        const eventId = job.id ?? String(job.data?.event_id ?? '');
        const tenantId = tenantDoJob(job.data);
        // `attemptsMade` conta as que **já** falharam; esta é a seguinte.
        const tentativa = job.attemptsMade + 1;
        const ultima = tentativa >= TENTATIVAS;

        // A leitura do envelope corre **antes** do `processar()`, e por isso
        // fora da política dele. Um erro aqui, deixado a subir, esgotava as
        // seis tentativas e deixava o *job* em `failed` no Redis — sem linha
        // na DLQ, sem métrica e sem alerta —, e como não há `events_consumed`
        // nem `events_dlq` o reconciliador voltava a enfileirá-lo de cinco em
        // cinco minutos durante 24 h. Um ciclo silencioso, que é a pior forma
        // de perder um evento. Cada classe de erro tem aqui a sua resposta.
        let envelope: Envelope;
        try {
          envelope = await envelopeDoEvento(bd, eventId, tenantId);
        } catch (erro) {
          if (erro instanceof TenantEmFaltaError) {
            // Nenhuma retentativa acrescenta um `tenant_id` ao *job*, e sem
            // ele não há linha de DLQ possível: a DLQ é isolada por tenant e
            // quem escreve está sujeito à política. Falha à primeira, para
            // não gastar seis tentativas no que não muda.
            log?.({ evento: 'consumo', fila, event_id: eventId, tentativa, desfecho: 'sem_tenant' });
            throw new UnrecoverableError(erro.message);
          }
          if (erro instanceof EventoDesconhecidoError) {
            // Pode ser cedo: o publicador põe o *job* na fila **antes** do
            // `COMMIT` que arquiva, pelo que uma entrega muito rápida chega a
            // um arquivo que ainda não tem a linha. Adia-se; esgotadas as
            // tentativas, abre-se a entrada com o que se sabe.
            if (!ultima) throw new Adiar(ADIAMENTO_POR_OMISSAO, erro.message);
            await paraDlqSemEnvelope({
              bd,
              consumer: subscricao.consumer,
              eventId,
              tenantId,
              erro: erro.message,
              tentativas: tentativa,
            });
            log?.({ evento: 'consumo', fila, event_id: eventId, tentativa, desfecho: 'dlq' });
            throw new UnrecoverableError(`dlq: ${erro.message}`);
          }
          // Erro da base ou da ligação. A sessão pode estar morta.
          largarLigacao();
          throw erro;
        }

        let resultado: ResultadoDoTrabalho;
        try {
          resultado = await processar(
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
        } catch (erro) {
          // O `processar()` devolve desfecho para tudo o que é política e só
          // relança o que é técnico — e técnico inclui «a base caiu».
          largarLigacao();
          throw erro;
        }
        log?.({
          evento: 'consumo',
          fila,
          event_id: eventId,
          tentativa,
          desfecho: resultado.desfecho,
        });
        if (resultado.desfecho === 'adiado') {
          // Relança para o BullMQ repetir. O atraso sai do `backoffStrategy`,
          // que reconhece o `Adiar` e usa o atraso dele.
          //
          // **Não** se chama `moveToDelayed` aqui, e isso foi uma correcção: o
          // BullMQ só aceita esse movimento se o que se lançar a seguir for um
          // `DelayedError` dele; com outro erro, o *job* já não está activo e o
          // tratamento da falha rebenta a dizer que falta o *lock* — um evento
          // adiado ficava preso em vez de ser retentado.
          throw new Adiar(resultado.adiamento ?? ADIAMENTO_POR_OMISSAO);
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
          // número de tentativas já feitas e com o erro que falhou — e é o erro
          // que distingue os dois atrasos: um `Adiar` traz o seu (5 s, §6.3),
          // tudo o mais recua pela escada.
          backoffStrategy: (tentativasFeitas: number, _tipo?: string, erro?: Error) =>
            erro instanceof Adiar
              ? erro.atrasoMs
              : atrasoDaTentativaDoConsumidor(Math.max(tentativasFeitas, 1), escada),
        },
      },
    );
  });

  return {
    trabalhadores,
    async fechar(): Promise<void> {
      // Os *workers* primeiro: fechar uma ligação debaixo de um *job* a correr
      // fazia a transacção dele morrer a meio, e o evento voltava à fila com a
      // marca de consumo por confirmar. Fechados os *workers*, não há mais
      // transacções.
      await Promise.all(trabalhadores.map((t) => t.close()));
      const ligacoes = await Promise.allSettled(abertas);
      await Promise.all(
        ligacoes.map((resultado) =>
          resultado.status === 'fulfilled'
            ? resultado.value.end().catch(() => {})
            : Promise.resolve(),
        ),
      );
      ligacao.disconnect();
    },
  };
}
