/**
 * GWY — unico endpoint de webhook da Meta (ADR-001); esqueleto
 *
 * Todo o trafego externo entra por aqui. No KAM-001 so existe a sonda:
 * a verificacao de assinatura, a deduplicacao e a fila sao o KAM-013.
 *
 * Hono 4.13.x por decisão de `docs/tecnica/09` §3.1: o 5.0.0-rc.0 saiu a 2026-10-08 e
 * um *release candidate* não entra em produção (E4 §2.13).
 */

import { Hono } from "hono";
import { healthz } from "@kamba/core-ts";
import type { Logger } from "@kamba/core-ts/logger";

import { SERVICE, VERSION } from "./meta.ts";

export function createApp(log?: Logger): Hono {
  const app = new Hono();

  // Sem isto, o tratador de erro por omissão do Hono faz `console.error(err)`:
  // a mensagem e a pilha de qualquer erro de um tratador iam em claro para o
  // `stderr`, sem passar pelo *logger* (KAM-068, `docs/logs.md` §3.3). Sai o
  // código e a classe, e a resposta não diz o que falhou.
  app.onError((erro, c) => {
    log?.excepcao(erro, "tratador_falhou");
    return c.json({ error: "internal" }, 500);
  });

  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));

  return app;
}
