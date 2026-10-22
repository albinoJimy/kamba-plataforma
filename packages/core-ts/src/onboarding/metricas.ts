/**
 * As métricas do onboarding de canal (KAM-016).
 *
 *     es_onboardings_7d              gauge    clientes novos na janela de 7 dias
 *     es_onboarding_fase             gauge    tentativas por fase
 *     es_onboarding_compensado_total counter  compensações corridas, por recurso
 *     es_onboarding_recusado_total   counter  recusas, por motivo
 *
 * A primeira é a que o critério 8 nomeia — «o contador `es_onboardings_7d` está
 * exposto para o limite de 10 clientes/7 dias». As outras três estão aqui pela
 * razão que a `outbound_rate_limited_total` da emenda 1.21, a
 * `meta_free_tier_alert_total` da 1.25 e a `channel_quality_event_total` da 1.27
 * escreveram: **compensar sem contar é compensar em silêncio.** Uma saga que
 * reverte tudo correctamente e uma saga que nunca chega ao passo 4 produzem o
 * mesmo número de canais activos — zero — e um painel que só veja canais não
 * distingue as duas.
 *
 * A forma é a do `qualidade/metricas.ts` e a do `metering/metricas.ts`: um `Map`
 * de números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus. Um módulo por domínio, pelo precedente que o KAM-009 abriu.
 *
 * ## `es_onboardings_7d` é um *gauge* e **não** leva `_total`
 *
 * O nome vem do critério, e felizmente está certo: a contagem de uma **janela
 * móvel** desce quando uma tentativa sai dela pelo lado antigo. Um `_total` que
 * desce é um contador que mente, e a convenção do Prometheus é exactamente essa.
 *
 * O valor vem da base (`SQL_CONTAR_JANELA`) e não de um contador em memória, e
 * isso não é indiferente: um contador em memória reinicia com o processo e a
 * janela é de sete dias — o número ficava a zero depois de cada
 * reinício e o tecto parecia livre. Este *gauge* é um **espelho** da consulta, e
 * quem o escreve é quem a corre.
 *
 * ## Nenhuma métrica leva etiqueta de tenant, e já se sabe porquê
 *
 * O `OBS-I` de `docs/seguranca/ameacas_stride.md` recusa identificadores em
 * etiquetas, e as quatro bibliotecas de métricas da casa recusam por **gramática**
 * uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$` — um `tenant_id` é um UUID
 * com hífenes e **a chamada levanta**. É a mesma medição que a emenda 1.21 fez
 * para a `meta_cost_usd_total` e a 1.25 para as quatro do *free tier*.
 *
 * Aqui isso nem custa nada, e é a diferença face àqueles dois casos: o
 * `es_onboardings_7d` é, por definição, um número **da plataforma** — o limite de
 * dez clientes por sete dias é da nossa app perante a Meta e não de uma loja.
 * Uma etiqueta de tenant neste *gauge* seria errada mesmo que a gramática a
 * aceitasse.
 *
 * As três etiquetas que existem — `fase`, `recurso`, `motivo` — são domínios
 * **fechados** de nove, quatro e três valores, e nenhum cresce com o tráfego. É
 * por isso que passam onde a de tenant não passa; é a mesma distinção que a
 * `channel_quality{rating}` do KAM-021 fez.
 */

import { FASES, RECURSOS } from "./contrato.ts";

export const METRICA_JANELA = "es_onboardings_7d";
export const METRICA_FASE = "es_onboarding_fase";
export const METRICA_COMPENSADO = "es_onboarding_compensado_total";
export const METRICA_RECUSADO = "es_onboarding_recusado_total";

export const CONTADORES = [METRICA_COMPENSADO, METRICA_RECUSADO] as const;
export const GAUGES = [METRICA_JANELA, METRICA_FASE] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;

/**
 * Os motivos de recusa, para a etiqueta da `es_onboarding_recusado_total`.
 *
 * Três, e são as três recusas que este ticket produz antes de criar recurso
 * nenhum: o critério 1 (`es_nao_e_v4`), o critério 4 (`numero_de_outro_tenant`)
 * e o critério 8 (`limite_7d`). Uma falha **depois** de haver recursos não é uma
 * recusa — é uma compensação, e conta na outra série.
 */
export const MOTIVOS_DE_RECUSA = [
  "es_nao_e_v4",
  "numero_de_outro_tenant",
  "limite_7d",
] as const;
export type MotivoDeRecusa = (typeof MOTIVOS_DE_RECUSA)[number];

/** As etiquetas, por métrica, com a lista fechada de valores. */
const ETIQUETAS: Readonly<Record<string, { nome: string; valores: readonly string[] }>> = {
  [METRICA_FASE]: { nome: "fase", valores: FASES },
  [METRICA_COMPENSADO]: { nome: "recurso", valores: RECURSOS },
  [METRICA_RECUSADO]: { nome: "motivo", valores: MOTIVOS_DE_RECUSA },
};

/** A ajuda de cada série, para o `# HELP` da exposição. */
const AJUDA: Readonly<Record<string, string>> = {
  [METRICA_JANELA]:
    "clientes novos com onboarding iniciado nos ultimos 7 dias (tecto da Meta: 10)",
  [METRICA_FASE]: "tentativas de onboarding por fase",
  [METRICA_COMPENSADO]: "compensacoes de saga corridas, por tipo de recurso desfeito",
  [METRICA_RECUSADO]: "onboardings recusados antes de criar recursos, por motivo",
};

/**
 * O registo.
 *
 * `-1` como «ainda não sei» nos dois *gauges*, pela razão da emenda 1.27 que o
 * `consent_accepted_ratio` do KAM-022 repetiu: «não sei» não é «zero», e um `0`
 * no `es_onboardings_7d` antes da primeira leitura dizia que o tecto está
 * inteiro quando ele pode estar gasto. Quem lê o número tem de poder distinguir
 * «medi e deu zero» de «não medi».
 */
export class Metricas {
  readonly #valores = new Map<string, number>();

  /** Soma `1` a um contador. */
  contar(nome: Contador, etiqueta: string): void {
    this.#verificar(nome, etiqueta);
    const chave = `${nome}{${ETIQUETAS[nome]?.nome}="${etiqueta}"}`;
    this.#valores.set(chave, (this.#valores.get(chave) ?? 0) + 1);
  }

  /** Fixa o valor de um *gauge* sem etiqueta (`es_onboardings_7d`). */
  medir(nome: Gauge, valor: number): void {
    if (nome !== METRICA_JANELA) {
      throw new Error(`${nome} tem etiqueta; use medirPorFase`);
    }
    this.#valores.set(nome, valor);
  }

  /**
   * Fixa quantas tentativas estão em cada fase.
   *
   * Recebe o mapa **inteiro** e reescreve as nove séries, incluindo as que
   * ficam a zero. Uma fase que deixa de ter tentativas tem de passar a zero e
   * não desaparecer: uma série que desaparece fica no último valor em qualquer
   * painel que a tenha visto, e «cinco tentativas em `falhado`» a congelar para
   * sempre é pior do que não ter a métrica.
   */
  medirPorFase(contagens: Readonly<Record<string, number>>): void {
    for (const fase of FASES) {
      this.#valores.set(`${METRICA_FASE}{fase="${fase}"}`, contagens[fase] ?? 0);
    }
  }

  /** O valor de uma série, ou `-1` se nunca foi escrita. Para os testes e para o `/metrics`. */
  valor(chave: string): number {
    return this.#valores.get(chave) ?? -1;
  }

  #verificar(nome: string, etiqueta: string): void {
    const definicao = ETIQUETAS[nome];
    if (definicao === undefined) throw new Error(`${nome} não leva etiqueta`);
    if (!definicao.valores.includes(etiqueta)) {
      throw new Error(
        `${etiqueta} não é um valor de ${definicao.nome} em ${nome} ` +
          `(${definicao.valores.join(", ")})`,
      );
    }
  }

  /**
   * A exposição no formato do Prometheus.
   *
   * As séries sem valor **não** saem: um `es_onboardings_7d -1` exposto era um
   * número negativo num *gauge* que conta clientes, e qualquer regra de alerta
   * que o comparasse com 10 passava. O `-1` é para quem pergunta pelo valor em
   * código (os testes, e quem decide se pode admitir mais um cliente); o
   * `/metrics` cala-se até haver medição, que é o que o Prometheus espera de uma
   * série que ainda não existe.
   */
  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of [...GAUGES, ...CONTADORES]) {
      const series = [...this.#valores.entries()].filter(
        ([chave]) => chave === nome || chave.startsWith(`${nome}{`),
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
