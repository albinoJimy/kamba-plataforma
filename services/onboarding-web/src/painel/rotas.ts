/**
 * As rotas do painel do dono (KAM-099).
 *
 *     GET   /painel/entrar          a sessão do registo (KAM-086) troca-se pela
 *                                   sessão do painel; 401 sem ela
 *     POST  /painel/sair            revoga a sessão do painel
 *     GET   /painel/produtos        a lista, sem formulários (KAM-206)
 *     GET   /painel/produtos/:id    um produto, com o formulário (critério 2)
 *     PATCH /painel/produtos/:id    o preço, com `Idempotency-Key` e versão; o
 *                                   stock recusa-se — ver `./validacao.ts`
 *     GET   /painel/encomendas      só leitura, por estado e data (critério 6)
 *     GET   /painel/encomendas/:id  uma encomenda
 *     POST  /painel/encomendas/:id/contacto
 *                                   o contacto do cliente, mascarado, pedido pelo
 *                                   botão da encomenda e auditado no COM (KAM-206)
 *     GET   /painel/canal           o estado do canal (critério 7) e o canal do
 *                                   dono, o `owner_channel_wa` (KAM-216)
 *     POST  /painel/codigo          a reentrada (KAM-190): o telefone, e o código
 *                                   vai por SMS ao telefone registado
 *     POST  /painel/verificar       o código: acertou, e a sessão do painel é
 *                                   cunhada sem passar pela do registo
 *     GET   /painel/ligar           a reconexão (KAM-190): manda o código ao
 *                                   telefone registado e pede-o; o código certo
 *                                   abre o `/ligar` do KAM-093 — ao caso em
 *                                   `aguarda_es` e, desde o KAM-207, ao caso
 *                                   `activo` cujo canal caiu
 *     GET   /painel/telefone        a troca viva do tenant, se há (KAM-223)
 *     POST  /painel/telefone        a troca de telefone do dono (KAM-211): um
 *                                   número e qual é (`numero`: `novo`, por
 *                                   omissão, ou `antigo`), e o código vai a ele
 *     POST  /painel/telefone/verificar
 *                                   o número outra vez e o código: o do novo põe
 *                                   a troca pendente 72 h, o do antigo fá-la já
 *     POST  /painel/telefone/concluir
 *                                   passadas as 72 h, a troca faz-se sem o antigo
 *     POST  /painel/telefone/cancelar
 *                                   a troca viva do tenant cancela-se
 *     GET   /painel/social          a página Social (KAM-246): as artes aprovadas
 *                                   e entregues, a legenda para copiar e a ligação
 *                                   de descarga de 24 h, pedidas ao AGR
 *     GET   /painel/social/descarga a ligação aberta: 302 para um URL do STO de
 *                                   cinco minutos, ou 404 — ver `./social.ts`
 *     GET   /painel/conversa        a conversa do dono com o Assistente (KAM-223),
 *                                   depois de uma entrada (`?depois={id}`)
 *     POST  /painel/conversa        uma mensagem do dono ao Assistente
 *
 * ## A troca de telefone (KAM-211, com a regra C do KAM-223)
 *
 * As rotas ligam o OTP do KAM-086 à `TrocaDeTelefone` do KAM-118. **O papel só
 * muda depois de uma de duas provas**: o OTP do número antigo, ou 72 h
 * (*proposta*) com a troca pendente, avisada ao número antigo e ao e-mail, que
 * qualquer sessão do tenant cancela (decisão 3 do fundador de 2026-11-19, opção
 * C). Até lá o número novo é `cliente` como qualquer desconhecido, e o antigo
 * continua dono. A chave do pedido é a **sessão** — `troca:{sid}` —, e não um
 * campo do pedido: um dono não verifica o número novo pedido por outra sessão,
 * e o tenant é o da sessão como em todas as rotas. O código errado, expirado,
 * sem pedido, com tentativas a mais, de outro número ou de um número que não é o
 * do dono dá **401 {"erro":"codigo"}**, uma resposta só, pela razão do
 * `/painel/verificar`. **O estado vive na base** (`owner_phone_changes`, revisão
 * `0077`): um reinício a meio não perde a troca nem o código.
 *
 * ## A conversa do dono (KAM-223)
 *
 * O texto grava-se na fonte persistida e o AGR lê-o pelo identificador; a
 * resposta volta pelo evento `agent.replied` do canal `painel` (decisões 1 e 2
 * do fundador). A conversa é a do dono no WhatsApp — o mesmo `thread_id` —, e
 * nenhuma rota recebe o identificador dela: é a do tenant da sessão. O cursor
 * da leitura é o `id` de uma entrada, e um `id` que não é desta conversa dá
 * **404**.
 *
 * ## A reentrada não depende da sessão de 24 h do registo (KAM-190)
 *
 * O dono que só tem a sessão do painel — ou nenhuma, num telemóvel novo — entra
 * outra vez pelo telefone: `POST /painel/codigo` procura o caso **pelo HMAC do
 * telefone** e manda o código ao número **registado** (que é o submetido, por
 * construção do HMAC); `POST /painel/verificar` confere-o e cunha a sessão do
 * painel. As duas respostas não dizem se o telefone tem painel:
 *
 * ```text
 * /painel/codigo     200 com um bilhete, sempre — o de um telefone sem painel
 *                    aponta para um caso que não existe; o envio corre fora do
 *                    pedido, para o tempo de resposta não o denunciar
 * /painel/verificar  401 {"erro":"codigo"} a qualquer falha — errado, expirado,
 *                    sem desafio, tentativas a mais, ou caso sem painel
 * ```
 *
 * O bilhete tem separador próprio (`./sessao.ts`), e não serve no
 * `/api/otp/verificar` do registo, que distingue `sem_desafio` de `errou`. O que
 * **não** fecha, e é o mesmo do critério 8 do KAM-086: o SMS chega ou não chega
 * ao telefone, e isso vive fora da resposta. O limite por rede (`LIMITE_POR_REDE`)
 * é o que torna a sonda de telefones cara; os limites por destino e o orçamento
 * diário são os do `Otp`.
 *
 * ## A religação de um caso activo (KAM-207)
 *
 * A ponte do KAM-190 servia só o caso em `aguarda_es`. Um caso `activo` passa
 * por ela quando o COM diz que o canal está `desligado` **e não restrito** — o
 * `suspenso` e o `encerrado` chegam como `desligado` com `restrito`, e não
 * reabrem: são decisões nossas, que o dono não desfaz ligando o número outra
 * vez. A pergunta faz-se **duas vezes**, no `GET /painel/ligar` (antes de mandar
 * o SMS) e no `POST /painel/verificar` (antes de cunhar a sessão do registo),
 * porque entre as duas cabem dez minutos e uma suspensão. Só depois da segunda
 * o guia passa a `desligado` (`PassoGuiado.religar`), e é isso que abre o
 * `/ligar` a um caso activo. **O caso não muda de fase**, e o tenant é o do
 * caso. Sem a porta `religar` (o guia não está montado), o caso activo tem o
 * 409 de antes.
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

import {
  cabecalhoDoCookie,
  cabecalhoQueApaga,
  cookieDoCabecalho,
  cunharReferencia,
  DOMINIOS,
  hmacDe,
  IdentificadorInvalidoError,
  lerReferencia,
  prefixoDeIp,
  ReferenciaInvalidaError,
  Telefone,
  type Contadores,
  type Otp,
} from "@kamba/core-ts/inscricao";
import { canalNoPainel, type ConversaDoDono, type NumeroDaTroca, type TrocaDeTelefone } from "@kamba/core-ts/dono";
import { FASE_DA_RELIGACAO, GuiaRecusadoError } from "@kamba/core-ts/guia";
import type { Logger } from "@kamba/core-ts/logger";

import { csp } from "../pagina.ts";
import { enderecoDoPedido } from "../rotas.ts";
import type { LeitorDoCanal } from "./canal.ts";
import { ESTADOS_DA_ENCOMENDA, type Comercio, type EstadoDaEncomenda } from "./comercio.ts";
import { FORMA_DA_CHAVE, Idempotencia, type Guardada } from "./idempotencia.ts";
import { MetricasDoPainel, type MotivoDeErro, type RotaDoPainel } from "./metricas.ts";
import {
  cabecalhos,
  paginaDaEncomenda,
  paginaDeEncomendas,
  paginaDeProdutos,
  paginaDoProduto,
  paginaDaLigacaoFechada,
  paginaDoCanal,
  paginaDoCodigoDaLigacao,
  paginaDoSocial,
  paginaNaoEncontrada,
  paginaSemSessao,
} from "./pagina.ts";
import {
  cabecalhoDaSessao,
  cabecalhoQueApagaASessao,
  cookieDoPainel,
  cunharBilhete,
  cunharSessao,
  lerBilhete,
  lerSessao,
  novaSessao,
  renovacao,
  type Revogacoes,
  type SessaoDoPainel,
} from "./sessao.ts";
import { corpoDoSocial, cspComImagens, ligacaoComForma, origensDasImagens, type SocialDoPainel } from "./social.ts";
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

/**
 * Quantos pedidos de código por rede (o prefixo do IP do `inscricao`) numa janela.
 * ***Proposta***: 10 por hora — mais do que um dono com rede partilhada precisa, e
 * pouco para quem sonda telefones.
 */
export const LIMITE_POR_REDE = 10;
export const JANELA_DO_LIMITE_MS = 3_600_000;

/** O fuso de apresentação (§2): `Africa/Luanda`, UTC+1 sem hora de Verão. */
export const DESVIO_DE_LUANDA_MS = 3_600_000;

/**
 * O início, em UTC, de um dia de calendário de Luanda (`AAAA-MM-DD`), ou `null`
 * se o dia não existe (`2026-02-31`). O filtro do dono é por dias **dele**, e o
 * COM recebe instantes.
 */
export function inicioDoDiaEmLuanda(dia: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dia);
  if (m === null) return null;
  const [a, me, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const utc = new Date(Date.UTC(a, me - 1, d));
  if (utc.getUTCFullYear() !== a || utc.getUTCMonth() !== me - 1 || utc.getUTCDate() !== d) return null;
  return new Date(utc.getTime() - DESVIO_DE_LUANDA_MS);
}

/** O que a reentrada por código precisa (KAM-190). Sem ela, as duas rotas respondem 503. */
export interface OpcoesDaReentrada {
  readonly otp: Pick<Otp, "enviar" | "verificar">;
  /** O telefone registado de um caso (`Registo.telefoneDoCaso`), para o código da ligação. */
  readonly telefoneDoCaso: (id: string) => Promise<Telefone | null>;
  /** Os casos vivos com este HMAC de telefone (`RepositorioDeCasos.porTelefoneHmac`). */
  readonly casosPorTelefone: (hmac: string) => Promise<readonly { readonly id: string; readonly fase: string }[]>;
  /** O anel do `pepper_onboarding_ident`: cunha o HMAC do telefone e o da rede. */
  readonly anelDoPepper: readonly (Uint8Array | null)[];
  readonly contadores: Pick<Contadores, "anotar">;
  /** Quantos *proxies* de confiança há à frente. Zero por omissão (ver `../rotas.ts`). */
  readonly proxiesDeConfianca?: number | undefined;
  /**
   * Reabre o passo do ES a um caso `activo` cujo canal caiu
   * (`PassoGuiado.religar`, KAM-207). Sem ela, o caso activo tem o 409.
   */
  readonly religar?: ((id: string) => Promise<unknown>) | undefined;
}

/**
 * O canal do tenant caiu, e pode voltar? **KAM-207.** `true` só para `desligado`
 * **sem** `restrito`; `null` quando o COM não respondeu — e «não se sabe» não é
 * «caiu», pela razão do `./canal.ts`. Função do módulo, pela razão do
 * `redeDoPedido`.
 */
async function canalReligavel(canal: LeitorDoCanal, tenantId: string, casoId: string): Promise<boolean | null> {
  const vista = await canal.ler(tenantId, { id: casoId, traceId: randomUUID() });
  return vista === null ? null : vista.estado === "desligado" && !vista.restrito;
}

/**
 * O que a troca de telefone precisa (KAM-211). Sem ela, as duas rotas
 * respondem 503 — como a reentrada sem as suas.
 */
export interface OpcoesDaTroca {
  /** A `TrocaDeTelefone` do KAM-118, com o OTP, o contacto, a porta, os avisos e o estado na base. */
  readonly troca: Pick<TrocaDeTelefone, "pedir" | "verificar" | "estado" | "concluir" | "cancelar">;
  /** O anel do `pepper_onboarding_ident`: cunha o `Telefone` do número novo e o da rede. */
  readonly anelDoPepper: readonly (Uint8Array | null)[];
  /** Os contadores do limite por rede, como os da reentrada. */
  readonly contadores: Pick<Contadores, "anotar">;
  /** Quantos *proxies* de confiança há à frente. Zero por omissão. */
  readonly proxiesDeConfianca?: number | undefined;
  /**
   * O guia confirmou que o número da loja é o telefone do caso? (KAM-216.)
   *
   * O `canalDoDono` usa o `phone_hmac` do caso como HMAC do número da loja, e
   * isso só vale depois de o `confirmarNumero` do KAM-093 o ter comparado com o
   * `display_phone_number` (o `numeroConfirmado` do guia). Sem a confirmação, ou
   * sem esta porta, a troca guarda o painel: comparar com um número da loja que
   * ninguém confirmou podia mandar o dono para o WhatsApp do próprio telefone.
   */
  readonly numeroDaLojaConfirmado?: ((casoId: string) => Promise<boolean>) | undefined;
}

/**
 * A fase do caso em que a troca abre: **só `activo`** (achado 4 da revisão
 * adversarial do KAM-211). Antes disso o `tenant.provisioned` ainda não saiu, e
 * uma troca sem dono anterior criava o primeiro dono por `troca_de_telefone` —
 * e o provisionamento seguinte recusava com `23505`, deixando o dono a ser o
 * número da troca e não o verificado no registo.
 */
export const FASE_DA_TROCA = "activo";

/** A chave do pedido de troca de uma sessão. O prefixo separa-a do caso do OTP. */
export function pedidoDaTroca(s: SessaoDoPainel): string {
  return `troca:${s.sid}`;
}

/**
 * O que a conversa do dono precisa (KAM-223): a `ConversaDoDono`, com a ligação
 * `kamba_app` e a credencial do AGR. Sem ela, as duas rotas respondem 503.
 */
export interface OpcoesDaConversa {
  readonly conversa: Pick<ConversaDoDono, "enviar" | "ler">;
}

/**
 * O tecto do corpo de uma mensagem do dono, em octetos: 4096 caracteres de
 * texto, a quatro octetos no pior caso do UTF-8, e o JSON à volta.
 */
export const CORPO_MAXIMO_DA_CONVERSA = 4 * 4096 + 1024;

/** O `numero` de um pedido da troca: `novo` por omissão, `antigo`, ou `null` se é outra coisa. */
function numeroDaTroca(corpo: Corpo): NumeroDaTroca | null {
  const bruto = corpo["numero"];
  if (bruto === undefined) return "novo";
  return bruto === "novo" || bruto === "antigo" ? bruto : null;
}

/** A única fase em que o teste ponta a ponta se abre (KAM-094, passo 9). */
export const FASE_DO_TESTE = "aguarda_teste";

/**
 * O teste ponta a ponta pelo lado da página (KAM-202, critério 2): o `start` do
 * `SmokeOwnerAssisted`, com o caso e o tenant **da sessão**. Quem o fecha é o
 * processo de lote.
 */
export interface TesteDoPainel {
  iniciar(onboardingId: string, tenantId: string): Promise<{ readonly instrucoes: string; readonly expiraEm: Date }>;
}

/** O que as rotas do painel precisam. */
export interface OpcoesDoPainel {
  readonly comercio: Comercio;
  readonly canal: LeitorDoCanal;
  readonly revogacoes: Revogacoes;
  /**
   * Os casos do KAM-086: o tenant e a fase na entrada, e o `telefoneHmac`, que é
   * o HMAC do número da loja para a troca de telefone (`canalDoDono`, KAM-216).
   * Sem ele, a troca guarda o painel.
   */
  readonly casos: {
    porId(
      id: string,
    ): Promise<{ readonly tenantId: string; readonly fase: string; readonly telefoneHmac?: string } | null>;
  };
  /** O anel da `segredo_onboarding_assinatura`: lê a `sessao` do KAM-086 e assina a do painel. */
  readonly anelDaAssinatura: readonly (Uint8Array | null)[];
  readonly idempotencia?: Idempotencia | undefined;
  readonly metricas?: MetricasDoPainel | undefined;
  readonly reentrada?: OpcoesDaReentrada | undefined;
  readonly troca?: OpcoesDaTroca | undefined;
  readonly conversa?: OpcoesDaConversa | undefined;
  /**
   * O início do teste ponta a ponta (KAM-202, critério 2): abre a tentativa pela
   * ligação da aplicação. **Opcional**: sem ele, o `POST /painel/teste` responde
   * 503 e o resto do painel serve igual.
   */
  readonly teste?: TesteDoPainel | undefined;
  /**
   * A página Social (KAM-246): a lista e a ligação, pedidas ao AGR
   * (`socialPeloAgr`). **Opcional**: sem ela, as duas rotas respondem 503 e o
   * resto do painel serve igual.
   */
  readonly social?: SocialDoPainel | undefined;
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

/** O JSON de um valor com as chaves ordenadas, a qualquer profundidade. */
function canonico(valor: unknown): string {
  if (Array.isArray(valor)) return `[${valor.map(canonico).join(",")}]`;
  if (valor !== null && typeof valor === "object") {
    const pares = Object.keys(valor as Record<string, unknown>)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonico((valor as Record<string, unknown>)[k])}`);
    return `{${pares.join(",")}}`;
  }
  return JSON.stringify(valor);
}

/** Um `bigint` sai como cadeia de dígitos. */
function semBigInt(valor: unknown): unknown {
  return JSON.parse(JSON.stringify(valor, (_k, v) => (typeof v === "bigint" ? v.toString() : v)));
}

/**
 * O HMAC da rede de quem pede (o prefixo do IP, pela regra do `../rotas.ts`), para
 * a chave dos limites da reentrada. Função do módulo e não `const x = (` dentro
 * das rotas: a enumeração do *gate* 6 nomeia cada rota pela última função antes
 * dela, e as do painel são todas do `actor`.
 */
function redeDoPedido(
  c: { req: { header(n: string): string | undefined }; env?: unknown },
  r: Pick<OpcoesDaReentrada, "proxiesDeConfianca">,
  pepper: Uint8Array,
): string {
  const env = c.env as { incoming?: { socket?: { remoteAddress?: string } } } | undefined;
  const prefixo = prefixoDeIp(enderecoDoPedido(c.req.header("x-forwarded-for"), env?.incoming?.socket?.remoteAddress, r.proxiesDeConfianca ?? 0));
  return prefixo === null ? "sem-rede" : hmacDe(pepper, DOMINIOS.rede, prefixo).toString("hex");
}

/** O corpo JSON de um `POST` da reentrada, ou `null`. O tecto é o do `PATCH`, salvo outro. */
async function corpoDaReentrada(
  c: { req: { header(n: string): string | undefined; text(): Promise<string> } },
  maximo: number = CORPO_MAXIMO_DO_PAINEL,
): Promise<Corpo | null> {
  if (!(c.req.header("content-type") ?? "").toLowerCase().startsWith("application/json")) return null;
  const texto = await c.req.text();
  if (Buffer.byteLength(texto, "utf8") > maximo) return null;
  try {
    const lido: unknown = JSON.parse(texto);
    return typeof lido === "object" && lido !== null && !Array.isArray(lido) ? (lido as Corpo) : null;
  } catch {
    return null;
  }
}

/**
 * As duas recusas comuns às rotas da troca de telefone (KAM-211), por esta
 * ordem: a **fase** do caso (só `activo`, ver `FASE_DA_TROCA`) e o **limite por
 * rede** — o mesmo número da reentrada, noutra chave. Sem limite, uma sessão do
 * painel mandava SMS a números diferentes até esgotar o orçamento diário do
 * `Otp`, e com ele os códigos de todos os registos (achado 3 da revisão
 * adversarial). Função do módulo, pela razão do `redeDoPedido`.
 */
async function recusaDaTroca(
  c: { req: { header(n: string): string | undefined }; env?: unknown },
  t: OpcoesDaTroca,
  sessao: { readonly renovar: Record<string, string>; readonly fase: string },
  rota: "troca" | "troca_verificar" | "troca_concluir" | "troca_cancelar",
  agora: Date,
  falhou: (rota: RotaDoPainel, motivo: MotivoDeErro) => void,
): Promise<Response | null> {
  if (sessao.fase !== FASE_DA_TROCA) {
    falhou(rota, "conflito");
    return json({ erro: "fase" }, 409, sessao.renovar);
  }
  const pepper = t.anelDoPepper[0];
  const rede = pepper instanceof Uint8Array ? redeDoPedido(c, t, pepper) : "sem-pepper";
  if ((await t.contadores.anotar(`painel:${rota}:${rede}`, agora, JANELA_DO_LIMITE_MS)) > LIMITE_POR_REDE) {
    falhou(rota, "limite");
    return json({ erro: "limite" }, 429, sessao.renovar);
  }
  return null;
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
  async function sessaoDe(
    cabecalho: string | undefined,
  ): Promise<{
    s: SessaoDoPainel;
    renovar: Record<string, string>;
    fase: string;
    telefoneHmac: string | null;
  } | null> {
    const agora = relogio();
    const s = lerSessao(cookieDoPainel(cabecalho), opcoes.anelDaAssinatura, agora);
    if (s === null || (await opcoes.revogacoes.revogada(s))) return null;
    // **O caso lê-se outra vez a cada pedido.** Uma sessão de 30 dias sobre um
    // caso que entretanto foi `cancelado` ou `rejeitado` continuava a abrir o
    // catálogo até ao tecto; com esta leitura, mudar a fase do caso fecha o
    // painel no pedido seguinte. E o tenant tem de ser o do caso, e não só o
    // da assinatura. Achado da revisão adversarial.
    const caso = await opcoes.casos.porId(s.dono);
    if (caso === null || caso.tenantId.toLowerCase() !== s.tenantId) return null;
    if (!(FASES_COM_PAINEL as readonly string[]).includes(caso.fase)) return null;
    const nova = renovacao(s, agora);
    const chave = opcoes.anelDaAssinatura[0];
    const telefoneHmac = caso.telefoneHmac ?? null;
    if (nova === null || !(chave instanceof Uint8Array)) return { s, renovar: {}, fase: caso.fase, telefoneHmac };
    return {
      s,
      renovar: { "set-cookie": cabecalhoDaSessao(cunharSessao(nova, chave)) },
      fase: caso.fase,
      telefoneHmac,
    };
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
    if (sessao !== null) await opcoes.revogacoes.revogar(sessao.s);
    log?.info({ outcome: "painel_sessao_revogada" });
    // **Apaga as duas sessões, e não só a do painel.** A do registo (24 h) ficava
    // no navegador, e um `GET /painel/entrar` a seguir cunhava logo outra de 30
    // dias: num telemóvel partilhado, quem pegasse a seguir entrava. O valor da
    // do registo não se revoga (não tem lista), pelo que uma cópia dele vale até
    // às 24 h — e é esse o limite que fica. Achado da revisão adversarial.
    const r = html(paginaSemSessao(n), 200, n);
    r.headers.append("set-cookie", cabecalhoQueApagaASessao());
    r.headers.append("set-cookie", cabecalhoQueApaga());
    return r;
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

  // **Um produto, pelo `get-offer`** (KAM-206): o formulário do preço saiu da
  // lista, que era pesada de mais para um telemóvel em 3G. O `sku` procura-se no
  // tenant da sessão, e um `sku` de outro tenant é o mesmo 404 de um que não
  // existe (critério 8 do KAM-099).
  app.get("/painel/produtos/:id", async (c) => {
    metricas.pedido("produto");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("produto", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    const r = await comercio.obterOferta(sessao.s.tenantId, actor(sessao.s), c.req.param("id"));
    if (r.tipo === "ok") return html(paginaDoProduto(n, r.valor), 200, n, sessao.renovar);
    const indisponivel = r.tipo !== "erro" || (r.erro !== "NOT_FOUND" && r.erro !== "VALIDATION_ERROR");
    falhou("produto", indisponivel ? "indisponivel" : "nao_encontrado");
    return html(paginaNaoEncontrada(n), indisponivel ? 503 : 404, n, sessao.renovar);
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
    // A impressao e o corpo **canonico** (chaves ordenadas), e nao o texto: o
    // mesmo pedido com outro espacamento e o mesmo pedido.
    const impressao = `${sku}\u0000${canonico(corpo)}`;

    const desfecho = await idempotencia.uma(s.tenantId, chave, impressao, async (): Promise<Guardada> => {
      // **Uma oferta, e não a lista** (KAM-190): o preço anterior lê-se pelo
      // `get-offer` do COM, e uma oferta para lá da 200.ª deixou de dar 404.
      const lida = await comercio.obterOferta(s.tenantId, actor(s), sku);
      if (lida.tipo === "erro" && (lida.erro === "NOT_FOUND" || lida.erro === "VALIDATION_ERROR")) {
        return { estado: 404, corpo: { erro: "nao_encontrado" } };
      }
      if (lida.tipo !== "ok") return { estado: 503, corpo: { erro: "indisponivel" } };
      const antes = lida.valor;
      if (!pedido.confirmarVariacao && pedeConfirmacao(antes.precoMinor, pedido.precoMinor)) {
        return {
          estado: 422,
          corpo: { erro: "confirmacao", variacao_pct: String(variacaoPct(antes.precoMinor, pedido.precoMinor)) },
        };
      }
      // A segunda leitura da revogação: ver a nota do módulo.
      if (await opcoes.revogacoes.revogada(s)) return { estado: 401, corpo: { erro: "sessao" }, guardar: false };
      const r = await comercio.alterarOferta(s.tenantId, actor(s), {
        sku,
        precoTipo: pedido.precoTipo,
        precoMinor: pedido.precoMinor,
        versao: pedido.versao,
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
    const cursor = c.req.query("cursor") || null;
    // Os dias são de **Luanda** e o COM recebe instantes: `desde` é o início do
    // dia, e `ate` o início do dia seguinte (exclusive), pelo que o dia de `ate`
    // entra inteiro. O filtro aplica-se no COM, na consulta, e não à página que
    // ele devolve (KAM-190).
    const inicio = desde === null ? null : inicioDoDiaEmLuanda(desde);
    const fimDoDia = ate === null ? null : inicioDoDiaEmLuanda(ate);
    const fim = fimDoDia === null ? null : new Date(fimDoDia.getTime() + 86_400_000);
    if (
      !(ESTADOS_DA_ENCOMENDA as readonly string[]).includes(estado) ||
      (desde !== null && inicio === null) ||
      (ate !== null && fim === null) ||
      (inicio !== null && fim !== null && inicio >= fim) ||
      (cursor !== null && !/^[A-Za-z0-9_.-]{1,512}$/.test(cursor))
    ) {
      falhou("encomendas", "invalido");
      return html(paginaNaoEncontrada(n), 400, n, sessao.renovar);
    }
    const r = await comercio.listarEncomendas(sessao.s.tenantId, actor(sessao.s), {
      estado: estado as EstadoDaEncomenda,
      ...(cursor === null ? {} : { cursor }),
      ...(inicio === null ? {} : { criadoDesde: inicio.toISOString() }),
      ...(fim === null ? {} : { criadoAte: fim.toISOString() }),
    });
    if (r.tipo === "erro" && r.erro === "VALIDATION_ERROR") {
      // Um cursor que não é deste filtro: o COM prende o intervalo ao cursor.
      falhou("encomendas", "invalido");
      return html(paginaNaoEncontrada(n), 400, n, sessao.renovar);
    }
    if (r.tipo !== "ok") {
      falhou("encomendas", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    return html(paginaDeEncomendas(n, { estado, desde, ate }, r.valor.itens, r.valor.proximo), 200, n, sessao.renovar);
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

  // **O contacto do cliente, pelo botão** (KAM-206). Um `POST` e não um `GET`:
  // é uma acção do dono que fica no `audit_log`, e uma ligação que se abre por
  // engano, ou que um navegador pré-carrega, não a pode fazer. O cookie é
  // `SameSite=Lax`, que não vai num `POST` de outro **sítio** — mas um sítio é
  // mais largo do que uma origem, e por isso o `Sec-Fetch-Site` que o navegador
  // põe tem de ser `same-origin` (ou faltar, num cliente que não é navegador):
  // um formulário de outra origem do mesmo sítio não escreve uma linha de
  // `audit_log` em nome do dono. A encomenda lê-se primeiro (sem auditoria), e só
  // depois o contacto: uma encomenda que não existe não chega ao COM do
  // contacto. Fora da regra, ou de outro tenant, é o mesmo 404.
  app.post("/painel/encomendas/:id/contacto", async (c) => {
    metricas.pedido("contacto");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("contacto", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    const sitio = c.req.header("sec-fetch-site");
    if (sitio !== undefined && sitio !== "same-origin") {
      falhou("contacto", "invalido");
      return html(paginaNaoEncontrada(n), 403, n, sessao.renovar);
    }
    const id = c.req.param("id").toLowerCase();
    const lida = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id)
      ? await comercio.obterEncomenda(sessao.s.tenantId, actor(sessao.s), id)
      : ({ tipo: "erro", erro: "NOT_FOUND" } as const);
    const r = lida.tipo === "ok" ? await comercio.contactoDaEncomenda(sessao.s.tenantId, actor(sessao.s), id) : lida;
    if (lida.tipo === "ok" && r.tipo === "ok") {
      // Sem identificadores nem máscara: só o desfecho (`OBS-I`).
      log?.info({ outcome: "painel_contacto_mostrado" });
      return html(paginaDaEncomenda(n, lida.valor, r.valor), 200, n, sessao.renovar);
    }
    const indisponivel = r.tipo !== "erro" || (r.erro !== "NOT_FOUND" && r.erro !== "VALIDATION_ERROR");
    falhou("contacto", indisponivel ? "indisponivel" : "nao_encontrado");
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
    const vista = await opcoes.canal.ler(sessao.s.tenantId, actor(sessao.s));
    if (vista === null) {
      // Não se sabe: e «não se sabe» não é «desligado» (ver o `./canal.ts`).
      falhou("canal", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    // O canal do dono (KAM-216): o que a troca guardou, que o COM lê na mesma
    // linha do canal e com o mesmo tenant da sessão.
    return html(paginaDoCanal(n, vista, canalNoPainel(vista.ownerChannelWa, vista.estado)), 200, n, sessao.renovar);
  });

  // ------------------------------------------------- a página Social (KAM-246)

  app.get("/painel/social", async (c) => {
    metricas.pedido("social");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("social", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    if (opcoes.social === undefined) {
      falhou("social", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    // O tenant é o da sessão, e não há outro sítio de onde venha.
    const r = await opcoes.social.itens(sessao.s.tenantId);
    if (r.tipo !== "ok") {
      falhou("social", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    // A CSP desta página, e só desta, deixa as imagens vir das origens dos URLs do STO.
    const politica = cspComImagens(csp(n), origensDasImagens(r.valor));
    return html(paginaDoSocial(n, corpoDoSocial(r.valor)), 200, n, {
      ...sessao.renovar,
      "Content-Security-Policy": politica,
    });
  });

  app.get("/painel/social/descarga", async (c) => {
    metricas.pedido("social_descarga");
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("social_descarga", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    const ligacao = c.req.query("l");
    if (!ligacaoComForma(ligacao)) {
      // A mesma página de uma ligação recusada: a forma também não se diz.
      falhou("social_descarga", "nao_encontrado");
      return html(paginaNaoEncontrada(n), 404, n, sessao.renovar);
    }
    if (opcoes.social === undefined) {
      falhou("social_descarga", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    const r = await opcoes.social.abrir(sessao.s.tenantId, ligacao);
    if (r.tipo === "recusada") {
      // Expirada, adulterada ou de outro tenant: a mesma resposta, sem dizer se o item existe.
      falhou("social_descarga", "nao_encontrado");
      return html(paginaNaoEncontrada(n), 404, n, sessao.renovar);
    }
    if (r.tipo !== "ok") {
      falhou("social_descarga", "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    // O URL do STO vale cinco minutos; a ligação de 24 h fica com o dono.
    return new Response(null, {
      status: 302,
      headers: { location: r.valor, "cache-control": "no-store", "referrer-policy": "no-referrer", ...sessao.renovar },
    });
  });

  // ------------------------------------------- a reconexão e a reentrada (KAM-190)

  app.get("/painel/ligar", async (c) => {
    const n = nonce();
    const sessao = await sessaoDe(c.req.header("cookie"));
    const r = opcoes.reentrada;
    const chave = opcoes.anelDaAssinatura[0];
    if (sessao === null) {
      metricas.pedido("ligar");
      falhou("ligar", "sem_sessao");
      return html(paginaSemSessao(n), 401, n);
    }
    // **A religação conta à parte** (KAM-207): `religar` é a ponte pedida por
    // um caso activo, `ligar` a de um caso que ainda não ligou o número. As
    // duas somam os pedidos desta rota; a de sem sessão conta em `ligar`,
    // porque sem sessão não há caso.
    const rota: RotaDoPainel = sessao.fase === FASE_DA_RELIGACAO ? "religar" : "ligar";
    metricas.pedido(rota);
    if (r === undefined || !(chave instanceof Uint8Array)) {
      falhou(rota, "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    // **A sessão do painel não cunha a do registo.** A primeira versão desta
    // rota fazia-o, e a revisão adversarial mediu o ciclo que isso abria: painel
    // → `sessao` do registo → `/painel/entrar` → painel novo, com `sid` novo e
    // `emitida` de agora — o tecto de 90 dias e as duas revogações deixavam de
    // valer, e um cookie roubado vivia para sempre. Agora a ponte pede o código:
    // a sessão do painel diz **de que caso** é, e o OTP ao telefone registado
    // prova a posse, como na entrada.
    //
    // **E só para um caso no passo do ES** (`aguarda_es`), ou activo com o canal
    // caído e não restrito (KAM-207): são os dois em que o `/ligar` do KAM-093
    // vai abrir. Mandar um SMS para uma página que recusa era gastar o código do
    // dono.
    const caso = await opcoes.casos.porId(sessao.s.dono);
    let abre = caso !== null && caso.fase === "aguarda_es";
    if (caso !== null && caso.fase === FASE_DA_RELIGACAO && r.religar !== undefined) {
      const religavel = await canalReligavel(opcoes.canal, sessao.s.tenantId, sessao.s.dono);
      if (religavel === null) {
        falhou(rota, "indisponivel");
        return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
      }
      abre = religavel;
    }
    if (!abre) {
      falhou(rota, "conflito");
      return html(paginaDaLigacaoFechada(n), 409, n, sessao.renovar);
    }
    const telefone = await r.telefoneDoCaso(sessao.s.dono);
    if (telefone === null) {
      falhou(rota, "indisponivel");
      return html(paginaNaoEncontrada(n), 503, n, sessao.renovar);
    }
    void r.otp
      .enviar(sessao.s.dono, telefone)
      .then((e) => {
        if (!e.enviado) log?.info({ outcome: "painel_codigo_nao_enviado", error_code: e.recusa });
      })
      .catch((erro: unknown) => log?.excepcao(erro, "painel_codigo_falhou"));
    log?.info({ outcome: rota === "religar" ? "painel_religar" : "painel_ligar" });
    return html(paginaDoCodigoDaLigacao(n, cunharBilhete(sessao.s.dono, chave, relogio())), 200, n, sessao.renovar);
  });

  app.post("/painel/codigo", async (c) => {
    metricas.pedido("codigo");
    const r = opcoes.reentrada;
    const chave = opcoes.anelDaAssinatura[0];
    const pepper = r?.anelDoPepper[0];
    if (r === undefined || !(chave instanceof Uint8Array) || !(pepper instanceof Uint8Array)) {
      falhou("codigo", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const corpo = await corpoDaReentrada(c);
    if (corpo === null) {
      falhou("codigo", "invalido");
      return json({ erro: "corpo" }, 400);
    }
    // **O limite por rede vem antes de tudo**, e é o mesmo para um telefone que
    // existe e para um que não existe: um 429 que dependesse do telefone era o
    // oráculo que o resto desta rota fecha.
    if ((await r.contadores.anotar(`painel:codigo:${redeDoPedido(c, r, pepper)}`, relogio(), JANELA_DO_LIMITE_MS)) > LIMITE_POR_REDE) {
      falhou("codigo", "limite");
      return json({ erro: "limite" }, 429);
    }
    let telefone: Telefone;
    try {
      telefone = new Telefone(corpo["telefone"], r.anelDoPepper);
    } catch (erro) {
      if (!(erro instanceof IdentificadorInvalidoError)) throw erro;
      falhou("codigo", "invalido");
      return json({ erro: "campo", campo: "telefone" }, 400);
    }
    let casoId: string | null = null;
    for (const hmac of telefone.hmacs) {
      for (const caso of await r.casosPorTelefone(hmac)) {
        if ((FASES_COM_PAINEL as readonly string[]).includes(caso.fase)) casoId ??= caso.id;
      }
    }
    if (casoId !== null) {
      // **Fora do pedido**: o envio é o único trabalho que só um telefone com
      // painel faz, e esperar por ele punha a diferença no tempo de resposta. Os
      // limites por destino do `Otp` recusam em silêncio, como no registo.
      void r.otp
        .enviar(casoId, telefone)
        .then((e) => {
          if (!e.enviado) log?.info({ outcome: "painel_codigo_nao_enviado", error_code: e.recusa });
        })
        .catch((erro: unknown) => log?.excepcao(erro, "painel_codigo_falhou"));
    }
    log?.info({ outcome: "painel_codigo_pedido" });
    return json({ referencia: cunharBilhete(casoId ?? randomUUID(), chave, relogio()) }, 200);
  });

  app.post("/painel/verificar", async (c) => {
    metricas.pedido("verificar");
    const r = opcoes.reentrada;
    const chave = opcoes.anelDaAssinatura[0];
    if (r === undefined || !(chave instanceof Uint8Array)) {
      falhou("verificar", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const corpo = await corpoDaReentrada(c);
    if (corpo === null) {
      falhou("verificar", "invalido");
      return json({ erro: "corpo" }, 400);
    }
    // **Também com limite por rede.** Com um bilhete na mão, quem não tem o
    // telefone gastava as tentativas do desafio vivo do dono (`TENTATIVAS_MAXIMAS`
    // do `Otp`) sem tecto nenhum. O limite é o mesmo número, noutra chave.
    const pepper = r.anelDoPepper[0];
    const rede = pepper instanceof Uint8Array ? redeDoPedido(c, r, pepper) : "sem-pepper";
    if ((await r.contadores.anotar(`painel:verificar:${rede}`, relogio(), JANELA_DO_LIMITE_MS)) > LIMITE_POR_REDE) {
      falhou("verificar", "limite");
      return json({ erro: "limite" }, 429);
    }
    const ligar = corpo["destino"] === "ligar";
    const casoId = lerBilhete(corpo["referencia"], opcoes.anelDaAssinatura, relogio());
    const veredicto = casoId === null ? null : await r.otp.verificar(casoId, corpo["codigo"]);
    const caso = casoId === null || veredicto !== "acertou" ? null : await opcoes.casos.porId(casoId);
    // A religação de um caso activo (KAM-207) pergunta **outra vez** ao COM, e
    // só aqui: entre o `GET /painel/ligar` e este pedido cabem dez minutos e
    // uma suspensão. Um COM que não responde é 503 — quem chegou aqui acertou
    // no código, e o 503 não lhe diz nada que ele não saiba.
    let religa = false;
    if (ligar && casoId !== null && caso !== null && caso.fase === FASE_DA_RELIGACAO && r.religar !== undefined) {
      const religavel = await canalReligavel(opcoes.canal, caso.tenantId.toLowerCase(), casoId);
      if (religavel === null) {
        falhou("verificar", "indisponivel");
        return json({ erro: "indisponivel" }, 503);
      }
      religa = religavel;
    }
    // Uma falha, uma resposta: bilhete que não serve, código errado, expirado,
    // sem desafio, tentativas a mais, ou caso que já não tem painel (ou, para a
    // ligação, que já não está no passo do ES nem é um activo com o canal
    // caído). Ver a nota do módulo.
    if (
      casoId === null ||
      caso === null ||
      !(FASES_COM_PAINEL as readonly string[]).includes(caso.fase) ||
      (ligar && caso.fase !== "aguarda_es" && !religa)
    ) {
      falhou("verificar", "sem_sessao");
      return json({ erro: "codigo" }, 401);
    }
    if (religa && r.religar !== undefined) {
      // O guia passa a `desligado` **antes** de se cunhar a sessão do registo:
      // é ele que abre o `/ligar` a um caso activo. Um guia que não volta (sem
      // guia, ou num estado de onde a matriz não leva ao `desligado`) é a mesma
      // falha das outras.
      try {
        await r.religar(casoId);
      } catch (erro) {
        if (!(erro instanceof GuiaRecusadoError)) throw erro;
        falhou("verificar", "sem_sessao");
        return json({ erro: "codigo" }, 401);
      }
    }
    const s = novaSessao(caso.tenantId, casoId, relogio());
    log?.info({ outcome: "painel_sessao_aberta" });
    const resposta = json(ligar ? { ok: true, seguinte: "/ligar" } : { ok: true }, 200);
    resposta.headers.append("set-cookie", cabecalhoDaSessao(cunharSessao(s, chave)));
    // A ligação (KAM-093) exige a `sessao` do registo, e cunha-se **aqui**, depois
    // de o código acertar — nunca a partir da sessão do painel.
    if (ligar) resposta.headers.append("set-cookie", cabecalhoDoCookie(cunharReferencia("sessao", casoId, chave, relogio)));
    return resposta;
  });

  // ------------------------------------------------- a troca de telefone (KAM-211)

  app.post("/painel/telefone", async (c) => {
    metricas.pedido("troca");
    const t = opcoes.troca;
    if (t === undefined) {
      falhou("troca", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("troca", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    const recusa = await recusaDaTroca(c, t, sessao, "troca", relogio(), falhou);
    if (recusa !== null) return recusa;
    const corpo = await corpoDaReentrada(c);
    const numero = corpo === null ? null : numeroDaTroca(corpo);
    if (corpo === null || numero === null) {
      falhou("troca", "invalido");
      return json({ erro: "corpo" }, 400, sessao.renovar);
    }
    let telefone: Telefone;
    try {
      telefone = new Telefone(corpo["telefone"], t.anelDoPepper);
    } catch (erro) {
      if (!(erro instanceof IdentificadorInvalidoError)) throw erro;
      falhou("troca", "invalido");
      return json({ erro: "campo", campo: "telefone" }, 400, sessao.renovar);
    }
    // O tenant e o da sessao, e so ele: um `tenant_id` no corpo, na consulta ou
    // num cabecalho nao e lido (a nota do modulo).
    // O HMAC do número da loja é o do caso da sessão, e não um campo do pedido —
    // e só conta no número novo, que é o que a troca guarda —
    // e só depois de o guia o ter confirmado (KAM-216). Sem isso, `null`: painel.
    const confirmado =
      t.numeroDaLojaConfirmado !== undefined && (await t.numeroDaLojaConfirmado(sessao.s.dono));
    const hmacDaLoja = confirmado ? sessao.telefoneHmac : null;
    const envio = await t.troca.pedir(pedidoDaTroca(sessao.s), sessao.s.tenantId, telefone, hmacDaLoja, numero);
    if (!envio.enviado) {
      if (envio.recusa === "ocupado" || envio.recusa === "sem_troca") {
        // Ja ha uma troca viva (`novo`), ou nao ha nenhuma pendente (`antigo`).
        falhou("troca", "conflito");
        return json({ erro: envio.recusa }, 409, sessao.renovar);
      }
      if (envio.recusa === "numero") {
        falhou("troca", "invalido");
        return json({ erro: "campo", campo: "telefone" }, 400, sessao.renovar);
      }
      falhou("troca", "limite");
      return json({ erro: "limite" }, 429, sessao.renovar);
    }
    log?.info({ outcome: numero === "novo" ? "painel_troca_pedida" : "painel_troca_antigo_pedido" });
    return json({ ok: true }, 200, sessao.renovar);
  });

  app.get("/painel/telefone", async (c) => {
    metricas.pedido("troca_estado");
    const t = opcoes.troca;
    if (t === undefined) {
      falhou("troca_estado", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("troca_estado", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    if (sessao.fase !== FASE_DA_TROCA) {
      falhou("troca_estado", "conflito");
      return json({ erro: "fase" }, 409, sessao.renovar);
    }
    // Sem numero nenhum: so o estado e o prazo da troca viva do tenant.
    const vista = await t.troca.estado(sessao.s.tenantId);
    return json(
      { troca: vista === null ? null : { estado: vista.estado, prazo: vista.prazo.toISOString() } },
      200,
      sessao.renovar,
    );
  });

  app.post("/painel/telefone/verificar", async (c) => {
    metricas.pedido("troca_verificar");
    const t = opcoes.troca;
    if (t === undefined) {
      falhou("troca_verificar", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("troca_verificar", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    const recusa = await recusaDaTroca(c, t, sessao, "troca_verificar", relogio(), falhou);
    if (recusa !== null) return recusa;
    const corpo = await corpoDaReentrada(c);
    const codigo = corpo?.["codigo"];
    const numero = corpo === null ? null : numeroDaTroca(corpo);
    if (corpo === null || typeof codigo !== "string" || numero === null) {
      falhou("troca_verificar", "invalido");
      return json({ erro: "corpo" }, 400, sessao.renovar);
    }
    // O numero vem outra vez com o codigo: a base so guarda o HMAC dele.
    let telefone: Telefone;
    try {
      telefone = new Telefone(corpo["telefone"], t.anelDoPepper);
    } catch (erro) {
      if (!(erro instanceof IdentificadorInvalidoError)) throw erro;
      falhou("troca_verificar", "invalido");
      return json({ erro: "campo", campo: "telefone" }, 400, sessao.renovar);
    }
    // **O papel so se move com o codigo do numero antigo, ou pelo `concluir`
    // depois das 72 h.** O do novo so abre a espera. Um aviso que falhe depois
    // sobe (a `TrocaDeTelefone` nao desfaz o estado), e a resposta 500 nao o
    // esconde.
    const desfecho = await t.troca.verificar(pedidoDaTroca(sessao.s), sessao.s.tenantId, telefone, codigo, numero);
    if (desfecho.estado === "recusada") {
      falhou("troca_verificar", "invalido");
      return json({ erro: "codigo" }, 401, sessao.renovar);
    }
    if (desfecho.estado === "pendente") {
      log?.info({ outcome: "painel_troca_pendente" });
      return json({ estado: "pendente", prazo: desfecho.prazo.toISOString() }, 200, sessao.renovar);
    }
    log?.info({ outcome: "painel_troca_feita" });
    return json({ estado: "feita" }, 200, sessao.renovar);
  });

  app.post("/painel/telefone/concluir", async (c) => {
    metricas.pedido("troca_concluir");
    const t = opcoes.troca;
    if (t === undefined) {
      falhou("troca_concluir", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("troca_concluir", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    const recusa = await recusaDaTroca(c, t, sessao, "troca_concluir", relogio(), falhou);
    if (recusa !== null) return recusa;
    const desfecho = await t.troca.concluir(sessao.s.tenantId);
    if (desfecho.estado !== "feita") {
      // `cedo`: as 72 h nao passaram. Os outros: nao ha troca pendente.
      falhou("troca_concluir", "conflito");
      const erro = desfecho.estado === "recusada" && desfecho.veredicto === "cedo" ? "cedo" : "sem_troca";
      return json({ erro }, 409, sessao.renovar);
    }
    log?.info({ outcome: "painel_troca_feita" });
    return json({ estado: "feita" }, 200, sessao.renovar);
  });

  app.post("/painel/telefone/cancelar", async (c) => {
    metricas.pedido("troca_cancelar");
    const t = opcoes.troca;
    if (t === undefined) {
      falhou("troca_cancelar", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("troca_cancelar", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    const recusa = await recusaDaTroca(c, t, sessao, "troca_cancelar", relogio(), falhou);
    if (recusa !== null) return recusa;
    // **Qualquer sessao do tenant cancela**, e e o que a espera da: o dono
    // legitimo, na sessao dele, ve a troca que um *cookie* roubado abriu.
    if (!(await t.troca.cancelar(sessao.s.tenantId))) {
      falhou("troca_cancelar", "conflito");
      return json({ erro: "sem_troca" }, 409, sessao.renovar);
    }
    log?.info({ outcome: "painel_troca_cancelada" });
    return json({ ok: true }, 200, sessao.renovar);
  });

  // ------------------------------------------------- a conversa do dono (KAM-223)

  app.get("/painel/conversa", async (c) => {
    metricas.pedido("conversa");
    const v = opcoes.conversa;
    if (v === undefined) {
      falhou("conversa", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("conversa", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    // O cursor e um `id` desta conversa; a conversa e a do tenant da sessao.
    const depois = c.req.query("depois") ?? null;
    const lidas = await v.conversa.ler(sessao.s.tenantId, depois);
    if (lidas === "nao_encontrado") {
      falhou("conversa", "nao_encontrado");
      return json({ erro: "nao_encontrado" }, 404, sessao.renovar);
    }
    if (typeof lidas === "string") {
      falhou("conversa", "conflito");
      return json({ erro: lidas }, 409, sessao.renovar);
    }
    return json(
      {
        entradas: lidas.map((e) => ({
          id: e.id,
          autor: e.autor,
          texto: e.texto,
          botoes: e.botoes,
          em: e.em.toISOString(),
        })),
      },
      200,
      sessao.renovar,
    );
  });

  app.post("/painel/conversa", async (c) => {
    metricas.pedido("conversa_enviar");
    const v = opcoes.conversa;
    if (v === undefined) {
      falhou("conversa_enviar", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("conversa_enviar", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    // **So JSON**, pela razao do `PATCH`: um `<form>` de outra origem nao manda
    // `application/json` sem *preflight*.
    const corpo = await corpoDaReentrada(c, CORPO_MAXIMO_DA_CONVERSA);
    if (corpo === null) {
      falhou("conversa_enviar", "invalido");
      return json({ erro: "corpo" }, 400, sessao.renovar);
    }
    // So o `texto` se le. Um `botao`, um `tenant_id` ou um `thread_id` no corpo
    // nao chegam a lado nenhum: o que imita um botao e texto.
    const enviado = await v.conversa.enviar(sessao.s.tenantId, corpo["texto"]);
    if (!enviado.enviado) {
      if (enviado.motivo === "texto") {
        falhou("conversa_enviar", "invalido");
        return json({ erro: "campo", campo: "texto" }, 400, sessao.renovar);
      }
      if (enviado.motivo === "agr") {
        // A mensagem ficou gravada e o turno nao correu: o dono ve-a sem
        // resposta e pode repetir.
        falhou("conversa_enviar", "indisponivel");
        return json({ erro: "agr", mensagem: enviado.messageId ?? null }, 502, sessao.renovar);
      }
      falhou("conversa_enviar", "conflito");
      return json({ erro: enviado.motivo }, 409, sessao.renovar);
    }
    log?.info({ outcome: "painel_conversa_enviada" });
    return json({ ok: true, mensagem: enviado.messageId }, 200, sessao.renovar);
  });

  /**
   * Abre a tentativa do teste ponta a ponta (KAM-202, critério 2). O caso e o
   * tenant são os da sessão, e só eles: um `onboarding_id` ou um `tenant_id` no
   * corpo, na consulta ou num cabeçalho não é lido. Só na fase do teste; um
   * segundo clique dentro da janela devolve a mesma janela (o `start`).
   */
  app.post("/painel/teste", async (c) => {
    metricas.pedido("teste");
    const t = opcoes.teste;
    if (t === undefined) {
      falhou("teste", "indisponivel");
      return json({ erro: "indisponivel" }, 503);
    }
    const sessao = await sessaoDe(c.req.header("cookie"));
    if (sessao === null) {
      falhou("teste", "sem_sessao");
      return json({ erro: "sessao" }, 401);
    }
    if (sessao.fase !== FASE_DO_TESTE) {
      falhou("teste", "conflito");
      return json({ erro: "fase" }, 409, sessao.renovar);
    }
    let aberta: { readonly instrucoes: string; readonly expiraEm: Date };
    try {
      aberta = await t.iniciar(sessao.s.dono, sessao.s.tenantId);
    } catch {
      // Sem a excepção no corpo nem no registo: o motivo de uma falha da base
      // não é do dono. A fase mudou entre a sessão e o `start` também cai aqui.
      falhou("teste", "indisponivel");
      return json({ erro: "indisponivel" }, 503, sessao.renovar);
    }
    log?.info({ outcome: "painel_teste_iniciado" });
    return json({ instrucoes: aberta.instrucoes, expira_em: aberta.expiraEm.toISOString() }, 200, sessao.renovar);
  });

  return app;
}
