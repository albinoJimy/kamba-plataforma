/**
 * Processo do publicador de eventos (KAM-005).
 *
 * É um **segundo processo** do `worker-canal`, e não um serviço novo. A escolha
 * é a que o ticket deixa aberta («processo de `services/worker-canal` ou serviço
 * próprio `services/evt-publisher`») e as razões estão em `docs/eventos.md` §6;
 * a curta é: o publicador partilha a configuração de base de dados e de fila do
 * worker, e um serviço novo pagava manifesto, imagem, egressos e entrada no
 * `make smoke` para correr o mesmo laço.
 *
 *     node src/publicador.ts
 *
 * Escala **para cima** com réplicas em espera, não com concorrência: só o
 * processo que ganha `pg_try_advisory_lock(7101)` publica. É por isso que não
 * vive no mesmo processo que o consumidor da fila de entrada (`server.ts`), que
 * escala horizontalmente — N réplicas do consumidor dariam N-1 publicadores a
 * dormir dentro de processos que têm trabalho a fazer.
 *
 * ## O que serve em HTTP
 *
 *     GET /healthz    a mesma carga útil dos outros serviços
 *     GET /metrics    as métricas do critério 8, formato do Prometheus
 *
 * Numa porta própria (`PUBLICADOR_PORT`, por omissão 3011) e em `127.0.0.1` por
 * omissão, como o `server.ts`: é o `Dockerfile` que põe `HOST=0.0.0.0`, nunca o
 * código. O `/metrics` fica **aqui** e não no `server.ts`: os serviços têm um
 * teste que exige 404 em `/metrics` (KAM-001), e abrir lá a rota mudava um
 * contrato de outro ticket por conveniência deste.
 *
 * ## Ligações
 *
 * Uma ligação **dedicada** ao PostgreSQL, não um *pool*: o lock consultivo é de
 * sessão e tem de sobreviver às transacções do laço. O `pg` entra como
 * dependência de execução deste serviço (era só de desenvolvimento em
 * `packages/core-ts`, onde serve os testes).
 */

import { serve } from "@hono/node-server";
import { healthz } from "@kamba/core-ts";
import { METRICAS, Publicador } from "@kamba/core-ts/eventos";
import { FilasBullmq } from "@kamba/core-ts/eventos/filas_bullmq";
import { instalar } from "@kamba/core-ts/logger";
import { Hono } from "hono";
import { Client } from "pg";

import { SERVICE, VERSION } from "./meta.ts";

/** Porta da sonda e das métricas do publicador. */
export const PORTA_POR_OMISSAO = 3011;

/** O `pg` aceita `connectionString`; a palavra-passe vem do cofre (KAM-010). */
const VARIAVEL_DA_BASE = "KAMBA_PUBLICADOR_DB_URL";
/** `redis://…` do Redis-compatível. A fila chama-se `queue` (D12 em aberto). */
const VARIAVEL_DA_FILA = "KAMBA_QUEUE_URL";

const log = instalar(SERVICE);

function exigir(nome: string): string {
  const valor = (process.env[nome] ?? "").trim();
  if (valor === "") {
    // Arrancar sem saber a que base ou a que fila se liga é pior do que não
    // arrancar (`specs/01` §6, princípio 7). O valor nunca entra no erro.
    throw new Error(`${nome} em falta: o publicador nao arranca as cegas`);
  }
  return valor;
}

function porta(): number {
  const bruto = (process.env.PUBLICADOR_PORT ?? "").trim();
  if (bruto === "") return PORTA_POR_OMISSAO;
  const numero = Number(bruto);
  if (!Number.isInteger(numero) || numero < 1 || numero > 65535) {
    throw new Error(`PUBLICADOR_PORT invalida: ${JSON.stringify(bruto)}`);
  }
  return numero;
}

/** A aplicação HTTP do publicador: sonda e métricas, e mais nada. */
export function criarApp(): Hono {
  const app = new Hono();
  app.onError((erro, c) => {
    log.excepcao(erro, "tratador_falhou");
    return c.json({ error: "internal" }, 500);
  });
  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  app.get("/metrics", (c) =>
    c.text(METRICAS.exposicao(), 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
}

async function principal(): Promise<void> {
  const bd = new Client({ connectionString: exigir(VARIAVEL_DA_BASE) });
  await bd.connect();
  const filas = new FilasBullmq({ url: exigir(VARIAVEL_DA_FILA) });
  const publicador = new Publicador({ bd, filas, metricas: METRICAS, log });

  const paragem = new AbortController();
  // `SIGTERM` é o que o orquestrador manda; `SIGINT` é o Ctrl-C. Os dois pedem
  // o encerramento limpo, que larga o lock e deixa a réplica assumir sem
  // esperar pelo tempo de detecção de ligação morta.
  for (const sinal of ["SIGTERM", "SIGINT"] as const) {
    process.on(sinal, () => {
      log.info({ outcome: "service_stopping" });
      paragem.abort();
    });
  }

  // `NOTIFY evt_novo` acorda o laço antes dos 200 ms (`docs/tecnica/06` §6.2). O
  // `LISTEN` é pedido pelo publicador ao ganhar a liderança; o que falta é ouvir
  // — e ouvir é do *driver*, por isso é aqui.
  bd.on("notification", (aviso) => {
    if (aviso.channel === "evt_novo") log.debug({ outcome: "evt_novo" });
  });

  const servidor = serve({
    fetch: criarApp().fetch,
    hostname: process.env.HOST?.trim() || "127.0.0.1",
    port: porta(),
  });

  log.info({ outcome: "service_started" });
  try {
    await publicador.correr(paragem.signal);
  } finally {
    servidor.close();
    await filas.fechar();
    await bd.end();
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
