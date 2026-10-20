/**
 * O `ClienteDoProvedor` sobre a API do Chatwoot (KAM-019).
 *
 * É a única parte deste módulo que nomeia o Chatwoot, e é de propósito: o
 * ADR-012 fixa a costura `HandoffProvider` e diz que ele é **substituível**,
 * pelo que tudo o que seja específico dele tem de caber num ficheiro que se
 * troca. Nada daqui é exportado pelo `index.ts` como tipo de domínio — o resto
 * da plataforma vê a porta, não este cliente.
 *
 * ## Duas APIs e dois segredos, e a diferença importa
 *
 * O Chatwoot tem a **Platform API** (cria contas, utilizadores e *agent bots*)
 * e a **Application API** (fala dentro de uma conta). São dois níveis de poder
 * muito diferentes, e o `docs/tecnica/08` §3.6 é explícito: «o *token* da
 * Platform API (poderoso) só existe no serviço de *provisioning*, nunca no
 * AGR». Por isso o `criarConta` recebe o *token* da plataforma e as outras três
 * operações recebem o do bot — **são parâmetros diferentes**, e não um campo
 * `token` que serve para tudo.
 *
 * ## O que está NÃO VERIFICADO, e fica dito
 *
 * **Os caminhos e os parâmetros exactos da Platform API não constam do `E4`**
 * (as páginas de referência da API não foram lidas; o que está confirmado é a
 * existência dos *controllers* `accounts`, `users`, `account_users`,
 * `agent_bots` e o facto de um `agent_bot` com `account_id` nulo ser **global**
 * — `E4` §2.2). Os caminhos abaixo são **proposta**, e o spike do critério 8 é
 * o que os confirma contra um Chatwoot 4.18 real: é lá que se descobre se o
 * *token* do *agent bot* consegue passar `pending → open` (**L7**, NÃO
 * VERIFICADO, `docs/tecnica/01` §18) ou se é preciso o plano B — um
 * utilizador-serviço «KAMBÁ Bot» com *token* da Application API.
 *
 * A versão da API vai em configuração e **não** embutida, pela mesma razão que
 * o KAM-015 escreveu para a Graph: fixar uma versão num literal obriga a um
 * *commit* para a mudar, e quem a muda é quem opera.
 */

import {
  ProvedorIndisponivelError,
  type AberturaNoProvedor,
  type ClienteDoProvedor,
  type ContaDeAtendimento,
  type MirrorMessage,
} from "./contrato.ts";
import { ATRIBUTO_DO_HANDOFF } from "./eventos.ts";

/** A base por omissão, para o compose de desenvolvimento. */
export const BASE_POR_OMISSAO = "http://chatwoot.localhost:3000";

/** O *timeout* por chamada. Nosso, e *proposta*: o Chatwoot não o publica. */
export const ESPERA_MAXIMA_MS = 10_000;

/**
 * O tipo de *inbox* que se cria.
 *
 * `api` e não `whatsapp`, e é o critério 2: «nenhum *inbox* é do tipo
 * WhatsApp». O GWY é o único ponto que fala com a Meta (ADR-001) e o Chatwoot
 * é **espelho**; um *inbox* de WhatsApp aqui era um segundo caminho para o
 * mesmo número, com as credenciais da Meta do lado dele.
 */
export const TIPO_DE_INBOX = "api";

/** O `bot_type` do *agent bot*. O único que o Chatwoot aceita (`E4` §2.2). */
export const TIPO_DE_BOT = "webhook";

export interface Configuracao {
  /** A base, sem barra no fim. O Chatwoot do compose entra por aqui. */
  readonly base?: string;
  /** O *token* da **Platform API**. Só o provisionamento o tem. */
  readonly tokenDaPlataforma: string;
  /** O *token* do *agent bot* de uma conta. Nunca é registado. */
  readonly tokenDoBot: (conta: ContaDeAtendimento) => Promise<string>;
  /** Para onde o *agent bot* manda os *callbacks*: o nosso HND. */
  readonly urlDeSaida: string;
  /** O `secret` do bot, que é o que autentica os *callbacks* de volta. */
  readonly segredoDoBot: string;
  /** O `fetch` a usar. Porta para que um teste unitário não abra socket. */
  readonly buscar?: typeof fetch;
  readonly esperaMaximaMs?: number;
}

/** Uma resposta do Chatwoot que não se consegue usar. */
export class RespostaInesperadaError extends Error {
  constructor(caminho: string, estado: number, detalhe: string) {
    super(`${caminho} respondeu ${estado}: ${detalhe}`);
    this.name = "RespostaInesperadaError";
  }
}

/**
 * O cliente do Chatwoot.
 *
 * **Toda a indisponibilidade vira `ProvedorIndisponivelError`**, e é isso que
 * faz a passagem degradar em vez de falhar: uma falha de rede, um *timeout* e
 * um 5xx são a mesma coisa para quem chama — o provedor não respondeu. Um 4xx
 * **não** é: é um pedido nosso errado, e degradar por causa dele esconderia um
 * defeito atrás de uma fila que nunca drenaria.
 */
export class ClienteDoChatwoot implements ClienteDoProvedor {
  readonly #base: string;
  readonly #tokenDaPlataforma: string;
  readonly #tokenDoBot: (conta: ContaDeAtendimento) => Promise<string>;
  readonly #urlDeSaida: string;
  readonly #segredoDoBot: string;
  readonly #buscar: typeof fetch;
  readonly #espera: number;

  constructor(configuracao: Configuracao) {
    this.#base = (configuracao.base ?? BASE_POR_OMISSAO).replace(/\/+$/, "");
    this.#tokenDaPlataforma = configuracao.tokenDaPlataforma;
    this.#tokenDoBot = configuracao.tokenDoBot;
    this.#urlDeSaida = configuracao.urlDeSaida;
    this.#segredoDoBot = configuracao.segredoDoBot;
    this.#buscar = configuracao.buscar ?? fetch;
    this.#espera = configuracao.esperaMaximaMs ?? ESPERA_MAXIMA_MS;
  }

  /**
   * Cria conta, *inbox* de tipo `api` e *agent bot* da conta.
   *
   * **O `account_id` do bot vai sempre preenchido**, e é a asserção do critério
   * 1 («um *agent bot* com `account_id` nulo é impossível por construção»). A
   * razão está confirmada no código do Chatwoot (`E4` §2.2): um bot com
   * `account_id` nulo é **global e acessível a todas as contas** — isto é, um
   * bot de uma PME a poder ler as conversas de todas as outras. É por isso que
   * o `account_id` não é opcional nesta chamada nem tem valor por omissão: não
   * há caminho de código que o deixe de fora.
   */
  async criarConta(tenantId: string): Promise<ContaDeAtendimento> {
    const conta = await this.#pedir<{ id: number }>(
      "POST",
      "/platform/api/v1/accounts",
      this.#tokenDaPlataforma,
      { name: `kamba-${tenantId}` },
    );
    const caixa = await this.#pedir<{ id: number }>(
      "POST",
      `/api/v1/accounts/${conta.id}/inboxes`,
      this.#tokenDaPlataforma,
      {
        name: `kamba-${tenantId}`,
        channel: { type: TIPO_DE_INBOX, webhook_url: this.#urlDeSaida },
      },
    );
    const bot = await this.#pedir<{ id: number }>(
      "POST",
      "/platform/api/v1/agent_bots",
      this.#tokenDaPlataforma,
      {
        name: `kamba-bot-${tenantId}`,
        // **Nunca nulo.** Ver a nota do método: um bot sem conta é global.
        account_id: conta.id,
        bot_type: TIPO_DE_BOT,
        outgoing_url: this.#urlDeSaida,
        secret: this.#segredoDoBot,
      },
    );
    return { accountId: conta.id, inboxId: caixa.id, botId: bot.id };
  }

  /**
   * Cria a conversa, põe-na em `open` e deixa a nota privada com o resumo.
   *
   * **A passagem a `open` é o L7**, e é a única coisa deste ficheiro que pode
   * não funcionar com o *token* do bot: a documentação indica que ele acede
   * apenas a APIs «permitidas ao bot» (`docs/tecnica/01` §11.3) e nenhuma
   * fonte deste repositório confirma que `pending → open` é uma delas. Se o
   * spike do critério 8 mostrar que não é, o plano B já está escrito — um
   * utilizador-serviço com *token* da Application API — e **só este método
   * muda**.
   *
   * O `handoffId` vai nos `custom_attributes`, que é por onde o `openHandoff`
   * «procura a conversa por atributo» (critério 4). É do lado deles e segue a
   * convenção deles: `handoffId` em *camelCase*, como o critério escreve.
   */
  async abrirConversa(abertura: AberturaNoProvedor): Promise<string> {
    const token = await this.#tokenDoBot(abertura.conta);
    const conversa = await this.#pedir<{ id: number }>(
      "POST",
      `/api/v1/accounts/${abertura.conta.accountId}/conversations`,
      token,
      {
        inbox_id: abertura.conta.inboxId,
        source_id: abertura.contactId,
        status: "open",
        custom_attributes: { [ATRIBUTO_DO_HANDOFF]: abertura.handoffId },
      },
    );
    // A nota privada com o resumo. **Depois** da conversa e não no mesmo
    // pedido: se esta falhar, a conversa existe e alguém a atende sem o
    // resumo — o contrário (resumo sem conversa) não serve a ninguém.
    await this.#pedir(
      "POST",
      `/api/v1/accounts/${abertura.conta.accountId}/conversations/${conversa.id}/messages`,
      token,
      { content: abertura.resumo, message_type: "outgoing", private: true },
    );
    return String(conversa.id);
  }

  /**
   * Espelha uma mensagem.
   *
   * O `wamid` vai em `source_id`, que é o campo que o Chatwoot usa para
   * de-duplicar do lado dele. A nossa de-duplicação é a da fila (o `jobId` é o
   * `wamid`); esta é a segunda rede, e as duas são precisas por razões
   * diferentes — a fila protege-nos de reenviar, o `source_id` protege-nos de
   * um reenvio que a fila já esqueceu.
   */
  async espelhar(conta: ContaDeAtendimento, m: MirrorMessage): Promise<void> {
    const token = await this.#tokenDoBot(conta);
    await this.#pedir(
      "POST",
      `/api/v1/accounts/${conta.accountId}/conversations/${m.wamid}/messages`,
      token,
      {
        content: m.texto,
        message_type: m.direccao === "entrada" ? "incoming" : "outgoing",
        source_id: m.wamid,
        content_attributes: { wa_type: m.waType },
      },
    );
  }

  async fecharConversa(conta: ContaDeAtendimento, externalId: string): Promise<void> {
    const token = await this.#tokenDoBot(conta);
    await this.#pedir(
      "POST",
      `/api/v1/accounts/${conta.accountId}/conversations/${externalId}/toggle_status`,
      token,
      { status: "resolved" },
    );
  }

  /**
   * Uma chamada à API, com *timeout* e com a tradução dos erros.
   *
   * O *token* vai no cabeçalho `api_access_token` e **nunca** no corpo, na URL
   * ou numa mensagem de erro — é a mesma regra que o cliente da Meta já segue.
   * O `detalhe` de um erro leva o corpo da resposta **truncado**: um corpo de
   * erro do Chatwoot pode citar o pedido, e o pedido leva o resumo da conversa.
   */
  async #pedir<T>(
    metodo: string,
    caminho: string,
    token: string,
    corpo: Readonly<Record<string, unknown>>,
  ): Promise<T> {
    const controlador = new AbortController();
    const relogio = setTimeout(() => controlador.abort(), this.#espera);
    try {
      const resposta = await this.#buscar(`${this.#base}${caminho}`, {
        method: metodo,
        headers: {
          "content-type": "application/json",
          api_access_token: token,
        },
        body: JSON.stringify(corpo),
        signal: controlador.signal,
      });
      if (resposta.status >= 500) {
        throw new ProvedorIndisponivelError(`${caminho} respondeu ${resposta.status}`);
      }
      if (!resposta.ok) {
        // Um 4xx **não** degrada: é um pedido nosso errado, e uma fila que o
        // repetisse nunca drenava.
        throw new RespostaInesperadaError(
          caminho,
          resposta.status,
          (await resposta.text()).slice(0, 200),
        );
      }
      return (await resposta.json()) as T;
    } catch (erro) {
      if (erro instanceof ProvedorIndisponivelError) throw erro;
      if (erro instanceof RespostaInesperadaError) throw erro;
      // Falha de rede ou `abort` do *timeout*: o provedor não respondeu. A
      // causa leva o **caminho** e não a URL completa, que leva a base — e a
      // base pode ter credenciais num ambiente mal configurado.
      throw new ProvedorIndisponivelError(
        `${caminho}: ${erro instanceof Error ? erro.name : "erro desconhecido"}`,
      );
    } finally {
      clearTimeout(relogio);
    }
  }
}
