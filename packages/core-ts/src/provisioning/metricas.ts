/**
 * As métricas da saga de provisioning (KAM-091, critério 9).
 *
 *     saga_first_attempt_total        counter  passagens, por «passou à 1.ª» (sim/nao)
 *     saga_step_duration_ms           gauge    duração da última passagem, por passo
 *     saga_step_failures_total        counter  falhas, por passo
 *     saga_escalada_total             counter  escaladas ao 3.º falhanço, por passo
 *     saga_compensado_total           counter  compensações corridas, por recurso
 *     saga_orfaos                     gauge    órfãos da última reconciliação, por classe
 *
 * O critério 9 pede «`saga_first_attempt_success_ratio`, duração por passo,
 * falhas por passo e órfãos; alvo ≥ 95% à 1.ª tentativa». A razão **não** é
 * uma série própria: é o quociente de duas, e expor um rácio pré-calculado era
 * expor um número que não se pode reagregar — a média de rácios de três
 * instâncias não é o rácio do conjunto. Por isso o que sai é a
 * `saga_first_attempt_total{passou="sim"|"nao"}` e o alvo escreve-se na regra de
 * alerta:
 *
 *     sum(rate(saga_first_attempt_total{passou="sim"}[1d]))
 *       / sum(rate(saga_first_attempt_total[1d])) >= 0.95
 *
 * É a mesma escolha que o `consent_accepted_ratio` do KAM-022 **não** fez e que
 * a emenda 1.27 corrigiu: o nome do critério ficou, a forma da série é a que o
 * Prometheus pode somar.
 *
 * A forma é a dos outros módulos (`onboarding/metricas.ts`,
 * `qualidade/metricas.ts`): um `Map` em memória, sem dependências, com
 * `exposicao()`, e **nenhuma etiqueta de tenant** — o `OBS-I` de
 * `docs/seguranca/ameacas_stride.md` recusa identificadores em etiquetas e a
 * gramática abaixo recusa-os por construção. As etiquetas que existem são
 * domínios **fechados**: oito passos, onze recursos, duas classes de
 * divergência, dois valores de `passou`. Nenhum cresce com o tráfego.
 */

import { CLASSES_DE_DIVERGENCIA, PASSOS, RECURSOS } from "./contrato.ts";

export const METRICA_PRIMEIRA_TENTATIVA = "saga_first_attempt_total";
export const METRICA_DURACAO = "saga_step_duration_ms";
export const METRICA_FALHAS = "saga_step_failures_total";
export const METRICA_ESCALADO = "saga_escalada_total";
export const METRICA_COMPENSADO = "saga_compensado_total";
export const METRICA_ORFAOS = "saga_orfaos";

export const CONTADORES = [
  METRICA_PRIMEIRA_TENTATIVA,
  METRICA_FALHAS,
  METRICA_ESCALADO,
  METRICA_COMPENSADO,
] as const;
export const GAUGES = [METRICA_DURACAO, METRICA_ORFAOS] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;

/** Os dois valores de `passou`. Fechado. */
export const PASSOU = ["sim", "nao"] as const;

/** As etiquetas, por métrica, com a lista fechada de valores. */
const ETIQUETAS: Readonly<Record<string, { nome: string; valores: readonly string[] }>> = {
  [METRICA_PRIMEIRA_TENTATIVA]: { nome: "passou", valores: PASSOU },
  [METRICA_DURACAO]: { nome: "step", valores: PASSOS },
  [METRICA_FALHAS]: { nome: "step", valores: PASSOS },
  [METRICA_ESCALADO]: { nome: "step", valores: PASSOS },
  [METRICA_COMPENSADO]: { nome: "recurso", valores: RECURSOS },
  [METRICA_ORFAOS]: { nome: "classe", valores: CLASSES_DE_DIVERGENCIA },
};

const AJUDA: Readonly<Record<string, string>> = {
  [METRICA_PRIMEIRA_TENTATIVA]:
    "passagens da saga de provisioning, por ter concluido a primeira tentativa (alvo: >= 95% sim)",
  [METRICA_DURACAO]: "duracao da ultima passagem de cada passo da saga, em milissegundos",
  [METRICA_FALHAS]: "falhas de passo da saga de provisioning",
  [METRICA_ESCALADO]: "casos escalados ao terceiro falhanco, por passo",
  [METRICA_COMPENSADO]: "compensacoes corridas, por tipo de recurso desfeito",
  [METRICA_ORFAOS]: "divergencias da ultima reconciliacao nocturna, por classe",
};

/**
 * O registo.
 *
 * `-1` como «ainda não sei» nos *gauges*, pela razão que o
 * `onboarding/metricas.ts` escreveu: «não sei» não é «zero», e um `0` em
 * `saga_orfaos` antes da primeira reconciliação dizia que não há órfãos quando
 * ninguém olhou. O critério de saída do epic pede «0 recursos órfãos em 14
 * reconciliações nocturnas consecutivas» — e uma série que vale 0 por nunca ter
 * corrido satisfazia-o sem medir nada.
 */
export class Metricas {
  readonly #valores = new Map<string, number>();

  contar(nome: Contador, etiqueta: string): void {
    const chave = this.#chave(nome, etiqueta);
    this.#valores.set(chave, (this.#valores.get(chave) ?? 0) + 1);
  }

  medir(nome: Gauge, etiqueta: string, valor: number): void {
    this.#valores.set(this.#chave(nome, etiqueta), valor);
  }

  /**
   * Fixa as duas classes de divergência de uma vez, incluindo as que ficam a
   * zero.
   *
   * Recebe o mapa inteiro pela razão do `medirPorFase` do onboarding: uma
   * classe que deixa de ter divergências tem de passar a zero e **não**
   * desaparecer. Uma série que desaparece fica no último valor em qualquer
   * painel que a tenha visto, e «três órfãos» a congelar para sempre é pior do
   * que não ter a métrica — aqui a dobrar, porque é sobre esta série que o
   * critério de saída do epic conta catorze noites a zero.
   */
  medirDivergencias(contagens: Readonly<Record<string, number>>): void {
    for (const classe of CLASSES_DE_DIVERGENCIA) {
      this.#valores.set(`${METRICA_ORFAOS}{classe="${classe}"}`, contagens[classe] ?? 0);
    }
  }

  /** O valor de uma série, ou `-1` se nunca foi escrita. */
  valor(chave: string): number {
    return this.#valores.get(chave) ?? -1;
  }

  #chave(nome: string, etiqueta: string): string {
    const definicao = ETIQUETAS[nome];
    if (definicao === undefined) throw new Error(`${nome} nao e uma metrica desta biblioteca`);
    if (!definicao.valores.includes(etiqueta)) {
      throw new Error(
        `${etiqueta} nao e um valor de ${definicao.nome} em ${nome} ` +
          `(${definicao.valores.join(", ")})`,
      );
    }
    return `${nome}{${definicao.nome}="${etiqueta}"}`;
  }

  /** A exposição no formato do Prometheus. Séries sem valor não saem. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of [...GAUGES, ...CONTADORES]) {
      const series = [...this.#valores.entries()].filter(([chave]) =>
        chave.startsWith(`${nome}{`),
      );
      if (series.length === 0) continue;
      linhas.push(`# HELP ${nome} ${AJUDA[nome] ?? ""}`);
      linhas.push(`# TYPE ${nome} ${NOMES_DE_CONTADOR.includes(nome) ? "counter" : "gauge"}`);
      for (const [chave, valor] of series.sort(([a], [b]) => (a < b ? -1 : 1))) {
        linhas.push(`${chave} ${valor}`);
      }
    }
    return linhas.length === 0 ? "" : `${linhas.join("\n")}\n`;
  }
}

/** O registo do processo, como nos outros módulos. */
export const METRICAS = new Metricas();
