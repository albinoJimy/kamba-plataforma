/**
 * As rotas do passo guiado do Embedded Signup (KAM-093).
 *
 *     GET  /ligar                 a página; exige a `sessao`, e `?r=` se vier
 *                                 tem de ser a retoma **do mesmo** caso
 *     GET  /api/es/estado         o estado visível e o pré-voo gravado
 *     POST /api/es/preflight      grava os atestados e devolve os sete itens
 *     POST /api/es/iniciar        capacidade e configuração do popup v4
 *     POST /api/es/cancelar       popup fechado
 *     POST /api/es/concluir       o `FINISH` do popup
 *     POST /api/es/pagamento      repete a verificação do `meta_pagamento`
 *     POST /api/es/retoma         sem sessão: manda o OTP ao telefone
 *                                 **registado** e devolve um bilhete
 *
 * ## A sessão é a única fonte do caso
 *
 * Nenhuma rota aceita um `onboarding_id` no corpo nem na consulta. O caso sai do
 * cookie `sessao` (KAM-086), que só se cunha depois de o OTP acertar — e é isso
 * que faz «a sessão do dono A não vê nem retoma o caso B» ser verdade por
 * construção e não por um `if`. A ligação de retoma (`?r=`) **não autentica**:
 * diz de que caso é a página, e se não for o da sessão a resposta é 403.
 *
 * ## O 403 não distingue forjado de alheio
 *
 * Uma retoma forjada, expirada, de outro caso, ou sem sessão ao lado dão todas o
 * mesmo 403 com o mesmo corpo. Distinguir era dizer a quem tenta se acertou na
 * assinatura de alguém.
 */

import { Hono } from "hono";
import { randomBytes } from "node:crypto";

import { GuiaRecusadoError, type PassoGuiado } from "@kamba/core-ts/guia";
import {
  type Otp,
  type Registo,
  ReferenciaInvalidaError,
  cookieDoCabecalho,
  cunharReferencia,
  lerReferencia,
} from "@kamba/core-ts/inscricao";
import type { Logger } from "@kamba/core-ts/logger";

import { cabecalhosDaLigacao, paginaDaLigacao, paginaDeRecusaDaLigacao } from "./pagina_guia.ts";

/** O que as rotas do guia precisam. */
export interface OpcoesDoGuia {
  readonly guia: PassoGuiado;
  readonly registo: Registo;
  readonly otp: Otp;
  readonly anelDaAssinatura: readonly (Uint8Array | null)[];
  /** O `appId` da app Meta, para o SDK. Identificador público, não segredo. */
  readonly appIdDaMeta: string;
  /** A versão da Graph, do `versaoDaGraph()` do KAM-016. */
  readonly versaoDaGraph: string;
  readonly relogio?: (() => Date) | undefined;
  readonly log?: Logger | undefined;
}

type Corpo = Record<string, unknown>;

async function corpoJson(pedido: Request): Promise<Corpo> {
  try {
    const bruto: unknown = await pedido.json();
    return typeof bruto === "object" && bruto !== null && !Array.isArray(bruto) ? (bruto as Corpo) : {};
  } catch {
    return {};
  }
}

function ler(
  fim: "sessao" | "retoma",
  bruto: unknown,
  anel: readonly (Uint8Array | null)[],
  relogio: () => Date,
): string | null {
  try {
    return lerReferencia(fim, bruto, anel, relogio);
  } catch (erro) {
    if (erro instanceof ReferenciaInvalidaError) return null;
    throw erro;
  }
}

/** O estado HTTP de uma recusa do guia. */
function estadoHttp(erro: GuiaRecusadoError): 404 | 409 {
  return erro.motivo === "sem_caso" ? 404 : 409;
}

/** Monta as rotas do guia. */
export function rotasDoGuia(opcoes: OpcoesDoGuia): Hono {
  const app = new Hono();
  const relogio = opcoes.relogio ?? ((): Date => new Date());
  const { guia, log } = opcoes;

  const sessaoDe = (cabecalho: string | undefined): string | null => {
    const valor = cookieDoCabecalho(cabecalho);
    return valor === null ? null : ler("sessao", valor, opcoes.anelDaAssinatura, relogio);
  };

  /** Corre uma operação do guia com a sessão, e traduz as recusas. */
  async function comSessao(
    cabecalho: string | undefined,
    fazer: (id: string) => Promise<unknown>,
  ): Promise<{ readonly estado: 200 | 403 | 404 | 409; readonly corpo: unknown }> {
    const id = sessaoDe(cabecalho);
    if (id === null) return { estado: 403, corpo: { erro: "token" } };
    try {
      return { estado: 200, corpo: await fazer(id) };
    } catch (erro) {
      if (!(erro instanceof GuiaRecusadoError)) throw erro;
      log?.info({ outcome: "es_recusado", error_code: erro.motivo });
      return { estado: estadoHttp(erro), corpo: { erro: erro.motivo } };
    }
  }

  app.get("/ligar", async (c) => {
    const nonce = randomBytes(12).toString("hex");
    const id = sessaoDe(c.req.header("cookie"));
    const r = c.req.query("r");
    // A retoma, se vier, tem de ser do caso da sessão. Ver a nota do módulo.
    const daRetoma = r === undefined ? null : ler("retoma", r, opcoes.anelDaAssinatura, relogio);
    if (id === null || (r !== undefined && daRetoma !== id)) {
      log?.info({ outcome: "ligar_recusado" });
      return c.html(paginaDeRecusaDaLigacao(), 403, cabecalhosDaLigacao(nonce));
    }
    try {
      await guia.abrir(id);
    } catch (erro) {
      if (!(erro instanceof GuiaRecusadoError)) throw erro;
      log?.info({ outcome: "ligar_recusado", error_code: erro.motivo });
      return c.html(paginaDeRecusaDaLigacao(), estadoHttp(erro), cabecalhosDaLigacao(nonce));
    }
    return c.html(paginaDaLigacao({ nonce, appId: opcoes.appIdDaMeta, versaoDaGraph: opcoes.versaoDaGraph }), 200, cabecalhosDaLigacao(nonce));
  });

  app.get("/api/es/estado", async (c) => {
    const r = await comSessao(c.req.header("cookie"), async (id) => {
      const g = await guia.abrir(id);
      return { estado: g.estado, preflight: g.preflight?.itens ?? null, rota: g.preflight?.rota ?? null };
    });
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/es/preflight", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    const r = await comSessao(c.req.header("cookie"), async (id) => {
      const p = await guia.preflight(id, {
        versaoDaApp: corpo.versao_da_app,
        appAbertaRecentemente: corpo.app_aberta_recentemente,
        numeroEmWhatsAppPessoal: corpo.numero_em_whatsapp_pessoal,
        cartaoInternacional: corpo.cartao_internacional,
        donoPresente: corpo.dono_presente,
      });
      return { itens: p.itens, pode_abrir: p.podeAbrir, rota: p.rota };
    });
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/es/iniciar", async (c) => {
    const r = await comSessao(c.req.header("cookie"), async (id) => guia.iniciar(id));
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/es/cancelar", async (c) => {
    const r = await comSessao(c.req.header("cookie"), async (id) => ({ estado: await guia.cancelar(id) }));
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/es/concluir", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    const r = await comSessao(c.req.header("cookie"), async (id) =>
      // **Quatro campos, e o `tenant_id` não é um deles**: sai do caso.
      guia.concluir(id, {
        code: corpo.code,
        waba_id: corpo.waba_id,
        phone_number_id: corpo.phone_number_id,
        session_info: corpo.session_info,
      }),
    );
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/es/pagamento", async (c) => {
    const r = await comSessao(c.req.header("cookie"), async (id) => guia.verificarPagamento(id));
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/es/retoma", async (c) => {
    // **Sem sessão**, e é o caso que esta rota existe para servir: o dono
    // recebeu a ligação por SMS dias depois, e a sessão de 24 h já morreu. A
    // ligação diz de que caso é; o OTP vai para o telefone **registado**, nunca
    // para um que o pedido traga — é o mesmo caminho de recuperação do
    // critério 8 do KAM-086, e o bilhete que sai daqui não autentica ninguém.
    const corpo = await corpoJson(c.req.raw);
    const id = ler("retoma", corpo.r, opcoes.anelDaAssinatura, relogio);
    if (id === null) return c.json({ erro: "token" }, 403);
    const telefone = await opcoes.registo.telefoneDoCaso(id);
    if (telefone === null) return c.json({ erro: "token" }, 403);
    const envio = await opcoes.otp.enviar(id, telefone);
    if (!envio.enviado) return c.json({ erro: "limite" }, 429);
    const chave = opcoes.anelDaAssinatura[0];
    if (!(chave instanceof Uint8Array)) return c.json({ erro: "indisponivel" }, 503);
    return c.json({ referencia: cunharReferencia("ticket", id, chave, relogio) }, 200);
  });

  return app;
}
