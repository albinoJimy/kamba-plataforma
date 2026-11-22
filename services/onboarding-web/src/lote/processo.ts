/**
 * O processo de lote do onboarding (KAM-198): a composição, separada da casca.
 *
 * ```text
 * lerConfiguracao     as variáveis de arranque; sem as credenciais de lote, não arranca
 * verificarPapeis     cada ligação é do papel que diz ser (`kamba_batch`, `kamba_app`)
 * montarProcesso      a fila sobre os adaptadores SQL, o ciclo, as duas portas do KAM-092,
 *                     o T&S ligado à fila com as suas varreduras (KAM-200), e o avanço
 *                     do caso até `es_concluido` que emite o `tenant.provisioned` (KAM-215)
 * consumidorDoTrust   o consumidor dos sete tipos de evento de T&S, como `kamba_app`
 * consumidorDoPainel  o consumidor da resposta do AGR de canal `painel` (KAM-224)
 * cicloDoOffboarding  as fases do encerramento deste lado, agendadas (KAM-210)
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
 * ## Trust & Safety corre aqui (KAM-200)
 *
 * Três coisas, e as três são do lote porque atravessam tenants ou mudam o estado
 * de um tenant:
 *
 * * **O efeito de uma decisão** sobre um caso `trust` ou `recurso`: o
 *   `ServicoDeTrust` do lado do lote é o `trust` das dependências do
 *   `ServicoDeRevisao`. Sem ele, decidir um desses casos falhava fechado
 *   (`EfeitoPorAplicarError`) e o caso ficava para reaplicar para sempre.
 * * **As varreduras**, agendadas (`CicloDoTrust`), cada corrida no `audit_log`.
 * * **O consumidor** dos sete tipos do critério 1 do KAM-097, com o
 *   `efeitoDeTrust`, sobre ligações do `kamba_app` (a marca de consumo e os
 *   sinais sob a RLS do tenant do envelope). As subscrições estão declaradas em
 *   `registry/trust.yaml`.
 *
 * O aviso de uma sanção ao dono é o mesmo caso do aviso da fila, abaixo: sem
 * agregador nem telefone em claro, levanta, e o efeito fica por reaplicar.
 *
 * ## A confiança gradual corre aqui também (KAM-203)
 *
 * O recálculo do nível de cada tenant (`@kamba/core-ts/confianca`, KAM-096) em
 * quatro sítios, todos neste processo: a volta diária e a varredura das
 * descidas (`CicloDaConfianca`, que a casca agenda), o `order.delivered` depois
 * de o consumidor de T&S o consumir (`depoisDoTrust`), e cada aprovação que
 * passa pela porta (`OnboardingsQueRecalculam`). O nome do consumidor que marca
 * a independência é o da subscrição (`SUBSCRICAO_DO_TRUST`), e não um literal.
 *
 * ## O off-boarding corre aqui (KAM-210)
 *
 * As três fases do encerramento deste lado que correm sem pedido — o canal, os
 * pendentes e a revogação; o pedido corre-o quem o recebe — correm num ciclo
 * agendado, como `kamba_batch` (`CicloDoOffboarding`). As métricas dele contam as
 * **sete** fases, lidas da base, e são as do alerta da fase parada
 * (`infra/compose/prometheus/regras/kamba-offboarding.yml`). As três do lado dos
 * dados correm pelo `correr_volta` do `kamba_core.offboarding.processo`, que
 * ainda não tem processo que o chame (credor KAM-218).
 *
 * **A Meta está ligada desde o KAM-218** (`portasDoOffboarding`): o
 * `CanalDaMetaPelaGraph` com o *token* de cada WABA lido do cofre
 * (`tokenDoWabaPeloCofre`, a `kek_token_cliente` e o ambiente que o lançador
 * do cofre enche, ADR-L002), pelo `proxy-saida`. **A revogação está ligada
 * desde o KAM-233** ao LiteLLM (a chave pelo alias) e ao Chatwoot (a conta
 * suspensa), na rede interna; a Medusa continua sem adaptador (D3), e a saga
 * não lhe deixa recurso. Uma fase que precise de uma porta sem adaptador falha
 * pelo nome e fica parada, com alerta — nunca «feita» sem o lado de fora saber.
 * **Um LiteLLM sem base também**: o proxy de `prod` arranca sem `DATABASE_URL`,
 * responde 500 ao `/key/list` (medido), e a fase `revogacao` pára na chave.
 *
 * ## O aviso ao dono não sai deste processo, e é de propósito
 *
 * O aviso precisa do telefone registado em claro (`DadosPessoais`) e de um
 * agregador de SMS. **Nenhum dos dois existe em produção**: o agregador não está
 * escolhido (fundador, KAM-116), e o telefone cifrado do `onboarding_case` não
 * se decifra **neste** processo — tem decifrador desde o KAM-215, mas a KEK dele
 * (`kek_telefone_do_caso`) só a recebem o `onboarding-web` e o consumidor `dono`
 * (decisão do fundador de 2026-11-20), e o lote corre como `kamba_batch`. O duplo `FakeSmsProvider` não entra aqui — um
 * aviso «enviado» para lado nenhum resolvia o efeito e o dono nunca sabia.
 * O `AvisoSemVia` levanta `AvisoSemDestinoError`: a fase e o screening aplicam-se
 * (vêm antes), o efeito fica por reaplicar, e o ciclo di-lo em cada volta.
 */

import { healthz } from "@kamba/core-ts";
import {
  CicloDaActivacao,
  filaDoTeste,
  type ResultadoDoCicloDaActivacao,
} from "@kamba/core-ts/activacao";
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
  aprovacaoDoKyc,
  decisaoHumanaDeScreening,
  varrerAprovacoes,
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
import type { AprovacaoDoKyc } from "@kamba/core-ts/kyc";
import {
  CicloDaConfianca,
  MetricasDaConfianca,
  RecalculoDaConfianca,
  SQL_NIVEL_DO_TENANT,
  type ResultadoDoCicloDaConfianca,
} from "@kamba/core-ts/confianca";
import { METRICAS, MaquinaNaBase, filasDe, type Envelope } from "@kamba/core-ts/eventos";
// Só os tipos: o `bullmq` e o `ioredis` carregam-se na casca, **depois** de a
// porta abrir (ver o `consumidorDoTrust`).
import type { criarTrabalhadores, Trabalhadores } from "@kamba/core-ts/eventos/trabalhador_bullmq";
import { varrerProvisionamentos } from "@kamba/core-ts/provisioning";
import { CONSUMIDOR_DO_PAINEL, efeitoDoPainel } from "@kamba/core-ts/resposta";
import { EscritorSql, LeitorSql, type EscritorDeDecisoes } from "@kamba/core-ts/screening";
import { isAmbiente } from "@kamba/core-ts/secrets";
import { METRICAS_DA_GUARDA, comTenant } from "@kamba/core-ts/tenant_guard";
import {
  CANAL_SEM_ADAPTADOR,
  CanalDaMetaPelaGraph,
  ChaveDoLlmPeloProxy,
  CicloDoOffboarding,
  INTERVALO_DO_OFFBOARDING_POR_OMISSAO_MS,
  MetricasDoOffboarding,
  REVOGACAO_SEM_ADAPTADOR,
  TELEFONES_SEM_ADAPTADOR,
  telefonesPeloCofre,
  tokenDoWabaPeloCofre,
  type PoolDaIdentidade,
  type PortaDosTelefones,
  type CofreDoToken,
  type PortasDoCiclo,
  type ResultadoDoCicloDoOffboarding,
} from "@kamba/core-ts/offboarding";
import { ArquivoDoChatwoot, arquivarContaDoTenant } from "@kamba/core-ts/hnd";
import { EnvKeyProvider, Identidade } from "@kamba/core-ts/identity";
import {
  criarStorageS3,
  lerConfig as lerConfigDoStorage,
  type CofreLeitor,
  type StorageProvider,
} from "@kamba/core-ts/storage";
import { GraphHttp, versaoDaGraph } from "@kamba/core-ts/onboarding";
import { ANFITRIAO_DA_GRAPH } from "@kamba/core-ts/outbound";
import { EnvSecretProvider } from "@kamba/core-ts/secrets";
import {
  AvisoDeSancaoSemDestinoError,
  CONSUMIDOR_DE_TRUST,
  CicloDoTrust,
  EstadoDosTenantsSql,
  INTERVALO_DO_TRUST_POR_OMISSAO_MS,
  MetricasDoTrust,
  RepositorioDeTrustSql,
  ServicoDeTrust,
  efeitoDeTrust,
  type AvisoDeSancao,
  type MotivoPublicoDaSancao,
  type ResultadoDoCicloDoTrust,
} from "@kamba/core-ts/trust";
import { Hono } from "hono";
import pg from "pg";

import { SERVICE, VERSION } from "../meta.ts";

/** As variáveis que o processo lê. Nenhuma outra. */
export const VARIAVEIS_DO_LOTE = {
  ambiente: "KAMBA_AMBIENTE",
  /** A cadeia de ligação do `kamba_batch`. A palavra-passe vem do cofre (KAM-010). */
  lote: "KAMBA_LOTE_DB_URL",
  /**
   * A do `kamba_app`: as leituras que só a aplicação faz (o catálogo e o teste da
   * activação, KAM-202) e os consumidores de eventos. A decisão humana de
   * screening deixou de passar por aqui (KAM-202, critério 6).
   */
  app: "KAMBA_LOTE_APP_DB_URL",
  porta: "LOTE_PORT",
  intervalo: "LOTE_INTERVALO_MS",
  /** A fila de eventos (Valkey), de onde o consumidor de T&S lê (KAM-200). */
  fila: "KAMBA_QUEUE_URL",
  /** O intervalo das varreduras de T&S. */
  intervaloDoTrust: "LOTE_TRUST_INTERVALO_MS",
  /** O intervalo do ciclo do off-boarding (KAM-210). */
  intervaloDoOffboarding: "LOTE_OFFBOARDING_INTERVALO_MS",
  /** O dia em que a amostragem das aprovações automáticas começou (`AAAA-MM-DD`). */
  amostragem: "ONBOARDING_LOTE_AMOSTRAGEM_DESDE",
} as const;

/**
 * A subscrição do consumidor de T&S, **uma vez**: o consumidor corre com ela, e
 * o recálculo da confiança lê dela o nome que marca a independência (KAM-203,
 * critério 5). Dois literais eram dois sítios a mudar, e um esquecido deixava
 * o recálculo a perguntar por marcas de um consumidor que não existe — com
 * todos os pedidos `por_avaliar`, e ninguém a subir.
 */
export const SUBSCRICAO_DO_TRUST = { consumer: CONSUMIDOR_DE_TRUST, exigeOrdem: true } as const;

/**
 * A subscrição do consumidor da resposta do AGR no painel (KAM-224). Sem ordem:
 * o `agent.replied` não transita estado nenhum, e cada resposta é uma linha.
 */
export const SUBSCRICAO_DO_PAINEL = { consumer: CONSUMIDOR_DO_PAINEL, exigeOrdem: false } as const;

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
  readonly urlDaFila: string;
  readonly intervaloDoTrustMs: number;
  readonly intervaloDoOffboardingMs: number;
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
  // **Obrigatória**, como as credenciais: sem a fila o consumidor de T&S não
  // consome, e um processo verde que não consome é o defeito do KAM-187.
  const urlDaFila = exigir(env, VARIAVEIS_DO_LOTE.fila);
  const porta = inteiro(env, VARIAVEIS_DO_LOTE.porta, PORTA_POR_OMISSAO, 1, 65_535);
  const intervaloMs = inteiro(env, VARIAVEIS_DO_LOTE.intervalo, INTERVALO_POR_OMISSAO_MS, 1_000, 86_400_000);
  const intervaloDoTrustMs = inteiro(
    env,
    VARIAVEIS_DO_LOTE.intervaloDoTrust,
    INTERVALO_DO_TRUST_POR_OMISSAO_MS,
    1_000,
    86_400_000,
  );
  const intervaloDoOffboardingMs = inteiro(
    env,
    VARIAVEIS_DO_LOTE.intervaloDoOffboarding,
    INTERVALO_DO_OFFBOARDING_POR_OMISSAO_MS,
    1_000,
    86_400_000,
  );
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
  return {
    ambiente,
    urlDoLote,
    urlDaApp,
    porta,
    intervaloMs,
    inicioDaAmostragem,
    urlDaFila,
    intervaloDoTrustMs,
    intervaloDoOffboardingMs,
  };
}

/** As variáveis da revogação (KAM-233). A base de cada um, na rede interna. */
export const VARIAVEIS_DA_REVOGACAO = {
  litellm: "KAMBA_LLM_PROXY_URL",
  chatwoot: "KAMBA_CHATWOOT_URL",
} as const;

/**
 * As portas do off-boarding deste processo (KAM-218, critério 3; KAM-233,
 * critério 2): a Meta, o LiteLLM e o Chatwoot ligados.
 *
 * **A revogação** (decisão do fundador de 2026-11-21, Q1 = A): a chave do
 * tenant apaga-se no proxy pelo alias, com a `litellm_master_key`, e a conta do
 * Chatwoot do tenant suspende-se pela Platform API, com o
 * `chatwoot_platform_token` — as duas pelo cofre, lidas **a cada chamada**, como
 * o *token* do WABA, para que uma rotação não peça reinício. A conta lê-se da
 * `handoff_accounts` pela ligação do lote (`arquivarContaDoTenant`, a mesma
 * função do `archiveAccount` do `HandoffProvider`). Sem a base de um deles no
 * ambiente, essa porta fica sem adaptador e a fase pára nela, com alerta. O
 * canal da Medusa e a *inbox* continuam sem adaptador (D3, e a saga não os
 * cria), e só se chamam quando a saga os registou.
 *
 * O *token* de cada WABA lê-se do cofre a cada fase (`tokenDoWabaPeloCofre`),
 * pela ligação do lote — a leitura da `tenant_channels` não tem tenant do
 * pedido, e o leitor recusa um WABA de dois tenants. A Graph é a do KAM-016
 * (`GraphHttp`), só com as duas operações que o adaptador usa: o `app_id` e o
 * `app_secret` servem a troca do *code*, que não corre neste processo, e por isso
 * vão vazios — o tipo `Pick` impede de a chamar.
 */
export function portasDoOffboarding(o: {
  readonly lote: ConjuntoSql;
  readonly ambiente: "dev" | "staging" | "prod";
  readonly env: Ambiente;
  /** O cofre. Por omissão, o do ambiente do processo (ADR-L002). */
  readonly cofre?: CofreDoToken;
  /** O `fetch` da Graph. Porta para os ensaios. */
  readonly buscar?: typeof fetch;
  /** Os telefones para a exportação (KAM-233). Sem ela, o fecho dos `pendentes` pára. */
  readonly telefones?: PortaDosTelefones;
}): PortasDoCiclo {
  const graph: Pick<GraphHttp, "subscrever" | "anularSubscricao"> = new GraphHttp({
    base: ANFITRIAO_DA_GRAPH,
    versao: versaoDaGraph(o.env),
    appId: "",
    appSecret: "",
    ...(o.buscar === undefined ? {} : { buscar: o.buscar }),
  });
  const cofre = o.cofre ?? new EnvSecretProvider({ ambiente: o.ambiente, env: o.env as NodeJS.ProcessEnv });
  const buscar = o.buscar === undefined ? {} : { buscar: o.buscar };
  const baseDoLlm = (o.env[VARIAVEIS_DA_REVOGACAO.litellm] ?? "").trim();
  const baseDoChatwoot = (o.env[VARIAVEIS_DA_REVOGACAO.chatwoot] ?? "").trim();
  const proxy = async () =>
    new ChaveDoLlmPeloProxy({ base: baseDoLlm, chaveMestra: await cofre.get("litellm_master_key"), ...buscar });
  return {
    canal: new CanalDaMetaPelaGraph(graph, tokenDoWabaPeloCofre({ bd: o.lote, cofre })),
    telefones: o.telefones ?? TELEFONES_SEM_ADAPTADOR,
    revogacao: {
      ...REVOGACAO_SEM_ADAPTADOR,
      chaveDeLlm:
        baseDoLlm === ""
          ? REVOGACAO_SEM_ADAPTADOR.chaveDeLlm
          : {
              revogarDoTenant: async (tenantId) => (await proxy()).revogarDoTenant(tenantId),
            },
      contaDeAtendimento:
        baseDoChatwoot === ""
          ? REVOGACAO_SEM_ADAPTADOR.contaDeAtendimento
          : {
              archiveAccount: async (tenantId) =>
                arquivarContaDoTenant({
                  bd: o.lote,
                  arquivo: new ArquivoDoChatwoot({
                    base: baseDoChatwoot,
                    tokenDaPlataforma: await cofre.get("chatwoot_platform_token"),
                    ...buscar,
                  }),
                  tenantId,
                  provedor: "chatwoot",
                }),
            },
    },
  };
}

/** A cadeia de ligação do `kamba_identity`, para os telefones da exportação (KAM-233). */
export const VARIAVEL_DA_IDENTIDADE_DO_LOTE = "KAMBA_LOTE_IDENTITY_DB_URL";

/**
 * Os telefones para a exportação do off-boarding (KAM-233; decisões do fundador
 * de 2026-11-21, Q2 = B, e de 2026-11-22, Q2b = A): o cofre de contactos como
 * `kamba_identity`, com a `kek_contact_dek` e **só** o `lerEndpoints` (o
 * arranque confere só a KEK, como o COM do KAM-206), e o STO do tenant com o
 * par de credenciais e o destino ADR-008 do ambiente — os mesmos do
 * `offboarding-dados`, que lê o objecto.
 *
 * **O papel confere-se antes**: uma `KAMBA_LOTE_IDENTITY_DB_URL` com outro papel
 * decifrava sob uma RLS que não é a do cofre. Uma falha aqui **não** derruba o
 * processo de lote — a casca regista-a e monta os telefones sem adaptador, e o
 * fecho dos `pendentes` pára nele, com alerta.
 */
export async function telefonesDoLote(o: {
  readonly identidades: PoolDaIdentidade & { query<T>(sql: string): Promise<{ readonly rows: readonly T[] }> };
  readonly ambiente: "dev" | "staging" | "prod";
  readonly env: Ambiente;
  /** O cofre. Por omissão, o do ambiente do processo (ADR-L002). */
  readonly cofre?: CofreLeitor;
  /** Portas para os ensaios. */
  readonly identidade?: Pick<Identidade, "lerEndpoints">;
  readonly armazenamento?: StorageProvider;
}): Promise<PortaDosTelefones> {
  const papel = await o.identidades.query<{ papel: string }>("SELECT current_user::text AS papel");
  if (papel.rows[0]?.papel !== "kamba_identity") {
    throw new PapelErradoError(VARIAVEL_DA_IDENTIDADE_DO_LOTE, "kamba_identity");
  }
  const env = o.env as NodeJS.ProcessEnv;
  const identidade =
    o.identidade ??
    (await Identidade.arrancar({ chaves: new EnvKeyProvider({ ambiente: o.ambiente, env }), env, soLeEndpoints: true }));
  const armazenamento =
    o.armazenamento ??
    criarStorageS3({
      config: lerConfigDoStorage({ ambiente: o.ambiente, env }),
      secrets: o.cofre ?? new EnvSecretProvider({ ambiente: o.ambiente, env }),
    });
  return telefonesPeloCofre({ pool: o.identidades, identidade, armazenamento });
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

/**
 * O aviso de uma sanção ao dono, **sem via**, pela razão do `AvisoSemVia`: o
 * `ServicoDeTrust` avisa por último, e o efeito fica por reaplicar.
 */
export class AvisoDeSancaoSemVia implements AvisoDeSancao {
  async avisar(_pedido: { readonly tenantId: string; readonly motivo: MotivoPublicoDaSancao }): Promise<void> {
    throw new AvisoDeSancaoSemDestinoError();
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
 * O escritor da decisão humana de screening: `kamba_batch`, dentro do
 * `comTenant` do tenant da linha, e **idempotente**.
 *
 * **O `kamba_batch` e não o `kamba_app`** (KAM-202, critério 6, decisão do
 * fundador de 2026-11-20): a base só aceita a `origem = 'humano'` do papel do
 * lote (*trigger* `screening_decision_humano_so_do_lote`). Era a aplicação que a
 * gravava, e uma linha `humano`/`permitida` levanta qualquer recusa de produto
 * no `assertPublishable` e na base — um defeito da aplicação podia publicar o que
 * a fila nunca aprovou.
 *
 * A idempotência é deste adaptador e não do `EscritorSql`, e é medida: a
 * `screening_decision` é *append-only* e sem unicidade sobre a chave, e o
 * `reaplicarEfeitos` corre o screening em **cada** volta enquanto o aviso (que
 * vem depois) falhar. Sem isto, um caso `categoria` aprovado ganhava uma linha
 * `humano`/`permitida` por minuto. Uma linha igual à última da chave — mesma
 * decisão, mesma origem — não se repete; uma diferente (o recurso que inverte a
 * primeira, ou uma decisão do motor pelo meio) grava-se.
 */
export function escritorHumanoDeScreening(lote: ConjuntoSql): EscritorDeDecisoes {
  return {
    async gravar(linha) {
      const ligacao = await lote.connect();
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

/**
 * Os onboardings da fila, com o recálculo da confiança **depois** de cada
 * aprovação (KAM-203, critério 3).
 *
 * O `aprovar` é a porta por onde passam as aprovações deste processo — a
 * decisão humana da fila e o varrimento do ciclo, e o `k1_ok` do KYC quando um
 * `ServicoKyc` for montado sobre o `aprovacaoDoKyc` daqui (hoje nenhum `src` o
 * monta) —, e é a mesma transacção que emite o `tenant.approved`. **Quem
 * aprovar por outro `OnboardingsSql`** (a consola `/equipa`, quando for ligada
 * à base) não passa por aqui: o tenant nasce na volta diária, e até lá não
 * cobra. Quando devolve `aprovado` a
 * transacção já confirmou, e o recálculo dá ao tenant o nível 0 antes de
 * qualquer cobrança: até ele correr não há nível, e sem nível o *trigger* da
 * cobrança recusa (KAM-096) — falha fechada, e nunca um tecto por omissão.
 *
 * **O `aoAprovar` não lança**: a aprovação já está feita, e uma falha do
 * recálculo não a pode fazer parecer recusada a quem a pediu. Quem o passa
 * conta e regista a falha; a volta diária repara-a.
 */
export class OnboardingsQueRecalculam extends OnboardingsSql {
  readonly #aoAprovar: (onboardingId: string) => Promise<void>;

  constructor(lote: ConjuntoSql, aoAprovar: (onboardingId: string) => Promise<void>) {
    super(lote);
    this.#aoAprovar = aoAprovar;
  }

  override async aprovar(
    id: string,
    evento: Parameters<OnboardingsSql["aprovar"]>[1],
    actor: string,
  ): ReturnType<OnboardingsSql["aprovar"]> {
    const r = await super.aprovar(id, evento, actor);
    if (r.estado === "aprovado") await this.#aoAprovar(id);
    return r;
  }
}

/**
 * O `depois` do consumidor de T&S (KAM-203, critério 2): o `order.delivered`,
 * já consumido, recalcula o tenant do evento. Corre **depois** do `COMMIT` do
 * consumo, numa ligação `kamba_batch` sua, e por isso vê a marca de consumo do
 * `order.paid` que dá a independência — que veio antes, na mesma partição.
 *
 * Uma falha **lança**: o BullMQ repete, a repetição chega como `duplicado`, e o
 * recálculo corre outra vez. A reentrega do mesmo evento recalcula outra vez e
 * não escreve nada, porque o recálculo é idempotente.
 */
export function depoisDoTrust(recalculo: Pick<RecalculoDaConfianca, "recalcular">) {
  return async (envelope: Envelope): Promise<void> => {
    if (envelope.tipo !== "order.delivered") return;
    await recalculo.recalcular(envelope.tenant_id, "entrega");
  };
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
  /** As métricas de T&S. Por omissão, uma instância nova. */
  readonly metricasDoTrust?: MetricasDoTrust;
  /** O aviso de uma sanção. Por omissão, o que não tem via (ver a nota do módulo). */
  readonly avisoDeSancao?: AvisoDeSancao;
  /** As métricas do recálculo da confiança. Por omissão, uma instância nova. */
  readonly metricasDaConfianca?: MetricasDaConfianca;
  /** As métricas do off-boarding. Por omissão, uma instância nova. */
  readonly metricasDoOffboarding?: MetricasDoOffboarding;
  /** As portas do off-boarding. Por omissão, as sem adaptador (ver a nota do módulo). */
  readonly portasDoOffboarding?: PortasDoCiclo;
}

/** O processo montado: o ciclo, o serviço da fila e o gancho do KAM-092. */
export interface ProcessoDeLote {
  readonly servico: ServicoDeRevisao;
  readonly ciclo: CicloDaFila;
  /** O T&S do lado do lote: o efeito das decisões da fila e o `fecharEncerramentos`. */
  readonly trust: ServicoDeTrust;
  /** As varreduras de T&S, para a casca agendar (KAM-200, critério 2). */
  readonly cicloDoTrust: CicloDoTrust;
  readonly metricasDoTrust: MetricasDoTrust;
  /** O recálculo da confiança de um tenant (KAM-203), para o consumidor de T&S. */
  readonly recalculo: RecalculoDaConfianca;
  /** A volta diária e a varredura das descidas, para a casca agendar. */
  readonly cicloDaConfianca: CicloDaConfianca;
  readonly metricasDaConfianca: MetricasDaConfianca;
  /** As fases do encerramento deste lado, para a casca agendar (KAM-210, critério 1). */
  readonly cicloDoOffboarding: CicloDoOffboarding;
  readonly metricasDoOffboarding: MetricasDoOffboarding;
  /** A activação dos casos, para a casca agendar (KAM-202, critério 2). */
  readonly cicloDaActivacao: CicloDaActivacao;
  /**
   * **O ponto onde o KAM-092 chama o `amostrar`** sobre cada aprovação
   * automática, que é ele quem conhece (critério 4). Corre neste processo, com
   * as credenciais de lote, e devolve o caso `auditoria` aberto quando a
   * aprovação cai na amostra — `null` fora da janela, fora da fracção, ou sem
   * `inicioDaAmostragem`.
   */
  aprovacaoAutomatica(onboardingId: string, tenantId: string): Promise<ResultadoDaAbertura | null>;
  /**
   * **A porta do `k1_ok`** (KAM-092): o `aprovacao` das dependências do
   * `ServicoKyc`. Aprova pela porta da base (`platform.advance_case`, como
   * `kamba_batch` sob o `app.tenant_id` do caso) e, sem intervenção humana,
   * passa a aprovação ao `aprovacaoAutomatica` acima.
   */
  readonly aprovacaoDoKyc: AprovacaoDoKyc;
}

/**
 * A fila sobre os adaptadores SQL. **Nenhum duplo em memória**: o repositório,
 * os onboardings, a auditoria, o leitor das métricas e o screening são SQL; o
 * que não é deste processo (cifra, dados pessoais, documentos) recusa em vez de
 * fingir, e o aviso levanta (ver a nota do módulo).
 */
export function montarProcesso(o: OpcoesDoProcesso): ProcessoDeLote {
  const metricasDaConfianca = o.metricasDaConfianca ?? new MetricasDaConfianca();
  const recalculo = new RecalculoDaConfianca({
    lote: o.lote,
    app: o.app,
    consumidorDeTrust: SUBSCRICAO_DO_TRUST.consumer,
    metricas: metricasDaConfianca,
    ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
  });
  const onboardings: OnboardingsSql = new OnboardingsQueRecalculam(o.lote, async (onboardingId) => {
    try {
      const ob = await onboardings.porId(onboardingId);
      if (ob === null) return;
      // **Só faz nascer.** A aprovação repete-se — a fila reaplica a decisão de
      // um caso já `aprovado` em cada volta enquanto o aviso ao dono não tiver
      // via —, e um recálculo por minuto e por caso só para dizer «sem mudança»
      // era tranca e duas ligações por nada (achado 5 da revisão adversarial).
      // Quem já tem nível é da volta diária e da varredura das descidas.
      if ((await o.lote.query(SQL_NIVEL_DO_TENANT, [ob.tenantId])).rows.length > 0) return;
      await recalculo.recalcular(ob.tenantId, "aprovacao");
    } catch {
      // A falha do recálculo já contou (`desfecho="falhou"`); só o nome do
      // passo vai para o registo, como no ciclo.
      o.log.warn({ outcome: "confianca_aprovacao_falhou" });
    }
  });
  const metricasDoTrust = o.metricasDoTrust ?? new MetricasDoTrust();
  // O T&S propõe sanções **à** fila e a fila aplica as decisões **pelo** T&S: um
  // precisa do outro. A fila do T&S é o serviço de revisão, lido quando é
  // chamada — antes de ele existir não há proposta nenhuma a abrir.
  let revisao: ServicoDeRevisao | undefined;
  const trust = new ServicoDeTrust({
    repositorio: new RepositorioDeTrustSql(o.lote, "lote"),
    tenants: new EstadoDosTenantsSql(o.lote),
    aviso: o.avisoDeSancao ?? new AvisoDeSancaoSemVia(),
    fila: {
      abrir: (p) => exigirRevisao(revisao).abrir(p),
      abrirRecurso: (casoId) => exigirRevisao(revisao).abrirRecurso(casoId),
    },
    contadores: metricasDoTrust,
    ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
  });
  const servico = new ServicoDeRevisao({
    repositorio: new RevisaoSql(o.lote, { conjunto: o.lote }),
    onboardings,
    auditoria: new AuditoriaSql(o.lote),
    aviso: new AvisoSemVia(),
    // Só o motivo: o caso e o tipo não estão na *allowlist* do registo, e quem
    // quer saber qual é lê a fila.
    alerta: (motivo) => o.log.warn({ outcome: motivo }),
    cifra: SEM_CIFRA,
    dados: SEM_DADOS,
    documentos: SEM_DOCUMENTOS,
    // KAM-202, critério 6: o `humano` só o grava o `kamba_batch`.
    screening: decisaoHumanaDeScreening(escritorHumanoDeScreening(o.lote)),
    // A mesma lista que o ciclo reaplica: o serviço marca antes dos efeitos.
    efeitos: o.efeitos,
    // KAM-200, critério 9: decidir um caso `trust` ou `recurso` aplica a sanção.
    trust,
    inicioDaAmostragem: o.inicioDaAmostragem ?? null,
    ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
  });
  revisao = servico;
  const cicloDoTrust = new CicloDoTrust({
    lote: o.lote,
    servico: trust,
    metricas: metricasDoTrust,
    ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
  });
  const ciclo = new CicloDaFila({
    servico,
    leitor: new LeitorDaFilaSql(o.lote),
    efeitos: o.efeitos,
    feriados: FERIADOS_POR_OMISSAO,
    // KAM-201: aprova o que já pode ser aprovado e ninguém aprovou — a última
    // condição do agregador (o aceite) não chama a porta.
    aprovar: (limite) =>
      varrerAprovacoes({
        cliente: o.lote,
        onboardings,
        amostrar: (onboardingId, tenantId) => servico.amostrar(onboardingId, tenantId),
        limite,
      }),
    // KAM-215: o caso avança até `es_concluido` pela porta da base, como
    // `kamba_batch`, e é aí que sai o `tenant.provisioned`.
    provisionar: (limite) => varrerProvisionamentos({ lote: o.lote, limite }),
    ...(o.limite === undefined ? {} : { limite: o.limite }),
  });
  const aprovacaoAutomatica = (onboardingId: string, tenantId: string) =>
    ciclo.aprovacaoAutomatica(onboardingId, tenantId);
  const metricasDoOffboarding = o.metricasDoOffboarding ?? new MetricasDoOffboarding();
  const cicloDoOffboarding = new CicloDoOffboarding({
    lote: o.lote,
    portas: o.portasDoOffboarding ?? {
      canal: CANAL_SEM_ADAPTADOR,
      revogacao: REVOGACAO_SEM_ADAPTADOR,
      telefones: TELEFONES_SEM_ADAPTADOR,
    },
    metricas: metricasDoOffboarding,
    ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
  });
  // KAM-202: a activação no lote, com a fila do teste falhado sobre o serviço
  // da fila deste processo.
  const cicloDaActivacao = new CicloDaActivacao({
    lote: o.lote,
    app: o.app,
    fila: (maquina) => filaDoTeste(servico, maquina),
    ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
  });
  return {
    servico,
    ciclo,
    trust,
    cicloDoTrust,
    metricasDoTrust,
    recalculo,
    cicloDaConfianca: new CicloDaConfianca({ lote: o.lote, recalculo }),
    metricasDaConfianca,
    cicloDoOffboarding,
    metricasDoOffboarding,
    cicloDaActivacao,
    aprovacaoAutomatica,
    aprovacaoDoKyc: aprovacaoDoKyc(onboardings, aprovacaoAutomatica),
  };
}

function exigirRevisao(s: ServicoDeRevisao | undefined): ServicoDeRevisao {
  if (s === undefined) throw new Error("a fila de revisao ainda nao esta montada");
  return s;
}

/**
 * **O consumidor de T&S** (KAM-200, critério 1): as dezasseis filas
 * `evt.trust.p<n>`, com o `efeitoDeTrust`, numa ligação `kamba_app` por fila —
 * a marca de consumo e os sinais confirmam juntos, sob a RLS do tenant do
 * envelope. `exigeOrdem`, porque dois dos sete tipos são `payment.*` (a
 * restrição `evt_subscricoes_payment_exige_ordem` da `0005`).
 *
 * **E com a máquina de estados das encomendas** (`orders_mirror`, a do
 * consumidor de pagamentos do COM): o `consumir` exige-a para os `payment.*`,
 * que têm estado pretendido, e lança sem ela. T&S não transita nada, mas a
 * pré-condição é a mesma: um pagamento sobre uma encomenda que a réplica ainda
 * não tem **adia**, e sobre uma já paga vai ao efeito como excepção (KAM-050).
 *
 * Aqui, e não na casca, para que o *gate* 4 veja o nome, as filas, o papel e as
 * métricas com que ele nasce. **O `criar` é obrigatório**, e é o
 * `criarTrabalhadores` que a casca importa dinamicamente depois de abrir a
 * porta: carregar o `bullmq` e o `ioredis` numa montagem do Windows leva dezenas
 * de segundos, e à cabeça do módulo atrasava a sonda do `/healthz`.
 */
export function consumidorDoTrust(o: {
  readonly urlDaApp: string;
  readonly urlDaFila: string;
  readonly metricasDoTrust: MetricasDoTrust;
  /** O recálculo que o `order.delivered` corre depois do consumo (KAM-203). */
  readonly recalculo: Pick<RecalculoDaConfianca, "recalcular">;
  readonly log: Pick<Logger, "info">;
  readonly criar: typeof criarTrabalhadores;
}): Trabalhadores {
  return o.criar({
    ligar: async () => {
      const cliente = new pg.Client({ connectionString: o.urlDaApp, application_name: "onboarding-lote:trust" });
      await cliente.connect();
      return cliente;
    },
    subscricao: SUBSCRICAO_DO_TRUST,
    filas: filasDe(SUBSCRICAO_DO_TRUST.consumer),
    efeito: efeitoDeTrust({ contadores: o.metricasDoTrust }),
    depois: depoisDoTrust(o.recalculo),
    maquina: new MaquinaNaBase("orders_mirror"),
    metricas: METRICAS,
    url: o.urlDaFila,
    // Só o desfecho: o `event_id` e a fila não estão na *allowlist* do registo.
    log: (dados) => o.log.info({ outcome: `trust_${String(dados["desfecho"])}` }),
  });
}

/**
 * O consumidor da resposta do AGR de canal `painel` (KAM-224), como `kamba_app`.
 *
 * A decisão 1 do fundador de 2026-11-19 (bloco do KAM-217) põe a resposta a
 * voltar ao painel pelo canal `painel`. O efeito marca a linha da
 * `agent_replies` como entregue, uma vez, sob a RLS do tenant do envelope; a
 * rota que a mostra ao dono é a `OwnerPort` do **KAM-223**. Corre aqui, e não no
 * `server.ts`, porque o servidor recusa `prod` e este processo não.
 */
export function consumidorDoPainel(o: {
  readonly urlDaApp: string;
  readonly urlDaFila: string;
  readonly log: Pick<Logger, "info">;
  readonly criar: typeof criarTrabalhadores;
}): Trabalhadores {
  return o.criar({
    ligar: async () => {
      const cliente = new pg.Client({ connectionString: o.urlDaApp, application_name: "onboarding-lote:painel" });
      await cliente.connect();
      return cliente;
    },
    subscricao: SUBSCRICAO_DO_PAINEL,
    filas: filasDe(SUBSCRICAO_DO_PAINEL.consumer),
    efeito: efeitoDoPainel({ aoTratar: (desfecho) => o.log.info({ outcome: `painel_${desfecho}` }) }),
    metricas: METRICAS,
    url: o.urlDaFila,
    log: (dados) => o.log.info({ outcome: `painel_consumo_${String(dados["desfecho"])}` }),
  });
}

/**
 * A linha de registo de uma volta. **Por nome de passo**, nunca pela mensagem do
 * erro (`../../../../packages/core-ts/src/revisao/ciclo.ts`).
 */
export function registarVolta(log: Pick<Logger, "info" | "error">, r: ResultadoDoCiclo): void {
  if (r.falhas.length === 0) log.info({ outcome: "ciclo_concluido" });
  else log.error({ outcome: "ciclo_com_falhas", error_code: r.falhas.join(",") });
}

/** A linha de registo de uma volta do off-boarding: pelo nome da fase, nunca pelo tenant. */
export function registarVoltaDoOffboarding(log: Pick<Logger, "info" | "error">, r: ResultadoDoCicloDoOffboarding): void {
  if (r.falhas.length === 0) log.info({ outcome: "offboarding_volta_concluida" });
  else log.error({ outcome: "offboarding_volta_com_falhas", error_code: r.falhas.join(",") });
}

/** A linha de registo de uma volta da activação (KAM-202): o que falhou, pelo passo. */
export function registarVoltaDaActivacao(log: Pick<Logger, "info" | "error">, r: ResultadoDoCicloDaActivacao): void {
  if (r.falhas.length === 0) log.info({ outcome: "activacao_volta_concluida" });
  else log.error({ outcome: "activacao_volta_com_falhas", error_code: r.falhas.join(",") });
}

/** A linha de registo de uma volta das varreduras de T&S: pelo nome da varredura. */
export function registarVoltaDoTrust(log: Pick<Logger, "info" | "error">, r: ResultadoDoCicloDoTrust): void {
  if (r.falhas.length === 0) log.info({ outcome: "trust_varreduras_concluidas" });
  else log.error({ outcome: "trust_varreduras_com_falhas", error_code: r.falhas.join(",") });
}

/** A linha de registo de uma volta da confiança: o que correu e falhou, em números. */
export function registarVoltaDaConfianca(
  log: Pick<Logger, "info" | "error">,
  qual: "diaria" | "descida",
  r: ResultadoDoCicloDaConfianca,
): void {
  if (r.falhas === 0) log.info({ outcome: `confianca_${qual}_concluida` });
  else log.error({ outcome: `confianca_${qual}_com_falhas`, error_code: "recalculo_falhou" });
}

/**
 * A aplicação HTTP do processo: a sonda e as métricas da fila, e mais nada.
 *
 * `/metrics` serve as quatro séries do dicionário §3.61 da **mesma** instância
 * que o ciclo recalcula; as de T&S (KAM-200) da mesma instância que o serviço,
 * o consumidor e as varreduras contam; e as do consumo de eventos (`METRICAS`
 * do KAM-006), que aqui são as do consumidor de T&S. Sem argumento, instâncias
 * vazias: é como o condutor da bateria X-01 a levanta nas sondas. As etiquetas
 * são domínios fechados e nenhuma leva tenant nem caso (`OBS-I`); o caso X-01
 * do `/metrics` mede-o com um caso de outro tenant na fila.
 */
export function criarApp(
  metricas: MetricasDaRevisao = new MetricasDaRevisao(),
  metricasDoTrust: MetricasDoTrust = new MetricasDoTrust(),
  metricasDaConfianca: MetricasDaConfianca = new MetricasDaConfianca(),
  metricasDoOffboarding: MetricasDoOffboarding = new MetricasDoOffboarding(),
): Hono {
  const app = new Hono();
  app.onError((_erro, c) => c.json({ error: "internal" }, 500));
  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  app.get("/metrics", (c) =>
    c.text(
      metricas.exposicao() +
        metricasDoTrust.exposicao() +
        metricasDaConfianca.exposicao() +
        metricasDoOffboarding.exposicao() +
        METRICAS.exposicao() +
        // KAM-219: o 42501 sobre o tecto, visto pelo `comTenant`/`comBatch` deste processo.
        METRICAS_DA_GUARDA.exposicao(),
      200,
      {
        "content-type": "text/plain; version=0.0.4; charset=utf-8",
      },
    ),
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
    // Uma volta corre em série, e o trinco empresta uma ligação de cada vez. A
    // da `app` serve o screening e a leitura dos pedidos do recálculo da
    // confiança (KAM-203), que toma **uma de cada conjunto** por tenant: a do
    // lote primeiro e só depois a da aplicação, pela mesma ordem em todos os
    // chamadores, para que dois recálculos não fiquem cada um com metade.
    max: 4,
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
  /** As portas do off-boarding (KAM-218). Por omissão, as sem adaptador. */
  readonly portasDoOffboarding?: PortasDoCiclo;
}): Promise<Arranque> {
  await verificarPapeis(o.lote, o.app);
  const processo = montarProcesso({
    lote: o.lote,
    app: o.app,
    efeitos: efeitosDoLote(o.lote),
    log: o.log,
    inicioDaAmostragem: o.inicioDaAmostragem,
    ...(o.portasDoOffboarding === undefined ? {} : { portasDoOffboarding: o.portasDoOffboarding }),
  });
  return {
    processo,
    app: criarApp(
      processo.ciclo.metricas,
      processo.metricasDoTrust,
      processo.metricasDaConfianca,
      processo.metricasDoOffboarding,
    ),
  };
}
