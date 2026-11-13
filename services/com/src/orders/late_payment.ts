/**
 * O pagamento que chega fora do caminho normal (KAM-050, `docs/tecnica/03` §6.6).
 *
 * O caminho normal — `aguarda_pagamento` ou `pendente_confirmacao` → `paga` — é do
 * KAM-055 (`../payments/efeito.ts`). Este módulo é o resto: um `payment.*`
 * autenticado sobre uma encomenda que **não** está à espera dele.
 *
 * ```text
 * estado da encomenda   ramo                  o que acontece
 * expirada              tardio                regra 1: re-reserva e paga
 *                                             regra 2: sem stock, paga com excepção
 * cancelada             apos_cancelamento     regra 3: excepção e pedido de reembolso
 * paga e seguintes      duplicado             regra 4: excepção e pedido de reembolso
 * ```
 *
 * Tudo corre na transacção do consumo (`packages/core-ts/src/eventos/consumo.ts`),
 * que já escreveu o recibo do evento em `events_consumed` antes de chegar aqui. É
 * esse recibo que torna as quatro regras **idempotentes por evento**: um
 * `payment.confirmed` entregue duas vezes é `duplicado` no consumo e não chega a
 * este módulo, pelo que não duplica excepções nem pedidos de reembolso (DoD).
 *
 * ## Regras 1 e 2: reservar primeiro, depois transitar
 *
 * É a ordem dos *Detalhes Técnicos* do bloco. A re-reserva é o `reserveStock` do
 * KAM-045 sem alteração nenhuma, dentro de um *savepoint* (ver o
 * `SQL_ABRIR_RERESERVA`), e só para as linhas cuja reserva foi **libertada** —
 * uma linha com reserva ainda `ativa` (o varrimento de expiração ainda não
 * passou) consome-se como no caminho normal. Para que a mesma linha possa ter
 * uma segunda reserva, a revisão `0046` troca a `stock_reservations_linha_uq`
 * por um índice único **parcial** (`WHERE estado <> 'libertada'`): a unicidade
 * que importa — uma reserva viva por linha — fica, e a que impedia re-reservar
 * uma linha libertada sai. A mesma restrição impedia o `expirada ->
 * aguarda_pagamento` do núcleo de voltar a reservar, e com ela isso também passa.
 *
 * ## Regras 3 e 4: não transitam
 *
 * O dinheiro chegou e a encomenda não o pode receber — está `cancelada`, ou já
 * está paga. O grafo não tem aresta para isto e não deve ter: a encomenda fica no
 * estado em que está, ganha a excepção na coluna e emite `order.exception` e
 * `order.refund_requested`. **Não se escreve na `refund_cases`**: ver a nota do
 * `refunds.ts` — abre-a o PAY ao consumir o pedido (decisão (b) do fundador).
 *
 * **A regra 4 dispara pelos dois caminhos desde o KAM-197.** Um segundo
 * pagamento de uma **segunda cobrança** (uma referência antiga paga depois de
 * uma nova) chega como `payment.confirmed`; um segundo pagamento da **mesma**
 * cobrança é `pagamento_duplicado` no *ledger*, e a revisão `0051` mapeia-o para
 * o mesmo `payment.confirmed`. Os dois passam por aqui.
 */

import { TTL_OMISSAO_MS } from "../reservations/contrato.ts";
import {
  commitReservation,
  lerReservas,
  reserveStock,
} from "../reservations/reserve.ts";
import type { LinhaAReservar } from "../reservations/contrato.ts";
import {
  type CausaQuePaga,
  type Excepcao,
  type MotivoDeReembolso,
  type OrderState,
} from "./contrato.ts";
import {
  SQL_ABRIR_RERESERVA,
  SQL_DESFAZER_RERESERVA,
  SQL_FECHAR_RERESERVA,
  SQL_MARCAR_EXCEPCAO,
} from "./consultas.ts";
import {
  EMISSOES,
  emitir,
  payloadDeExcepcao,
  payloadDeReembolsoPedido,
} from "./eventos.ts";
import {
  transition,
  type Encomendas,
  type ResultadoDaTransicao,
} from "./transition.ts";

/** Os quatro ramos de um pagamento autenticado, pelo estado da encomenda. */
export type RamoDoPagamento =
  | "normal"
  | "tardio"
  | "apos_cancelamento"
  | "duplicado";

/** Os estados em que a encomenda já recebeu o pagamento dela (regra 4). */
export const ESTADOS_JA_PAGOS: readonly OrderState[] = [
  "paga",
  "em_entrega",
  "entregue",
  "entrega_falhada",
  "em_disputa",
  "reembolso_pendente",
  "reembolsada",
];

/**
 * O ramo, pelo estado. `criada` é `normal` porque não chega aqui: o consumo
 * **adia** um pagamento sobre uma encomenda sem referência emitida, e quem decide
 * isso é o `podeTransitar`, não este módulo.
 */
export function ramoDoPagamento(estado: OrderState): RamoDoPagamento {
  if (estado === "expirada") return "tardio";
  if (estado === "cancelada") return "apos_cancelamento";
  if (ESTADOS_JA_PAGOS.includes(estado)) return "duplicado";
  return "normal";
}

/** O pagamento, como o efeito do consumo o leu do envelope. */
export interface PagamentoRecebido {
  readonly orderId: string;
  /** O `id` do envelope do `payment.*`, que é o que tem recibo de consumo. */
  readonly eventoId: string;
  readonly causa: CausaQuePaga;
  readonly valorMinor: bigint;
  readonly currency: string;
}

/** O desfecho de um pagamento tardio. */
export type DesfechoTardio =
  | { readonly tipo: "re_reservada"; readonly resultado: ResultadoDaTransicao }
  | { readonly tipo: "sem_stock"; readonly resultado: ResultadoDaTransicao };

/** Um erro do `reserveStock` que não é falta de stock. Não se adivinha: lança. */
export class ReReservaRecusadaError extends Error {
  override readonly name = "ReReservaRecusadaError";

  constructor(orderId: string, motivo: string) {
    super(
      `a re-reserva da encomenda ${orderId} foi recusada com ${motivo}, que nao ` +
        "e falta de stock: a regra 2 do §6.6 e para quando nao ha stock, e um " +
        "pedido invalido nao se trata como tal (KAM-050)",
    );
  }
}

/**
 * As linhas a re-reservar: as que **não** têm reserva viva.
 *
 * Lê as reservas da encomenda e devolve, por `line_no`, a linha das que só têm
 * reservas `libertada`. Uma linha com reserva `ativa` não se re-reserva — o
 * `commitReservation` consome-a —, e uma encomenda sem reserva nenhuma (uma
 * venda de serviço, ou uma encomenda que nunca chegou a reservar) devolve zero
 * linhas: não há stock a re-reservar, e a regra 1 aplica-se sem ele.
 */
export async function linhasARefazer(
  e: Encomendas,
  orderId: string,
): Promise<readonly LinhaAReservar[]> {
  const reservas = await lerReservas({ repo: e.repo }, orderId);
  const vivas = new Set<number>();
  const libertadas = new Map<number, LinhaAReservar>();
  for (const r of reservas) {
    if (r.estado === "libertada") {
      libertadas.set(r.lineNo, { lineNo: r.lineNo, sku: r.sku, qty: r.qty });
    } else {
      vivas.add(r.lineNo);
    }
  }
  return [...libertadas.values()]
    .filter((linha) => !vivas.has(linha.lineNo))
    .sort((a, b) => a.lineNo - b.lineNo);
}

/**
 * Tenta re-reservar. `true` se há stock para todas as linhas, `false` se não.
 *
 * **Tudo ou nada, pelo *savepoint***: uma linha sem stock desfaz as que já
 * tinham passado, e a regra 2 segue sem reserva nenhuma. Reservar metade da
 * encomenda era prometer stock a uma encomenda que vai ser resolvida à mão.
 */
async function reReservar(e: Encomendas, orderId: string): Promise<boolean> {
  const linhas = await linhasARefazer(e, orderId);
  if (linhas.length === 0) return true;
  await e.emitir.query(SQL_ABRIR_RERESERVA);
  const r = await reserveStock(
    { repo: e.repo, ...(e.agora === undefined ? {} : { agora: e.agora }) },
    {
      orderId,
      linhas,
      // O prazo cheio e não o provisório: a reserva consome-se já a seguir,
      // na mesma transacção, e um prazo de dois minutos à espera de um
      // `charge.issued` que não vem não descreve nada.
      ttlMs: TTL_OMISSAO_MS,
      provisoria: false,
    },
  );
  if (r.tipo === "erro") {
    await e.emitir.query(SQL_DESFAZER_RERESERVA);
    if (r.erro === "OUT_OF_STOCK" || r.erro === "NOT_FOUND") return false;
    throw new ReReservaRecusadaError(orderId, r.erro);
  }
  await e.emitir.query(SQL_FECHAR_RERESERVA);
  return true;
}

/** Marca a excepção e emite o `order.exception`. */
async function excepcionar(
  e: Encomendas,
  pagamento: PagamentoRecebido,
  excepcao: Excepcao,
): Promise<void> {
  await e.repo.noTenant(SQL_MARCAR_EXCEPCAO, [pagamento.orderId, excepcao]);
  await emitir(e.emitir, e.ctx.tenantId, {
    ...EMISSOES.excepcao,
    orderId: pagamento.orderId,
    payload: payloadDeExcepcao(pagamento.orderId, excepcao, pagamento.eventoId),
  });
}

/**
 * **Regras 1 e 2.** A encomenda está `expirada` e chegou um pagamento autenticado.
 *
 * As duas acabam em `paga` — o dinheiro é real e a encomenda aceita-o (ADR-013:
 * pelo evento autenticado, com o recibo de consumo que o `order_estado_exige_log`
 * exige). A diferença é o stock: com ele, as reservas consomem-se como no caminho
 * normal; sem ele, a encomenda fica paga **com a excepção**, e a resolução é
 * manual (entregar mais tarde ou reembolsar, ADR-004). O `order.paid` sai nas
 * duas, pelo `transition`; o `order.exception` só na segunda.
 *
 * Um `conflito` ou um `erro` do `transition` devolve-se sem mais nada: quem
 * chama lança, e a transacção do consumo reverte — a re-reserva incluída.
 */
export async function aplicarPagamentoTardio(
  e: Encomendas,
  pagamento: PagamentoRecebido,
  expectedVersion: number,
): Promise<DesfechoTardio> {
  const comStock = await reReservar(e, pagamento.orderId);
  const resultado = await transition(e, {
    orderId: pagamento.orderId,
    para: "paga",
    expectedVersion,
    causa: { causa: pagamento.causa, eventoId: pagamento.eventoId },
  });
  if (resultado.tipo !== "ok") {
    return { tipo: comStock ? "re_reservada" : "sem_stock", resultado };
  }
  if (!comStock) {
    await excepcionar(e, pagamento, "pagamento_tardio_sem_stock");
    return { tipo: "sem_stock", resultado };
  }
  const reservas = await commitReservation({ repo: e.repo }, pagamento.orderId);
  if (reservas.tipo === "erro") {
    throw new ReReservaRecusadaError(pagamento.orderId, reservas.erro);
  }
  return { tipo: "re_reservada", resultado };
}

/**
 * **Regras 3 e 4.** O pagamento não paga nada: a encomenda está `cancelada`, ou
 * já está paga. Marca a excepção, emite `order.exception` e pede o reembolso.
 *
 * O `valor_minor` do pedido é **o do pagamento**, e não o total da encomenda: é o
 * que chegou a mais, e um duplicado parcial (que o G4 do PAY já teria recusado,
 * mas o COM não o assume) pede de volta o que entrou.
 */
export async function aplicarPagamentoExcedente(
  e: Encomendas,
  pagamento: PagamentoRecebido,
  ramo: "apos_cancelamento" | "duplicado",
): Promise<void> {
  const excepcao: Excepcao & MotivoDeReembolso =
    ramo === "apos_cancelamento"
      ? "pagamento_apos_cancelamento"
      : "pagamento_duplicado";
  await excepcionar(e, pagamento, excepcao);
  await emitir(e.emitir, e.ctx.tenantId, {
    ...EMISSOES.reembolso,
    orderId: pagamento.orderId,
    payload: payloadDeReembolsoPedido(
      pagamento.orderId,
      excepcao,
      pagamento.valorMinor,
      pagamento.currency,
    ),
  });
}
