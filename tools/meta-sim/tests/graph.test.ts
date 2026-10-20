/**
 * O servidor Graph falso: os oito cenários do critério 5 (KAM-024).
 *
 * Metade dos testes corre contra `responder()`, que é puro, e metade contra um
 * `node:http` a sério levantado por `ouvir()`. As duas metades medem coisas
 * diferentes e são as duas necessárias: o roteamento e os cenários provam-se
 * sem socket, mas «o KAM-015 pode apontar o seu cliente HTTP a isto» só se
 * prova com um `fetch` por cima de TCP.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CODIGOS_CONFIRMADOS } from "../src/codigos.ts";
import { CAMINHO_DA_MIDIA, CENARIOS_DE_ENVIO, GraphFalso, type Plano } from "../src/graph.ts";
import { CAMPOS } from "../src/campos.ts";
import { Gerador } from "../src/semente.ts";

const VERSAO = "v23.0";
const NUMERO = "123456789012345";
const WABA = "101234567890123";

function servidor(plano: Plano = {}): GraphFalso {
  return new GraphFalso(new Gerador("graph-do-kam-024"), plano);
}

function enviar(g: GraphFalso, corpo: Record<string, unknown> = { to: "999123456789" }) {
  return g.responder({
    metodo: "POST",
    caminho: `/${VERSAO}/${NUMERO}/messages`,
    consulta: {},
    corpo,
    cabecalhos: { authorization: "Bearer ensaio" },
  });
}

function erroDe(resposta: { corpo: Record<string, unknown> | Uint8Array }): Record<string, unknown> {
  assert.ok(!(resposta.corpo instanceof Uint8Array));
  const erro = resposta.corpo.error;
  assert.ok(typeof erro === "object" && erro !== null);
  return erro as Record<string, unknown>;
}

describe("envio (cenarios 200, 130429 N vezes, 131049, 5xx)", () => {
  it("por omissao responde 200 com um wamid", () => {
    const resposta = enviar(servidor());
    assert.equal(resposta.estado, 200);
    assert.ok(!(resposta.corpo instanceof Uint8Array));
    const mensagens = resposta.corpo.messages as { id: string }[];
    assert.match(mensagens[0]?.id ?? "", /^wamid\./);
  });

  it("130429 tres vezes e depois 200 — a letra do criterio 1 do KAM-015", () => {
    const g = servidor({ envio: { cenario: "debito_excedido", vezes: 3 } });
    const estados: number[] = [];
    for (let i = 0; i < 5; i += 1) estados.push(enviar(g).estado);
    assert.deepEqual(estados, [429, 429, 429, 200, 200]);
    assert.equal(g.envios, 5);
  });

  it("o 130429 leva o codigo CONFIRMADO e um Retry-After", () => {
    const resposta = enviar(servidor({ envio: { cenario: "debito_excedido" } }));
    assert.equal(erroDe(resposta).code, CODIGOS_CONFIRMADOS.debitoExcedido);
    assert.equal(resposta.cabecalhos?.["retry-after"], "1");
  });

  it("131049 responde 400 com o codigo do limite por utilizador", () => {
    const resposta = enviar(servidor({ envio: { cenario: "limite_por_utilizador" } }));
    assert.equal(resposta.estado, 400);
    assert.equal(erroDe(resposta).code, CODIGOS_CONFIRMADOS.limitePorUtilizador);
  });

  it("os dois 5xx distinguem-se: 500 e 503", () => {
    assert.equal(enviar(servidor({ envio: { cenario: "erro_servidor" } })).estado, 500);
    assert.equal(enviar(servidor({ envio: { cenario: "indisponivel" } })).estado, 503);
  });

  it("sem vezes, o cenario e permanente — o caso «Meta em baixo»", () => {
    const g = servidor({ envio: { cenario: "indisponivel" } });
    for (let i = 0; i < 4; i += 1) assert.equal(enviar(g).estado, 503);
  });

  it("reiniciarContagens volta a dar o cenario do inicio", () => {
    const g = servidor({ envio: { cenario: "debito_excedido", vezes: 1 } });
    assert.equal(enviar(g).estado, 429);
    assert.equal(enviar(g).estado, 200);
    g.reiniciarContagens();
    assert.equal(enviar(g).estado, 429);
  });

  it("programar() volta a contagem a zero — o vezes conta desde o cenario", () => {
    // **Achado da revisao adversarial.** O `vezes` contava envios desde sempre,
    // e por isso um envio de aquecimento antes de programar o cenario tirava uma
    // falha: `{ debito_excedido, vezes: 3 }` dava `429, 429, 200` em vez de
    // `429, 429, 429, 200`. O teste do backoff do KAM-015 passava a afirmar
    // duas tentativas em vez de tres e ficava verde a medir outra coisa.
    const g = servidor();
    assert.equal(enviar(g).estado, 200, "o envio de aquecimento");
    g.programar({ envio: { cenario: "debito_excedido", vezes: 3 } });
    const estados: number[] = [];
    for (let i = 0; i < 4; i += 1) estados.push(enviar(g).estado);
    assert.deepEqual(estados, [429, 429, 429, 200]);
  });

  it("programar() nao apaga o registo nem as subscricoes", () => {
    // O cenario reinicia-se; a historia do servidor nao. Sao coisas diferentes,
    // e quem le o registo depois de programar quer o registo todo.
    const g = servidor();
    enviar(g);
    const antes = g.registo.length;
    g.programar({ envio: { cenario: "indisponivel" } });
    assert.equal(g.registo.length, antes);
    assert.equal(g.envios, 0, "a contagem do cenario e que volta a zero");
  });

  it("o estado HTTP do 130429 e parametro, porque e NAO VERIFICADO", () => {
    // Nenhuma fonte deste repositorio da o estado HTTP do 130429 — o `01` §16 e
    // o `E1` §5 dao o codigo e mais nada —, e ha relato de a Cloud API devolver
    // 400 com o codigo no corpo. A diferenca nao e academica: um cliente que
    // ramifique por `status === 429` passa os testes e **nunca repete em
    // producao**. A regra para o KAM-015 e ramificar pelo `error.code`, e este
    // parametro existe para que o teste dele possa provar que o faz.
    const comum = servidor({ envio: { cenario: "debito_excedido" } });
    const resposta = enviar(comum);
    assert.equal(resposta.estado, 429, "a omissao");
    assert.equal(erroDe(resposta).code, CODIGOS_CONFIRMADOS.debitoExcedido);

    const outro = servidor({ envio: { cenario: "debito_excedido", estadoHttp: 400 } });
    const quatrocentos = enviar(outro);
    assert.equal(quatrocentos.estado, 400);
    // **O codigo e o mesmo nos dois.** E por isso que ramificar pelo codigo
    // funciona nas duas hipoteses e ramificar pelo estado HTTP so numa.
    assert.equal(erroDe(quatrocentos).code, CODIGOS_CONFIRMADOS.debitoExcedido);
  });

  it("os cinco cenarios estao nomeados", () => {
    assert.equal(CENARIOS_DE_ENVIO.length, 5);
  });

  it("o registo guarda o que foi enviado, para o KAM-015 o afirmar", () => {
    const g = servidor();
    enviar(g, { to: "999100000001", type: "text", text: { body: "ola" } });
    const ultimo = g.registo[g.registo.length - 1];
    assert.equal(ultimo?.versao, VERSAO);
    assert.equal(ultimo?.pedido.corpo?.to, "999100000001");
  });
});

describe("templates", () => {
  it("a submissao devolve id, status e categoria", () => {
    const g = servidor();
    const resposta = g.responder({
      metodo: "POST",
      caminho: `/${VERSAO}/${WABA}/message_templates`,
      consulta: {},
      corpo: { name: "confirmacao_de_pedido", category: "UTILITY" },
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 200);
    assert.ok(!(resposta.corpo instanceof Uint8Array));
    assert.equal(resposta.corpo.status, "PENDING");
    assert.equal(resposta.corpo.category, "UTILITY");
    assert.equal(resposta.corpo.waba_id, WABA);
  });

  it("o plano manda no estado e na categoria devolvidos", () => {
    const g = servidor({ template: { estado: "REJECTED", categoria: "MARKETING" } });
    const resposta = g.responder({
      metodo: "POST",
      caminho: `/${VERSAO}/${WABA}/message_templates`,
      consulta: {},
      corpo: { name: "promo", category: "UTILITY" },
      cabecalhos: {},
    });
    assert.ok(!(resposta.corpo instanceof Uint8Array));
    assert.equal(resposta.corpo.status, "REJECTED");
    // A recategorização é o caso do critério 9 do KAM-015: o template pedido
    // como `UTILITY` volta como `MARKETING`.
    assert.equal(resposta.corpo.category, "MARKETING");
  });

  it("o GET lista o que foi submetido", () => {
    const g = servidor();
    g.responder({
      metodo: "POST",
      caminho: `/${VERSAO}/${WABA}/message_templates`,
      consulta: {},
      corpo: { name: "um" },
      cabecalhos: {},
    });
    const lista = g.responder({
      metodo: "GET",
      caminho: `/${VERSAO}/${WABA}/message_templates`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.ok(!(lista.corpo instanceof Uint8Array));
    assert.equal((lista.corpo.data as unknown[]).length, 1);
  });
});

describe("troca de code (KAM-016)", () => {
  it("com code devolve um token que se ve ser de ensaio", () => {
    const resposta = servidor().responder({
      metodo: "GET",
      caminho: `/${VERSAO}/oauth/access_token`,
      consulta: { code: "AQB-codigo" },
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 200);
    assert.ok(!(resposta.corpo instanceof Uint8Array));
    // O prefixo `ensaio-` é o que permite ao scan de segredos do KAM-002
    // separar este de um token real sem heurística.
    assert.match(resposta.corpo.access_token as string, /^ensaio-token-/);
  });

  it("sem code responde 400", () => {
    const resposta = servidor().responder({
      metodo: "GET",
      caminho: `/${VERSAO}/oauth/access_token`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 400);
  });

  it("o plano pode fazer a troca falhar", () => {
    const resposta = servidor({ code: "invalido" }).responder({
      metodo: "GET",
      caminho: `/${VERSAO}/oauth/access_token`,
      consulta: { code: "AQB-codigo" },
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 400);
  });
});

describe("subscricoes (KAM-016)", () => {
  function subscrever(g: GraphFalso, campos: string) {
    return g.responder({
      metodo: "POST",
      caminho: `/${VERSAO}/${WABA}/subscribed_apps`,
      consulta: {},
      corpo: { subscribed_fields: campos },
      cabecalhos: {},
    });
  }

  it("guarda os campos subscritos, e nao so que a chamada aconteceu", () => {
    const g = servidor();
    assert.equal(subscrever(g, CAMPOS.join(",")).estado, 200);
    // É isto que o KAM-016 vai afirmar: os **onze**, por nome.
    assert.deepEqual([...g.subscricoes(WABA)].sort(), [...CAMPOS].sort());
  });

  it("o GET devolve o que foi guardado", () => {
    const g = servidor();
    subscrever(g, "messages,history");
    const lista = g.responder({
      metodo: "GET",
      caminho: `/${VERSAO}/${WABA}/subscribed_apps`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.ok(!(lista.corpo instanceof Uint8Array));
    const dados = lista.corpo.data as { subscribed_fields: string[] }[];
    assert.deepEqual(dados[0]?.subscribed_fields.sort(), ["history", "messages"]);
  });

  it("o DELETE apaga a subscricao", () => {
    const g = servidor();
    subscrever(g, "messages");
    g.responder({
      metodo: "DELETE",
      caminho: `/${VERSAO}/${WABA}/subscribed_apps`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.deepEqual(g.subscricoes(WABA), []);
  });

  it("subscrever duas vezes nao duplica", () => {
    const g = servidor();
    subscrever(g, "messages");
    subscrever(g, "messages,history");
    assert.equal(g.subscricoes(WABA).length, 2);
  });
});

describe("midia (KAM-020)", () => {
  const BYTES = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]);

  it("a metainformacao traz a URL, o tamanho e o mime", () => {
    const g = servidor();
    const id = g.oferecerMidia(BYTES, "image/jpeg");
    const resposta = g.responder({
      metodo: "GET",
      caminho: `/${VERSAO}/${id}`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 200);
    assert.ok(!(resposta.corpo instanceof Uint8Array));
    assert.equal(resposta.corpo.file_size, BYTES.byteLength);
    assert.equal(resposta.corpo.mime_type, "image/jpeg");
    assert.ok((resposta.corpo.url as string).includes(CAMINHO_DA_MIDIA));
  });

  it("a descarga devolve os bytes", () => {
    const g = servidor();
    const id = g.oferecerMidia(BYTES, "image/jpeg");
    const resposta = g.responder({
      metodo: "GET",
      caminho: `${CAMINHO_DA_MIDIA}/${id}`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 200);
    assert.ok(resposta.corpo instanceof Uint8Array);
    assert.ok(Buffer.from(resposta.corpo).equals(Buffer.from(BYTES)));
  });

  it("uma URL expirada da 404 na descarga e 200 na metainformacao", () => {
    // É o caso real: a URL da Meta expira. Um cliente que guarde a URL em vez
    // de a pedir outra vez falha exactamente aqui, e esta *fixture* é a que o
    // apanha.
    const g = servidor({ midia: { expirada: true } });
    const id = g.oferecerMidia(BYTES, "image/jpeg");
    assert.equal(
      g.responder({ metodo: "GET", caminho: `/${VERSAO}/${id}`, consulta: {}, corpo: null, cabecalhos: {} }).estado,
      200,
    );
    assert.equal(
      g.responder({ metodo: "GET", caminho: `${CAMINHO_DA_MIDIA}/${id}`, consulta: {}, corpo: null, cabecalhos: {} }).estado,
      404,
    );
  });

  it("uma midia que nao existe da 404", () => {
    const resposta = servidor().responder({
      metodo: "GET",
      caminho: `/${VERSAO}/000000000000000000000000`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 404);
  });
});

describe("roteamento", () => {
  it("um caminho sem versao da 404 e di-lo", () => {
    const resposta = servidor().responder({
      metodo: "POST",
      caminho: "/messages",
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 404);
    assert.match(erroDe(resposta).message as string, /sem segmento de versao/);
  });

  it("aceita qualquer versao e registra a que o cliente usou", () => {
    // O repositório não fixa versão da Graph API, e o servidor não inventa uma.
    const g = servidor();
    for (const versao of ["v21.0", "v23.0", "v99.9"]) {
      g.responder({
        metodo: "POST",
        caminho: `/${versao}/${NUMERO}/messages`,
        consulta: {},
        corpo: { to: "999100000001" },
        cabecalhos: {},
      });
    }
    assert.deepEqual(
      g.registo.map((r) => r.versao),
      ["v21.0", "v23.0", "v99.9"],
    );
  });

  it("uma rota nao simulada da 404 e diz qual", () => {
    const resposta = servidor().responder({
      metodo: "POST",
      caminho: `/${VERSAO}/${WABA}/nao_existe`,
      consulta: {},
      corpo: null,
      cabecalhos: {},
    });
    assert.equal(resposta.estado, 404);
    assert.match(erroDe(resposta).message as string, /rota nao simulada/);
  });
});

describe("por cima de TCP, como o KAM-015 o vai usar", () => {
  it("um fetch a um servidor a escuta devolve o 200 e o 429", async () => {
    const g = servidor({ envio: { cenario: "debito_excedido", vezes: 1 } });
    const { base, fechar, porta } = await g.ouvir();
    try {
      assert.ok(porta > 0, "o SO escolheu uma porta");
      const primeira = await fetch(`${base}/${VERSAO}/${NUMERO}/messages`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ to: "999100000001" }),
      });
      assert.equal(primeira.status, 429);
      assert.equal(primeira.headers.get("retry-after"), "1");

      const segunda = await fetch(`${base}/${VERSAO}/${NUMERO}/messages`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ to: "999100000001" }),
      });
      assert.equal(segunda.status, 200);
      const dados = (await segunda.json()) as { messages: { id: string }[] };
      assert.match(dados.messages[0]?.id ?? "", /^wamid\./);
    } finally {
      await fechar();
    }
  });

  it("a descarga de midia por TCP devolve os bytes e o content-type", async () => {
    const g = servidor();
    const { base, fechar } = await g.ouvir();
    try {
      const id = g.oferecerMidia(new Uint8Array([1, 2, 3, 4]), "audio/ogg");
      const meta = await fetch(`${base}/${VERSAO}/${id}`);
      const dados = (await meta.json()) as { url: string };
      // A URL que o servidor devolve aponta para **ele**, e por isso o cliente
      // pode seguir o fluxo inteiro sem saber onde está.
      const descarga = await fetch(dados.url);
      assert.equal(descarga.status, 200);
      assert.equal(descarga.headers.get("content-type"), "audio/ogg");
      const bytes = new Uint8Array(await descarga.arrayBuffer());
      assert.deepEqual([...bytes], [1, 2, 3, 4]);
    } finally {
      await fechar();
    }
  });
});
