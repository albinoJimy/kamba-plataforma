/**
 * O adaptador do LiteLLM para a revogação do off-boarding (KAM-233, critério 2):
 * a chave virtual do tenant apagada no proxy.
 *
 * ## Pelo alias, porque a chave do tenant não está na saga
 *
 * As chaves dos tenants nascem pelo `infra/llm/chaves.py provisionar`, com o
 * alias `tenant-<uuid>` (KAM-030), e não ficam no `provisioning_step`. Quando a
 * saga não registou o recurso, a revogação apaga pelo alias (`revogarDoTenant`);
 * quando registou, pelo *token* que a saga guardou (`revogar`). O alias é o do
 * `alias_do_tenant` do `chaves.py`, e não um segundo nome.
 *
 * ## O que se mediu na imagem fixada (`docs/evidencia/KAM-233.md` §3)
 *
 *   `POST /key/delete {"keys": [token]}`          200 `{"deleted_keys": [token]}`
 *   `POST /key/delete {"key_aliases": [alias]}`   200 `{"deleted_keys": [alias]}`
 *   o mesmo pedido outra vez                       404 `No keys found`
 *   a chave apagada, num pedido seu                401
 *
 * Daí as três regras. **Um 404 é o sucesso de uma repetição** (idempotente do
 * lado de fora): um *crash* entre o pedido e a gravação do passo repete-o. **Um
 * 200 conta só se o `deleted_keys` nomear o que se pediu**: um 200 que apagou
 * outra coisa, ou nada, levanta, em vez de dar por revogada uma chave que
 * continua a gastar o orçamento. **E nenhum dos dois basta sem a listagem**
 * (decisão do fundador de 2026-11-21, Q1 = A): depois do `DELETE`, o
 * `/key/list?return_full_object=true` por páginas, até ao `total_count`, não
 * pode ter a chave. Um 404 de um proxy que a perdeu de vista não fecha o passo
 * se ela ainda lá estiver.
 *
 * ## O limite que fica: o proxy de `prod` não tem base
 *
 * Sem `DATABASE_URL` a imagem fixada não tem chaves virtuais nenhumas, e o
 * `/key/delete` responde 500 (`DB not connected`, medido no §2 do mesmo anexo).
 * Esse 500 **sobe**, como qualquer outro: a fase fica parada com alerta, e o
 * passo não se dá por `sem_recurso` pela leitura de uma mensagem de erro.
 */

import type { ChaveDeLlm } from "../provisioning/contrato.ts";

/** O alias da chave de um tenant. O mesmo do `alias_do_tenant` do `infra/llm/chaves.py`. */
export function aliasDaChaveDoTenant(tenantId: string): string {
  return `tenant-${tenantId}`;
}

/** O proxy respondeu o que a revogação não aceita. A mensagem nunca leva a chave mestra. */
export class LiteLlmRecusouError extends Error {
  override readonly name = "LiteLlmRecusouError";
  readonly estado: number;

  constructor(estado: number, razao: string) {
    super(`o /key/delete do LiteLLM respondeu ${estado}: ${razao}`);
    this.estado = estado;
  }
}

export interface ChaveDoLlmPeloProxyOpcoes {
  /** A base do proxy, na rede interna (`http://litellm:4000`). */
  readonly base: string;
  /** A `litellm_master_key`. Só vai no cabeçalho, e nunca a registo nem a erro. */
  readonly chaveMestra: string;
  /** O `fetch`. Por omissão, o global do Node 24. */
  readonly buscar?: typeof fetch;
}

/** O desfecho de uma revogação: apagada agora, ou já não estava lá. */
export type DesfechoDaRevogacaoDaChave = "revogada" | "inexistente";

export class ChaveDoLlmPeloProxy implements Pick<ChaveDeLlm, "revogar"> {
  readonly #base: string;
  readonly #chave: string;
  readonly #buscar: typeof fetch;

  constructor(o: ChaveDoLlmPeloProxyOpcoes) {
    this.#base = o.base.replace(/\/+$/, "");
    this.#chave = o.chaveMestra;
    this.#buscar = o.buscar ?? ((url, init) => fetch(url, init));
  }

  /** Pelo *token* que a saga registou (o `external_id` do passo `chave_llm`). */
  async revogar(token: string): Promise<void> {
    await this.#apagar("keys", token);
  }

  /** Pelo alias do tenant, quando a saga não registou a chave. */
  async revogarDoTenant(tenantId: string): Promise<DesfechoDaRevogacaoDaChave> {
    return this.#apagar("key_aliases", aliasDaChaveDoTenant(tenantId));
  }

  async #apagar(campo: "keys" | "key_aliases", valor: string): Promise<DesfechoDaRevogacaoDaChave> {
    const resposta = await this.#buscar(`${this.#base}/key/delete`, {
      method: "POST",
      headers: { authorization: `Bearer ${this.#chave}`, "content-type": "application/json" },
      body: JSON.stringify({ [campo]: [valor] }),
    });
    if (resposta.status === 404) {
      await this.#confirmarAusencia(campo, valor);
      return "inexistente";
    }
    if (resposta.status !== 200) {
      // O corpo não entra na mensagem: o 401 do proxy ecoa o princípio e o fim da chave.
      throw new LiteLlmRecusouError(resposta.status, "a chave nao foi revogada");
    }
    let corpo: unknown;
    try {
      corpo = await resposta.json();
    } catch {
      throw new LiteLlmRecusouError(200, "o corpo nao e JSON");
    }
    const apagadas = (corpo as { deleted_keys?: unknown } | null)?.deleted_keys;
    if (!Array.isArray(apagadas) || !apagadas.includes(valor)) {
      throw new LiteLlmRecusouError(200, "o deleted_keys nao nomeia a chave pedida");
    }
    await this.#confirmarAusencia(campo, valor);
    return "revogada";
  }

  /**
   * A listagem inteira, por páginas, não tem a chave. Lança se a tiver, ou se
   * não a conseguir ler toda: uma lista incompleta não prova ausência nenhuma
   * (a mesma regra do `Proxy.listar` do `chaves.py`).
   */
  async #confirmarAusencia(campo: "keys" | "key_aliases", valor: string): Promise<void> {
    const atributo = campo === "keys" ? "token" : "key_alias";
    let vistas = 0;
    for (let pagina = 1; ; pagina += 1) {
      const resposta = await this.#buscar(
        `${this.#base}/key/list?return_full_object=true&size=${PAGINA_DO_KEY_LIST}&page=${pagina}`,
        { method: "GET", headers: { authorization: `Bearer ${this.#chave}` } },
      );
      if (resposta.status !== 200) {
        throw new LiteLlmRecusouError(resposta.status, "o /key/list nao confirmou a revogacao");
      }
      let corpo: unknown;
      try {
        corpo = await resposta.json();
      } catch {
        throw new LiteLlmRecusouError(200, "o /key/list nao devolveu JSON");
      }
      const { keys, total_count: total } = (corpo ?? {}) as { keys?: unknown; total_count?: unknown };
      if (!Array.isArray(keys) || typeof total !== "number") {
        throw new LiteLlmRecusouError(200, "o /key/list veio sem keys ou sem total_count");
      }
      if (keys.some((k) => (k as Record<string, unknown> | null)?.[atributo] === valor)) {
        throw new LiteLlmRecusouError(200, "a chave continua no /key/list depois do /key/delete");
      }
      vistas += keys.length;
      if (keys.length === 0 || vistas >= total) {
        if (vistas !== total) throw new LiteLlmRecusouError(200, "o /key/list ficou incompleto");
        return;
      }
    }
  }
}

/** Quantas chaves por página da listagem. A mesma do `Proxy.POR_PAGINA` do `chaves.py`. */
export const PAGINA_DO_KEY_LIST = 500;
