/**
 * O início do teste ponta a ponta pela página do dono (KAM-202, critério 2), pela
 * superfície HTTP.
 *
 * O `TesteDoPainel` é aqui um duplo que regista o caso e o tenant de cada
 * chamada; o de produção (`../src/painel/teste.ts`, sobre o `kamba_app`) mede-se
 * contra o PostgreSQL em `packages/core-ts/tests_bd/activacao.bd.test.ts`. O que
 * aqui se prova é a ligação:
 *
 * ```text
 * sem ligacao da aplicacao           503, e o resto do painel serve igual
 * sem sessao                         401, e a porta nao e chamada
 * fora de aguarda_teste              409 `fase`
 * a sessao de A                      200, com o caso e o tenant DA SESSAO, mesmo
 *                                    com o tenant e o caso de B no pedido
 * a base em baixo                    503, sem o motivo
 * ```
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CanalEmMemoria } from "../src/painel/canal.ts";
import { ComercioEmMemoria } from "../src/painel/comercio.ts";
import { MetricasDoPainel } from "../src/painel/metricas.ts";
import { FASE_DO_TESTE, rotasDoPainel, type TesteDoPainel } from "../src/painel/rotas.ts";
import { RevogacoesEmMemoria, cunharSessao, novaSessao } from "../src/painel/sessao.ts";

const TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CASO_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a";
const CASO_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b";
const CASO_ACTIVO = "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c";
const CHAVE = new Uint8Array(32).fill(7);
const AGORA = new Date("2026-11-20T10:00:00.000Z");
const EXPIRA = new Date("2026-11-20T10:01:00.000Z");

function montar(teste?: TesteDoPainel) {
  const metricas = new MetricasDoPainel();
  const casos = new Map([
    [CASO_A, { tenantId: TENANT_A, fase: FASE_DO_TESTE }],
    [CASO_B, { tenantId: TENANT_B, fase: FASE_DO_TESTE }],
    [CASO_ACTIVO, { tenantId: TENANT_A, fase: "activo" }],
  ]);
  const app = rotasDoPainel({
    comercio: new ComercioEmMemoria(),
    canal: new CanalEmMemoria(),
    revogacoes: new RevogacoesEmMemoria(),
    metricas,
    casos: { porId: async (id) => casos.get(id) ?? null },
    anelDaAssinatura: [CHAVE, null],
    relogio: () => AGORA,
    teste,
  });
  return { app, metricas };
}

function espiao(falha = false) {
  const chamadas: { onboardingId: string; tenantId: string }[] = [];
  const teste: TesteDoPainel = {
    async iniciar(onboardingId, tenantId) {
      chamadas.push({ onboardingId, tenantId });
      if (falha) throw new Error("ligacao caiu: dados do dono");
      return { instrucoes: "envie «teste»", expiraEm: EXPIRA };
    },
  };
  return { teste, chamadas };
}

function cookie(tenant: string, caso: string): string {
  return `kamba_painel=${cunharSessao(novaSessao(tenant, caso, AGORA), CHAVE)}`;
}

function post(app: ReturnType<typeof montar>["app"], caminho: string, cabecalhos: Record<string, string>, corpo: unknown = {}) {
  return app.request(caminho, {
    method: "POST",
    headers: { "content-type": "application/json", ...cabecalhos },
    body: JSON.stringify(corpo),
  });
}

describe("KAM-202 — o inicio do teste pelo painel", () => {
  it("sem a ligacao da aplicacao, 503", async () => {
    const { app, metricas } = montar();
    const r = await post(app, "/painel/teste", { cookie: cookie(TENANT_A, CASO_A) });
    assert.equal(r.status, 503);
    assert.equal(metricas.valor("teste", "indisponivel"), 1);
  });

  it("sem sessao, 401, e a porta nao e chamada", async () => {
    const { teste, chamadas } = espiao();
    const { app } = montar(teste);
    const r = await post(app, "/painel/teste", {});
    assert.equal(r.status, 401);
    assert.deepEqual(chamadas, []);
  });

  it("fora da fase do teste, 409", async () => {
    const { teste, chamadas } = espiao();
    const { app } = montar(teste);
    const r = await post(app, "/painel/teste", { cookie: cookie(TENANT_A, CASO_ACTIVO) });
    assert.equal(r.status, 409);
    assert.deepEqual(await r.json(), { erro: "fase" });
    assert.deepEqual(chamadas, []);
  });

  it("com a sessao de A, abre a tentativa no caso e no tenant da sessao, e devolve a janela", async () => {
    const { teste, chamadas } = espiao();
    const { app, metricas } = montar(teste);
    const r = await post(app, "/painel/teste", { cookie: cookie(TENANT_A, CASO_A) });
    assert.equal(r.status, 200);
    assert.deepEqual(await r.json(), { instrucoes: "envie «teste»", expira_em: EXPIRA.toISOString() });
    assert.deepEqual(chamadas, [{ onboardingId: CASO_A, tenantId: TENANT_A }]);
    assert.equal(metricas.valor("teste"), 1);
  });

  it("o caso e o tenant de B no corpo, na consulta e no cabecalho nao sao lidos", async () => {
    const { teste, chamadas } = espiao();
    const { app } = montar(teste);
    const deA = cookie(TENANT_A, CASO_A);
    await post(app, "/painel/teste", { cookie: deA }, { onboarding_id: CASO_B, tenant_id: TENANT_B });
    await post(app, `/painel/teste?tenant_id=${TENANT_B}&onboarding_id=${CASO_B}`, { cookie: deA });
    await post(app, "/painel/teste", { cookie: deA, "x-kamba-tenant": TENANT_B });
    assert.equal(chamadas.length, 3);
    assert.ok(chamadas.every((c) => c.onboardingId === CASO_A && c.tenantId === TENANT_A));
  });

  it("a base em baixo da 503, e o motivo nao sai", async () => {
    const { teste } = espiao(true);
    const { app, metricas } = montar(teste);
    const r = await post(app, "/painel/teste", { cookie: cookie(TENANT_A, CASO_A) });
    assert.equal(r.status, 503);
    assert.doesNotMatch(await r.text(), /ligacao|dados/);
    assert.equal(metricas.valor("teste", "indisponivel"), 1);
  });
});
