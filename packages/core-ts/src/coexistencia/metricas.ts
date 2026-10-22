/**
 * As métricas da coexistência (KAM-017).
 *
 *     coex_sync_duration_s          histogram  quanto demorou uma sincronizacao
 *     coex_sync_failed_total        counter    sincronizacoes falhadas, por motivo
 *     channel_disconnected_total    counter    canais desligados, por motivo
 *     coex_echo_total               counter    echoes, por desfecho
 *
 * As **três** primeiras são as que o DoD nomeia. A quarta não está no DoD e
 * entra pela razão que a emenda 1.21 escreveu para a `outbound_rate_limited_total`
 * e a 1.29 para a `conv_mode_rejected_total`: o critério 7 manda distinguir o
 * *echo* do dono do *echo* que é nosso, e **separar sem contar é separar em
 * silêncio**. É o único sítio onde o **NÃO VERIFICADO L6** — se um envio por
 * API gera *echo* — fica visível em produção: o dia em que a Meta passar a
 * gerá-los, a série `nosso` começa a subir sozinha.
 *
 * ## Nenhuma leva etiqueta de *tenant* nem de canal
 *
 * Pela regra do OBS-I de `docs/seguranca/ameacas_stride.md`, que o
 * `modos/metricas.ts` cita e o `metering/` do KAM-023 pagou: as bibliotecas da
 * casa recusam por gramática uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`,
 * e **um UUID com hífenes levanta**. Um `coex_sync_failed_total` por canal era
 * também cardinalidade sem tecto.
 *
 * ## A duração é um histograma e não um *gauge*, e isso é o critério 3
 *
 * O que interessa de uma sincronização de 24 h não é a última: é quantas
 * passaram das 12 h. Um *gauge* com a última duração respondia «6 h» num dia em
 * que metade tinha passado das 12 — e os *buckets* estão escolhidos nos dois
 * prazos que o critério nomeia, para que a pergunta «quantas alertaram» e
 * «quantas falharam» se leiam do próprio histograma.
 */

import {
  DESFECHOS_DO_ECHO,
  MOTIVOS_DE_DESLIGAMENTO,
} from "./contrato.ts";

/** Quanto demorou uma sincronização de coexistência, em segundos. */
export const METRICA_DURACAO = "coex_sync_duration_s";
/** Sincronizações que não acabaram dentro do prazo, por motivo. */
export const METRICA_FALHADAS = "coex_sync_failed_total";
/** Canais que passaram a `desligado`, por motivo de `PARTNER_REMOVED`. */
export const METRICA_DESLIGADOS = "channel_disconnected_total";
/** *Echoes* tratados, por desfecho. */
export const METRICA_ECHOES = "coex_echo_total";

export const CONTADORES = [
  METRICA_FALHADAS,
  METRICA_DESLIGADOS,
  METRICA_ECHOES,
] as const;
export type Contador = (typeof CONTADORES)[number];

export const HISTOGRAMAS = [METRICA_DURACAO] as const;
export type Histograma = (typeof HISTOGRAMAS)[number];

/**
 * Porque é que uma sincronização falhou.
 *
 * **Um valor só, e isso é honesto.** O único caminho que escreve `falhado` é o
 * prazo das 24 h a cair (critério 3). O 2593109 **não** é falha — é o
 * `sincronizado_sem_historico` do critério 4 —, e um motivo `sem_historico`
 * nesta lista era contá-lo como avaria. Um segundo valor nasce com o segundo
 * caminho, e não antes: uma lista com valores que nada escreve é uma lista que
 * apodrece, que é o que o `canon/extensoes.yaml` recusa pela mesma razão.
 */
export const MOTIVOS_DE_FALHA = ["prazo_esgotado"] as const;
export type MotivoDeFalha = (typeof MOTIVOS_DE_FALHA)[number];

/**
 * Os cortes do histograma, em segundos.
 *
 * Escolhidos **nos prazos do critério 3** e não numa escada redonda: o 12 h é o
 * alerta e o 24 h é a falha, e com eles como cortes a pergunta «quantas
 * passaram do alerta» lê-se do histograma sem precisar de outra métrica. Os
 * três primeiros (1 min, 15 min, 1 h) são o caso normal — o `E1` §2 manda
 * sincronizar logo —, e sem eles tudo o que corre bem caía no mesmo *bucket*.
 */
export const CORTES_DA_DURACAO: readonly number[] = [
  60,
  15 * 60,
  60 * 60,
  6 * 60 * 60,
  12 * 60 * 60,
  24 * 60 * 60,
];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_DURACAO]: [
    "histogram",
    "Duracao de uma sincronizacao de coexistencia, em segundos. Cortes nos prazos do criterio 3 (12 h e 24 h).",
  ],
  [METRICA_FALHADAS]: [
    "counter",
    "Sincronizacoes de coexistencia que nao acabaram no prazo de 24 h (E1 §2), por motivo. Cada uma e um offboard.",
  ],
  [METRICA_DESLIGADOS]: [
    "counter",
    "Canais que passaram a desligado por PARTNER_REMOVED, pelos seis motivos do E1 §2.",
  ],
  [METRICA_ECHOES]: [
    "counter",
    "Echoes tratados, por desfecho. A serie nosso>0 responde ao NAO VERIFICADO L6; sem_conversa>0 e echo que nao resolveu contacto.",
  ],
};

/** Que etiqueta cada contador aceita, e com que valores. Listas fechadas. */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_FALHADAS]: { nome: "motivo", valores: MOTIVOS_DE_FALHA },
  [METRICA_DESLIGADOS]: { nome: "motivo", valores: MOTIVOS_DE_DESLIGAMENTO },
  [METRICA_ECHOES]: { nome: "desfecho", valores: DESFECHOS_DO_ECHO },
};

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;

/** Um nome que não está na lista fechada. */
export class MetricaDesconhecidaError extends Error {
  constructor(metrica: string) {
    super(
      `${JSON.stringify(metrica)} nao e uma metrica da coexistencia. ` +
        `Contadores: ${CONTADORES.join(", ")}; histogramas: ${HISTOGRAMAS.join(", ")}.`,
    );
    this.name = "MetricaDesconhecidaError";
  }
}

/** Um sufixo que não está na lista fechada da sua métrica. */
export class SufixoInvalidoError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(
      `${metrica}: sufixo ${JSON.stringify(sufixo)} nao esta na lista fechada. ` +
        "Identificadores (tenant_id, channel_id, phone_number_id) nao entram " +
        "em metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores e histograma da coexistência, em memória. Só números. */
export class MetricasDaCoexistencia {
  readonly #contadores = new Map<string, number>();
  readonly #baldes = new Map<number, number>();
  #somaDaDuracao = 0;
  #contagemDaDuracao = 0;

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

  /**
   * Observa a duração de uma sincronização, em segundos.
   *
   * Uma duração negativa **levanta** em vez de entrar: ela só pode vir de um
   * `concluido_em` anterior ao `iniciado_em`, que é relógio ao contrário, e um
   * histograma que a aceitasse dava um `_sum` que não quer dizer nada. É a
   * mesma escolha do guarda do `NaN` que a revisão adversarial do KAM-018
   * encontrou pelo outro lado: uma comparação com `NaN` é sempre falsa, e um
   * `fail-open` de um caracter é o que se paga.
   */
  observarDuracao(segundos: number): void {
    if (!Number.isFinite(segundos) || segundos < 0) {
      throw new RangeError(
        `${METRICA_DURACAO}: duracao invalida (${segundos}). ` +
          "So pode vir de um concluido_em anterior ao iniciado_em.",
      );
    }
    this.#somaDaDuracao += segundos;
    this.#contagemDaDuracao += 1;
    for (const corte of CORTES_DA_DURACAO) {
      if (segundos <= corte) {
        this.#baldes.set(corte, (this.#baldes.get(corte) ?? 0) + 1);
      }
    }
  }

  ler(): Record<string, number> {
    const fora: Record<string, number> = Object.fromEntries(this.#contadores);
    fora[`${METRICA_DURACAO}_count`] = this.#contagemDaDuracao;
    fora[`${METRICA_DURACAO}_sum`] = this.#somaDaDuracao;
    for (const corte of CORTES_DA_DURACAO) {
      fora[`${METRICA_DURACAO}_bucket:${corte}`] = this.#baldes.get(corte) ?? 0;
    }
    return fora;
  }

  repor(): void {
    this.#contadores.clear();
    this.#baldes.clear();
    this.#somaDaDuracao = 0;
    this.#contagemDaDuracao = 0;
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * Todas aparecem sempre, a zero quando nunca foram contadas. A escolha é a do
   * `chr/metricas.ts` e a razão é a mesma: um painel que mostre «sem dados» não
   * distingue «nenhum canal desligado» de «o processo não arrancou».
   */
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
      const etiqueta = ETIQUETAS[nome]?.nome ?? "motivo";
      for (const chave of series) {
        const sufixo = chave.slice(nome.length + 1);
        const valor = this.#contadores.get(chave) ?? 0;
        linhas.push(
          sufixo === "" ? `${nome} ${valor}` : `${nome}{${etiqueta}="${sufixo}"} ${valor}`,
        );
      }
    }
    const duracao = AJUDA[METRICA_DURACAO];
    if (duracao !== undefined) {
      linhas.push(`# HELP ${METRICA_DURACAO} ${duracao[1]}`);
      linhas.push(`# TYPE ${METRICA_DURACAO} ${duracao[0]}`);
      for (const corte of CORTES_DA_DURACAO) {
        linhas.push(
          `${METRICA_DURACAO}_bucket{le="${corte}"} ${this.#baldes.get(corte) ?? 0}`,
        );
      }
      linhas.push(`${METRICA_DURACAO}_bucket{le="+Inf"} ${this.#contagemDaDuracao}`);
      linhas.push(`${METRICA_DURACAO}_sum ${this.#somaDaDuracao}`);
      linhas.push(`${METRICA_DURACAO}_count ${this.#contagemDaDuracao}`);
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As métricas da coexistência. */
export const METRICAS_DA_COEXISTENCIA = new MetricasDaCoexistencia();
