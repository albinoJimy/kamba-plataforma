/**
 * O banco de ensaio do adaptador RPS (KAM-056), para o harness do §3.5.
 *
 * O harness e o do KAM-052 e nao muda; isto e so a forma de provocar os dez
 * casos **contra o servidor falso local**. O caso 1 recebe callbacks assinados
 * com a chave de outra conta, o caso 7 perde a resposta de um `PUT` que o
 * servidor processou, e o caso 9 recebe um 429 verdadeiro por HTTP.
 *
 * As `fraquezas` sao os canarios: cada uma estraga **uma ligacao** do
 * adaptador — a memoria das referencias, a resolucao da chave por conta, o
 * transporte — e o ensaio exige que o caso dela fique vermelho. Nao mexem no
 * codigo do adaptador: mexem no que ele recebe, que e onde um erro de *wiring*
 * do servico `pay` cairia.
 */

import { randomUUID } from "node:crypto";

import {
  type AccountSecrets,
  type BancoDeEnsaio,
  type CreateChargeReq,
  type ProviderRef,
  type RawHttpCallback,
  proxypay,
} from "../src/pagamentos/index.ts";
import { ServidorProxyPay } from "./pagamentos.proxypay.servidor.ts";

/** O instante fixo dos ensaios. As referencias valem ate ao dia seguinte. */
export const AGORA = Date.UTC(2026, 9, 29, 12, 0, 0);
export const VALID_UNTIL = "2026-10-30T12:00:00.000Z";

/** Literais de ensaio, sem forma de chave de fornecedor. */
export const CHAVES: Readonly<Record<string, string>> = {
  "cofre/proxypay/conta-a": "chave-de-ensaio-conta-a-kam-056",
  "cofre/proxypay/conta-a/anterior": "chave-de-ensaio-conta-a-anterior-kam-056",
  "cofre/proxypay/conta-b": "chave-de-ensaio-conta-b-kam-056",
};

export const CONTA_A: AccountSecrets = {
  accountId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  credenciaisRef: "cofre/proxypay/conta-a",
  credenciaisRefAnterior: "cofre/proxypay/conta-a/anterior",
};

export const CONTA_B: AccountSecrets = {
  accountId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  credenciaisRef: "cofre/proxypay/conta-b",
};

export const TENANT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

export type FraquezasRps = {
  /** As referencias esquecem-se: cada `createCharge` pede um id novo. */
  readonly semMemoriaDeReferencias?: boolean;
  /**
   * O cofre resolve todas as `credenciais_ref` na **mesma** chave (a da conta
   * B): a chave partilhada entre PMEs que o §3.3 proibe.
   */
  readonly chavePartilhada?: boolean;
  /** O transporte troca o 429 por um 503. */
  readonly rateLimitComoIndisponivel?: boolean;
  /**
   * O cofre resolve a `credenciais_ref` anterior na chave **corrente**: a conta
   * aponta para a anterior, e o adaptador nunca a usa de facto.
   */
  readonly anteriorErrada?: boolean;
};

export type Ambiente = {
  readonly servidor: ServidorProxyPay;
  readonly adaptador: proxypay.ProxyPayRps;
  readonly referencias: proxypay.ReferenciasEmitidas;
  readonly contaA: AccountSecrets;
  pedido(conta?: AccountSecrets, amount?: bigint): CreateChargeReq;
  fechar(): Promise<void>;
};

/** O servidor falso a correr e o adaptador ligado a ele. */
export async function ambiente(fraquezas: FraquezasRps = {}): Promise<Ambiente> {
  const servidor = new ServidorProxyPay();
  await servidor.iniciar();
  servidor.conta(_chave(CONTA_A.credenciaisRef));
  servidor.conta(_chave(CONTA_B.credenciaisRef));

  const referencias: proxypay.ReferenciasEmitidas = fraquezas.semMemoriaDeReferencias
    ? {
        porCobranca: async () => undefined,
        porReferencia: async () => [],
        reservar: async (r) => r,
      }
    : new proxypay.ReferenciasEmMemoria();
  const contaA: AccountSecrets = CONTA_A;
  const base = proxypay.transporteFetch(5_000);
  const transporte: proxypay.Transporte = fraquezas.rateLimitComoIndisponivel
    ? async (p) => {
        const r = await base(p);
        return r.estado === 429 ? { estado: 503, corpo: r.corpo } : r;
      }
    : base;
  const adaptador = new proxypay.ProxyPayRps({
    base: servidor.base,
    transporte,
    contas: {
      conta: async (id) =>
        id === CONTA_A.accountId
          ? { segredos: contaA, entidade: "00123" }
          : id === CONTA_B.accountId
            ? { segredos: CONTA_B, entidade: "00456" }
            : undefined,
    },
    chaves: async (ref) =>
      fraquezas.chavePartilhada
        ? _chave(CONTA_B.credenciaisRef)
        : fraquezas.anteriorErrada && ref === CONTA_A.credenciaisRefAnterior
          ? _chave(CONTA_A.credenciaisRef)
          : _chave(ref),
    referencias,
    agora: () => AGORA,
  });
  return {
    servidor,
    adaptador,
    referencias,
    contaA,
    pedido: (conta = CONTA_A, amount = 1_500_00n) => ({
      chargeId: randomUUID(),
      tenantId: TENANT,
      accountId: conta.accountId,
      numeroPublico: "K-0001",
      amount,
      currency: "AOA",
      metodo: "referencia",
      validUntil: VALID_UNTIL,
      customFields: {},
    }),
    fechar: () => servidor.fechar(),
  };
}

export function _chave(ref: string): string {
  const chave = CHAVES[ref];
  if (chave === undefined) throw new Error(`chave de ensaio desconhecida: ${ref}`);
  return chave;
}

/** O corpo cru de um pagamento, assinado com uma chave. */
export function assinado(pagamento: Record<string, unknown>, chave: string): RawHttpCallback {
  const corpo = new TextEncoder().encode(JSON.stringify(pagamento));
  return { corpo, cabecalhos: { "X-Signature": proxypay.assinaturaRps(corpo, chave) } };
}

/** O banco do harness do §3.5 sobre o ambiente. */
export async function bancoRps(fraquezas: FraquezasRps = {}): Promise<{ banco: BancoDeEnsaio; fechar(): Promise<void> }> {
  const a = await ambiente(fraquezas);
  const cobrancaDaReferencia = new Map<string, string>();
  const banco: BancoDeEnsaio = {
    provider: a.adaptador,
    conta: a.contaA,
    contaAlternativa: CONTA_B,
    pedido: () => a.pedido(),
    async callback(evento, chave = "actual", conta = a.contaA) {
      let referencia = evento.referencia;
      let charge: string | undefined;
      if (referencia === undefined) {
        const pedido = a.pedido(conta);
        const cobranca = await a.adaptador.createCharge(pedido);
        if (cobranca.kind !== "referencia") throw new Error("o RPS devolveu outra coisa");
        referencia = cobranca.referencia;
        charge = pedido.chargeId;
        cobrancaDaReferencia.set(referencia, charge);
      }
      const pagamento = a.servidor.pagar(_chave(conta.credenciaisRef), {
        id: evento.providerEventId,
        referencia,
        amount: _decimal2(evento.valor),
        datetime: evento.ocorridoEm,
        ...(charge === undefined ? {} : { charge }),
      });
      const ref = chave === "anterior" ? conta.credenciaisRefAnterior : conta.credenciaisRef;
      if (ref === undefined) throw new Error("a conta de ensaio nao tem chave anterior");
      return assinado(pagamento, _chave(ref));
    },
    adulterar(callback) {
      const assinatura = Object.values(callback.cabecalhos)[0] ?? "";
      const trocado = `${assinatura[0] === "0" ? "1" : "0"}${assinatura.slice(1)}`;
      return { corpo: callback.corpo, cabecalhos: { "X-Signature": trocado } };
    },
    programar: (falha) => a.servidor.programar(falha),
    criacoesNoFacilitador: () => a.servidor.criacoes,
    refDe: (evento): ProviderRef => ({
      providerId: proxypay.ID_PROXYPAY_RPS,
      ...(evento.referencia === undefined ? {} : { referencia: evento.referencia }),
      ...(evento.referencia !== undefined && cobrancaDaReferencia.has(evento.referencia)
        ? { providerChargeId: cobrancaDaReferencia.get(evento.referencia) as string }
        : {}),
    }),
    refDesconhecida: () => ({ providerId: proxypay.ID_PROXYPAY_RPS, referencia: "000000001" }),
  };
  return { banco, fechar: a.fechar };
}

/** `102409n` -> `"1024.09"`, sem o adaptador. */
export function _decimal2(valor: bigint): string {
  const kz = valor / 100n;
  const centimos = valor % 100n;
  return `${kz}.${`${centimos}`.padStart(2, "0")}`;
}
