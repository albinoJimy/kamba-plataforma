/**
 * A rotação no `audit_log` (KAM-072, critério 7): «cada rotação escreve no
 * `audit_log` o identificador e a hora, nunca o valor».
 *
 * Pela porta de sempre, a `platform.audit_append` (KAM-012), na **cadeia de
 * plataforma** (`tenant_id` nulo): um segredo é da plataforma e não de um
 * tenant. Quem escreve essa cadeia é o `kamba_batch` (revisão `0006`), pelo que
 * o cliente que se passa aqui é uma ligação com esse papel.
 *
 * A linha:
 *
 * | Coluna | Valor |
 * |---|---|
 * | `action` | a rotação, a de emergência e o início: a de rodar; a revogação: a de revogar (revisão `0066`) |
 * | `entity` | o identificador do segredo (`meta_app_secret`, `litellm_virtual_key/<instância>`) |
 * | `entity_id` | a versão: a que passou a actual, ou a que foi retirada |
 * | `actor_type` / `actor_id` | `staff` / o actor do rotador |
 * | `payload_hash` | o SHA-256 dos metadados da acção — tipo, `kid`, `kid` anterior, `criadaEm` |
 * | `criado_at` | a hora, escrita pelo *trigger* e não por quem insere |
 *
 * **Nem o valor nem um resumo dele.** A `EntradaDeRotacao` não tem campo para o
 * valor, e o `payload_hash` é calculado sobre um objecto montado aqui campo a
 * campo, e não sobre a entrada inteira: um campo que alguém acrescente à
 * entrada amanhã não entra no resumo sem passar por este ficheiro.
 */

import { createHash } from "node:crypto";

import type { EntradaDeRotacao } from "./rotacao.ts";

/** A porta: escreve a acção no registo de auditoria. */
export interface AuditoriaDeRotacao {
  gravar(entrada: EntradaDeRotacao): Promise<void>;
}

/** O mínimo de um cliente `pg`: `query(texto, valores)`. */
export interface ClienteSqlDeAuditoria {
  query(texto: string, valores: readonly unknown[]): Promise<unknown>;
}

/** As duas acções da revisão `0066`. */
export const ACCAO_DE_RODAR = "secret.rotate";
export const ACCAO_DE_REVOGAR = "secret.revoke";

/**
 * A escrita, na cadeia de plataforma. `$1` actor, `$2` acção, `$3` segredo,
 * `$4` versão, `$5` o resumo dos metadados.
 */
export const SQL_AUDITAR_ROTACAO = `SELECT platform.audit_append(NULL, 'staff', $1, $2, $3, $4, NULL, $5)`;

/** A versão que a linha nomeia: a nova numa rotação, a retirada numa revogação. */
function versaoDaLinha(entrada: EntradaDeRotacao): string {
  if (entrada.accao === "revogacao") {
    if (entrada.kidAnterior === null) {
      throw new RangeError("uma revogação sem versão retirada não tem o que auditar");
    }
    return entrada.kidAnterior;
  }
  return entrada.kid;
}

/** O resumo dos metadados da acção. Montado campo a campo, por ordem fixa. */
export function resumoDaAccao(entrada: EntradaDeRotacao): Buffer {
  const metadados = JSON.stringify([
    entrada.accao,
    entrada.kid,
    entrada.kidAnterior,
    entrada.criadaEm === null ? null : entrada.criadaEm.toISOString(),
  ]);
  return createHash("sha256").update(metadados, "utf8").digest();
}

/** O adaptador para a `platform.audit_append`. */
export class AuditoriaDeRotacaoSql implements AuditoriaDeRotacao {
  readonly #c: ClienteSqlDeAuditoria;

  constructor(cliente: ClienteSqlDeAuditoria) {
    this.#c = cliente;
  }

  async gravar(entrada: EntradaDeRotacao): Promise<void> {
    await this.#c.query(SQL_AUDITAR_ROTACAO, [
      entrada.actor,
      entrada.accao === "revogacao" ? ACCAO_DE_REVOGAR : ACCAO_DE_RODAR,
      entrada.segredo,
      versaoDaLinha(entrada),
      resumoDaAccao(entrada),
    ]);
  }
}
