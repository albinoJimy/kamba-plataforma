/**
 * A saída de `publicado` de um produto que o screening bloqueia (KAM-245,
 * KAM-253).
 *
 * **Um só escritor para os dois caminhos.** Uma `bloqueada` sobre o conteúdo
 * exacto de um publicado tira-o do catálogo visível venha de onde vier: do
 * `/internal/screen` do COM (decisão A do fundador de 2026-11-23, bloco do
 * KAM-245) ou da re-análise de uma versão nova da política (decisão A do
 * fundador de 2026-11-24, bloco do KAM-253). Os dois chamam o `despublicar`
 * deste módulo — a mesma instrução e o mesmo `catalog.product_changed` —, e
 * nenhum tem uma cópia dele. É por isso que a saída mora aqui e não no COM: a
 * re-análise vive no `core-ts`, e o `core-ts` não importa serviços.
 *
 * **Não é um segundo escritor da `offer_terms.estado`** no sentido da nota do
 * `activacao/sql.ts`: aquela recusa um caminho de publicar, retirar ou renomear
 * **sem** evento. Este leva o evento na mesma transacção, e o rasto de porquê
 * fica na `screening_decision` e na violação, que são *append-only*. Não há
 * linha de `audit_log`, cujas origens são uma lista fechada do KAM-043 — como
 * no KAM-245.
 *
 * **Para `rascunho`, e não `arquivado`**, que é terminal: o recurso humano da
 * T&S (uma `permitida` de `humano`) deixa o dono republicar. É o que o *trigger*
 * `offer_terms_publicacao_segura` da revisão `0080` faz a um publicado cujo
 * nome novo não tem decisão. A saída não colide com o *trigger* da `limitacao`
 * da revisão `0067`, que só pergunta na transição `rascunho → publicado`; a
 * republicação sob `limitacao` é o achado que a decisão D2 do KAM-245 deixou
 * escrito, sem credor.
 */

import { validarPayload } from "../eventos/contratos.ts";
import { assertPublishable, NaoPublicavelError } from "./motor.ts";
import type { ProdutoPublicado, RetiradaDoCatalogo } from "./reanalise.ts";
import type { PoliticaCompilada } from "./regras.ts";
import { LeitorSql, SQL_CATEGORIA_DO_TENANT, type ClienteSql } from "./sql.ts";
import type { EntradaDoScreen } from "./tipos.ts";

/**
 * O `nome` de uma oferta **publicada** do tenant, com a linha trancada.
 *
 * A tranca serializa os dois caminhos sobre o mesmo `sku`: o segundo espera que
 * o primeiro confirme, e a leitura das decisões que faz a seguir já vê a
 * `bloqueada` dele. Sem ela, dois `screen` liam «ainda não bloqueada» e
 * emitiam os dois (KAM-245).
 */
export const SQL_PUBLICADO_SOB_TRANCA = `
SELECT nome FROM platform.offer_terms
WHERE tenant_id = $1 AND sku = $2 AND estado = 'publicado' AND deleted_at IS NULL
FOR UPDATE`;

/** Tira de `publicado` a oferta deste tenant e deste `sku`. Ver a nota do módulo. */
export const SQL_DESPUBLICAR = `
UPDATE platform.offer_terms
   SET estado = 'rascunho', atualizado_at = clock_timestamp()
 WHERE tenant_id = $1 AND sku = $2 AND estado = 'publicado' AND deleted_at IS NULL
RETURNING sku`;

/** O evento que o IDX lê para reescrever o documento a partir da oferta viva. */
export const TIPO_PRODUTO_ALTERADO = "catalog.product_changed";
/** A `v1`, como o COM: a `transacao` está no domínio dela. */
export const VERSAO_PRODUTO_ALTERADO = 1;
/** Os do COM (`services/com/src/produtos/contrato.ts`): o mesmo par `product`/`sku`. */
export const AGREGADO_PRODUTO_ALTERADO = "product";
export const CLASSE_PII_PRODUTO_ALTERADO = "P0";
export const FINALIDADES_PRODUTO_ALTERADO = ["transacao"] as const;

export const SQL_EMITIR_PRODUTO_ALTERADO = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb, $7, $8::text[]
  ) AS event_id
`;

/**
 * Tira de `publicado` a oferta deste `sku` e emite o `catalog.product_changed`
 * com o `estado` `rascunho`, pelo cliente de quem chama — logo na transacção
 * dele, com a decisão e a violação.
 *
 * Devolve `false` sem escrever nada se não houver oferta publicada; quem tem a
 * linha trancada lê isso como defeito, e lança.
 *
 * @throws se a instrução tocar mais do que uma linha, se o payload não bater com
 *   o contrato, ou se o `evt_emitir` não devolver um `event_id`: a transacção
 *   de quem chama desfaz-se toda.
 */
export async function despublicar(cliente: ClienteSql, tenantId: string, sku: string): Promise<boolean> {
  const saiu = await cliente.query(SQL_DESPUBLICAR, [tenantId, sku]);
  if (saiu.rows.length === 0) return false;
  if (saiu.rows.length !== 1) {
    throw new Error("a saida de publicado tocou mais do que uma oferta");
  }
  const payload = { sku, estado: "rascunho" };
  validarPayload(TIPO_PRODUTO_ALTERADO, VERSAO_PRODUTO_ALTERADO, payload);
  const { rows } = await cliente.query<{ event_id: unknown }>(SQL_EMITIR_PRODUTO_ALTERADO, [
    TIPO_PRODUTO_ALTERADO,
    VERSAO_PRODUTO_ALTERADO,
    tenantId,
    AGREGADO_PRODUTO_ALTERADO,
    sku,
    JSON.stringify(payload),
    CLASSE_PII_PRODUTO_ALTERADO,
    [...FINALIDADES_PRODUTO_ALTERADO],
  ]);
  if (typeof rows[0]?.event_id !== "string") {
    throw new Error(
      "platform.evt_emitir nao devolveu um event_id para o catalog.product_changed: " +
        "a oferta saiu de publicado e o indice nao saberia",
    );
  }
  return true;
}

/**
 * A retirada da re-análise (KAM-253): o adaptador da porta `RetiradaDoCatalogo`,
 * sobre o cliente **da transacção do produto** — o mesmo do `EscritorSql` e do
 * `EmissorSql` (`dependenciasDaReanalise`).
 *
 * ```text
 * sem oferta publicada com este sku          nada (o dono tirou-a ou apagou-a)
 * o conteudo publicado e publicavel, ou       nada (uma permitida humana ganha; ou mudou o
 *   nao tem decisao nesta versao                nome ou a categoria, e e outro conteudo)
 * o conteudo publicado esta bloqueada         despublica e emite o product_changed
 * ```
 *
 * O leitor do catálogo corre noutra ligação (`kamba_batch`) e antes desta
 * transacção, pelo que o produto pode ter mudado entretanto. Por isso tranca a
 * oferta e volta a ler o conteúdo publicado — o `nome` e a categoria do tenant —
 * e pergunta ao `assertPublishable` **por esse** conteúdo, como o
 * `gravarComViolacao` do COM. Um conteúdo que mudou não tem a decisão que esta
 * transacção acabou de gravar, e dá `sem_decisao`: fica, e a re-análise
 * seguinte analisa-o por si. Se tiver uma `bloqueada` própria nesta versão,
 * sai, e é o que se quer.
 */
export class RetiradaSql implements RetiradaDoCatalogo {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async retirar(produto: ProdutoPublicado, politica: PoliticaCompilada): Promise<boolean> {
    const oferta = await this.#cliente.query(SQL_PUBLICADO_SOB_TRANCA, [produto.tenantId, produto.sku]);
    const nome = oferta.rows[0]?.["nome"];
    if (typeof nome !== "string") return false;
    const { rows } = await this.#cliente.query(SQL_CATEGORIA_DO_TENANT, [produto.tenantId]);
    const categoria = rows[0]?.["sujeito_ref"];
    const publicada: EntradaDoScreen = {
      categoria_declarada: typeof categoria === "string" ? categoria : "",
      textos: [nome],
    };
    try {
      await assertPublishable(
        { tenantId: produto.tenantId, ref: produto.sku, entrada: publicada },
        { politica, leitor: new LeitorSql(this.#cliente) },
      );
      return false;
    } catch (excepcao) {
      if (!(excepcao instanceof NaoPublicavelError)) throw excepcao;
      if (excepcao.motivo !== "bloqueada") return false;
    }
    if (!(await despublicar(this.#cliente, produto.tenantId, produto.sku))) {
      // A linha está trancada desde o início: não sair é um defeito, e lançar
      // desfaz a decisão e a violação com ela.
      throw new Error("a oferta trancada nao saiu de publicado");
    }
    return true;
  }
}
