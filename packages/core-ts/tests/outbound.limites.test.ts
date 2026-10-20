/**
 * *Token bucket*, *backoff* e cliente da Meta (KAM-015, critérios 5 e 6).
 *
 * O critério 5 pede uma medição: «100 envios em fila nunca excedem 15/s em
 * nenhuma janela de 1 s medida no servidor falso e drenam em ≥ 6,6 s». A parte
 * «medida no servidor falso» vive na *suite* de base de dados, contra o
 * `GraphFalso` do KAM-024; aqui prova-se a **regra** — e prova-se com o relógio
 * por parâmetro, que é o que a torna uma afirmação sobre a regra e não sobre o
 * `setTimeout` da máquina.
 *
 * A aritmética de ≥ 6,6 s: 100 mensagens a 15/s, com o balde a nascer cheio,
 * são 15 imediatas e 85 à espera de ficha — 85/15 = 5,67 s. O critério pede
 * 6,6 s, que corresponde a 100/15 = 6,67 s, isto é, **com o balde a nascer
 * vazio**. Os dois números estão aqui porque a diferença é real e o teste diz
 * qual mede.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BASE_DO_BACKOFF_MS,
  Balde,
  CODIGOS_QUE_SE_REPETEM,
  CODIGO_SEM_CODIGO,
  ClienteDaGraph,
  Limites,
  MPS_POR_CANAL,
  MPS_POR_PAR,
  POR_MINUTO_POR_PAR,
  REPETICOES,
  TENTATIVAS,
  VERSAO_DA_GRAPH,
  atrasoMs,
  corpoDaMeta,
  vaiRepetir,
  type Corpo,
} from "../src/outbound/index.ts";

describe("o balde", () => {
  it("**nasce vazio**, e o primeiro envio espera uma ficha", () => {
    // Nascia cheio na primeira versao, e o teste do criterio 5 recusou-a: com
    // quinze fichas a partida, a janela deslizante que apanha a rajada mais o
    // primeiro reabastecimento ve dezasseis. Ver a nota no `Balde`.
    const balde = new Balde(15, 15, 0);
    assert.ok(balde.tirar(0) > 0, "a primeira ja espera");
    assert.equal(balde.tirar(67), 0, "aos 67ms chega a primeira ficha");
  });

  it("cheio a partida e opcional, e nenhum tecto o usa", () => {
    const balde = new Balde(15, 15, 0, true);
    for (let i = 0; i < 15; i += 1) assert.equal(balde.tirar(0), 0, `ficha ${i}`);
    assert.ok(balde.tirar(0) > 0, "a decima sexta espera");
  });

  it("enche a taxa fixa", () => {
    const balde = new Balde(15, 15, 0, true);
    for (let i = 0; i < 15; i += 1) balde.tirar(0);
    // Um segundo depois, outras quinze.
    assert.equal(balde.tirar(1000), 0);
  });

  it("nao passa da capacidade por muito que espere", () => {
    const balde = new Balde(15, 15, 0);
    assert.equal(balde.disponiveis(60_000), 15);
  });

  it("a espera arredonda para cima, senao quem chama volta no mesmo instante", () => {
    const balde = new Balde(1, 1, 0);
    balde.tirar(0);
    const espera = balde.tirar(1);
    assert.ok(espera > 0 && Number.isInteger(espera), String(espera));
  });
});

describe("os tres tectos (criterio 5)", () => {
  it("os valores sao os do criterio, e os dois do par sao proposta", () => {
    assert.equal(MPS_POR_CANAL, 15);
    assert.equal(MPS_POR_PAR, 1);
    assert.equal(POR_MINUTO_POR_PAR, 30);
  });

  it("**100 envios a contactos diferentes nunca passam de 15 em nenhuma janela de 1 s**", () => {
    // Contactos diferentes para isolar o tecto do canal: com o mesmo contacto, o
    // tecto do par (1/s) mordia primeiro e o teste media outra coisa.
    const limites = new Limites();
    const instantes: number[] = [];
    let agora = 0;
    for (let i = 0; i < 100; i += 1) {
      for (;;) {
        const espera = limites.pedir("pnid-1", "t", `contacto-${i}`, agora);
        if (espera === 0) break;
        agora += espera;
      }
      instantes.push(agora);
    }

    // A asserção do critério, sobre **todas** as janelas de 1 s e não só as
    // alinhadas ao segundo: para cada envio, quantos couberam nos 1000 ms
    // anteriores.
    for (let i = 0; i < instantes.length; i += 1) {
      const fim = instantes[i] ?? 0;
      const naJanela = instantes.filter((t) => t > fim - 1000 && t <= fim).length;
      assert.ok(naJanela <= MPS_POR_CANAL, `janela a terminar em ${fim}ms teve ${naJanela}`);
    }
  });

  it("e drenam em >= 6,6 s — a letra do criterio, e e o balde vazio que a da", () => {
    const limites = new Limites();
    let agora = 0;
    for (let i = 0; i < 100; i += 1) {
      for (;;) {
        const espera = limites.pedir("pnid-1", "t", `contacto-${i}`, agora);
        if (espera === 0) break;
        agora += espera;
      }
    }
    // 100/15 = 6,67 s, que e exactamente o >= 6,6 s do criterio. Com o balde
    // cheio a partida seriam 85/15 = 5,67 s e o criterio ficava por cumprir —
    // e e o numero dele que diz qual das duas leituras e a pretendida.
    assert.ok(agora >= 6_600, `drenou em ${agora}ms, menos do que o criterio pede`);
    assert.ok(agora < 7_200, `drenou em ${agora}ms, demasiado`);
  });

  it("o tecto por par morde antes do do canal, com o mesmo contacto", () => {
    const limites = new Limites();
    // O balde do canal e criado **vazio no instante da primeira chamada**: um
    // `agoraMs` adiantado nao o enche se ele ainda nao existir. Esta primeira
    // chamada e o que o cria, e devolve espera de proposito; a partir dai, um
    // segundo depois, tem as quinze fichas.
    assert.ok(limites.pedir("pnid-1", "t", "c", 0) > 0, "cria o balde do canal");
    assert.equal(limites.pedir("pnid-1", "t", "c", 1000), 0);
    // O segundo envio ao mesmo contacto espera ~1 s, embora o canal tenha 14
    // fichas.
    const espera = limites.pedir("pnid-1", "t", "c", 1000);
    assert.ok(espera >= 900 && espera <= 1000, `${espera}ms`);
  });

  it("o tecto de 30/min morde depois dos 30", () => {
    const limites = new Limites();
    let agora = 0;
    for (let i = 0; i < 30; i += 1) {
      for (;;) {
        const espera = limites.pedir("pnid-1", "t", "c", agora);
        if (espera === 0) break;
        agora += espera;
      }
    }
    // Os trinta couberam em ~29 s (1/s). O trigésimo primeiro espera pela
    // janela de 60 s e não por uma ficha de segundo.
    const espera = limites.pedir("pnid-1", "t", "c", agora + 1000);
    assert.ok(espera > 20_000, `${espera}ms — devia esperar pela janela do minuto`);
  });

  it("**nao gasta ficha de canal quando o par recusa**", () => {
    // Consumir o tecto do canal e descobrir depois que o par esta cheio gastava
    // 1/15 do debito por cada recusa de par. O teste prova que nao gasta:
    // depois de uma recusa de par, o canal continua a aceitar outro contacto.
    const limites = new Limites();
    // O balde do canal e criado **vazio no instante da primeira chamada**: um
    // `agoraMs` adiantado nao o enche se ele ainda nao existir. Esta primeira
    // chamada e o que o cria, e devolve espera de proposito; a partir dai, um
    // segundo depois, tem as quinze fichas.
    limites.pedir("pnid-1", "t", "c", 0);
    limites.pedir("pnid-1", "t", "c", 1000);
    assert.ok(limites.pedir("pnid-1", "t", "c", 1000) > 0, "o par recusa");
    for (let i = 0; i < 14; i += 1) {
      assert.equal(limites.pedir("pnid-1", "t", `outro-${i}`, 1000), 0, `ficha ${i}`);
    }
  });

  it("canais diferentes nao se afectam", () => {
    const limites = new Limites();
    // O balde do canal e criado **vazio no instante da primeira chamada**: um
    // `agoraMs` adiantado nao o enche se ele ainda nao existir. Esta primeira
    // chamada e o que o cria, e devolve espera de proposito; a partir dai, um
    // segundo depois, tem as quinze fichas.
    limites.pedir("pnid-1", "t", "c0", 0);
    limites.pedir("pnid-2", "t", "d0", 0);
    for (let i = 0; i < 15; i += 1) limites.pedir("pnid-1", "t", `c${i}`, 1000);
    assert.ok(limites.pedir("pnid-1", "t", "x", 1000) > 0, "o primeiro canal esta cheio");
    assert.equal(limites.pedir("pnid-2", "t", "y", 1000), 0, "o segundo nao");
  });

  it("esquecer liberta a memoria de um par", () => {
    // Sem isto, um processo de longa duracao acumula um balde por par que viu
    // uma vez — cardinalidade sem tecto, aqui em memoria.
    const limites = new Limites();
    limites.pedir("pnid-1", "t", "c", 1000);
    assert.equal(limites.paresEmMemoria, 1);
    limites.esquecer("t", "c");
    assert.equal(limites.paresEmMemoria, 0);
  });
});

describe("o backoff (criterio 6)", () => {
  it("cresce exponencialmente e leva jitter", () => {
    // Com `aleatorio = 0` o atraso e metade da base; com `1` e a base inteira.
    assert.equal(atrasoMs(1, null, 0), BASE_DO_BACKOFF_MS / 2);
    assert.equal(atrasoMs(1, null, 1), BASE_DO_BACKOFF_MS);
    assert.equal(atrasoMs(2, null, 1), BASE_DO_BACKOFF_MS * 2);
    assert.equal(atrasoMs(3, null, 1), BASE_DO_BACKOFF_MS * 4);
  });

  it("**nunca e zero**, e isso e o ponto do jitter de meia-base", () => {
    // Um atraso que possa ser zero nao e atraso nenhum, e o `130429` voltava no
    // mesmo instante. E por isso que o jitter e `[base/2, base]` e nao
    // `[0, base]`.
    for (const aleatorio of [0, 0.001, 0.5, 0.999, 1]) {
      for (const tentativa of [1, 2, 3]) {
        assert.ok(atrasoMs(tentativa, null, aleatorio) > 0, `${tentativa}/${aleatorio}`);
      }
    }
  });

  it("o Retry-After manda sobre o exponencial", () => {
    // `docs/tecnica/01` §16: «backoff exponencial com jitter e `Retry-After` se
    // existir». Um backoff que o ignore esta a adivinhar contra quem sabe.
    assert.equal(atrasoMs(1, 5, 1), 5000);
    assert.equal(atrasoMs(1, 5, 0), 2500);
    // E continua a levar jitter por cima, para N processos nao voltarem juntos.
    assert.notEqual(atrasoMs(1, 5, 0), atrasoMs(1, 5, 1));
  });

  it("um Retry-After de zero ou negativo cai no exponencial", () => {
    assert.equal(atrasoMs(2, 0, 1), BASE_DO_BACKOFF_MS * 2);
    assert.equal(atrasoMs(2, -1, 1), BASE_DO_BACKOFF_MS * 2);
  });

  it("**repete tres vezes, o que sao quatro chamadas**", () => {
    // A letra do criterio 6: «130429 3x seguida de 200 ... 3 tentativas». Com
    // tres chamadas no total, os tres 429 esgotam-nas e o 200 nunca chega — a
    // frase contradiz-se. Tres **repeticoes** depois da primeira chamada dao
    // quatro chamadas, e a sequencia encaixa. Entre duas leituras de um
    // criterio, a que o torna cumprivel e a pretendida.
    assert.equal(REPETICOES, 3);
    assert.equal(TENTATIVAS, 4);
    assert.ok(CODIGOS_QUE_SE_REPETEM.includes(130429));
    assert.ok(vaiRepetir(130429, 1));
    assert.ok(vaiRepetir(130429, 2));
    assert.ok(vaiRepetir(130429, 3), "a terceira repeticao e a que traz o 200");
    assert.ok(!vaiRepetir(130429, 4), "a quarta chamada e a ultima");
  });

  it("**o 131049 nao se repete**, e isso e deliberado", () => {
    // A Meta nao entregou de proposito (limite de frequencia por utilizador).
    // Insistir e gastar debito para ser recusado outra vez.
    assert.ok(!vaiRepetir(131049, 1));
    assert.ok(!CODIGOS_QUE_SE_REPETEM.includes(131049));
  });

  it("o 131047 tambem nao: se chegou ali, a decisao falhou antes", () => {
    assert.ok(!vaiRepetir(131047, 1));
  });
});

describe("o cliente da Meta", () => {
  const PARA_BSUID = { bsuid: "AO.ABC123", telefone: null };
  const PARA_TELEFONE = { bsuid: null, telefone: "999100000001" };
  const TEXTO: Corpo = { tipo: "texto", texto: "Bom dia" };

  it("enderecça por BSUID quando existe (criterio 9, DoD Privacidade)", () => {
    const corpo = corpoDaMeta(PARA_BSUID, TEXTO);
    assert.equal(corpo.recipient, "AO.ABC123");
    assert.equal(corpo.to, undefined, "o telefone nao vai quando ha BSUID");
  });

  it("so usa telefone na falta de BSUID", () => {
    const corpo = corpoDaMeta(PARA_TELEFONE, TEXTO);
    assert.equal(corpo.to, "999100000001");
    assert.equal(corpo.recipient, undefined);
  });

  it("os quatro tipos de corpo tem a forma da Meta", () => {
    assert.equal(corpoDaMeta(PARA_BSUID, TEXTO).type, "text");
    assert.equal(
      corpoDaMeta(PARA_BSUID, {
        tipo: "botoes",
        texto: "x",
        botoes: [{ id: "a", titulo: "A" }],
      }).type,
      "interactive",
    );
    assert.equal(
      corpoDaMeta(PARA_BSUID, {
        tipo: "lista",
        texto: "x",
        titulo: "T",
        linhas: [{ id: "a", titulo: "A" }],
      }).type,
      "interactive",
    );
    assert.equal(
      corpoDaMeta(PARA_BSUID, {
        tipo: "template",
        nome: "t",
        idioma: "pt_PT",
        parametros: [],
      }).type,
      "template",
    );
  });

  it("um template sem parametros nao leva components vazios a mais", () => {
    const corpo = corpoDaMeta(PARA_BSUID, {
      tipo: "template",
      nome: "t",
      idioma: "pt_PT",
      parametros: [],
    });
    const template = corpo.template as { components: unknown[] };
    assert.deepEqual(template.components, []);
  });

  it("o botao leva o `id`, que e o que o AGR usa", () => {
    const corpo = corpoDaMeta(PARA_BSUID, {
      tipo: "botoes",
      texto: "x",
      botoes: [{ id: "confirmar:1", titulo: "Confirmar" }],
    });
    const interactivo = corpo.interactive as {
      action: { buttons: { reply: { id: string } }[] };
    };
    assert.equal(interactivo.action.buttons[0]?.reply.id, "confirmar:1");
  });

  it("le o wamid de um 200 e devolve ok", async () => {
    const cliente = new ClienteDaGraph({
      token: "ensaio",
      base: "http://exemplo.localhost",
      buscar: async () =>
        new Response(JSON.stringify({ messages: [{ id: "wamid.ABC" }] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    });
    const resposta = await cliente.enviar("pnid", PARA_BSUID, TEXTO);
    assert.deepEqual(resposta, { ok: true, wamid: "wamid.ABC" });
  });

  it("**um 200 sem wamid nao e um envio**", async () => {
    // Sem o identificador nao ha como casar os `statuses` que vem depois, e
    // tratar isto como exito deixava uma linha em `sent` que nunca avanca.
    const cliente = new ClienteDaGraph({
      token: "ensaio",
      buscar: async () => new Response(JSON.stringify({ messages: [] }), { status: 200 }),
    });
    const resposta = await cliente.enviar("pnid", PARA_BSUID, TEXTO);
    assert.equal(resposta.ok, false);
  });

  it("le o error.code do corpo, e o estado HTTP e so informacao", async () => {
    // A armadilha que o KAM-024 documentou: nenhuma fonte da o estado HTTP do
    // 130429, e ha relato de a Cloud API devolver 400. Quem ramifique por
    // `status === 429` passa os testes e nunca repete em producao.
    for (const estado of [400, 429]) {
      const cliente = new ClienteDaGraph({
        token: "ensaio",
        buscar: async () =>
          new Response(JSON.stringify({ error: { code: 130429 } }), {
            status: estado,
            headers: { "retry-after": "3" },
          }),
      });
      const resposta = await cliente.enviar("pnid", PARA_BSUID, TEXTO);
      assert.equal(resposta.ok, false);
      if (!resposta.ok) {
        assert.equal(resposta.codigo, 130429, `estado ${estado}`);
        assert.equal(resposta.estadoHttp, estado);
        assert.equal(resposta.esperar, 3);
        assert.ok(vaiRepetir(resposta.codigo, 1), "repete pelos dois estados");
      }
    }
  });

  it("um erro sem codigo da CODIGO_SEM_CODIGO e nao rebenta", async () => {
    const cliente = new ClienteDaGraph({
      token: "ensaio",
      buscar: async () => new Response("nao e json", { status: 500 }),
    });
    const resposta = await cliente.enviar("pnid", PARA_BSUID, TEXTO);
    assert.equal(resposta.ok, false);
    assert.equal(resposta.ok === false ? resposta.codigo : 0, CODIGO_SEM_CODIGO);
  });

  it("uma falha de rede nao propaga a excepcao — e ela leva a URL", async () => {
    // A mensagem de um erro de `fetch` leva a URL, e a URL leva o
    // `phone_number_id`. Quem registra e o adapter, com o que pode registar.
    const cliente = new ClienteDaGraph({
      token: "ensaio",
      buscar: async () => {
        throw new Error("ECONNREFUSED http://graph.facebook.com/v23.0/pnid-secreto/messages");
      },
    });
    const resposta = await cliente.enviar("pnid-secreto", PARA_BSUID, TEXTO);
    assert.equal(resposta.ok, false);
    assert.equal(resposta.ok === false ? resposta.estadoHttp : -1, 0);
  });

  it("a versao da Graph e proposta e vai na URL", async () => {
    let pedida = "";
    const cliente = new ClienteDaGraph({
      token: "ensaio",
      base: "http://exemplo.localhost",
      buscar: async (url) => {
        pedida = String(url);
        return new Response(JSON.stringify({ messages: [{ id: "wamid.X" }] }), { status: 200 });
      },
    });
    await cliente.enviar("pnid-1", PARA_BSUID, TEXTO);
    assert.equal(pedida, `http://exemplo.localhost/${VERSAO_DA_GRAPH}/pnid-1/messages`);
    // Marcada como proposta no modulo: nenhum documento do repositorio a fixa.
    assert.match(VERSAO_DA_GRAPH, /^v\d+\.\d+$/);
  });

  it("o token vai no cabecalho e nao no corpo", async () => {
    let cabecalhos: Record<string, string> = {};
    const cliente = new ClienteDaGraph({
      // O valor e curto e obvio de proposito. A primeira versao tinha aqui
      // vinte caracteres com entropia suficiente para nao serem uma palavra, e
      // o `scan_secrets` recusou o commit — com razao, porque essa e a forma de
      // um segredo embutido num nome que **significa** segredo. E depois
      // recusou outra vez, porque eu tinha **citado o valor antigo neste
      // comentario**: um segredo citado fica na historia igual, e por isso nao
      // esta aqui.
      //
      // A alternativa era declarar o ficheiro em `ci/secrets-allow.yaml`, e por
      // uma constante de teste baixar a entropia e proporcionado. Mesma decisao
      // que o `VERIFICACAO` do `services/gwy/tests/webhook.test.ts` (KAM-013).
      // Nao alargar de volta.
      token: "ensaio",
      buscar: async (_url, opcoes) => {
        cabecalhos = (opcoes?.headers ?? {}) as Record<string, string>;
        return new Response(JSON.stringify({ messages: [{ id: "wamid.X" }] }), { status: 200 });
      },
    });
    await cliente.enviar("pnid", PARA_BSUID, TEXTO);
    assert.equal(cabecalhos.authorization, "Bearer ensaio");
  });
});
