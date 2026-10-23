/**
 * As métricas do aviso ao dono (KAM-115, DoD «Custo e observabilidade»).
 *
 *     owner_notice_sent_total       counter    avisos entregues, por gatilho e canal
 *     owner_notice_latency_s        histogram  do evento ao aviso entregue
 *     owner_alt_contact_missing     gauge      tenants `ativo` sem contacto verificado
 *     owner_notice_suppressed_total counter    avisos recusados por nós, por motivo
 *     owner_notice_failed_total     counter    avisos que o fornecedor não entregou
 *
 * As três primeiras são as que o DoD nomeia. As outras duas entram pela razão
 * que a `outbound_rate_limited_total` da emenda 1.21 e a
 * `channel_quality_event_total` da 1.27 escreveram: **recusar sem contar é
 * recusar em silêncio.**
 *
 * E aqui isso é mais do que um princípio. Este módulo tem duas maneiras de um
 * aviso não chegar ao dono, e elas são opostas: **nós** recusámos (um limite de
 * frequência, um gatilho desconhecido) ou **o fornecedor** não entregou (um
 * *bounce*, uma rejeição). Sem as duas séries, um painel vê «o dono não foi
 * avisado» e não distingue a regra a funcionar do canal alternativo a estar
 * quebrado — que é a diferença entre não fazer nada e acordar alguém. O critério
 * 7 escreve-o por extenso: «nenhum aviso se perde em silêncio».
 *
 * ## Duas etiquetas, e é a primeira métrica desta casa com duas
 *
 * O DoD escreve `owner_notice_sent_total{gatilho,canal}`. Os módulos anteriores
 * têm uma etiqueta por métrica, e a `exposicao()` deles assume isso. Aqui há
 * duas, e **nenhuma é identificador**: o `gatilho` tem cinco valores fechados e
 * o `canal` dois. O produto são dez séries, fixas e conhecidas em tempo de
 * compilação — o `OBS-I` de `../../../../docs/seguranca/ameacas_stride.md`
 * recusa identificadores, não dimensões pequenas, e dez séries não são
 * cardinalidade.
 *
 * A chave interna junta-as por `|`, e o `|` não aparece em nenhum dos valores
 * (são duas listas fechadas de letras minúsculas). Um separador que pudesse
 * aparecer nos valores fazia `a|b,c` e `a,b|c` darem a mesma chave.
 *
 * ## Nenhuma leva etiqueta de *tenant*, e isto já custou duas vezes
 *
 * Um `tenant_id` é um UUID com hífenes e **levanta** na validação de etiquetas
 * (`^[a-z][a-z0-9_]{1,62}$`). Não é escolha deste módulo: é decisão escrita
 * (OBS-I), e o KAM-015 e o KAM-023 pagaram-na nos DoD deles. O
 * `owner_alt_contact_missing` é por isso um **número** e não uma série por
 * tenant: a pergunta que o critério 6 faz — «≥ 95% dos tenants `ativo` com
 * contacto verificado» — responde-se com dois números, quantos faltam e quantos
 * há, e não com uma série por loja.
 *
 * A forma é a do `../qualidade/metricas.ts` e a do `../coexistencia/metricas.ts`:
 * um `Map` de números, em memória, sem dependências, com `exposicao()` no
 * formato do Prometheus.
 */

import { CANAIS, GATILHOS, MOTIVOS_DE_FALHA, MOTIVOS_DE_SUPRESSAO } from "./contrato.ts";

export const METRICA_ENVIADOS = "owner_notice_sent_total";
export const METRICA_LATENCIA = "owner_notice_latency_s";
export const METRICA_SEM_CONTACTO = "owner_alt_contact_missing";
export const METRICA_SUPRIMIDOS = "owner_notice_suppressed_total";
export const METRICA_FALHADOS = "owner_notice_failed_total";

export const CONTADORES = [
  METRICA_ENVIADOS,
  METRICA_SUPRIMIDOS,
  METRICA_FALHADOS,
] as const;
export const GAUGES = [METRICA_SEM_CONTACTO] as const;
export const HISTOGRAMAS = [METRICA_LATENCIA] as const;

export type Contador = (typeof CONTADORES)[number];

/** O separador das duas etiquetas na chave interna. Ver a nota do módulo. */
const JUNTA = "|";

/**
 * As etiquetas de cada contador, com os valores que cada uma admite.
 *
 * Fechadas nos dois sentidos: o nome e a lista. É isto que faz um `sufixo`
 * errado levantar em vez de criar uma série nova — uma métrica que aceita
 * qualquer etiqueta é uma métrica que, no dia em que alguém lhe passe um
 * `tenant_id`, o publica.
 */
const ETIQUETAS: Readonly<
  Record<Contador, { readonly nomes: readonly string[]; readonly valores: readonly (readonly string[])[] }>
> = {
  [METRICA_ENVIADOS]: { nomes: ["gatilho", "canal"], valores: [GATILHOS, CANAIS] },
  [METRICA_SUPRIMIDOS]: {
    nomes: ["gatilho", "motivo"],
    // O `gatilho_desconhecido` e o unico caso em que o gatilho **nao** e um dos
    // cinco — e por definicao, porque e isso que ele diz. A etiqueta leva
    // `nenhum`, que esta na lista de propositio: sem ele, a recusa que o
    // criterio 1 manda («um gatilho fora da lista nao envia nada») era a unica
    // que nao se podia contar.
    valores: [[...GATILHOS, "nenhum"], MOTIVOS_DE_SUPRESSAO],
  },
  [METRICA_FALHADOS]: { nomes: ["canal", "motivo"], valores: [CANAIS, MOTIVOS_DE_FALHA] },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_ENVIADOS]: [
    "counter",
    "Avisos ao dono entregues pelo fornecedor, por gatilho e canal. Entregues e nao registados: um aviso que ficou pendente nao conta aqui.",
  ],
  [METRICA_SUPRIMIDOS]: [
    "counter",
    "Avisos que nao sairam por decisao nossa, por gatilho e motivo. Recusar sem contar e recusar em silencio, e esta serie e o que distingue a regra a funcionar do canal quebrado.",
  ],
  [METRICA_FALHADOS]: [
    "counter",
    "Avisos que o fornecedor nao entregou, por canal e motivo. O criterio 7: nenhum aviso se perde em silencio.",
  ],
  [METRICA_LATENCIA]: [
    "histogram",
    "Segundos do evento ao aviso entregue ao fornecedor. O alvo do criterio 3 e 5 min p95 (proposta), e o corte de 300 esta nos baldes para que o p95 se leia sem interpolar.",
  ],
  [METRICA_SEM_CONTACTO]: [
    "gauge",
    "Tenants ativo sem nenhum contacto alternativo verificado. Um numero e nao uma serie por tenant: um tenant_id e um UUID com hifenes e levanta na validacao de etiquetas (OBS-I).",
  ],
};

/**
 * Os cortes do histograma, em segundos.
 *
 * O **300** está lá por causa do critério 3: o alvo é «≤ 5 min p95», e um balde
 * exactamente nos 300 segundos faz a pergunta ler-se do histograma sem
 * interpolar entre dois cortes. Os cortes abaixo dizem o caminho normal (o
 * fornecedor responde em segundos) e os de cima dizem o quanto se passou do alvo
 * quando se passa. É a mesma escolha que os `CORTES_DA_DURACAO` do KAM-017
 * fizeram com as 12 h.
 */
export const CORTES_DA_LATENCIA: readonly number[] = [1, 5, 15, 30, 60, 120, 300, 600, 1_800];

/** Uma métrica que não existe. */
export class MetricaDesconhecidaError extends Error {
  override readonly name = "MetricaDesconhecidaError";

  constructor(metrica: string) {
    super(`metrica desconhecida: ${JSON.stringify(metrica)}`);
  }
}

/** Uma etiqueta que não está na lista fechada da sua métrica. */
export class SufixoInvalidoError extends Error {
  override readonly name = "SufixoInvalidoError";

  constructor(metrica: string, sufixo: readonly string[]) {
    super(
      `${metrica}: etiquetas ${JSON.stringify(sufixo)} nao estao na lista fechada. ` +
        "Identificadores (tenant_id, channel_id, phone_number_id) nao entram em " +
        "metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
  }
}

/** Contadores, *gauge* e histograma do aviso ao dono, em memória. Só números. */
export class MetricasDoAviso {
  readonly #contadores = new Map<string, number>();
  readonly #baldes = new Map<number, number>();
  #somaDaLatencia = 0;
  #contagemDaLatencia = 0;
  #semContacto = 0;
  #comContacto = 0;

  /**
   * Conta um evento numa das três séries de contador.
   *
   * As etiquetas são **posicionais e obrigatórias**: um contador desta família
   * tem duas, e aceitar uma só fazia `owner_notice_sent_total{gatilho="x"}`
   * conviver com `{gatilho="x",canal="email"}` na mesma recolha — o Prometheus
   * trata-as como séries diferentes e a soma deixa de ser o número de avisos.
   */
  contar(metrica: string, etiquetas: readonly string[], quanto = 1): void {
    if (!(CONTADORES as readonly string[]).includes(metrica)) {
      throw new MetricaDesconhecidaError(metrica);
    }
    const definicao = ETIQUETAS[metrica as Contador];
    if (etiquetas.length !== definicao.nomes.length) {
      throw new SufixoInvalidoError(metrica, etiquetas);
    }
    for (const [indice, valor] of etiquetas.entries()) {
      if (!definicao.valores[indice]?.includes(valor)) {
        throw new SufixoInvalidoError(metrica, etiquetas);
      }
    }
    const chave = `${metrica}${JUNTA}${etiquetas.join(JUNTA)}`;
    this.#contadores.set(chave, (this.#contadores.get(chave) ?? 0) + quanto);
  }

  /**
   * Observa a latência de um aviso entregue, em segundos.
   *
   * Um valor que não é finito não entra — um `NaN` no formato de exposição faz o
   * Prometheus descartar a recolha **toda** —, e um negativo também não: uma
   * latência negativa é um relógio ao contrário, e um histograma que a aceitasse
   * dava um `_sum` que não quer dizer nada. É a lição que o KAM-017 escreveu.
   */
  observarLatencia(segundos: number): void {
    if (!Number.isFinite(segundos) || segundos < 0) return;
    this.#somaDaLatencia += segundos;
    this.#contagemDaLatencia += 1;
    for (const corte of CORTES_DA_LATENCIA) {
      if (segundos <= corte) this.#baldes.set(corte, (this.#baldes.get(corte) ?? 0) + 1);
    }
  }

  /**
   * Observa a contagem de tenants `ativo` com e sem contacto verificado.
   *
   * **Os dois números, e não só o que falta.** O critério 6 pede «≥ 95% dos
   * tenants `ativo` com contacto verificado», e uma percentagem precisa de
   * denominador: com o numerador sozinho, «doze tenants sem contacto» não se
   * distingue de catástrofe nem de ruído. Publicam-se os dois e a razão lê-se
   * deles.
   */
  observarContactos(semContacto: number, comContacto: number): void {
    if (!Number.isInteger(semContacto) || semContacto < 0) return;
    if (!Number.isInteger(comContacto) || comContacto < 0) return;
    this.#semContacto = semContacto;
    this.#comContacto = comContacto;
  }

  ler(): Record<string, number> {
    return {
      ...Object.fromEntries(this.#contadores),
      [METRICA_SEM_CONTACTO]: this.#semContacto,
      [`${METRICA_SEM_CONTACTO}_total`]: this.#semContacto + this.#comContacto,
      [`${METRICA_LATENCIA}_sum`]: this.#somaDaLatencia,
      [`${METRICA_LATENCIA}_count`]: this.#contagemDaLatencia,
    };
  }

  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of CONTADORES) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      const series = [...this.#contadores.keys()]
        .filter((chave) => chave.startsWith(`${nome}${JUNTA}`))
        .sort();
      if (series.length === 0) {
        // Sem series, e **nao se escreve uma linha a zero**: com duas etiquetas
        // obrigatorias nao ha forma de escrever `nome 0` sem inventar valores
        // para elas, e uma serie inventada e pior do que nenhuma. O
        // `../coexistencia/metricas.ts` escreve o zero porque la a etiqueta e
        // opcional.
        continue;
      }
      const nomes = ETIQUETAS[nome].nomes;
      for (const chave of series) {
        const valores = chave.slice(nome.length + 1).split(JUNTA);
        const par = nomes.map((etiqueta, indice) => `${etiqueta}="${valores[indice] ?? ""}"`);
        linhas.push(`${nome}{${par.join(",")}} ${this.#contadores.get(chave) ?? 0}`);
      }
    }
    const latencia = AJUDA[METRICA_LATENCIA];
    if (latencia !== undefined) {
      linhas.push(`# HELP ${METRICA_LATENCIA} ${latencia[1]}`);
      linhas.push(`# TYPE ${METRICA_LATENCIA} ${latencia[0]}`);
      for (const corte of CORTES_DA_LATENCIA) {
        linhas.push(`${METRICA_LATENCIA}_bucket{le="${corte}"} ${this.#baldes.get(corte) ?? 0}`);
      }
      linhas.push(`${METRICA_LATENCIA}_bucket{le="+Inf"} ${this.#contagemDaLatencia}`);
      linhas.push(`${METRICA_LATENCIA}_sum ${this.#somaDaLatencia}`);
      linhas.push(`${METRICA_LATENCIA}_count ${this.#contagemDaLatencia}`);
    }
    const falta = AJUDA[METRICA_SEM_CONTACTO];
    if (falta !== undefined) {
      linhas.push(`# HELP ${METRICA_SEM_CONTACTO} ${falta[1]}`);
      linhas.push(`# TYPE ${METRICA_SEM_CONTACTO} ${falta[0]}`);
      linhas.push(`${METRICA_SEM_CONTACTO} ${this.#semContacto}`);
      linhas.push(`${METRICA_SEM_CONTACTO}_total ${this.#semContacto + this.#comContacto}`);
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** A instância do processo, como nos outros módulos desta casa. */
export const METRICAS_DO_AVISO = new MetricasDoAviso();
