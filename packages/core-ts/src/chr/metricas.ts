/**
 * As métricas do CHR (KAM-014, DoD «Custo e observabilidade», ADR-018).
 *
 *     chr_resolve_total      counter  resolucoes, por desfecho
 *     chr_unrouted_total     counter  linhas de quarentena escritas pelo CHR
 *     chr_resolve_ms         gauge    duracao da ultima resolucao, em ms
 *     chr_cache_hit_ratio    gauge    acertos / resolucoes, entre 0 e 1
 *
 * A forma é a do `entrada/metricas.ts`, que é a do `ten/metricas.ts` — um `Map`
 * de números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus. Um módulo por domínio e não um registo central, pelo precedente
 * que o KAM-009 abriu.
 *
 * ## São quatro, e o DoD nomeia três
 *
 * A quarta é `chr_resolve_total`, com etiqueta `desfecho`. Está aqui porque é o
 * **único** sítio onde duas recusas ficam visíveis: a do Fluxo B (critério 5,
 * que pede «0 *jobs*, alerta» e **não** uma linha de quarentena) e a da matriz
 * de estados. Sem ela, um painel não distingue «ninguém escreveu» de «foi tudo
 * recusado», e as outras três não o dizem — a de quarentena só conta o que não
 * se conseguiu encaminhar. É a mesma razão do `gwy_shed_total` da emenda 1.19:
 * recusar sem contar é recusar em silêncio. Entra no dicionário §3.13 declarada
 * como acrescento deste ticket e não como uma das três.
 *
 * ## Etiquetas: uma, e de lista fechada
 *
 * O `desfecho` tem cinco valores (`DESFECHOS`) e não cresce com o tráfego.
 * Nenhuma métrica leva `tenant_id`, `phone_number_id`, `channel_id` nem
 * `event_key` (`docs/seguranca/ameacas_stride.md`, OBS-I) — e isso é também a
 * razão por que `chr_resolve_ms` não é por tenant: seria cardinalidade sem
 * tecto e, pior, um painel que diz com quem a plataforma fala.
 *
 * ## O que `chr_resolve_ms` **não** dá
 *
 * Percentis. É um *gauge* com o **último** valor, como o `gwy_enqueue_ms` e
 * pela mesma razão: o formato de exposição tem histogramas e esta biblioteca
 * não os implementa (ADR-018, observabilidade leve no Piloto). O p95 do
 * critério 8 mede-se onde tem significado — na suite de base de dados, sobre
 * uma amostra —, e a agregação contínua é KAM-080.
 */

import { DESFECHOS, MOTIVOS_DO_CHR } from "./contrato.ts";

export const METRICA_RESOLUCOES = "chr_resolve_total";
export const METRICA_EM_QUARENTENA = "chr_unrouted_total";
export const METRICA_DURACAO = "chr_resolve_ms";
export const METRICA_ACERTOS = "chr_cache_hit_ratio";

/** Os contadores, pela ordem em que saem. Lista fechada. */
export const CONTADORES = [METRICA_RESOLUCOES, METRICA_EM_QUARENTENA] as const;
/** Os *gauges*, pela ordem em que saem. Lista fechada. */
export const GAUGES = [METRICA_DURACAO, METRICA_ACERTOS] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_RESOLUCOES]: [
    "counter",
    "Resolucoes de canal, por desfecho. fluxo_b_recusado > 0 e um alerta: ADR-011.",
  ],
  [METRICA_EM_QUARENTENA]: [
    "counter",
    "Linhas de quarentena escritas pelo CHR, por motivo. Qualquer uma e alerta.",
  ],
  [METRICA_DURACAO]: [
    "gauge",
    "Duracao da ultima resolucao em ms. Ultimo valor, nao percentil.",
  ],
  [METRICA_ACERTOS]: [
    "gauge",
    "Acertos da cache sobre o total de resolucoes, entre 0 e 1. -1 se nao houve nenhuma.",
  ],
};

/** Que etiqueta cada contador aceita, e com que valores. Listas fechadas. */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_RESOLUCOES]: { nome: "desfecho", valores: DESFECHOS },
  // A razao da quarentena vive **aqui** e nao no desfecho: sao os dois valores
  // de `unrouted_events.motivo` que o CHR escreve (dicionario §3.12), e
  // reparti-los pelas duas metricas era a mesma informacao em duas series.
  [METRICA_EM_QUARENTENA]: { nome: "motivo", valores: MOTIVOS_DO_CHR },
};

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;
const NOMES_DE_GAUGE: readonly string[] = GAUGES;

/** Um nome que não está numa das duas listas fechadas. */
export class MetricaDesconhecidaError extends Error {
  constructor(metrica: string) {
    super(
      `${JSON.stringify(metrica)} nao e uma metrica do CHR. ` +
        `Contadores: ${CONTADORES.join(", ")}. Gauges: ${GAUGES.join(", ")}.`,
    );
    this.name = "MetricaDesconhecidaError";
  }
}

/** Um sufixo que não está na lista fechada da sua métrica. */
export class SufixoInvalidoError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(
      `${metrica}: sufixo ${JSON.stringify(sufixo)} nao esta na lista fechada. ` +
        "Identificadores (tenant_id, phone_number_id, channel_id, event_key) " +
        "nao entram em metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores e *gauges* do CHR, em memória. Só números. */
export class MetricasDoChr {
  readonly #contadores = new Map<string, number>();
  readonly #gauges = new Map<string, number>();
  #resolucoes = 0;
  #acertos = 0;

  contar(metrica: string, sufixo?: string, quanto = 1): void {
    if (AJUDA[metrica] === undefined || !NOMES_DE_CONTADOR.includes(metrica)) {
      throw new MetricaDesconhecidaError(metrica);
    }
    if (sufixo !== undefined) {
      const permitidos = ETIQUETAS[metrica]?.valores;
      if (permitidos === undefined || !permitidos.includes(sufixo)) {
        throw new SufixoInvalidoError(metrica, sufixo);
      }
    }
    const nome = sufixo === undefined ? metrica : `${metrica}:${sufixo}`;
    this.#contadores.set(nome, (this.#contadores.get(nome) ?? 0) + quanto);
  }

  medir(metrica: Gauge, valor: number): void {
    if (!NOMES_DE_GAUGE.includes(metrica)) throw new MetricaDesconhecidaError(metrica);
    // Um valor que não é finito não substitui o anterior: um `NaN` no formato
    // de exposição faz o Prometheus descartar a recolha **toda**.
    if (!Number.isFinite(valor)) return;
    this.#gauges.set(metrica, valor);
  }

  /**
   * Registra uma resolução: a duração e se veio da *cache*.
   *
   * O rácio calcula-se aqui e não em quem chama, por uma razão que a revisão
   * adversarial do KAM-013 já ensinou sobre o `gwy_enqueue_ms`: um *gauge* que
   * quem chama escreve é um *gauge* que dois sítios escrevem com contas
   * diferentes. Os dois contadores vivem dentro desta classe e o rácio sai
   * deles.
   */
  resolucao(duracaoMs: number, daCache: boolean): void {
    this.#resolucoes += 1;
    if (daCache) this.#acertos += 1;
    this.medir(METRICA_DURACAO, duracaoMs);
    this.medir(METRICA_ACERTOS, this.#acertos / this.#resolucoes);
  }

  ler(): Record<string, number> {
    return {
      ...Object.fromEntries(this.#contadores),
      ...Object.fromEntries(this.#gauges),
    };
  }

  repor(): void {
    this.#contadores.clear();
    this.#gauges.clear();
    this.#resolucoes = 0;
    this.#acertos = 0;
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * As quatro aparecem sempre, os contadores a zero e os *gauges* a `-1`
   * quando nunca foram medidos. A escolha é a do `entrada/metricas.ts` e a
   * razão é a mesma: um painel que mostre «sem dados» não distingue «nenhuma
   * recusa» de «o processo não arrancou». No `chr_cache_hit_ratio`, o `-1` diz
   * «ainda não houve resolução nenhuma» sem se confundir com zero, que para um
   * rácio de acertos é uma resposta legítima e muito diferente.
   */
  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of [...CONTADORES, ...GAUGES]) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      if (NOMES_DE_GAUGE.includes(nome)) {
        linhas.push(`${nome} ${this.#gauges.get(nome) ?? -1}`);
        continue;
      }
      const series = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (series.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = ETIQUETAS[nome]?.nome ?? "desfecho";
      for (const chave of series) {
        const sufixo = chave.slice(nome.length + 1);
        const valor = this.#contadores.get(chave) ?? 0;
        linhas.push(
          sufixo === "" ? `${nome} ${valor}` : `${nome}{${etiqueta}="${sufixo}"} ${valor}`,
        );
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As métricas do CHR. */
export const METRICAS_DO_CHR = new MetricasDoChr();
