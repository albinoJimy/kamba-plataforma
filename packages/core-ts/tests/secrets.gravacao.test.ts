/**
 * A escrita numa referência fixa do cofre (KAM-250), do lado TypeScript.
 *
 * Espelho de `libs/py-core/tests/test_secrets_escrita.py`. O duplo **lê o texto do
 * pedido** — URL, cabeçalhos e corpo —, como o bloco do KAM-250 manda.
 *
 * **Canário:** «recusa uma familia que nao e das chaves».
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AmbienteErradoError,
  CofreInacessivelError,
  DopplerGravador,
  FAMILIAS_DAS_CHAVES_DO_LLM,
  FamiliaNaoGravavelError,
  type PedidoHttpDeEscrita,
} from "../src/secrets/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const VALOR = "sk-valor-ensaio";

function transporte(status = 200, corpo = "{}", levanta?: Error) {
  const pedidos: PedidoHttpDeEscrita[] = [];
  const f = async (p: PedidoHttpDeEscrita) => {
    pedidos.push(p);
    if (levanta !== undefined) throw levanta;
    return { status, corpo };
  };
  return { pedidos, f };
}

function gravador(f: (p: PedidoHttpDeEscrita) => Promise<{ status: number; corpo: string }>) {
  return new DopplerGravador({
    ambiente: "prod",
    projecto: "kamba-llm-chaves",
    config: "prod",
    tokenServico: "dp.st.escrita",
    transporte: f,
  });
}

describe("KAM-250 — o DopplerGravador", () => {
  it("o corpo leva o projecto, a config e o nome da variavel", async () => {
    const t = transporte();
    await gravador(t.f).gravar(`litellm_virtual_key/${TENANT}`, VALOR);
    const p = t.pedidos[0];
    assert.ok(p !== undefined);
    assert.equal(p.url, "https://api.doppler.com/v3/configs/config/secrets");
    assert.equal(p.cabecalhos.authorization, "Bearer dp.st.escrita");
    assert.deepEqual(JSON.parse(p.corpo), {
      project: "kamba-llm-chaves",
      config: "prod",
      secrets: { [`KAMBA_SECRET_LITELLM_VIRTUAL_KEY__${TENANT.replace(/-/g, "_")}`]: VALOR },
    });
  });

  it("as familias sao as duas chaves virtuais", () => {
    assert.deepEqual([...FAMILIAS_DAS_CHAVES_DO_LLM], ["litellm_virtual_key", "litellm_screening_key"]);
  });

  it("recusa uma familia que nao e das chaves", async () => {
    const t = transporte();
    for (const ref of ["meta_app_secret", "litellm_master_key", "doppler_llm_chaves_leitura"]) {
      await assert.rejects(gravador(t.f).gravar(ref, VALOR), FamiliaNaoGravavelError);
    }
    assert.equal(t.pedidos.length, 0);
  });

  it("recusa um valor vazio", async () => {
    const t = transporte();
    await assert.rejects(gravador(t.f).gravar("litellm_screening_key", " "));
    assert.equal(t.pedidos.length, 0);
  });

  it("recusa construir com a config de outro ambiente", () => {
    assert.throws(
      () =>
        new DopplerGravador({
          ambiente: "prod",
          projecto: "kamba-llm-chaves",
          config: "staging",
          tokenServico: "x",
          transporte: transporte().f,
        }),
      AmbienteErradoError,
    );
  });

  for (const [nome, t] of [
    ["uma falha de transporte que cita o corpo", transporte(200, "{}", new Error(`enviei ${VALOR}`))],
    ["um 500 que ecoa o pedido", transporte(500, JSON.stringify({ eco: VALOR }))],
    ["um 403", transporte(403, VALOR)],
  ] as const) {
    it(`o valor nao sai no erro: ${nome}`, async () => {
      await assert.rejects(gravador(t.f).gravar("litellm_screening_key", VALOR), (erro: unknown) => {
        assert.ok(erro instanceof CofreInacessivelError);
        assert.ok(!erro.message.includes(VALOR));
        assert.ok(!erro.message.includes("dp.st.escrita"));
        return true;
      });
    });
  }
});
