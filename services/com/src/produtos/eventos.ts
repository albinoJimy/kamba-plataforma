/**
 * Os quatro eventos de catálogo e de stock, pelo outbox (KAM-043, critério 5).
 *
 * O envelope **constrói-se em SQL** (`platform.evt_emitir`), como em todos os
 * produtores deste repositório: não há construtor de envelope em TypeScript, de
 * propósito, para não haver duas fontes para a mesma forma (KAM-005, ADR-009).
 *
 * A emissão corre **na transacção de quem chama** — por isso estas funções
 * recebem o cliente e não o abrem. A escrita e o evento entram ou não entram
 * juntos; é isso que faz do outbox um outbox e não um segundo sistema a precisar
 * de reconciliação.
 *
 * `validarPayload` corre **antes** do SQL: o `evt_emitir` não valida contra o
 * catálogo de contratos — aceita qualquer `p_tipo`, incluindo um que não exista —
 * e um payload errado entrava no outbox e só falhava no consumidor, do outro lado
 * da fila.
 *
 * ## Os nomes são os do catálogo publicado, e os do critério não existem
 *
 * Dos cinco nomes que o critério 5 escreve, **um** existe: o `stock.low`. Os
 * outros quatro — `price.changed`, `stock.changed`, `product.published`,
 * `product.updated` — não têm contrato, não estão no dicionário §3.5 e não estão
 * no `docs/tecnica/06` §5. Os que servem este ticket chamam-se:
 *
 * ```text
 * price.changed                      -> catalog.price_changed  (payload sku, preco_tipo, preco_minor?, currency)
 * stock.changed                      -> stock.adjusted         (payload sku, qty, motivo)
 * stock.low                          -> stock.low              (payload sku, qty)
 * product.published / product.updated -> catalog.product_changed (payload sku, estado)
 * ```
 *
 * Resolve-se a favor do dicionário (fonte 4) contra o bloco (fonte 8) e contra o
 * §12 do `docs/tecnica/03` (fonte 9). A ordem das fontes não é o argumento mais
 * forte: emitir com os nomes do critério levantava `TipoDesconhecidoError` no
 * `validarPayload` da linha abaixo, antes de o *gate* 7 chegar a ver o envelope.
 * A divergência já estava registada em `docs/dividas-documentais.md` (dívida 37,
 * «é um segundo catálogo de eventos, paralelo ao do `docs/tecnica/06` §5, e
 * discorda dele em nomes e em payloads») antes deste ticket, e o
 * `servicos/eventos.ts` do KAM-047 fez a mesma escolha pela mesma razão.
 *
 * **E o `por` (dono/ops) do §12 não tem onde viver.** Aquele documento dá a
 * `price.changed` um campo `por`; o contrato publicado do
 * `catalog.price_changed` tem `additionalProperties: false` e não o conhece.
 * Quem guarda a atribuição é o `audit_log`, nas colunas `actor_type` e
 * `actor_id`, que é o sítio desenhado para ela — e com cadeia de *hash* atrás,
 * que um campo de evento não tem.
 *
 * ## O `catalog.price_changed` leva o preço, e o de produto não leva nada
 *
 * O critério 5 acaba com «`product.published`/`product.updated` não contêm preço
 * nem stock (ADR-007)», e é isso que se cumpre: o payload do
 * `catalog.product_changed` é `{sku, estado}` e o contrato impõe-o por máquina.
 *
 * O `catalog.price_changed`, esse, **leva** `preco_tipo`, `preco_minor` e
 * `currency`, e não é uma excepção à regra — é o que a regra diz. O ADR-007 à
 * letra é «preço e stock nunca em embeddings nem em prompts»; o
 * `docs/tecnica/06` diz onde morde («o IDX não precisa de preço (ADR-007) e não
 * deve reindexar a cada alteração de preço») e manda o DAT **construir** o
 * `preco_obs` a partir deste evento. Um `catalog.price_changed` sem
 * `preco_minor` deixava o consumidor documentado sem nada para observar.
 *
 * O `preco_minor` vai **ausente** e não nulo quando o modo é `sob_consulta`: o
 * contrato tem-no em `properties` e não em `required`, e um `null` afirmava que
 * há um preço cujo valor é nulo em vez de não haver preço. É a mesma distinção
 * que a coluna faz com o `offer_terms_preco_ck`.
 */

import { validarPayload } from "@kamba/core-ts/eventos";

import {
  AGREGADO_PRODUTO,
  AGREGADO_SKU,
  CLASSE_PII_CATALOGO,
  FINALIDADES_CATALOGO,
  SOB_CONSULTA,
  TIPO_PRICE_CHANGED,
  TIPO_PRODUCT_CHANGED,
  TIPO_STOCK_ADJUSTED,
  TIPO_STOCK_LOW,
  VERSAO_PRICE_CHANGED,
  VERSAO_PRODUCT_CHANGED,
  VERSAO_STOCK_ADJUSTED,
  VERSAO_STOCK_LOW,
  type ClienteSql,
  type EstadoDaOferta,
  type MotivoDeAjuste,
  type PrecoTipo,
} from "./contrato.ts";
import { SQL_EMITIR } from "./consultas.ts";

/** O que se emite, já pronto para o `evt_emitir`. */
interface Emissao {
  readonly tipo: string;
  readonly versao: number;
  readonly agregadoTipo: string;
  readonly agregadoId: string;
  readonly payload: Readonly<Record<string, unknown>>;
}

/**
 * O payload de `catalog.price_changed`.
 *
 * O `preco_minor` é `number` e não `bigint` no payload, e a conversão é aqui com
 * a razão escrita: o `JSON.stringify` **lança** `TypeError` sobre um `bigint`, e
 * o contrato declara o campo `integer`. A conversão é segura porque o
 * `Number.MAX_SAFE_INTEGER` são ~90 mil bilhões de kwanzas — mas «é seguro na
 * prática» não é uma propriedade, pelo que se verifica.
 */
export function payloadDoPreco(
  sku: string,
  precoTipo: PrecoTipo,
  precoMinor: bigint | null,
  currency: string,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    sku,
    preco_tipo: precoTipo,
    currency,
  };
  if (precoTipo !== SOB_CONSULTA) {
    if (precoMinor === null) {
      throw new TypeError(
        `catalog.price_changed com preco_tipo='${precoTipo}' e preco_minor ` +
          "nulo: o offer_terms_preco_ck da revisao 0028 recusa este par na base " +
          "(KAM-043, criterio 1)",
      );
    }
    payload["preco_minor"] = emInteiroSeguro(precoMinor, sku);
  }
  return payload;
}

/** Um `bigint` como `number`, ou lança. Ver a nota do `payloadDoPreco`. */
function emInteiroSeguro(valor: bigint, sku: string): number {
  if (valor > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new RangeError(
      `preco_minor de ${sku} acima de Number.MAX_SAFE_INTEGER (${valor}): o ` +
        "contrato do evento declara o campo `integer` e o JSON.stringify lanca " +
        "sobre um bigint, pelo que o payload tem de o converter — e a conversao " +
        "perdia precisao em silencio acima deste tecto (KAM-043)",
    );
  }
  return Number(valor);
}

/** O payload de `catalog.product_changed`. **Sem preço nem stock** (ADR-007). */
export function payloadDoProduto(
  sku: string,
  estado: EstadoDaOferta,
): Record<string, unknown> {
  return { sku, estado };
}

/** O payload de `stock.adjusted`. */
export function payloadDoStock(
  sku: string,
  qty: number,
  motivo: MotivoDeAjuste,
): Record<string, unknown> {
  return { sku, qty, motivo };
}

/** O payload de `stock.low`. */
export function payloadDoStockBaixo(
  sku: string,
  qty: number,
): Record<string, unknown> {
  return { sku, qty };
}

/**
 * Emite um evento e devolve o `event_id`.
 *
 * O `agregado_id` é o `sku` nos quatro, e o `agregado_tipo` é o `const` do
 * contrato de cada um — `product` nos de catálogo, `sku` nos de stock. É por
 * esse par que o `evt_agregado_seq` dá a sequência, e usar o mesmo
 * `agregado_tipo` nos quatro fazia a sequência de preço e a de stock serem a
 * mesma linhagem.
 */
async function emitir(
  cliente: ClienteSql,
  tenantId: string,
  emissao: Emissao,
): Promise<string> {
  validarPayload(emissao.tipo, emissao.versao, emissao.payload);
  const { rows } = await cliente.query(SQL_EMITIR, [
    emissao.tipo,
    emissao.versao,
    tenantId,
    emissao.agregadoTipo,
    emissao.agregadoId,
    JSON.stringify(emissao.payload),
    CLASSE_PII_CATALOGO,
    [...FINALIDADES_CATALOGO],
  ]);
  const id = rows[0]?.["event_id"];
  if (typeof id !== "string") {
    throw new Error(
      `platform.evt_emitir nao devolveu um event_id para ${emissao.tipo}: a ` +
        "alteracao ficou escrita e o evento nao, o que e exactamente o que o " +
        "outbox existe para impedir (KAM-005)",
    );
  }
  return id;
}

/** `catalog.price_changed`. O preço vai no payload — ver a nota do módulo. */
export function emitirPrecoAlterado(
  cliente: ClienteSql,
  tenantId: string,
  sku: string,
  precoTipo: PrecoTipo,
  precoMinor: bigint | null,
  currency: string,
): Promise<string> {
  return emitir(cliente, tenantId, {
    tipo: TIPO_PRICE_CHANGED,
    versao: VERSAO_PRICE_CHANGED,
    agregadoTipo: AGREGADO_PRODUTO,
    agregadoId: sku,
    payload: payloadDoPreco(sku, precoTipo, precoMinor, currency),
  });
}

/**
 * `catalog.product_changed`. É o `product.published` **e** o `product.updated`.
 *
 * Um tipo e não dois, com o `estado` a distingui-los: é o que o contrato
 * publicado tem, e é melhor, porque um consumidor que queira as duas coisas
 * subscreve um e não dois.
 */
export function emitirProdutoAlterado(
  cliente: ClienteSql,
  tenantId: string,
  sku: string,
  estado: EstadoDaOferta,
): Promise<string> {
  return emitir(cliente, tenantId, {
    tipo: TIPO_PRODUCT_CHANGED,
    versao: VERSAO_PRODUCT_CHANGED,
    agregadoTipo: AGREGADO_PRODUTO,
    agregadoId: sku,
    payload: payloadDoProduto(sku, estado),
  });
}

/** `stock.adjusted`. É o `stock.changed` do critério 5. */
export function emitirStockAjustado(
  cliente: ClienteSql,
  tenantId: string,
  sku: string,
  qty: number,
  motivo: MotivoDeAjuste,
): Promise<string> {
  return emitir(cliente, tenantId, {
    tipo: TIPO_STOCK_ADJUSTED,
    versao: VERSAO_STOCK_ADJUSTED,
    agregadoTipo: AGREGADO_SKU,
    agregadoId: sku,
    payload: payloadDoStock(sku, qty, motivo),
  });
}

/** `stock.low`, abaixo do limiar. O único nome do critério 5 que existia. */
export function emitirStockBaixo(
  cliente: ClienteSql,
  tenantId: string,
  sku: string,
  qty: number,
): Promise<string> {
  return emitir(cliente, tenantId, {
    tipo: TIPO_STOCK_LOW,
    versao: VERSAO_STOCK_LOW,
    agregadoTipo: AGREGADO_SKU,
    agregadoId: sku,
    payload: payloadDoStockBaixo(sku, qty),
  });
}
