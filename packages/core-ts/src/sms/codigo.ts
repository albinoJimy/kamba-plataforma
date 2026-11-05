/**
 * O código do OTP, num tipo que não sabe dizer-se por extenso (KAM-116,
 * critério 6).
 *
 * «O código nunca aparece em logs, traces ou métricas (KAM-068).»
 *
 * O mecanismo está em `opaco.ts`, com as quatro vias de conversão e a razão por
 * que são quatro. O que este ficheiro acrescenta é a **forma** e o sítio de
 * chamada do `revelar()`:
 *
 * ```ts
 * const c = new CodigoOtp("123456");
 * `${c}`                  // "***"
 * JSON.stringify({ c })   // '{"c":"***"}'
 * console.log(c)          // ***
 * c.revelar()             // "123456"  ← o único caminho, e é procurável
 * ```
 *
 * **O `revelar()` de um código é chamado uma vez em todo o módulo**, em
 * `modelos.ts`, para compor o texto que vai para o agregador. Um segundo sítio
 * de chamada é um achado de revisão.
 *
 * ## Quem gera o código não é este módulo
 *
 * É o KAM-086, que é dono do fluxo do OTP (geração, validade, tentativas,
 * disjuntor de orçamento). O que aqui se valida é a forma, e a gama de
 * comprimentos é larga de propósito: fixar seis dígitos era decidir por esse
 * ticket.
 */

import { Opaco } from "./opaco.ts";

export { MASCARA } from "./opaco.ts";

/** Comprimentos aceites. A escolha dentro da gama é do KAM-086. */
export const DIGITOS_MINIMOS = 4;
export const DIGITOS_MAXIMOS = 8;

const FORMA = new RegExp(`^[0-9]{${DIGITOS_MINIMOS},${DIGITOS_MAXIMOS}}$`);

/**
 * Levantado quando o código não tem forma de código.
 *
 * **A mensagem não leva o valor recusado**, nem sequer «parecia um telefone»:
 * se alguém passou o telefone onde devia passar o código, o telefone não entra
 * no log por causa desta mensagem. Leva o comprimento, que é o que permite
 * perceber o erro sem o revelar.
 */
export class CodigoInvalidoError extends Error {
  override readonly name = "CodigoInvalidoError";
  readonly comprimento: number;

  constructor(comprimento: number) {
    super(
      `codigo de OTP invalido (${comprimento} caracteres); esperava ` +
        `${DIGITOS_MINIMOS} a ${DIGITOS_MAXIMOS} algarismos`,
    );
    this.comprimento = comprimento;
  }
}

/** Um código de OTP que se recusa a aparecer em texto. Ver `opaco.ts`. */
export class CodigoOtp extends Opaco {
  constructor(valor: string) {
    const bruto = typeof valor === "string" ? valor : "";
    if (!FORMA.test(bruto)) throw new CodigoInvalidoError(bruto.length);
    super(bruto);
  }
}
