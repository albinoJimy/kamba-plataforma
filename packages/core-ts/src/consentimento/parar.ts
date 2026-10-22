/**
 * A detecção do «PARAR» (KAM-022, critério 5).
 *
 * «"PARAR" (insensível a maiúsculas e **acentos**) em qualquer ponto grava
 * `purpose='marketing'`, `accepted=false`, passa a conversa a `pausada` e
 * responde 1 confirmação.»
 *
 * ## Porque é uma função e não uma expressão regular numa linha
 *
 * O opt-out é uma obrigação da Messaging Policy da Meta (`E1` §4, CONFIRMADO) e
 * do Art. 19.º da Lei 22/11 (`E3`, CONFIRMADO para o artigo). Falhar em
 * reconhecê-lo não é um defeito de conveniência: é continuar a escrever a quem
 * pediu para parar. Por isso a detecção tem oito variantes nos Testes
 * Requeridos e está aqui, com teste próprio, em vez de inline num `if`.
 *
 * ## O que conta como «PARAR», e o que não conta
 *
 * **Conta:** a palavra sozinha, em qualquer caixa, com ou sem acentos, com
 * espaços à volta, com pontuação final, e os sinónimos que uma pessoa em Angola
 * escreveria — `STOP` (que a Meta usa nos avisos dela em inglês), `SAIR` e
 * `CANCELAR`.
 *
 * **Não conta:** a palavra dentro de uma frase. «não parar» e «pode parar de
 * me mandar isso?» **não** disparam, e isso é escolha com um custo de cada
 * lado: disparar numa frase dava revogações que o cliente não pediu (ele estava
 * a conversar), e não disparar deixa passar um pedido escrito por extenso. A
 * escolha é a conservadora para o **registo** — uma revogação é um facto que
 * fica —, e o que apanha o resto é o caminho normal: a mensagem segue para o
 * assistente, que tem «falar com humano» em todas as conversas (§9.2).
 *
 * Isto fica **dito** e não escondido, porque é exactamente o tipo de decisão
 * que um parecer pode mandar mudar: o critério 3 já diz «comportamento a
 * confirmar por parecer» sobre o seu vizinho.
 */

/**
 * As palavras que valem como opt-out, já sem acentos e em minúsculas.
 *
 * `parar` é a do critério. As outras três são as que uma pessoa escreve de
 * facto: `stop` porque é a que a Meta usa nos avisos em inglês e muita gente
 * copia, `sair` e `cancelar` porque são o português corrente para o mesmo
 * pedido. **Não** entram `nao` nem `chega`: a primeira é uma resposta a
 * qualquer pergunta e a segunda é ambígua.
 */
export const PALAVRAS_DE_PARAR = ["parar", "stop", "sair", "cancelar"] as const;

/**
 * Normaliza um texto para comparação: sem acentos, minúsculas, sem pontuação
 * nas pontas e sem espaço repetido.
 *
 * `normalize("NFD")` separa a letra do acento e o `replace` apaga a marca
 * diacrítica — é a forma que não depende de uma tabela de pares escrita à mão,
 * e apanha `PARÁR`, `Pãrar` e qualquer outra combinação que um teclado
 * produza. **A ordem importa:** primeiro separa-se, depois apaga-se a marca, e
 * só então se corta a pontuação; cortar antes deixava um acento combinante
 * sozinho a contar como carácter.
 */
export function normalizar(texto: string): string {
  return texto
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

/**
 * `true` quando o texto **é** um pedido de opt-out.
 *
 * Compara a cadeia normalizada **inteira** com a lista, e não procura dentro
 * dela: ver a nota do módulo para o que isso troca.
 */
export function eParar(texto: string): boolean {
  const limpo = normalizar(texto);
  return (PALAVRAS_DE_PARAR as readonly string[]).includes(limpo);
}
