/**
 * COM — anfitriao do registo de comercio Medusa 2.21.x; a sonda, as metricas e a
 * API interna.
 *
 * Anfitriao do Medusa 2.21.x (ADR-003). O arranque do Medusa depende do
 * spike KAM-041 e da porta CommerceRegistry do KAM-042; aqui a sonda, as
 * metricas do repo-base e as nove rotas `/internal/*`: sete do KAM-178 e duas do
 * painel do dono (KAM-099).
 *
 * Hono 4.13.x por decisão de `docs/tecnica/09` §3.1: o 5.0.0-rc.0 saiu a 2026-10-08 e
 * um *release candidate* não entra em produção (E4 §2.13).
 *
 * ## Três superfícies, e duas delas sem credencial
 *
 * ```text
 * GET  /healthz     sem credencial  a sonda do rolling deploy (KAM-001)
 * GET  /metrics     sem credencial  os dois contadores do repo-base (§3.39)
 * POST /internal/*  COM credencial  a API interna (x-kamba-interno + x-kamba-tenant)
 * ```
 *
 * A sonda não leva credencial porque uma sonda que precisa de segredo falha no
 * dia em que o segredo roda; o `/metrics` não leva porque o *scraper* não tem
 * segredo nosso e o que sai dali são duas contagens por filtro, sem
 * identificador nenhum.
 *
 * **As duas não estão protegidas por rede, e isso fica dito.** O código escuta
 * em `127.0.0.1` por omissão e só o `Dockerfile` põe `0.0.0.0`, mas o
 * `infra/compose/docker-compose.dev.yml` **publica** a porta do COM em
 * `127.0.0.1:${COM_PORT:-3002}`: em `dev`, qualquer processo da máquina de quem
 * desenvolve alcança as três. É por isso que o `/internal/*` tem credencial e
 * não só rede. A aplicação na rede é o **KAM-076**, como para o AGR.
 *
 * ## Sem a API interna montada, o `/internal/*` responde **503** e não 404
 *
 * Um 404 dizia a quem chama «essa rota não existe» — e ela existe, só não está
 * montada, o que é um defeito de arranque e não um pedido errado. O 503 é a
 * resposta que um *shim* ou um executor sabe repetir, e é *fail-closed*: nenhuma
 * operação corre. Em serviço isto não acontece, porque o `server.ts` aborta o
 * arranque sem os segredos obrigatórios (KAM-178, critério 6); o caminho existe
 * para que um `createApp()` sem dependências — o do teste da sonda — não sirva
 * uma superfície pela metade.
 */

import { Hono } from "hono";
import { healthz } from "@kamba/core-ts";
import type { Logger } from "@kamba/core-ts/logger";

import { SERVICE, VERSION } from "./meta.ts";
import {
  apiInterna,
  rotaDasMetricas,
  type DependenciasDaApi,
} from "./api/interna.ts";

export function createApp(log?: Logger, api?: DependenciasDaApi): Hono {
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

  app.route("/", rotaDasMetricas());

  if (api === undefined) {
    app.all("/internal/*", (c) => c.json({ error: "unavailable" }, 503));
    return app;
  }
  app.route("/", apiInterna(api));

  return app;
}
