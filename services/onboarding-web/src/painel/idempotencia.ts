/**
 * A `Idempotency-Key` do `PATCH /painel/produtos/:id` (KAM-099, critério 5).
 *
 * «Pedido duplicado (mesma chave) não duplica a gravação.» A chave vale **por
 * tenant**: a mesma cadeia em dois tenants são duas chaves, e uma resposta
 * guardada para A nunca se devolve a B.
 *
 * ## A promessa guarda-se antes de a gravação acabar
 *
 * Dois pedidos com a mesma chave ao mesmo tempo — o duplo toque num telemóvel
 * lento — não podem gravar os dois. Por isso o que se guarda é a **promessa** da
 * resposta, no instante em que o primeiro chega; o segundo espera por ela em vez
 * de gravar. Uma resposta que falhe por excepção sai do mapa, para que a
 * repetição possa tentar outra vez.
 *
 * ## A mesma chave com outro conteúdo é recusada
 *
 * Devolver a resposta antiga a um pedido diferente dizia «gravado» sobre um
 * valor que ninguém gravou. A impressão do pedido (`sku` e corpo) guarda-se ao
 * lado, e uma chave reutilizada com outra impressão dá `422`.
 *
 * **Em memória, pela razão do `./sessao.ts`**: o `server.ts` não arranca em
 * `prod`. O tecto de entradas e a validade são *proposta*.
 */

/** Validade de uma chave, em milissegundos. ***Proposta***: 24 horas. */
export const VALIDADE_DA_CHAVE_MS = 24 * 3600 * 1000;

/** Tecto de chaves guardadas. ***Proposta***: 10 000; acima, as mais velhas saem. */
export const MAXIMO_DE_CHAVES = 10_000;

/** A forma de uma chave: 16 a 128 caracteres sem espaços nem controlo. */
export const FORMA_DA_CHAVE = /^[A-Za-z0-9_.:-]{16,128}$/;

/** Uma resposta HTTP guardada: estado e corpo. */
export interface Guardada {
  readonly estado: number;
  readonly corpo: unknown;
  /** `false` para uma resposta que não responde ao pedido (a sessão revogada). */
  readonly guardar?: boolean | undefined;
}

interface Entrada {
  readonly impressao: string;
  readonly em: number;
  readonly resposta: Promise<Guardada>;
}

export type Desfecho =
  | { readonly tipo: "nova" | "repetida"; readonly resposta: Guardada }
  | { readonly tipo: "reutilizada" };

export class Idempotencia {
  readonly #entradas = new Map<string, Entrada>();
  readonly #relogio: () => number;

  constructor(relogio: () => number = () => Date.now()) {
    this.#relogio = relogio;
  }

  /**
   * Corre `fazer` uma vez por `(tenant, chave)`.
   *
   * `repetida` quer dizer que a resposta é a da primeira vez e **nada** correu.
   */
  async uma(tenantId: string, chave: string, impressao: string, fazer: () => Promise<Guardada>): Promise<Desfecho> {
    const agora = this.#relogio();
    const id = `${tenantId}\u0000${chave}`;
    const viva = this.#entradas.get(id);
    if (viva !== undefined && agora - viva.em <= VALIDADE_DA_CHAVE_MS) {
      if (viva.impressao !== impressao) return { tipo: "reutilizada" };
      return { tipo: "repetida", resposta: await viva.resposta };
    }
    const resposta = fazer();
    // Apaga antes de pôr, para que uma chave renovada vá para o fim do mapa: a
    // poda varre do princípio, e uma chave fresca no princípio saía primeiro.
    this.#entradas.delete(id);
    this.#entradas.set(id, { impressao, em: agora, resposta });
    this.#podar(agora);
    try {
      const r = await resposta;
      // Uma resposta 5xx não se guarda: o COM em baixo não é uma resposta ao
      // pedido, e a repetição com a mesma chave tem de poder tentar outra vez.
      if (r.estado >= 500 || r.guardar === false) this.#entradas.delete(id);
      return { tipo: "nova", resposta: r };
    } catch (erro) {
      this.#entradas.delete(id);
      throw erro;
    }
  }

  #podar(agora: number): void {
    for (const [id, e] of this.#entradas) {
      if (this.#entradas.size <= MAXIMO_DE_CHAVES && agora - e.em <= VALIDADE_DA_CHAVE_MS) break;
      this.#entradas.delete(id);
    }
  }
}
