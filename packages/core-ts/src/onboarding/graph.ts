/**
 * O cliente da Graph API para o onboarding: trocar o *code* e subscrever (KAM-016).
 *
 * ## Os caminhos não estão CONFIRMADOS, e isso está escrito aqui e não escondido
 *
 * Os *Detalhes Técnicos* do bloco dizem-no: «Os pontos finais e parâmetros
 * exactos da Graph API **não** constam de E1 (páginas de referência de API não
 * lidas): ler a documentação vigente ("Updated: Jul 24, 2026") e fixar a versão
 * da Graph API em configuração.» Não há rede nesta sessão, pelo que a
 * documentação vigente **não foi lida** e os três caminhos abaixo são
 * ***proposta***.
 *
 * O que os torna utilizáveis apesar disso é que o `GraphFalso` do KAM-024 — que
 * é a Graph falsa que quatro tickets deste epic usam — encaminha exactamente
 * estes três, e di-lo nos seus próprios comentários: `/<versao>/oauth/access_token`
 * («A troca de *code* do Embedded Signup (KAM-016)») e
 * `/<versao>/<waba_id>/subscribed_apps` («(KAM-016)», com `POST`, `GET` e
 * `DELETE`). Os testes deste módulo provam que o cliente fala com **essa**
 * superfície; o primeiro contacto real é o nono critério, e está por marcar.
 *
 * Os caminhos vivem em **constantes exportadas** e não em literais no meio do
 * código, para que o dia em que alguém leia a documentação vigente seja uma
 * alteração de três linhas com um teste a afirmá-las — e não uma caça a cadeias.
 *
 * ## Nenhum *token* entra num log, nem numa mensagem de erro
 *
 * O *token* de cliente é argumento de dois dos três métodos e resultado do
 * terceiro. Vai no cabeçalho `Authorization` e **nunca** na consulta: uma URL
 * com um *token* aparece em registos de proxy, em registos de acesso e em
 * `Referer`. Os erros deste ficheiro levam o estado HTTP e o código da Meta, e
 * nada do corpo que não seja isso — um corpo de erro da Graph pode repetir o
 * parâmetro que recusou, e o parâmetro recusado pode ser o *code*.
 *
 * ## Limitação declarada: o *code* e o `client_secret` vão na **consulta**
 *
 * E não deviam, pela regra do parágrafo anterior. Vão, e a razão não é
 * descuido — é o único caminho que não inventa.
 *
 * A primeira versão deste cliente mandava-os no corpo
 * `application/x-www-form-urlencoded`, que é o que a RFC 6749 §4.1.3 exige do
 * ponto final de *token* de OAuth 2.0 e precisamente por este motivo. **Ficou
 * vermelha na primeira execução:** o `#trocarCode` do `GraphFalso` lê
 * `pedido.consulta.code` e responde `400` a quem não o ponha lá. Não é um
 * defeito do simulador — é ele a modelar a `GET /oauth/access_token` que a Meta
 * documenta, e o autor do KAM-024 sabia da outra forma (o comentário do
 * `ouvir()` di-lo: «o Graph aceita `form-urlencoded` em algumas rotas»).
 *
 * Havia duas saídas e escolheu-se a que não afirma o que não se sabe:
 *
 * * **alargar o simulador** para ler também o corpo, e passar a provar o cliente
 *   contra uma superfície que eu próprio tinha alargado para lhe servir. Se a
 *   Graph real só aceitar a consulta, o primeiro onboarding real falha com os
 *   testes verdes — que é exactamente o desfecho que o «não inventes caminhos de
 *   API» do bloco existe para evitar;
 * * **seguir o simulador**, que é a superfície de referência deste epic, e
 *   escrever a exposição.
 *
 * **A exposição, e o que está e não está mitigado.** O pedido sai em TLS para a
 * Meta, pelo que a consulta não aparece em claro no fio; o *code* é de uso único
 * e é esta chamada que o gasta. O que **não** está mitigado é o nosso próprio
 * lado: um proxy de saída que registre a linha de pedido guarda o `code` e o
 * `client_secret` num ficheiro. Este cliente nunca escreve a URL num log — e a
 * configuração do proxy é KAM-077. Fica na secção de verificação do bloco.
 */

import { CAMPOS_DE_WEBHOOK, type Graph } from "./contrato.ts";

/**
 * A troca do *code* por um *token* de cliente. ***Proposta***.
 *
 * O `GraphFalso` encaminha `/<versao>/oauth/access_token` e lê o `code` dos
 * **parâmetros de consulta** (`pedido.consulta.code`). Este cliente segue-o —
 * ver a limitação declarada no `docstring` do módulo, que é onde está escrito
 * porque é que isso não é o que se queria e porque é assim de qualquer forma.
 */
export const CAMINHO_DA_TROCA = "oauth/access_token";

/** A subscrição da app ao WABA. ***Proposta***. `POST`, `GET` e `DELETE`. */
export function caminhoDasSubscricoes(wabaId: string): string {
  return `${encodeURIComponent(wabaId)}/subscribed_apps`;
}

/** O que a Graph respondeu, quando não respondeu bem. */
export class GraphRecusouError extends Error {
  override readonly name = "GraphRecusouError";
  readonly estado: number;
  /** O `error.code` da Meta, ou `null` se o corpo não o trouxe. */
  readonly codigo: number | null;
  readonly caminho: string;

  constructor(caminho: string, estado: number, codigo: number | null) {
    super(
      `a Graph recusou ${caminho}: estado ${estado}` +
        (codigo === null ? "" : `, código ${codigo}`),
    );
    this.estado = estado;
    this.codigo = codigo;
    this.caminho = caminho;
  }
}

/** O `fetch` que este cliente usa. Injectável, para os testes. */
export type Buscar = (
  url: string,
  opcoes: {
    readonly method: string;
    readonly headers: Readonly<Record<string, string>>;
    readonly body?: string;
  },
) => Promise<{
  readonly status: number;
  json(): Promise<unknown>;
}>;

/** Opções do cliente. */
export interface GraphHttpOpcoes {
  /** A base da Graph, sem barra final: `https://graph.facebook.com`. */
  readonly base: string;
  /** A versão, `vNN.N`. Vem do `versaoDaGraph()` do contrato. */
  readonly versao: string;
  /** O `app_id` e o `app_secret` da nossa app Meta, para a troca do *code*. */
  readonly appId: string;
  readonly appSecret: string;
  /** O `fetch`. Por omissão, o global do Node 24. */
  readonly buscar?: Buscar;
}

/** O que a Graph devolve na troca do *code*, reduzido ao que se lê. */
interface RespostaDoToken {
  readonly access_token?: unknown;
}

/** O que a Graph devolve na leitura das subscrições, reduzido ao que se lê. */
interface RespostaDasSubscricoes {
  readonly data?: readonly { readonly subscribed_fields?: unknown }[];
}

function codigoDoErro(corpo: unknown): number | null {
  if (typeof corpo !== "object" || corpo === null) return null;
  const erro = (corpo as { error?: unknown }).error;
  if (typeof erro !== "object" || erro === null) return null;
  const codigo = (erro as { code?: unknown }).code;
  return typeof codigo === "number" ? codigo : null;
}

/** O cliente HTTP da Graph. */
export class GraphHttp implements Graph {
  readonly #base: string;
  readonly #versao: string;
  readonly #appId: string;
  readonly #appSecret: string;
  readonly #buscar: Buscar;

  constructor(opcoes: GraphHttpOpcoes) {
    this.#base = opcoes.base.replace(/\/+$/, "");
    this.#versao = opcoes.versao;
    this.#appId = opcoes.appId;
    this.#appSecret = opcoes.appSecret;
    this.#buscar = opcoes.buscar ?? ((url, o) => fetch(url, o));
  }

  #url(caminho: string): string {
    return `${this.#base}/${this.#versao}/${caminho}`;
  }

  async #pedir(
    caminho: string,
    method: string,
    cabecalhos: Readonly<Record<string, string>>,
    body?: string,
  ): Promise<unknown> {
    const resposta = await this.#buscar(this.#url(caminho), {
      method,
      headers: cabecalhos,
      ...(body === undefined ? {} : { body }),
    });
    // O corpo lê-se **sempre**, incluindo no erro: é lá que vem o `error.code`, e
    // o `01` §16 manda ramificar pelo código e não pelo estado HTTP — a nota do
    // `Plano.envio.estadoHttp` do KAM-024 mediu que o `130429` pode vir com 400.
    let corpo: unknown = null;
    try {
      corpo = await resposta.json();
    } catch {
      // Um corpo que não é JSON num erro é possível (um 502 de um balanceador).
      // Não é motivo para esconder o estado, que é a informação que importa.
      corpo = null;
    }
    if (resposta.status < 200 || resposta.status >= 300) {
      // **Sem a consulta**: o `caminho` entra no `error_code` de um log, e a
      // consulta da troca leva o `code` e o `client_secret`. É o mesmo cuidado
      // que a nota do módulo descreve, do lado do registo.
      throw new GraphRecusouError(
        caminho.split("?")[0] ?? caminho,
        resposta.status,
        codigoDoErro(corpo),
      );
    }
    return corpo;
  }

  /**
   * Troca o *code* pelo *token* de cliente.
   *
   * `GET` com os três parâmetros na consulta, que é a forma que a Meta documenta
   * e que o `GraphFalso` modela. **A exposição do `code` e do `client_secret`
   * numa URL está declarada no `docstring` do módulo**, com o que está e o que
   * não está mitigado; não é uma omissão.
   *
   * A resposta **tem** de trazer `access_token`: um 200 sem *token* é uma
   * resposta que não serve para nada, e tratá-la como sucesso punha uma cadeia
   * vazia no cofre e um canal com um `token_ref` que nunca abre.
   */
  async trocarCode(code: string): Promise<string> {
    const consulta = new URLSearchParams({
      client_id: this.#appId,
      client_secret: this.#appSecret,
      code,
    }).toString();
    const resposta = (await this.#pedir(
      `${CAMINHO_DA_TROCA}?${consulta}`,
      "GET",
      {},
    )) as RespostaDoToken;
    const token = resposta.access_token;
    if (typeof token !== "string" || token.length === 0) {
      // O caminho na excepção é a constante e **não** a URL com a consulta: o
      // `caminho` de um `GraphRecusouError` entra no `error_code` de um log.
      throw new GraphRecusouError(CAMINHO_DA_TROCA, 200, null);
    }
    return token;
  }

  /**
   * Subscreve a app ao WABA nos campos dados.
   *
   * Os campos vão em `subscribed_fields` separados por vírgula, que é a forma
   * que o `GraphFalso` lê primeiro (`typeof campos === "string"`). Ele aceita
   * também um *array*; escolhe-se a cadeia porque é a forma que a Graph
   * documenta para parâmetros de lista em `form-urlencoded`, e o corpo aqui é
   * JSON apenas porque o simulador o interpreta — a diferença está marcada como
   * *proposta* no `docstring` do módulo.
   */
  async subscrever(wabaId: string, campos: readonly string[], token: string): Promise<void> {
    await this.#pedir(
      caminhoDasSubscricoes(wabaId),
      "POST",
      {
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
      },
      JSON.stringify({ subscribed_fields: campos.join(",") }),
    );
  }

  /**
   * Lê os campos subscritos deste WABA.
   *
   * A resposta da Graph é uma lista de apps subscritas; o que interessa é a
   * **nossa**, e o simulador devolve uma entrada só. Com mais de uma entrada,
   * esta leitura junta os campos de todas — e isso é deliberado: no novo modelo
   * de contas um número pode estar ligado a várias *Messaging accounts* de
   * parceiros diferentes (CONFIRMADO, `E1` §3), e distinguir a nossa exige o
   * `app_id`, que a forma exacta da resposta **não está CONFIRMADA** a trazer. A
   * consequência é que a igualdade de conjuntos do critério 5 é verificada
   * contra a união, e está na secção de verificação.
   */
  async lerSubscricoes(wabaId: string, token: string): Promise<readonly string[]> {
    const corpo = (await this.#pedir(caminhoDasSubscricoes(wabaId), "GET", {
      authorization: `Bearer ${token}`,
    })) as RespostaDasSubscricoes;
    const campos = new Set<string>();
    for (const entrada of corpo.data ?? []) {
      const lista = entrada.subscribed_fields;
      if (!Array.isArray(lista)) continue;
      for (const campo of lista) if (typeof campo === "string") campos.add(campo);
    }
    return [...campos];
  }

  /** Anula a subscrição. A compensação do passo 4 (`01` §13.2). */
  async anularSubscricao(wabaId: string, token: string): Promise<void> {
    await this.#pedir(caminhoDasSubscricoes(wabaId), "DELETE", {
      authorization: `Bearer ${token}`,
    });
  }
}

/**
 * Compara o conjunto subscrito com o conjunto pedido. **A igualdade do critério 5.**
 *
 * Igualdade de **conjuntos** e não de listas, e o critério di-lo. A razão é que a
 * Meta devolve `subscribed_fields` sem ordem garantida; comparar listas tornava
 * o teste verde ou vermelho pela ordem com que o servidor as iterou.
 *
 * Devolve as duas diferenças e não um booleano: um campo que falta e um campo a
 * mais são defeitos distintos — o primeiro é um webhook que outro ticket espera e
 * nunca vai chegar, o segundo é tráfego que ninguém trata. Contar os dois na
 * mesma afirmação escondia qual dos dois aconteceu.
 */
export function compararCampos(
  obtidos: readonly string[],
  pedidos: readonly string[] = CAMPOS_DE_WEBHOOK,
): { readonly falta: readonly string[]; readonly aMais: readonly string[] } {
  const temObtido = new Set(obtidos);
  const temPedido = new Set(pedidos);
  return {
    falta: pedidos.filter((c) => !temObtido.has(c)),
    aMais: [...temObtido].filter((c) => !temPedido.has(c)),
  };
}
