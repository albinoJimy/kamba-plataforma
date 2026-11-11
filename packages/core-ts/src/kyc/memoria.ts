/**
 * Duplos em memória das portas do KYC (KAM-087), para ensaios e para correr
 * o módulo sem base.
 *
 * O repositório reafirma as duas restrições que o SQL tem — a unicidade de
 * `(onboarding_id, sha256)` e a comparação de `phash` só contra **outros**
 * casos — pela razão escrita na `../inscricao/contrato.ts`: uma restrição que
 * só existe no SQL é uma que o duplo não tem, e os ensaios passavam contra o
 * duplo e falhavam contra a base.
 */

import { randomUUID } from "node:crypto";

import { hamming } from "./forense.ts";
import type {
  CasoDoKyc,
  CasosDoKyc,
  FilaDeRevisao,
  Marca,
  Recomendacao,
  RepositorioDeVerificacoes,
  Resultado,
  Verificacao,
  VerificacaoNova,
} from "./contrato.ts";
import { FASES_PURGAVEIS, type CasosMortos } from "./servico.ts";

export class VerificacoesEmMemoria implements RepositorioDeVerificacoes {
  readonly linhas: Verificacao[] = [];
  readonly #relogio: () => Date;

  constructor(relogio: () => Date = () => new Date()) {
    this.#relogio = relogio;
  }

  async porSha(onboardingId: string, sha256: string): Promise<Verificacao | null> {
    return this.linhas.find((v) => v.onboardingId === onboardingId && v.sha256 === sha256) ?? null;
  }

  async inserir(nova: VerificacaoNova): Promise<{ verificacao: Verificacao; repetida: boolean }> {
    const ja = await this.porSha(nova.onboardingId, nova.sha256);
    if (ja !== null) return { verificacao: ja, repetida: true };
    const v: Verificacao = { ...nova, id: randomUUID(), score: null, criadoEm: this.#relogio() };
    this.linhas.push(v);
    return { verificacao: v, repetida: false };
  }

  async doCaso(onboardingId: string): Promise<readonly Verificacao[]> {
    return this.linhas.filter((v) => v.onboardingId === onboardingId);
  }

  async phashVistoNoutroCaso(onboardingId: string, phash: string, maximo: number): Promise<boolean> {
    return this.linhas.some(
      (v) => v.onboardingId !== onboardingId && v.phash !== null && hamming(v.phash, phash) <= maximo,
    );
  }

  async decidir(ids: readonly string[], resultado: Resultado, score: number): Promise<void> {
    for (let i = 0; i < this.linhas.length; i++) {
      const v = this.linhas[i]!;
      if (ids.includes(v.id)) this.linhas[i] = { ...v, resultado, score };
    }
  }

  async custoDoCaso(onboardingId: string): Promise<number> {
    return this.linhas.filter((v) => v.onboardingId === onboardingId).reduce((s, v) => s + v.custoMicroUsd, 0);
  }

  /** O `esquecer` da purga, para o duplo de `CasosMortos`. */
  esquecer(ids: readonly string[]): void {
    for (let i = 0; i < this.linhas.length; i++) {
      const v = this.linhas[i]!;
      if (ids.includes(v.id)) this.linhas[i] = { ...v, extraidoCifrado: null };
    }
  }
}

/** Um caso com a data em que entrou na fase actual (`fase_at`). */
export interface CasoEmMemoria extends CasoDoKyc {
  readonly faseEm: Date;
}

export class CasosEmMemoria implements CasosDoKyc, CasosMortos {
  readonly casos = new Map<string, CasoEmMemoria>();
  readonly #verificacoes: VerificacoesEmMemoria;
  readonly #relogio: () => Date;

  constructor(verificacoes: VerificacoesEmMemoria, relogio: () => Date = () => new Date()) {
    this.#verificacoes = verificacoes;
    this.#relogio = relogio;
  }

  juntar(caso: Omit<CasoEmMemoria, "faseEm"> & { readonly faseEm?: Date }): void {
    this.casos.set(caso.id, { ...caso, faseEm: caso.faseEm ?? this.#relogio() });
  }

  async porId(id: string): Promise<CasoDoKyc | null> {
    return this.casos.get(id) ?? null;
  }

  async marcarFase(id: string, fase: "rejeitado" | "em_revisao"): Promise<boolean> {
    const c = this.casos.get(id);
    if (c === undefined) return false;
    this.casos.set(id, { ...c, fase, faseEm: this.#relogio() });
    return true;
  }

  async mortosAte(limite: Date): Promise<readonly { onboardingId: string; tenantId: string }[]> {
    return [...this.casos.values()]
      .filter((c) => FASES_PURGAVEIS.includes(c.fase) && c.faseEm <= limite)
      .map((c) => ({ onboardingId: c.id, tenantId: c.tenantId }));
  }

  async esquecer(ids: readonly string[]): Promise<void> {
    this.#verificacoes.esquecer(ids);
  }
}

export class FilaEmMemoria implements FilaDeRevisao {
  readonly pedidos: {
    onboardingId: string;
    score: number;
    marcas: readonly Marca[];
    recomendacao: Recomendacao;
  }[] = [];

  async enviar(p: {
    onboardingId: string;
    score: number;
    marcas: readonly Marca[];
    recomendacao: Recomendacao;
  }): Promise<void> {
    this.pedidos.push({ ...p });
  }
}
