/**
 * O banco de ensaio do `FakeProvider`, para o harness de conformidade.
 *
 * Nao e um ficheiro de teste: e o duplo que o `pagamentos.conformidade.test.ts`
 * conduz. Fica separado pela mesma razao que o `coexistencia.base_falsa.ts` do
 * KAM-017 — e o que o harness **recebe**, e lê melhor longe das asserções.
 *
 * O KAM-054 e o KAM-056 escrevem o seu, com a assinatura e os modos de falha do
 * facilitador deles; o harness nao muda.
 */

import type {
  BancoDeEnsaio,
  CreateChargeReq,
  FalhaProgramada,
  PaymentProvider,
  ProviderRef,
  RawHttpCallback,
  VerifiedEvent,
} from "../src/pagamentos/index.ts";
import {
  AuthError,
  CABECALHO_DA_ASSINATURA,
  FakeProvider,
  ProviderError,
  type AccountSecrets,
  type Minor,
} from "../src/pagamentos/index.ts";

/**
 * As duas chaves da janela de rotacao (§3.3).
 *
 * Sao literais de ensaio e **nao segredos**: o `ci/secrets-allow.yaml` permite a
 * classe nos ficheiros de teste, e o varrimento do criterio 7 corre sobre as
 * colunas e as fixtures da base, nao sobre isto. Mesmo assim nao tem forma de
 * chave de fornecedor nenhum, para nao disparar o gate 9 por semelhanca.
 */
const CHAVES: Readonly<Record<string, Buffer>> = {
  "fake_api_key": Buffer.from("chave-de-ensaio-actual-kam-052", "utf8"),
  "fake_api_key/anterior": Buffer.from("chave-de-ensaio-anterior-kam-052", "utf8"),
  // **A chave da segunda conta**, que e o que torna o caso 1 capaz de medir
  // autenticidade. Ver o cabecalho de `BancoDeEnsaio`: «uma chave por conta de
  // PME e nunca partilhada» (§3.3).
  "fake_api_key_b": Buffer.from("chave-de-ensaio-da-conta-b-kam-052", "utf8"),
};

export const CONTA_DE_ENSAIO: AccountSecrets = {
  accountId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  credenciaisRef: "fake_api_key",
  credenciaisRefAnterior: "fake_api_key/anterior",
};

/** A segunda conta, de outra PME. Chave diferente e sem janela de rotacao. */
export const CONTA_ALTERNATIVA: AccountSecrets = {
  accountId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  credenciaisRef: "fake_api_key_b",
};

const VALID_UNTIL = "2026-10-30T12:00:00.000Z";

/** Opcoes para enfraquecer o duplo, e assim provar que o harness mede. */
export type Fraquezas = {
  /** Aceita qualquer assinatura: mata o caso 1. */
  readonly semVerificarAssinatura?: boolean;
  /** Converte o valor por `number`: mata o caso 2. */
  readonly valorPorFloat?: boolean;
  /**
   * Deriva o `provider_event_id` de um contador **por entrega**: mata o caso 4.
   *
   * A primeira versao desta fraqueza mudava o identificador no **corpo**, no
   * momento de o construir — e nao matava o caso nenhum, porque o caso 4 entrega
   * dez vezes o **mesmo** callback e o corpo so se constroi uma. O defeito que
   * importa esta no adaptador: inventar a chave de deduplicacao a cada entrega.
   */
  readonly eventIdPorContador?: boolean;
  /** Ignora a chave anterior: mata o caso 8. */
  readonly semJanelaDeRotacao?: boolean;
  /** Devolve `UNAVAILABLE` em vez de `RATE_LIMIT`: mata o caso 9. */
  readonly rateLimitGenerico?: boolean;
  /**
   * Ignora o `acct` e usa uma chave global: mata o caso 1 pela via cruzada.
   *
   * E o segundo adaptador defeituoso que a revisao adversarial construiu, e
   * **nenhuma mutacao de assinatura o apanharia**: ele verifica HMAC a serio. O
   * que ele nao faz e ligar a chave a conta, pelo que aceita o callback da PME A
   * entregue no `webhook_token` da PME B.
   */
  readonly chaveGlobal?: boolean;
  /** Descarta um callback de referencia desconhecida: mata o caso 3. */
  readonly descartaOrfao?: boolean;
  /** Usa o instante da chegada e nao o do evento: mata os casos 5 e 6. */
  readonly instanteDaChegada?: boolean;
  /** Nao memoriza o `chargeId`: mata o caso 7 pelo contador do facilitador. */
  readonly criaSempre?: boolean;
  /** O `status()` diz sempre `pendente`: mata o caso 10. */
  readonly statusDiscordante?: boolean;
};

export function bancoDeEnsaio(fraquezas: Fraquezas = {}): BancoDeEnsaio {
  const provider = new FakeProvider({
    resolver: (ref) => {
      const chave = CHAVES[ref];
      if (chave === undefined) throw new Error(`chave de ensaio desconhecida: ${ref}`);
      return chave;
    },
  });
  const conta: AccountSecrets = fraquezas.semJanelaDeRotacao
    ? { accountId: CONTA_DE_ENSAIO.accountId, credenciaisRef: CONTA_DE_ENSAIO.credenciaisRef }
    : CONTA_DE_ENSAIO;

  const banco: BancoDeEnsaio = {
    provider: _talvezEnfraquecido(provider, fraquezas),
    conta,
    contaAlternativa: CONTA_ALTERNATIVA,

    pedido(): CreateChargeReq {
      return {
        chargeId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        tenantId: "11111111-1111-4111-8111-111111111111",
        accountId: CONTA_DE_ENSAIO.accountId,
        numeroPublico: "P-0001",
        // 1024,09 Kz: o montante em que o caminho por `float` perde um centimo,
        // e portanto o valor contra o qual o caso 2 mede a divergencia de ±1.
        amount: 102_409n,
        currency: "AOA",
        metodo: "referencia",
        validUntil: VALID_UNTIL,
        customFields: { charge: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" },
      };
    },

    async callback(evento, chave = "actual", paraConta): Promise<RawHttpCallback> {
      const destino = paraConta ?? conta;
      const ref =
        chave === "anterior"
          ? (destino.credenciaisRefAnterior ?? destino.credenciaisRef)
          : destino.credenciaisRef;
      return provider.corpoAssinado(
        {
          provider_event_id: evento.providerEventId,
          entity_id: provider.entidade,
          reference_id: evento.referencia ?? "000000001",
          amount: provider.decimal2(evento.valor),
          payment_datetime: evento.ocorridoEm,
        },
        ref,
      );
    },

    criacoesNoFacilitador(): number {
      return provider.criacoes;
    },

    adulterar(callback: RawHttpCallback): RawHttpCallback {
      const assinatura = callback.cabecalhos[CABECALHO_DA_ASSINATURA] ?? "";
      // Vira o ultimo digito hexadecimal: mantem o comprimento, muda o valor.
      const ultimo = assinatura.slice(-1);
      const trocado = ultimo === "0" ? "1" : "0";
      return {
        corpo: callback.corpo,
        cabecalhos: {
          ...callback.cabecalhos,
          [CABECALHO_DA_ASSINATURA]: `${assinatura.slice(0, -1)}${trocado}`,
        },
      };
    },

    programar(falha: FalhaProgramada): void {
      provider.programar(falha);
    },

    refDe(evento: VerifiedEvent): ProviderRef {
      return { providerId: provider.id, ...(evento.referencia === undefined ? {} : { referencia: evento.referencia }) };
    },

    refDesconhecida(): ProviderRef {
      return { providerId: provider.id, referencia: "nao-existe" };
    },
  };
  return banco;
}

/**
 * Embrulha o `FakeProvider` com as fraquezas pedidas.
 *
 * E isto que torna o canario possivel: tirar uma barreira ao duplo e exigir que
 * o caso correspondente fique vermelho. Sem este passo, dez casos verdes podiam
 * estar verdes por nao medirem nada — e o passo de canario dos gates 3b, 9 e 11
 * existe pela mesma razao.
 *
 * **E delega por metodos ligados e nao por `Object.create`**, o que nao e
 * estetica: a primeira versao fazia `Object.create(provider)` e os **dez** casos
 * ficavam vermelhos de uma vez. A razao e que o `FakeProvider` guarda o estado
 * em campos privados (`#resolver`, `#cobrancas`, `#noFacilitador`), e um objecto cuja
 * cadeia de prototipos aponta para a instancia **nao tem** esses campos: o
 * primeiro metodo que os toque levanta `TypeError: Cannot read private member`.
 * Um delegador que parece funcionar e nao funciona e pior do que nenhum, e foi
 * o executor de testes que o disse — nao a leitura.
 */
function _talvezEnfraquecido(provider: FakeProvider, fraquezas: Fraquezas): PaymentProvider {
  const base: PaymentProvider = {
    id: provider.id,
    capabilities: provider.capabilities,
    createCharge: (req) => provider.createCharge(req),
    status: (ref) => provider.status(ref),
    refund: (req) => provider.refund(req),
    payout: (req) => provider.payout(req),
    verifyCallback: (raw, acct) => provider.verifyCallback(raw, acct),
    listUnacknowledged: (acct, cursor) => provider.listUnacknowledged(acct, cursor),
    acknowledge: (acct, id) => provider.acknowledge(acct, id),
    cancelCharge: (ref) => provider.cancelCharge(ref),
  };
  if (Object.keys(fraquezas).length === 0) return base;

  const enfraquecido: PaymentProvider = { ...base };
  let entregas = 0;
  const mexeNoCallback =
    fraquezas.semVerificarAssinatura === true ||
    fraquezas.valorPorFloat === true ||
    fraquezas.eventIdPorContador === true ||
    fraquezas.chaveGlobal === true ||
    fraquezas.descartaOrfao === true ||
    fraquezas.instanteDaChegada === true;
  if (mexeNoCallback) {
    enfraquecido.verifyCallback = async (raw, acct) => {
      let eventos: readonly VerifiedEvent[];
      if (fraquezas.semVerificarAssinatura === true) {
        // Aceita **qualquer** assinatura: le o corpo e devolve o evento.
        const corpo = JSON.parse(new TextDecoder().decode(raw.corpo)) as Record<string, string>;
        eventos = [
          {
            providerEventId: corpo["provider_event_id"] ?? "",
            referencia: corpo["reference_id"] ?? "",
            valor: BigInt((corpo["amount"] ?? "0").replace(".", "")),
            currency: "AOA" as const,
            authnMethod: "hmac" as const,
            ocorridoEm: corpo["payment_datetime"] ?? "",
          },
        ];
      } else if (fraquezas.chaveGlobal === true) {
        // **Verifica HMAC a serio e ignora a conta.** Tenta as tres chaves de
        // ensaio como se fossem um conjunto global. Nenhuma mutacao de
        // assinatura apanha isto — o que o apanha e o callback cruzado.
        let aceito: readonly VerifiedEvent[] | null = null;
        for (const ref of ["fake_api_key", "fake_api_key/anterior", "fake_api_key_b"]) {
          try {
            aceito = await provider.verifyCallback(raw, {
              accountId: acct.accountId,
              credenciaisRef: ref,
            });
            break;
          } catch {
            continue;
          }
        }
        if (aceito === null) throw new AuthError("nenhuma das chaves globais verifica");
        eventos = aceito;
      } else {
        eventos = await provider.verifyCallback(raw, acct);
      }
      if (fraquezas.valorPorFloat === true) {
        eventos = eventos.map((e) => ({ ...e, valor: _porFloat(provider.decimal2(e.valor)) }));
      }
      if (fraquezas.eventIdPorContador === true) {
        // **Por entrega e nao pelo corpo**, que e o defeito que importa: um
        // adaptador que invente a chave de deduplicacao a cada entrega deixa a
        // unicidade da base sem nada por onde morder, e as dez entregas do
        // mesmo callback confirmam o pagamento dez vezes.
        eventos = eventos.map((e) => {
          entregas += 1;
          return { ...e, providerEventId: `entrega-${entregas}` };
        });
      }
      if (fraquezas.descartaOrfao === true) {
        // Descarta em silencio o que nao reconhece. O caso 3 existe porque isto
        // **perde o pagamento de um cliente**: um orfao e para registar e
        // investigar (§8), nao para deitar fora.
        eventos = eventos.filter((e) => e.referencia === "000000001");
      }
      if (fraquezas.instanteDaChegada === true) {
        // Usa a hora da chegada e nao a do evento. Mata o caso 6 (ninguem pode
        // comparar com o `valid_until`) e o caso 5 (a ordem passa a depender de
        // quem chegou primeiro).
        eventos = eventos.map((e) => ({ ...e, ocorridoEm: new Date().toISOString() }));
      }
      return eventos;
    };
  }
  if (fraquezas.rateLimitGenerico === true || fraquezas.criaSempre === true) {
    enfraquecido.createCharge = async (req) => {
      try {
        // `criaSempre`: sem memoria do `chargeId`, cada chamada emite uma
        // cobranca nova no facilitador. Dois `chargeId` diferentes por chamada
        // fazem o `FakeProvider` contar cada uma.
        const pedido = fraquezas.criaSempre === true
          ? { ...req, chargeId: `${req.chargeId}-${Math.random()}` }
          : req;
        return await provider.createCharge(pedido);
      } catch (erro) {
        if (
          fraquezas.rateLimitGenerico === true &&
          (erro as { codigo?: string }).codigo === "RATE_LIMIT"
        ) {
          throw new ProviderError("UNAVAILABLE", "indisponivel (fraqueza do ensaio)");
        }
        throw erro;
      }
    };
  }
  if (fraquezas.statusDiscordante === true) {
    // O `status()` nunca concorda com o callback. Mata o caso 10 — que existe
    // precisamente porque «e a discordancia que denuncia um callback forjado
    // que passou a assinatura».
    enfraquecido.status = async () => ({ estado: "pendente" });
  }
  return enfraquecido;
}

/**
 * A travessia **errada**, de propria decisao: e o que a fraqueza do caso 2 imita.
 *
 * E o unico `parseFloat` sobre dinheiro em todo o ticket, e esta aqui e nao em
 * `src/pagamentos/` por uma razao que vale dizer: o `tools/money_lint` varre
 * `src/pagamentos/` e **recusaria esta linha**, que e o que o criterio 1 pede.
 * O canario tem de poder escrever o defeito para provar que o harness o apanha,
 * e por isso vive do lado dos testes — a mesma separacao que as *fixtures*
 * negativas do `canon_lint` tem face as superficies que ele varre.
 */
function _porFloat(texto: string): Minor {
  return BigInt(Math.trunc(Number.parseFloat(texto) * 100));
}
