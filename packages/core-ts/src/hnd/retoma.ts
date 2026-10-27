/**
 * O cliente de `POST /internal/resume`: o HND pede ao AGR que retome (KAM-019).
 *
 * **Nasce da emenda 1.42 do dicionário (§3.32), que decide uma fronteira.** Até
 * ela, a `platform.handoffs` tinha dois escritores para a saída de `waiting` e o
 * deste lado corria primeiro: o `#fechar` do `receber` escrevia `resumed` e o
 * *compare-and-set* do AGR — que é o **gatilho** do `Command(resume=…)` — não
 * casava linha nenhuma, respondia 200 `repetido`, e o `interrupt()` do
 * `handoff_wait` ficava pendente para sempre (`docs/analises/ANALISE-35`,
 * achado 1). A emenda tira o `status` a este lado e põe aqui o pedido: é este
 * ficheiro o fio que faltava entre o *webhook* do Chatwoot e o grafo.
 *
 * É casca, como o `agr/shim.ts`, e a semelhança é deliberada — a decisão toda
 * (o CAS, a tranca da conversa, a classificação do zero linhas, a compensação)
 * vive no AGR, em Python, e tem prova própria contra PostgreSQL. O que aqui se
 * decide é uma coisa só, e é a que pode errar em silêncio: **a tradução da
 * resposta HTTP**.
 *
 * ## As duas credenciais, e porque são duas
 *
 * A rota pede **ambas** (`services/agr/src/kamba_agr/api_interna.py`), e provam
 * coisas diferentes:
 *
 * - **`x-kamba-interno`** (§3.24, segredo `agr_internal_token`) prova «este
 *   pedido vem de dentro da rede». É a mesma credencial que o *shim* do turno
 *   usa, e o inventário já lista o HND como consumidor dela.
 * - **`x-kamba-hnd-bot`** (§3.32, segredo `chatwoot_bot_secret`) prova «este
 *   pedido vem do *agent bot* **deste tenant**». É **por conta**, como o
 *   `chatwoot_bot_token`, e é por isso que se resolve a partir do `thread_id`:
 *   com só a primeira, qualquer componente interno retomava a passagem de
 *   qualquer *tenant*.
 *
 * **O mesmo segredo com que o HND verifica o *callback* é o que ele apresenta
 * aqui**, e isso é o desenho e não um atalho: o §3.32 dá-lhe «dois
 * consumidores», e os dois são estes dois lados do mesmo bot.
 *
 * ## O que se repete e o que não se repete
 *
 * A tabela é a do `api_interna.py`, lida do lado de quem chama:
 *
 * | Resposta | O que isto faz |
 * |---|---|
 * | 200 `retomado` / `repetido` | devolve o desfecho: tratado |
 * | 404 `recusado` | **levanta**: a passagem não é deste *thread*, e isso é um defeito nosso |
 * | 400 | **levanta**: nenhuma repetição acrescenta um campo que falta |
 * | 401 | **levanta**: nenhuma repetição conserta uma credencial |
 * | 503 com `Retry-After` | espera o que ele pede e tenta outra vez; **nada foi escrito** |
 * | 5xx, rede, corte | **levanta**: o AGR já devolveu a passagem a `waiting` |
 *
 * **O 401 não se engole**, e é a regra que esta casa já escreveu para o
 * `CredencialRecusadaError` do *shim*: um `secret` errado dos dois lados fazia
 * **todas** as retomas falharem, e com um `catch` silencioso o sintoma era
 * conversas mortas sem um único registo — exactamente o defeito que a emenda
 * 1.42 corrige, com outra causa.
 *
 * **O 404 levanta e isso merece a razão por extenso.** Do lado do AGR o
 * `recusado` é «esta passagem não é deste *thread*», que ele trata como pedido
 * de fora (404 e não 403, para não confirmar a existência de uma passagem de
 * outro — ADR-015). Mas **nós** derivámos o `thread_id` da própria linha da
 * passagem, com o `external_id` do *callback* no predicado
 * (`SQL_THREAD_DA_PASSAGEM`): se ele nos recusa, as duas leituras da mesma
 * verdade divergiram, e isso é um defeito e não um ataque. Tratá-lo como
 * «normal» era deixar o painel a contar recusas de isolamento que são nossas.
 *
 * ## O 503 repete-se **aqui** e o 5xx não, e a diferença é a janela
 *
 * Esta chamada corre **dentro** do pedido do *webhook* do Chatwoot: o tempo que
 * ela leva é tempo que ele espera, e um provedor que desista fecha a ligação e
 * reenvia. Por isso só se repete o caso em que repetir é curto e seguro —
 * o 503, que o AGR dá quando não há grafo para a *thread* e em que **nada foi
 * escrito** — e nunca mais do que o que o `TECTO_DA_ESPERA_MS` permite. Um 5xx
 * (o `Command` levantou) também é seguro de repetir, mas aí já houve ida e volta
 * à base e uma compensação: é mais honesto devolver o erro e deixar o
 * *webhook* voltar, que é a retentativa com a escada do provedor em vez de uma
 * nossa dentro do pedido dele.
 *
 * E a idempotência que sustenta qualquer destas repetições não é nossa: é o CAS
 * do AGR. Dois pedidos com o mesmo `handoff_id` dão **uma** retoma, e o segundo
 * sai `repetido` — é o critério 3 do KAM-034, provado contra PostgreSQL.
 */

import { Logger } from "../logger/index.ts";
import { CABECALHO_INTERNO } from "../agr/contrato.ts";
import type { Outcome } from "./contrato.ts";

/** O caminho da rota que retoma uma passagem. Dicionário §3.24 e §3.32. */
export const CAMINHO_DA_RETOMA = "/internal/resume";

/**
 * O cabeçalho que leva o `secret` do *agent bot*. Dicionário §3.32.
 *
 * O mesmo nome que o `CABECALHO_DO_BOT` do `handoff/autenticacao.py` do AGR, e
 * há ensaio a confrontar os dois ficheiros: é uma cadeia de texto em dois
 * idiomas, e a única coisa que impede os dois lados de divergirem é alguém
 * medir que não divergiram.
 */
export const CABECALHO_DO_BOT = "x-kamba-hnd-bot";

/**
 * Os três desfechos de uma retoma, como o AGR os devolve. Lista **fechada**.
 *
 * São os do §3.32 e os do `DESFECHOS_DA_RETOMA` do `handoff/retoma.py`:
 * `retomado` venceu o CAS, `repetido` é o *webhook* duplicado, e `recusado` é a
 * passagem que não é deste *thread* — este último não chega a sair desta função
 * como valor, porque levanta.
 */
export const DESFECHOS_DA_RETOMA = ["retomado", "repetido", "recusado"] as const;

export type DesfechoDaRetoma = (typeof DESFECHOS_DA_RETOMA)[number];

/**
 * Quanto tempo o `fetch` espera, em ms. *Proposta*.
 *
 * Dez segundos e não os trinta do turno (`agr/contrato.ts`), e a razão é a
 * janela: esta chamada corre dentro do pedido do *webhook* do provedor, e o
 * trabalho do outro lado é um `UPDATE` e um `Command` sobre um grafo
 * interrompido — não é um turno de 3–7 s com LLM. Calibra-se em KAM-084.
 */
export const ESPERA_DA_RETOMA_MS = 10_000;

/**
 * Quantas vezes se pede a retoma, contando a primeira. **Duas.**
 *
 * Uma repetição e não cinco, pela razão escrita no cabeçalho: o tempo é o do
 * *webhook*. Com o AGR a responder 503 duas vezes, devolve-se o erro e deixa-se
 * o provedor reenviar — a escada dele é mais larga do que qualquer uma que se
 * possa gastar aqui dentro.
 */
export const TENTATIVAS_DA_RETOMA = 2;

/**
 * O que se espera entre tentativas quando o 503 não traz `Retry-After`, em ms.
 *
 * O mesmo valor que o `ESPERAR_SEGUNDOS` do `api_interna.py` propõe, em ms.
 */
export const ESPERA_POR_OMISSAO_MS = 5_000;

/**
 * O tecto do que se espera entre tentativas, em ms, **mesmo se o AGR pedir
 * mais**.
 *
 * Um `Retry-After: 120` cumprido à letra segurava o *webhook* do provedor dois
 * minutos — e o provedor desiste muito antes, pelo que o que se conseguia era
 * manter uma ligação aberta para nada e responder-lhe depois de ele a ter
 * fechado. Acima do tecto não se espera: levanta-se, e a retentativa é a dele.
 */
export const TECTO_DA_ESPERA_MS = 5_000;

/** O corpo de `/internal/resume`: três campos de forma fechada (§3.32). */
export interface PedidoDeRetoma {
  /** `{tenant_id}:{contact_id}` (§3.1). */
  readonly threadId: string;
  readonly handoffId: string;
  /** Um dos três do §11.1. Atravessa o `interrupt()` sem tradução. */
  readonly outcome: Outcome;
}

/** O que o cliente precisa para funcionar. */
export interface OpcoesDaRetoma {
  /** A URL base do AGR na rede interna, sem barra final. */
  readonly agr: string;
  /**
   * A credencial interna (`x-kamba-interno`). Lida a cada pedido.
   *
   * Função e não cadeia, pela razão do `api_interna.py` e do *shim*: o segredo
   * roda (`ops/secrets-inventory.yaml`, `agr_internal_token`, 90 dias), e um
   * valor lido uma vez no arranque ficava a levar 401 depois da rotação.
   */
  readonly credencial: () => Promise<string> | string;
  /**
   * O `secret` do *agent bot* de um *tenant* (`x-kamba-hnd-bot`).
   *
   * É a **mesma** porta que o `segredoDoBot` do `provedor.ts` usa para verificar
   * os *callbacks*: um segredo, dois sentidos (§3.32).
   */
  readonly segredoDoBot: (tenantId: string) => Promise<string> | string;
  /** Injectável para teste. Por omissão, o `fetch` global. */
  readonly buscar?: typeof fetch;
  /** Injectável para teste: sem isto, um ensaio do 503 esperava 5 s a sério. */
  readonly esperar?: (ms: number) => Promise<void>;
  readonly log?: Logger;
}

/** O `thread_id` de um par, na forma do §3.1. */
export function threadDe(tenantId: string, contactId: string): string {
  return `${tenantId}:${contactId}`;
}

/**
 * O `tenant_id` de um `thread_id`, ou `null` se ele não tem a forma.
 *
 * A mesma leitura que o `tenant_do_thread` do `handoff/autenticacao.py` faz do
 * outro lado, e pela mesma razão: o segredo é por bot, logo por *tenant*, e o
 * *tenant* sai do prefixo e **não** de um campo do corpo — um `tenant_id`
 * escrito por quem chama é um `tenant_id` que alguém pode trocar.
 *
 * Corta no **primeiro** `:` e um prefixo vazio devolve `null`: `":x"` não é um
 * *tenant*, e pedir o segredo de uma cadeia vazia era pedir ao cofre uma
 * referência que não existe.
 */
export function tenantDoThread(threadId: string): string | null {
  const separador = threadId.indexOf(":");
  if (separador <= 0) return null;
  return threadId.slice(0, separador);
}

/** O AGR recusou a credencial. Nenhuma repetição a conserta. */
export class RetomaNaoAutorizadaError extends Error {
  constructor() {
    super(
      "o AGR respondeu 401 a /internal/resume: nenhuma retentativa corrige uma " +
        "credencial errada. Confirme o agr_internal_token e o " +
        "chatwoot_bot_secret deste tenant nos dois lados " +
        "(ops/secrets-inventory.yaml). Enquanto isto durar, nenhuma passagem " +
        "resolvida por um humano retoma o grafo",
    );
    this.name = "RetomaNaoAutorizadaError";
  }
}

/**
 * O AGR respondeu 404 `recusado`: a passagem não é deste *thread*.
 *
 * **É um defeito nosso e não um pedido de fora.** Ver o cabeçalho: o
 * `thread_id` foi derivado da própria linha da passagem, com o `external_id` do
 * *callback* no predicado, pelo que as duas leituras da mesma verdade
 * divergiram.
 */
export class RetomaRecusadaError extends Error {
  constructor(handoffId: string) {
    super(
      `o AGR respondeu 404 recusado a /internal/resume (handoff ${handoffId}): ` +
        "a passagem nao e do thread que lhe pedimos. O thread_id vem da linha " +
        "da passagem (SQL_THREAD_DA_PASSAGEM), pelo que isto e divergencia " +
        "entre os dois lados e nao isolamento a morder",
    );
    this.name = "RetomaRecusadaError";
  }
}

/** O AGR recusou o corpo (400). Nenhuma repetição acrescenta um campo. */
export class CorpoDaRetomaRecusadoError extends Error {
  constructor(codigo: string) {
    super(
      `o AGR recusou o corpo de /internal/resume (400, ${codigo}): os tres ` +
        "campos sao de forma fechada (dicionario §3.32)",
    );
    this.name = "CorpoDaRetomaRecusadoError";
  }
}

/**
 * O AGR não tratou a retoma. Repete-se, e a repetição é segura.
 *
 * `estado` é o código HTTP, ou `null` quando foi a rede. Segura porque o CAS é
 * idempotente: no 503 nada foi escrito, no 5xx a passagem já voltou a
 * `waiting`, e em qualquer dos casos um segundo pedido com o mesmo
 * `handoff_id` dá **uma** retoma.
 */
export class RetomaIndisponivelError extends Error {
  readonly estado: number | null;
  constructor(estado: number | null, motivo: string) {
    super(
      `o AGR nao tratou a retoma (${motivo}): o webhook do provedor vai ` +
        "reenviar, e a repeticao e segura porque o compare-and-set e " +
        "idempotente por handoff_id",
    );
    this.name = "RetomaIndisponivelError";
    this.estado = estado;
  }
}

/** O desfecho que a resposta traz, ou `null` se não é dos três. */
function desfechoDe(corpo: unknown): DesfechoDaRetoma | null {
  if (typeof corpo !== "object" || corpo === null) return null;
  const valor = (corpo as Record<string, unknown>)["outcome"];
  return (DESFECHOS_DA_RETOMA as readonly string[]).includes(String(valor))
    ? (valor as DesfechoDaRetoma)
    : null;
}

/** O `error_code` da resposta, para a mensagem do 400. Nunca o corpo inteiro. */
function codigoDe(corpo: unknown): string {
  if (typeof corpo !== "object" || corpo === null) return "sem_codigo";
  const valor = (corpo as Record<string, unknown>)["error_code"];
  return typeof valor === "string" && valor.length > 0 ? valor : "sem_codigo";
}

/**
 * O que esperar antes de repetir, em ms, a partir do `Retry-After`.
 *
 * `null` quer dizer «não repitas»: ou o valor é maior do que o tecto, ou não se
 * consegue ler. Aceita-se **só** a forma em segundos — a forma de data HTTP
 * existe na norma e o AGR nunca a manda (`str(ESPERAR_SEGUNDOS)`), e aceitar um
 * formato que ninguém produz é código sem caminho.
 */
export function esperaDoRetryAfter(cabecalho: string | null): number | null {
  if (cabecalho === null || cabecalho.trim().length === 0) {
    return ESPERA_POR_OMISSAO_MS;
  }
  const segundos = Number(cabecalho.trim());
  if (!Number.isFinite(segundos) || segundos < 0) return null;
  const ms = segundos * 1000;
  return ms > TECTO_DA_ESPERA_MS ? null : ms;
}

/**
 * Pede a retoma uma vez. Devolve o desfecho, ou levanta.
 *
 * Separada do `clienteDaRetoma` para que a repetição do 503 seja legível num
 * sítio só: aqui não há estado nem contagem.
 */
async function pedirUmaVez(
  opcoes: OpcoesDaRetoma,
  pedido: PedidoDeRetoma,
  segredo: string,
): Promise<{ desfecho: DesfechoDaRetoma } | { esperar: number | null }> {
  const buscar = opcoes.buscar ?? fetch;
  const credencial = await opcoes.credencial();
  let resposta: Response;
  try {
    resposta = await buscar(`${opcoes.agr}${CAMINHO_DA_RETOMA}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        [CABECALHO_INTERNO]: credencial,
        [CABECALHO_DO_BOT]: segredo,
      },
      // **Os três campos e mais nenhum**, e a rota confirma-o:
      // `set(corpo) != set(CAMPOS_DA_RETOMA)` dá 400. Em particular **não** vai
      // o `tenant_id` (sai do prefixo do `thread_id`) nem o `resolver` (o
      // ADR-010 mantém a identidade do agente fora do AGR).
      body: JSON.stringify({
        thread_id: pedido.threadId,
        handoff_id: pedido.handoffId,
        outcome: pedido.outcome,
      }),
      // `AbortSignal.timeout` e não um `setTimeout` à mão, pela razão do
      // *shim*: sem corte, um AGR que aceita a ligação e nunca responde segura o
      // pedido do *webhook* até o provedor desistir.
      signal: AbortSignal.timeout(ESPERA_DA_RETOMA_MS),
    });
  } catch (erro) {
    throw new RetomaIndisponivelError(null, (erro as Error).name || "rede");
  }

  if (resposta.status === 401) throw new RetomaNaoAutorizadaError();

  let corpo: unknown = null;
  try {
    corpo = await resposta.json();
  } catch {
    // Um corpo que não é JSON não muda a decisão, que é do estado HTTP.
    corpo = null;
  }

  if (resposta.status === 404) throw new RetomaRecusadaError(pedido.handoffId);
  if (resposta.status === 400) throw new CorpoDaRetomaRecusadoError(codigoDe(corpo));
  if (resposta.status === 503) {
    return { esperar: esperaDoRetryAfter(resposta.headers.get("retry-after")) };
  }
  if (resposta.status >= 500) {
    throw new RetomaIndisponivelError(resposta.status, `http_${resposta.status}`);
  }
  const desfecho = desfechoDe(corpo);
  if (!resposta.ok || desfecho === null) {
    // Um 2xx com um desfecho que não é dos três é tão mau como um 3xx: a rota
    // tem três e mais nenhum, e inventar um quarto aqui era aceitar que o outro
    // lado mudou de contrato sem ninguém reparar.
    throw new RetomaIndisponivelError(
      resposta.status,
      `resposta_inesperada_${resposta.status}`,
    );
  }
  return { desfecho };
}

/**
 * Fecha as opções num `retomar(pedido)` — a porta que o `Handoff` recebe.
 *
 * Uma função e não uma classe: não há estado nenhum para guardar entre
 * chamadas, e o que o `provedor.ts` precisa é de uma porta que ele possa
 * substituir no ensaio sem levantar um servidor.
 */
export function clienteDaRetoma(
  opcoes: OpcoesDaRetoma,
): (pedido: PedidoDeRetoma) => Promise<DesfechoDaRetoma> {
  return async (pedido: PedidoDeRetoma): Promise<DesfechoDaRetoma> => {
    const tenantId = tenantDoThread(pedido.threadId);
    if (tenantId === null) {
      // Não chega a sair daqui: o `thread_id` é construído por nós, a partir da
      // linha da passagem. Verifica-se porque um 401 do outro lado por um
      // prefixo vazio era um erro de credencial a apontar para o sítio errado.
      throw new CorpoDaRetomaRecusadoError("thread_id_sem_tenant");
    }
    const segredo = await opcoes.segredoDoBot(tenantId);
    const esperar = opcoes.esperar ?? ((ms: number) => new Promise((pronto) => setTimeout(pronto, ms)));

    for (let tentativa = 1; ; tentativa += 1) {
      const resultado = await pedirUmaVez(opcoes, pedido, segredo);
      if ("desfecho" in resultado) {
        if (resultado.desfecho === "repetido") {
          // Não é erro e não se registra como tal: é o *webhook* duplicado do
          // Chatwoot e o *no-op* do critério 3 a funcionar. O que **não** pode
          // acontecer é este valor aparecer no caminho feliz — era o defeito
          // que a emenda 1.42 corrige —, e é isso que o ensaio mede.
          opcoes.log?.info({ outcome: "retoma_repetida", tenant_id: tenantId });
        }
        return resultado.desfecho;
      }
      const espera = resultado.esperar;
      if (espera === null || tentativa >= TENTATIVAS_DA_RETOMA) {
        opcoes.log?.warn({ outcome: "retoma_indisponivel", tenant_id: tenantId });
        throw new RetomaIndisponivelError(503, "grafo_nao_registado");
      }
      await esperar(espera);
    }
  };
}
