/**
 * Os duplos em memória da activação (KAM-094).
 *
 * São o que CI e `dev` usam, pela razão do `../guia/memoria.ts`. Cada um faz a
 * pergunta difícil, e não a fácil:
 *
 * * a `MaquinaEmMemoria` recusa o `activar` sem os seis gates **por ela
 *   própria**, como o `transition_tenant` da revisão 0058 — um duplo que
 *   activasse sempre fazia o caso adversarial (d) passar pelo duplo e não pelo
 *   serviço — e compara-e-escreve sem `await` pelo meio, para que dois
 *   `activar` seguidos dêem um evento;
 * * o `CatalogoEmMemoria` recusa publicar com `categoria_restrita`, como o
 *   `SQL_PUBLICAR`, e filtra por tenant em cada leitura, como a RLS;
 * * o `RegistoDoTesteEmMemoria` conta falhas **seguidas**: um `ok` pelo meio
 *   recomeça a contagem.
 */

import {
  type CasoDeActivacao,
  type CatalogoDoTenant,
  type CategoriaDoTenant,
  type CausaDoTeste,
  type FaseDoCaso,
  type FilaDoTeste,
  type GateDeActivacao,
  GATES_DE_ACTIVACAO,
  type GateDoKam094,
  type GatesDaActivacao,
  type MaquinaDoCaso,
  type MarcadorDeTeste,
  type ProdutoDoCatalogo,
  type RegistoDoTeste,
  type TentativaDoTeste,
} from "./contrato.ts";

export class CatalogoEmMemoria implements CatalogoDoTenant {
  readonly #linhas = new Map<string, ProdutoDoCatalogo>();

  #chave(tenantId: string, sku: string): string {
    return `${tenantId}|${sku}`;
  }

  /** Semeia ou substitui um produto. */
  semear(p: ProdutoDoCatalogo): void {
    this.#linhas.set(this.#chave(p.tenantId, p.sku), p);
  }

  ler(tenantId: string, sku: string): ProdutoDoCatalogo | undefined {
    return this.#linhas.get(this.#chave(tenantId, sku));
  }

  async produtos(tenantId: string): Promise<readonly ProdutoDoCatalogo[]> {
    return [...this.#linhas.values()].filter((p) => p.tenantId === tenantId);
  }

  async publicar(tenantId: string, sku: string): Promise<boolean> {
    const p = this.ler(tenantId, sku);
    if (p === undefined || p.apagado || p.categoriaRestrita !== null || p.estado === "arquivado") return false;
    this.semear({ ...p, estado: "publicado" });
    return true;
  }

  async retirar(tenantId: string, sku: string): Promise<boolean> {
    const p = this.ler(tenantId, sku);
    if (p === undefined || p.apagado) return false;
    if (p.estado === "publicado") this.semear({ ...p, estado: "rascunho" });
    return true;
  }

  async renomear(tenantId: string, sku: string, nome: string): Promise<boolean> {
    const p = this.ler(tenantId, sku);
    if (p === undefined || p.apagado) return false;
    this.semear({ ...p, nome });
    return true;
  }
}

export class CategoriaEmMemoria implements CategoriaDoTenant {
  readonly #por = new Map<string, string>();

  semear(tenantId: string, categoria: string): void {
    this.#por.set(tenantId, categoria);
  }

  async declarada(tenantId: string): Promise<string> {
    return this.#por.get(tenantId) ?? "";
  }
}

export class GatesEmMemoria implements GatesDaActivacao {
  readonly #linhas = new Map<string, Map<GateDeActivacao, { ok: boolean; evidencia: string }>>();

  /** Para semear os quatro gates que não são deste ticket. */
  semear(onboardingId: string, gate: GateDeActivacao, ok: boolean, evidencia = "ensaio"): void {
    const g = this.#linhas.get(onboardingId) ?? new Map();
    g.set(gate, { ok, evidencia });
    this.#linhas.set(onboardingId, g);
  }

  ler(onboardingId: string, gate: GateDeActivacao): { ok: boolean; evidencia: string } | undefined {
    return this.#linhas.get(onboardingId)?.get(gate);
  }

  async marcar(onboardingId: string, gate: GateDoKam094, ok: boolean, evidencia: string): Promise<void> {
    this.semear(onboardingId, gate, ok, evidencia);
  }

  emFaltaJa(onboardingId: string): GateDeActivacao[] {
    const g = this.#linhas.get(onboardingId);
    return GATES_DE_ACTIVACAO.filter((n) => g?.get(n)?.ok !== true);
  }

  async emFalta(onboardingId: string): Promise<readonly GateDeActivacao[]> {
    return this.emFaltaJa(onboardingId);
  }
}

/** A máquina do caso do KAM-092, nos dois eventos deste ticket. */
export class MaquinaEmMemoria implements MaquinaDoCaso {
  readonly #casos = new Map<string, CasoDeActivacao>();
  readonly #gates: GatesEmMemoria;
  /** Os eventos emitidos, por ordem: `tipo|tenant`. */
  readonly eventos: string[] = [];

  constructor(gates: GatesEmMemoria) {
    this.#gates = gates;
  }

  semear(caso: CasoDeActivacao): void {
    this.#casos.set(caso.onboardingId, caso);
  }

  async ler(onboardingId: string): Promise<CasoDeActivacao | null> {
    return this.#casos.get(onboardingId) ?? null;
  }

  async avancar(onboardingId: string, evento: "catalogo_minimo" | "activar", _actor: string): Promise<FaseDoCaso> {
    const caso = this.#casos.get(onboardingId);
    if (caso === undefined) throw new Error("caso de onboarding nao existe");
    const [de, para] = evento === "catalogo_minimo" ? ["aguarda_catalogo", "aguarda_teste"] : ["aguarda_teste", "activo"];
    if (caso.fase === para) return para;
    if (caso.fase !== de) throw new Error(`evento ${evento} recusado na fase ${caso.fase}`);
    if (evento === "activar") {
      const falta = this.#gates.emFaltaJa(onboardingId);
      if (falta.length > 0) throw new Error(`tenant sem os gates de activacao: ${falta.join(",")}`);
      this.eventos.push(`tenant.activated|${caso.tenantId}`);
    }
    this.#casos.set(onboardingId, { ...caso, fase: para });
    return para;
  }
}

export class FilaDoTesteEmMemoria implements FilaDoTeste {
  readonly abertos: { onboardingId: string; tipo: "es_falhado" | "saga"; causa: CausaDoTeste }[] = [];

  async abrir(onboardingId: string, tipo: "es_falhado" | "saga", causa: CausaDoTeste): Promise<void> {
    this.abertos.push({ onboardingId, tipo, causa });
  }
}

export class MarcadorEmMemoria implements MarcadorDeTeste {
  readonly marcadas = new Set<string>();

  async marcar(tenantId: string, conversationId: string): Promise<void> {
    this.marcadas.add(`${tenantId}|${conversationId}`);
  }
}

export class RegistoDoTesteEmMemoria implements RegistoDoTeste {
  readonly #tentativas = new Map<string, TentativaDoTeste[]>();
  readonly #zeradoEm = new Map<string, number>();

  async iniciar(onboardingId: string, iniciadaEm: Date, expiraEm: Date): Promise<TentativaDoTeste> {
    const t: TentativaDoTeste = { onboardingId, iniciadaEm, expiraEm, resultado: "pendente", causa: null };
    const lista = this.#tentativas.get(onboardingId) ?? [];
    lista.push(t);
    this.#tentativas.set(onboardingId, lista);
    return t;
  }

  async corrente(onboardingId: string): Promise<TentativaDoTeste | null> {
    return this.#tentativas.get(onboardingId)?.at(-1) ?? null;
  }

  async fechar(onboardingId: string, resultado: "ok" | "falhou", causa: CausaDoTeste | null): Promise<void> {
    const lista = this.#tentativas.get(onboardingId);
    const ultima = lista?.at(-1);
    if (lista === undefined || ultima === undefined || ultima.resultado !== "pendente") return;
    lista[lista.length - 1] = { ...ultima, resultado, causa };
  }

  async falhasSeguidas(onboardingId: string): Promise<number> {
    const lista = (this.#tentativas.get(onboardingId) ?? []).slice(this.#zeradoEm.get(onboardingId) ?? 0);
    let n = 0;
    for (let i = lista.length - 1; i >= 0; i--) {
      if (lista[i]!.resultado === "falhou") n += 1;
      else if (lista[i]!.resultado === "ok") break;
    }
    return n;
  }

  async zerar(onboardingId: string): Promise<void> {
    this.#zeradoEm.set(onboardingId, this.#tentativas.get(onboardingId)?.length ?? 0);
  }
}
