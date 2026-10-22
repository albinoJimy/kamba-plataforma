/**
 * As métricas dos modos da conversa (KAM-018, DoD «Custo e observabilidade»,
 * ADR-018).
 *
 *     conv_mode_transitions_total  counter  transicoes, por gatilho
 *     conv_mode_rejected_total     counter  gatilhos rejeitados, por gatilho
 *     reply_suppressed_total       counter  envios do bot descartados, por motivo
 *
 * A forma é a do `chr/metricas.ts`, que é a do `entrada/metricas.ts`: um `Map`
 * de números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus. Um módulo por domínio e não um registo central, pelo precedente
 * que o KAM-009 abriu.
 *
 * ## São três, e o DoD nomeia três — mas não estas três
 *
 * O DoD pede `conv_mode_transitions_total`, `echo_latency_ms` e
 * `reply_suppressed_total`. Duas estão aqui; a terceira **não**, e não é
 * esquecimento:
 *
 * **`echo_latency_ms` fica de fora com o critério 8.** Ela mede a diferença
 * entre o carimbo da Meta e a recepção de um *echo*, e um *echo* só existe em
 * coexistência: a tabela `smb_message_echoes` é KAM-017 e os ≥ 30 *echoes* reais
 * que o critério 8 pede são números de *staging* com números +244 (R6/L6,
 * KAM-100). Uma métrica declarada e sempre a zero é pior do que uma métrica
 * ausente: um painel que a mostre a zero diz «a latência do *echo* é nula»
 * quando o que se passa é que ninguém a mede. Nasce com o ticket que consegue
 * medi-la.
 *
 * **E há uma a mais, a `conv_mode_rejected_total`.** É o único sítio onde
 * «qualquer outra transição é rejeitada» (critério 1) fica visível em produção.
 * Sem ela, a tabela de transições recusa em silêncio e um gatilho mal ligado —
 * um `comando_bot` disparado sobre uma conversa em `humano`, por exemplo —
 * parece-se exactamente com «não houve gatilho nenhum». É a mesma razão do
 * `chr_resolve_total` da emenda 1.20 e do `gwy_shed_total` da 1.19: recusar sem
 * contar é recusar em silêncio. Entra no dicionário declarada como acrescento
 * deste ticket e não como uma das três do DoD.
 *
 * ## Etiquetas: uma por métrica, e de lista fechada
 *
 * O `gatilho` tem oito valores (`GATILHOS`) e o `motivo` da supressão tem dois;
 * nenhum cresce com o tráfego. **Nenhuma métrica leva `tenant_id`,
 * `conversation_id` nem `contact_id`** (`docs/seguranca/ameacas_stride.md`,
 * OBS-I) — e no caso destas é mais do que cardinalidade: uma série por conversa
 * é um painel que diz quando é que cada cliente de cada loja falou com uma
 * pessoa.
 *
 * E **não há etiqueta de modo**, nem de origem nem de destino. A tentação é
 * óbvia (`conv_mode_transitions_total{de="bot",para="dono"}`) e a razão para a
 * recusar é a do `STATE_REFUSED` do KAM-021: o par (modo, gatilho) determina o
 * destino — é o que a `TABELA` é —, logo o `de`/`para` é informação que o
 * `gatilho` já tem, repartida por dezesseis séries em vez de oito. Quem precisa
 * da distribuição por modo lê `platform.conversations`, que é onde ela está.
 *
 * ## O que estas métricas **não** dão
 *
 * Percentis e histogramas: esta biblioteca não os implementa (ADR-018,
 * observabilidade leve no Piloto), e por isso não há aqui um `gauge` de duração.
 * O que o critério 6 pede medido em tempo — «o estado visível em HND em ≤ 5 s» —
 * mede-se onde tem significado, contra um Chatwoot real, e isso é KAM-019.
 */

import { GATILHOS } from "./contrato.ts";

export const METRICA_TRANSICOES = "conv_mode_transitions_total";
export const METRICA_REJEITADAS = "conv_mode_rejected_total";
export const METRICA_SUPRIMIDAS = "reply_suppressed_total";

/**
 * Porque é que um envio do bot foi descartado. Lista **fechada**: é etiqueta.
 *
 * `modo`              a conversa não estava em `bot` — há uma pessoa com a
 *                     palavra, e o invariante da §10.2 é que o bot não a
 *                     interrompe
 * `actividade_humana` a conversa estava em `bot` **e** houve actividade humana
 *                     depois do início do turno. É a corrida do §10.3: o
 *                     *echo* chegou depois de o turno começar e antes de a
 *                     resposta estar pronta
 *
 * **Dois e não um**, e a separação paga-se a si mesma: o primeiro é o caso
 * normal (uma conversa em atendimento humano, onde o bot não devia nem ter sido
 * invocado) e o segundo é a corrida que o ticket existe para fechar. Um painel
 * que os some não sabe se a janela de corrida está a ser atingida — que é
 * precisamente o que o R6/L6 fica à espera de medir.
 *
 * `sem_turno` é o terceiro, e é um defeito de ligação e não de tráfego: um envio
 * do bot que chega ao guarda sem dizer quando começou o turno. Ver
 * `guarda.ts`.
 */
export const MOTIVOS_DE_SUPRESSAO = ["modo", "actividade_humana", "sem_turno"] as const;
export type MotivoDeSupressao = (typeof MOTIVOS_DE_SUPRESSAO)[number];

/** Os contadores, pela ordem em que saem. Lista fechada. */
export const CONTADORES = [
  METRICA_TRANSICOES,
  METRICA_REJEITADAS,
  METRICA_SUPRIMIDAS,
] as const;
export type Contador = (typeof CONTADORES)[number];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_TRANSICOES]: [
    "counter",
    "Transicoes de modo de conversa, por gatilho (docs/tecnica/01 §10.2).",
  ],
  [METRICA_REJEITADAS]: [
    "counter",
    "Gatilhos recusados pela tabela de transicoes, por gatilho. Qualquer um e um gatilho mal ligado.",
  ],
  [METRICA_SUPRIMIDAS]: [
    "counter",
    "Envios do bot descartados pelo PreSendGuard, por motivo. sem_turno > 0 e defeito de ligacao.",
  ],
};

/** Que etiqueta cada contador aceita, e com que valores. Listas fechadas. */
const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_TRANSICOES]: { nome: "gatilho", valores: GATILHOS },
  [METRICA_REJEITADAS]: { nome: "gatilho", valores: GATILHOS },
  [METRICA_SUPRIMIDAS]: { nome: "motivo", valores: MOTIVOS_DE_SUPRESSAO },
};

const NOMES_DE_CONTADOR: readonly string[] = CONTADORES;

/** Um nome que não está na lista fechada. */
export class MetricaDesconhecidaError extends Error {
  constructor(metrica: string) {
    super(
      `${JSON.stringify(metrica)} nao e uma metrica dos modos de conversa. ` +
        `Contadores: ${CONTADORES.join(", ")}.`,
    );
    this.name = "MetricaDesconhecidaError";
  }
}

/** Um sufixo que não está na lista fechada da sua métrica. */
export class SufixoInvalidoError extends Error {
  constructor(metrica: string, sufixo: string) {
    super(
      `${metrica}: sufixo ${JSON.stringify(sufixo)} nao esta na lista fechada. ` +
        "Identificadores (tenant_id, conversation_id, contact_id) nao entram " +
        "em metricas (docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "SufixoInvalidoError";
  }
}

/** Contadores dos modos de conversa, em memória. Só números. */
export class MetricasDosModos {
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

  ler(): Record<string, number> {
    return Object.fromEntries(this.#contadores);
  }

  repor(): void {
    this.#contadores.clear();
  }

  /**
   * Formato de exposição do Prometheus.
   *
   * As três aparecem sempre, a zero quando nunca foram contadas. A escolha é a
   * do `chr/metricas.ts` e a razão é a mesma: um painel que mostre «sem dados»
   * não distingue «nenhuma supressão» de «o processo não arrancou».
   */
  exposicao(): string {
    const linhas: string[] = [];
    for (const nome of CONTADORES) {
      const descricao = AJUDA[nome];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${nome} ${descricao[1]}`);
      linhas.push(`# TYPE ${nome} ${descricao[0]}`);
      const series = [...this.#contadores.keys()]
        .filter((chave) => chave === nome || chave.startsWith(`${nome}:`))
        .sort();
      if (series.length === 0) {
        linhas.push(`${nome} 0`);
        continue;
      }
      const etiqueta = ETIQUETAS[nome]?.nome ?? "gatilho";
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

/** As métricas dos modos de conversa. */
export const METRICAS_DOS_MODOS = new MetricasDosModos();
