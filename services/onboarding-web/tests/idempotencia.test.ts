/**
 * O `server.ts` dá ao painel a idempotência na base sempre que há base (KAM-240,
 * critério 3).
 *
 * O `server.ts` não se importa num ensaio (arranca o processo no carregamento),
 * e por isso a ligação mede-se pelo **texto** dele: a opção `idempotencia` do
 * painel é a `IdempotenciaNaBase` com a base, e `undefined` (a das rotas, em
 * memória) sem ela; e sem base o arranque em `prod` recusa, pelo que em `prod`
 * é sempre a da base. O que a classe faz contra a base mede-se em
 * `packages/core-ts/tests_bd/idempotencia.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const SERVIDOR = readFileSync(new URL("../src/server.ts", import.meta.url), "utf8");

describe("a idempotência do painel no server.ts (KAM-240)", () => {
  it("com base, o painel recebe a IdempotenciaNaBase num pool só seu; sem ela, a das rotas", () => {
    assert.match(
      SERVIDOR,
      /\n {4}idempotencia: NA_BASE \? new IdempotenciaNaBase\(poolDe\(URL_DA_APP, "idempotencia", LIGACOES_DA_IDEMPOTENCIA\)\) : undefined,\n/,
    );
    assert.equal(SERVIDOR.match(/\bidempotencia:/g)?.length, 1, "uma só opção idempotencia no painel");
  });

  it("em prod sem base o arranque recusa, logo em prod a idempotência é a da base", () => {
    assert.match(SERVIDOR, /\nif \(env === "prod" && !NA_BASE\) throw new BaseEmFaltaEmProducaoError\(\);\n/);
    assert.match(SERVIDOR, /\nconst NA_BASE = URL_DA_APP !== "";\n/);
  });
});
