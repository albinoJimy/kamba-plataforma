/**
 * O provedor de atendimento sobre a API do Chatwoot (KAM-019).
 *
 * É a única parte deste módulo que nomeia o Chatwoot, e é de propósito: o
 * ADR-012 fixa a costura `HandoffProvider` e diz que ele é **substituível**,
 * pelo que tudo o que seja específico dele tem de caber num ficheiro que se
 * troca. Nada daqui é exportado pelo `index.ts` como tipo de domínio — o resto
 * da plataforma vê a porta, não este cliente.
 *
 * ## Três segredos e dois objectos, e a separação é o ponto
 *
 * O Chatwoot tem a **Platform API** (cria contas, utilizadores e *agent bots*)
 * e a **Application API** (fala dentro de uma conta), e esta segunda tem **dois**
 * níveis: o do utilizador da conta e o do *agent bot*. São três poderes
 * diferentes e por isso há três segredos, não um campo `token` que serve para
 * tudo:
 *
 * | Segredo | O que faz | Onde vive |
 * |---|---|---|
 * | `chatwoot_platform_token` | cria contas, utilizadores e bots | só no `ProvisionadorDoChatwoot` |
 * | `chatwoot_user_token` | cria *inboxes* e **contactos** | por conta, no cofre |
 * | `chatwoot_bot_token` | abre, fecha e escreve em conversas | por conta, no cofre |
 *
 * **E são dois objectos e não um**, porque o `docs/tecnica/08` §3.6 exige que «o
 * *token* da Platform API (poderoso) só exista no serviço de *provisioning*,
 * nunca no AGR». A primeira versão deste ficheiro tinha uma classe só, com o
 * *token* da plataforma como campo obrigatório do mesmo objecto que abre
 * conversas: qualquer processo que precisasse de abrir uma conversa tinha de o
 * ter em memória. Um parâmetro distinto não é um processo distinto.
 *
 * ## O que o spike mediu, e que nenhuma leitura tinha dado
 *
 * Os caminhos e os parâmetros desta API não constam do `E4` — o que lá está
 * confirmado é a existência dos *controllers* `accounts`, `users`,
 * `account_users` e `agent_bots`, e o facto de um `agent_bot` com `account_id`
 * nulo ser **global** (`E4` §2.2). A primeira versão deste ficheiro era, por
 * isso, *proposta*; o spike do critério 8 correu contra um Chatwoot v4.18.0
 * fixado por digest e mediu **cinco** coisas que a mudaram:
 *
 * 1. `pending → open` com o *token* do **bot** responde 200 (o **L7**, que
 *    estava NÃO VERIFICADO). O plano B — um utilizador-serviço com *token* da
 *    Application API — **não** é preciso para o estado.
 * 2. O *token* da **Platform API** responde **401** em `/api/v1/accounts/…`:
 *    «Access to this endpoint is not authorized for bots». Ele não serve os
 *    *endpoints* da conta, e a primeira versão criava o *inbox* com ele.
 * 3. Os *endpoints* da conta querem o `access_token` de um **utilizador**
 *    criado por `/platform/api/v1/users` e ligado à conta por `account_users`.
 * 4. O *agent bot* tem de ser **ligado ao *inbox*** (`set_agent_bot`), ou o
 *    `POST /conversations` responde 404 e ele não recebe os *callbacks* dele.
 * 5. O *token* do bot responde **401** a criar contactos, e a conversa quer o
 *    `source_id` de um `contact_inbox` que exista. Logo o *token* do utilizador
 *    é preciso em **tempo de execução** — é o que põe as duas colunas novas na
 *    `handoff_accounts` (emenda 1.23).
 *
 * A versão da API vai em configuração e **não** embutida, pela mesma razão que
 * o KAM-015 escreveu para a Graph: fixar uma versão num literal obriga a um
 * *commit* para a mudar, e quem a muda é quem opera.
 */

import {
  ProvedorIndisponivelError,
  type AberturaNoProvedor,
  type ClienteDoProvedor,
  type ContaCriada,
  type ContaDeAtendimento,
  type MirrorMessage,
  type ProvisionadorDoProvedor,
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
 *
 * O Chatwoot devolve-o como `Channel::Api`, e foi isso que o spike leu.
 */
export const TIPO_DE_INBOX = "api";

/** O `bot_type` do *agent bot*. O único que o Chatwoot aceita (`E4` §2.2). */
export const TIPO_DE_BOT = "webhook";

/**
 * O papel do utilizador da conta.
 *
 * `administrator` porque ele tem de criar *inboxes* e ligar o bot, e o papel
 * `agent` não chega para nenhuma das duas. É o **único** utilizador humano-like
 * que a plataforma cria, e existe só para o provisionamento e para os
 * contactos: as pessoas da PME entram pelo painel com contas próprias, que são
 * do KAM-091.
 */
export const PAPEL_DO_UTILIZADOR = "administrator";

/** Uma resposta do Chatwoot que não se consegue usar. */
export class RespostaInesperadaError extends Error {
  constructor(caminho: string, estado: number, detalhe: string) {
    super(`${caminho} respondeu ${estado}: ${detalhe}`);
    this.name = "RespostaInesperadaError";
  }
}

/** O que os dois objectos precisam para falar com a API. */
export interface Transporte {
  /** A base, sem barra no fim. O Chatwoot do compose entra por aqui. */
  readonly base?: string;
  /** O `fetch` a usar. Porta para que um teste unitário não abra socket. */
  readonly buscar?: typeof fetch;
  readonly esperaMaximaMs?: number;
}

/**
 * Uma chamada à API, com *timeout* e com a tradução dos erros.
 *
 * O *token* vai no cabeçalho `api_access_token` e **nunca** no corpo, na URL
 * ou numa mensagem de erro — é a mesma regra que o cliente da Meta já segue.
 * O `detalhe` de um erro leva o corpo da resposta **truncado**: um corpo de
 * erro do Chatwoot pode citar o pedido, e o pedido leva o resumo da conversa.
 *
 * **Toda a indisponibilidade vira `ProvedorIndisponivelError`**, e é isso que
 * faz a passagem degradar em vez de falhar: uma falha de rede, um *timeout* e
 * um 5xx são a mesma coisa para quem chama — o provedor não respondeu. Um 4xx
 * **não** é: é um pedido nosso errado, e degradar por causa dele esconderia um
 * defeito atrás de uma fila que nunca drenaria.
 */
class Chamador {
  readonly #base: string;
  readonly #buscar: typeof fetch;
  readonly #espera: number;

  constructor(transporte: Transporte) {
    this.#base = (transporte.base ?? BASE_POR_OMISSAO).replace(/\/+$/, "");
    this.#buscar = transporte.buscar ?? fetch;
    this.#espera = transporte.esperaMaximaMs ?? ESPERA_MAXIMA_MS;
  }

  /** Um pedido cujo corpo **não** interessa. */
  async vazio(
    metodo: string,
    caminho: string,
    token: string,
    corpo: Readonly<Record<string, unknown>>,
  ): Promise<void> {
    await this.#enviar(metodo, caminho, token, corpo);
  }

  /**
   * Um pedido cujo corpo se lê como JSON.
   *
   * **Um corpo que não é JSON numa resposta de sucesso levanta
   * `RespostaInesperadaError` e não `ProvedorIndisponivelError`**, e a
   * distinção é a correcção de um defeito. A primeira versão fazia `json()`
   * em todas as chamadas, mesmo nas duas que ignoram o valor, e o `catch`
   * convertia o `SyntaxError` em indisponibilidade: um 200 com corpo vazio
   * fazia o `openHandoff` degradar uma passagem **cuja conversa já tinha sido
   * criada** no provedor, que é a órfã que a ordem dos passos existe para
   * evitar. Um corpo que não entendemos é um mal-entendido nosso sobre a API,
   * e uma fila que o repetisse nunca drenava.
   */
  async json<T>(
    metodo: string,
    caminho: string,
    token: string,
    corpo: Readonly<Record<string, unknown>>,
  ): Promise<T> {
    const resposta = await this.#enviar(metodo, caminho, token, corpo);
    const texto = await resposta.text();
    try {
      return JSON.parse(texto) as T;
    } catch {
      throw new RespostaInesperadaError(
        caminho,
        resposta.status,
        `corpo nao e JSON: ${texto.slice(0, 120)}`,
      );
    }
  }

  async #enviar(
    metodo: string,
    caminho: string,
    token: string,
    corpo: Readonly<Record<string, unknown>>,
  ): Promise<Response> {
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
        throw new RespostaInesperadaError(
          caminho,
          resposta.status,
          (await resposta.text()).slice(0, 200),
        );
      }
      return resposta;
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

export interface ConfiguracaoDoProvisionamento extends Transporte {
  /** O *token* da **Platform API**. Só o provisionamento o tem. */
  readonly tokenDaPlataforma: string;
  /** Para onde o *agent bot* manda os *callbacks*: o nosso HND. */
  readonly urlDeSaida: string;
  /** O `secret` do bot, que é o que autentica os *callbacks* de volta. */
  readonly segredoDoBot: string;
  /**
   * A palavra-passe do utilizador da conta, pedida ao cofre.
   *
   * **Porta e não valor**, e não é cerimónia: a Platform API exige uma
   * palavra-passe para criar um utilizador, e uma que viesse num literal deste
   * ficheiro seria a mesma em todas as contas de todas as PMEs. Quem a gera é
   * quem tem o cofre. O Chatwoot recusa com 422 se ela não tiver maiúscula e
   * dígito — medido no spike.
   */
  readonly palavraPasseDoUtilizador: () => Promise<string>;
}

/**
 * O provisionamento: cria conta, utilizador, *inbox* e bot.
 *
 * É o único objecto que tem o *token* da Platform API, e por isso o único que
 * pode criar qualquer coisa. Vive no serviço de *provisioning* (KAM-091) e
 * **não** no caminho que atende conversas.
 */
export class ProvisionadorDoChatwoot implements ProvisionadorDoProvedor {
  readonly #chamador: Chamador;
  readonly #tokenDaPlataforma: string;
  readonly #urlDeSaida: string;
  readonly #segredoDoBot: string;
  readonly #palavraPasse: () => Promise<string>;

  constructor(configuracao: ConfiguracaoDoProvisionamento) {
    this.#chamador = new Chamador(configuracao);
    this.#tokenDaPlataforma = configuracao.tokenDaPlataforma;
    this.#urlDeSaida = configuracao.urlDeSaida;
    this.#segredoDoBot = configuracao.segredoDoBot;
    this.#palavraPasse = configuracao.palavraPasseDoUtilizador;
  }

  /**
   * Cria conta, utilizador da conta, *inbox* de tipo `api` e *agent bot*, e
   * liga o bot ao *inbox*.
   *
   * **Seis pedidos, e a ordem é a que o spike mediu.** Cada um depende do
   * anterior: o utilizador precisa da conta para se lhe ligar, o *inbox*
   * precisa do *token* do utilizador, o `set_agent_bot` precisa do *inbox* e
   * do bot. A primeira versão fazia três, dois deles com o *token* errado.
   *
   * **O `account_id` do bot vai sempre preenchido**, e é a asserção do critério
   * 1 («um *agent bot* com `account_id` nulo é impossível por construção»). A
   * razão está confirmada no código do Chatwoot (`E4` §2.2): um bot com
   * `account_id` nulo é **global e acessível a todas as contas** — isto é, um
   * bot de uma PME a poder ler as conversas de todas as outras.
   *
   * **Se isto falhar a meio, fica o que já foi criado.** Não há transacção do
   * lado do provedor e não a podemos inventar; o que se faz é a ordem que deixa
   * o destroço mais inofensivo — a conta e o utilizador antes do *inbox*, e o
   * bot depois do *inbox*, porque um bot ligado a nada não recebe nada, e um
   * *inbox* sem bot não encaminha nada. O que **não** se pode deixar é a linha
   * na nossa base sem os identificadores, e é por isso que quem chama só a
   * escreve depois de isto devolver.
   */
  async criarConta(tenantId: string): Promise<ContaCriada> {
    const conta = await this.#chamador.json<{ id: number }>(
      "POST",
      "/platform/api/v1/accounts",
      this.#tokenDaPlataforma,
      { name: `kamba-${tenantId}` },
    );

    // O utilizador da conta. É o `access_token` **dele** que os endpoints
    // `/api/v1/accounts/…` aceitam — medido: o da plataforma dá 401.
    const utilizador = await this.#chamador.json<{
      id: number;
      access_token: string;
    }>("POST", "/platform/api/v1/users", this.#tokenDaPlataforma, {
      name: `kamba-provisioner-${tenantId}`,
      email: `kamba-${tenantId}@handoff.invalid`,
      password: await this.#palavraPasse(),
    });
    if (!utilizador.access_token) {
      throw new RespostaInesperadaError(
        "/platform/api/v1/users",
        200,
        "utilizador criado sem access_token; sem ele nao ha token de conta",
      );
    }

    await this.#chamador.vazio(
      "POST",
      `/platform/api/v1/accounts/${conta.id}/account_users`,
      this.#tokenDaPlataforma,
      { user_id: utilizador.id, role: PAPEL_DO_UTILIZADOR },
    );

    const caixa = await this.#chamador.json<{ id: number }>(
      "POST",
      `/api/v1/accounts/${conta.id}/inboxes`,
      utilizador.access_token,
      {
        name: `kamba-${tenantId}`,
        channel: { type: TIPO_DE_INBOX, webhook_url: this.#urlDeSaida },
      },
    );

    const bot = await this.#chamador.json<{ id: number; access_token: string }>(
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
    if (!bot.access_token) {
      throw new RespostaInesperadaError(
        "/platform/api/v1/agent_bots",
        200,
        "bot criado sem access_token; sem ele nao se abre conversa nenhuma",
      );
    }

    // **A ligação do bot ao inbox**, que faltava e sem a qual nada funciona: o
    // `POST /conversations` dá 404 e o bot não recebe os `callbacks` do inbox.
    // Endpoint da conta, logo com o token do utilizador.
    await this.#chamador.vazio(
      "POST",
      `/api/v1/accounts/${conta.id}/inboxes/${caixa.id}/set_agent_bot`,
      utilizador.access_token,
      { agent_bot: bot.id },
    );

    return {
      conta: {
        accountId: conta.id,
        inboxId: caixa.id,
        botId: bot.id,
        providerUserId: utilizador.id,
      },
      tokenDoBot: bot.access_token,
      tokenDoUtilizador: utilizador.access_token,
    };
  }
}

export interface Configuracao extends Transporte {
  /** O *token* do *agent bot* de uma conta. Nunca é registado. */
  readonly tokenDoBot: (conta: ContaDeAtendimento) => Promise<string>;
  /**
   * O *token* do utilizador da conta. Nunca é registado.
   *
   * Existe porque o do bot responde 401 a criar contactos, e a conversa quer um
   * contacto que exista. São duas portas e não uma por isso: os dois alcances
   * são diferentes e trocá-los dá 401 numa direcção e poder a mais na outra.
   */
  readonly tokenDoUtilizador: (conta: ContaDeAtendimento) => Promise<string>;
  /** Para onde o *agent bot* manda os *callbacks*: o nosso HND. */
  readonly urlDeSaida: string;
}

/**
 * O cliente de execução: abre, espelha e fecha.
 *
 * **Não tem o *token* da Platform API**, e é isso que o distingue do
 * provisionamento: um processo que atenda conversas não pode criar contas.
 */
export class ClienteDoChatwoot implements ClienteDoProvedor {
  readonly #chamador: Chamador;
  readonly #tokenDoBot: (conta: ContaDeAtendimento) => Promise<string>;
  readonly #tokenDoUtilizador: (conta: ContaDeAtendimento) => Promise<string>;
  readonly #urlDeSaida: string;

  constructor(configuracao: Configuracao) {
    this.#chamador = new Chamador(configuracao);
    this.#tokenDoBot = configuracao.tokenDoBot;
    this.#tokenDoUtilizador = configuracao.tokenDoUtilizador;
    this.#urlDeSaida = configuracao.urlDeSaida;
  }

  /**
   * Cria o contacto, a conversa, põe-na em `open` e deixa a nota privada.
   *
   * **O `pending → open` com o *token* do bot está CONFIRMADO** pelo spike do
   * critério 8 — 200, com `"current_status":"open"` no corpo —, e é por isso
   * que o plano B (um utilizador-serviço com *token* da Application API) não é
   * preciso e fica arquivado. O que o spike mudou aqui foi outra coisa: **o
   * contacto**, que tem de existir antes da conversa.
   *
   * O `handoffId` vai nos `custom_attributes`, que é por onde o `openHandoff`
   * «procura a conversa por atributo» (critério 4). É do lado deles e segue a
   * convenção deles: `handoffId` em *camelCase*, como o critério escreve.
   *
   * **A chave do contacto é opaca e não é o nosso `contact_id`.** Ver a nota do
   * `PedidoDeHandoff`: a primeira versão mandava o nosso identificador no
   * `source_id`, o que era uma fuga contra o ADR-010 e, de qualquer modo, um
   * 404 — o provedor quer um `source_id` que ele próprio emitiu.
   */
  async abrirConversa(abertura: AberturaNoProvedor): Promise<string> {
    const tokenDoUtilizador = await this.#tokenDoUtilizador(abertura.conta);
    // O contacto, com o token do utilizador: o do bot responde 401 aqui.
    // A forma da resposta é `payload.contact`, medida no spike — ler `payload`
    // directamente dá um objecto sem `contact_inboxes`.
    const contacto = await this.#chamador.json<{
      payload: { contact: { contact_inboxes?: { source_id?: string }[] } };
    }>(
      "POST",
      `/api/v1/accounts/${abertura.conta.accountId}/contacts`,
      tokenDoUtilizador,
      {
        inbox_id: abertura.conta.inboxId,
        // O `identifier` é a chave opaca. Nada de telefone, nada de nome: o
        // provedor não precisa de saber quem é para mostrar a conversa.
        identifier: abertura.chaveDoContacto,
      },
    );
    const origem = contacto.payload?.contact?.contact_inboxes?.[0]?.source_id;
    if (!origem) {
      throw new RespostaInesperadaError(
        "/contacts",
        200,
        "contacto criado sem contact_inboxes[0].source_id, e e esse que a " +
          "conversa aponta",
      );
    }

    const token = await this.#tokenDoBot(abertura.conta);
    const conversa = await this.#chamador.json<{ id: number }>(
      "POST",
      `/api/v1/accounts/${abertura.conta.accountId}/conversations`,
      token,
      {
        inbox_id: abertura.conta.inboxId,
        source_id: origem,
        status: "open",
        custom_attributes: { [ATRIBUTO_DO_HANDOFF]: abertura.handoffId },
      },
    );
    // A nota privada com o resumo. **Depois** da conversa e não no mesmo
    // pedido: se esta falhar, a conversa existe e alguém a atende sem o
    // resumo — o contrário (resumo sem conversa) não serve a ninguém. E é
    // `vazio`: o corpo não interessa, e lê-lo como JSON fazia um 200 mal
    // formado degradar uma passagem já aberta.
    await this.#chamador.vazio(
      "POST",
      `/api/v1/accounts/${abertura.conta.accountId}/conversations/${conversa.id}/messages`,
      token,
      { content: abertura.resumo, message_type: "outgoing", private: true },
    );
    return String(conversa.id);
  }

  /**
   * Espelha uma mensagem numa conversa que já existe.
   *
   * O `wamid` vai em `source_id`, que é o campo que o Chatwoot usa para
   * de-duplicar do lado dele. A nossa de-duplicação é a da fila (o `jobId` é o
   * `wamid`); esta é a segunda rede, e as duas são precisas por razões
   * diferentes — a fila protege-nos de reenviar, o `source_id` protege-nos de
   * um reenvio que a fila já esqueceu.
   *
   * **O `externalId` é um argumento**, e é a correcção do defeito: a primeira
   * versão punha o `wamid` no URL, onde vai o identificador da **conversa**.
   */
  async espelhar(
    conta: ContaDeAtendimento,
    externalId: string,
    m: MirrorMessage,
  ): Promise<void> {
    const token = await this.#tokenDoBot(conta);
    await this.#chamador.vazio(
      "POST",
      `/api/v1/accounts/${conta.accountId}/conversations/${externalId}/messages`,
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
    await this.#chamador.vazio(
      "POST",
      `/api/v1/accounts/${conta.accountId}/conversations/${externalId}/toggle_status`,
      token,
      { status: "resolved" },
    );
  }

  /** A URL de saída configurada, para quem precise de a conferir. */
  get urlDeSaida(): string {
    return this.#urlDeSaida;
  }
}
