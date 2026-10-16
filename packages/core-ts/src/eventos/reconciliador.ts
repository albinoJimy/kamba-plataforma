/**
 * O reconciliador: repõe o que a fila perdeu (KAM-006, `docs/tecnica/06` §6.5).
 *
 * ## Porque é preciso, com o outbox a existir
 *
 * O publicador marca `publicado_at` **depois** do `add` à fila. Se o Redis
 * perder o *job* — por falha, por `FLUSHALL`, por uma expiração mal
 * configurada —, a linha do outbox já está publicada e o publicador não volta a
 * tocar-lhe: para ele, o trabalho está feito. O evento ficou arquivado em
 * `events_log` e nunca chegou a consumidor nenhum.
 *
 * É esse o buraco que isto fecha, e a verdade usada para o detectar não é a
 * fila (que já perdeu a informação): é a diferença entre **o que o arquivo diz
 * que foi publicado** e **o que o consumo e a DLQ dizem que chegou**.
 *
 * ## A consulta é a do documento, com dois parâmetros
 *
 * O §6.5 escreve `interval '24 hours'` e `interval '10 minutes'` como literais.
 * Aqui são parâmetros, por uma razão de prova e não de gosto: com os literais
 * dentro do SQL, verificar a reposição levava dez minutos de espera real por
 * execução (critério 8). Os valores por omissão são os do documento.
 *
 * ## Um líder, e o mesmo *lock* do publicador? Não.
 *
 * O reconciliador tem **o seu** *lock* consultivo. Com o do publicador, as duas
 * tarefas ficavam amarradas: uma réplica em espera para publicar também ficava
 * em espera para reconciliar, e um publicador líder pendurado numa chamada de
 * rede impedia a reposição de correr. São trabalhos diferentes, com ritmos
 * diferentes (200 ms contra 5 min).
 */

import { SQL_A_REPOR } from './consultas_consumo.ts';
import { nomeDaFila } from './particao.ts';
import type { ClienteSql } from './publicador.ts';
import type { Filas, Trabalho } from './filas.ts';
import { REPETICAO } from './filas.ts';

/**
 * O *lock* consultivo do reconciliador.
 *
 * 7102, o seguinte ao do publicador (7101, §6.2). O documento não o nomeia; o
 * número está aqui e não espalhado, para que uma colisão futura se veja num
 * sítio só.
 */
export const LOCK_DO_RECONCILIADOR = 7102;

/** Janela de procura, em segundos: o `interval '24 hours'` do §6.5. */
export const JANELA_POR_OMISSAO = 24 * 60 * 60;

/** Idade mínima para considerar perdido: o `interval '10 minutes'` do §6.5. */
export const CARENCIA_POR_OMISSAO = 10 * 60;

/** Quantos eventos se repõem por passagem. */
export const LOTE_POR_OMISSAO = 500;

/** Intervalo entre passagens: os «5 min» do §6.5. */
export const INTERVALO_POR_OMISSAO = 5 * 60 * 1_000;

export interface LinhaAReporar {
  readonly event_id: string;
  readonly tipo: string;
  readonly tenant_id: string;
  readonly agregado_id: string;
  readonly consumer: string;
}

export interface ResultadoDaReposicao {
  /** Quantas linhas a consulta devolveu. */
  readonly encontradas: number;
  /** Quantos *jobs* foram re-enfileirados. */
  readonly repostos: number;
  /** Quantas filas distintas foram tocadas. */
  readonly filas: number;
}

export interface OpcoesDoReconciliador {
  readonly bd: ClienteSql;
  readonly filas: Filas;
  readonly janela?: number;
  readonly carencia?: number;
  readonly lote?: number;
  readonly log?: (dados: Record<string, unknown>) => void;
}

/**
 * A partição de um evento, calculada como o `evt_emitir` a calcula.
 *
 * **Não** se lê do `events_outbox`: a linha pode já ter saído do outbox por
 * retenção, e o arquivo (`events_log`) não guarda a partição. Recalcular com a
 * mesma conta do §6.5 dá o mesmo número — e é o teste
 * `test_a_conta_e_a_do_documento` do KAM-005 que prende a conta ao documento.
 *
 * A conta corre **na base** (`hashtextextended`), e não em TypeScript: é a
 * mesma função que escolheu a fila na publicação, e reimplementá-la aqui era
 * assinar que duas implementações de um *hash* concordam para sempre.
 */
export const SQL_PARTICAO = `
  SELECT (hashtextextended($1::text || $2, 0) & 15)::int AS particao
`;

/**
 * Uma passagem: procura o que se perdeu e volta a pô-lo na fila do consumidor.
 *
 * O `jobId` é o `event_id`, como na publicação: se o *job* original ainda
 * existir na fila (porque o que se perdeu foi outra coisa), o BullMQ recusa o
 * duplicado e a reposição não duplica nada. E se chegar duas vezes, o consumo
 * idempotente absorve — são as duas redes, e as duas são precisas.
 */
export async function reporUmaVez(
  opcoes: OpcoesDoReconciliador,
): Promise<ResultadoDaReposicao> {
  const {
    bd,
    filas,
    janela = JANELA_POR_OMISSAO,
    carencia = CARENCIA_POR_OMISSAO,
    lote = LOTE_POR_OMISSAO,
    log,
  } = opcoes;

  const { rows } = await bd.query(SQL_A_REPOR, [janela, carencia, lote]);
  const linhas = rows as unknown as LinhaAReporar[];
  if (linhas.length === 0) return { encontradas: 0, repostos: 0, filas: 0 };

  // Agrupa por fila antes de escrever: um `addLote` por fila, como o publicador
  // faz. Um `add` por evento multiplicava as idas à fila pelo número de
  // eventos perdidos — e eles vêm em rajada, por definição.
  const porFila = new Map<string, Trabalho[]>();
  for (const linha of linhas) {
    const { rows: calculo } = await bd.query(SQL_PARTICAO, [
      linha.tenant_id,
      linha.agregado_id,
    ]);
    const particao = Number(calculo[0]?.particao);
    const fila = nomeDaFila(linha.consumer, particao);
    const trabalhos = porFila.get(fila) ?? [];
    trabalhos.push({
      jobId: linha.event_id,
      nome: linha.tipo,
      dados: {
        event_id: linha.event_id,
        consumer: linha.consumer,
        // Sem isto o consumidor não põe o contexto da RLS e o arquivo
        // responde-lhe zero linhas: um evento reposto ia para a DLQ como
        // «evento desconhecido». A consulta do §6.5 já traz o `tenant_id`.
        tenant_id: linha.tenant_id,
        reposto: true,
      },
    });
    porFila.set(fila, trabalhos);
  }

  let repostos = 0;
  for (const [fila, trabalhos] of porFila) {
    await filas.addLote(fila, trabalhos);
    repostos += trabalhos.length;
  }
  log?.({
    evento: 'reposicao',
    encontradas: linhas.length,
    repostos,
    filas: porFila.size,
    tentativas: REPETICAO.tentativas,
  });
  return { encontradas: linhas.length, repostos, filas: porFila.size };
}
