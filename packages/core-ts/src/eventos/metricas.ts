/**
 * Métricas do publicador (KAM-005 CA8, ADR-018).
 *
 * O ADR-018 manda observabilidade leve no Piloto: métricas próprias, sem
 * Langfuse e sem agente. São três, e os nomes são os do critério de aceitação:
 *
 *     evt_outbox_lag_seconds       gauge    idade do evento pendente mais antigo
 *     evt_publish_total            counter  *jobs* entregues, por desfecho
 *     evt_publish_errors_total     counter  erros de publicação, por motivo
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

export const METRICA_ATRASO = "evt_outbox_lag_seconds";
export const METRICA_PUBLICADOS = "evt_publish_total";
export const METRICA_ERROS = "evt_publish_errors_total";

/** Se o processo é o líder (1) ou está em espera (0). Ajuda a diagnosticar. */
export const METRICA_LIDER = "evt_publisher_leader";

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
      const permitidos: readonly string[] =
        metrica === METRICA_ERROS ? MOTIVOS : DESFECHOS;
      if (!permitidos.includes(sufixo)) {
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
    ]);
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`);
      linhas.push(`# TYPE ${nome} ${tipo}`);
      const gauge = this.#gauges.get(nome);
      if (gauge !== undefined) {
        linhas.push(`${nome} ${gauge}`);
        continue;
      }
      const sufixos = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (sufixos.length === 0) {
        if (valores.has(nome)) linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = nome === METRICA_ERROS ? "motivo" : "desfecho";
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
