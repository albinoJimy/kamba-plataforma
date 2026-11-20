/**
 * As instruções dos dois consumidores da resposta do AGR (KAM-224).
 *
 * Correm **dentro** da transacção do consumo do KAM-006, como `kamba_app`, com o
 * `app.tenant_id` do envelope: a `agent_replies`, a `conversations` e a
 * `tenant_channels` têm RLS `FORCE`, e a linha de outro tenant não se vê.
 */

/**
 * A resposta de canal `whatsapp`, com o canal e o `phone_number_id` da conversa.
 *
 * Com o *template* que o AGR escolheu, quando o escolheu (`template_nome` e
 * `template_parametros`, revisão `0076` do KAM-221).
 *
 * O `tenant_id` e o `conversation_id` repetem-se no `WHERE` de propósito: o
 * `reply_id` do evento tem de ser **desta** conversa, e não só deste tenant. A
 * linha tranca-se (`FOR UPDATE OF r`): duas entregas concorrentes do mesmo
 * evento a dois consumidores do mesmo nome serializam aqui.
 */
export const SQL_RESPOSTA_DO_WHATSAPP = `
  SELECT r.reply_id, r.chave, r.contact_id, r.conversation_id, r.texto, r.botoes,
         r.template_nome, r.template_parametros,
         r.turno_iniciado_em, r.entregue_at, c.channel_id, tc.phone_number_id
    FROM platform.agent_replies r
    JOIN platform.conversations c
      ON c.tenant_id = r.tenant_id AND c.id = r.conversation_id
    JOIN platform.tenant_channels tc
      ON tc.tenant_id = c.tenant_id AND tc.id = c.channel_id
   WHERE r.tenant_id = $1 AND r.reply_id = $2 AND r.conversation_id = $3
     AND r.canal = 'whatsapp'
     FOR UPDATE OF r`;

/** A resposta de canal `painel`, trancada, para a marcar entregue uma vez. */
export const SQL_RESPOSTA_DO_PAINEL = `
  SELECT r.reply_id, r.entregue_at
    FROM platform.agent_replies r
   WHERE r.tenant_id = $1 AND r.reply_id = $2 AND r.conversation_id = $3
     AND r.canal = 'painel'
     FOR UPDATE`;

/** Marca a entrega. Só a primeira vez: um `entregue_at` não se reescreve. */
export const SQL_MARCAR_ENTREGUE = `
  UPDATE platform.agent_replies SET entregue_at = now()
   WHERE tenant_id = $1 AND reply_id = $2 AND entregue_at IS NULL`;

/**
 * O estado da linha do Outbound de uma chave, quando o `Saida` diz `repetido`.
 *
 * O `Saida` responde `ok` a uma chave que já passou **sem olhar ao estado** da
 * linha: uma linha `queued` (o processo morreu entre a linha e a rede) ou
 * `failed` também é «repetida». Só uma linha que saiu conta como entregue.
 *
 * O `wamid` e o `error_code` são do KAM-227: uma linha com `wamid` foi aceite
 * pela Meta e nunca se reenvia, e um `failed` com código ambíguo pode ter saído
 * (`decidirEnvio`, no `efeito.ts`).
 */
export const SQL_ESTADO_DO_ENVIO = `
  SELECT state, wamid, error_code FROM platform.outbound_messages
   WHERE tenant_id = $1 AND idempotency_key = $2`;
