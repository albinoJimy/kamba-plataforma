/**
 * As três métricas do MED (KAM-020, critério 9).
 *
 * `media_bytes_total{classe}`, `media_download_ms` e
 * `media_rejected_total{motivo}` — os nomes são os do bloco do ticket, e entram
 * no dicionário §3.16 com o resto.
 *
 * ## As etiquetas, e o que **não** entra nelas
 *
 * **Nenhuma leva `tenant_id`, `contact_id`, `conversation_id`, `wamid`,
 * `media_id` nem `asset_id`.** A gramática de uma etiqueta é
 * `^[a-z][a-z0-9_]{1,62}$` e um identificador não cabe lá — mas a razão não é a
 * gramática: é a cardinalidade. O `OBS-I` do `docs/seguranca/ameacas_stride.md`
 * proíbe-o, e um contador por *tenant* multiplica as séries pelo número de PMEs.
 *
 * E a `media_bytes_total` leva a **classe** e não o `content_type`: três valores
 * contra uma lista que cresce sempre que a *allowlist* cresce.
 *
 * ## O que a `media_download_ms` **não** dá
 *
 * Percentis. É um *gauge* com o **último** valor, pela mesma razão que o
 * `gwy_enqueue_ms` do `entrada/metricas.ts` escreveu: o formato de exposição do
 * Prometheus tem histogramas e esta biblioteca não os implementa (ADR-018,
 * observabilidade leve no Piloto). O sufixo `_ms` do nome que o ticket fixa
 * convida a ler isto como uma distribuição, e não é — fica dito aqui para
 * ninguém o ler como um p95. A agregação contínua é KAM-080.
 */

import { CLASSES, MOTIVOS_DE_REJEICAO } from "./contrato.ts";

export const METRICA_BYTES = "media_bytes_total";
export const METRICA_DESCARGA_MS = "media_download_ms";
export const METRICA_REJEICOES = "media_rejected_total";

export const CONTADORES = [METRICA_BYTES, METRICA_REJEICOES] as const;
export const GAUGES = [METRICA_DESCARGA_MS] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;
const NOMES_DE_GAUGE: readonly string[] = GAUGES;

/**
 * As etiquetas, e cada uma tem lista **fechada**.
 *
 * Fechada porque é etiqueta: um valor livre aqui é cardinalidade aberta, e é a
 * mesma regra que o HND seguiu para os quatro motivos de recusa.
 */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_BYTES]: { nome: "classe", valores: CLASSES },
  [METRICA_REJEICOES]: { nome: "motivo", valores: MOTIVOS_DE_REJEICAO },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_BYTES]: [
    "counter",
    "Bytes de midia armazenados, por classe (media_audio, media_imagem, media_documento). E o que sustenta o custo de armazenamento por PME; sem a classe nao se distingue um catalogo de fotos de um mes de notas de voz, que tem politicas de retencao opostas.",
  ],
  [METRICA_REJEICOES]: [
    "counter",
    "Objectos recusados pela allowlist, por motivo. Lista fechada de tres: tipo_nao_permitido, tamanho_excedido, classe_desconhecida. Uma subida em tipo_nao_permitido e um sinal de que a allowlist esta apertada demais para o que os clientes mandam.",
  ],
  [METRICA_DESCARGA_MS]: [
    "gauge",
    "Duracao da ultima descarga de midia, em ms. **Nao e um histograma**: e o ultimo valor (ADR-018, observabilidade leve no Piloto). -1 antes da primeira medicao.",
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
        "Identificadores (tenant_id, contact_id, conversation_id, wamid, " +
        "media_id, asset_id) nao entram em metricas " +
        "(docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores e *gauges* do MED, em memória. Só números. */
export class MetricasDoMed {
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

  medir(metrica: string, valor: number): void {
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
   * nunca foi medido: um painel que mostre «sem dados» não distingue «nenhuma
   * mídia» de «o processo não arrancou».
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

/** As métricas do MED. */
export const METRICAS_DO_MED = new MetricasDoMed();
