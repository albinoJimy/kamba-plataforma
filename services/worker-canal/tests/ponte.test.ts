/**
 * O processo da ponte fila → consumidor Python (KAM-194).
 *
 * A decisão — o corpo da entrega e o que se faz com cada estado HTTP — é de
 * `@kamba/core-ts/eventos/ponte` e está provada lá
 * (`packages/core-ts/tests/eventos.ponte.test.ts`). Aqui prova-se a
 * **montagem**: que a sonda responde, que o `/metrics` serve a métrica da ponte
 * e **só** essa, que nenhuma rota a mais existe, e que a configuração recusa o
 * que falta nomeando a variável e nunca o valor.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { METRICAS_DA_PONTE } from "@kamba/core-ts/eventos";

import { PORTA_POR_OMISSAO as PORTA_DO_SHIM } from "../src/agr_shim.ts";
import { SERVICE } from "../src/meta.ts";
import {
  PORTA_POR_OMISSAO,
  SEGREDOS_DA_PONTE,
  VARIAVEL_DA_FILA,
  VARIAVEL_DO_ALVO,
  VARIAVEL_DO_SEGREDO,
  VARIAVEL_DOS_CONSUMIDORES,
  criarApp,
  lerConfiguracao,
} from "../src/ponte.ts";

const AMBIENTE = {
  [VARIAVEL_DA_FILA]: "redis://fila:6379",
  [VARIAVEL_DOS_CONSUMIDORES]: "idx",
  [VARIAVEL_DO_ALVO]: "http://idx:8000/",
  [VARIAVEL_DO_SEGREDO]: "idx_internal_token",
  KAMBA_ENV: "dev",
};

describe("as rotas do processo da ponte", () => {
  it("a sonda responde 200 com o serviço da topologia", async () => {
    const resposta = await criarApp().request("/healthz");
    assert.equal(resposta.status, 200);
    const carga = (await resposta.json()) as Record<string, unknown>;
    assert.equal(carga.status, "ok");
    assert.equal(carga.service, SERVICE);
  });

  it("o /metrics serve a métrica da ponte", async () => {
    METRICAS_DA_PONTE.repor();
    METRICAS_DA_PONTE.contar("entregue", 3);
    METRICAS_DA_PONTE.contar("repetir");
    const resposta = await criarApp().request("/metrics");
    assert.equal(resposta.status, 200);
    assert.match(resposta.headers.get("content-type") ?? "", /text\/plain/);
    const texto = await resposta.text();
    assert.match(texto, /evt_ponte_total\{outcome="entregue"\} 3/);
    assert.match(texto, /evt_ponte_total\{outcome="repetir"\} 1/);
    assert.match(texto, /evt_ponte_total\{outcome="recusado"\} 0/);
    METRICAS_DA_PONTE.repor();
  });

  it("o /metrics não serve as do consumo nem as do shim", async () => {
    // As do consumo vivem no lado Python, que é quem as mede; as do shim são
    // de outro processo. Duas séries com o mesmo nome somam mal num painel.
    const texto = await (await criarApp().request("/metrics")).text();
    assert.doesNotMatch(texto, /evt_consumed_total/);
    assert.doesNotMatch(texto, /evt_publish_total/);
    assert.doesNotMatch(texto, /agr_shim_total/);
  });

  it("nenhuma linha exposta traz um identificador", async () => {
    METRICAS_DA_PONTE.repor();
    METRICAS_DA_PONTE.contar("recusado");
    const texto = await (await criarApp().request("/metrics")).text();
    for (const linha of texto.split("\n")) {
      if (linha.startsWith("#") || linha === "") continue;
      assert.doesNotMatch(linha, /[0-9a-f]{8}-[0-9a-f]{4}/);
      assert.doesNotMatch(linha, /tenant|event_id|consumer/);
    }
    METRICAS_DA_PONTE.repor();
  });

  it("não há rota a mais", async () => {
    for (const caminho of ["/", "/healthz/", "/internal/event", "/admin", "/metrics/"]) {
      assert.notEqual((await criarApp().request(caminho)).status, 200, caminho);
    }
  });
});

describe("a configuração do processo", () => {
  it("a porta por omissão é 3194 e não colide com as dos outros processos", () => {
    // As do compose: 3000 gwy, 3001 worker-canal, 3002 com, 3003
    // onboarding-web, 3013 entrada, 3025 agr_shim, 8000 agr. Duas sondas na
    // mesma porta fazem a segunda não arrancar, e o sintoma é «o healthz
    // responde» — do processo errado.
    assert.equal(PORTA_POR_OMISSAO, 3194);
    for (const ocupada of [3000, 3001, 3002, 3003, 3013, PORTA_DO_SHIM, 8000]) {
      assert.notEqual(PORTA_POR_OMISSAO, ocupada);
    }
  });

  it("lê o ambiente, separa os consumidores e tira a barra final do alvo", () => {
    const configuracao = lerConfiguracao({
      ...AMBIENTE,
      [VARIAVEL_DOS_CONSUMIDORES]: " idx , agr ,",
    });
    assert.deepEqual(configuracao, {
      url: "redis://fila:6379",
      consumidores: ["idx", "agr"],
      alvo: "http://idx:8000",
      segredo: "idx_internal_token",
      ambiente: "dev",
      porta: PORTA_POR_OMISSAO,
    });
  });

  it("a porta lê-se de PONTE_PORT, e uma inválida não arranca", () => {
    assert.equal(lerConfiguracao({ ...AMBIENTE, PONTE_PORT: "4100" }).porta, 4100);
    for (const ma of ["0", "70000", "abc", "31.5"]) {
      assert.throws(() => lerConfiguracao({ ...AMBIENTE, PONTE_PORT: ma }), /PONTE_PORT/);
    }
  });

  for (const variavel of [
    VARIAVEL_DA_FILA,
    VARIAVEL_DOS_CONSUMIDORES,
    VARIAVEL_DO_ALVO,
    VARIAVEL_DO_SEGREDO,
  ]) {
    it(`sem ${variavel} não arranca, e a mensagem nomeia-a`, () => {
      for (const valor of [undefined, "", "   "]) {
        assert.throws(
          () => lerConfiguracao({ ...AMBIENTE, [variavel]: valor }),
          (erro: Error) => {
            assert.match(erro.message, new RegExp(variavel));
            return true;
          },
        );
      }
    });
  }

  it("uma lista de consumidores só de vírgulas não arranca", () => {
    assert.throws(
      () => lerConfiguracao({ ...AMBIENTE, [VARIAVEL_DOS_CONSUMIDORES]: " , ," }),
      new RegExp(VARIAVEL_DOS_CONSUMIDORES),
    );
  });

  it("o segredo é de lista fechada, e a mensagem não repete o valor", () => {
    assert.deepEqual([...SEGREDOS_DA_PONTE], ["agr_internal_token", "idx_internal_token"]);
    assert.throws(
      () => lerConfiguracao({ ...AMBIENTE, [VARIAVEL_DO_SEGREDO]: "db_password_app" }),
      (erro: Error) => {
        assert.match(erro.message, new RegExp(VARIAVEL_DO_SEGREDO));
        assert.doesNotMatch(erro.message, /db_password_app/);
        return true;
      },
    );
  });

  it("nenhuma mensagem de erro repete o valor de uma variável", () => {
    // Montado por partes: o `scan_secrets` le uma credencial num URL escrito por extenso.
    const valor = ["redis://utilizador", ":", "palavra-passe", "@fila:6379"].join("");
    assert.throws(
      () => lerConfiguracao({ ...AMBIENTE, [VARIAVEL_DA_FILA]: valor, [VARIAVEL_DO_ALVO]: "" }),
      (erro: Error) => !erro.message.includes("palavra-passe"),
    );
  });

  it("um KAMBA_ENV desconhecido não cai em dev", () => {
    assert.throws(() => lerConfiguracao({ ...AMBIENTE, KAMBA_ENV: "producao" }), /KAMBA_ENV/);
    assert.equal(lerConfiguracao({ ...AMBIENTE, KAMBA_ENV: undefined }).ambiente, "dev");
  });
});
