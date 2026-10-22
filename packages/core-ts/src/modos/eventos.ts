/**
 * A emissão de `conversation.mode_changed` (KAM-018, critério 6).
 *
 * A forma é a do `chr/eventos.ts`: mapeia o que temos para o payload que o
 * contrato publicado exige, valida-o **antes** de qualquer escrita, e chama
 * `platform.evt_emitir` com o papel `kamba_app` e contexto de tenant.
 *
 * ## O tipo já existia, e a carga dele não chega
 *
 * O critério 6 escreve «(tipo acrescentado ao catálogo, KAM-007)». Fui ver:
 * `contratos/eventos/conversation.mode_changed/` **existe**, com `v1` e `v2`, e
 * nenhuma das duas é deste ticket — são do KAM-007/KAM-159. Portanto não há
 * nada a acrescentar, e dizê-lo é melhor do que inventar um contrato novo.
 *
 * O que **não** chega é o domínio: a carga é `{thread_id, channel_mode}` com
 * `channel_mode ∈ {ai, humano, desligado}` e `additionalProperties: false`, e os
 * nossos modos são **quatro**. O `dono` e o `humano` saem os dois como `humano`,
 * e um consumidor do barramento não os distingue. A correspondência e a razão de
 * cada linha estão em `MODO_PARA_CHANNEL_MODE`; a decisão de criar (ou não) uma
 * `v3` de quatro valores é do KAM-007 e devolve-se a quem escreveu o critério.
 *
 * ## A validação corre **antes** do SQL
 *
 * É a regra do KAM-007 (`eventos/contratos.ts`): o `evt_emitir` grava o envelope
 * e **não** valida o payload contra o contrato. Validar depois é descobrir o
 * defeito com o evento já publicado.
 *
 * ## Privacidade
 *
 * O payload não leva telefone, BSUID, `display_name` nem conteúdo — é o DoD
 * «Privacidade» do ticket e o ADR-010. O `thread_id` é `{tenant_id}:{contact_id}`
 * (dicionário §3.1): dois UUID, e o `contact_id` é a referência opaca que o
 * KAM-008 criou precisamente para não se usar o telefone. O `agregado.id` é o
 * `conversation_id`, também um UUID nosso.
 */

import type { PayloadConversationModeChangedV2 } from "@kamba/contracts";

import { threadIdDe } from "../chr/contrato.ts";
import { validarPayload } from "../eventos/contratos.ts";
import {
  AGREGADO_MODE_CHANGED,
  type ClienteSql,
  MODO_PARA_CHANNEL_MODE,
  type Modo,
  TIPO_MODE_CHANGED,
  VERSAO_MODE_CHANGED,
} from "./contrato.ts";
import { SQL_EMITIR_MODE_CHANGED } from "./consultas.ts";

export { threadIdDe };

/**
 * O payload do contrato publicado, a partir de um modo nosso.
 *
 * Exportada e testada à parte porque é aqui que vive a perda: `dono` e `humano`
 * colapsam num `humano`, e uma tabela que mapeasse `dono` para `desligado`
 * publicava «não há ninguém a falar» sobre uma conversa em que o dono está a
 * falar. Ver `MODO_PARA_CHANNEL_MODE`.
 */
export function payloadDoModo(
  threadId: string,
  modo: Modo,
): PayloadConversationModeChangedV2 {
  const channelMode = MODO_PARA_CHANNEL_MODE[modo];
  return {
    thread_id: threadId,
    channel_mode: channelMode as PayloadConversationModeChangedV2["channel_mode"],
  };
}

/**
 * Emite o `conversation.mode_changed`. Devolve o `event_id`.
 *
 * Corre na transacção de quem chama — é o que a assinatura do `cliente`
 * garante — e por isso o evento e a mudança de modo confirmam juntos.
 *
 * @throws {PayloadInvalidoError} se o payload não bater com o contrato, e isso é
 *   antes de qualquer escrita.
 */
export async function emitirModoMudado(
  cliente: ClienteSql,
  tenantId: string,
  conversationId: string,
  threadId: string,
  modo: Modo,
): Promise<string> {
  const payload = payloadDoModo(threadId, modo);
  validarPayload(TIPO_MODE_CHANGED, VERSAO_MODE_CHANGED, payload);
  const resultado = await cliente.query(SQL_EMITIR_MODE_CHANGED, [
    TIPO_MODE_CHANGED,
    VERSAO_MODE_CHANGED,
    tenantId,
    AGREGADO_MODE_CHANGED,
    conversationId,
    JSON.stringify(payload),
  ]);
  const id = resultado.rows[0]?.event_id;
  if (typeof id !== "string") {
    throw new Error(
      "platform.evt_emitir nao devolveu um event_id: o evento " +
        "`conversation.mode_changed` pode nao ter sido escrito no outbox",
    );
  }
  return id;
}
