/**
 * As métricas da qualidade do canal (KAM-021, DoD «Custo e observabilidade»).
 *
 *     channel_quality                gauge    canais na pior qualidade vista, por rating
 *     messaging_limit_usage_ratio    gauge    fraccao do escalao, no canal MAIS PERTO
 *     channel_restricted_total       counter  transicoes para restrito, por motivo
 *     channel_quality_event_total    counter  webhooks de canal tratados, por evento
 *
 * As três primeiras são as que o DoD nomeia. A quarta está aqui pela razão que a
 * `outbound_rate_limited_total` da emenda 1.21 e a `meta_free_tier_alert_total`
 * da 1.24 escreveram: **tratar sem contar é tratar em silêncio.** São quatro
 * tipos de *webhook* que caem no mesmo destino, e sem a etiqueta `evento` um
 * painel não distingue «a Meta não mandou nada» de «mandámos tudo para o braço
 * errado» — que é exactamente a diferença entre uma conta calma e um defeito de
 * encaminhamento.
 *
 * A forma é a do `metering/metricas.ts` e a do `outbound/metricas.ts`: um `Map`
 * de números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus. Um módulo por domínio, pelo precedente que o KAM-009 abriu.
 *
 * ## `channel_quality` é um *gauge* com etiqueta, e isso precisa de explicação
 *
 * O DoD escreve `channel_quality{rating}`. A etiqueta **não** é um
 * identificador: `rating` tem três valores (`green`, `yellow`, `red`), fechados,
 * e nenhum cresce com o tráfego. É por isso que ela passa onde a `{tenant}` do
 * KAM-015 e do KAM-023 não passava — o `OBS-I` de
 * `docs/seguranca/ameacas_stride.md` recusa identificadores, não dimensões
 * pequenas.
 *
 * O que ela conta é **quantos canais estão em cada qualidade**, e por isso é um
 * *gauge* por série e não um contador: um canal que vai de `yellow` para `green`
 * tem de sair de uma série e entrar na outra. Guarda-se o estado por canal num
 * mapa interno — que **nunca sai do processo**, não é etiqueta e não cria séries
 * —, pela mesma distinção que o `metering/metricas.ts` fez: saber por canal é
 * legítimo, publicar por canal não é.
 *
 * ## E o nome não leva `_total` por não ser contador
 *
 * O `channel_restricted_total` leva, porque é monótono: uma transição para
 * `restrito` aconteceu e não desacontece. O `channel_quality` não leva, e a
 * convenção do Prometheus é exactamente essa — um `_total` que desce é um
 * contador que mente.
 */

import { EVENTOS_DE_CANAL, QUALIDADES } from "./contrato.ts";

export const METRICA_QUALIDADE = "channel_quality";
export const METRICA_UTILIZACAO = "messaging_limit_usage_ratio";
export const METRICA_RESTRICOES = "channel_restricted_total";
export const METRICA_EVENTOS = "channel_quality_event_total";

export const CONTADORES = [METRICA_RESTRICOES, METRICA_EVENTOS] as const;
export const GAUGES = [METRICA_QUALIDADE, METRICA_UTILIZACAO] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;

/**
 * Os motivos por que um canal passa a `restrito`, para a etiqueta.
 *
 * É o domínio do `tenant_channels.motivo_restricao` da revisão `0013`, e está
 * aqui inteiro — não só o `quality` — porque a métrica é do canal e não deste
 * ticket: quando o KAM-023 ou o KAM-017 restringirem, contam na mesma série.
 */
export const MOTIVOS = ["payment_method", "quality", "policy"] as const;

/**
 * As etiquetas, por métrica, com a lista fechada de valores.
 *
 * **Nenhuma cresce com o tráfego**: `rating` tem três valores, `motivo` tem
 * três e `evento` tem quatro. Nenhuma leva `tenant_id`, `channel_id`,
 * `phone_number_id` nem `wamid`.
 */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_QUALIDADE]: { nome: "rating", valores: QUALIDADES },
  [METRICA_RESTRICOES]: { nome: "motivo", valores: MOTIVOS },
  [METRICA_EVENTOS]: { nome: "evento", valores: EVENTOS_DE_CANAL },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_QUALIDADE]: [
    "gauge",
    "Quantos canais estao em cada qualidade (green, yellow, red). Gauge e nao contador porque um canal que melhora tem de sair de uma serie e entrar na outra. A etiqueta rating tem tres valores fechados e nao e um identificador: e por isso que passa onde a de tenant nao passa (OBS-I).",
  ],
  [METRICA_UTILIZACAO]: [
    "gauge",
    "Fraccao do escalao de mensagens consumida, no canal MAIS PERTO do tecto: utilizadores unicos contactados por template em 24 h moveis, a dividir pelo tecto. Maximo e nao media, pela razao do meta_free_tier_used_ratio. -1 antes da primeira observacao, e tambem quando o escalao nao se reconhece — «nao sei» nao e «esta folgado».",
  ],
  [METRICA_RESTRICOES]: [
    "counter",
    "Transicoes de um canal para restrito, por motivo. Monotono: uma transicao aconteceu e nao desacontece, e e por isso que leva _total. O motivo e o dominio da coluna motivo_restricao, inteiro — quando outro ticket restringir, conta na mesma serie.",
  ],
  [METRICA_EVENTOS]: [
    "counter",
    "Webhooks de gestao de canal tratados, por evento. Nao esta no DoD e esta aqui porque tratar sem contar e tratar em silencio: sem a etiqueta, um painel nao distingue «a Meta nao mandou nada» de «mandamos tudo para o braco errado».",
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
        "Identificadores (tenant_id, channel_id, phone_number_id, wamid) nao " +
        "entram em metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores e *gauges* da qualidade, em memória. Só números. */
export class MetricasDaQualidade {
  readonly #contadores = new Map<string, number>();
  /** A qualidade de cada canal. Chave interna — nunca é etiqueta. */
  readonly #qualidadePorCanal = new Map<string, string>();
  /** O rácio de cada canal. Idem. */
  readonly #racioPorCanal = new Map<string, number>();

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
   * Observa a qualidade de um canal.
   *
   * Substitui a observação anterior **desse** canal, e é isso que faz o *gauge*
   * ser um *gauge*: um canal que vai de `yellow` para `green` sai de uma série
   * e entra na outra. Somar fazia as três séries crescerem para sempre e a
   * soma delas deixar de ser o número de canais.
   *
   * Uma qualidade que não está na lista fechada **não entra**: é o valor
   * desconhecido do critério 1, que se registra na base e não se publica numa
   * série que não existe.
   */
  observarQualidade(canal: string, qualidade: string): void {
    if (!QUALIDADES.includes(qualidade as (typeof QUALIDADES)[number])) return;
    this.#qualidadePorCanal.set(canal, qualidade);
  }

  /**
   * Observa o rácio de utilização de um canal.
   *
   * Um valor que não é finito não entra: um `NaN` no formato de exposição faz o
   * Prometheus descartar a recolha **toda**. E um rácio negativo não existe.
   */
  observarUtilizacao(canal: string, racio: number): void {
    if (!Number.isFinite(racio) || racio < 0) return;
    this.#racioPorCanal.set(canal, racio);
  }

  ler(): Record<string, number> {
    return {
      ...Object.fromEntries(this.#contadores),
      ...this.#seriesDaQualidade(),
      [METRICA_UTILIZACAO]: this.#utilizacao(),
    };
  }

  repor(): void {
    this.#contadores.clear();
    this.#qualidadePorCanal.clear();
    this.#racioPorCanal.clear();
  }

  /** Quantos canais em cada qualidade, como séries com sufixo. */
  #seriesDaQualidade(): Record<string, number> {
    const contagem: Record<string, number> = {};
    for (const q of QUALIDADES) contagem[`${METRICA_QUALIDADE}:${q}`] = 0;
    for (const qualidade of this.#qualidadePorCanal.values()) {
      const chave = `${METRICA_QUALIDADE}:${qualidade}`;
      contagem[chave] = (contagem[chave] ?? 0) + 1;
    }
    return contagem;
  }

  /** O máximo dos rácios, ou `-1` antes da primeira observação. */
  #utilizacao(): number {
    if (this.#racioPorCanal.size === 0) return -1;
    let maximo = 0;
    for (const racio of this.#racioPorCanal.values()) {
      if (racio > maximo) maximo = racio;
    }
    return maximo;
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * As quatro aparecem sempre: os contadores a zero, o `channel_quality` com as
   * três séries a zero, e o rácio a `-1` quando nunca foi observado. A razão é
   * a do `entrada/metricas.ts`: um painel que mostre «sem dados» não distingue
   * «nenhum canal» de «o processo não arrancou».
   */
  exposicao(): string {
    const linhas: string[] = [];
    const series = this.#seriesDaQualidade();
    for (const nome of [...CONTADORES, ...GAUGES]) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      if (nome === METRICA_UTILIZACAO) {
        linhas.push(`${nome} ${this.#utilizacao()}`);
        continue;
      }
      if (nome === METRICA_QUALIDADE) {
        for (const q of QUALIDADES) {
          linhas.push(`${nome}{rating="${q}"} ${series[`${nome}:${q}`] ?? 0}`);
        }
        continue;
      }
      const chaves = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (chaves.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = ETIQUETAS[nome]?.nome ?? "motivo";
      for (const chave of chaves) {
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

/** As métricas da qualidade. */
export const METRICAS_DA_QUALIDADE = new MetricasDaQualidade();
