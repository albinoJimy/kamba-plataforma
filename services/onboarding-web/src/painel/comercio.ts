/**
 * O que o painel pede ao COM, e as duas maneiras de lho pedir (KAM-099).
 *
 *     ComercioPorHttp     a API interna do COM (`/internal/*`), em produção
 *     ComercioEmMemoria   o duplo de `dev`, de `staging` e das baterias
 *
 * ## O tenant é um argumento, e quem o passa é a sessão
 *
 * Cada método recebe o `tenantId` como **primeiro** argumento, e o único
 * chamador (`./rotas.ts`) passa-lhe o da sessão do painel. O adaptador HTTP
 * põe-no no `x-kamba-tenant`, que é o cabeçalho que o COM lê para montar o `ctx`
 * — e não lê de mais lado nenhum: não há campo do corpo nem parâmetro do caminho
 * por onde um pedido do navegador chegue a esse cabeçalho. É essa a ligação que
 * a bateria muta.
 *
 * ## Toda a escrita passa pelo COM, e o COM tem o CAS
 *
 * O painel **não** fala SQL e não tem cliente de base de dados (o
 * `package.json` deste serviço não tem `pg`). A escrita é o `update-offer` do
 * COM, que corre o `alterarOferta` do módulo `produtos`: CAS sobre o
 * `atualizado_at`, `audit_log` e `catalog.price_changed`/`stock.adjusted` na
 * mesma transacção.
 */

/** Os três modos de preço (dicionário §3.3, `preco_tipo`). */
export const PRECO_TIPOS = ["fixo", "a_partir_de", "sob_consulta"] as const;
export type PrecoTipo = (typeof PRECO_TIPOS)[number];

/**
 * Os estados de uma encomenda, pela ordem do dicionário §3.3.
 *
 * **Uma cópia da lista da porta do COM**, e é a única: o `onboarding-web` não
 * importa código de outro serviço (`lint_arch`). O ensaio deste serviço
 * confronta-a com o texto do `services/com/src/port/contrato.ts`.
 */
export const ESTADOS_DA_ENCOMENDA = [
  "criada",
  "aguarda_pagamento",
  "pendente_confirmacao",
  "paga",
  "expirada",
  "em_entrega",
  "entrega_falhada",
  "entregue",
  "em_disputa",
  "reembolso_pendente",
  "reembolsada",
  "cancelada",
] as const;
export type EstadoDaEncomenda = (typeof ESTADOS_DA_ENCOMENDA)[number];

/** Uma oferta, como a lista do painel a mostra. */
export interface Oferta {
  readonly sku: string;
  readonly nome: string;
  readonly precoTipo: PrecoTipo;
  readonly precoMinor: bigint | null;
  readonly currency: string;
  readonly stockModo: string;
  readonly stockQuantidade: number | null;
  readonly stockReservada: number;
  readonly estado: string;
  readonly versao: string;
}

/** Uma encomenda, **sem telefone**: o contacto vai por `contactId`. */
export interface Encomenda {
  readonly orderId: string;
  readonly numeroPublico: string;
  readonly estado: EstadoDaEncomenda;
  readonly totalMinor: bigint;
  readonly currency: string;
  readonly criadoAt: string;
  readonly contactId: string;
}

/** O pedido de gravação, já validado pelo painel. */
export interface Alteracao {
  readonly sku: string;
  readonly precoTipo: PrecoTipo;
  readonly precoMinor: bigint | null;
  readonly stock?: number | undefined;
  readonly versao: string;
}

/** O resultado de uma chamada: os três casos do `Resultado` da porta. */
export type Resposta<T> =
  | { readonly tipo: "ok"; readonly valor: T }
  | { readonly tipo: "conflito"; readonly valor: T }
  | { readonly tipo: "erro"; readonly erro: string };

/** Quem pede: o dono, com o `onboarding_id` do caso como identificador. */
export interface Actor {
  readonly id: string;
  readonly traceId: string;
}

export interface Comercio {
  listarOfertas(tenantId: string, a: Actor): Promise<Resposta<{ itens: readonly Oferta[]; truncada: boolean }>>;
  alterarOferta(tenantId: string, a: Actor, alteracao: Alteracao): Promise<Resposta<Oferta>>;
  listarEncomendas(
    tenantId: string,
    a: Actor,
    filtro: { readonly estado: EstadoDaEncomenda; readonly cursor?: string | undefined },
  ): Promise<Resposta<{ itens: readonly Encomenda[]; proximo: string | null }>>;
  obterEncomenda(tenantId: string, a: Actor, orderId: string): Promise<Resposta<Encomenda>>;
}

// ------------------------------------------------------------ o adaptador HTTP

/** Os dois cabeçalhos da API interna do COM (dicionário §3.24 e §3.39). */
export const CABECALHO_INTERNO = "x-kamba-interno";
export const CABECALHO_TENANT = "x-kamba-tenant";

/** O tecto de uma chamada ao COM, em milissegundos. ***Proposta***: 5 s. */
export const TECTO_DO_COM_MS = 5_000;

type Buscar = (url: string, init: RequestInit) => Promise<Response>;

function minor(valor: unknown): bigint | null {
  if (valor === null || valor === undefined) return null;
  if (typeof valor === "string" && /^-?[0-9]+$/.test(valor)) return BigInt(valor);
  if (typeof valor === "number" && Number.isSafeInteger(valor)) return BigInt(valor);
  throw new Error("valor monetario ilegivel vindo do COM");
}

function oferta(bruto: Record<string, unknown>): Oferta {
  return {
    sku: String(bruto["sku"]),
    nome: String(bruto["nome"]),
    precoTipo: bruto["precoTipo"] as PrecoTipo,
    precoMinor: minor(bruto["precoMinor"]),
    currency: String(bruto["currency"]),
    stockModo: String(bruto["stockModo"]),
    stockQuantidade: bruto["stockQuantidade"] === null ? null : Number(bruto["stockQuantidade"]),
    stockReservada: Number(bruto["stockReservada"] ?? 0),
    estado: String(bruto["estado"]),
    versao: String(bruto["versao"]),
  };
}

function encomenda(bruto: Record<string, unknown>): Encomenda {
  return {
    orderId: String(bruto["orderId"]),
    numeroPublico: String(bruto["numeroPublico"]),
    estado: bruto["estado"] as EstadoDaEncomenda,
    totalMinor: minor(bruto["totalMinor"]) ?? 0n,
    currency: String(bruto["currency"]),
    criadoAt: String(bruto["criadoAt"]),
    contactId: String(bruto["contactId"]),
  };
}

/** Os erros do COM que o painel distingue. O resto é «indisponível». */
const ERROS_CONHECIDOS = new Set(["NOT_FOUND", "VALIDATION_ERROR", "TENANT_MISMATCH"]);

/**
 * A API interna do COM, por HTTP.
 *
 * Um `TENANT_MISMATCH` do COM vira `NOT_FOUND` aqui: para o dono, um recurso de
 * outro tenant **não existe** (critério 8, «404, não 403»), e distinguir os dois
 * era dizer-lhe que acertou num identificador alheio.
 */
export class ComercioPorHttp implements Comercio {
  readonly #base: string;
  readonly #credencial: string;
  readonly #buscar: Buscar;

  constructor(base: string, credencial: string, buscar: Buscar = (u, i) => fetch(u, i)) {
    this.#base = base.replace(/\/+$/, "");
    this.#credencial = credencial;
    this.#buscar = buscar;
  }

  async #chamar(rota: string, tenantId: string, a: Actor, corpo: Record<string, unknown>): Promise<Resposta<unknown>> {
    let r: Response;
    try {
      r = await this.#buscar(`${this.#base}${rota}`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          [CABECALHO_INTERNO]: this.#credencial,
          [CABECALHO_TENANT]: tenantId,
        },
        body: JSON.stringify({ ...corpo, actor: { kind: "dono", id: a.id }, trace_id: a.traceId }),
        signal: AbortSignal.timeout(TECTO_DO_COM_MS),
      });
    } catch {
      return { tipo: "erro", erro: "UPSTREAM_DOWN" };
    }
    let lido: unknown;
    try {
      lido = await r.json();
    } catch {
      return { tipo: "erro", erro: "UPSTREAM_DOWN" };
    }
    const c = (lido ?? {}) as Record<string, unknown>;
    if (c["tipo"] === "ok" || c["tipo"] === "conflito") {
      return { tipo: c["tipo"], valor: c["valor"] };
    }
    const codigo = typeof c["erro"] === "string" ? c["erro"] : "UPSTREAM_DOWN";
    if (codigo === "TENANT_MISMATCH") return { tipo: "erro", erro: "NOT_FOUND" };
    return { tipo: "erro", erro: ERROS_CONHECIDOS.has(codigo) ? codigo : "UPSTREAM_DOWN" };
  }

  async listarOfertas(tenantId: string, a: Actor) {
    const r = await this.#chamar("/internal/list-offers", tenantId, a, {});
    if (r.tipo !== "ok") return r as Resposta<never>;
    const v = r.valor as { itens: Record<string, unknown>[]; truncada: boolean };
    return { tipo: "ok" as const, valor: { itens: v.itens.map(oferta), truncada: v.truncada === true } };
  }

  async alterarOferta(tenantId: string, a: Actor, x: Alteracao) {
    const r = await this.#chamar("/internal/update-offer", tenantId, a, {
      sku: x.sku,
      preco_tipo: x.precoTipo,
      preco_minor: x.precoMinor === null ? null : x.precoMinor.toString(),
      versao: x.versao,
      ...(x.stock === undefined ? {} : { stock: x.stock }),
    });
    if (r.tipo === "erro") return r;
    return { tipo: r.tipo, valor: oferta(r.valor as Record<string, unknown>) };
  }

  async listarEncomendas(tenantId: string, a: Actor, f: { estado: EstadoDaEncomenda; cursor?: string | undefined }) {
    const r = await this.#chamar("/internal/list-orders", tenantId, a, {
      estado: f.estado,
      // O máximo do `listOrders` do KAM-044: o filtro de data é sobre esta página.
      limite: 100,
      ...(f.cursor === undefined ? {} : { cursor: f.cursor }),
    });
    if (r.tipo !== "ok") return r as Resposta<never>;
    const v = r.valor as { itens: Record<string, unknown>[]; proximo: string | null };
    return { tipo: "ok" as const, valor: { itens: v.itens.map(encomenda), proximo: v.proximo ?? null } };
  }

  async obterEncomenda(tenantId: string, a: Actor, orderId: string) {
    const r = await this.#chamar("/internal/get-order", tenantId, a, { order_id: orderId });
    if (r.tipo !== "ok") return r as Resposta<never>;
    return { tipo: "ok" as const, valor: encomenda(r.valor as Record<string, unknown>) };
  }
}

// ------------------------------------------------------------- o duplo

/** O microssegundo seguinte de uma versão. O `clock_timestamp()` do duplo. */
export function versaoSeguinte(versao: string): string {
  const [segundos, micro] = versao.slice(0, -1).split(".");
  return `${segundos}.${String(Number(micro) + 1).padStart(6, "0")}Z`;
}

/**
 * O COM em memória, **por tenant**. Para `dev`, `staging` e as baterias.
 *
 * Guarda as ofertas e as encomendas num mapa por tenant, e **só** lê do mapa do
 * tenant que recebe: um `sku` ou um `orderId` de outro tenant é `NOT_FOUND`,
 * como no COM. Conta as gravações, que é o que a bateria da idempotência mede.
 */
export class ComercioEmMemoria implements Comercio {
  readonly ofertas = new Map<string, Map<string, Oferta>>();
  readonly encomendas = new Map<string, Encomenda[]>();
  /** Gravações efectivas, por tenant e `sku`. */
  readonly gravacoes: { tenantId: string; sku: string; actor: string }[] = [];

  semear(tenantId: string, ofertas: readonly Oferta[], encomendas: readonly Encomenda[] = []): void {
    this.ofertas.set(tenantId, new Map(ofertas.map((o) => [o.sku, o])));
    this.encomendas.set(tenantId, [...encomendas]);
  }

  async listarOfertas(tenantId: string) {
    const itens = [...(this.ofertas.get(tenantId)?.values() ?? [])];
    return { tipo: "ok" as const, valor: { itens, truncada: false } };
  }

  async alterarOferta(tenantId: string, a: Actor, x: Alteracao): Promise<Resposta<Oferta>> {
    const doTenant = this.ofertas.get(tenantId);
    const antes = doTenant?.get(x.sku);
    if (doTenant === undefined || antes === undefined) return { tipo: "erro", erro: "NOT_FOUND" };
    if (antes.versao !== x.versao) return { tipo: "conflito", valor: antes };
    const depois: Oferta = {
      ...antes,
      precoTipo: x.precoTipo,
      precoMinor: x.precoMinor,
      versao: versaoSeguinte(antes.versao),
    };
    doTenant.set(x.sku, depois);
    this.gravacoes.push({ tenantId, sku: x.sku, actor: a.id });
    return { tipo: "ok", valor: depois };
  }

  async listarEncomendas(tenantId: string, _a: Actor, f: { estado: EstadoDaEncomenda }) {
    const itens = (this.encomendas.get(tenantId) ?? []).filter((e) => e.estado === f.estado);
    return { tipo: "ok" as const, valor: { itens, proximo: null } };
  }

  async obterEncomenda(tenantId: string, _a: Actor, orderId: string): Promise<Resposta<Encomenda>> {
    const e = (this.encomendas.get(tenantId) ?? []).find((x) => x.orderId === orderId);
    return e === undefined ? { tipo: "erro", erro: "NOT_FOUND" } : { tipo: "ok", valor: e };
  }
}
