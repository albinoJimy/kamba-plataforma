/**
 * Duplos em memória da fila de revisão (KAM-089), para os ensaios e para o
 * `onboarding-web` fora de produção.
 *
 * O `FilaDeRevisaoEmMemoria` imita o que a base impõe: a chave de idempotência, a
 * transição só a partir do estado esperado, a tabela de transições do *trigger*
 * e o registo de decisões *append-only*. O que ele **não** imita é a RLS e os
 * privilégios — isso mede-se no `db/tests/test_revisao_schema.py`.
 */

import { randomUUID } from "node:crypto";

import {
  TRANSICOES,
  type CasoDeRevisao,
  type CasoNovo,
  type DecisaoNova,
  type DecisaoRegistada,
  type EstadoDoCaso,
  type FiltroDaFila,
  type OnboardingDaRevisao,
  type OnboardingsDaRevisao,
  type RegistoDeAuditoria,
  type RepositorioDeRevisao,
  type Sla,
} from "./contrato.ts";
import { ESTADOS_PENDENTES } from "./contrato.ts";

export class FilaDeRevisaoEmMemoria implements RepositorioDeRevisao {
  readonly casos = new Map<string, CasoDeRevisao>();
  readonly registo: DecisaoRegistada[] = [];
  /** A origem de cada onboarding, para a quota. Quem monta o duplo dá-a. */
  readonly #origem: (onboardingId: string) => string | null;
  readonly #agora: () => Date;

  constructor(origem: (onboardingId: string) => string | null = () => null, agora: () => Date = () => new Date()) {
    this.#origem = origem;
    this.#agora = agora;
  }

  async abrir(novo: CasoNovo): Promise<{ caso: CasoDeRevisao; repetido: boolean }> {
    for (const c of this.casos.values()) {
      if (
        c.tipo === novo.tipo &&
        c.tenantId === novo.tenantId &&
        c.onboardingId === novo.onboardingId &&
        c.motivoCodigo === novo.motivoCodigo
      ) {
        return { caso: c, repetido: true };
      }
    }
    const caso: CasoDeRevisao = {
      ...novo,
      evidencias: [...novo.evidencias],
      id: randomUUID(),
      slaAlertadoEm: null,
      criadoEm: this.#agora(),
    };
    this.casos.set(caso.id, caso);
    return { caso, repetido: false };
  }

  async porId(id: string): Promise<CasoDeRevisao | null> {
    return this.casos.get(id) ?? null;
  }

  async transitar(id: string, de: EstadoDoCaso, para: EstadoDoCaso, sla?: Sla & { filaEm?: Date }): Promise<boolean> {
    const c = this.casos.get(id);
    if (c === undefined || c.estado !== de) return false;
    if (!TRANSICOES[de].includes(para)) throw new Error(`transicao recusada: ${de} -> ${para}`);
    this.casos.set(id, {
      ...c,
      estado: para,
      ...(sla === undefined
        ? {}
        : { slaDueAt: sla.slaDueAt, slaAlertaAt: sla.slaAlertaAt, slaAlertadoEm: null, filaEm: sla.filaEm ?? c.filaEm }),
    });
    return true;
  }

  async registarDecisao(nova: DecisaoNova): Promise<DecisaoRegistada> {
    if (!this.casos.has(nova.casoId)) throw new Error("caso inexistente");
    const d: DecisaoRegistada = Object.freeze({ ...nova, id: randomUUID(), em: this.#agora() });
    this.registo.push(d);
    return d;
  }

  async decisoes(casoId: string): Promise<readonly DecisaoRegistada[]> {
    return this.registo.filter((d) => d.casoId === casoId);
  }

  async pendentesDoOnboarding(onboardingId: string): Promise<readonly CasoDeRevisao[]> {
    return [...this.casos.values()].filter(
      (c) => c.onboardingId === onboardingId && (ESTADOS_PENDENTES.includes(c.estado) || c.estado === "em_triagem_automatica"),
    );
  }

  async contarNaFilaDesde(origem: string | null, desde: Date): Promise<number> {
    return [...this.casos.values()].filter(
      (c) =>
        c.onboardingId !== null &&
        c.estado !== "em_triagem_automatica" &&
        c.filaEm.getTime() >= desde.getTime() &&
        this.#origem(c.onboardingId) === origem,
    ).length;
  }

  async emTriagem(limite: number): Promise<readonly CasoDeRevisao[]> {
    return [...this.casos.values()]
      .filter((c) => c.estado === "em_triagem_automatica")
      .sort((a, b) => a.criadoEm.getTime() - b.criadoEm.getTime())
      .slice(0, limite);
  }

  async alertasDevidos(agora: Date): Promise<readonly CasoDeRevisao[]> {
    return [...this.casos.values()].filter(
      (c) => ESTADOS_PENDENTES.includes(c.estado) && c.slaAlertadoEm === null && c.slaAlertaAt.getTime() <= agora.getTime(),
    );
  }

  async marcarAlertado(id: string, em: Date): Promise<void> {
    const c = this.casos.get(id);
    if (c !== undefined) this.casos.set(id, { ...c, slaAlertadoEm: em });
  }

  async pagina(filtro: FiltroDaFila, limite: number, depoisDe: number): Promise<readonly CasoDeRevisao[]> {
    return [...this.casos.values()]
      .filter((c) => c.estado !== "em_triagem_automatica")
      .filter((c) => filtro.tipo === undefined || c.tipo === filtro.tipo)
      .filter((c) => filtro.estado === undefined || c.estado === filtro.estado)
      .sort((a, b) => a.prioridade - b.prioridade || a.slaDueAt.getTime() - b.slaDueAt.getTime() || a.id.localeCompare(b.id))
      .slice(depoisDe, depoisDe + limite);
  }
}

/** Onboardings em memória, com o que a fila lê e as fases que ela marca. */
export class OnboardingsEmMemoria implements OnboardingsDaRevisao {
  readonly casos = new Map<string, OnboardingDaRevisao>();
  readonly fases: { readonly id: string; readonly fase: string }[] = [];

  async porId(id: string): Promise<OnboardingDaRevisao | null> {
    return this.casos.get(id) ?? null;
  }

  async marcarFase(id: string, fase: "aprovado" | "rejeitado" | "kyc_pendente"): Promise<boolean> {
    const c = this.casos.get(id);
    if (c === undefined) return false;
    this.casos.set(id, { ...c, fase });
    this.fases.push({ id, fase });
    return true;
  }
}

/** O `audit_log` em memória. */
export class AuditoriaEmMemoria {
  readonly linhas: RegistoDeAuditoria[] = [];

  async registar(r: RegistoDeAuditoria): Promise<void> {
    this.linhas.push(r);
  }
}
