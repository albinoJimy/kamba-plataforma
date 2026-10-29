/**
 * `capturar`: devolve o erro que uma chamada lanca, para se poder inspeccionar.
 *
 * Existe porque o `assert.throws` do Node devolve **`undefined`**, e nao o erro
 * — o que torna `(assert.throws(f, Classe) as Erro).codigo` um
 * `TypeError: Cannot read properties of undefined` em vez de uma asercao.
 * Aconteceu, em 42 asserções de uma vez, e foi o executor de testes que o
 * apanhou e nao a leitura.
 *
 * Usa-se quando o que importa e **o conteudo** do erro — o codigo tipado, a
 * mensagem, o campo que ele leva. Para verificar so a classe, o `assert.throws`
 * continua a ser o certo e mais curto.
 */

/** Corre `accao` e devolve o erro que ela lanca. Lanca se ela **nao** lancar. */
export function capturar<E extends Error = Error>(accao: () => unknown): E {
  try {
    accao();
  } catch (erro) {
    return erro as E;
  }
  throw new Error("esperava-se que a chamada lancasse, e ela devolveu");
}

/** A versao assincrona, para o que devolve `Promise`. */
export async function capturarAsync<E extends Error = Error>(
  accao: () => Promise<unknown>,
): Promise<E> {
  try {
    await accao();
  } catch (erro) {
    return erro as E;
  }
  throw new Error("esperava-se que a chamada rejeitasse, e ela resolveu");
}
