/**
 * Um `ObservadorDoTeste` alimentado por webhooks da Meta (KAM-094, critério 4).
 *
 * Lê dos corpos o que a Meta diz — o `inbound` com «teste» e o `delivered` da
 * resposta — e recebe do lado de dentro o que a Meta não diz: a resposta que o
 * bot mandou (com o texto, para conferir a identificação) e o `consent_event`
 * do aviso de 1.º contacto. É o observador dos ensaios com o simulador do
 * KAM-024 e do `dev`.
 *
 * shortcut: não há observador de produção. As tabelas da conversa guardam o
 * `last_inbound_at`, o `delivered_at` e o `consent_event`, mas não o texto do
 * «teste» nem o da resposta (ADR-010), e sem eles não se confere a palavra nem a
 * identificação da loja; revê-se quando o `worker-canal` emitir um sinal de
 * teste no caminho de entrada (credor no bloco do KAM-094).
 *
 * **Nenhum telefone se guarda.** O `from` serve para separar conversas e entra
 * só como `sha256`, e o texto da mensagem do dono só se compara.
 */

import { createHash } from "node:crypto";

import type { FactosDoTeste, ObservadorDoTeste } from "./contrato.ts";
import { eMensagemDeTeste, identificaAssistenteELoja } from "./smoke.ts";

/** A loja de um caso: o número dela e os dois nomes que a resposta tem de ter. */
export interface LojaDoTeste {
  readonly phoneNumberId: string;
  readonly loja: string;
  readonly assistente: string;
}

interface Inbound {
  readonly pnid: string;
  readonly conversa: string;
  readonly em: Date;
}

interface Resposta {
  readonly pnid: string;
  readonly wamid: string;
  readonly identifica: boolean;
  readonly em: Date;
}

function objecto(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function resumo(texto: string): string {
  return createHash("sha256").update(texto, "utf8").digest("hex").slice(0, 32);
}

export class ObservadorPorWebhook implements ObservadorDoTeste {
  readonly #lojas: ReadonlyMap<string, LojaDoTeste>;
  readonly #inbound: Inbound[] = [];
  readonly #respostas: Resposta[] = [];
  readonly #entregues = new Set<string>();
  readonly #consentimentos: { pnid: string; em: Date }[] = [];

  /** `lojas`: do `onboardingId` à loja. */
  constructor(lojas: ReadonlyMap<string, LojaDoTeste>) {
    this.#lojas = lojas;
  }

  /** Aplica um corpo de webhook recebido em `em`. O que não tem a forma, ignora-se. */
  aplicar(corpo: unknown, em: Date): void {
    const entradas = objecto(corpo)?.entry;
    if (!Array.isArray(entradas)) return;
    for (const entrada of entradas) {
      const changes = objecto(entrada)?.changes;
      if (!Array.isArray(changes)) continue;
      for (const change of changes) {
        const c = objecto(change);
        if (c?.field !== "messages") continue;
        const valor = objecto(c.value);
        const pnid = objecto(valor?.metadata)?.phone_number_id;
        if (typeof pnid !== "string" || pnid === "") continue;
        for (const m of Array.isArray(valor?.messages) ? valor.messages : []) {
          const msg = objecto(m);
          if (msg?.type !== "text" || !eMensagemDeTeste(objecto(msg.text)?.body)) continue;
          const de = typeof msg.from === "string" ? msg.from : typeof msg.from_user_id === "string" ? msg.from_user_id : "";
          if (de === "") continue;
          this.#inbound.push({ pnid, conversa: `teste:${resumo(`${pnid}|${de}`)}`, em });
        }
        for (const s of Array.isArray(valor?.statuses) ? valor.statuses : []) {
          const st = objecto(s);
          if (typeof st?.id === "string" && (st.status === "delivered" || st.status === "read")) {
            this.#entregues.add(st.id);
          }
        }
      }
    }
  }

  /** A resposta que o bot mandou, com o texto, para conferir a identificação. */
  respondeu(onboardingId: string, wamid: string, texto: string, em: Date): void {
    const loja = this.#lojas.get(onboardingId);
    if (loja === undefined) return;
    this.#respostas.push({
      pnid: loja.phoneNumberId,
      wamid,
      identifica: identificaAssistenteELoja(texto, loja.assistente, loja.loja),
      em,
    });
  }

  /** O `consent_event` do aviso de 1.º contacto, gravado. */
  consentiu(onboardingId: string, em: Date): void {
    const loja = this.#lojas.get(onboardingId);
    if (loja !== undefined) this.#consentimentos.push({ pnid: loja.phoneNumberId, em });
  }

  async factos(onboardingId: string, desde: Date, ate: Date): Promise<FactosDoTeste> {
    const loja = this.#lojas.get(onboardingId);
    const na = (em: Date) => em >= desde && em <= ate;
    if (loja === undefined) {
      return { inbound: false, resposta: false, entregue: false, consentimento: false, conversationId: null };
    }
    const inbound = this.#inbound.find((i) => i.pnid === loja.phoneNumberId && na(i.em));
    const respostas = this.#respostas.filter((r) => r.pnid === loja.phoneNumberId && na(r.em) && r.identifica);
    return {
      inbound: inbound !== undefined,
      resposta: respostas.length > 0,
      entregue: respostas.some((r) => this.#entregues.has(r.wamid)),
      consentimento: this.#consentimentos.some((c) => c.pnid === loja.phoneNumberId && na(c.em)),
      conversationId: inbound?.conversa ?? null,
    };
  }
}
