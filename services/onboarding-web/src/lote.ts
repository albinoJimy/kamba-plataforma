/**
 * Processo de lote do onboarding (KAM-198): `onboarding-lote` no compose.
 *
 *     node services/onboarding-web/src/lote.ts
 *
 * É um **segundo processo** da imagem do `onboarding-web`, como os quatro do
 * `worker-canal` (KAM-187), e não um serviço novo: partilha o pacote, o
 * `Dockerfile` e o `@kamba/core-ts/revisao`, e um serviço novo pagava manifesto,
 * imagem e entrada no `make smoke` para correr o mesmo módulo. Corre o ciclo da
 * fila de revisão com credenciais de lote, serve as métricas dela, e é onde o
 * KAM-092 liga o `amostrar` e a reconciliação da saga (KAM-091) vai correr.
 *
 * Esta é a casca: abre as duas ligações, verifica os papéis, serve a porta e
 * agenda o ciclo. Tudo o que pode errar em silêncio está em `./lote/processo.ts`,
 * com bateria própria.
 *
 * ## O que serve em HTTP
 *
 *     GET /healthz    a mesma carga útil dos outros processos
 *     GET /metrics    as quatro séries do dicionário §3.61
 *
 * Na porta `LOTE_PORT` (3014 por omissão) e em `127.0.0.1` por omissão: é o
 * `Dockerfile` que põe `HOST=0.0.0.0`, nunca o código.
 *
 * ## Arranca em `prod`, e não arranca sem as credenciais
 *
 * Ao contrário do `server.ts`, que recusa `prod` por correr sobre repositórios em
 * memória, este processo corre sobre os adaptadores SQL e arranca em `prod`. Sem
 * a `KAMBA_LOTE_DB_URL` ou a `KAMBA_LOTE_APP_DB_URL`, ou com uma delas de outro
 * papel, **não arranca** — sai com código 1 antes de abrir a porta.
 */

import { serve } from "@hono/node-server";
import { instalar } from "@kamba/core-ts/logger";
import pg from "pg";

import { SERVICE } from "./meta.ts";
import {
  criarApp,
  efeitosDoLote,
  lerConfiguracao,
  montarProcesso,
  registarVolta,
  verificarPapeis,
} from "./lote/processo.ts";

const log = instalar(SERVICE);

async function principal(): Promise<void> {
  const config = lerConfiguracao(process.env);
  // `max: 4` no lote: uma volta corre em série, e o trinco da quota empresta uma
  // ligação de cada vez. A da `app` só serve o screening.
  const lote = new pg.Pool({ connectionString: config.urlDoLote, max: 4 });
  const app = new pg.Pool({ connectionString: config.urlDaApp, max: 2 });
  try {
    await verificarPapeis(lote, app);
    const processo = montarProcesso({
      lote,
      app,
      efeitos: efeitosDoLote(lote),
      log,
      inicioDaAmostragem: config.inicioDaAmostragem,
    });
    const servidor = serve({
      fetch: criarApp(processo.ciclo.metricas).fetch,
      hostname: process.env.HOST?.trim() || "127.0.0.1",
      port: config.porta,
    });
    const parar = processo.ciclo.agendar(config.intervaloMs, (r) => registarVolta(log, r));
    // A primeira volta já, e não daqui a um intervalo: as métricas sairiam a
    // zero durante um minuto inteiro depois de cada arranque.
    void processo.ciclo.correr().then((r) => registarVolta(log, r));
    log.info({ outcome: "service_started" });
    await new Promise<void>((resolver) => {
      for (const sinal of ["SIGTERM", "SIGINT"] as const) process.once(sinal, () => resolver());
    });
    log.info({ outcome: "service_stopping" });
    parar();
    servidor.close();
  } finally {
    await Promise.allSettled([lote.end(), app.end()]);
    log.info({ outcome: "service_stopped" });
  }
}

// `import.meta.main` (Node 24): o módulo também é importado pelos testes, e
// então não arranca nada.
if (import.meta.main) {
  principal().catch((erro: unknown) => {
    log.excepcao(erro, "arranque_falhou");
    process.exitCode = 1;
  });
}
