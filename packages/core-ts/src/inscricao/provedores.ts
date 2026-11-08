/**
 * Os dois `OtpProvider`: o SMS local, que é o do Piloto, e o WhatsApp, que está
 * vedado (KAM-086, módulo `otp`).
 *
 * «`otp` (`OtpProvider`: `sms_local` activo; `whatsapp` **desactivado** até
 * D10).»
 *
 * ## Este ficheiro é a ligação, e é a razão de a porta de SMS existir antes
 *
 * O KAM-116 entregou a `SmsProvider` e escreveu, no cabeçalho do
 * `../sms/contrato.ts`, que «o KAM-086 liga esta porta ao `OtpProvider`
 * (`sms_local`)». É isto. Não há aqui HTTP, não há agregador e não há escolha de
 * fornecedor — essa é do fundador e não está feita.
 *
 * ## O `whatsapp` existe e recusa, e isso não é cerimónia
 *
 * Um canal que não existisse deixava o dia da **D10** a quem reinventasse o
 * nome, e um canal que existisse e funcionasse era uma decisão aberta fechada
 * por omissão. Um canal que existe e **levanta** é a terceira coisa: o nome
 * está fixado, a fronteira está marcada, e ligar o WhatsApp é apagar uma linha
 * com o ticket da D10 no *commit*. É o desenho que o `../sms/fornecedor.ts` usa
 * para o *gate* de `prod`.
 *
 * ## Os dois HMAC do telefone, e porque não são redundância
 *
 * O `Telefone` do `./identificadores.ts` leva o HMAC da
 * `pepper_onboarding_ident`: é o que identifica **a pessoa** dentro do
 * onboarding, e é o que entra no `phone_hmac` de um caso. O `Destino` do
 * `../sms/destino.ts` leva o HMAC da `pepper_sms_destino`: é o que identifica **o
 * endereço** dentro do agregador, e é o que entra no relatório de entrega do
 * KAM-116. Chaves diferentes de propósito — o argumento está escrito no
 * cabeçalho do `../sms/destino.ts` —, e este ficheiro é o único sítio onde os
 * dois espaços se tocam.
 *
 * **É também o único sítio legítimo deste módulo onde o número volta a texto**:
 * o `revelar()` abaixo entrega-o ao `cunharDestino`, que o valida outra vez e o
 * guarda opaco. Um segundo `revelar()` neste módulo é um achado de revisão.
 */

import type { CodigoOtp } from "../sms/codigo.ts";
import type { SmsProvider } from "../sms/contrato.ts";
import { cunharDestino } from "../sms/destino.ts";

import { CanalDesactivadoError, type CanalDeOtp, type OtpProvider } from "./contrato.ts";
import type { Telefone } from "./identificadores.ts";

/** Opções do provedor por SMS local. */
export interface OpcoesDeSmsLocal {
  /** A porta do KAM-116. Em CI e `staging` é o `FakeSmsProvider`. */
  readonly sms: SmsProvider;
  /** A chave **actual** do anel da `pepper_sms_destino`. **Não** a da inscrição. */
  readonly pepperDoDestino: Uint8Array;
}

/** O OTP por SMS de agregador local. É o canal do Piloto. */
export class OtpPorSmsLocal implements OtpProvider {
  readonly canal: CanalDeOtp = "sms_local";
  readonly #sms: SmsProvider;
  readonly #pepper: Uint8Array;

  constructor(opcoes: OpcoesDeSmsLocal) {
    this.#sms = opcoes.sms;
    this.#pepper = opcoes.pepperDoDestino;
  }

  async enviar(
    telefone: Telefone,
    codigo: CodigoOtp,
    validadeMin: number,
    chave: string,
  ): Promise<void> {
    // O único `revelar()` deste módulo. Ver a nota do ficheiro.
    const destino = cunharDestino(telefone.revelar(), this.#pepper);
    // O nome do modelo é literal e não configurável: o registo de
    // `../sms/modelos.ts` é fechado, e um modelo em configuração era texto de
    // SMS escolhido fora de um diff.
    await this.#sms.send(destino, "otp_posse_telefone", { codigo, validade_min: validadeMin }, chave);
  }
}

/**
 * O OTP por WhatsApp. **Levanta sempre.**
 *
 * Ver a nota do ficheiro: está aqui para que o nome do canal esteja fixado e a
 * fronteira esteja marcada. Ligá-lo depende da **D10** (número operacional
 * próprio) e do **KAM-101** (perguntas à Meta), e nenhum dos dois está decidido.
 */
export class OtpPorWhatsApp implements OtpProvider {
  readonly canal: CanalDeOtp = "whatsapp";

  async enviar(): Promise<void> {
    throw new CanalDesactivadoError("whatsapp");
  }
}
