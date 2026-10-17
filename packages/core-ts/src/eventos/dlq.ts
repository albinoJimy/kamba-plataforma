/**
 * A fila de mortos (KAM-006, `docs/tecnica/06` §6.4).
 *
 * Uma entrada na DLQ não é um erro técnico: é **um efeito de negócio que
 * ninguém aplicou**. Um `payment.*` ou um `order.paid` ali é cliente que pagou
 * sem confirmação — Sev1, e é por isso que a severidade se decide pelo tipo e
 * não pela contagem.
 *
 * O que vive aqui:
 *
 * - `paraDlq()` — abre a entrada, uma vez por `(consumer, event_id)`;
 * - `severidade()` — Sev1 pelo tipo, ou Sev2 pela idade (> 1 h aberta);
 * - `abertas()` — o que a métrica `evt_dlq_open{tipo}` expõe;
 * - `fechar()` — marca `reprocessada` ou `descartada`, com quem o fez.
 *
 * **O que não vive aqui:** a decisão de descartar. Descartar um `payment.*`
 * exige duas pessoas (§6.4), e isso é um acto de operação com registo próprio
 * (`evt_dlq_aprovacoes`) — está na ferramenta de linha de comando, onde há um
 * ser humano a escrever o seu nome, e não numa função que um processo possa
 * chamar sozinho.
 */

import {
  SQL_APROVADORES,
  SQL_DEFINIR_TENANT,
  SQL_DLQ_ABERTAS,
  SQL_DLQ_POR_ID,
  SQL_FECHAR_DLQ,
  SQL_PARA_DLQ,
} from './consultas_consumo.ts';
import type { Envelope } from './envelope.ts';
import { METRICA_DLQ_ABERTAS, type Metricas } from './metricas.ts';

import type { ClienteSql } from './publicador.ts';

/**
 * Os tipos cuja entrada na DLQ é **Sev1**, e a razão de cada um.
 *
 * `payment.*` por prefixo: a família inteira move dinheiro. `order.paid` por
 * nome, porque é o evento que diz que o dinheiro chegou — sem ele, a encomenda
 * paga fica parada e o cliente espera por algo que já pagou.
 */
export const PREFIXOS_SEV1 = ['payment.'] as const;
export const TIPOS_SEV1 = ['order.paid'] as const;

/** Quanto tempo uma entrada que não é Sev1 pode ficar aberta sem alerta (§6.4). */
export const HORAS_ATE_ALERTAR = 1;

/**
 * O `tipo` de uma entrada aberta sem envelope.
 *
 * Casa a gramática `familia.verbo` que a etiqueta de `evt_dlq_open` exige, e
 * **não** é um tipo de evento do catálogo: é um sinal de que o arquivo não
 * respondeu por um `event_id` que a fila trouxe. Ver `paraDlqSemEnvelope`.
 */
export const TIPO_ILEGIVEL = 'evt.ilegivel';

/** A `versao` de uma entrada sem envelope: não se sabe, e zero não é versão. */
export const VERSAO_ILEGIVEL = 0;

export type Severidade = 'sev1' | 'sev2' | 'nenhuma';

export interface EntradaDaDlq {
  readonly id: string;
  readonly consumer: string;
  readonly event_id: string;
  readonly tipo: string;
  readonly versao: number;
  readonly tenant_id: string;
  readonly envelope: unknown;
  readonly erro: string;
  readonly tentativas: number;
  readonly estado: string;
  readonly criado_at: Date | string;
}

export interface AberturaPorTipo {
  readonly tipo: string;
  readonly quantas: number;
  readonly maisAntiga: Date;
}

/** O tipo move dinheiro? É pergunta de uma linha, e aparece em três sítios. */
export function eSev1(tipo: string): boolean {
  return (
    PREFIXOS_SEV1.some((prefixo) => tipo.startsWith(prefixo)) ||
    (TIPOS_SEV1 as readonly string[]).includes(tipo)
  );
}

/**
 * A severidade de uma entrada aberta.
 *
 * Sev1 pelo tipo, **sem olhar à idade**: um `payment.confirmed` na DLQ há dez
 * segundos já é um cliente a olhar para o telefone. As restantes só alertam
 * depois de uma hora aberta — antes disso, é ruído de um consumidor a recuar.
 */
export function severidade(tipo: string, idadeEmHoras: number): Severidade {
  if (eSev1(tipo)) return 'sev1';
  return idadeEmHoras >= HORAS_ATE_ALERTAR ? 'sev2' : 'nenhuma';
}

export interface OpcoesDaDlq {
  readonly bd: ClienteSql;
  readonly consumer: string;
  readonly envelope: Envelope;
  readonly erro: string;
  readonly tentativas: number;
}

export interface ResultadoDaDlq {
  /**
   * Ficou uma entrada **aberta** por causa desta chamada?
   *
   * `false` quando já havia uma aberta para este `(consumer, event_id)` — e
   * **não** quando havia uma fechada: essa reabre-se, e aí isto é `true`.
   */
  readonly abriu: boolean;
  readonly severidade: Severidade;
}

/**
 * Abre uma entrada na DLQ, ou não faz nada se já estiver aberta.
 *
 * Fora de qualquer transacção de efeito: a transacção do consumo já fez
 * `ROLLBACK` quando se chega aqui. Se esta escrita falhar, o evento fica na
 * fila e volta — é melhor voltar do que desaparecer.
 *
 * **Abre a sua própria transacção**, e é por causa da RLS: `events_dlq` tem
 * `FORCE` e a política `tenant_iso`, quem escreve aqui é `kamba_app`
 * (`NOBYPASSRLS`), e a transacção do consumo — onde o contexto estava — já foi
 * revertida. Sem o `SET LOCAL` próprio, a entrada não passa o `WITH CHECK` e o
 * evento que falhou seis vezes desaparecia sem deixar linha.
 */
export async function paraDlq(opcoes: OpcoesDaDlq): Promise<ResultadoDaDlq> {
  const { bd, consumer, envelope, erro, tentativas } = opcoes;
  // A métrica **não** se actualiza aqui, e são duas razões. A primeira é de
  // privilégio: `evt_dlq_open` lê a tabela, e quem consome não tem `SELECT`
  // nela (o `id` é sequencial e não pode ser lido por um papel com RLS). A
  // segunda é de desenho: é um *gauge* da realidade e não um contador de
  // chamadas, pelo que quem o publica é o processo, pela ligação de operação,
  // com `publicarAbertas` — e não quem acabou de falhar um evento.
  return escreverNaDlq(bd, envelope.tenant_id, [
    consumer,
    envelope.id,
    envelope.tipo,
    envelope.versao,
    envelope.tenant_id,
    JSON.stringify(envelope),
    erro,
    tentativas,
  ]);
}

export interface OpcoesDaDlqSemEnvelope {
  readonly bd: ClienteSql;
  readonly consumer: string;
  readonly eventId: string;
  readonly tenantId: string;
  readonly erro: string;
  readonly tentativas: number;
}

/**
 * Abre uma entrada para um evento cujo **envelope não se conseguiu ler**.
 *
 * Existe porque sem ela esse evento desaparecia em silêncio: a leitura do
 * arquivo corre antes do `processar()`, e um erro ali nunca chegava ao
 * `paraDlq()`. O *job* esgotava as seis tentativas e ficava em `failed` no
 * Redis — sem linha na DLQ, sem métrica, sem alerta — e, como não há linha em
 * `events_consumed` nem em `events_dlq`, o reconciliador voltava a
 * enfileirá-lo de cinco em cinco minutos durante as 24 h da janela. Um ciclo
 * silencioso, que é a pior forma de perder um evento.
 *
 * O que fica guardado no `envelope` é o que se sabe: o `event_id`, o
 * `consumer` e o motivo. Não é um envelope — e é por isso que o `tipo` é
 * `evt.ilegivel` e a `versao` é 0, para que ninguém o confunda com um evento
 * reprocessável sem olhar.
 */
export async function paraDlqSemEnvelope(
  opcoes: OpcoesDaDlqSemEnvelope,
): Promise<ResultadoDaDlq> {
  const { bd, consumer, eventId, tenantId, erro, tentativas } = opcoes;
  const substituto = {
    id: eventId,
    consumer,
    motivo: erro,
    aviso: 'o arquivo não respondeu por este event_id: isto não é um envelope',
  };
  return escreverNaDlq(bd, tenantId, [
    consumer,
    eventId,
    TIPO_ILEGIVEL,
    VERSAO_ILEGIVEL,
    tenantId,
    JSON.stringify(substituto),
    erro,
    tentativas,
  ]);
}

/**
 * O `INSERT` na DLQ, na sua transacção e com o contexto posto.
 *
 * Um sítio só para as duas entradas (com e sem envelope): são os mesmos oito
 * parâmetros, a mesma política de RLS e o mesmo `ROLLBACK`, e duas cópias
 * divergiam na que se esquecesse de uma delas.
 */
async function escreverNaDlq(
  bd: ClienteSql,
  tenantId: string,
  parametros: readonly unknown[],
): Promise<ResultadoDaDlq> {
  const tipo = String(parametros[2]);
  let rowCount: number | null = 0;
  await bd.query('BEGIN');
  try {
    await bd.query(SQL_DEFINIR_TENANT, [tenantId, true]);
    ({ rowCount } = await bd.query(SQL_PARA_DLQ, parametros));
    await bd.query('COMMIT');
  } catch (falha) {
    try {
      await bd.query('ROLLBACK');
    } catch {
      /* a ligação já morreu; o erro de cima é o que explica */
    }
    throw falha;
  }
  return { abriu: (rowCount ?? 0) > 0, severidade: severidade(tipo, 0) };
}

/** As entradas abertas, agrupadas por tipo. */
export async function abertas(bd: ClienteSql): Promise<AberturaPorTipo[]> {
  const { rows } = await bd.query(SQL_DLQ_ABERTAS);
  return rows.map((linha) => ({
    tipo: String(linha.tipo),
    quantas: Number(linha.quantas),
    maisAntiga: new Date(String(linha.mais_antiga)),
  }));
}

/**
 * Põe `evt_dlq_open{tipo}` igual ao que a tabela diz.
 *
 * Repõe as séries antes de escrever: sem isso, um tipo que **deixou** de ter
 * entradas abertas ficava com o último valor para sempre — um alerta que nunca
 * se desliga é um alerta que se ignora.
 */
export async function publicarAbertas(bd: ClienteSql, metricas: Metricas): Promise<void> {
  const linhas = await abertas(bd);
  metricas.reporTipos(METRICA_DLQ_ABERTAS);
  for (const linha of linhas) {
    metricas.medirPorTipo(METRICA_DLQ_ABERTAS, linha.tipo, linha.quantas);
  }
}

/** Uma entrada pelo seu `id`, ou `null`. */
export async function porId(bd: ClienteSql, id: string | number): Promise<EntradaDaDlq | null> {
  const { rows } = await bd.query(SQL_DLQ_POR_ID, [id]);
  return rows.length === 0 ? null : (rows[0] as unknown as EntradaDaDlq);
}

/** Quem já aprovou o descarte desta entrada. */
export async function aprovadores(bd: ClienteSql, id: string | number): Promise<string[]> {
  const { rows } = await bd.query(SQL_APROVADORES, [id]);
  return rows.map((linha) => String(linha.aprovador));
}

export type Fecho = 'reprocessada' | 'descartada';

/**
 * Fecha uma entrada aberta. Devolve `false` se já estava fechada.
 *
 * O `false` **não** é sucesso: reprocessar duas vezes uma entrada já
 * reprocessada aplicaria o efeito outra vez se a janela de deduplicação já
 * tivesse expirado (são 90 dias; a DLQ guarda 30 **depois** de resolvida). Quem
 * chama tem de distinguir, e é por isso que isto devolve um booleano em vez de
 * não dizer nada.
 */
export async function fechar(
  bd: ClienteSql,
  id: string | number,
  fecho: Fecho,
  por: string,
): Promise<boolean> {
  const { rowCount } = await bd.query(SQL_FECHAR_DLQ, [id, fecho, por]);
  return (rowCount ?? 0) > 0;
}
