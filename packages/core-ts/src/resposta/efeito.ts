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
 * a chave `chaveDoReenvio(chave)` — a do turno com o sufixo `:reenvio`. Duas
 * entradas, e as duas acabam no mesmo sítio:
 *
 * - **o `Saida` devolve uma falha** (`SEND_FAILED`, `RATE_LIMITED`): o efeito
 *   levanta `ReenvioAdiadoError`, a transacção do consumo desfaz-se, e a escada
 *   do KAM-006 repete o evento **mais tarde** — reenviar no mesmo instante a um
 *   *token bucket* sem vaga, ou a uma Meta que acabou de recusar, era gastar a
 *   única segunda vez;
 * - **o `Saida` diz `repetido` e a linha da chave não saiu** (`queued`,
 *   `failed`, ou sem linha): é a repetição de cima, ou um processo que morreu
 *   entre a linha e a rede. O efeito envia pela chave derivada.
 *
 * O envio pela chave derivada é **o último**: uma falha dele é `falhou`, e uma
 * chave derivada repetida que não saiu é `repetida_sem_envio`, os dois sem
 * `entregue_at` e com o evento consumido. **O que não muda:** uma linha que
 * saiu (`sent`, `delivered`, `read`) com a chave do turno nunca se reenvia — o
 * reenvio só nasce de uma linha que, pelo próprio `Saida`, não saiu.
 *
 * **O limite, e fica dito.** Um processo que morra depois do `200` da Meta e
 * antes de o `Saida` marcar a linha `sent` deixa-a `queued` com a mensagem já
 * entregue, e a reentrega envia pela chave derivada: o cliente recebe a resposta
 * duas vezes. A janela é uma instrução (`SQL_MARCAR_ENVIADA`), e o `statuses`
 * da Meta não a fecha, porque o `wamid` não chegou à linha. É o preço de o
 * reenvio existir; sem ele, a mesma morte deixava a resposta perdida em
 * silêncio em todos os outros casos de `queued`.
 *
 * ## Um canal sem credencial é desfecho, e não erro
 *
 * `CanalSemCredencialError` (`./credencial.ts`) chega **antes** de a linha do
 * Outbound nascer: o efeito consome o evento com `sem_credencial` e o motivo, e
 * a resposta fica sem `entregue_at`. Nenhuma tentativa faz aparecer um segredo
 * que o cofre não tem.
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

import type { Efeito } from "../eventos/consumo.ts";
import type { Envelope } from "../eventos/envelope.ts";
import type { ClienteSql } from "../eventos/publicador.ts";
import type { Corpo, Pedido, Resultado } from "../outbound/contrato.ts";
import { CanalSemCredencialError } from "./credencial.ts";
import {
  CONSUMIDOR_DO_OUTBOUND,
  CONSUMIDOR_DO_PAINEL,
  RespostaInexistenteError,
  RespostaInvalidaError,
  TIPO_DA_RESPOSTA,
  botoesDaLinha,
  lerResposta,
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
] as const;
export type DesfechoDaResposta = (typeof DESFECHOS_DA_RESPOSTA)[number];

/**
 * Os motivos do Outbound que não são uma decisão, e sim uma falha: a rede ou o
 * débito. Os outros (janela, *template*, guarda, estados) são decisões.
 */
export const MOTIVOS_DE_FALHA = ["SEND_FAILED", "RATE_LIMITED"] as const;

/** Os estados da `outbound_messages` em que a mensagem saiu para a Meta. */
export const ESTADOS_QUE_SAIRAM = ["sent", "delivered", "read"] as const;

/** O sufixo da chave do único reenvio. Ver a nota do módulo. */
export const SUFIXO_DO_REENVIO = ":reenvio";

/** A chave do reenvio de uma resposta: a do turno, com o sufixo. */
export function chaveDoReenvio(chave: string): string {
  return `${chave}${SUFIXO_DO_REENVIO}`;
}

/**
 * A primeira tentativa falhou na rede ou no débito, e a resposta reenvia-se uma
 * vez na próxima tentativa do consumo. **Não leva o texto nem a chave**: só o
 * motivo do Outbound.
 */
export class ReenvioAdiadoError extends Error {
  override readonly name = "ReenvioAdiadoError";
  readonly motivo: string;

  constructor(motivo: string) {
    super(`a resposta nao saiu (${motivo}) e reenvia-se uma vez na proxima tentativa`);
    this.motivo = motivo;
  }
}

export interface OpcoesDoEfeito {
  /** Chamado uma vez por evento aplicado, com o desfecho. Sem tenant nem texto. */
  readonly aoTratar?: (desfecho: DesfechoDaResposta, motivo?: string) => void;
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
    turnoIniciadoEm: data(l["turno_iniciado_em"]),
    entregueEm: data(l["entregue_at"]),
  };
}

/** O `Pedido` do Outbound de uma resposta. O bot envia; a chave é a do turno. */
export function pedidoDaResposta(tenantId: string, r: RespostaParaEnviar): Pedido {
  const corpo: Corpo =
    r.botoes.length === 0
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

/** Se a linha da `outbound_messages` de uma chave saiu, e o estado dela. */
async function estadoDoEnvio(
  bd: ClienteSql,
  tenantId: string,
  chave: string,
): Promise<{ readonly saiu: boolean; readonly estado: string }> {
  const { rows } = await bd.query(SQL_ESTADO_DO_ENVIO, [tenantId, chave]);
  const estado = rows[0]?.["state"];
  return {
    saiu: (ESTADOS_QUE_SAIRAM as readonly unknown[]).includes(estado),
    estado: typeof estado === "string" ? estado : "sem_linha",
  };
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

/**
 * O efeito do consumidor `outbound`: a resposta de canal `whatsapp` sai pelo
 * `Saida` do KAM-015.
 *
 * **Uma recusa do Outbound é desfecho, e não erro.** Janela fechada, conversa
 * em modo humano (o `PreSendGuard` do KAM-018), *template* por aprovar: são
 * decisões, já registadas pelo próprio `Saida`, e nenhuma das seis tentativas as
 * muda. Um canal sem credencial também (`sem_credencial`). **Uma falha de rede
 * ou de débito** levanta `ReenvioAdiadoError`, e a próxima tentativa reenvia
 * pela chave derivada — ver a nota do módulo. **Uma excepção do `enviar`** — a
 * base em baixo — recua pela escada, e a repetição trata a linha que tiver
 * ficado.
 */
export function efeitoDoOutbound(enviar: EnviarResposta, opcoes: OpcoesDoEfeito = {}): Efeito {
  return async (bd: ClienteSql, envelope: Envelope) => {
    const payload = payloadDe(envelope);
    if (payload.canal !== "whatsapp") {
      opcoes.aoTratar?.("de_outro_canal");
      return;
    }
    const tenantId = envelope.tenant_id;
    const resposta = await respostaParaEnviar(bd, tenantId, payload);
    if (resposta.entregueEm !== null) {
      opcoes.aoTratar?.("ja_entregue");
      return;
    }
    const pedido = pedidoDaResposta(tenantId, resposta);
    const resultado = await tentar(enviar, pedido);
    if (resultado instanceof CanalSemCredencialError) {
      opcoes.aoTratar?.("sem_credencial", resultado.motivo);
      return;
    }
    if (!resultado.ok) {
      if (eFalha(resultado.motivo)) throw new ReenvioAdiadoError(resultado.motivo);
      opcoes.aoTratar?.("recusada", resultado.motivo);
      return;
    }
    if (resultado.repetido && !(await estadoDoEnvio(bd, tenantId, pedido.idempotencyKey)).saiu) {
      // A chave do turno já tinha linha, e a linha não saiu: o único reenvio.
      const reenvio = { ...pedido, idempotencyKey: chaveDoReenvio(pedido.idempotencyKey) };
      await reenviar(bd, enviar, reenvio, resposta.replyId, opcoes);
      return;
    }
    await bd.query(SQL_MARCAR_ENTREGUE, [tenantId, resposta.replyId]);
    opcoes.aoTratar?.(resultado.repetido ? "repetida" : "enviada");
  };
}

/** O envio pela chave derivada. É o último: nada aqui volta a adiar. */
async function reenviar(
  bd: ClienteSql,
  enviar: EnviarResposta,
  pedido: Pedido,
  replyId: string,
  opcoes: OpcoesDoEfeito,
): Promise<void> {
  const resultado = await tentar(enviar, pedido);
  if (resultado instanceof CanalSemCredencialError) {
    opcoes.aoTratar?.("sem_credencial", resultado.motivo);
    return;
  }
  if (!resultado.ok) {
    opcoes.aoTratar?.(eFalha(resultado.motivo) ? "falhou" : "recusada", resultado.motivo);
    return;
  }
  if (resultado.repetido) {
    const envio = await estadoDoEnvio(bd, pedido.tenantId, pedido.idempotencyKey);
    if (!envio.saiu) {
      opcoes.aoTratar?.("repetida_sem_envio", envio.estado);
      return;
    }
  }
  await bd.query(SQL_MARCAR_ENTREGUE, [pedido.tenantId, replyId]);
  opcoes.aoTratar?.(resultado.repetido ? "repetida" : "reenviada");
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
