/**
 * O aviso ao dono de um passo da escada ou de um recurso (KAM-097, critério 9).
 *
 * «O dono é notificado por SMS/e-mail e painel com `motivo_publico`; nunca se
 * revela a heurística.» O SMS é um dos seis modelos `ts_*` de
 * `../sms/modelos.ts`, **sem parâmetros**: o corpo é o texto fixo do motivo
 * público, e não há campo por onde entre o motivo interno, a regra ou um sinal.
 * O painel lê os códigos em vigor pelo `ServicoDeTrust.avisosDoPainel`.
 *
 * A via é o telefone **registado no onboarding** (o mesmo da fila de revisão,
 * `../revisao/avisos.ts`), nunca o número da loja: uma loja suspensa nem tem
 * por onde responder, e o número da loja é do público.
 */

import { randomUUID } from "node:crypto";

import type { DadosPessoais, OnboardingsDaRevisao } from "../revisao/contrato.ts";
import type { SmsProvider } from "../sms/contrato.ts";
import { cunharDestino } from "../sms/destino.ts";
import type { NomeDeModelo } from "../sms/modelos.ts";
import type { AvisoDeSancao, MotivoPublicoDaSancao } from "./contrato.ts";

/** O modelo de SMS de cada motivo público. */
export const MODELO_DO_MOTIVO: Readonly<Record<MotivoPublicoDaSancao, NomeDeModelo>> = {
  conduta_em_analise: "ts_aviso",
  actividade_limitada: "ts_limitacao",
  loja_suspensa: "ts_suspensao",
  loja_encerrada: "ts_encerramento",
  recurso_aceite: "ts_recurso_aceite",
  recurso_mantido: "ts_recurso_mantido",
};

/** O telefone do dono de um tenant, em claro, para cunhar o destino. `null` se não há. */
export interface TelefoneDoDono {
  ler(tenantId: string): Promise<string | null>;
}

/** O telefone pelo onboarding do tenant: as duas portas que a fila já tem. */
export function telefoneDoDonoPelaFila(onboardings: Pick<OnboardingsDaRevisao, "porTenant">, dados: DadosPessoais): TelefoneDoDono {
  return {
    async ler(tenantId) {
      const o = await onboardings.porTenant(tenantId);
      return o === null ? null : dados.ler(o.id, "telefone");
    },
  };
}

/** Um aviso sem telefone levanta: o efeito fica por aplicar e o ciclo da fila volta a tentá-lo. */
export class AvisoDeSancaoSemDestinoError extends Error {
  override readonly name = "AvisoDeSancaoSemDestinoError";
  constructor() {
    super("aviso de sancao sem telefone do dono");
  }
}

export class AvisoDeSancaoPorSms implements AvisoDeSancao {
  readonly #sms: Pick<SmsProvider, "send">;
  readonly #telefone: TelefoneDoDono;
  readonly #pepper: Uint8Array;

  constructor(o: { readonly sms: Pick<SmsProvider, "send">; readonly telefone: TelefoneDoDono; readonly pepperDoDestino: Uint8Array }) {
    if (!(o.pepperDoDestino instanceof Uint8Array)) throw new TypeError("pepper do destino em falta");
    this.#sms = o.sms;
    this.#telefone = o.telefone;
    this.#pepper = o.pepperDoDestino;
  }

  async avisar(pedido: { readonly tenantId: string; readonly motivo: MotivoPublicoDaSancao }): Promise<void> {
    const modelo = MODELO_DO_MOTIVO[pedido.motivo];
    if (modelo === undefined) throw new RangeError("motivo publico da sancao fora da lista");
    const telefone = await this.#telefone.ler(pedido.tenantId);
    if (telefone === null) throw new AvisoDeSancaoSemDestinoError();
    await this.#sms.send(cunharDestino(telefone, this.#pepper), modelo, {}, `trust:${randomUUID()}`);
  }
}
