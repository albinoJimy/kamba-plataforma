/**
 * O servidor Graph falso, com cenários programáveis (KAM-024, critério 5).
 *
 * O critério enumera os cenários: «envio 200, 130429 (N vezes), 131049, 5xx,
 * mídia, submissão de templates, troca de *code*, subscrições; usado por
 * KAM-015, 016, 017 e 020». São esses, e só esses — o servidor não imita o Graph
 * inteiro, imita a superfície que esses quatro tickets usam.
 *
 * ## Duas formas de o usar, e a razão de serem duas
 *
 * `responder()` é **puro**: recebe um pedido e devolve uma resposta, sem socket
 * nenhum. É o que os testes usam, porque um teste que precise de uma porta TCP
 * livre falha em paralelo e falha no CI por razões que não têm a ver com o que
 * se está a medir.
 *
 * `ouvir()` levanta um `node:http` de verdade. É o que o KAM-015 e o KAM-020
 * precisam quando o que querem exercitar é o **cliente HTTP** deles — `fetch`,
 * *timeouts*, *retries*, o proxy de saída — e não a lógica de envio. Um cliente
 * testado só contra uma função nunca prova que trata um socket que fecha a meio.
 *
 * ## Sem dependências novas
 *
 * `node:http` e não Hono, embora o repositório já tenha Hono e o GWY o use.
 * Não é preferência: o `tools/meta-sim` está **na** *workspace* do pnpm
 * precisamente porque não acrescenta dependência nenhuma — é isso que faz o
 * `pnpm -r run typecheck` e o `pnpm -r run test` cobri-lo de graça, e é isso que
 * mantém o «versões fixadas; licenças permitidas» do DoD trivialmente
 * verdadeiro. Um router de sete rotas em `node:http` custa menos do que essa
 * promessa vale.
 *
 * ## A versão do Graph não está fixada aqui, de propósito
 *
 * Nenhum documento do repositório fixa a versão da Graph API, e inventar uma
 * («v23.0») era afirmar o que não se sabe. O servidor **aceita qualquer**
 * `/v<maior>.<menor>/` e registra a que o cliente usou: assim nunca mente sobre
 * a versão, e o dia em que o KAM-015 fixar uma, um teste pode afirmar que o
 * cliente a usa — contra o registo, que é onde essa afirmação pertence.
 */

import { createServer, type Server } from "node:http";

import { CODIGOS_CONFIRMADOS, CODIGOS_PROPOSTOS, erroDoGraph } from "./codigos.ts";
import type { Gerador } from "./semente.ts";

/** O prefixo da rota de descarga de mídia servida por este servidor. */
export const CAMINHO_DA_MIDIA = "/midia-de-ensaio";

/** A forma `/v<maior>.<menor>` de um segmento de versão. */
const VERSAO = /^v\d+\.\d+$/;

/** Um pedido ao Graph falso. */
export interface Pedido {
  readonly metodo: string;
  /** O caminho, sem consulta. */
  readonly caminho: string;
  readonly consulta: Readonly<Record<string, string>>;
  /** O corpo já em objecto, ou `null`. */
  readonly corpo: Record<string, unknown> | null;
  readonly cabecalhos: Readonly<Record<string, string>>;
}

/** Uma resposta do Graph falso. */
export interface Resposta {
  readonly estado: number;
  /** O corpo. `Uint8Array` para a descarga de mídia; objecto para o resto. */
  readonly corpo: Record<string, unknown> | Uint8Array;
  readonly tipo?: string;
  readonly cabecalhos?: Readonly<Record<string, string>>;
}

/** Os cenários de envio que o critério nomeia. */
export const CENARIOS_DE_ENVIO = [
  "ok",
  "debito_excedido",
  "limite_por_utilizador",
  "erro_servidor",
  "indisponivel",
] as const;
export type CenarioDeEnvio = (typeof CENARIOS_DE_ENVIO)[number];

/** O plano programável. Tudo opcional; por omissão, tudo responde 200. */
export interface Plano {
  /**
   * O cenário do envio, e quantas vezes antes de voltar ao 200.
   *
   * `{ cenario: "debito_excedido", vezes: 3 }` é literalmente o critério 1 do
   * KAM-015 («Resposta 130429 do servidor falso 3× seguida de 200»). `vezes`
   * ausente significa **sempre**, que é o que o cenário «Meta em baixo» precisa.
   */
  readonly envio?: { readonly cenario: CenarioDeEnvio; readonly vezes?: number };
  /** O estado com que um template submetido fica. Por omissão, `PENDING`. */
  readonly template?: { readonly estado: string; readonly categoria?: string };
  /** `invalido` faz a troca de *code* falhar. */
  readonly code?: "ok" | "invalido";
  /**
   * A mídia. `expirada` faz a descarga dar 404 **com** a metainformação a
   * responder 200 — que é o caso real: a URL de mídia expira (`01` §5.4), e um
   * cliente que guarde a URL em vez de a pedir outra vez falha exactamente aqui.
   */
  readonly midia?: {
    readonly bytes?: Uint8Array;
    readonly mimeType?: string;
    readonly expirada?: boolean;
  };
  /** A base absoluta das URLs de mídia. Por omissão, a do servidor. */
  readonly base?: string;
}

/** O registo de um pedido atendido, para os testes afirmarem o que foi enviado. */
export interface Registo {
  readonly pedido: Pedido;
  readonly resposta: Resposta;
  /** A versão do segmento `/vNN.N/`, ou `null` se o caminho não a tinha. */
  readonly versao: string | null;
}

function segmentos(caminho: string): readonly string[] {
  return caminho.split("/").filter((s) => s.length > 0);
}

/**
 * O Graph falso.
 *
 * O estado é todo interno e mutável — contagem de envios, subscrições,
 * templates, mídia — porque é isso que um servidor é. O que não é mutável é o
 * **plano**: `programar` substitui-o por inteiro, e não há meia-alteração que
 * deixe o servidor num estado que ninguém pediu.
 */
export class GraphFalso {
  #plano: Plano;
  readonly #g: Gerador;
  #envios = 0;
  readonly #registo: Registo[] = [];
  readonly #subscritos = new Map<string, Set<string>>();
  readonly #templates = new Map<string, Record<string, unknown>>();
  readonly #midias = new Map<string, { bytes: Uint8Array; mimeType: string }>();
  #base: string;

  constructor(g: Gerador, plano: Plano = {}) {
    this.#g = g;
    this.#plano = plano;
    this.#base = plano.base ?? "http://graph-de-ensaio.localhost";
  }

  /** Substitui o plano. Não mexe no estado acumulado nem no registo. */
  programar(plano: Plano): void {
    this.#plano = plano;
    if (plano.base !== undefined) this.#base = plano.base;
  }

  /** Volta a contagem de envios a zero. Para reutilizar o servidor entre casos. */
  reiniciarContagens(): void {
    this.#envios = 0;
  }

  /** Tudo o que o servidor atendeu, pela ordem. */
  get registo(): readonly Registo[] {
    return this.#registo;
  }

  /** Quantos envios atendeu, incluindo os que recusou. */
  get envios(): number {
    return this.#envios;
  }

  /** Os `subscribed_apps` de um WABA. */
  subscricoes(wabaId: string): readonly string[] {
    return [...(this.#subscritos.get(wabaId) ?? [])];
  }

  /** Registra uma mídia e devolve o seu `id`, para o KAM-020 a ir buscar. */
  oferecerMidia(bytes: Uint8Array, mimeType: string): string {
    const id = this.#g.texto(24, "0123456789");
    this.#midias.set(id, { bytes, mimeType });
    return id;
  }

  #fbtrace(): string {
    return this.#g.texto(22, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789");
  }

  /** Atende um pedido. Puro quanto ao transporte; muda o estado do servidor. */
  responder(pedido: Pedido): Resposta {
    const partes = segmentos(pedido.caminho);
    const versao = partes[0] !== undefined && VERSAO.test(partes[0]) ? partes[0] : null;
    const resposta = this.#encaminhar(pedido, partes, versao);
    this.#registo.push({ pedido, resposta, versao });
    return resposta;
  }

  #encaminhar(pedido: Pedido, partes: readonly string[], versao: string | null): Resposta {
    // A descarga de mídia não leva versão: a URL que a Meta devolve é um
    // *lookaside* próprio, e tratá-la como rota versionada era inventar.
    if (pedido.caminho.startsWith(CAMINHO_DA_MIDIA)) {
      return this.#descarregar(partes[partes.length - 1] ?? "");
    }
    if (versao === null) {
      return {
        estado: 404,
        corpo: erroDoGraph(
          CODIGOS_PROPOSTOS.erroInterno,
          `caminho sem segmento de versao: ${pedido.caminho}`,
          this.#fbtrace(),
        ) as unknown as Record<string, unknown>,
      };
    }
    const resto = partes.slice(1);

    if (resto[0] === "oauth" && resto[1] === "access_token") return this.#trocarCode(pedido);
    if (resto.length === 2 && resto[1] === "messages") return this.#enviar(pedido, resto[0] ?? "");
    if (resto.length === 2 && resto[1] === "message_templates") {
      return this.#template(pedido, resto[0] ?? "");
    }
    if (resto.length === 2 && resto[1] === "subscribed_apps") {
      return this.#subscrever(pedido, resto[0] ?? "");
    }
    if (resto.length === 1 && pedido.metodo === "GET") return this.#metaDaMidia(resto[0] ?? "");

    return {
      estado: 404,
      corpo: erroDoGraph(
        CODIGOS_PROPOSTOS.erroInterno,
        `rota nao simulada: ${pedido.metodo} ${pedido.caminho}`,
        this.#fbtrace(),
      ) as unknown as Record<string, unknown>,
    };
  }

  /**
   * `POST /<versao>/<phone_number_id>/messages`.
   *
   * O cenário consome-se por ordem: as primeiras `vezes` chamadas levam o erro
   * e as seguintes levam 200. É assim e não ao contrário porque é o que o
   * KAM-015 precisa de provar — «130429 3× seguida de 200: *backoff*
   * exponencial com *jitter*, 3 tentativas, 1 mensagem entregue, 0 duplicados».
   */
  #enviar(pedido: Pedido, phoneNumberId: string): Resposta {
    this.#envios += 1;
    const plano = this.#plano.envio;
    const dentroDoLimite = plano !== undefined && (plano.vezes === undefined || this.#envios <= plano.vezes);
    const cenario: CenarioDeEnvio = dentroDoLimite && plano !== undefined ? plano.cenario : "ok";

    if (cenario === "debito_excedido") {
      return {
        estado: 429,
        corpo: erroDoGraph(
          CODIGOS_CONFIRMADOS.debitoExcedido,
          "Rate limit hit",
          this.#fbtrace(),
        ) as unknown as Record<string, unknown>,
        // `Retry-After` **quando existir** é o que o `01` §16 manda respeitar;
        // o servidor dá-o para que o cliente o possa honrar, e o teste do
        // KAM-015 pode programar um cenário sem ele para provar o *backoff* cego.
        cabecalhos: { "retry-after": "1" },
      };
    }
    if (cenario === "limite_por_utilizador") {
      return {
        estado: 400,
        corpo: erroDoGraph(
          CODIGOS_CONFIRMADOS.limitePorUtilizador,
          "This message was not delivered to maintain healthy ecosystem engagement.",
          this.#fbtrace(),
        ) as unknown as Record<string, unknown>,
      };
    }
    if (cenario === "erro_servidor" || cenario === "indisponivel") {
      return {
        estado: cenario === "indisponivel" ? 503 : 500,
        corpo: erroDoGraph(
          CODIGOS_PROPOSTOS.erroInterno,
          "An unknown error occurred",
          this.#fbtrace(),
        ) as unknown as Record<string, unknown>,
      };
    }

    const para = typeof pedido.corpo?.to === "string" ? pedido.corpo.to : "";
    return {
      estado: 200,
      corpo: {
        messaging_product: "whatsapp",
        contacts: [{ input: para, wa_id: para }],
        // O `wamid` que a Meta devolve é o que o KAM-015 guarda para casar com
        // os `statuses` que chegam depois. A forma é a do `identificadores.ts`.
        messages: [{ id: `wamid.${Buffer.from(`${phoneNumberId}|${this.#g.texto(16, "0123456789abcdef")}`, "utf8").toString("base64url")}` }],
      },
    };
  }

  /** `POST /<versao>/<waba_id>/message_templates` e o `GET` da lista. */
  #template(pedido: Pedido, wabaId: string): Resposta {
    if (pedido.metodo === "GET") {
      return { estado: 200, corpo: { data: [...this.#templates.values()] } };
    }
    if (pedido.metodo !== "POST") return this.#metodoErrado(pedido);
    const nome = typeof pedido.corpo?.name === "string" ? pedido.corpo.name : "sem_nome";
    const categoria =
      this.#plano.template?.categoria ??
      (typeof pedido.corpo?.category === "string" ? pedido.corpo.category : "UTILITY");
    const registo = {
      id: this.#g.texto(15, "0123456789"),
      status: this.#plano.template?.estado ?? "PENDING",
      category: categoria,
      name: nome,
      waba_id: wabaId,
    };
    this.#templates.set(nome, registo);
    return { estado: 200, corpo: registo };
  }

  /**
   * `GET /<versao>/oauth/access_token?code=...`.
   *
   * A troca de *code* do Embedded Signup (KAM-016). O *token* devolvido é de
   * ensaio e di-lo no próprio valor: um *token* opaco num registo de teste é
   * indistinguível de um real, e o scan de segredos do KAM-002 tem de poder
   * separar os dois sem heurística.
   */
  #trocarCode(pedido: Pedido): Resposta {
    if ((this.#plano.code ?? "ok") === "invalido" || pedido.consulta.code === undefined) {
      return {
        estado: 400,
        corpo: erroDoGraph(
          CODIGOS_PROPOSTOS.erroInterno,
          "Invalid verification code format.",
          this.#fbtrace(),
        ) as unknown as Record<string, unknown>,
      };
    }
    return {
      estado: 200,
      corpo: {
        access_token: `ensaio-token-${this.#g.texto(32, "0123456789abcdef")}`,
        token_type: "bearer",
      },
    };
  }

  /** `POST`/`GET`/`DELETE /<versao>/<waba_id>/subscribed_apps` (KAM-016). */
  #subscrever(pedido: Pedido, wabaId: string): Resposta {
    const conjunto = this.#subscritos.get(wabaId) ?? new Set<string>();
    if (pedido.metodo === "POST") {
      // O corpo da subscrição leva os campos; o KAM-016 subscreve os onze, e o
      // servidor guarda-os para que o teste possa afirmar **quais**, e não só
      // que a chamada aconteceu.
      const campos = pedido.corpo?.subscribed_fields;
      const lista =
        typeof campos === "string"
          ? campos.split(",").map((c) => c.trim())
          : Array.isArray(campos)
            ? campos.filter((c): c is string => typeof c === "string")
            : [];
      for (const campo of lista) conjunto.add(campo);
      this.#subscritos.set(wabaId, conjunto);
      return { estado: 200, corpo: { success: true } };
    }
    if (pedido.metodo === "GET") {
      return {
        estado: 200,
        corpo: {
          data: [
            {
              whatsapp_business_api_data: { id: wabaId },
              subscribed_fields: [...conjunto],
            },
          ],
        },
      };
    }
    if (pedido.metodo === "DELETE") {
      this.#subscritos.delete(wabaId);
      return { estado: 200, corpo: { success: true } };
    }
    return this.#metodoErrado(pedido);
  }

  /** `GET /<versao>/<media_id>`: a metainformação, com a URL que expira. */
  #metaDaMidia(id: string): Resposta {
    const midia = this.#midias.get(id);
    if (midia === undefined) {
      return {
        estado: 404,
        corpo: erroDoGraph(
          CODIGOS_PROPOSTOS.erroInterno,
          `Unsupported get request. Object with ID '${id}' does not exist`,
          this.#fbtrace(),
        ) as unknown as Record<string, unknown>,
      };
    }
    return {
      estado: 200,
      corpo: {
        id,
        url: `${this.#base}${CAMINHO_DA_MIDIA}/${id}`,
        mime_type: this.#plano.midia?.mimeType ?? midia.mimeType,
        sha256: this.#g.texto(64, "0123456789abcdef"),
        file_size: midia.bytes.byteLength,
        messaging_product: "whatsapp",
      },
    };
  }

  /** A descarga em si. `expirada` dá 404, que é o caso real que se tem de tratar. */
  #descarregar(id: string): Resposta {
    const midia = this.#midias.get(id);
    if (midia === undefined || (this.#plano.midia?.expirada ?? false)) {
      return {
        estado: 404,
        corpo: erroDoGraph(
          CODIGOS_PROPOSTOS.erroInterno,
          "The media URL has expired or does not exist.",
          this.#fbtrace(),
        ) as unknown as Record<string, unknown>,
      };
    }
    const bytes = this.#plano.midia?.bytes ?? midia.bytes;
    return { estado: 200, corpo: bytes, tipo: this.#plano.midia?.mimeType ?? midia.mimeType };
  }

  #metodoErrado(pedido: Pedido): Resposta {
    return {
      estado: 405,
      corpo: erroDoGraph(
        CODIGOS_PROPOSTOS.erroInterno,
        `metodo nao simulado: ${pedido.metodo}`,
        this.#fbtrace(),
      ) as unknown as Record<string, unknown>,
    };
  }

  /**
   * Levanta um `node:http` na porta dada (0 = o SO escolhe) e devolve como o
   * fechar.
   *
   * Porta 0 por omissão: um teste que fixe a porta falha quando dois testes
   * correm ao mesmo tempo, e o CI corre-os ao mesmo tempo.
   */
  async ouvir(porta = 0): Promise<{ porta: number; base: string; fechar: () => Promise<void> }> {
    const servidor: Server = createServer((req, res) => {
      const pedacos: Buffer[] = [];
      req.on("data", (p: Buffer) => pedacos.push(p));
      req.on("end", () => {
        const url = new URL(req.url ?? "/", "http://interno");
        const texto = Buffer.concat(pedacos).toString("utf8");
        let corpo: Record<string, unknown> | null = null;
        if (texto.length > 0) {
          try {
            const lido: unknown = JSON.parse(texto);
            corpo = typeof lido === "object" && lido !== null ? (lido as Record<string, unknown>) : null;
          } catch {
            // Um corpo que não é JSON não é erro deste servidor: o Graph
            // aceita `form-urlencoded` em algumas rotas, e o que interessa aos
            // testes é a rota e os parâmetros de consulta.
            corpo = null;
          }
        }
        const cabecalhos: Record<string, string> = {};
        for (const [nome, valor] of Object.entries(req.headers)) {
          if (typeof valor === "string") cabecalhos[nome] = valor;
        }
        const resposta = this.responder({
          metodo: req.method ?? "GET",
          caminho: url.pathname,
          consulta: Object.fromEntries(url.searchParams),
          corpo,
          cabecalhos,
        });
        if (resposta.corpo instanceof Uint8Array) {
          res.writeHead(resposta.estado, {
            "content-type": resposta.tipo ?? "application/octet-stream",
            ...resposta.cabecalhos,
          });
          res.end(Buffer.from(resposta.corpo));
          return;
        }
        res.writeHead(resposta.estado, {
          "content-type": "application/json",
          ...resposta.cabecalhos,
        });
        res.end(JSON.stringify(resposta.corpo));
      });
    });

    await new Promise<void>((resolver) => servidor.listen(porta, "127.0.0.1", resolver));
    const endereco = servidor.address();
    const escolhida = typeof endereco === "object" && endereco !== null ? endereco.port : porta;
    const base = `http://127.0.0.1:${escolhida}`;
    if (this.#plano.base === undefined) this.#base = base;
    return {
      porta: escolhida,
      base,
      fechar: () =>
        new Promise<void>((resolver, rejeitar) => {
          servidor.close((erro) => (erro === undefined || erro === null ? resolver() : rejeitar(erro)));
        }),
    };
  }
}
