/**
 * O transporte HTTP do adaptador ProxyPay e o mapa de erros do §3.1 (KAM-056).
 *
 * O adaptador **nao chama `fetch` directamente**: recebe um `Transporte`. E a
 * costura que deixa os ensaios correrem contra um servidor falso local — o
 * ticket proibe tocar no *sandbox* real enquanto nao houver contrato (`ext:KAM-103`)
 * — e e a mesma costura que o servico `pay` vai usar para por *timeouts* e
 * metricas a volta de cada pedido.
 *
 * ## «Nao sei» nao e «falhou»
 *
 * O §3.1 tem dois codigos que um adaptador ingenuo confunde, e confundi-los
 * custa uma segunda referencia Multicaixa para a mesma encomenda:
 *
 *     UNAVAILABLE      o pedido **nao saiu** (ligacao recusada, DNS) ou o
 *                      facilitador respondeu 5xx. Repetir so e seguro no
 *                      primeiro caso, ou numa rota idempotente: um 502 de um
 *                      *gateway* pode chegar depois de o pedido ter sido
 *                      processado, e por isso quem faz um POST sem
 *                      idempotencia longa pede `incertoEm5xx`
 *     TIMEOUT_UNKNOWN  o pedido **saiu** e a resposta perdeu-se: o efeito pode
 *                      existir, e quem repete tem de repetir pela mesma chave
 *
 * O `transporteFetch` distingue os dois pelo codigo da causa do erro de rede.
 * Uma causa que nao reconhece cai em `TIMEOUT_UNKNOWN`, e e de proposito: na
 * duvida, assume-se que o pedido saiu (fail closed, §2 principio 1).
 *
 * ## O 429 nao se absorve aqui
 *
 * «*Backoff* exponencial com *jitter* para 429; o valor do limite e NAO
 * VERIFICADO e fica em configuracao.» O adaptador **devolve** `RATE_LIMIT` e nao
 * repete sozinho: um `createCharge` que dormisse dentro de si prendia o
 * *handler* do agente, e o caso 9 da suite de conformidade (§3.5) mede
 * precisamente que o 429 chega ao chamador com o codigo certo. Quem repete e o
 * chamador, com o `comRecuo` deste ficheiro — o *job* de reconciliacao usa-o.
 */

import { randomInt } from "node:crypto";

import { ProviderError } from "../tipos.ts";

/** Um pedido ao facilitador, ja com a autenticacao nos cabecalhos. */
export type PedidoHttp = {
  readonly metodo: "GET" | "POST" | "PUT" | "DELETE";
  readonly url: string;
  readonly cabecalhos: Readonly<Record<string, string>>;
  readonly corpo?: string;
};

/** A resposta crua. O corpo e texto: quem o le decide se e JSON. */
export type RespostaHttp = {
  readonly estado: number;
  readonly corpo: string;
};

export type Transporte = (pedido: PedidoHttp) => Promise<RespostaHttp>;

/**
 * Um erro de rede, com a resposta a pergunta que importa: o pedido saiu?
 *
 * `enviado: false` so quando ha a certeza de que o facilitador nao o recebeu.
 */
export class ErroDeTransporte extends Error {
  override readonly name = "ErroDeTransporte";
  readonly enviado: boolean;
  constructor(mensagem: string, enviado: boolean) {
    super(mensagem);
    this.enviado = enviado;
  }
}

/**
 * Os codigos de erro do Node em que o pedido **nao saiu**: nao houve ligacao.
 *
 * Fora desta lista — `ECONNRESET`, `UND_ERR_SOCKET`, um *timeout* — o pedido
 * pode ter chegado ao facilitador.
 */
const SEM_LIGACAO = new Set(["ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN", "EHOSTUNREACH", "ENETUNREACH"]);

/**
 * O transporte de producao, sobre o `fetch` do Node.
 *
 * `prazoMs` e o *timeout* de cada pedido. **Proposta**, sem calibracao: o
 * facilitador nao publica latencias (NAO VERIFICADO), e calibra-se com o
 * *sandbox* real, que e o `ext:KAM-103`.
 */
export function transporteFetch(prazoMs: number): Transporte {
  return async (pedido) => {
    let resposta: Response;
    try {
      resposta = await fetch(pedido.url, {
        method: pedido.metodo,
        headers: pedido.cabecalhos,
        ...(pedido.corpo === undefined ? {} : { body: pedido.corpo }),
        signal: AbortSignal.timeout(prazoMs),
        redirect: "error",
      });
    } catch (erro) {
      const codigo = _codigoDaCausa(erro);
      throw new ErroDeTransporte(
        `pedido ${pedido.metodo} ao facilitador falhou na rede (${codigo ?? "sem codigo"})`,
        codigo === undefined ? true : !SEM_LIGACAO.has(codigo),
      );
    }
    let corpo: string;
    try {
      corpo = await resposta.text();
    } catch {
      // O estado chegou e o corpo nao: o pedido saiu e foi processado.
      throw new ErroDeTransporte("a resposta do facilitador perdeu-se a meio do corpo", true);
    }
    return { estado: resposta.status, corpo };
  };
}

function _codigoDaCausa(erro: unknown): string | undefined {
  const causa = (erro as { cause?: { code?: unknown } } | null)?.cause;
  return typeof causa?.code === "string" ? causa.code : undefined;
}

/**
 * Faz o pedido e traduz o resultado para os sete codigos do §3.1.
 *
 * Devolve a resposta **so** quando o estado e 2xx, ou quando e um dos
 * `aceites` que o chamador declara (o `DELETE` aceita 404, por exemplo). Tudo o
 * resto levanta `ProviderError` — e a mensagem nunca leva o corpo da resposta,
 * que pode trazer dados do pagador.
 */
export async function pedir(
  transporte: Transporte,
  pedido: PedidoHttp,
  aceites: readonly number[] = [],
  incertoEm5xx = false,
): Promise<RespostaHttp> {
  let resposta: RespostaHttp;
  try {
    resposta = await transporte(pedido);
  } catch (erro) {
    if (erro instanceof ErroDeTransporte && !erro.enviado) {
      throw new ProviderError("UNAVAILABLE", `${erro.message}: o pedido nao saiu`);
    }
    throw new ProviderError(
      "TIMEOUT_UNKNOWN",
      `${pedido.metodo} ${_semConsulta(pedido.url)}: a resposta perdeu-se e o efeito ` +
        "pode existir no facilitador. Repete-se pela mesma chave de idempotencia",
    );
  }
  if ((resposta.estado >= 200 && resposta.estado < 300) || aceites.includes(resposta.estado)) {
    return resposta;
  }
  const codigo = incertoEm5xx && resposta.estado >= 500 ? "TIMEOUT_UNKNOWN" : codigoDoEstado(resposta.estado);
  throw new ProviderError(codigo, `${pedido.metodo} ${_semConsulta(pedido.url)} devolveu ${resposta.estado}`);
}

/** O codigo do §3.1 para um estado HTTP que nao e sucesso. */
export function codigoDoEstado(estado: number): ProviderError["codigo"] {
  if (estado === 401 || estado === 403) return "AUTH";
  if (estado === 429) return "RATE_LIMIT";
  if (estado >= 500) return "UNAVAILABLE";
  if (estado === 400 || estado === 404 || estado === 409 || estado === 422) return "VALIDATION";
  return "REJECTED";
}

/** O caminho sem a cadeia de consulta, para as mensagens. */
function _semConsulta(url: string): string {
  const indice = url.indexOf("?");
  return indice < 0 ? url : url.slice(0, indice);
}

/**
 * Os parametros do recuo. **Proposta**: o limite do facilitador e NAO
 * VERIFICADO (`evidencia/E2` §1.2: «o valor nao e publicado»), e estes valores
 * so mudam por configuracao, depois de recebidos por escrito.
 */
export type ParametrosDeRecuo = {
  /** Quantos pedidos ao todo, contando o primeiro. */
  readonly pedidos: number;
  readonly baseMs: number;
  readonly tectoMs: number;
};

export const RECUO_PROPOSTO: ParametrosDeRecuo = { pedidos: 5, baseMs: 500, tectoMs: 30_000 };

/**
 * O recuo da tentativa `ordem` (a primeira repeticao e a 0), com *jitter* total.
 *
 * `aleatorio(n)` devolve um inteiro em `[0, n)`. Aritmetica de inteiros, sem
 * `Math`: o *lint* de dinheiro do gate 2 recusa `Math.floor` neste directorio, e
 * nao ha aqui nada que precise dele.
 */
export function recuoComJitter(
  ordem: number,
  parametros: ParametrosDeRecuo,
  aleatorio: (n: number) => number = randomInt,
): number {
  let janela = parametros.baseMs;
  for (let i = 0; i < ordem && janela < parametros.tectoMs; i += 1) janela *= 2;
  if (janela > parametros.tectoMs) janela = parametros.tectoMs;
  return aleatorio(janela + 1);
}

/**
 * Repete `fn` enquanto ela levantar `RATE_LIMIT`, com recuo e *jitter*.
 *
 * **So o 429.** Um `TIMEOUT_UNKNOWN` nao se repete aqui: repetir um pedido cujo
 * efeito pode existir e decisao de quem conhece a chave de idempotencia, nao de
 * um ciclo generico. Esgotados os pedidos, o ultimo `RATE_LIMIT` sobe.
 */
export async function comRecuo<T>(
  fn: () => Promise<T>,
  parametros: ParametrosDeRecuo = RECUO_PROPOSTO,
  dormir: (ms: number) => Promise<void> = _dormir,
  aleatorio: (n: number) => number = randomInt,
): Promise<T> {
  for (let ordem = 0; ; ordem += 1) {
    try {
      return await fn();
    } catch (erro) {
      const limitado = erro instanceof ProviderError && erro.codigo === "RATE_LIMIT";
      if (!limitado || ordem + 1 >= parametros.pedidos) throw erro;
      await dormir(recuoComJitter(ordem, parametros, aleatorio));
    }
  }
}

function _dormir(ms: number): Promise<void> {
  return new Promise((resolver) => setTimeout(resolver, ms));
}
