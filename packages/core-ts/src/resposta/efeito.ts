/**
 * Os dois efeitos da resposta do AGR (KAM-224), para o `consumir` do KAM-006.
 *
 * Cada consumidor recebe **todos** os `agent.replied` e aplica só o seu canal: o
 * de outro canal consome-se sem efeito, que é a marca a dizer «este não era
 * meu». Os dois correm com a ligação da transacção do consumo, sob a RLS do
 * tenant do envelope.
 *
 * ## A idempotência, às duas camadas
 *
 * A reentrega do **mesmo** evento pára no `events_consumed` (o duplicado do
 * KAM-006). Um **segundo** evento com a mesma resposta não existe — o AGR só
 * emite quando a linha nasce —, mas se existisse parava no `entregue_at` e, no
 * WhatsApp, na chave do `Saida` (`outbound_messages`, `ON CONFLICT DO NOTHING`):
 * a chave do envio **é** a `agent_replies.chave` do turno.
 *
 * ## «No máximo uma vez», e é a semântica do `Saida`
 *
 * A chave do envio é a do turno, e o `Saida` do KAM-015 nunca chama a Meta duas
 * vezes com a mesma chave — nem quando a primeira chamada falhou. Por isso uma
 * falha de rede depois de esgotadas as repetições do próprio `Saida`
 * (`SEND_FAILED`), o *token bucket* sem vaga (`RATE_LIMITED`), ou um processo
 * que morra entre a linha e a rede, deixam a resposta **por enviar**: repetir o
 * evento não a enviaria com a chave do turno.
 *
 * ## O reenvio, uma vez, por uma chave derivada (KAM-227, critério 5)
 *
 * Uma resposta que a chave do turno deixou por enviar reenvia-se **uma vez**, com
 * a chave `chaveDoReenvio(chave)` — a do turno com o sufixo `:reenvio` —, e
 * **só quando se sabe que a mensagem não saiu**. Duas entradas:
 *
 * - **o `Saida` devolve uma falha que não saiu**: o *token bucket* sem vaga
 *   (`RATE_LIMITED`, sem chamada HTTP) ou uma recusa da Meta com código
 *   (`SEND_FAILED` com um `error.code` que não é ambíguo). O efeito levanta
 *   `ReenvioAdiadoError`, que é um `Adiar` do KAM-006 de **60 s** (*proposta*):
 *   a transacção do consumo desfaz-se e a fila devolve o evento um minuto
 *   depois, que é a janela mais longa do *token bucket* (o tecto por minuto do
 *   par). Reenviar ao primeiro degrau da escada, um segundo depois, gastava a
 *   única segunda vez no mesmo tecto;
 * - **o `Saida` diz `repetido` e a linha da chave não saiu e pode reenviar-se**
 *   (`podeReenviar`): sem linha, `queued` sem `wamid`, ou `failed` sem `wamid` e
 *   com um código que não é ambíguo. O efeito envia pela chave derivada.
 *
 * **Uma falha ambígua não se reenvia**, e é `falhou`: o `CODIGO_SEM_CODIGO` do
 * cliente da Graph (*timeout*, rede, um `200` sem `wamid`) e os erros internos da
 * Meta (`1`, `2`), que o `Saida` já repetiu — em qualquer dos três a Meta pode
 * ter aceitado a mensagem. **Uma linha com `wamid` nunca se reenvia**, esteja no
 * estado que estiver: o `wamid` é a prova de que a Meta a aceitou, e um
 * `statuses` posterior pode passá-la de `sent` a `failed` (a entrega falhou), o
 * que não a faz «não ter saído».
 *
 * O envio pela chave derivada é **o último**: uma falha dele é `falhou`, e uma
 * chave derivada repetida que não saiu é `repetida_sem_envio`, os dois sem
 * `entregue_at` e com o evento consumido.
 *
 * **O limite, e fica dito.** Um processo que morra depois do `200` da Meta e
 * antes de o `Saida` marcar a linha `sent` deixa-a `queued` **sem** `wamid` com
 * a mensagem já entregue, e a reentrega envia pela chave derivada: o cliente
 * recebe a resposta duas vezes. A janela é uma instrução (`SQL_MARCAR_ENVIADA`),
 * e o `statuses` da Meta não a fecha, porque o `wamid` não chegou à linha. O
 * critério manda reenviar o `queued`, e é o preço de o reenvio existir: sem ele,
 * a mesma morte deixava a resposta perdida em silêncio.
 *
 * ## Um canal sem credencial é desfecho, e não erro
 *
 * `CanalSemCredencialError` (`./credencial.ts`) chega **antes** de a linha do
 * Outbound nascer: o efeito consome o evento com `sem_credencial` e o motivo, e
 * a resposta fica sem `entregue_at`. Nenhuma tentativa faz aparecer um segredo
 * que o cofre não tem.
 *
 * ## A imagem sai antes do texto, e cada uma com a sua chave (KAM-246)
 *
 * Uma resposta com `media_ref` são **duas** mensagens: a imagem, com a chave
 * `chaveDaImagem(chave)`, e depois o texto e os botões, com a chave do turno. A
 * legenda e a nota de IA vão no texto, que se copia. Antes de ler o STO, a chave
 * tem de ser do tenant do envelope e da classe `arte` (`arte.ts`): senão a
 * resposta inteira é `arte_recusada`, com **0** bytes à Meta, e não se repete.
 *
 * Cada mensagem passa pelo mesmo caminho (`enviarUma`): o reenvio único pela
 * chave derivada, e o `ReenvioAdiadoError` quando se sabe que não saiu. **Uma
 * imagem que se sabe não ter saído adia a resposta inteira**, e o texto não sai
 * antes dela; na volta seguinte, a imagem que já saiu não se lê nem se envia
 * outra vez (a linha da chave dela diz que saiu). Uma imagem que não sai por
 * outra razão (ambígua, recusada) fica registada na `outbound_messages` e no
 * desfecho `imagem_nao_enviada`, e o texto segue: a arte fica na página do
 * painel. O `entregue_at` marca-se pelo texto, como antes.
 *
 * **Um objecto que já não existe no STO** (a retenção da classe `arte` apagou-o)
 * também não prende o texto: nenhuma tentativa o traz de volta, e a legenda é
 * o que o dono copia. Sai o texto, sem a imagem, com o desfecho
 * `imagem_nao_enviada:arte_inexistente`. Qualquer outra falha do STO (em baixo,
 * uma resposta sem forma) recua pela escada, como uma falha da base.
 *
 * ## O `Saida` corre noutra ligação, e porquê
 *
 * O `Saida` do KAM-015 grava a linha **antes** da rede, em *autocommit*, e é isso
 * que o torna idempotente. Dentro da transacção do consumo, a linha só ficava
 * com o `COMMIT` do consumo: um processo que morresse depois do `200` da Meta e
 * antes do `COMMIT` perdia a linha, e a reentrega enviava outra vez. Por isso o
 * envio é uma porta (`EnviarResposta`) que quem monta o processo liga a uma
 * ligação própria (`envioPeloSaida`).
 */

import { Adiar, type Efeito } from "../eventos/consumo.ts";
import type { Envelope } from "../eventos/envelope.ts";
import type { ClienteSql } from "../eventos/publicador.ts";
import { CODIGO_SEM_CODIGO } from "../outbound/cliente.ts";
import { IDIOMA_BASE, type Corpo, type Pedido, type Resultado } from "../outbound/contrato.ts";
import { ObjectoInexistenteError } from "../storage/port.ts";
import { ArteRecusadaError, chaveDaArte, type LerArte } from "./arte.ts";
import { CanalSemCredencialError } from "./credencial.ts";
import {
  CONSUMIDOR_DO_OUTBOUND,
  CONSUMIDOR_DO_PAINEL,
  RespostaInexistenteError,
  RespostaInvalidaError,
  TIPO_DA_RESPOSTA,
  botoesDaLinha,
  lerResposta,
  templateDaLinha,
  type PayloadDaResposta,
  type RespostaParaEnviar,
} from "./contrato.ts";
import {
  SQL_ESTADO_DO_ENVIO,
  SQL_MARCAR_ENTREGUE,
  SQL_RESPOSTA_DO_PAINEL,
  SQL_RESPOSTA_DO_WHATSAPP,
} from "./sql.ts";

/** O envio de um pedido ao Outbound. Em produção, `envioPeloSaida`. */
export type EnviarResposta = (pedido: Pedido) => Promise<Resultado>;

/** O que aconteceu a uma resposta, para a métrica e o registo de quem monta. */
export const DESFECHOS_DA_RESPOSTA = [
  "enviada",
  "reenviada",
  "repetida",
  "repetida_sem_envio",
  "recusada",
  "falhou",
  "sem_credencial",
  "entregue_ao_painel",
  "ja_entregue",
  "de_outro_canal",
  // KAM-246: a imagem de uma resposta com média, que se conta à parte do texto.
  "imagem_enviada",
  "imagem_nao_enviada",
  "arte_recusada",
] as const;
export type DesfechoDaResposta = (typeof DESFECHOS_DA_RESPOSTA)[number];

/**
 * Os motivos do Outbound que não são uma decisão, e sim uma falha: a rede ou o
 * débito. Os outros (janela, *template*, guarda, estados) são decisões.
 */
export const MOTIVOS_DE_FALHA = ["SEND_FAILED", "RATE_LIMITED"] as const;

/** Os estados da `outbound_messages` em que a mensagem saiu para a Meta. */
export const ESTADOS_QUE_SAIRAM = ["sent", "delivered", "read"] as const;

/**
 * Os códigos de uma falha **ambígua**: a Meta pode ter aceitado a mensagem.
 * `CODIGO_SEM_CODIGO` é o do cliente da Graph sem resposta legível (*timeout*,
 * rede, `200` sem `wamid`); `1` e `2` são os erros internos que o `Saida` já
 * repete (`CODIGOS_QUE_SE_REPETEM`, sem o `130429`, que é uma recusa de débito).
 */
export const CODIGOS_AMBIGUOS: readonly number[] = [CODIGO_SEM_CODIGO, 1, 2];

/** A espera do reenvio, em segundos: a janela por minuto do *token bucket*. *Proposta*. */
export const ESPERA_DO_REENVIO_S = 60;

/** O sufixo da chave do único reenvio. Ver a nota do módulo. */
export const SUFIXO_DO_REENVIO = ":reenvio";

/** A chave do reenvio de uma resposta: a do turno, com o sufixo. */
export function chaveDoReenvio(chave: string): string {
  return `${chave}${SUFIXO_DO_REENVIO}`;
}

/** O sufixo da chave da imagem de uma resposta com média (KAM-246). */
export const SUFIXO_DA_IMAGEM = ":imagem";

/** A chave da imagem de uma resposta. O reenvio dela é o `chaveDoReenvio` desta. */
export function chaveDaImagem(chave: string): string {
  return `${chave}${SUFIXO_DA_IMAGEM}`;
}

/**
 * O processo não tem leitor do STO, e a resposta tem imagem. É configuração e
 * não desfecho: recua pela escada e vai à DLQ, e o texto não sai sem a imagem.
 * Em produção o `efeitoDoConsumidor` não monta o `outbound` sem o leitor.
 */
export class ArteSemLeitorError extends Error {
  override readonly name = "ArteSemLeitorError";

  constructor() {
    super("a resposta tem imagem e o consumidor nao tem leitor do STO");
  }
}

/**
 * A primeira tentativa não saiu, e sabe-se que não saiu: a resposta reenvia-se
 * uma vez, `ESPERA_DO_REENVIO_S` depois. É um `Adiar` do KAM-006, e não um erro:
 * a fila devolve o evento com o atraso dele, e, esgotadas as tentativas, a DLQ
 * diz `adiado_sem_resolver` com o motivo. **Não leva o texto nem a chave**.
 */
export class ReenvioAdiadoError extends Adiar {
  readonly motivo: string;

  constructor(motivo: string) {
    super(ESPERA_DO_REENVIO_S, `a resposta nao saiu (${motivo}) e reenvia-se uma vez`);
    this.name = "ReenvioAdiadoError";
    this.motivo = motivo;
  }
}

export interface OpcoesDoEfeito {
  /**
   * Chamado uma vez por mensagem tratada, com o desfecho: uma vez por evento
   * aplicado, e duas numa resposta com imagem (a imagem e o texto). Sem tenant
   * nem texto.
   */
  readonly aoTratar?: (desfecho: DesfechoDaResposta, motivo?: string) => void;
  /** O JPEG da arte (`arteDoSto`, em produção). Só o `outbound` o usa. */
  readonly lerArte?: LerArte;
}

function data(v: unknown): Date | null {
  if (v === null || v === undefined) return null;
  return v instanceof Date ? v : new Date(String(v));
}

function payloadDe(envelope: Envelope): PayloadDaResposta {
  if (envelope.tipo !== TIPO_DA_RESPOSTA) {
    throw new RespostaInvalidaError(`tipo ${envelope.tipo} nao e ${TIPO_DA_RESPOSTA}`);
  }
  return lerResposta(envelope.tenant_id, envelope.payload);
}

function mediaDaLinha(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v !== "string" || v === "") throw new RespostaInvalidaError("media_ref sem forma");
  return v;
}

/** A linha do WhatsApp, lida e trancada na transacção do consumo. */
export async function respostaParaEnviar(
  bd: ClienteSql,
  tenantId: string,
  payload: PayloadDaResposta,
): Promise<RespostaParaEnviar> {
  const { rows } = await bd.query(SQL_RESPOSTA_DO_WHATSAPP, [
    tenantId,
    payload.replyId,
    payload.conversationId,
  ]);
  const l = rows[0];
  if (l === undefined) throw new RespostaInexistenteError();
  if (String(l["contact_id"]) !== payload.contactId) {
    throw new RespostaInvalidaError("contact_id do evento nao e o da linha");
  }
  return {
    replyId: String(l["reply_id"]),
    chave: String(l["chave"]),
    contactId: String(l["contact_id"]),
    conversationId: String(l["conversation_id"]),
    channelId: String(l["channel_id"]),
    phoneNumberId: String(l["phone_number_id"]),
    texto: String(l["texto"]),
    botoes: botoesDaLinha(l["botoes"]),
    template: templateDaLinha(l["template_nome"], l["template_parametros"]),
    mediaRef: mediaDaLinha(l["media_ref"]),
    turnoIniciadoEm: data(l["turno_iniciado_em"]),
    entregueEm: data(l["entregue_at"]),
  };
}

/**
 * O `Pedido` do Outbound de uma resposta. O bot envia; a chave é a do turno.
 *
 * **O corpo é o que a linha diz** (KAM-221, opção A da coordenação do lote
 * 13): com `template_nome`, um corpo de *template* com os valores dos
 * parâmetros pela ordem; sem ele, o texto ou os botões. O consumidor **nunca
 * troca sozinho**: uma resposta de texto que o `Saida` recusa com a janela
 * fechada sai como `recusada`, e quem a volta a emitir com o *template* é o
 * AGR, na volta seguinte do *job* (`reemitir_pela_janela`).
 */
export function pedidoDaResposta(tenantId: string, r: RespostaParaEnviar): Pedido {
  const corpo: Corpo =
    r.template !== null
      ? {
          tipo: "template",
          nome: r.template.nome,
          idioma: IDIOMA_BASE,
          parametros: r.template.parametros,
        }
      : r.botoes.length === 0
        ? { tipo: "texto", texto: r.texto }
        : { tipo: "botoes", texto: r.texto, botoes: r.botoes };
  return {
    tenantId,
    channelId: r.channelId,
    contactId: r.contactId,
    conversationId: r.conversationId,
    phoneNumberId: r.phoneNumberId,
    idempotencyKey: r.chave,
    corpo,
    doBot: true,
    ...(r.turnoIniciadoEm === null ? {} : { turnoIniciadoEm: r.turnoIniciadoEm }),
  };
}

/** Um código de falha ambíguo: a Meta pode ter aceitado. Ver `CODIGOS_AMBIGUOS`. */
export function eAmbiguo(codigo: number | null | undefined): boolean {
  return codigo !== null && codigo !== undefined && CODIGOS_AMBIGUOS.includes(codigo);
}

/** O que a linha da `outbound_messages` de uma chave diz do envio. */
export interface EstadoDoEnvio {
  /** Saiu e está entregue à Meta: `sent`, `delivered` ou `read`. Marca-se. */
  readonly saiu: boolean;
  /** Sabe-se que não saiu, e um reenvio não pode duplicar nada. */
  readonly podeReenviar: boolean;
  /** O estado, para o motivo do desfecho. */
  readonly estado: string;
}

/**
 * A decisão sobre uma linha da `outbound_messages`. Exportada para se ensaiar
 * pela tabela. Ver a nota do módulo: o `wamid` manda sobre o estado.
 */
export function decidirEnvio(linha: Record<string, unknown> | undefined): EstadoDoEnvio {
  if (linha === undefined) return { saiu: false, podeReenviar: true, estado: "sem_linha" };
  const estado = typeof linha["state"] === "string" ? linha["state"] : "desconhecido";
  const saiu = (ESTADOS_QUE_SAIRAM as readonly unknown[]).includes(estado);
  const comWamid = linha["wamid"] !== null && linha["wamid"] !== undefined;
  const codigo = linha["error_code"];
  const ambiguo = eAmbiguo(typeof codigo === "number" ? codigo : codigo === null || codigo === undefined ? null : Number(codigo));
  const podeReenviar =
    !saiu && !comWamid && (estado === "queued" || (estado === "failed" && !ambiguo));
  return { saiu, podeReenviar, estado: ambiguo && estado === "failed" ? "failed_ambiguo" : estado };
}

async function estadoDoEnvio(bd: ClienteSql, tenantId: string, chave: string): Promise<EstadoDoEnvio> {
  const { rows } = await bd.query(SQL_ESTADO_DO_ENVIO, [tenantId, chave]);
  return decidirEnvio(rows[0]);
}

/** O resultado de um envio, ou a falta de credencial do canal. */
async function tentar(
  enviar: EnviarResposta,
  pedido: Pedido,
): Promise<Resultado | CanalSemCredencialError> {
  try {
    return await enviar(pedido);
  } catch (erro) {
    if (erro instanceof CanalSemCredencialError) return erro;
    throw erro;
  }
}

function eFalha(motivo: string): boolean {
  return (MOTIVOS_DE_FALHA as readonly string[]).includes(motivo);
}

/** Uma falha do `Saida` de que se sabe que não saiu: débito nosso, ou recusa com código. */
function naoSaiu(resultado: { readonly motivo: string; readonly codigo: number | null }): boolean {
  return eFalha(resultado.motivo) && !eAmbiguo(resultado.codigo);
}

/** O desfecho de uma mensagem: saiu (e como), ou não saiu (e porquê). */
type DesfechoDeUma =
  | { readonly saiu: true; readonly desfecho: "enviada" | "reenviada" | "repetida" }
  | {
      readonly saiu: false;
      readonly desfecho: "recusada" | "falhou" | "sem_credencial" | "repetida_sem_envio";
      readonly motivo: string;
    };

/**
 * Uma mensagem pelo `Saida`, com o reenvio único do KAM-227. Levanta
 * `ReenvioAdiadoError` quando a primeira tentativa se sabe não ter saído.
 */
async function enviarUma(bd: ClienteSql, enviar: EnviarResposta, pedido: Pedido): Promise<DesfechoDeUma> {
  const resultado = await tentar(enviar, pedido);
  if (resultado instanceof CanalSemCredencialError) {
    return { saiu: false, desfecho: "sem_credencial", motivo: resultado.motivo };
  }
  if (!resultado.ok) {
    if (naoSaiu(resultado)) throw new ReenvioAdiadoError(resultado.motivo);
    return { saiu: false, desfecho: eFalha(resultado.motivo) ? "falhou" : "recusada", motivo: resultado.motivo };
  }
  if (resultado.repetido) {
    const envio = await estadoDoEnvio(bd, pedido.tenantId, pedido.idempotencyKey);
    if (envio.podeReenviar) {
      // A chave já tinha linha, e sabe-se que não saiu: o único reenvio.
      return reenviar(bd, enviar, { ...pedido, idempotencyKey: chaveDoReenvio(pedido.idempotencyKey) });
    }
    if (!envio.saiu) return { saiu: false, desfecho: "repetida_sem_envio", motivo: envio.estado };
  }
  return { saiu: true, desfecho: resultado.repetido ? "repetida" : "enviada" };
}

/** O envio pela chave derivada. É o último: nada aqui volta a adiar. */
async function reenviar(bd: ClienteSql, enviar: EnviarResposta, pedido: Pedido): Promise<DesfechoDeUma> {
  const resultado = await tentar(enviar, pedido);
  if (resultado instanceof CanalSemCredencialError) {
    return { saiu: false, desfecho: "sem_credencial", motivo: resultado.motivo };
  }
  if (!resultado.ok) {
    return { saiu: false, desfecho: eFalha(resultado.motivo) ? "falhou" : "recusada", motivo: resultado.motivo };
  }
  if (resultado.repetido) {
    const envio = await estadoDoEnvio(bd, pedido.tenantId, pedido.idempotencyKey);
    if (!envio.saiu) return { saiu: false, desfecho: "repetida_sem_envio", motivo: envio.estado };
  }
  return { saiu: true, desfecho: resultado.repetido ? "repetida" : "reenviada" };
}

/** O `Pedido` da imagem de uma resposta: o do texto, com o JPEG e a chave da imagem. */
export function pedidoDaImagem(pedido: Pedido, jpeg: Uint8Array): Pedido {
  return { ...pedido, idempotencyKey: chaveDaImagem(pedido.idempotencyKey), corpo: { tipo: "imagem", jpeg } };
}

/**
 * A imagem de uma resposta com média, antes do texto. Devolve `false` quando a
 * resposta inteira se recusa (a arte não serve), e o texto não sai.
 */
async function enviarImagem(
  bd: ClienteSql,
  enviar: EnviarResposta,
  pedido: Pedido,
  mediaRef: string,
  opcoes: OpcoesDoEfeito,
): Promise<boolean> {
  let jpeg: Uint8Array;
  try {
    // A chave confere-se antes de tudo, e sem o leitor: 0 bytes à Meta.
    chaveDaArte(pedido.tenantId, mediaRef);
    // Uma imagem que já saiu numa volta anterior não se lê nem se envia.
    const { rows } = await bd.query(SQL_ESTADO_DO_ENVIO, [pedido.tenantId, chaveDaImagem(pedido.idempotencyKey)]);
    if (rows[0] !== undefined && decidirEnvio(rows[0]).saiu) {
      opcoes.aoTratar?.("imagem_enviada", "repetida");
      return true;
    }
    if (opcoes.lerArte === undefined) throw new ArteSemLeitorError();
    jpeg = await opcoes.lerArte(pedido.tenantId, mediaRef);
  } catch (erro) {
    if (erro instanceof ArteRecusadaError) {
      opcoes.aoTratar?.("arte_recusada", erro.motivo);
      return false;
    }
    // Ver a nota do módulo: o objecto já não existe, e o texto sai sem ele.
    if (erro instanceof ObjectoInexistenteError) {
      opcoes.aoTratar?.("imagem_nao_enviada", "arte_inexistente");
      return true;
    }
    throw erro;
  }
  const imagem = await enviarUma(bd, enviar, pedidoDaImagem(pedido, jpeg));
  if (imagem.saiu) opcoes.aoTratar?.("imagem_enviada", imagem.desfecho);
  else opcoes.aoTratar?.("imagem_nao_enviada", `${imagem.desfecho}:${imagem.motivo}`);
  return true;
}

/**
 * O efeito do consumidor `outbound`: a resposta de canal `whatsapp` sai pelo
 * `Saida` do KAM-015.
 *
 * **Uma recusa do Outbound é desfecho, e não erro.** Janela fechada, conversa
 * em modo humano (o `PreSendGuard` do KAM-018), *template* por aprovar: são
 * decisões, já registadas pelo próprio `Saida`, e nenhuma das seis tentativas as
 * muda. Um canal sem credencial também (`sem_credencial`). **Uma falha que não
 * saiu** adia (`ReenvioAdiadoError`), e a próxima tentativa reenvia pela chave
 * derivada; **uma falha ambígua** é `falhou` e não se reenvia — ver a nota do
 * módulo. **Uma excepção do `enviar`** — a base em baixo — recua pela escada, e
 * a repetição trata a linha que tiver ficado.
 *
 * Com `media_ref`, a imagem sai primeiro (KAM-246): ver «A imagem sai antes do
 * texto» na nota do módulo.
 */
export function efeitoDoOutbound(enviar: EnviarResposta, opcoes: OpcoesDoEfeito = {}): Efeito {
  return async (bd: ClienteSql, envelope: Envelope) => {
    const payload = payloadDe(envelope);
    if (payload.canal !== "whatsapp") {
      opcoes.aoTratar?.("de_outro_canal");
      return;
    }
    const resposta = await respostaParaEnviar(bd, envelope.tenant_id, payload);
    const tenantId = envelope.tenant_id;
    if (resposta.entregueEm !== null) {
      opcoes.aoTratar?.("ja_entregue");
      return;
    }
    const pedido = pedidoDaResposta(tenantId, resposta);
    if (resposta.mediaRef !== null) {
      // A base recusa a linha (o `CHECK` da revisão do KAM-246); esta é a outra metade.
      if (resposta.template !== null) throw new RespostaInvalidaError("media com template");
      if (!(await enviarImagem(bd, enviar, pedido, resposta.mediaRef, opcoes))) return;
    }
    const texto = await enviarUma(bd, enviar, pedido);
    if (!texto.saiu) {
      opcoes.aoTratar?.(texto.desfecho, texto.motivo);
      return;
    }
    await bd.query(SQL_MARCAR_ENTREGUE, [tenantId, resposta.replyId]);
    opcoes.aoTratar?.(texto.desfecho);
  };
}

/**
 * O efeito do consumidor `painel`: a resposta de canal `painel` fica entregue.
 *
 * A decisão 1 do fundador de 2026-11-19 (bloco do KAM-217) põe a resposta a
 * voltar ao painel pelo canal `painel`, e o `onboarding-web` lê-a pelo
 * `thread_id`. O texto já está na `agent_replies`; o que este consumidor faz é
 * dizer que a resposta chegou ao destino, uma vez, e é isso que o painel lê —
 * a rota que a mostra é a `OwnerPort` do **KAM-223**.
 */
export function efeitoDoPainel(opcoes: OpcoesDoEfeito = {}): Efeito {
  return async (bd: ClienteSql, envelope: Envelope) => {
    const payload = payloadDe(envelope);
    if (payload.canal !== "painel") {
      opcoes.aoTratar?.("de_outro_canal");
      return;
    }
    const { rows } = await bd.query(SQL_RESPOSTA_DO_PAINEL, [
      envelope.tenant_id,
      payload.replyId,
      payload.conversationId,
    ]);
    const linha = rows[0];
    if (linha === undefined) throw new RespostaInexistenteError();
    if (linha["entregue_at"] !== null && linha["entregue_at"] !== undefined) {
      opcoes.aoTratar?.("ja_entregue");
      return;
    }
    await bd.query(SQL_MARCAR_ENTREGUE, [envelope.tenant_id, payload.replyId]);
    opcoes.aoTratar?.("entregue_ao_painel");
  };
}

/** O consumidor de cada canal, para quem monta o processo pelo nome. */
export const CONSUMIDORES_DA_RESPOSTA = {
  whatsapp: CONSUMIDOR_DO_OUTBOUND,
  painel: CONSUMIDOR_DO_PAINEL,
} as const;
