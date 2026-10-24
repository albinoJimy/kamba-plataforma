/**
 * A tradução de estados HTTP do AGR em «repete» ou «não repete» (KAM-025).
 *
 * É a única coisa do *shim* que pode errar em silêncio, e os dois erros custam
 * caro em direcções opostas: um 400 retentado gasta as seis tentativas da
 * escada — cerca de treze minutos com `concurrency` baixa — num corpo que nunca
 * melhora; um 503 **não** retentado perde uma conversa.
 *
 * Sem fila e sem AGR: o `fetch` é injectado. Quem exercita o `Worker` de
 * verdade é a *suite* do *gate* 8, e a casca está fora da medição por isso
 * (`ci/thresholds.yaml`).
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { UnrecoverableError } from "bullmq";

import {
  AJUSTES_DO_SHIM,
  AgrIndisponivelError,
  CABECALHO_INTERNO,
  CAMINHO_DO_TURNO,
  DESFECHOS_DO_AGR,
  ESPERA_MAXIMA_MS,
  METRICA_FALHAS,
  METRICA_JOBS,
  MetricaDesconhecidaError,
  MetricasDoShim,
  SufixoInvalidoError,
  TRANCA_DO_JOB_MS,
  chamarOTurno,
  desfechoDe,
} from "../src/agr/index.ts";

const CREDENCIAL = "credencial de teste do agr";

function respostaDe(estado: number, corpo: unknown): Response {
  return new Response(corpo === null ? null : JSON.stringify(corpo), {
    status: estado,
    headers: { "content-type": "application/json" },
  });
}

function opcoes(resposta: Response | (() => never), pedidos: unknown[] = []) {
  return {
    url: "redis://x:6379",
    agr: "http://agr:8000",
    credencial: () => CREDENCIAL,
    buscar: (async (url: string | URL | Request, init?: RequestInit) => {
      pedidos.push({ url: String(url), init });
      if (typeof resposta === "function") resposta();
      return resposta;
    }) as unknown as typeof fetch,
  };
}

describe("chamarOTurno — o pedido", () => {
  it("chama /internal/turn com a credencial no cabeçalho", async () => {
    const pedidos: Array<{ url: string; init?: RequestInit }> = [];
    await chamarOTurno(
      opcoes(respostaDe(200, { outcome: "executado" }), pedidos) as never,
      { tenant_id: "x" },
    );
    assert.equal(pedidos.length, 1);
    assert.equal(pedidos[0]?.url, `http://agr:8000${CAMINHO_DO_TURNO}`);
    assert.equal(pedidos[0]?.init?.method, "POST");
    const cabecalhos = pedidos[0]?.init?.headers as Record<string, string>;
    assert.equal(cabecalhos[CABECALHO_INTERNO], CREDENCIAL);
    assert.equal(pedidos[0]?.init?.body, JSON.stringify({ tenant_id: "x" }));
  });

  it("passa o corpo do job como veio, sem o olhar", async () => {
    // Um *shim* que validasse era uma segunda implementação do contrato do AGR,
    // a divergir. Um corpo que o AGR vai recusar passa igual.
    const pedidos: Array<{ init?: RequestInit }> = [];
    await chamarOTurno(
      opcoes(respostaDe(200, { outcome: "executado" }), pedidos) as never,
      { isto: "nao e um agent_invocation" },
    );
    assert.equal(
      pedidos[0]?.init?.body,
      JSON.stringify({ isto: "nao e um agent_invocation" }),
    );
  });

  it("lê a credencial a cada chamada, porque o segredo roda", async () => {
    let lidas = 0;
    const base = opcoes(respostaDe(200, { outcome: "executado" }));
    const comContador = { ...base, credencial: () => { lidas += 1; return CREDENCIAL; } };
    await chamarOTurno(comContador as never, {});
    await chamarOTurno(comContador as never, {});
    assert.equal(lidas, 2);
  });

  it("corta o pedido antes do lockDuration", () => {
    // Se a espera do `fetch` passasse o `lockDuration`, o BullMQ declarava o
    // *job* `stalled` com este *worker* vivo, e o turno corria duas vezes em
    // dois processos.
    assert.ok(ESPERA_MAXIMA_MS < TRANCA_DO_JOB_MS);
  });
});

describe("chamarOTurno — a tabela de estados", () => {
  it("2xx devolve o desfecho e o job completa", async () => {
    for (const outcome of DESFECHOS_DO_AGR) {
      if (outcome === "nao_autorizado" || outcome === "invocacao_invalida") continue;
      const saida = await chamarOTurno(
        opcoes(respostaDe(200, { outcome })) as never,
        {},
      );
      assert.deepEqual(saida, { desfecho: outcome, estado: 200 });
    }
  });

  it("um 200 com corpo que não é JSON não rebenta", async () => {
    const resposta = new Response("nao e json", { status: 200 });
    const saida = await chamarOTurno(opcoes(resposta) as never, {});
    assert.deepEqual(saida, { desfecho: "desconhecido", estado: 200 });
  });

  it("400 é UnrecoverableError: nenhuma retentativa conserta um corpo", async () => {
    await assert.rejects(
      () =>
        chamarOTurno(
          opcoes(respostaDe(400, { outcome: "invocacao_invalida" })) as never,
          {},
        ),
      UnrecoverableError,
    );
  });

  it("401 é UnrecoverableError, e nomeia o segredo dos dois lados", async () => {
    await assert.rejects(
      () => chamarOTurno(opcoes(respostaDe(401, { outcome: "nao_autorizado" })) as never, {}),
      (erro: Error) => {
        assert.ok(erro instanceof UnrecoverableError);
        assert.match(erro.message, /agr_internal_token/);
        return true;
      },
    );
  });

  it("401 não chega a ler o corpo", async () => {
    // Um 401 decide-se pelo estado: ler o corpo de quem nos recusou é trabalho
    // a mais sobre dados em que não confiamos.
    let lido = false;
    const resposta = new Response("{}", { status: 401 });
    Object.defineProperty(resposta, "json", {
      value: async () => {
        lido = true;
        return {};
      },
    });
    await assert.rejects(() => chamarOTurno(opcoes(resposta) as never, {}));
    assert.equal(lido, false);
  });

  it("503 devolve o job à fila", async () => {
    for (const estado of [503, 500, 502, 429]) {
      await assert.rejects(
        () => chamarOTurno(opcoes(respostaDe(estado, { outcome: "tecto_do_tenant" })) as never, {}),
        (erro: Error) => {
          assert.ok(erro instanceof AgrIndisponivelError);
          assert.ok(!(erro instanceof UnrecoverableError));
          assert.equal((erro as AgrIndisponivelError).estado, estado);
          return true;
        },
      );
    }
  });

  it("uma falha de rede devolve o job à fila", async () => {
    await assert.rejects(
      () =>
        chamarOTurno(
          opcoes(() => {
            throw new TypeError("fetch failed");
          }) as never,
          {},
        ),
      (erro: Error) => {
        assert.ok(erro instanceof AgrIndisponivelError);
        assert.equal((erro as AgrIndisponivelError).estado, null);
        // A mensagem diz porque é que a repetição é segura.
        assert.match(erro.message, /idempotente por turn_id/);
        return true;
      },
    );
  });

  it("os 4xx e 3xx que sobram não se retentam", async () => {
    for (const estado of [403, 404, 409, 418, 301]) {
      await assert.rejects(
        () => chamarOTurno(opcoes(respostaDe(estado, {})) as never, {}),
        UnrecoverableError,
      );
    }
  });
});

describe("os ajustes do worker", () => {
  it("registam a estratégia de recuo, sem a qual um job que falha rebenta", () => {
    // «Unknown backoff strategy custom»: medido na *suite* `tests_entrada`.
    assert.equal(typeof AJUSTES_DO_SHIM.backoffStrategy, "function");
    assert.ok(AJUSTES_DO_SHIM.backoffStrategy(1) > 0);
    // A escada sobe. É a do consumidor (`docs/tecnica/06` §6.4).
    assert.ok(AJUSTES_DO_SHIM.backoffStrategy(3) > AJUSTES_DO_SHIM.backoffStrategy(1));
  });

  it("uma tentativa zero não dá atraso negativo", () => {
    assert.ok(AJUSTES_DO_SHIM.backoffStrategy(0) > 0);
  });
});

describe("desfechoDe", () => {
  it("reconhece os oito desfechos do AGR", () => {
    for (const outcome of DESFECHOS_DO_AGR) {
      assert.equal(desfechoDe({ outcome }), outcome);
    }
  });

  it("o que não é um dos oito é `desconhecido`", () => {
    for (const corpo of [null, undefined, 1, "x", {}, { outcome: "inventado" }, []]) {
      assert.equal(desfechoDe(corpo), "desconhecido");
    }
  });
});

describe("as métricas do shim", () => {
  it("contam por desfecho e expõem no formato do Prometheus", () => {
    const metricas = new MetricasDoShim();
    metricas.contar(METRICA_JOBS, "executado", 2);
    metricas.contar(METRICA_FALHAS);
    const texto = metricas.exposicao();
    assert.match(texto, /# TYPE agr_shim_total counter/);
    assert.match(texto, /agr_shim_total\{outcome="executado"\} 2/);
    assert.match(texto, /agr_shim_failed_total 1/);
  });

  it("uma métrica sem série sai a zero, e não em falta", () => {
    // Um painel que não vê a série não distingue «não houve falhas» de «ninguém
    // mede».
    assert.match(new MetricasDoShim().exposicao(), /agr_shim_failed_total 0/);
  });

  it("recusa um identificador em etiqueta", () => {
    const metricas = new MetricasDoShim();
    for (const valor of [
      "11111111-1111-1111-1111-111111111111",
      "wamid.HBgMMjQ0OTAwMDAwMDAw",
      "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
    ]) {
      assert.throws(() => metricas.contar(METRICA_JOBS, valor), SufixoInvalidoError);
    }
  });

  it("recusa uma métrica que não é do shim", () => {
    const metricas = new MetricasDoShim();
    assert.throws(
      () => metricas.contar("agr_turns_total", "executado"),
      MetricaDesconhecidaError,
    );
  });

  it("não aceita etiqueta no contador de falhas", () => {
    assert.throws(
      () => new MetricasDoShim().contar(METRICA_FALHAS, "executado"),
      SufixoInvalidoError,
    );
  });

  it("nenhuma linha exposta traz um identificador", () => {
    const metricas = new MetricasDoShim();
    for (const outcome of DESFECHOS_DO_AGR) metricas.contar(METRICA_JOBS, outcome);
    metricas.contar(METRICA_FALHAS);
    for (const linha of metricas.exposicao().split("\n")) {
      if (linha.startsWith("#") || linha === "") continue;
      assert.doesNotMatch(linha, /[0-9a-f]{8}-[0-9a-f]{4}/);
      assert.doesNotMatch(linha, /wamid/);
    }
  });

  it("repõe", () => {
    const metricas = new MetricasDoShim();
    metricas.contar(METRICA_FALHAS);
    metricas.repor();
    assert.deepEqual(metricas.ler(), {});
  });
});
