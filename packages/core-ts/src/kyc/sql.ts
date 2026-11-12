/**
 * O adaptador PostgreSQL do `platform.kyc_check` e da purga (KAM-087).
 *
 * As consultas são constantes exportadas, e é de propósito: a suite de base de
 * dados (`db/tests/test_kyc_schema.py`) executa **estas** cadeias pela
 * `ConsultaDoTypeScript`, e não uma cópia delas.
 *
 * ## Corre como `kamba_batch`
 *
 * A pergunta do `phash` (critério 4) é «esta imagem já foi vista noutro caso
 * **ou tenant**», e com RLS `FORCE` por `tenant_id` uma sessão de um caso não
 * vê os outros — por desenho. O KYC é um passo de retaguarda, sem pedido de
 * utilizador por trás de cada consulta, e corre por isso no papel que tem
 * `BYPASSRLS` e é auditado. A alternativa era uma função `SECURITY DEFINER`, e o
 * `../docs/tecnica/08` §3.3 proíbe-as fora da lista aprovada.
 *
 * A comparação de Hamming é feita na base (`bit_count` sobre o XOR de dois
 * `bit(64)`), sobre toda a tabela. ***shortcut:*** varrimento sequencial,
 * aceitável à escala do Piloto (um `kyc_check` por documento, quatro por caso);
 * revê-se acima de 100 000 linhas, com um índice por bandas do `phash`.
 */

import type {
  Marca,
  RepositorioDeVerificacoes,
  Resultado,
  TipoDeDocumento,
  Verificacao,
  VerificacaoNova,
} from "./contrato.ts";
import type { CasosMortos } from "./servico.ts";

/** O cliente de base de dados, como nos outros módulos. */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

export const SQL_POR_SHA = `SELECT id, onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, phash,
  extraido_enc, flags, score, resultado, versao_regras, custo_micro_usd, criado_at
  FROM platform.kyc_check WHERE onboarding_id = $1 AND sha256 = $2`;

/**
 * `ON CONFLICT DO NOTHING` sobre a unicidade `(onboarding_id, sha256)`: um
 * reenvio do mesmo ficheiro não cria segunda linha (DoD 4). Sem linha devolvida
 * houve conflito, e quem chama relê com o `SQL_POR_SHA`.
 *
 * O `tenant_id` não vem de quem chama: lê-se do caso, na mesma instrução, e a
 * FK composta `(onboarding_id, tenant_id)` prende os dois.
 */
export const SQL_INSERIR = `INSERT INTO platform.kyc_check
  (onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, phash, extraido_enc, flags,
   resultado, versao_regras, custo_micro_usd)
  SELECT c.id, c.tenant_id, $2, $3, $4, $5, $6, $7::text[], $8, $9, $10
    FROM platform.onboarding_case c WHERE c.id = $1
  ON CONFLICT (onboarding_id, sha256) DO NOTHING
  RETURNING id, onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, phash, extraido_enc, flags,
    score, resultado, versao_regras, custo_micro_usd, criado_at`;

export const SQL_DO_CASO = `SELECT id, onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, phash,
  extraido_enc, flags, score, resultado, versao_regras, custo_micro_usd, criado_at
  FROM platform.kyc_check WHERE onboarding_id = $1 ORDER BY criado_at, id`;

export const SQL_PHASH_NOUTRO_CASO = `SELECT EXISTS (
  SELECT 1 FROM platform.kyc_check
   WHERE onboarding_id <> $1 AND phash IS NOT NULL
     AND bit_count(('x' || encode(phash, 'hex'))::bit(64)
                   # ('x' || encode($2::bytea, 'hex'))::bit(64)) <= $3) AS visto`;

/** Só o resultado e o *score*: as `flags` são do ficheiro (achado A1). */
export const SQL_DECIDIR = `UPDATE platform.kyc_check
  SET resultado = $2, score = $3
  WHERE id = ANY($1::uuid[])`;

export const SQL_CUSTO_DO_CASO = `SELECT coalesce(sum(custo_micro_usd), 0)::bigint AS total
  FROM platform.kyc_check WHERE onboarding_id = $1`;

/** Os casos mortos há mais de D+30, pelo `fase_at` que o *trigger* mantém. */
export const SQL_MORTOS_ATE = `SELECT id AS onboarding_id, tenant_id FROM platform.onboarding_case
  WHERE fase IN ('rejeitado', 'abandonado') AND fase_at <= $1`;

export const SQL_ESQUECER = `UPDATE platform.kyc_check SET extraido_enc = NULL
  WHERE id = ANY($1::uuid[])`;

interface Linha {
  id: string;
  onboarding_id: string;
  doc_tipo: TipoDeDocumento;
  doc_ref: string;
  sha256: Uint8Array;
  phash: Uint8Array | null;
  extraido_enc: Uint8Array | null;
  flags: Marca[];
  score: number | null;
  resultado: Resultado;
  versao_regras: string;
  custo_micro_usd: number;
  criado_at: Date;
}

function verificacaoDe(l: Linha): Verificacao {
  return {
    id: l.id,
    onboardingId: l.onboarding_id,
    tipo: l.doc_tipo,
    docRef: l.doc_ref,
    sha256: Buffer.from(l.sha256).toString("hex"),
    phash: l.phash === null ? null : Buffer.from(l.phash).toString("hex"),
    extraidoCifrado: l.extraido_enc === null ? null : new Uint8Array(l.extraido_enc),
    flags: l.flags,
    score: l.score,
    resultado: l.resultado,
    versaoRegras: l.versao_regras,
    custoMicroUsd: Number(l.custo_micro_usd),
    criadoEm: l.criado_at,
  };
}

export class VerificacoesSql implements RepositorioDeVerificacoes {
  readonly #c: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#c = cliente;
  }

  async porSha(onboardingId: string, sha256: string): Promise<Verificacao | null> {
    const r = await this.#c.query<Linha>(SQL_POR_SHA, [onboardingId, Buffer.from(sha256, "hex")]);
    return r.rows[0] === undefined ? null : verificacaoDe(r.rows[0]);
  }

  async inserir(n: VerificacaoNova): Promise<{ verificacao: Verificacao; repetida: boolean }> {
    const r = await this.#c.query<Linha>(SQL_INSERIR, [
      n.onboardingId,
      n.tipo,
      n.docRef,
      Buffer.from(n.sha256, "hex"),
      n.phash === null ? null : Buffer.from(n.phash, "hex"),
      n.extraidoCifrado === null ? null : Buffer.from(n.extraidoCifrado),
      [...n.flags],
      n.resultado,
      n.versaoRegras,
      n.custoMicroUsd,
    ]);
    if (r.rows[0] !== undefined) return { verificacao: verificacaoDe(r.rows[0]), repetida: false };
    const ja = await this.porSha(n.onboardingId, n.sha256);
    if (ja === null) throw new Error("kyc_check nao inserido: o caso nao existe");
    return { verificacao: ja, repetida: true };
  }

  async doCaso(onboardingId: string): Promise<readonly Verificacao[]> {
    return (await this.#c.query<Linha>(SQL_DO_CASO, [onboardingId])).rows.map(verificacaoDe);
  }

  async phashVistoNoutroCaso(onboardingId: string, phash: string, maximo: number): Promise<boolean> {
    const r = await this.#c.query<{ visto: boolean }>(SQL_PHASH_NOUTRO_CASO, [
      onboardingId,
      Buffer.from(phash, "hex"),
      maximo,
    ]);
    return r.rows[0]?.visto === true;
  }

  async decidir(ids: readonly string[], resultado: Resultado, score: number): Promise<void> {
    await this.#c.query(SQL_DECIDIR, [[...ids], resultado, score]);
  }

  async custoDoCaso(onboardingId: string): Promise<number> {
    const r = await this.#c.query<{ total: string | number }>(SQL_CUSTO_DO_CASO, [onboardingId]);
    return Number(r.rows[0]?.total ?? 0);
  }
}

export class CasosMortosSql implements CasosMortos {
  readonly #c: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#c = cliente;
  }

  async mortosAte(limite: Date): Promise<readonly { onboardingId: string; tenantId: string }[]> {
    const r = await this.#c.query<{ onboarding_id: string; tenant_id: string }>(SQL_MORTOS_ATE, [limite]);
    return r.rows.map((l) => ({ onboardingId: l.onboarding_id, tenantId: l.tenant_id }));
  }

  async esquecer(ids: readonly string[]): Promise<void> {
    await this.#c.query(SQL_ESQUECER, [[...ids]]);
  }
}
