/**
 * O consumidor de `booking.created`: agenda o lembrete (KAM-048, critério 1).
 *
 * «Evento `booking.created` → *scheduler* cria `booking.reminder_due` em T−24 h»
 * — e a primeira seta é esta. O que este módulo faz é **uma** coisa: ler a
 * marcação como ela está agora e pedir à fila o despertar. A política de
 * instantes é do `schedule.ts` e é pura; o que aqui se acrescenta é a leitura.
 *
 * A forma é a do `../../reservations/consumers.ts` do KAM-045, e a razão é a
 * mesma: o que se exporta é a **decisão e o efeito**, e quem recebe o evento do
 * EVT chama-os. Não há aqui subscrição nem processo de fila — o consumidor
 * genérico com recibo em `platform.events_consumed` é do KAM-006, e o anfitrião
 * do *worker* é decisão de arquitectura com credor escrito (**KAM-071**, dono do
 * varrimento agendado).
 *
 * ## Porque é que se lê a base em vez de se usar o payload
 *
 * O `booking.created` traz `inicio_at`, e usá-lo directamente poupava uma
 * consulta. Não se faz, e a razão é a garantia do EVT: a entrega é «pelo menos
 * uma vez» e **não é imediata**. Entre a emissão e o consumo cabe um
 * cancelamento e cabe uma remarcação — e nos dois casos o payload está certo
 * sobre o passado e errado sobre o presente. Agendar pelo payload punha na fila
 * um despertar para um instante que já não existe, e deixava ao disparo o
 * trabalho de o recusar: funcionava, e gastava uma volta de fila por cada
 * marcação que mudou.
 *
 * O payload continua a ser lido para **uma** coisa: o `booking_id`. É o que
 * identifica a linha, e é o único campo dele em que o tempo não mexe.
 */

import { SQL_MARCACAO } from "../consultas.ts";
import type { ComTenant, Estado } from "../contrato.ts";
import {
  agendarLembrete,
  type Agendamento,
  type FilaDeLembretes,
} from "./schedule.ts";
import {
  MetricasDoLembrete,
  METRICA_AGENDADOS,
} from "./metricas.ts";

/** O tipo do evento que este módulo consome. */
export const BOOKING_CREATED = "booking.created";

/**
 * O que o `booking.created` traz, na parte que este módulo lê.
 *
 * **Um campo**, e não os seis do contrato. Não é descuido: ver a nota do módulo
 * para a razão de os outros cinco se lerem da base. Declarar só o que se lê é o
 * que torna a nota verificável — um campo a mais aqui e alguém ia usá-lo.
 */
export interface BookingCreated {
  readonly booking_id: string;
}

/** O que o consumidor precisa que lhe dêem. */
export interface Dependencias {
  readonly comTenant: ComTenant;
  readonly fila: FilaDeLembretes;
  readonly metricas?: MetricasDoLembrete;
  /** O relógio, injectável para que os ensaios de instante não esperem. */
  readonly agora?: () => Date;
}

/**
 * **A primeira seta do critério 1.** Agenda o lembrete de uma marcação criada.
 *
 * Devolve o `Agendamento`, que diz se agendou ou porque não. **Uma marcação que
 * já não está `confirmada` devolve `nao_confirmada` e não é erro**: é o
 * cancelamento a chegar antes do consumo, que é o caso normal de uma fila
 * assíncrona.
 *
 * Uma marcação que a base não tem devolve `nao_confirmada` também, e a escolha
 * fica dita: não há motivo próprio para «não existe» porque o efeito é o mesmo —
 * não se agenda — e um motivo a mais na métrica pagava uma etiqueta para
 * distinguir dois casos que o painel trata da mesma maneira. O que distingue os
 * dois é a DLQ do KAM-006, onde um `booking.created` sem linha aparece como o que
 * é: um evento sobre um agregado que desapareceu.
 */
export async function agendarDoBookingCreated(
  deps: Dependencias,
  tenantId: string,
  evento: BookingCreated,
): Promise<Agendamento> {
  const metricas = deps.metricas ?? new MetricasDoLembrete();
  const agora = (deps.agora ?? (() => new Date()))();

  const marcacao = await deps.comTenant(tenantId, async (cliente) => {
    const { rows } = await cliente.query(SQL_MARCACAO, [evento.booking_id]);
    const linha = rows[0];
    if (linha === undefined) return null;
    return {
      bookingId: String(linha["booking_id"]),
      // O `pg` devolve `Date` para `timestamptz`; o `inicio_at` tem de chegar à
      // fila na **mesma** forma em que o disparo o vai comparar. Ver a nota do
      // `instanteComoIso` no `deliver.ts`: sem isto, o `inicioAt` do `jobId` e o
      // do payload do lembrete divergiam e nenhum lembrete saía.
      inicioAt:
        linha["inicio_at"] instanceof Date
          ? (linha["inicio_at"] as Date).toISOString()
          : String(linha["inicio_at"]),
      estado: String(linha["estado"]) as Estado,
    };
  });

  if (marcacao === null) {
    metricas.contar(METRICA_AGENDADOS, "nao_confirmada");
    return { agenda: false, motivo: "nao_confirmada" };
  }

  const decisao = await agendarLembrete(deps.fila, agora, tenantId, marcacao);
  metricas.contar(
    METRICA_AGENDADOS,
    decisao.agenda ? "agendado" : decisao.motivo,
  );
  return decisao;
}
