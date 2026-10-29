/**
 * A conta de pagamento: beneficiario, `credenciais_ref` e `webhook_token`
 * (KAM-052, criterios 5 e 7).
 *
 * A tabela e o *trigger* vivem na revisao `0027`; este modulo e o lado da
 * aplicacao das mesmas tres invariantes, e **nao substitui a base**. A ordem e
 * essa de propria decisao: a barreira de dinheiro e a base (um *trigger* e um
 * `CHECK` nao se contornam por um caminho de codigo esquecido), e isto aqui
 * existe para que o erro chegue a quem escreve com uma mensagem util em vez de
 * um `23514` cru.
 *
 * ## `credenciais_ref` e um `SecretRef` e nao «um texto que parece um caminho»
 *
 * O criterio 7 pede que a coluna «so aceite caminho do cofre». Isto nao se
 * escreve com uma expressao nova: ja existe uma forma canonica de referencia de
 * segredo neste repositorio — o `SecretRef` do KAM-010, com o `validarRef` do
 * `secrets/port.ts` — e o `token_ref` do §3.15 e exactamente o mesmo tipo de
 * coluna (uma referencia opaca que o cofre resolve). Reutiliza-se.
 *
 * Duas propriedades dessa forma fazem o trabalho do criterio, e vale nomea-las
 * porque nao sao obvias:
 *
 * * o tecto de **200 caracteres** e, por escrito no `port.ts`, «o que impede
 *   que alguem passe um **valor** de segredo onde devia passar uma referencia»;
 * * a forma recusa espacos, plicas e `=`, que e o que um segredo copiado de um
 *   painel traz quase sempre (`AKIA…`, `sk-ant-…`, um PEM, um `base64` com
 *   `=` de enchimento).
 *
 * O que nenhuma forma pode garantir e que a referencia aponte para o segredo
 * certo. Isso mede-se com o varrimento do criterio 7 — que corre com os
 * **padroes do gate 9** e nao com uma segunda lista escrita a mao (ver
 * `db/tests/test_pagamentos_schema.py`) — e com a cifra em repouso, que e do
 * KAM-010.
 */

import { randomBytes } from "node:crypto";

import { type SecretRef, SecretRefInvalidaError, validarRef } from "../secrets/port.ts";
import type { Uuid } from "./tipos.ts";

/** O dominio do dicionario §3.4. **`pme`, e nao `tenant`** — ver `index.ts`. */
export const BENEFICIARY_KINDS = ["pme", "plataforma_receita_propria"] as const;
export type BeneficiaryKind = (typeof BENEFICIARY_KINDS)[number];

/** O dominio do `liquidacao_destino` do §6.2. */
export const LIQUIDACAO_DESTINOS = [
  "conta_banco",
  "carteira_unitel_money",
  "conta_pme_fora_plataforma",
] as const;
export type LiquidacaoDestino = (typeof LIQUIDACAO_DESTINOS)[number];

/**
 * Octetos do `webhook_token` (§3.1 das notas do bloco: «32 bytes aleatorios»).
 *
 * E o identificador **publico** da conta no URL do callback. Opaco: nao leva o
 * `tenant_id`, o `account_id` nem o `provider`, porque um URL de webhook aparece
 * em paineis de terceiros e em registos de proxy. Quem conhece o token sabe
 * apenas que existe uma conta.
 */
export const OCTETOS_DO_WEBHOOK_TOKEN = 32;

/**
 * Gera o `webhook_token`: 32 octetos aleatorios em `base64url`.
 *
 * `base64url` e nao hexadecimal: 43 caracteres em vez de 64, e sem `+`, `/` nem
 * `=`, pelo que entra num caminho de URL sem *escaping* — o que importa porque
 * e **isso** que ele e, um segmento de URL (§6.2: «gerado na aplicacao;
 * opaco»).
 *
 * `randomBytes` e nao `Math.random`: e o CSPRNG do sistema. Um token adivinhavel
 * deixava um terceiro enviar callbacks para a conta de uma PME — o que a
 * verificacao de assinatura ainda recusaria, mas a conta de um
 * `callbackAuth='none'` nao.
 */
export function gerarWebhookToken(): string {
  return randomBytes(OCTETOS_DO_WEBHOOK_TOKEN).toString("base64url");
}

/**
 * Comprimento de um `webhook_token` em `base64url`: `ceil(32 * 4 / 3)` = **43**.
 *
 * A formula escrita aqui antes era `ceil(32 / 3) * 4`, que da **44** — o valor da
 * forma **com** enchimento, que o `base64url` nao usa. O numero sempre esteve
 * certo (medido: 2 000 sorteios, todos de 43); a formula e que estava errada, e
 * uma revisao adversarial apanhou-a. Fica dito porque uma formula errada ao lado
 * de um valor certo e um convite a «corrigir» o valor.
 */
export const COMPRIMENTO_DO_WEBHOOK_TOKEN = 43;

export class CredenciaisRefInvalida extends Error {
  override readonly name = "CredenciaisRefInvalida";
  /** **Nunca o conteudo**, pela mesma razao do `SecretRefInvalidaError`. */
  readonly comprimento: number;
  constructor(valor: string) {
    super(
      "credenciais_ref tem de ser um caminho do cofre (SecretRef do KAM-010), " +
        `nunca o segredo. Recebida uma cadeia de ${valor.length} caracteres ` +
        "que nao tem essa forma.",
    );
    this.comprimento = valor.length;
  }
}

/**
 * Valida `credenciais_ref`. Devolve a referencia; lanca se nao tiver a forma.
 *
 * A conversao do `SecretRefInvalidaError` para um erro proprio nao e cerimonia:
 * o chamador aqui esta a escrever uma **coluna**, e a mensagem tem de dizer
 * qual, senao quem a le vai procurar o defeito no cofre.
 */
export function validarCredenciaisRef(valor: string): SecretRef {
  try {
    return validarRef(valor);
  } catch (erro) {
    if (erro instanceof SecretRefInvalidaError) throw new CredenciaisRefInvalida(valor);
    throw erro;
  }
}

/** A conta, do lado da aplicacao. Espelha as colunas do §6.2. */
export type ContaDePagamento = {
  readonly id: Uuid;
  readonly beneficiaryKind: BeneficiaryKind;
  readonly tenantId: Uuid | null;
  readonly provider: string;
  readonly entidade: string | null;
  readonly posId: string | null;
  readonly iec: string | null;
  readonly credenciaisRef: SecretRef | null;
  readonly webhookToken: string;
  readonly liquidacaoDestino: LiquidacaoDestino | null;
  readonly manualInstrucoes: string | null;
};

export const BENEFICIARIO_INCOERENTE = "BENEFICIARIO_INCOERENTE";
export const CONTA_DE_OUTRO_TENANT = "CONTA_DE_OUTRO_TENANT";
export const CONTA_DA_PLATAFORMA_EM_ENCOMENDA = "CONTA_DA_PLATAFORMA_EM_ENCOMENDA";
export const CONTA_DE_PME_EM_BILLING = "CONTA_DE_PME_EM_BILLING";

export type CodigoDeBeneficiario =
  | typeof BENEFICIARIO_INCOERENTE
  | typeof CONTA_DE_OUTRO_TENANT
  | typeof CONTA_DA_PLATAFORMA_EM_ENCOMENDA
  | typeof CONTA_DE_PME_EM_BILLING;

export type VeredictoDeBeneficiario =
  | { readonly ok: true }
  | { readonly ok: false; readonly codigo: CodigoDeBeneficiario; readonly motivo: string };

/**
 * G-1, do lado da aplicacao: a mesma regra que o *trigger* `assert_beneficiary`.
 *
 * O §10.4 escreve a guarda em tres frases, e sao tres asserções diferentes:
 *
 * 1. «para cobrancas de encomenda, `payment_accounts.tenant_id =
 *    payment_charges.tenant_id` e `beneficiary_kind='pme'`»;
 * 2. «cobrancas de billing so com `plataforma_receita_propria`»;
 * 3. «Uma conta nunca e partilhada entre tenants.»
 *
 * A terceira nao e uma quarta coluna: e a **primeira vista de fora**. Com um so
 * `tenant_id` por linha, «partilhada» quer dizer dois tenants a emitir cobrancas
 * contra o mesmo `account_id` — e cada uma dessas cobrancas e, uma a uma, o caso
 * 1. E por isso que o ensaio do criterio 5 a mede com **dois** tenants: provar
 * que a conta de A recusa a cobranca de B uma vez nao prova que ela nao e um
 * recurso partilhado; provar que recusa B **e** C prova.
 *
 * O `exactamente um de order_id/billing_cycle_id` do §6.1 e pressuposto e nao
 * verificado aqui: e um `CHECK` da `payment_charges`, que e do KAM-055.
 */
export function verificarBeneficiario(
  conta: Pick<ContaDePagamento, "id" | "beneficiaryKind" | "tenantId">,
  cobranca: { readonly tenantId: Uuid; readonly ehDeEncomenda: boolean },
): VeredictoDeBeneficiario {
  if ((conta.beneficiaryKind === "pme") !== (conta.tenantId !== null)) {
    return {
      ok: false,
      codigo: BENEFICIARIO_INCOERENTE,
      motivo:
        `a conta ${conta.id} tem beneficiary_kind='${conta.beneficiaryKind}' e ` +
        `tenant_id=${conta.tenantId ?? "nulo"}: uma conta de 'pme' tem sempre ` +
        "tenant, e uma de 'plataforma_receita_propria' nunca tem " +
        "(docs/tecnica/04 §6.2, CHECK de equivalencia).",
    };
  }
  if (cobranca.ehDeEncomenda) {
    if (conta.beneficiaryKind !== "pme") {
      return {
        ok: false,
        codigo: CONTA_DA_PLATAFORMA_EM_ENCOMENDA,
        motivo:
          `a conta ${conta.id} e de 'plataforma_receita_propria' e nao pode ` +
          "receber uma cobranca de encomenda: isso poria a plataforma a receber " +
          "o dinheiro de uma venda da PME (ADR-004; §10.4 G-1).",
      };
    }
    if (conta.tenantId !== cobranca.tenantId) {
      return {
        ok: false,
        codigo: CONTA_DE_OUTRO_TENANT,
        motivo:
          `a conta ${conta.id} e do tenant ${conta.tenantId} e a cobranca e do ` +
          `tenant ${cobranca.tenantId}: o beneficiario de uma venda e a PME que ` +
          "vendeu, e uma conta nunca e partilhada entre tenants (§10.4 G-1).",
      };
    }
    return { ok: true };
  }
  if (conta.beneficiaryKind !== "plataforma_receita_propria") {
    return {
      ok: false,
      codigo: CONTA_DE_PME_EM_BILLING,
      motivo:
        `a conta ${conta.id} e de 'pme' e nao pode receber uma cobranca de ` +
        "billing: a assinatura e receita da KAMBA e cobra-se numa conta de " +
        "'plataforma_receita_propria' (§11.2), que e o que evita activar o " +
        "tenant 'platform' (vedado por D2).",
    };
  }
  return { ok: true };
}
