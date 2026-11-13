/**
 * As métricas da fila de revisão (KAM-089, critério 2 e 8; DoD: «métricas de
 * SLA e fila nascem com a funcionalidade», ADR-018).
 *
 * ```text
 * review_first_decision_p90_segundos        gauge  p90 do tempo útil até à 1.ª decisão
 * review_casos{tipo,estado}                 gauge  casos por tipo e estado
 * review_decisoes{tipo,decisao}             gauge  casos pela última decisão
 * review_falsos_aprovados_ratio             gauge  auditorias rejeitadas / auditorias decididas
 * ```
 *
 * O nome do critério é `review_first_decision_p90`; leva o sufixo da unidade
 * pela convenção do `docs/observabilidade.md`. O p90 é do **tempo útil** de
 * Luanda (`./sla.ts`), em segundos, entre a entrada na vista humana e a
 * primeira decisão gravada — a mesma régua do SLA, senão um caso aberto
 * sexta à noite contava o fim-de-semana contra o revisor.
 *
 * **As etiquetas são domínios fechados** (`tipo` 9, `estado` 7, `decisao` 4 e
 * `sem_decisao`), nenhuma leva tenant nem caso (`OBS-I`). Os contadores **por
 * motivo** vivem no `SQL_CONTADORES` (`./sql.ts`), por família de motivo: o
 * motivo não entra como etiqueta, porque `screening:<sha256>` dava uma série
 * por caso.
 *
 * **Recalculadas e servidas**: o *job* da fila (`./ciclo.ts`, KAM-196)
 * recalcula-as a cada volta, e o processo de lote do onboarding (KAM-198,
 * `services/onboarding-web/src/lote.ts`) serve a mesma instância em `/metrics`.
 */

import { DECISOES, ESTADOS, TIPOS_DE_CASO, type Decisao, type EstadoDoCaso, type TipoDeCaso } from "./contrato.ts";
import { percentil, tempoUtilEntre, type Feriados } from "./sla.ts";

export const METRICA_P90 = "review_first_decision_p90_segundos";
export const METRICA_CASOS = "review_casos";
export const METRICA_DECISOES = "review_decisoes";
export const METRICA_FALSOS_APROVADOS = "review_falsos_aprovados_ratio";

/** Uma linha da `v_review_sla`, na forma que as métricas lêem. */
export interface LinhaDaVista {
  readonly tipo: TipoDeCaso;
  readonly estado: EstadoDoCaso;
  readonly filaEm: Date;
  readonly primeiraDecisaoEm: Date | null;
}

/** Uma linha do `SQL_CONTADORES`. */
export interface Contador {
  readonly tipo: TipoDeCaso;
  readonly motivo: string;
  readonly decisao: Decisao | null;
  readonly n: number;
}

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_P90]: ["gauge", "p90 do tempo util (Luanda) ate a primeira decisao de um caso de revisao, em segundos."],
  [METRICA_CASOS]: ["gauge", "Casos de revisao por tipo e estado."],
  [METRICA_DECISOES]: ["gauge", "Casos de revisao pela ultima decisao."],
  [METRICA_FALSOS_APROVADOS]: ["gauge", "Auditorias de aprovacao automatica rejeitadas sobre as decididas."],
};

export class MetricasDaRevisao {
  #p90: number | null = null;
  #falsos: number | null = null;
  readonly #casos = new Map<string, number>();
  readonly #decisoes = new Map<string, number>();

  constructor() {
    this.#zerar();
  }

  #zerar(): void {
    for (const t of TIPOS_DE_CASO) {
      for (const e of ESTADOS) this.#casos.set(`${t}|${e}`, 0);
      for (const d of [...DECISOES, "sem_decisao"]) this.#decisoes.set(`${t}|${d}`, 0);
    }
  }

  /** Recalcula tudo de uma leitura. Idempotente: a mesma leitura dá a mesma exposição. */
  actualizar(vista: readonly LinhaDaVista[], contadores: readonly Contador[], feriados: Feriados): void {
    this.#zerar();
    const tempos: number[] = [];
    for (const l of vista) {
      this.#casos.set(`${l.tipo}|${l.estado}`, (this.#casos.get(`${l.tipo}|${l.estado}`) ?? 0) + 1);
      if (l.primeiraDecisaoEm !== null) tempos.push(tempoUtilEntre(l.filaEm, l.primeiraDecisaoEm, feriados) / 1000);
    }
    this.#p90 = percentil(tempos, 0.9);
    let aprovadas = 0;
    let rejeitadas = 0;
    for (const c of contadores) {
      const d = c.decisao ?? "sem_decisao";
      this.#decisoes.set(`${c.tipo}|${d}`, (this.#decisoes.get(`${c.tipo}|${d}`) ?? 0) + c.n);
      if (c.tipo === "auditoria" && c.decisao === "aprovar") aprovadas += c.n;
      if (c.tipo === "auditoria" && c.decisao === "rejeitar") rejeitadas += c.n;
    }
    this.#falsos = aprovadas + rejeitadas === 0 ? null : rejeitadas / (aprovadas + rejeitadas);
  }

  get p90(): number | null {
    return this.#p90;
  }

  get falsosAprovados(): number | null {
    return this.#falsos;
  }

  casos(tipo: TipoDeCaso, estado: EstadoDoCaso): number {
    return this.#casos.get(`${tipo}|${estado}`) ?? 0;
  }

  /** O formato de exposição do Prometheus. Um valor desconhecido sai `NaN`, nunca zero. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`, `# TYPE ${nome} ${tipo}`);
      if (nome === METRICA_P90) linhas.push(`${nome} ${this.#p90 ?? "NaN"}`);
      else if (nome === METRICA_FALSOS_APROVADOS) linhas.push(`${nome} ${this.#falsos ?? "NaN"}`);
      else if (nome === METRICA_CASOS) {
        for (const [chave, n] of this.#casos) {
          const [t, e] = chave.split("|");
          linhas.push(`${nome}{tipo="${t}",estado="${e}"} ${n}`);
        }
      } else {
        for (const [chave, n] of this.#decisoes) {
          const [t, d] = chave.split("|");
          linhas.push(`${nome}{tipo="${t}",decisao="${d}"} ${n}`);
        }
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}
