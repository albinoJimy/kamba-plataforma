/**
 * As rotas do `onboarding-web` (KAM-086).
 *
 * Cinco, e são a superfície inteira do ticket:
 *
 *     GET  /entrar              o convite assinado abre o ecrã; 403 se não abrir
 *     POST /api/registo         cria o caso, ou recupera a sessão de quem já tem
 *     POST /api/otp/reenviar    pede outro código, dentro dos limites
 *     POST /api/otp/verificar   confere o código e, se acertar, dá a sessão
 *     POST /api/actividade      a batida de 30 s do critério 10
 *
 * ## É aqui que o anti-abuso e os limites **ficam ligados**, e é o que se mede
 *
 * As barreiras vivem no `@kamba/core-ts/inscricao` e são exercitadas lá. O que
 * **só** se pode medir aqui é que elas estão ligadas ao sítio certo: um limite
 * que um ensaio exercita chamando o contador que ele próprio incrementa não prova
 * nada sobre o pedido HTTP. A bateria deste serviço submete pedidos e conta
 * casos criados, pelo que apagar a chamada ao anti-abuso **nesta** camada põe-na
 * vermelha — e é essa a propriedade que se quer, porque é a ligação que se
 * desfaz num *refactor*, não a função.
 *
 * ## O IP não vem do `X-Forwarded-For` por omissão
 *
 * O limite do critério 7 é por prefixo de IP. Ler o `X-Forwarded-For` de um
 * pedido sem saber quantos *proxies* de confiança há à frente é deixar o
 * atacante escolher o seu próprio balde — isto é, desligar o limite com um
 * cabeçalho. Por omissão lê-se o endereço da ligação e **ignora-se** o
 * cabeçalho; quem põe o serviço atrás de um balanceador declara quantos saltos
 * de confiança existem, e aí lê-se a posição certa a contar **da direita**, que
 * é a única que o atacante não consegue empurrar.
 *
 * ## O corpo das respostas de recusa não diz o que falhou
 *
 * Um `{"erro":"nif_duplicado"}` era a enumeração que o critério 9 proíbe,
 * servida num campo. O que sai é o código fechado do `RegistoRecusado` —
 * `token`, `campo`, `abuso`, `limite`, `indisponivel` —, que diz a quem
 * preencheu o que fazer e não diz nada sobre o estado de um NIF.
 */

import { Hono } from "hono";
import { randomBytes } from "node:crypto";

import {
  Actividade,
  AntiAbuso,
  Otp,
  Registo,
  RegistoRecusado,
  cabecalhoDoCookie,
  cookieDoCabecalho,
  cunharReferencia,
  lerReferencia,
  prefixoDeIp,
  ReferenciaInvalidaError,
  TokenInvalidoError,
  verificarToken,
  type Veredicto,
} from "@kamba/core-ts/inscricao";
import type { Logger } from "@kamba/core-ts/logger";

import { cabecalhos, paginaDeRecusa, paginaDeRegisto } from "./pagina.ts";

/** Octetos do `nonce` da CSP e da chave de idempotência da página. */
export const OCTETOS_DE_NONCE = 12;

/** O que as rotas precisam de ter montado. */
export interface OpcoesDasRotas {
  readonly registo: Registo;
  readonly otp: Otp;
  readonly actividade: Actividade;
  readonly antiabuso: AntiAbuso;
  /** O anel da chave de assinatura: actual primeiro. */
  readonly anelDaAssinatura: readonly (Uint8Array | null)[];
  /** O anel do `segredo_onboarding_assinatura` para o *token* de `/entrar`. */
  readonly anelDoToken: readonly (Uint8Array | null)[];
  /**
   * Quantos *proxies* de confiança há à frente. **Zero por omissão** — ver a
   * nota do módulo.
   */
  readonly proxiesDeConfianca?: number | undefined;
  readonly log?: Logger | undefined;
}

/** Um `nonce` em hexadecimais: serve de `nonce` de CSP e casa a forma de `CHAVE`. */
function nonce(): string {
  return randomBytes(OCTETOS_DE_NONCE).toString("hex");
}

/**
 * O endereço de quem pediu, ou `null`.
 *
 * Ver a nota do módulo: com `proxiesDeConfianca` a zero o cabeçalho é ignorado.
 */
export function enderecoDoPedido(
  xff: string | undefined,
  enderecoDaLigacao: string | undefined,
  proxiesDeConfianca: number,
): string | null {
  if (proxiesDeConfianca <= 0) return enderecoDaLigacao ?? null;
  const saltos = (xff ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s !== "");
  // A contar **da direita**: o salto mais à direita é o que o *proxy* mais
  // próximo escreveu, e esse não é forjável por quem pede. Os da esquerda são.
  const indice = saltos.length - proxiesDeConfianca;
  if (indice < 0 || indice >= saltos.length) return enderecoDaLigacao ?? null;
  return saltos[indice] ?? null;
}

/** Levantado nunca: o tipo do corpo JSON que se aceita. */
type Corpo = Record<string, unknown>;

async function corpoJson(pedido: Request): Promise<Corpo> {
  try {
    const bruto: unknown = await pedido.json();
    return typeof bruto === "object" && bruto !== null ? (bruto as Corpo) : {};
  } catch {
    return {};
  }
}

/** Monta as rotas do ticket numa aplicação Hono. */
export function rotasDeInscricao(opcoes: OpcoesDasRotas): Hono {
  const app = new Hono();
  const proxies = opcoes.proxiesDeConfianca ?? 0;
  const log = opcoes.log;

  const ipDe = (c: {
    req: { header: (nome: string) => string | undefined };
    env?: unknown;
  }): string | null => {
    const ligacao = (
      c.env as { incoming?: { socket?: { remoteAddress?: string } } } | undefined
    )?.incoming?.socket?.remoteAddress;
    return enderecoDoPedido(c.req.header("x-forwarded-for"), ligacao, proxies);
  };

  app.get("/entrar", async (c) => {
    const n = nonce();
    try {
      verificarToken(c.req.query("c"), opcoes.anelDoToken);
    } catch (erro) {
      if (!(erro instanceof TokenInvalidoError)) throw erro;
      // O `outcome` e o `error_code` são campos da *allowlist* do KAM-068; o
      // *token* **não** entra em nenhum deles, e a `recusa` é um valor de lista
      // fechada. Ver `../../../packages/core-ts/src/logger/politica.ts`.
      log?.info({ outcome: "entrar_recusado", error_code: erro.recusa });
      return c.html(paginaDeRecusa(), 403, cabecalhos(n));
    }
    const desafio = await opcoes.antiabuso.emitir(prefixoDeIpOuNulo(ipDe(c)));
    return c.html(
      paginaDeRegisto({
        desafio: desafio.desafio,
        dificuldade: desafio.dificuldade,
        nonce: n,
        chave: nonce(),
        token: c.req.query("c") ?? "",
      }),
      200,
      cabecalhos(n),
    );
  });

  app.post("/api/registo", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    try {
      const aceite = await opcoes.registo.inscrever({
        token: corpo.token,
        nomeNegocio: corpo.nome_negocio,
        categoria: corpo.categoria,
        nif: corpo.nif,
        telefone: corpo.telefone,
        email: corpo.email,
        // A chave vem do cabeçalho **e** do corpo, nesta ordem: o cabeçalho é a
        // convenção HTTP (ADR-009) e o corpo é o que um cliente sem controlo
        // sobre cabeçalhos consegue mandar. Um dos dois, nunca os dois somados.
        chaveDeIdempotencia: c.req.header("idempotency-key") ?? corpo.chave,
        desafio: corpo.desafio,
        solucao: corpo.solucao,
        honeypot: corpo.honeypot,
        ip: ipDe(c),
        dispositivo: corpo.dispositivo,
      });
      log?.info({ outcome: "registo_aceite" });
      // **Os três campos do `Aceite` e nem um a mais.** Acrescentar aqui um
      // `novo`, um `onboarding_id` nu ou uma mensagem por caminho é desfazer o
      // critério 9 — ver o cabeçalho do `registo.ts` do pacote.
      return c.json(
        {
          referencia: aceite.referencia,
          expira_em: aceite.expiraEm.toISOString(),
          digitos: aceite.digitos,
        },
        200,
      );
    } catch (erro) {
      if (!(erro instanceof RegistoRecusado)) throw erro;
      log?.info({ outcome: "registo_recusado", error_code: erro.codigo });
      return c.json({ erro: erro.codigo }, erro.estadoHttp);
    }
  });

  app.post("/api/otp/reenviar", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    const id = idDaReferencia(corpo.referencia, opcoes.anelDaAssinatura);
    if (id === null) return c.json({ erro: "token" }, 403);
    const telefone = await opcoes.registo.telefoneDoCaso(id);
    if (telefone === null) return c.json({ erro: "indisponivel" }, 503);
    const resultado = await opcoes.otp.enviar(id, telefone);
    if (!resultado.enviado) {
      log?.info({ outcome: "otp_recusado", error_code: resultado.recusa });
      return c.json({ erro: "limite" }, 429);
    }
    return c.json({ expira_em: resultado.expiraEm.toISOString() }, 200);
  });

  app.post("/api/otp/verificar", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    const id = idDaReferencia(corpo.referencia, opcoes.anelDaAssinatura);
    if (id === null) return c.json({ erro: "token" }, 403);
    const veredicto: Veredicto = await opcoes.otp.verificar(id, corpo.codigo);
    log?.info({ outcome: `otp_${veredicto}`, error_code: veredicto });
    if (veredicto !== "acertou") return c.json({ veredicto }, 200);
    await opcoes.registo.concluirOtp(id);
    const chave = opcoes.anelDaAssinatura[0];
    if (!(chave instanceof Uint8Array)) return c.json({ erro: "indisponivel" }, 503);
    // **A sessão é cunhada aqui e só aqui.** O bilhete que o cliente trouxe tem
    // outro separador de domínio e não serve de cookie — ver o `sessao.ts` do
    // pacote. É esta linha que faz a posse do telefone ser condição de entrada.
    c.header("Set-Cookie", cabecalhoDoCookie(cunharReferencia("sessao", id, chave)));
    return c.json({ veredicto }, 200);
  });

  app.post("/api/actividade", async (c) => {
    const corpo = await corpoJson(c.req.raw);
    // O cookie primeiro, o bilhete depois: depois do OTP é a sessão que manda, e
    // antes dele o bilhete é a única referência que existe. Os dois saem de um
    // HMAC nosso, e **o id sai de dentro deles** — nunca de um parâmetro ao
    // lado, que é o que faz o 404 do teste de isolamento ser inevitável.
    const daSessao = idDaSessao(c.req.header("cookie"), opcoes.anelDaAssinatura);
    const id = daSessao ?? idDaReferencia(corpo.referencia, opcoes.anelDaAssinatura);
    if (id === null) return c.json({ erro: "token" }, 403);
    const batida = await opcoes.actividade.bater(id);
    if (batida === null) return c.json({ erro: "token" }, 404);
    return c.json({ somados: batida.somados, total: batida.total }, 200);
  });

  return app;
}

function prefixoDeIpOuNulo(ip: string | null): string | null {
  return ip === null ? null : prefixoDeIp(ip);
}

function idDaReferencia(bruto: unknown, anel: readonly (Uint8Array | null)[]): string | null {
  try {
    return lerReferencia("ticket", bruto, anel);
  } catch (erro) {
    if (erro instanceof ReferenciaInvalidaError) return null;
    throw erro;
  }
}

function idDaSessao(
  cabecalho: string | undefined,
  anel: readonly (Uint8Array | null)[],
): string | null {
  const valor = cookieDoCabecalho(cabecalho);
  if (valor === null) return null;
  try {
    return lerReferencia("sessao", valor, anel);
  } catch (erro) {
    if (erro instanceof ReferenciaInvalidaError) return null;
    throw erro;
  }
}
