/**
 * Os dois `id` de segredo que o módulo `inscricao/` lê, e **nada mais**
 * (KAM-086).
 *
 * O ficheiro existe pelo desenho e pela razão do `../sms/refs.ts` e do
 * `../onboarding/segredos.ts`: uma referência de segredo tem, **por força**, a
 * forma que o `scan_secrets` apanha — o nome da constante significa segredo —, e
 * a dispensa de `ci/secrets-allow.yaml` fica num ficheiro **sem lógica
 * nenhuma**, de modo que o `./segredos.ts`, que é onde um valor de segredo passa
 * pelas mãos do código, continua inteiramente varrido.
 *
 * Se um dia um valor a sério entrar neste ficheiro, o *gate* deixa de o apanhar.
 * É por isso que ele não leva mais nada, e acrescentar-lhe uma função é um
 * achado de revisão.
 *
 * ## Dois, e não cinco, e a divisão é por propriedade de segurança
 *
 *     pepper_onboarding_ident           pseudonimidade — transformar um NIF, um
 *                                       telefone, um dispositivo ou um prefixo
 *                                       de rede num nome estável que não é o
 *                                       valor. Dono: privacidade
 *     segredo_onboarding_assinatura     infalsificabilidade — assinar o que
 *                                       entregamos a um cliente e voltamos a
 *                                       receber dele: o convite de `/entrar`, o
 *                                       bilhete do OTP e o cookie de sessão.
 *                                       Dono: segurança
 *
 * Dentro de cada um, os campos separam-se por **separador de domínio** e não por
 * chave nova. É o argumento escrito no cabeçalho do `../sms/destino.ts`, levado
 * ao caso em que os domínios são campos do mesmo registo: a separação sai da
 * chave quando os sistemas são diferentes, e sai do separador quando o dono, a
 * retenção e o ciclo de rotação são os mesmos. Cinco chaves para cinco colunas
 * da mesma linha eram cinco rotações para coordenar.
 *
 * **A `pepper_sms_destino` não está aqui**, e é de propósito: ela é do KAM-116,
 * cunha o endereço do SMS e não a pessoa, e quem a lê é o `../sms/segredos.ts`.
 * O `./provedores.ts` é o único sítio onde os dois espaços se tocam.
 */

import type { SecretRef } from "../secrets/port.ts";

/** O *pepper* dos HMAC de identificador. Ver `./identificadores.ts`. */
export const REF_PEPPER: SecretRef = "pepper_onboarding_ident";

/** A chave que assina convites, bilhetes e sessões. Ver `./token.ts` e `./sessao.ts`. */
export const REF_ASSINATURA: SecretRef = "segredo_onboarding_assinatura";

/** Todas as referências deste módulo, para quem monta a lista de obrigatórios. */
export const REFERENCIAS = [REF_PEPPER, REF_ASSINATURA] as const;
