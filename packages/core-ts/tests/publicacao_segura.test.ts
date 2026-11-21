/**
 * O resumo do conteúdo de um produto, partilhado com a base (KAM-202).
 *
 * O *trigger* `offer_terms_publicacao_segura` recalcula na base o
 * `conteudo_sha256` do KAM-088 (`platform.conteudo_sha256_do_produto`), e só
 * encontra a decisão gravada pelo `screen` se os dois resumos forem os mesmos
 * bytes. A fixture tem os valores esperados, calculados à parte; este ensaio
 * prende-lhes o `conteudoSha256` de TypeScript, e o
 * `db/tests/test_publicacao_segura_schema.py` prende-lhes a função SQL. Com os
 * casos difíceis do escape de JSON: aspas, barra invertida, os escapes curtos,
 * controlo abaixo de `0x20`, acentos e caracteres fora do plano básico.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { conteudoSha256 } from "../src/screening/index.ts";

describe("o conteudo_sha256 de um produto, partilhado com a base", () => {
  it("o conteudoSha256 do KAM-088 da os valores da fixture que a funcao SQL tambem tem de dar", () => {
    const casos = JSON.parse(
      readFileSync(new URL("./fixtures/conteudo_sha256.json", import.meta.url), "utf8"),
    ) as { categoria: string; nome: string; sha256: string }[];
    assert.ok(casos.length >= 9);
    for (const c of casos) {
      const sha = Buffer.from(conteudoSha256({ categoria_declarada: c.categoria, textos: [c.nome] })).toString("hex");
      assert.equal(sha, c.sha256, JSON.stringify(c.nome));
    }
  });
});
