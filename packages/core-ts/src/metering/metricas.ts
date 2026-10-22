/**
 * As métricas do *free tier* (KAM-023, critérios 3, 4 e 5; DoD «Custo e
 * observabilidade», ADR-018).
 *
 *     meta_free_tier_used_ratio      gauge    fraccao consumida, o PIOR canal
 *     meta_cost_usd_estimate         gauge    estimativa acima do tecto, em MICRO-dolares, SOMADA
 *     meta_free_tier_alert_total     counter  avisos emitidos, por nivel
 *     meta_payment_suspect_total     counter  suspeitas de metodo de pagamento
 *
 * A forma é a do `outbound/metricas.ts`, que é a do `chr/metricas.ts` e a do
 * `ten/metricas.ts` — um `Map` de números, em memória, sem dependências, com
 * `exposicao()` no formato do Prometheus. Um módulo por domínio, pelo
 * precedente que o KAM-009 abriu.
 *
 * ## São quatro, e o critério 4 nomeia duas
 *
 * As duas a mais são contadores, e estão aqui pela razão que o
 * `outbound_rate_limited_total` da emenda 1.21 e o `gwy_shed_total` da 1.19
 * escreveram: **avisar sem contar é avisar em silêncio**. O critério 3 pede «1
 * aviso aos 800 e 1 aos 1.000»; sem a `meta_free_tier_alert_total` não há como
 * verificar, depois do facto, que saiu um e não zero nem duzentos — e «saiu
 * um» é precisamente a propriedade que o critério afirma. A
 * `meta_payment_suspect_total` é o mesmo argumento para o critério 5, e vale
 * ainda mais ali: a detecção é uma **heurística com limiares propostos** (20%
 * em 20), e sem a contar não há como calibrar os limiares contra o que
 * aconteceu.
 *
 * ## As duas do critério 4 **não levam etiqueta de *tenant***
 *
 * O critério escreve `meta_free_tier_used_ratio{tenant}` e
 * `meta_cost_usd_estimate{tenant}`. Não é implementável, as caixas ficam
 * vazias com esta razão, e **a decisão não é nova** — é a mesma que o KAM-015
 * registou no §3.14 do dicionário para a `meta_cost_usd_total{tenant}`, há dois
 * módulos de distância. Decidir ao contrário aqui era pôr o repositório a
 * contradizer-se:
 *
 * - as bibliotecas de métricas deste repositório recusam **por gramática** uma
 *   etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID
 *   com hífenes que muitas vezes começa por dígito. A chamada **levanta**;
 * - a razão de fundo é o `OBS-I` de `docs/seguranca/ameacas_stride.md`
 *   («identificadores em etiquetas explodem a cardinalidade e re-identificam»)
 *   e o X-11 do *gate* 6, que varre registos por identificadores — uma
 *   etiqueta é tão legível como uma linha de registo;
 * - o por-*tenant* e o por-canal saem de **consulta** (`SQL_ESTADO`,
 *   `SQL_RECONCILIAR`), que é o caminho que o `docs/tecnica/01` §16 já aponta
 *   («custo monitorizado por tenant e por mensagem | mecanismo: `pricing` dos
 *   *status*») e o único que não re-identifica ninguém.
 *
 * ## Mas um *gauge* sem etiqueta precisava de uma decisão, e esta é ela
 *
 * Tirar a etiqueta a um contador é inofensivo — soma tudo. Tirá-la a um
 * **gauge** não é: com muitos canais, `gauges.set(nome, valor)` deixa no
 * ficheiro o valor do **último canal observado**, que não é o de nenhum canal
 * em particular e muda a cada mensagem. Um painel assim não mente por omissão,
 * mente por inteiro.
 *
 * Por isso os dois *gauges* são **agregados explícitos** sobre um mapa interno
 * por canal:
 *
 * - `meta_free_tier_used_ratio` é o **máximo** — «qual é o canal mais perto do
 *   tecto». É a pergunta que um alerta de 80% faz, e a média respondia-a mal:
 *   um canal a 100% entre dez a zero dá média de 10%;
 * - `meta_cost_usd_estimate` é a **soma** — «quanto é que isto vai custar». Um
 *   máximo aqui respondia «o canal mais caro», que não é a conta que alguém
 *   quer fazer.
 *
 * O mapa interno tem o canal por chave e **nunca sai do processo**: não é uma
 * etiqueta, não vai para o formato de exposição, e não cria séries. A
 * cardinalidade do Prometheus não cresce; o que cresce é memória, limitada pelo
 * número de canais que o processo serve. É a mesma distinção que o
 * `SQL_CUSTO_DO_TENANT` do KAM-015 faz: saber por canal é legítimo, publicar
 * por canal não é.
 *
 * ## E o nome diz `usd` mas a unidade é o micro-dólar
 *
 * Como no KAM-015, e pela mesma razão: o nome é o do critério e não se muda; a
 * unidade é a do §2 do dicionário, inteira, porque somar `0.004` mil vezes em
 * `float64` não dá `4.00`. O `# HELP` di-lo por extenso, que é onde quem lê o
 * painel o vai ver. O rácio **é** fraccionário e está certo que seja: não é
 * dinheiro e não se acumula.
 */

import { NIVEIS } from "./contrato.ts";

export const METRICA_RACIO = "meta_free_tier_used_ratio";
export const METRICA_ESTIMATIVA = "meta_cost_usd_estimate";
export const METRICA_ALERTAS = "meta_free_tier_alert_total";
export const METRICA_SUSPEITAS = "meta_payment_suspect_total";

export const CONTADORES = [METRICA_ALERTAS, METRICA_SUSPEITAS] as const;
export const GAUGES = [METRICA_RACIO, METRICA_ESTIMATIVA] as const;

export type Contador = (typeof CONTADORES)[number];
export type Gauge = (typeof GAUGES)[number];

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;

/**
 * As etiquetas, por métrica, com a lista fechada de valores.
 *
 * **Nenhuma cresce com o tráfego.** A única é o `nivel`, de dois valores.
 * Nenhuma leva `tenant_id`, `channel_id`, `phone_number_id` nem `wamid`.
 */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_ALERTAS]: { nome: "nivel", valores: NIVEIS },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_RACIO]: [
    "gauge",
    "Fraccao do free tier de service messages consumida, no canal MAIS PERTO do tecto. Maximo e nao media: um canal a 100% entre dez a zero daria media de 10%. Nao leva etiqueta de tenant: ver o modulo, e o por-canal sai de SQL_ESTADO. -1 antes da primeira observacao.",
  ],
  [METRICA_ESTIMATIVA]: [
    "gauge",
    "Custo estimado acima do free tier em MICRO-dolares (1e-6 USD), inteiro, SOMADO sobre os canais. E uma estimativa nossa a partir do contador; o que a Meta cobrou e o meta_cost_usd_total do KAM-015, e a diferenca entre os dois e o que a reconciliacao mede. -1 antes da primeira observacao.",
  ],
  [METRICA_ALERTAS]: [
    "counter",
    "Avisos de free tier emitidos, por nivel: aviso (80% do tecto) ou esgotado (o tecto). Existe para se poder verificar que saiu UM por travessia e por mes, que e o que o critario 3 afirma.",
  ],
  [METRICA_SUSPEITAS]: [
    "counter",
    "Vezes que a heuristica concluiu possivel metodo de pagamento ausente ou invalido. Os limiares (20% em 20 mensagens) sao PROPOSTA e este contador e o que permite calibra-los; o codigo de erro concreto da Meta e NAO VERIFICADO.",
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

/** Contadores e *gauges* do *free tier*, em memória. Só números. */
export class MetricasDoFreeTier {
  readonly #contadores = new Map<string, number>();
  /** O rácio e a estimativa por canal. Chave interna — nunca é etiqueta. */
  readonly #porCanal = new Map<string, { racio: number; microUsd: number }>();

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
   * Observa o estado de um canal.
   *
   * Substitui a observação anterior **desse** canal em vez de somar: o rácio e
   * a estimativa são o estado actual do contador, não um acumulado. Somar
   * fazia a estimativa crescer a cada mensagem e dizer, ao fim de um mês, a
   * soma de todos os estados intermédios.
   *
   * Um valor que não é finito não entra: um `NaN` no formato de exposição faz o
   * Prometheus descartar a recolha **toda**. E a estimativa que não for inteira
   * é recusada pela razão do `somarCusto` do KAM-015 — um custo fraccionário
   * aqui é um erro de unidade em quem chama, e arredondá-lo em silêncio era
   * transformar um defeito de conversão num número plausível.
   */
  observar(canal: string, racio: number, microUsd: number): void {
    if (!Number.isFinite(racio) || racio < 0) return;
    if (!Number.isInteger(microUsd) || microUsd < 0) return;
    this.#porCanal.set(canal, { racio, microUsd });
  }

  ler(): Record<string, number> {
    return {
      ...Object.fromEntries(this.#contadores),
      [METRICA_RACIO]: this.#racio(),
      [METRICA_ESTIMATIVA]: this.#estimativa(),
    };
  }

  repor(): void {
    this.#contadores.clear();
    this.#porCanal.clear();
  }

  /** O máximo dos rácios, ou `-1` antes da primeira observação. */
  #racio(): number {
    if (this.#porCanal.size === 0) return -1;
    let maximo = 0;
    for (const { racio } of this.#porCanal.values()) {
      if (racio > maximo) maximo = racio;
    }
    return maximo;
  }

  /** A soma das estimativas, ou `-1` antes da primeira observação. */
  #estimativa(): number {
    if (this.#porCanal.size === 0) return -1;
    let soma = 0;
    for (const { microUsd } of this.#porCanal.values()) soma += microUsd;
    return soma;
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * As quatro aparecem sempre, os contadores a zero e os *gauges* a `-1`
   * quando nunca foram observados. A razão é a do `entrada/metricas.ts`: um
   * painel que mostre «sem dados» não distingue «nenhuma mensagem» de «o
   * processo não arrancou».
   */
  exposicao(): string {
    const linhas: string[] = [];
    const valores: Readonly<Record<string, number>> = {
      [METRICA_RACIO]: this.#racio(),
      [METRICA_ESTIMATIVA]: this.#estimativa(),
    };
    for (const nome of [...CONTADORES, ...GAUGES]) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      const valorDeGauge = valores[nome];
      if (valorDeGauge !== undefined) {
        linhas.push(`${nome} ${valorDeGauge}`);
        continue;
      }
      const series = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (series.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = ETIQUETAS[nome]?.nome ?? "nivel";
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

/** As métricas do *free tier*. */
export const METRICAS_DO_FREE_TIER = new MetricasDoFreeTier();
