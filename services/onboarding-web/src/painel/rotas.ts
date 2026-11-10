/**
 * As rotas do painel do dono (KAM-099).
 *
 *     GET   /painel/entrar          a sessão do registo (KAM-086) troca-se pela
 *                                   sessão do painel; 401 sem ela
 *     POST  /painel/sair            revoga a sessão do painel
 *     GET   /painel/produtos        a lista, com o formulário (critério 2)
 *     PATCH /painel/produtos/:id    preço e stock, com `Idempotency-Key` e versão
 *     GET   /painel/encomendas      só leitura, por estado e data (critério 6)
 *     GET   /painel/encomendas/:id  uma encomenda
 *     GET   /painel/canal           o estado do canal (critério 7)
 *
 * ## O tenant é o da sessão, e não há outro sítio de onde ele venha
 *
 * Nenhuma rota lê tenant do caminho, da consulta, do corpo ou de um cabeçalho.
 * O `:id` é um `sku` ou um `order_id`, e é **dentro do tenant da sessão** que se
 * procura: um `sku` de outro tenant não existe para este dono, e a resposta é
 * **404 e nunca 403** (critério 8) — um 403 dizia a quem tenta que acertou num
 * identificador alheio.
 *
 * ## A revogação vê-se duas vezes num `PATCH`
 *
 * À entrada, como em todas as rotas, e outra vez **imediatamente antes** de a
 * escrita ir ao COM. Um pedido que estava a meio quando a sessão foi revogada
 * — à espera da lista para o critério dos 50%, por exemplo — não grava. O que
 * já tinha chegado ao COM quando a revogação chegou acaba: o COM não tem forma
 * de desfazer uma transacção confirmada, e uma revogação não é um *rollback*.
 * Fica dito na verificação do bloco.
 *
 * ## Sem sessão é 401, e é o único 401
 *
 * «Sem sessão» não é «recurso alheio»: quem não se autenticou não aprende nada
 * com um 401, porque não chegou a perguntar por nenhum recurso de ninguém.
 */

import { Hono } from "hono";
import { randomBytes, randomUUID } from "node:crypto";

import { cookieDoCabecalho, lerReferencia, ReferenciaInvalidaError } from "@kamba/core-ts/inscricao";
import type { Logger } from "@kamba/core-ts/logger";

import type { LeitorDoCanal } from "./canal.ts";
import { ESTADOS_DA_ENCOMENDA, type Comercio, type EstadoDaEncomenda } from "./comercio.ts";
import { FORMA_DA_CHAVE, Idempotencia, type Guardada } from "./idempotencia.ts";
import { MetricasDoPainel, type MotivoDeErro, type RotaDoPainel } from "./metricas.ts";
import {
  cabecalhos,
  paginaDaEncomenda,
  paginaDeEncomendas,
  paginaDeProdutos,
  paginaDoCanal,
  paginaNaoEncontrada,
  paginaSemSessao,
} from "./pagina.ts";
import {
  cabecalhoDaSessao,
  cabecalhoQueApagaASessao,
  cookieDoPainel,
  cunharSessao,
  lerSessao,
  novaSessao,
  renovacao,
  type Revogacoes,
  type SessaoDoPainel,
} from "./sessao.ts";
import { lerPedido, pedeConfirmacao, PRECO_MAXIMO_KZ_POR_OMISSAO, variacaoPct } from "./validacao.ts";

/**
 * As fases do caso em que o tenant já existe, e por isso o painel abre.
 *
 * Do `aguarda_es` em diante: o provisionamento já correu, e o dono que ainda não
 * ligou o número precisa do painel para ver o estado do canal e o passo de
 * reconexão (critério 7). As fases terminais (`rejeitado`, `abandonado`,
 * `cancelado`) e as anteriores ao provisionamento não abrem.
 */
export const FASES_COM_PAINEL = ["aguarda_es", "lista_espera", "aguarda_catalogo", "aguarda_teste", "activo"] as const;

/** O tecto do corpo de um `PATCH`, em octetos. */
export const CORPO_MAXIMO_DO_PAINEL = 4 * 1024;

/** O que as rotas do painel precisam. */
export interface OpcoesDoPainel {
  readonly comercio: Comercio;
  readonly canal: LeitorDoCanal;
  readonly revogacoes: Revogacoes;
  /** Os casos do KAM-086: só para ler o tenant e a fase na entrada. */
  readonly casos: { porId(id: string): Promise<{ readonly tenantId: string; readonly fase: string } | null> };
  /** O anel da `segredo_onboarding_assinatura`: lê a `sessao` do KAM-086 e assina a do painel. */
  readonly anelDaAssinatura: readonly (Uint8Array | null)[];
  readonly idempotencia?: Idempotencia | undefined;
  readonly metricas?: MetricasDoPainel | undefined;
  /** O preço máximo em Kz (critério 5). */
  readonly precoMaximoKz?: bigint | undefined;
  readonly relogio?: (() => Date) | undefined;
  readonly log?: Logger | undefined;
}

type Corpo = Record<string, unknown>;

function nonce(): string {
  return randomBytes(12).toString("hex");
}

function json(corpo: unknown, estado: number, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(corpo), {
    status: estado,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

function html(corpo: string, estado: number, n: string, extra: Record<string, string> = {}): Response {
  return new Response(corpo, {
    status: estado,
    headers: { "content-type": "text/html; charset=utf-8", ...cabecalhos(n), ...extra },
  });
}

/** Um `bigint` sai como cadeia de dígitos. */
function semBigInt(valor: unknown): unknown {
  return JSON.parse(JSON.stringify(valor, (_k, v) => (typeof v === "bigint" ? v.toString() : v)));
}

/** Monta as rotas do painel. */
export function rotasDoPainel(opcoes: OpcoesDoPainel): Hono {
  const app = new Hono();
  const relogio = opcoes.relogio ?? ((): Date => new Date());
  const idempotencia = opcoes.idempotencia ?? new Idempotencia(() => relogio().getTime());
  const metricas = opcoes.metricas ?? new MetricasDoPainel();
  const maximoKz = opcoes.precoMaximoKz ?? PRECO_MAXIMO_KZ_POR_OMISSAO;
  const { comercio, log } = opcoes;

  const falhou = (rota: RotaDoPainel, motivo: MotivoDeErro): void => {
    metricas.erro(rota, motivo);
    log?.info({ outcome: "painel_recusado", error_code: motivo });
  };

  /**
   * A sessão do painel, verificada **e** confrontada com as revogadas, ou `null`.
   *
   * Devolve também o `Set-Cookie` da renovação, quando é altura dela. A
   * renovação só se calcula aqui, depois das duas verificações — ver o
   * `./sessao.ts`.
   */
  async function sessaoDe(cabecalho: string | undefined): Promise<{ s: SessaoDoPainel; renovar: Record<string, string> } | null> {
    const agora = relogio();
    const s = lerSessao(cookieDoPainel(cabecalho), opcoes.anelDaAssinatura, agora);
    if (s === null || (await opcoes.revogacoes.revogada(s))) return null;
    const nova = renovacao(s, agora);
    const chave = opcoes.anelDaAssinatura[0];
    if (nova === null || !(chave instanceof Uint8Array)) return { s, renovar: {} };
    return { s, renovar: { "set-cookie": cabecalhoDaSessao(cunharSessao(nova, chave)) } };
  }

  const actor = (s: SessaoDoPainel) => ({ id: s.dono, traceId: randomUUID() });

  app.get("/painel/entrar", async (c) => {
    metricas.pedido("entrar");
    const n = nonce();
    const bruto = cookieDoCabecalho(c.req.header("cookie"));
    let casoId: string | null = null;
    try {
      casoId = bruto === null ? null : lerReferencia("sessao", bruto, opcoes.anelDaAssinatura, relogio);
    } catch (erro) {
      if (!(erro instanceof ReferenciaInvalidaError)) throw erro;
    }
    const caso = casoId === null ? null : await opcoes.casos.porId(casoId);
    const chave = opcoes.anelDaAssinatura[0];
    if (caso === null || casoId === null || !(FASES_COM_PAINEL as readonly string[]).includes(caso.fase) || !(chave instanceof Uint8Array)) {
      falhou("entrar", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    const s = novaSessao(caso.tenantId, casoId, relogio());
    log?.info({ outcome: "painel_sessao_aberta" });
    return new Response(null, {
      status: 303,
      headers: { location: "/painel/produtos", "set-cookie": cabecalhoDaSessao(cunharSessao(s, chave)) },
    });
  });

  app.post("/painel/sair", async (c) => {
    metricas.pedido("sair");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao !== null) await opcoes.revogacoes.revogar(sessao.s.sid);
    log?.info({ outcome: "painel_sessao_revogada" });
    return html(paginaSemSessao(n), 200, n, { "set-cookie": cabecalhoQueApagaASessao() });
  });

  app.get("/painel/produtos", async (c) => {
    metricas.pedido("produtos");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("produtos", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    const r = await comercio.listarOfertas(sessao.s.tenantId, actor(sessao.s));
    if (r.tipo !== "ok") {
      falhou("produtos", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    return html(paginaDeProdutos(n, r.valor.itens, r.valor.truncada), 200, n, sessao.renovar);
  });

  app.patch("/painel/produtos/:id", async (c) => {
    metricas.pedido("gravar");
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("gravar", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    const { s, renovar } = sessao;
    // **Só JSON.** Um `<form>` de outra origem não consegue mandar
    // `application/json` sem *preflight*, e o `SameSite=Lax` já não lhe dava o
    // cookie num `PATCH`; as duas barreiras juntas fecham o CSRF.
    if (!(c.req.header("content-type") ?? "").toLowerCase().startsWith("application/json")) {
      falhou("gravar", "invalido");
      return json({ erro: "tipo_de_conteudo" }, 415, renovar);
    }
    const chave = c.req.header("idempotency-key") ?? "";
    if (!FORMA_DA_CHAVE.test(chave)) {
      falhou("gravar", "invalido");
      return json({ erro: "idempotency_key" }, 400, renovar);
    }
    const texto = await c.req.text();
    let corpo: Corpo;
    try {
      const lido: unknown = Buffer.byteLength(texto, "utf8") > CORPO_MAXIMO_DO_PAINEL ? null : JSON.parse(texto);
      if (typeof lido !== "object" || lido === null || Array.isArray(lido)) throw new Error("corpo");
      corpo = lido as Corpo;
    } catch {
      falhou("gravar", "invalido");
      return json({ erro: "corpo" }, 400, renovar);
    }
    const sku = c.req.param("id");
    const leitura = lerPedido(corpo, maximoKz);
    if (leitura.tipo === "erro") {
      falhou("gravar", "invalido");
      return json({ erro: "campo", campo: leitura.campo }, 400, renovar);
    }
    const pedido = leitura.pedido;
    const impressao = `${sku}\u0000${texto}`;

    const desfecho = await idempotencia.uma(s.tenantId, chave, impressao, async (): Promise<Guardada> => {
      const lista = await comercio.listarOfertas(s.tenantId, actor(s));
      if (lista.tipo !== "ok") return { estado: 503, corpo: { erro: "indisponivel" } };
      const antes = lista.valor.itens.find((o) => o.sku === sku);
      if (antes === undefined) return { estado: 404, corpo: { erro: "nao_encontrado" } };
      if (!pedido.confirmarVariacao && pedeConfirmacao(antes.precoMinor, pedido.precoMinor)) {
        return {
          estado: 422,
          corpo: { erro: "confirmacao", variacao_pct: String(variacaoPct(antes.precoMinor, pedido.precoMinor)) },
        };
      }
      // A segunda leitura da revogação: ver a nota do módulo.
      if (await opcoes.revogacoes.revogada(s)) return { estado: 401, corpo: { erro: "sessao" } };
      const r = await comercio.alterarOferta(s.tenantId, actor(s), {
        sku,
        precoTipo: pedido.precoTipo,
        precoMinor: pedido.precoMinor,
        versao: pedido.versao,
        ...(pedido.stock === undefined ? {} : { stock: pedido.stock }),
      });
      if (r.tipo === "ok") return { estado: 200, corpo: semBigInt({ versao: r.valor.versao, oferta: r.valor }) };
      if (r.tipo === "conflito") return { estado: 409, corpo: semBigInt({ erro: "conflito", versao: r.valor.versao, oferta: r.valor }) };
      if (r.erro === "NOT_FOUND") return { estado: 404, corpo: { erro: "nao_encontrado" } };
      if (r.erro === "VALIDATION_ERROR") return { estado: 400, corpo: { erro: "campo", campo: "pedido" } };
      return { estado: 503, corpo: { erro: "indisponivel" } };
    });

    if (desfecho.tipo === "reutilizada") {
      falhou("gravar", "invalido");
      return json({ erro: "idempotency_key_reutilizada" }, 422, renovar);
    }
    const { estado, corpo: resposta } = desfecho.resposta;
    const motivo: MotivoDeErro | null =
      estado === 404 ? "nao_encontrado" : estado === 409 ? "conflito" : estado === 422 ? "confirmacao"
        : estado === 401 ? "sem_sessao" : estado >= 500 ? "indisponivel" : estado >= 400 ? "invalido" : null;
    if (motivo !== null) falhou("gravar", motivo);
    if (estado === 200 && desfecho.tipo === "nova") log?.info({ outcome: "painel_oferta_gravada" });
    return json(resposta, estado, desfecho.tipo === "repetida" ? { ...renovar, "idempotent-replayed": "true" } : renovar);
  });

  app.get("/painel/encomendas", async (c) => {
    metricas.pedido("encomendas");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("encomendas", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    const estado = c.req.query("estado") ?? "aguarda_pagamento";
    const desde = c.req.query("desde") || null;
    const ate = c.req.query("ate") || null;
    const data = /^\d{4}-\d{2}-\d{2}$/;
    if (
      !(ESTADOS_DA_ENCOMENDA as readonly string[]).includes(estado) ||
      (desde !== null && !data.test(desde)) ||
      (ate !== null && !data.test(ate))
    ) {
      falhou("encomendas", "invalido");
      return html(paginaNaoEncontrada(n), 400, n, sessao.renovar);
    }
    const r = await comercio.listarEncomendas(sessao.s.tenantId, actor(sessao.s), { estado: estado as EstadoDaEncomenda });
    if (r.tipo !== "ok") {
      falhou("encomendas", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    // O filtro de data é sobre a página que o COM devolveu (até 100), e não
    // sobre o histórico inteiro: o `listOrders` do KAM-044 não filtra por data.
    const itens = r.valor.itens.filter((e) => {
      const dia = e.criadoAt.slice(0, 10);
      return (desde === null || dia >= desde) && (ate === null || dia <= ate);
    });
    return html(paginaDeEncomendas(n, { estado, desde, ate }, itens), 200, n, sessao.renovar);
  });

  app.get("/painel/encomendas/:id", async (c) => {
    metricas.pedido("encomenda");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("encomenda", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    const id = c.req.param("id").toLowerCase();
    const r = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id)
      ? await comercio.obterEncomenda(sessao.s.tenantId, actor(sessao.s), id)
      : ({ tipo: "erro", erro: "NOT_FOUND" } as const);
    if (r.tipo === "ok") return html(paginaDaEncomenda(n, r.valor), 200, n, sessao.renovar);
    const indisponivel = r.tipo === "erro" && r.erro !== "NOT_FOUND" && r.erro !== "VALIDATION_ERROR";
    falhou("encomenda", indisponivel ? "indisponivel" : "nao_encontrado");
    return html(paginaNaoEncontrada(n), indisponivel ? 503 : 404, n, sessao.renovar);
  });

  app.get("/painel/canal", async (c) => {
    metricas.pedido("canal");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("canal", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    return html(paginaDoCanal(n, await opcoes.canal.ler(sessao.s.tenantId)), 200, n, sessao.renovar);
  });

  return app;
}
