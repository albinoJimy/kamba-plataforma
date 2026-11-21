/**
 * O consumidor `dono` (KAM-215): `onboarding-provisionamento` no compose.
 *
 *     node services/onboarding-web/src/provisionamento.ts
 *
 * O contacto `dono` nasce do `tenant.provisioned`: o telefone verificado do caso
 * decifra-se com a `kek_telefone_do_caso`, resolve-se no contacto do tenant e
 * passa a dono pela `platform.definir_dono(…, 'provisionamento')`. É um terceiro
 * processo da imagem do `onboarding-web`, ao lado do `server.ts` e do
 * `lote.ts`, e não um módulo do lote: a decisão do fundador de 2026-11-20 dá a
 * KEK do telefone ao `onboarding-web` e a este processo, e o lote corre como
 * `kamba_batch`, que lia o telefone de qualquer tenant.
 *
 * Esta é a casca: abre as ligações, verifica os papéis, lê os segredos, serve a
 * porta e levanta os *workers*. A composição está em `./provisionamento/processo.ts`.
 *
 *     GET /healthz    a mesma carga útil dos outros processos
 *     GET /metrics    as do consumo (KAM-006) e as da guarda de tenant
 *
 * Na porta `PROVISIONAMENTO_PORT` (3015 por omissão), em `127.0.0.1` por
 * omissão — é o `Dockerfile` que põe `HOST=0.0.0.0`.
 */

import { serve } from "@hono/node-server";
import { provisionamentoPelaBase } from "@kamba/core-ts/dono";
import { EnvKeyProvider, Identidade } from "@kamba/core-ts/identity";
import { lerAnelDoTelefone } from "@kamba/core-ts/inscricao";
import { instalar } from "@kamba/core-ts/logger";
import { EnvSecretProvider, Secrets } from "@kamba/core-ts/secrets";
import pg from "pg";

import { SERVICE } from "./meta.ts";
import {
  SEGREDOS_DO_PROVISIONAMENTO,
  consumidorDoDono,
  criarApp,
  lerConfiguracao,
  verificarPapeis,
} from "./provisionamento/processo.ts";

const log = instalar(SERVICE);

async function principal(): Promise<void> {
  const config = lerConfiguracao(process.env);
  const app = new pg.Pool({ connectionString: config.urlDaApp, max: 2, application_name: "onboarding-provisionamento:app" });
  const identidadeBd = new pg.Pool({
    connectionString: config.urlDaIdentidade,
    max: 4,
    application_name: "onboarding-provisionamento:identidade",
  });
  for (const conjunto of [app, identidadeBd]) {
    conjunto.on("error", (erro: Error & { code?: string }) =>
      log.warn({ outcome: "ligacao_perdida", error_code: erro.code ?? erro.name }),
    );
  }
  let arrancou = false;
  try {
    await verificarPapeis(app, identidadeBd);
    // A do `kamba_app` só servia a verificação: o consumo abre as suas, uma por
    // fila, com a mesma cadeia.
    await app.end();
    const secrets = await Secrets.arrancar({
      servico: SERVICE,
      provider: new EnvSecretProvider({ ambiente: config.ambiente }),
      obrigatorios: [...SEGREDOS_DO_PROVISIONAMENTO],
    });
    const anel = await lerAnelDoTelefone(secrets);
    const identidade = await Identidade.arrancar({ chaves: new EnvKeyProvider({ ambiente: config.ambiente }) });
    const efeito = provisionamentoPelaBase({ anel, identidade, pool: identidadeBd });

    const servidor = await new Promise<ReturnType<typeof serve>>((aberto, falhou) => {
      const s = serve(
        { fetch: criarApp().fetch, hostname: process.env.HOST?.trim() || "127.0.0.1", port: config.porta },
        () => aberto(s),
      );
      s.once("error", (erro: Error & { code?: string }) => {
        log.error({ outcome: "porta_falhou", error_code: erro.code ?? erro.name });
        falhou(erro);
      });
    });
    // O `bullmq` carrega-se com a porta já aberta (a razão do `lote.ts`).
    const { criarTrabalhadores } = await import("@kamba/core-ts/eventos/trabalhador_bullmq");
    const consumo = consumidorDoDono({ urlDaApp: config.urlDaApp, urlDaFila: config.urlDaFila, efeito, log, criar: criarTrabalhadores });
    arrancou = true;
    log.info({ outcome: "service_started" });
    await new Promise<void>((resolver) => {
      for (const sinal of ["SIGTERM", "SIGINT"] as const) process.once(sinal, () => resolver());
    });
    log.info({ outcome: "service_stopping" });
    await Promise.race([
      consumo.fechar().catch(() => {}),
      new Promise<void>((pronto) => setTimeout(pronto, 10_000).unref()),
    ]);
    servidor.close();
  } finally {
    await Promise.allSettled([app.end(), identidadeBd.end()]);
    if (arrancou) log.info({ outcome: "service_stopped" });
  }
}

if (import.meta.main) {
  principal()
    .catch((erro: unknown) => {
      log.excepcao(erro, "arranque_falhou");
      process.exitCode = 1;
    })
    .finally(() => process.exit());
}
