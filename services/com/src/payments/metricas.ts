/**
 * O atraso entre o evento de pagamento e o `order.paid` (KAM-055).
 *
 * É a métrica que a DoD do bloco pede («*lag* `payment→order.paid`») e o
 * instrumento do critério 9 («p95 ≤ 5 s em 100 eventos simulados»). A outra
 * metade da observabilidade — a DLQ de `payment.*` — **já existe e já está
 * classificada**: é o *gauge* `evt_dlq_open` do
 * `packages/core-ts/src/eventos/metricas.ts`, publicado pelo `publicarAbertas`
 * a partir da ligação de operação, e o `payment.` está nos `PREFIXOS_SEV1` do
 * `dlq.ts`. Escrever aqui uma segunda contagem da DLQ era uma segunda fonte
 * para um número que já tem uma.
 *
 * ## Sem etiquetas, e isso é regra e não economia
 *
 * O `tenant_id`, o `event_id`, o `agregado_id` e o **`consumer`** não entram em
 * etiqueta nenhuma (`OBS-I` de `docs/seguranca/ameacas_stride.md`, e a nota do
 * `packages/core-ts/src/eventos/metricas.ts`). O que resta deste atraso não tem
 * eixo: é um histograma só. Um eixo por tenant dizia, a quem lê o painel, quem
 * paga e quando.
 *
 * ## O 5 está nos cortes de propósito
 *
 * O critério 9 pergunta «o p95 fica em 5 s?», e um histograma cujo corte mais
 * próximo fosse 3 ou 10 obrigava a interpolar entre dois cestos para responder.
 * É a mesma escolha que o `../../../../packages/core-ts/src/sms/metricas.ts`
 * fez com os 30 s do seu alvo.
 */

/** O nome da métrica. `_seconds` porque a unidade é o segundo. */
export const METRICA_LAG = "com_payment_to_paid_seconds";

/** Os cortes, em segundos. O 5 é o alvo do critério 9. */
export const CORTES_DO_LAG: readonly number[] = [0.5, 1, 2, 5, 10, 30, 60, 300];

/** `[tipo, ajuda]` da métrica, para o formato de exposição. */
export const AJUDA: readonly [string, string] = [
  "histogram",
  "atraso entre o ocorrido_em do evento de pagamento e o order.paid, em segundos",
];

export const TIPO_DE_CONTEUDO = "text/plain; version=0.0.4; charset=utf-8";

/**
 * O histograma do atraso. Uma instância por processo.
 *
 * Classe e não módulo com estado solto para que os ensaios possam ter a sua: um
 * contador global partilhado entre ensaios dava a cada um o resíduo do
 * anterior, e isso é um verde que depende da ordem de execução.
 */
export class Lag {
  readonly #baldes = new Map<number, number>();
  #soma = 0;
  #contagem = 0;

  /**
   * Observa um atraso em segundos.
   *
   * Um valor não finito **não entra** — um `NaN` no formato de exposição faz o
   * Prometheus descartar a recolha toda —, e um negativo também não: um atraso
   * negativo é um relógio ao contrário, não um evento rápido. É a lição que o
   * KAM-017 escreveu e que o `sms/metricas.ts` repete.
   */
  observar(segundos: number): void {
    if (!Number.isFinite(segundos) || segundos < 0) return;
    this.#soma += segundos;
    this.#contagem += 1;
    for (const corte of CORTES_DO_LAG) {
      if (segundos <= corte) {
        this.#baldes.set(corte, (this.#baldes.get(corte) ?? 0) + 1);
      }
    }
  }

  get contagem(): number {
    return this.#contagem;
  }

  /** Quantas observações caíram em `<= corte`. Para os ensaios e para o p95. */
  balde(corte: number): number {
    return this.#baldes.get(corte) ?? 0;
  }

  /**
   * O p95 lido do histograma: o menor corte que cobre 95% das observações.
   *
   * Devolve `null` sem observações, e `null` também quando nem o corte mais
   * alto cobre os 95% — que é «passou de 300 s» e não «está bem». Um número
   * inventado para o caso vazio era pior do que a ausência dele: o critério 9
   * compara-o com 5, e um zero passava.
   */
  p95(): number | null {
    if (this.#contagem === 0) return null;
    const alvo = this.#contagem * 0.95;
    for (const corte of CORTES_DO_LAG) {
      if (this.balde(corte) >= alvo) return corte;
    }
    return null;
  }

  /** O formato de exposição do Prometheus. */
  exposicao(): string {
    const linhas = [
      `# HELP ${METRICA_LAG} ${AJUDA[1]}`,
      `# TYPE ${METRICA_LAG} ${AJUDA[0]}`,
    ];
    for (const corte of CORTES_DO_LAG) {
      linhas.push(`${METRICA_LAG}_bucket{le="${corte}"} ${this.balde(corte)}`);
    }
    linhas.push(`${METRICA_LAG}_bucket{le="+Inf"} ${this.#contagem}`);
    linhas.push(`${METRICA_LAG}_sum ${this.#soma}`);
    linhas.push(`${METRICA_LAG}_count ${this.#contagem}`);
    return `${linhas.join("\n")}\n`;
  }
}

/** A instância do processo. Os ensaios constroem a sua. */
export const LAG = new Lag();
