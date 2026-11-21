/**
 * As sessões do painel revogadas, na base (KAM-236; decisão do fundador de
 * 2026-11-21, D3-A): a `platform.painel_revogacao` da revisão `0084`.
 *
 * Como `kamba_app`, e sob a RLS do tenant **da sessão**: o tenant sai da sessão
 * assinada (ver `./sessao.ts`), nunca do pedido. Uma linha por sessão revogada,
 * ou um corte por tenant que só sobe. O `expira_at` de cada linha é o fim do
 * tecto absoluto (`TECTO_DO_PAINEL_S`): depois dele, a sessão que a linha revoga
 * já é recusada pelos prazos, e a linha não revoga nada.
 */

import { numaLigacaoDaInscricao, type PoolDaInscricao } from "@kamba/core-ts/inscricao";
import { comTenant } from "@kamba/core-ts/tenant_guard";

import { TECTO_DO_PAINEL_S, type Revogacoes, type SessaoDoPainel } from "./sessao.ts";

export const SQL_REVOGAR_SESSAO = `
  INSERT INTO platform.painel_revogacao (tenant_id, sid, expira_at)
  VALUES ($1, $2, to_timestamp($3))
  ON CONFLICT (tenant_id, sid) WHERE sid IS NOT NULL DO NOTHING`;

export const SQL_REVOGAR_DO_TENANT = `
  INSERT INTO platform.painel_revogacao AS r (tenant_id, ate, expira_at)
  VALUES ($1, $2, to_timestamp($3))
  ON CONFLICT (tenant_id) WHERE ate IS NOT NULL DO UPDATE
     SET ate = greatest(r.ate, EXCLUDED.ate), expira_at = greatest(r.expira_at, EXCLUDED.expira_at)`;

/** Revogada pela sessão, ou por um corte do tenant que a cobre. O tenant é o do contexto. */
export const SQL_REVOGADA = `
  SELECT EXISTS (SELECT 1 FROM platform.painel_revogacao WHERE tenant_id = $1 AND sid = $2)
      OR EXISTS (SELECT 1 FROM platform.painel_revogacao WHERE tenant_id = $1 AND ate >= $3) AS revogada`;

export class RevogacoesNaBase implements Revogacoes {
  readonly #pool: PoolDaInscricao;

  constructor(pool: PoolDaInscricao) {
    this.#pool = pool;
  }

  async revogar(s: SessaoDoPainel): Promise<void> {
    await numaLigacaoDaInscricao(this.#pool, (bd) =>
      comTenant(bd, s.tenantId, (tx) => tx.query(SQL_REVOGAR_SESSAO, [s.tenantId, s.sid, s.emitida + TECTO_DO_PAINEL_S])),
    );
  }

  async revogarDoTenant(tenantId: string, ate: number): Promise<void> {
    const corte = Math.max(0, Math.trunc(ate));
    await numaLigacaoDaInscricao(this.#pool, (bd) =>
      comTenant(bd, tenantId, (tx) => tx.query(SQL_REVOGAR_DO_TENANT, [tenantId, corte, corte + TECTO_DO_PAINEL_S])),
    );
  }

  async revogada(s: SessaoDoPainel): Promise<boolean> {
    return numaLigacaoDaInscricao(this.#pool, (bd) =>
      comTenant(bd, s.tenantId, async (tx) => {
        const { rows } = await tx.query<{ revogada: boolean }>(SQL_REVOGADA, [s.tenantId, s.sid, s.emitida]);
        return rows[0]?.revogada === true;
      }),
    );
  }
}
