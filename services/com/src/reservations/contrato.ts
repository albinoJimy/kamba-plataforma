/**
 * O vocabulário das reservas de stock: estados, motivos e os prazos (KAM-045).
 *
 * Os nomes são os do dicionário §3.46 e os do `../port/contrato.ts`, que já fixa
 * o `Reservation`, o `MOTIVOS_DE_LIBERTACAO` e o `Duration` desde o KAM-178.
 * **Nada aqui inventa nome**: o que este ficheiro acrescenta são os três estados
 * de uma reserva e os prazos do critério 2, que são números e não nomes.
 *
 * ## Os prazos são **propostas**, e o critério diz onde se calibram
 *
 * O critério 2 escreve-os e marca-os: «valores *proposta*, calibrar com PAY».
 * Ficam aqui, em constantes, e **não** num `CHECK` de coluna — a razão é a do
 * `TTL_DO_HOLD_MS` do KAM-047, registada no dicionário §3.3: um número no
 * `CHECK` de uma coluna obrigava a uma revisão de base de dados para o
 * calibrar.
 *
 * O que a base impõe é a **forma** (um prazo existe, é `NOT NULL`, e uma reserva
 * terminal não volta atrás); o quanto é desenho, e o desenho ainda não foi
 * medido contra nenhum facilitador.
 *
 * ## A folga de 15 min existe porque o ATM não fecha quando nós fechamos
 *
 * `expira_at = fim_validade_cobranca + 15 min`. A referência Multicaixa pode ser
 * paga em ATM **até ao fim da sua validade** e o callback pode atrasar-se
 * (`docs/tecnica/evidencia/E2_Pagamentos_Angola.md` §1.2, §1.3): libertar o
 * stock no instante exacto em que a referência caduca era libertar stock de uma
 * encomenda que alguém acabou de pagar e cujo callback vem a caminho.
 *
 * A folga **não** substitui a consulta final ao PAY do critério 5 — é a
 * diferença entre reduzir a probabilidade e fechar o caso. O ADR-013 fecha-o: a
 * expiração não decide pagamento, consulta.
 */

import {
  MOTIVOS_DE_LIBERTACAO,
  type Duration,
  type MotivoDeLibertacao,
} from "../port/contrato.ts";

export { MOTIVOS_DE_LIBERTACAO, type Duration, type MotivoDeLibertacao };

/**
 * Os **três** estados de uma reserva, pela ordem do ciclo de vida.
 *
 * `ativa` é o nome que os *Detalhes Técnicos* do bloco escrevem no índice
 * parcial; `consumida` sai do critério 5 e `libertada` do critério 6. A lista
 * fechada daqui e a do `stock_reservations_estado_ck` da revisão `0033` são
 * confrontadas por um ensaio, como o `ESTADOS` do KAM-029.
 */
export const ESTADOS_DA_RESERVA = ["ativa", "consumida", "libertada"] as const;
export type EstadoDaReserva = (typeof ESTADOS_DA_RESERVA)[number];

/** O estado em que uma reserva nasce, e o único a partir do qual ela muda. */
export const ATIVA: EstadoDaReserva = "ativa";

/**
 * Os **dois** estados terminais. Uma reserva que esteja num deles não volta.
 *
 * A barreira não é esta lista: é o *trigger* `stock_reserva_terminal` da
 * revisão `0033`, que levanta `KA009`. Esta lista é o que permite ao módulo
 * recusar antes de a base o fazer, e dar um erro de domínio em vez de um
 * SQLSTATE.
 */
export const ESTADOS_TERMINAIS = ["consumida", "libertada"] as const;

/**
 * O TTL de omissão de um *tenant*: **48 h** (*proposta*).
 *
 * O critério 2 dá `ttl_tenant ∈ [24 h, 72 h]` com omissão 48 h. O 48 é o meio
 * da banda e não uma medição; calibra-se com o PAY.
 */
export const TTL_OMISSAO_MS: Duration = 48 * 60 * 60 * 1000;

/** O mínimo da banda do critério 2: **24 h** (*proposta*). */
export const TTL_MINIMO_MS: Duration = 24 * 60 * 60 * 1000;

/**
 * O máximo da banda, e o tecto do critério 7: **72 h** (*proposta*).
 *
 * É o único dos cinco com apoio em evidência: a referência AppyPay tem 72 h por
 * omissão, **CONFIRMADO** em `docs/tecnica/evidencia/E2_Pagamentos_Angola.md`
 * §1.3. O que continua *proposta* é usá-lo como tecto de **todas** as vias — no
 * ProxyPay o `end_datetime` é nosso, pelo que o 72 h ali é escolha e não limite
 * de terceiro.
 */
export const TTL_MAXIMO_MS: Duration = 72 * 60 * 60 * 1000;

/**
 * A folga sobre o fim da validade da cobrança: **15 min** (*proposta*).
 *
 * Ver a nota do módulo para a razão de existir, e para a razão de não bastar.
 */
export const FOLGA_MS: Duration = 15 * 60 * 1000;

/**
 * A reserva de uma cobrança Express: **30 min** (*proposta*).
 *
 * O Express é *push* e dura minutos — 30 min, expiração do OPG, **INDÍCIO** em
 * `docs/tecnica/evidencia/E2_Pagamentos_Angola.md` §1.2. Herda o estado da
 * fonte: o anexo não o dá como CONFIRMADO.
 */
export const TTL_EXPRESS_MS: Duration = 30 * 60 * 1000;

/**
 * Quanto vive uma reserva **provisória** sem `charge.issued`: **2 min**.
 *
 * O critério 3 à letra: «sem `charge.issued` em 2 min a reserva provisória é
 * libertada e a encomenda fica `criada`». É o mesmo número que o
 * `MINUTOS_PARA_RETOMAR` do dicionário §3.28 usa para uma reserva de
 * idempotência abandonada, e a coincidência não é reuso — são ciclos
 * diferentes, e misturá-los punha o varrimento de um a olhar para o outro.
 */
export const PROVISORIA_MS: Duration = 2 * 60 * 1000;

/**
 * As vias de cobrança que este módulo distingue para efeito de prazo.
 *
 * **Não é o catálogo de facilitadores** — esse é do EPIC-05 e não deste ticket.
 * É a partição que o critério 2 faz: as vias com referência (ATM, 24–72 h) e a
 * via *push* (Express, 30 min). Um facilitador novo entra numa das duas.
 */
export const VIAS_DE_COBRANCA = ["referencia", "express"] as const;
export type ViaDeCobranca = (typeof VIAS_DE_COBRANCA)[number];

/** Uma reserva, como este módulo a lê da base. */
export interface Reserva {
  readonly reservationId: string;
  readonly orderId: string;
  readonly lineNo: number;
  readonly sku: string;
  readonly qty: number;
  readonly estado: EstadoDaReserva;
  readonly motivo: MotivoDeLibertacao | null;
  readonly expiraAt: string;
  /** Nulo enquanto o `charge.issued` não tiver fixado o prazo (critério 3). */
  readonly confirmadaAt: string | null;
  readonly version: number;
}

/** Uma linha a reservar: o que o `reserveStock` recebe por cada linha. */
export interface LinhaAReservar {
  readonly lineNo: number;
  readonly sku: string;
  readonly qty: number;
}

/**
 * O fim da validade da cobrança, pelo critério 2.
 *
 * `fim_validade_cobranca = min(now + ttl_tenant, now + 72 h)`, e o `expira_at`
 * é isso mais a folga. O `ttl_tenant` entra validado contra a banda: fora dela
 * **não se silencia**, porque um TTL de uma hora aceito em silêncio era uma
 * reserva que expira antes de o cliente chegar ao ATM.
 */
export function fimDaValidade(agora: Date, ttlMs: Duration): Date {
  const limitado = Math.min(ttlMs, TTL_MAXIMO_MS);
  return new Date(agora.getTime() + limitado);
}

/** O `expira_at` do critério 2: fim da validade mais a folga. */
export function prazoDaReserva(agora: Date, ttlMs: Duration): Date {
  return new Date(fimDaValidade(agora, ttlMs).getTime() + FOLGA_MS);
}

/**
 * O TTL está dentro da banda do critério 2?
 *
 * **O Express é a excepção declarada**, e não um buraco: 30 min está abaixo do
 * mínimo de 24 h de propósito, porque a cobrança dura minutos. Por isso a
 * pergunta é feita com a via, e não sobre o número nu.
 */
export function ttlAceitavel(ttlMs: Duration, via: ViaDeCobranca): boolean {
  if (!Number.isFinite(ttlMs) || ttlMs <= 0) return false;
  if (via === "express") return ttlMs <= TTL_EXPRESS_MS;
  return ttlMs >= TTL_MINIMO_MS && ttlMs <= TTL_MAXIMO_MS;
}

/** O prazo provisório do critério 3: dois minutos a contar de agora. */
export function prazoProvisorio(agora: Date): Date {
  return new Date(agora.getTime() + PROVISORIA_MS);
}
