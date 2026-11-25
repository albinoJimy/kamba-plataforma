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
 * A categoria declarada do tenant: a da decisão de categoria mais recente.
 * A mesma ordem do `SQL_POR_REANALISAR`.
 *
 * Mora aqui desde o KAM-253, e não no COM (KAM-222), porque a retirada da
 * re-análise (`retirada.ts`) a lê na transacção do produto, como o `/internal/screen`
 * do COM; o COM importa-a daqui.
 */
export const SQL_CATEGORIA_DO_TENANT = `
SELECT sujeito_ref FROM platform.screening_decision
WHERE tenant_id = $1 AND sujeito_tipo = 'categoria'
ORDER BY criado_at DESC, id DESC LIMIT 1`;

/**
 * Os produtos publicados sem decisão para a versão `$1` **e para o conteúdo
 * publicado**, até `$2`.
 *
 * A categoria declarada do tenant é a `sujeito_ref` da sua decisão de
 * categoria mais recente; sem ela, vai vazia e o produto cai em
 * `condicional` — um tenant sem categoria avaliada não tem nada `permitida`.
 *
 * ## A decisão conta só se for sobre este conteúdo (KAM-119)
 *
 * Um produto publicado salta-se só se houver uma decisão `produto` do mesmo
 * `sku` e da mesma versão **cujo `conteudo_sha256` é o da entrada que esta
 * re-análise lhe daria** — `{categoria_declarada, textos: [nome]}`, a do
 * `CatalogoSql.porReanalisar`. Até ao KAM-119 bastava o `sku` e a versão, e
 * uma decisão gravada com outro texto (pela rota `/internal/screen` do COM,
 * antes de o dono mudar o nome, ou com outra categoria) fazia a re-análise
 * saltar o produto, e o `screening.violation_detected` nunca saía (achado 1
 * da revisão adversarial do KAM-222).
 *
 * O resumo calcula-se aqui, em SQL, e tem de ser **octeto a octeto** o do
 * `conteudoSha256` do `motor.ts`: `sha256` do UTF-8 de
 * `JSON.stringify([categoria, [nome]])`. O `to_json(text)::text` do
 * PostgreSQL escreve a cadeia como o `JSON.stringify`: escapa `"` e `\`, usa
 * `\b \f \n \r \t` e `\u00xx` em minúsculas para os outros de controlo, e deixa
 * tudo o resto cru — acentos, astrais, U+2028, `<` e `/`. O separador é a
 * vírgula sem espaço, e por isso o vector monta-se à mão e não com o
 * `json_build_array`, que escreve `", "`. O `NUL` e os substitutos soltos não
 * chegam: uma coluna `text` não os guarda. A igualdade prova-se contra a base
 * no `db/tests/test_screening_schema.py`, com os vectores fixados pelo
 * `packages/core-ts/tests/screening.test.ts`.
 *
 * Mudou a categoria do tenant, ou o nome de um publicado? O resumo muda, e o
 * produto volta a ser analisado nesta versão — que é o que se quer: a decisão
 * antiga é sobre um conteúdo que já não é o publicado.
 */
export const SQL_POR_REANALISAR = `
SELECT p.tenant_id::text AS tenant_id, p.sku, p.nome, p.categoria_declarada
FROM (
  SELECT o.tenant_id, o.sku, o.nome,
    coalesce((SELECT c.sujeito_ref FROM platform.screening_decision c
              WHERE c.tenant_id = o.tenant_id AND c.sujeito_tipo = 'categoria'
              ORDER BY c.criado_at DESC, c.id DESC LIMIT 1), '') AS categoria_declarada
  FROM platform.offer_terms o
  WHERE o.estado = 'publicado' AND o.deleted_at IS NULL
) p
WHERE NOT EXISTS (SELECT 1 FROM platform.screening_decision d
                  WHERE d.tenant_id = p.tenant_id AND d.sujeito_tipo = 'produto'
                    AND d.sujeito_ref = p.sku AND d.versao_politica = $1
                    AND d.conteudo_sha256 = sha256(convert_to('[' || to_json(p.categoria_declarada)::text || ',[' || to_json(p.nome)::text || ']]', 'UTF8')))
ORDER BY p.tenant_id, p.sku LIMIT $2`;

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
