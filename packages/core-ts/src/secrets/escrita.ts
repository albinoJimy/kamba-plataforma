/**
 * A porta de **escrita** no cofre (KAM-016, a lacuna que o `ADR-L002` §6 declarou).
 *
 * O `port.ts` do KAM-010 diz, no `docstring` da `SecretProvider`: «Cunhar uma
 * referência nova — escrever um segredo no cofre e receber de volta a referência
 * que a base de dados guarda — é o que o **KAM-016** (Embedded Signup v4) vai
 * precisar, e **não está aqui**: nenhum serviço do Piloto escreve no cofre, e uma
 * porta de escrita sem consumidor é desenho especulativo. A lacuna está declarada
 * em `docs/adr/ADR-L002-injeccao-de-segredos.md` §6 para que o KAM-016 não a
 * descubra tarde.»
 *
 * Este é esse dia, e a porta entra **separada** da de leitura e não acrescentada
 * a ela. Três razões, e a terceira é a que decide:
 *
 * 1. A `SecretProvider` tem três implementações e uma suite de contrato que corre
 *    a mesma bateria sobre as três. O `EnvSecretProvider` lê variáveis de
 *    ambiente: **não há escrita possível** — um processo não escreve no seu
 *    próprio ambiente de forma que outro processo veja. Juntar a escrita à porta
 *    de leitura obrigava-o a implementar um método que lança sempre, e uma porta
 *    cujos implementadores lançam em metade dos métodos não é um contrato.
 * 2. Quem lê um segredo e quem o escreve não são o mesmo papel. O GWY lê o App
 *    Secret em cada webhook; o provisionamento cunha um *token* por cliente, uma
 *    vez. Separar as portas deixa a diferença visível no tipo de quem recebe a
 *    dependência, em vez de a deixar a uma convenção.
 * 3. **O `supply_chain` e o *gate* 9 varrem por atribuição com forma de
 *    segredo.** Um `cunhar(familia, valor)` é a única assinatura deste
 *    repositório onde um valor de segredo é um argumento, e tê-la num ficheiro
 *    só é o que mantém a área a vigiar pequena — o mesmo raciocínio que põe os
 *    dois `id` do GWY em `services/gwy/src/segredos.ts`.
 *
 * ## O que uma referência cunhada é, e o que não é
 *
 * É `<familia>/<sufixo>`, com a família a vir do `ops/secrets-inventory.yaml` e o
 * sufixo a ser **opaco**. O `port.ts` di-lo: «Para famílias com uma instância por
 * tenant (o token de cliente do Embedded Signup é a única no Piloto) a referência
 * é o `id` da família seguido de um sufixo opaco que o cofre cunhou … **Quem
 * recebe uma referência não a interpreta.** Não a parte, não deriva `tenant_id`
 * dela, não assume que o sufixo é um UUID.»
 *
 * **O sufixo não é o `tenant_id`, e isso é a decisão deste ficheiro.** Seria
 * cómodo — a referência dizia de quem era o segredo, e a compensação não
 * precisaria de a ler da base. É exactamente por isso que não se faz: o
 * `token_ref` vive numa coluna que o `kamba_app` **lê** (o `GRANT UPDATE` da
 * `0001` nomeia-a), e um sufixo que é o `tenant_id` torna cada referência um
 * identificador de tenant em claro num sítio onde o resto do esquema tem cuidado
 * de não o ter. O sufixo é aleatório, e quem precisa de saber de quem é a
 * referência lê a linha que a guarda.
 */

import { randomBytes } from "node:crypto";

import { type SecretRef, validarRef } from "./port.ts";

/** Octetos do sufixo aleatório de uma referência cunhada. */
export const OCTETOS_DO_SUFIXO = 16;

/** A forma de uma família: o `id` do inventário, `snake_case` minúsculo. */
const FAMILIA = /^[a-z][a-z0-9_]{2,63}$/;

/** Levantada quando a família pedida não tem a forma de um `id` do inventário. */
export class FamiliaInvalidaError extends Error {
  override readonly name = "FamiliaInvalidaError";
  readonly familia: string;

  constructor(familia: string) {
    super(
      `família de segredo inválida: ${JSON.stringify(familia)}; ` +
        "esperava um id do inventário em snake_case",
    );
    this.familia = familia;
  }
}

/**
 * Levantada quando se tenta escrever num provedor que não sabe escrever.
 *
 * Classe própria e não `CofreInacessivelError`: o cofre está acessível, e a
 * reacção certa é outra — não se repete, configura-se um provedor que escreva. O
 * caso real é o `EnvSecretProvider` em desenvolvimento.
 */
export class SemEscritaError extends Error {
  override readonly name = "SemEscritaError";
  readonly provedor: string;

  constructor(provedor: string) {
    super(
      `o provedor ${provedor} não escreve no cofre; ` +
        "cunhar uma referência exige um provedor de escrita (ADR-L002 §6)",
    );
    this.provedor = provedor;
  }
}

/**
 * A porta de escrita.
 *
 * Duas operações e nenhuma de leitura: quem precisa das duas recebe as duas
 * portas. É o que o `Cofre` do `onboarding/contrato.ts` faz, e é lá — no sítio
 * de uso — que elas se juntam.
 */
export interface SecretWriter {
  /** Nome curto da implementação, o mesmo da `SecretProvider`. */
  readonly nome: string;

  /**
   * Escreve `valor` numa instância nova de `familia` e devolve a referência.
   *
   * O sufixo é cunhado aqui e é **aleatório** — ver a nota do módulo. Duas
   * chamadas com o mesmo valor dão duas referências: esta porta não deduplica, e
   * a idempotência de quem a usa vive na base (no KAM-016, nas duas unicidades
   * de `channel_onboarding`).
   *
   * @throws {FamiliaInvalidaError} se `familia` não tem forma de `id`.
   * @throws {CofreInacessivelError} se o cofre não responde.
   */
  cunhar(familia: string, valor: string): Promise<SecretRef>;

  /**
   * Apaga o segredo de `ref`.
   *
   * **Idempotente por contrato**: revogar uma referência que já não existe
   * resolve, e não lança. A razão é a compensação de uma saga — ela pode correr
   * duas vezes (um processo que cai a meio e outro que a retoma), e uma
   * compensação que falha na segunda passagem deixa a saga sem forma de acabar.
   *
   * @throws {SecretRefInvalidaError} se `ref` não tem forma de referência.
   * @throws {CofreInacessivelError} se o cofre não responde.
   */
  revogar(ref: SecretRef): Promise<void>;
}

/** Valida a forma de uma família e devolve-a, para encadear. */
export function validarFamilia(familia: string): string {
  if (typeof familia !== "string" || !FAMILIA.test(familia)) {
    throw new FamiliaInvalidaError(typeof familia === "string" ? familia : "");
  }
  return familia;
}

/**
 * Cunha uma referência nova para uma família. Pura: não escreve nada.
 *
 * Separada da escrita para que uma implementação de cofre não tenha de repetir a
 * regra da forma — e para que um teste possa afirmar a forma sem um cofre.
 */
export function cunharRef(familia: string): SecretRef {
  const sufixo = randomBytes(OCTETOS_DO_SUFIXO).toString("hex");
  return validarRef(`${validarFamilia(familia)}/${sufixo}`);
}
