/**
 * O *job* que o CHR entrega ao AGR: contrato `agent_invocation` (KAM-014).
 *
 * O contrato publicado é `packages/contracts/schemas/agent_invocation.v1.json`,
 * e este módulo é quem monta uma mensagem que lhe obedece. **O esquema é a
 * verdade**: há um teste que compara os campos exigidos por ele com os que esta
 * função escreve, nos dois sentidos, para que um campo novo num lado não passe
 * sem o outro.
 *
 * ## O caminho do contrato não é o do critério, e isso fica dito
 *
 * O critério 6 escreve `packages/contracts/agent_invocation.schema.json`. O
 * ficheiro está em `packages/contracts/schemas/agent_invocation.v1.json`, por
 * duas razões medidas:
 *
 * 1. os esquemas deste pacote vivem em `schemas/` e levam a versão no nome
 *    (`healthz.response.v1.json`), e o `specs/01` §5 manda que uma quebra de
 *    contrato seja um ficheiro `v2`;
 * 2. um ficheiro que acabe em `.schema.json` bate numa **sentinela** do *gate*
 *    3b (`ci/canon-lint.yaml`), que o exige dentro da superfície
 *    `contratos/eventos/` ou declarado fora de âmbito. Este não é um contrato
 *    de evento — não tem envelope, não é publicado no barramento — e pô-lo
 *    nessa pasta era declará-lo como aquilo que não é.
 *
 * A caixa desse critério fica **por marcar**, com esta razão, e a decisão sobre
 * o caminho devolve-se a quem o escreveu.
 *
 * ## O `wamid` vai no *job* e não vai na chave
 *
 * O critério exige o `wamid` no *job*, pelo nome. O `wamid` leva o número do
 * interlocutor codificado em base64 (INDÍCIO, `docs/logs.md` §2.1), e por isso
 * **não** serve de `jobId`: a chave de um *job* é lida por quem opera a fila,
 * aparece em painéis e em listagens de Redis. O `jobId` é um resumo de
 * `{tenant_id}:{wamid}` — determinístico (a repetição do mesmo `wamid` não cria
 * um segundo *job*) e opaco.
 */

import { createHash } from "node:crypto";

import type { Persona } from "../dono/contrato.ts";
import type { ChannelContext } from "./contrato.ts";
import {
  type AgentInvocation,
  type Modo,
  threadIdDe,
} from "./contrato.ts";

/** Um pedido de invocação sem os dados mínimos. */
export class InvocacaoIncompletaError extends Error {
  constructor(campo: string) {
    super(
      `o job do AGR nao se monta sem ${campo}. O contrato ` +
        "`agent_invocation` tem `additionalProperties: false` e todos os " +
        "campos obrigatorios.",
    );
    this.name = "InvocacaoIncompletaError";
  }
}

/**
 * O resumo que serve de `jobId` na fila `agr-inbound`.
 *
 * SHA-256 de `{tenant_id}:{wamid}` em hexadecimal. O `tenant_id` entra porque
 * a chave é global à fila e dois tenants não devem poder colidir nem adivinhar
 * a chave um do outro; o `wamid` porque é o que identifica o turno.
 */
export function jobIdDe(tenantId: string, wamid: string): string {
  return createHash("sha256").update(`${tenantId}:${wamid}`, "utf8").digest("hex");
}

/**
 * O prefixo de domínio do `message_id` de uma mensagem do WhatsApp (KAM-232).
 *
 * Sem ele, o `message_id` era os primeiros 128 bits do `jobId` da mesma
 * mensagem, que é lido por quem opera a fila: um identificador da fonte
 * persistida não se deduz do nome de um *job*.
 */
export const DOMINIO_DO_MESSAGE_ID = "agent_messages";

/**
 * O `message_id` de uma mensagem `text` do WhatsApp na `platform.agent_messages`
 * (KAM-232): um UUID **determinístico** de `{tenant_id}:{wamid}`.
 *
 * É ele que torna a reentrega idempotente sem coluna nova: o mesmo `wamid` no
 * mesmo tenant dá o mesmo identificador, e o `ON CONFLICT (message_id) DO
 * NOTHING` da `SQL_GRAVAR_MENSAGEM_DO_WHATSAPP` não grava segunda linha. O
 * desenho mínimo foi aceite pela coordenação do lote 16 a 2026-11-20 (só o
 * `GRANT INSERT (message_id)` ao `kamba_app`, revisão `0083`).
 *
 * Forma: os primeiros 16 bytes do SHA-256 de `agent_messages:{tenant}:{wamid}`,
 * com a versão `8` e a variante RFC 9562 — a versão das UUID de construção
 * própria. O AGR só confere a forma canónica em minúsculas (`_UUID` de
 * `kamba_agr/contexto.py`), e o `uuid` do PostgreSQL aceita qualquer versão.
 * As mensagens do painel continuam com o `gen_random_uuid()` da coluna.
 */
export function messageIdDe(tenantId: string, wamid: string): string {
  const bytes = createHash("sha256")
    .update(`${DOMINIO_DO_MESSAGE_ID}:${tenantId}:${wamid}`, "utf8")
    .digest()
    .subarray(0, 16);
  bytes[6] = (bytes[6]! & 0x0f) | 0x80;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Monta o *job* do AGR, ou lança.
 *
 * **Não recebe telefone, BSUID nem `display_name`**, e isso não é por
 * disciplina de quem chama: os argumentos não têm por onde os passar. É a forma
 * de o ADR-010 ser verdade por construção e não por revisão — a mesma ideia do
 * `idOpaco` do *logger*.
 */
export function montarInvocacao(pedido: {
  readonly contexto: ChannelContext;
  readonly contactId: string;
  readonly conversationId: string;
  readonly wamid: string;
  readonly type: string;
  readonly modo: Modo;
  readonly persona: Persona;
  /** O `reply.id` de uma resposta interactiva, já com a forma conferida. */
  readonly botao?: string | null;
  /** O identificador da mensagem na `platform.agent_messages` (KAM-223), já gravada. */
  readonly messageId?: string | null;
  /** O `asset_id` da foto do dono na `platform.media_assets` (KAM-231), já armazenada. */
  readonly assetId?: string | null;
}): AgentInvocation {
  if (pedido.contactId === "") throw new InvocacaoIncompletaError("`contact_id`");
  if (pedido.conversationId === "") {
    throw new InvocacaoIncompletaError("`conversation_id`");
  }
  if (pedido.wamid === "") throw new InvocacaoIncompletaError("`wamid`");
  return {
    tenant_id: pedido.contexto.tenant_id,
    contact_id: pedido.contactId,
    conversation_id: pedido.conversationId,
    channel_id: pedido.contexto.channel_id,
    wamid: pedido.wamid,
    type: pedido.type,
    modo: pedido.modo,
    thread_id: threadIdDe(pedido.contexto.tenant_id, pedido.contactId),
    vertical: pedido.contexto.vertical,
    persona: pedido.persona,
    // KAM-211. **Só num `interactive`**: o AGR recusa um `botao` noutro tipo
    // (`campo_invalido_botao`), e um `job` recusado é um turno perdido. A
    // explosão já só o tira de uma resposta interactiva; esta é a segunda
    // barreira, para quem monte a invocação por outro caminho.
    ...(typeof pedido.botao === "string" && pedido.type === "interactive"
      ? { botao: pedido.botao }
      : {}),
    // KAM-223. O identificador e não o texto: o corpo fica na fonte persistida.
    ...(typeof pedido.messageId === "string" ? { message_id: pedido.messageId } : {}),
    // KAM-231. A referência e não os bytes, e **só** numa `image` do dono: o
    // esquema recusa-a noutro tipo ou noutra persona (`dependentSchemas`), e o
    // AGR também (`campo_invalido_asset_id`). Segunda barreira, como a do
    // `botao`, para quem monte a invocação por outro caminho.
    ...(typeof pedido.assetId === "string" && pedido.type === "image" && pedido.persona === "dono"
      ? { asset_id: pedido.assetId }
      : {}),
  };
}
