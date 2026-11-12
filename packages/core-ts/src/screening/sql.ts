/**
 * Os adaptadores SQL do screening, sobre a `platform.screening_decision`
 * (KAM-088). As constantes são exportadas porque os ensaios contra PostgreSQL
 * as importam daqui: um ensaio que reescrevesse o SQL à mão media o SQL dele.
 *
 * **A ordem das decisoes e a do `criado_at`**, que a revisao preenche com
 * `clock_timestamp()` e nao com `now()`: o `id` e `uuid` aleatorio (dicionario §2)
 * e nao ordena nada, e o `now()` e o mesmo para toda a transaccao.
 *
 * O escritor e o leitor correm pela ligação da **aplicação**, dentro do
 * `comTenant` de quem monta o módulo: a tabela tem RLS `FORCE` e o `INSERT` só
 * passa o `WITH CHECK` com `app.tenant_id` igual ao `tenant_id` da linha. A
 * leitura do catálogo por re-analisar atravessa tenants e corre como
 * `kamba_batch`, que é o papel dos *jobs*.
 */

import type { ChaveDaDecisao, EscritorDeDecisoes, LeitorDeDecisoes, LinhaDeDecisao } from "./motor.ts";
import type { LeitorDoCatalogo, ProdutoPublicado } from "./reanalise.ts";
import type { Decisao, Origem } from "./tipos.ts";

/** O cliente de SQL que este módulo precisa. */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

export const SQL_GRAVAR = `
INSERT INTO platform.screening_decision
  (tenant_id, onboarding_id, sujeito_tipo, sujeito_ref, decisao, regras,
   versao_politica, origem, conteudo_sha256)
VALUES ($1, $2, $3, $4, $5, $6::text[], $7, $8, $9)`;

export const SQL_DECISOES = `
SELECT decisao, origem FROM platform.screening_decision
WHERE tenant_id = $1 AND sujeito_tipo = $2 AND sujeito_ref = $3
  AND versao_politica = $4 AND conteudo_sha256 = $5
ORDER BY criado_at, id`;

/**
 * Os produtos publicados sem decisão para a versão `$1`, até `$2`.
 *
 * A categoria declarada do tenant é a `sujeito_ref` da sua decisão de
 * categoria mais recente; sem ela, vai vazia e o produto cai em
 * `condicional` — um tenant sem categoria avaliada não tem nada `permitida`.
 */
export const SQL_POR_REANALISAR = `
SELECT o.tenant_id::text AS tenant_id, o.sku, o.nome,
  coalesce((SELECT c.sujeito_ref FROM platform.screening_decision c
            WHERE c.tenant_id = o.tenant_id AND c.sujeito_tipo = 'categoria'
            ORDER BY c.criado_at DESC, c.id DESC LIMIT 1), '') AS categoria_declarada
FROM platform.offer_terms o
WHERE o.estado = 'publicado' AND o.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM platform.screening_decision d
                  WHERE d.tenant_id = o.tenant_id AND d.sujeito_tipo = 'produto'
                    AND d.sujeito_ref = o.sku AND d.versao_politica = $1)
ORDER BY o.tenant_id, o.sku LIMIT $2`;

export class EscritorSql implements EscritorDeDecisoes {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async gravar(linha: LinhaDeDecisao): Promise<void> {
    await this.#cliente.query(SQL_GRAVAR, [
      linha.tenantId,
      linha.onboardingId,
      linha.sujeitoTipo,
      linha.sujeitoRef,
      linha.decisao,
      linha.regras,
      linha.versaoPolitica,
      linha.origem,
      Buffer.from(linha.conteudoSha256),
    ]);
  }
}

export class LeitorSql implements LeitorDeDecisoes {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async decisoes(chave: ChaveDaDecisao) {
    const { rows } = await this.#cliente.query<{ decisao: Decisao; origem: Origem }>(SQL_DECISOES, [
      chave.tenantId,
      chave.sujeitoTipo,
      chave.sujeitoRef,
      chave.versaoPolitica,
      Buffer.from(chave.conteudoSha256),
    ]);
    return rows.map((l) => ({ decisao: l.decisao, origem: l.origem }));
  }
}

export class CatalogoSql implements LeitorDoCatalogo {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async porReanalisar(versao: string, limite: number): Promise<readonly ProdutoPublicado[]> {
    const { rows } = await this.#cliente.query<{
      tenant_id: string;
      sku: string;
      nome: string;
      categoria_declarada: string;
    }>(SQL_POR_REANALISAR, [versao, limite]);
    return rows.map((l) => ({
      tenantId: l.tenant_id,
      sku: l.sku,
      categoriaDeclarada: l.categoria_declarada,
      textos: [l.nome],
    }));
  }
}
