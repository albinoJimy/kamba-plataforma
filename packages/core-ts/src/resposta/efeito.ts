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
 * evento não a enviaria. O efeito di-lo em vez de o esconder — `falhou` com o
 * motivo, ou `repetida_sem_envio` —, deixa a linha sem `entregue_at`, e consome
 * o evento. Reenviar uma resposta nesses casos pede uma chave derivada ou um
 * reprocessamento da linha do Outbound, e é do **KAM-226**.
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
  "repetida",
  "repetida_sem_envio",
  "recusada",
  "falhou",
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

/**
 * O efeito do consumidor `outbound`: a resposta de canal `whatsapp` sai pelo
 * `Saida` do KAM-015.
 *
 * **Uma recusa do Outbound é desfecho, e não erro.** Janela fechada, conversa
 * em modo humano (o `PreSendGuard` do KAM-018), *template* por aprovar: são
 * decisões, já registadas pelo próprio `Saida`, e nenhuma das seis tentativas as
 * muda. Uma falha de rede ou de débito também não se resolve a repetir, pela
 * semântica de cima, e sai como `falhou`. Nos dois casos o evento consome-se e
 * a linha fica sem `entregue_at`. **Só uma excepção do `enviar`** — a base em
 * baixo antes de a linha do Outbound existir — recua pela escada, e essa sim
 * envia na repetição.
 */
export function efeitoDoOutbound(enviar: EnviarResposta, opcoes: OpcoesDoEfeito = {}): Efeito {
  return async (bd: ClienteSql, envelope: Envelope) => {
    const payload = payloadDe(envelope);
    if (payload.canal !== "whatsapp") {
      opcoes.aoTratar?.("de_outro_canal");
      return;
    }
    const resposta = await respostaParaEnviar(bd, envelope.tenant_id, payload);
    if (resposta.entregueEm !== null) {
      opcoes.aoTratar?.("ja_entregue");
      return;
    }
    const resultado = await enviar(pedidoDaResposta(envelope.tenant_id, resposta));
    if (!resultado.ok) {
      const falha = (MOTIVOS_DE_FALHA as readonly string[]).includes(resultado.motivo);
      opcoes.aoTratar?.(falha ? "falhou" : "recusada", resultado.motivo);
      return;
    }
    if (resultado.repetido) {
      // A chave já tinha linha: só conta como entregue se a linha saiu.
      const { rows } = await bd.query(SQL_ESTADO_DO_ENVIO, [envelope.tenant_id, resposta.chave]);
      const estado = rows[0]?.["state"];
      if (!(ESTADOS_QUE_SAIRAM as readonly unknown[]).includes(estado)) {
        opcoes.aoTratar?.("repetida_sem_envio", typeof estado === "string" ? estado : "sem_linha");
        return;
      }
    }
    await bd.query(SQL_MARCAR_ENTREGUE, [envelope.tenant_id, resposta.replyId]);
    opcoes.aoTratar?.(resultado.repetido ? "repetida" : "enviada");
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
