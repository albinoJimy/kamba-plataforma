/**
 * O aviso ao dono sobre a decisão da fila de revisão: os modelos de SMS e de
 * e-mail, e o adaptador da porta `AvisoAoDono` (KAM-196, critério 5).
 *
 * «Modelos de SMS (ASCII, ≤ 160 caracteres) e de e-mail para `aprovado`,
 * `rejeitado`, `pedir_info` e `recurso_decidido`, com o texto fixo do motivo
 * público; a via é o telefone registado ou o e-mail, **nunca** o número da loja.»
 *
 * ## Nenhum texto livre chega ao dono
 *
 * Um aviso é um par (aviso, motivo), e os dois são códigos de listas fechadas. O
 * SMS é um modelo do registo do `../sms/modelos.ts` (que só aceita um nome de
 * modelo, nunca um corpo), e o e-mail é um dos cinco textos deste ficheiro. O
 * motivo entra pelo texto fixo da fila (`TEXTO_DO_MOTIVO_PUBLICO`). Não há
 * parâmetro por onde entre um nome, um número, uma nota do revisor ou o motivo
 * interno.
 *
 * ## O recurso decidido não diz «aprovado»
 *
 * O serviço manda `recurso_decidido` sem motivo quando o recurso é aceite, mesmo
 * que o onboarding continue bloqueado por outro caso pendente (`#efeitos`). Por
 * isso o texto do recurso aceite diz que o **recurso** foi aceite e manda ver o
 * estado, e não que o pedido foi aprovado: seria mentir ao dono. O recurso
 * recusado leva só a **causa** do motivo (`CAUSA_DO_MOTIVO_PUBLICO`), porque o
 * texto inteiro do `nao_foi_possivel_validar` oferece um recurso que já não
 * existe.
 *
 * ## A via, e o número que nunca é usado
 *
 * O SMS vai para o telefone **registado no onboarding**, que a fila já lê pela
 * porta `DadosPessoais` (`telefone`), cunhado como `Destino` com o *pepper* do
 * agregador (KAM-116). Este adaptador não recebe o canal nem o número da loja:
 * não há dependência por onde ele chegue. O e-mail vai pela porta
 * `CorreioDoDono`, que resolve o endereço registado do lado dela; a fila não o vê.
 *
 * Um aviso sem destino **levanta** (`AvisoSemDestinoError`): o efeito fica por
 * aplicar, e o *job* da fila volta a tentá-lo (`./ciclo.ts`), em vez de o caso
 * ficar decidido e o dono sem saber.
 */

import { randomUUID } from "node:crypto";

import type { SmsProvider } from "../sms/contrato.ts";
import { cunharDestino } from "../sms/destino.ts";
import type { NomeDeModelo, Parametros } from "../sms/modelos.ts";
import {
  AVISOS,
  CAUSA_DO_MOTIVO_PUBLICO,
  MOTIVOS_PUBLICOS,
  TEXTO_DO_MOTIVO_PUBLICO,
  type Aviso,
  type AvisoAoDono,
  type DadosPessoais,
  type MotivoPublico,
  type ViaDoAviso,
} from "./contrato.ts";

/** Um e-mail do aviso. Texto simples: o motivo é o texto fixo da fila. */
export interface EmailDoAviso {
  readonly assunto: string;
  readonly corpo: string;
}

/** O que sai para o dono, nas duas vias. */
export interface MensagemDoAviso {
  readonly sms: { readonly modelo: NomeDeModelo; readonly parametros: Parametros };
  readonly email: EmailDoAviso;
}

const ASSINATURA = "\n\nEquipa KAMBÁ\n\nEsta mensagem é automática. Não responda a este endereço.";

/**
 * A mensagem de um aviso. Recusa a combinação que o serviço nunca manda — um
 * `rejeitado` ou um `pedir_info` sem motivo —, em vez de inventar um.
 */
export function mensagemDoAviso(aviso: Aviso, motivo: MotivoPublico | null): MensagemDoAviso {
  if (!AVISOS.includes(aviso)) throw new RangeError("aviso fora da lista");
  if (motivo !== null && !MOTIVOS_PUBLICOS.includes(motivo)) throw new RangeError("motivo publico fora da lista");
  switch (aviso) {
    case "aprovado":
      return {
        sms: { modelo: "revisao_aprovado", parametros: {} },
        email: {
          assunto: "KAMBÁ: o seu pedido de adesão foi aprovado",
          corpo:
            "O seu pedido de adesão à KAMBÁ foi aprovado.\n\n" +
            "Volte à página de registo para continuar a configurar a loja." +
            ASSINATURA,
        },
      };
    case "rejeitado": {
      const m = exigirMotivo(aviso, motivo);
      return {
        sms: { modelo: "revisao_rejeitado", parametros: { motivo: m } },
        email: {
          assunto: "KAMBÁ: o seu pedido de adesão não foi aprovado",
          corpo: `O seu pedido de adesão à KAMBÁ não foi aprovado.\n\n${TEXTO_DO_MOTIVO_PUBLICO[m]}${ASSINATURA}`,
        },
      };
    }
    case "pedir_info": {
      const m = exigirMotivo(aviso, motivo);
      return {
        sms: { modelo: "revisao_pedir_info", parametros: { motivo: m } },
        email: {
          assunto: "KAMBÁ: precisamos de mais informação",
          corpo:
            `${TEXTO_DO_MOTIVO_PUBLICO[m]}\n\n` +
            "Volte à página de registo para enviar o que falta." +
            ASSINATURA,
        },
      };
    }
    case "recurso_decidido":
      if (motivo === null) {
        return {
          sms: { modelo: "revisao_recurso_aprovado", parametros: {} },
          email: {
            assunto: "KAMBÁ: o seu recurso foi aceite",
            corpo:
              "O seu recurso foi analisado e aceite.\n\n" +
              "Volte à página de registo para ver o estado do pedido." +
              ASSINATURA,
          },
        };
      }
      return {
        sms: { modelo: "revisao_recurso_mantido", parametros: { causa: motivo } },
        email: {
          assunto: "KAMBÁ: o seu recurso foi analisado",
          corpo:
            "O seu recurso foi analisado e a decisão mantém-se. Esta decisão é final.\n\n" +
            CAUSA_DO_MOTIVO_PUBLICO[motivo] +
            ASSINATURA,
        },
      };
  }
}

function exigirMotivo(aviso: Aviso, motivo: MotivoPublico | null): MotivoPublico {
  if (motivo === null) throw new RangeError(`o aviso ${aviso} leva motivo`);
  return motivo;
}

/**
 * A via de e-mail. **O endereço resolve-o quem implementa**, a partir do
 * onboarding: a fila nunca o lê, e por isso também não o pode trocar.
 */
export interface CorreioDoDono {
  enviar(pedido: {
    readonly onboardingId: string;
    readonly assunto: string;
    readonly corpo: string;
    readonly chave: string;
  }): Promise<void>;
}

/** O aviso não tem para onde ir. O efeito fica por aplicar, e o *job* volta a tentá-lo. */
export class AvisoSemDestinoError extends Error {
  override readonly name = "AvisoSemDestinoError";
  readonly via: ViaDoAviso;

  constructor(via: ViaDoAviso) {
    super(`aviso ao dono sem destino pela via ${via}`);
    this.via = via;
  }
}

export interface OpcoesDoAvisoAoDono {
  /** A porta do KAM-116. Só se usa o `send`. */
  readonly sms: Pick<SmsProvider, "send">;
  /** A mesma porta `DadosPessoais` da fila: é dela que vem o telefone **registado**. */
  readonly dados: DadosPessoais;
  /** O *pepper* do destino do SMS (`REF_PEPPER` do `../sms/refs.ts`). */
  readonly pepperDoDestino: Uint8Array;
  /** A via de e-mail. Sem ela, um aviso por e-mail levanta. */
  readonly correio?: CorreioDoDono | null;
  /** A chave de idempotência de um envio. Por omissão, uma por chamada. */
  readonly chave?: () => string;
}

/**
 * O adaptador da porta `AvisoAoDono`.
 *
 * A chave de idempotência é **uma por chamada**: o `Envios` do SMS reusa-a nas
 * suas próprias repetições, e um segundo aviso legítimo — um segundo
 * `pedir_info` no mesmo onboarding — não pode ser engolido como repetido. O
 * `reaplicarEfeitos` só reenvia quando um efeito falhou, e o aviso é o último
 * efeito: se ele tivesse saído, não havia o que reaplicar.
 */
export class AvisoAoDonoPorVia implements AvisoAoDono {
  readonly #o: OpcoesDoAvisoAoDono;

  constructor(opcoes: OpcoesDoAvisoAoDono) {
    if (!(opcoes.pepperDoDestino instanceof Uint8Array)) throw new TypeError("pepper do destino em falta");
    this.#o = opcoes;
  }

  async avisar(pedido: {
    readonly onboardingId: string;
    readonly via: ViaDoAviso;
    readonly aviso: Aviso;
    readonly motivoPublico: MotivoPublico | null;
  }): Promise<void> {
    const m = mensagemDoAviso(pedido.aviso, pedido.motivoPublico);
    const chave = this.#o.chave?.() ?? `revisao:${randomUUID()}`;
    if (pedido.via === "sms") {
      const telefone = await this.#o.dados.ler(pedido.onboardingId, "telefone");
      if (telefone === null) throw new AvisoSemDestinoError("sms");
      const destino = cunharDestino(telefone, this.#o.pepperDoDestino);
      await this.#o.sms.send(destino, m.sms.modelo, m.sms.parametros, chave);
      return;
    }
    if (pedido.via === "email") {
      if (this.#o.correio === undefined || this.#o.correio === null) throw new AvisoSemDestinoError("email");
      await this.#o.correio.enviar({ onboardingId: pedido.onboardingId, ...m.email, chave });
      return;
    }
    throw new RangeError("via do aviso fora da lista");
  }
}
