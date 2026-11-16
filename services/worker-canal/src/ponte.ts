/**
 * O processo da ponte fila → consumidor Python (KAM-194).
 *
 * É o sexto processo do `worker-canal`, ao lado do `server.ts`, do
 * `publicador.ts`, do `consumidor.ts`, do `entrada.ts` e do `agr_shim.ts`, e a
 * razão de ser um processo e não um módulo do servidor é a mesma dos outros:
 * escala com réplicas. O molde é o `agr_shim.ts`, linha a linha.
 *
 * ## O que faz, e o que deliberadamente não faz
 *
 * 1. Levanta um *worker* BullMQ por partição `evt.<consumer>.p<0..15>` de cada
 *    consumidor de `KAMBA_PONTE_CONSUMERS`, que o publicador do EVT enche.
 * 2. Por cada *job*: `POST /internal/event` em `KAMBA_PONTE_ALVO`, com a
 *    credencial interna, e **espera pela resposta**. O estado HTTP decide se o
 *    *job* se repete; a tabela está em `@kamba/core-ts/eventos/ponte`.
 * 3. Serve `/healthz` e `/metrics`, como os outros.
 *
 * **Não abre ligação nenhuma à base e não marca `events_consumed`.** É a
 * diferença entre este processo e o `consumidor.ts`: aquele corre o `consumir`
 * em TypeScript e marca o evento, e um consumidor Python atrás dele via-o
 * sempre como `duplicado`. A decisão toda — marca, ordem, DLQ — fica do lado
 * Python.
 *
 * **Não olha para dentro do envelope e não regista o corpo.** O que vai a
 * registo é o desfecho e o estado HTTP; nunca o `event_id`, o `tenant_id` nem o
 * envelope.
 *
 * ## Um processo por alvo
 *
 * O AGR e o IDX são dois alvos, com dois segredos: uma réplica serve **um**
 * alvo (`KAMBA_PONTE_ALVO`) e apresenta **um** segredo (`KAMBA_PONTE_SEGREDO`),
 * e os consumidores que lhe cabem vão em `KAMBA_PONTE_CONSUMERS`. O compose
 * levanta uma por alvo.
 *
 * ## A credencial lê-se a cada *job*, e não no arranque
 *
 * O segredo roda (`ops/secrets-inventory.yaml`). Um valor lido uma vez ficava a
 * levar 401 depois da rotação, e um 401 é `UnrecoverableError` — o *job*
 * morria em vez de esperar. O `Secrets.arrancar` carrega e serve com TTL; a
 * leitura por *job* é o que faz a rotação não ter corte.
 */

import { serve } from "@hono/node-server";
import { healthz } from "@kamba/core-ts";
import { METRICAS_DA_PONTE } from "@kamba/core-ts/eventos";
import { codigoDaFalha, desfechoDaFalha } from "@kamba/core-ts/eventos/ponte";
import { criarPonte } from "@kamba/core-ts/eventos/ponte_bullmq";
import { type Logger, instalar } from "@kamba/core-ts/logger";
import { type Ambiente, EnvSecretProvider, Secrets, isAmbiente } from "@kamba/core-ts/secrets";
import { Hono } from "hono";

import { SERVICE, VERSION } from "./meta.ts";

/** A porta da sonda deste processo. Tem de coincidir com o compose. */
export const PORTA_POR_OMISSAO = 3194;

export const VARIAVEL_DA_PORTA = "PONTE_PORT";
export const VARIAVEL_DA_FILA = "KAMBA_REDIS_URL";
export const VARIAVEL_DOS_CONSUMIDORES = "KAMBA_PONTE_CONSUMERS";
export const VARIAVEL_DO_ALVO = "KAMBA_PONTE_ALVO";
export const VARIAVEL_DO_SEGREDO = "KAMBA_PONTE_SEGREDO";

/**
 * Os segredos que a ponte pode apresentar. Lista fechada.
 *
 * O `KAMBA_PONTE_SEGREDO` diz **qual** se apresenta, e não o valor; mas um id
 * livre deixava uma variável mal escrita mandar a palavra-passe da base num
 * cabeçalho para o alvo que estivesse configurado. Fora desta lista não arranca.
 */
export const SEGREDOS_DA_PONTE = ["agr_internal_token", "idx_internal_token"] as const;
export type SegredoDaPonte = (typeof SEGREDOS_DA_PONTE)[number];

export interface Configuracao {
  readonly url: string;
  readonly consumidores: readonly string[];
  readonly alvo: string;
  readonly segredo: SegredoDaPonte;
  readonly ambiente: Ambiente;
  readonly porta: number;
}

type Variaveis = Readonly<Record<string, string | undefined>>;

function exigir(env: Variaveis, nome: string): string {
  const valor = env[nome]?.trim();
  if (valor === undefined || valor === "") {
    // Nomeia a variável e nunca o valor: é a regra de `db/ligacao.py` e do
    // `agr_shim.ts`, e vale aqui pela mesma razão.
    throw new Error(`a variavel de ambiente ${nome} nao esta definida (ou esta vazia)`);
  }
  return valor;
}

/**
 * A configuração do processo, lida do ambiente. Lança antes de abrir o que quer
 * que seja, e a mensagem nomeia a variável e nunca o valor.
 *
 * Os nomes dos consumidores só se separam aqui; a gramática deles é do
 * `criarPonte`, que recusa no arranque.
 */
export function lerConfiguracao(env: Variaveis = process.env): Configuracao {
  const url = exigir(env, VARIAVEL_DA_FILA);
  const consumidores = exigir(env, VARIAVEL_DOS_CONSUMIDORES)
    .split(",")
    .map((nome) => nome.trim())
    .filter((nome) => nome !== "");
  if (consumidores.length === 0) {
    throw new Error(`${VARIAVEL_DOS_CONSUMIDORES} nao nomeia nenhum consumidor`);
  }
  const alvo = exigir(env, VARIAVEL_DO_ALVO).replace(/\/+$/, "");
  const segredo = exigir(env, VARIAVEL_DO_SEGREDO);
  if (!(SEGREDOS_DA_PONTE as readonly string[]).includes(segredo)) {
    throw new Error(
      `${VARIAVEL_DO_SEGREDO} fora de ${SEGREDOS_DA_PONTE.join("/")}`,
    );
  }
  const ambiente = env.KAMBA_ENV?.trim() ?? "dev";
  if (!isAmbiente(ambiente)) {
    // Um valor desconhecido **não** cai em `dev`: a lição do `chaves.ts` do
    // KAM-008. Um `KAMBA_ENV=producao` a servir segredos de `dev` é pior do
    // que não arrancar.
    throw new Error("KAMBA_ENV fora de dev/staging/prod");
  }
  return {
    url,
    consumidores,
    alvo,
    segredo: segredo as SegredoDaPonte,
    ambiente,
    porta: porta(env),
  };
}

function porta(env: Variaveis): number {
  const bruto = env[VARIAVEL_DA_PORTA];
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
  // Só a da ponte. As do consumo vivem no lado Python, que é quem as mede.
  app.get("/metrics", (c) =>
    c.text(METRICAS_DA_PONTE.exposicao(), 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
}

async function principal(): Promise<void> {
  // Antes de tudo o resto: a partir daqui, um erro por tratar sai como uma
  // linha sem conteúdo, e não como a pilha no `stderr` (KAM-068).
  const log = instalar(SERVICE);

  const configuracao = lerConfiguracao();
  const secrets = await Secrets.arrancar({
    servico: SERVICE,
    provider: new EnvSecretProvider({ ambiente: configuracao.ambiente }),
    obrigatorios: [configuracao.segredo],
  });

  const ponte = criarPonte({
    url: configuracao.url,
    consumidores: configuracao.consumidores,
    alvo: configuracao.alvo,
    credencial: () => secrets.get(configuracao.segredo),
    aoTratar: (outcome) => {
      METRICAS_DA_PONTE.contar(outcome);
      log.info({ outcome });
    },
    aoFalhar: (erro) => {
      const outcome = desfechoDaFalha(erro);
      METRICAS_DA_PONTE.contar(outcome);
      // O estado HTTP vai no `error_code` (`http_503`); o corpo, o `event_id` e
      // o `tenant_id` não vão a lado nenhum.
      log.excepcao(erro, codigoDaFalha(erro), { outcome });
    },
  });

  // `hostname` explícito, e não a omissão do Node — que é `::`/`0.0.0.0`.
  // `specs/01` §6 princípio 7 e o DoD do KAM-001, «nada além de localhost».
  const servidor = serve({
    fetch: criarApp(log).fetch,
    hostname: process.env.HOST?.trim() || "127.0.0.1",
    port: configuracao.porta,
  });
  log.info({ outcome: "service_started" });

  const paragem = new AbortController();
  for (const sinal of ["SIGTERM", "SIGINT"] as const) {
    process.on(sinal, () => paragem.abort());
  }
  await new Promise<void>((resolver) => {
    paragem.signal.addEventListener("abort", () => resolver(), { once: true });
  });

  // Os *workers* primeiro, pela ordem do `agr_shim.ts`: fechar a ligação à
  // fila debaixo de um *job* a correr deixava-o sem tranca.
  await ponte.fechar();
  servidor.close();
}

if (import.meta.main) {
  await principal();
}
