/**
 * O gerador pseudo-aleatório do simulador: determinismo byte a byte (KAM-024).
 *
 * O critério 1 pede «a partir de uma semente, payloads **byte-idênticos**». Isso
 * exclui `Math.random`, `crypto.randomUUID` e `Date.now` em qualquer sítio do
 * caminho de geração — e é uma exclusão que se verifica por teste, não por
 * disciplina: há um que gera o conjunto completo duas vezes e compara os bytes.
 *
 * ## Porque é que o algoritmo está aqui e não vem de uma dependência
 *
 * Um gerador determinístico é vinte linhas e um teste. Uma dependência nova
 * entra no SBOM, no veredicto de licenças do *gate* 11 e na superfície de
 * *supply chain* — para vinte linhas. O `sfc32` é de domínio público, tem
 * período longo o suficiente para o que aqui se faz (gerar identificadores
 * sintéticos) e **não é criptográfico**: não serve para gerar segredos, e nada
 * aqui o usa para isso.
 *
 * ## O que a semente garante, e o que não garante
 *
 * **Garante** que a mesma semente dá a mesma sequência, nesta e em qualquer
 * máquina: a aritmética é toda sobre inteiros de 32 bits com `>>> 0`, sem
 * ponto flutuante. **Não garante** estabilidade entre versões deste ficheiro —
 * mudar a ordem em que o gerador é consultado muda os identificadores, e é por
 * isso que as *fixtures* gravadas são o contrato, e não a semente.
 */

/** O estado do gerador: quatro inteiros de 32 bits. */
export interface Estado {
  a: number;
  b: number;
  c: number;
  d: number;
}

/**
 * FNV-1a de 32 bits sobre a semente em texto.
 *
 * Quatro passagens com sufixos diferentes dão as quatro palavras do estado — o
 * que o `sfc32` precisa. Uma só passagem repetida punha as quatro iguais, e o
 * `sfc32` com estado uniforme tem um arranque pobre.
 */
export function estadoDe(semente: string): Estado {
  const palavra = (sufixo: string): number => {
    let h = 0x811c9dc5;
    for (const texto of [semente, sufixo]) {
      for (let i = 0; i < texto.length; i += 1) {
        h ^= texto.charCodeAt(i);
        h = Math.imul(h, 0x01000193) >>> 0;
      }
    }
    return h >>> 0;
  };
  return {
    a: palavra(":a"),
    b: palavra(":b"),
    c: palavra(":c"),
    d: palavra(":d"),
  };
}

/**
 * Um gerador determinístico sobre uma semente de texto.
 *
 * Não é uma classe por gosto: o estado tem de ser privado e avançar a cada
 * leitura, e um objecto com métodos é o que torna «duas gerações com a mesma
 * semente» uma afirmação sobre duas instâncias e não sobre uma variável global.
 */
export class Gerador {
  #estado: Estado;
  readonly semente: string;
  /** Quantas vezes o gerador foi consultado. Para os testes de determinismo. */
  #passos = 0;

  constructor(semente: string) {
    this.semente = semente;
    this.#estado = estadoDe(semente);
    // Vinte passos de aquecimento: o `sfc32` recém-semeado tem correlação nos
    // primeiros valores, e o custo é nulo.
    for (let i = 0; i < 20; i += 1) this.#proximo();
  }

  get passos(): number {
    return this.#passos;
  }

  /** Um inteiro de 32 bits sem sinal. */
  #proximo(): number {
    const e = this.#estado;
    const t = (e.a + e.b) >>> 0;
    e.a = e.b ^ (e.b >>> 9);
    e.b = (e.c + (e.c << 3)) >>> 0;
    e.c = ((e.c << 21) | (e.c >>> 11)) >>> 0;
    e.d = (e.d + 1) >>> 0;
    const u = (t + e.d) >>> 0;
    e.c = (e.c + u) >>> 0;
    this.#passos += 1;
    return u;
  }

  /** Um inteiro em `[0, limite)`. Sem módulo enviesado para os limites usados. */
  inteiro(limite: number): number {
    if (!Number.isInteger(limite) || limite <= 0) {
      throw new RangeError(`limite tem de ser um inteiro positivo: ${limite}`);
    }
    // Rejeição: o maior múltiplo de `limite` que cabe em 2^32. Sem isto, um
    // limite que não divida 2^32 enviesa os primeiros valores — pouco, mas
    // determinismo e enviesamento são coisas diferentes, e esta é barata.
    const tecto = Math.floor(0x100000000 / limite) * limite;
    for (;;) {
      const valor = this.#proximo();
      if (valor < tecto) return valor % limite;
    }
  }

  /** Uma cadeia de `comprimento` caracteres do alfabeto dado. */
  texto(comprimento: number, alfabeto: string): string {
    let saida = "";
    for (let i = 0; i < comprimento; i += 1) {
      saida += alfabeto[this.inteiro(alfabeto.length)];
    }
    return saida;
  }

  /** Um elemento da lista. Lança se a lista estiver vazia. */
  escolher<T>(itens: readonly T[]): T {
    if (itens.length === 0) throw new RangeError("escolher de uma lista vazia");
    const item = itens[this.inteiro(itens.length)];
    if (item === undefined) throw new RangeError("escolher devolveu undefined");
    return item;
  }

  /** Um gerador novo, derivado deste por um rótulo. Para sub-sequências estáveis. */
  derivar(rotulo: string): Gerador {
    return new Gerador(`${this.semente}/${rotulo}`);
  }
}
