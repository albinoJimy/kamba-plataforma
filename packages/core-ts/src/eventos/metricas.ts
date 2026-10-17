/**
 * Métricas do publicador (KAM-005 CA8, ADR-018).
 *
 * O ADR-018 manda observabilidade leve no Piloto: métricas próprias, sem
 * Langfuse e sem agente. São as dos critérios de aceitação — três do publicador
 * (KAM-005 CA8) e três do consumidor (KAM-006 CA5):
 *
 *     evt_outbox_lag_seconds       gauge    idade do evento pendente mais antigo
 *     evt_publish_total            counter  *jobs* entregues, por desfecho
 *     evt_publish_errors_total     counter  erros de publicação, por motivo
 *     evt_consumed_total           counter  eventos processados, por desfecho
 *     evt_retry_total              counter  retentativas, por motivo
 *     evt_dlq_open                 gauge    entradas abertas na DLQ, por tipo
 *
 * ## Nenhuma etiqueta leva identificadores
 *
 * O `docs/seguranca/ameacas_stride.md` (`OBS-I`) avisa: identificadores em
 * etiquetas de métricas explodem a cardinalidade e re-identificam. O *lint* de
 * cardinalidade é o KAM-080 e não existe; até existir, a regra é de quem
 * escreve, e aqui é imposta pelo **tipo**: os sufixos permitidos são listas
 * fechadas (`DESFECHOS`, `MOTIVOS`), e `contar` recusa um sufixo que não esteja
 * nelas. `tenant_id`, `event_id`, `agregado_id` e `consumer` **não** entram em
 * etiqueta nenhuma — o `consumer` é uma lista aberta (cada ticket acrescenta um)
 * e não compensa a cardinalidade.
 *
 * **Uma excepção, declarada: o `tipo` do `evt_dlq_open`.** O critério 5 do
 * KAM-006 pede a métrica por tipo de evento, porque é o tipo que decide a
 * severidade do alerta — um `payment.*` na DLQ é Sev1 e um `channel.*` não. Um
 * tipo de evento não re-identifica ninguém e é limitado pelo catálogo (KAM-007),
 * mas «limitado pelo catálogo» não é «limitado»: entra com a gramática
 * `familia.verbo` (a mesma que o `lerEnvelope` exige) e com um **tecto** de
 * `MAXIMO_DE_TIPOS` séries. Acima do tecto, `medirPorTipo` lança — é melhor uma
 * métrica que falha alto do que um painel que cresce sem fim.
 *
 * ## Exposição
 *
 * `exposicao()` dá o texto no formato de exposição do Prometheus. Quem o serve é
 * o processo (`services/worker-canal/src/publicador.ts`, em `/metrics`): esta
 * biblioteca não abre portas.
 *
 * A implementação é a mesma ideia do `Contadores` do *logger* e do
 * `tenant_guard` — um `Map` de números, em memória, sem dependências — com
 * *gauges* a mais, porque o atraso não é um contador.
 */

/**
 * Desfecho de uma publicação. Lista fechada: é sufixo de métrica.
 *
 * São dois, e não três. Havia um `repetido` que **nada incrementava** — uma
 * etiqueta anunciada e vazia, publicada em `docs/eventos.md` como se tivesse
 * valores (ANALISE-20, achado 14). Uma republicação depois de um `kill -9` é
 * indistinguível de uma primeira entrega do ponto de vista do publicador (é a
 * mesma linha, o mesmo `jobId`), e por isso conta como `entregue`: quem a
 * distingue é o consumidor, por `(consumer, event_id)` (KAM-006).
 */
export const DESFECHOS = ["entregue", "sem_destino"] as const;
export type Desfecho = (typeof DESFECHOS)[number];

/** Motivo de um erro de publicação. Lista fechada: é sufixo de métrica. */
export const MOTIVOS = [
  "fila_indisponivel",
  "sem_conversor",
  "envelope_invalido",
  "padrao_de_telefone",
  "destino_invalido",
  "base_indisponivel",
] as const;
export type Motivo = (typeof MOTIVOS)[number];

/**
 * Desfecho de um consumo (KAM-006). Lista fechada: é sufixo de métrica.
 *
 * São dois, e `duplicado` é o que importa: é a prova de que a entrega
 * *at-least-once* aconteceu e que a deduplicação a absorveu. Um `adiado` **não**
 * está aqui — adiar não é um desfecho do consumo, é uma retentativa, e conta no
 * `evt_retry_total`.
 */
export const DESFECHOS_DO_CONSUMO = ["aplicado", "duplicado"] as const;
export type DesfechoDoConsumo = (typeof DESFECHOS_DO_CONSUMO)[number];

/**
 * Motivo de uma retentativa (KAM-006). Lista fechada.
 *
 * `adiado` é a pré-condição que ainda não se verifica (§6.3); `erro` é tudo o
 * mais. A diferença entre os dois é operacional e não cosmética: uma subida de
 * `adiado` é um consumidor à espera de um agregado que não chega, e uma subida
 * de `erro` é código a falhar.
 */
export const MOTIVOS_DE_RETENTATIVA = ["adiado", "erro"] as const;
export type MotivoDeRetentativa = (typeof MOTIVOS_DE_RETENTATIVA)[number];

/** Quantas séries de `evt_dlq_open{tipo}` se aceitam antes de desistir. */
export const MAXIMO_DE_TIPOS = 64;

/** A gramática de um tipo de evento, a mesma que o `lerEnvelope` exige. */
export const TIPO_DE_EVENTO = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/;

export const METRICA_ATRASO = "evt_outbox_lag_seconds";
export const METRICA_PUBLICADOS = "evt_publish_total";
export const METRICA_ERROS = "evt_publish_errors_total";

/** Se o processo é o líder (1) ou está em espera (0). Ajuda a diagnosticar. */
export const METRICA_LIDER = "evt_publisher_leader";

export const METRICA_CONSUMIDOS = "evt_consumed_total";
export const METRICA_RETENTATIVAS = "evt_retry_total";
export const METRICA_DLQ_ABERTAS = "evt_dlq_open";

/**
 * Que sufixos cada contador aceita, e como se chama a etiqueta de cada um.
 *
 * Era um ternário (`metrica === METRICA_ERROS ? "motivo" : "desfecho"`) em dois
 * sítios. Com cinco métricas e três etiquetas deixava de se ler, e um sufixo
 * novo passava a ser aceite por omissão — que é o contrário do que a lista
 * fechada existe para fazer.
 */
const ETIQUETAS: Record<string, { readonly nome: string; readonly valores: readonly string[] }> = {
  [METRICA_PUBLICADOS]: { nome: "desfecho", valores: DESFECHOS },
  [METRICA_ERROS]: { nome: "motivo", valores: MOTIVOS },
  [METRICA_CONSUMIDOS]: { nome: "desfecho", valores: DESFECHOS_DO_CONSUMO },
  [METRICA_RETENTATIVAS]: { nome: "motivo", valores: MOTIVOS_DE_RETENTATIVA },
};

const AJUDA: Record<string, [string, string]> = {
  [METRICA_ATRASO]: [
    "gauge",
    "Idade em segundos do evento pendente mais antigo do outbox.",
  ],
  [METRICA_PUBLICADOS]: [
    "counter",
    "Jobs entregues as filas, por desfecho.",
  ],
  [METRICA_ERROS]: [
    "counter",
    "Erros de publicacao, por motivo. Nunca com identificadores.",
  ],
  [METRICA_LIDER]: [
    "gauge",
    "1 se este processo tem o lock consultivo do publicador, 0 se espera.",
  ],
  [METRICA_CONSUMIDOS]: [
    "counter",
    "Eventos processados por um consumidor, por desfecho.",
  ],
  [METRICA_RETENTATIVAS]: [
    "counter",
    "Retentativas de consumo, por motivo. adiado e pre-condicao por verificar.",
  ],
  [METRICA_DLQ_ABERTAS]: [
    "gauge",
    "Entradas abertas na DLQ, por tipo de evento. Um payment.* aqui e Sev1.",
  ],
};

/** Um sufixo de métrica que não está numa das listas fechadas. */
export class EtiquetaInvalidaError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(
      `${metrica}: sufixo ${JSON.stringify(sufixo)} nao esta na lista fechada. ` +
        "Identificadores (tenant_id, event_id, consumer) nao entram em metricas " +
        "(docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "EtiquetaInvalidaError";
  }
}

/** Contadores e *gauges* em memória. Só números. */
export class Metricas {
  readonly #contadores = new Map<string, number>();
  readonly #gauges = new Map<string, number>();

  /** Soma `quanto` (1 por omissão) ao contador. */
  contar(metrica: string, sufixo?: string, quanto = 1): void {
    if (sufixo !== undefined) {
      const permitidos = ETIQUETAS[metrica]?.valores;
      if (permitidos === undefined || !permitidos.includes(sufixo)) {
        throw new EtiquetaInvalidaError(metrica, sufixo);
      }
    }
    const nome = sufixo === undefined ? metrica : `${metrica}:${sufixo}`;
    this.#contadores.set(nome, (this.#contadores.get(nome) ?? 0) + quanto);
  }

  /** Fixa o valor de um *gauge*. */
  medir(metrica: string, valor: number): void {
    this.#gauges.set(metrica, valor);
  }

  /**
   * Fixa o valor de um *gauge* **por tipo de evento** (só `evt_dlq_open`).
   *
   * Valida a gramática e o tecto, pelas razões da docstring do módulo. Um tipo
   * que não case a gramática é tratado como etiqueta inválida: se um
   * identificador chegasse aqui por engano, não casava `familia.verbo`.
   */
  medirPorTipo(metrica: string, tipo: string, valor: number): void {
    if (metrica !== METRICA_DLQ_ABERTAS) {
      throw new EtiquetaInvalidaError(metrica, tipo);
    }
    if (!TIPO_DE_EVENTO.test(tipo)) throw new EtiquetaInvalidaError(metrica, tipo);
    const prefixo = `${metrica}:`;
    const series = [...this.#gauges.keys()].filter((chave) => chave.startsWith(prefixo));
    const nome = `${prefixo}${tipo}`;
    if (!series.includes(nome) && series.length >= MAXIMO_DE_TIPOS) {
      throw new RangeError(
        `${metrica}: ${MAXIMO_DE_TIPOS} series e o tecto, e o tipo ${tipo} seria mais uma. ` +
          "Uma metrica que cresce sem fim deixa de ser observabilidade.",
      );
    }
    this.#gauges.set(nome, valor);
  }

  /** Esquece as séries de `evt_dlq_open`: a leitura seguinte é a verdade toda. */
  reporTipos(metrica: string): void {
    const prefixo = `${metrica}:`;
    for (const chave of [...this.#gauges.keys()]) {
      if (chave.startsWith(prefixo)) this.#gauges.delete(chave);
    }
  }

  ler(): Record<string, number> {
    return { ...Object.fromEntries(this.#contadores), ...Object.fromEntries(this.#gauges) };
  }

  repor(): void {
    this.#contadores.clear();
    this.#gauges.clear();
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * O sufixo depois de `:` passa a etiqueta `desfecho` ou `motivo`, que são as
   * duas únicas etiquetas que existem. Uma métrica declarada e nunca
   * incrementada aparece a zero: um painel que mostre «sem dados» não distingue
   * «nenhum erro» de «o publicador não arrancou».
   */
  exposicao(): string {
    const linhas: string[] = [];
    const valores = new Map<string, number>([
      [METRICA_ERROS, 0],
      [METRICA_PUBLICADOS, 0],
      [METRICA_CONSUMIDOS, 0],
      [METRICA_RETENTATIVAS, 0],
    ]);
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`);
      linhas.push(`# TYPE ${nome} ${tipo}`);
      const gauge = this.#gauges.get(nome);
      if (gauge !== undefined) {
        linhas.push(`${nome} ${gauge}`);
        continue;
      }
      // Um *gauge* por tipo (só o `evt_dlq_open`): as séries vivem com sufixo.
      const porTipo = [...this.#gauges.keys()]
        .filter((chave) => chave.startsWith(`${nome}:`))
        .sort();
      if (porTipo.length > 0) {
        for (const chave of porTipo) {
          linhas.push(
            `${nome}{tipo="${chave.slice(nome.length + 1)}"} ${this.#gauges.get(chave) ?? 0}`,
          );
        }
        continue;
      }
      const sufixos = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (sufixos.length === 0) {
        if (valores.has(nome)) linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = ETIQUETAS[nome]?.nome ?? "desfecho";
      for (const chave of sufixos) {
        const sufixo = chave.slice(nome.length + 1);
        const valor = this.#contadores.get(chave) ?? 0;
        linhas.push(
          sufixo === ""
            ? `${nome} ${valor}`
            : `${nome}{${etiqueta}="${sufixo}"} ${valor}`,
        );
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As métricas do processo. */
export const METRICAS = new Metricas();
