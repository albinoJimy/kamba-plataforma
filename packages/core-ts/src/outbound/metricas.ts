/**
 * As métricas da saída de canal (KAM-015, DoD «Custo e observabilidade»).
 *
 *     outbound_sent_total            counter  envios, por categoria
 *     outbound_window_closed_total   counter  recusas, por motivo
 *     outbound_rate_limited_total    counter  envios travados pelo token bucket
 *     meta_cost_usd_total            counter  custo acumulado, em MICRO-dolares
 *     outbound_latency_ms            gauge    duracao do ultimo envio, em ms
 *
 * A forma é a do `chr/metricas.ts`, que é a do `entrada/metricas.ts` e a do
 * `ten/metricas.ts` — um `Map` de números, em memória, sem dependências, com
 * `exposicao()` no formato do Prometheus. Um módulo por domínio, pelo precedente
 * que o KAM-009 abriu.
 *
 * ## São cinco, e o DoD nomeia três
 *
 * As duas a mais são `outbound_sent_total` e `outbound_rate_limited_total`.
 *
 * A **`outbound_rate_limited_total`** está aqui pela razão do `gwy_shed_total`
 * da emenda 1.19 e da `chr_resolve_total` da 1.20: **recusar sem contar é
 * recusar em silêncio**. É o único sítio onde um envio travado pelo *token
 * bucket* fica visível, e sem ela um painel não distingue «ninguém enviou» de
 * «foi tudo travado» — que é exactamente a diferença entre um dia calmo e um
 * incidente de débito.
 *
 * A **`outbound_sent_total`**, com etiqueta `kind`, é o que torna o custo
 * auditável: o `meta_cost_usd_total` é uma soma e não se consegue verificar
 * sozinho, mas `sent_total{kind}` × tarifa reconcilia-se com ele. Sem as duas,
 * um erro de conversão de unidade passava sem ninguém ver.
 *
 * ## `meta_cost_usd_total` **não leva etiqueta de tenant**, e o DoD pede uma
 *
 * O DoD escreve `meta_cost_usd_total{tenant}`. Não é implementável e a caixa
 * fica vazia, com esta razão escrita no §3.14 e na secção de verificação:
 *
 * - as quatro bibliotecas de métricas deste repositório recusam **por
 *   gramática** uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`, e um
 *   `tenant_id` é um UUID com hífenes que muitas vezes começa por dígito. A
 *   chamada **levanta**;
 * - a razão é o `OBS-I` de `docs/seguranca/ameacas_stride.md` («identificadores
 *   em etiquetas explodem a cardinalidade e re-identificam») e o X-11 do gate
 *   6, que varre registos por identificadores — uma etiqueta é tão legível
 *   como uma linha de registo;
 * - o `docs/tecnica/01` §16 já aponta o caminho certo: «custo monitorizado por
 *   tenant e por mensagem | mecanismo: `pricing` dos *status*». O por-tenant
 *   sai do `SQL_CUSTO_DO_TENANT`, por consulta, e não re-identifica ninguém.
 *
 * ## E o nome diz `usd` mas a unidade é o micro-dólar
 *
 * O nome é o do DoD e não se muda. A unidade é a do §2 do dicionário: inteira,
 * porque somar `0.004` mil vezes em `float64` não dá `4.00`, e um acumulador de
 * custo com deriva não se reconcilia contra uma factura. O `# HELP` diz-o por
 * extenso, que é onde quem lê o painel o vai ver.
 */

import { CATEGORIAS, MOTIVOS_DE_RECUSA } from "./contrato.ts";

export const METRICA_ENVIADAS = "outbound_sent_total";
export const METRICA_JANELA_FECHADA = "outbound_window_closed_total";
export const METRICA_TRAVADAS = "outbound_rate_limited_total";
export const METRICA_CUSTO = "meta_cost_usd_total";
export const METRICA_DURACAO = "outbound_latency_ms";

export const CONTADORES = [
  METRICA_ENVIADAS,
  METRICA_JANELA_FECHADA,
  METRICA_TRAVADAS,
  METRICA_CUSTO,
] as const;
export const GAUGES = [METRICA_DURACAO] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;
const NOMES_DE_GAUGE: readonly string[] = GAUGES;

/**
 * As etiquetas, por métrica, com a lista fechada de valores.
 *
 * **Nenhuma cresce com o tráfego**, e é isso que as torna admissíveis: o `kind`
 * tem quatro valores e o `motivo` tem dez. Nenhuma leva `tenant_id`,
 * `contact_id`, `channel_id`, `phone_number_id` nem `wamid`.
 */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_ENVIADAS]: { nome: "kind", valores: CATEGORIAS },
  [METRICA_JANELA_FECHADA]: { nome: "motivo", valores: MOTIVOS_DE_RECUSA },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_ENVIADAS]: ["counter", "Mensagens aceites pela Meta, por categoria."],
  [METRICA_JANELA_FECHADA]: [
    "counter",
    "Envios recusados antes ou depois da chamada, por motivo. Inclui o WINDOW_CLOSED, que nao gasta chamada HTTP.",
  ],
  [METRICA_TRAVADAS]: [
    "counter",
    "Envios travados pelo token bucket (por canal ou por par). Recusar sem contar e recusar em silencio.",
  ],
  [METRICA_CUSTO]: [
    "counter",
    "Custo acumulado em MICRO-dolares (1e-6 USD), inteiro. O nome e o do DoD; a unidade e inteira porque o §2 proibe virgula flutuante em dinheiro. Nao leva etiqueta de tenant: ver o modulo, e o por-tenant sai de SQL_CUSTO_DO_TENANT.",
  ],
  [METRICA_DURACAO]: ["gauge", "Duracao do ultimo envio, em ms. -1 antes do primeiro."],
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
        "Identificadores (tenant_id, contact_id, channel_id, phone_number_id, " +
        "wamid) nao entram em metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores e *gauges* da saída, em memória. Só números. */
export class MetricasDaSaida {
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

  /**
   * Soma custo, em micro-dólares **inteiros**.
   *
   * Recusa o que não for inteiro em vez de o arredondar: um custo fraccionário
   * aqui é um erro de unidade em quem chama — alguém passou dólares —, e
   * arredondá-lo em silêncio era transformar um defeito de conversão num número
   * plausível que ninguém volta a questionar.
   */
  somarCusto(microUsd: number): void {
    if (!Number.isInteger(microUsd) || microUsd < 0) return;
    this.contar(METRICA_CUSTO, undefined, microUsd);
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
   * As cinco aparecem sempre, os contadores a zero e o *gauge* a `-1` quando
   * nunca foi medido. A razão é a do `entrada/metricas.ts`: um painel que mostre
   * «sem dados» não distingue «nenhum envio» de «o processo não arrancou».
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

/** As métricas da saída. */
export const METRICAS_DA_SAIDA = new MetricasDaSaida();
