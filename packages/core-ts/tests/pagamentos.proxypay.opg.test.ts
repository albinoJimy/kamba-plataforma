/**
 * O adaptador ProxyPay OPG (KAM-056, criterio 8) contra o servidor falso local.
 *
 * Os numeros sao ficticios, com o prefixo 999 (ver o servidor). O que se mede:
 * o `Idempotency-Key`, a janela de 5 min da resposta perdida, o callback como
 * dica, o mapa de codigos e a recusa de activacao sem consulta confirmada.
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import {
  AdapterCannotConfirm,
  type CreateChargeReq,
  ProviderError,
  RegistoDeProviders,
  proxypay,
} from "../src/pagamentos/index.ts";
import { AGORA, CONTA_A, TENANT, VALID_UNTIL } from "./pagamentos.proxypay.banco.ts";
import { OPG_ACEITA, OPG_RECUSA, ServidorProxyPay } from "./pagamentos.proxypay.servidor.ts";

const PORTADOR_OPG = "portador-opg-de-ensaio";

type Opg = {
  readonly servidor: ServidorProxyPay;
  readonly relogio: { agora: number };
  readonly cabecalhos: Record<string, string>[];
  adaptador(statusQueryConfirmado?: boolean): proxypay.ProxyPayOpg;
};

async function opg(): Promise<Opg> {
  const servidor = new ServidorProxyPay();
  await servidor.iniciar();
  servidor.opgTokens.add(PORTADOR_OPG);
  const relogio = { agora: AGORA };
  const cabecalhos: Record<string, string>[] = [];
  const tentativas = new proxypay.TentativasOpgEmMemoria();
  const transporte = proxypay.transporteFetch(5_000);
  return {
    servidor,
    relogio,
    cabecalhos,
    adaptador: (statusQueryConfirmado = false) =>
      new proxypay.ProxyPayOpg({
        base: servidor.base,
        transporte: async (p) => {
          cabecalhos.push({ ...p.cabecalhos });
          return transporte(p);
        },
        contas: { conta: async () => ({ segredos: CONTA_A, posId: "POS-1" }) },
        chaves: async () => PORTADOR_OPG,
        telemovel: async (ref) => (ref === "recusa" ? OPG_RECUSA : OPG_ACEITA),
        tentativas,
        statusQueryConfirmado,
        agora: () => relogio.agora,
      }),
  };
}

function pedido(payer = "aceita"): CreateChargeReq {
  return {
    chargeId: randomUUID(),
    tenantId: TENANT,
    accountId: CONTA_A.accountId,
    numeroPublico: "K-0002",
    amount: 5_000n,
    currency: "AOA",
    metodo: "express_push",
    validUntil: VALID_UNTIL,
    payer: { endpointRef: payer },
    customFields: {},
  };
}

describe("proxypay/opg: criterio 8 — Idempotency-Key e resposta perdida", () => {
  let o: Opg;
  before(async () => {
    o = await opg();
  });
  after(async () => {
    await o.servidor.fechar();
  });

  it("envia Idempotency-Key = chargeId, Bearer e amount decimal2", async () => {
    const p = pedido();
    const cobranca = await o.adaptador().createCharge(p);
    assert.equal(cobranca.kind, "push");
    const ultimo = o.cabecalhos.at(-1) ?? {};
    assert.equal(ultimo["Idempotency-Key"], p.chargeId);
    assert.equal(ultimo.Authorization, `Bearer ${PORTADOR_OPG}`);
    if (cobranca.kind !== "push") return;
    assert.equal(o.servidor.transaccoes.get(cobranca.providerChargeId)?.amount, "50.00");
  });

  it("resposta perdida: repete o POST dentro de 5 min pela mesma chave, e cria uma so transaccao", async () => {
    const p = pedido();
    const adaptador = o.adaptador();
    const criadas = o.servidor.criacoesOpg;
    o.servidor.programar("resposta_perdida");
    const erro = await adaptador.createCharge(p).catch((e: unknown) => e);
    assert.ok(erro instanceof ProviderError && erro.codigo === "TIMEOUT_UNKNOWN");
    o.relogio.agora = AGORA + 4 * 60_000;
    const cobranca = await adaptador.createCharge(p);
    assert.equal(cobranca.kind, "push");
    assert.equal(o.servidor.criacoesOpg - criadas, 1);
    o.relogio.agora = AGORA;
  });

  it("depois de 5 min sem resposta, nao repete o POST: criacao_incerta", async () => {
    const p = pedido();
    const adaptador = o.adaptador();
    o.servidor.programar("resposta_perdida");
    await adaptador.createCharge(p).catch(() => undefined);
    const posts = o.servidor.registo.filter((r) => r.startsWith("POST /opg")).length;
    o.relogio.agora = AGORA + 5 * 60_000 + 1;
    const erro = await adaptador.createCharge(p).catch((e: unknown) => e);
    assert.ok(erro instanceof proxypay.CriacaoIncerta);
    assert.equal(erro.codigo, "TIMEOUT_UNKNOWN");
    assert.equal(erro.novaTentativaDepoisDe, new Date(AGORA + 30 * 60_000).toISOString());
    assert.equal(o.servidor.registo.filter((r) => r.startsWith("POST /opg")).length, posts);
    o.relogio.agora = AGORA;
  });

  it("uma ligacao recusada nao conta como primeira tentativa, e um 5xx no POST e TIMEOUT_UNKNOWN", async () => {
    const p = pedido();
    const tentativas = new proxypay.TentativasOpgEmMemoria();
    // Uma porta efemera que ja nao escuta: ligacao recusada. (A porta 1 nao
    // serve: o `fetch` recusa-a como «bad port» sem codigo, e isso le-se, bem,
    // como «nao sei se saiu».)
    const fechado = new ServidorProxyPay();
    await fechado.iniciar();
    const base = fechado.base;
    await fechado.fechar();
    const morto = new proxypay.ProxyPayOpg({
      base,
      transporte: proxypay.transporteFetch(2_000),
      contas: { conta: async () => ({ segredos: CONTA_A, posId: "POS-1" }) },
      chaves: async () => PORTADOR_OPG,
      telemovel: async () => OPG_ACEITA,
      tentativas,
      agora: () => AGORA,
    });
    const erro = await morto.createCharge(p).catch((e: unknown) => e);
    assert.ok(erro instanceof ProviderError && erro.codigo === "UNAVAILABLE", String(erro));
    assert.equal(await tentativas.porCobranca(p.chargeId), undefined);

    const gateway = new proxypay.ProxyPayOpg({
      base: o.servidor.base,
      transporte: async () => ({ estado: 502, corpo: "" }),
      contas: { conta: async () => ({ segredos: CONTA_A, posId: "POS-1" }) },
      chaves: async () => PORTADOR_OPG,
      telemovel: async () => OPG_ACEITA,
      tentativas,
      agora: () => AGORA,
    });
    const incerto = await gateway.createCharge(p).catch((e: unknown) => e);
    assert.ok(incerto instanceof ProviderError && incerto.codigo === "TIMEOUT_UNKNOWN");
    assert.equal((await tentativas.porCobranca(p.chargeId))?.primeiraMs, AGORA);
  });

  it("o mesmo chargeId noutra conta recusa, e um push guardado com mais de 30 min tambem", async () => {
    const p = pedido();
    const a = o.adaptador();
    await a.createCharge(p);
    const outra = await a.createCharge({ ...p, accountId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" }).catch((e: unknown) => e);
    assert.ok(outra instanceof ProviderError && outra.codigo === "VALIDATION");
    o.relogio.agora = AGORA + 30 * 60_000 + 1;
    const velho = await a.createCharge(p).catch((e: unknown) => e);
    assert.ok(velho instanceof ProviderError && velho.codigo === "VALIDATION");
    o.relogio.agora = AGORA;
  });

  it("recusa referencia, pagador em falta e refund/payout", async () => {
    const a = o.adaptador();
    const ref = await a.createCharge({ ...pedido(), metodo: "referencia" }).catch((e: unknown) => e);
    assert.ok(ref instanceof ProviderError && ref.codigo === "NOT_SUPPORTED");
    const { payer: _sem, ...semPagador } = pedido();
    const falta = await a.createCharge(semPagador).catch((e: unknown) => e);
    assert.ok(falta instanceof ProviderError && falta.codigo === "VALIDATION");
    assert.deepEqual(await a.refund({ chargeId: "x", amount: 1n }), { ok: false, erro: "NOT_SUPPORTED" });
  });
});

describe("proxypay/opg: o callback e dica e nunca confirma sozinho", () => {
  let o: Opg;
  before(async () => {
    o = await opg();
  });
  after(async () => {
    await o.servidor.fechar();
  });

  function dica(id: string, amount = "1.00"): { corpo: Uint8Array; cabecalhos: Record<string, string> } {
    return { corpo: new TextEncoder().encode(JSON.stringify({ id, status: "accepted", amount })), cabecalhos: {} };
  }

  it("o callback nunca produz evento, com ou sem consulta confirmada", async () => {
    for (const confirmada of [false, true]) {
      const a = o.adaptador(confirmada);
      const cobranca = await a.createCharge(pedido());
      if (cobranca.kind !== "push") throw new Error("esperava push");
      assert.deepEqual(await a.verifyCallback(dica(cobranca.providerChargeId), CONTA_A), []);
      assert.equal(a.transaccaoDaDica(dica(cobranca.providerChargeId)), cobranca.providerChargeId);
    }
    const semId = { corpo: new TextEncoder().encode("{}"), cabecalhos: {} };
    const erro = await o.adaptador().verifyCallback(semId, CONTA_A).catch((e: unknown) => e);
    assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION");
  });

  it("o status() le o valor da consulta autenticada, e nao do corpo da dica", async () => {
    const a = o.adaptador(true);
    const cobranca = await a.createCharge(pedido());
    if (cobranca.kind !== "push") throw new Error("esperava push");
    const estado = await a.status({ providerId: "proxypay_opg", providerChargeId: a.transaccaoDaDica(dica(cobranca.providerChargeId, "1.00")) });
    assert.equal(estado.estado, "paga");
    assert.equal(estado.valor, 5_000n);
    assert.equal(estado.providerEventId, `opg:${cobranca.providerChargeId}`);
  });

  it("uma transaccao recusada da falhada, e uma desconhecida da desconhecida", async () => {
    const a = o.adaptador(true);
    const cobranca = await a.createCharge(pedido("recusa"));
    if (cobranca.kind !== "push") throw new Error("esperava push");
    assert.equal((await a.status({ providerId: "proxypay_opg", providerChargeId: cobranca.providerChargeId })).estado, "falhada");
    assert.equal((await a.status({ providerId: "proxypay_opg", providerChargeId: "123" })).estado, "desconhecida");
  });

  it("sem consulta confirmada, o registo recusa activar: ADAPTER_CANNOT_CONFIRM", () => {
    const registo = new RegistoDeProviders({ green: () => true });
    const flags = { proxypayEnabled: true, proxypayOpgEnabled: true };
    assert.throws(() => proxypay.activarProxyPay(registo, flags, { opg: o.adaptador(false) }), AdapterCannotConfirm);
    assert.throws(
      () => proxypay.activarProxyPay(registo, { proxypayEnabled: true, proxypayOpgEnabled: false }, { opg: o.adaptador(true) }),
      proxypay.ProxyPayDesligado,
    );
  });
});

describe("proxypay/opg: codigos -> mensagens do §3.3", () => {
  const ESPERADO: readonly [number, string, boolean, boolean][] = [
    [1000, "Nao foi possivel enviar o pedido. A tentar novamente.", true, false],
    [1003, "Nao foi possivel enviar o pedido. A tentar novamente.", true, false],
    [2001, "O saldo nao chega para este valor.", false, false],
    [2003, "Atingiu o limite diario do cartao.", false, false],
    [2004, "O tempo para aprovar terminou. Quer que reenvie?", false, false],
    [3000, "Pedido recusado por si. Posso cancelar ou tentar outro meio.", false, false],
    [2010, "Nao foi possivel concluir o pagamento. Posso tentar outro meio.", false, true],
  ];
  for (const [codigo, texto, repetir, registar] of ESPERADO) {
    it(`${codigo}`, () => {
      const m = proxypay.mensagemOpg(codigo);
      assert.equal(m.texto, `${texto} A aprovacao aparece na sua app do banco; nunca partilhe o PIN.`);
      assert.equal(m.repetir, repetir);
      assert.equal(m.registarCodigo, registar);
    });
  }

  it("todas levam o aviso anti-phishing", () => {
    for (let c = 1000; c <= 3000; c += 1) {
      assert.ok(proxypay.mensagemOpg(c).texto.endsWith(proxypay.AVISO_ANTI_PHISHING));
    }
  });
});
