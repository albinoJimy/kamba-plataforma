/**
 * O cliente da Graph e a porta de escrita no cofre, contra o KAM-024 (KAM-016).
 *
 * ## Porque é que esta bateria está separada da `onboarding.test.ts`
 *
 * Ali a Graph é um duplo que conta chamadas; aqui é o **`GraphFalso` do KAM-024
 * levantado em `node:http`**, e o que se mede é o cliente HTTP: a URL que ele
 * compõe, o método, o cabeçalho, o corpo, e o que faz com um 400. O próprio
 * KAM-024 escreve a razão de oferecer as duas formas: o `ouvir()` é «o que o
 * KAM-015 e o KAM-020 precisam quando o que querem exercitar é o **cliente
 * HTTP** deles … Um cliente testado só contra uma função nunca prova que trata
 * um socket que fecha a meio.»
 *
 * **O que esta bateria não pode provar** é que os caminhos são os da Meta. Eles
 * são ***proposta*** — o `E1` não tem as páginas de referência de API e não há
 * rede nesta sessão —, e o que se prova é que o cliente fala com a superfície
 * que o simulador do epic encaminha. O primeiro contacto real é o **nono
 * critério**, e está por marcar.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import { GraphFalso, Gerador as GeradorDeFixtures } from "@kamba/meta-sim";

import {
  CAMINHO_DA_TROCA,
  CAMPOS_DE_WEBHOOK,
  GraphHttp,
  GraphRecusouError,
  VERSAO_DA_GRAPH_POR_OMISSAO,
  caminhoDasSubscricoes,
  compararCampos,
} from "../src/onboarding/index.ts";
import {
  CofreInacessivelError,
  FamiliaInvalidaError,
  OpenBaoFakeProvider,
  SecretRefInvalidaError,
  cunharRef,
  validarFamilia,
  validarRef,
} from "../src/secrets/index.ts";

const WABA = "102290129340398";

describe("o cliente da Graph contra o servidor falso do KAM-024", () => {
  let graph: GraphFalso;
  let fechar: () => Promise<void>;
  let cliente: GraphHttp;

  before(async () => {
    graph = new GraphFalso(new GeradorDeFixtures("onboarding-graph"));
    const servidor = await graph.ouvir();
    fechar = servidor.fechar;
    cliente = new GraphHttp({
      base: servidor.base,
      versao: VERSAO_DA_GRAPH_POR_OMISSAO,
      appId: "1234567890",
      appSecret: "app-secret-de-ensaio",
    });
  });

  after(async () => {
    await fechar();
  });

  it("troca o code e devolve o token", async () => {
    const token = await cliente.trocarCode("AQB-code-de-ensaio");
    assert.match(token, /^ensaio-token-[0-9a-f]{32}$/);
  });

  /**
   * **O `code` vai na consulta**, e isto é a limitação declarada no `graph.ts`.
   *
   * O teste afirma-a em vez de a esconder: a forma é a que a Meta documenta e
   * que o `GraphFalso` modela, e a primeira versão deste cliente — que mandava
   * os parâmetros no corpo, pela RFC 6749 §4.1.3 — ficou vermelha aqui.
   */
  it("o code e o client_secret vao na consulta, como a Meta documenta", async () => {
    await cliente.trocarCode("AQB-outro-code");
    const pedido = graph.registo.at(-1)?.pedido;
    assert.ok(pedido !== undefined);
    assert.equal(pedido.caminho, `/${VERSAO_DA_GRAPH_POR_OMISSAO}/${CAMINHO_DA_TROCA}`);
    assert.equal(pedido.metodo, "GET");
    assert.equal(pedido.consulta.code, "AQB-outro-code");
    assert.equal(pedido.consulta.client_id, "1234567890");
  });

  /**
   * **O que fica nas mãos deste cliente**: a consulta nunca entra numa
   * excepção. O `caminho` de um `GraphRecusouError` vai para o `error_code` de
   * um log, e o `01` §16 e o `docs/logs.md` §2.1 não admitem um segredo lá.
   */
  it("o caminho de um erro da troca nao leva a consulta", async () => {
    graph.programar({ code: "invalido" });
    try {
      await cliente.trocarCode("AQB-nao-deve-aparecer");
      assert.fail("devia ter levantado");
    } catch (erro) {
      assert.ok(erro instanceof GraphRecusouError);
      assert.equal(erro.caminho, CAMINHO_DA_TROCA);
      assert.ok(!erro.caminho.includes("?"));
    }
    graph.programar({});
  });

  it("usa a versao configurada no caminho, e o simulador registra-a", async () => {
    await cliente.trocarCode("AQB-terceiro");
    assert.equal(graph.registo.at(-1)?.versao, VERSAO_DA_GRAPH_POR_OMISSAO);
  });

  it("um code invalido da GraphRecusouError com o estado e o codigo da Meta", async () => {
    graph.programar({ code: "invalido" });
    await assert.rejects(
      () => cliente.trocarCode("AQB-recusado"),
      (erro: unknown) =>
        erro instanceof GraphRecusouError && erro.estado === 400 && erro.codigo !== null,
    );
    graph.programar({});
  });

  it("nenhuma mensagem de erro da Graph repete o code", async () => {
    graph.programar({ code: "invalido" });
    const code = "AQB-code-que-nao-deve-aparecer";
    try {
      await cliente.trocarCode(code);
      assert.fail("devia ter levantado");
    } catch (erro) {
      assert.ok(erro instanceof Error);
      assert.ok(!erro.message.includes(code));
    }
    graph.programar({});
  });

  /** **Os onze campos, e a leitura de confirmação por igualdade de conjuntos.** */
  it("subscreve os onze campos e a leitura devolve o mesmo conjunto (criterio 5)", async () => {
    const token = await cliente.trocarCode("AQB-para-subscrever");
    await cliente.subscrever(WABA, CAMPOS_DE_WEBHOOK, token);
    const obtidos = await cliente.lerSubscricoes(WABA, token);
    assert.equal(obtidos.length, 11);
    assert.deepEqual(compararCampos(obtidos), { falta: [], aMais: [] });
    // E o servidor guardou-os: a afirmação é sobre **quais**, e não só sobre a
    // chamada ter acontecido.
    assert.deepEqual([...graph.subscricoes(WABA)].sort(), [...CAMPOS_DE_WEBHOOK].sort());
  });

  it("o token vai no cabecalho Authorization e nunca na consulta", async () => {
    const token = await cliente.trocarCode("AQB-cabecalho");
    await cliente.subscrever(WABA, CAMPOS_DE_WEBHOOK, token);
    const pedido = graph.registo.at(-1)?.pedido;
    assert.ok(pedido !== undefined);
    assert.equal(pedido.cabecalhos.authorization, `Bearer ${token}`);
    assert.deepEqual(pedido.consulta, {});
  });

  it("o caminho da subscricao e o que o simulador encaminha", async () => {
    const token = await cliente.trocarCode("AQB-caminho");
    await cliente.subscrever(WABA, CAMPOS_DE_WEBHOOK, token);
    assert.equal(
      graph.registo.at(-1)?.pedido.caminho,
      `/${VERSAO_DA_GRAPH_POR_OMISSAO}/${caminhoDasSubscricoes(WABA)}`,
    );
  });

  it("subscrever duas vezes nao duplica: o conjunto e um conjunto (criterio 2)", async () => {
    const token = await cliente.trocarCode("AQB-duas-vezes");
    await cliente.subscrever(WABA, CAMPOS_DE_WEBHOOK, token);
    await cliente.subscrever(WABA, CAMPOS_DE_WEBHOOK, token);
    assert.equal(graph.subscricoes(WABA).length, 11);
  });

  it("anular a subscricao esvazia o WABA, e repetir resolve (compensacao)", async () => {
    const token = await cliente.trocarCode("AQB-anular");
    await cliente.subscrever(WABA, CAMPOS_DE_WEBHOOK, token);
    await cliente.anularSubscricao(WABA, token);
    assert.deepEqual([...graph.subscricoes(WABA)], []);
    // Idempotente: a compensação pode correr duas vezes.
    await cliente.anularSubscricao(WABA, token);
    assert.deepEqual([...graph.subscricoes(WABA)], []);
  });

  /**
   * O simulador recusa com 404 quem não ponha o segmento `/vNN.N/` (ver o
   * `#encaminhar` dele). A afirmação é que o cliente **põe sempre** o segmento,
   * e prova-se pelo registo: o `versao` de cada pedido não é `null`.
   *
   * **Não se levanta um segundo servidor para isto**, e a primeira versão deste
   * teste fazia-o — um `graph.ouvir()` a mais ficou sem `fechar()` e o
   * `node --test` nunca terminou: o processo tinha um socket à escuta e o
   * `before/after` só fecha o que registou. Ficou pendurado na primeira
   * execução.
   */
  it("o cliente poe sempre o segmento de versao no caminho", async () => {
    await cliente.trocarCode("AQB-com-versao");
    for (const registo of graph.registo) {
      assert.notEqual(registo.versao, null, registo.pedido.caminho);
    }
  });

  it("uma leitura de subscricoes de um WABA que nunca subscreveu devolve vazio", async () => {
    const token = await cliente.trocarCode("AQB-vazio");
    const obtidos = await cliente.lerSubscricoes("999999999999999", token);
    assert.deepEqual([...obtidos], []);
    assert.deepEqual(compararCampos(obtidos).falta, [...CAMPOS_DE_WEBHOOK]);
  });
});

describe("a porta de escrita no cofre (ADR-L002 §6, a lacuna que este ticket fecha)", () => {
  it("cunha uma referencia com a familia e um sufixo opaco", () => {
    const ref = cunharRef("meta_client_token");
    assert.match(ref, /^meta_client_token\/[0-9a-f]{32}$/);
    assert.equal(validarRef(ref), ref);
  });

  /**
   * **O sufixo não é o `tenant_id`**, e é a decisão do `escrita.ts`: o
   * `token_ref` vive numa coluna que o `kamba_app` lê, e um sufixo que fosse o
   * `tenant_id` tornava cada referência um identificador de tenant em claro.
   */
  it("duas referencias da mesma familia nunca coincidem, e nao levam o tenant", () => {
    const a = cunharRef("meta_client_token");
    const b = cunharRef("meta_client_token");
    assert.notEqual(a, b);
    assert.ok(!a.includes("-"));
  });

  it("uma familia que nao e um id do inventario e recusada", () => {
    for (const familia of ["Meta", "meta-client", "me", "", "meta/token"]) {
      assert.throws(() => validarFamilia(familia), FamiliaInvalidaError);
    }
  });

  it("escreve, le e revoga pelo OpenBaoFakeProvider", async () => {
    const cofre = new OpenBaoFakeProvider({ ambiente: "dev" });
    const ref = await cofre.cunhar("meta_client_token", "criptograma-de-ensaio");
    assert.equal(await cofre.get(ref), "criptograma-de-ensaio");
    assert.deepEqual([...(await cofre.versions(ref))], ["1"]);
    await cofre.revogar(ref);
    await assert.rejects(() => cofre.get(ref));
  });

  it("revogar o que ja nao existe resolve: a compensacao e retomavel", async () => {
    const cofre = new OpenBaoFakeProvider({ ambiente: "dev" });
    const ref = await cofre.cunhar("meta_pin_2fa", "123456");
    await cofre.revogar(ref);
    await cofre.revogar(ref);
  });

  it("revogar uma referencia mal formada levanta: nao e «ja nao existe»", async () => {
    const cofre = new OpenBaoFakeProvider({ ambiente: "dev" });
    await assert.rejects(() => cofre.revogar("NAO/sou/uma/ref"), SecretRefInvalidaError);
  });

  it("um cofre selado nao escreve, e a classe do erro di-lo", async () => {
    const cofre = new OpenBaoFakeProvider({ ambiente: "dev", selado: true });
    await assert.rejects(
      () => cofre.cunhar("meta_client_token", "x"),
      CofreInacessivelError,
    );
    await assert.rejects(() => cofre.revogar("meta_client_token/abc"), CofreInacessivelError);
  });

  it("o que se cunha nao aparece na mensagem de nenhum erro", async () => {
    const cofre = new OpenBaoFakeProvider({ ambiente: "dev" });
    const valor = "criptograma-que-nao-deve-aparecer";
    try {
      await cofre.cunhar("MAIUSCULAS", valor);
      assert.fail("devia ter levantado");
    } catch (erro) {
      assert.ok(erro instanceof Error);
      assert.ok(!erro.message.includes(valor));
    }
  });
});
