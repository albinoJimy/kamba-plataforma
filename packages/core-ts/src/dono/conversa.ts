/**
 * A `OwnerPort` (KAM-223): o dono fala com o Assistente do Dono pelo painel.
 *
 * As três decisões do fundador de 2026-11-19 (bloco do KAM-217) dão a forma:
 *
 * ```text
 * painel  --texto-->  platform.agent_messages (kamba_app, tenant da sessão)
 *         --agent_invocation com message_id, persona dono-->  AGR /internal/turn
 * AGR     lê o texto pelo message_id, redige-o, corre o turno do dono
 *         --agent.replied canal painel-->  platform.agent_replies
 * lote    o consumidor `painel` marca a resposta entregue (KAM-224)
 * painel  lê as respostas entregues da conversa do dono
 * ```
 *
 * **O texto nunca viaja na invocação** (decisão do KAM-186): fica na fonte
 * persistida e o AGR lê-o pelo identificador (decisão 1, opção A). A resposta
 * sai por evento (decisão 2, opção A, KAM-224) e volta pelo canal `painel`.
 *
 * ## O mesmo `thread_id` e a mesma ToolLayer do WhatsApp
 *
 * O contacto é o `tenants.owner_contact_id`, e a conversa é a **dele** no canal
 * do tenant — a mesma linha de `platform.conversations` que o CHR usa quando o
 * dono escreve pelo WhatsApp (`UNIQUE (tenant_id, contact_id, channel_id)`).
 * Logo o `thread_id` é o mesmo (`{tenant_id}:{contact_id}`), a tranca é a mesma,
 * e o grafo é o da persona `dono`, com as mesmas tools. Uma mensagem pelo painel
 * e uma pelo WhatsApp entram na mesma *thread*.
 *
 * ## O que esta porta **não** mexe
 *
 * A janela de 24 h do WhatsApp (`last_inbound_at`, `window_expires_at`): uma
 * mensagem pelo painel não é uma mensagem do WhatsApp, e abrir a janela por ela
 * deixava o Outbound responder fora de uma janela que a Meta não abriu. A
 * conversa que esta porta cria quando o dono nunca escreveu pelo WhatsApp nasce
 * com as duas a `NULL`, que o `CHECK` da `0009` permite.
 *
 * ## O tenant é o da sessão
 *
 * Esta porta recebe o `tenantId` de quem chama, e quem chama é a rota do painel,
 * que o tira do *cookie* assinado. O contacto, a conversa, o canal e a vertical
 * lêem-se **dentro** desse tenant (`app.tenant_id`), e nenhum vem do pedido.
 */

import type { AgentInvocation, Modo } from "../chr/contrato.ts";
import { threadIdDe } from "../chr/contrato.ts";
import {
  CABECALHO_INTERNO,
  CAMINHO_DO_TURNO,
  ESPERA_MAXIMA_MS,
  desfechoDe,
  type DesfechoDoAgr,
} from "../agr/contrato.ts";

/** O canal da resposta e da mensagem que entram pelo painel. */
export const CANAL_DO_PAINEL = "painel";

/** Os canais da fonte persistida: os mesmos da `agent_replies` (KAM-224). */
export const CANAIS_DA_MENSAGEM = ["whatsapp", "painel"] as const;
export type CanalDaMensagem = (typeof CANAIS_DA_MENSAGEM)[number];

/** O tecto de uma mensagem: o de um texto da Cloud API, e o `CHECK` da coluna. */
export const MAXIMO_DA_MENSAGEM = 4096;

/**
 * O prefixo do `wamid` de um turno do painel: `painel.{message_id}`. O esquema
 * do `agent_invocation` aceita o ponto e não aceita os dois pontos, e o
 * `turn_id` do AGR é o `wamid` — a chave da resposta fica `painel.{id}:{seq}`.
 */
export const PREFIXO_DO_TURNO_DO_PAINEL = "painel.";

/**
 * Quanto a leitura com cursor volta para trás, em ms. ***Proposta***: mais do que
 * dura a transacção do consumidor que marca uma resposta entregue. Ver o
 * `SQL_LER_CONVERSA`; o painel deduplica pelo `id`.
 */
export const MARGEM_DO_CURSOR_MS = 30_000;

/** Quantas entradas da conversa uma leitura devolve, no máximo. *Proposta*. */
export const LEITURA_MAXIMA = 50;

/** A forma de um `id` de entrada (`message_id` ou `reply_id`): um uuid. */
const FORMA_DO_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** O `wa_type` com que a mensagem do painel entra: é texto, sempre. */
export const TIPO_DA_MENSAGEM_DO_PAINEL = "text";

/** O contexto do dono no seu tenant, lido como `kamba_app`. */
export interface ContextoDoDono {
  /** O `tenants.owner_contact_id`. */
  readonly contactId: string;
  readonly conversationId: string;
  readonly channelId: string;
  /** A vertical do canal (`tenant_channels.vertical`): a persona não a muda. */
  readonly vertical: string;
  readonly modo: Modo;
}

/** Porque é que não há contexto: sem dono provisionado, ou sem canal. */
export type SemContexto = "sem_dono" | "sem_canal";

/** Uma entrada da conversa, como o painel a mostra. */
export interface EntradaDaConversa {
  readonly id: string;
  readonly autor: "dono" | "assistente";
  readonly texto: string;
  readonly botoes: readonly { readonly id: string; readonly titulo: string }[];
  readonly em: Date;
}

/** O que a porta precisa. As SQL estão em `./conversa_sql.ts`. */
export interface PortasDaConversa {
  /** O dono, o canal e a conversa dele — que se abre, sem janela, se não houver. */
  contexto(tenantId: string): Promise<ContextoDoDono | SemContexto>;
  /** Grava a mensagem do dono e devolve o `message_id`. */
  gravar(pedido: {
    readonly tenantId: string;
    readonly contactId: string;
    readonly conversationId: string;
    readonly texto: string;
  }): Promise<string>;
  /** Entrega a invocação ao AGR (`InvocarAgr`, abaixo). */
  invocar(invocacao: AgentInvocation): Promise<DesfechoDaEntrega>;
  /**
   * As mensagens do dono e as respostas **entregues** pelo canal `painel`,
   * depois da entrada `depois` (um `id` da própria conversa). `null` se essa
   * entrada não é desta conversa: um `id` de outra conversa ou de outro tenant
   * não se encontra, e o painel responde 404.
   */
  ler(pedido: {
    readonly tenantId: string;
    readonly conversationId: string;
    readonly depois: string | null;
    readonly limite: number;
  }): Promise<readonly EntradaDaConversa[] | null>;
}

/** O que o AGR respondeu, com o estado HTTP. */
export interface DesfechoDaEntrega {
  readonly estado: number;
  readonly desfecho: DesfechoDoAgr | "desconhecido";
}

/** O resultado de um envio. */
export type ResultadoDoEnvio =
  | { readonly enviado: true; readonly messageId: string; readonly desfecho: DesfechoDoAgr | "desconhecido" }
  | { readonly enviado: false; readonly motivo: "texto" | SemContexto | "agr"; readonly messageId?: string };

/** O texto de uma mensagem do painel, ou `null` se não serve. */
export function textoDaMensagem(bruto: unknown): string | null {
  if (typeof bruto !== "string") return null;
  const texto = bruto.trim();
  if (texto.length === 0 || texto.length > MAXIMO_DA_MENSAGEM) return null;
  return texto;
}

/**
 * A invocação de um turno do painel. **O texto não entra**: só o identificador.
 *
 * Sem `botao`, e é o ensaio adversarial «texto que imita um botão»: um
 * `confirm:{id}` escrito no painel é texto, e o `confirmar` do AGR só lê o
 * `botao`, que só existe num `interactive` do WhatsApp.
 */
export function invocacaoDoPainel(tenantId: string, contexto: ContextoDoDono, messageId: string): AgentInvocation {
  return {
    tenant_id: tenantId,
    contact_id: contexto.contactId,
    conversation_id: contexto.conversationId,
    channel_id: contexto.channelId,
    wamid: `${PREFIXO_DO_TURNO_DO_PAINEL}${messageId}`,
    type: TIPO_DA_MENSAGEM_DO_PAINEL,
    modo: contexto.modo,
    thread_id: threadIdDe(tenantId, contexto.contactId),
    vertical: contexto.vertical,
    persona: "dono",
    message_id: messageId,
  };
}

/** A conversa do dono pelo painel. Uma instância por processo. */
export class ConversaDoDono {
  readonly #portas: PortasDaConversa;

  constructor(portas: PortasDaConversa) {
    this.#portas = portas;
  }

  /**
   * Grava a mensagem e corre o turno. A resposta não vem aqui: chega pelo
   * evento e lê-se com o `ler`.
   *
   * **A mensagem grava-se antes de se invocar**, e é isso que deixa o AGR
   * lê-la. Se o AGR falhar, a mensagem fica gravada e o dono vê-a sem resposta;
   * reenviar grava outra (é outra mensagem, com outro identificador).
   */
  async enviar(tenantId: string, bruto: unknown): Promise<ResultadoDoEnvio> {
    const texto = textoDaMensagem(bruto);
    if (texto === null) return { enviado: false, motivo: "texto" };
    const contexto = await this.#portas.contexto(tenantId);
    if (typeof contexto === "string") return { enviado: false, motivo: contexto };
    const messageId = await this.#portas.gravar({
      tenantId,
      contactId: contexto.contactId,
      conversationId: contexto.conversationId,
      texto,
    });
    const entrega = await this.#portas.invocar(invocacaoDoPainel(tenantId, contexto, messageId));
    if (entrega.estado < 200 || entrega.estado >= 300) {
      return { enviado: false, motivo: "agr", messageId };
    }
    return { enviado: true, messageId, desfecho: entrega.desfecho };
  }

  /**
   * As entradas da conversa do dono, depois da entrada `depois`. O cursor é um
   * `id` da conversa e não um instante, e é de propósito: um `id` que não é
   * desta conversa dá `nao_encontrado`, que o painel diz 404 — a sessão de A
   * com uma mensagem de B não aprende nada sobre ela.
   */
  async ler(
    tenantId: string,
    depois: string | null,
  ): Promise<readonly EntradaDaConversa[] | SemContexto | "nao_encontrado"> {
    if (depois !== null && !FORMA_DO_ID.test(depois)) return "nao_encontrado";
    const contexto = await this.#portas.contexto(tenantId);
    if (typeof contexto === "string") return contexto;
    const entradas = await this.#portas.ler({
      tenantId,
      conversationId: contexto.conversationId,
      depois,
      limite: LEITURA_MAXIMA,
    });
    return entradas ?? "nao_encontrado";
  }
}

/** A porta `invocar` sobre HTTP: o `POST /internal/turn` do AGR. */
export interface OpcoesDoInvocador {
  /** A URL base do AGR na rede interna, sem barra final (`KAMBA_AGR_URL`). */
  readonly agr: string;
  /** O `agr_painel_token`. Lido a cada pedido, porque o segredo roda. */
  readonly credencial: () => Promise<string> | string;
  /** Injectável para teste. Por omissão, o `fetch` global. */
  readonly buscar?: typeof fetch;
}

/**
 * Chama o AGR com a credencial **do painel** (`agr_painel_token`), e não com a
 * do *shim*: quem tem o `agr_internal_token` corre o turno de qualquer pessoa,
 * e o AGR só aceita o do painel num turno do dono com `message_id`.
 *
 * Uma falha de rede ou um *timeout* devolvem o estado `0`: o dono vê a mensagem
 * sem resposta e pode repetir, que é o que um painel síncrono pode fazer — não
 * há fila por trás desta chamada.
 */
export function invocadorPorHttp(opcoes: OpcoesDoInvocador): PortasDaConversa["invocar"] {
  const buscar = opcoes.buscar ?? fetch;
  return async (invocacao) => {
    const credencial = await opcoes.credencial();
    let resposta: Response;
    try {
      resposta = await buscar(`${opcoes.agr}${CAMINHO_DO_TURNO}`, {
        method: "POST",
        headers: { "content-type": "application/json", [CABECALHO_INTERNO]: credencial },
        body: JSON.stringify(invocacao),
        signal: AbortSignal.timeout(ESPERA_MAXIMA_MS),
      });
    } catch {
      return { estado: 0, desfecho: "desconhecido" };
    }
    let corpo: unknown = null;
    try {
      corpo = await resposta.json();
    } catch {
      corpo = null;
    }
    return { estado: resposta.status, desfecho: desfechoDe(corpo) };
  };
}
