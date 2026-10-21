/**
 * O provisionamento e as operações do Chatwoot (KAM-019, critérios 1, 2 e 4).
 *
 * **Esta bateria foi reescrita depois de o spike correr, e vale dizer porquê.**
 * A primeira versão estava verde e exigia, por asserção, o comportamento que um
 * Chatwoot verdadeiro recusa com 401: tinha um teste chamado «o provisionamento
 * usa o *token* da plataforma, e só ele» que afirmava `pedido.token ===
 * PLATAFORMA` para **os três** pedidos, incluindo o do *inbox*. O *token* da
 * plataforma não serve os *endpoints* da conta.
 *
 * > **Um duplo prova que o nosso código chama o que pretendíamos chamar. Não
 * > prova que o terceiro aceita a chamada.**
 *
 * O que estes testes prendem agora é a sequência **medida**, e cada asserção
 * aponta para o 401 ou o 404 que a motivou. Os cinco factos estão no
 * `docs/evidencia/KAM-019-bot-open.md` e no preâmbulo da §3.15 do dicionário:
 *
 * 1. O *token* da Platform API cria contas, utilizadores e bots. Nos
 *    *endpoints* `/api/v1/accounts/…` responde **401**.
 * 2. Os *endpoints* da conta querem o `access_token` de um **utilizador**
 *    ligado à conta por `account_users`.
 * 3. O bot tem de ser **ligado ao *inbox*** (`set_agent_bot`), ou a conversa
 *    responde 404 e os *callbacks* não chegam.
 * 4. A conversa quer o `source_id` de um **contacto que exista**.
 * 5. O *token* do bot responde **401** a criar contactos.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ATRIBUTO_DO_HANDOFF,
  ClienteDoChatwoot,
  PAPEL_DO_UTILIZADOR,
  ProvedorIndisponivelError,
  ProvisionadorDoChatwoot,
  RespostaInesperadaError,
  TIPO_DE_BOT,
  TIPO_DE_INBOX,
  type ContaDeAtendimento,
} from "../src/hnd/index.ts";

// Tres valores **distinguiveis** e sem forma de chave. O `scan_secrets` recusou
// a primeira versao destas linhas, com razao: um valor de ensaio que parece uma
// chave a serio e um valor que alguem um dia copia para um ambiente.
const PLATAFORMA = "aaaa-plataforma";
const DO_BOT = "bbbb-bot";
const DO_UTILIZADOR = "dddd-utilizador";
const SEGREDO = "cccc-segredo";
const PALAVRA_PASSE = "eeee-palavra-passe";
const CONTA: ContaDeAtendimento = {
  accountId: 10,
  inboxId: 20,
  botId: 30,
  providerUserId: 40,
};

/** Um pedido que o cliente fez, como o `fetch` falso o viu. */
interface Pedido {
  readonly url: string;
  readonly metodo: string;
  readonly token: string | null;
  readonly corpo: Record<string, unknown>;
}

type Resposta = { estado: number; corpo: unknown } | { estado: number; texto: string };

function buscarFalso(
  pedidos: Pedido[],
  responder: (url: string) => Resposta | Error,
): typeof fetch {
  return (async (url: string, opcoes: RequestInit) => {
    const cabecalhos = opcoes.headers as Record<string, string>;
    pedidos.push({
      url,
      metodo: String(opcoes.method),
      token: cabecalhos["api_access_token"] ?? null,
      corpo: JSON.parse(String(opcoes.body)) as Record<string, unknown>,
    });
    const resultado = responder(url);
    if (resultado instanceof Error) throw resultado;
    const texto =
      "texto" in resultado ? resultado.texto : JSON.stringify(resultado.corpo);
    return {
      ok: resultado.estado >= 200 && resultado.estado < 300,
      status: resultado.estado,
      text: async () => texto,
    } as Response;
  }) as unknown as typeof fetch;
}

interface MontagemDoProvisionamento {
  readonly provisionador: ProvisionadorDoChatwoot;
  readonly pedidos: Pedido[];
}

function montarProvisionamento(
  responder: (url: string) => Resposta | Error,
): MontagemDoProvisionamento {
  const pedidos: Pedido[] = [];
  const provisionador = new ProvisionadorDoChatwoot({
    tokenDaPlataforma: PLATAFORMA,
    urlDeSaida: "https://hnd.kamba.localhost/callbacks",
    segredoDoBot: SEGREDO,
    palavraPasseDoUtilizador: async () => PALAVRA_PASSE,
    buscar: buscarFalso(pedidos, responder),
  });
  return { provisionador, pedidos };
}

interface MontagemDoCliente {
  readonly cliente: ClienteDoChatwoot;
  readonly pedidos: Pedido[];
}

function montarCliente(
  responder: (url: string) => Resposta | Error,
): MontagemDoCliente {
  const pedidos: Pedido[] = [];
  const cliente = new ClienteDoChatwoot({
    tokenDoBot: async () => DO_BOT,
    tokenDoUtilizador: async () => DO_UTILIZADOR,
    urlDeSaida: "https://hnd.kamba.localhost/callbacks",
    buscar: buscarFalso(pedidos, responder),
  });
  return { cliente, pedidos };
}

/** O guião de um provisionamento que corre bem, pela ordem medida. */
function provisionamentoBom(url: string): Resposta {
  if (url.includes("/platform/api/v1/accounts/") && url.includes("account_users")) {
    return { estado: 200, corpo: { id: 1 } };
  }
  if (url.endsWith("/platform/api/v1/accounts")) {
    return { estado: 200, corpo: { id: 10 } };
  }
  if (url.includes("/platform/api/v1/users")) {
    return { estado: 200, corpo: { id: 40, access_token: DO_UTILIZADOR } };
  }
  if (url.includes("/platform/api/v1/agent_bots")) {
    return { estado: 200, corpo: { id: 30, access_token: DO_BOT } };
  }
  if (url.includes("/set_agent_bot")) return { estado: 200, corpo: {} };
  if (url.includes("/inboxes")) return { estado: 200, corpo: { id: 20 } };
  return { estado: 200, corpo: { id: 1 } };
}

/** O guião de uma abertura que corre bem. */
function aberturaBoa(url: string): Resposta {
  if (url.includes("/contacts")) {
    return {
      estado: 200,
      corpo: {
        payload: {
          contact: { id: 7, contact_inboxes: [{ source_id: "origem-do-provedor" }] },
        },
      },
    };
  }
  if (url.includes("/messages")) return { estado: 200, corpo: {} };
  if (url.includes("/conversations")) return { estado: 200, corpo: { id: 9001 } };
  return { estado: 200, corpo: {} };
}

describe("o provisionamento (criterio 1 e 2)", () => {
  it("**sao seis pedidos, pela ordem que o spike mediu**", async () => {
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    const criada = await provisionador.criarConta("t1");

    assert.deepEqual(
      pedidos.map((p) => p.url.replace("http://chatwoot.localhost:3000", "")),
      [
        "/platform/api/v1/accounts",
        "/platform/api/v1/users",
        "/platform/api/v1/accounts/10/account_users",
        "/api/v1/accounts/10/inboxes",
        "/platform/api/v1/agent_bots",
        "/api/v1/accounts/10/inboxes/20/set_agent_bot",
      ],
    );
    assert.deepEqual(criada.conta, {
      accountId: 10,
      inboxId: 20,
      botId: 30,
      providerUserId: 40,
    });
  });

  it("**o inbox e criado com o token do UTILIZADOR e nao da plataforma**", async () => {
    // Medido: `POST /api/v1/accounts/{id}/inboxes` com o token da plataforma
    // responde 401 «Access to this endpoint is not authorized for bots». A
    // primeira versao desta bateria **exigia** o token da plataforma aqui.
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    await provisionador.criarConta("t1");
    const inbox = pedidos.find((p) => p.url.endsWith("/inboxes"));
    assert.equal(inbox?.token, DO_UTILIZADOR);
    assert.notEqual(inbox?.token, PLATAFORMA);
  });

  it("**o set_agent_bot existe, e sem ele nada funciona**", async () => {
    // Sem a ligacao o `POST /conversations` da 404 e o bot nao recebe os
    // callbacks do inbox (criterio 5). Faltava em todo o lado.
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    await provisionador.criarConta("t1");
    const ligacao = pedidos.find((p) => p.url.includes("/set_agent_bot"));
    assert.ok(ligacao !== undefined, "o bot tem de ser ligado ao inbox");
    assert.equal(ligacao.corpo["agent_bot"], 30);
    assert.equal(ligacao.token, DO_UTILIZADOR, "e um endpoint da conta");
  });

  it("os tres pedidos da Platform API usam o token da plataforma", async () => {
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    await provisionador.criarConta("t1");
    for (const pedido of pedidos.filter((p) => p.url.includes("/platform/api/"))) {
      assert.equal(pedido.token, PLATAFORMA, pedido.url);
    }
  });

  it("**o account_id do bot nunca vai nulo**", async () => {
    // Um bot com `account_id` nulo e **global e acessivel a todas as contas**
    // (`E4` §2.2): o bot de uma PME a poder ler as conversas de todas as
    // outras. Exige-se **presente** e nao nulo, nao so «diferente de null».
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    await provisionador.criarConta("t1");
    const bot = pedidos.find((p) => p.url.includes("/agent_bots"));
    assert.ok(bot !== undefined);
    assert.ok("account_id" in bot.corpo, "o campo tem de estar presente");
    assert.equal(bot.corpo["account_id"], 10);
    assert.equal(bot.corpo["bot_type"], TIPO_DE_BOT);
  });

  it("**o inbox e de tipo api e nao de WhatsApp** (criterio 2)", async () => {
    // O GWY e o unico ponto que fala com a Meta (ADR-001) e o Chatwoot e
    // espelho; um inbox de WhatsApp aqui era um segundo caminho para o mesmo
    // numero, com as credenciais da PME do lado dele.
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    await provisionador.criarConta("t1");
    const inbox = pedidos.find((p) => p.url.endsWith("/inboxes"));
    const canal = inbox?.corpo["channel"] as Record<string, unknown>;
    assert.equal(canal["type"], TIPO_DE_INBOX);
    assert.equal(canal["type"], "api");
    assert.notEqual(canal["type"], "whatsapp");
  });

  it("o utilizador entra na conta como administrator", async () => {
    // `agent` nao chega para criar inboxes nem para ligar o bot.
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    await provisionador.criarConta("t1");
    const ligacao = pedidos.find((p) => p.url.includes("account_users"));
    assert.equal(ligacao?.corpo["role"], PAPEL_DO_UTILIZADOR);
    assert.equal(ligacao?.corpo["user_id"], 40);
  });

  it("**os dois access_token sao devolvidos, porque so se veem uma vez**", async () => {
    const { provisionador } = montarProvisionamento(provisionamentoBom);
    const criada = await provisionador.criarConta("t1");
    assert.equal(criada.tokenDoBot, DO_BOT);
    assert.equal(criada.tokenDoUtilizador, DO_UTILIZADOR);
  });

  it("**um utilizador sem access_token levanta e nao segue**", async () => {
    // Sem ele nao ha token de conta, e continuar criava um inbox que ninguem
    // consegue usar — ou, pior, uma linha na base sem nada atras das refs.
    const { provisionador } = montarProvisionamento((url) =>
      url.includes("/platform/api/v1/users")
        ? { estado: 200, corpo: { id: 40 } }
        : provisionamentoBom(url),
    );
    await assert.rejects(
      () => provisionador.criarConta("t1"),
      RespostaInesperadaError,
    );
  });

  it("**um bot sem access_token levanta**", async () => {
    const { provisionador } = montarProvisionamento((url) =>
      url.includes("/agent_bots")
        ? { estado: 200, corpo: { id: 30 } }
        : provisionamentoBom(url),
    );
    await assert.rejects(
      () => provisionador.criarConta("t1"),
      RespostaInesperadaError,
    );
  });

  it("a palavra-passe vem da porta e nao de um literal", async () => {
    // Uma palavra-passe num literal deste ficheiro era a mesma em todas as
    // contas de todas as PMEs. O Chatwoot recusa com 422 sem maiuscula e
    // digito — medido no spike.
    const { provisionador, pedidos } = montarProvisionamento(provisionamentoBom);
    await provisionador.criarConta("t1");
    const utilizador = pedidos.find((p) => p.url.includes("/users"));
    assert.equal(utilizador?.corpo["password"], PALAVRA_PASSE);
  });

  it("um 5xx vira ProvedorIndisponivelError", async () => {
    const { provisionador } = montarProvisionamento(() => ({
      estado: 503,
      corpo: {},
    }));
    await assert.rejects(
      () => provisionador.criarConta("t1"),
      ProvedorIndisponivelError,
    );
  });

  it("um 4xx **nao** degrada: e um pedido nosso errado", async () => {
    // Degradar por causa de um 4xx escondia um defeito atras de uma fila que
    // nunca drenava.
    const { provisionador } = montarProvisionamento(() => ({
      estado: 422,
      corpo: { error: "assim nao" },
    }));
    await assert.rejects(
      () => provisionador.criarConta("t1"),
      RespostaInesperadaError,
    );
  });

  it("uma falha de rede vira ProvedorIndisponivelError", async () => {
    const { provisionador } = montarProvisionamento(() => new TypeError("fetch failed"));
    await assert.rejects(
      () => provisionador.criarConta("t1"),
      ProvedorIndisponivelError,
    );
  });
});

describe("a abertura da conversa (criterio 4)", () => {
  it("**o contacto vem antes da conversa, e com o token do utilizador**", async () => {
    // Medido: o token do bot responde 401 a criar contactos, e a conversa quer
    // o `source_id` de um `contact_inbox` que exista — um valor inventado da
    // 404.
    const { cliente, pedidos } = montarCliente(aberturaBoa);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "o cliente quer falar com alguem",
    });
    const contacto = pedidos[0];
    assert.ok(contacto !== undefined, "houve pedido");
    assert.ok(contacto.url.includes("/contacts"), "o contacto e o primeiro");
    assert.equal(contacto.token, DO_UTILIZADOR);
    assert.ok(pedidos[1]?.url.endsWith("/conversations"));
  });

  it("**a conversa usa o source_id que o provedor emitiu**", async () => {
    const { cliente, pedidos } = montarCliente(aberturaBoa);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "resumo",
    });
    const conversa = pedidos.find((p) => p.url.endsWith("/conversations"));
    assert.equal(conversa?.corpo["source_id"], "origem-do-provedor");
  });

  it("**a chave opaca nao e o nosso contact_id, e nada nosso sai**", async () => {
    // A primeira versao punha o nosso `contact_id` no `source_id`: um
    // identificador nosso a sair para fora, contra o ADR-010, no mesmo modulo
    // que diz na nota do `MirrorMessage` que isso nao se faz. Os quatro testes
    // de entao inspeccionavam o atributo, o inbox, o estado e o token, e
    // **nenhum** procurava o identificador no corpo.
    const NOSSO_ID = "33333333-3333-4333-8333-333333333333";
    const { cliente, pedidos } = montarCliente(aberturaBoa);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "resumo",
    });
    const tudo = JSON.stringify(pedidos);
    assert.ok(!tudo.includes(NOSSO_ID), "nenhum identificador nosso sai");
    const contacto = pedidos.find((p) => p.url.includes("/contacts"));
    assert.equal(contacto?.corpo["identifier"], "chave-opaca");
    // E o que **nao** vai: nem telefone, nem nome.
    assert.ok(!("phone_number" in (contacto?.corpo ?? {})));
    assert.ok(!("name" in (contacto?.corpo ?? {})));
  });

  it("**um contacto sem source_id levanta e nao abre conversa**", async () => {
    const { cliente, pedidos } = montarCliente((url) =>
      url.includes("/contacts")
        ? { estado: 200, corpo: { payload: { contact: { id: 7 } } } }
        : aberturaBoa(url),
    );
    await assert.rejects(
      () =>
        cliente.abrirConversa({
          conta: CONTA,
          handoffId: "h_abc",
          chaveDoContacto: "chave-opaca",
          resumo: "resumo",
        }),
      RespostaInesperadaError,
    );
    assert.equal(
      pedidos.filter((p) => p.url.endsWith("/conversations")).length,
      0,
      "sem source_id nao se tenta a conversa",
    );
  });

  it("**le-se `payload.contact` e nao `payload`**", async () => {
    // Medido: ler `payload` directamente da um objecto sem `contact_inboxes`, e
    // o spike parou a dizer que o Chatwoot nao devolvia o `source_id` quando
    // devolvia. Aqui o `source_id` esta **so** no sitio certo.
    const { cliente } = montarCliente((url) =>
      url.includes("/contacts")
        ? {
            estado: 200,
            corpo: {
              payload: {
                contact: { contact_inboxes: [{ source_id: "o-certo" }] },
                contact_inboxes: [{ source_id: "o-errado" }],
              },
            },
          }
        : aberturaBoa(url),
    );
    const id = await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "resumo",
    });
    assert.equal(id, "9001");
  });

  it("a conversa leva o handoffId no atributo e o token do bot", async () => {
    const { cliente, pedidos } = montarCliente(aberturaBoa);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "resumo",
    });
    const conversa = pedidos.find((p) => p.url.endsWith("/conversations"));
    const atributos = conversa?.corpo["custom_attributes"] as Record<string, unknown>;
    assert.equal(atributos[ATRIBUTO_DO_HANDOFF], "h_abc");
    assert.equal(conversa?.corpo["status"], "open");
    assert.equal(conversa?.token, DO_BOT);
  });

  it("a nota privada vem **depois** da conversa, e e privada", async () => {
    // Se esta falhar, a conversa existe e alguem a atende sem o resumo. O
    // contrario — resumo sem conversa — nao serve a ninguem.
    const { cliente, pedidos } = montarCliente(aberturaBoa);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "o resumo que a pessoa vai ler",
    });
    const nota = pedidos.at(-1);
    assert.ok(nota !== undefined, "houve pedido");
    assert.ok(nota.url.includes("/conversations/9001/messages"));
    assert.equal(nota.corpo["private"], true);
    assert.equal(nota.corpo["content"], "o resumo que a pessoa vai ler");
  });

  it("**um 200 com corpo vazio na nota nao degrada a passagem**", async () => {
    // A primeira versao fazia `json()` em todas as chamadas: um 200 com corpo
    // vazio na nota privada virava `ProvedorIndisponivelError` e o
    // `openHandoff` degradava uma passagem **cuja conversa ja existia** no
    // provedor — a orfa que a ordem dos passos existe para evitar.
    const { cliente } = montarCliente((url) =>
      url.includes("/messages")
        ? { estado: 200, texto: "" }
        : aberturaBoa(url),
    );
    const id = await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "resumo",
    });
    assert.equal(id, "9001", "a conversa abriu e a nota nao a derrubou");
  });

  it("**um 200 que nao e JSON onde se le JSON levanta Inesperada**", async () => {
    // E nao `Indisponivel`: um corpo que nao entendemos e um mal-entendido
    // nosso sobre a API, e uma fila que o repetisse nunca drenava.
    const { cliente } = montarCliente((url) =>
      url.includes("/contacts") ? { estado: 200, texto: "<html>" } : aberturaBoa(url),
    );
    await assert.rejects(
      () =>
        cliente.abrirConversa({
          conta: CONTA,
          handoffId: "h_abc",
          chaveDoContacto: "chave-opaca",
          resumo: "resumo",
        }),
      RespostaInesperadaError,
    );
  });
});

describe("o espelho e o fecho", () => {
  it("**o espelho usa o externalId no URL e o wamid no corpo**", async () => {
    // A primeira versao punha o `wamid` **no URL**, onde vai o identificador da
    // conversa: qualquer chamada real dava 404. O teste de entao afirmava o
    // corpo e nunca o `url`, e e por isso que o defeito passou.
    const { cliente, pedidos } = montarCliente(() => ({ estado: 200, corpo: {} }));
    await cliente.espelhar(CONTA, "9001", {
      wamid: "wamid.HBgLABC",
      direccao: "entrada",
      waType: "text",
      texto: "bom dia",
      criadoEm: new Date(0),
    });
    assert.equal(pedidos.length, 1);
    assert.ok(
      pedidos[0]?.url.endsWith("/api/v1/accounts/10/conversations/9001/messages"),
      `o URL leva a conversa e nao o wamid: ${pedidos[0]?.url}`,
    );
    assert.ok(!pedidos[0]?.url.includes("wamid"), "o wamid nao entra no URL");
    assert.equal(pedidos[0]?.corpo["source_id"], "wamid.HBgLABC");
    assert.equal(pedidos[0]?.corpo["message_type"], "incoming");
  });

  it("uma mensagem de saida vai como outgoing", async () => {
    const { cliente, pedidos } = montarCliente(() => ({ estado: 200, corpo: {} }));
    await cliente.espelhar(CONTA, "9001", {
      wamid: "wamid.HBgLXYZ",
      direccao: "saida",
      waType: "text",
      texto: "ja vai",
      criadoEm: new Date(0),
    });
    assert.equal(pedidos[0]?.corpo["message_type"], "outgoing");
  });

  it("o fecho poe a conversa em resolved, com o token do bot", async () => {
    const { cliente, pedidos } = montarCliente(() => ({ estado: 200, corpo: {} }));
    await cliente.fecharConversa(CONTA, "9001");
    assert.ok(pedidos[0]?.url.endsWith("/conversations/9001/toggle_status"));
    assert.equal(pedidos[0]?.corpo["status"], "resolved");
    assert.equal(pedidos[0]?.token, DO_BOT);
  });

  it("**o cliente de execucao nao conhece o token da plataforma**", async () => {
    // E a propriedade do `docs/tecnica/08` §3.6: «o token da Platform API
    // (poderoso) so existe no servico de provisioning, nunca no AGR». A
    // primeira versao punha-o como campo obrigatorio **deste** objecto, pelo
    // que qualquer processo que abrisse uma conversa tinha de o ter em memoria.
    // Um parametro distinto nao e um processo distinto.
    const { cliente, pedidos } = montarCliente(aberturaBoa);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      chaveDoContacto: "chave-opaca",
      resumo: "resumo",
    });
    for (const pedido of pedidos) {
      assert.notEqual(pedido.token, PLATAFORMA, pedido.url);
      assert.ok(!pedido.url.includes("/platform/api/"), pedido.url);
    }
    assert.ok(!JSON.stringify(cliente).includes(PLATAFORMA));
  });
});
