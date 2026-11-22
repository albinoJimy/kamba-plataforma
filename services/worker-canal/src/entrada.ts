/**
 * O processo que consome a fila de entrada do webhook (KAM-013).
 *
 * É o quarto processo do `worker-canal`, ao lado do `server.ts`, do
 * `publicador.ts` e do `consumidor.ts`, e a razão de ser um processo e não um
 * módulo do servidor é a mesma dos outros dois: escala com réplicas.
 *
 * ## O que faz
 *
 * 1. Levanta um *worker* BullMQ sobre a fila `wa-inbound`.
 * 2. Por cada *job*: descodifica o corpo, explode-o em eventos de canal,
 *    registra cada um em `inbound_events` com `ON CONFLICT DO NOTHING`,
 *    encaminha os novos pelo `kind` e põe em `unrouted_events` o que não
 *    encaixa. A decisão toda está em `@kamba/core-ts/entrada`; aqui monta-se.
 * 3. Serve `/healthz` e `/metrics`, como os outros dois.
 *
 * ## Um dos quatro destinos já encaminha; os outros três continuam costura
 *
 * O braço `chr` é o **CHR** (KAM-014): resolve o canal, aplica a guarda do
 * ADR-011 e a matriz de estados, resolve o contacto, abre a conversa e entrega
 * ao AGR ou ao dono. Os outros três continuam a existir como costura — o
 * *stage* de *outbound* é KAM-015, a ingestão de coexistência é KAM-017 e a
 * gestão de canal está repartida entre KAM-016 e KAM-021 —, e o que o KAM-013
 * entregou e continua a valer é a decisão de **para onde** cada `kind` vai,
 * incluindo as duas propriedades negativas que importam: um `statuses` nunca
 * vai ao AGR, e um `history` nunca dispara resposta.
 *
 * O `EncaminhadorQueSoRegista` fica, e é com ele que o teste do critério 8 do
 * KAM-013 continua a correr. Em produção o que se monta é o
 * `EncaminhadorDoCanal`, que delega `chr` no CHR e mantém os outros três a
 * contar.
 *
 * ## Quatro ligações, três papéis, e nenhuma faz o trabalho de outra
 *
 * `kamba_app` para a entrada (`inbound_events`, `unrouted_events`, e agora
 * `conversations`), `kamba_resolver` para a resolução de canal e para a guarda
 * de arranque, e `kamba_identity` para o contacto. É o padrão do
 * `consumidor.ts`, que já abre duas ligações com dois papéis; dar uma só — a de
 * `kamba_batch`, que vê tudo — resolvia tudo e era exactamente o que o ADR-015
 * recusa.
 *
 * `inbound_events` e `unrouted_events` não têm `tenant_id` — o tenant nasce no
 * CHR —, pelo que a escrita delas não leva contexto nem política; a
 * `conversations` tem as duas coisas, e por isso toda a escrita nela passa pelo
 * `comTenant`.
 *
 * ## A guarda do ADR-011 corre **antes** de o processo aceitar trabalho
 *
 * `verificarArranque` é a segunda metade do critério 5: «o arranque falha se
 * existir tal linha em produção». Corre com a ligação de `kamba_resolver` — o
 * único papel que prova que vê todas as linhas sem contornar a RLS — e levanta
 * antes de se criar o *worker* da fila. Com `KAMBA_FASE` ausente ou com outro
 * valor, levanta também: um valor desconhecido não desliga a guarda.
 */

import { serve } from "@hono/node-server";
import { healthz } from "@kamba/core-ts";
import {
  CONSUMIDOR_DO_CHR,
  Chr,
  type EntregaDoChr,
  METRICAS_DO_CHR,
  type RecepcaoDeMidia,
  ResolvedorDeCanal,
  efeitoDaActivacao,
  emitirContactMerged,
  repontarConversas,
  verificarArranque,
} from "@kamba/core-ts/chr";
import { criarFilaDoAgr } from "@kamba/core-ts/chr/fila";
import {
  FILA_ENTRADA,
  METRICAS_DO_WORKER,
  METRICA_EM_QUARENTENA,
  METRICA_ENTRADAS,
  METRICA_FALHAS,
  type Encaminhador,
  type EventoDeEntrada,
  type Registo,
  criarTrabalhadorDeEntrada,
  porEmQuarentena,
  sha256Hex,
  tratarCorpo,
} from "@kamba/core-ts/entrada";
import { METRICAS, filasDe } from "@kamba/core-ts/eventos";
import { criarTrabalhadores } from "@kamba/core-ts/eventos/trabalhador_bullmq";
import { EnvKeyProvider, Identidade } from "@kamba/core-ts/identity";
import { type Logger, instalar } from "@kamba/core-ts/logger";
import {
  type Buscar,
  ClienteDeMidiaDaGraph,
  type ClienteSql as ClienteSqlDoMed,
  type CofreDaMidia,
  Med,
  MetricasDoMed,
  tokenDaConversa,
} from "@kamba/core-ts/med";
import {
  type Ambiente,
  ArranqueAbortadoError,
  EnvSecretProvider,
  Secrets,
  isAmbiente,
} from "@kamba/core-ts/secrets";
import { type StorageConfig, type StorageProvider, criarStorageS3, lerConfig } from "@kamba/core-ts/storage";
import { METRICAS_DA_GUARDA, comTenant } from "@kamba/core-ts/tenant_guard";
import { Hono } from "hono";
import { Client } from "pg";

import { SERVICE, VERSION } from "./meta.ts";

const log = instalar(SERVICE);

/** A porta do `/metrics` deste processo. As outras são 3011 e 3012. */
export const PORTA_POR_OMISSAO = 3013;

const VARIAVEL_DA_BASE = "KAMBA_ENTRADA_DB_URL";
/**
 * A ligacao do **resolvedor de canal**, que e outro papel (KAM-014).
 *
 * `kamba_resolver`: `NOBYPASSRLS`, politica propria `resolver_leitura`,
 * `SELECT` em dez colunas de `tenant_channels` e de `tenants` e mais nada
 * (`docs/isolamento.md` §3). E o unico papel que pode responder
 * `phone_number_id -> tenant` **antes** de haver contexto, e e tambem com ele
 * que corre a guarda de arranque do ADR-011 — como `kamba_app`, a guarda
 * recusa-se a correr (`GuardaCega`) em vez de contar zero e arrancar.
 */
const VARIAVEL_DO_RESOLVEDOR = "KAMBA_CHR_RESOLVER_DB_URL";
/**
 * A ligacao da **identidade de contacto**, que e o terceiro papel (KAM-008).
 *
 * `kamba_identity` e o unico papel de servico com `SELECT` em
 * `contact_endpoints` e `contact_deks`. E tambem o papel em que corre o gancho
 * de fusao que reaponta conversas, porque a fusao e uma transacao dele.
 */
const VARIAVEL_DA_IDENTIDADE = "KAMBA_CHR_IDENTITY_DB_URL";
const VARIAVEL_DA_FILA = "KAMBA_QUEUE_URL";
const VARIAVEL_DA_PORTA = "ENTRADA_PORT";

function exigir(nome: string): string {
  const valor = process.env[nome];
  if (valor === undefined || valor.trim() === "") {
    throw new Error(`falta a variável de ambiente ${nome}`);
  }
  return valor;
}

function porta(): number {
  const bruto = process.env[VARIAVEL_DA_PORTA];
  if (bruto === undefined || bruto.trim() === "") return PORTA_POR_OMISSAO;
  const valor = Number(bruto);
  if (!Number.isInteger(valor) || valor < 1 || valor > 65_535) {
    throw new Error(`${VARIAVEL_DA_PORTA} inválida: ${bruto}`);
  }
  return valor;
}

/**
 * O encaminhador do esqueleto: conta por destino e mais nada.
 *
 * Exportado para o teste do critério 8, que é o que prova que `statuses` vai a
 * `outbound` e **não** ao CHR, e que `history` vai a `ingestao` e não dispara
 * resposta nenhuma. Os tratadores a sério são de outros tickets — ver a
 * docstring do módulo.
 */
export class EncaminhadorQueSoRegista implements Encaminhador {
  readonly entregues: EventoDeEntrada[] = [];

  async chr(evento: EventoDeEntrada): Promise<void> {
    this.entregues.push(evento);
  }

  async outbound(evento: EventoDeEntrada): Promise<void> {
    this.entregues.push(evento);
  }

  async ingestao(evento: EventoDeEntrada): Promise<void> {
    this.entregues.push(evento);
  }

  async gestaoDeCanal(evento: EventoDeEntrada): Promise<void> {
    this.entregues.push(evento);
  }
}

/**
 * O encaminhador de producao: o braco `chr` e o CHR, os outros tres contam.
 *
 * Herda do esqueleto de proposito, e nao o substitui: os tres destinos que ainda
 * nao tem tratador continuam a contar exactamente como contavam, e o teste do
 * criterio 8 do KAM-013 — «`statuses` vai a `outbound` e nao ao CHR», «`history`
 * nao dispara resposta» — continua a valer sobre esta classe.
 */
export class EncaminhadorDoCanal extends EncaminhadorQueSoRegista {
  readonly #chr: Chr;

  constructor(chr: Chr) {
    super();
    this.#chr = chr;
  }

  override async chr(evento: EventoDeEntrada): Promise<void> {
    this.entregues.push(evento);
    await this.#chr.tratar(evento);
  }
}

/**
 * A entrega do CHR: o AGR por fila, o dono por contador.
 *
 * O braco do dono **nao envia nada**, e isso e o ambito: o protocolo bot <-> dono
 * e KAM-018 e o espelho no Chatwoot e KAM-019. O que este ticket entrega e a
 * decisao de nao mandar ao AGR, e a prova de que ela se toma — o contador e o
 * que o teste do criterio 7 le. Um tratador inventado aqui era desenho de outro
 * ticket escrito sem o seu criterio de aceitacao, que e a mesma razao pela qual
 * o KAM-013 deixou os quatro destinos a contar.
 */
export class EntregaDoCanal implements EntregaDoChr {
  readonly #publicar: (invocacao: Parameters<EntregaDoChr["agr"]>[0]) => Promise<void>;
  /** Quantas mensagens foram para o dono/HND em vez do AGR. */
  aoDono = 0;
  /** Quantos turnos foram para o AGR. */
  aoAgr = 0;

  constructor(publicar: (invocacao: Parameters<EntregaDoChr["agr"]>[0]) => Promise<void>) {
    this.#publicar = publicar;
  }

  async agr(invocacao: Parameters<EntregaDoChr["agr"]>[0]): Promise<void> {
    await this.#publicar(invocacao);
    this.aoAgr += 1;
  }

  /**
   * Conta, e **nao registra**: quem registra e o CHR.
   *
   * Escreveu aqui uma linha `chr_ao_dono` enquanto o CHR escrevia
   * `chr_entregue_ao_dono` para o mesmo acontecimento — duas linhas por
   * entrega, com `outcome` diferentes, e um painel que conte por `outcome` a
   * contar a mesma entrega duas vezes. Achado da revisao adversarial.
   */
  async dono(): Promise<void> {
    this.aoDono += 1;
  }
}

export function criarApp(registo?: Logger): Hono {
  const app = new Hono();

  // Sem isto, o tratador de erro por omissao do Hono faz `console.error(err)`:
  // a mensagem e a pilha de qualquer erro iam em claro para o `stderr`, sem
  // passar pelo *logger* (KAM-068, `docs/logs.md` §3.3). O `publicador.ts` e o
  // `consumidor.ts` **nao** o tem, e sao anteriores a este ticket: ficam na
  // linha 46 de `docs/dividas-documentais.md`, com a do `hostname`.
  app.onError((erro, c) => {
    registo?.excepcao(erro, "tratador_falhou");
    return c.json({ error: "internal" }, 500);
  });

  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  // **As metricas do *worker*, e nao as do GWY.** Serviam-se antes as cinco
  // de `entrada/metricas.ts`, que o GWY incrementa e este processo nao: saiam
  // `gwy_sig_fail 0` e `inbound_queue_depth -1` permanentes, a diluir qualquer
  // media e a por um `-1` ao lado do valor real do GWY — e do trabalho que
  // este processo faz de verdade nao saia nada. Achado da revisao adversarial.
  // **As do *worker* e as do CHR**, nesta ordem. Os dois conjuntos sao de
  // dominios diferentes e nenhum sabe do outro (`entrada/metricas.ts` e
  // `chr/metricas.ts`), e o formato de exposicao do Prometheus e so texto: a
  // concatenacao e valida desde que nenhum nome apareca nas duas — e nao
  // aparece, `inbound_*` contra `chr_*`. Um registo central para os juntar e o
  // KAM-080.
  app.get("/metrics", (c) =>
    // KAM-219: e a recusa da base sobre o tecto, que o `comTenant` deste processo ve.
    // KAM-231: e as do MED, que corre neste processo desde que recebe a foto do dono.
    c.text(`${METRICAS_DO_WORKER.exposicao()}${METRICAS_DO_CHR.exposicao()}${METRICAS_DA_GUARDA.exposicao()}${METRICAS_DA_MIDIA.exposicao()}`, 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
}

/**
 * O ambiente do provedor de chaves de identidade, lido do `KAMBA_ENV`.
 *
 * **Era `KAMBA_ENV === "prod" ? "prod" : "dev"`, e isso impedia o arranque em
 * *staging* (KAM-187).** O `exigirAmbienteDoKeyProvider` do KAM-008 exige que o
 * ambiente declarado e o do provedor coincidam: `KAMBA_ENV=staging` dava um
 * provedor de `dev` e o processo saía com `AmbienteDeIdentidadeError`. Nenhum
 * compose corria este processo, pelo que ninguém o tinha visto.
 *
 * Um valor fora de `dev`/`staging`/`prod` devolve `dev` e **não** liga nada: o
 * `exigirAmbienteDoKeyProvider` recusa-o na mesma, porque compara com o valor
 * declarado e não com este.
 */
export function ambienteDasChaves(env: NodeJS.ProcessEnv): Ambiente {
  const declarado = (env.KAMBA_ENV ?? "").trim();
  return isAmbiente(declarado) ? declarado : "dev";
}

/**
 * O módulo de identidade deste processo, ou a recusa do arranque.
 *
 * As chaves vêm do ambiente que o lançador do cofre enche (ADR-L002), também em
 * `prod`: decisão do fundador, 2026-11-20, que emendou o critério 9 do KAM-008.
 * Em `prod` o `Identidade.arrancar` recusa sem a KEK ou sem a chave de pesquisa
 * — este processo resolve contactos, e usa as duas. Exportada para se medir o
 * arranque sem levantar o processo.
 */
export async function identidadeDaEntrada(env: NodeJS.ProcessEnv): Promise<Identidade> {
  return Identidade.arrancar({
    chaves: new EnvKeyProvider({ ambiente: ambienteDasChaves(env), env }),
    env,
  });
}

// ------------------------------------------------------------------ o MED
//
// KAM-231. A foto do dono passa pelo MED do KAM-020 **neste** processo: o CHR
// chama-o no braco do dono (`chr.ts`, passo 6b) e a invocacao leva o
// `asset_id`. Decisao do fundador de 2026-11-21 (P4, opcao A): o
// `worker-canal-entrada` recebe os segredos de que precisa, e em `staging` e
// `prod` recusa arrancar sem eles, como o consumidor do KAM-227. Recusadas: uma
// fila `med-inbound` propria, e a foto so pelo painel.

/** O nome com que este processo se apresenta ao cofre. */
export const SERVICO_DO_COFRE = "worker-canal-entrada";

/**
 * As metricas do MED deste processo. **Uma instancia**, e nao uma por `Med`: o
 * `recepcaoDeMidia` monta um `Med` por pedido, e cada um contava para o seu.
 */
export const METRICAS_DA_MIDIA = new MetricasDoMed();

/** A ligacao `kamba_app` do processo, como o `pg` a da. */
export interface LigacaoDaEntrada {
  query(texto: string, valores?: unknown[]): Promise<{ rows: unknown[] }>;
}

/**
 * O ambiente do MED, lido do `KAMBA_ENV`.
 *
 * Vazio e `dev`, como para as chaves de identidade (`ambienteDasChaves`). Um
 * valor desconhecido **recusa**, como o `ambienteDoOutbound` do consumidor: um
 * `producao` ou um `PROD` lido como `dev` desligava as recusas de arranque em
 * silencio.
 */
export function ambienteDaMidia(env: Readonly<Record<string, string | undefined>>): Ambiente {
  const declarado = (env["KAMBA_ENV"] ?? "").trim();
  if (declarado === "") return "dev";
  if (!isAmbiente(declarado)) {
    throw new Error(`KAMBA_ENV tem de ser dev, staging ou prod para a midia do ${SERVICO_DO_COFRE}`);
  }
  return declarado;
}

/**
 * A base do MED, com o contexto do tenant em **cada** instrucao.
 *
 * O MED nao poe o `app.tenant_id` (ver o `medDe` de `tests_bd/media.bd.test.ts`),
 * e a `media_assets` tem RLS com `FORCE`. **Uma transaccao por instrucao, e nao
 * uma a volta do `receber`**, por tres razoes:
 *
 * 1. a reserva em `pendente` tem de ficar confirmada **antes** da descarga — e
 *    ela que outro *worker* le para devolver `pendente` sem descarregar
 *    (`pipeline.ts`, passo 2); dentro de uma transaccao so, ele ficava a
 *    espera do *lock* da linha durante a descarga inteira;
 * 2. se o `put` correr e a marcacao falhar, a linha fica em `pendente` e e
 *    recuperavel, que e a ordem que o `pipeline.ts` escreve (passo 6 antes do
 *    7); um `ROLLBACK` da transaccao inteira apagava a reserva e deixava o
 *    objecto orfao;
 * 3. nenhuma transaccao fica aberta durante as idas a Meta.
 *
 * Corre na ligacao do processo, que o *worker* usa um *job* de cada vez
 * (`CONCORRENCIA = 1`), e **fora** de qualquer `comTenant` do CHR: o passo 6b
 * do `chr.ts` chama a midia depois de a transaccao da conversa fechar. Um
 * `comTenant` dentro de outro na mesma ligacao recusava (`LigacaoEmUsoError`).
 */
export function sqlDoTenant(ligacao: LigacaoDaEntrada, tenantId: string): ClienteSqlDoMed {
  return {
    query: async <T,>(texto: string, valores?: readonly unknown[]) => {
      const resultado = await comTenant(ligacao, tenantId, () =>
        ligacao.query(texto, valores === undefined ? [] : [...valores]),
      );
      return { rows: resultado.rows as readonly T[] };
    },
  };
}

export interface PortasDaMidia {
  readonly ligacao: LigacaoDaEntrada;
  readonly cofre: CofreDaMidia;
  readonly armazenamento: StorageProvider;
  /** O `fetch` da Graph. Porta para os ensaios. */
  readonly buscar?: Buscar;
  readonly log?: Logger;
  readonly metricas?: MetricasDoMed;
}

/**
 * A recepcao de midia que o CHR chama: um `Med` por pedido.
 *
 * Por pedido porque o *token* e o do **canal da conversa** do pedido
 * (`tokenDaConversa`), e a base e a do **tenant** do pedido (`sqlDoTenant`):
 * as duas portas fecham sobre o pedido, e o `Med` nao guarda estado entre
 * chamadas — as metricas, que guardavam, sao partilhadas.
 *
 * **O `avisarAgr` nao faz nada, e e de proposito.** O sinal do criterio 6 do
 * KAM-020 existe para o caminho em que a descarga corre **fora** do turno, e o
 * AGR nao sabe que a midia falhou. Aqui ela corre **dentro** do turno: o CHR
 * espera pelo resultado, e um `falhou` vai ao AGR na propria invocacao, sem
 * `asset_id` (`chr.ts`, passo 6b). Avisar tambem era um segundo *job* ao AGR
 * pela mesma mensagem — o dono recebia duas respostas. O MED regista o
 * `media_descarga_falhou` na mesma.
 */
export function recepcaoDeMidia(o: PortasDaMidia): RecepcaoDeMidia {
  const metricas = o.metricas ?? METRICAS_DA_MIDIA;
  return async (pedido) => {
    const bd = sqlDoTenant(o.ligacao, pedido.tenantId);
    const med = new Med({
      bd,
      armazenamento: o.armazenamento,
      midia: new ClienteDeMidiaDaGraph({
        token: tokenDaConversa({ cofre: o.cofre, bd, conversationId: pedido.conversationId }),
        ...(o.buscar === undefined ? {} : { buscar: o.buscar }),
      }),
      avisarAgr: async () => {},
      metricas,
      ...(o.log === undefined ? {} : { log: o.log }),
    });
    return await med.receber(pedido);
  };
}

export interface ArranqueDaMidia {
  readonly env: Readonly<Record<string, string | undefined>>;
  readonly ligacao: LigacaoDaEntrada;
  readonly log?: Logger;
  readonly buscar?: Buscar;
}

/**
 * A recepcao de midia deste processo, `undefined` em `dev` sem ela, ou a
 * recusa do arranque.
 *
 * - **`staging` e `prod`**: os tres segredos sao obrigatorios no
 *   `Secrets.arrancar` (`ArranqueAbortadoError` sem eles), e o armazenamento
 *   sem configuracao tambem aborta. Nunca se cai para «sem midia» em silencio.
 * - **`dev`**: sem a configuracao do armazenamento ou sem um dos tres
 *   segredos, o processo arranca **sem** midia — a foto vai ao AGR sem
 *   `asset_id`, como antes do KAM-231 — e regista **um** aviso.
 *
 * Exportada para se medir o arranque sem levantar o processo.
 *
 * @throws {ArranqueAbortadoError} em `staging`/`prod`, sem um dos segredos ou
 *   sem a configuracao do armazenamento.
 */
export async function midiaDaEntrada(a: ArranqueDaMidia): Promise<RecepcaoDeMidia | undefined> {
  const ambiente = ambienteDaMidia(a.env);
  const cofre = await Secrets.arrancar({
    servico: SERVICO_DO_COFRE,
    provider: new EnvSecretProvider({ ambiente, env: a.env }),
    // A KEK abre o criptograma do `token_ref` do canal; as duas do
    // armazenamento assinam o `put` no STO. Obrigatorias onde o inventario as
    // declara obrigatorias; em `dev` o processo arranca sem elas.
    obrigatorios: ambiente === "dev" ? [] : ["kek_token_cliente", "storage_access_key_id", "storage_secret_access_key"],
  });

  let config: StorageConfig;
  try {
    config = lerConfig({ ambiente, env: a.env });
  } catch (erro) {
    if (ambiente !== "dev") {
      // A mensagem do `lerConfig` nomeia as variaveis e nunca os valores.
      const motivo = erro instanceof Error ? erro.message : "configuracao ilegivel";
      throw new ArranqueAbortadoError(SERVICO_DO_COFRE, `armazenamento da midia: ${motivo}`);
    }
    a.log?.warn({ outcome: "midia_desligada_em_dev" });
    return undefined;
  }

  if (ambiente === "dev") {
    // Em `dev` nada e obrigatorio no arranque, e por isso pergunta-se aqui: um
    // processo que ligasse o MED sem a KEK falhava a primeira foto do dono em
    // vez de arrancar sem ela.
    const presentes = await Promise.all(
      [
        cofre.getRing("kek_token_cliente"),
        cofre.getRing("storage_access_key_id"),
        cofre.getRing("storage_secret_access_key"),
      ].map((leitura) => leitura.then(() => true, () => false)),
    );
    if (presentes.includes(false)) {
      a.log?.warn({ outcome: "midia_desligada_em_dev" });
      return undefined;
    }
  }

  return recepcaoDeMidia({
    ligacao: a.ligacao,
    cofre,
    armazenamento: criarStorageS3({ config, secrets: cofre }),
    ...(a.buscar === undefined ? {} : { buscar: a.buscar }),
    ...(a.log === undefined ? {} : { log: a.log }),
  });
}

async function principal(): Promise<void> {
  const urlDaBase = exigir(VARIAVEL_DA_BASE);
  const urlDaFila = exigir(VARIAVEL_DA_FILA);

  const urlDoResolvedor = exigir(VARIAVEL_DO_RESOLVEDOR);
  const urlDaIdentidade = exigir(VARIAVEL_DA_IDENTIDADE);

  const bd = new Client({ connectionString: urlDaBase });
  await bd.connect();
  const resolvedorBd = new Client({ connectionString: urlDoResolvedor });
  await resolvedorBd.connect();
  const identidadeBd = new Client({ connectionString: urlDaIdentidade });
  await identidadeBd.connect();

  // **A guarda do ADR-011, antes de tudo.** E a segunda metade do criterio 5 do
  // KAM-014, e corre antes de se criar o *worker*: um processo que aceite
  // trabalho e so depois descubra que ha Fluxo B na base ja tratou mensagens
  // por um canal que o Piloto nao autoriza. Levanta tambem se `KAMBA_FASE`
  // faltar ou tiver outro valor — um valor desconhecido nao desliga a guarda.
  await verificarArranque(resolvedorBd, process.env);

  const identidade = await identidadeDaEntrada(process.env);
  // O gancho que reaponta conversas numa fusao de contactos. Corre **dentro** da
  // transacao da fusao, com a ligacao e o contexto que o modulo de identidade
  // abriu — e e por isso que o `kamba_identity` tem privilegios por coluna na
  // `conversations` (revisao `0009`). Se lancar, a fusao inteira e desfeita.
  identidade.onContactMerge(async ({ cliente, tenantId, de, para }) => {
    await repontarConversas(cliente, tenantId, de, para);
  });

  // KAM-231: o MED, **antes** de o processo aceitar trabalho. Em `staging` e
  // `prod` recusa aqui sem os segredos ou sem o armazenamento; em `dev` sem
  // eles devolve `undefined`, e o CHR corre sem midia, como antes.
  const midia = await midiaDaEntrada({ env: process.env, ligacao: bd, log });
  if (midia !== undefined) log.info({ outcome: "midia_ligada" });

  const resolvedor = new ResolvedorDeCanal(resolvedorBd);
  // **O consumidor `chr` do `tenant.activated`** (KAM-201): corre aqui, e não
  // no `consumidor.ts`, porque a *cache* que ele esquece é a deste processo. O
  // consumo é `kamba_app` (a marca em `events_consumed` sob a RLS do tenant do
  // envelope), numa ligação por fila, como no `consumidor.ts`. Cada evento
  // chega a **uma** réplica: ver a nota do `chr/activacao.ts`.
  const activacoes = criarTrabalhadores({
    ligar: async () => {
      const cliente = new Client({ connectionString: urlDaBase });
      await cliente.connect();
      return cliente;
    },
    subscricao: { consumer: CONSUMIDOR_DO_CHR, exigeOrdem: false },
    filas: filasDe(CONSUMIDOR_DO_CHR),
    efeito: efeitoDaActivacao(resolvedor),
    metricas: METRICAS,
    url: urlDaFila,
    log: (dados) => log.info({ outcome: `activacao_${String(dados.desfecho)}` }),
  });
  const filaDoAgr = criarFilaDoAgr(urlDaFila);
  const entrega = new EntregaDoCanal((invocacao) => filaDoAgr.publicar(invocacao));

  const chr = new Chr({
    resolvedor,
    contacto: async (pedido) => {
      const resolvido = await identidade.resolveContact(identidadeBd, pedido);
      // O evento `contact.merged` que a fusao devolve e emitido por **quem
      // chama** (KAM-008, `docs/identidade.md` §4), e esse somos nos. Vai para
      // o outbox do KAM-005 com o papel `kamba_app` e contexto de tenant, e o
      // payload e mapeado para o contrato publicado — os nomes divergem, e o
      // `chr/eventos.ts` escreve porque.
      //
      // Emite-se **depois** da transacao da fusao ter confirmado, e o limite
      // esta dito em `docs/chr.md` §5: um `kill -9` entre o `COMMIT` da fusao e
      // esta emissao perde o evento. Pagar a atomicidade exigia dar ao
      // `kamba_identity` o `EXECUTE` do `evt_emitir`, isto e, deixar a
      // identidade emitir qualquer evento.
      if (resolvido.evento !== null) {
        const fusao = resolvido.evento;
        await comTenant(bd, fusao.tenant_id, () => emitirContactMerged(bd, fusao));
        log.info({ outcome: "contact_merged" });
      }
      return { contactId: resolvido.contactId };
    },
    entrega,
    quarentena: async (evento, motivo) =>
      porEmQuarentena(
        bd,
        {
          kind: "desconhecido",
          eventKey: evento.eventKey,
          motivo,
          wabaId: evento.wabaId,
          phoneNumberId: evento.phoneNumberId,
        },
        // **Sem corpo.** A quarentena do KAM-013 guarda o corpo porque sem ele
        // nao se diagnostica um JSON ilegivel; aqui o corpo e legivel e o que
        // falta e o canal — e guardar conteudo de conversa por causa de um
        // canal removido era guardar dados pessoais sem necessidade (ADR-010).
        null,
      ),
    metricas: METRICAS_DO_CHR,
    registar: (campos) => log.info(campos),
    // A ligacao fecha-se aqui e passa-se nos dois sitios: o `comTenant` poe o
    // contexto nela e o trabalho corre nela. Ver a nota de `ComTenant` — e a
    // forma que resolve a variancia dos dois `ClienteSql`, e deixa o CHR sem
    // nenhuma ligacao a mao fora de uma transacao com contexto.
    comTenant: (tenant, trabalho) => comTenant(bd, tenant, () => trabalho(bd)),
    ...(midia === undefined ? {} : { midia }),
  });

  const encaminhador = new EncaminhadorDoCanal(chr);
  // O `log` da biblioteca tem *allowlist* de campos (`docs/tecnica/08` §7.3), e
  // é o `tratarCorpo` que escolhe o que lá cabe: o `outcome`, o `msg_id` já
  // opaco e o `wa_type` da lista fechada. **Nada do corpo passa por aqui**.
  const registar: Registo = (campos) => log.info(campos);

  const consumo = criarTrabalhadorDeEntrada({
    url: urlDaFila,
    tratar: async (trabalho) => {
      // O resumo recalcula-se a partir do corpo, e não se lê do *job*: o
      // `jobId` é o mesmo valor, mas vem do BullMQ, e a `event_key` de um
      // corpo sem `entry` utilizável não deve depender de a fila ter
      // preservado o identificador do *job*.
      const resumo = sha256Hex(Buffer.from(trabalho.corpo, "base64"));
      await tratarCorpo(
        bd,
        trabalho,
        encaminhador,
        resumo,
        registar,
        (desfecho) => {
          // `quarentena` nao chega aqui: o `tratarCorpo` so chama este contador
          // para o que passou pelo `registarEvento`.
          if (desfecho !== "quarentena") {
            METRICAS_DO_WORKER.contar(METRICA_ENTRADAS, desfecho);
          }
        },
        (motivo) => METRICAS_DO_WORKER.contar(METRICA_EM_QUARENTENA, motivo),
      );
    },
    // Sai o codigo e a classe do erro, nunca a mensagem: um
    // `permission denied for table unrouted_events` nao leva conteudo, mas um
    // erro de `pg` pode levar a instrucao com os parametros, e os parametros
    // deste caminho sao o corpo do webhook.
    aoFalhar: (erro) => {
      METRICAS_DO_WORKER.contar(METRICA_FALHAS);
      log.excepcao(erro, "entrada_falhou");
    },
  });

  // `hostname` explicito, e nao a omissao do Node — que e `::`/`0.0.0.0`.
  // O `services/gwy/src/server.ts` fixa a regra e escreve a razao: `specs/01`
  // §6 principio 7 e o DoD do KAM-001, «nada alem de localhost». Correr este
  // processo a mao numa rede partilhada nao pode abrir o `/metrics` a essa
  // rede; dentro de um contentor e o `Dockerfile` que poe `HOST=0.0.0.0`.
  //
  // O `publicador.ts` e o `consumidor.ts` tem o defeito (sao anteriores a este
  // ticket, e esta na revisao adversarial do KAM-013); aqui segue-se o
  // `server.ts` e nao o padrao deles.
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

  // Os *workers* primeiro: fechar a ligação debaixo de um *job* a correr fazia
  // a escrita dele morrer a meio, e o evento voltava à fila. É a mesma ordem do
  // `trabalhador_bullmq.ts`, e pela mesma razão.
  await consumo.fechar();
  await activacoes.fechar();
  servidor.close();
  await filaDoAgr.fechar().catch(() => {});
  await bd.end().catch(() => {});
  await identidadeBd.end().catch(() => {});
  await resolvedorBd.end().catch(() => {});
}

if (import.meta.main) {
  await principal();
}
