/**
 * O `ClienteDeMidia` de producao: a API de midia da Meta, pela Graph (KAM-231).
 *
 * Ate aqui a porta `ClienteDeMidia` do `contrato.ts` so tinha duplos: o MED do
 * KAM-020 nascia sem ninguem que falasse com a Meta. Este modulo e esse
 * alguem, e faz as duas etapas que a porta pede e nada mais:
 *
 *     resolver     GET <graph>/<versao>/<media_id>   com o *token* do canal
 *                  -> { url, mime_type, file_size, sha256 }
 *     descarregar  GET <url>                          com o mesmo *token*
 *                  -> os bytes, e o `content-type` DA RESPOSTA
 *
 * ## O que e *proposta*, e fica dito
 *
 * **A API de midia da Meta nao tem evidencia nenhuma** (`contrato.ts`, nota do
 * modulo): o `E1` nao tem a pagina. A forma da resposta do `resolver` e o
 * anfitriao da descarga sao o que a documentacao publica da Cloud API descreve
 * e **NAO VERIFICADO** contra a API real. Calibram no primeiro contacto com
 * ela (`ext:KAM-101`, `ext:KAM-102`), como os limites do `classes.ts`.
 *
 * ## O *token* so vai para anfitrioes de uma lista fechada
 *
 * O URL da descarga **vem da resposta da Meta**, e o *token* do canal vai no
 * `Authorization` desse pedido. Aceitar qualquer URL era entregar o *token* a
 * quem conseguisse pôr um URL naquela resposta. Por isso o URL so se segue se
 * for `https`, sem credenciais embutidas, na porta por omissao, e num
 * anfitriao de `ANFITRIOES_DA_DESCARGA` — comparado por igualdade, e nao por
 * sufixo. E os dois pedidos levam `redirect: "manual"`: um 3xx nao se segue
 * (seguir um redireccionamento era sair da lista pela porta das traseiras), e
 * e recusa definitiva.
 *
 * ## O que nunca sai daqui
 *
 * Nem o *token*, nem o URL, nem o `media_id` da Meta: as mensagens de erro
 * levam a **etapa** e o **estado HTTP**, e mais nada. A excepcao de um `fetch`
 * nao se propaga — a mensagem dela leva o URL. Este modulo nao regista nada;
 * quem regista e o `pipeline.ts`, com a lista branca do *logger*.
 *
 * ## Que falha se repete
 *
 * O `pipeline.ts` so repete a `MidiaIndisponivelError` (tres tentativas), e e
 * para ela que vai o que pode passar: falha de rede, tempo esgotado, `408`,
 * `429` e `5xx`. Tudo o resto — `4xx`, `3xx`, uma resposta que nao se le, um
 * URL fora da lista, um objecto acima do tecto — e `MidiaInesperadaError`:
 * repetir nao muda a resposta.
 */

import { ANFITRIAO_DA_GRAPH, VERSAO_DA_GRAPH } from "../outbound/cliente.ts";
import { LIMITES_POR_OMISSAO, type LimiteDaClasse } from "./classes.ts";
import {
  MidiaIndisponivelError,
  MidiaInesperadaError,
  type Classe,
  type ClienteDeMidia,
  type MidiaDescarregada,
  type MidiaResolvida,
} from "./contrato.ts";

/**
 * Os anfitrioes de onde a descarga pode vir. Lista **fechada**.
 *
 * **NAO VERIFICADO.** `lookaside.fbsbx.com` e o anfitriao que a documentacao
 * publica da Cloud API mostra nos exemplos do URL de midia; nenhuma evidencia
 * do repositorio o confirma (`contrato.ts`, nota do modulo). Se a Meta servir
 * de outro anfitriao, a descarga recusa (`MidiaInesperadaError`) e o MED nao
 * guarda a foto — falha fechada, e nunca o *token* num anfitriao que ninguem
 * aprovou. Acrescentar um anfitriao aqui pede o mesmo FQDN na lista de saidas
 * do servico que corre este cliente e na *allowlist* do proxy de saida.
 */
export const ANFITRIOES_DA_DESCARGA: readonly string[] = ["lookaside.fbsbx.com"];

/**
 * O tempo maximo de cada pedido, em ms, corpo incluido. **Proposta.**
 *
 * Mais largo do que os 10 s do envio (`outbound/cliente.ts`): aqui move-se ate
 * ao tecto de bytes, e uma rede movel lenta do lado de quem serve nao e nossa.
 * O que o limita por cima e a janela que o `pipeline.ts` defende: tres
 * tentativas deste tamanho ainda cabem num *job* da `wa-inbound`.
 */
export const ESPERA_MAXIMA_DA_MIDIA_MS = 30_000;

/** A forma minima do `fetch` de que este cliente precisa. Porta para os ensaios. */
export type Buscar = (url: string, init: RequestInit) => Promise<Response>;

/**
 * O *token* do canal que recebeu a midia, pedido a cada etapa.
 *
 * Porta, e nao um valor: o *token* le-se do cofre quando e preciso e nao fica
 * a viver num campo entre pedidos (a razao do `resposta/credencial.ts`).
 */
export type TokenDoCanal = (tenantId: string) => Promise<string>;

export interface OpcoesDoClienteDeMidia {
  readonly token: TokenDoCanal;
  readonly buscar?: Buscar;
  /** A base da Graph. Por omissao, a de producao (`outbound/cliente.ts`). */
  readonly base?: string;
  readonly versao?: string;
  /** Os anfitrioes aceites para a descarga. Por omissao, `ANFITRIOES_DA_DESCARGA`. */
  readonly anfitrioes?: readonly string[];
  /** O tecto de bytes da descarga. Por omissao, o maior dos limites por classe. */
  readonly bytesMaximos?: number;
  readonly esperaMaximaMs?: number;
}

/**
 * O tecto de bytes: o maior dos limites por classe.
 *
 * **Este cliente nao sabe a classe** — a porta recebe o `tenantId` e o
 * `MidiaResolvida`, e a traducao de vocabulario e do `pipeline.ts`. O tecto e
 * por isso o da classe mais larga: protege a memoria do processo (a negacao de
 * servico do `docs/tecnica/08` §4.2), e o veredicto por classe continua a ser
 * do `recusar`, sobre os bytes que aqui chegam.
 */
export function tectoDosLimites(
  limites: Readonly<Record<Classe, LimiteDaClasse>> = LIMITES_POR_OMISSAO,
): number {
  return Math.max(...Object.values(limites).map((limite) => limite.bytesMaximos));
}

/**
 * O `media_id` so com a forma que se pode pôr num caminho.
 *
 * A Meta devolve-o numerico; aceita-se um pouco mais, mas nunca `/`, `.`, `?`
 * ou `%`: o identificador vai para o caminho do pedido, e um `../` nele mudava
 * o recurso pedido com o *token* do canal.
 */
const MEDIA_ID = /^[A-Za-z0-9_-]{1,256}$/;

/** Os estados HTTP que passam com o tempo. O resto do `4xx` e definitivo. */
function passaComOTempo(estado: number): boolean {
  return estado === 408 || estado === 429 || estado >= 500;
}

/** O cliente da API de midia da Meta. Ver a nota do modulo. */
export class ClienteDeMidiaDaGraph implements ClienteDeMidia {
  readonly #token: TokenDoCanal;
  readonly #buscar: Buscar;
  readonly #base: string;
  readonly #versao: string;
  readonly #anfitrioes: ReadonlySet<string>;
  readonly #bytesMaximos: number;
  readonly #espera: number;

  constructor(opcoes: OpcoesDoClienteDeMidia) {
    this.#token = opcoes.token;
    this.#buscar = opcoes.buscar ?? ((url, init) => fetch(url, init));
    this.#base = opcoes.base ?? ANFITRIAO_DA_GRAPH;
    this.#versao = opcoes.versao ?? VERSAO_DA_GRAPH;
    this.#anfitrioes = new Set(
      (opcoes.anfitrioes ?? ANFITRIOES_DA_DESCARGA).map((a) => a.toLowerCase()),
    );
    this.#bytesMaximos = opcoes.bytesMaximos ?? tectoDosLimites();
    this.#espera = opcoes.esperaMaximaMs ?? ESPERA_MAXIMA_DA_MIDIA_MS;
  }

  async resolver(tenantId: string, mediaId: string): Promise<MidiaResolvida> {
    if (!MEDIA_ID.test(mediaId)) {
      throw new MidiaInesperadaError("resolver: o identificador da midia nao tem forma");
    }
    const token = await this.#token(tenantId);
    const corpo = await this.#pedir(
      "resolver",
      `${this.#base}/${this.#versao}/${mediaId}`,
      token,
      async (resposta) => {
        // O texto primeiro e o JSON depois: um corpo interrompido a meio e
        // falha que passa (`#pedir`), e um corpo inteiro que nao e JSON nao.
        const texto = await resposta.text();
        try {
          return JSON.parse(texto) as unknown;
        } catch {
          throw new MidiaInesperadaError("resolver: a resposta nao e JSON");
        }
      },
    );
    const mapa = typeof corpo === "object" && corpo !== null ? (corpo as Record<string, unknown>) : {};
    const url = mapa["url"];
    if (typeof url !== "string" || !this.#aceite(url)) {
      // **Sem o URL nem o anfitriao na mensagem**: o URL e temporario mas
      // autenticado pelo *token*, e o anfitriao e meio caminho para ele.
      throw new MidiaInesperadaError(
        "resolver: o URL da midia falta, ou nao e https num anfitriao da lista",
      );
    }
    const tipo = mapa["mime_type"];
    const tamanho = numero(mapa["file_size"]);
    return {
      url,
      contentType: typeof tipo === "string" ? tipo : "",
      ...(tamanho === null ? {} : { tamanho }),
    };
  }

  async descarregar(tenantId: string, resolvida: MidiaResolvida): Promise<MidiaDescarregada> {
    // A lista confere-se outra vez: a porta aceita um `MidiaResolvida` de
    // quem quer que o construa, e o *token* vai neste pedido.
    if (!this.#aceite(resolvida.url)) {
      throw new MidiaInesperadaError("descarregar: o URL da midia nao e https num anfitriao da lista");
    }
    // **O anuncio recusa antes de descarregar** (`contrato.ts`, nota do
    // `tamanho`): um objecto anunciado acima do tecto nao se pede.
    if (resolvida.tamanho !== undefined && resolvida.tamanho > this.#bytesMaximos) {
      throw new MidiaInesperadaError("descarregar: o tamanho anunciado excede o tecto");
    }
    const token = await this.#token(tenantId);
    return await this.#pedir("descarregar", resolvida.url, token, async (resposta) => ({
      bytes: await this.#lerComTecto(resposta),
      // **O da resposta, e so ele** (`contrato.ts`, `MidiaDescarregada`). Sem
      // cabecalho, vazio — e a *allowlist* do `recusar` recusa-o.
      contentType: resposta.headers.get("content-type") ?? "",
    }));
  }

  /**
   * Um pedido autenticado, com o tempo maximo a cobrir o corpo tambem.
   *
   * O `ler` corre dentro do mesmo relogio: um servidor que responda os
   * cabecalhos depressa e depois pingue o corpo byte a byte nao prende o
   * *worker* para sempre.
   */
  async #pedir<T>(
    etapa: "resolver" | "descarregar",
    url: string,
    token: string,
    ler: (resposta: Response) => Promise<T>,
  ): Promise<T> {
    const controlo = new AbortController();
    const relogio = setTimeout(() => controlo.abort(), this.#espera);
    try {
      let resposta: Response;
      try {
        resposta = await this.#buscar(url, {
          method: "GET",
          headers: { authorization: `Bearer ${token}` },
          redirect: "manual",
          signal: controlo.signal,
        });
      } catch {
        // Rede ou tempo esgotado. **A excepcao do `fetch` nao se propaga**: a
        // mensagem dela leva o URL.
        throw new MidiaIndisponivelError(`${etapa}: sem resposta`);
      }
      if (resposta.status >= 200 && resposta.status < 300) {
        try {
          return await ler(resposta);
        } catch (erro) {
          if (erro instanceof MidiaInesperadaError || erro instanceof MidiaIndisponivelError) throw erro;
          // O corpo interrompido a meio (tempo esgotado, ligacao caida).
          throw new MidiaIndisponivelError(`${etapa}: o corpo nao chegou inteiro`);
        }
      }
      // O corpo de um erro nao se le: nao serve a decisao, e lê-lo era gastar
      // o relogio. Cancela-se para libertar a ligacao.
      await resposta.body?.cancel().catch(() => {});
      if (passaComOTempo(resposta.status)) {
        throw new MidiaIndisponivelError(`${etapa}: http ${resposta.status}`);
      }
      throw new MidiaInesperadaError(`${etapa}: http ${resposta.status}`);
    } finally {
      clearTimeout(relogio);
    }
  }

  /** Le o corpo, e desiste ao passar o tecto — sem o materializar todo antes. */
  async #lerComTecto(resposta: Response): Promise<Uint8Array> {
    const declarado = numero(resposta.headers.get("content-length"));
    if (declarado !== null && declarado > this.#bytesMaximos) {
      await resposta.body?.cancel().catch(() => {});
      throw new MidiaInesperadaError("descarregar: o tamanho declarado excede o tecto");
    }
    if (resposta.body === null) return new Uint8Array(0);
    const leitor = resposta.body.getReader();
    const partes: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await leitor.read();
      if (done) break;
      total += value.byteLength;
      if (total > this.#bytesMaximos) {
        await leitor.cancel().catch(() => {});
        throw new MidiaInesperadaError("descarregar: o corpo excede o tecto");
      }
      partes.push(value);
    }
    const bytes = new Uint8Array(total);
    let posicao = 0;
    for (const parte of partes) {
      bytes.set(parte, posicao);
      posicao += parte.byteLength;
    }
    return bytes;
  }

  /** `https`, sem credenciais, na porta por omissao, num anfitriao da lista. */
  #aceite(bruto: string): boolean {
    let url: URL;
    try {
      url = new URL(bruto);
    } catch {
      return false;
    }
    return (
      url.protocol === "https:" &&
      url.username === "" &&
      url.password === "" &&
      url.port === "" &&
      this.#anfitrioes.has(url.hostname.toLowerCase())
    );
  }
}

/** Um inteiro nao negativo, de numero ou de texto decimal; `null` se nao for. */
function numero(valor: unknown): number | null {
  if (typeof valor === "number") {
    return Number.isSafeInteger(valor) && valor >= 0 ? valor : null;
  }
  if (typeof valor === "string" && /^[0-9]{1,15}$/.test(valor.trim())) {
    return Number(valor.trim());
  }
  return null;
}
