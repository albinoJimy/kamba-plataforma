/**
 * O cliente de `POST /internal/resume`, visto de fora (KAM-019).
 *
 * **O que só aqui se prova**, e não na bateria do `provedor.ts` nem do lado do
 * AGR:
 *
 * 1. **A tradução da resposta HTTP.** É a única decisão deste ficheiro, e é a
 *    que pode errar em silêncio: um 401 engolido faz **todas** as passagens
 *    resolvidas deixarem de retomar o grafo, sem um único registo — que é o
 *    defeito que a emenda 1.42 corrige, com outra causa. A tabela que se mede é
 *    a do `api_interna.py`, lida do lado de quem chama.
 * 2. **As duas credenciais vão, e o `secret` do bot é o deste *tenant*.** O
 *    `x-kamba-interno` prova «vem de dentro da rede» e o `x-kamba-hnd-bot`
 *    prova «vem do *agent bot* deste *tenant*» (§3.32); com só a primeira,
 *    qualquer componente interno retomava a passagem de qualquer *tenant*.
 * 3. **O corpo tem três campos e mais nenhum.** A rota recusa com 400 um corpo
 *    com um quarto (`set(corpo) != set(CAMPOS_DA_RETOMA)`), pelo que um campo a
 *    mais aqui era 400 em produção e nenhum teste a apanhá-lo.
 * 4. **O 503 repete-se com o `Retry-After` e o 5xx não.** A diferença está no
 *    cabeçalho do `retoma.ts`: esta chamada corre dentro do pedido do *webhook*
 *    do provedor, e o tempo que ela leva é tempo que ele espera.
 *
 * O que **não** se mede aqui: o *compare-and-set*, que é uma instrução de
 * PostgreSQL e tem prova própria em `db/tests_agr/test_handoff_retoma.py`; e a
 * ordem das escritas do HND, que está na bateria do `provedor.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Logger } from "../src/logger/index.ts";
import {
  CABECALHO_DO_BOT,
  CAMINHO_DA_RETOMA,
  CorpoDaRetomaRecusadoError,
  ESPERA_DA_RETOMA_MS,
  ESPERA_POR_OMISSAO_MS,
  MINIMO_DA_TENTATIVA_MS,
  ORCAMENTO_DA_RETOMA_MS,
  RetomaIndisponivelError,
  RetomaNaoAutorizadaError,
  RetomaRecusadaError,
  TECTO_DA_ESPERA_MS,
  clienteDaRetoma,
  esperaDoRetryAfter,
  tenantDoThread,
  threadDe,
  type PedidoDeRetoma,
} from "../src/hnd/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const INTERNO = "a credencial interna com espacos";
const SEGREDO_DO_BOT = "o secret do agent bot desta conta";
const AGR = "http://agr.interno:8080";

const PEDIDO: PedidoDeRetoma = {
  threadId: threadDe(TENANT, CONTACTO),
  handoffId: "h_abc",
  outcome: "resolved",
};

interface Chamada {
  readonly url: string;
  readonly cabecalhos: Record<string, string>;
  readonly corpo: unknown;
}

interface Montagem {
  readonly retomar: (pedido: PedidoDeRetoma) => Promise<string>;
  readonly chamadas: Chamada[];
  readonly esperas: number[];
  readonly registo: Record<string, unknown>[];
  readonly segredosPedidos: string[];
  /** Os tectos de cada tentativa, em ms. É o que o orçamento encurta. */
  readonly tectos: number[];
}

/**
 * O cliente com o `fetch` por porta e as respostas em fila.
 *
 * `respostas` é uma lista: cada chamada consome a primeira, e a última repete-se
 * se a fila esgotar. É o que permite montar «503 e depois 200» sem contadores no
 * teste.
 */
function montar(
  respostas: {
    estado: number;
    corpo?: unknown;
    retryAfter?: string;
    /** Quanto tempo esta tentativa «demora», em ms. Avança o relógio do ensaio. */
    demora?: number;
  }[],
): Montagem {
  const chamadas: Chamada[] = [];
  const esperas: number[] = [];
  const registo: Record<string, unknown>[] = [];
  const segredosPedidos: string[] = [];
  const tectos: number[] = [];
  // O `Logger` **real** e em modo estrito: e o que recusa um campo fora da
  // *allowlist*. Um registo falso provava que o teste sabe guardar objectos.
  const log = new Logger("worker-canal", {
    estrito: true,
    relogio: () => new Date("2026-10-27T12:00:00.000Z"),
    destino: {
      write: (texto: string) => {
        registo.push(JSON.parse(texto) as Record<string, unknown>);
      },
    },
  });
  // O relógio é nosso: o orçamento total mede-se fazendo o tempo passar, não
  // esperando por ele. Um ensaio que demora o orçamento é um ensaio que ninguém
  // corre duas vezes.
  let relogio = 1_000_000;
  let i = 0;
  const buscar = (async (url: string, opcoes: RequestInit) => {
    const cabecalhos = opcoes.headers as Record<string, string>;
    chamadas.push({
      url,
      cabecalhos,
      corpo: JSON.parse(String(opcoes.body)) as unknown,
    });
    const resposta = respostas[Math.min(i, respostas.length - 1)];
    i += 1;
    relogio += resposta?.demora ?? 0;
    const cabecalhosDaResposta = new Headers();
    if (resposta?.retryAfter !== undefined) {
      cabecalhosDaResposta.set("retry-after", resposta.retryAfter);
    }
    return {
      status: resposta?.estado ?? 500,
      ok: (resposta?.estado ?? 500) < 400,
      headers: cabecalhosDaResposta,
      json: async () => resposta?.corpo ?? {},
    } as unknown as Response;
  }) as unknown as typeof fetch;

  const retomar = clienteDaRetoma({
    agr: AGR,
    credencial: () => INTERNO,
    segredoDoBot: (tenantId) => {
      segredosPedidos.push(tenantId);
      return SEGREDO_DO_BOT;
    },
    buscar,
    // **O relogio nao avanca de verdade.** Sem isto, o ensaio do 503 esperava
    // cinco segundos a serio — e um ensaio que dorme e um ensaio que ninguem
    // corre duas vezes.
    esperar: async (ms: number) => {
      esperas.push(ms);
      relogio += ms;
    },
    agora: () => relogio,
    // O corte vai por porta porque um `AbortSignal` nao diz de fora quantos ms
    // leva, e sem isto a parte do orcamento que encurta a segunda tentativa nao
    // tinha ensaio.
    cortar: (ms: number) => {
      tectos.push(ms);
      return AbortSignal.timeout(ms);
    },
    log,
  });
  return { retomar, chamadas, esperas, registo, segredosPedidos, tectos };
}

describe("o pedido que sai", () => {
  it("**vai para /internal/resume, com as duas credenciais**", async () => {
    const { retomar, chamadas } = montar([{ estado: 200, corpo: { outcome: "retomado" } }]);
    await retomar(PEDIDO);

    assert.equal(chamadas.length, 1);
    assert.equal(chamadas[0]?.url, `${AGR}${CAMINHO_DA_RETOMA}`);
    assert.equal(chamadas[0]?.cabecalhos["x-kamba-interno"], INTERNO);
    assert.equal(chamadas[0]?.cabecalhos[CABECALHO_DO_BOT], SEGREDO_DO_BOT);
    assert.equal(chamadas[0]?.cabecalhos["content-type"], "application/json");
  });

  it("**o secret do bot e o deste tenant, lido do prefixo do thread_id**", async () => {
    // O corpo nao tem campo de *tenant* e nao vai ter um: um `tenant_id`
    // escrito por quem chama e um `tenant_id` que alguem pode trocar (§3.32).
    const { retomar, segredosPedidos } = montar([
      { estado: 200, corpo: { outcome: "retomado" } },
    ]);
    await retomar(PEDIDO);

    assert.deepEqual(segredosPedidos, [TENANT]);
  });

  it("**o corpo tem os tres campos e mais nenhum**", async () => {
    const { retomar, chamadas } = montar([{ estado: 200, corpo: { outcome: "retomado" } }]);
    await retomar(PEDIDO);

    assert.deepEqual(chamadas[0]?.corpo, {
      thread_id: `${TENANT}:${CONTACTO}`,
      handoff_id: "h_abc",
      outcome: "resolved",
    });
    // A assercao negativa, que e a que apanha a regressao: a rota recusa com
    // 400 um corpo cujo conjunto de chaves nao e **exactamente** o dela.
    assert.deepEqual(Object.keys(chamadas[0]?.corpo as object).sort(), [
      "handoff_id",
      "outcome",
      "thread_id",
    ]);
  });

  it("um thread_id sem prefixo de tenant nao sai daqui", async () => {
    const { retomar, chamadas } = montar([{ estado: 200, corpo: { outcome: "retomado" } }]);
    for (const threadId of ["", ":sem-tenant", "sem-separador"]) {
      await assert.rejects(
        () => retomar({ ...PEDIDO, threadId }),
        CorpoDaRetomaRecusadoError,
        threadId,
      );
    }
    assert.deepEqual(chamadas, [], "e nao se faz chamada nenhuma");
  });
});

describe("a traducao da resposta", () => {
  it("200 retomado e 200 repetido devolvem o desfecho", async () => {
    for (const desfecho of ["retomado", "repetido"] as const) {
      const { retomar } = montar([{ estado: 200, corpo: { outcome: desfecho } }]);
      assert.equal(await retomar(PEDIDO), desfecho);
    }
  });

  it("**401 levanta, e nao se engole**", async () => {
    // Com um `catch` silencioso, um `secret` errado dos dois lados fazia todas
    // as retomas falharem e o sintoma eram conversas mortas sem um registo.
    const { retomar } = montar([{ estado: 401, corpo: { outcome: "nao_autorizado" } }]);
    await assert.rejects(() => retomar(PEDIDO), RetomaNaoAutorizadaError);
    await assert.rejects(() => retomar(PEDIDO), /chatwoot_bot_secret/);
  });

  it("**o segredo nao vai na mensagem do erro nem a registo**", async () => {
    const { retomar, registo } = montar([{ estado: 401 }]);
    const erro = await retomar(PEDIDO).then(
      () => null,
      (e: Error) => e,
    );
    assert.ok(!String(erro?.message).includes(SEGREDO_DO_BOT));
    assert.ok(!String(erro?.message).includes(INTERNO));
    const tudo = JSON.stringify(registo);
    assert.ok(!tudo.includes(SEGREDO_DO_BOT));
    assert.ok(!tudo.includes(INTERNO));
  });

  it("**404 recusado levanta, porque e divergencia nossa**", async () => {
    // O `thread_id` foi derivado da propria linha da passagem, com o
    // `external_id` do *callback* no predicado: se o AGR o recusa, as duas
    // leituras da mesma verdade divergiram.
    const { retomar } = montar([{ estado: 404, corpo: { outcome: "recusado" } }]);
    await assert.rejects(() => retomar(PEDIDO), RetomaRecusadaError);
    await assert.rejects(() => retomar(PEDIDO), /h_abc/);
  });

  it("400 levanta com o error_code, e nao se repete", async () => {
    const { retomar, chamadas } = montar([
      { estado: 400, corpo: { outcome: "corpo_invalido", error_code: "desfecho_invalido" } },
    ]);
    await assert.rejects(() => retomar(PEDIDO), /desfecho_invalido/);
    assert.equal(chamadas.length, 1, "nenhuma retentativa acrescenta um campo que falta");
  });

  it("um 2xx com um desfecho que nao e dos tres levanta", async () => {
    // A rota tem tres e mais nenhum: inventar um quarto aqui era aceitar que o
    // outro lado mudou de contrato sem ninguem reparar.
    for (const corpo of [{ outcome: "conflito" }, {}, { outcome: null }, null]) {
      const { retomar } = montar([{ estado: 200, corpo }]);
      await assert.rejects(() => retomar(PEDIDO), RetomaIndisponivelError);
    }
  });

  it("5xx levanta **sem** repetir: a passagem ja voltou a waiting", async () => {
    const { retomar, chamadas, esperas } = montar([{ estado: 500 }]);
    await assert.rejects(() => retomar(PEDIDO), RetomaIndisponivelError);
    assert.equal(chamadas.length, 1);
    assert.deepEqual(esperas, []);
  });

  it("uma falha de rede levanta, e a repeticao e do provedor", async () => {
    const retomar = clienteDaRetoma({
      agr: AGR,
      credencial: () => INTERNO,
      segredoDoBot: () => SEGREDO_DO_BOT,
      buscar: (() => Promise.reject(new TypeError("fetch failed"))) as unknown as typeof fetch,
    });
    const erro = await retomar(PEDIDO).then(
      () => null,
      (e: Error) => e,
    );
    assert.ok(erro instanceof RetomaIndisponivelError);
    assert.equal(erro.estado, null, "nao houve estado HTTP nenhum");
  });
});

describe("o 503 e o Retry-After", () => {
  it("**503 e depois 200: espera o que ele pede e retoma**", async () => {
    const { retomar, chamadas, esperas } = montar([
      { estado: 503, corpo: { outcome: "grafo_nao_registado" }, retryAfter: "2" },
      { estado: 200, corpo: { outcome: "retomado" } },
    ]);
    assert.equal(await retomar(PEDIDO), "retomado");
    assert.equal(chamadas.length, 2);
    assert.deepEqual(esperas, [2000], "em ms, e o que o cabecalho pediu");
  });

  it("503 sem Retry-After espera a omissao", async () => {
    const { retomar, esperas } = montar([
      { estado: 503 },
      { estado: 200, corpo: { outcome: "retomado" } },
    ]);
    await retomar(PEDIDO);
    assert.deepEqual(esperas, [ESPERA_POR_OMISSAO_MS]);
  });

  it("**dois 503 levantam: a terceira tentativa e do provedor**", async () => {
    const { retomar, chamadas, esperas, registo } = montar([{ estado: 503, retryAfter: "1" }]);
    await assert.rejects(() => retomar(PEDIDO), RetomaIndisponivelError);
    assert.equal(chamadas.length, 2, "duas tentativas, que e o TENTATIVAS_DA_RETOMA");
    assert.deepEqual(esperas, [1000]);
    assert.ok(registo.some((l) => l["outcome"] === "retoma_indisponivel"));
  });

  it("**um Retry-After acima do tecto nao se espera**", async () => {
    // Cumprir `Retry-After: 120` a letra segurava o *webhook* do provedor dois
    // minutos, e ele desiste muito antes: o que se conseguia era manter uma
    // ligacao aberta para nada.
    const { retomar, chamadas, esperas } = montar([{ estado: 503, retryAfter: "120" }]);
    await assert.rejects(() => retomar(PEDIDO), RetomaIndisponivelError);
    assert.equal(chamadas.length, 1, "nem se tentou outra vez");
    assert.deepEqual(esperas, []);
  });

  it("**o orcamento total impede a segunda tentativa**", async () => {
    // O `TECTO_DA_ESPERA_MS` limita so o **sono**, e com ele sozinho o pior caso
    // eram 25 s dentro do pedido do *webhook* do provedor: 10 s de tentativa,
    // 5 s de sono — que e o que o AGR pede **sempre** —, 10 s de tentativa.
    // Achado da revisao adversarial. Aqui a primeira tentativa «demora» 18 s, e
    // o que resta do orcamento nao chega para outra.
    const { retomar, chamadas, esperas } = montar([
      { estado: 503, retryAfter: "5", demora: 18_000 },
    ]);
    await assert.rejects(() => retomar(PEDIDO), RetomaIndisponivelError);
    assert.equal(chamadas.length, 1, "nao se tenta outra vez com o orcamento gasto");
    assert.deepEqual(esperas, [], "e nem se dorme");
  });

  it("com o orcamento a sobrar, a segunda tentativa corre", async () => {
    // O controlo positivo: sem ele, o ensaio de cima passava com um cliente que
    // **nunca** repetisse — e o 503 que repete e metade do que este modulo faz.
    const { retomar, chamadas, esperas } = montar([
      { estado: 503, retryAfter: "5", demora: 200 },
      { estado: 200, corpo: { outcome: "retomado" }, demora: 200 },
    ]);
    assert.equal(await retomar(PEDIDO), "retomado");
    assert.equal(chamadas.length, 2);
    assert.deepEqual(esperas, [5000]);
  });

  it("**a segunda tentativa leva o que resta do orcamento, e nao o tecto inteiro**", async () => {
    // Sem isto, o orcamento so decidia **se** havia segunda tentativa: ela podia
    // levar 10 s a mais do que o que restava, e o total passava dos 20 s.
    const { retomar, tectos } = montar([
      { estado: 503, retryAfter: "5", demora: 8_000 },
      { estado: 200, corpo: { outcome: "retomado" }, demora: 100 },
    ]);
    assert.equal(await retomar(PEDIDO), "retomado");
    // A primeira leva o tecto inteiro; a segunda, o que resta: 20 000 - 8 000
    // (a primeira) - 5 000 (o sono) = 7 000.
    assert.deepEqual(tectos, [ESPERA_DA_RETOMA_MS, 7_000]);
  });

  it("e nunca menos do que o minimo, mesmo com o orcamento gasto", async () => {
    // O `Math.max` com o `MINIMO_DA_TENTATIVA_MS` existe para a **primeira**
    // tentativa de um cliente reutilizado: um tecto de zero (ou negativo)
    // abortava o pedido antes de ele sair, e isso nao e um 503 — e nada.
    const { retomar, tectos } = montar([
      { estado: 200, corpo: { outcome: "retomado" }, demora: 30_000 },
    ]);
    await retomar(PEDIDO);
    assert.deepEqual(tectos, [ESPERA_DA_RETOMA_MS]);
    assert.ok(tectos.every((t) => t >= MINIMO_DA_TENTATIVA_MS));
  });

  it("o orcamento e maior do que uma tentativa mais o sono mais outra", () => {
    // A fronteira **pelo valor** e nao por um literal: se alguem baixar o
    // orcamento abaixo disto, o 503 deixa de repetir alguma vez e o ensaio de
    // cima passa a medir outra coisa.
    assert.ok(
      ORCAMENTO_DA_RETOMA_MS >= ESPERA_DA_RETOMA_MS + ESPERA_POR_OMISSAO_MS + MINIMO_DA_TENTATIVA_MS,
      `orcamento ${ORCAMENTO_DA_RETOMA_MS} nao cabe uma segunda tentativa`,
    );
  });

  it("**as duas credenciais leem-se a cada tentativa**", async () => {
    // A rotacao vale para as duas (`agr_internal_token` 90 dias,
    // `chatwoot_bot_secret` 182), e a primeira versao resolvia o segredo do bot
    // **uma vez** antes do ciclo com a *docstring* a justificar a releitura.
    const { retomar, segredosPedidos } = montar([
      { estado: 503, retryAfter: "1", demora: 100 },
      { estado: 200, corpo: { outcome: "retomado" }, demora: 100 },
    ]);
    await retomar(PEDIDO);
    assert.deepEqual(segredosPedidos, [TENANT, TENANT]);
  });

  it("a leitura do Retry-After, nos casos todos", () => {
    assert.equal(esperaDoRetryAfter("3"), 3000);
    assert.equal(esperaDoRetryAfter(" 3 "), 3000);
    assert.equal(esperaDoRetryAfter("0"), 0);
    assert.equal(esperaDoRetryAfter(null), ESPERA_POR_OMISSAO_MS);
    assert.equal(esperaDoRetryAfter("  "), ESPERA_POR_OMISSAO_MS);
    // A fronteira **pelo valor** e nao por um literal, que e a licao do 800 do
    // KAM-023: o tecto muda e o ensaio tem de o seguir.
    assert.equal(esperaDoRetryAfter(String(TECTO_DA_ESPERA_MS / 1000)), TECTO_DA_ESPERA_MS);
    assert.equal(esperaDoRetryAfter(String(TECTO_DA_ESPERA_MS / 1000 + 1)), null);
    // A forma de data HTTP existe na norma e o AGR nunca a manda
    // (`str(ESPERAR_SEGUNDOS)`): nao se aceita, e recusar e nao esperar.
    assert.equal(esperaDoRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT"), null);
    assert.equal(esperaDoRetryAfter("-1"), null);
    assert.equal(esperaDoRetryAfter("muitos"), null);
  });
});

describe("o thread_id", () => {
  it("o tenant sai do prefixo, e um prefixo vazio nao e um tenant", () => {
    assert.equal(tenantDoThread(`${TENANT}:${CONTACTO}`), TENANT);
    assert.equal(tenantDoThread(":x"), null);
    assert.equal(tenantDoThread("sem-separador"), null);
    assert.equal(tenantDoThread(""), null);
    // Corta no **primeiro** `:`, como o `tenant_do_thread` do AGR: um
    // `thread_id` com tres partes recusa-se em vez de levantar.
    assert.equal(tenantDoThread("a:b:c"), "a");
  });

  it("a forma e a do §3.1, e as duas funcoes sao inversas", () => {
    assert.equal(threadDe(TENANT, CONTACTO), `${TENANT}:${CONTACTO}`);
    assert.equal(tenantDoThread(threadDe(TENANT, CONTACTO)), TENANT);
  });
});
