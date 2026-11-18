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
 * ## Está entregue, e não está ligado
 *
 * Duas coisas faltam fora deste ticket, e ligar o consumidor sem elas era pôr
 * eventos numa fila que só pode falhar:
 *
 * * **o evento não sai em produção** — o `platform.advance_case(...,
 *   'es_concluido')` da revisão `0058` emite-o, e nenhum serviço o chama;
 * * **o telefone do caso não se lê em claro** — a `onboarding_case.phone_enc`
 *   não tem adaptador nem KEK no inventário (`lote/processo.ts`, `SEM_DADOS`), e
 *   o `phone_hmac` do caso está noutro espaço de chave que o de `contacts`.
 *
 * Por isso o efeito recebe o telefone por uma porta (`TelefoneDoCaso`), e a
 * subscrição em `platform.evt_subscricoes` e o `registry/` do consumidor ficam
 * para quando houver emissor e adaptador. Está na secção de verificação do bloco.
 */

import type { Efeito } from "../eventos/consumo.ts";
import type { Telefone } from "../inscricao/identificadores.ts";

/** O nome do consumidor, quando for ligado. Fora do prefixo `agr_` das verticais. */
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

/** O telefone verificado por OTP do caso. É o `telefoneDe` do KAM-086. */
export interface TelefoneDoCaso {
  (onboardingId: string): Promise<Telefone | null>;
}

/** O contacto do telefone, no tenant. É o `resolveContact` do KAM-008. */
export interface ContactoDoTelefone {
  (pedido: { readonly tenantId: string; readonly telefone: Telefone }): Promise<{
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
  return async (_bd, envelope) => {
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
    const telefone = await portas.telefoneDoCaso(onboardingId);
    if (telefone === null) throw new TelefoneDoCasoIndisponivelError();

    // O tenant é o do envelope, que o `consumir` já pôs no contexto da RLS; não
    // vem do payload, que não o tem.
    const tenantId = envelope.tenant_id;
    const { contactId } = await portas.contacto({ tenantId, telefone });
    await portas.definirDono({ tenantId, contactId, origem: ORIGEM_DO_PROVISIONAMENTO });
  };
}
