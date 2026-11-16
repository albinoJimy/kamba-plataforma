/**
 * Confiança gradual — o tecto no caminho de cobrança (KAM-096, critério 6).
 *
 * `assertWithinTrustCeiling(tenantId, amountMinor)` é o que um
 * `PaymentProvider` chama antes de criar uma cobrança: o `ManualProvider`
 * chama-o (`../pagamentos/manual.ts`), e qualquer adaptador futuro recebe a
 * mesma porta. **Não é a barreira**: a barreira é o *trigger*
 * `payment_charges_dentro_do_tecto`, que recusa a cobrança na mesma instrução
 * que a escreve. Isto é a recusa **antes** de se falar com o facilitador, e a
 * mensagem fixa que o agente mostra.
 *
 * O tecto efectivo é o gravado em `trust_level`, e o do nível 0 se uma sanção
 * `limitacao` ou acima estiver em vigor (o `tectoNoNivelZero` do KAM-097) —
 * mesmo antes de o recálculo gravar a descida. Nas cobranças manuais o
 * `ManualProvider` junta-lhe o `manual_max_minor`: o efectivo é o menor dos
 * dois (`tectoEfectivoManual`).
 */

import { CONFIGURACAO_DA_CONFIANCA, type ConfiguracaoDaConfianca, validarConfiguracao } from "./config.ts";
import type { LeitorDeRestricoes } from "./niveis.ts";

/**
 * O que o agente diz quando a cobrança passa o tecto. **Fixa, e sem números**:
 * o tecto e o nível são do T&S, e um número na mensagem dizia a quem ensaia
 * valores onde está a fronteira.
 */
export const MENSAGEM_ACIMA_DO_TECTO =
  "Este pedido ainda nao pode ser pago por este meio. Proponha outro meio de pagamento " +
  "ou aguarde a confirmacao pelo facilitador.";

export const MOTIVOS_FORA_DO_TECTO = ["sem_nivel", "acima_do_tecto"] as const;
export type MotivoForaDoTecto = (typeof MOTIVOS_FORA_DO_TECTO)[number];

export class ForaDoTectoDeConfiancaError extends Error {
  override readonly name = "ForaDoTectoDeConfiancaError";
  readonly motivo: MotivoForaDoTecto;
  constructor(motivo: MotivoForaDoTecto) {
    super(MENSAGEM_ACIMA_DO_TECTO);
    this.motivo = motivo;
  }
}

/** De onde vem o tecto gravado. Lê `trust_level.tecto_pedido_minor` do próprio tenant. */
export interface LeitorDoTecto {
  tectoDoTenant(tenantId: string): Promise<bigint | null>;
}

/** O que um `PaymentProvider` recebe. */
export interface GuardaDoTecto {
  assertWithinTrustCeiling(tenantId: string, amountMinor: bigint): Promise<void>;
}

/** `min(tecto_pedido_minor, manual_max_minor)`; `null` em qualquer dos dois recusa. */
export function tectoEfectivoManual(tectoPedidoMinor: bigint | null, manualMaxMinor: bigint | null): bigint | null {
  if (tectoPedidoMinor === null || manualMaxMinor === null) return null;
  return tectoPedidoMinor < manualMaxMinor ? tectoPedidoMinor : manualMaxMinor;
}

export class GuardaDeConfianca implements GuardaDoTecto {
  readonly #tecto: LeitorDoTecto;
  readonly #restricoes: LeitorDeRestricoes;
  readonly #c: ConfiguracaoDaConfianca;

  constructor(d: {
    readonly tecto: LeitorDoTecto;
    readonly restricoes: LeitorDeRestricoes;
    readonly configuracao?: ConfiguracaoDaConfianca;
  }) {
    this.#tecto = d.tecto;
    this.#restricoes = d.restricoes;
    this.#c = validarConfiguracao(d.configuracao ?? CONFIGURACAO_DA_CONFIANCA);
  }

  /** O tecto que vale agora para o tenant, ou `null` sem nível. */
  async tectoEfectivo(tenantId: string): Promise<bigint | null> {
    const gravado = await this.#tecto.tectoDoTenant(tenantId);
    if (gravado === null) return null;
    const { tectoNoNivelZero } = await this.#restricoes.restricoes(tenantId);
    const zero = this.#c.niveis[0].tectoPedidoMinor.valor;
    return tectoNoNivelZero && zero < gravado ? zero : gravado;
  }

  /** Recusa com `ForaDoTectoDeConfiancaError`; **no limite exacto aceita**. */
  async assertWithinTrustCeiling(tenantId: string, amountMinor: bigint): Promise<void> {
    if (typeof amountMinor !== "bigint" || amountMinor <= 0n) {
      throw new RangeError("o montante e um bigint positivo em unidade menor");
    }
    const tecto = await this.tectoEfectivo(tenantId);
    if (tecto === null) throw new ForaDoTectoDeConfiancaError("sem_nivel");
    if (amountMinor > tecto) throw new ForaDoTectoDeConfiancaError("acima_do_tecto");
  }
}
