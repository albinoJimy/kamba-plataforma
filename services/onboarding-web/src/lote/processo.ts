/**
 * O processo de lote do onboarding (KAM-198): a composição, separada da casca.
 *
 * ```text
 * lerConfiguracao     as variáveis de arranque; sem as credenciais de lote, não arranca
 * verificarPapeis     cada ligação é do papel que diz ser (`kamba_batch`, `kamba_app`)
 * montarProcesso      a fila sobre os adaptadores SQL, o ciclo e o gancho do KAM-092
 * criarApp            `/healthz` e `/metrics`, e mais nada
 * arrancar            os papéis verificados, o processo montado e a app das métricas dele
 * opcoesDoConjunto    a ligação de cada papel, com limites de tempo
 * ```
 *
 * A casca que abre as ligações, serve a porta e agenda o ciclo é o `../lote.ts`.
 * Está partido em dois pela razão do `services/com/src/payments/arranque.ts`: o
 * que pode errar em silêncio — a configuração, a verificação dos papéis, a
 * composição — fica aqui, com bateria, e a casca fica com o `pg.Pool` e o
 * `serve`, que só uma pilha levantada exercita.
 *
 * ## É infraestrutura de lote do onboarding, e não só da fila
 *
 * O bloco do KAM-198 pede-o assim: a reconciliação da saga (KAM-091) vai correr
 * aqui também, e escrever um processo só para a fila era escrever dois. Por isso
 * o processo tem nome próprio (`onboarding-lote` no compose) e a fila é a
 * primeira coisa que ele corre, não a única que pode correr.
 *
 * ## Dois papéis, e porquê o segundo
 *
 * A fila corre como `kamba_batch`: atravessa tenants por natureza, e é o papel
 * com `BYPASSRLS`, que é o auditado (`../../../../packages/core-ts/src/revisao/sql.ts`).
 * Mas **um** efeito de uma decisão não é da fila: a decisão humana de screening
 * grava-se em `platform.screening_decision`, onde o `kamba_batch` só lê e o
 * `INSERT` é do `kamba_app` com `app.tenant_id` posto (revisão `0044`). Em vez
 * de dar ao lote um privilégio novo — uma revisão de base de dados —, o processo
 * abre uma segunda ligação, como `kamba_app`, e grava dentro do `comTenant` do
 * tenant do caso. A RLS dessa tabela continua a ser a guarda.
 *
 * ## O aviso ao dono não sai deste processo, e é de propósito
 *
 * O aviso precisa do telefone registado em claro (`DadosPessoais`) e de um
 * agregador de SMS. **Nenhum dos dois existe em produção**: o agregador não está
 * escolhido (fundador, KAM-116), e o telefone cifrado do `onboarding_case` não
 * tem adaptador que o decifre. O duplo `FakeSmsProvider` não entra aqui — um
 * aviso «enviado» para lado nenhum resolvia o efeito e o dono nunca sabia.
 * O `AvisoSemVia` levanta `AvisoSemDestinoError`: a fase e o screening aplicam-se
 * (vêm antes), o efeito fica por reaplicar, e o ciclo di-lo em cada volta.
 */

import { healthz } from "@kamba/core-ts";
import type { Logger } from "@kamba/core-ts/logger";
import {
  AuditoriaSql,
  AvisoSemDestinoError,
  CicloDaFila,
  EfeitosPorReaplicarSql,
  FERIADOS_POR_OMISSAO,
  LeitorDaFilaSql,
  MetricasDaRevisao,
  OnboardingsSql,
  RevisaoSql,
  ServicoDeRevisao,
  decisaoHumanaDeScreening,
  type Aviso,
  type AvisoAoDono,
  type Cifra,
  type ConjuntoSql,
  type DadosPessoais,
  type DocumentosDaRevisao,
  type EfeitosPorReaplicar,
  type MotivoPublico,
  type Relogio,
  type ResultadoDaAbertura,
  type ResultadoDoCiclo,
  type ViaDoAviso,
} from "@kamba/core-ts/revisao";
import { EscritorSql, LeitorSql, type EscritorDeDecisoes } from "@kamba/core-ts/screening";
import { isAmbiente } from "@kamba/core-ts/secrets";
import { comTenant } from "@kamba/core-ts/tenant_guard";
import { Hono } from "hono";

import { SERVICE, VERSION } from "../meta.ts";

/** As variáveis que o processo lê. Nenhuma outra. */
export const VARIAVEIS_DO_LOTE = {
  ambiente: "KAMBA_AMBIENTE",
  /** A cadeia de ligação do `kamba_batch`. A palavra-passe vem do cofre (KAM-010). */
  lote: "KAMBA_LOTE_DB_URL",
  /** A do `kamba_app`, só para a decisão humana de screening. */
  app: "KAMBA_LOTE_APP_DB_URL",
  porta: "LOTE_PORT",
  intervalo: "LOTE_INTERVALO_MS",
  /** O dia em que a amostragem das aprovações automáticas começou (`AAAA-MM-DD`). */
  amostragem: "ONBOARDING_LOTE_AMOSTRAGEM_DESDE",
} as const;

/** A porta da sonda e das métricas do processo de lote. */
export const PORTA_POR_OMISSAO = 3014;

/** Uma volta por minuto: o alerta dos 80% é de um prazo em dias úteis. */
export const INTERVALO_POR_OMISSAO_MS = 60_000;

/** O nome do papel de cada ligação, como o `current_user` o devolve. */
export const PAPEIS_DO_LOTE = { lote: "kamba_batch", app: "kamba_app" } as const;

export interface ConfiguracaoDoLote {
  readonly ambiente: "dev" | "staging" | "prod";
  readonly urlDoLote: string;
  readonly urlDaApp: string;
  readonly porta: number;
  readonly intervaloMs: number;
  readonly inicioDaAmostragem: Date | null;
}

/**
 * Falta uma variável de que o processo precisa para arrancar. **O valor nunca
 * entra na mensagem**: é uma cadeia de ligação com palavra-passe.
 */
export class ConfiguracaoDoLoteError extends Error {
  override readonly name = "ConfiguracaoDoLoteError";
  readonly variavel: string;

  constructor(variavel: string, motivo: "em_falta" | "invalida") {
    super(
      motivo === "em_falta"
        ? `${variavel} em falta: o processo de lote do onboarding nao arranca sem as credenciais de lote`
        : `${variavel} invalida`,
    );
    this.variavel = variavel;
  }
}

type Ambiente = Readonly<Record<string, string | undefined>>;

function exigir(env: Ambiente, nome: string): string {
  const valor = (env[nome] ?? "").trim();
  if (valor === "") throw new ConfiguracaoDoLoteError(nome, "em_falta");
  return valor;
}

function inteiro(env: Ambiente, nome: string, omissao: number, minimo: number, maximo: number): number {
  const bruto = (env[nome] ?? "").trim();
  if (bruto === "") return omissao;
  const n = Number(bruto);
  if (!Number.isInteger(n) || n < minimo || n > maximo) throw new ConfiguracaoDoLoteError(nome, "invalida");
  return n;
}

/**
 * A configuração do processo. **Em `prod` arranca** — é a diferença para o
 * `server.ts` do `onboarding-web`, que recusa `prod` por correr sobre
 * repositórios em memória — e em nenhum ambiente arranca sem as duas
 * credenciais: uma fila sem base não é uma fila vazia, é um processo verde que
 * não faz nada.
 */
export function lerConfiguracao(env: Ambiente): ConfiguracaoDoLote {
  const ambiente = exigir(env, VARIAVEIS_DO_LOTE.ambiente);
  if (!isAmbiente(ambiente)) throw new ConfiguracaoDoLoteError(VARIAVEIS_DO_LOTE.ambiente, "invalida");
  const urlDoLote = exigir(env, VARIAVEIS_DO_LOTE.lote);
  const urlDaApp = exigir(env, VARIAVEIS_DO_LOTE.app);
  const porta = inteiro(env, VARIAVEIS_DO_LOTE.porta, PORTA_POR_OMISSAO, 1, 65_535);
  const intervaloMs = inteiro(env, VARIAVEIS_DO_LOTE.intervalo, INTERVALO_POR_OMISSAO_MS, 1_000, 86_400_000);
  const bruto = (env[VARIAVEIS_DO_LOTE.amostragem] ?? "").trim();
  let inicioDaAmostragem: Date | null = null;
  if (bruto !== "") {
    // Um dia, e só um dia: `2026-02-30` passava num `new Date` e virava março.
    if (!/^\d{4}-\d{2}-\d{2}$/.test(bruto)) throw new ConfiguracaoDoLoteError(VARIAVEIS_DO_LOTE.amostragem, "invalida");
    const dia = new Date(`${bruto}T00:00:00Z`);
    if (Number.isNaN(dia.getTime()) || dia.toISOString().slice(0, 10) !== bruto) {
      throw new ConfiguracaoDoLoteError(VARIAVEIS_DO_LOTE.amostragem, "invalida");
    }
    inicioDaAmostragem = dia;
  }
  return { ambiente, urlDoLote, urlDaApp, porta, intervaloMs, inicioDaAmostragem };
}

/** Uma ligação que não é do papel que a variável promete. */
export class PapelErradoError extends Error {
  override readonly name = "PapelErradoError";
  readonly esperado: string;

  constructor(variavel: string, esperado: string) {
    // O papel obtido **não** sai: uma cadeia trocada pode ser a do dono da base,
    // e o nome dele não tem de ir parar ao registo.
    super(`${variavel} nao e do papel ${esperado}: o processo de lote nao arranca com outro papel`);
    this.esperado = esperado;
  }
}

/**
 * **Cada ligação é do papel que diz ser.** Uma `KAMBA_LOTE_DB_URL` com o dono da
 * base corria a fila sem o papel auditado — e o `BYPASSRLS` do `kamba_batch` é
 * aceitável **porque** é auditado; o de outro papel não é. E uma
 * `KAMBA_LOTE_APP_DB_URL` com o `kamba_batch` gravava o screening sem a RLS que
 * a guarda. O arranque recusa as duas trocas.
 */
export async function verificarPapeis(lote: ConjuntoSql, app: ConjuntoSql): Promise<void> {
  for (const [ligacao, variavel, esperado] of [
    [lote, VARIAVEIS_DO_LOTE.lote, PAPEIS_DO_LOTE.lote],
    [app, VARIAVEIS_DO_LOTE.app, PAPEIS_DO_LOTE.app],
  ] as const) {
    const r = await ligacao.query<{ papel: string }>("SELECT current_user::text AS papel");
    if (r.rows[0]?.papel !== esperado) throw new PapelErradoError(variavel, esperado);
  }
}

/**
 * O aviso ao dono, **sem via**. Ver a nota do módulo: levanta sempre, e o
 * efeito fica por reaplicar até haver agregador e telefone em claro.
 */
export class AvisoSemVia implements AvisoAoDono {
  async avisar(pedido: {
    readonly onboardingId: string;
    readonly via: ViaDoAviso;
    readonly aviso: Aviso;
    readonly motivoPublico: MotivoPublico | null;
  }): Promise<void> {
    throw new AvisoSemDestinoError(pedido.via);
  }
}

/** O que o lote nunca faz: decidir com nota, ler um dado pessoal, abrir um documento. */
export class OperacaoForaDoLoteError extends Error {
  override readonly name = "OperacaoForaDoLoteError";

  constructor(operacao: string) {
    super(`${operacao} nao corre no processo de lote: e da consola da equipa`);
  }
}

const SEM_CIFRA: Cifra = {
  cifrar: async () => {
    throw new OperacaoForaDoLoteError("cifrar a nota do revisor");
  },
  decifrar: async () => {
    throw new OperacaoForaDoLoteError("decifrar a nota do revisor");
  },
};

const SEM_DADOS: DadosPessoais = {
  ler: async () => {
    throw new OperacaoForaDoLoteError("ler um dado pessoal");
  },
};

const SEM_DOCUMENTOS: DocumentosDaRevisao = {
  url: async () => {
    throw new OperacaoForaDoLoteError("abrir um documento");
  },
};

/**
 * O escritor da decisão humana de screening: `kamba_app`, dentro do
 * `comTenant` do tenant da linha, e **idempotente**.
 *
 * A idempotência é deste adaptador e não do `EscritorSql`, e é medida: a
 * `screening_decision` é *append-only* e sem unicidade sobre a chave, e o
 * `reaplicarEfeitos` corre o screening em **cada** volta enquanto o aviso (que
 * vem depois) falhar. Sem isto, um caso `categoria` aprovado ganhava uma linha
 * `humano`/`permitida` por minuto. Uma linha igual à última da chave — mesma
 * decisão, mesma origem — não se repete; uma diferente (o recurso que inverte a
 * primeira, ou uma decisão do motor pelo meio) grava-se.
 */
export function escritorHumanoDeScreening(app: ConjuntoSql): EscritorDeDecisoes {
  return {
    async gravar(linha) {
      const ligacao = await app.connect();
      let estragada: Error | undefined;
      try {
        // A `ligacao` e não o cliente que o `comTenant` entrega: são o mesmo
        // objecto, e o tipo do `tenant_guard` só promete `Promise<unknown>`.
        await comTenant(ligacao, linha.tenantId, async () => {
          const ultima = (
            await new LeitorSql(ligacao).decisoes({
              tenantId: linha.tenantId,
              sujeitoTipo: linha.sujeitoTipo,
              sujeitoRef: linha.sujeitoRef,
              versaoPolitica: linha.versaoPolitica,
              conteudoSha256: linha.conteudoSha256,
            })
          ).at(-1);
          if (ultima !== undefined && ultima.origem === linha.origem && ultima.decisao === linha.decisao) return;
          await new EscritorSql(ligacao).gravar(linha);
        });
      } catch (erro) {
        // O `comTenant` engole uma falha do `ROLLBACK`, e então não se sabe se
        // a transacção ficou fechada: a ligação devolve-se **com** o erro, e o
        // `pg` descarta-a em vez de a dar ao próximo (achado 9 da revisão
        // adversarial).
        estragada = erro instanceof Error ? erro : new Error("escrita do screening falhou");
        throw erro;
      } finally {
        ligacao.release(estragada);
      }
    },
  };
}

/**
 * A lista de efeitos por reaplicar do processo: a coluna
 * `review_case.efeito_pendente_at` da revisão `0053`, como `kamba_batch`.
 * **Sobrevive a um reinício** (critério 2), e é a mesma que a consola marca
 * quando tiver o serviço montado sobre a base.
 */
export function efeitosDoLote(lote: ConjuntoSql, opcoes: { readonly carenciaMs?: number } = {}): EfeitosPorReaplicar {
  return new EfeitosPorReaplicarSql(lote, opcoes);
}

export interface OpcoesDoProcesso {
  /** O conjunto de ligações do `kamba_batch`. */
  readonly lote: ConjuntoSql;
  /** O conjunto de ligações do `kamba_app`. */
  readonly app: ConjuntoSql;
  readonly efeitos: EfeitosPorReaplicar;
  readonly log: Pick<Logger, "warn">;
  readonly inicioDaAmostragem?: Date | null;
  readonly relogio?: Relogio;
  /** Quantos casos da triagem, e quantos efeitos, numa volta. */
  readonly limite?: number;
}

/** O processo montado: o ciclo, o serviço da fila e o gancho do KAM-092. */
export interface ProcessoDeLote {
  readonly servico: ServicoDeRevisao;
  readonly ciclo: CicloDaFila;
  /**
   * **O ponto onde o KAM-092 chama o `amostrar`** sobre cada aprovação
   * automática, que é ele quem conhece (critério 4). Corre neste processo, com
   * as credenciais de lote, e devolve o caso `auditoria` aberto quando a
   * aprovação cai na amostra — `null` fora da janela, fora da fracção, ou sem
   * `inicioDaAmostragem`.
   */
  aprovacaoAutomatica(onboardingId: string, tenantId: string): Promise<ResultadoDaAbertura | null>;
}

/**
 * A fila sobre os adaptadores SQL. **Nenhum duplo em memória**: o repositório,
 * os onboardings, a auditoria, o leitor das métricas e o screening são SQL; o
 * que não é deste processo (cifra, dados pessoais, documentos) recusa em vez de
 * fingir, e o aviso levanta (ver a nota do módulo).
 */
export function montarProcesso(o: OpcoesDoProcesso): ProcessoDeLote {
  const servico = new ServicoDeRevisao({
    repositorio: new RevisaoSql(o.lote, { conjunto: o.lote }),
    onboardings: new OnboardingsSql(o.lote),
    auditoria: new AuditoriaSql(o.lote),
    aviso: new AvisoSemVia(),
    // Só o motivo: o caso e o tipo não estão na *allowlist* do registo, e quem
    // quer saber qual é lê a fila.
    alerta: (motivo) => o.log.warn({ outcome: motivo }),
    cifra: SEM_CIFRA,
    dados: SEM_DADOS,
    documentos: SEM_DOCUMENTOS,
    screening: decisaoHumanaDeScreening(escritorHumanoDeScreening(o.app)),
    // A mesma lista que o ciclo reaplica: o serviço marca antes dos efeitos.
    efeitos: o.efeitos,
    inicioDaAmostragem: o.inicioDaAmostragem ?? null,
    ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
  });
  const ciclo = new CicloDaFila({
    servico,
    leitor: new LeitorDaFilaSql(o.lote),
    efeitos: o.efeitos,
    feriados: FERIADOS_POR_OMISSAO,
    ...(o.limite === undefined ? {} : { limite: o.limite }),
  });
  return {
    servico,
    ciclo,
    aprovacaoAutomatica: (onboardingId, tenantId) => ciclo.aprovacaoAutomatica(onboardingId, tenantId),
  };
}

/**
 * A linha de registo de uma volta. **Por nome de passo**, nunca pela mensagem do
 * erro (`../../../../packages/core-ts/src/revisao/ciclo.ts`).
 */
export function registarVolta(log: Pick<Logger, "info" | "error">, r: ResultadoDoCiclo): void {
  if (r.falhas.length === 0) log.info({ outcome: "ciclo_concluido" });
  else log.error({ outcome: "ciclo_com_falhas", error_code: r.falhas.join(",") });
}

/**
 * A aplicação HTTP do processo: a sonda e as métricas da fila, e mais nada.
 *
 * `/metrics` serve as quatro séries do dicionário §3.61 da **mesma** instância
 * que o ciclo recalcula. Sem argumento, uma instância vazia: é como o condutor
 * da bateria X-01 a levanta nas sondas. As etiquetas são domínios fechados e
 * nenhuma leva tenant nem caso (`OBS-I`); o caso X-01 do `/metrics` mede-o com
 * um caso de outro tenant na fila.
 */
export function criarApp(metricas: MetricasDaRevisao = new MetricasDaRevisao()): Hono {
  const app = new Hono();
  app.onError((_erro, c) => c.json({ error: "internal" }, 500));
  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  app.get("/metrics", (c) =>
    c.text(metricas.exposicao(), 200, { "content-type": "text/plain; version=0.0.4; charset=utf-8" }),
  );
  return app;
}

/**
 * A ligação de um papel, com **limites de tempo** (achado 5 da revisão
 * adversarial). Sem eles, uma sessão presa a segurar o trinco da quota
 * congelava o `pg_advisory_xact_lock` do lote sem limite, e o `correr()`, que
 * devolve a volta em curso, congelava todas as seguintes com o `/healthz` verde.
 * Com eles, a espera falha, o passo diz-se no registo, e a volta seguinte corre.
 *
 * *Propostas*, sem medição de carga: uma instrução da fila não passa de
 * milissegundos, e trinta segundos é folga de duas ordens de grandeza.
 */
export function opcoesDoConjunto(url: string, papel: "lote" | "app") {
  return {
    connectionString: url,
    // Uma volta corre em série, e o trinco empresta uma ligação de cada vez; a
    // da `app` só serve o screening.
    max: papel === "lote" ? 4 : 2,
    statement_timeout: 30_000,
    lock_timeout: 10_000,
    idle_in_transaction_session_timeout: 60_000,
    application_name: `onboarding-lote:${papel}`,
  };
}

/** O que a casca precisa depois de arrancar: o processo e a app que o serve. */
export interface Arranque {
  readonly processo: ProcessoDeLote;
  readonly app: Hono;
}

/**
 * **O arranque inteiro, menos as ligações e a porta.** Verifica os papéis antes
 * de montar o que quer que seja, monta o processo sobre a lista de efeitos da
 * base, e devolve a app que serve as métricas **do ciclo** — a mesma instância
 * que ele recalcula. Está aqui, e não na casca, para que os ensaios do *gate* 4
 * o alcancem: com ele no `../lote.ts`, servir uma instância vazia ou saltar a
 * verificação dos papéis passavam todos os ensaios (achado 6 da revisão
 * adversarial).
 */
export async function arrancar(o: {
  readonly lote: ConjuntoSql;
  readonly app: ConjuntoSql;
  readonly log: Pick<Logger, "warn">;
  readonly inicioDaAmostragem: Date | null;
}): Promise<Arranque> {
  await verificarPapeis(o.lote, o.app);
  const processo = montarProcesso({
    lote: o.lote,
    app: o.app,
    efeitos: efeitosDoLote(o.lote),
    log: o.log,
    inicioDaAmostragem: o.inicioDaAmostragem,
  });
  return { processo, app: criarApp(processo.ciclo.metricas) };
}
