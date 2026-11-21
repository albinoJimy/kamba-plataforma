/**
 * O leitor de contactos do COM sobre a identidade (KAM-206): o que ele pede ao
 * `lerEndpoints`, a ligação que toma e devolve, e o que faz aos erros.
 *
 * A identidade é um duplo: o que se mede aqui é a **ligação** entre o COM e o
 * `lerEndpoints` — as opções que vão, o `antes` que chega a quem lê, e a ligação
 * devolvida ao *pool* em todos os caminhos. A ordem auditar-antes-de-decifrar
 * mede-se contra o PostgreSQL, em `packages/core-ts/tests_bd/identity.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ContactoApagadoError, DekDestruidaError, type OpcoesDaLeitura } from "@kamba/core-ts/identity";

import { leitorPelaIdentidade, type LigacaoDaIdentidade } from "../src/orders/contacto_identidade.ts";

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const CONTACTO = "0000000c-0000-4000-8000-0000000000c1";
const DEPOIS = new Date("2026-12-20T10:00:00.000Z");

function montar(comportamento: (opcoes: OpcoesDaLeitura, ligacao: LigacaoDaIdentidade) => Promise<unknown>) {
  const registo = { tomadas: 0, devolvidas: 0, opcoes: [] as OpcoesDaLeitura[], pedidos: [] as string[] };
  const ligacao: LigacaoDaIdentidade = {
    async query() {
      return { rows: [], rowCount: 0 };
    },
    release() {
      registo.devolvidas += 1;
    },
  };
  const leitor = leitorPelaIdentidade({
    pool: {
      async connect() {
        registo.tomadas += 1;
        return ligacao;
      },
    },
    identidade: {
      async lerEndpoints(cliente, tenantId, contactId, opcoes = {}) {
        assert.equal(cliente, ligacao, "a leitura nao correu na ligacao tomada");
        registo.pedidos.push(`${tenantId}:${contactId}`);
        registo.opcoes.push(opcoes);
        return (await comportamento(opcoes, ligacao)) as never;
      },
    },
  });
  return { leitor, registo };
}

test("pede so os telefones da encomenda, passa o antes na ligacao da leitura e devolve a ligacao", async () => {
  const { leitor, registo } = montar(async (opcoes, ligacao) => {
    await opcoes.antes?.(ligacao);
    return {
      contactId: CONTACTO,
      bsuids: [],
      telefones: [{ finalidade: "entrega", telefone: "+244 999 000 222", expiraAt: DEPOIS }],
    };
  });
  const vistos: unknown[] = [];
  const telefones = await leitor.telefones(TENANT, CONTACTO, async (cliente) => {
    vistos.push(cliente);
  });
  assert.deepEqual(telefones, [{ finalidade: "entrega", telefone: "+244 999 000 222", expiraAt: DEPOIS }]);
  assert.deepEqual(registo.pedidos, [`${TENANT}:${CONTACTO}`]);
  assert.equal(registo.opcoes[0]?.soTelefones, true);
  assert.deepEqual(registo.opcoes[0]?.finalidades, ["contacto_pedido", "entrega"]);
  assert.equal(vistos.length, 1, "o antes nao chegou a quem le");
  assert.deepEqual([registo.tomadas, registo.devolvidas], [1, 1]);
});

test("contacto apagado e chave destruida dao null; outro erro sobe; a ligacao volta sempre", async () => {
  for (const ErroDaIdentidade of [ContactoApagadoError, DekDestruidaError]) {
    const { leitor, registo } = montar(async () => {
      throw new ErroDaIdentidade();
    });
    assert.equal(await leitor.telefones(TENANT, CONTACTO, async () => {}), null, ErroDaIdentidade.name);
    assert.deepEqual([registo.tomadas, registo.devolvidas], [1, 1], ErroDaIdentidade.name);
  }
  const { leitor, registo } = montar(async () => {
    throw new Error("a base caiu");
  });
  await assert.rejects(leitor.telefones(TENANT, CONTACTO, async () => {}), /a base caiu/);
  assert.deepEqual([registo.tomadas, registo.devolvidas], [1, 1]);
});
