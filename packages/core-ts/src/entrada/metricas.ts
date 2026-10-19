/**
 * As métricas da entrada de canal (KAM-013, DoD «Custo e observabilidade»,
 * ADR-018).
 *
 *     gwy_requests_total   counter  pedidos recebidos no webhook
 *     gwy_sig_fail         counter  pedidos recusados por assinatura
 *     gwy_shed_total       counter  corpos descartados sob saturação
 *     gwy_enqueue_ms       gauge    duração do último enfileiramento
 *     inbound_queue_depth  gauge    jobs por fazer na fila de entrada
 *
 * A forma é a do `ten/metricas.ts`, que é a do `eventos/metricas.ts` — um `Map`
 * de números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus. Um módulo por domínio e não um registo central: é o precedente
 * que o KAM-009 abriu, e a razão é que o `exposicao()` do `eventos/` só emite
 * os nomes do seu próprio `AJUDA` — pôr os do GWY lá era pôr métricas de
 * webhook no registo do barramento de eventos. Esta biblioteca não abre portas:
 * quem expõe `/metrics` é o serviço.
 *
 * ## Nenhuma destas métricas tem etiquetas, e isso é deliberado
 *
 * Os quatro nomes do DoD são contadores e *gauges* simples. Não há por onde
 * dividi-los que não seja por identificador — `phone_number_id`, `waba_id` —, e
 * esses não entram em etiqueta nenhuma (`docs/seguranca/ameacas_stride.md`,
 * `OBS-I`). Sem etiquetas, não há gramática nem tecto de séries a impor: o
 * `contar` aceita um nome da lista fechada e mais nada.
 *
 * ## `gwy_shed_total` é uma quinta métrica, e o DoD nomeia quatro
 *
 * Está aqui porque o critério 7 manda descartar tráfego sob saturação, e
 * descartar sem contar é descartar em silêncio: um painel sem esta métrica não
 * distingue «a Meta mandou menos estados» de «nós deitámos fora os estados
 * dela». Entra no dicionário §3.12 com o resto, declarada como acrescento
 * deste ticket e não como um dos quatro.
 *
 * ## O que `gwy_enqueue_ms` **não** dá
 *
 * Percentis. É um *gauge* com o **último** valor: o formato de exposição do
 * Prometheus tem histogramas e esta biblioteca não os implementa (o
 * `eventos/metricas.ts` também não, por ADR-018 — observabilidade leve no
 * Piloto). O p99 do critério 7 mede-se na prova de carga, que é onde o número
 * tem significado; a agregação contínua é KAM-080 e o dimensionamento é
 * KAM-084. Fica dito aqui para ninguém ler este *gauge* como um p99.
 */

export const METRICA_PEDIDOS = "gwy_requests_total";
export const METRICA_ASSINATURA_FALHOU = "gwy_sig_fail";
export const METRICA_DESCARTADOS = "gwy_shed_total";
export const METRICA_ENFILEIRAMENTO_MS = "gwy_enqueue_ms";
export const METRICA_PROFUNDIDADE = "inbound_queue_depth";

/** Os contadores, pela ordem em que saem. Lista fechada. */
export const CONTADORES = [
  METRICA_PEDIDOS,
  METRICA_ASSINATURA_FALHOU,
  METRICA_DESCARTADOS,
] as const;

/** Os *gauges*, pela ordem em que saem. Lista fechada. */
export const GAUGES = [METRICA_ENFILEIRAMENTO_MS, METRICA_PROFUNDIDADE] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_PEDIDOS]: ["counter", "Pedidos recebidos no webhook da Meta."],
  [METRICA_ASSINATURA_FALHOU]: [
    "counter",
    "Pedidos recusados por assinatura ausente ou invalida. Alerta acima de 5/min: e sondagem.",
  ],
  [METRICA_DESCARTADOS]: [
    "counter",
    "Corpos descartados sob saturacao. So estados sem preco; nunca messages.",
  ],
  [METRICA_ENFILEIRAMENTO_MS]: [
    "gauge",
    "Duracao do ultimo enfileiramento em ms. Ultimo valor, nao percentil.",
  ],
  [METRICA_PROFUNDIDADE]: [
    "gauge",
    "Jobs por fazer na fila de entrada: a espera, adiados e a correr. -1 se nao se conseguiu ler.",
  ],
};

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;
const NOMES_DE_GAUGE: readonly string[] = GAUGES;

/** Um nome que não está numa das duas listas fechadas. */
export class MetricaDesconhecidaError extends Error {
  constructor(metrica: string) {
    super(
      `${JSON.stringify(metrica)} nao e uma metrica da entrada de canal. ` +
        `Contadores: ${CONTADORES.join(", ")}. Gauges: ${GAUGES.join(", ")}.`,
    );
    this.name = "MetricaDesconhecidaError";
  }
}

/** Contadores e *gauges* em memória. Só números. */
export class MetricasDaEntrada {
  readonly #contadores = new Map<string, number>();
  readonly #gauges = new Map<string, number>();

  /** Soma `quanto` (1 por omissão) ao contador. */
  contar(metrica: Contador, quanto = 1): void {
    if (!NOMES_DE_CONTADOR.includes(metrica)) throw new MetricaDesconhecidaError(metrica);
    this.#contadores.set(metrica, (this.#contadores.get(metrica) ?? 0) + quanto);
  }

  /** Fixa o valor de um *gauge*. */
  medir(metrica: Gauge, valor: number): void {
    if (!NOMES_DE_GAUGE.includes(metrica)) throw new MetricaDesconhecidaError(metrica);
    // Um valor que não é um número finito não substitui o anterior: um `NaN` no
    // formato de exposição faz o Prometheus descartar a recolha **toda**, e
    // perder-se-iam as outras quatro por causa desta.
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
   * As cinco aparecem sempre, as contadoras a zero e os *gauges* a `-1` quando
   * nunca foram medidos. A escolha é a do `eventos/metricas.ts` e a razão é a
   * mesma: um painel que mostre «sem dados» não distingue «nenhum pedido
   * recusado» de «o GWY não arrancou». O `-1` de um *gauge* diz «ainda não há
   * leitura» sem se confundir com «zero», que para a profundidade da fila é uma
   * resposta legítima e muito diferente.
   */
  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of [...CONTADORES, ...GAUGES]) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      const valor = NOMES_DE_CONTADOR.includes(nome)
        ? (this.#contadores.get(nome) ?? 0)
        : (this.#gauges.get(nome) ?? -1);
      linhas.push(`${nome} ${valor}`);
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As métricas do processo. */
export const METRICAS = new MetricasDaEntrada();
