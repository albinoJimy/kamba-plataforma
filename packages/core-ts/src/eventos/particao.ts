/**
 * Partições e nomes de fila (KAM-005, `docs/tecnica/06` §6.5).
 *
 * São dezasseis filas por grupo de consumidores, `evt.<consumer>.p<0..15>`, com
 * concorrência 1 por fila. A ordem só vale **dentro** da partição, e a partição
 * é `hash(tenant_id ‖ agregado.id) & 15`.
 *
 * ## Onde vive o *hash*, e porque não aqui
 *
 * O *hash* é calculado **em SQL**, dentro de `platform.evt_emitir`:
 *
 *     v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 15)::smallint
 *
 * e fica guardado em `events_outbox.particao`. Este módulo **lê** essa coluna;
 * não recalcula o *hash*.
 *
 * Reimplementar o `hashtextextended` em TypeScript era possível — é o `lookup3`
 * do Bob Jenkins, na variante de 64 bits — e era um defeito: duas
 * implementações do mesmo *hash* divergem na primeira versão do PostgreSQL que
 * mude o algoritmo, e o sintoma seria eventos do mesmo agregado em duas filas,
 * isto é, **perda de ordem** — silenciosa, e descoberta em produção. Uma só
 * fonte, e é a que escreve a coluna.
 *
 * O que fica por verificar deste lado, e é verificado do outro: que o *hash* é
 * determinista, que dá sempre 0..15 e que o mesmo `(tenant_id, agregado.id)` dá
 * sempre a mesma partição. Está em `db/tests/test_eventos_schema.TestParticao`,
 * contra o PostgreSQL real.
 *
 * O que este módulo garante, e é o que o publicador precisa: que uma partição
 * fora de 0..15 **não** chega a uma fila (falha fechada, em vez de `p16`), e que
 * o nome da fila é sempre o mesmo para o mesmo par.
 */

/** Quantas filas por grupo de consumidores (`docs/tecnica/06` §6.5). */
export const PARTICOES = 16;

/** Prefixo dos nomes de fila. */
export const PREFIXO_DA_FILA = "evt";

/** `consumer` de uma subscrição: minúsculas, `snake_case` ou com `-`. */
const NOME_DE_CONSUMER = /^[a-z][a-z0-9_-]{1,62}$/;

/** Uma partição fora de 0..15, ou um `consumer` que não é um nome. */
export class DestinoInvalidoError extends Error {
  constructor(motivo: string) {
    super(`destino de fila invalido: ${motivo}`);
    this.name = "DestinoInvalidoError";
  }
}

/** A partição, validada. Fora de 0..15 lança — nunca se dobra por módulo. */
export function exigirParticao(particao: number): number {
  if (
    typeof particao !== "number" ||
    !Number.isInteger(particao) ||
    particao < 0 ||
    particao >= PARTICOES
  ) {
    throw new DestinoInvalidoError(
      `particao ${String(particao)} fora de 0..${PARTICOES - 1}`,
    );
  }
  return particao;
}

/**
 * O nome da fila de um consumidor para uma partição: `evt.<consumer>.p<n>`.
 *
 * Não dobra a partição por módulo de propósito: um valor fora do intervalo é um
 * defeito a montante (uma coluna escrita por outra via que não `evt_emitir`), e
 * mandá-lo para `p<n mod 16>` escondia-o e trocava a ordem do agregado.
 */
export function nomeDaFila(consumer: string, particao: number): string {
  if (!NOME_DE_CONSUMER.test(consumer)) {
    throw new DestinoInvalidoError(
      `consumer ${JSON.stringify(consumer)} nao e um nome (minusculas, 2 a 63)`,
    );
  }
  return `${PREFIXO_DA_FILA}.${consumer}.p${exigirParticao(particao)}`;
}

/** Os dezasseis nomes de fila de um consumidor, por ordem de partição. */
export function filasDe(consumer: string): string[] {
  return Array.from({ length: PARTICOES }, (_, p) => nomeDaFila(consumer, p));
}
