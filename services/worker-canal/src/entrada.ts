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
 * ## O encaminhador deste processo não encaminha, e isso é o âmbito
 *
 * Os quatro destinos existem como **costura**, não como implementação: o CHR é
 * KAM-014, o *stage* de *outbound* é KAM-015, a ingestão de coexistência é
 * KAM-017 e a gestão de canal está repartida entre KAM-016 e KAM-021. O que
 * este ticket entrega é a decisão de **para onde** cada `kind` vai, e a prova
 * de que ela é a do critério 8 — incluindo as duas propriedades negativas que
 * importam: um `statuses` nunca vai ao AGR, e um `history` nunca dispara
 * resposta. É o mesmo desenho do `consumidor.ts`, que traz o esqueleto com um
 * efeito que só registra, pela mesma razão: um tratador inventado aqui era
 * desenho de outro ticket escrito sem o seu critério de aceitação.
 *
 * O `EncaminhadorQueSoRegista` **conta** por destino, e é isso que o teste
 * exercita. Quem acrescentar um tratador troca a implementação e mais nada.
 *
 * ## A ligação é `kamba_app`, e nenhuma das duas tabelas tem RLS
 *
 * `inbound_events` e `unrouted_events` não têm `tenant_id` — o tenant só nasce
 * no CHR (KAM-014) —, pelo que não há contexto de tenant a pôr nem política a
 * cumprir. É a única escrita da plataforma nessa situação, e a revisão `0008`
 * explica porquê.
 */

import { serve } from "@hono/node-server";
import { healthz } from "@kamba/core-ts";
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
  sha256Hex,
  tratarCorpo,
} from "@kamba/core-ts/entrada";
import { instalar } from "@kamba/core-ts/logger";
import { Hono } from "hono";
import { Client } from "pg";

import { SERVICE, VERSION } from "./meta.ts";

const log = instalar(SERVICE);

/** A porta do `/metrics` deste processo. As outras são 3011 e 3012. */
export const PORTA_POR_OMISSAO = 3013;

const VARIAVEL_DA_BASE = "KAMBA_ENTRADA_DB_URL";
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

export function criarApp(): Hono {
  const app = new Hono();
  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));
  // **As metricas do *worker*, e nao as do GWY.** Serviam-se antes as cinco
  // de `entrada/metricas.ts`, que o GWY incrementa e este processo nao: saiam
  // `gwy_sig_fail 0` e `inbound_queue_depth -1` permanentes, a diluir qualquer
  // media e a por um `-1` ao lado do valor real do GWY — e do trabalho que
  // este processo faz de verdade nao saia nada. Achado da revisao adversarial.
  app.get("/metrics", (c) =>
    c.text(METRICAS_DO_WORKER.exposicao(), 200, {
      "content-type": "text/plain; version=0.0.4; charset=utf-8",
    }),
  );
  return app;
}

async function principal(): Promise<void> {
  const urlDaBase = exigir(VARIAVEL_DA_BASE);
  const urlDaFila = exigir(VARIAVEL_DA_FILA);

  const bd = new Client({ connectionString: urlDaBase });
  await bd.connect();

  const encaminhador = new EncaminhadorQueSoRegista();
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
    fetch: criarApp().fetch,
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
  await bd.end().catch(() => {});
}

if (import.meta.main) {
  await principal();
}
