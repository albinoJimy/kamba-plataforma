/**
 * As métricas do recálculo da confiança gradual (KAM-203, critério 6).
 *
 * ```text
 * confianca_recalculos_total{origem,desfecho}  counter  recálculos de um tenant
 * confianca_mudancas_total{motivo}             counter  níveis escritos, por motivo
 * ```
 *
 * O `motivo` é o de `trust_level.motivo` (`MOTIVOS_DO_NIVEL`), e é ele que diz
 * o sentido: `historico_independente` é a subida, `disputa_aceite`,
 * `sinal_alto` e `sancao` são as descidas, `k1_completo` o nascimento e
 * `recalibracao` a mudança de tecto sem mudança de nível.
 *
 * **Contam depois do `COMMIT`**: o recálculo corre numa transacção por tenant,
 * e quem chama o `recalcular` desta classe só conta quando ela confirmou. Uma
 * mudança desfeita não conta, e a repetição que não escreve (`mudou: false`)
 * conta como `sem_mudanca`.
 *
 * **As etiquetas são domínios fechados** (`origem` 4, `desfecho` 3, `motivo` 6)
 * e nenhuma leva tenant (`OBS-I`): qual tenant mudou lê-se do `audit_log`
 * (`trust.tecto`), por quem tem papel para isso. **Nascem a zero**, pela razão
 * do `../trust/metricas.ts`: uma regra com `increase(...)` vê a primeira
 * ocorrência.
 */

import { MOTIVOS_DO_NIVEL, type MotivoDoNivel } from "./niveis.ts";

export const METRICA_RECALCULOS = "confianca_recalculos_total";
export const METRICA_MUDANCAS = "confianca_mudancas_total";

/**
 * Quem pediu o recálculo. `diario` é a volta do processo de lote, `entrega` o
 * `order.delivered`, `aprovacao` a aprovação do tenant, e `descida` a varredura
 * curta dos tenants acima do nível 0 com uma sanção, um sinal alto ou uma
 * disputa aceite posteriores ao nível.
 */
export const ORIGENS_DO_RECALCULO = ["diario", "entrega", "aprovacao", "descida"] as const;
export type OrigemDoRecalculo = (typeof ORIGENS_DO_RECALCULO)[number];

export const DESFECHOS_DO_RECALCULO = ["mudou", "sem_mudanca", "falhou"] as const;
export type DesfechoDoRecalculo = (typeof DESFECHOS_DO_RECALCULO)[number];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_RECALCULOS]: ["counter", "Recalculos da confianca gradual de um tenant, por origem e desfecho."],
  [METRICA_MUDANCAS]: ["counter", "Niveis de confianca escritos, por motivo."],
};

/** O que o recálculo conta. A `MetricasDaConfianca` cumpre-a. */
export interface ContadoresDaConfianca {
  recalculo(origem: OrigemDoRecalculo, desfecho: DesfechoDoRecalculo): void;
  mudanca(motivo: MotivoDoNivel): void;
}

export class MetricasDaConfianca implements ContadoresDaConfianca {
  readonly #recalculos = new Map<string, number>(
    ORIGENS_DO_RECALCULO.flatMap((o) => DESFECHOS_DO_RECALCULO.map((d) => [`${o}|${d}`, 0] as const)),
  );
  readonly #mudancas = new Map<string, number>(MOTIVOS_DO_NIVEL.map((m) => [m, 0]));

  recalculo(origem: OrigemDoRecalculo, desfecho: DesfechoDoRecalculo): void {
    const k = `${origem}|${desfecho}`;
    // Um valor fora do domínio não abre série nova: a etiqueta é fechada.
    if (!this.#recalculos.has(k)) return;
    this.#recalculos.set(k, (this.#recalculos.get(k) ?? 0) + 1);
  }

  mudanca(motivo: MotivoDoNivel): void {
    if (!this.#mudancas.has(motivo)) return;
    this.#mudancas.set(motivo, (this.#mudancas.get(motivo) ?? 0) + 1);
  }

  /** O formato de exposição do Prometheus. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`, `# TYPE ${nome} ${tipo}`);
      if (nome === METRICA_RECALCULOS) {
        for (const [k, n] of this.#recalculos) {
          const [o, d] = k.split("|");
          linhas.push(`${nome}{origem="${o}",desfecho="${d}"} ${n}`);
        }
      } else {
        for (const [m, n] of this.#mudancas) linhas.push(`${nome}{motivo="${m}"} ${n}`);
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}
