/**
 * As métricas do HND (KAM-019).
 *
 *     hnd_handoff_total            counter  passagens, por desfecho
 *     hnd_callback_rejeitado_total counter  callbacks recusados, por motivo
 *     hnd_mirror_pendentes         gauge    mensagens a espelhar em fila
 *
 * A forma é a do `outbound/metricas.ts`, que é a do `chr/metricas.ts` — um
 * `Map` de números, em memória, sem dependências, com `exposicao()` no formato
 * do Prometheus. Um módulo por domínio, pelo precedente que o KAM-009 abriu.
 *
 * ## São três, e o critério nomeia uma
 *
 * A **`hnd_callback_rejeitado_total`** é a que o critério 5 pede por extenso
 * («devolve 401 e incrementa uma métrica»). As outras duas estão aqui por
 * razões que o ticket implica sem nomear:
 *
 * A **`hnd_handoff_total{desfecho}`** é o que torna o SLA de retoma observável.
 * O `docs/tecnica/02` §11 fixa «SLA < 15 min por tenant» e sem contagem por
 * desfecho não se distingue um dia em que ninguém pediu ajuda de um dia em que
 * todas as passagens expiraram — que é a diferença entre um negócio calmo e um
 * atendimento abandonado.
 *
 * A **`hnd_mirror_pendentes`** é *gauge* e é o que o «healthcheck alerta» do
 * critério 9 lê. Com o provedor em baixo, o espelho acumula: esta é a única
 * grandeza que distingue «ninguém falou» de «ninguém conseguiu espelhar». É
 * *gauge* e não contador porque o que interessa é a profundidade **agora**, não
 * quantas passaram.
 *
 * ## Nenhuma leva `tenant_id`
 *
 * Pela razão que o §3.14 já escreveu e a emenda 1.22 repete: as bibliotecas de
 * métricas deste repositório recusam **por gramática** uma etiqueta que não
 * case `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID com hífenes — a
 * chamada **levanta**. O `OBS-I` de `../../../../docs/seguranca/ameacas_stride.md`
 * proíbe-a por outra razão (cardinalidade e re-identificação). O por-*tenant*
 * sai do `SQL_FORA_DO_SLA`, por consulta.
 */

import { ESTADOS } from "./contrato.ts";
import { MOTIVOS_DE_RECUSA } from "./assinatura.ts";

export const METRICA_HANDOFFS = "hnd_handoff_total";
export const METRICA_RECUSAS = "hnd_callback_rejeitado_total";
export const METRICA_PENDENTES = "hnd_mirror_pendentes";

export const CONTADORES = [METRICA_HANDOFFS, METRICA_RECUSAS] as const;
export const GAUGES = [METRICA_PENDENTES] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;
const NOMES_DE_GAUGE: readonly string[] = GAUGES;

/**
 * As etiquetas, por métrica, com a lista fechada de valores.
 *
 * **Nenhuma cresce com o tráfego**: o `desfecho` tem cinco valores e o `motivo`
 * tem quatro. Nenhuma leva `tenant_id`, `contact_id`, `conversation_id`,
 * `handoff_id` nem `external_id`.
 */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_HANDOFFS]: { nome: "desfecho", valores: ESTADOS },
  [METRICA_RECUSAS]: { nome: "motivo", valores: MOTIVOS_DE_RECUSA },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_HANDOFFS]: [
    "counter",
    "Passagens a humano, por desfecho (os cinco estados de handoffs.status). Sem contagem por desfecho nao se distingue um dia calmo de um atendimento abandonado.",
  ],
  [METRICA_RECUSAS]: [
    "counter",
    "Callbacks do provedor recusados com 401, por motivo. Lista fechada de quatro: sem_secret, secret_errado, tipo_desconhecido, conta_desconhecida.",
  ],
  [METRICA_PENDENTES]: [
    "gauge",
    "Mensagens a espelhar que estao em fila. Com o provedor em baixo o espelho acumula, e e a unica grandeza que distingue «ninguem falou» de «ninguem conseguiu espelhar». -1 antes da primeira medicao.",
  ],
};

/** Uma métrica que não existe. */
export class MetricaDesconhecidaError extends Error {
  constructor(metrica: string) {
    super(`metrica desconhecida: ${JSON.stringify(metrica)}`);
    this.name = "MetricaDesconhecidaError";
  }
}

/** Um sufixo que não está na lista fechada da sua métrica. */
export class SufixoInvalidoError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(
      `${metrica}: sufixo ${JSON.stringify(sufixo)} nao esta na lista fechada. ` +
        "Identificadores (tenant_id, contact_id, conversation_id, handoff_id, " +
        "external_id) nao entram em metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores e *gauges* do HND, em memória. Só números. */
export class MetricasDoHnd {
  readonly #contadores = new Map<string, number>();
  readonly #gauges = new Map<string, number>();

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

  ler(): Record<string, number> {
    return {
      ...Object.fromEntries(this.#contadores),
      ...Object.fromEntries(this.#gauges),
    };
  }

  repor(): void {
    this.#contadores.clear();
    this.#gauges.clear();
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * As três aparecem sempre, os contadores a zero e o *gauge* a `-1` quando
   * nunca foi medido. A razão é a do `entrada/metricas.ts`: um painel que
   * mostre «sem dados» não distingue «nenhuma passagem» de «o processo não
   * arrancou».
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
      const etiqueta = ETIQUETAS[nome]?.nome ?? "motivo";
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

/** As métricas do HND. */
export const METRICAS_DO_HND = new MetricasDoHnd();
