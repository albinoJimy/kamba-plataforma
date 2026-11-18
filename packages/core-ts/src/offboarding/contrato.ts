/**
 * O contrato do off-boarding de um tenant (KAM-098): as fases, o calendário e
 * as portas.
 *
 * ## Duas línguas, uma tabela, e quem escreve que fase
 *
 * As sete fases vivem em `platform.offboarding_run` (revisão `*_offboarding.py`),
 * uma linha por fase. **Este módulo escreve quatro** — `verificacao`,
 * `pendentes`, `canal` e `revogacao` —, porque são as que usam as portas da saga
 * de provisioning (KAM-091) e o guarda que nunca apaga o WABA nem o número
 * (`provisioning/compensacao.ts`). **As outras três** — `exportacao`, `purga` e
 * `certificado` — são do `libs/py-core/src/kamba_core/offboarding/`, porque usam
 * o `purge_log`, os *holds* e o *ledger* do KAM-070 e do KAM-071, que vivem lá.
 *
 * Cada lado lê as linhas do outro **pela base**, e nenhum tem cópia do
 * calendário do outro: o prazo de cada fase escreve-o o pedido (`abrirPedido`),
 * uma vez, e o Python lê o `prazo_at`.
 *
 * ## Os prazos são *proposta*
 *
 * O bloco diz «Prazos D0–D30 são *propostas*», e o `docs/tecnica/10` §15.2
 * também. Estão aqui como números, e o dicionário diz que são proposta.
 */

import type { ChaveDeLlm, InboxDeAtendimento, RegistoDeCanalDeComercio, CanalDoCliente } from "../provisioning/contrato.ts";

/** As sete fases, pela ordem do bloco. O `CHECK` da revisão tem as mesmas. */
export const FASES = [
  "verificacao",
  "pendentes",
  "canal",
  "exportacao",
  "revogacao",
  "purga",
  "certificado",
] as const;
export type Fase = (typeof FASES)[number];

/** Os seis estados de uma fase. `cancelada` é o pedido cancelado até D7. */
export const ESTADOS_DA_FASE = [
  "pendente",
  "em_curso",
  "concluida",
  "suspensa_disputa",
  "falhada",
  "cancelada",
] as const;
export type EstadoDaFase = (typeof ESTADOS_DA_FASE)[number];

/**
 * O dia de cada fase, contado do pedido (D0). É o **prazo**: a fase pode
 * acabar antes. *Proposta* (`docs/tecnica/10` §15.2):
 *
 *   verificacao  D0    o pedido com a dupla confirmação
 *   canal        D1    o CHR deixa de encaminhar, a subscrição cancela-se
 *   pendentes    D7    encomendas, reservas e reembolsos fechados
 *   exportacao   D7    o pacote ao titular
 *   revogacao    D7    chave, conta, canal Medusa, entitlements; `tenant.closed`
 *   purga        D30   os dados operacionais
 *   certificado  D30   o certificado de eliminação
 */
export const DIA_DA_FASE: Readonly<Record<Fase, number>> = {
  verificacao: 0,
  canal: 1,
  pendentes: 7,
  exportacao: 7,
  revogacao: 7,
  purga: 30,
  certificado: 30,
};

/** Até este dia (exclusive) o pedido do titular é cancelável. *Proposta*. */
export const DIAS_DE_CANCELAMENTO = 7;

/** Quando cada fase **pode começar**, em dias desde D0. A revogação espera o fim do cancelamento. */
export const DIA_DE_INICIO: Readonly<Record<Fase, number>> = {
  verificacao: 0,
  canal: 0,
  pendentes: 0,
  exportacao: 0,
  revogacao: DIAS_DE_CANCELAMENTO,
  purga: 30,
  certificado: 30,
};

const MS_POR_DIA = 86_400_000;

/** O prazo de cada fase para um pedido feito em `d0`. Puro. */
export function prazos(d0: Date): Readonly<Record<Fase, Date>> {
  const saida = {} as Record<Fase, Date>;
  for (const fase of FASES) saida[fase] = new Date(d0.getTime() + DIA_DA_FASE[fase] * MS_POR_DIA);
  return saida;
}

/** Se uma fase já pode começar em `agora`, para um pedido feito em `d0`. Puro. */
export function podeComecar(fase: Fase, d0: Date, agora: Date): boolean {
  return agora.getTime() >= d0.getTime() + DIA_DE_INICIO[fase] * MS_POR_DIA;
}

/** Se o pedido ainda se pode cancelar em `agora`. Puro. */
export function cancelavel(d0: Date, agora: Date): boolean {
  return agora.getTime() < d0.getTime() + DIAS_DE_CANCELAMENTO * MS_POR_DIA;
}

/**
 * O aviso do critério 1, que vai no resultado do pedido para quem o mostra ao
 * dono. **Sem nomes nem números**: o texto é igual para todos.
 */
export const AVISO_DA_APP_BUSINESS =
  "O encerramento foi pedido. O número e a conta WhatsApp Business continuam seus: " +
  "a KAMBÁ deixa de responder por eles, e a aplicação WhatsApp Business volta a " +
  "funcionar normalmente no seu telefone. Pode cancelar o pedido nos próximos 7 dias.";

/** As duas origens do encerramento (bloco: «por pedido do titular» ou «por decisão de T&S»). */
export const ORIGENS = ["titular", "trust_safety"] as const;
export type Origem = (typeof ORIGENS)[number];

/** O `motivo` do `tenant.closed` e do `tenant_state_log`, por origem. Sem nada do dono. */
export const MOTIVO_DO_ENCERRAMENTO: Readonly<Record<Origem, string>> = {
  titular: "pedido_do_titular",
  trust_safety: "decisao_trust_safety",
};

/** O actor do encerramento no `tenant_state_log` e no `audit_log`. */
export const ACTOR_DO_ENCERRAMENTO = "kamba_batch:offboarding";

/**
 * As duas provas do titular (critério 1): o OTP ao telefone provado e a
 * ligação enviada ao e-mail registado. **As duas**, e cada uma pela sua porta:
 * uma porta que respondesse às duas era um sítio onde uma tomada de conta com a
 * sessão do dono passava com uma só.
 *
 * As provas são opacas para este módulo — o código do OTP e o *token* da
 * ligação — e não se guardam: o resultado do pedido diz só que as duas
 * passaram, e quando.
 */
export interface ProvasDoTitular {
  /** O OTP mandado ao telefone provado do dono confere? */
  otpConfere(tenantId: string, codigo: string): Promise<boolean>;
  /** A ligação mandada ao e-mail registado foi aberta com este *token*? */
  ligacaoDoEmailConfere(tenantId: string, token: string): Promise<boolean>;
}

/** As portas da revogação: as da saga de provisioning (KAM-091), as mesmas. */
export interface PortasDaRevogacao {
  readonly chaveDeLlm: Pick<ChaveDeLlm, "revogar">;
  readonly canalDeComercio: Pick<RegistoDeCanalDeComercio, "arquivar">;
  readonly inbox: Pick<InboxDeAtendimento, "desligar">;
}

/** A porta do canal do cliente na Meta, a da saga. Só se usa pelo guarda. */
export type CanalDaMeta = CanalDoCliente;

/** O pedido não tem as duas provas, ou uma delas não confere. Nada se escreve. */
export class ConfirmacaoIncompletaError extends Error {
  override readonly name = "ConfirmacaoIncompletaError";
  constructor(falta: readonly string[]) {
    super(`o encerramento exige as duas confirmacoes do titular; falta: ${falta.join(", ")}`);
  }
}

/** O tenant não está num estado de onde se encerra (`ativo` ou `suspenso`). */
export class EstadoDoTenantError extends Error {
  override readonly name = "EstadoDoTenantError";
  constructor(estado: string, origem: Origem) {
    super(`um tenant ${estado} nao se encerra por ${origem}`);
  }
}

/** Uma fase foi pedida antes do tempo, ou com a anterior por concluir. */
export class FaseForaDeOrdemError extends Error {
  override readonly name = "FaseForaDeOrdemError";
  constructor(fase: Fase, razao: string) {
    super(`a fase ${fase} nao pode correr: ${razao}`);
  }
}

/** O pedido não existe, foi cancelado, ou já não se pode cancelar. */
export class PedidoError extends Error {
  override readonly name = "PedidoError";
}
