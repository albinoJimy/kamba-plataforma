/**
 * A rotação da chave do facilitador sem perder pagamentos (KAM-072, critério 2,
 * e o F-16 do `docs/tecnica/04` §3.3), contra o servidor falso do KAM-056.
 *
 * A chave HMAC do ProxyPay **é** a API key. O ensaio faz a rotação inteira: o
 * cofre roda (`Rotador`), o facilitador passa a conhecer só a nova, e durante a
 * janela o PAY aceita *callbacks* assinados com as duas. Revogada a anterior,
 * um *callback* assinado com ela é recusado (`AuthError`) — e o pagamento que
 * ele trazia **não se perde**: o reconciliador lê-o da fila `GET /payments` com
 * a chave nova.
 *
 * Se o facilitador aceita duas chaves em simultâneo é **NÃO VERIFICADO**
 * (`evidencia/E2` Q10): o servidor falso modela o pior caso — troca, sem
 * sobreposição do lado dele. O ensaio contra o *sandbox* real é a caixa
 * devolvida do critério 2.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import {
  type Anel,
  CofreEmMemoria,
  RegistoEmMemoria,
  Rotador,
  chavesVivas,
  gerarValor,
} from "../src/keyring/index.ts";
import { type AccountSecrets, AuthError, proxypay } from "../src/pagamentos/index.ts";
import { assinado } from "./pagamentos.proxypay.banco.ts";
import { ServidorProxyPay } from "./pagamentos.proxypay.servidor.ts";

const SEGREDO = "proxypay_api_key";
const REF_ANTERIOR = `${SEGREDO}/anterior`;
const T0 = new Date("2026-11-16T10:00:00.000Z");

const CONTA: AccountSecrets = {
  accountId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  credenciaisRef: SEGREDO,
  credenciaisRefAnterior: REF_ANTERIOR,
};

function pagamento(id: string): Record<string, unknown> {
  return {
    id,
    reference_id: "100000001",
    amount: "1024.09",
    datetime: "2026-11-16T10:30:00.000Z",
    custom_fields: { charge: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" },
    entity_id: "00123",
    fee: "15.00",
    terminal_type: "ATM",
  };
}

async function erroDe(promessa: Promise<unknown>): Promise<unknown> {
  try {
    await promessa;
  } catch (erro) {
    return erro;
  }
  return undefined;
}

describe("keyring + proxypay: rotação trimestral sem perder pagamentos (critério 2, F-16)", () => {
  const relogio = { agora: T0 };
  const cofre = new CofreEmMemoria();
  const rotador = new Rotador({ cofre, registo: new RegistoEmMemoria(), actor: "eng_pagamentos", agora: () => relogio.agora });
  const servidor = new ServidorProxyPay();
  let adaptador: proxypay.ProxyPayRps;
  const k1 = { kid: "k1", valor: gerarValor() };
  const k2 = { kid: "k2", valor: gerarValor() };

  /**
   * O resolvedor de `credenciais_ref` que o PAY recebe: a corrente é a actual
   * do anel, e a anterior só existe enquanto estiver **viva** — dentro da
   * janela e não revogada. Fora disso levanta, como o cofre levanta por um
   * segredo apagado, e o adaptador cai para «só a corrente».
   */
  async function resolver(ref: string): Promise<string> {
    const vivas = chavesVivas((await cofre.ler(SEGREDO)) as Anel, relogio.agora);
    if (ref === SEGREDO) return (vivas[0] as { valor: string }).valor;
    if (ref === REF_ANTERIOR && vivas[1] !== undefined) return vivas[1].valor;
    throw new Error("sem essa versão no cofre");
  }

  before(async () => {
    await servidor.iniciar();
    servidor.conta(k1.valor);
    await rotador.iniciar(SEGREDO, k1);
    adaptador = new proxypay.ProxyPayRps({
      base: servidor.base,
      transporte: proxypay.transporteFetch(5_000),
      contas: { conta: async (id) => (id === CONTA.accountId ? { segredos: CONTA, entidade: "00123" } : undefined) },
      chaves: resolver,
      referencias: new proxypay.ReferenciasEmMemoria(),
      agora: () => relogio.agora.getTime(),
    });
  });

  after(async () => {
    await servidor.fechar();
  });

  /** O facilitador troca a chave da conta: a antiga deixa de lhe servir. */
  function facilitadorTroca(de: string, para: string): void {
    const conta = servidor.contas.get(de);
    if (conta === undefined) throw new Error("conta desconhecida no servidor falso");
    servidor.contas.delete(de);
    servidor.contas.set(para, conta);
  }

  it("durante a janela aceita callbacks assinados com a corrente e com a anterior", async () => {
    await rotador.rotate(SEGREDO, k2);
    facilitadorTroca(k1.valor, k2.valor);
    relogio.agora = new Date(T0.getTime() + 3_600_000);
    for (const [id, chave] of [["777000001", k1.valor], ["777000002", k2.valor]] as const) {
      const [evento] = await adaptador.verifyCallback(assinado(pagamento(id), chave), CONTA);
      assert.equal(evento?.providerEventId, `rps:${id}`);
      assert.equal(evento?.authnMethod, "hmac");
    }
  });

  it("revogada a anterior, recusa-a com AuthError — e o reconciliador recupera o pagamento pela consulta", async () => {
    await rotador.revogar(SEGREDO);
    // O pagamento chegou à fila do facilitador; o *callback* veio assinado com
    // a chave que já não aceitamos (entregue a meio da troca).
    const pago = servidor.pagar(k2.valor, {
      id: "777000003",
      referencia: "100000001",
      amount: "1024.09",
      datetime: "2026-11-16T11:30:00.000Z",
      charge: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    });
    const erro = await erroDe(adaptador.verifyCallback(assinado(pago, k1.valor), CONTA));
    assert.ok(erro instanceof AuthError, "a chave revogada é recusada");

    const pagina = await adaptador.listUnacknowledged(CONTA);
    assert.deepEqual(
      pagina.eventos.map((e) => [e.providerEventId, e.authnMethod, e.valor]),
      [["rps:777000003", "consulta", 102_409n]],
      "o pagamento não se perdeu: chega por consulta, com a chave nova",
    );
  });

  it("a janela também fecha sozinha: passada a janela, a anterior já não verifica mesmo sem revogação", async () => {
    const k3 = { kid: "k3", valor: gerarValor() };
    await rotador.rotate(SEGREDO, k3);
    facilitadorTroca(k2.valor, k3.valor);
    relogio.agora = new Date(relogio.agora.getTime() + 86_400_000);
    const erro = await erroDe(adaptador.verifyCallback(assinado(pagamento("777000004"), k2.valor), CONTA));
    assert.ok(erro instanceof AuthError);
    assert.equal((await adaptador.verifyCallback(assinado(pagamento("777000005"), k3.valor), CONTA)).length, 1);
  });
});
