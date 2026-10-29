/**
 * `Minor` ↔ `decimal2` e `inteiro_kz`, em aritmetica de inteiros (KAM-052).
 *
 * Os «Testes Requeridos» do bloco pedem esta conversao por nome, e ela e o sitio
 * exacto onde a regra do dicionario §2 — «nunca virgula flutuante» — deixa de
 * ser um principio e passa a ser codigo que ou esta certo ou perde dinheiro.
 *
 * ## Porque e que isto nao se escreve com `parseFloat`
 *
 * O `amountFormat` do §3.1 tem dois valores e os dois chegam como **texto** de
 * uma API:
 *
 *     decimal2      "1234.57"   kwanzas com duas casas (ProxyPay, §3.3)
 *     inteiro_kz    "1234"      kwanzas inteiros, sem centimos
 *
 * A travessia obvia — `parseFloat(texto) * 100` — perde centimos, e isto esta
 * **medido** e nao inferido (Node 24.21.0, `test_o_caminho_por_number_perde_um_centimo`):
 *
 *     parseFloat("1024.09") * 100  ->  102408.99999999999   (exacto: 102409)
 *     parseFloat("2.01")    * 100  ->  200.99999999999997   (exacto: 201)
 *     parseFloat("0.07")    * 100  ->  7.000000000000001    (exacto: 7)
 *
 * Com `Math.trunc` por cima, o primeiro cobra **1024,08 Kz** por uma encomenda
 * de 1024,09 Kz. Com `Math.round` os tres acertam — e e precisamente isso que
 * torna o `round` pior do que o erro: esconde a classe inteira atras de casos
 * que passam, e volta a aparecer na **soma** (`0.1 + 0.2` da
 * `0.30000000000000004`), que e onde um acumulador de ledger vive.
 *
 * **Uma correccao ao que esta pagina dizia antes**, porque apagar um erro sem o
 * nomear e o mesmo defeito ao contrario: a primeira versao afirmava que
 * `parseFloat("1234.57") * 100` dava `123456.99999999999`. **Nao da** — da
 * 123457 exacto, e o ensaio que o afirmava ficou vermelho na primeira execucao.
 * O tecto de **99.999.999,99** Kz do §3.3 tambem converte exacto por esta via.
 * O argumento nao era falso, mas os exemplos eram inventados, e os de cima sao
 * medidos.
 *
 * Por isso a conversao e **lexical e nao numerica**: separa-se a cadeia no
 * ponto, confere-se a forma, e constroi-se o `bigint` por concatenacao. Nao ha
 * passo nenhum em que um valor de dinheiro seja um `number` — e e isso que o
 * `tools/money_lint` impoe neste directorio, no gate 2.
 *
 * ## O sentido inverso tambem nao usa divisao com virgula
 *
 * `minorParaDecimal2(123457n)` e `"1234.57"`, obtido por `/` e `%` de `bigint` e
 * enchimento a esquerda. Um `Number(minor) / 100` com `toFixed(2)` voltaria a
 * passar pelo `float`.
 *
 * ## O que esta funcao **nao** faz
 *
 * Nao arredonda. Um `decimal2` com tres casas e um erro de contrato do
 * facilitador, nao um valor a truncar: truncar aqui perdia centimos em silencio,
 * que e o modo de falha que esta pagina existe para fechar. Levanta.
 */

import type { Minor } from "./tipos.ts";

/** Centimos num kwanza. */
export const MINOR_POR_KZ = 100n;

/** Casas decimais do formato `decimal2`. */
export const CASAS_DO_DECIMAL2 = 2;

export class ValorDeDinheiroInvalido extends Error {
  override readonly name = "ValorDeDinheiroInvalido";
  readonly valor: string;
  constructor(valor: string, motivo: string) {
    super(`valor de dinheiro invalido (${JSON.stringify(valor)}): ${motivo}`);
    this.valor = valor;
  }
}

/**
 * `-?` nao e aceite: ver `_recusarNegativo`. Grupos: inteiro, fraccao.
 *
 * ## O tecto de digitos, e porque ele subiu
 *
 * Era `{1,15}` e nao estava escrito em sitio nenhum do modulo nem vinha de fonte
 * nenhuma. Uma revisao adversarial mostrou o que ele recusava:
 * `"0000000000000001.00"` — 1,00 Kz com enchimento a zeros, 16 digitos — e
 * **campos de montante de largura fixa com enchimento a zeros sao comuns em
 * integracoes bancarias e EMIS**. Recusar um callback genuino e perder um
 * pagamento, e a mensagem mandava quem depura procurar um erro de forma onde
 * havia um limite arbitrario.
 *
 * Passa a `{1,30}`, que e folga larga sobre o tecto do facilitador
 * (99.999.999,99 Kz, §3.3) e continua a ser um tecto — uma cadeia sem limite
 * nenhum deixava um corpo de callback de megabytes a construir um `bigint`. E o
 * `_LIMITE_DE_DIGITOS` fica nomeado, para que a mensagem o possa dizer.
 */
const LIMITE_DE_DIGITOS = 30;
const DECIMAL2 = /^([0-9]{1,30})(?:\.([0-9]{1,2}))?$/;
const INTEIRO_KZ = /^([0-9]{1,30})$/;

/**
 * `"1234.57"` → `123457n`. Aceita `"1234"`, `"1234.5"` e `"1234.57"`.
 *
 * `"1234.5"` vale 123450 e nao 12345: a casa que falta e a dos centimos, e um
 * facilitador que escreva uma casa so esta a dizer «cinquenta centimos». Enche-se
 * a **direita**, que e a unica leitura que preserva a grandeza.
 */
export function minorDeDecimal2(texto: string): Minor {
  const encontro = DECIMAL2.exec(texto);
  if (encontro === null) {
    throw new ValorDeDinheiroInvalido(
      texto,
      "nao tem a forma decimal2 (ate " +
        `${LIMITE_DE_DIGITOS} digitos, opcionalmente um ponto e uma ou duas ` +
        "casas). Tres casas sao erro de contrato do facilitador e nao se " +
        "truncam aqui: truncar perde centimos em silencio. Se o valor tem a " +
        "forma e mais digitos do que o limite, e o limite que esta errado",
    );
  }
  const inteiro = encontro[1] ?? "";
  const fraccao = (encontro[2] ?? "").padEnd(CASAS_DO_DECIMAL2, "0");
  return BigInt(`${inteiro}${fraccao}`);
}

/** `123457n` → `"1234.57"`. */
export function minorParaDecimal2(minor: Minor): string {
  _recusarNegativo(minor);
  const kz = minor / MINOR_POR_KZ;
  const centimos = minor % MINOR_POR_KZ;
  return `${kz}.${`${centimos}`.padStart(CASAS_DO_DECIMAL2, "0")}`;
}

/**
 * `"1234"` → `123400n`. Kwanzas inteiros, sem centimos.
 *
 * Recusa qualquer ponto: num facilitador `inteiro_kz`, um `"1234.57"` nao e um
 * valor com centimos — e uma unidade que nao se sabe qual e, e adivinhar entre
 * «1234 kwanzas e 57 centimos» e «1234,57 kwanzas arredondado» e exactamente a
 * escolha que ninguem deve fazer num caminho de dinheiro.
 */
export function minorDeInteiroKz(texto: string): Minor {
  const encontro = INTEIRO_KZ.exec(texto);
  if (encontro === null) {
    throw new ValorDeDinheiroInvalido(
      texto,
      `nao tem a forma inteiro_kz (ate ${LIMITE_DE_DIGITOS} digitos, sem ponto). ` +
        "Um ponto num facilitador inteiro_kz deixa a unidade ambigua, e nao se " +
        "adivinha num caminho de dinheiro",
    );
  }
  return BigInt(encontro[1] ?? "0") * MINOR_POR_KZ;
}

/**
 * `123400n` → `"1234"`. Levanta se houver centimos a perder.
 *
 * E a assimetria deliberada deste modulo: enviar 1234,57 Kz a um facilitador que
 * so aceita kwanzas inteiros **nao tem resposta correcta**, e as duas erradas —
 * arredondar para cima (cobra-se a mais ao cliente) e para baixo (recebe-se a
 * menos) — sao as que um `Math.round` escolheria em silencio. Quem apanhar este
 * erro tem de decidir no desenho da cobranca, nao na conversao.
 */
export function minorParaInteiroKz(minor: Minor): string {
  _recusarNegativo(minor);
  if (minor % MINOR_POR_KZ !== 0n) {
    throw new ValorDeDinheiroInvalido(
      `${minor}`,
      "tem centimos e o facilitador e inteiro_kz: arredondar aqui cobra a mais " +
        "ao cliente ou recebe a menos, e a escolha e do desenho da cobranca",
    );
  }
  return `${minor / MINOR_POR_KZ}`;
}

/** Converte conforme o `amountFormat` declarado pelo adaptador (§3.1). */
export function minorDeFormato(texto: string, formato: "decimal2" | "inteiro_kz"): Minor {
  return formato === "decimal2" ? minorDeDecimal2(texto) : minorDeInteiroKz(texto);
}

/** O inverso, conforme o `amountFormat`. */
export function minorParaFormato(minor: Minor, formato: "decimal2" | "inteiro_kz"): string {
  return formato === "decimal2" ? minorParaDecimal2(minor) : minorParaInteiroKz(minor);
}

/**
 * Um montante negativo nao e um valor a formatar.
 *
 * O `amount_minor` da `payment_charges` tem `CHECK (amount_minor > 0)` (§6.2), e
 * uma correccao no ledger faz-se por **evento compensatorio** e nunca por um
 * valor negativo (§2, principio 3). Formatar um negativo era dar forma a algo
 * que o esquema recusa.
 */
function _recusarNegativo(minor: Minor): void {
  if (minor < 0n) {
    throw new ValorDeDinheiroInvalido(
      `${minor}`,
      "e negativo. O ledger corrige-se por eventos compensatorios e nunca por " +
        "valores negativos (docs/tecnica/04 §2, principio 3)",
    );
  }
}
