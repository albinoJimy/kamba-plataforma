/**
 * O *shim* da fila do AGR: `agr-inbound` → `POST /internal/turn` (KAM-025).
 *
 * É casca, como o `entrada/trabalhador.ts` e o `eventos/trabalhador_bullmq.ts`:
 * a decisão toda — tranca por conversa, coalescência, tectos, quem tem a
 * palavra — vive no AGR, em Python, e testa-se sem fila nenhuma. Aqui só se
 * traduz entre o BullMQ e um pedido HTTP.
 *
 * A escolha está em `docs/adr/ADR-L004-fila-e-tranca-do-agr.md` (Decisão 1). Em
 * duas linhas: o AGR tem de saber correr um turno a partir de um pedido HTTP de
 * qualquer forma (é o critério 1, e é a retoma do `docs/tecnica/02` §11 regra
 * 3), e a alternativa — `bullmq` para Python — assentava numa compatibilidade
 * de protocolo entre a versão 3.3.1 e a 6.3.11 que nenhum documento deste
 * conjunto mediu.
 *
 * ## O que se reutiliza, e porque é que não se reutiliza o resto
 *
 * Reutiliza-se tudo o que custou a aprender: a `LIGACAO_QUE_ESPERA` (o BullMQ
 * recusa um `Worker` com `maxRetriesPerRequest` diferente de `null`), o cliente
 * `ioredis` construído à mão e passado como instância (o `require` dinâmico
 * falha em ESM), o ouvinte de `error` que impede uma queda da fila de derrubar
 * o processo, e o `aoFalhar` — **sem ele, um *job* que falha não deixa linha
 * nenhuma**, que é a lição medida na *suite* `tests_entrada`.
 *
 * Não se reutiliza o `criarTrabalhadores` do KAM-006: aquele lê um envelope do
 * `events_log` pelo `event_id` do *job*, põe contexto de tenant e abre DLQ.
 * Um *job* desta fila é um `agent_invocation` que **já traz** o `tenant_id`
 * resolvido pelo CHR, não tem `event_id` e não tem agregado.
 *
 * ## Este ficheiro é a **decisão**; a casca está ao lado
 *
 * O `new Worker` e o cliente `ioredis` vivem em `trabalhador.ts`, e a divisão
 * não é estética: é a de `chr/invocacao.ts` contra `chr/fila.ts`, escrita em
 * `ci/thresholds.yaml`. Casca sobre o BullMQ só se exercita com uma fila real,
 * que não produz cobertura V8; o que **pode errar em silêncio** é a tabela de
 * tradução de estados HTTP abaixo, e essa mede-se sem fila nenhuma.
 *
 * ## A concorrência não é 1, e é a única vez neste repositório
 *
 * Os outros dois *workers* da casa têm concorrência 1, e a razão escrita é a
 * mesma nos dois: o trabalho é uma transacção curta numa ligação à base, e duas
 * transacções da mesma ligação intercalavam `BEGIN`/`COMMIT`. **Aqui não há
 * ligação à base nenhuma**: há um `fetch`. Um *worker* com concorrência 1 a
 * esperar 3–7 s por turno processava, no limite, uns dez turnos por minuto —
 * e o que serializa por conversa é a tranca do AGR, não este número.
 *
 * ## O que o *shim* **nunca** faz
 *
 * **Não olha para dentro do `agent_invocation`.** Não lê o `tenant_id`, não
 * reconstrói o `thread_id`, não decide nada com o `modo`. Passa o corpo do
 * *job* como veio e deixa o AGR validá-lo — que é quem tem o contrato
 * (`contexto.ler_invocacao`). Um *shim* que validasse era uma segunda
 * implementação do mesmo contrato, a divergir.
 *
 * **Não registra o `wamid`.** Ele carrega o número do interlocutor codificado
 * em base64 (INDÍCIO, `docs/logs.md` §2.1). O que vai a registo é o desfecho e
 * o estado HTTP.
 */

import { UnrecoverableError } from "bullmq";

import { atrasoDaTentativaDoConsumidor } from "../eventos/consumo.ts";
import {
  CABECALHO_INTERNO,
  CAMINHO_DO_TURNO,
  ESPERA_MAXIMA_MS,
  TENTATIVAS,
  type DesfechoDoAgr,
  desfechoDe,
} from "./contrato.ts";

/**
 * Os ajustes do *worker*, numa constante para terem teste **sem** fila.
 *
 * O `backoffStrategy` não é opcional: o `addLote` do `filas_bullmq.ts` põe
 * `backoff: { type: "custom" }` em todos os *jobs*, e um *worker* que o não
 * registe lança «Unknown backoff strategy custom» ao calcular o atraso da
 * segunda tentativa — e o *job* fica em `failed` sem passar por tratamento
 * nenhum. Medido na *suite* `tests_entrada`, e vale aqui pela mesma razão.
 *
 * **O `lockDuration` não está aqui**, e o comentário anterior dizia que estava:
 * ele é opção do `new Worker` e vive em `trabalhador.ts`, com a constante
 * `TRANCA_DO_JOB_MS` de `contrato.ts` — que é o que um teste lê sem abrir
 * ligação nenhuma. Achado da revisão adversarial.
 */
export const AJUSTES_DO_SHIM = {
  backoffStrategy: (tentativasFeitas: number): number =>
    atrasoDaTentativaDoConsumidor(Math.max(tentativasFeitas, 1)),
} as const;

/** O que falhou ao chamar o AGR, na forma que o *shim* devolve a quem ouve. */
export class AgrIndisponivelError extends Error {
  readonly estado: number | null;
  constructor(estado: number | null, motivo: string) {
    super(
      `o AGR nao tratou o turno (${motivo}): o job volta a fila. ` +
        "O AGR e idempotente por turn_id, pelo que a repeticao e segura",
    );
    this.name = "AgrIndisponivelError";
    this.estado = estado;
  }
}

/** Um 401 do AGR: a credencial do *shim* não serve. Não se retenta. */
export class CredencialRecusadaError extends Error {
  constructor() {
    super(
      "o AGR respondeu 401 ao x-kamba-interno deste shim: nenhuma " +
        "retentativa corrige uma credencial errada. Confirme o segredo " +
        "agr_internal_token nos dois lados (ops/secrets-inventory.yaml)",
    );
    this.name = "CredencialRecusadaError";
  }
}

export interface OpcoesDoShim {
  /** `redis://anfitriao:porta`. */
  readonly url: string;
  /** A URL base do AGR na rede interna, sem barra final. */
  readonly agr: string;
  /** A credencial interna. Lida a cada *job*, porque o segredo roda. */
  readonly credencial: () => Promise<string> | string;
  readonly fila?: string;
  readonly concorrencia?: number;
  /** Chamado por cada *job* tratado, com o desfecho e o estado HTTP. */
  readonly aoTratar?: (
    desfecho: DesfechoDoAgr | "desconhecido",
    estado: number,
  ) => void;
  /**
   * Chamado quando um *job* falha, com o erro.
   *
   * **Sem isto, um *job* que falha não deixa linha nenhuma**: o BullMQ não
   * escreve nada por si quando ninguém ouve o acontecimento `failed`, e o
   * silêncio é a pior forma de perder uma conversa.
   */
  readonly aoFalhar?: (erro: unknown, tentativa: number) => void;
  /** Injectável para teste. Por omissão, o `fetch` global. */
  readonly buscar?: typeof fetch;
}

/**
 * Chama `POST /internal/turn` e traduz a resposta em «repete» ou «não repete».
 *
 * A tradução é a tabela de `api_interna.py`, e está aqui porque é o único
 * sítio onde a decisão do *shim* vive:
 *
 * | Estado | O que isto faz |
 * |---|---|
 * | 2xx | devolve: o *job* completa |
 * | 400 | `UnrecoverableError`: nenhuma retentativa conserta um corpo |
 * | 401 | `UnrecoverableError`: nenhuma retentativa conserta a credencial |
 * | 503, 5xx, rede, *timeout* | lança: o *job* volta à fila com atraso |
 *
 * O 400 e o 401 são `UnrecoverableError` pela razão que o
 * `entrada/trabalhador.ts` escreveu: gastar as seis tentativas da escada —
 * cerca de treze minutos — num *job* que se sabe irrecuperável à primeira
 * leitura é desperdício que atrasa os outros.
 */
export async function chamarOTurno(
  opcoes: OpcoesDoShim,
  dados: unknown,
): Promise<{ desfecho: DesfechoDoAgr | "desconhecido"; estado: number }> {
  const buscar = opcoes.buscar ?? fetch;
  const credencial = await opcoes.credencial();
  // `AbortSignal.timeout` e nao um `setTimeout` a mao: sem corte, um AGR que
  // aceita a ligacao e nunca responde segura o *job* para alem do
  // `lockDuration`, e o BullMQ declara-o `stalled` com este *worker* vivo — o
  // turno corria duas vezes em dois processos.
  let resposta: Response;
  try {
    resposta = await buscar(`${opcoes.agr}${CAMINHO_DO_TURNO}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        [CABECALHO_INTERNO]: credencial,
      },
      body: JSON.stringify(dados),
      signal: AbortSignal.timeout(ESPERA_MAXIMA_MS),
    });
  } catch (erro) {
    // Rede, DNS, ligacao recusada, ou o corte acima. Todos se retentam.
    throw new AgrIndisponivelError(null, (erro as Error).name || "rede");
  }

  if (resposta.status === 401) throw new UnrecoverableError(new CredencialRecusadaError().message);

  let corpo: unknown = null;
  try {
    corpo = await resposta.json();
  } catch {
    // Um corpo que nao e JSON nao muda a decisao, que e do estado HTTP.
    corpo = null;
  }
  const desfecho = desfechoDe(corpo);

  if (resposta.status === 400) {
    throw new UnrecoverableError(
      `o AGR recusou o corpo do job (400, ${desfecho}): nenhuma retentativa ` +
        "acrescenta um campo que falta. O job vem do CHR (KAM-014)",
    );
  }
  if (resposta.status >= 500 || resposta.status === 429) {
    throw new AgrIndisponivelError(resposta.status, `http_${resposta.status}`);
  }
  if (!resposta.ok) {
    // 3xx e os 4xx que sobram. Nao se retentam: nao melhoram.
    throw new UnrecoverableError(
      `o AGR respondeu ${resposta.status} (${desfecho}), que este shim nao sabe tratar`,
    );
  }
  return { desfecho, estado: resposta.status };
}

export { TENTATIVAS };
