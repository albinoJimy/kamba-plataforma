/**
 * A ponte fila → consumidor Python: a decisão, sem fila e sem consumidor (KAM-194).
 *
 * Os «Testes Requeridos» do ticket pedem, do lado TypeScript: «a casca traduz
 * 200, 400 e 503 em completar, falhar sem repetir e repetir com atraso; não
 * abre ligação à base». As duas metades estão aqui. A tradução é a única coisa
 * da ponte que pode errar em silêncio, e os dois erros custam em direcções
 * opostas: um 400 retentado gasta a escada inteira num corpo que nunca melhora;
 * um 503 **não** retentado perde um evento que o lado Python pediu para ver.
 *
 * O `fetch` é injectado. Quem exercita o `Worker` de verdade é o ensaio de
 * pilha levantada, e a casca fica fora da medição por isso.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { UnrecoverableError } from "bullmq";

import { CABECALHO_INTERNO as CABECALHO_DO_AGR } from "../src/agr/contrato.ts";
import { ESCADA_DO_CONSUMIDOR, atrasoDaTentativaDoConsumidor } from "../src/eventos/consumo.ts";
import {
  DESFECHOS_DA_PONTE,
  DesfechoDaPonteInvalidoError,
  METRICA_PONTE,
  MetricasDaPonte,
} from "../src/eventos/metricas_ponte.ts";
import { PARTICOES } from "../src/eventos/particao.ts";
import {
  AJUSTES_DA_PONTE,
  CABECALHO_INTERNO,
  CAMINHO_DO_EVENTO,
  CONCORRENCIA_DA_PONTE,
  ConsumidorIndisponivelError,
  type CorpoDaEntrega,
  ESPERA_MAXIMA_DA_PONTE_MS,
  EntregaRecusadaError,
  largarAoFalhar,
  RepetirDepoisError,
  TRANCA_DA_PONTE_MS,
  atrasoDoRetryAfter,
  chamarOConsumidor,
  codigoDaFalha,
  corpoDaEntrega,
  desfechoDaFalha,
  filasDaPonte,
} from "../src/eventos/ponte.ts";

const ALVO = "http://idx:8000";
const CREDENCIAL = "credencial de teste da ponte";
const TENANT = "0b6c1f0e-6a43-4a0e-9d55-6d0f6f6c2a11";
const EVENTO = "7d8e9f00-1a2b-4c3d-8e4f-5a6b7c8d9e0f";

const CORPO: CorpoDaEntrega = {
  event_id: EVENTO,
  tenant_id: TENANT,
  envelope: null,
  tentativas: 1,
};

interface Pedido {
  readonly url: string;
  readonly init: RequestInit | undefined;
}

function respostaDe(
  estado: number,
  cabecalhos: Record<string, string> = {},
  corpo: unknown = { outcome: "aplicado" },
): Response {
  // 204 e 304 não podem levar corpo; os outros levam um JSON qualquer.
  const semCorpo = estado === 204 || estado === 304;
  return new Response(semCorpo ? null : JSON.stringify(corpo), {
    status: estado,
    headers: { "content-type": "application/json", ...cabecalhos },
  });
}

function opcoes(
  resposta: Response | (() => never),
  pedidos: Pedido[] = [],
  credencial: () => string = () => CREDENCIAL,
) {
  return {
    alvo: ALVO,
    credencial,
    buscar: (async (url: string | URL | Request, init?: RequestInit) => {
      pedidos.push({ url: String(url), init });
      if (typeof resposta === "function") resposta();
      return resposta;
    }) as unknown as typeof fetch,
  };
}

describe("corpoDaEntrega — o que vai no pedido", () => {
  it("o job do publicador leva o envelope como veio, e o jobId é o event_id", () => {
    const envelope = { id: EVENTO, tenant_id: TENANT, tipo: "catalog.product_changed" };
    const corpo = corpoDaEntrega({
      id: EVENTO,
      data: { tenant_id: TENANT, envelope, repeticao: { tentativas: 6 } },
      attemptsMade: 0,
    });
    assert.deepEqual(corpo, { event_id: EVENTO, tenant_id: TENANT, envelope, tentativas: 1 });
    // O mesmo objecto, e não uma cópia validada: a ponte não olha para dentro.
    assert.equal(corpo.envelope, envelope);
  });

  it("o job do reconciliador não traz envelope, e vai null", () => {
    // O lado Python lê o arquivo pelo `event_id`.
    const corpo = corpoDaEntrega({ id: EVENTO, data: { tenant_id: TENANT }, attemptsMade: 2 });
    assert.deepEqual(corpo, { event_id: EVENTO, tenant_id: TENANT, envelope: null, tentativas: 3 });
  });

  it("tentativas é attemptsMade + 1: o lado Python conta a partir de 1", () => {
    for (const feitas of [0, 1, 5, 9]) {
      const corpo = corpoDaEntrega({ id: EVENTO, data: { tenant_id: TENANT }, attemptsMade: feitas });
      assert.equal(corpo.tentativas, feitas + 1);
    }
  });

  it("o tenant de um job antigo vem de dentro do envelope", () => {
    const corpo = corpoDaEntrega({
      id: EVENTO,
      data: { envelope: { tenant_id: TENANT } },
      attemptsMade: 0,
    });
    assert.equal(corpo.tenant_id, TENANT);
  });

  it("não valida: um job sem nada segue vazio e o lado Python responde 400", () => {
    const corpo = corpoDaEntrega({ data: null, attemptsMade: 0 });
    assert.deepEqual(corpo, { event_id: "", tenant_id: "", envelope: null, tentativas: 1 });
  });

  it("o corpo enviado tem exactamente as quatro chaves", async () => {
    // O `ler_entrega` do lado Python recusa campos a mais: o `repeticao` do
    // *job* do publicador não pode passar.
    const pedidos: Pedido[] = [];
    const corpo = corpoDaEntrega({
      id: EVENTO,
      data: { tenant_id: TENANT, envelope: { x: 1 }, repeticao: { tentativas: 6 }, outro: true },
      attemptsMade: 0,
    });
    await chamarOConsumidor(opcoes(respostaDe(200), pedidos), corpo);
    const enviado = JSON.parse(String(pedidos[0]?.init?.body)) as Record<string, unknown>;
    assert.deepEqual(Object.keys(enviado).sort(), ["envelope", "event_id", "tenant_id", "tentativas"]);
  });
});

describe("chamarOConsumidor — o pedido", () => {
  it("POST ao /internal/event do alvo, com JSON e o cabeçalho interno", async () => {
    const pedidos: Pedido[] = [];
    await chamarOConsumidor(opcoes(respostaDe(200), pedidos), CORPO);
    assert.equal(pedidos.length, 1);
    assert.equal(pedidos[0]?.url, `${ALVO}${CAMINHO_DO_EVENTO}`);
    assert.equal(CAMINHO_DO_EVENTO, "/internal/event");
    assert.equal(pedidos[0]?.init?.method, "POST");
    const cabecalhos = pedidos[0]?.init?.headers as Record<string, string>;
    assert.equal(cabecalhos["content-type"], "application/json");
    assert.equal(cabecalhos[CABECALHO_INTERNO], CREDENCIAL);
    assert.equal(pedidos[0]?.init?.body, JSON.stringify(CORPO));
    assert.ok(pedidos[0]?.init?.signal instanceof AbortSignal);
  });

  it("o cabeçalho é o mesmo que o AGR verifica", () => {
    assert.equal(CABECALHO_INTERNO, CABECALHO_DO_AGR);
    assert.equal(CABECALHO_INTERNO, "x-kamba-interno");
  });

  it("lê a credencial a cada chamada, porque o segredo roda", async () => {
    const valores = ["primeira", "segunda"];
    let lidas = 0;
    const pedidos: Pedido[] = [];
    const comRotacao = opcoes(respostaDe(200), pedidos, () => valores[lidas++] ?? "");
    await chamarOConsumidor(comRotacao, CORPO);
    await chamarOConsumidor({ ...comRotacao, buscar: opcoes(respostaDe(200), pedidos).buscar }, CORPO);
    assert.equal(lidas, 2);
    const enviadas = pedidos.map(
      (p) => (p.init?.headers as Record<string, string>)[CABECALHO_INTERNO],
    );
    assert.deepEqual(enviadas, ["primeira", "segunda"]);
  });

  it("corta o pedido antes do lockDuration", () => {
    // Se a espera do `fetch` passasse o `lockDuration`, o BullMQ declarava o
    // *job* `stalled` com este *worker* vivo, e o evento ia duas vezes.
    assert.ok(ESPERA_MAXIMA_DA_PONTE_MS < TRANCA_DA_PONTE_MS);
  });

  it("um worker por partição, e concorrência 1: a ordem é da partição", () => {
    assert.equal(CONCORRENCIA_DA_PONTE, 1);
  });
});

describe("chamarOConsumidor — a tabela de estados", () => {
  it("200 completa o job: devolve entregue e o estado", async () => {
    assert.deepEqual(await chamarOConsumidor(opcoes(respostaDe(200)), CORPO), {
      outcome: "entregue",
      estado: 200,
    });
  });

  it("um 200 cujo corpo diz dlq completa igual: foi tratado", async () => {
    // O lado Python responde 200 ao que pôs na DLQ. Repeti-lo abria a mesma
    // entrada seis vezes.
    const saida = await chamarOConsumidor(opcoes(respostaDe(200, {}, { outcome: "dlq" })), CORPO);
    assert.equal(saida.outcome, "entregue");
  });

  it("um 2xx que não é JSON não rebenta", async () => {
    const resposta = new Response("nao e json", { status: 200 });
    assert.deepEqual(await chamarOConsumidor(opcoes(resposta), CORPO), {
      outcome: "entregue",
      estado: 200,
    });
    assert.deepEqual(await chamarOConsumidor(opcoes(respostaDe(204)), CORPO), {
      outcome: "entregue",
      estado: 204,
    });
  });

  for (const estado of [400, 401]) {
    it(`${estado} é UnrecoverableError: nenhuma retentativa o conserta`, async () => {
      await assert.rejects(
        () => chamarOConsumidor(opcoes(respostaDe(estado)), CORPO),
        (erro: unknown) => {
          assert.ok(erro instanceof UnrecoverableError);
          assert.ok(erro instanceof EntregaRecusadaError);
          assert.equal(erro.estado, estado);
          return true;
        },
      );
    });
  }

  it("401 nomeia a variável do segredo, e não o valor", async () => {
    await assert.rejects(
      () => chamarOConsumidor(opcoes(respostaDe(401)), CORPO),
      (erro: Error) => {
        assert.match(erro.message, /KAMBA_PONTE_SEGREDO/);
        assert.doesNotMatch(erro.message, new RegExp(CREDENCIAL));
        return true;
      },
    );
  });

  it("503 com Retry-After: 7 repete daqui a 7000 ms", async () => {
    await assert.rejects(
      () => chamarOConsumidor(opcoes(respostaDe(503, { "retry-after": "7" })), CORPO),
      (erro: unknown) => {
        assert.ok(erro instanceof RepetirDepoisError);
        assert.ok(!(erro instanceof UnrecoverableError));
        assert.equal(erro.atrasoMs, 7_000);
        // O `backoffStrategy` é o que o BullMQ consulta, e devolve o mesmo.
        assert.equal(AJUSTES_DA_PONTE.backoffStrategy(1, "custom", erro), 7_000);
        assert.equal(AJUSTES_DA_PONTE.backoffStrategy(4, "custom", erro), 7_000);
        return true;
      },
    );
  });

  it("503 sem Retry-After repete pela escada da tentativa em curso", async () => {
    for (const tentativas of [1, 2, 3, 6]) {
      await assert.rejects(
        () => chamarOConsumidor(opcoes(respostaDe(503)), { ...CORPO, tentativas }),
        (erro: unknown) => {
          assert.ok(erro instanceof RepetirDepoisError);
          assert.equal(erro.atrasoMs, atrasoDaTentativaDoConsumidor(tentativas));
          return true;
        },
      );
    }
  });

  it("503 com um Retry-After ilegível também cai na escada", async () => {
    for (const valor of ["1.5", "-3", "Wed, 21 Oct 2026 07:28:00 GMT", "sete", ""]) {
      await assert.rejects(
        () => chamarOConsumidor(opcoes(respostaDe(503, { "retry-after": valor })), CORPO),
        (erro: unknown) => {
          assert.ok(erro instanceof RepetirDepoisError, valor);
          assert.equal(erro.atrasoMs, ESCADA_DO_CONSUMIDOR[0], valor);
          return true;
        },
      );
    }
  });

  for (const estado of [500, 502, 504, 429]) {
    it(`${estado} repete pela escada`, async () => {
      await assert.rejects(
        () => chamarOConsumidor(opcoes(respostaDe(estado)), CORPO),
        (erro: unknown) => {
          assert.ok(erro instanceof ConsumidorIndisponivelError);
          assert.ok(!(erro instanceof UnrecoverableError));
          assert.equal(erro.estado, estado);
          return true;
        },
      );
    });
  }

  it("a rede em baixo repete", async () => {
    const rede = () => {
      throw new TypeError("fetch failed");
    };
    await assert.rejects(
      () => chamarOConsumidor(opcoes(rede as () => never), CORPO),
      (erro: unknown) => {
        assert.ok(erro instanceof ConsumidorIndisponivelError);
        assert.equal(erro.estado, null);
        assert.equal(codigoDaFalha(erro), "rede");
        return true;
      },
    );
  });

  it("o corte do AbortSignal.timeout repete", async () => {
    const corte = () => {
      throw new DOMException("The operation was aborted due to timeout", "TimeoutError");
    };
    await assert.rejects(
      () => chamarOConsumidor(opcoes(corte as () => never), CORPO),
      (erro: unknown) => {
        assert.ok(erro instanceof ConsumidorIndisponivelError);
        assert.equal(codigoDaFalha(erro), "timeout");
        return true;
      },
    );
  });

  for (const estado of [301, 302, 404, 405, 409, 422]) {
    it(`${estado} não se repete: não melhora`, async () => {
      await assert.rejects(
        () => chamarOConsumidor(opcoes(respostaDe(estado)), CORPO),
        UnrecoverableError,
      );
    });
  }
});

describe("AJUSTES_DA_PONTE — o atraso que o BullMQ pede", () => {
  it("fora do 503, o degrau da escada pelas tentativas feitas", () => {
    const erro = new ConsumidorIndisponivelError(500, "http_500");
    for (let feitas = 1; feitas <= 7; feitas++) {
      assert.equal(
        AJUSTES_DA_PONTE.backoffStrategy(feitas, "custom", erro),
        atrasoDaTentativaDoConsumidor(feitas),
      );
    }
  });

  it("zero tentativas feitas não rebenta: é o primeiro degrau", () => {
    assert.equal(AJUSTES_DA_PONTE.backoffStrategy(0), ESCADA_DO_CONSUMIDOR[0]);
  });

  it("um 503 sem Retry-After dá o mesmo degrau pelos dois caminhos", async () => {
    // O corpo leva `attemptsMade + 1`, e o BullMQ chama o `backoffStrategy`
    // com o `attemptsMade` já contada a falha: são o mesmo número.
    const corpo = corpoDaEntrega({ id: EVENTO, data: { tenant_id: TENANT }, attemptsMade: 2 });
    await assert.rejects(
      () => chamarOConsumidor(opcoes(respostaDe(503)), corpo),
      (erro: Error) => {
        assert.equal(
          AJUSTES_DA_PONTE.backoffStrategy(3, "custom", erro),
          AJUSTES_DA_PONTE.backoffStrategy(3, "custom", new Error("outro")),
        );
        return true;
      },
    );
  });
});

describe("atrasoDoRetryAfter", () => {
  it("segundos inteiros, em milissegundos", () => {
    assert.equal(atrasoDoRetryAfter("7"), 7_000);
    assert.equal(atrasoDoRetryAfter(" 30 "), 30_000);
    assert.equal(atrasoDoRetryAfter("0"), 0);
  });

  it("o resto é null, e cai na escada", () => {
    for (const valor of [null, "", "1.5", "-1", "7s", "Wed, 21 Oct 2026 07:28:00 GMT"]) {
      assert.equal(atrasoDoRetryAfter(valor), null, String(valor));
    }
  });
});

describe("o desfecho e o código de uma falha", () => {
  it("o que não se repete é recusado; o resto é repetir", () => {
    assert.equal(desfechoDaFalha(new EntregaRecusadaError(400, "x")), "recusado");
    assert.equal(desfechoDaFalha(new UnrecoverableError("x")), "recusado");
    assert.equal(desfechoDaFalha(new RepetirDepoisError(7_000)), "repetir");
    assert.equal(desfechoDaFalha(new ConsumidorIndisponivelError(500, "http_500")), "repetir");
    assert.equal(desfechoDaFalha(new Error("x")), "repetir");
  });

  it("o código é o estado HTTP e nunca a mensagem", () => {
    assert.equal(codigoDaFalha(new RepetirDepoisError(7_000)), "http_503");
    assert.equal(codigoDaFalha(new EntregaRecusadaError(401, "x")), "http_401");
    assert.equal(codigoDaFalha(new ConsumidorIndisponivelError(502, "http_502")), "http_502");
    assert.equal(codigoDaFalha(new Error(`um url com ${TENANT}`)), "interno");
  });
});

describe("filasDaPonte — os consumidores, recusados no arranque", () => {
  it("dezasseis filas por consumidor, pela ordem da partição", () => {
    const filas = filasDaPonte(["agr", "idx"]);
    assert.equal(filas.length, 2 * PARTICOES);
    assert.equal(filas[0], "evt.agr.p0");
    assert.equal(filas[PARTICOES - 1], "evt.agr.p15");
    assert.equal(filas[PARTICOES], "evt.idx.p0");
  });

  it("recusa a lista vazia, o nome fora da gramática e o repetido", () => {
    for (const mau of [[], ["Agr"], ["idx-pesquisa"], ["1idx"], ["a b"], [""], ["idx", "idx"]]) {
      assert.throws(() => filasDaPonte(mau), RangeError, JSON.stringify(mau));
    }
  });

  it("a mensagem não repete o nome recusado", () => {
    assert.throws(
      () => filasDaPonte(["NOME_SECRETO"]),
      (erro: Error) => !erro.message.includes("NOME_SECRETO"),
    );
  });
});

describe("a métrica da ponte", () => {
  it("um contador, com outcome de lista fechada", () => {
    const metricas = new MetricasDaPonte();
    for (const desfecho of DESFECHOS_DA_PONTE) metricas.contar(desfecho);
    metricas.contar("entregue", 2);
    assert.deepEqual(metricas.ler(), { entregue: 3, repetir: 1, recusado: 1 });
    assert.deepEqual([...DESFECHOS_DA_PONTE], ["entregue", "repetir", "recusado"]);
  });

  it("fora da lista levanta, e não abre série", () => {
    const metricas = new MetricasDaPonte();
    for (const mau of [TENANT, EVENTO, "aplicado", "idx", ""]) {
      assert.throws(() => metricas.contar(mau), DesfechoDaPonteInvalidoError);
    }
    assert.deepEqual(metricas.ler(), {});
  });

  it("a exposição traz as três séries, a zero quando nada aconteceu", () => {
    const metricas = new MetricasDaPonte();
    metricas.contar("repetir");
    const texto = metricas.exposicao();
    assert.match(texto, new RegExp(`# TYPE ${METRICA_PONTE} counter`));
    assert.match(texto, /evt_ponte_total\{outcome="entregue"\} 0/);
    assert.match(texto, /evt_ponte_total\{outcome="repetir"\} 1/);
    assert.match(texto, /evt_ponte_total\{outcome="recusado"\} 0/);
    for (const linha of texto.split("\n")) {
      if (linha.startsWith("#") || linha === "") continue;
      assert.doesNotMatch(linha, /[0-9a-f]{8}-[0-9a-f]{4}/);
      assert.doesNotMatch(linha, /tenant|event_id|consumer/);
    }
  });
});

describe("largarAoFalhar — a rede do reconciliador", () => {
  it("larga na última tentativa e num irrecuperável, e não antes", () => {
    const erro = new Error("rede");
    assert.equal(largarAoFalhar(erro, 5, 6), false);
    assert.equal(largarAoFalhar(erro, 6, 6), true);
    assert.equal(largarAoFalhar(new EntregaRecusadaError(401, "x"), 1, 6), true);
    assert.equal(largarAoFalhar(new UnrecoverableError("x"), 1, 6), true);
    assert.equal(largarAoFalhar(erro, 1, undefined), true, "sem attempts, o BullMQ dá uma");
  });
});

describe("a casca liga os ajustes certos ao Worker", () => {
  // A casca não tem cobertura V8 (só uma fila real a exercita); o que se prende
  // aqui é a **ligação**: os ajustes, a concorrência e a tranca vêm das
  // constantes testadas acima, e o `failed` larga o job. Sem o `settings`, o
  // BullMQ lança «Unknown backoff strategy custom» na segunda tentativa.
  const fonte = readFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), "../src/eventos/ponte_bullmq.ts"),
    "utf-8",
  );
  for (const ligacao of [
    "settings: AJUSTES_DA_PONTE",
    "concurrency: opcoes.concorrencia ?? CONCORRENCIA_DA_PONTE",
    "lockDuration: TRANCA_DA_PONTE_MS",
    "largarAoFalhar(erro, job.attemptsMade, job.opts.attempts)",
    "chamarOConsumidor(opcoes, corpoDaEntrega(job))",
  ]) {
    it(`a casca usa ${ligacao}`, () => {
      assert.ok(fonte.includes(ligacao), `ponte_bullmq.ts perdeu: ${ligacao}`);
    });
  }
});

describe("a ponte não abre ligação à base", () => {
  const AQUI = dirname(fileURLToPath(import.meta.url));
  const EVENTOS = resolve(AQUI, "../src/eventos");
  const IMPORTACAO = /(?:^|\n)\s*(?:import|export)\b[^;]*?\bfrom\s*["']([^"']+)["']|(?:^|\n)\s*import\s*["']([^"']+)["']|\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;

  function especificadores(texto: string): string[] {
    return [...texto.matchAll(IMPORTACAO)].map((m) => m[1] ?? m[2] ?? m[3] ?? "");
  }

  /** O código sem comentários: o cabeçalho fala de `events_consumed` de propósito. */
  function semComentarios(texto: string): string {
    return texto.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  }

  for (const ficheiro of ["ponte.ts", "ponte_bullmq.ts"]) {
    it(`${ficheiro} não importa o pg nem SQL`, () => {
      const texto = readFileSync(resolve(EVENTOS, ficheiro), "utf-8");
      const importados = especificadores(texto);
      assert.ok(importados.length > 0, "o leitor de importações não leu nada");
      for (const especificador of importados) {
        assert.notEqual(especificador, "pg", ficheiro);
        assert.ok(!especificador.startsWith("pg/"), especificador);
        assert.doesNotMatch(especificador, /consultas|publicador|dlq|trabalho\.ts|reconciliador/, especificador);
      }
      const codigo = semComentarios(texto);
      assert.doesNotMatch(codigo, /\bSQL_[A-Z_]+/);
      assert.doesNotMatch(codigo, /\.query\s*\(/);
      assert.doesNotMatch(codigo, /\b(?:BEGIN|COMMIT|INSERT|SELECT)\b/);
      assert.doesNotMatch(codigo, /events_consumed/);
    });
  }

  it("nada do que a ponte carrega, transitivamente, importa o pg", () => {
    // O `tenantDoJob` vem do `trabalhador_bullmq.ts`, que carrega cadeias de
    // SQL do consumidor TypeScript sem as correr. O que não pode haver é um
    // cliente: o `pg` não está em módulo nenhum do grafo.
    const vistos = new Set<string>();
    const externos = new Set<string>();
    const fila = [resolve(EVENTOS, "ponte.ts"), resolve(EVENTOS, "ponte_bullmq.ts")];
    while (fila.length > 0) {
      const caminho = fila.pop() as string;
      if (vistos.has(caminho)) continue;
      vistos.add(caminho);
      for (const especificador of especificadores(readFileSync(caminho, "utf-8"))) {
        if (especificador.startsWith(".")) fila.push(resolve(dirname(caminho), especificador));
        else externos.add(especificador);
      }
    }
    assert.ok(vistos.size > 2, "o grafo não foi percorrido");
    assert.ok(externos.has("bullmq"), [...externos].join(", "));
    for (const externo of externos) {
      assert.ok(externo !== "pg" && !externo.startsWith("pg/"), externo);
    }
  });
});
