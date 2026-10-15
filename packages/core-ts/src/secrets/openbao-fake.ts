/**
 * `OpenBaoFakeProvider` — o *fake* de OpenBao (KAM-010).
 *
 * ## O que isto é, e o que não é
 *
 * É um ***fake* da porta**, com a semântica de versões do KV v2: cada
 * referência tem uma lista de versões numeradas a partir de `1`, a maior é a
 * actual, a anterior é a penúltima. É isso que a suite de contrato precisa para
 * provar que `getRing` e `versions` significam a mesma coisa em todas as
 * implementações, e é isso que o KAM-013 vai usar para testar a aceitação das
 * duas assinaturas da Meta sem um cofre a correr.
 *
 * **Não** é um *mock* do protocolo do OpenBao. Não imita caminhos
 * (`/v1/secret/data/…`), nem códigos de estado, nem a forma do JSON de resposta.
 * A forma exacta das respostas da API do OpenBao é **NÃO VERIFICADO** nesta
 * sessão (sem rede e sem cofre instalado); confirma-se em
 * `openbao.org/api-docs/secret/kv/kv-v2/` antes de alguém escrever o adaptador
 * verdadeiro, que é trabalho dos Clusters e não deste ticket (`docs/tecnica/08`
 * §5: «OpenBao entra nos Clusters»).
 *
 * O que o *fake* **sim** reproduz, porque é o que o nosso código tem de
 * aguentar: um cofre **selado**. Um OpenBao selado responde, mas não serve
 * segredos — é o estado em que um reinício do cofre deixa o cluster até alguém
 * o destrancar, e é a razão pela qual `CofreInacessivelError` existe como classe
 * separada de `SecretAusenteError`.
 */

import {
  type Ambiente,
  CofreInacessivelError,
  SecretAusenteError,
  type SecretProvider,
  type SecretRef,
  type SecretRingTuple,
  validarRef,
} from "./port.ts";

/** Opções de construção. */
export interface OpenBaoFakeOpcoes {
  readonly ambiente: Ambiente;
  /**
   * Conteúdo inicial: referência → versões, da **mais antiga para a mais
   * recente**. Uma referência com uma só versão não tem anterior.
   */
  readonly dados?: Readonly<Record<string, readonly string[]>>;
  /** Arrancar selado (o estado de um OpenBao que acabou de reiniciar). */
  readonly selado?: boolean;
}

/** *Fake* de OpenBao com semântica de versões do KV v2. */
export class OpenBaoFakeProvider implements SecretProvider {
  readonly nome = "openbao-fake";
  readonly ambiente: Ambiente;
  #selado: boolean;
  readonly #dados = new Map<string, string[]>();

  constructor(opcoes: OpenBaoFakeOpcoes) {
    this.ambiente = opcoes.ambiente;
    this.#selado = opcoes.selado ?? false;
    for (const [ref, versoes] of Object.entries(opcoes.dados ?? {})) {
      if (versoes.length === 0) continue;
      this.#dados.set(validarRef(ref), [...versoes]);
    }
  }

  /** Sela o cofre: tudo passa a `CofreInacessivelError` até `destrancar()`. */
  selar(): void {
    this.#selado = true;
  }

  /** Destranca o cofre. */
  destrancar(): void {
    this.#selado = false;
  }

  /**
   * Escreve uma versão nova e devolve o seu identificador.
   *
   * Existe para os testes montarem o cenário de rotação (duas versões vivas).
   * **A porta não tem escrita** — ver `port.ts`, `SecretProvider`.
   */
  escrever(ref: SecretRef, valor: string): string {
    const chave = validarRef(ref);
    const versoes = this.#dados.get(chave) ?? [];
    versoes.push(valor);
    this.#dados.set(chave, versoes);
    return String(versoes.length);
  }

  async health(): Promise<void> {
    if (this.#selado) {
      throw new CofreInacessivelError(this.nome, "cofre selado");
    }
  }

  async get(ref: SecretRef): Promise<string> {
    const versoes = await this.#versoes(ref);
    // `at(-1)` devolve `string | undefined` com `noUncheckedIndexedAccess`;
    // `#versoes` garante que a lista não é vazia, e o `??` é o que convence o
    // compilador disso sem um `!` que esconderia um defeito real mais tarde.
    return versoes.at(-1) ?? "";
  }

  async getRing(ref: SecretRef): Promise<SecretRingTuple> {
    const versoes = await this.#versoes(ref);
    return [versoes.at(-1) ?? "", versoes.length > 1 ? (versoes.at(-2) ?? null) : null];
  }

  async versions(ref: SecretRef): Promise<readonly string[]> {
    const versoes = await this.#versoes(ref);
    // Do mais recente para o mais antigo, como a porta exige: a versão `n` é a
    // actual.
    return Array.from({ length: versoes.length }, (_, i) => String(versoes.length - i));
  }

  async #versoes(ref: SecretRef): Promise<string[]> {
    await this.health();
    const chave = validarRef(ref);
    const versoes = this.#dados.get(chave);
    if (versoes === undefined || versoes.length === 0) {
      throw new SecretAusenteError(chave, this.nome);
    }
    return versoes;
  }
}
