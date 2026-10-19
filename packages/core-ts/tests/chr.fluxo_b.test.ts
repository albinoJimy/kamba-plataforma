/**
 * A guarda do Fluxo B, nas duas metades do critério 5 do KAM-014.
 *
 * «Um canal `origem='plataforma'` ou `vertical='assistente'` é recusado» é a
 * recusa **em execução** (`recusaDoFluxoB`), e é função pura. «O arranque falha
 * se existir tal linha em produção» é `verificarArranque`, e aqui prova-se com
 * uma base falsa: o que corre contra um PostgreSQL real — incluindo que o
 * `kamba_app` **não** consegue correr a guarda — está em `db/tests_chr/`.
 *
 * O ficheiro prova também a **paridade com o espelho Python**: as constantes
 * deste módulo são as mesmas de
 * `libs/py-core/src/kamba_core/fluxo_piloto.py`, lidas do ficheiro.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  FASE_PILOTO,
  canalDaLinha,
  FaseNaoDefinidaError,
  FluxoBNoPilotoError,
  GuardaCegaError,
  ORIGEM_DE_PLATAFORMA,
  SQL_GUARDA_FLUXO_B,
  SQL_VISIBILIDADE,
  TIPO_DE_PLATAFORMA,
  VARIAVEL_DA_FASE,
  VERTICAIS_DO_PILOTO,
  exigirFaseDoPiloto,
  recusaDoFluxoB,
  verificarArranque,
} from "../src/chr/index.ts";
import { BaseFalsa, linhaDeCanal } from "./apoio/chr-base-falsa.ts";

const ESPELHO = new URL(
  "../../../libs/py-core/src/kamba_core/fluxo_piloto.py",
  import.meta.url,
);

const PILOTO = { [VARIAVEL_DA_FASE]: FASE_PILOTO };

function contagens(
  tenants = 0,
  canais = 0,
  verticais = 0,
): { readonly rows: readonly Readonly<Record<string, unknown>>[] } {
  return {
    rows: [
      {
        tenants_plataforma: tenants,
        canais_plataforma: canais,
        verticais_fora: verticais,
      },
    ],
  };
}

function baseQueVeTudo(...resto: Parameters<BaseFalsa["responde"]>[1][]): BaseFalsa {
  const bd = new BaseFalsa().responde("ve_tudo", { rows: [{ ve_tudo: true }] });
  if (resto.length > 0) bd.responde("tenants_plataforma", ...resto);
  return bd;
}

describe("paridade com o espelho Python", () => {
  const fonte = readFileSync(ESPELHO, "utf8");

  it("a variavel e o valor da fase sao os mesmos", () => {
    assert.match(fonte, new RegExp(`VARIAVEL = "${VARIAVEL_DA_FASE}"`));
    assert.match(fonte, new RegExp(`FASE_PILOTO = "${FASE_PILOTO}"`));
  });

  it("as verticais do Piloto sao as mesmas, e na mesma ordem", () => {
    const encontrado = /VERTICAIS_DO_PILOTO = \(([^)]*)\)/.exec(fonte);
    assert.ok(
      encontrado?.[1] !== undefined,
      "o espelho deixou de declarar VERTICAIS_DO_PILOTO",
    );
    const doPython = [...encontrado[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    assert.deepEqual(doPython, [...VERTICAIS_DO_PILOTO]);
  });

  it("os dois valores recusados aparecem no espelho", () => {
    assert.ok(fonte.includes(`tipo = '${TIPO_DE_PLATAFORMA}'`));
    assert.ok(fonte.includes(`origem = '${ORIGEM_DE_PLATAFORMA}'`));
  });

  it("o SQL de visibilidade do espelho e o deste modulo, sem espacos", () => {
    // Nao se compara caractere a caractere: o Python parte a consulta em
    // literais com indentacao propria. Compara-se sem espacos, que e o que
    // torna a divergencia **semantica** visivel sem apanhar reformatacoes.
    const semEspacos = (texto: string) => texto.replace(/\s+/g, "");
    const doPython = /CONSULTA_DE_VISIBILIDADE = \(([\s\S]*?)\n\)/.exec(fonte);
    assert.ok(
      doPython?.[1] !== undefined,
      "o espelho deixou de declarar CONSULTA_DE_VISIBILIDADE",
    );
    const juntas = [...doPython[1].matchAll(/"([^"]*)"/g)].map((m) => m[1]).join("");
    assert.equal(semEspacos(juntas), semEspacos(SQL_VISIBILIDADE.replace("AS ve_tudo", "")));
  });
});

describe("exigirFaseDoPiloto", () => {
  it("`piloto` passa", () => {
    exigirFaseDoPiloto(PILOTO);
  });

  it("ausente, vazia ou com outro valor **levanta** — nao se desliga", () => {
    for (const valor of [undefined, "", "producao", "clusters", "PILOTO"]) {
      assert.throws(
        () => exigirFaseDoPiloto(valor === undefined ? {} : { [VARIAVEL_DA_FASE]: valor }),
        FaseNaoDefinidaError,
        String(valor),
      );
    }
  });
});

describe("recusaDoFluxoB", () => {
  it("um canal do Piloto passa", () => {
    assert.equal(recusaDoFluxoB(canal(), "pme"), null);
    assert.equal(recusaDoFluxoB(canal({ vertical: "servicos" }), "pme"), null);
  });

  it("um tenant `platform` e recusado", () => {
    assert.match(String(recusaDoFluxoB(canal(), TIPO_DE_PLATAFORMA)), /tenants\.tipo/);
  });

  it("um canal `origem = plataforma` e recusado", () => {
    assert.match(
      String(recusaDoFluxoB(canal({ origem: ORIGEM_DE_PLATAFORMA }), "pme")),
      /origem/,
    );
  });

  it("`assistente` e recusado, e **tambem** `assistente_v2`", () => {
    // Lista de permitidas e nao de proibidas: uma comparacao por igualdade com
    // `assistente` nao via `assistente_v2`. E a razao escrita no espelho.
    for (const vertical of ["assistente", "assistente_v2", "catalogo", "social"]) {
      assert.match(
        String(recusaDoFluxoB(canal({ vertical }), "pme")),
        /vertical fora de/,
        vertical,
      );
    }
  });

  it("o tipo do tenant tem precedencia na mensagem, e isso e deliberado", () => {
    // Com os tres defeitos ao mesmo tempo, a mensagem nomeia o do tenant: e o
    // mais largo, e corrigir a vertical de um tenant `platform` nao resolvia
    // nada. A ordem e a do espelho Python.
    assert.match(
      String(
        recusaDoFluxoB(
          canal({ origem: ORIGEM_DE_PLATAFORMA, vertical: "assistente" }),
          TIPO_DE_PLATAFORMA,
        ),
      ),
      /tenants\.tipo/,
    );
  });
});

describe("verificarArranque", () => {
  it("base limpa e fase `piloto`: arranca", async () => {
    const bd = baseQueVeTudo(contagens());
    const contagem = await verificarArranque(bd, PILOTO);
    assert.deepEqual(contagem, {
      tenantsPlataforma: 0,
      canaisPlataforma: 0,
      verticaisFora: 0,
    });
    // A visibilidade e perguntada **antes** da contagem.
    assert.ok(bd.instrucoes[0]?.sql.includes("ve_tudo"));
    assert.equal(bd.instrucoes[1]?.sql, SQL_GUARDA_FLUXO_B);
    assert.deepEqual(bd.instrucoes[1]?.parametros, [
      TIPO_DE_PLATAFORMA,
      ORIGEM_DE_PLATAFORMA,
      [...VERTICAIS_DO_PILOTO],
    ]);
  });

  it("a fase e verificada **antes** de se tocar na base", async () => {
    const bd = baseQueVeTudo(contagens());
    await assert.rejects(() => verificarArranque(bd, {}), FaseNaoDefinidaError);
    assert.equal(bd.instrucoes.length, 0);
  });

  it("um papel que nao prova que ve tudo **nao conta**: levanta GuardaCega", async () => {
    const bd = new BaseFalsa().responde("ve_tudo", { rows: [{ ve_tudo: false }] });
    await assert.rejects(() => verificarArranque(bd, PILOTO), GuardaCegaError);
    assert.equal(bd.quantas("tenants_plataforma"), 0);
  });

  it("uma resposta de visibilidade que nao e `true` e tratada como cega", async () => {
    // `null`, ausente ou qualquer outra coisa: uma contagem de zero sobre uma
    // base que o papel nao ve e a resposta que esta guarda nao pode inventar.
    for (const resposta of [
      { rows: [] },
      { rows: [{ ve_tudo: null }] },
      { rows: [{ ve_tudo: "t" }] },
      { rows: [{}] },
    ]) {
      const bd = new BaseFalsa().responde("ve_tudo", resposta);
      await assert.rejects(() => verificarArranque(bd, PILOTO), GuardaCegaError);
    }
  });

  it("uma contagem ilegivel e tratada como cega, e nao como zero", async () => {
    const bd = baseQueVeTudo({ rows: [{ tenants_plataforma: null }] });
    await assert.rejects(() => verificarArranque(bd, PILOTO), GuardaCegaError);
  });

  it("`count(*)` como texto — que e o que o `pg` devolve — e aceite", async () => {
    const bd = baseQueVeTudo({
      rows: [
        { tenants_plataforma: "0", canais_plataforma: "0", verticais_fora: "0" },
      ],
    });
    const contagem = await verificarArranque(bd, PILOTO);
    assert.equal(contagem.tenantsPlataforma, 0);
  });

  it("cada uma das tres linhas de Fluxo B recusa o arranque, e a mensagem di-lo", async () => {
    const casos: [number, number, number, RegExp][] = [
      [1, 0, 0, /tenants\.tipo/],
      [0, 2, 0, /2 linha\(s\) com platform\.tenant_channels\.origem/],
      [0, 0, 3, /3 linha\(s\) com platform\.tenant_channels\.vertical fora de/],
    ];
    for (const [t, c, v, esperado] of casos) {
      const bd = baseQueVeTudo(contagens(t, c, v));
      await assert.rejects(
        () => verificarArranque(bd, PILOTO),
        (erro: unknown) => {
          assert.ok(erro instanceof FluxoBNoPilotoError);
          assert.match(erro.message, esperado);
          assert.match(erro.message, /ADR-011/);
          return true;
        },
      );
    }
  });

  it("com as tres, a mensagem nomeia as tres", async () => {
    const bd = baseQueVeTudo(contagens(1, 1, 1));
    await assert.rejects(
      () => verificarArranque(bd, PILOTO),
      (erro: unknown) => {
        assert.ok(erro instanceof FluxoBNoPilotoError);
        assert.equal(erro.message.split(";").length, 3);
        return true;
      },
    );
  });
});

function canal(troca: Readonly<Record<string, unknown>> = {}) {
  return canalDaLinha(linhaDeCanal(troca)).contexto;
}
