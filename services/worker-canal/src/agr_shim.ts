/**
 * O processo que consome a fila `agr-inbound` e entrega ao AGR (KAM-025).
 *
 * É o quinto processo do `worker-canal`, ao lado do `server.ts`, do
 * `publicador.ts`, do `consumidor.ts` e do `entrada.ts`, e a razão de ser um
 * processo e não um módulo do servidor é a mesma dos outros: escala com
 * réplicas.
 *
 * ## O que faz, e o que deliberadamente não faz
 *
 * 1. Levanta um *worker* BullMQ sobre a fila `agr-inbound`, que o CHR enche
 *    (`@kamba/core-ts/chr/fila`).
 * 2. Por cada *job*: `POST /internal/turn` no AGR, com a credencial interna, e
 *    **espera pela resposta**. O estado HTTP decide se o *job* se repete; a
 *    tabela está em `services/agr/src/kamba_agr/api_interna.py`.
 * 3. Serve `/healthz` e `/metrics`, como os outros.
 *
 * **Não olha para dentro do *job*.** Não lê o `tenant_id`, não reconstrói o
 * `thread_id`, não decide com o `modo`. O contrato é do AGR
 * (`contexto.ler_invocacao`), e um segundo validador aqui era uma segunda
 * implementação a divergir. É por isso que este ficheiro não importa nada do
 * `chr/contrato.ts` além do nome da fila.
 *
 * **Não abre ligação nenhuma à base.** É a diferença entre este processo e os
 * outros quatro, e é a razão pela qual a concorrência aqui não é 1: ver
 * `@kamba/core-ts/agr`.
 *
 * ## Porque é que isto é um *shim* e não um consumidor Python
 *
 * `docs/adr/ADR-L004-fila-e-tranca-do-agr.md`, Decisão 1. Em duas linhas: o AGR
 * tem de saber correr um turno a partir de um pedido HTTP de qualquer forma (é
 * o critério 1 do KAM-025 e a retoma do `docs/tecnica/02` §11 regra 3), e a
 * alternativa — `bullmq` para Python, 3.3.1 — assentava numa compatibilidade de
 * protocolo com o `bullmq` TypeScript 6.3.11 que nenhum documento deste
 * conjunto mediu.
 *
 * ## A credencial lê-se a cada *job*, e não no arranque
 *
 * O `agr_internal_token` roda a 90 dias (`ops/secrets-inventory.yaml`). Um
 * valor lido uma vez ficava a levar 401 depois da rotação, e um 401 é
 * `UnrecoverableError` — isto é, o *job* morria em vez de esperar. O
 * `Secrets.arrancar` carrega e serve com TTL; a leitura por *job* é o que faz a
 * rotação não ter corte.
 */

import { serve } from "@hono/node-server";
import { healthz } from "@kamba/core-ts";
import {
  METRICA_FALHAS,
  METRICA_JOBS,
  METRICAS_DO_SHIM,
  VARIAVEL_DO_AGR,
  criarShimDoAgr,
} from "@kamba/core-ts/agr";
import { type Logger, instalar } from "@kamba/core-ts/logger";
import { EnvSecretProvider, Secrets, isAmbiente } from "@kamba/core-ts/secrets";
import { Hono } from "hono";

import { SERVICE, VERSION } from "./meta.ts";

/** A porta da sonda deste processo. Tem de coincidir com o compose. */
export const PORTA_POR_OMISSAO = 3025;

const VARIAVEL_DA_PORTA = "AGR_SHIM_PORT";
const VARIAVEL_DA_FILA = "KAMBA_REDIS_URL";

/** O `id` do segredo no inventário. O mesmo que o AGR verifica. */
export const SEGREDO_DA_API = "agr_internal_token";

function exigir(nome: string): string {
  const valor = process.env[nome]?.trim();
  if (valor === undefined || valor === "") {
    // Nomeia a variável e nunca o valor: é a regra de `db/ligacao.py` e do
    // `kamba_agr/ligacao.py`, e vale aqui pela mesma razão.
    throw new Error(`a variavel de ambiente ${nome} nao esta definida (ou esta vazia)`);
  }
  return valor;
}

function porta(): number {
  const bruto = process.env[VARIAVEL_DA_PORTA];
  if (bruto === undefined || bruto.trim() === "") return PORTA_POR_OMISSAO;
  const valor = Number(bruto);
  if (!Number.isInteger(valor) || valor <= 0 || valor > 65_535) {
    throw new Error(`${VARIAVEL_DA_PORTA} invalida`);
  }
  return valor;
}

export function criarApp(registo?: Logger): Hono {
  const app = new Hono();

  // Sem isto, o tratador de erro por omissão do Hono faz `console.error(err)`:
  // a mensagem e a pilha de qualquer erro iam em claro para o `stderr`, sem
  // passar pelo *logger* (KAM-068, `docs/logs.md` §3.3).
  app.onError((erro, c) => {
    registo?.excepcao(erro, "tratador_falhou");
    return c.json({ error: "internal" }, 500);
  });

  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  // Só as do *shim*. As do turno vivem no AGR, que é quem as mede: repetir-lhes
  // o nome aqui dava duas séries a contar a mesma coisa de dois sítios.
  app.get("/metrics", (c) =>
    c.text(METRICAS_DO_SHIM.exposicao(), 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
}

async function principal(): Promise<void> {
  // Antes de tudo o resto: a partir daqui, um erro por tratar sai como uma
  // linha sem conteúdo, e não como a pilha no `stderr` (KAM-068).
  const log = instalar(SERVICE);

  const urlDaFila = exigir(VARIAVEL_DA_FILA);
  const urlDoAgr = exigir(VARIAVEL_DO_AGR).replace(/\/+$/, "");

  const ambienteBruto = process.env.KAMBA_ENV?.trim() ?? "dev";
  if (!isAmbiente(ambienteBruto)) {
    // Um valor desconhecido **não** cai em `dev`: a lição do `chaves.ts` do
    // KAM-008. Um `KAMBA_ENV=producao` a servir segredos de `dev` é pior do
    // que não arrancar.
    throw new Error("KAMBA_ENV fora de dev/staging/prod");
  }
  const secrets = await Secrets.arrancar({
    servico: SERVICE,
    provider: new EnvSecretProvider({ ambiente: ambienteBruto }),
    obrigatorios: [SEGREDO_DA_API],
  });

  const shim = criarShimDoAgr({
    url: urlDaFila,
    agr: urlDoAgr,
    credencial: () => secrets.get(SEGREDO_DA_API),
    aoTratar: (desfecho) => {
      METRICAS_DO_SHIM.contar(METRICA_JOBS, desfecho);
      // O desfecho é lista fechada e cabe no `outcome` da *allowlist* do
      // `docs/tecnica/08` §7.3. O `wamid` **não** sai: carrega o número do
      // interlocutor em base64 (`docs/logs.md` §2.1).
      log.info({ outcome: desfecho });
    },
    aoFalhar: (erro) => {
      METRICAS_DO_SHIM.contar(METRICA_FALHAS);
      log.excepcao(erro, "agr_shim");
    },
  });

  // `hostname` explícito, e não a omissão do Node — que é `::`/`0.0.0.0`.
  // `specs/01` §6 princípio 7 e o DoD do KAM-001, «nada além de localhost».
  const servidor = serve({
    fetch: criarApp(log).fetch,
    hostname: process.env.HOST?.trim() || "127.0.0.1",
    port: porta(),
  });
  log.info({ outcome: "service_started" });

  const paragem = new AbortController();
  for (const sinal of ["SIGTERM", "SIGINT"] as const) {
    process.on(sinal, () => paragem.abort());
  }
  await new Promise<void>((resolver) => {
    paragem.signal.addEventListener("abort", () => resolver(), { once: true });
  });

  // O *worker* primeiro: fechar o servidor debaixo de um *job* a correr não o
  // interrompia, mas fechar a ligação à fila sim. É a mesma ordem do
  // `entrada.ts`, e pela mesma razão.
  await shim.fechar();
  servidor.close();
}

if (import.meta.main) {
  await principal();
}
