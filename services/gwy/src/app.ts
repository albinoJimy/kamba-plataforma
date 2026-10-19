/**
 * GWY — unico endpoint de webhook da Meta (ADR-001)
 *
 * Todo o trafego externo entra por aqui. O KAM-001 deixou so a sonda; o
 * KAM-013 poe-lhe o webhook: a verificacao, a assinatura sobre o corpo bruto, a
 * deduplicacao e a fila vivem em `webhook.ts`.
 *
 * Hono 4.13.x por decisão de `docs/tecnica/09` §3.1: o 5.0.0-rc.0 saiu a 2026-10-08 e
 * um *release candidate* não entra em produção (E4 §2.13).
 */

import { Hono } from "hono";
import { healthz } from "@kamba/core-ts";
import { METRICAS } from "@kamba/core-ts/entrada";
import type { Logger } from "@kamba/core-ts/logger";

import { SERVICE, VERSION } from "./meta.ts";
import { type DependenciasDoWebhook, montarWebhook } from "./webhook.ts";

/**
 * Monta o serviço.
 *
 * `dependencias` é opcional e isso não é comodidade: os testes da sonda e do
 * KAM-068 não precisam de fila nem de segredos, e exigir-lhos obrigava-os a
 * montar um GWY inteiro para provar que `/healthz` responde. Sem elas, o
 * webhook não é montado — e **isso é visível**: o `POST /wa/webhook` responde
 * 404, não 200. Um GWY sem segredo que aceitasse pedidos era o defeito que o
 * `Secrets.arrancar` em `prod` existe para impedir.
 */
export function createApp(log?: Logger, dependencias?: DependenciasDoWebhook): Hono {
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

  // `/metrics` passa a existir no gwy com o KAM-013, e até aqui não existia —
  // o `publicador.ts` do `worker-canal` registou por escrito que não o
  // expunha no gwy porque o teste da sonda afirmava que não respondia 200.
  // O DoD deste ticket pede as métricas do GWY «desde o código», e métricas
  // que nada expõe não são observabilidade: o teste foi alterado com a rota.
  // **Não leva dados de tenant nem identificadores** — as cinco métricas são
  // contadores e *gauges* sem etiquetas (`entrada/metricas.ts`).
  app.get("/metrics", (c) =>
    c.text(METRICAS.exposicao(), 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );

  if (dependencias !== undefined) montarWebhook(app, dependencias, log);

  return app;
}
