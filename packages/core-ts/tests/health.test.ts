/** O núcleo partilhado produz a carga útil que o contrato descreve. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { COMMIT_ENV, commitSha, healthz, port } from "../src/index.ts";

test("commitSha aceita SHA completo e curto, e normaliza maiúsculas", () => {
  const sha = "0123456789abcdef0123456789abcdef01234567";
  assert.equal(commitSha({ [COMMIT_ENV]: sha }), sha);
  assert.equal(commitSha({ [COMMIT_ENV]: "abc1234" }), "abc1234");
  assert.equal(commitSha({ [COMMIT_ENV]: "ABC1234" }), "abc1234");
});

test("commitSha dá 'unknown' em vez de falhar", () => {
  // Fail-soft deliberado: a sonda de vivacidade não cai por metadados maus.
  for (const valor of ["", "   ", "não-é-um-sha", "123456"]) {
    assert.equal(commitSha({ [COMMIT_ENV]: valor }), "unknown");
  }
  assert.equal(commitSha({}), "unknown");
});

test("healthz devolve exactamente os quatro campos do contrato", () => {
  const payload = healthz("gwy", "1.2.3", {});
  assert.deepEqual(Object.keys(payload).sort(), [
    "commit",
    "service",
    "status",
    "version",
  ]);
  assert.deepEqual(payload, {
    status: "ok",
    service: "gwy",
    version: "1.2.3",
    commit: "unknown",
  });
});

test("port usa o fallback quando PORT não está definida", () => {
  assert.equal(port(3000, {}), 3000);
  assert.equal(port(3000, { PORT: "" }), 3000);
  assert.equal(port(3000, { PORT: "8080" }), 8080);
});

test("port falha em voz alta com um valor inválido", () => {
  // Ao contrário do SHA, uma porta errada não é um metadado: é escutar no sítio
  // errado, e isso é pior do que não arrancar.
  for (const valor of ["0", "-1", "65536", "abc", "3000.5"]) {
    assert.throws(() => port(3000, { PORT: valor }), /PORT inválida/);
  }
});
