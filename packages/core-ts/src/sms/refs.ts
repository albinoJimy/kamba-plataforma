/**
 * Os três `id` de segredo que o módulo `sms/` lê, e **nada mais** (KAM-116).
 *
 * O ficheiro existe para que a área de `ci/secrets-allow.yaml` seja tão
 * estreita quanto possível, pelo mesmo desenho e pela mesma razão do
 * `../onboarding/segredos.ts` (KAM-016) e do `services/gwy/src/segredos.ts`
 * (KAM-013): uma referência de segredo tem, **por força**, a forma que o
 * `scan_secrets` apanha — o nome da constante significa segredo e o valor tem
 * entropia de sobra para não ser uma palavra —, e não há maneira de escrever um
 * `id` canónico ao lado de um nome canónico sem o varrimento disparar.
 *
 * A alternativa era declarar o `segredos.ts` inteiro, que é onde o cofre se lê e
 * onde um valor de segredo passa de facto pelas mãos do código. Assim esse
 * ficheiro continua **inteiramente varrido**, e este — que não tem lógica
 * nenhuma — é o único com a dispensa.
 *
 * O que aqui está são **nomes**, publicados em `ops/secrets-inventory.yaml` com
 * `introduzido_por: KAM-116`. Se um dia um valor a sério entrar neste ficheiro,
 * o *gate* deixa de o apanhar; é por isso que ele não leva mais nada, e
 * acrescentar-lhe uma função é um achado de revisão.
 */

import type { SecretRef } from "../secrets/port.ts";

/** A credencial de API do agregador. */
export const REF_CREDENCIAL: SecretRef = "sms_agregador_credencial";

/** O segredo com que o agregador assina os recibos. */
export const REF_RECIBO: SecretRef = "sms_recibo_segredo";

/** A chave do HMAC do destino. Ver `destino.ts`. */
export const REF_PEPPER: SecretRef = "pepper_sms_destino";

/** Todas as referências deste módulo, para quem monta a lista de obrigatórios. */
export const REFERENCIAS = [REF_CREDENCIAL, REF_RECIBO, REF_PEPPER] as const;
