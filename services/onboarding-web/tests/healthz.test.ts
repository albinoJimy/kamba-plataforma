/**
 * A sonda do onboarding-web responde o que o contrato diz (`packages/contracts`).
 *
 * Usa o executor de testes do Node (`node --test`): zero dependências a fixar e
 * a bloquear, o que para um esqueleto é a escolha certa (ver
 * `docs/adr/ADR-L001-toolchain.md`).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { HealthzResponseV1 } from "@kamba/contracts";
import { Logger } from "@kamba/core-ts/logger";

import { createApp } from "../src/app.ts";
import { SERVICE } from "../src/meta.ts";

/**
 * `Response.json()` devolve `unknown`, e é isso que se quer: a resposta vem de
 * fora do tipo. Afirma-se o tipo do contrato **depois** de verificar o estado,
 * e os testes abaixo confirmam campo a campo que a afirmação se sustenta.
 */
async function sonda(path = "/healthz") {
  const response = await createApp().request(path);
  return response;
}

test("GET /healthz responde 200 com serviço, versão e commit", async () => {
  const response = await sonda();
  assert.equal(response.status, 200);

  const body = (await response.json()) as HealthzResponseV1;
  assert.equal(body.status, "ok");
  assert.equal(body.service, SERVICE);
  assert.match(body.version, /^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$/);
  assert.match(body.commit, /^(?:[0-9a-f]{40}|[0-9a-f]{7,12}|unknown)$/);
  assert.deepEqual(Object.keys(body).sort(), [
    "commit",
    "service",
    "status",
    "version",
  ]);
});

test("o SHA do commit vem do ambiente quando o CI o injecta", async () => {
  const previous = process.env.KAMBA_COMMIT_SHA;
  process.env.KAMBA_COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567";
  try {
    const body = (await (await sonda()).json()) as HealthzResponseV1;
    assert.equal(body.commit, "0123456789abcdef0123456789abcdef01234567");
  } finally {
    if (previous === undefined) delete process.env.KAMBA_COMMIT_SHA;
    else process.env.KAMBA_COMMIT_SHA = previous;
  }
});

test("uma rota desconhecida não responde 200", async () => {
  for (const path of ["/", "/healthz/", "/metrics", "/admin"]) {
    const response = await sonda(path);
    assert.notEqual(response.status, 200, `${path} devia recusar`);
  }
});

// --- KAM-068: o erro de um tratador não sai pela consola ---------------------
//
// O tratador de erro por omissão do Hono faz `console.error(err)`: a mensagem e
// a pilha de qualquer erro de um tratador iam em claro para o `stderr`, ao lado
// do *logger* e sem passar por ele (revisão adversarial do KAM-068, A1).

test("um erro num tratador sai pelo logger, sem mensagem nem pilha", async (t) => {
  const canario = "payload invalido de +244 923 456 789: queria duas pizzas";
  const consola: unknown[][] = [];
  for (const metodo of ["error", "log", "warn", "info"] as const) {
    t.mock.method(console, metodo, (...argumentos: unknown[]) => {
      consola.push(argumentos);
    });
  }
  let escrito = "";
  const log = new Logger(SERVICE, {
    destino: { write: (pedaco: string) => (escrito += pedaco) },
    relogio: () => new Date("2026-01-01T00:00:00.000Z"),
    estrito: true,
  });
  const app = createApp(log);
  app.get("/rebenta", () => {
    throw new RangeError(canario);
  });

  const response = await app.request("/rebenta");
  const corpo = await response.text();
  t.mock.restoreAll();

  assert.equal(response.status, 500);
  assert.deepEqual(JSON.parse(corpo), { error: "internal" });
  assert.deepEqual(consola, []);
  assert.equal(
    escrito,
    `{"ts":"2026-01-01T00:00:00.000Z","level":"error","svc":"${SERVICE}","error_code":"tratador_falhou:RangeError"}\n`,
  );
  for (const texto of [escrito, corpo]) {
    assert.ok(!texto.includes("923"));
    assert.ok(!texto.includes("pizzas"));
  }
});

test("sem logger, o erro de um tratador continua a não ir para a consola", async (t) => {
  const consola: unknown[][] = [];
  t.mock.method(console, "error", (...argumentos: unknown[]) => {
    consola.push(argumentos);
  });
  const app = createApp();
  app.get("/rebenta", () => {
    throw new Error("923456789");
  });
  const response = await app.request("/rebenta");
  t.mock.restoreAll();
  assert.equal(response.status, 500);
  assert.deepEqual(consola, []);
});
