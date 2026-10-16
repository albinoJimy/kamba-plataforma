/**
 * O consumidor idempotente (KAM-006, `docs/tecnica/06` §6.3).
 *
 * ## O que faz, e porque é esta a ordem
 *
 *     BEGIN
 *       n = INSERT events_consumed ON CONFLICT DO NOTHING
 *       se n == 0: COMMIT; duplicado — e não se faz mais nada
 *       se exige_ordem: ler o último seq e o estado do agregado
 *                       → Adiar (pré-condição por chegar)
 *                       → ForaDeOrdem (seq atrasado E transição inválida)
 *       efeito(bd)      ← na MESMA transacção
 *     COMMIT
 *
 * A marca e o efeito partilham a transacção, e é isso que o torna
 * exactamente-uma-vez. Em duas transacções haveria dois modos de falha e os
 * dois acontecem: efeito sem marca (repete-se à próxima entrega) ou marca sem
 * efeito (perde-se para sempre). A entrega da fila continua *at-least-once* —
 * o publicador do KAM-005 republica tudo o que não tenha `publicado_at` —, e é
 * esse o pressuposto.
 *
 * ## Adiar não é falhar, e falhar não é descartar
 *
 * Três saídas, e a diferença entre elas é o que decide se um pagamento se perde:
 *
 * - **`Adiar(s)`** — a pré-condição ainda não se verifica (`payment.confirmed`
 *   antes de a encomenda estar em `aguarda_pagamento`). Tenta-se outra vez. Uma
 *   pré-condição que **nunca** se verifica esgota as tentativas e vai para a
 *   DLQ; nunca se aplica a transição (§6.3).
 * - **`ForaDeOrdem`** — o evento vem atrasado **e** a transição não é válida na
 *   máquina de estados. Não há tentativa que resolva: vai directo para a DLQ,
 *   com `erro = 'fora_de_ordem'`.
 * - **qualquer outro erro** — recua pela escada e, esgotadas as seis
 *   tentativas, DLQ.
 *
 * ## A escada é a do §6.4 e não a do publicador
 *
 * 1 s, 5 s, 30 s, 2 min, 10 min, sobre 1 + 5 tentativas. O publicador tem uma
 * escada **diferente** (`ESCADA_DE_RECUO`, tecto de 30 s) de propósito: ali o
 * que recua é a republicação de um evento que ninguém consumiu, e meia hora de
 * espera não ajuda; aqui o que recua é um efeito de negócio cuja pré-condição
 * pode levar minutos a chegar.
 */

import {
  SQL_MARCAR_CONSUMIDO,
  SQL_ULTIMO_SEQ,
} from './consultas_consumo.ts';
import type { Envelope } from './envelope.ts';
import {
  ESTADO_PRETENDIDO,
  type MaquinaDeEstados,
  podeTransitar,
} from './estados.ts';
import {
  METRICA_CONSUMIDOS,
  METRICA_RETENTATIVAS,
  type DesfechoDoConsumo,
  type Metricas,
} from './metricas.ts';
import type { ClienteSql } from './publicador.ts';

/**
 * A escada de recuo do consumidor (§6.4), em milissegundos.
 *
 * Cinco atrasos para cinco retentativas; com a primeira tentativa são as **6**
 * do critério 2. O `filas.ts` já declara `REPETICAO.tentativas = 6` para o
 * `add`, e os dois números têm de ser o mesmo — o teste
 * `test_a_escada_tem_uma_entrada_por_retentativa` prende-os.
 */
export const ESCADA_DO_CONSUMIDOR = [1_000, 5_000, 30_000, 120_000, 600_000] as const;

/** 1 + 5. O número do critério 2, derivado da escada e não escrito ao lado. */
export const TENTATIVAS = 1 + ESCADA_DO_CONSUMIDOR.length;

/** Quantos segundos adiar quando a pré-condição ainda não se verifica (§6.3). */
export const ADIAMENTO_POR_OMISSAO = 5;

/**
 * O atraso antes da tentativa número `tentativas + 1`.
 *
 * `tentativas` é quantas já falharam. Acima da escada devolve o último degrau,
 * em vez de crescer para sempre: a sexta falha não espera, vai para a DLQ.
 */
export function atrasoDaTentativaDoConsumidor(tentativas: number): number {
  if (!Number.isInteger(tentativas) || tentativas < 1) {
    throw new RangeError(`tentativas tem de ser um inteiro >= 1: ${tentativas}`);
  }
  const indice = Math.min(tentativas, ESCADA_DO_CONSUMIDOR.length) - 1;
  return ESCADA_DO_CONSUMIDOR[indice];
}

/** A pré-condição ainda não se verifica. Tenta-se outra vez. */
export class Adiar extends Error {
  constructor(
    readonly segundos: number = ADIAMENTO_POR_OMISSAO,
    readonly porque = 'pré-condição de estado por verificar',
  ) {
    super(`adiar ${segundos}s: ${porque}`);
    this.name = 'Adiar';
  }
}

/** O evento vem atrasado e a transição não é válida. Não há tentativa que resolva. */
export class ForaDeOrdem extends Error {
  /** O valor que vai para a coluna `erro` da DLQ, e que o critério 4 exige. */
  static readonly CODIGO = 'fora_de_ordem';

  constructor(readonly detalhe: string) {
    super(`${ForaDeOrdem.CODIGO}: ${detalhe}`);
    this.name = 'ForaDeOrdem';
  }
}

/**
 * O que aconteceu a um evento.
 *
 * E o mesmo tipo que a etiqueta da metrica aceita (`DESFECHOS_DO_CONSUMO`), e
 * nao uma uniao escrita ao lado: duas listas dos mesmos dois valores divergem
 * no dia em que aparecer um terceiro.
 */
export type Desfecho = DesfechoDoConsumo;

export interface ResultadoDoConsumo {
  readonly desfecho: Desfecho;
  /** O `seq` mais alto já consumido deste agregado, quando se leu. */
  readonly ultimoSeq: number | null;
}

/** O efeito de negócio. Corre **dentro** da transacção, com o mesmo cliente. */
export type Efeito = (bd: ClienteSql) => Promise<void>;

export interface OpcoesDoConsumo {
  readonly bd: ClienteSql;
  readonly consumer: string;
  readonly envelope: Envelope;
  /** Da subscrição. Para `payment.*` é sempre `true` (restrição da revisão 0005). */
  readonly exigeOrdem: boolean;
  /** Obrigatória quando `exigeOrdem` e o tipo tem estado pretendido. */
  readonly maquina?: MaquinaDeEstados;
  readonly metricas?: Metricas;
}

/**
 * Processa um evento uma só vez, com o efeito na mesma transacção.
 *
 * Não trata de retentativas nem de DLQ: isso é política, e vive no
 * `processar()` do trabalhador. Aqui está a transacção e nada mais — é o que
 * permite testá-la sem fila.
 */
export async function consumir(
  opcoes: OpcoesDoConsumo,
  efeito: Efeito,
): Promise<ResultadoDoConsumo> {
  const { bd, consumer, envelope, exigeOrdem, maquina, metricas } = opcoes;
  const agregado = envelope.agregado;

  await bd.query('BEGIN');
  try {
    const marca = await bd.query(SQL_MARCAR_CONSUMIDO, [
      consumer,
      envelope.id,
      envelope.tenant_id,
      agregado.tipo,
      agregado.id,
      agregado.seq,
    ]);
    if ((marca.rowCount ?? 0) === 0) {
      // Duplicado. `COMMIT` e não `ROLLBACK`: não há nada para desfazer, e um
      // `ROLLBACK` aqui lia-se como erro no registo de quem depurar.
      await bd.query('COMMIT');
      metricas?.contar(METRICA_CONSUMIDOS, 'duplicado');
      return { desfecho: 'duplicado', ultimoSeq: null };
    }

    let ultimoSeq: number | null = null;
    if (exigeOrdem) {
      const { rows } = await bd.query(SQL_ULTIMO_SEQ, [
        consumer,
        agregado.tipo,
        agregado.id,
        envelope.id,
      ]);
      const bruto = rows[0]?.ultimo;
      ultimoSeq = bruto === null || bruto === undefined ? null : Number(bruto);

      const pretendido = ESTADO_PRETENDIDO[envelope.tipo];
      if (pretendido !== undefined) {
        if (maquina === undefined) {
          throw new Error(
            `o tipo ${envelope.tipo} tem estado pretendido e a subscrição exige ordem, ` +
              'mas não foi dada máquina de estados: sem ela não se verifica a pré-condição',
          );
        }
        const estado = await maquina.estadoDe(agregado.tipo, agregado.id);
        if (estado === null) {
          // O agregado ainda não existe para este consumidor. Não é inválido:
          // é cedo. `null` nunca é «pode».
          throw new Adiar(
            ADIAMENTO_POR_OMISSAO,
            `${agregado.tipo} ${agregado.id} ainda não existe neste consumidor`,
          );
        }
        if (!podeTransitar(estado, pretendido)) {
          const atrasado = ultimoSeq !== null && agregado.seq < ultimoSeq;
          if (atrasado) {
            throw new ForaDeOrdem(
              `seq ${agregado.seq} < ${ultimoSeq} e ${estado} -> ${pretendido} ` +
                'não é transição válida',
            );
          }
          throw new Adiar(
            ADIAMENTO_POR_OMISSAO,
            `${estado} -> ${pretendido} ainda não é válido`,
          );
        }
      }
    }

    await efeito(bd);
    await bd.query('COMMIT');
    metricas?.contar(METRICA_CONSUMIDOS, 'aplicado');
    return { desfecho: 'aplicado', ultimoSeq };
  } catch (erro) {
    // `ROLLBACK` sempre, e só depois se propaga: sem ele a ligação fica numa
    // transacção abortada e o trabalho seguinte falha com um erro que não é o
    // dele. O `catch` vazio é deliberado — se o próprio `ROLLBACK` falhar, o
    // erro que interessa é o de cima.
    try {
      await bd.query('ROLLBACK');
    } catch {
      /* a ligação já morreu; o erro de cima é o que explica */
    }
    if (erro instanceof Adiar) metricas?.contar(METRICA_RETENTATIVAS, 'adiado');
    throw erro;
  }
}
