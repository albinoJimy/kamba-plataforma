/**
 * Worker de canal — a sonda do `server.ts`, e mais nada.
 *
 * **Isto nao consome fila nenhuma.** Quem consome o que o GWY poe na
 * `wa-inbound` e o `entrada.ts` (KAM-013); a `agr-inbound`, o `agr_shim.ts`
 * (KAM-025); o *outbox*, o `publicador.ts` (KAM-005); e as particoes, o
 * `consumidor.ts` (KAM-006). Cada um e um servico proprio do compose desde o
 * KAM-187, e cada um serve o seu `/healthz`. O `server.ts` ficou como o `CMD`
 * por omissao da imagem e nao corre em compose nenhum: a regra
 * `consumidor-sem-comando` do `compose_prod` recusa um servico desta imagem sem
 * `command:`.
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
