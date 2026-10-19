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
  Chr,
  type EntregaDoChr,
  METRICAS_DO_CHR,
  ResolvedorDeCanal,
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
import { EnvKeyProvider, Identidade } from "@kamba/core-ts/identity";
import { type Logger, instalar } from "@kamba/core-ts/logger";
import { comTenant } from "@kamba/core-ts/tenant_guard";
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
    c.text(`${METRICAS_DO_WORKER.exposicao()}${METRICAS_DO_CHR.exposicao()}`, 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
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

  const identidade = await Identidade.arrancar({
    chaves: new EnvKeyProvider({
      ambiente: process.env.KAMBA_ENV === "prod" ? "prod" : "dev",
    }),
  });
  // O gancho que reaponta conversas numa fusao de contactos. Corre **dentro** da
  // transacao da fusao, com a ligacao e o contexto que o modulo de identidade
  // abriu — e e por isso que o `kamba_identity` tem privilegios por coluna na
  // `conversations` (revisao `0009`). Se lancar, a fusao inteira e desfeita.
  identidade.onContactMerge(async ({ cliente, tenantId, de, para }) => {
    await repontarConversas(cliente, tenantId, de, para);
  });

  const resolvedor = new ResolvedorDeCanal(resolvedorBd);
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
  servidor.close();
  await filaDoAgr.fechar().catch(() => {});
  await bd.end().catch(() => {});
  await identidadeBd.end().catch(() => {});
  await resolvedorBd.end().catch(() => {});
}

if (import.meta.main) {
  await principal();
}
