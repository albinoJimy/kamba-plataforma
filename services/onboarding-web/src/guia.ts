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
 *     GET  /api/lista/posicao     a posição na lista de espera e a
 *                                 estimativa rotulada (KAM-095)
 *     POST /api/lista/convite     o convite `{c}` ainda vale para o caso da
 *                                 sessão? Só lê: gasta-se ao abrir o popup
 *     POST /api/lista/recusar     recusa-o: conta como uma expiração
 *     POST /api/lista/desistir    sai da lista; a posição liberta-se já
 *
 * As quatro da lista (KAM-095) só existem se o arranque lhes der uma
 * `ListaDeEspera`; sem ela respondem 404 **depois** da sessão, para que a
 * superfície e a recusa sejam as mesmas com e sem lista.
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

import { type ListaDeEspera, ListaRecusadaError, type Posicao } from "@kamba/core-ts/capacidade";
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
  /** A lista de espera (KAM-095), se o arranque a montou. */
  readonly lista?: ListaDeEspera | undefined;
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

/**
 * O estado HTTP de uma recusa da lista. O convite inválido é **403**, e o
 * mesmo para forjado, usado, vencido ou de outro caso (adversarial b).
 */
function estadoDaLista(erro: ListaRecusadaError): 403 | 409 {
  return erro.motivo === "convite_invalido" ? 403 : 409;
}

/**
 * A lista, ou a recusa de quem não a tem. Chama-se **dentro** do `comSessao`,
 * para que a sessão seja verificada primeiro.
 *
 * Fica no topo do módulo, e não ao lado do `comSessao`, por uma razão que não
 * é de estilo: a enumeração do X-01 (`tools/isolamento/enumeracao.py`) dá a
 * cada rota, como actor, a última função declarada antes dela — uma função
 * nova dentro do `rotasDoGuia` mudava o identificador das oito rotas do guia.
 */
function exigirLista(lista: ListaDeEspera | undefined): ListaDeEspera {
  if (lista === undefined) throw new GuiaRecusadoError("sem_caso");
  return lista;
}

/** A posição em JSON: datas em ISO, e o «sem estimativa» (infinito) a `null`. */
function posicaoEmJson(p: Posicao | null): unknown {
  if (p === null) return null;
  if (p.estado === "aguardando") {
    const finito = (n: number): number | null => (Number.isFinite(n) ? n : null);
    return {
      estado: p.estado,
      posicao: p.posicao,
      estimativa: {
        rotulo: p.estimativa.rotulo,
        minimo_dias: finito(p.estimativa.minimoDias),
        maximo_dias: finito(p.estimativa.maximoDias),
      },
    };
  }
  if (p.estado === "convidado") return { estado: p.estado, expira_em: p.expiraEm.toISOString() };
  return { estado: p.estado };
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
      // A reserva do `iniciar` passa pela lista: a recusa dela chega aqui.
      if (erro instanceof ListaRecusadaError) {
        log?.info({ outcome: "lista_espera_recusada", error_code: erro.motivo });
        return { estado: estadoDaLista(erro), corpo: { erro: erro.motivo === "convite_invalido" ? "token" : erro.motivo } };
      }
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
      return c.html(paginaDeRecusaDaLigacao(nonce), 403, cabecalhosDaLigacao(nonce));
    }
    try {
      await guia.abrir(id);
    } catch (erro) {
      if (!(erro instanceof GuiaRecusadoError)) throw erro;
      log?.info({ outcome: "ligar_recusado", error_code: erro.motivo });
      return c.html(paginaDeRecusaDaLigacao(nonce), estadoHttp(erro), cabecalhosDaLigacao(nonce));
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
      // **Três campos, e o `tenant_id` não é um deles**: sai do caso. O
      // `session_info` também não: compõe-o o guia, a partir da rota gravada.
      guia.concluir(id, {
        code: corpo.code,
        waba_id: corpo.waba_id,
        phone_number_id: corpo.phone_number_id,
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
    // A chave **antes** do envio: um 503 depois de mandar o SMS era um código
    // gasto que ninguém podia usar. E o caso tem de estar no passo do ES — uma
    // ligação de retoma de um caso que já não está em `aguarda_es` não tem
    // página a que voltar, e não serve para mandar SMS ao dono.
    const chave = opcoes.anelDaAssinatura[0];
    if (!(chave instanceof Uint8Array)) return c.json({ erro: "indisponivel" }, 503);
    try {
      await guia.abrir(id);
    } catch (erro) {
      if (!(erro instanceof GuiaRecusadoError)) throw erro;
      return c.json({ erro: "token" }, 403);
    }
    const telefone = await opcoes.registo.telefoneDoCaso(id);
    if (telefone === null) return c.json({ erro: "token" }, 403);
    const envio = await opcoes.otp.enviar(id, telefone);
    if (!envio.enviado) return c.json({ erro: "limite" }, 429);
    return c.json({ referencia: cunharReferencia("ticket", id, chave, relogio) }, 200);
  });

  app.get("/api/lista/posicao", async (c) => {
    const r = await comSessao(c.req.header("cookie"), async (id) => ({
      posicao: posicaoEmJson(await exigirLista(opcoes.lista).posicao(id)),
    }));
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/lista/convite", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    const r = await comSessao(c.req.header("cookie"), async (id) => {
      const { expiraEm } = await exigirLista(opcoes.lista).validarConvite(id, corpo.c);
      return { valido: true, expira_em: expiraEm.toISOString() };
    });
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/lista/recusar", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    const r = await comSessao(c.req.header("cookie"), async (id) => {
      await exigirLista(opcoes.lista).recusar(id, corpo.c);
      return { recusado: true };
    });
    return c.json(r.corpo, r.estado);
  });

  app.post("/api/lista/desistir", async (c) => {
    const r = await comSessao(c.req.header("cookie"), async (id) => {
      await exigirLista(opcoes.lista).desistir(id);
      return { desistiu: true };
    });
    return c.json(r.corpo, r.estado);
  });

  return app;
}
