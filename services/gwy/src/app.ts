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

  if (dependencias !== undefined) montarWebhook(app, dependencias, log);

  return app;
}

/**
 * As métricas, **noutra porta**, e a razão é a revisão adversarial.
 *
 * O `/metrics` esteve no mesmo `Hono` que o `/wa/webhook`, e isso punha-o na
 * porta pública: o webhook é por definição alcançável de fora (ADR-001), e
 * qualquer pessoa que lhe chegasse lia `inbound_queue_depth` — o atraso da
 * plataforma em tempo real —, `gwy_requests_total` e `gwy_sig_fail`. Com a
 * profundidade visível, quem quisesse provocar o descarte do critério 7 sabia
 * exactamente quando a fila passara os 10 000.
 *
 * Os outros processos do conjunto servem o `/metrics` em portas internas
 * (3011, 3012, 3013) e este passa a fazer o mesmo. Não é defesa suficiente por
 * si — a porta interna também é uma porta —, mas é a diferença entre «exposto
 * a quem alcança a Internet» e «exposto a quem alcança a rede interna», e é a
 * que está nas mãos deste ticket. Fechar a rede é KAM-077.
 */
export function criarAppDeMetricas(log?: Logger): Hono {
  const app = new Hono();

  // **O mesmo `onError` da app pública, e não é zelo.** Sem ele, o tratador por
  // omissão do Hono faz `console.error(err)`: a mensagem e a pilha de qualquer
  // erro nesta app iam em claro para o `stderr`, sem passar pelo *logger*
  // (KAM-068, `docs/logs.md` §3.3). Uma app nova sem `onError` é a mesma
  // omissão que o `createApp` acima existe para fechar — e foi o que eu deixei
  // aqui quando separei as portas. O `log_policy` passou a contar as duas
  // coisas (`tools/log_policy/tests/test_cablagem.py`) para que não volte.
  app.onError((erro, c) => {
    log?.excepcao(erro, "tratador_falhou");
    return c.json({ error: "internal" }, 500);
  });

  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  // **Não leva dados de tenant nem identificadores** — as cinco métricas são
  // contadores e *gauges* sem etiquetas (`entrada/metricas.ts`).
  app.get("/metrics", (c) =>
    c.text(METRICAS.exposicao(), 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
}
