/**
 * A ponte fila → consumidor Python: a **decisão** (KAM-194).
 *
 * O publicador do EVT põe um *job* por consumidor nas dezasseis partições
 * `evt.<consumer>.p<0..15>`. Quando o consumidor é Python — o AGR (KAM-038) ou o
 * IDX (KAM-061) —, alguém tem de tirar o *job* da fila e entregá-lo por HTTP. É
 * isto, pelo molde do `agr/shim.ts` (`docs/adr/ADR-L004-fila-e-tranca-do-agr.md`,
 * Decisão 1): o lado Python sabe tratar uma entrega HTTP de qualquer forma, e
 * a alternativa — `bullmq` para Python — assentava numa compatibilidade de
 * protocolo que nenhum documento deste conjunto mediu.
 *
 * ## Este ficheiro é a decisão; a casca está ao lado
 *
 * O `new Worker` e o cliente `ioredis` vivem em `ponte_bullmq.ts`, pela divisão
 * de `agr/shim.ts` contra `agr/trabalhador.ts`: casca sobre o BullMQ só se
 * exercita com uma fila real, que não produz cobertura V8, e o que **pode errar
 * em silêncio** é a tabela de tradução de estados HTTP abaixo — que se mede sem
 * fila nenhuma.
 *
 * ## O que a ponte **nunca** faz
 *
 * **Não abre ligação à base, não importa nada do `pg` e não marca
 * `events_consumed`.** É a diferença inteira para o `trabalhador_bullmq.ts` do
 * KAM-006, e a razão de a ponte existir: aquele marca o evento em
 * `events_consumed` dentro da sua transacção, e um consumidor Python posto
 * atrás dele via o evento sempre como `duplicado`. Aqui a marca, a ordem, a DLQ
 * e o contexto de tenant são todos do lado Python; um teste lê o texto deste
 * ficheiro e do `ponte_bullmq.ts` e falha se algum importar o `pg` ou SQL.
 *
 * **Não olha para dentro do envelope.** Não o valida, não lê o tipo, não decide
 * com o agregado. Passa-o como veio — ou `null`, quando o *job* é do
 * reconciliador, que só traz o ponteiro, e o lado Python lê o arquivo. Uma ponte
 * que validasse era uma segunda implementação do contrato, a divergir.
 *
 * **Não regista o corpo**, nem o `event_id`, nem o `tenant_id`. O que vai a
 * registo e a métrica é o desfecho e o estado HTTP.
 *
 * ## A idempotência não assenta na fila
 *
 * As garantias de entrega do BullMQ continuam NÃO VERIFICADAS (L6): um *job*
 * pode chegar duas vezes. Quem garante «uma vez» é a marca em `events_consumed`,
 * do lado Python — e é por isso que repetir um 503 aqui é seguro.
 */

import { UnrecoverableError } from "bullmq";

import { CABECALHO_INTERNO } from "../agr/contrato.ts";
import { atrasoDaTentativaDoConsumidor } from "./consumo.ts";
import type { DesfechoDaPonte } from "./metricas_ponte.ts";
import { filasDe } from "./particao.ts";
import { tenantDoJob } from "./trabalhador_bullmq.ts";

export { CABECALHO_INTERNO };

/** O caminho da rota de entrega, no AGR e no IDX. */
export const CAMINHO_DO_EVENTO = "/internal/event";

/**
 * Quanto tempo o `fetch` ao consumidor espera, em ms. *Proposta*.
 *
 * Tem de ser **menor** do que o `TRANCA_DA_PONTE_MS`: um consumidor que aceita a
 * ligação e nunca responde seguraria o *job* para além do `lockDuration`, e o
 * BullMQ declarava-o `stalled` com este *worker* vivo — o evento entregue duas
 * vezes em dois processos. A marca em `events_consumed` torna isso inofensivo,
 * mas não gratuito.
 */
export const ESPERA_MAXIMA_DA_PONTE_MS = 30_000;

/**
 * O `lockDuration` de cada *worker* da ponte, em ms. *Proposta*.
 *
 * Quatro vezes a espera do `fetch`, pela razão do `TRANCA_DO_JOB_MS` do AGR: o
 * tempo que o *job* fica aberto é a espera **mais** a admissão do lado Python
 * (a vaga do *tenant* no AGR), que não tem tecto fixo.
 */
export const TRANCA_DA_PONTE_MS = 120_000;

/**
 * Quantos *jobs* cada fila trata ao mesmo tempo.
 *
 * **Um**, como o `trabalhador_bullmq.ts`: uma fila é uma partição, e a ordem só
 * vale dentro dela (`docs/tecnica/06` §6.5). Dois *jobs* da mesma partição em
 * paralelo chegavam ao lado Python fora de ordem — e um consumidor com
 * `exige_ordem` adiava-os, gastando tentativas no que a ponte desordenou. A
 * concorrência do processo vem das dezasseis filas por consumidor.
 *
 * **E não se escala com réplicas**, ao contrário do que esta nota dizia: a
 * `concurrency` do BullMQ é por instância de *worker*, e duas réplicas tiravam
 * dois *jobs* da mesma partição ao mesmo tempo. O `tools/compose_prod` limita
 * os serviços da ponte a uma réplica. Achado da revisão adversarial.
 */
export const CONCORRENCIA_DA_PONTE = 1;

/** O nome de um consumidor servido pela ponte. */
export const NOME_DO_CONSUMIDOR = /^[a-z][a-z0-9_]*$/;

/** O corpo de `POST /internal/event`. Fechado: quatro campos, nem mais um. */
export interface CorpoDaEntrega {
  readonly event_id: string;
  readonly tenant_id: string;
  /** O envelope convertido, do publicador; `null` num *job* do reconciliador. */
  readonly envelope: unknown;
  /** A tentativa em curso, a contar de 1. */
  readonly tentativas: number;
}

/** O que a ponte lê de um *job*: o `Job` do BullMQ satisfaz isto. */
export interface JobDaPonte {
  readonly id?: string | undefined;
  readonly data: unknown;
  readonly attemptsMade: number;
}

export interface OpcoesDaChamada {
  /** A URL base do consumidor na rede interna, sem barra final. */
  readonly alvo: string;
  /** A credencial interna. Lida a cada *job*, porque o segredo roda. */
  readonly credencial: () => Promise<string> | string;
  /** Injectável para teste. Por omissão, o `fetch` global. */
  readonly buscar?: typeof fetch;
}

/** Um 503: o consumidor pediu para voltar depois de `atrasoMs`. */
export class RepetirDepoisError extends Error {
  readonly atrasoMs: number;
  readonly estado = 503;
  constructor(atrasoMs: number) {
    super(
      `o consumidor respondeu 503: o job volta a fila daqui a ${atrasoMs} ms. ` +
        "A marca de consumo, do lado Python, torna a repeticao segura",
    );
    this.name = "RepetirDepoisError";
    this.atrasoMs = atrasoMs;
  }
}

/** Outro 5xx, um 429, a rede ou o corte: volta pela escada do consumidor. */
export class ConsumidorIndisponivelError extends Error {
  readonly estado: number | null;
  /** `rede`, `timeout` ou `http_<estado>`: lista curta, cabe no `error_code`. */
  readonly motivo: string;
  constructor(estado: number | null, motivo: string) {
    super(
      `o consumidor nao tratou o evento (${motivo}): o job volta a fila pela ` +
        "escada do §6.4",
    );
    this.name = "ConsumidorIndisponivelError";
    this.estado = estado;
    this.motivo = motivo;
  }
}

/**
 * Uma resposta que nenhuma retentativa conserta: 400, 401, 3xx, outro 4xx.
 *
 * Subclasse do `UnrecoverableError`, e não um `Error` à parte, porque é pelo
 * `instanceof` dele que o BullMQ deixa de gastar tentativas — e porque o
 * processo precisa do `estado` para o registo.
 */
export class EntregaRecusadaError extends UnrecoverableError {
  readonly estado: number;
  constructor(estado: number, motivo: string) {
    super(`o consumidor recusou a entrega (${estado}): ${motivo}`);
    this.name = "EntregaRecusadaError";
    this.estado = estado;
  }
}

/**
 * Os ajustes dos *workers*, numa constante para terem teste **sem** fila.
 *
 * O `backoffStrategy` não é opcional: o publicador põe `backoff: {type:
 * "custom"}` em todos os *jobs* (`filas_bullmq.ts`), e um *worker* que o não
 * registe lança «Unknown backoff strategy custom» ao calcular o atraso da
 * segunda tentativa. Para um `RepetirDepoisError` devolve o atraso que o
 * consumidor pediu; para tudo o mais, o degrau da escada.
 *
 * O `tentativasFeitas` é o `attemptsMade` **depois** de contada a falha, isto
 * é, o mesmo número que foi no `tentativas` do corpo: a escada aqui e a do
 * 503 sem `Retry-After` dão o mesmo degrau.
 */
export const AJUSTES_DA_PONTE = {
  backoffStrategy: (tentativasFeitas: number, _tipo?: string, erro?: Error): number =>
    erro instanceof RepetirDepoisError
      ? erro.atrasoMs
      : atrasoDaTentativaDoConsumidor(Math.max(tentativasFeitas, 1)),
} as const;

/**
 * As filas de uma lista de consumidores: dezasseis por cada um.
 *
 * Recusa no arranque, e não à primeira entrega: uma lista vazia, um nome fora
 * de `^[a-z][a-z0-9_]*$` ou um nome repetido. O repetido não é cosmético: dois
 * *workers* sobre a mesma fila no mesmo processo são concorrência 2 na
 * partição, e a ordem perdia-se sem nenhuma linha a dizê-lo.
 */
export function filasDaPonte(consumidores: readonly string[]): string[] {
  if (consumidores.length === 0) {
    throw new RangeError("a ponte precisa de pelo menos um consumidor");
  }
  const vistos = new Set<string>();
  for (const consumidor of consumidores) {
    if (typeof consumidor !== "string" || !NOME_DO_CONSUMIDOR.test(consumidor)) {
      // O nome vem de configuração e não de um pedido, mas a mensagem não o
      // repete na mesma: a regra é a do `exigir`, que nomeia e não ecoa.
      throw new RangeError(
        "um consumidor da ponte nao tem a forma ^[a-z][a-z0-9_]*$",
      );
    }
    if (vistos.has(consumidor)) {
      throw new RangeError(
        "um consumidor da ponte aparece duas vezes: seriam dois workers por particao",
      );
    }
    vistos.add(consumidor);
  }
  return consumidores.flatMap((consumidor) => filasDe(consumidor));
}

/**
 * O corpo da entrega, a partir do *job*. Não valida nada.
 *
 * - `event_id` — o `jobId`, que o publicador e o reconciliador põem igual ao
 *   `event_id`;
 * - `tenant_id` — o ponteiro da fila (`tenantDoJob`), e não autoridade: o
 *   contexto de RLS do consumo sai do envelope, do lado Python;
 * - `envelope` — o do publicador, ou `null` no *job* do reconciliador, que não
 *   o traz (o lado Python lê o arquivo);
 * - `tentativas` — `attemptsMade + 1`: o `attemptsMade` conta as que **já**
 *   falharam, e o lado Python conta a partir de 1.
 *
 * Um campo em falta segue vazio, e o lado Python responde 400: é ele quem tem o
 * contrato (`ler_entrega`), e um segundo validador aqui era uma segunda
 * implementação a divergir.
 */
export function corpoDaEntrega(job: JobDaPonte): CorpoDaEntrega {
  const dados = job.data;
  const envelope =
    typeof dados === "object" && dados !== null
      ? (dados as Record<string, unknown>).envelope
      : undefined;
  return {
    event_id: job.id ?? "",
    tenant_id: tenantDoJob(dados),
    envelope: envelope === undefined ? null : envelope,
    tentativas: job.attemptsMade + 1,
  };
}

/**
 * O `Retry-After` em milissegundos, ou `null` se não houver um legível.
 *
 * Só a forma de segundos inteiros (`delay-seconds` do RFC 9110 §10.2.3), que é a
 * que o lado Python escreve. A forma de data HTTP e tudo o mais caem na escada:
 * adivinhar um relógio alheio é pior do que o degrau que já está escrito.
 */
export function atrasoDoRetryAfter(valor: string | null): number | null {
  if (valor === null) return null;
  const limpo = valor.trim();
  if (!/^[0-9]{1,9}$/.test(limpo)) return null;
  return Number(limpo) * 1_000;
}

/** Larga o corpo de uma resposta que não se vai ler, para soltar a ligação. */
async function descartar(resposta: Response): Promise<void> {
  try {
    await resposta.body?.cancel();
  } catch {
    // Um corpo que já fechou não muda nada.
  }
}

/**
 * Chama `POST ${alvo}/internal/event` e traduz a resposta.
 *
 * | Estado | O que isto faz |
 * |---|---|
 * | 2xx | devolve: o *job* completa (inclui o evento que foi para a DLQ — foi tratado) |
 * | 400, 401 | `EntregaRecusadaError` (`UnrecoverableError`): nenhuma retentativa conserta um corpo nem uma credencial |
 * | 503 | `RepetirDepoisError` com o `Retry-After × 1000`; sem ele, o degrau da escada |
 * | outro 5xx, 429, rede, *timeout* | `ConsumidorIndisponivelError`: volta pela escada |
 * | 3xx, outro 4xx | `EntregaRecusadaError`: não melhoram |
 *
 * O corpo da resposta **não se lê**: a decisão é do estado HTTP, e o desfecho
 * que o lado Python escreve lá dentro é medido por ele, nas métricas dele.
 */
export async function chamarOConsumidor(
  opcoes: OpcoesDaChamada,
  corpo: CorpoDaEntrega,
): Promise<{ outcome: DesfechoDaPonte; estado: number }> {
  const buscar = opcoes.buscar ?? fetch;
  const credencial = await opcoes.credencial();
  let resposta: Response;
  try {
    resposta = await buscar(`${opcoes.alvo}${CAMINHO_DO_EVENTO}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        [CABECALHO_INTERNO]: credencial,
      },
      body: JSON.stringify(corpo),
      // `AbortSignal.timeout` e não um `setTimeout` à mão: ver
      // `ESPERA_MAXIMA_DA_PONTE_MS`.
      signal: AbortSignal.timeout(ESPERA_MAXIMA_DA_PONTE_MS),
    });
  } catch (erro) {
    // Rede, DNS, ligação recusada, ou o corte acima. Todos se retentam.
    const nome = erro instanceof Error && erro.name === "TimeoutError" ? "timeout" : "rede";
    throw new ConsumidorIndisponivelError(null, nome);
  }

  const estado = resposta.status;
  if (resposta.ok) {
    await descartar(resposta);
    return { outcome: "entregue", estado };
  }
  const retryAfter = resposta.headers.get("retry-after");
  await descartar(resposta);

  if (estado === 400) {
    throw new EntregaRecusadaError(
      estado,
      "o corpo nao e uma entrega, e nenhuma retentativa lhe acrescenta um campo",
    );
  }
  if (estado === 401) {
    throw new EntregaRecusadaError(
      estado,
      "a credencial desta ponte nao serve. Confirme o segredo indicado em " +
        "KAMBA_PONTE_SEGREDO nos dois lados (ops/secrets-inventory.yaml)",
    );
  }
  if (estado === 503) {
    throw new RepetirDepoisError(
      atrasoDoRetryAfter(retryAfter) ?? atrasoDaTentativaDoConsumidor(corpo.tentativas),
    );
  }
  if (estado >= 500 || estado === 429) {
    throw new ConsumidorIndisponivelError(estado, `http_${estado}`);
  }
  // 3xx e os 4xx que sobram. Não se retentam: não melhoram.
  throw new EntregaRecusadaError(estado, "estado que esta ponte nao sabe tratar");
}

/**
 * Larga-se o *job* que falhou de vez? Sim, quando já não há tentativa por vir.
 *
 * **É o que faz a rede do reconciliador funcionar.** Um *job* falhado fica no
 * conjunto `failed` da fila (o `removeOnFail` guarda dez mil), e o
 * reconciliador repõe com `jobId = event_id`: o BullMQ vê a chave a existir e
 * trata a reposição como duplicado. Um 401 durante uma rotação da credencial,
 * ou o processo Python em baixo durante a escada inteira, deixava o evento sem
 * marca, sem DLQ **e** sem reposição — perdido. Largado, o reconciliador
 * repõe-no daqui a dez minutos, e a decisão volta ao lado Python, que é quem
 * a tem. Achado da revisão adversarial.
 *
 * `attemptsMade` conta as que já falharam, esta incluída (o BullMQ incrementa-o
 * antes de emitir `failed`); um `UnrecoverableError` não volta, tenha as
 * tentativas que tiver.
 */
export function largarAoFalhar(
  erro: unknown,
  attemptsMade: number,
  attempts: number | undefined,
): boolean {
  if (erro instanceof UnrecoverableError) return true;
  return attemptsMade >= (attempts ?? 1);
}

/** O desfecho de uma falha, para a métrica: recusado se não se repete. */
export function desfechoDaFalha(erro: unknown): Exclude<DesfechoDaPonte, "entregue"> {
  return erro instanceof UnrecoverableError ? "recusado" : "repetir";
}

/**
 * O `error_code` de uma falha, na forma da *allowlist* do *logger*.
 *
 * `http_503`, `rede`, `timeout`, ou `interno` para o que não veio da chamada.
 * Nunca a mensagem do erro: a do `fetch` pode levar o URL, e o URL pode levar
 * o que não devia.
 */
export function codigoDaFalha(erro: unknown): string {
  if (erro instanceof RepetirDepoisError) return "http_503";
  if (erro instanceof EntregaRecusadaError) return `http_${erro.estado}`;
  if (erro instanceof ConsumidorIndisponivelError) return erro.motivo;
  return "interno";
}
