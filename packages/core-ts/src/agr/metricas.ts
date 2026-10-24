/**
 * As métricas do *shim* da fila do AGR (KAM-025).
 *
 *     agr_shim_total{outcome}   counter  jobs tratados, por desfecho do AGR
 *     agr_shim_failed_total     counter  jobs que lançaram e voltaram à fila
 *
 * A forma é a do `chr/metricas.ts`, que é a do `entrada/metricas.ts`: um `Map`
 * de números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus. Um módulo por domínio e não um registo central, pelo precedente
 * que o KAM-009 abriu.
 *
 * ## São duas, e nenhuma é a do turno
 *
 * A latência do turno, a profundidade da fila de admissão e os turnos por
 * desfecho vivem no **AGR**, em `services/agr/src/kamba_agr/metricas.py`, que é
 * quem os mede. Repeti-los aqui dava duas séries com o mesmo nome a contar a
 * mesma coisa de dois sítios, a somar mal num painel.
 *
 * O que só este lado vê é **o que aconteceu ao *job***, e é a diferença que
 * importa: um `agr_shim_total{outcome="executado"}` muito abaixo de
 * `agr_turns_total{outcome="executado"}` significa que o AGR corre turnos que
 * o *shim* não sabe que correram — isto é, que o `lockDuration` está curto e há
 * *jobs* duplicados. Sem esta métrica, esse defeito não tem onde aparecer.
 *
 * ## A profundidade da fila `agr-inbound` **não** está aqui
 *
 * Seria `queue.getJobCounts()`, que é uma ida ao Redis por amostra. Um *gauge*
 * que só se preenche com uma sondagem periódica que ninguém escreveu ficava a
 * `-1` permanente — e um `-1` ao lado de valores reais é a armadilha que a
 * revisão adversarial do KAM-013 já apanhou no `inbound_queue_depth`. Nasce com
 * quem puser a sondagem (KAM-080, agregação contínua).
 *
 * ## Etiquetas: uma, e de lista fechada
 *
 * O `outcome` são os oito desfechos de `contrato.ts` mais `desconhecido`, e não
 * cresce com o tráfego. **Nenhuma métrica leva `tenant_id`, `wamid` nem
 * `thread_id`** (`docs/seguranca/ameacas_stride.md`, OBS-I) — e no caso do
 * `wamid` é mais do que cardinalidade: ele carrega o número do interlocutor
 * codificado em base64 (INDÍCIO, `docs/logs.md` §2.1).
 */

import { DESFECHOS_DO_AGR } from "./contrato.ts";

export const METRICA_JOBS = "agr_shim_total";
export const METRICA_FALHAS = "agr_shim_failed_total";

/** Os contadores, pela ordem em que saem. Lista fechada. */
export const CONTADORES = [METRICA_JOBS, METRICA_FALHAS] as const;

/** Os valores do `outcome`: os oito do AGR mais o que não é nenhum deles. */
export const DESFECHOS: readonly string[] = [...DESFECHOS_DO_AGR, "desconhecido"];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_JOBS]: [
    "counter",
    "Jobs da agr-inbound tratados pelo shim, por desfecho do AGR.",
  ],
  [METRICA_FALHAS]: [
    "counter",
    "Jobs que lancaram e voltaram a fila. Qualquer valor sustentado e alerta.",
  ],
};

/** Um nome que não está na lista fechada. */
export class MetricaDesconhecidaError extends Error {
  constructor(metrica: string) {
    super(
      `${JSON.stringify(metrica)} nao e uma metrica do shim do AGR. ` +
        `Contadores: ${CONTADORES.join(", ")}.`,
    );
    this.name = "MetricaDesconhecidaError";
  }
}

/** Um sufixo que não está na lista fechada da sua métrica. */
export class SufixoInvalidoError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(
      `${metrica}: sufixo ${JSON.stringify(sufixo)} nao esta na lista fechada. ` +
        "Identificadores (tenant_id, wamid, thread_id) nao entram em metricas " +
        "(docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores do *shim*, em memória. Só números. */
export class MetricasDoShim {
  readonly #contadores = new Map<string, number>();

  contar(metrica: string, sufixo?: string, quanto = 1): void {
    if (!(CONTADORES as readonly string[]).includes(metrica)) {
      throw new MetricaDesconhecidaError(metrica);
    }
    if (sufixo !== undefined) {
      if (metrica !== METRICA_JOBS || !DESFECHOS.includes(sufixo)) {
        throw new SufixoInvalidoError(metrica, sufixo);
      }
    }
    const nome = sufixo === undefined ? metrica : `${metrica}:${sufixo}`;
    this.#contadores.set(nome, (this.#contadores.get(nome) ?? 0) + quanto);
  }

  ler(): Readonly<Record<string, number>> {
    return Object.fromEntries(this.#contadores);
  }

  repor(): void {
    this.#contadores.clear();
  }

  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of CONTADORES) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      const series = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (series.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      for (const chave of series) {
        const sufixo = chave.slice(nome.length + 1);
        const valor = this.#contadores.get(chave) ?? 0;
        linhas.push(
          sufixo === "" ? `${nome} ${valor}` : `${nome}{outcome="${sufixo}"} ${valor}`,
        );
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As métricas do *shim*. */
export const METRICAS_DO_SHIM = new MetricasDoShim();
