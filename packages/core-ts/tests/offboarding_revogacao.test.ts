/**
 * Os adaptadores da revogação do off-boarding (KAM-233, critério 2): a chave
 * do LiteLLM e a conta do Chatwoot, cada um contra um duplo que lê o **texto**
 * do pedido — o método, o caminho, o cabeçalho e o corpo.
 *
 * Os desfechos que os duplos dão são os **medidos** nas imagens fixadas
 * (`docs/evidencia/KAM-233.md` §3 e §5): um duplo prova que o nosso código
 * chama o que pretendíamos, e a evidência é que diz que o terceiro o aceita.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ArquivoDoChatwoot,
  ESTADO_DA_CONTA_ARQUIVADA,
  Handoff,
  ProvedorIndisponivelError,
  RespostaInesperadaError,
  SemPrivilegioError,
  arquivarContaDoTenant,
  type ArquivoDoProvedor,
} from "../src/hnd/index.ts";
import { SQL_CONTA } from "../src/hnd/consultas.ts";
import { ChaveDoLlmPeloProxy, LiteLlmRecusouError, aliasDaChaveDoTenant } from "../src/offboarding/litellm.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
// Valores distinguíveis e sem forma de chave (o `scan_secrets` recusa os que a têm).
const MESTRA = "mestra-de-ensaio";
const PLATAFORMA = "aaaa-plataforma";

interface Pedido {
  readonly url: string;
  readonly metodo: string;
  readonly cabecalhos: Record<string, string>;
  readonly corpo: Record<string, unknown>;
}

function buscarFalso(pedidos: Pedido[], responder: (p: Pedido) => { estado: number; corpo: unknown }): typeof fetch {
  return (async (url: string, opcoes: RequestInit) => {
    const pedido: Pedido = {
      url,
      metodo: String(opcoes.method),
      cabecalhos: opcoes.headers as Record<string, string>,
      corpo: (opcoes.body === undefined ? {} : JSON.parse(String(opcoes.body))) as Record<string, unknown>,
    };
    pedidos.push(pedido);
    const r = responder(pedido);
    const texto = typeof r.corpo === "string" ? r.corpo : JSON.stringify(r.corpo);
    return {
      ok: r.estado >= 200 && r.estado < 300,
      status: r.estado,
      text: async () => texto,
      json: async () => JSON.parse(texto) as unknown,
    } as Response;
  }) as unknown as typeof fetch;
}

/**
 * O proxy medido: apaga o que lhe pedem e devolve-o no `deleted_keys`; o que não
 * tem dá 404. O `/key/list` devolve o que sobra, com a forma medida (`keys` e
 * `total_count`), e cada chave com o mesmo valor no `token` e no `key_alias`.
 */
function proxyMedido(chaves: Set<string>, porPagina = 500) {
  return (p: Pedido) => {
    if (p.metodo === "GET") {
      const url = new URL(p.url);
      assert.equal(url.pathname, "/key/list");
      assert.equal(url.searchParams.get("return_full_object"), "true");
      const pagina = Number(url.searchParams.get("page"));
      const todas = [...chaves].map((k) => ({ token: k, key_alias: k }));
      const keys = todas.slice((pagina - 1) * porPagina, pagina * porPagina);
      return { estado: 200, corpo: { keys, total_count: todas.length, current_page: pagina } };
    }
    const pedidas = [...((p.corpo.keys ?? p.corpo.key_aliases ?? []) as string[])];
    const apagadas = pedidas.filter((k) => chaves.delete(k));
    if (apagadas.length === 0) return { estado: 404, corpo: { error: { message: "No keys found" } } };
    return { estado: 200, corpo: { deleted_keys: apagadas } };
  };
}

describe("a chave do LiteLLM (KAM-233, critério 2)", () => {
  it("o alias é o do chaves.py: tenant-<uuid>", () => {
    assert.equal(aliasDaChaveDoTenant(TENANT), `tenant-${TENANT}`);
  });

  it("revogar pelo tenant é um POST /key/delete com key_aliases e a chave mestra só no cabeçalho", async () => {
    const pedidos: Pedido[] = [];
    const chaves = new Set([aliasDaChaveDoTenant(TENANT), "tenant-outro"]);
    const llm = new ChaveDoLlmPeloProxy({ base: "http://litellm:4000/", chaveMestra: MESTRA, buscar: buscarFalso(pedidos, proxyMedido(chaves)) });

    assert.equal(await llm.revogarDoTenant(TENANT), "revogada");
    assert.equal(pedidos.length, 2, "o DELETE e a listagem que o confirma");
    assert.equal(pedidos[1]?.metodo, "GET");
    assert.equal(pedidos[1]?.cabecalhos.authorization, `Bearer ${MESTRA}`);
    assert.equal(pedidos[0]?.url, "http://litellm:4000/key/delete");
    assert.equal(pedidos[0]?.metodo, "POST");
    assert.deepEqual(pedidos[0]?.corpo, { key_aliases: [aliasDaChaveDoTenant(TENANT)] });
    assert.equal(pedidos[0]?.cabecalhos.authorization, `Bearer ${MESTRA}`);
    assert.ok(!JSON.stringify(pedidos[0]?.corpo).includes(MESTRA), "a chave mestra nao vai no corpo");
    assert.deepEqual([...chaves], ["tenant-outro"], "so a chave do tenant sai");
  });

  it("revogar pelo token da saga manda keys, e não key_aliases", async () => {
    const pedidos: Pedido[] = [];
    const llm = new ChaveDoLlmPeloProxy({ base: "http://litellm:4000", chaveMestra: MESTRA, buscar: buscarFalso(pedidos, proxyMedido(new Set(["resumo-a"]))) });
    await llm.revogar("resumo-a");
    assert.deepEqual(pedidos[0]?.corpo, { keys: ["resumo-a"] });
  });

  it("repetir é o 404 medido, e é o sucesso de uma repetição", async () => {
    const pedidos: Pedido[] = [];
    const chaves = new Set([aliasDaChaveDoTenant(TENANT)]);
    const llm = new ChaveDoLlmPeloProxy({ base: "http://litellm:4000", chaveMestra: MESTRA, buscar: buscarFalso(pedidos, proxyMedido(chaves)) });
    assert.equal(await llm.revogarDoTenant(TENANT), "revogada");
    assert.equal(await llm.revogarDoTenant(TENANT), "inexistente");
  });

  it("um 404 com a chave ainda na listagem levanta: o 404 só vale confirmado", async () => {
    const chaves = new Set([aliasDaChaveDoTenant(TENANT)]);
    const listar = proxyMedido(chaves);
    const llm = new ChaveDoLlmPeloProxy({
      base: "http://litellm:4000",
      chaveMestra: MESTRA,
      buscar: buscarFalso([], (p) => (p.metodo === "POST" ? { estado: 404, corpo: {} } : listar(p))),
    });
    await assert.rejects(llm.revogarDoTenant(TENANT), /continua no \/key\/list/);
  });

  it("um 200 com a chave ainda na listagem levanta", async () => {
    const alias = aliasDaChaveDoTenant(TENANT);
    const listar = proxyMedido(new Set([alias]));
    const llm = new ChaveDoLlmPeloProxy({
      base: "http://litellm:4000",
      chaveMestra: MESTRA,
      buscar: buscarFalso([], (p) => (p.metodo === "POST" ? { estado: 200, corpo: { deleted_keys: [alias] } } : listar(p))),
    });
    await assert.rejects(llm.revogarDoTenant(TENANT), /continua no \/key\/list/);
  });

  it("a listagem lê-se por páginas até ao total, e uma lista incompleta não confirma nada", async () => {
    const pedidos: Pedido[] = [];
    const outras = Array.from({ length: 5 }, (_, i) => `tenant-outro-${i}`);
    const alvo = aliasDaChaveDoTenant(TENANT);
    // O alvo na última página: só a leitura até ao fim o encontra.
    const listar = proxyMedido(new Set([...outras, alvo]), 2);
    const llm = new ChaveDoLlmPeloProxy({
      base: "http://litellm:4000",
      chaveMestra: MESTRA,
      buscar: buscarFalso(pedidos, (p) => (p.metodo === "POST" ? { estado: 404, corpo: {} } : listar(p))),
    });
    await assert.rejects(llm.revogarDoTenant(TENANT), /continua/);
    assert.deepEqual(
      pedidos.filter((p) => p.metodo === "GET").map((p) => new URL(p.url).searchParams.get("page")),
      ["1", "2", "3"],
    );
    const incompleta = new ChaveDoLlmPeloProxy({
      base: "http://litellm:4000",
      chaveMestra: MESTRA,
      buscar: buscarFalso([], (p) =>
        p.metodo === "POST" ? { estado: 404, corpo: {} } : { estado: 200, corpo: { keys: [], total_count: 3 } },
      ),
    });
    await assert.rejects(incompleta.revogarDoTenant(TENANT), /incompleto/);
    const semBase = new ChaveDoLlmPeloProxy({
      base: "http://litellm:4000",
      chaveMestra: MESTRA,
      buscar: buscarFalso([], (p) => (p.metodo === "POST" ? { estado: 404, corpo: {} } : { estado: 500, corpo: {} })),
    });
    await assert.rejects(semBase.revogarDoTenant(TENANT), (e: unknown) => e instanceof LiteLlmRecusouError && e.estado === 500);
  });

  it("um 200 que não nomeia a chave pedida levanta, em vez de a dar por revogada", async () => {
    const llm = new ChaveDoLlmPeloProxy({
      base: "http://litellm:4000",
      chaveMestra: MESTRA,
      buscar: buscarFalso([], () => ({ estado: 200, corpo: { deleted_keys: ["tenant-outro"] } })),
    });
    await assert.rejects(llm.revogarDoTenant(TENANT), LiteLlmRecusouError);
  });

  it("o 500 do proxy sem base sobe, e a mensagem não leva o corpo nem a chave", async () => {
    const llm = new ChaveDoLlmPeloProxy({
      base: "http://litellm:4000",
      chaveMestra: MESTRA,
      buscar: buscarFalso([], () => ({ estado: 500, corpo: { error: { message: `DB not connected ${MESTRA}` } } })),
    });
    await assert.rejects(llm.revogarDoTenant(TENANT), (erro: unknown) => {
      assert.ok(erro instanceof LiteLlmRecusouError);
      assert.equal(erro.estado, 500);
      assert.ok(!erro.message.includes(MESTRA));
      assert.ok(!erro.message.includes("DB not connected"));
      return true;
    });
  });
});

/** O Chatwoot medido: suspende a conta que existe, 404 na que não existe. */
function chatwootMedido(contas: Map<number, string>) {
  return (p: Pedido) => {
    const id = Number(p.url.split("/").pop());
    if (!contas.has(id)) return { estado: 404, corpo: { status: 404, error: "Not Found" } };
    contas.set(id, String(p.corpo.status));
    return { estado: 200, corpo: { id, name: "kamba", status: contas.get(id) } };
  };
}

describe("a conta do Chatwoot (KAM-233, critério 2)", () => {
  it("arquivar é um PATCH à conta pela Platform API com status suspended, e nada mais", async () => {
    const pedidos: Pedido[] = [];
    const contas = new Map([[7, "active"], [8, "active"]]);
    const arquivo = new ArquivoDoChatwoot({ base: "http://chatwoot:3000", tokenDaPlataforma: PLATAFORMA, buscar: buscarFalso(pedidos, chatwootMedido(contas)) });

    assert.equal(await arquivo.arquivarConta(7), "arquivada");
    assert.equal(pedidos.length, 1);
    assert.equal(pedidos[0]?.metodo, "PATCH");
    assert.equal(pedidos[0]?.url, "http://chatwoot:3000/platform/api/v1/accounts/7");
    assert.deepEqual(pedidos[0]?.corpo, { status: ESTADO_DA_CONTA_ARQUIVADA });
    assert.equal(pedidos[0]?.cabecalhos.api_access_token, PLATAFORMA);
    assert.equal(contas.get(8), "active", "a outra conta fica");
  });

  it("repetir é 200 outra vez, e uma conta que já não existe é inexistente", async () => {
    const contas = new Map([[7, "active"]]);
    const arquivo = new ArquivoDoChatwoot({ tokenDaPlataforma: PLATAFORMA, buscar: buscarFalso([], chatwootMedido(contas)) });
    assert.equal(await arquivo.arquivarConta(7), "arquivada");
    assert.equal(await arquivo.arquivarConta(7), "arquivada");
    assert.equal(await arquivo.arquivarConta(99), "inexistente");
  });

  it("um 200 com a conta ainda activa levanta", async () => {
    const arquivo = new ArquivoDoChatwoot({
      tokenDaPlataforma: PLATAFORMA,
      buscar: buscarFalso([], () => ({ estado: 200, corpo: { id: 7, status: "active" } })),
    });
    await assert.rejects(arquivo.arquivarConta(7), RespostaInesperadaError);
  });

  it("um 401 de outro PlatformApp sobe, e um 5xx é o provedor indisponível", async () => {
    const recusa = new ArquivoDoChatwoot({
      tokenDaPlataforma: PLATAFORMA,
      buscar: buscarFalso([], () => ({ estado: 401, corpo: { error: "Non permissible resource" } })),
    });
    await assert.rejects(recusa.arquivarConta(7), RespostaInesperadaError);
    const em_baixo = new ArquivoDoChatwoot({
      tokenDaPlataforma: PLATAFORMA,
      buscar: buscarFalso([], () => ({ estado: 503, corpo: "" })),
    });
    await assert.rejects(em_baixo.arquivarConta(7), ProvedorIndisponivelError);
  });
});

describe("a conta do tenant lê-se da handoff_accounts (KAM-233)", () => {
  function bdCom(linhas: Record<string, unknown>[], vistos: unknown[][]) {
    return {
      async query<T>(sql: string, valores?: readonly unknown[]): Promise<{ readonly rows: readonly T[] }> {
        assert.equal(sql, SQL_CONTA);
        vistos.push([...(valores ?? [])]);
        return { rows: linhas as unknown as T[] };
      },
    };
  }

  it("arquiva a conta da linha do tenant e do provedor", async () => {
    const vistos: unknown[][] = [];
    const pedidos: number[] = [];
    const arquivo: ArquivoDoProvedor = { arquivarConta: async (id) => (pedidos.push(id), "arquivada") };
    const r = await arquivarContaDoTenant({ bd: bdCom([{ account_id: "42" }], vistos), arquivo, tenantId: TENANT, provedor: "chatwoot" });
    assert.equal(r, "arquivada");
    assert.deepEqual(vistos, [[TENANT, "chatwoot"]]);
    assert.deepEqual(pedidos, [42]);
  });

  it("um tenant sem conta é sem_conta, e nada sai para o provedor", async () => {
    const arquivo: ArquivoDoProvedor = { arquivarConta: async () => assert.fail("nao devia chamar o provedor") };
    assert.equal(await arquivarContaDoTenant({ bd: bdCom([], []), arquivo, tenantId: TENANT, provedor: "chatwoot" }), "sem_conta");
  });

  it("a Handoff sem o arquivo levanta pelo nome, e nunca finge", async () => {
    const h = new Handoff({
      bd: bdCom([], []),
      provedor: {} as never,
      provisionador: {} as never,
      fila: {} as never,
      refDoTokenDoBot: () => "x",
      refDoTokenDoUtilizador: () => "y",
      guardarSegredo: async () => {},
      segredoDoBot: async () => "z",
      retomar: async () => ({}) as never,
    });
    await assert.rejects(h.archiveAccount(TENANT), SemPrivilegioError);
  });

  it("a Handoff com o arquivo usa a mesma função", async () => {
    const pedidos: number[] = [];
    const h = new Handoff({
      bd: bdCom([{ account_id: 5 }], []),
      provedor: {} as never,
      provisionador: {} as never,
      arquivo: { arquivarConta: async (id) => (pedidos.push(id), "arquivada") },
      fila: {} as never,
      refDoTokenDoBot: () => "x",
      refDoTokenDoUtilizador: () => "y",
      guardarSegredo: async () => {},
      segredoDoBot: async () => "z",
      retomar: async () => ({}) as never,
    });
    assert.equal(await h.archiveAccount(TENANT), "arquivada");
    assert.deepEqual(pedidos, [5]);
  });
});
