/**
 * onboarding-web — aplicacao web do onboarding self-service
 *
 * Substitui a vitrine Next.js no Piloto (ADR-019). O registo, o OTP e o
 * anti-abuso são o KAM-086 e vivem em `./rotas.ts`; a página guiada do Embedded
 * Signup v4 é o KAM-093 e vive em `./guia.ts`; o painel do dono é o KAM-099 e
 * vive em `./painel/`. A troca do `code` é o KAM-016, no GWY, e não está aqui.
 *
 * Hono 4.13.x por decisão de `docs/tecnica/09` §3.1: o 5.0.0-rc.0 saiu a 2026-10-08 e
 * um *release candidate* não entra em produção (E4 §2.13).
 *
 * ## As rotas do registo são opcionais, e a razão não é conveniência
 *
 * O `createApp()` sem `inscricao` serve **só** a sonda. É o que permite ao
 * `/healthz` ser exercitado sem montar cofre, porta de SMS e repositório — e é
 * também o que mantém honesto o arranque: o `./server.ts` **falha** se as
 * chaves não existirem, em vez de subir um serviço que responde `200` no
 * `/healthz` e `503` em tudo o que é registo. Um serviço meio montado que
 * responde à sonda é um serviço que um balanceador manda tráfego para.
 */

import { Hono } from "hono";
import { healthz } from "@kamba/core-ts";
import type { Logger } from "@kamba/core-ts/logger";

import { SERVICE, VERSION } from "./meta.ts";
import { rotasDoGuia, type OpcoesDoGuia } from "./guia.ts";
import { rotasDoPainel, type OpcoesDoPainel } from "./painel/rotas.ts";
import { rotasDeInscricao, type OpcoesDasRotas } from "./rotas.ts";

export function createApp(
  log?: Logger,
  inscricao?: OpcoesDasRotas,
  guia?: OpcoesDoGuia,
  painel?: OpcoesDoPainel,
): Hono {
  const app = new Hono();

  // Sem isto, o tratador de erro por omissão do Hono faz `console.error(err)`:
  // a mensagem e a pilha de qualquer erro de um tratador iam em claro para o
  // `stderr`, sem passar pelo *logger* (KAM-068, `docs/logs.md` §3.3). Sai o
  // código e a classe, e a resposta não diz o que falhou.
  app.onError((erro, c) => {
    log?.excepcao(erro, "tratador_falhou");
    return c.json({ error: "internal" }, 500);
  });

  app.get("/healthz", (c) => c.json(healthz(SERVICE, VERSION)));

  if (inscricao !== undefined) app.route("/", rotasDeInscricao({ ...inscricao, log }));
  // O passo guiado do ES (KAM-093) monta-se ao lado, e só com a inscrição: a
  // página exige a sessão que o OTP cunha.
  if (inscricao !== undefined && guia !== undefined) app.route("/", rotasDoGuia({ ...guia, log }));
  // O painel do dono (KAM-099) também só com a inscrição: entra-se nele com a
  // sessão que o OTP cunha.
  if (inscricao !== undefined && painel !== undefined) app.route("/", rotasDoPainel({ ...painel, log }));

  return app;
}
