/**
 * As métricas da lista de espera (KAM-095, critério 8; DoD: «métricas e
 * alertas nascem com o código», ADR-018).
 *
 * ```text
 * es_lista_espera_entradas{estado}          gauge    entradas por estado; «aguardando» é o tamanho da fila
 * es_lista_espera_espera_media_segundos     gauge    média de (vaga − entrada) dos concluídos na janela
 * es_lista_espera_convites_total{desfecho}  counter  convites enviados, aceites, recusados, expirados
 * es_vagas_concedidas_7d                    gauge    vagas dadas na janela de 7 dias (os «ES por semana»)
 * es_limite_7d{origem}                      gauge    o limite em vigor, com a origem
 * ```
 *
 * A taxa de convites aceites é `aceite / enviado` sobre o contador, e o «ES
 * por semana vs limite» é o par `es_vagas_concedidas_7d` / `es_limite_7d`. O
 * `es_onboardings_7d` do KAM-016 conta outra coisa — as tentativas de ligação
 * na base do GWY, incluindo as abandonadas — e fica ao lado, não substituído.
 *
 * **As etiquetas são domínios fechados** (`estado` 5, `desfecho` 4, `origem`
 * 2), e nenhuma leva caso nem *tenant* (`OBS-I`). A `origem` está no limite de
 * propósito: um painel que mostre 200 tem de mostrar ao lado se é
 * `nao_verificado`.
 */

import { ESTADOS_DA_ENTRADA, type Fotografia, ORIGENS_DO_LIMITE } from "./contrato.ts";

export const METRICA_ENTRADAS = "es_lista_espera_entradas";
export const METRICA_ESPERA_MEDIA = "es_lista_espera_espera_media_segundos";
export const METRICA_CONVITES = "es_lista_espera_convites_total";
export const METRICA_VAGAS_7D = "es_vagas_concedidas_7d";
export const METRICA_LIMITE_7D = "es_limite_7d";

/** Os desfechos de um convite, para o contador. */
export const DESFECHOS_DO_CONVITE = ["enviado", "aceite", "recusado", "expirado"] as const;

export type DesfechoDoConvite = (typeof DESFECHOS_DO_CONVITE)[number];

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_ENTRADAS]: ["gauge", "Entradas da lista de espera por estado; aguardando e o tamanho da fila."],
  [METRICA_ESPERA_MEDIA]: ["gauge", "Media da espera (da entrada a vaga) dos concluidos na janela, em segundos."],
  [METRICA_CONVITES]: ["counter", "Convites da lista de espera por desfecho."],
  [METRICA_VAGAS_7D]: ["gauge", "Vagas de Embedded Signup dadas na janela de 7 dias."],
  [METRICA_LIMITE_7D]: ["gauge", "Limite de clientes novos por 7 dias em vigor, com a origem."],
};

export class MetricasDaLista {
  readonly #entradas = new Map<string, number>(ESTADOS_DA_ENTRADA.map((e) => [e, 0]));
  readonly #convites = new Map<string, number>(DESFECHOS_DO_CONVITE.map((d) => [d, 0]));
  #esperaMedia: number | null = null;
  #vagas = 0;
  #limite: { maximo: number; origem: string } | null = null;

  /** Um desfecho de convite. */
  convite(desfecho: DesfechoDoConvite): void {
    this.#convites.set(desfecho, (this.#convites.get(desfecho) ?? 0) + 1);
  }

  /** Recalcula os *gauges* de uma fotografia. Idempotente. */
  actualizar(f: Fotografia): void {
    for (const e of ESTADOS_DA_ENTRADA) this.#entradas.set(e, f.porEstado[e]);
    this.#esperaMedia = f.esperaMediaSegundos;
    this.#vagas = f.concluidosNaJanela.length;
    this.#limite = { maximo: f.limite.maximo, origem: f.limite.origem };
  }

  entradas(estado: (typeof ESTADOS_DA_ENTRADA)[number]): number {
    return this.#entradas.get(estado) ?? 0;
  }

  convites(desfecho: DesfechoDoConvite): number {
    return this.#convites.get(desfecho) ?? 0;
  }

  /** O formato de exposição do Prometheus. Um valor desconhecido sai `NaN`, nunca zero. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`, `# TYPE ${nome} ${tipo}`);
      if (nome === METRICA_ENTRADAS) {
        for (const [e, n] of this.#entradas) linhas.push(`${nome}{estado="${e}"} ${n}`);
      } else if (nome === METRICA_CONVITES) {
        for (const [d, n] of this.#convites) linhas.push(`${nome}{desfecho="${d}"} ${n}`);
      } else if (nome === METRICA_ESPERA_MEDIA) {
        linhas.push(`${nome} ${this.#esperaMedia ?? "NaN"}`);
      } else if (nome === METRICA_VAGAS_7D) {
        linhas.push(`${nome} ${this.#vagas}`);
      } else {
        // Antes da primeira leitura o limite é desconhecido: `NaN` nas duas
        // origens, e nunca um zero que um alarme lesse como «tecto a zero».
        for (const o of ORIGENS_DO_LIMITE) {
          const valor = this.#limite === null ? "NaN" : this.#limite.origem === o ? String(this.#limite.maximo) : "NaN";
          linhas.push(`${nome}{origem="${o}"} ${valor}`);
        }
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}
