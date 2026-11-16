/**
 * O adaptador ProxyPay RPS (KAM-056) contra um servidor falso local.
 *
 * Nenhum ensaio toca no fornecedor: o *sandbox* e o `ext:KAM-103`. O que aqui
 * se mede e o adaptador — o que ele manda, o que aceita e o que recusa — sobre
 * HTTP verdadeiro em `127.0.0.1`, com o transporte de producao (`fetch`).
 *
 * Os oraculos nao vem do alvo: o valor `decimal2` esperado e um literal do
 * ensaio, e a assinatura e calculada com o `node:crypto` directamente.
 */

import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { after, before, describe, it } from "node:test";

import {
  AuthError,
  ProviderError,
  RegistoDeProviders,
  correr,
  relatorio,
  proxypay,
} from "../src/pagamentos/index.ts";
import {
  AGORA,
  type Ambiente,
  CONTA_A,
  CONTA_B,
  type FraquezasRps,
  _chave,
  ambiente,
  assinado,
  bancoRps,
} from "./pagamentos.proxypay.banco.ts";

function hmacHex(corpo: Uint8Array, chave: string): string {
  return createHmac("sha256", chave).update(corpo).digest("hex");
}

function pagamento(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "777000111",
    reference_id: "100000001",
    amount: "1024.09",
    datetime: "2026-10-29T12:00:00.000Z",
    custom_fields: { charge: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" },
    entity_id: "00123",
    fee: "15.00",
    terminal_type: "ATM",
    ...extra,
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

describe("proxypay/rps: criterio 3 — a suite de conformidade do §3.5 contra o servidor falso", () => {
  it("os dez casos passam", async () => {
    const { banco, fechar } = await bancoRps();
    try {
      const veredicto = await correr(banco);
      assert.equal(veredicto.verde, true, relatorio(veredicto));
      assert.equal(veredicto.resultados.length, 10);
      assert.equal(veredicto.adaptador, "proxypay_rps");
    } finally {
      await fechar();
    }
  });

  /**
   * Os canarios: cada um estraga uma ligacao do adaptador e exige o seu caso
   * vermelho. Sem isto, dez verdes podiam ser dez casos que nao medem nada.
   */
  const CANARIOS: readonly [keyof FraquezasRps, string][] = [
    ["semMemoriaDeReferencias", "criacao_com_resposta_perdida_e_idempotente"],
    ["chavePartilhada", "assinatura_adulterada_rejeita"],
    ["rateLimitComoIndisponivel", "rate_limit_429"],
    ["anteriorErrada", "rotacao_de_chave"],
  ];
  for (const [fraqueza, caso] of CANARIOS) {
    it(`sem '${fraqueza}', o caso '${caso}' fica vermelho`, async () => {
      const { banco, fechar } = await bancoRps({ [fraqueza]: true });
      try {
        const veredicto = await correr(banco);
        const resultado = veredicto.resultados.find((r) => r.caso === caso);
        assert.ok(resultado !== undefined);
        assert.equal(resultado.ok, false, `o caso '${caso}' passou com '${fraqueza}'`);
      } finally {
        await fechar();
      }
    });
  }
});

describe("proxypay/rps: criterio 1 — createCharge", () => {
  let a: Ambiente;
  before(async () => {
    a = await ambiente();
  });
  after(async () => {
    await a.fechar();
  });

  it("faz POST /reference_ids e PUT /references/{id} com amount decimal2, end_datetime e custom_fields {charge}", async () => {
    const pedido = a.pedido(CONTA_A, 102_409n);
    const antes = a.servidor.registo.length;
    const cobranca = await a.adaptador.createCharge(pedido);
    assert.deepEqual(a.servidor.registo.slice(antes), [
      "POST /reference_ids",
      `PUT /references/${cobranca.kind === "referencia" ? cobranca.referencia : "?"}`,
    ]);
    assert.equal(cobranca.kind, "referencia");
    if (cobranca.kind !== "referencia") return;
    assert.equal(cobranca.entidade, "00123");
    assert.equal(cobranca.valor, 102_409n);
    const guardada = a.servidor.conta(_chave(CONTA_A.credenciaisRef)).referencias.get(cobranca.referencia);
    assert.deepEqual(guardada, {
      amount: "1024.09",
      end_datetime: "2026-10-30T12:00:00.000Z",
      custom_fields: { charge: pedido.chargeId },
    });
  });

  it("repetir com o mesmo chargeId repete o PUT pelo mesmo id e nao cria 2.a referencia", async () => {
    const pedido = a.pedido();
    const criacoes = a.servidor.criacoes;
    const antes = a.servidor.registo.length;
    const uma = await a.adaptador.createCharge(pedido);
    const outra = await a.adaptador.createCharge(pedido);
    assert.deepEqual(uma, outra);
    assert.equal(a.servidor.criacoes - criacoes, 1);
    const pedidos = a.servidor.registo.slice(antes);
    assert.equal(pedidos.filter((p) => p === "POST /reference_ids").length, 1);
    assert.equal(pedidos.filter((p) => p.startsWith("PUT ")).length, 2);
  });

  it("uma resposta perdida no PUT da TIMEOUT_UNKNOWN, e a repeticao reutiliza o id", async () => {
    const pedido = a.pedido();
    const criacoes = a.servidor.criacoes;
    a.servidor.programar("resposta_perdida");
    const erro = await erroDe(a.adaptador.createCharge(pedido));
    assert.ok(erro instanceof ProviderError);
    assert.equal(erro.codigo, "TIMEOUT_UNKNOWN");
    const depois = await a.adaptador.createCharge(pedido);
    assert.equal(depois.kind, "referencia");
    assert.equal(a.servidor.criacoes - criacoes, 1);
  });

  it("o mesmo chargeId com outro montante ou outro valid_until recusa, sem reescrever a referencia", async () => {
    const pedido = a.pedido();
    const cobranca = await a.adaptador.createCharge(pedido);
    if (cobranca.kind !== "referencia") throw new Error("esperava referencia");
    const antes = a.servidor.registo.length;
    for (const outro of [{ ...pedido, amount: pedido.amount + 1n }, { ...pedido, validUntil: "2026-10-31T12:00:00.000Z" }]) {
      const erro = await erroDe(a.adaptador.createCharge(outro));
      assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION");
    }
    assert.equal(a.servidor.registo.length, antes, "nenhum PUT saiu");
    assert.equal(
      a.servidor.conta(_chave(CONTA_A.credenciaisRef)).referencias.get(cobranca.referencia)?.amount,
      "1500.00",
    );
  });

  it("uma chave vazia no cofre recusa antes de qualquer pedido", async () => {
    const vazia = new proxypay.ProxyPayRps({
      base: a.servidor.base,
      transporte: proxypay.transporteFetch(5_000),
      contas: { conta: async () => ({ segredos: CONTA_A, entidade: "00123" }) },
      chaves: async () => "",
      referencias: new proxypay.ReferenciasEmMemoria(),
      agora: () => AGORA,
    });
    const antes = a.servidor.registo.length;
    const erro = await erroDe(vazia.createCharge(a.pedido()));
    assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION");
    assert.equal(a.servidor.registo.length, antes);
  });

  it("um id de referencia mais comprido do que o refMaxLen recusa", async () => {
    const comprido = new proxypay.ProxyPayRps({
      base: a.servidor.base,
      transporte: async (p) =>
        p.metodo === "POST" ? { estado: 200, corpo: "1234567890" } : proxypay.transporteFetch(5_000)(p),
      contas: { conta: async () => ({ segredos: CONTA_A, entidade: "00123" }) },
      chaves: async (ref) => _chave(ref),
      referencias: new proxypay.ReferenciasEmMemoria(),
      agora: () => AGORA,
    });
    const erro = await erroDe(comprido.createCharge(a.pedido()));
    assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION");
  });

  it("recusa campos alem de {charge} sem fazer pedido nenhum (sem PII)", async () => {
    const antes = a.servidor.registo.length;
    const pedido = { ...a.pedido(), customFields: { telefone: "999 000 000" } };
    const erro = await erroDe(a.adaptador.createCharge(pedido));
    assert.ok(erro instanceof ProviderError);
    assert.equal(erro.codigo, "VALIDATION");
    assert.equal(a.servidor.registo.length, antes);
  });

  it("recusa um charge nos custom_fields que nao e o chargeId", async () => {
    const pedido = { ...a.pedido(), customFields: { charge: "outro" } };
    const erro = await erroDe(a.adaptador.createCharge(pedido));
    assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION");
  });

  it("os limites do amount: 0,01 e 99.999.999,99 aceitam, 0 e 100.000.000,00 recusam", async () => {
    for (const ok of [1n, 9_999_999_999n]) {
      await a.adaptador.createCharge(a.pedido(CONTA_A, ok));
    }
    for (const mau of [0n, 10_000_000_000n]) {
      const erro = await erroDe(a.adaptador.createCharge(a.pedido(CONTA_A, mau)));
      assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION", `${mau}`);
    }
  });

  it("recusa outro metodo com NOT_SUPPORTED, e um valid_until no passado", async () => {
    const push = await erroDe(a.adaptador.createCharge({ ...a.pedido(), metodo: "express_push" }));
    assert.ok(push instanceof ProviderError && push.codigo === "NOT_SUPPORTED");
    const passado = await erroDe(a.adaptador.createCharge({ ...a.pedido(), validUntil: "2026-10-29T11:00:00.000Z" }));
    assert.ok(passado instanceof ProviderError && passado.codigo === "VALIDATION");
  });

  it("autentica com Authorization: Token <API_KEY> da conta", async () => {
    let autorizacao = "";
    const espiao = new proxypay.ProxyPayRps({
      base: a.servidor.base,
      transporte: async (p) => {
        autorizacao = p.cabecalhos.Authorization ?? "";
        return proxypay.transporteFetch(5_000)(p);
      },
      contas: { conta: async () => ({ segredos: CONTA_A, entidade: "00123" }) },
      chaves: async (ref) => _chave(ref),
      referencias: new proxypay.ReferenciasEmMemoria(),
      agora: () => AGORA,
    });
    await espiao.createCharge(a.pedido());
    assert.equal(autorizacao, `Token ${_chave(CONTA_A.credenciaisRef)}`);
  });

  it("refund e payout devolvem NOT_SUPPORTED (ADR-004)", async () => {
    assert.deepEqual(await a.adaptador.refund({ chargeId: "x", amount: 1n }), { ok: false, erro: "NOT_SUPPORTED" });
    assert.deepEqual(
      await a.adaptador.payout({ tenantId: "t", accountId: "a", amount: 1n, currency: "AOA" }),
      { ok: false, erro: "NOT_SUPPORTED" },
    );
  });

  it("cancelCharge apaga a referencia, e um 404 e erro (a rota e NAO VERIFICADA)", async () => {
    const pedido = a.pedido();
    const cobranca = await a.adaptador.createCharge(pedido);
    if (cobranca.kind !== "referencia") throw new Error("esperava referencia");
    const ref = { providerId: "proxypay_rps", referencia: cobranca.referencia, providerChargeId: pedido.chargeId };
    await a.adaptador.cancelCharge(ref);
    assert.equal(a.servidor.conta(_chave(CONTA_A.credenciaisRef)).referencias.has(cobranca.referencia), false);
    const segunda = await erroDe(a.adaptador.cancelCharge(ref));
    assert.ok(segunda instanceof ProviderError && segunda.codigo === "VALIDATION");
  });
});

describe("proxypay/rps: criterio 2 — verifyCallback e a janela de duas chaves", () => {
  let a: Ambiente;
  before(async () => {
    a = await ambiente();
  });
  after(async () => {
    await a.fechar();
  });

  it("aceita a chave corrente e a anterior, e devolve o valor exacto e o fee", async () => {
    for (const ref of [CONTA_A.credenciaisRef, CONTA_A.credenciaisRefAnterior ?? ""]) {
      const [evento] = await a.adaptador.verifyCallback(assinado(pagamento(), _chave(ref)), CONTA_A);
      assert.ok(evento !== undefined);
      assert.equal(evento.valor, 102_409n);
      assert.equal(evento.fee, 1_500n);
      assert.equal(evento.authnMethod, "hmac");
      assert.equal(evento.providerEventId, "rps:777000111");
      assert.equal(evento.referencia, "100000001");
      // O `charge` dos `custom_fields` segue no evento, para o G5 do worker.
      assert.equal(evento.providerChargeId, "dddddddd-dddd-4ddd-8ddd-dddddddddddd");
    }
  });

  it("a assinatura e o HMAC-SHA256 hexadecimal do corpo cru com a API key", async () => {
    const corpo = new TextEncoder().encode(JSON.stringify(pagamento()));
    const chave = _chave(CONTA_A.credenciaisRef);
    assert.equal(proxypay.assinaturaRps(corpo, chave), hmacHex(corpo, chave));
  });

  it("1 byte alterado no corpo levanta AuthError — em cada posicao", async () => {
    const genuino = assinado(pagamento(), _chave(CONTA_A.credenciaisRef));
    for (let i = 0; i < genuino.corpo.length; i += 1) {
      const corpo = Uint8Array.from(genuino.corpo);
      corpo[i] = (corpo[i] ?? 0) ^ 0x01;
      const erro = await erroDe(a.adaptador.verifyCallback({ corpo, cabecalhos: genuino.cabecalhos }, CONTA_A));
      assert.ok(erro instanceof AuthError, `posicao ${i}`);
    }
  });

  it("1 caractere alterado na assinatura levanta AuthError", async () => {
    const genuino = assinado(pagamento(), _chave(CONTA_A.credenciaisRef));
    const assinatura = genuino.cabecalhos["X-Signature"] ?? "";
    for (let i = 0; i < assinatura.length; i += 1) {
      const trocado = `${assinatura.slice(0, i)}${assinatura[i] === "a" ? "b" : "a"}${assinatura.slice(i + 1)}`;
      const erro = await erroDe(
        a.adaptador.verifyCallback({ corpo: genuino.corpo, cabecalhos: { "X-Signature": trocado } }, CONTA_A),
      );
      assert.ok(erro instanceof AuthError, `posicao ${i}`);
    }
  });

  it("a chave de outra conta, a ausencia do cabecalho e uma assinatura truncada levantam AuthError", async () => {
    const deB = assinado(pagamento(), _chave(CONTA_B.credenciaisRef));
    assert.ok((await erroDe(a.adaptador.verifyCallback(deB, CONTA_A))) instanceof AuthError);
    const sem = { corpo: deB.corpo, cabecalhos: {} };
    assert.ok((await erroDe(a.adaptador.verifyCallback(sem, CONTA_B))) instanceof AuthError);
    const curta = { corpo: deB.corpo, cabecalhos: { "X-Signature": (deB.cabecalhos["X-Signature"] ?? "").slice(0, 63) } };
    assert.ok((await erroDe(a.adaptador.verifyCallback(curta, CONTA_B))) instanceof AuthError);
  });

  it("a anterior revogada no cofre nao derruba a corrente", async () => {
    const revogada = new proxypay.ProxyPayRps({
      base: a.servidor.base,
      transporte: proxypay.transporteFetch(5_000),
      contas: { conta: async () => undefined },
      chaves: async (ref) => {
        if (ref === CONTA_A.credenciaisRefAnterior) throw new Error("revogada");
        return _chave(ref);
      },
      referencias: new proxypay.ReferenciasEmMemoria(),
    });
    const genuino = assinado(pagamento(), _chave(CONTA_A.credenciaisRef));
    assert.equal((await revogada.verifyCallback(genuino, CONTA_A)).length, 1);
  });

  it("uma chave vazia no cofre nao verifica nada, nem um HMAC calculado com ela", async () => {
    const vazia = new proxypay.ProxyPayRps({
      base: a.servidor.base,
      transporte: proxypay.transporteFetch(5_000),
      contas: { conta: async () => undefined },
      chaves: async () => "",
      referencias: new proxypay.ReferenciasEmMemoria(),
    });
    const forjado = assinado(pagamento(), "");
    assert.ok((await erroDe(vazia.verifyCallback(forjado, CONTA_A))) instanceof AuthError);
  });

  it("sem chave anterior na conta, a anterior ja nao verifica", async () => {
    const comAnterior = assinado(pagamento(), _chave(CONTA_A.credenciaisRefAnterior ?? ""));
    const so = { accountId: CONTA_A.accountId, credenciaisRef: CONTA_A.credenciaisRef };
    assert.ok((await erroDe(a.adaptador.verifyCallback(comAnterior, so))) instanceof AuthError);
  });

  it("o nome do cabecalho nao distingue maiusculas", async () => {
    const genuino = assinado(pagamento(), _chave(CONTA_A.credenciaisRef));
    const minusculas = { corpo: genuino.corpo, cabecalhos: { "x-signature": genuino.cabecalhos["X-Signature"] ?? "" } };
    assert.equal((await a.adaptador.verifyCallback(minusculas, CONTA_A)).length, 1);
  });

  it("um corpo assinado com forma errada e VALIDATION e nao AuthError", async () => {
    const casos: Record<string, unknown>[] = [
      pagamento({ amount: 1024.09 }),
      pagamento({ amount: "1024.091" }),
      pagamento({ id: 9_007_199_254_740_993 }),
      pagamento({ datetime: undefined }),
      pagamento({ datetime: "29/10/2026" }),
      pagamento({ reference_id: "" }),
      pagamento({ fee: 15 }),
    ];
    for (const caso of casos) {
      const erro = await erroDe(a.adaptador.verifyCallback(assinado(caso, _chave(CONTA_A.credenciaisRef)), CONTA_A));
      assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION", JSON.stringify(caso));
    }
    const lixo = new TextEncoder().encode("nao e json");
    const naoJson = { corpo: lixo, cabecalhos: { "X-Signature": hmacHex(lixo, _chave(CONTA_A.credenciaisRef)) } };
    const erro = await erroDe(a.adaptador.verifyCallback(naoJson, CONTA_A));
    assert.ok(erro instanceof ProviderError && erro.codigo === "VALIDATION");
  });

  it("o instante vem do corpo e normaliza-se para UTC", async () => {
    const [evento] = await a.adaptador.verifyCallback(
      assinado(pagamento({ datetime: "2026-10-29T13:00:00+01:00" }), _chave(CONTA_A.credenciaisRef)),
      CONTA_A,
    );
    assert.equal(evento?.ocorridoEm, "2026-10-29T12:00:00.000Z");
  });

  /**
   * Criterio 6: «sem *timestamp* assinado, a janela ±5 min nao e aplicada; a
   * defesa de *replay* e G7». Um corpo de ha um ano verifica, e dez entregas do
   * mesmo corpo dao uma chave so — que e por onde o G7 absorve.
   */
  it("criterio 6: sem janela de tempo, e o replay da sempre a mesma chave do G7", async () => {
    const antigo = assinado(pagamento({ datetime: "2025-10-29T12:00:00.000Z" }), _chave(CONTA_A.credenciaisRef));
    const chaves = new Set<string>();
    for (let n = 0; n < 10; n += 1) {
      for (const e of await a.adaptador.verifyCallback(antigo, CONTA_A)) chaves.add(e.providerEventId);
    }
    assert.deepEqual([...chaves], ["rps:777000111"]);
  });

  it("criterio 7: o fee vai para payload.fee em unidade menor", () => {
    const lido = proxypay.lerPagamentoRps(pagamento());
    assert.deepEqual(proxypay.payloadDoPagamento(lido), {
      fee: "1500",
      entity_id: "00123",
      terminal_type: "ATM",
    });
  });
});

describe("proxypay/rps: status e fila", () => {
  let a: Ambiente;
  before(async () => {
    a = await ambiente();
  });
  after(async () => {
    await a.fechar();
  });

  it("status: desconhecida fora da fila, paga com o valor da fila, desconhecida fora das nossas", async () => {
    const pedido = a.pedido();
    const cobranca = await a.adaptador.createCharge(pedido);
    if (cobranca.kind !== "referencia") throw new Error("esperava referencia");
    const ref = { providerId: "proxypay_rps", providerChargeId: pedido.chargeId };
    assert.equal((await a.adaptador.status(ref)).estado, "desconhecida");
    a.servidor.pagar(_chave(CONTA_A.credenciaisRef), {
      id: "880000001",
      referencia: cobranca.referencia,
      amount: "1500.00",
      datetime: "2026-10-29T12:05:00.000Z",
    });
    const estado = await a.adaptador.status(ref);
    assert.equal(estado.estado, "paga");
    assert.equal(estado.valor, 150_000n);
    assert.equal(estado.providerEventId, "rps:880000001");
    assert.equal((await a.adaptador.status({ providerId: "proxypay_rps", referencia: "000000002" })).estado, "desconhecida");
  });

  it("status: um pagamento a mesma referencia com o charge de outra integracao, ou sem charge, nao conta", async () => {
    for (const [id, charge] of [["880000002", "de-outra-integracao"], ["880000003", ""]] as const) {
      const pedido = a.pedido();
      const cobranca = await a.adaptador.createCharge(pedido);
      if (cobranca.kind !== "referencia") throw new Error("esperava referencia");
      const pago = a.servidor.pagar(_chave(CONTA_A.credenciaisRef), {
        id,
        referencia: cobranca.referencia,
        amount: "1500.00",
        datetime: "2026-10-29T12:05:00.000Z",
        charge: charge === "" ? "x" : charge,
      });
      if (charge === "") pago.custom_fields = {};
      const estado = await a.adaptador.status({ providerId: "proxypay_rps", providerChargeId: pedido.chargeId });
      assert.equal(estado.estado, "desconhecida", id);
    }
  });

  it("listUnacknowledged le a fila como 'consulta', e acknowledge tira dela (404 e sucesso)", async () => {
    const chave = _chave(CONTA_B.credenciaisRef);
    a.servidor.pagar(chave, { id: "990000001", referencia: "100000009", amount: "10.00", datetime: "2026-10-29T12:00:00.000Z" });
    const pagina = await a.adaptador.listUnacknowledged(CONTA_B);
    assert.deepEqual(pagina.eventos.map((e) => [e.providerEventId, e.authnMethod, e.valor]), [["rps:990000001", "consulta", 1_000n]]);
    await a.adaptador.acknowledge(CONTA_B, "rps:990000001");
    assert.deepEqual(a.servidor.fila(chave), []);
    await a.adaptador.acknowledge(CONTA_B, "rps:990000001");
  });
});

describe("proxypay/rps: os erros do §3.1 por HTTP", () => {
  it("401 -> AUTH, 429 -> RATE_LIMIT, 5xx -> UNAVAILABLE, 422 -> VALIDATION", () => {
    assert.equal(proxypay.codigoDoEstado(401), "AUTH");
    assert.equal(proxypay.codigoDoEstado(403), "AUTH");
    assert.equal(proxypay.codigoDoEstado(429), "RATE_LIMIT");
    assert.equal(proxypay.codigoDoEstado(503), "UNAVAILABLE");
    assert.equal(proxypay.codigoDoEstado(422), "VALIDATION");
    assert.equal(proxypay.codigoDoEstado(418), "REJECTED");
  });

  it("uma chave errada da AUTH pelo servidor", async () => {
    const a = await ambiente();
    try {
      const errado = new proxypay.ProxyPayRps({
        base: a.servidor.base,
        transporte: proxypay.transporteFetch(5_000),
        contas: { conta: async () => ({ segredos: CONTA_A, entidade: "00123" }) },
        chaves: async () => "chave-que-o-servidor-nao-conhece",
        referencias: new proxypay.ReferenciasEmMemoria(),
        agora: () => AGORA,
      });
      const erro = await erroDe(errado.createCharge(a.pedido()));
      assert.ok(erro instanceof ProviderError && erro.codigo === "AUTH");
    } finally {
      await a.fechar();
    }
  });

  it("uma ligacao recusada e UNAVAILABLE: o pedido nao saiu", async () => {
    const a = await ambiente();
    const base = a.servidor.base;
    await a.fechar();
    const morto = new proxypay.ProxyPayRps({
      base,
      transporte: proxypay.transporteFetch(2_000),
      contas: { conta: async () => ({ segredos: CONTA_A, entidade: "00123" }) },
      chaves: async (ref) => _chave(ref),
      referencias: new proxypay.ReferenciasEmMemoria(),
      agora: () => AGORA,
    });
    const erro = await erroDe(morto.createCharge(a.pedido()));
    assert.ok(erro instanceof ProviderError && erro.codigo === "UNAVAILABLE", String(erro));
  });

  it("a mensagem de erro nunca leva a chave, no 429, no 401 nem na resposta perdida", async () => {
    const a = await ambiente();
    try {
      const erros: unknown[] = [];
      a.servidor.programar("rate_limit");
      erros.push(await erroDe(a.adaptador.createCharge(a.pedido())));
      a.servidor.programar("resposta_perdida");
      erros.push(await erroDe(a.adaptador.createCharge(a.pedido())));
      a.servidor.contas.delete(_chave(CONTA_A.credenciaisRef));
      erros.push(await erroDe(a.adaptador.createCharge(a.pedido())));
      assert.deepEqual(
        erros.map((e) => (e instanceof ProviderError ? e.codigo : String(e))),
        ["RATE_LIMIT", "TIMEOUT_UNKNOWN", "AUTH"],
      );
      for (const e of erros) {
        assert.equal((e as Error).message.includes(_chave(CONTA_A.credenciaisRef)), false);
      }
    } finally {
      await a.fechar();
    }
  });

  it("a base tem de ser HTTPS, salvo no anel local", () => {
    assert.throws(() => proxypay.baseSegura("http://api.proxypay.co.ao"), ProviderError);
    assert.equal(proxypay.baseSegura("https://api.sandbox.proxypay.co.ao/"), "https://api.sandbox.proxypay.co.ao");
    assert.equal(proxypay.baseSegura("http://127.0.0.1:8080"), "http://127.0.0.1:8080");
  });
});

describe("proxypay/rps: recuo com jitter para o 429", () => {
  const P = { pedidos: 4, baseMs: 100, tectoMs: 1_000 };

  it("a janela dobra e para no tecto, e o jitter cai dentro dela", () => {
    const janelas = [0, 1, 2, 3, 4, 10].map((ordem) => proxypay.recuoComJitter(ordem, P, (n) => n - 1));
    assert.deepEqual(janelas, [100, 200, 400, 800, 1_000, 1_000]);
    assert.equal(proxypay.recuoComJitter(3, P, () => 0), 0);
  });

  it("repete so o RATE_LIMIT, e esgotadas as tentativas o ultimo sobe", async () => {
    let chamadas = 0;
    const dormidas: number[] = [];
    const resultado = await proxypay.comRecuo(
      async () => {
        chamadas += 1;
        if (chamadas < 3) throw new ProviderError("RATE_LIMIT", "429");
        return "ok";
      },
      P,
      async (ms) => {
        dormidas.push(ms);
      },
      (n) => n - 1,
    );
    assert.equal(resultado, "ok");
    assert.deepEqual(dormidas, [100, 200]);

    let sempre = 0;
    const erro = await erroDe(
      proxypay.comRecuo(async () => {
        sempre += 1;
        throw new ProviderError("RATE_LIMIT", "429");
      }, P, async () => undefined),
    );
    assert.ok(erro instanceof ProviderError && erro.codigo === "RATE_LIMIT");
    assert.equal(sempre, 4);

    let incerto = 0;
    await erroDe(
      proxypay.comRecuo(async () => {
        incerto += 1;
        throw new ProviderError("TIMEOUT_UNKNOWN", "?");
      }, P, async () => undefined),
    );
    assert.equal(incerto, 1, "um TIMEOUT_UNKNOWN nao se repete as cegas");
  });
});

describe("proxypay: criterio 9 — atras de proxypay_enabled=false", () => {
  it("as omissoes sao as duas desligadas", () => {
    assert.deepEqual(proxypay.FLAGS_PROXYPAY_OMISSAO, { proxypayEnabled: false, proxypayOpgEnabled: false });
  });

  it("com a flag desligada, o RPS nao se activa", async () => {
    const a = await ambiente();
    try {
      const registo = new RegistoDeProviders({ green: () => true });
      assert.throws(
        () => proxypay.activarProxyPay(registo, proxypay.FLAGS_PROXYPAY_OMISSAO, { rps: a.adaptador }),
        proxypay.ProxyPayDesligado,
      );
      assert.deepEqual(registo.ids, []);
    } finally {
      await a.fechar();
    }
  });

  it("com a flag ligada continua a exigir a suite verde (CONFORMANCE_REQUIRED)", async () => {
    const a = await ambiente();
    try {
      const flags = { proxypayEnabled: true, proxypayOpgEnabled: false };
      const semSuite = new RegistoDeProviders();
      assert.throws(() => proxypay.activarProxyPay(semSuite, flags, { rps: a.adaptador }), /conformidade/);
      const comSuite = new RegistoDeProviders({ green: (id) => id === "proxypay_rps" });
      proxypay.activarProxyPay(comSuite, flags, { rps: a.adaptador });
      assert.deepEqual(comSuite.ids, ["proxypay_rps"]);
    } finally {
      await a.fechar();
    }
  });
});
