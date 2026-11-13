/**
 * Os duplos de Trust & Safety para os ensaios (KAM-097).
 *
 * O repositório em memória **impõe as mesmas regras que a base** (revisão
 * `0053`): a chave de cada linha, a severidade fixa, a sanção grave só humana e
 * com caso, o desfecho de recurso só humano, o salto sem justificação recusado,
 * e o `kamba_app` sem linhas humanas. Um duplo mais permissivo do que a base
 * deixava passar nos ensaios o que a base recusa.
 */

import { randomUUID } from "node:crypto";

import type {
  EstadoDosTenants,
  RepositorioDeTrust,
  SancaoGravada,
  SancaoNova,
  SinalGravado,
  SinalNovo,
} from "./contrato.ts";
import { PASSOS_AUTOMATICOS, SEVERIDADE_DO_TIPO, ordem } from "./regras.ts";
import { emVigor } from "./servico.ts";

/** A mesma recusa que a base dá, com o mesmo `SQLSTATE`. */
export class RecusaDaBaseError extends Error {
  override readonly name = "RecusaDaBaseError";
  readonly codigo: string;
  constructor(codigo: string, mensagem: string) {
    super(mensagem);
    this.codigo = codigo;
  }
}

export class RepositorioDeTrustEmMemoria implements RepositorioDeTrust {
  readonly sinais: SinalGravado[] = [];
  readonly sancoes: SancaoGravada[] = [];
  /** O papel de quem escreve: `kamba_app` não escreve linhas humanas. */
  papel: "kamba_app" | "kamba_batch" = "kamba_batch";
  readonly #relogio: () => Date;

  constructor(relogio: () => Date = () => new Date()) {
    this.#relogio = relogio;
  }

  async gravarSinal(s: SinalNovo): Promise<{ readonly sinal: SinalGravado; readonly repetido: boolean }> {
    const e = this.sinais.find((x) => x.tenantId === s.tenantId && x.tipo === s.tipo && x.refEvento === s.refEvento);
    if (e !== undefined) return { sinal: e, repetido: true };
    const sinal: SinalGravado = { ...s, id: randomUUID(), severidade: SEVERIDADE_DO_TIPO[s.tipo] };
    this.sinais.push(sinal);
    return { sinal, repetido: false };
  }

  async sinaisDoTenant(tenantId: string): Promise<readonly SinalGravado[]> {
    return this.sinais.filter((x) => x.tenantId === tenantId);
  }

  async gravarSancao(s: SancaoNova): Promise<{ readonly sancao: SancaoGravada; readonly repetido: boolean }> {
    if (this.papel === "kamba_app" && (s.origem !== "automatica" || s.recursoDe !== null)) {
      throw new RecusaDaBaseError("42501", "o kamba_app so escreve sancoes automaticas");
    }
    if (s.motivoInterno.trim() === "") throw new RecusaDaBaseError("23514", "ts_sanction_motivo_interno_ck");
    if (s.origem === "automatica" && !PASSOS_AUTOMATICOS.includes(s.passo)) {
      throw new RecusaDaBaseError("23514", "ts_sanction_grave_humana_ck");
    }
    if (s.origem === "humana" && s.casoId === null) throw new RecusaDaBaseError("23514", "ts_sanction_humana_com_caso_ck");
    if ((s.recursoDe === null) !== (s.recursoEstado === null) || (s.recursoDe !== null && s.origem !== "humana")) {
      throw new RecusaDaBaseError("23514", "ts_sanction_recurso_ck");
    }
    const e = this.sancoes.find((x) => x.tenantId === s.tenantId && x.chave === s.chave);
    if (e !== undefined) return { sancao: e, repetido: true };
    if (s.recursoDe === null) {
      const vigor = emVigor(this.sancoes.filter((x) => x.tenantId === s.tenantId)).passo;
      if (ordem(s.passo) > ordem(vigor) + 1 && s.justificacaoDoSalto === null) {
        throw new RecusaDaBaseError("23514", "saltar passos da escada exige justificacao escrita");
      }
    }
    const sancao: SancaoGravada = { ...s, id: randomUUID(), em: this.#relogio() };
    this.sancoes.push(sancao);
    return { sancao, repetido: false };
  }

  async sancoesDoTenant(tenantId: string): Promise<readonly SancaoGravada[]> {
    return this.sancoes.filter((x) => x.tenantId === tenantId);
  }
}

/** O estado dos tenants em memória, com o CAS da base. */
export class EstadoDosTenantsEmMemoria implements EstadoDosTenants {
  readonly estados = new Map<string, string>();
  readonly transicoes: { readonly tenantId: string; readonly de: string; readonly para: string }[] = [];

  async estado(tenantId: string): Promise<string | null> {
    return this.estados.get(tenantId) ?? null;
  }

  async transitar(tenantId: string, de: readonly string[], para: string): Promise<boolean> {
    const actual = this.estados.get(tenantId);
    if (actual === undefined || !de.includes(actual)) return false;
    this.estados.set(tenantId, para);
    this.transicoes.push({ tenantId, de: actual, para });
    return true;
  }
}
