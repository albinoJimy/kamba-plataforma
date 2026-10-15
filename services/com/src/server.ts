/**
 * Arranque do com.
 *
 * Escuta em `127.0.0.1` por omissão. Dentro de um contentor é preciso escutar em
 * `0.0.0.0` para que a rede do compose chegue ao processo, e é por isso que o
 * `Dockerfile` define `HOST=0.0.0.0` — mas nunca o faz o código por si, para que
 * correr o serviço à mão na máquina de alguém não abra uma porta na rede local
 * (`specs/01` §6, princípio 7, e o DoD do KAM-001: nada além de localhost).
 */

import { serve } from "@hono/node-server";
import { port } from "@kamba/core-ts";
import { instalar } from "@kamba/core-ts/logger";

import { createApp } from "./app.ts";
import { DEFAULT_PORT, SERVICE } from "./meta.ts";

// Antes de tudo o resto: a partir daqui, um erro por tratar — incluindo uma
// `PORT` inválida, duas linhas abaixo — sai como uma linha sem conteúdo, e não
// como a pilha com a mensagem no `stderr` (KAM-068, `docs/logs.md`).
const log = instalar(SERVICE);

const hostname = process.env.HOST?.trim() || "127.0.0.1";
const listenPort = port(DEFAULT_PORT);

serve({ fetch: createApp(log).fetch, hostname, port: listenPort }, () => {
  // O anfitrião e a porta não estão na *allowlist* de `docs/tecnica/08` §7.3,
  // e por isso não saem: quem os quer saber lê a configuração do contentor.
  log.info({ outcome: "service_started" });
});
