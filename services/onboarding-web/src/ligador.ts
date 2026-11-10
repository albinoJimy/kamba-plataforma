/**
 * O `LigadorDeCanal` por HTTP: o `POST /internal/channels` do GWY (KAM-016).
 *
 * O guia não troca o `code` — o *Handoff* do KAM-093 proíbe-o. Manda o que o
 * popup devolveu à rota interna do GWY, que troca, cifra, guarda no cofre e
 * subscreve; o *token* e o PIN nunca voltam por aqui. A tradução dos códigos é
 * a tabela do cabeçalho do `services/gwy/src/canais.ts`:
 *
 *     201  criado        200  repetido        429  lista_espera
 *     400, 409, 502 e o resto   recusado
 *
 * **O 409 é recusa e não repetição**: é o `phone_number_id` de outro tenant
 * (critério 4 do KAM-016), e a resposta não diz de quem — o guia passa a
 * `falhado` com `ligacao_recusada`.
 *
 * O GWY interno está na rede do compose e não é saída: o `egress.yaml` deste
 * serviço continua `destinos: []`, pela regra escrita nele.
 */

import type { LigadorDeCanal, ResultadoDaLigacao } from "@kamba/core-ts/guia";
import type { ResultadoDoEs } from "@kamba/core-ts/onboarding";

/** O `fetch` como porta, para os ensaios. */
export type Buscar = (url: string, init: RequestInit) => Promise<Response>;

export class LigadorPorHttp implements LigadorDeCanal {
  readonly #base: string;
  readonly #buscar: Buscar;

  constructor(base: string, buscar: Buscar = fetch) {
    this.#base = base.replace(/\/+$/, "");
    this.#buscar = buscar;
  }

  async ligar(entrada: ResultadoDoEs): Promise<ResultadoDaLigacao> {
    const resposta = await this.#buscar(`${this.#base}/internal/channels`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(entrada),
    });
    if (resposta.status === 429) return { desfecho: "lista_espera", tentativaId: null };
    if (resposta.status !== 200 && resposta.status !== 201) {
      return { desfecho: "recusado", tentativaId: null };
    }
    let id: unknown = null;
    try {
      id = ((await resposta.json()) as { onboarding_id?: unknown }).onboarding_id;
    } catch {
      id = null;
    }
    return {
      desfecho: resposta.status === 201 ? "criado" : "repetido",
      tentativaId: typeof id === "string" ? id : null,
    };
  }
}
