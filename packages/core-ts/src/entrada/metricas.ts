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

import { MOTIVOS as MOTIVOS_DE_QUARENTENA } from "./contrato.ts";

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

/** As métricas do GWY. */
export const METRICAS = new MetricasDaEntrada();

// ---------------------------------------------------------------------------
// As do *worker* de entrada, que são outras
// ---------------------------------------------------------------------------
//
// **Isto nasceu de um achado da revisão adversarial.** O *worker* servia as
// cinco de cima no seu `/metrics`, e não incrementa nenhuma: saíam
// `gwy_sig_fail 0` e `inbound_queue_depth -1` permanentes — a diluir qualquer
// média sobre os alvos do serviço, e a pôr um `-1` ao lado do valor real do
// GWY, onde um alerta sobre a profundidade da fila o lê e não dispara. E do
// trabalho que o *worker* faz de verdade não saía nada.
//
// Os nomes não estão no DoD do ticket — o DoD nomeia as do GWY — e entram como
// *proposta*, pela mesma razão do `gwy_shed_total`: um processo que escreve na
// base sem uma métrica do que escreveu não tem observabilidade nenhuma.

/** Eventos de canal registados, por desfecho. */
export const METRICA_ENTRADAS = "inbound_events_total";
/** Eventos postos em quarentena, por motivo. */
export const METRICA_EM_QUARENTENA = "inbound_unrouted_total";
/** *Jobs* que falharam e o BullMQ vai repetir. */
export const METRICA_FALHAS = "inbound_job_failed_total";

/** Desfecho de um registo. Lista fechada: é sufixo de métrica. */
export const DESFECHOS_DA_ENTRADA = ["registado", "duplicado", "recuperado"] as const;
export type DesfechoDaEntrada = (typeof DESFECHOS_DA_ENTRADA)[number];

const AJUDA_DO_WORKER: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_ENTRADAS]: [
    "counter",
    "Eventos de canal registados, por desfecho. recuperado = estava sem processado_at.",
  ],
  [METRICA_EM_QUARENTENA]: [
    "counter",
    "Eventos postos em quarentena, por motivo. Um json_invalido aqui e um corpo que nao encaixou.",
  ],
  [METRICA_FALHAS]: [
    "counter",
    "Jobs da fila de entrada que falharam. Nunca por conteudo do corpo: isso vai a quarentena.",
  ],
};

/**
 * Que sufixos cada contador aceita. Listas **fechadas**, como no
 * `eventos/metricas.ts`: um identificador não entra em etiqueta nenhuma
 * (`docs/seguranca/ameacas_stride.md`, OBS-I), e os motivos de quarentena são
 * os quatro do dicionário §3.12 — não crescem com o tráfego.
 */
const ETIQUETAS_DO_WORKER: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_ENTRADAS]: { nome: "desfecho", valores: DESFECHOS_DA_ENTRADA },
  [METRICA_EM_QUARENTENA]: { nome: "motivo", valores: MOTIVOS_DE_QUARENTENA },
};

/** Um sufixo que não está na lista fechada da sua métrica. */
export class SufixoInvalidoError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(
      `${metrica}: sufixo ${JSON.stringify(sufixo)} nao esta na lista fechada. ` +
        "Identificadores (waba_id, phone_number_id, event_key) nao entram em " +
        "metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores do *worker* de entrada. Só números. */
export class MetricasDoWorker {
  readonly #contadores = new Map<string, number>();

  contar(metrica: string, sufixo?: string, quanto = 1): void {
    if (AJUDA_DO_WORKER[metrica] === undefined) {
      throw new MetricaDesconhecidaError(metrica);
    }
    if (sufixo !== undefined) {
      const permitidos = ETIQUETAS_DO_WORKER[metrica]?.valores;
      if (permitidos === undefined || !permitidos.includes(sufixo)) {
        throw new SufixoInvalidoError(metrica, sufixo);
      }
    }
    const nome = sufixo === undefined ? metrica : `${metrica}:${sufixo}`;
    this.#contadores.set(nome, (this.#contadores.get(nome) ?? 0) + quanto);
  }

  ler(): Record<string, number> {
    return Object.fromEntries(this.#contadores);
  }

  repor(): void {
    this.#contadores.clear();
  }

  /** Formato de exposição do Prometheus. As três aparecem sempre. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA_DO_WORKER)) {
      linhas.push(`# HELP ${nome} ${ajuda}`);
      linhas.push(`# TYPE ${nome} ${tipo}`);
      const series = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (series.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = ETIQUETAS_DO_WORKER[nome]?.nome ?? "desfecho";
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

/** As métricas do *worker* de entrada. */
export const METRICAS_DO_WORKER = new MetricasDoWorker();
