/**
 * Processo de lote do onboarding (KAM-198): `onboarding-lote` no compose.
 *
 *     node services/onboarding-web/src/lote.ts
 *
 * É um **segundo processo** da imagem do `onboarding-web`, como os quatro do
 * `worker-canal` (KAM-187), e não um serviço novo: partilha o pacote, o
 * `Dockerfile` e o `@kamba/core-ts/revisao`, e um serviço novo pagava manifesto,
 * imagem e entrada no `make smoke` para correr o mesmo módulo. Corre o ciclo da
 * fila de revisão com credenciais de lote, serve as métricas dela, e é onde o
 * KAM-092 liga o `amostrar` e a reconciliação da saga (KAM-091) vai correr.
 *
 * Esta é a casca: abre as duas ligações, verifica os papéis, serve a porta e
 * agenda o ciclo. Tudo o que pode errar em silêncio está em `./lote/processo.ts`,
 * com bateria própria.
 *
 * ## O que serve em HTTP
 *
 *     GET /healthz    a mesma carga útil dos outros processos
 *     GET /metrics    as quatro séries do dicionário §3.61
 *
 * Na porta `LOTE_PORT` (3014 por omissão) e em `127.0.0.1` por omissão: é o
 * `Dockerfile` que põe `HOST=0.0.0.0`, nunca o código.
 *
 * **E a rota interna do guia** (KAM-239), só com a `LOTE_INTERNO_PORT`: as oito
 * operações `POST /interno/guia/*` (`./lote/interno.ts`), noutra porta e no
 * anfitrião `LOTE_INTERNO_HOST` — nunca o `HOST` das métricas —, com a credencial
 * `onboarding_lote_token` obrigatória no arranque.
 *
 * ## Arranca em `prod`, e não arranca sem as credenciais
 *
 * Ao contrário do `server.ts`, que recusa `prod` por correr sobre repositórios em
 * memória, este processo corre sobre os adaptadores SQL e arranca em `prod`. Sem
 * a `KAMBA_LOTE_DB_URL` ou a `KAMBA_LOTE_APP_DB_URL`, ou com uma delas de outro
 * papel, **não arranca** — sai com código 1 antes de abrir a porta.
 */

import { serve } from "@hono/node-server";
import { INTERVALO_DA_CONFIANCA_POR_OMISSAO_MS } from "@kamba/core-ts/confianca";
import { instalar } from "@kamba/core-ts/logger";
import { EnvSecretProvider, Secrets } from "@kamba/core-ts/secrets";
import pg from "pg";

import { SERVICE } from "./meta.ts";
import { REF_DA_CREDENCIAL_DO_LOTE, servirRotaInterna } from "./lote/interno.ts";
import {
  arrancar,
  registarVoltaDoGuia,
  consumidorDoPainel,
  consumidorDoTrust,
  lerConfiguracao,
  opcoesDoConjunto,
  portasDoOffboarding,
  registarVolta,
  registarVoltaDaActivacao,
  registarVoltaDaConfianca,
  registarVoltaDoOffboarding,
  registarVoltaDoTrust,
} from "./lote/processo.ts";

const log = instalar(SERVICE);

async function principal(): Promise<void> {
  const config = lerConfiguracao(process.env);
  const lote = new pg.Pool(opcoesDoConjunto(config.urlDoLote, "lote"));
  const app = new pg.Pool(opcoesDoConjunto(config.urlDaApp, "app"));
  // Uma ligação **ociosa** que a base corta (um reinício, o
  // `idle_in_transaction_session_timeout`) chega como um `error` do conjunto, e
  // sem ouvinte é uma excepção não tratada que mata o processo. O `pg` já tira
  // a ligação do conjunto; aqui só se diz, pelo código do erro e não pela
  // mensagem.
  for (const conjunto of [lote, app]) {
    conjunto.on("error", (erro: Error & { code?: string }) =>
      log.warn({ outcome: "ligacao_perdida", error_code: erro.code ?? erro.name }),
    );
  }
  let arrancou = false;
  try {
    // KAM-239: a credencial da rota interna do guia, **obrigatória** com a porta
    // dela — o `Secrets.arrancar` sai antes de abrir porta nenhuma sem ela.
    const credencialDoGuia =
      config.interno === null
        ? null
        : await (
            await Secrets.arrancar({
              servico: SERVICE,
              provider: new EnvSecretProvider({ ambiente: config.ambiente }),
              obrigatorios: [REF_DA_CREDENCIAL_DO_LOTE],
            })
          ).get(REF_DA_CREDENCIAL_DO_LOTE);
    const { processo, app: http, interna } = await arrancar({
      lote,
      app,
      log,
      inicioDaAmostragem: config.inicioDaAmostragem,
      // KAM-218: a Meta ligada, com o *token* de cada WABA lido do cofre.
      portasDoOffboarding: portasDoOffboarding({ lote, ambiente: config.ambiente, env: process.env }),
      ...(config.interno === null || credencialDoGuia === null
        ? {}
        : { guia: { origem: config.interno.origem, credencial: credencialDoGuia } }),
    });
    // **Espera-se pela porta aberta antes de dizer `service_started`.** O
    // `serve` devolve antes de o `listen` acabar, e uma porta ocupada chegava
    // depois como um `error` sem ouvinte — uma excepção não tratada com o
    // `service_started` já escrito (medido no gate 8 do runner). Assim é um
    // arranque recusado, com o código do sistema no registo.
    const servidor = await new Promise<ReturnType<typeof serve>>((aberto, falhou) => {
      const s = serve(
        { fetch: http.fetch, hostname: process.env.HOST?.trim() || "127.0.0.1", port: config.porta },
        () => aberto(s),
      );
      s.once("error", (erro: Error & { code?: string }) => {
        log.error({ outcome: "porta_falhou", error_code: erro.code ?? erro.name });
        falhou(erro);
      });
    });
    // KAM-239: a rota interna do guia, **noutra porta e noutro anfitrião** — o
    // do compose só a rede `app` o resolve —, e nunca na das métricas.
    const rotaInterna = config.interno;
    const servidorInterno =
      interna === null || rotaInterna === null
        ? null
        : await servirRotaInterna(interna, rotaInterna).catch((erro: Error & { code?: string }) => {
            log.error({ outcome: "porta_interna_falhou", error_code: erro.code ?? erro.name });
            throw erro;
          });
    log.info({ outcome: servidorInterno === null ? "guia_interno_desligado" : "guia_interno_ligado" });
    // E a volta do guia que saiu do `onboarding-web`: os 30 minutos e a lista.
    const pararGuia =
      processo.guia === null ? () => {} : processo.guia.ciclo.agendar(config.intervaloMs, (r) => registarVoltaDoGuia(log, r));
    const parar = processo.ciclo.agendar(config.intervaloMs, (r) => registarVolta(log, r));
    // A primeira volta já, e não daqui a um intervalo: as métricas sairiam a
    // zero durante um minuto inteiro depois de cada arranque.
    void processo.ciclo.correr().then((r) => registarVolta(log, r));
    // KAM-200: as varreduras de T&S, a primeira volta também já.
    const pararTrust = processo.cicloDoTrust.agendar(config.intervaloDoTrustMs, (r) => registarVoltaDoTrust(log, r));
    void processo.cicloDoTrust.correr().then((r) => registarVoltaDoTrust(log, r));
    // KAM-203: a volta diária da confiança — a primeira já, para que um tenant
    // aprovado durante uma paragem não espere um dia pelo nível 0 — e a
    // varredura das descidas, ao ritmo do ciclo da fila. Uma volta que nem
    // chegou a listar os tenants diz-se pelo nome, e a seguinte corre.
    const falhouAConfianca = (): void =>
      log.error({ outcome: "confianca_volta_falhou", error_code: "confianca_volta_falhou" });
    const pararDiaria = processo.cicloDaConfianca.agendar(
      "correr",
      INTERVALO_DA_CONFIANCA_POR_OMISSAO_MS,
      (r) => registarVoltaDaConfianca(log, "diaria", r),
      falhouAConfianca,
    );
    void processo.cicloDaConfianca.correr().then((r) => registarVoltaDaConfianca(log, "diaria", r), falhouAConfianca);
    const pararDescidas = processo.cicloDaConfianca.agendar(
      "descer",
      config.intervaloMs,
      (r) => registarVoltaDaConfianca(log, "descida", r),
      falhouAConfianca,
    );
    // KAM-210: as fases do off-boarding deste lado, e as métricas das sete.
    const pararOffboarding = processo.cicloDoOffboarding.agendar(config.intervaloDoOffboardingMs, (r) =>
      registarVoltaDoOffboarding(log, r),
    );
    void processo.cicloDoOffboarding.correr().then((r) => registarVoltaDoOffboarding(log, r));
    // KAM-202: a activação dos casos — o catálogo mínimo, o teste e o `activar` —,
    // ao ritmo do ciclo da fila, que é o da janela do teste.
    const pararActivacao = processo.cicloDaActivacao.agendar(config.intervaloMs, (r) =>
      registarVoltaDaActivacao(log, r),
    );
    void processo.cicloDaActivacao.correr().then((r) => registarVoltaDaActivacao(log, r));
    // E o consumidor dos sete tipos de evento de T&S, como `kamba_app`. O
    // `bullmq` carrega-se aqui, com a porta já aberta (ver o `consumidorDoTrust`).
    const { criarTrabalhadores } = await import("@kamba/core-ts/eventos/trabalhador_bullmq");
    const consumo = consumidorDoTrust({
      urlDaApp: config.urlDaApp,
      urlDaFila: config.urlDaFila,
      metricasDoTrust: processo.metricasDoTrust,
      recalculo: processo.recalculo,
      log,
      criar: criarTrabalhadores,
    });
    // KAM-224: a resposta do AGR de canal `painel`, pelo mesmo barramento.
    const painel = consumidorDoPainel({
      urlDaApp: config.urlDaApp,
      urlDaFila: config.urlDaFila,
      log,
      criar: criarTrabalhadores,
    });
    arrancou = true;
    log.info({ outcome: "service_started" });
    await new Promise<void>((resolver) => {
      for (const sinal of ["SIGTERM", "SIGINT"] as const) process.once(sinal, () => resolver());
    });
    log.info({ outcome: "service_stopping" });
    parar();
    pararGuia();
    servidorInterno?.close();
    pararTrust();
    pararDiaria();
    pararDescidas();
    pararOffboarding();
    pararActivacao();
    // Os *workers* e as ligações que cada fila abriu — **com tecto**: com a fila
    // em baixo, fechar um *worker* espera por uma ligação que não vem, e um
    // `SIGTERM` que pendura é um contentor que o orquestrador mata à força.
    await Promise.race([
      Promise.all([consumo.fechar().catch(() => {}), painel.fechar().catch(() => {})]),
      new Promise<void>((pronto) => setTimeout(pronto, 10_000).unref()),
    ]);
    servidor.close();
  } finally {
    await Promise.allSettled([lote.end(), app.end()]);
    // Só quem arrancou pára: um arranque recusado diz-se pelo `arranque_falhou`.
    if (arrancou) log.info({ outcome: "service_stopped" });
  }
}

// `import.meta.main` (Node 24): o módulo também é importado pelos testes, e
// então não arranca nada.
if (import.meta.main) {
  principal()
    .catch((erro: unknown) => {
      log.excepcao(erro, "arranque_falhou");
      process.exitCode = 1;
    })
    // **Sai, e não espera que o *event loop* esvazie** (KAM-200): com a fila em
    // baixo, as tentativas de religação do `ioredis` dos *workers* que não
    // fecharam a tempo mantinham o processo vivo depois do `service_stopped`, e
    // um `SIGTERM` que não termina é um contentor morto à força. O código de
    // saída é o que ficou no `exitCode`.
    .finally(() => process.exit());
}
