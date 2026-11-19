/**
 * As duas portas de produção da resposta do AGR (KAM-227), sem base.
 *
 * - o **cliente da Graph de cada canal**: o `token_ref` lido sob o tenant do
 *   pedido, o criptograma do cofre, a `kek_token_cliente`, e o *token* no
 *   cabeçalho de autorização — e só lá;
 * - o **destinatário**: o BSUID quando existe, o telefone dentro do prazo só sem
 *   ele, nada para um contacto apagado.
 *
 * O cofre é o `EnvSecretProvider` do Piloto (ADR-L002) sobre um ambiente de
 * ensaio, e o criptograma é o do `cifrarToken` do KAM-016: o mesmo caminho que o
 * processo percorre. O ensaio contra o PostgreSQL — a RLS, o `kamba_identity` e
 * o `lerEndpoints` reais — está em `tests_bd/resposta.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { describe, it } from "node:test";

import { ContactoApagadoError, DekDestruidaError } from "../src/identity/index.ts";
import type { EndpointsDoContacto } from "../src/identity/index.ts";
import { cifrarToken } from "../src/onboarding/cifra.ts";
import type { Corpo } from "../src/outbound/contrato.ts";
import {
  CanalSemCredencialError,
  SEM_DESTINATARIO,
  SQL_TOKEN_REF_DO_CANAL,
  clienteDaGraphPorCanal,
  destinatarioPelaIdentidade,
  escolherDestinatario,
} from "../src/resposta/index.ts";
import { EnvSecretProvider, nomeDaVariavel } from "../src/secrets/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const OUTRO = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b";
const CANAL = "5c6d7e8f-9a0b-4c1d-8e2f-3a4b5c6d7e8f";
const NUMERO = "109876543210987";
const CONTACTO = "2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901";
/** Um *token* de ensaio: não é de conta nenhuma, e não tem a forma de um da Meta. */
const ACESSO_DE_ENSAIO = "token-de-ensaio-kam227-nao-e-da-meta";
const CORPO: Corpo = { tipo: "texto", texto: "ola" };

/** Um canal no cofre: a KEK, e o criptograma do *token* sob uma referência cunhada. */
function cofreCom(tenantDoCriptograma = TENANT): { cofre: EnvSecretProvider; ref: string; env: Record<string, string> } {
  const kek = randomBytes(32).toString("base64");
  const ref = `meta_client_token/${randomBytes(16).toString("hex")}`;
  const env: Record<string, string> = {
    KAMBA_SECRET_KEK_TOKEN_CLIENTE: `t1:${kek}`,
    [nomeDaVariavel(ref)]: cifrarToken(kek, "t1", tenantDoCriptograma, ACESSO_DE_ENSAIO),
  };
  return { cofre: new EnvSecretProvider({ ambiente: "staging", env }), ref, env };
}

/**
 * A ligação do envio, que só sabe responder ao `SQL_TOKEN_REF_DO_CANAL` — e
 * **lê o predicado no texto**: sem o `id = $2` e o `phone_number_id = $3`
 * escritos, o canal de outro número casava.
 */
class LigacaoDoCanal {
  readonly instrucoes: string[] = [];
  readonly parametros: (readonly unknown[])[] = [];
  readonly #canais: { tenant: string; id: string; numero: string; ref: string }[];

  constructor(canais: { tenant: string; id: string; numero: string; ref: string }[]) {
    this.#canais = canais;
  }

  async query<T = Record<string, unknown>>(sql: string, valores: readonly unknown[] = []): Promise<{ readonly rows: readonly T[] }> {
    this.instrucoes.push(sql.trim());
    if (sql !== SQL_TOKEN_REF_DO_CANAL) return { rows: [] };
    this.parametros.push(valores);
    const [tenant, id, numero] = valores as string[];
    const porId = /\bid = \$2\b/.test(sql);
    const porNumero = /phone_number_id = \$3/.test(sql);
    const rows = this.#canais
      .filter((c) => c.tenant === tenant && (!porId || c.id === id) && (!porNumero || c.numero === numero))
      .map((c) => ({ token_ref: c.ref }));
    return { rows: rows as T[] };
  }
}

/** O `fetch` do cliente da Graph, que guarda o pedido e responde 200. */
function buscarQueGuarda() {
  const pedidos: { url: string; cabecalhos: Record<string, string>; corpo: string }[] = [];
  const buscar = (async (url: string, init: RequestInit) => {
    pedidos.push({
      url,
      cabecalhos: init.headers as Record<string, string>,
      corpo: String(init.body),
    });
    return new Response(JSON.stringify({ messages: [{ id: "wamid.ENSAIO227" }] }), { status: 200 });
  }) as unknown as typeof fetch;
  return { buscar, pedidos };
}

const PEDIDO = { tenantId: TENANT, channelId: CANAL, phoneNumberId: NUMERO };

describe("clienteDaGraphPorCanal (critério 1)", () => {
  it("lê o token_ref sob o tenant do pedido, abre o criptograma e envia com o token do canal", async () => {
    const { cofre, ref } = cofreCom();
    const { buscar, pedidos } = buscarQueGuarda();
    const ligacao = new LigacaoDoCanal([{ tenant: TENANT, id: CANAL, numero: NUMERO, ref }]);
    const cliente = await clienteDaGraphPorCanal({ cofre, buscar, base: "http://graph.ensaio" })(ligacao, PEDIDO);
    const resposta = await cliente.enviar(NUMERO, { bsuid: "AO.ENSAIOENSAIOENSAIO0227", telefone: null }, CORPO);
    assert.deepEqual(resposta, { ok: true, wamid: "wamid.ENSAIO227" });
    assert.equal(pedidos.length, 1);
    assert.equal(pedidos[0]!.cabecalhos["authorization"], `Bearer ${ACESSO_DE_ENSAIO}`);
    assert.match(pedidos[0]!.url, new RegExp(`^http://graph\\.ensaio/v[0-9.]+/${NUMERO}/messages$`));
    // O token vai no cabeçalho e em mais lado nenhum do pedido.
    assert.equal(pedidos[0]!.corpo.includes(ACESSO_DE_ENSAIO), false);
    // A leitura correu numa transacção com o tenant local, com o tenant e o canal do pedido.
    assert.deepEqual(ligacao.parametros, [[TENANT, CANAL, NUMERO]]);
    const i = ligacao.instrucoes.indexOf(SQL_TOKEN_REF_DO_CANAL.trim());
    assert.match(ligacao.instrucoes[i - 1] ?? "", /set_config\('app\.tenant_id', \$1, true\)/);
    assert.match(ligacao.instrucoes[i - 2] ?? "", /^BEGIN$/i);
    assert.match(ligacao.instrucoes[i + 1] ?? "", /^COMMIT$/i);
  });

  it("um canal que não é o do pedido não serve: sem_canal", async () => {
    const { cofre, ref } = cofreCom();
    for (const canal of [
      { tenant: OUTRO, id: CANAL, numero: NUMERO, ref },
      { tenant: TENANT, id: "0b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e", numero: NUMERO, ref },
      { tenant: TENANT, id: CANAL, numero: "109876543210000", ref },
    ]) {
      await assert.rejects(
        clienteDaGraphPorCanal({ cofre })(new LigacaoDoCanal([canal]), PEDIDO),
        (erro: unknown) => erro instanceof CanalSemCredencialError && erro.motivo === "sem_canal",
      );
    }
  });

  it("**token em falta** no cofre, ou referência sem forma: sem_segredo, e a mensagem não leva a referência", async () => {
    const { env, ref } = cofreCom();
    delete env[nomeDaVariavel(ref)];
    const cofre = new EnvSecretProvider({ ambiente: "staging", env });
    for (const r of [ref, "nao e uma referencia"]) {
      await assert.rejects(
        clienteDaGraphPorCanal({ cofre })(new LigacaoDoCanal([{ tenant: TENANT, id: CANAL, numero: NUMERO, ref: r }]), PEDIDO),
        (erro: unknown) => {
          assert.ok(erro instanceof CanalSemCredencialError);
          assert.equal(erro.motivo, "sem_segredo");
          assert.equal(erro.message.includes(r), false);
          return true;
        },
      );
    }
  });

  it("**isolamento:** o token_ref de A na linha de B não abre sob B — nao_abre, e o token não aparece", async () => {
    // A escrita que a base aceita: o `GRANT UPDATE (token_ref)` da `0001` é do `kamba_app`.
    const { cofre, ref } = cofreCom(TENANT);
    const ligacao = new LigacaoDoCanal([{ tenant: OUTRO, id: CANAL, numero: NUMERO, ref }]);
    await assert.rejects(
      clienteDaGraphPorCanal({ cofre })(ligacao, { ...PEDIDO, tenantId: OUTRO }),
      (erro: unknown) => {
        assert.ok(erro instanceof CanalSemCredencialError);
        assert.equal(erro.motivo, "nao_abre");
        assert.equal(erro.message.includes(ACESSO_DE_ENSAIO), false);
        return true;
      },
    );
  });

  it("um criptograma com outra KEK não abre: nao_abre", async () => {
    const { env, ref } = cofreCom();
    env["KAMBA_SECRET_KEK_TOKEN_CLIENTE"] = `t1:${randomBytes(32).toString("base64")}`;
    await assert.rejects(
      clienteDaGraphPorCanal({ cofre: new EnvSecretProvider({ ambiente: "staging", env }) })(
        new LigacaoDoCanal([{ tenant: TENANT, id: CANAL, numero: NUMERO, ref }]),
        PEDIDO,
      ),
      (erro: unknown) => erro instanceof CanalSemCredencialError && erro.motivo === "nao_abre",
    );
  });

  it("a KEK em falta não é do canal: sobe como erro do cofre, e não como sem_credencial", async () => {
    const { env, ref } = cofreCom();
    delete env["KAMBA_SECRET_KEK_TOKEN_CLIENTE"];
    await assert.rejects(
      clienteDaGraphPorCanal({ cofre: new EnvSecretProvider({ ambiente: "staging", env }) })(
        new LigacaoDoCanal([{ tenant: TENANT, id: CANAL, numero: NUMERO, ref }]),
        PEDIDO,
      ),
      (erro: unknown) => !(erro instanceof CanalSemCredencialError) && /kek_token_cliente/.test(String(erro)),
    );
  });
});

describe("o destinatário de produção (critério 2)", () => {
  const AGORA = new Date("2026-11-19T12:00:00Z");
  const depois = new Date("2027-11-19T12:00:00Z");
  const antes = new Date("2026-11-18T12:00:00Z");
  const endpoints = (
    bsuids: string[],
    telefones: { telefone: string; expiraAt: Date; finalidade?: "pagamento_express" | "entrega" | "contacto_pedido" }[],
  ): EndpointsDoContacto => ({
    contactId: CONTACTO,
    bsuids,
    telefones: telefones.map((t) => ({ finalidade: "contacto_pedido" as const, ...t })),
  });

  it("o BSUID quando existe, e então o telefone nem se escolhe", () => {
    assert.deepEqual(
      escolherDestinatario(endpoints(["AO.ENSAIOENSAIOENSAIO0227"], [{ telefone: "999100000227", expiraAt: depois }]), AGORA),
      { bsuid: "AO.ENSAIOENSAIOENSAIO0227", telefone: null },
    );
  });

  it("o telefone só sem BSUID, e só dentro do prazo", () => {
    assert.deepEqual(
      escolherDestinatario(
        endpoints([], [
          { telefone: "999100000001", expiraAt: antes },
          { telefone: "999100000227", expiraAt: depois },
        ]),
        AGORA,
      ),
      { bsuid: null, telefone: "999100000227" },
    );
    assert.deepEqual(escolherDestinatario(endpoints([], [{ telefone: "999100000001", expiraAt: antes }]), AGORA), SEM_DESTINATARIO);
  });

  it("um telefone guardado para outra finalidade não serve para responder", () => {
    for (const finalidade of ["pagamento_express", "entrega"] as const) {
      assert.deepEqual(
        escolherDestinatario(endpoints([], [{ telefone: "999100000227", expiraAt: depois, finalidade }]), AGORA),
        SEM_DESTINATARIO,
      );
    }
  });

  it("**sem BSUID nem telefone** não há destinatário, e o Saida recusa NO_RECIPIENT", () => {
    assert.deepEqual(escolherDestinatario(endpoints([], []), AGORA), { bsuid: null, telefone: null });
  });

  it("lê pela ligação de identidade, com o tenant e o contacto do pedido, e devolve-a limpa", async () => {
    const ligacao = { query: async () => ({ rows: [] }) };
    const lidos: unknown[] = [];
    const devolvidas: unknown[] = [];
    const destinatario = destinatarioPelaIdentidade({
      identidade: {
        lerEndpoints: async (cliente, tenantId, contactId) => {
          lidos.push(cliente, tenantId, contactId);
          return endpoints(["AO.ENSAIOENSAIOENSAIO0227"], []);
        },
      },
      tomar: async () => ligacao,
      devolver: (_l, erro) => {
        devolvidas.push(erro ?? "limpa");
      },
      agora: () => AGORA,
    });
    assert.deepEqual(await destinatario(TENANT, CONTACTO), { bsuid: "AO.ENSAIOENSAIOENSAIO0227", telefone: null });
    assert.deepEqual(lidos, [ligacao, TENANT, CONTACTO]);
    assert.deepEqual(devolvidas, ["limpa"]);
  });

  it("um contacto apagado (ou com a DEK destruída) não tem destinatário", async () => {
    for (const erro of [new ContactoApagadoError(), new DekDestruidaError()]) {
      const destinatario = destinatarioPelaIdentidade({
        identidade: {
          lerEndpoints: async () => {
            throw erro;
          },
        },
        tomar: async () => ({ query: async () => ({ rows: [] }) }),
        devolver: () => {},
      });
      assert.deepEqual(await destinatario(TENANT, CONTACTO), SEM_DESTINATARIO);
    }
  });

  it("a base de identidade em baixo sobe, e a ligação volta com o erro", async () => {
    const devolvidas: unknown[] = [];
    const destinatario = destinatarioPelaIdentidade({
      identidade: {
        lerEndpoints: async () => {
          throw new Error("identidade em baixo");
        },
      },
      tomar: async () => ({ query: async () => ({ rows: [] }) }),
      devolver: (_l, erro) => {
        devolvidas.push(erro);
      },
    });
    await assert.rejects(destinatario(TENANT, CONTACTO), /identidade em baixo/);
    assert.equal(devolvidas.length, 1);
    assert.ok(devolvidas[0] instanceof Error);
  });
});
