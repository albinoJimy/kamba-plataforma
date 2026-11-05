/**
 * Um valor que se recusa a aparecer em texto (KAM-116, critério 6).
 *
 * O critério 6 pede duas coisas da mesma natureza: «o código nunca aparece em
 * logs, traces ou métricas» e «o telefone só em memória, com HMAC nos
 * registos». Os dois são valores que o processo **tem** de ter em claro — um vai
 * no corpo do SMS, o outro no endereço do SMS — e que não podem sair para onde a
 * saída é permanente.
 *
 * Esta classe é a metade comum, e está num ficheiro próprio em vez de
 * duplicada: uma segunda implementação das mesmas quatro vias de conversão é a
 * classe de duplicação que se paga com uma fuga, não com ruído. É a mesma razão
 * que põe o `assinaturaValida` em `../entrada/assinatura.ts` e não dentro do
 * `gwy`.
 *
 * ## As quatro vias, e porque são quatro
 *
 * Uma `string` chega a texto por quatro caminhos distintos em JavaScript, e
 * tapar três deles não serve de nada:
 *
 *     toString              `${v}`, `"a" + v`, `String(v)`
 *     toJSON                `JSON.stringify(v)`, e tudo o que serializa JSON
 *     Symbol.toPrimitive    a coerção, inclusive `+v` e comparações soltas
 *     inspect.custom        `console.log(v)`, `util.inspect`, o `%o` do format
 *
 * O `../logger/politica.ts` já fecha a porta da frente — a *allowlist* de
 * campos não tem nenhum que leve um código ou um telefone, pelo que passá-los ao
 * *logger* é **erro de compilação**. O que ele não fecha é o resto: um `throw
 * new Error(\`destino ${d}\`)`, uma etiqueta de métrica, um *span* de *trace*,
 * um `process.stdout.write`. Estes são os caminhos que esta classe tapa.
 *
 * ## O que não é
 *
 * Não é cifra e não é cofre. O valor está em memória, em claro, no processo que
 * o precisa. O que isto impede é a **saída acidental**.
 */

/** O que qualquer conversão para texto devolve. A mesma do `../avisos/modelos.ts`. */
export const MASCARA = "***";

/** A chave que o `util.inspect` do Node consulta. */
export const INSPECCIONAR = Symbol.for("nodejs.util.inspect.custom");

/**
 * Base de um valor opaco: guarda, revela por um método nomeado, e mascara em
 * todas as conversões.
 *
 * O `revelar()` é o **único** caminho para o valor, e o nome é deliberado: vê-se
 * num diff e procura-se com um `grep`. Cada subclasse documenta onde é legítimo
 * chamá-lo, e um sítio a mais é um achado de revisão.
 */
export abstract class Opaco {
  readonly #valor: string;
  /** O comprimento, que é seguro publicar e às vezes é o que falta num log. */
  readonly comprimento: number;

  protected constructor(valor: string) {
    this.#valor = valor;
    this.comprimento = valor.length;
  }

  /** O valor em claro. **O único caminho para ele.** */
  revelar(): string {
    return this.#valor;
  }

  toString(): string {
    return MASCARA;
  }

  toJSON(): string {
    return MASCARA;
  }

  /**
   * A coerção para primitivo.
   *
   * O `number` devolve `NaN` de propósito: nem um código de OTP nem um
   * telefone são números — têm zeros à esquerda e um `+` que um `Number()`
   * come —, e devolver `NaN` faz quem os tentasse somar falhar em voz alta em
   * vez de trabalhar com um valor errado.
   */
  [Symbol.toPrimitive](dica: string): string | number {
    return dica === "number" ? Number.NaN : MASCARA;
  }

  [INSPECCIONAR](): string {
    return MASCARA;
  }
}
