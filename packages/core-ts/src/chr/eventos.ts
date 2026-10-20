/**
 * A emissão de `contact.merged` (KAM-014, critério 4).
 *
 * O módulo de identidade **devolve** o evento e não o emite — «quem emite é
 * quem chama» (`docs/identidade.md` §4), e quem chama é o CHR. Este ficheiro é
 * esse passo: mapeia o que o KAM-008 devolve para o payload que o contrato
 * publicado exige, valida-o, e chama `platform.evt_emitir` com o papel
 * `kamba_app` e contexto de tenant.
 *
 * ## O nome do campo diverge, e por isso há um mapeamento e não uma passagem
 *
 * O `EventoContactMerged` do KAM-008 traz
 * `{ contact_id: <o que fica>, merged_contact_id: <o absorvido> }`. O contrato
 * publicado (`contratos/eventos/contact.merged/v1.schema.json`, KAM-007) exige
 * `{ contact_id, merged_into }` — dois nomes diferentes **e** a leitura
 * invertida: `contact_id` é o **absorvido** e `merged_into` é quem ficou, que é
 * como se lê «A foi fundido em B» e como a coluna `contacts.merged_into` da
 * revisão `0003` já o escreve.
 *
 * Passar o payload do KAM-008 tal e qual era um `PayloadInvalidoError` do
 * `validarPayload` — `merged_contact_id` não está nos permitidos — e, sem a
 * validação, um `check_violation` do `evt_emitir` ou, pior, um evento publicado
 * com um campo que nenhum consumidor conhece. A divergência está em
 * `docs/dividas-documentais.md`.
 *
 * ## Dentro da transacção de quem chama, e **depois** do `COMMIT` da fusão
 *
 * O `evt_emitir` escreve no `events_outbox` do KAM-005, que é lido pelo
 * publicador: a emissão é durável assim que a transacção que a contém confirma.
 * Mas essa transacção **não é a da fusão** — a da fusão corre com
 * `kamba_identity`, que não tem `EXECUTE` no `evt_emitir` (e dar-lho era deixar
 * a identidade emitir qualquer evento). A janela está declarada em
 * `docs/chr.md` §5: um `kill -9` entre o `COMMIT` da fusão e esta emissão perde
 * o evento.
 *
 * ## A validação corre **antes** do SQL
 *
 * É a regra do KAM-007 (`eventos/contratos.ts`): o `evt_emitir` grava o
 * envelope e não valida o payload contra o contrato. Validar depois é descobrir
 * o defeito com o evento já publicado.
 */

import type { PayloadContactMerged } from "@kamba/contracts";

import { validarPayload } from "../eventos/contratos.ts";
import type { ClienteDoChr } from "./contrato.ts";

/** O tipo e a versão do contrato publicado que este módulo emite. */
export const TIPO_CONTACT_MERGED = "contact.merged";
export const VERSAO_CONTACT_MERGED = 1;

/**
 * O tipo de agregado do evento.
 *
 * É `contact`, como o exemplo do contrato. O **identificador** do agregado é o
 * contacto **absorvido**, o mesmo que o `payload.contact_id`: o evento é sobre
 * a vida que terminou, e o `seq` por agregado conta-se onde o assunto está. O
 * exemplo publicado tem os dois diferentes e não decide isto; fica declarado.
 */
export const AGREGADO_CONTACT_MERGED = "contact";

/** O que o `resolveContact` do KAM-008 devolve quando funde. */
export interface EventoDeFusao {
  readonly tenant_id: string;
  readonly payload: {
    /** O contacto que **ficou** (o mais antigo). */
    readonly contact_id: string;
    /** O contacto **absorvido**; a sua linha fica como lápide. */
    readonly merged_contact_id: string;
  };
}

/**
 * O payload do contrato publicado, a partir do que o KAM-008 devolveu.
 *
 * Exportada e testada à parte porque é aqui que vive a inversão: trocar os dois
 * campos publicava «B foi fundido em A» onde aconteceu o contrário, e nenhum
 * esquema o apanhava — os dois são UUID.
 */
export function payloadDaFusao(evento: EventoDeFusao): PayloadContactMerged {
  return {
    contact_id: evento.payload.merged_contact_id,
    merged_into: evento.payload.contact_id,
  };
}

/**
 * `SELECT platform.evt_emitir(...)` para `contact.merged`. Precisa de contexto
 * de tenant e do papel `kamba_app`.
 *
 * Os marcadores são `$n` contíguos a partir de 1, para a
 * `ConsultaDoTypeScript` da suite Python os poder reordenar.
 */
export const SQL_EMITIR_CONTACT_MERGED = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb
  ) AS event_id
`;

/**
 * Emite o `contact.merged`. Devolve o `event_id`.
 *
 * @throws {PayloadInvalidoError} se o payload não bater com o contrato — e isso
 *   é antes de qualquer escrita.
 */
export async function emitirContactMerged(
  cliente: ClienteDoChr,
  evento: EventoDeFusao,
): Promise<string> {
  const payload = payloadDaFusao(evento);
  validarPayload(TIPO_CONTACT_MERGED, VERSAO_CONTACT_MERGED, payload);
  const resultado = await cliente.query(SQL_EMITIR_CONTACT_MERGED, [
    TIPO_CONTACT_MERGED,
    VERSAO_CONTACT_MERGED,
    evento.tenant_id,
    AGREGADO_CONTACT_MERGED,
    payload.contact_id,
    JSON.stringify(payload),
  ]);
  const id = resultado.rows[0]?.event_id;
  if (typeof id !== "string") {
    throw new Error(
      "platform.evt_emitir nao devolveu um event_id: o evento `contact.merged` " +
        "pode nao ter sido escrito no outbox",
    );
  }
  return id;
}
