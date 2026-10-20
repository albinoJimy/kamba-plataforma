/**
 * O cliente da Graph API (KAM-015).
 *
 * ## O que é *proposta* aqui, e fica dito
 *
 * **A versão da Graph API.** Nenhum documento deste repositório a fixa — o
 * `GraphFalso` do KAM-024 escreveu-o: «inventar uma ("v23.0") era afirmar o que
 * não se sabe». Este módulo fixa `v23.0` como **proposta, 2026-10-20**, e é a
 * primeira afirmação do repositório sobre isso. É parâmetro: quem souber a
 * certa muda uma constante, e o servidor falso aceita qualquer `/vN.N/` de
 * propósito, pelo que os testes não a assumem.
 *
 * **O FQDN de saída.** `graph.facebook.com` está em `docs/tecnica/08` §4.4 como
 * regra de proxy com *allowlist*, e este é o primeiro código que sai para lá.
 *
 * ## Ramifica pelo `error.code`, nunca pelo estado HTTP
 *
 * É a regra mais importante deste ficheiro e está aqui porque o KAM-024 a
 * documentou: nenhuma fonte dá o estado HTTP do `130429`, e há relato de a
 * Cloud API devolver `400` com o código no corpo. Um cliente que ramifique por
 * `status === 429` passa os testes contra o servidor falso e **nunca repete em
 * produção**. Por isso `RespostaDaMeta` leva o `codigo` como campo de primeira
 * classe e o `estadoHttp` como informação.
 *
 * ## O telefone nunca entra num registo
 *
 * O `enviar` recebe um `Destinatario` que pode ter telefone, e **não o escreve
 * em sítio nenhum**: não há `log` neste módulo, de propósito. Quem registra é o
 * adapter, e registra o `contactId` (um UUID) e o `id_opaco` do `wamid`. É o
 * DoD «Privacidade» e o X-11 do gate 6.
 */

import type {
  ClienteDaMeta,
  Corpo,
  Destinatario,
  RespostaDaMeta,
} from "./contrato.ts";

/**
 * A versão da Graph API. **Proposta, 2026-10-20.**
 *
 * Ver a nota do módulo: nenhum documento a fixa, e esta é a primeira afirmação
 * do repositório. Marcada como proposta e não como CONFIRMADO.
 */
export const VERSAO_DA_GRAPH = "v23.0";

/** O anfitrião da Graph API. `docs/tecnica/08` §4.4 põe-no na *allowlist*. */
export const ANFITRIAO_DA_GRAPH = "https://graph.facebook.com";

/** O que o cliente precisa para falar com a Meta. */
export interface Configuracao {
  /** A base, sem barra no fim. O servidor falso do KAM-024 entra por aqui. */
  readonly base?: string;
  readonly versao?: string;
  /** O *token* de acesso. Nunca é registado nem aparece numa mensagem de erro. */
  readonly token: string;
  /** O `fetch` a usar. Porta para que um teste unitário não abra socket. */
  readonly buscar?: typeof fetch;
  /** *Timeout* por chamada, em ms. **NÃO VERIFICADO** do lado da Meta: parâmetro. */
  readonly esperaMaximaMs?: number;
}

/** O *timeout* por omissão. Nosso, e *proposta*: a Meta não o publica. */
export const ESPERA_MAXIMA_MS = 10_000;

/** O corpo que a Meta espera, para um `Corpo` nosso. */
export function corpoDaMeta(para: Destinatario, corpo: Corpo): Record<string, unknown> {
  // **O destinatário vai por BSUID quando existe** (critério 9, DoD
  // «Privacidade»). O campo é `recipient` para BSUID e `to` para telefone, e a
  // ordem desta decisão é a do critério: BSUID primeiro, telefone só na falta.
  const destino =
    para.bsuid !== null ? { recipient: para.bsuid } : { to: para.telefone ?? "" };
  const base = { messaging_product: "whatsapp", ...destino };

  switch (corpo.tipo) {
    case "texto":
      return { ...base, type: "text", text: { body: corpo.texto } };
    case "botoes":
      return {
        ...base,
        type: "interactive",
        interactive: {
          type: "button",
          body: { text: corpo.texto },
          action: {
            buttons: corpo.botoes.map((botao) => ({
              type: "reply",
              reply: { id: botao.id, title: botao.titulo },
            })),
          },
        },
      };
    case "lista":
      return {
        ...base,
        type: "interactive",
        interactive: {
          type: "list",
          body: { text: corpo.texto },
          action: {
            button: corpo.titulo,
            sections: [
              {
                title: corpo.titulo,
                rows: corpo.linhas.map((linha) => ({
                  id: linha.id,
                  title: linha.titulo,
                })),
              },
            ],
          },
        },
      };
    case "template":
      return {
        ...base,
        type: "template",
        template: {
          name: corpo.nome,
          language: { code: corpo.idioma },
          components:
            corpo.parametros.length === 0
              ? []
              : [
                  {
                    type: "body",
                    parameters: corpo.parametros.map((valor) => ({
                      type: "text",
                      text: valor,
                    })),
                  },
                ],
        },
      };
  }
}

/** Um código de erro para quando a Meta não manda nenhum. */
export const CODIGO_SEM_CODIGO = -1;

/** O cliente HTTP da Graph API. */
export class ClienteDaGraph implements ClienteDaMeta {
  readonly #base: string;
  readonly #versao: string;
  readonly #token: string;
  readonly #buscar: typeof fetch;
  readonly #espera: number;

  constructor(configuracao: Configuracao) {
    this.#base = configuracao.base ?? ANFITRIAO_DA_GRAPH;
    this.#versao = configuracao.versao ?? VERSAO_DA_GRAPH;
    this.#token = configuracao.token;
    this.#buscar = configuracao.buscar ?? fetch;
    this.#espera = configuracao.esperaMaximaMs ?? ESPERA_MAXIMA_MS;
  }

  async enviar(
    phoneNumberId: string,
    para: Destinatario,
    corpo: Corpo,
  ): Promise<RespostaDaMeta> {
    const url = `${this.#base}/${this.#versao}/${phoneNumberId}/messages`;
    const controlo = new AbortController();
    const relogio = setTimeout(() => controlo.abort(), this.#espera);
    try {
      const resposta = await this.#buscar(url, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${this.#token}`,
        },
        body: JSON.stringify(corpoDaMeta(para, corpo)),
        signal: controlo.signal,
      });
      return await this.#ler(resposta);
    } catch {
      // Um `abort` ou uma falha de rede. **Não se registra a excepção aqui**:
      // a mensagem de um erro de `fetch` leva a URL, e a URL leva o
      // `phone_number_id`. Quem registra é o adapter, com o que pode registar.
      return {
        ok: false,
        codigo: CODIGO_SEM_CODIGO,
        estadoHttp: 0,
        esperar: null,
      };
    } finally {
      clearTimeout(relogio);
    }
  }

  async #ler(resposta: Response): Promise<RespostaDaMeta> {
    let corpo: unknown = null;
    try {
      corpo = await resposta.json();
    } catch {
      corpo = null;
    }
    const mapa = typeof corpo === "object" && corpo !== null ? (corpo as Record<string, unknown>) : {};

    if (resposta.ok) {
      const mensagens = mapa.messages;
      const primeira = Array.isArray(mensagens) ? mensagens[0] : null;
      const wamid =
        typeof primeira === "object" && primeira !== null
          ? (primeira as { id?: unknown }).id
          : null;
      if (typeof wamid === "string" && wamid.length > 0) {
        return { ok: true, wamid };
      }
      // Um 200 sem `wamid` não é um envio: sem o identificador não há como
      // casar os `statuses` que vêm depois, e tratá-lo como êxito deixava uma
      // linha em `sent` que nunca avança.
      return {
        ok: false,
        codigo: CODIGO_SEM_CODIGO,
        estadoHttp: resposta.status,
        esperar: null,
      };
    }

    const erro = mapa.error;
    const codigo =
      typeof erro === "object" && erro !== null && typeof (erro as { code?: unknown }).code === "number"
        ? ((erro as { code: number }).code)
        : CODIGO_SEM_CODIGO;
    // O `Retry-After` quando existe, que é o que o `01` §16 manda respeitar.
    const cabecalho = resposta.headers.get("retry-after");
    const esperar = cabecalho === null ? null : Number.parseInt(cabecalho, 10);
    return {
      ok: false,
      codigo,
      estadoHttp: resposta.status,
      esperar: esperar === null || Number.isNaN(esperar) ? null : esperar,
    };
  }
}
