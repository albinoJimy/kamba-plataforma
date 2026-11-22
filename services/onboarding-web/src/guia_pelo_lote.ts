/**
 * As portas do guia que pedem `kamba_batch`, cumpridas pela rota interna do
 * processo de lote (KAM-239; decisão do fundador de 2026-11-22, A).
 *
 *     ListaPeloLote    o `CapacityGate` e as quatro da lista de espera
 *     GatesPeloLote    os dois *gates* do guia
 *     RevisaoPeloLote  o caso `es_falhado` na fila de revisão
 *
 * O `PassoGuiado` e as rotas do guia não mudam: recebem estas em vez dos duplos em
 * memória. **Síncronas, e é o motivo da escolha**: a reserva decide no mesmo pedido
 * se a página abre o popup ou mostra a lista, e o navegador só abre o popup perto
 * do clique.
 *
 * ## O que sai daqui
 *
 * Só o `onboarding_id` do caso da sessão e os campos que cada operação lê — o
 * convite do dono, o *gate*, a cor, o motivo. **Nunca um tenant**: o lote lê-o do
 * caso. A credencial vai no `x-kamba-interno`.
 *
 * ## O que volta, e como se lê
 *
 *     200   a resposta da operação
 *     409   `{ recusa }` da lista: volta a ser a `ListaRecusadaError` do motivo,
 *           que o `comSessao` traduz como traduzia
 *     outro o lote não respondeu como devia: `LoteIndisponivelError`, que o
 *           `comSessao` deixa subir (500). **Falha fechado**: uma reserva que não
 *           se sabe não abre o popup
 *
 * Um tecto de tempo por pedido (`TECTO_DO_LOTE_MS`): o dono está à espera.
 */

import {
  ListaRecusadaError,
  MOTIVOS_DE_RECUSA,
  type MotivoDeRecusa,
  type Posicao,
} from "@kamba/core-ts/capacidade";
import type {
  CapacityGate,
  FilaDeRevisao,
  GateDoEs,
  GatesDoOnboarding,
  MotivoDeFalha,
} from "@kamba/core-ts/guia";

import { CABECALHO_DO_LOTE, PREFIXO_DO_GUIA, type OperacaoDoGuia } from "./lote/interno.ts";

/** O tecto de cada pedido ao lote, em ms. ***Proposta***: uma operação é uma transacção curta. */
export const TECTO_DO_LOTE_MS = 5_000;

/** O lote não respondeu, ou respondeu fora do contrato. Ver a nota do módulo. */
export class LoteIndisponivelError extends Error {
  override readonly name = "LoteIndisponivelError";
  readonly operacao: OperacaoDoGuia;

  constructor(operacao: OperacaoDoGuia, motivo: string) {
    super(`o lote nao respondeu a ${operacao}: ${motivo}`);
    this.operacao = operacao;
  }
}

/** O que o `ClienteDoLote` precisa. */
export interface OpcoesDoClienteDoLote {
  /** O endereço da rota interna, sem barra final (`http://onboarding-lote-interno:3015`). */
  readonly base: string;
  /** A credencial, lida a cada pedido: roda. */
  readonly credencial: () => Promise<string>;
  /** O `fetch`. Porta para os ensaios. */
  readonly buscar?: typeof fetch;
}

/** O cliente das oito operações. */
export class ClienteDoLote {
  readonly #o: OpcoesDoClienteDoLote;
  readonly #buscar: typeof fetch;

  constructor(o: OpcoesDoClienteDoLote) {
    this.#o = o;
    this.#buscar = o.buscar ?? fetch;
  }

  async chamar(operacao: OperacaoDoGuia, corpo: Record<string, unknown>): Promise<Record<string, unknown>> {
    let resposta: Response;
    try {
      resposta = await this.#buscar(`${this.#o.base}${PREFIXO_DO_GUIA}/${operacao}`, {
        method: "POST",
        headers: { "content-type": "application/json", [CABECALHO_DO_LOTE]: await this.#o.credencial() },
        body: JSON.stringify(corpo),
        signal: AbortSignal.timeout(TECTO_DO_LOTE_MS),
      });
    } catch (erro) {
      throw new LoteIndisponivelError(operacao, erro instanceof Error ? erro.name : "desconhecido");
    }
    let lido: unknown = null;
    try {
      lido = await resposta.json();
    } catch {
      lido = null;
    }
    const json = typeof lido === "object" && lido !== null && !Array.isArray(lido) ? (lido as Record<string, unknown>) : {};
    if (resposta.status === 409) {
      const motivo = json["recusa"];
      if (typeof motivo === "string" && (MOTIVOS_DE_RECUSA as readonly string[]).includes(motivo)) {
        throw new ListaRecusadaError(motivo as MotivoDeRecusa);
      }
    }
    if (resposta.status !== 200) throw new LoteIndisponivelError(operacao, `http_${resposta.status}`);
    return json;
  }
}

function data(valor: unknown, operacao: OperacaoDoGuia): Date {
  const d = typeof valor === "string" ? new Date(valor) : null;
  if (d === null || Number.isNaN(d.getTime())) throw new LoteIndisponivelError(operacao, "data");
  return d;
}

/** A posição que o lote devolveu em JSON, de volta à forma do domínio. O inverso do `posicaoEmJson`. */
export function posicaoDoJson(bruto: unknown): Posicao | null {
  if (bruto === null || bruto === undefined) return null;
  const p = (typeof bruto === "object" ? bruto : {}) as Record<string, unknown>;
  const estado = p["estado"];
  if (estado === "aguardando") {
    const e = (typeof p["estimativa"] === "object" && p["estimativa"] !== null ? p["estimativa"] : {}) as Record<
      string,
      unknown
    >;
    const dias = (v: unknown): number => (typeof v === "number" ? v : Number.POSITIVE_INFINITY);
    return {
      estado,
      posicao: Number(p["posicao"]),
      estimativa: {
        rotulo: "estimativa",
        minimoDias: dias(e["minimo_dias"]),
        maximoDias: dias(e["maximo_dias"]),
      },
    };
  }
  if (estado === "convidado") return { estado, expiraEm: data(p["expira_em"], "posicao") };
  if (estado === "concluido" || estado === "expirado" || estado === "desistiu") return { estado };
  throw new LoteIndisponivelError("posicao", "estado");
}

/** O `CapacityGate` e as quatro da lista, pelo lote. */
export class ListaPeloLote implements CapacityGate {
  readonly #cliente: ClienteDoLote;

  constructor(cliente: ClienteDoLote) {
    this.#cliente = cliente;
  }

  async reserve(onboardingId: string): Promise<"granted" | "lista_espera"> {
    const r = (await this.#cliente.chamar("reservar", { onboarding_id: onboardingId }))["resultado"];
    if (r === "granted" || r === "lista_espera") return r;
    throw new LoteIndisponivelError("reservar", "resultado");
  }

  async release(onboardingId: string): Promise<void> {
    await this.#cliente.chamar("libertar", { onboarding_id: onboardingId });
  }

  async posicao(onboardingId: string): Promise<Posicao | null> {
    return posicaoDoJson((await this.#cliente.chamar("posicao", { onboarding_id: onboardingId }))["posicao"]);
  }

  async validarConvite(onboardingId: string, convite: unknown): Promise<{ readonly expiraEm: Date }> {
    const r = await this.#cliente.chamar("convite", { onboarding_id: onboardingId, convite });
    return { expiraEm: data(r["expira_em"], "convite") };
  }

  async recusar(onboardingId: string, convite: unknown): Promise<void> {
    await this.#cliente.chamar("recusar", { onboarding_id: onboardingId, convite });
  }

  async desistir(onboardingId: string): Promise<void> {
    await this.#cliente.chamar("desistir", { onboarding_id: onboardingId });
  }
}

/** Os dois *gates* do guia, pelo lote. */
export class GatesPeloLote implements GatesDoOnboarding {
  readonly #cliente: ClienteDoLote;

  constructor(cliente: ClienteDoLote) {
    this.#cliente = cliente;
  }

  async marcar(onboardingId: string, gate: GateDoEs, verde: boolean, motivo: string): Promise<void> {
    await this.#cliente.chamar("gate", { onboarding_id: onboardingId, gate, verde, motivo });
  }
}

/** O caso `es_falhado`, pelo lote. */
export class RevisaoPeloLote implements FilaDeRevisao {
  readonly #cliente: ClienteDoLote;

  constructor(cliente: ClienteDoLote) {
    this.#cliente = cliente;
  }

  async abrir(onboardingId: string, _tipo: "es_falhado", motivo: MotivoDeFalha): Promise<void> {
    await this.#cliente.chamar("revisao", { onboarding_id: onboardingId, motivo });
  }
}

/**
 * Levantado em `prod` com o guia configurado e sem a rota interna do lote. **Falha
 * fechado**, pela razão do `BaseEmFaltaEmProducaoError`: o guia em memória perdia o
 * estado no reinício, e a lista, os *gates* e a fila em memória eram de um processo
 * só — um caso posto `verificado` aqui não chegava ao `onboarding_gate` que a
 * activação lê.
 */
export class LoteEmFaltaEmProducaoError extends Error {
  override readonly name = "LoteEmFaltaEmProducaoError";

  constructor() {
    super(
      "o onboarding-web nao monta o guia em prod sem a ONBOARDING_LOTE_INTERNO_URL: a lista, " +
        "os gates e a fila do guia correm no processo de lote, como kamba_batch",
    );
  }
}

/** As portas do guia que pedem `kamba_batch`, e se o processo corre a volta dos 30 minutos. */
export interface PortasDoGuia<L> {
  readonly lista: L | ListaPeloLote;
  readonly gates: GatesDoOnboarding;
  readonly revisao: FilaDeRevisao;
  /**
   * `true` quando a volta (o abandono e a lista) corre **neste** processo: só com
   * as portas em memória. Pelo lote, quem a corre é o `onboarding-lote`.
   */
  readonly voltaNoProcesso: boolean;
}

/**
 * **A escolha das portas**, fora do `server.ts` para que os ensaios a alcancem.
 *
 * Com a rota interna do lote: as três pelo lote, e nenhuma volta aqui. Sem ela:
 * em `prod`, recusa (`LoteEmFaltaEmProducaoError`); em `dev` e `staging`, os
 * duplos em memória que quem chama dá, com a volta no processo — o fluxo continua
 * exercitável ponta a ponta sem o lote.
 */
export function portasDoGuia<L>(o: {
  readonly ambiente: "dev" | "staging" | "prod";
  readonly lote: ClienteDoLote | null;
  readonly emMemoria: () => { readonly lista: L; readonly gates: GatesDoOnboarding; readonly revisao: FilaDeRevisao };
}): PortasDoGuia<L> {
  if (o.lote !== null) {
    return {
      lista: new ListaPeloLote(o.lote),
      gates: new GatesPeloLote(o.lote),
      revisao: new RevisaoPeloLote(o.lote),
      voltaNoProcesso: false,
    };
  }
  if (o.ambiente === "prod") throw new LoteEmFaltaEmProducaoError();
  return { ...o.emMemoria(), voltaNoProcesso: true };
}
