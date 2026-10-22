/**
 * As métricas do consentimento (KAM-022, DoD «Custo e observabilidade»).
 *
 *     consent_notice_sent_total   counter  avisos enviados
 *     consent_optout_total        counter  revogacoes de marketing («PARAR»)
 *     consent_accepted_ratio      gauge    aceites / avisos enviados
 *     consent_blocked_total       counter  mensagens que nao chegaram ao AGR, por accao
 *
 * As três primeiras são as que o DoD nomeia, pelos nomes dele. A quarta está
 * aqui pela razão que a `outbound_rate_limited_total` da emenda 1.21 e a
 * `channel_quality_event_total` da 1.27 escreveram: **barrar sem contar é
 * barrar em silêncio.** O critério 1 promete «0 invocações do AGR» e o 4 promete
 * «0 violações em 1.000 mensagens»; sem esta série, um painel não distingue «os
 * clientes estão todos a consentir» de «o gate está a barrar tudo porque não há
 * texto vigente» — e o segundo caso é uma loja muda, que é o pior desfecho
 * possível e o mais fácil de não notar.
 *
 * A forma é a do `qualidade/metricas.ts` e a do `metering/metricas.ts`: um `Map`
 * de números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus.
 *
 * ## O `consent_accepted_ratio` é um *gauge* derivado, e não uma terceira contagem
 *
 * O DoD nomeia-o. Ele é `aceites / avisos`, calculado na leitura a partir dos
 * dois contadores que já existem — e não uma série guardada, que podia divergir
 * deles. Vale `-1` antes do primeiro aviso, pela razão do
 * `messaging_limit_usage_ratio` do KAM-021: «não sei» não é «ninguém aceitou», e
 * um `0` ali fazia um painel acender um alarme no primeiro minuto de vida de
 * cada processo.
 *
 * ## Nenhuma leva `tenant_id`, e a decisão não é nova
 *
 * É a mesma da emenda 1.21 (KAM-015), repetida na 1.24 (KAM-023) e na 1.27
 * (KAM-021): as etiquetas têm de casar `^[a-z][a-z0-9_]{1,62}$` e um UUID com
 * hífenes **levanta**. Quem precisa do corte por *tenant* lê a base — e aqui a
 * base é a `consent_event`, que é append-only e tem a resposta exacta.
 *
 * **A etiqueta `accao` passa**, pela mesma razão que o `rating` do KAM-021: tem
 * seis valores fechados, nenhum cresce com o tráfego, e não é um identificador.
 */

import { ACCOES } from "./contrato.ts";

export const METRICA_AVISOS = "consent_notice_sent_total";
export const METRICA_OPTOUT = "consent_optout_total";
export const METRICA_BARRADAS = "consent_blocked_total";
export const METRICA_ACEITES = "consent_accepted_total";
export const METRICA_RACIO = "consent_accepted_ratio";

/**
 * Os contadores. O `consent_accepted_total` **não está no DoD** e existe porque
 * o `consent_accepted_ratio`, que está, precisa de um numerador — e um rácio
 * sem os dois números expostos é um número que ninguém pode verificar.
 */
export const CONTADORES = [
  METRICA_AVISOS,
  METRICA_OPTOUT,
  METRICA_BARRADAS,
  METRICA_ACEITES,
] as const;
export const GAUGES = [METRICA_RACIO] as const;

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;

/** As etiquetas, por métrica, com a lista fechada de valores. */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_BARRADAS]: { nome: "accao", valores: ACCOES },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_AVISOS]: [
    "counter",
    "Avisos de privacidade enviados. O criterio 1 pede exactamente um por primeiro contacto sem consentimento valido.",
  ],
  [METRICA_OPTOUT]: [
    "counter",
    "Revogacoes de marketing pelo PARAR. Obrigacao da Messaging Policy (E1 §4) e do Art. 19.o da Lei 22/11: falhar em reconhecer um opt-out e continuar a escrever a quem pediu para parar.",
  ],
  [METRICA_BARRADAS]: [
    "counter",
    "Mensagens que nao chegaram ao AGR, por accao do gate. Nao esta no DoD e entra porque barrar sem contar e barrar em silencio: sem ela, um painel nao distingue clientes a consentir de um gate a barrar tudo por nao haver texto vigente.",
  ],
  [METRICA_ACEITES]: [
    "counter",
    "Consentimentos aceites e registados. E o numerador do consent_accepted_ratio, e esta exposto para que o racio se possa verificar.",
  ],
  [METRICA_RACIO]: [
    "gauge",
    "Aceites por aviso enviado. Vale -1 antes do primeiro aviso: nao sei nao e ninguem aceitou.",
  ],
};

/** Uma métrica que não existe. Levanta, porque um nome errado é um defeito. */
export class MetricaDesconhecidaError extends Error {
  constructor(nome: string) {
    super(`metrica desconhecida: ${nome}`);
    this.name = "MetricaDesconhecidaError";
  }
}

/** Um sufixo de etiqueta fora da lista fechada. */
export class SufixoInvalidoError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(`o sufixo "${sufixo}" nao pertence a etiqueta de ${metrica}`);
    this.name = "SufixoInvalidoError";
  }
}

/** As métricas do consentimento. */
export class MetricasDoConsentimento {
  readonly #contadores = new Map<string, number>();

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

  /** O total de uma métrica, somando as séries com etiqueta. */
  #total(metrica: string): number {
    let soma = 0;
    for (const [chave, valor] of this.#contadores) {
      if (chave === metrica || chave.startsWith(`${metrica}:`)) soma += valor;
    }
    return soma;
  }

  /**
   * `aceites / avisos`, ou `-1` antes do primeiro aviso.
   *
   * **Não se limita a 1**, e isso é deliberado: o mesmo contacto pode aceitar
   * numa versão e voltar a aceitar na seguinte sem novo aviso pelo meio (ele
   * carregou no botão de um aviso antigo que ainda estava no telefone), e um
   * rácio acima de 1 é informação — é o sinal de que isso está a acontecer. É a
   * mesma escolha que o `racioDoFreeTier` do KAM-023 fez.
   */
  racio(): number {
    const avisos = this.#total(METRICA_AVISOS);
    if (avisos === 0) return -1;
    return this.#total(METRICA_ACEITES) / avisos;
  }

  ler(): Record<string, number> {
    return {
      ...Object.fromEntries(this.#contadores),
      [METRICA_RACIO]: this.racio(),
    };
  }

  repor(): void {
    this.#contadores.clear();
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * As cinco aparecem sempre: os contadores a zero e o rácio a `-1` quando nunca
   * houve aviso. A razão é a do `entrada/metricas.ts`: um painel que mostre «sem
   * dados» não distingue «nenhum contacto novo» de «o processo não arrancou».
   */
  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of [...CONTADORES, ...GAUGES]) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      if (nome === METRICA_RACIO) {
        linhas.push(`${nome} ${this.racio()}`);
        continue;
      }
      const chaves = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (chaves.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = ETIQUETAS[nome]?.nome;
      for (const chave of chaves) {
        const sufixo = chave.slice(nome.length + 1);
        const valor = this.#contadores.get(chave) ?? 0;
        linhas.push(
          sufixo === "" || etiqueta === undefined
            ? `${nome} ${valor}`
            : `${nome}{${etiqueta}="${sufixo}"} ${valor}`,
        );
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As métricas do consentimento. */
export const METRICAS_DO_CONSENTIMENTO = new MetricasDoConsentimento();
