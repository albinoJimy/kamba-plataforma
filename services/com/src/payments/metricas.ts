/**
 * As métricas de pagamento deste serviço: o atraso do KAM-055 e os sinais de
 * anomalia do KAM-060.
 *
 * ## Dois donos, um módulo — e a razão é o inventário fechado do `obs_lint`
 *
 * O `tools/obs_lint/tests/test_contar_metricas.py` prende o **conjunto nomeado**
 * dos módulos de métricas, e não uma contagem: um módulo novo aparece como nome
 * a mais e o *gate* 4 diz qual. A escolha mediu-se — `fraud_signals_total` cabe
 * aqui sem acrescentar módulo, e um `fraude/metricas.ts` novo custava a lista
 * fechada, a prosa de `docs/observabilidade.md` e a do `specs/EPIC-08`, que tem
 * um PR aberto ao lado. O preço é este comentário; a alternativa era um vermelho
 * numa suite que não é deste ticket.
 *
 * O atraso entre o evento de pagamento e o `order.paid` (KAM-055).
 *
 * É a métrica que a DoD do bloco pede («*lag* `payment→order.paid`») e o
 * instrumento do critério 9 («p95 ≤ 5 s em 100 eventos simulados»). A outra
 * metade da observabilidade — a DLQ de `payment.*` — **já existe e já está
 * classificada**: é o *gauge* `evt_dlq_open` do
 * `packages/core-ts/src/eventos/metricas.ts`, publicado pelo `publicarAbertas`
 * a partir da ligação de operação, e o `payment.` está nos `PREFIXOS_SEV1` do
 * `dlq.ts`. Escrever aqui uma segunda contagem da DLQ era uma segunda fonte
 * para um número que já tem uma.
 *
 * ## Sem etiquetas, e isso é regra e não economia
 *
 * O `tenant_id`, o `event_id`, o `agregado_id` e o **`consumer`** não entram em
 * etiqueta nenhuma (`OBS-I` de `docs/seguranca/ameacas_stride.md`, e a nota do
 * `packages/core-ts/src/eventos/metricas.ts`). O que resta deste atraso não tem
 * eixo: é um histograma só. Um eixo por tenant dizia, a quem lê o painel, quem
 * paga e quando.
 *
 * ## O 5 está nos cortes de propósito
 *
 * O critério 9 pergunta «o p95 fica em 5 s?», e um histograma cujo corte mais
 * próximo fosse 3 ou 10 obrigava a interpolar entre dois cestos para responder.
 * É a mesma escolha que o `../../../../packages/core-ts/src/sms/metricas.ts`
 * fez com os 30 s do seu alvo.
 */

import { REGRAS } from "@kamba/core-ts/pagamentos";

/** O nome da métrica. `_seconds` porque a unidade é o segundo. */
export const METRICA_LAG = "com_payment_to_paid_seconds";

/** Os cortes, em segundos. O 5 é o alvo do critério 9. */
export const CORTES_DO_LAG: readonly number[] = [0.5, 1, 2, 5, 10, 30, 60, 300];

/** `[tipo, ajuda]` da métrica, para o formato de exposição. */
export const AJUDA: readonly [string, string] = [
  "histogram",
  "atraso entre o ocorrido_em do evento de pagamento e o order.paid, em segundos",
];

export const TIPO_DE_CONTEUDO = "text/plain; version=0.0.4; charset=utf-8";

/**
 * O histograma do atraso. Uma instância por processo.
 *
 * Classe e não módulo com estado solto para que os ensaios possam ter a sua: um
 * contador global partilhado entre ensaios dava a cada um o resíduo do
 * anterior, e isso é um verde que depende da ordem de execução.
 */
export class Lag {
  readonly #baldes = new Map<number, number>();
  #soma = 0;
  #contagem = 0;

  /**
   * Observa um atraso em segundos.
   *
   * Um valor não finito **não entra** — um `NaN` no formato de exposição faz o
   * Prometheus descartar a recolha toda —, e um negativo também não: um atraso
   * negativo é um relógio ao contrário, não um evento rápido. É a lição que o
   * KAM-017 escreveu e que o `sms/metricas.ts` repete.
   */
  observar(segundos: number): void {
    if (!Number.isFinite(segundos) || segundos < 0) return;
    this.#soma += segundos;
    this.#contagem += 1;
    for (const corte of CORTES_DO_LAG) {
      if (segundos <= corte) {
        this.#baldes.set(corte, (this.#baldes.get(corte) ?? 0) + 1);
      }
    }
  }

  get contagem(): number {
    return this.#contagem;
  }

  /** Quantas observações caíram em `<= corte`. Para os ensaios e para o p95. */
  balde(corte: number): number {
    return this.#baldes.get(corte) ?? 0;
  }

  /**
   * O p95 lido do histograma: o menor corte que cobre 95% das observações.
   *
   * Devolve `null` sem observações, e `null` também quando nem o corte mais
   * alto cobre os 95% — que é «passou de 300 s» e não «está bem». Um número
   * inventado para o caso vazio era pior do que a ausência dele: o critério 9
   * compara-o com 5, e um zero passava.
   */
  p95(): number | null {
    if (this.#contagem === 0) return null;
    const alvo = this.#contagem * 0.95;
    for (const corte of CORTES_DO_LAG) {
      if (this.balde(corte) >= alvo) return corte;
    }
    return null;
  }

  /** O formato de exposição do Prometheus. */
  exposicao(): string {
    const linhas = [
      `# HELP ${METRICA_LAG} ${AJUDA[1]}`,
      `# TYPE ${METRICA_LAG} ${AJUDA[0]}`,
    ];
    for (const corte of CORTES_DO_LAG) {
      linhas.push(`${METRICA_LAG}_bucket{le="${corte}"} ${this.balde(corte)}`);
    }
    linhas.push(`${METRICA_LAG}_bucket{le="+Inf"} ${this.#contagem}`);
    linhas.push(`${METRICA_LAG}_sum ${this.#soma}`);
    linhas.push(`${METRICA_LAG}_count ${this.#contagem}`);
    return `${linhas.join("\n")}\n`;
  }
}

/** A instância do processo. Os ensaios constroem a sua. */
export const LAG = new Lag();

// ------------------------------------------- os sinais de anomalia (KAM-060)

/** O nome da métrica que a DoD do KAM-060 nomeia, à letra. */
export const METRICA_SINAIS = "fraud_signals_total";

/** `[tipo, ajuda]` da métrica, para o formato de exposição. */
export const AJUDA_DOS_SINAIS: readonly [string, string] = [
  "counter",
  "sinais do motor de anomalias de pagamento, por regra",
];

/**
 * O nome da etiqueta. **`regra` e não `rule`**, porque é o nome da coluna
 * `platform.fraud_signals.regra` e o vocabulário desta casa é o do dicionário.
 */
export const ETIQUETA_DA_REGRA = "regra";

/**
 * O domínio fechado da etiqueta `regra`, que é o que a torna admissível.
 *
 * O `OBS-I` recusa **identificadores**, não **dimensões pequenas**: o
 * `ops/metricas/catalogo.yaml` escreve-o na linha da `channel_quality{rating}`,
 * e o `tools/obs_lint` exige que toda a etiqueta declare lista fechada ou tecto.
 * Oito valores, fixos no código das regras — nem `tenant_id`, nem `contact_id`,
 * nem `charge_id` entram aqui, e é por isso que esta métrica pode ter eixo onde
 * o histograma do atraso não pode.
 *
 * **Deriva do `REGRAS` e não é uma segunda lista.** Uma cópia literal ficava a
 * mentir no dia em que uma regra mudasse de nome, e o ensaio que a confrontasse
 * era mais um sítio a actualizar. O custo é a importação: este módulo passa a
 * depender de `@kamba/core-ts/pagamentos`, como o `./efeito.ts` já depende.
 */
export const REGRAS_CONHECIDAS: readonly string[] = REGRAS.map((r) => r.regra);

/**
 * A contagem de sinais por regra. Uma instância por processo.
 *
 * Classe e não estado solto pela razão do `Lag`: um contador global partilhado
 * entre ensaios dá a cada um o resíduo do anterior.
 */
export class Sinais {
  readonly #porRegra = new Map<string, number>();

  /**
   * Conta um sinal. **Uma regra desconhecida não entra**, e levanta.
   *
   * Aceitá-la abria a cardinalidade da etiqueta a qualquer cadeia que chegasse
   * — que é exactamente o que o domínio fechado do catálogo existe para impedir
   * —, e descartá-la em silêncio fazia uma regra nova nascer com a métrica a
   * zero para sempre. As duas falhas são piores do que esta excepção.
   */
  contar(regra: string): void {
    if (!REGRAS_CONHECIDAS.includes(regra)) {
      throw new RegraDesconhecida(regra);
    }
    this.#porRegra.set(regra, (this.#porRegra.get(regra) ?? 0) + 1);
  }

  total(regra: string): number {
    return this.#porRegra.get(regra) ?? 0;
  }

  /**
   * O formato de exposição.
   *
   * **Expõe as oito regras, incluindo as que estão a zero.** Uma série que só
   * aparece depois do primeiro sinal faz o painel mostrar «sem dados» onde a
   * leitura certa é «zero anomalias», e um alerta `increase(...) > 0` sobre uma
   * série que não existe nunca dispara — é o defeito que o catálogo nomeia.
   */
  exposicao(): string {
    const linhas = [
      `# HELP ${METRICA_SINAIS} ${AJUDA_DOS_SINAIS[1]}`,
      `# TYPE ${METRICA_SINAIS} ${AJUDA_DOS_SINAIS[0]}`,
    ];
    for (const regra of REGRAS_CONHECIDAS) {
      linhas.push(
        `${METRICA_SINAIS}{${ETIQUETA_DA_REGRA}="${regra}"} ${this.total(regra)}`,
      );
    }
    return `${linhas.join("\n")}\n`;
  }
}

export class RegraDesconhecida extends Error {
  override readonly name = "RegraDesconhecida";

  constructor(regra: string) {
    super(
      `a regra '${regra}' não está no REGRAS do motor de anomalias: a ` +
        `etiqueta '${ETIQUETA_DA_REGRA}' tem domínio fechado em ` +
        "ops/metricas/catalogo.yaml, e uma regra nova entra lá antes de entrar " +
        "numa série",
    );
  }
}

/** A instância do processo. Os ensaios constroem a sua. */
export const SINAIS = new Sinais();
