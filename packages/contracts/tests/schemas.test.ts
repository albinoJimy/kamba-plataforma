/**
 * Os esquemas publicados são JSON válido e descrevem o que os consumidores usam.
 *
 * Validação estrutural leve, sem validador de JSON Schema: a validação a sério
 * corre em `tools/healthz_check.py`, contra o serviço a responder. Aqui só se
 * guarda que o ficheiro não se estragou e que os tipos de TS não divergiram dele.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { HEALTHZ_RESPONSE_V1_PATH, SERVICES } from "../src/index.ts";

const schema = JSON.parse(readFileSync(HEALTHZ_RESPONSE_V1_PATH, "utf8"));

test("o esquema de /healthz tem os campos obrigatórios", () => {
  assert.deepEqual(
    [...schema.required].sort(),
    ["commit", "service", "status", "version"],
  );
  assert.equal(schema.additionalProperties, false);
  assert.equal(schema.properties.status.const, "ok");
});

test("a lista de serviços do esquema é a mesma do código", () => {
  // Se divergirem, um serviço novo responde /healthz e o contrato rejeita-o.
  assert.deepEqual([...schema.properties.service.enum].sort(), [...SERVICES].sort());
});

test("o padrão de commit aceita SHA e 'unknown', e recusa lixo", () => {
  const pattern = new RegExp(schema.properties.commit.pattern);
  for (const valor of ["unknown", "a1b2c3d", "0123456789abcdef0123456789abcdef01234567"]) {
    assert.ok(pattern.test(valor), `devia aceitar ${valor}`);
  }
  for (const valor of ["", "ABC1234", "não-é-um-sha", "123456"]) {
    assert.ok(!pattern.test(valor), `devia recusar ${valor}`);
  }
});

test("o padrão de versão é SemVer", () => {
  const pattern = new RegExp(schema.properties.version.pattern);
  for (const valor of ["0.1.0", "1.2.3", "1.0.0-rc.1"]) {
    assert.ok(pattern.test(valor), `devia aceitar ${valor}`);
  }
  for (const valor of ["1.2", "v1.2.3", "latest", ""]) {
    assert.ok(!pattern.test(valor), `devia recusar ${valor}`);
  }
});
