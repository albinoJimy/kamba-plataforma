/**
 * O *job* de reconciliacao do RPS e a expiracao (KAM-056, criterios 4 e 5).
 *
 * O ledger e um duplo minimo com as duas propriedades que a reconciliacao usa:
 * o G7 (um `providerEventId` so tem um efeito) e o *commit* (o `processar`
 * resolve depois de escrever). A ordem *commit* -> `DELETE` mede-se pelo
 * registo intercalado dos dois lados, e nao pela leitura do codigo.
 */

import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import { type AccountSecrets, type VerifiedEvent, proxypay } from "../src/pagamentos/index.ts";
import { type Ambiente, CONTA_A, CONTA_B, _chave, ambiente } from "./pagamentos.proxypay.banco.ts";

type Ledger = {
  readonly efeitos: Map<string, VerifiedEvent>;
  readonly payloads: Map<string, Readonly<Record<string, unknown>>>;
  readonly ordem: string[];
  falharProximo: boolean;
};

function ledger(): Ledger {
  return { efeitos: new Map(), payloads: new Map(), ordem: [], falharProximo: false };
}

/** As dependencias do *job* sobre o ambiente, com o ledger falso e um relogio. */
function deps(
  a: Ambiente,
  l: Ledger,
  relogio: { agora: number },
  orfaos: string[] = [],
): proxypay.DependenciasDaReconciliacao {
  const fila: proxypay.FilaRps = {
    pagamentosPorReconhecer: (acct) => a.adaptador.pagamentosPorReconhecer(acct),
    acknowledge: async (acct, id) => {
      l.ordem.push(`delete ${id}`);
      await a.adaptador.acknowledge(acct, id);
    },
  };
  return {
    fila,
    cobrancaNossa: async (accountId, referencia) => {
      const [emitida] = (await a.referencias.porReferencia(referencia)).filter((r) => r.accountId === accountId);
      return emitida === undefined ? undefined : { chargeId: emitida.chargeId };
    },
    processar: async (_acct, evento, pagamento) => {
      if (l.falharProximo) {
        l.falharProximo = false;
        throw new Error("rollback");
      }
      // G7: o mesmo `providerEventId` escreve-se uma vez.
      if (!l.efeitos.has(evento.providerEventId)) {
        l.efeitos.set(evento.providerEventId, evento);
        l.payloads.set(evento.providerEventId, proxypay.payloadDoPagamento(pagamento));
      }
      l.ordem.push(`commit ${evento.providerEventId}`);
    },
    alertarOrfao: async (_conta, pagamento) => {
      orfaos.push(pagamento.id);
    },
    agora: () => relogio.agora,
    dormir: async () => undefined,
  };
}

async function cobrar(a: Ambiente, conta: AccountSecrets = CONTA_A): Promise<{ chargeId: string; referencia: string }> {
  const pedido = a.pedido(conta);
  const cobranca = await a.adaptador.createCharge(pedido);
  if (cobranca.kind !== "referencia") throw new Error("esperava referencia");
  return { chargeId: pedido.chargeId, referencia: cobranca.referencia };
}

describe("proxypay/reconcile: criterio 4 — commit antes do DELETE, e so cobrancas nossas", () => {
  let a: Ambiente;
  before(async () => {
    a = await ambiente();
  });
  after(async () => {
    await a.fechar();
  });

  it("processa, faz commit e so depois reconhece", async () => {
    const l = ledger();
    const { referencia } = await cobrar(a);
    a.servidor.pagar(_chave(CONTA_A.credenciaisRef), {
      id: "500000001",
      referencia,
      amount: "1500.00",
      datetime: "2026-10-29T12:00:00.000Z",
    });
    const r = await proxypay.reconciliarConta(CONTA_A, deps(a, l, { agora: Date.parse("2026-10-29T12:03:00.000Z") }));
    assert.equal(r.reconhecidos, 1);
    assert.deepEqual(l.ordem, ["commit rps:500000001", "delete rps:500000001"]);
    assert.deepEqual(a.servidor.fila(_chave(CONTA_A.credenciaisRef)), []);
  });

  it("um pagamento desconhecido gera alerta, passa pelo ledger (orfao) e NAO e reconhecido", async () => {
    const l = ledger();
    const orfaos: string[] = [];
    a.servidor.pagar(_chave(CONTA_A.credenciaisRef), {
      id: "500000002",
      referencia: "300000000",
      amount: "50.00",
      datetime: "2026-10-29T12:00:00.000Z",
    });
    const antes = a.servidor.registo.length;
    const r = await proxypay.reconciliarConta(CONTA_A, deps(a, l, { agora: Date.parse("2026-10-29T12:01:00.000Z") }, orfaos));
    assert.equal(r.orfaos, 1);
    assert.equal(r.reconhecidos, 0);
    assert.deepEqual(orfaos, ["500000002"]);
    assert.ok(l.efeitos.has("rps:500000002"), "o orfao fica no ledger (G3 -> pagamento_orfao)");
    assert.equal(a.servidor.registo.slice(antes).some((p) => p.startsWith("DELETE")), false);
    assert.deepEqual(a.servidor.fila(_chave(CONTA_A.credenciaisRef)), ["500000002"]);
  });

  it("um pagamento a nossa referencia sem charge nos custom_fields e orfao", async () => {
    const l = ledger();
    const orfaos: string[] = [];
    const chave = _chave(CONTA_B.credenciaisRef);
    for (const id of a.servidor.fila(chave)) a.servidor.conta(chave).reconhecidos.add(id);
    const { referencia } = await cobrar(a, CONTA_B);
    const pago = a.servidor.pagar(chave, { id: "500000005", referencia, amount: "1500.00", datetime: "2026-10-29T12:00:00.000Z" });
    pago.custom_fields = {};
    const r = await proxypay.reconciliarConta(CONTA_B, deps(a, l, { agora: AGORA_MAIS(1) }, orfaos));
    assert.equal(r.reconhecidos, 0);
    assert.deepEqual(orfaos, ["500000005"]);
    assert.deepEqual(a.servidor.fila(chave), ["500000005"]);
    a.servidor.conta(chave).reconhecidos.add("500000005");
  });

  it("a mesma referencia com o charge de outra integracao e orfao", async () => {
    const l = ledger();
    const orfaos: string[] = [];
    const { referencia } = await cobrar(a, CONTA_B);
    a.servidor.pagar(_chave(CONTA_B.credenciaisRef), {
      id: "500000003",
      referencia,
      amount: "1500.00",
      datetime: "2026-10-29T12:00:00.000Z",
      charge: "loja-web-da-pme",
    });
    const r = await proxypay.reconciliarConta(CONTA_B, deps(a, l, { agora: AGORA_MAIS(1) }, orfaos));
    assert.equal(r.reconhecidos, 0);
    assert.deepEqual(orfaos, ["500000003"]);
    assert.deepEqual(a.servidor.fila(_chave(CONTA_B.credenciaisRef)), ["500000003"]);
  });

  it("sem commit nao ha DELETE: o pagamento fica e volta na volta seguinte", async () => {
    const l = ledger();
    const chave = _chave(CONTA_B.credenciaisRef);
    for (const id of a.servidor.fila(chave)) a.servidor.conta(chave).reconhecidos.add(id);
    const { referencia } = await cobrar(a, CONTA_B);
    a.servidor.pagar(chave, { id: "500000004", referencia, amount: "1500.00", datetime: "2026-10-29T12:00:00.000Z" });
    l.falharProximo = true;
    const primeira = await proxypay.reconciliarConta(CONTA_B, deps(a, l, { agora: AGORA_MAIS(1) }));
    assert.equal(primeira.falhasDeProcessamento, 1);
    assert.deepEqual(l.ordem, []);
    assert.deepEqual(a.servidor.fila(chave), ["500000004"]);
    const segunda = await proxypay.reconciliarConta(CONTA_B, deps(a, l, { agora: AGORA_MAIS(6) }));
    assert.equal(segunda.reconhecidos, 1);
    assert.deepEqual(l.ordem, ["commit rps:500000004", "delete rps:500000004"]);
  });
});

function AGORA_MAIS(minutos: number): number {
  return Date.parse("2026-10-29T12:00:00.000Z") + minutos * 60_000;
}

describe("proxypay/reconcile: criterio 5 — 100 pagamentos perdidos, lag p99 <= 10 min, DELETE falhado", () => {
  let a: Ambiente;
  before(async () => {
    a = await ambiente();
  });
  after(async () => {
    await a.fechar();
  });

  it("os 100 entram no ledger uma vez cada, com lag p99 <= 10 min e fee em 100%", async () => {
    const l = ledger();
    const chave = _chave(CONTA_A.credenciaisRef);
    const relogio = { agora: AGORA_MAIS(0) };
    const reconciliador = new proxypay.Reconciliador(deps(a, l, relogio), async () => [
      { segredos: CONTA_A, estado: "activa" },
      { segredos: CONTA_B, estado: "suspensa" },
    ]);
    let tique: (() => void) | undefined;
    let periodo = 0;
    reconciliador.agendar(
      () => undefined,
      (fn, ms) => {
        tique = fn;
        periodo = ms;
        return () => undefined;
      },
    );
    assert.equal(periodo, 5 * 60_000);

    // Cem pagamentos cujo callback se perdeu, espalhados por 25 min.
    const lags: number[] = [];
    let n = 0;
    for (let volta = 1; volta <= 5; volta += 1) {
      for (let k = 0; k < 20; k += 1) {
        n += 1;
        const { referencia } = await cobrar(a);
        const pagoEm = AGORA_MAIS((volta - 1) * 5) + k * 14_000;
        a.servidor.pagar(chave, {
          id: `${600_000_000 + n}`,
          referencia,
          amount: "1500.00",
          datetime: new Date(pagoEm).toISOString(),
        });
      }
      // Uma volta a cada 5 min. O DELETE de um falha na terceira volta.
      relogio.agora = AGORA_MAIS(volta * 5);
      if (volta === 3) a.servidor.programar("erro_no_delete");
      const { resultados, falhas } = await reconciliador.volta();
      assert.equal(falhas.size, 0);
      const r = resultados.get(CONTA_A.accountId);
      assert.ok(r !== undefined);
      assert.equal(resultados.has(CONTA_B.accountId), false, "conta suspensa nao se reconcilia");
      lags.push(...r.lagsMs);
      if (volta === 3) {
        assert.equal(r.falhasDeReconhecimento, 1);
        assert.equal(r.reconhecidos, 19);
      }
      // O que falhou o DELETE reaparece na volta seguinte e o G7 absorve-o:
      // 21 lidos, 21 reconhecidos, e o ledger nao ganha efeito nenhum a mais.
      if (volta === 4) {
        assert.equal(r.lidos, 21);
        assert.equal(r.reconhecidos, 21);
      }
    }
    assert.ok(tique !== undefined);

    const nossos = [...l.efeitos.keys()].filter((k) => k.startsWith("rps:6"));
    assert.equal(nossos.length, 100);
    assert.equal(new Set(nossos).size, 100);
    assert.deepEqual(a.servidor.fila(chave), []);
    const p99 = proxypay.percentil(lags, 99);
    assert.ok(p99 <= proxypay.ALVO_DO_LAG_P99_MS, `p99 = ${p99} ms`);
    for (const id of nossos) assert.equal(l.payloads.get(id)?.fee, "1500", id);
  });

  it("o percentil e o do posto mais proximo", () => {
    const cem = Array.from({ length: 100 }, (_, i) => i + 1);
    assert.equal(proxypay.percentil(cem, 99), 99);
    assert.equal(proxypay.percentil(cem, 100), 100);
    assert.equal(proxypay.percentil([5], 99), 5);
    assert.equal(proxypay.percentil([], 99), 0);
  });

  it("duas voltas pedidas ao mesmo tempo sobre a mesma conta sao uma", async () => {
    const l = ledger();
    const reconciliador = new proxypay.Reconciliador(deps(a, l, { agora: AGORA_MAIS(40) }), async () => []);
    const antes = a.servidor.registo.length;
    await Promise.all([reconciliador.conta(CONTA_A), reconciliador.conta(CONTA_A)]);
    assert.deepEqual(
      a.servidor.registo.slice(antes).filter((r) => r === "GET /payments"),
      ["GET /payments"],
      "uma leitura da fila, e nao duas",
    );
    // E a «fresca» espera pela que corre e faz outra.
    const depois = a.servidor.registo.length;
    await Promise.all([reconciliador.conta(CONTA_A), reconciliador.conta(CONTA_A, true)]);
    assert.equal(a.servidor.registo.slice(depois).filter((r) => r === "GET /payments").length, 2);
  });

  it("uma conta que falha nao para as outras, e a falha chega ao aoFalhar", async () => {
    const l = ledger();
    const revogada: AccountSecrets = { accountId: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", credenciaisRef: "cofre/proxypay/conta-a" };
    const d = deps(a, l, { agora: AGORA_MAIS(42) });
    const fila: proxypay.FilaRps = {
      pagamentosPorReconhecer: async (acct) => {
        if (acct.accountId === revogada.accountId) throw new Error("AUTH");
        return d.fila.pagamentosPorReconhecer(acct);
      },
      acknowledge: d.fila.acknowledge,
    };
    const reconciliador = new proxypay.Reconciliador({ ...d, fila }, async () => [
      { segredos: revogada, estado: "activa" },
      { segredos: CONTA_B, estado: "activa" },
    ]);
    const { resultados, falhas } = await reconciliador.volta();
    assert.deepEqual([...falhas.keys()], [revogada.accountId]);
    assert.ok(resultados.has(CONTA_B.accountId), "a conta B correu depois da falha da primeira");
    const avisadas: (string | undefined)[] = [];
    let tique: (() => void) | undefined;
    reconciliador.agendar(
      (_erro, conta) => avisadas.push(conta),
      (fn) => {
        tique = fn;
        return () => undefined;
      },
    );
    tique?.();
    for (let i = 0; i < 50 && avisadas.length === 0; i += 1) await new Promise((r) => setTimeout(r, 20));
    assert.deepEqual(avisadas, [revogada.accountId]);
  });

  it("um 429 na leitura da fila recua e repete", async () => {
    const l = ledger();
    a.servidor.programar("rate_limit");
    const r = await proxypay.reconciliarConta(CONTA_A, deps(a, l, { agora: AGORA_MAIS(41) }));
    assert.equal(r.falhasDeProcessamento, 0);
  });
});

describe("proxypay/reconcile: a expiracao reconcilia antes de expirar", () => {
  it("um pagamento cujo callback se perdeu impede a expiracao; sem pagamento, expira", async () => {
    const a = await ambiente();
    try {
      const l = ledger();
      const reconciliador = new proxypay.Reconciliador(deps(a, l, { agora: AGORA_MAIS(10) }), async () => []);
      const paga = await cobrar(a);
      const porPagar = await cobrar(a);
      a.servidor.pagar(_chave(CONTA_A.credenciaisRef), {
        id: "700000001",
        referencia: paga.referencia,
        amount: "1500.00",
        datetime: "2026-10-29T12:00:00.000Z",
      });
      const estaPaga = (referencia: string) => async () =>
        [...l.efeitos.values()].some((e) => e.referencia === referencia);
      assert.equal(await proxypay.antesDeExpirar(reconciliador, CONTA_A, estaPaga(paga.referencia)), "paga");
      assert.equal(await proxypay.antesDeExpirar(reconciliador, CONTA_A, estaPaga(porPagar.referencia)), "expirar");
    } finally {
      await a.fechar();
    }
  });

  it("com um processar falhado, nao expira: ExpiracaoAdiada", async () => {
    const a = await ambiente();
    try {
      const l = ledger();
      const reconciliador = new proxypay.Reconciliador(deps(a, l, { agora: AGORA_MAIS(10) }), async () => []);
      const paga = await cobrar(a);
      a.servidor.pagar(_chave(CONTA_A.credenciaisRef), {
        id: "700000002",
        referencia: paga.referencia,
        amount: "1500.00",
        datetime: "2026-10-29T12:00:00.000Z",
      });
      l.falharProximo = true;
      await assert.rejects(
        proxypay.antesDeExpirar(reconciliador, CONTA_A, async () => false),
        proxypay.ExpiracaoAdiada,
      );
      // Na volta seguinte o processar passa, e a decisao e «paga».
      const estaPaga = async () => [...l.efeitos.values()].some((e) => e.referencia === paga.referencia);
      assert.equal(await proxypay.antesDeExpirar(reconciliador, CONTA_A, estaPaga), "paga");
    } finally {
      await a.fechar();
    }
  });

  it("cem orfaos a cabeca da fila bloqueiam-na, e a expiracao fica adiada", async () => {
    const a = await ambiente();
    try {
      const l = ledger();
      const chave = _chave(CONTA_A.credenciaisRef);
      for (let i = 0; i < 100; i += 1) {
        a.servidor.pagar(chave, {
          id: `${800_000_000 + i}`,
          referencia: "300000001",
          amount: "1.00",
          datetime: "2026-10-29T12:00:00.000Z",
        });
      }
      const nossa = await cobrar(a);
      a.servidor.pagar(chave, { id: "899999999", referencia: nossa.referencia, amount: "1500.00", datetime: "2026-10-29T12:01:00.000Z" });
      const orfaos: string[] = [];
      const r = await proxypay.reconciliarConta(CONTA_A, deps(a, l, { agora: AGORA_MAIS(5) }, orfaos));
      assert.equal(r.filaBloqueada, true);
      assert.equal(r.orfaos, 100);
      assert.equal(l.efeitos.has("rps:899999999"), false, "o nosso esta atras da pagina e nao se ve");
      const reconciliador = new proxypay.Reconciliador(deps(a, l, { agora: AGORA_MAIS(6) }), async () => []);
      await assert.rejects(
        proxypay.antesDeExpirar(reconciliador, CONTA_A, async () => false),
        proxypay.ExpiracaoAdiada,
      );
    } finally {
      await a.fechar();
    }
  });

  it("sem conseguir ler a fila, nao expira: levanta", async () => {
    const a = await ambiente();
    const l = ledger();
    const reconciliador = new proxypay.Reconciliador(deps(a, l, { agora: AGORA_MAIS(10) }), async () => []);
    await a.fechar();
    await assert.rejects(proxypay.antesDeExpirar(reconciliador, CONTA_A, async () => false));
  });
});
