/**
 * O processo do *shim* da fila do AGR (KAM-025).
 *
 * A decisão — o que se faz com cada estado HTTP do AGR — é de
 * `@kamba/core-ts/agr` e está provada lá (`packages/core-ts/tests/agr.shim.test.ts`).
 * Aqui prova-se a **montagem**: que a sonda responde, que o `/metrics` serve as
 * métricas do *shim* e **só** essas, e que nenhuma rota a mais existe.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { METRICA_FALHAS, METRICA_JOBS, METRICAS_DO_SHIM } from "@kamba/core-ts/agr";

import { PORTA_POR_OMISSAO, SEGREDO_DA_API, criarApp } from "../src/agr_shim.ts";
import { SERVICE } from "../src/meta.ts";

describe("as rotas do processo do shim", () => {
  it("a sonda responde 200 com o serviço da topologia", async () => {
    const resposta = await criarApp().request("/healthz");
    assert.equal(resposta.status, 200);
    const carga = (await resposta.json()) as Record<string, unknown>;
    assert.equal(carga.status, "ok");
    assert.equal(carga.service, SERVICE);
  });

  it("o /metrics serve as métricas do shim", async () => {
    METRICAS_DO_SHIM.repor();
    METRICAS_DO_SHIM.contar(METRICA_JOBS, "executado", 3);
    METRICAS_DO_SHIM.contar(METRICA_FALHAS);
    const resposta = await criarApp().request("/metrics");
    assert.equal(resposta.status, 200);
    assert.match(resposta.headers.get("content-type") ?? "", /text\/plain/);
    const texto = await resposta.text();
    assert.match(texto, /agr_shim_total\{outcome="executado"\} 3/);
    assert.match(texto, /agr_shim_failed_total 1/);
    METRICAS_DO_SHIM.repor();
  });

  it("o /metrics não serve as métricas do AGR", async () => {
    // Elas vivem no processo Python, que é quem as mede. Duas séries com o
    // mesmo nome a contar a mesma coisa de dois sítios somam mal num painel.
    const texto = await (await criarApp().request("/metrics")).text();
    assert.doesNotMatch(texto, /agr_turns_total/);
    assert.doesNotMatch(texto, /agr_queue_depth/);
    assert.doesNotMatch(texto, /agr_turn_latency_ms/);
  });

  it("nenhuma linha exposta traz um identificador", async () => {
    METRICAS_DO_SHIM.repor();
    METRICAS_DO_SHIM.contar(METRICA_JOBS, "entregue_ao_hnd");
    const texto = await (await criarApp().request("/metrics")).text();
    for (const linha of texto.split("\n")) {
      if (linha.startsWith("#") || linha === "") continue;
      assert.doesNotMatch(linha, /[0-9a-f]{8}-[0-9a-f]{4}/);
      assert.doesNotMatch(linha, /wamid/);
    }
    METRICAS_DO_SHIM.repor();
  });

  it("não há rota a mais", async () => {
    for (const caminho of ["/", "/healthz/", "/internal/turn", "/admin", "/metrics/"]) {
      assert.notEqual((await criarApp().request(caminho)).status, 200, caminho);
    }
  });
});

describe("a configuração do processo", () => {
  it("a porta por omissão não colide com as dos outros processos", () => {
    // As do compose: 3000 gwy, 3001 worker-canal, 3002 com, 3003
    // onboarding-web, 3013 entrada, 8000 agr. Duas sondas na mesma porta
    // fazem a segunda não arrancar, e o sintoma é «o healthz responde» — do
    // processo errado.
    assert.equal(PORTA_POR_OMISSAO, 3025);
    for (const ocupada of [3000, 3001, 3002, 3003, 3013, 8000]) {
      assert.notEqual(PORTA_POR_OMISSAO, ocupada);
    }
  });

  it("o id do segredo é o mesmo que o AGR verifica", () => {
    // Dois nomes diferentes dariam 401 em todos os turnos, com os dois lados
    // a parecer configurados.
    assert.equal(SEGREDO_DA_API, "agr_internal_token");
  });
});
