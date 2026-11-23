/**
 * As métricas de Trust & Safety (KAM-200, critério 3; DoD do KAM-097: «métricas
 * e alertas nascem com o código», ADR-018).
 *
 * ```text
 * ts_sinais_total{tipo}             counter  sinais novos gravados, por tipo
 * ts_sancoes_total{passo,origem}    counter  passos novos da escada, por passo e origem
 * ts_varreduras_total{varredura,desfecho}  counter  corridas das varreduras do lote
 * ts_ofertas_nao_avaliadas{motivo}  gauge    ofertas publicadas que a varredura dos preços não avaliou (KAM-209)
 * ```
 *
 * **Contam o que é novo.** Um sinal ou uma sanção repetidos (a reentrega de um
 * evento, a mesma decisão reaplicada) não contam: a chave da base diz que já
 * existiam, e é o `ServicoDeTrust` que conta. O desfecho de um recurso **não**
 * é um passo, e não conta aqui. O sinal `mudanca_de_conta` nasce num *trigger*
 * (revisão `0067`) e conta-se na varredura que lhe abre o caso.
 *
 * **O limite, dito:** as varreduras contam depois do `COMMIT`; o consumidor
 * conta **dentro** da transacção do `consumir`, que não tem gancho depois dela.
 * Um efeito que grava e depois falha (outro sinal, o `COMMIT`) conta, desfaz-se,
 * e a reentrega conta outra vez. É raro — só uma falha a meio do efeito o
 * produz — e infla o alerta da escada no sentido que pede um humano a olhar.
 * shortcut: contagem antes do COMMIT no consumidor; revê-se quando o `consumir`
 * ganhar um gancho depois da transacção (ou um contador por `events_consumed`).
 *
 * **As etiquetas são domínios fechados** (`tipo` 10, `passo` 4, `origem` 2,
 * `varredura` 7, `desfecho` 2, `motivo` 2), e nenhuma leva tenant, sinal nem caso
 * (`OBS-I`). Qual tenant é lê-se da `ts_sanction`, por quem tem papel para isso.
 *
 * **Nascem a zero**: todas as séries saem desde o arranque, e uma regra de
 * alerta com `increase(...)` vê a primeira ocorrência (a lição do cabeçalho do
 * `infra/compose/prometheus/regras/kamba.yml`). Servidas pelo processo de lote
 * do onboarding (`services/onboarding-web/src/lote.ts`), onde correm o
 * consumidor, as varreduras e as decisões da fila.
 */

import { ORIGENS, type Origem } from "./contrato.ts";
import { PASSOS, TIPOS_DE_SINAL, type Passo, type TipoDeSinal } from "./regras.ts";

export const METRICA_SINAIS = "ts_sinais_total";
export const METRICA_SANCOES = "ts_sancoes_total";
export const METRICA_VARREDURAS = "ts_varreduras_total";
export const METRICA_NAO_AVALIADAS = "ts_ofertas_nao_avaliadas";

/**
 * Porque uma oferta publicada não se avaliou (KAM-209): sem categoria (as de
 * antes da revisão `0088`), ou com vinte referências de menos de três lojas.
 * Domínio da etiqueta `motivo`.
 */
export const MOTIVOS_DE_NAO_AVALIADA = ["sem_categoria", "poucas_lojas"] as const;
export type MotivoDeNaoAvaliada = (typeof MOTIVOS_DE_NAO_AVALIADA)[number];

/** As varreduras do lote. Domínio da etiqueta `varredura`. */
export const VARREDURAS = [
  "nao_entrega",
  "fotos",
  "encerramentos",
  "mudancas_de_conta",
  "pseudonimos",
  "compradores_do_dono",
  "precos",
] as const;
export type Varredura = (typeof VARREDURAS)[number];

/** O desfecho de uma corrida. Uma falha não pára as outras varreduras. */
export const DESFECHOS_DA_VARREDURA = ["concluida", "falhou"] as const;
export type DesfechoDaVarredura = (typeof DESFECHOS_DA_VARREDURA)[number];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_SINAIS]: ["counter", "Sinais de Trust & Safety novos, por tipo."],
  [METRICA_SANCOES]: ["counter", "Passos novos da escada de sancoes, por passo e origem."],
  [METRICA_VARREDURAS]: ["counter", "Corridas das varreduras de Trust & Safety, por desfecho."],
  [METRICA_NAO_AVALIADAS]: ["gauge", "Ofertas publicadas que a varredura dos precos nao avaliou, por motivo."],
};

/** O que o `ServicoDeTrust` e as varreduras contam. A `MetricasDoTrust` cumpre-a. */
export interface ContadoresDoTrust {
  sinal(tipo: TipoDeSinal): void;
  sancao(passo: Passo, origem: Origem): void;
}

export class MetricasDoTrust implements ContadoresDoTrust {
  readonly #sinais = new Map<string, number>(TIPOS_DE_SINAL.map((t) => [t, 0]));
  readonly #sancoes = new Map<string, number>(PASSOS.flatMap((p) => ORIGENS.map((o) => [`${p}|${o}`, 0] as const)));
  readonly #varreduras = new Map<string, number>(
    VARREDURAS.flatMap((v) => DESFECHOS_DA_VARREDURA.map((d) => [`${v}|${d}`, 0] as const)),
  );

  sinal(tipo: TipoDeSinal): void {
    // Um valor fora do domínio não abre série nova: a etiqueta é fechada.
    if (!this.#sinais.has(tipo)) return;
    this.#sinais.set(tipo, (this.#sinais.get(tipo) ?? 0) + 1);
  }

  sancao(passo: Passo, origem: Origem): void {
    const k = `${passo}|${origem}`;
    if (!this.#sancoes.has(k)) return;
    this.#sancoes.set(k, (this.#sancoes.get(k) ?? 0) + 1);
  }

  readonly #naoAvaliadas = new Map<string, number>(MOTIVOS_DE_NAO_AVALIADA.map((m) => [m, 0]));

  /**
   * As ofertas publicadas que a última volta da varredura dos preços não
   * avaliou, pelo motivo (KAM-209). Um *gauge*, e não um contador: é o tamanho
   * do que fica por avaliar, e desce quando um dono dá categoria a uma oferta ou
   * quando chegam referências de mais lojas.
   */
  ofertasNaoAvaliadas(motivo: MotivoDeNaoAvaliada, n: number): void {
    if (!this.#naoAvaliadas.has(motivo) || !Number.isSafeInteger(n) || n < 0) return;
    this.#naoAvaliadas.set(motivo, n);
  }

  varredura(v: Varredura, desfecho: DesfechoDaVarredura): void {
    const k = `${v}|${desfecho}`;
    if (!this.#varreduras.has(k)) return;
    this.#varreduras.set(k, (this.#varreduras.get(k) ?? 0) + 1);
  }

  /** O formato de exposição do Prometheus. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`, `# TYPE ${nome} ${tipo}`);
      if (nome === METRICA_SINAIS) {
        for (const [t, n] of this.#sinais) linhas.push(`${nome}{tipo="${t}"} ${n}`);
      } else if (nome === METRICA_SANCOES) {
        for (const [k, n] of this.#sancoes) {
          const [p, o] = k.split("|");
          linhas.push(`${nome}{passo="${p}",origem="${o}"} ${n}`);
        }
      } else if (nome === METRICA_NAO_AVALIADAS) {
        for (const [m, n] of this.#naoAvaliadas) linhas.push(`${nome}{motivo="${m}"} ${n}`);
      } else {
        for (const [k, n] of this.#varreduras) {
          const [v, d] = k.split("|");
          linhas.push(`${nome}{varredura="${v}",desfecho="${d}"} ${n}`);
        }
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}
