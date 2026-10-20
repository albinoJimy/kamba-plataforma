/**
 * Os códigos de erro da Meta, **cada um com o seu estado de verificação**.
 *
 * Um simulador que invente códigos de erro é pior do que um que não os tenha:
 * produz *fixtures* que ensinam o código a tratar um número que a Meta nunca
 * manda, e o tratamento certo nunca é escrito. Por isso este módulo é a única
 * fonte de códigos do pacote, e cada um traz escrito ao lado o que o sustenta.
 *
 * **CONFIRMADO** (`docs/tecnica/evidencia/E1` §5 e `docs/tecnica/01` §4.4, §16):
 *
 * - `130429` — débito excedido (80 mps por omissão, 20 mps fixos em
 *   coexistência). É o código que o critério 5 pede «N vezes».
 * - `131049` — limites de frequência por utilizador em *marketing*; podem estar
 *   activos em Angola, porque Angola **não** aparece na lista de exclusões.
 * - `2593109` — o cliente não partilhou histórico. Caso **normal**, não falha.
 *
 * **NÃO VERIFICADO**: tudo o que está em `CODIGOS_PROPOSTOS`. Nenhuma página
 * primária lida dá estes números; estão aqui porque uma *fixture* de `failed` e
 * uma de `unsupported` precisam de **algum** código, e um campo em falta mudava
 * a forma do corpo. São **parâmetros**: quem os confirmar move a linha para
 * cima e o resto do pacote não muda, porque ninguém mais os escreve à mão.
 *
 * É a mesma disciplina que o ticket manda para o *timeout* do webhook e para o
 * *pair rate limit*: «o simulador não os inventa e expõe-nos como parâmetros
 * configuráveis».
 */

/** Códigos em fonte primária. Podem ser afirmados. */
export const CODIGOS_CONFIRMADOS = {
  /** Débito excedido. O critério 5 pede-o N vezes seguidas. */
  debitoExcedido: 130429,
  /** Limite de frequência por utilizador em *marketing*. */
  limitePorUtilizador: 131049,
  /** O cliente não partilhou histórico. Caso normal. */
  semHistorico: 2593109,
} as const;

/**
 * Códigos **NÃO VERIFICADOS**, usados onde a forma do corpo exige um número.
 *
 * Não se afirmam em documentação nem se tratam no código de produção como
 * sentinelas: quem lê um `errors[]` trata-o pela forma, não por estes valores.
 */
export const CODIGOS_PROPOSTOS = {
  /** Um `statuses` `failed` precisa de um código. */
  naoEntregue: 131026,
  /** Um item `unsupported` precisa de um código. */
  tipoNaoSuportado: 131051,
  /** Um 5xx do Graph precisa de um código no corpo de erro. */
  erroInterno: 1,
} as const;

/** O tipo de excepção que o Graph põe em `error.type`. */
export const TIPO_DE_EXCEPCAO = "OAuthException";

/** Um erro do Graph, na forma que a Meta devolve. */
export interface ErroDoGraph {
  readonly error: {
    readonly message: string;
    readonly type: string;
    readonly code: number;
    readonly error_subcode?: number;
    readonly fbtrace_id: string;
  };
}

/** O corpo de erro do Graph para um código. */
export function erroDoGraph(
  codigo: number,
  mensagem: string,
  fbtrace: string,
  subcodigo?: number,
): ErroDoGraph {
  return {
    error: {
      message: mensagem,
      type: TIPO_DE_EXCEPCAO,
      code: codigo,
      ...(subcodigo === undefined ? {} : { error_subcode: subcodigo }),
      fbtrace_id: fbtrace,
    },
  };
}
