/**
 * As métricas da ponte fila → consumidor Python (KAM-194).
 *
 *     evt_ponte_total{outcome}   counter  jobs tratados pela ponte, por desfecho
 *
 * A forma é a do `agr/metricas.ts`, que é a do `chr/metricas.ts`: um `Map` de
 * números, em memória, sem dependências, com `exposicao()` no formato do
 * Prometheus. Um módulo por domínio e não um registo central, pelo precedente
 * que o KAM-009 abriu — e um módulo à parte do `eventos/metricas.ts` porque
 * aquele é exposto pelo publicador e pelo consumidor TypeScript: juntar-lhe
 * esta série punha o processo da ponte a servir `evt_publish_total` a zero, e o
 * publicador a servir `evt_ponte_total` a zero, duas séries mortas num painel.
 *
 * ## Uma métrica, e nenhuma do consumo
 *
 * O que o consumidor Python fez com o evento — aplicado, duplicado, DLQ — é
 * dele, que é quem decide: o AGR conta-o em `agr_evt_consumidos_total`, e o IDX
 * regista a DLQ e o que não é 200 (`kamba_core.idx.__main__`), e a linha fica em
 * `events_dlq`. Repeti-lo aqui dava duas séries a contar a mesma coisa de dois
 * sítios. O que só este lado vê é **o que aconteceu ao *job***:
 *
 * - `entregue` — o consumidor respondeu 2xx e o *job* completou;
 * - `repetir` — o *job* lançou e volta à fila (503, outro 5xx, 429, rede,
 *   *timeout*). Conta **cada** tentativa falhada, e não cada evento;
 * - `recusado` — o *job* falhou sem repetição (400, 401, 3xx, outro 4xx).
 *   Qualquer valor aqui é configuração errada ou contrato divergente.
 *
 * ## Etiquetas: uma, e de lista fechada
 *
 * O `outcome` são os três desfechos acima, e não cresce com o tráfego. **Nenhuma
 * métrica leva `tenant_id`, `event_id`, `consumer` nem corpo**
 * (`docs/seguranca/ameacas_stride.md`, OBS-I): um valor fora da lista levanta,
 * em vez de abrir uma série nova.
 */

export const METRICA_PONTE = "evt_ponte_total";

/** Os valores do `outcome`. Lista fechada. */
export const DESFECHOS_DA_PONTE = ["entregue", "repetir", "recusado"] as const;
export type DesfechoDaPonte = (typeof DESFECHOS_DA_PONTE)[number];

const AJUDA: readonly [string, string] = [
  "counter",
  "Jobs evt.<consumer>.p<n> tratados pela ponte, por desfecho. recusado sustentado e alerta.",
];

/** Um desfecho que não está na lista fechada. A mensagem não o repete em claro. */
export class DesfechoDaPonteInvalidoError extends Error {
  constructor() {
    super(
      `${METRICA_PONTE}: o outcome nao esta na lista fechada ` +
        `(${DESFECHOS_DA_PONTE.join(", ")}). Identificadores (tenant_id, ` +
        "event_id, consumer) nao entram em metricas " +
        "(docs/seguranca/ameacas_stride.md, OBS-I)",
    );
    this.name = "DesfechoDaPonteInvalidoError";
  }
}

/** O contador da ponte, em memória. Só números. */
export class MetricasDaPonte {
  readonly #contadores = new Map<DesfechoDaPonte, number>();

  contar(desfecho: string, quanto = 1): void {
    if (!(DESFECHOS_DA_PONTE as readonly string[]).includes(desfecho)) {
      throw new DesfechoDaPonteInvalidoError();
    }
    const chave = desfecho as DesfechoDaPonte;
    this.#contadores.set(chave, (this.#contadores.get(chave) ?? 0) + quanto);
  }

  ler(): Readonly<Partial<Record<DesfechoDaPonte, number>>> {
    return Object.fromEntries(this.#contadores);
  }

  repor(): void {
    this.#contadores.clear();
  }

  exposicao(): string {
    const linhas = [
      `# HELP ${METRICA_PONTE} ${AJUDA[1]}`,
      `# TYPE ${METRICA_PONTE} ${AJUDA[0]}`,
    ];
    // Os três sempre, a zero quando nada aconteceu: um `recusado` que só
    // aparece no primeiro incidente não deixa escrever o alerta sobre um
    // `increase` que começa do nada.
    for (const desfecho of DESFECHOS_DA_PONTE) {
      linhas.push(
        `${METRICA_PONTE}{outcome="${desfecho}"} ${this.#contadores.get(desfecho) ?? 0}`,
      );
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** As métricas da ponte. */
export const METRICAS_DA_PONTE = new MetricasDaPonte();
