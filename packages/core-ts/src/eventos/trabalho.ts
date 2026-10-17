/**
 * A política: o que fazer com o que o consumo devolve (KAM-006, §6.3–§6.4).
 *
 * O `consumir()` tem a transacção e nada mais. Aqui está a decisão — retentar,
 * adiar, ou abrir a DLQ —, e está separada por uma razão de prova: assim
 * testa-se a política inteira **sem fila e sem BullMQ**, com um cliente SQL
 * falso. O que liga isto a uma fila real é o `trabalhador_bullmq.ts`, que é
 * casca.
 *
 * ## As quatro saídas
 *
 *     aplicado    o efeito correu e a transacção fechou
 *     duplicado   já tinha sido processado; não se fez nada
 *     adiado      a pré-condição não se verifica; **relança** para a fila repetir
 *     dlq         não há tentativa que resolva, ou esgotaram-se as seis
 *
 * ## Quem decide que as tentativas acabaram
 *
 * O número da tentativa vem de **fora** (da fila), e não de um contador nosso.
 * Com um contador próprio, duas réplicas do consumidor contavam metade cada uma
 * e o evento ia para a DLQ ao dobro das tentativas — ou, pior, nunca ia. A
 * fila já conta, e é a única que conta bem.
 */

import { Adiar, ForaDeOrdem, TENTATIVAS, consumir } from './consumo.ts';
import type { Efeito, OpcoesDoConsumo } from './consumo.ts';
import { paraDlq } from './dlq.ts';
import { METRICA_RETENTATIVAS, type Metricas } from './metricas.ts';

export type DesfechoDoTrabalho = 'aplicado' | 'duplicado' | 'adiado' | 'dlq';

export interface ResultadoDoTrabalho {
  readonly desfecho: DesfechoDoTrabalho;
  /** Segundos a esperar antes da tentativa seguinte, quando `adiado`. */
  readonly adiamento?: number;
  /** O erro que ficou na DLQ, quando `dlq`. */
  readonly erro?: string;
}

export interface OpcoesDoTrabalho extends OpcoesDoConsumo {
  /** Qual é esta tentativa, a contar de 1. Vem da fila. */
  readonly tentativa: number;
  /** Quantas tentativas no total. Por omissão, as seis do critério 2. */
  readonly tentativasMaximas?: number;
}

/**
 * Processa um evento e decide o que fazer com o resultado.
 *
 * **Não lança** por falha de negócio: devolve o desfecho. Quem lança é o
 * trabalhador da fila, que é quem sabe pedir uma retentativa — e a diferença
 * importa, porque uma excepção que atravessasse esta função perdia a
 * informação de **quantas** tentativas faltam.
 *
 * Lança, isso sim, quando a própria base de dados não responde: aí não há
 * decisão a tomar, e tratar isso como «vai para a DLQ» enchia a DLQ de eventos
 * bons por causa de uma falha de infra-estrutura.
 */
export async function processar(
  opcoes: OpcoesDoTrabalho,
  efeito: Efeito,
): Promise<ResultadoDoTrabalho> {
  const { tentativa, tentativasMaximas = TENTATIVAS, metricas } = opcoes;
  // O `paraDlq` **não** leva métricas: `evt_dlq_open` é um *gauge* que se lê da
  // tabela, e quem o publica é o processo pela ligação de operação (a de
  // consumo tem só `INSERT` na DLQ). Quem acabou de falhar um evento não
  // actualiza painéis.
  const paraDlqBase = {
    bd: opcoes.bd,
    consumer: opcoes.consumer,
    envelope: opcoes.envelope,
  };
  if (!Number.isInteger(tentativa) || tentativa < 1) {
    throw new RangeError(`tentativa tem de ser um inteiro >= 1: ${tentativa}`);
  }
  const ultima = tentativa >= tentativasMaximas;

  try {
    const { desfecho } = await consumir(opcoes, efeito);
    return { desfecho };
  } catch (erro) {
    if (erro instanceof ForaDeOrdem) {
      // Não há tentativa que resolva: um evento atrasado numa transição
      // inválida vai ser sempre inválido. Direito à DLQ, com o código que o
      // critério 4 exige.
      await paraDlq({ ...paraDlqBase, erro: ForaDeOrdem.CODIGO, tentativas: tentativa });
      return { desfecho: 'dlq', erro: ForaDeOrdem.CODIGO };
    }

    if (erro instanceof Adiar) {
      if (!ultima) return { desfecho: 'adiado', adiamento: erro.segundos };
      // Esgotadas as tentativas, uma pré-condição que nunca se verificou é
      // uma entrada na DLQ — e **não** uma transição aplicada à força (§6.3).
      const motivo = `adiado_sem_resolver: ${erro.porque}`;
      await paraDlq({ ...paraDlqBase, erro: motivo, tentativas: tentativa });
      return { desfecho: 'dlq', erro: motivo };
    }

    // Erro técnico. Se ainda há tentativas, conta e relança para a fila
    // repetir; na última, abre a DLQ com a mensagem do erro.
    metricas?.contar(METRICA_RETENTATIVAS, 'erro');
    if (!ultima) throw erro;
    const motivo = erro instanceof Error ? `${erro.name}: ${erro.message}` : String(erro);
    await paraDlq({ ...paraDlqBase, erro: motivo, tentativas: tentativa });
    return { desfecho: 'dlq', erro: motivo };
  }
}
