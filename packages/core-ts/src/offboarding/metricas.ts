/**
 * As métricas do off-boarding (KAM-210, critério 1; DoD: «métricas e alertas
 * nascem com o processo», ADR-018).
 *
 * ```text
 * offboarding_fases{fase,estado}              gauge    linhas da offboarding_run, por fase e estado
 * offboarding_fases_paradas{fase}             gauge    fases paradas: `falhada`, ou por acabar além do prazo e da folga
 * offboarding_execucoes_total{fase,desfecho}  counter  chamadas do ciclo a uma fase, por desfecho
 * ```
 *
 * **As duas primeiras leem-se da base, e cobrem as sete fases** — também as três
 * do lado dos dados (`libs/py-core/src/kamba_core/offboarding/`), que corre outro
 * processo. É de propósito: o alerta de uma fase parada tem de ver a fase onde
 * ela está, e não só as que este processo corre. O ciclo recalcula-as em cada
 * volta, com uma consulta só (`SQL_CONTAGEM_DAS_FASES`).
 *
 * **As etiquetas são domínios fechados** (`fase` 7, `estado` 6, `desfecho` 3), e
 * nenhuma leva tenant (`OBS-I`): qual tenant está parado lê-se da
 * `platform.offboarding_run`, por quem tem papel para isso — o *runbook* diz como.
 *
 * **Nascem a zero**: todas as séries saem desde o arranque, e uma regra com
 * `increase(...)` vê a primeira ocorrência (a lição do cabeçalho do
 * `infra/compose/prometheus/regras/kamba.yml`). Servidas pelo processo de lote do
 * onboarding (`services/onboarding-web/src/lote.ts`).
 */

import { ESTADOS_DA_FASE, FASES, type EstadoDaFase, type Fase } from "./contrato.ts";

export const METRICA_FASES = "offboarding_fases";
export const METRICA_FASES_PARADAS = "offboarding_fases_paradas";
export const METRICA_EXECUCOES = "offboarding_execucoes_total";

/** As fases que o ciclo deste processo corre. As outras três são do lado dos dados. */
export const FASES_DO_CICLO = ["canal", "pendentes", "revogacao"] as const satisfies readonly Fase[];
export type FaseDoCiclo = (typeof FASES_DO_CICLO)[number];

/**
 * O desfecho de uma chamada do ciclo a uma fase. `concluida` é a fase que acabou
 * nesta chamada (ou já estava); `em_curso` é a que correu e ainda espera (os
 * pendentes por fechar); `falhou` é a que levantou — e fica escrita, pelo nome.
 */
export const DESFECHOS_DA_EXECUCAO = ["concluida", "em_curso", "falhou"] as const;
export type DesfechoDaExecucao = (typeof DESFECHOS_DA_EXECUCAO)[number];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_FASES]: ["gauge", "Fases do off-boarding na base, por fase e estado."],
  [METRICA_FASES_PARADAS]: ["gauge", "Fases do off-boarding paradas: falhadas, ou por acabar alem do prazo e da folga."],
  [METRICA_EXECUCOES]: ["counter", "Chamadas do ciclo do off-boarding a uma fase, por desfecho."],
};

/** Uma linha da contagem: quantas fases há neste estado, e quantas delas estão paradas. */
export interface ContagemDaFase {
  readonly fase: Fase;
  readonly estado: EstadoDaFase;
  readonly n: number;
  readonly paradas: number;
}

export class MetricasDoOffboarding {
  readonly #fases = new Map<string, number>(FASES.flatMap((f) => ESTADOS_DA_FASE.map((e) => [`${f}|${e}`, 0] as const)));
  readonly #paradas = new Map<string, number>(FASES.map((f) => [f, 0] as const));
  readonly #execucoes = new Map<string, number>(
    FASES_DO_CICLO.flatMap((f) => DESFECHOS_DA_EXECUCAO.map((d) => [`${f}|${d}`, 0] as const)),
  );

  /**
   * Substitui os dois *gauges* pela contagem lida da base. **Substitui**, e não
   * soma: uma fase que deixou de estar parada volta a zero na volta seguinte. Uma
   * linha fora do domínio não abre série: as etiquetas são fechadas.
   */
  fixar(contagem: readonly ContagemDaFase[]): void {
    for (const k of this.#fases.keys()) this.#fases.set(k, 0);
    for (const k of this.#paradas.keys()) this.#paradas.set(k, 0);
    for (const c of contagem) {
      const k = `${c.fase}|${c.estado}`;
      if (!this.#fases.has(k)) continue;
      this.#fases.set(k, c.n);
      this.#paradas.set(c.fase, (this.#paradas.get(c.fase) ?? 0) + c.paradas);
    }
  }

  execucao(fase: FaseDoCiclo, desfecho: DesfechoDaExecucao): void {
    const k = `${fase}|${desfecho}`;
    if (!this.#execucoes.has(k)) return;
    this.#execucoes.set(k, (this.#execucoes.get(k) ?? 0) + 1);
  }

  /** O formato de exposição do Prometheus. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`, `# TYPE ${nome} ${tipo}`);
      if (nome === METRICA_FASES) {
        for (const [k, n] of this.#fases) {
          const [f, e] = k.split("|");
          linhas.push(`${nome}{fase="${f}",estado="${e}"} ${n}`);
        }
      } else if (nome === METRICA_FASES_PARADAS) {
        for (const [f, n] of this.#paradas) linhas.push(`${nome}{fase="${f}"} ${n}`);
      } else {
        for (const [k, n] of this.#execucoes) {
          const [f, d] = k.split("|");
          linhas.push(`${nome}{fase="${f}",desfecho="${d}"} ${n}`);
        }
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}
