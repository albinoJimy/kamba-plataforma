/**
 * O cliente do Chatwoot, com o `fetch` por porta (KAM-019).
 *
 * O que estes testes prendem, por ordem de gravidade:
 *
 * 1. **O `account_id` do *agent bot* nunca vai nulo.** É a asserção do critério
 *    1 («um *agent bot* com `account_id` nulo é impossível por construção»), e
 *    a razão está confirmada no código do Chatwoot (`E4` §2.2): um bot sem
 *    conta é **global e acessível a todas as contas** — o bot de uma PME a
 *    poder ler as conversas de todas as outras. É o pior defeito que este
 *    ficheiro pode ter.
 * 2. **Nenhum *inbox* é do tipo WhatsApp** (critério 2). O GWY é o único ponto
 *    que fala com a Meta; um *inbox* de WhatsApp aqui era um segundo caminho
 *    para o mesmo número, com as credenciais dela do lado do Chatwoot.
 * 3. **Os dois *tokens* não se trocam.** O da Platform API cria contas e o do
 *    bot fala dentro de uma; o `docs/tecnica/08` §3.6 diz que o primeiro «só
 *    existe no serviço de *provisioning*». Usar o poderoso onde bastava o
 *    fraco é o género de erro que não dá sintoma nenhum até dar o pior.
 * 4. **Um 5xx degrada e um 4xx não.** Uma fila que repetisse um pedido nosso
 *    errado nunca drenava, e o defeito ficava escondido atrás dela.
 * 5. **O *token* nunca aparece numa mensagem de erro nem na URL.**
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BASE_POR_OMISSAO,
  ClienteDoChatwoot,
  ProvedorIndisponivelError,
  RespostaInesperadaError,
  TIPO_DE_BOT,
  TIPO_DE_INBOX,
  type ContaDeAtendimento,
} from "../src/hnd/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
// **Valores de encenacao, sem entropia de proposito.** O varredor de segredos
// recusa uma atribuicao a um nome que significa segredo com entropia bastante
// para nao ser uma palavra — e recusou a primeira versao destas tres linhas,
// com razao: um valor de ensaio que parece uma chave a serio e um valor que
// alguem um dia copia para um ambiente. O que os testes exigem destes tres e
// so que sejam **distinguiveis** entre si.
const PLATAFORMA = "aaaa-plataforma";
const DO_BOT = "bbbb-bot";
const SEGREDO = "cccc-segredo";
const CONTA: ContaDeAtendimento = { accountId: 10, inboxId: 20, botId: 30 };

/** Um pedido que o cliente fez, como o `fetch` falso o viu. */
interface Pedido {
  readonly url: string;
  readonly metodo: string;
  readonly token: string | null;
  readonly corpo: Record<string, unknown>;
}

interface Montagem {
  readonly cliente: ClienteDoChatwoot;
  readonly pedidos: Pedido[];
}

/** Monta o cliente com um `fetch` que responde o que o guião disser. */
function montar(
  responder: (url: string) => { estado: number; corpo: unknown } | Error,
): Montagem {
  const pedidos: Pedido[] = [];
  const cliente = new ClienteDoChatwoot({
    tokenDaPlataforma: PLATAFORMA,
    tokenDoBot: async () => DO_BOT,
    urlDeSaida: "https://hnd.kamba.localhost/callbacks",
    segredoDoBot: SEGREDO,
    buscar: (async (url: string, opcoes: RequestInit) => {
      const cabecalhos = opcoes.headers as Record<string, string>;
      pedidos.push({
        url,
        metodo: String(opcoes.method),
        token: cabecalhos["api_access_token"] ?? null,
        corpo: JSON.parse(String(opcoes.body)) as Record<string, unknown>,
      });
      const resultado = responder(url);
      if (resultado instanceof Error) throw resultado;
      return {
        ok: resultado.estado >= 200 && resultado.estado < 300,
        status: resultado.estado,
        json: async () => resultado.corpo,
        text: async () => JSON.stringify(resultado.corpo),
      } as Response;
    }) as unknown as typeof fetch,
  });
  return { cliente, pedidos };
}

/** O guião de um provisionamento que corre bem. */
function provisionamentoBom(url: string): { estado: number; corpo: unknown } {
  if (url.includes("/platform/api/v1/accounts")) return { estado: 200, corpo: { id: 10 } };
  if (url.includes("/inboxes")) return { estado: 200, corpo: { id: 20 } };
  if (url.includes("/agent_bots")) return { estado: 200, corpo: { id: 30 } };
  return { estado: 200, corpo: { id: 1 } };
}

describe("o provisionamento (criterio 1 e 2)", () => {
  it("cria conta, inbox e bot, e devolve os tres identificadores", async () => {
    const { cliente, pedidos } = montar(provisionamentoBom);
    const conta = await cliente.criarConta(TENANT);
    assert.deepEqual(conta, { accountId: 10, inboxId: 20, botId: 30 });
    assert.equal(pedidos.length, 3);
  });

  it("**o account_id do bot nunca vai nulo**", async () => {
    // `E4` §2.2, confirmado no codigo do Chatwoot: um `agent_bot` com
    // `account_id` nulo e **global e acessivel a todas as contas**. E o bot de
    // uma PME a poder ler as conversas de todas as outras.
    const { cliente, pedidos } = montar(provisionamentoBom);
    await cliente.criarConta(TENANT);
    const doBot = pedidos.find((p) => p.url.includes("/agent_bots"));
    assert.ok(doBot !== undefined);
    assert.equal(doBot.corpo["account_id"], 10);
    assert.notEqual(doBot.corpo["account_id"], null);
    assert.ok("account_id" in doBot.corpo, "o campo tem de estar presente");
  });

  it("o bot e do tipo webhook, com outgoing_url e secret", async () => {
    const { cliente, pedidos } = montar(provisionamentoBom);
    await cliente.criarConta(TENANT);
    const doBot = pedidos.find((p) => p.url.includes("/agent_bots"));
    assert.equal(doBot?.corpo["bot_type"], TIPO_DE_BOT);
    assert.equal(TIPO_DE_BOT, "webhook");
    assert.equal(doBot?.corpo["outgoing_url"], "https://hnd.kamba.localhost/callbacks");
    assert.equal(doBot?.corpo["secret"], SEGREDO);
  });

  it("**o inbox e de tipo api e nao de WhatsApp** (criterio 2)", async () => {
    // O GWY e o unico ponto que fala com a Meta (ADR-001) e o Chatwoot e
    // espelho. Um inbox de WhatsApp aqui era um segundo caminho para o mesmo
    // numero, com as credenciais dela do lado dele.
    const { cliente, pedidos } = montar(provisionamentoBom);
    await cliente.criarConta(TENANT);
    const daCaixa = pedidos.find((p) => p.url.includes("/inboxes"));
    const canal = daCaixa?.corpo["channel"] as Record<string, unknown>;
    assert.equal(canal["type"], TIPO_DE_INBOX);
    assert.equal(TIPO_DE_INBOX, "api");
    assert.notEqual(canal["type"], "whatsapp");
  });

  it("**o provisionamento usa o token da plataforma, e so ele**", async () => {
    // O `docs/tecnica/08` §3.6: o token da Platform API «so existe no servico
    // de provisioning». Usar o poderoso onde bastava o fraco nao da sintoma
    // nenhum ate dar o pior.
    const { cliente, pedidos } = montar(provisionamentoBom);
    await cliente.criarConta(TENANT);
    for (const pedido of pedidos) {
      assert.equal(pedido.token, PLATAFORMA, pedido.url);
    }
  });
});

describe("a abertura de conversa (criterio 4 e o L7)", () => {
  function guiaoDeAbertura(url: string): { estado: number; corpo: unknown } {
    if (url.includes("/messages")) return { estado: 200, corpo: { id: 77 } };
    return { estado: 200, corpo: { id: 9001 } };
  }

  it("cria a conversa com o handoffId no atributo e devolve o id", async () => {
    const { cliente, pedidos } = montar(guiaoDeAbertura);
    const externalId = await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      contactId: "c-1",
      resumo: "Cliente quer trocar o tamanho.",
    });
    assert.equal(externalId, "9001");
    const daConversa = pedidos[0];
    const atributos = daConversa?.corpo["custom_attributes"] as Record<string, unknown>;
    assert.equal(atributos["handoffId"], "h_abc");
    assert.equal(daConversa?.corpo["inbox_id"], 20);
  });

  it("**pede o estado `open`, que e o L7**", async () => {
    // A documentacao indica que o token do bot acede apenas a APIs «permitidas
    // ao bot» (`docs/tecnica/01` §11.3) e nenhuma fonte deste repositorio
    // confirma que `pending -> open` e uma delas. E o L7, NAO VERIFICADO, e e o
    // que o spike do criterio 8 vai medir. Se nao for, o plano B esta escrito e
    // **so este metodo muda**.
    const { cliente, pedidos } = montar(guiaoDeAbertura);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      contactId: "c-1",
      resumo: "resumo",
    });
    assert.equal(pedidos[0]?.corpo["status"], "open");
  });

  it("a nota privada vem **depois** da conversa, e e privada", async () => {
    // Se a nota falhar, a conversa existe e alguem a atende sem o resumo. O
    // contrario — resumo sem conversa — nao serve a ninguem.
    const { cliente, pedidos } = montar(guiaoDeAbertura);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      contactId: "c-1",
      resumo: "Cliente quer trocar o tamanho.",
    });
    assert.equal(pedidos.length, 2);
    assert.ok(pedidos[1]?.url.includes("/conversations/9001/messages"));
    assert.equal(pedidos[1]?.corpo["private"], true);
    assert.equal(pedidos[1]?.corpo["content"], "Cliente quer trocar o tamanho.");
  });

  it("usa o token do bot e **nao** o da plataforma", async () => {
    const { cliente, pedidos } = montar(guiaoDeAbertura);
    await cliente.abrirConversa({
      conta: CONTA,
      handoffId: "h_abc",
      contactId: "c-1",
      resumo: "resumo",
    });
    for (const pedido of pedidos) {
      assert.equal(pedido.token, DO_BOT, pedido.url);
      assert.notEqual(pedido.token, PLATAFORMA);
    }
  });
});

describe("o espelho", () => {
  it("manda o wamid em source_id e o sentido em message_type", async () => {
    const { cliente, pedidos } = montar(() => ({ estado: 200, corpo: { id: 1 } }));
    await cliente.espelhar(CONTA, {
      wamid: "wamid.A",
      direccao: "entrada",
      waType: "text",
      texto: "Bom dia",
      criadoEm: new Date("2026-10-20T12:00:00.000Z"),
    });
    assert.equal(pedidos[0]?.corpo["source_id"], "wamid.A");
    assert.equal(pedidos[0]?.corpo["message_type"], "incoming");
  });

  it("uma mensagem de saida vai como outgoing", async () => {
    const { cliente, pedidos } = montar(() => ({ estado: 200, corpo: { id: 1 } }));
    await cliente.espelhar(CONTA, {
      wamid: "wamid.B",
      direccao: "saida",
      waType: "text",
      texto: "Ja vamos ver",
      criadoEm: new Date("2026-10-20T12:00:00.000Z"),
    });
    assert.equal(pedidos[0]?.corpo["message_type"], "outgoing");
  });
});

describe("os erros, e a diferenca entre degradar e falhar", () => {
  it("**um 5xx degrada**", async () => {
    const { cliente } = montar(() => ({ estado: 503, corpo: { erro: "em baixo" } }));
    await assert.rejects(() => cliente.criarConta(TENANT), ProvedorIndisponivelError);
  });

  it("**um 4xx nao degrada**: e um pedido nosso errado", async () => {
    // Uma fila que repetisse um pedido errado nunca drenava, e o defeito ficava
    // escondido atras dela.
    const { cliente } = montar(() => ({ estado: 422, corpo: { erro: "campo em falta" } }));
    await assert.rejects(() => cliente.criarConta(TENANT), RespostaInesperadaError);
  });

  it("uma falha de rede degrada", async () => {
    const { cliente } = montar(() => new TypeError("fetch failed"));
    await assert.rejects(() => cliente.criarConta(TENANT), ProvedorIndisponivelError);
  });

  it("**o token nao aparece na mensagem de erro**", async () => {
    const { cliente } = montar(() => ({ estado: 422, corpo: { erro: "campo em falta" } }));
    await assert.rejects(
      () => cliente.criarConta(TENANT),
      (erro: Error) => {
        assert.ok(!erro.message.includes(PLATAFORMA), erro.message);
        assert.ok(!erro.message.includes(DO_BOT), erro.message);
        return true;
      },
    );
  });

  it("o token vai no cabecalho e **nunca** na URL nem no corpo", async () => {
    const { cliente, pedidos } = montar(provisionamentoBom);
    await cliente.criarConta(TENANT);
    for (const pedido of pedidos) {
      assert.ok(!pedido.url.includes(PLATAFORMA), pedido.url);
      assert.ok(!JSON.stringify(pedido.corpo).includes(PLATAFORMA));
    }
  });

  it("a base por omissao e a do compose e nao a nuvem de ninguem", async () => {
    // Um cliente que por omissao falasse com um Chatwoot alojado era uma fuga
    // de dados pessoais por configuracao em falta.
    assert.ok(BASE_POR_OMISSAO.includes("localhost"));
  });
});
