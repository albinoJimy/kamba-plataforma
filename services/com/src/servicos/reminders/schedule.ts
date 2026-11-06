/**
 * O agendamento do lembrete: *delayed job* por marcação (KAM-048, critério 1).
 *
 * Tudo aqui são **funções puras**, sem relógio próprio e sem fila: o que o
 * critério 1 descreve é uma política — quando é que um lembrete se agenda, com
 * que atraso, e quando é que **não** se agenda de todo —, e uma política mede-se
 * sem Redis. A fila é um porto estreito, como no `../../reservations/scheduler.ts`
 * do KAM-045, e por exactamente a mesma razão: o `Filas` de
 * `@kamba/core-ts/eventos` é o porto do publicador de eventos e o `Trabalho`
 * dele não tem campo de atraso.
 *
 * ## O `jobId` leva o `inicio_at`, e é isso que faz a remarcação reagendar
 *
 * ```text
 * jobIdDoLembrete(booking_id, inicio_at)  ->  "lembrete:<uuid>:<iso>"
 * ```
 *
 * A escolha é a do `jobIdDaReserva` do KAM-045 com outro discriminante. Sem o
 * `inicio_at`, o `jobId` de uma marcação era sempre o mesmo e a fila
 * deduplicava o *job* novo contra o antigo: remarcar de quinta para sábado
 * deixava agendado o despertar de **quarta**, e o lembrete saía ao instante
 * errado. Com ele, a remarcação produz um `jobId` novo — e o *job* antigo,
 * quando dispara, encontra a marcação com outro `inicio` e o portão do
 * `deliver.ts` recusa-o.
 *
 * **É aqui que o critério 4 se cumpre em duas metades, e nenhuma basta
 * sozinha:** esta — o *job* novo acorda à hora certa — e a do disparo, que
 * reverifica `estado` e `inicio` contra a base. Um `jobId` só mudaria a hora e
 * deixaria o *job* velho a lembrar a marcação antiga; uma reverificação só
 * mataria o velho e nunca agendava o novo. O «1 lembrete **activo** por
 * marcação» do critério é a propriedade do par: dos dois *jobs* que podem estar
 * na fila depois de uma remarcação, só um pode produzir mensagem, e a chave de
 * idempotência garante que mesmo esse produz uma só.
 *
 * ## O que fica por ligar, e tem credor
 *
 * A implementação deste porto sobre BullMQ **não existe**, pela razão que o
 * KAM-045 já escreveu por extenso: o `FilasBullmq` do core serve o publicador e
 * não tem `delay`, e o `services/com` não tem processo de fila nem dependência
 * directa de `bullmq`. Credor: **KAM-071**, dono do varrimento agendado. Até lá
 * o agendamento corre por chamada e está medido por chamada — e o disparo, que
 * é o que entrega a mensagem, não depende da fila para ser correcto: ver o
 * `deliver.ts`.
 */

import type { Marcacao } from "../contrato.ts";
import { ANTECEDENCIA_MS, MINIMO_PARA_ENVIO_MS } from "./contrato.ts";

/** O nome da fila dos lembretes de marcação. */
export const FILA_DOS_LEMBRETES = "com:servicos:lembretes";

/** O nome do *job* adiado de um lembrete. */
export const JOB_DO_LEMBRETE = "lembrar-marcacao";

/** O estado em que uma marcação gera lembrete. Só um — ver o critério 4. */
export const ESTADO_QUE_LEMBRA = "confirmada";

/**
 * O `jobId` do lembrete de uma marcação. Ver a nota do módulo.
 *
 * Determinístico e sem relógio: o mesmo par dá sempre a mesma cadeia, e é isso
 * que deixa a fila deduplicar. Um `jobId` com o instante de agendamento lá
 * dentro produzia uma cadeia nova a cada chamada e a desduplicação não
 * acontecia nunca.
 */
export function jobIdDoLembrete(bookingId: string, inicioAt: string): string {
  return `lembrete:${bookingId}:${inicioAt}`;
}

/**
 * O instante em que o lembrete deve sair: `inicio − 24 h`.
 *
 * Devolve `null` para um `inicio_at` que não é uma data — e **não** lança: quem
 * chama recebe um `null` do `trabalhoDoLembrete` e não agenda nada, que é o
 * desfecho certo para uma linha que a base não devia ter. Lançar aqui fazia uma
 * marcação corrompida derrubar o agendamento das outras do mesmo lote.
 */
export function instanteDoLembrete(inicioAt: string): Date | null {
  const inicio = new Date(inicioAt).getTime();
  if (Number.isNaN(inicio)) return null;
  return new Date(inicio - ANTECEDENCIA_MS);
}

/**
 * Porque é que uma marcação **não** leva lembrete agendado.
 *
 *     nao_confirmada     o estado não é `confirmada`
 *     inicio_invalido    o `inicio_at` não é uma data
 *     ja_comecou         o início já passou
 *     antecedencia_curta o início está a menos de 2 h (critério 1, 2.ª metade)
 */
export const MOTIVOS_DE_NAO_AGENDAR = [
  "nao_confirmada",
  "inicio_invalido",
  "ja_comecou",
  "antecedencia_curta",
] as const;
export type MotivoDeNaoAgendar = (typeof MOTIVOS_DE_NAO_AGENDAR)[number];

/** Um *job* adiado, pronto a enfileirar. */
export interface TrabalhoDoLembrete {
  readonly jobId: string;
  readonly nome: string;
  /** Milissegundos a partir de agora. **Nunca negativo** — ver `atrasoAte`. */
  readonly atrasoMs: number;
  readonly dados: {
    readonly tenantId: string;
    readonly bookingId: string;
    /** O `inicio` **de quando se agendou**. É o que o disparo compara. */
    readonly inicioAt: string;
  };
}

/** O que a política decide para uma marcação. */
export type Agendamento =
  | { readonly agenda: true; readonly trabalho: TrabalhoDoLembrete }
  | { readonly agenda: false; readonly motivo: MotivoDeNaoAgendar };

/**
 * O atraso até um instante, **nunca negativo**.
 *
 * A forma é a do `atrasoAte` do KAM-045, e o zero quer dizer «corre já». É esse
 * zero que implementa o «agenda o lembrete **imediato**» do critério 1 para uma
 * marcação criada com menos de 24 h de antecedência: o instante do lembrete já
 * passou, e o atraso certo é nenhum.
 */
export function atrasoAte(agora: Date, alvo: Date): number {
  return Math.max(0, alvo.getTime() - agora.getTime());
}

/**
 * O porto estreito da fila dos lembretes. Ver a nota do módulo.
 *
 * Um método só, e não dois como no KAM-045: um lembrete não tem rede de
 * segurança repetível porque não tem prazo a vencer — o que o repetível de lá
 * protege é stock preso, e um lembrete que não sai não prende nada. O que o
 * protege de um *job* perdido é o `booking.created` poder ser reconsumido, que
 * é a garantia do EVT («pelo menos uma vez») e não uma segunda fila.
 */
export interface FilaDeLembretes {
  /** Agenda (ou reafirma) um *job* adiado. Idempotente pelo `jobId`. */
  agendarAdiado(trabalho: TrabalhoDoLembrete): Promise<void>;
}

/**
 * **O critério 1 inteiro.** O que se agenda para uma marcação, ou porque não.
 *
 * A ordem das recusas é a ordem das causas, e não é indiferente:
 *
 * 1. **o estado**, antes de tudo: uma marcação em `hold`, `cancelada` ou
 *    `expirada` não lembra, e nem vale calcular um instante para ela;
 * 2. **a forma do `inicio_at`**, porque o resto é aritmética sobre ele;
 * 3. **o início já passado**, que é uma marcação cuja hora chegou — o lembrete
 *    dela não tem destinatário interessado;
 * 4. **a antecedência curta**, que é a segunda metade do critério: o lembrete
 *    imediato só sai se o início estiver a **mais** de 2 h.
 *
 * Repare que (4) é um teto sobre o **início**, e não sobre o instante do
 * lembrete: a pergunta é «falta tempo suficiente para isto ser útil», e o
 * instante do lembrete é apenas quando se acorda. Medir (4) contra o instante do
 * lembrete dava a resposta errada para toda a marcação a mais de 24 h, porque
 * esse instante está no futuro por construção.
 */
export function agendamentoDaMarcacao(
  agora: Date,
  tenantId: string,
  marcacao: Pick<Marcacao, "bookingId" | "inicioAt" | "estado">,
): Agendamento {
  if (marcacao.estado !== ESTADO_QUE_LEMBRA) {
    return { agenda: false, motivo: "nao_confirmada" };
  }
  const alvo = instanteDoLembrete(marcacao.inicioAt);
  if (alvo === null) return { agenda: false, motivo: "inicio_invalido" };

  const faltaParaOInicio = new Date(marcacao.inicioAt).getTime() - agora.getTime();
  if (faltaParaOInicio <= 0) return { agenda: false, motivo: "ja_comecou" };
  if (faltaParaOInicio <= MINIMO_PARA_ENVIO_MS) {
    return { agenda: false, motivo: "antecedencia_curta" };
  }

  return {
    agenda: true,
    trabalho: {
      jobId: jobIdDoLembrete(marcacao.bookingId, marcacao.inicioAt),
      nome: JOB_DO_LEMBRETE,
      atrasoMs: atrasoAte(agora, alvo),
      dados: {
        tenantId,
        bookingId: marcacao.bookingId,
        inicioAt: marcacao.inicioAt,
      },
    },
  };
}

/**
 * Agenda o lembrete de uma marcação acabada de confirmar ou de remarcar.
 *
 * Chama-se **depois** do `COMMIT` de quem marcou, e isso é deliberado — a nota
 * do `agendarExpiracoes` do KAM-045 escreve a razão por extenso: um *job*
 * agendado dentro da transacção podia disparar antes de ela confirmar e
 * encontrar uma marcação que ainda não existe.
 *
 * Pela mesma razão **não falha a operação**: se a fila estiver em baixo, a
 * marcação já está escrita e o `booking.created` já está no outbox. Quem chama
 * decide se registra o erro; o que esta função garante é que a falta de fila não
 * desfaz uma marcação confirmada.
 */
export async function agendarLembrete(
  fila: FilaDeLembretes,
  agora: Date,
  tenantId: string,
  marcacao: Pick<Marcacao, "bookingId" | "inicioAt" | "estado">,
): Promise<Agendamento> {
  const decisao = agendamentoDaMarcacao(agora, tenantId, marcacao);
  if (decisao.agenda) await fila.agendarAdiado(decisao.trabalho);
  return decisao;
}

/**
 * Fila em memória, para os ensaios da política. Guarda por `jobId`.
 *
 * A forma do `FilaDeExpiracaoEmMemoria` do KAM-045, e pela mesma razão: o que os
 * ensaios têm de medir é a **desduplicação** e o atraso calculado, e nenhuma das
 * duas precisa de Redis.
 */
export class FilaDeLembretesEmMemoria implements FilaDeLembretes {
  readonly #adiados = new Map<string, TrabalhoDoLembrete>();
  /** Quantas vezes se agendou, **incluindo** os repetidos. */
  chamadas = 0;

  async agendarAdiado(trabalho: TrabalhoDoLembrete): Promise<void> {
    this.chamadas += 1;
    // `if (!has)` e não `set` directo, que é o que a desduplicação por `jobId`
    // significa: o primeiro ganha. Ver a nota do KAM-045 — um `set`
    // incondicional deixava a contagem de distintos certa e a desduplicação
    // errada, pelo que um ensaio que só contasse não distinguia as duas.
    if (!this.#adiados.has(trabalho.jobId)) {
      this.#adiados.set(trabalho.jobId, trabalho);
    }
  }

  /** Os *jobs* distintos, por `jobId`. */
  adiados(): Map<string, TrabalhoDoLembrete> {
    return new Map(this.#adiados);
  }

  /** Quantos *jobs* distintos ficaram agendados. */
  contar(): number {
    return this.#adiados.size;
  }
}
