/**
 * As instruções da `OwnerPort` (KAM-223), como `kamba_app` com o tenant da sessão.
 *
 * ## Porque é o `kamba_app`, e não o `kamba_identity` da troca
 *
 * O `kamba_identity` não lê `platform.tenants` nem `tenant_channels` — é
 * invariante do KAM-008, com ensaio —, e a conversa do dono precisa dos dois: o
 * `owner_contact_id` e o canal. A decisão 1 do fundador nomeia as duas saídas
 * (uma segunda ligação `kamba_app` com o tenant no contexto, ou pedir o
 * `thread_id` a quem o lê); esta é a primeira. O `kamba_app` lê as duas tabelas
 * desde a `0001`, insere em `conversations` desde a `0009`, e lê e insere na
 * fonte persistida da mensagem (`agent_messages`, revisão `0077`) e lê a
 * `agent_replies` (revisão `0073`). Tudo sob RLS `FORCE`, com o `app.tenant_id`
 * da transacção: uma linha de outro tenant não se vê.
 *
 * ## Uma ligação por operação
 *
 * Pela razão do `numaLigacao` de `./sql.ts`: o servidor atende pedidos
 * concorrentes, e o `tenant_guard` recusa a segunda transacção numa ligação
 * partilhada.
 */

import { comTenant, type ClienteSql } from "../tenant_guard/index.ts";
import type { ContextoDoDono, EntradaDaConversa, PortasDaConversa, SemContexto } from "./conversa.ts";
import { CANAL_DO_PAINEL, MARGEM_DO_CURSOR_MS } from "./conversa.ts";
import { numaLigacao, type PoolDeIdentidade } from "./sql.ts";

/** Um *pool* `pg` de qualquer papel, pela forma que o `numaLigacao` usa. */
export type PoolDaApp = PoolDeIdentidade;

/**
 * O dono e o canal do tenant. Um canal só, no Piloto; com mais, o `activo`
 * primeiro, e o `encerrado` nunca. O `tenant_id = $1` repete-se no `WHERE`
 * além da RLS, para que a instrução diga o que lê.
 */
export const SQL_DONO_E_CANAL = `
  SELECT t.owner_contact_id::text AS contact_id,
         c.id::text               AS channel_id,
         c.vertical               AS vertical
    FROM platform.tenant_channels c
    JOIN platform.tenants t ON t.id = c.tenant_id
   WHERE c.tenant_id = $1
     AND c.estado <> 'encerrado'
   ORDER BY (c.estado = 'ativo') DESC, c.id
   LIMIT 1`;

/** Só o dono, para distinguir «sem dono» de «sem canal». */
export const SQL_DONO = `
  SELECT owner_contact_id::text AS contact_id FROM platform.tenants WHERE id = $1`;

/**
 * A conversa do dono no canal, **sem janela**: as duas colunas da janela ficam
 * como estão (ou `NULL`, se nasce aqui). Ver a nota de `./conversa.ts`.
 */
export const SQL_ABRIR_CONVERSA_DO_DONO = `
  INSERT INTO platform.conversations (tenant_id, contact_id, channel_id)
  VALUES ($1, $2, $3)
  ON CONFLICT (tenant_id, contact_id, channel_id) DO NOTHING`;

export const SQL_CONVERSA_DO_DONO = `
  SELECT id::text AS conversation_id, mode
    FROM platform.conversations
   WHERE tenant_id = $1 AND contact_id = $2 AND channel_id = $3`;

/** A mensagem do dono, na fonte persistida. O texto já vem aparado e com tecto. */
export const SQL_GRAVAR_MENSAGEM = `
  INSERT INTO platform.agent_messages (tenant_id, contact_id, conversation_id, canal, texto)
  VALUES ($1, $2, $3, '${CANAL_DO_PAINEL}', $4)
  RETURNING message_id::text AS message_id`;

/**
 * As mensagens do dono pelo painel e as respostas **entregues** pelo canal
 * `painel` (o `entregue_at` é o que o consumidor `painel` do KAM-224 escreve:
 * a resposta volta pelo evento, e não por uma leitura directa do que o AGR
 * acabou de gravar). Da conversa e do tenant da sessão, por ordem.
 */
const ENTRADAS = `
    SELECT m.message_id::text AS id, 'dono' AS autor, m.texto, '[]'::jsonb AS botoes,
           m.criado_at AS em
      FROM platform.agent_messages m
     WHERE m.tenant_id = $1 AND m.conversation_id = $2 AND m.canal = '${CANAL_DO_PAINEL}'
    UNION ALL
    SELECT r.reply_id::text, 'assistente', r.texto, r.botoes, r.entregue_at
      FROM platform.agent_replies r
     WHERE r.tenant_id = $1 AND r.conversation_id = $2 AND r.canal = '${CANAL_DO_PAINEL}'
       AND r.entregue_at IS NOT NULL`;

/** O instante do cursor, **nesta** conversa. Zero linhas: não é dela. */
export const SQL_CURSOR_DA_CONVERSA = `
  SELECT em FROM (${ENTRADAS}) AS entradas WHERE id = $3`;

/**
 * As entradas desde o cursor, ou desde o início, **com uma margem para trás**
 * (`MARGEM_DO_CURSOR_MS`, *proposta*). O `em` de uma resposta é o `entregue_at`,
 * que é o `now()` do **início** da transacção do consumidor: uma resposta cuja
 * entrega começou antes de uma mensagem do dono e acabou depois dela tinha um
 * `em` anterior a um cursor já lido, e nunca aparecia (achado 5 da revisão
 * adversarial). Com a margem, a leitura repete o que caiu nela, e o painel
 * deduplica pelo `id`. O cursor só serve para dizer **de que conversa** se lê —
 * um `id` de outra dá `null` antes desta instrução.
 */
export const SQL_LER_CONVERSA = `
  SELECT id, autor, texto, botoes, em FROM (${ENTRADAS}) AS entradas
   WHERE $3::timestamptz IS NULL
      OR em > $3::timestamptz - make_interval(secs => ${MARGEM_DO_CURSOR_MS / 1000})
   ORDER BY em, id
   LIMIT $4`;

type Linha = Readonly<Record<string, unknown>>;

async function linhas(bd: ClienteSql, sql: string, parametros: readonly unknown[]): Promise<readonly Linha[]> {
  const resposta = (await bd.query(sql, parametros)) as { readonly rows?: readonly Linha[] };
  return resposta.rows ?? [];
}

function texto(linha: Linha | undefined, campo: string): string | null {
  const valor = linha?.[campo];
  return valor === null || valor === undefined ? null : String(valor);
}

/** O contexto do dono, numa transacção com o tenant. */
export async function contextoNaBase(bd: ClienteSql, tenantId: string): Promise<ContextoDoDono | SemContexto> {
  return comTenant(bd, tenantId, async (tx) => {
    const [canal] = await linhas(tx, SQL_DONO_E_CANAL, [tenantId]);
    if (canal === undefined) {
      const [dono] = await linhas(tx, SQL_DONO, [tenantId]);
      return texto(dono, "contact_id") === null ? "sem_dono" : "sem_canal";
    }
    const contactId = texto(canal, "contact_id");
    if (contactId === null) return "sem_dono";
    const channelId = String(canal["channel_id"]);
    await tx.query(SQL_ABRIR_CONVERSA_DO_DONO, [tenantId, contactId, channelId]);
    const [conversa] = await linhas(tx, SQL_CONVERSA_DO_DONO, [tenantId, contactId, channelId]);
    if (conversa === undefined) throw new Error("a conversa do dono nao ficou visivel depois de aberta");
    return {
      contactId,
      channelId,
      vertical: String(canal["vertical"]),
      conversationId: String(conversa["conversation_id"]),
      modo: String(conversa["mode"]) as ContextoDoDono["modo"],
    };
  });
}

function botoesDe(valor: unknown): EntradaDaConversa["botoes"] {
  const lista = typeof valor === "string" ? (JSON.parse(valor) as unknown) : valor;
  if (!Array.isArray(lista)) return [];
  return lista
    .filter((b): b is { id: unknown; titulo: unknown } => typeof b === "object" && b !== null)
    .map((b) => ({ id: String(b.id), titulo: String(b.titulo) }));
}

/** As três portas de base da `ConversaDoDono`, sobre um *pool* do `kamba_app`. */
export function conversaPeloPool(pool: PoolDaApp): Omit<PortasDaConversa, "invocar"> {
  return {
    contexto: (tenantId) => numaLigacao(pool, (bd) => contextoNaBase(bd, tenantId)),
    gravar: ({ tenantId, contactId, conversationId, texto: corpo }) =>
      numaLigacao(pool, (bd) =>
        comTenant(bd, tenantId, async (tx) => {
          const [linha] = await linhas(tx, SQL_GRAVAR_MENSAGEM, [tenantId, contactId, conversationId, corpo]);
          const id = texto(linha, "message_id");
          if (id === null) throw new Error("a mensagem do dono nao devolveu identificador");
          return id;
        }),
      ),
    ler: ({ tenantId, conversationId, depois, limite }) =>
      numaLigacao(pool, (bd) =>
        comTenant(bd, tenantId, async (tx) => {
          let instante: unknown = null;
          if (depois !== null) {
            const [cursor] = await linhas(tx, SQL_CURSOR_DA_CONVERSA, [tenantId, conversationId, depois]);
            if (cursor === undefined) return null;
            instante = cursor["em"];
          }
          const lidas = await linhas(tx, SQL_LER_CONVERSA, [tenantId, conversationId, instante, limite]);
          return lidas.map((l) => ({
            id: String(l["id"]),
            autor: l["autor"] === "dono" ? ("dono" as const) : ("assistente" as const),
            texto: String(l["texto"]),
            botoes: botoesDe(l["botoes"]),
            em: l["em"] instanceof Date ? l["em"] : new Date(String(l["em"])),
          }));
        }),
      ),
  };
}
