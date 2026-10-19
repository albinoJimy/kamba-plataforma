/**
 * O *worker* da fila de entrada, sobre BullMQ (KAM-013).
 *
 * É casca, como o `eventos/trabalhador_bullmq.ts`: a decisão toda — explodir,
 * registar, encaminhar, pôr em quarentena — vive em `explosao.ts` e em
 * `services/worker-canal/src/entrada.ts`, que se testam sem fila nenhuma. Aqui
 * só se traduz entre o BullMQ e essa decisão.
 *
 * ## Porque é que não reutiliza o `criarTrabalhadores` do KAM-006
 *
 * Porque aquele consome **eventos de plataforma**: lê o envelope do
 * `events_log` pelo `event_id` do *job*, põe o contexto de tenant, verifica a
 * ordem do agregado e abre a DLQ. Nada disso existe aqui. Um *job* desta fila é
 * um **corpo de webhook da Meta** em base64; não tem `event_id`, não tem
 * `tenant_id` — o tenant só nasce no CHR (KAM-014) — e não tem agregado. Usar
 * aquele caminho obrigava a inventar um envelope para o que ainda não é um
 * evento da plataforma, e era a abstracção a mentir sobre o que atravessa.
 *
 * O que **se** reutiliza é tudo o que custou a aprender: a `LIGACAO_QUE_ESPERA`
 * (o BullMQ recusa um `Worker` com `maxRetriesPerRequest` diferente de `null`,
 * e tem razão), o cliente construído à mão e passado como instância (o
 * `require` dinâmico do `ioredis` falha em ESM) e o ouvinte de `error` que
 * impede uma queda da fila de derrubar o processo.
 *
 * ## A concorrência é 1, e aqui não é pela ordem
 *
 * No KAM-006 a concorrência 1 é a ordem dentro da partição. Aqui não há ordem a
 * preservar — a Meta entrega **sem ordem garantida e em concorrência** (`E1`
 * §5), e quem reordena é o AGR, por conversa, na janela de coalescência do
 * KAM-025. A concorrência 1 por *worker* fica porque o trabalho é uma
 * transacção curta na base e escala-se com réplicas: duas transacções da mesma
 * ligação intercalavam `BEGIN`/`COMMIT`, que é a lição que o
 * `trabalhador_bullmq.ts` já pagou.
 */

import { Worker } from "bullmq";
import { Redis } from "ioredis";

import { atrasoDaTentativaDoConsumidor } from "../eventos/consumo.ts";
import { LIGACAO_QUE_ESPERA, opcoesDaUrl } from "../eventos/filas_bullmq.ts";
import { FILA_ENTRADA, type TrabalhoDeEntrada } from "./contrato.ts";

/** Um *job* de cada vez por *worker*. Escala-se com réplicas. */
export const CONCORRENCIA = 1;

/**
 * Os ajustes do *worker*, numa constante para terem teste **sem** fila.
 *
 * **Sem o `backoffStrategy`, um *job* que falhe rebenta com «Unknown backoff
 * strategy custom» e nunca é retentado.** Medido na suite `tests_entrada`: o
 * `addLote` do `filas_bullmq.ts` põe `backoff: { type: "custom" }` em **todos**
 * os *jobs* — é a forma de o BullMQ passar a decisão do atraso ao
 * `backoffStrategy` do *worker* —, e um *worker* que o não registe lança ao
 * calcular o atraso da segunda tentativa. O sintoma era pior do que «não
 * recua»: o tratamento da falha rebentava, o *job* ficava em `failed` sem
 * passar pela quarentena, e um corpo ilegível desaparecia em silêncio com a
 * Meta a re-entregar durante sete dias.
 *
 * A escada é a do consumidor (`docs/tecnica/06` §6.4: 1 s, 5 s, 30 s, 2 min,
 * 10 min) e não uma própria, por duas razões: é a única escada do repositório,
 * e o que se retenta aqui é da mesma natureza do que se retenta lá — uma falha
 * transitória da base. O que **não** se retenta é o conteúdo do corpo: isso vai
 * à quarentena (critério 6).
 *
 * Está fora da chamada ao `new Worker` para que o teste a possa exercitar sem
 * Redis: criar um `Worker` para ler as suas opções abria uma ligação, e o
 * defeito que isto fecha não precisa de uma para ser provado.
 */
export const AJUSTES_DO_TRABALHADOR = {
  backoffStrategy: (tentativasFeitas: number): number =>
    atrasoDaTentativaDoConsumidor(Math.max(tentativasFeitas, 1)),
} as const;

/** O que um *job* desta fila traz, visto de dentro do tratador. */
export interface OpcoesDoTrabalhadorDeEntrada {
  /** `redis://anfitriao:porta`. */
  readonly url: string;
  /**
   * O que fazer com um corpo.
   *
   * Lança para o BullMQ repetir. **Nunca deve lançar por causa do conteúdo do
   * corpo** — um corpo que não encaixa vai para a quarentena, não para a
   * repetição (critério 6: nunca 5xx, para não começar sete dias de
   * re-entregas). Lança por causa da base: uma transacção que falhou merece
   * outra tentativa.
   */
  readonly tratar: (trabalho: TrabalhoDeEntrada) => Promise<void>;
  /** A fila. Por omissão, a da entrada. */
  readonly fila?: string;
  readonly concorrencia?: number;
  /**
   * Chamado quando um *job* falha, com o erro.
   *
   * **Sem isto, um *job* que falha nao deixa linha nenhuma.** Medido na suite
   * `tests_entrada`: a quarentena ficava a zero, o *worker* registava
   * `entrada_registado` para os corpos bons e **nada** para o que falhou — e
   * um `permission denied` na insercao da quarentena parecia «o corpo nunca
   * chegou». O BullMQ nao escreve nada por si quando ninguem ouve o
   * acontecimento `failed`, e o silencio e a pior forma de perder um webhook.
   */
  readonly aoFalhar?: (erro: unknown, tentativa: number) => void;
}

export interface TrabalhadorDeEntrada {
  readonly trabalhador: Worker;
  fechar(): Promise<void>;
}

/**
 * O *job* na forma que o tratador espera, ou `null` se não tiver essa forma.
 *
 * Um *job* malformado não é um corpo malformado: o corpo vem da Meta e tem
 * quarentena; o *job* vem do GWY, e um *job* sem `corpo` significa que alguém
 * escreveu nesta fila outra coisa. Devolve-se `null` e quem chama decide — o
 * que não se faz é tratar `undefined` como um corpo vazio e registar um evento
 * que nunca existiu.
 */
export function lerTrabalho(dados: unknown): TrabalhoDeEntrada | null {
  if (typeof dados !== "object" || dados === null) return null;
  const registo = dados as Record<string, unknown>;
  const corpo = registo.corpo;
  if (typeof corpo !== "string") return null;
  const recebidoEm = registo.recebidoEm;
  return {
    corpo,
    recebidoEm: typeof recebidoEm === "number" && Number.isFinite(recebidoEm)
      ? recebidoEm
      : 0,
  };
}

/** Um *job* desta fila que não tem a forma de um. */
export class TrabalhoInvalidoError extends Error {
  constructor(fila: string) {
    super(
      `um job da fila ${fila} nao traz o campo \`corpo\`: nao veio do GWY. ` +
        "Nao se trata como corpo vazio — isso registava um evento que nunca chegou",
    );
    this.name = "TrabalhoInvalidoError";
  }
}

/** Cria o *worker* da fila de entrada e devolve-o com o seu `fechar()`. */
export function criarTrabalhadorDeEntrada(
  opcoes: OpcoesDoTrabalhadorDeEntrada,
): TrabalhadorDeEntrada {
  const fila = opcoes.fila ?? FILA_ENTRADA;
  const ligacao = new Redis({ ...opcoesDaUrl(opcoes.url), ...LIGACAO_QUE_ESPERA });
  // Sem isto, um erro de ligação num cliente `ioredis` sem ouvinte de `error` é
  // uma excepção não tratada que derruba o processo — e derrubar o *worker*
  // quando a fila cai deixa o GWY a enfileirar para ninguém.
  ligacao.on("error", () => {});

  const trabalhador = new Worker(
    fila,
    async (job) => {
      const trabalho = lerTrabalho(job.data);
      if (trabalho === null) throw new TrabalhoInvalidoError(fila);
      await opcoes.tratar(trabalho);
    },
    {
      connection: ligacao,
      concurrency: opcoes.concorrencia ?? CONCORRENCIA,
      settings: AJUSTES_DO_TRABALHADOR,
    },
  );

  if (opcoes.aoFalhar !== undefined) {
    const aoFalhar = opcoes.aoFalhar;
    trabalhador.on("failed", (job, erro) => {
      // `attemptsMade` conta as que **ja** falharam, e esta e uma delas.
      aoFalhar(erro, job?.attemptsMade ?? 0);
    });
    // Um erro do proprio *worker* (a ligacao caiu, o Lua do BullMQ recusou)
    // tambem nao pode passar calado: nao tem *job* associado, e por isso
    // chega aqui e nao no `failed`.
    trabalhador.on("error", (erro) => aoFalhar(erro, 0));
  }

  return {
    trabalhador,
    async fechar(): Promise<void> {
      await trabalhador.close();
      ligacao.disconnect();
    },
  };
}
