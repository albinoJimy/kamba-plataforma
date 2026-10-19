/**
 * As duas metricas do TEN (KAM-009 criterio 7, ADR-018).
 *
 *     ten_limit_denied_total{key}          counter  consumos recusados pelo tecto
 *     ten_entitlement_denied_total{modulo} counter  acessos recusados por entitlement
 *
 * A forma e a do `eventos/metricas.ts` — um `Map` de numeros, em memoria, sem
 * dependencias, com `exposicao()` no formato do Prometheus — e a razao de ser a
 * mesma e que quem serve as metricas de um processo serve-as todas do mesmo
 * modo. Esta biblioteca nao abre portas: quem expoe `/metrics` e o servico.
 *
 * ## O `tenant_id` nao entra em etiqueta nenhuma, e nao e so uma regra escrita
 *
 * O `docs/seguranca/ameacas_stride.md` (`OBS-I`) diz porque: identificadores em
 * etiquetas explodem a cardinalidade e re-identificam. O X-11 do gate 6 varre
 * os registos a procura de identificadores, e uma etiqueta e tao legivel como
 * uma linha de registo.
 *
 * Aqui a regra e imposta pela **gramatica**, e nao por uma lista de nomes
 * proibidos: uma etiqueta tem de casar `^[a-z][a-z0-9_]{1,62}$`. Um UUID
 * canonico tem hifenes e comeca frequentemente por um digito — nao casa, e a
 * chamada levanta. Uma lista de proibidos protegia contra os nomes que alguem
 * se lembrou de escrever; a gramatica protege contra a forma.
 *
 * ## Porque e que as etiquetas nao sao uma lista fechada
 *
 * O `eventos/metricas.ts` fecha os sufixos numa lista (`DESFECHOS`, `MOTIVOS`)
 * porque os desfechos de uma publicacao sao quatro e nunca mais serao outros.
 * As chaves de limite e os modulos **nao** sao desse tipo: o registo de chaves
 * cresce com os tickets (`registry/entitlement_keys.schema.json`) e os modulos
 * com as verticais do `registry/*.yaml`. Uma lista fechada aqui obrigava esta
 * biblioteca a importar o registo, e a falhar sempre que o registo andasse a
 * frente dela.
 *
 * O que substitui a lista fechada e o par gramatica + **tecto** de series
 * (`MAXIMO_DE_SERIES`), que e exactamente o que o `medirPorTipo` do
 * `eventos/metricas.ts` ja faz para o `evt_dlq_open{tipo}`. Acima do tecto,
 * levanta: e melhor uma metrica que falha alto do que um painel que cresce sem
 * fim.
 */

/** Consumos recusados porque o tecto nao chegava. Etiqueta: a chave. */
export const METRICA_LIMITE_NEGADO = "ten_limit_denied_total";

/** Acessos recusados porque o entitlement nao permite. Etiqueta: o modulo. */
export const METRICA_ENTITLEMENT_NEGADO = "ten_entitlement_denied_total";

/**
 * A gramatica de uma etiqueta. E a mesma do `CHECK` de
 * `tenant_usage.chave_limite` e da de `entitlements.modulo` na `0001`, com um
 * tecto de comprimento acrescentado: uma chave de 4 KB nao e uma chave.
 */
export const ETIQUETA = /^[a-z][a-z0-9_]{1,62}$/;

/** Quantas series se aceitam por metrica antes de desistir. */
export const MAXIMO_DE_SERIES = 64;

const AJUDA: Record<string, [string, string]> = {
  [METRICA_LIMITE_NEGADO]: [
    "counter",
    "Consumos recusados pelo tecto do plano, por chave de limite.",
  ],
  [METRICA_ENTITLEMENT_NEGADO]: [
    "counter",
    "Acessos recusados por entitlement inactivo ou estado do tenant, por modulo.",
  ],
};

/** Como se chama a etiqueta de cada metrica no formato de exposicao. */
const NOME_DA_ETIQUETA: Record<string, string> = {
  [METRICA_LIMITE_NEGADO]: "key",
  [METRICA_ENTITLEMENT_NEGADO]: "modulo",
};

/** Uma etiqueta que nao casa a gramatica. Um `tenant_id` cai sempre aqui. */
export class EtiquetaInvalidaError extends Error {
  constructor(metrica: string, etiqueta: string) {
    super(
      `${metrica}: etiqueta ${JSON.stringify(etiqueta)} nao casa ` +
        "^[a-z][a-z0-9_]{1,62}$. Identificadores (tenant_id, contact_id) nao " +
        "entram em metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "EtiquetaInvalidaError";
  }
}

/** Contadores em memoria. So numeros. */
export class MetricasDoTen {
  readonly #contadores = new Map<string, number>();

  /** Soma `quanto` (1 por omissao) ao contador da etiqueta. */
  contar(metrica: string, etiqueta: string, quanto = 1): void {
    if (NOME_DA_ETIQUETA[metrica] === undefined) {
      throw new EtiquetaInvalidaError(metrica, etiqueta);
    }
    if (typeof etiqueta !== "string" || !ETIQUETA.test(etiqueta)) {
      throw new EtiquetaInvalidaError(metrica, String(etiqueta));
    }
    const nome = `${metrica}:${etiqueta}`;
    if (!this.#contadores.has(nome)) {
      const prefixo = `${metrica}:`;
      let series = 0;
      for (const chave of this.#contadores.keys()) {
        if (chave.startsWith(prefixo)) series += 1;
      }
      if (series >= MAXIMO_DE_SERIES) {
        throw new RangeError(
          `${metrica}: ${MAXIMO_DE_SERIES} series e o tecto, e ${etiqueta} seria mais uma. ` +
            "Uma metrica que cresce sem fim deixa de ser observabilidade.",
        );
      }
    }
    this.#contadores.set(nome, (this.#contadores.get(nome) ?? 0) + quanto);
  }

  ler(): Record<string, number> {
    return Object.fromEntries(this.#contadores);
  }

  repor(): void {
    this.#contadores.clear();
  }

  /**
   * Formato de exposicao do Prometheus.
   *
   * As duas metricas aparecem sempre, mesmo a zero: um painel que mostre «sem
   * dados» nao distingue «ninguem foi recusado» de «o processo nao arrancou».
   * E a mesma escolha do `eventos/metricas.ts`.
   */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`);
      linhas.push(`# TYPE ${nome} ${tipo}`);
      const series = [...this.#contadores.keys()]
        .filter((chave) => chave.startsWith(`${nome}:`))
        .sort();
      if (series.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = NOME_DA_ETIQUETA[nome] ?? "etiqueta";
      for (const chave of series) {
        linhas.push(
          `${nome}{${etiqueta}="${chave.slice(nome.length + 1)}"} ` +
            `${this.#contadores.get(chave) ?? 0}`,
        );
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As metricas do processo. */
export const METRICAS = new MetricasDoTen();
