/**
 * O processo do consumidor `dono` (KAM-215): a configuração, os papéis, a
 * subscrição e a app. O efeito corre contra a base em
 * `packages/core-ts/tests_bd/provisionamento.bd.test.ts` (suite `tests_chr`).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { filasDe } from "@kamba/core-ts/eventos";

import {
  ConfiguracaoDoProvisionamentoError,
  PAPEIS_DO_PROVISIONAMENTO,
  PORTA_POR_OMISSAO,
  PapelErradoError,
  SEGREDOS_DO_PROVISIONAMENTO,
  SUBSCRICAO_DO_DONO,
  VARIAVEIS_DO_PROVISIONAMENTO,
  consumidorDoDono,
  criarApp,
  lerConfiguracao,
  verificarPapeis,
} from "../src/provisionamento/processo.ts";

const AMBIENTE = {
  KAMBA_ENV: "dev",
  KAMBA_PROVISIONAMENTO_APP_DB_URL: "postgresql://kamba_app@app.invalid:5432/kamba",
  KAMBA_PROVISIONAMENTO_IDENTITY_DB_URL: "postgresql://kamba_identity@identidade.invalid:5432/kamba",
  KAMBA_QUEUE_URL: "redis://fila:6379",
};

test("a configuração lê as quatro variáveis, e a porta por omissão é a 3015", () => {
  const c = lerConfiguracao(AMBIENTE);
  assert.equal(c.ambiente, "dev");
  assert.equal(c.porta, PORTA_POR_OMISSAO);
  assert.equal(PORTA_POR_OMISSAO, 3015);
  assert.equal(lerConfiguracao({ ...AMBIENTE, PROVISIONAMENTO_PORT: "4001" }).porta, 4001);
});

test("sem uma das ligações, sem a fila ou sem o ambiente não arranca — e o valor não sai na mensagem", () => {
  for (const variavel of [
    VARIAVEIS_DO_PROVISIONAMENTO.ambiente,
    VARIAVEIS_DO_PROVISIONAMENTO.app,
    VARIAVEIS_DO_PROVISIONAMENTO.identidade,
    VARIAVEIS_DO_PROVISIONAMENTO.fila,
  ]) {
    assert.throws(
      () => lerConfiguracao({ ...AMBIENTE, [variavel]: "  " }),
      (erro: unknown) => erro instanceof ConfiguracaoDoProvisionamentoError && erro.variavel === variavel,
    );
  }
  for (const [variavel, valor] of [
    [VARIAVEIS_DO_PROVISIONAMENTO.ambiente, "producao"],
    [VARIAVEIS_DO_PROVISIONAMENTO.porta, "70000"],
    [VARIAVEIS_DO_PROVISIONAMENTO.porta, "abc"],
  ] as const) {
    assert.throws(() => lerConfiguracao({ ...AMBIENTE, [variavel]: valor }), ConfiguracaoDoProvisionamentoError);
  }
  assert.throws(
    () => lerConfiguracao({ ...AMBIENTE, KAMBA_ENV: "producao" }),
    (erro: unknown) => !String((erro as Error).message).includes("producao"),
  );
  assert.throws(
    () => lerConfiguracao({ ...AMBIENTE, KAMBA_QUEUE_URL: "" }),
    (erro: unknown) => !String((erro as Error).message).includes("postgresql://"),
  );
});

function ligacaoDe(papel: string) {
  return { query: async () => ({ rows: [{ papel }] }) } as never;
}

test("cada ligação tem de ser do seu papel: kamba_app para o consumo e kamba_identity para a porta", async () => {
  await verificarPapeis(ligacaoDe("kamba_app"), ligacaoDe("kamba_identity"));
  // Trocadas, ou com o `kamba_batch` (que lia o telefone de qualquer tenant): recusa.
  for (const [app, identidade] of [
    ["kamba_identity", "kamba_app"],
    ["kamba_batch", "kamba_identity"],
    ["kamba_app", "kamba_app"],
    ["postgres", "kamba_identity"],
  ] as const) {
    await assert.rejects(verificarPapeis(ligacaoDe(app), ligacaoDe(identidade)), PapelErradoError);
  }
  assert.deepEqual(PAPEIS_DO_PROVISIONAMENTO, { app: "kamba_app", identidade: "kamba_identity" });
});

test("os segredos do arranque são a KEK do telefone e as duas do contacto — e nenhuma das KEK recusadas", () => {
  assert.deepEqual([...SEGREDOS_DO_PROVISIONAMENTO].sort(), ["kek_contact_dek", "kek_telefone_do_caso", "pepper_contact_hmac"]);
  assert.ok(!(SEGREDOS_DO_PROVISIONAMENTO as readonly string[]).includes("kek_token_cliente"));
});

test("o consumidor é o `dono`, sem ordem, nas dezasseis filas, com o efeito que recebe", () => {
  const efeito = async () => {};
  let opcoes: Record<string, unknown> | undefined;
  const linhas: unknown[] = [];
  consumidorDoDono({
    urlDaApp: AMBIENTE.KAMBA_PROVISIONAMENTO_APP_DB_URL,
    urlDaFila: AMBIENTE.KAMBA_QUEUE_URL,
    efeito,
    log: { info: (c: unknown) => linhas.push(c) } as never,
    criar: ((o: Record<string, unknown>) => {
      opcoes = o;
      return { fechar: async () => {} };
    }) as never,
  });
  assert.ok(opcoes !== undefined);
  assert.deepEqual(opcoes["subscricao"], { consumer: "dono", exigeOrdem: false });
  assert.deepEqual(SUBSCRICAO_DO_DONO, { consumer: "dono", exigeOrdem: false });
  assert.deepEqual(opcoes["filas"], filasDe("dono"));
  assert.equal((opcoes["filas"] as string[]).length, 16);
  assert.equal(opcoes["efeito"], efeito);
  assert.equal(opcoes["url"], AMBIENTE.KAMBA_QUEUE_URL);
  (opcoes["log"] as (d: Record<string, unknown>) => void)({ desfecho: "aplicado", event_id: "x", tenant_id: "y" });
  assert.deepEqual(linhas, [{ outcome: "dono_consumo_aplicado" }], "só o desfecho vai para o registo");
});

test("a app serve /healthz e /metrics, e mais nada", async () => {
  const app = criarApp();
  assert.equal((await app.request("/healthz")).status, 200);
  const metricas = await app.request("/metrics");
  assert.equal(metricas.status, 200);
  assert.match(metricas.headers.get("content-type") ?? "", /^text\/plain/);
  assert.equal((await app.request("/painel")).status, 404);
});
