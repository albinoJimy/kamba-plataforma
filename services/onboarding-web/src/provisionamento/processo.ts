/**
 * O processo do consumidor `dono` (KAM-215): a composição, separada da casca.
 *
 * ```text
 * lerConfiguracao      as variáveis de arranque; sem as duas ligações e a fila, não arranca
 * verificarPapeis      cada ligação é do papel que diz ser (`kamba_app`, `kamba_identity`)
 * (o efeito)          o `provisionamentoPelaBase` de `@kamba/core-ts/dono`, montado na casca
 * consumidorDoDono     as dezasseis filas `evt.dono.p<n>`, numa ligação `kamba_app` por fila
 * criarApp             `/healthz` e `/metrics`, e mais nada
 * ```
 *
 * A casca que abre as ligações, lê os segredos e serve a porta é o
 * `../provisionamento.ts`. Partido em dois pela razão do `../lote/processo.ts`: o
 * que pode errar em silêncio fica aqui, com bateria.
 *
 * ## Duas ligações, dois papéis, e nenhuma faz o trabalho da outra
 *
 * O `consumir` do KAM-006 corre como **`kamba_app`**: tem `INSERT` em
 * `events_consumed` e na DLQ, e põe o `app.tenant_id` **do envelope** na
 * transacção. É por essa ligação, e sob essa RLS, que o telefone do caso se lê
 * — um `onboarding_id` de outro tenant no *payload* dá zero linhas. O contacto e
 * a porta do papel correm como **`kamba_identity`**, o único papel com
 * `EXECUTE` na `platform.definir_dono` (revisão `0070`) e com acesso às DEK de
 * contacto: o `kamba_identity` não pode correr o `consumir` (não tem privilégios
 * em `events_consumed`), e o `kamba_app` recebe `42501` na porta. É a forma do
 * `worker-canal-entrada`.
 *
 * ## Três segredos, e só estes
 *
 * A `kek_telefone_do_caso` (decisão do fundador de 2026-11-20: só o
 * `onboarding-web` e este processo a recebem), e as duas chaves do contacto que o
 * `resolveContact` usa — o *pepper* do HMAC e a KEK das DEK. **Obrigatórias no
 * arranque**: sem uma delas, o primeiro evento falhava seis vezes e ia para a
 * DLQ, com o processo verde.
 *
 * ## Em `prod`
 *
 * Arranca, como o `worker-canal-entrada`: desde a decisão do fundador de
 * 2026-11-20 (ADR-L002, critério 9 do KAM-008 emendado, bloco do KAM-227) as
 * chaves do contacto vêm do ambiente que o lançador do cofre enche, e o
 * `Identidade.arrancar` recusa em `prod` sem o *pepper* ou sem a KEK das DEK.
 * Não está no *compose* de `prod` pelo orçamento de memória do conjunto
 * reduzido, que é do fundador (bloco do KAM-215, decisões do executor).
 */

import { healthz } from "@kamba/core-ts";
import { CONSUMIDOR_DO_DONO } from "@kamba/core-ts/dono";
import { METRICAS, filasDe, type Efeito } from "@kamba/core-ts/eventos";
import type { criarTrabalhadores, Trabalhadores } from "@kamba/core-ts/eventos/trabalhador_bullmq";
import type { Logger } from "@kamba/core-ts/logger";
import { isAmbiente } from "@kamba/core-ts/secrets";
import { METRICAS_DA_GUARDA } from "@kamba/core-ts/tenant_guard";
import { Hono } from "hono";
import pg from "pg";

import { SERVICE, VERSION } from "../meta.ts";

/** As variáveis que o processo lê. Nenhuma outra (os segredos vêm pelo cofre). */
export const VARIAVEIS_DO_PROVISIONAMENTO = {
  /** O ambiente, que o `Identidade.arrancar` também confere. */
  ambiente: "KAMBA_ENV",
  /** A cadeia do `kamba_app`, para o `consumir` e a leitura do telefone do caso. */
  app: "KAMBA_PROVISIONAMENTO_APP_DB_URL",
  /** A do `kamba_identity`, para o contacto e a porta do papel. */
  identidade: "KAMBA_PROVISIONAMENTO_IDENTITY_DB_URL",
  fila: "KAMBA_QUEUE_URL",
  porta: "PROVISIONAMENTO_PORT",
} as const;

/** Os três segredos que o processo exige no arranque. Ver a nota do módulo. */
export const SEGREDOS_DO_PROVISIONAMENTO = ["kek_telefone_do_caso", "pepper_contact_hmac", "kek_contact_dek"] as const;

/** A porta da sonda e das métricas. O lote é a 3014. */
export const PORTA_POR_OMISSAO = 3015;

/** O nome do papel de cada ligação, como o `current_user` o devolve. */
export const PAPEIS_DO_PROVISIONAMENTO = { app: "kamba_app", identidade: "kamba_identity" } as const;

/**
 * A subscrição. **Sem ordem**: o `tenant.provisioned` não transita estado nenhum
 * do consumidor, e a restrição da `0005` só exige ordem aos `payment.*`.
 */
export const SUBSCRICAO_DO_DONO = { consumer: CONSUMIDOR_DO_DONO, exigeOrdem: false } as const;

export interface ConfiguracaoDoProvisionamento {
  readonly ambiente: "dev" | "staging" | "prod";
  readonly urlDaApp: string;
  readonly urlDaIdentidade: string;
  readonly urlDaFila: string;
  readonly porta: number;
}

/** Falta uma variável, ou é inválida. **O valor nunca entra na mensagem.** */
export class ConfiguracaoDoProvisionamentoError extends Error {
  override readonly name = "ConfiguracaoDoProvisionamentoError";
  readonly variavel: string;

  constructor(variavel: string, motivo: "em_falta" | "invalida") {
    super(`${variavel} ${motivo === "em_falta" ? "em falta" : "invalida"}: o consumidor do dono nao arranca`);
    this.variavel = variavel;
  }
}

type Ambiente = Readonly<Record<string, string | undefined>>;

function exigir(env: Ambiente, nome: string): string {
  const valor = (env[nome] ?? "").trim();
  if (valor === "") throw new ConfiguracaoDoProvisionamentoError(nome, "em_falta");
  return valor;
}

/** A configuração. Sem uma das duas ligações ou sem a fila, não arranca. */
export function lerConfiguracao(env: Ambiente): ConfiguracaoDoProvisionamento {
  const ambiente = exigir(env, VARIAVEIS_DO_PROVISIONAMENTO.ambiente);
  if (!isAmbiente(ambiente)) throw new ConfiguracaoDoProvisionamentoError(VARIAVEIS_DO_PROVISIONAMENTO.ambiente, "invalida");
  const urlDaApp = exigir(env, VARIAVEIS_DO_PROVISIONAMENTO.app);
  const urlDaIdentidade = exigir(env, VARIAVEIS_DO_PROVISIONAMENTO.identidade);
  const urlDaFila = exigir(env, VARIAVEIS_DO_PROVISIONAMENTO.fila);
  const bruto = (env[VARIAVEIS_DO_PROVISIONAMENTO.porta] ?? "").trim();
  const porta = bruto === "" ? PORTA_POR_OMISSAO : Number(bruto);
  if (!Number.isInteger(porta) || porta < 1 || porta > 65_535) {
    throw new ConfiguracaoDoProvisionamentoError(VARIAVEIS_DO_PROVISIONAMENTO.porta, "invalida");
  }
  return { ambiente, urlDaApp, urlDaIdentidade, urlDaFila, porta };
}

/** Uma ligação que não é do papel que a variável promete. O papel obtido não sai. */
export class PapelErradoError extends Error {
  override readonly name = "PapelErradoError";

  constructor(variavel: string, esperado: string) {
    super(`${variavel} nao e do papel ${esperado}: o consumidor do dono nao arranca com outro papel`);
  }
}

/** A forma mínima de quem responde `current_user`: o `pg.Pool` ou um `pg.Client`. */
interface Consultavel {
  query<T extends Record<string, unknown>>(sql: string): Promise<{ rows: T[] }>;
}

/**
 * **Cada ligação é do papel que diz ser.** Uma `…_APP_DB_URL` com o
 * `kamba_batch` consumia sem a RLS do envelope (o `BYPASSRLS` lia o telefone do
 * caso de qualquer tenant); uma `…_IDENTITY_DB_URL` com o `kamba_app` dava
 * `42501` em cada evento, e todos iam para a DLQ. O arranque recusa as duas.
 */
export async function verificarPapeis(app: Consultavel, identidade: Consultavel): Promise<void> {
  for (const [ligacao, variavel, esperado] of [
    [app, VARIAVEIS_DO_PROVISIONAMENTO.app, PAPEIS_DO_PROVISIONAMENTO.app],
    [identidade, VARIAVEIS_DO_PROVISIONAMENTO.identidade, PAPEIS_DO_PROVISIONAMENTO.identidade],
  ] as const) {
    const r = await ligacao.query<{ papel: string }>("SELECT current_user::text AS papel");
    if (r.rows[0]?.papel !== esperado) throw new PapelErradoError(variavel, esperado);
  }
}

/**
 * O consumidor: as dezasseis filas `evt.dono.p<n>`, uma ligação `kamba_app` por
 * fila (a transacção do consumo é da fila). O `criar` é o `criarTrabalhadores`
 * que a casca importa depois de abrir a porta, pela razão do `../lote/processo.ts`.
 */
export function consumidorDoDono(o: {
  readonly urlDaApp: string;
  readonly urlDaFila: string;
  readonly efeito: Efeito;
  readonly log: Pick<Logger, "info">;
  readonly criar: typeof criarTrabalhadores;
}): Trabalhadores {
  return o.criar({
    ligar: async () => {
      const cliente = new pg.Client({ connectionString: o.urlDaApp, application_name: "onboarding-provisionamento:dono" });
      await cliente.connect();
      return cliente;
    },
    subscricao: SUBSCRICAO_DO_DONO,
    filas: filasDe(SUBSCRICAO_DO_DONO.consumer),
    efeito: o.efeito,
    metricas: METRICAS,
    url: o.urlDaFila,
    // Só o desfecho: o `event_id` e o tenant não estão na *allowlist* do registo.
    log: (dados) => o.log.info({ outcome: `dono_consumo_${String(dados["desfecho"])}` }),
  });
}

export function criarApp(): Hono {
  const app = new Hono();
  app.onError((_erro, c) => c.json({ error: "internal" }, 500));
  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  app.get("/metrics", (c) =>
    c.text(METRICAS.exposicao() + METRICAS_DA_GUARDA.exposicao(), 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
}
