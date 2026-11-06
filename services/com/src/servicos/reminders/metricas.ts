/**
 * As métricas do lembrete (KAM-048, critério 8 e DoD «Custo e
 * observabilidade»).
 *
 *     booking_reminder_sent_total      counter  lembretes aceites, por canal
 *     booking_reminder_blocked_total   counter  lembretes travados, por motivo
 *     booking_reminder_scheduled_total counter  agendamentos, por desfecho
 *
 * A forma é a do `outbound/metricas.ts` do KAM-015, que é a do `chr/metricas.ts`
 * e a do `consentimento/metricas.ts` — um `Map` de números, em memória, sem
 * dependências, com `exposicao()` no formato do Prometheus. Um módulo por
 * domínio, pelo precedente que o KAM-009 abriu.
 *
 * ## São três, e o critério pede quatro coisas
 *
 * O critério 8 pede «lembretes enviados, por canal (livre/template), custo e
 * falhas de entrega». Três contadores e não quatro, e a diferença está onde
 * cada número é verdade:
 *
 * * **enviados por canal** é a `booking_reminder_sent_total{canal}`, com dois
 *   valores: `service` (a mensagem livre, janela aberta) e `utility` (o
 *   *template*, janela fechada). É o número que diz quanto do tráfego de
 *   lembretes é pago;
 * * **falhas** são a `booking_reminder_blocked_total{motivo}`, e o domínio do
 *   motivo é a união dos nossos portões com as recusas do Outbound. **Recusar
 *   sem contar é recusar em silêncio** — a razão que a
 *   `outbound_rate_limited_total` da emenda 1.19 escreveu —, e sem a etiqueta um
 *   painel não distingue «os clientes cancelaram» de «o *template* está
 *   bloqueado», que é a diferença entre um dia normal e um incidente com dono;
 * * **custo não tem contador aqui**, e é a única das quatro que não é um
 *   contador deste módulo. O custo de um lembrete é o custo da mensagem que o
 *   Outbound enviou, e quem o acumula é o `meta_cost_usd_total` dele — um
 *   segundo acumulador sobre os mesmos envios somava o mesmo dinheiro duas vezes
 *   num painel que não tinha como saber. O custo **por lembrete e por tenant**
 *   sai do `SQL_LEMBRETES_DO_TENANT`, por consulta, como o §3.14 manda.
 *
 * O **`scheduled_total`** é o terceiro e não está no critério. Está aqui pela
 * razão das duas acima: um lembrete que nunca foi agendado não aparece em
 * nenhuma das outras duas, e sem ele um painel lê «zero bloqueados, zero
 * enviados» tanto num dia sem marcações como num dia em que o agendamento parou
 * de correr. O desfecho vai na etiqueta, e os valores são os
 * `MOTIVOS_DE_NAO_AGENDAR` mais o `agendado`.
 *
 * ## Nenhuma etiqueta cresce com o tráfego
 *
 * `canal` tem dois valores, `motivo` tem os das duas listas fechadas, e
 * `desfecho` tem cinco. Nenhuma leva `tenant_id`, `contact_id`, `booking_id`,
 * `channel_id`, `phone_number_id` nem `wamid` — pela mesma razão do KAM-015: uma
 * etiqueta é tão legível como uma linha de registo.
 */

import { MOTIVOS_DE_RECUSA } from "@kamba/core-ts/outbound";

import { MOTIVOS_DE_BLOQUEIO } from "./contrato.ts";
import { MOTIVOS_DE_NAO_AGENDAR } from "./schedule.ts";

export const METRICA_ENVIADOS = "booking_reminder_sent_total";
export const METRICA_TRAVADOS = "booking_reminder_blocked_total";
export const METRICA_AGENDADOS = "booking_reminder_scheduled_total";

export const CONTADORES = [
  METRICA_ENVIADOS,
  METRICA_TRAVADOS,
  METRICA_AGENDADOS,
] as const;
export type Contador = (typeof CONTADORES)[number];

/** Os dois canais por onde um lembrete sai. Ver a nota do módulo. */
export const CANAIS_DO_LEMBRETE = ["service", "utility"] as const;
export type CanalDoLembrete = (typeof CANAIS_DO_LEMBRETE)[number];

/** O desfecho de um agendamento: agendou, ou um dos motivos de não agendar. */
export const DESFECHOS_DO_AGENDAMENTO = [
  "agendado",
  ...MOTIVOS_DE_NAO_AGENDAR,
] as const;

/**
 * Os motivos que o contador de travados aceita.
 *
 * A **união** dos nossos portões com as recusas do Outbound, e derivada das duas
 * listas em vez de escrita ao lado: um motivo novo em qualquer das duas entra
 * aqui sozinho, e o `MetricaDesconhecidaError` deixa de ser a maneira de
 * descobrir que alguém acrescentou um.
 */
export const MOTIVOS_TRAVADOS: readonly string[] = [
  ...MOTIVOS_DE_BLOQUEIO,
  ...MOTIVOS_DE_RECUSA,
];

const ETIQUETAS: Readonly<
  Record<string, { readonly nome: string; readonly valores: readonly string[] }>
> = {
  [METRICA_ENVIADOS]: { nome: "canal", valores: CANAIS_DO_LEMBRETE },
  [METRICA_TRAVADOS]: { nome: "motivo", valores: MOTIVOS_TRAVADOS },
  [METRICA_AGENDADOS]: { nome: "desfecho", valores: DESFECHOS_DO_AGENDAMENTO },
};

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_ENVIADOS]: [
    "counter",
    "Lembretes de marcacao aceites pela Meta, por canal: service (mensagem livre, janela aberta) ou utility (template pago, janela fechada).",
  ],
  [METRICA_TRAVADOS]: [
    "counter",
    "Lembretes que nao sairam, por motivo. Inclui os portoes do KAM-048 (estado da marcacao, remarcacao, opt-in) e as recusas do Outbound (janela, template, estado do canal).",
  ],
  [METRICA_AGENDADOS]: [
    "counter",
    "Agendamentos de lembrete por desfecho: agendado, ou a razao de nao agendar. Existe para distinguir um dia sem marcacoes de um dia em que o agendamento parou.",
  ],
};

/** Pediu-se uma métrica que não existe. */
export class MetricaDesconhecidaError extends Error {
  override readonly name = "MetricaDesconhecidaError";
  constructor(nome: string) {
    super(`metrica desconhecida: ${nome}; as deste modulo sao ${CONTADORES.join(", ")}`);
  }
}

/** Pediu-se um valor de etiqueta fora da lista fechada. */
export class SufixoInvalidoError extends Error {
  override readonly name = "SufixoInvalidoError";
  constructor(metrica: string, valor: string) {
    const permitidos = ETIQUETAS[metrica]?.valores ?? [];
    super(
      `valor de etiqueta invalido para ${metrica}: ${valor}; ` +
        `os permitidos sao ${permitidos.join(", ")}`,
    );
  }
}

/**
 * As métricas do lembrete, em memória.
 *
 * `contar` **levanta** para uma métrica ou um valor de etiqueta que não exista,
 * e isso é a decisão do `MetricasDaSaida` do KAM-015 herdada aqui: uma etiqueta
 * escrita à mão com um erro de letra produzia uma série nova e silenciosa, e o
 * painel somava dois nomes para a mesma coisa sem ninguém ver.
 */
export class MetricasDoLembrete {
  readonly #valores = new Map<string, number>();

  contar(metrica: Contador | string, etiqueta?: string): void {
    if (!(CONTADORES as readonly string[]).includes(metrica)) {
      throw new MetricaDesconhecidaError(metrica);
    }
    const definicao = ETIQUETAS[metrica];
    if (definicao !== undefined) {
      if (etiqueta === undefined || !definicao.valores.includes(etiqueta)) {
        throw new SufixoInvalidoError(metrica, String(etiqueta));
      }
    }
    const chave = etiqueta === undefined ? metrica : `${metrica}|${etiqueta}`;
    this.#valores.set(chave, (this.#valores.get(chave) ?? 0) + 1);
  }

  /** O valor de uma série, ou `0`. Para os ensaios e para a exposição. */
  ler(metrica: Contador, etiqueta?: string): number {
    const chave = etiqueta === undefined ? metrica : `${metrica}|${etiqueta}`;
    return this.#valores.get(chave) ?? 0;
  }

  /** A exposição no formato do Prometheus. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const metrica of CONTADORES) {
      const [tipo, ajuda] = AJUDA[metrica] as readonly [string, string];
      linhas.push(`# HELP ${metrica} ${ajuda}`);
      linhas.push(`# TYPE ${metrica} ${tipo}`);
      const definicao = ETIQUETAS[metrica];
      if (definicao === undefined) {
        linhas.push(`${metrica} ${this.ler(metrica)}`);
        continue;
      }
      for (const valor of definicao.valores) {
        linhas.push(
          `${metrica}{${definicao.nome}="${valor}"} ${this.ler(metrica, valor)}`,
        );
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}
