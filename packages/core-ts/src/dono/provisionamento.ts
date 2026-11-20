/**
 * O contacto `dono` nasce do `tenant.provisioned` (KAM-118, critério 3).
 *
 * «O contacto `dono` é criado de forma idempotente ao consumir
 * `tenant.provisioned` (reentrega 3× → 1 contacto); sem o evento o remetente é
 * `cliente`.»
 *
 * ## A idempotência é da base, e não deste efeito
 *
 * O efeito resolve o contacto do telefone verificado (o `resolveContact` do
 * KAM-008, que é idempotente por `phone_hmac`) e chama
 * `platform.definir_dono(contacto, 'provisionamento')`. A função devolve sem
 * mudar nada quando o contacto já é o dono, e **recusa** quando o tenant já tem
 * outro dono: uma reentrega da saga não troca o dono, só o OTP o faz
 * (critério 2). Três entregas dão um contacto e um dono, porque as duas portas
 * o garantem e este código não guarda estado nenhum entre entregas.
 *
 * ## Ligado pelo KAM-215
 *
 * O KAM-118 entregou o efeito sem nada que o fizesse correr. O KAM-215 liga as
 * três peças em falta:
 *
 * * **o emissor** — o varrimento do processo de lote do onboarding
 *   (`../provisioning/avanco.ts`) avança o caso até `es_concluido` pela
 *   `platform.advance_case` (revisão `0058`), como `kamba_batch`, e é a função
 *   que emite o `tenant.provisioned`;
 * * **o telefone do caso** — o `phone_enc` tem cifra e KEK própria
 *   (`kek_telefone_do_caso`, decisão do fundador de 2026-11-20), e o decifrador
 *   é o `lerTelefoneDoCaso` de `../inscricao/telefone_do_caso.ts`;
 * * **o consumidor** — a subscrição em `platform.evt_subscricoes` (revisão de
 *   dados) e o `registry/dono_provisionamento.yaml`, e o processo
 *   `services/onboarding-web/src/provisionamento.ts`, com a ligação `kamba_app`
 *   para o `consumir` e a `kamba_identity` para o contacto e a porta.
 *
 * **O telefone lê-se pela ligação do consumo**, e não por uma ligação própria:
 * é `kamba_app` com o `app.tenant_id` do **envelope** já posto pelo `consumir`,
 * pelo que um `onboarding_id` de outro tenant no *payload* não se encontra (zero
 * linhas, `null`, DLQ) em vez de dar o telefone do dono de outro tenant.
 */

import type { Efeito } from "../eventos/consumo.ts";
import type { LigacaoDeLeitura } from "../inscricao/telefone_do_caso.ts";
import type { Opaco } from "../sms/opaco.ts";

/** O nome do consumidor (`events_consumed.consumer`, filas `evt.dono.p<n>`). Fora do prefixo `agr_` das verticais. */
export const CONSUMIDOR_DO_DONO = "dono";

/** O evento que cria o dono. Dicionário §3.5. */
export const TIPO_DO_PROVISIONAMENTO = "tenant.provisioned";

/** As versões que o efeito sabe tratar. As duas do catálogo de contratos. */
export const VERSOES_DO_PROVISIONAMENTO: readonly number[] = [1, 2];

/** A origem com que o efeito chama `definir_dono`. */
export const ORIGEM_DO_PROVISIONAMENTO = "provisionamento";

/** O evento não é o que o efeito trata. Vai para a DLQ, como no CHR. */
export class VersaoDoProvisionamentoError extends Error {
  override readonly name = "VersaoDoProvisionamentoError";

  constructor(tipo: string, versao: number) {
    super(`o consumidor do dono nao trata ${tipo} v${versao}`);
  }
}

/**
 * O caso de onboarding não tem telefone legível. Repetir não o muda: vai para a
 * DLQ, e o dono continua a ter o painel.
 */
export class TelefoneDoCasoIndisponivelError extends Error {
  override readonly name = "TelefoneDoCasoIndisponivelError";

  constructor() {
    // Nem o `onboarding_id` nem o tenant entram na mensagem.
    super("o caso de onboarding nao tem telefone verificado legivel");
  }
}

/** Um telefone em claro, opaco: só o `revelar()` o dá. */
export type TelefoneRevelavel = Pick<Opaco, "revelar">;

/**
 * O telefone verificado por OTP do caso, ou `null`. É o `lerTelefoneDoCaso` do
 * KAM-215: lê pela ligação do consumo, sob a RLS do tenant do envelope.
 */
export interface TelefoneDoCaso {
  (bd: LigacaoDeLeitura, caso: { readonly tenantId: string; readonly onboardingId: string }): Promise<TelefoneRevelavel | null>;
}

/** O contacto do telefone, no tenant. É o `resolveContact` do KAM-008. */
export interface ContactoDoTelefone {
  (pedido: { readonly tenantId: string; readonly telefone: TelefoneRevelavel }): Promise<{
    readonly contactId: string;
  }>;
}

/** `platform.definir_dono(contacto, origem)`, com o contexto do tenant. */
export interface DefinirDono {
  (pedido: {
    readonly tenantId: string;
    readonly contactId: string;
    readonly origem: typeof ORIGEM_DO_PROVISIONAMENTO;
  }): Promise<void>;
}

/** O efeito do consumidor do dono sobre o `tenant.provisioned`. */
export function efeitoDoProvisionamento(portas: {
  readonly telefoneDoCaso: TelefoneDoCaso;
  readonly contacto: ContactoDoTelefone;
  readonly definirDono: DefinirDono;
}): Efeito {
  return async (bd, envelope) => {
    if (
      envelope.tipo !== TIPO_DO_PROVISIONAMENTO ||
      !VERSOES_DO_PROVISIONAMENTO.includes(envelope.versao)
    ) {
      throw new VersaoDoProvisionamentoError(envelope.tipo, envelope.versao);
    }
    const onboardingId = envelope.payload["onboarding_id"];
    if (typeof onboardingId !== "string" || onboardingId === "") {
      throw new TelefoneDoCasoIndisponivelError();
    }
    // O tenant é o do envelope, que o `consumir` já pôs no contexto da RLS; não
    // vem do payload, que não o tem.
    const tenantId = envelope.tenant_id;
    const telefone = await portas.telefoneDoCaso(bd, { tenantId, onboardingId });
    if (telefone === null) throw new TelefoneDoCasoIndisponivelError();
    const { contactId } = await portas.contacto({ tenantId, telefone });
    await portas.definirDono({ tenantId, contactId, origem: ORIGEM_DO_PROVISIONAMENTO });
  };
}
