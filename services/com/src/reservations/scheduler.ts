/**
 * O agendamento da expiração: *job* repetível e *delayed job* (KAM-045).
 *
 * O critério 4 pede dois agendamentos e que os dois sejam idempotentes:
 *
 * ```text
 * repetível (1 min)   a rede de segurança: varre tudo o que venceu
 * delayed por reserva o caminho rápido: acorda no instante do `expira_at`
 * ```
 *
 * **Os dois, e não um.** O repetível sozinho dá um atraso médio de meio minuto e
 * um pior caso de um minuto inteiro, o que cabe no «p99 ≤ 60 s» por pouco e não
 * cabe se uma volta demorar. O *delayed* sozinho perde as reservas cujo *job* se
 * perdeu (Redis reiniciado, *job* removido, processo morto entre reservar e
 * agendar) — e essas ficariam presas para sempre, que é o modo de falha que o
 * repetível existe para fechar.
 *
 * ## A idempotência é por `jobId`, e o `jobId` leva a `version`
 *
 * ```text
 * jobIdDaReserva(id, version)  ->  "reserva:<uuid>:<version>"
 * ```
 *
 * **A `version` no `jobId` não é enfeite, e é o que faz o `extendReservation`
 * funcionar.** Sem ela, o `jobId` de uma reserva seria sempre o mesmo e a fila
 * deduplicaria o *job* novo contra o antigo: prolongar o prazo de 48 h para 72 h
 * deixava agendado o despertar das 48 h, e a reserva era varrida ao prazo
 * **antigo**. Com a `version`, o prolongamento produz um `jobId` novo — e o
 * *job* antigo, quando dispara, encontra a reserva com outra `version` e o CAS
 * do `SQL_LIBERTAR_UMA` recusa-o. Os dois lados fecham: o novo acorda à hora
 * certa, o velho não faz nada.
 *
 * Enfileirar o mesmo `(reserva, version)` duas vezes deixa **um** *job*, que é
 * a propriedade que o `Filas.addLote` do `@kamba/core-ts/eventos` já exige de si
 * mesmo («chamar duas vezes com o mesmo `jobId` deixa um *job*, não dois»).
 *
 * ## Porque é que este ficheiro tem um porto próprio em vez do `Filas` do core
 *
 * O `Filas` de `@kamba/core-ts/eventos/filas` é o porto do **publicador de
 * eventos**, e o `Trabalho` dele não tem campo de atraso — o publicador entrega
 * agora, não daqui a 48 h. Um *delayed job* não se expressa nele.
 *
 * Alargar o `Trabalho` com um `atraso` era mexer no contrato partilhado que o
 * publicador do **KAM-005** usa, e por uma necessidade que só este ticket tem.
 * Por isso aqui há um porto estreito — `FilaDeExpiracao`, dois métodos — e a
 * política (nomes, `jobId`, intervalos) vive em funções puras que se medem sem
 * fila nenhuma.
 *
 * **O que isto deixa por ligar, e fica dito com credor:** a implementação deste
 * porto sobre BullMQ não existe. O `FilasBullmq` do core serve o publicador e
 * não tem `delay`; escrevê-la exige decidir onde corre o *worker* da expiração —
 * o `services/com` não tem processo de fila hoje (nem dependência directa de
 * `bullmq`), e o `services/worker-canal` é o anfitrião natural. É **decisão de
 * arquitectura** e não trabalho deste ticket: credor o **KAM-071**, dono do
 * varrimento agendado, como o dicionário §3.43 já registou para o *job* da
 * reconciliação. Até lá o `varrer` corre por chamada e está medido por chamada.
 *
 * **NÃO VERIFICADO:** o «p99 ≤ 60 s» do critério 4 em execução, que depende do
 * agendador que não existe. O que está medido é o **atraso por libertação**
 * (`atrasosDaLibertacao`, lido da base) e a aritmética: com o repetível a cada
 * minuto, o pior caso é um minuto mais a duração de uma volta.
 */

import { ATIVA, type Reserva } from "./contrato.ts";

/**
 * O intervalo do *job* repetível: **um minuto**, que é a letra do critério 4.
 *
 * Não é *proposta*: o critério escreve «*job* repetível (1 min)». O que é
 * *proposta* é o `LOTE_DO_VARRIMENTO` do `./expire.ts`, porque o critério não
 * diz quantas reservas cabem numa volta.
 */
export const INTERVALO_DO_VARRIMENTO_MS = 60_000;

/** O nome da fila da expiração de reservas. */
export const FILA_DA_EXPIRACAO = "com:reservas:expiracao";

/** O nome do *job* repetível dentro dela. */
export const JOB_DO_VARRIMENTO = "varrer-vencidas";

/** O nome do *job* adiado de uma reserva. */
export const JOB_DA_RESERVA = "expirar-reserva";

/** O `jobId` do *job* repetível. Um só, para toda a plataforma. */
export const JOB_ID_DO_VARRIMENTO = "varrimento:global";

/**
 * O `jobId` de um *job* adiado. Ver a nota do módulo para a razão da `version`.
 *
 * Determinístico e sem relógio: o mesmo par dá sempre a mesma cadeia, e é isso
 * que deixa a fila deduplicar. Um `jobId` com instante lá dentro produzia uma
 * cadeia nova a cada chamada e a desduplicação não acontecia nunca.
 */
export function jobIdDaReserva(reservationId: string, version: number): string {
  return `reserva:${reservationId}:${version}`;
}

/** Um *job* adiado, pronto a enfileirar. */
export interface TrabalhoAdiado {
  readonly jobId: string;
  readonly nome: string;
  /** Milissegundos a partir de agora. Nunca negativo — ver o `atrasoAte`. */
  readonly atrasoMs: number;
  readonly dados: {
    readonly reservationId: string;
    readonly tenantId: string;
    readonly orderId: string;
    readonly version: number;
  };
}

/** O porto estreito da fila da expiração. Ver a nota do módulo. */
export interface FilaDeExpiracao {
  /** Agenda (ou reafirma) o *job* repetível. Idempotente pelo `jobId`. */
  agendarRepetivel(intervaloMs: number): Promise<void>;
  /** Agenda um *job* adiado. Idempotente pelo `jobId`. */
  agendarAdiado(trabalho: TrabalhoAdiado): Promise<void>;
}

/**
 * O atraso até um instante, **nunca negativo**.
 *
 * Uma reserva já vencida quando se agenda — o que acontece se o processo
 * demorou entre reservar e agendar, ou se o `expira_at` veio de um
 * `extendReservation` para trás — dá atraso **zero**, isto é, «corre já». Um
 * atraso negativo era rejeitado pela fila ou, pior, interpretado como
 * milissegundos no futuro por um `Math.abs` em algum lado.
 */
export function atrasoAte(agora: Date, instante: string): number {
  const alvo = new Date(instante).getTime();
  if (Number.isNaN(alvo)) return 0;
  return Math.max(0, alvo - agora.getTime());
}

/**
 * O *job* adiado de uma reserva, ou `null` se ela não precisar de um.
 *
 * Só as **activas** precisam: uma reserva `consumida` ou `libertada` não expira,
 * e agendar-lhe um despertar era pôr na fila trabalho que a chegada só pode
 * recusar. Devolver `null` em vez de um *job* inútil é o que mantém a fila
 * proporcional ao que está em curso e não ao histórico.
 */
export function trabalhoDaReserva(
  agora: Date,
  tenantId: string,
  reserva: Reserva,
): TrabalhoAdiado | null {
  if (reserva.estado !== ATIVA) return null;
  return {
    jobId: jobIdDaReserva(reserva.reservationId, reserva.version),
    nome: JOB_DA_RESERVA,
    atrasoMs: atrasoAte(agora, reserva.expiraAt),
    dados: {
      reservationId: reserva.reservationId,
      tenantId,
      orderId: reserva.orderId,
      version: reserva.version,
    },
  };
}

/**
 * Agenda o despertar das reservas que acabaram de ser criadas ou prolongadas.
 *
 * Chama-se **depois** do `COMMIT` de quem reservou, e isso é deliberado: um
 * *job* agendado dentro da transacção podia disparar antes de ela confirmar, e
 * encontrar uma reserva que ainda não existe — o *job* não faria nada (o CAS não
 * casa) e o despertar estaria perdido, com a reserva a depender só do repetível.
 *
 * Pela mesma razão **não falha a operação**: se a fila estiver em baixo, a
 * reserva já está escrita e o repetível apanha-a. Quem chama decide se registra
 * o erro; o que este módulo garante é que a falta de fila não desfaz stock já
 * prometido.
 */
export async function agendarExpiracoes(
  fila: FilaDeExpiracao,
  agora: Date,
  tenantId: string,
  reservas: readonly Reserva[],
): Promise<readonly TrabalhoAdiado[]> {
  const agendados: TrabalhoAdiado[] = [];
  for (const reserva of reservas) {
    const trabalho = trabalhoDaReserva(agora, tenantId, reserva);
    if (trabalho === null) continue;
    await fila.agendarAdiado(trabalho);
    agendados.push(trabalho);
  }
  return agendados;
}

/**
 * Fila em memória, para os ensaios da política. Guarda por `jobId`.
 *
 * A forma do `FilasEmMemoria` de `@kamba/core-ts/eventos/filas`, e pela mesma
 * razão: o que os ensaios do critério 4 têm de medir é a **desduplicação** e o
 * atraso calculado, e nenhuma das duas precisa de Redis.
 */
export class FilaDeExpiracaoEmMemoria implements FilaDeExpiracao {
  readonly #adiados = new Map<string, TrabalhoAdiado>();
  /** Quantas vezes se agendou, **incluindo** os repetidos. */
  chamadas = 0;
  /** O intervalo com que o repetível foi agendado, ou `null`. */
  intervalo: number | null = null;

  async agendarRepetivel(intervaloMs: number): Promise<void> {
    this.intervalo = intervaloMs;
  }

  async agendarAdiado(trabalho: TrabalhoAdiado): Promise<void> {
    this.chamadas += 1;
    // **`if (!has)` e não `set` directo**, que é o que a desduplicação por
    // `jobId` significa: o primeiro ganha. Um `set` incondicional substituía o
    // *job* e a contagem de distintos continuava certa — pelo que um ensaio
    // que só contasse não distinguia as duas, e a que a fila a sério faz é
    // esta.
    if (!this.#adiados.has(trabalho.jobId)) {
      this.#adiados.set(trabalho.jobId, trabalho);
    }
  }

  /** Os *jobs* distintos, por `jobId`. */
  adiados(): Map<string, TrabalhoAdiado> {
    return new Map(this.#adiados);
  }

  /** Quantos *jobs* distintos ficaram agendados. */
  contar(): number {
    return this.#adiados.size;
  }
}
