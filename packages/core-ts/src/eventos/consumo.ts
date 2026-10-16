/**
 * O consumidor idempotente (KAM-006, `docs/tecnica/06` §6.3).
 *
 * ## O que faz, e porque é esta a ordem
 *
 *     BEGIN
 *       SET LOCAL app.tenant_id = envelope.tenant_id
 *       n = INSERT events_consumed ON CONFLICT DO NOTHING
 *       se n == 0: COMMIT; duplicado — e não se faz mais nada
 *       se exige_ordem: ler o último seq e o estado do agregado
 *                       → Adiar (pré-condição por chegar)
 *                       → ForaDeOrdem (seq atrasado E transição inválida)
 *       efeito(bd, envelope)  ← na MESMA transacção
 *     COMMIT
 *
 * O `SET LOCAL` é a primeira instrução e não um detalhe de arranque: o
 * consumidor corre como `kamba_app`, que é `NOBYPASSRLS`, e as três tabelas
 * deste ticket têm `FORCE ROW LEVEL SECURITY`. Sem contexto, o `INSERT` não
 * passa o `WITH CHECK` da política `tenant_iso` e **nenhum** evento é
 * consumido. Vem do envelope — que é o arquivo a dizer de quem o evento é — e
 * não da fila, que trouxe um ponteiro.
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
  SQL_DEFINIR_TENANT,
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
 *
 * A `escada` é parâmetro com omissão, e a omissão é a do §6.4. Existe por uma
 * razão de prova: os «Testes Requeridos» do ticket pedem **relógio acelerado**,
 * e com a escada fechada dentro da função a suite de integração esperava
 * 756 s — 1 + 5 + 30 + 120 + 600 — por cada um dos dois testes que esgotam as
 * tentativas. Os **valores** continuam provados aqui e no espelho em Python
 * (`TestEscada`); o que a suite acelerada prova é a **contagem**, que é o que o
 * critério 2 pede. Em produção ninguém passa este argumento.
 */
export function atrasoDaTentativaDoConsumidor(
  tentativas: number,
  escada: readonly number[] = ESCADA_DO_CONSUMIDOR,
): number {
  if (!Number.isInteger(tentativas) || tentativas < 1) {
    throw new RangeError(`tentativas tem de ser um inteiro >= 1: ${tentativas}`);
  }
  if (escada.length === 0) throw new RangeError('a escada não pode estar vazia');
  const indice = Math.min(tentativas, escada.length) - 1;
  // O indice esta sempre dentro da escada (o `min` garante-o), mas o
  // `noUncheckedIndexedAccess` nao sabe isso — e um `!` calava a unica guarda
  // que ha. O `??` com o ultimo degrau diz o mesmo.
  return escada[indice] ?? escada[escada.length - 1] ?? 0;
}

/** A pré-condição ainda não se verifica. Tenta-se outra vez. */
export class Adiar extends Error {
  readonly segundos: number;
  readonly porque: string;

  /**
   * O mesmo atraso em milissegundos, que é a unidade da fila.
   *
   * Existe porque a escada deste módulo está em milissegundos e o `segundos`
   * está em segundos (o §6.3 fala em «Adiar(5 s)»): um `× 1000` esquecido na
   * fronteira transformava 5 s em 5 ms e queimava as seis tentativas num
   * instante. Quem re-enfileira usa isto e não multiplica nada.
   */
  get atrasoMs(): number {
    return this.segundos * 1_000;
  }

  constructor(
    segundos: number = ADIAMENTO_POR_OMISSAO,
    porque = 'pré-condição de estado por verificar',
  ) {
    super(`adiar ${segundos}s: ${porque}`);
    this.name = 'Adiar';
    this.segundos = segundos;
    this.porque = porque;
  }
}

/** O evento vem atrasado e a transição não é válida. Não há tentativa que resolva. */
export class ForaDeOrdem extends Error {
  /** O valor que vai para a coluna `erro` da DLQ, e que o critério 4 exige. */
  static readonly CODIGO = 'fora_de_ordem';

  readonly detalhe: string;

  constructor(detalhe: string) {
    super(`${ForaDeOrdem.CODIGO}: ${detalhe}`);
    this.name = 'ForaDeOrdem';
    this.detalhe = detalhe;
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

/**
 * O `seq` que a base devolveu, ou `null`.
 *
 * O `agregado_seq` é `bigint`, e o condutor devolve-o como cadeia. `Number()`
 * sobre um valor acima de 2^53 arredonda **em silêncio**, e um `seq`
 * arredondado compara-se mal — é a diferença entre adiar e mandar para a DLQ.
 * Acima do inteiro seguro, isto lança: é teórico no Piloto, e um erro alto vale
 * mais do que uma comparação errada. (Achado da revisão do espelho em Python.)
 */
function lerSeq(bruto: unknown): number | null {
  if (bruto === null || bruto === undefined) return null;
  const numero = Number(bruto);
  if (!Number.isSafeInteger(numero)) {
    throw new RangeError(
      `agregado_seq fora do inteiro seguro: ${String(bruto)}. Comparar um seq ` +
        'arredondado decidiria entre adiar e DLQ com um número errado',
    );
  }
  return numero;
}

/**
 * O efeito de negócio. Corre **dentro** da transacção, com o mesmo cliente.
 *
 * Recebe o envelope, e não só a ligação: um efeito precisa do `payload` para
 * saber o que aplicar e do `tenant_id` para escrever uma linha que passe a RLS.
 * Sem ele, o único efeito possível era um que não lesse o evento — o que é
 * aceitável no esqueleto e em nenhuma vertical.
 */
export type Efeito = (bd: ClienteSql, envelope: Envelope) => Promise<void>;

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
    // O contexto de tenant, **dentro** da transacção e tirado do envelope. O
    // consumidor é `kamba_app` e as três tabelas deste ticket têm RLS com
    // `FORCE`: sem isto, o `INSERT` abaixo viola o `WITH CHECK` da política
    // `tenant_iso` e nenhum evento é consumido. Com `is_local`, morre no
    // `COMMIT` — a ligação não fica com o tenant do último evento colado.
    await bd.query(SQL_DEFINIR_TENANT, [envelope.tenant_id, true]);
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

    // A leitura do último `seq` só interessa a quem exige ordem: é ela que
    // distingue «vem atrasado» de «vem cedo».
    let ultimoSeq: number | null = null;
    if (exigeOrdem) {
      const { rows } = await bd.query(SQL_ULTIMO_SEQ, [
        consumer,
        agregado.tipo,
        agregado.id,
        envelope.id,
      ]);
      ultimoSeq = lerSeq(rows[0]?.ultimo);
    }

    // A pré-condição de estado é verificada **fora** do `exigeOrdem`, e isto é
    // uma correcção: na primeira versão vivia dentro, e uma subscrição com
    // `exige_ordem = false` sobre um tipo que causa transição aplicava-a **sem
    // verificação nenhuma**. A restrição do DDL só obriga `exige_ordem` em
    // `payment.%`, pelo que o buraco era alcançável por configuração.
    //
    // A ordem é outra coisa, e continua dependente de `exigeOrdem`: sem o
    // último `seq` não se sabe se o evento vem atrasado, e sem isso a saída é
    // sempre `Adiar` — nunca `fora_de_ordem`.
    const pretendido = ESTADO_PRETENDIDO[envelope.tipo];
    if (pretendido !== undefined) {
      if (maquina === undefined) {
        throw new Error(
          `o tipo ${envelope.tipo} causa a transição para ${pretendido} e não foi dada ` +
            'máquina de estados: sem ela não se verifica a pré-condição, e o ADR-013 ' +
            'manda que o paga só se alcance por evento autenticado',
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

    await efeito(bd, envelope);
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
