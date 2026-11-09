/**
 * O manifesto das versões publicáveis (`gov/contratos/versoes.json`, KAM-090).
 *
 * É o lado do repositório de «uma versão publicada é imutável»: a base recusa
 * o `UPDATE` (revisão `0040`), e este ensaio recusa que o texto de um ficheiro
 * mude **sem o manifesto mudar**. Sem ele, o texto que uma PME aceitou e o que
 * o repositório tem podiam divergir por esquecimento.
 *
 * **O que ele não apanha**, e a primeira versão desta nota afirmava o
 * contrário: reescrever o `sha256` de uma entrada já publicada, em vez de
 * acrescentar uma versão nova. O ficheiro de uma versão antiga já não existe,
 * pelo que não há com que a comparar — o histórico prende-o a base e o `git`
 * (achado da revisão adversarial).
 *
 * **E é o contrato com o inventário do KAM-069** («o gate lê o inventário»): a
 * lista pública de subprocessadores é gerada de `gov/subprocessadores.yaml`, e
 * mudar o inventário muda a lista. Este ensaio fica vermelho até a mudança ter
 * versão nova — que é o histórico de versões que o critério 7 pede.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it } from "node:test";

import { TIPOS, canonizar, compararVersoes, sha256DoConteudo, versaoValida } from "../src/contratos/index.ts";

const RAIZ = resolve(import.meta.dirname, "..", "..", "..");

interface Entrada {
  readonly tipo: string;
  readonly versao: string;
  readonly ficheiro: string;
  readonly sha256: string;
}

const manifesto = JSON.parse(
  readFileSync(resolve(RAIZ, "gov", "contratos", "versoes.json"), "utf8"),
) as { readonly documentos: readonly Entrada[] };

describe("contratos: o manifesto das versões publicáveis", () => {
  it("cada um dos quatro tipos tem versões SemVer a crescer, sem repetir", () => {
    for (const tipo of TIPOS) {
      const versoes = manifesto.documentos.filter((e) => e.tipo === tipo).map((e) => e.versao);
      assert.ok(versoes.length > 0, `sem versao de ${tipo}`);
      for (const v of versoes) assert.ok(versaoValida(v), `${tipo} ${v}`);
      for (let i = 1; i < versoes.length; i += 1) {
        assert.equal(compararVersoes(versoes[i - 1] ?? "", versoes[i] ?? ""), -1, `${tipo}: ${versoes.join(" ")}`);
      }
    }
    for (const entrada of manifesto.documentos) {
      assert.ok((TIPOS as readonly string[]).includes(entrada.tipo), entrada.tipo);
    }
  });

  it("o texto de hoje é o da última versão de cada tipo", () => {
    for (const tipo of TIPOS) {
      const ultima = manifesto.documentos.filter((e) => e.tipo === tipo).at(-1);
      assert.ok(ultima);
      const texto = readFileSync(resolve(RAIZ, ultima.ficheiro), "utf8");
      assert.equal(
        sha256DoConteudo(canonizar(texto)).toString("hex"),
        ultima.sha256,
        `${ultima.ficheiro} mudou sem versao nova: acrescente uma entrada de ${tipo} ` +
          "a gov/contratos/versoes.json com a versao seguinte e o sha256 novo",
      );
    }
  });

  it("os três textos jurídicos têm os marcadores até ao parecer (KAM-104)", () => {
    for (const tipo of ["dpa", "privacidade", "tos"]) {
      const ultima = manifesto.documentos.filter((e) => e.tipo === tipo).at(-1);
      assert.ok(ultima);
      const texto = readFileSync(resolve(RAIZ, ultima.ficheiro), "utf8");
      if (ultima.versao.startsWith("0.")) assert.match(texto, /\[A CONFIRMAR POR PARECER\]/);
    }
  });
});
