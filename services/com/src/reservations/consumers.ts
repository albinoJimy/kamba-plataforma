/**
 * O consumidor de `charge.issued`: fixa o `expira_at` (KAM-045, critério 3).
 *
 * «Com `charge.issued` fixa `expira_at` e a encomenda passa a
 * `aguarda_pagamento`.» Duas coisas, e este módulo faz **uma** — a do stock. A
 * outra é uma transição de estado, e as transições passam todas pelo
 * `../orders/transition.ts`, que é o único sítio onde o grafo do §6.2 se
 * consulta e onde o registo auditado se escreve.
 *
 * ```text
 * fixarPrazo      estende o `expira_at` das reservas da encomenda   ESTE módulo
 * aguarda_pagamento  a transição da encomenda                       transition.ts
 * ```
 *
 * Juntá-las aqui era escrever a segunda implementação de uma transição — e seria
 * a implementação que não passa pelo grafo nem pelo `order_state_log`, isto é, a
 * que o `CONSTRAINT TRIGGER` diferido da revisão `0030` recusa no `COMMIT` com
 * `KA005`. Por isso o que este módulo exporta é a **decisão** (função pura) e o
 * efeito no stock; quem recebe o evento chama as duas coisas na mesma
 * transacção, e é por isso que elas são atómicas juntas.
 *
 * ## O prazo que se fixa é o do critério 2, e vem da cobrança e não do relógio
 *
 * ```text
 * fim_validade_cobranca = min(now + ttl_tenant, now + 72 h)
 * expira_at             = fim_validade_cobranca + 15 min
 * ```
 *
 * O `charge.issued` traz o fim da validade da **referência** — é o
 * `end_datetime` do ProxyPay, as 72 h do AppyPay, os 30 min do Express — e é
 * esse que manda, não o `ttl_tenant`. O `ttl_tenant` é o que se pede ao PAY; o
 * que a referência diz é o que o cliente tem de facto para pagar, e reservar
 * stock por mais tempo do que a referência vive era prender stock para uma
 * cobrança que já não pode ser paga.
 *
 * Quando o evento **não** traz prazo — o que acontece se o facilitador não o
 * der —, cai-se no `ttl_tenant` limitado às 72 h. Fica dito que é um recurso e
 * não o caminho normal: um prazo que não vem da cobrança é uma estimativa
 * nossa, e o critério 2 marca os números todos como *proposta* a calibrar.
 *
 * ## A idempotência é do `SQL_CONFIRMAR`, não deste módulo
 *
 * O EVT entrega «pelo menos uma vez» (`docs/tecnica/06`), pelo que o mesmo
 * `charge.issued` chega duas vezes com normalidade. O `confirmada_at IS NULL` no
 * predicado do `SQL_CONFIRMAR` é o que faz a segunda entrega não fazer nada —
 * e **não** é zelo: sem ele, cada entrega estendia o prazo outra vez, e uma
 * reserva de 48 h entregue três vezes durava 144 h, acima do tecto de 72 h do
 * critério 7, por um caminho que não passa pelo `extendReservation`.
 *
 * O recibo de consumo em `platform.events_consumed` — a idempotência do lado do
 * EVT — é do consumidor genérico do **KAM-006**, e este módulo não o escreve.
 */

import { erro, ok, type Erro, type ResultadoFinal } from "../port/contrato.ts";
import { SQL_CONFIRMAR } from "./consultas.ts";
import {
  FOLGA_MS,
  TTL_MAXIMO_MS,
  fimDaValidade,
  tectoComoIntervalo,
  type Duration,
  type Reserva,
} from "./contrato.ts";
import type { Reservas } from "./reserve.ts";

/** O tipo do evento que este módulo consome. */
export const CHARGE_ISSUED = "charge.issued";

/**
 * O que o `charge.issued` traz, na parte que este módulo lê.
 *
 * **Os campos são os que o payload tem, e nem um a mais.** O `charge.requested`
 * e o `charge.issued` **não existem** no catálogo publicado nem no §3.5 do
 * dicionário: vivem só no §12 do `docs/tecnica/03`, que é a dívida documental
 * **37**, e o dicionário §3.43 registou-o com credor (**KAM-054/055**, donos do
 * consumidor, mais o ticket de canon que acrescente os contratos).
 *
 * Por isso esta interface é **local e declarada como proposta**: é a forma que
 * este ticket precisa para fixar o prazo, não um contrato de evento. Quando o
 * contrato existir, esta interface passa a derivar dele — e o ensaio que a pina
 * é o que torna a substituição visível.
 */
export interface ChargeIssued {
  readonly orderId: string;
  /**
   * O fim da validade da referência, em ISO-8601. Opcional: ver a nota do
   * módulo para o que acontece quando o facilitador não o dá.
   */
  readonly validaAte?: string | null;
}

/**
 * O `expira_at` a escrever, pelo critério 2. **Função pura.**
 *
 * Três entradas e uma saída, e é a regra do critério inteira:
 *
 * ```text
 * validaAte presente   ->  validaAte + 15 min, limitado a now + 72 h + 15 min
 * validaAte ausente    ->  min(now + ttl, now + 72 h) + 15 min
 * ```
 *
 * **O tecto aplica-se nos dois casos**, e é o critério 7 a valer também aqui:
 * uma referência que o facilitador emitisse com validade de uma semana não
 * autoriza uma reserva de uma semana.
 *
 * ## O tecto desta função é contra `now`, e **não** é o do critério
 *
 * A primeira versão desta nota dizia «limitado a **criado** + 72 h», e o código
 * nunca fez isso — achado da revisão adversarial, e a afirmação estava escrita
 * como facto. Esta função **não pode** medir o tecto do critério: o `criado_at`
 * da reserva está na base e não no evento, e o único instante que ela tem é o
 * do consumo.
 *
 * O que ela faz é limitar o que **propõe**; quem impõe é o
 * `$4::interval` do `SQL_CONFIRMAR`, contra o `criado_at`. A distinção importa
 * porque sem ela uma primeira entrega tardia (sem agendador, uma provisória
 * fica `ativa` indefinidamente) dava 72 h a contar do consumo.
 */
export function prazoDoEvento(
  agora: Date,
  evento: ChargeIssued,
  ttlMs: Duration,
): Date {
  const tecto = new Date(agora.getTime() + TTL_MAXIMO_MS + FOLGA_MS);
  if (
    typeof evento.validaAte === "string" &&
    !Number.isNaN(new Date(evento.validaAte).getTime())
  ) {
    const daCobranca = new Date(
      new Date(evento.validaAte).getTime() + FOLGA_MS,
    );
    return daCobranca.getTime() <= tecto.getTime() ? daCobranca : tecto;
  }
  return new Date(fimDaValidade(agora, ttlMs).getTime() + FOLGA_MS);
}

/**
 * **O critério 3, metade do stock.** Fixa o prazo das reservas da encomenda.
 *
 * Devolve as reservas que mudaram. **Lista vazia não é erro**: é o
 * `charge.issued` repetido (o `confirmada_at` já não é nulo) ou uma encomenda
 * sem reservas activas — e nos dois casos o estado da base é o que quem chama
 * queria. Distinguir os dois exigia uma leitura a mais para uma informação que
 * ninguém usa; quem precisar dela lê com o `lerReservas`.
 *
 * **Não transita a encomenda.** Ver a nota do módulo: quem o faz é o
 * `transition`, na mesma transacção, e quem os chama aos dois é o consumidor.
 */
export async function fixarPrazo(
  r: Reservas,
  evento: ChargeIssued,
  ttlMs: Duration,
): Promise<ResultadoFinal<readonly Reserva[]>> {
  if (evento.orderId.trim() === "") return erro("VALIDATION_ERROR" as Erro);
  const agora = (r.agora ?? (() => new Date()))();
  const prazo = prazoDoEvento(agora, evento, ttlMs);
  // **O tecto vai para a base, e é lá que ele morde.** O `prazoDoEvento` acima
  // ancora o dele em `agora`, porque é o único instante que este módulo tem; o
  // que o critério 7 pede é o tecto contra o `criado_at` **da reserva**, e esse
  // está na base. Sem este `$4` uma primeira entrega tardia de `charge.issued`
  // dava 72 h a contar do consumo — vida total `T + 72 h + 15 min`. Achado da
  // revisão adversarial.
  const mudadas = await r.repo.noTenant(SQL_CONFIRMAR, [
    evento.orderId,
    prazo.toISOString(),
    tectoComoIntervalo(),
  ]);
  return ok(
    mudadas.map((linha) => ({
      reservationId: String(linha["id"]),
      orderId: evento.orderId,
      lineNo: Number(linha["line_no"]),
      sku: String(linha["sku"]),
      qty: Number(linha["qty"]),
      estado: "ativa" as const,
      motivo: null,
      expiraAt: String(linha["expira_at"]),
      // O `SQL_CONFIRMAR` põe `confirmada_at = now()` e não o devolve; o que
      // importa a quem chama é que deixou de ser nulo, e é o que se diz. O
      // instante exacto lê-se com o `lerReservas`.
      confirmadaAt: agora.toISOString(),
      version: Number(linha["version"]),
    })),
  );
}
