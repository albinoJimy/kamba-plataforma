/**
 * As guardas de arranque G-2 e G-4 (KAM-052, criterios 3 e 6).
 *
 * O ensaio que faz o trabalho e o **controlo positivo** da G-4. A lista de
 * entidades EMIS da KAMBA esta vazia em producao — os identificadores sao NAO
 * VERIFICADO (D4, KAM-103) —, pelo que a guarda passa sempre contra a
 * configuracao real. Um ensaio que so corresse contra ela media zero e dizia
 * zero. Por isso a lista entra por parametro e aqui enche-se.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  CAPACIDADES_DO_FAKE,
  CONTA_DE_PME_COM_ENTIDADE_DA_KAMBA,
  ENTIDADES_DA_KAMBA,
  FLAGS_OMISSAO,
  PAYOUTS_SEM_PSP_LICENCIADO,
  ArranqueRecusado,
  type Conformidade,
  type ContaParaGuarda,
  type EntidadesDaKamba,
  type PaymentProvider,
  type ProviderCapabilities,
  RegistoDeProviders,
  verificarArranque,
  verificarG2,
  verificarG4,
} from "../src/pagamentos/index.ts";
import { capturar } from "./apoio/capturar.ts";

const SEMPRE_VERDE: Conformidade = { green: () => true };

function adaptador(id: string, capacidades: Partial<ProviderCapabilities> = {}): PaymentProvider {
  const caps: ProviderCapabilities = { ...CAPACIDADES_DO_FAKE, ...capacidades };
  return {
    id,
    capabilities: caps,
    createCharge: async () => ({ kind: "manual", instrucoes: "" }),
    status: async () => ({ estado: "desconhecida" }),
    refund: async () => ({ ok: false, erro: "NOT_SUPPORTED" }),
    payout: async () => ({ ok: false, erro: "NOT_SUPPORTED" }),
    verifyCallback: async () => [],
  };
}

function conta(parcial: Partial<ContaParaGuarda> = {}): ContaParaGuarda {
  return {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    beneficiaryKind: "pme",
    tenantId: "11111111-1111-4111-8111-111111111111",
    estado: "ativo",
    entidade: "00987",
    posId: "POS-PME-1",
    iec: null,
    ...parcial,
  };
}

describe("pagamentos/arranque: as flags de dinheiro", () => {
  it("as duas estao desligadas por omissao (§10.4 G-2, §11.1)", () => {
    assert.deepEqual(FLAGS_OMISSAO, { payoutsEnabled: false, commissionEnabled: false });
  });
});

describe("pagamentos/arranque: criterio 3 — G-2", () => {
  it("com a flag desligada, arranca sem adaptador nenhum", () => {
    assert.doesNotThrow(() => verificarG2(FLAGS_OMISSAO, new RegistoDeProviders(SEMPRE_VERDE)));
  });

  /** **O teste de arranque que o criterio 3 pede por nome.** */
  it("com payouts_enabled=true e sem psp_licenciado, o servico nao arranca", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("fake"));
    const erro = capturar<ArranqueRecusado>(() => verificarG2({ payoutsEnabled: true, commissionEnabled: false }, registo));
    assert.equal(erro.codigo, PAYOUTS_SEM_PSP_LICENCIADO);
  });

  it("e tambem nao arranca com o registo vazio", () => {
    assert.throws(
      () =>
        verificarG2(
          { payoutsEnabled: true, commissionEnabled: false },
          new RegistoDeProviders(SEMPRE_VERDE),
        ),
      ArranqueRecusado,
    );
  });

  it("arranca com a flag ligada **e** um psp_licenciado", () => {
    const registo = new RegistoDeProviders(SEMPRE_VERDE);
    registo.activar(adaptador("psp", { pspLicenciado: true }));
    assert.doesNotThrow(() =>
      verificarG2({ payoutsEnabled: true, commissionEnabled: false }, registo),
    );
  });
});

describe("pagamentos/arranque: criterio 6 — G-4", () => {
  /**
   * A configuracao real. **Passa, e o verde nao diz nada** — e por isso que o
   * ensaio seguinte existe. Fica aqui para fixar o estado de hoje: se alguem
   * acrescentar uma entidade ao YAML e ao TypeScript, este ensaio nao muda, mas
   * o `test_as_duas_fontes_nao_divergem` passa a comparar outra coisa.
   */
  it("contra a configuracao de producao passa, porque ela esta vazia", () => {
    assert.doesNotThrow(() => verificarG4([conta()], ENTIDADES_DA_KAMBA));
  });

  /** **O controlo positivo: a guarda morde.** */
  it("recusa uma conta de pme que aponte para a entidade da KAMBA", () => {
    const daKamba: EntidadesDaKamba = { entidades: ["00987"], posIds: [], iecs: [] };
    const erro = capturar<ArranqueRecusado>(() => verificarG4([conta()], daKamba));
    assert.equal(erro.codigo, CONTA_DE_PME_COM_ENTIDADE_DA_KAMBA);
    assert.ok(erro.message.includes("00987"));
  });

  it("e morde pelos tres identificadores, nao so pela entidade", () => {
    const casos: readonly [keyof EntidadesDaKamba, Partial<ContaParaGuarda>][] = [
      ["entidades", { entidade: "X1", posId: null, iec: null }],
      ["posIds", { entidade: null, posId: "X1", iec: null }],
      ["iecs", { entidade: null, posId: null, iec: "X1" }],
    ];
    for (const [campo, parcial] of casos) {
      const daKamba: EntidadesDaKamba = {
        entidades: [],
        posIds: [],
        iecs: [],
        [campo]: ["X1"],
      } as EntidadesDaKamba;
      assert.throws(() => verificarG4([conta(parcial)], daKamba), ArranqueRecusado, campo);
    }
  });

  /**
   * As contas de `plataforma_receita_propria` **sao** o uso legitimo destes
   * identificadores: e com eles que a KAMBA cobra a assinatura (§11.2). Uma
   * guarda que as recusasse impedia o billing da propria plataforma — isto e,
   * tornava o KAM-059 impossivel.
   */
  it("nao recusa a conta de receita propria com a entidade da KAMBA", () => {
    const daKamba: EntidadesDaKamba = { entidades: ["00987"], posIds: [], iecs: [] };
    const propria = conta({
      beneficiaryKind: "plataforma_receita_propria",
      tenantId: null,
      posId: null,
    });
    assert.doesNotThrow(() => verificarG4([propria], daKamba));
  });

  it("nomeia todas as contas em falta, nao so a primeira", () => {
    const daKamba: EntidadesDaKamba = { entidades: ["E1", "E2"], posIds: [], iecs: [] };
    const erro = capturar<ArranqueRecusado>(() =>
      verificarG4(
        [
          conta({ id: "conta-1", entidade: "E1", posId: null }),
          conta({ id: "conta-2", entidade: "E2", posId: null }),
        ],
        daKamba,
      ),
    );
    assert.ok(erro.message.includes("conta-1"));
    assert.ok(erro.message.includes("conta-2"));
  });
});

describe("pagamentos/arranque: as duas guardas juntas", () => {
  it("a G-2 corre antes da G-4", () => {
    const daKamba: EntidadesDaKamba = { entidades: ["00987"], posIds: [], iecs: [] };
    const erro = capturar<ArranqueRecusado>(() =>
      verificarArranque(
        { payoutsEnabled: true, commissionEnabled: false },
        new RegistoDeProviders(SEMPRE_VERDE),
        [conta()],
        daKamba,
      ),
    );
    assert.equal(erro.codigo, PAYOUTS_SEM_PSP_LICENCIADO);
  });
});

describe("pagamentos/arranque: o YAML e o TypeScript dizem o mesmo", () => {
  /**
   * O espelho do `config/meta_rates.yaml` e do `outbound/tarifas.ts` (KAM-015):
   * nao ha leitor de YAML em `packages/core-ts`, pelo que a lista vive nos dois
   * sitios e **isto** e o que impede que divirjam.
   *
   * A leitura e por linha e nao por um leitor de YAML, de propria decisao: o que
   * se quer saber e se as tres listas estao vazias ou tem os mesmos valores, e
   * um leitor completo so para isto era a dependencia que o desenho evita. Uma
   * lista nao vazia no YAML que este ensaio nao saiba ler **falha**, que e o
   * lado certo para falhar.
   */
  it("as duas fontes nao divergem", () => {
    const caminho = new URL("../../../config/kamba_emis.yaml", import.meta.url);
    const texto = readFileSync(caminho, "utf8");
    const lido: Record<string, readonly string[]> = {};
    for (const linha of texto.split(/\r?\n/)) {
      const encontro = /^([a-z_]+):\s*(\[\]|\[(.*)\])\s*$/.exec(linha);
      if (encontro === null) continue;
      const interior = encontro[3];
      lido[encontro[1] ?? ""] =
        interior === undefined || interior.trim() === ""
          ? []
          : interior.split(",").map((v) => v.trim().replace(/^["']|["']$/g, ""));
    }
    assert.deepEqual(Object.keys(lido).sort(), ["entidades", "iecs", "pos_ids"]);
    assert.deepEqual(lido["entidades"], [...ENTIDADES_DA_KAMBA.entidades]);
    assert.deepEqual(lido["pos_ids"], [...ENTIDADES_DA_KAMBA.posIds]);
    assert.deepEqual(lido["iecs"], [...ENTIDADES_DA_KAMBA.iecs]);
  });

  /** E o YAML diz, por escrito, que o estado e NAO VERIFICADO. */
  it("o YAML declara o estado de verificacao e a decisao aberta", () => {
    const caminho = new URL("../../../config/kamba_emis.yaml", import.meta.url);
    const texto = readFileSync(caminho, "utf8");
    assert.match(texto, /NAO VERIFICADO/);
    assert.match(texto, /D4/);
    assert.match(texto, /KAM-103/);
  });
});
