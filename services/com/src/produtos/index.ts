/**
 * Módulo `produtos` do COM — preço opaco e stock não-garantido (KAM-043).
 *
 *     contrato.ts    o vocabulário: tipos, domínios fechados, constantes
 *     consultas.ts   as cadeias SQL, confrontadas pelo gate 8
 *     formato.ts     `precoDisplay`, disponibilidade e avisos (funções puras)
 *     auditoria.ts   `audit_append` para `price.update` e `stock.adjust`
 *     eventos.ts     os quatro eventos de catálogo e de stock, pelo outbox
 *     produtos.ts    as operações, ctx-first
 *
 * Três operações **são** métodos da porta `CommerceRegistry` — o
 * `upsertProductDraft`, o `publishProduct` e o `getOfferView` —, e o adaptador
 * (`../adapters/medusa/`) liga-as. As outras quatro não estão na porta e não vão
 * estar: o dicionário §3.39 fecha-a em doze métodos, pinados por
 * `port.contrato.test.ts`, e o critério 8 diz por escrito que o contrato não
 * expõe a pesquisa a longo prazo.
 *
 * O esquema é da revisão `0028`; a RLS `FORCE`, os `CHECK` e a chave composta
 * `(tenant_id, sku)` vivem lá, e **é lá que a colisão de SKU entre tenants é
 * impossível** — não aqui.
 */

export {
  ACCAO_PRECO,
  ACCAO_STOCK,
  ACTOR_AUDITADO,
  AGREGADO_PRODUTO,
  AGREGADO_SKU,
  A_PARTIR_DE,
  AVISOS,
  CLASSE_PII_CATALOGO,
  ENTIDADE_AUDITADA,
  ESTADOS_DA_COTACAO,
  ESTADOS_DA_OFERTA,
  FINALIDADES_CATALOGO,
  MAXIMO_DE_RESULTADOS,
  MOEDA,
  MOTIVOS_DE_AJUSTE,
  ORIGENS_DE_PRECO,
  PRECO_TIPOS,
  RELOGIO_DO_SISTEMA,
  SOB_CONSULTA,
  STOCK_BAIXO_LIMIAR,
  STOCK_MODOS,
  STOCK_POR_CONFIRMAR_MS,
  TIPO_PRICE_CHANGED,
  TIPO_PRODUCT_CHANGED,
  TIPO_STOCK_ADJUSTED,
  TIPO_STOCK_LOW,
  VERSAO_PRICE_CHANGED,
  VERSAO_PRODUCT_CHANGED,
  VERSAO_STOCK_ADJUSTED,
  VERSAO_STOCK_LOW,
  type AjusteDeStock,
  type Aviso,
  type ClienteSql,
  type Cotacao,
  type EstadoDaCotacao,
  type EstadoDaOferta,
  type MotivoDeAjuste,
  type OrigemDePreco,
  type PedidoDeCotacao,
  type PrecoTipo,
  type RascunhoDeProduto,
  type Relogio,
  type ResultadoDaPesquisa,
  type StockModo,
  type TermosDaOferta,
  type VistaDaOferta,
} from "./contrato.ts";

export {
  SQLSTATE_CHECK,
  SQLSTATE_FK,
  SQLSTATE_UNICIDADE,
  SQL_ACEITAR_COTACAO,
  SQL_ACTUALIZAR_TERMOS,
  SQL_AJUSTAR_STOCK,
  SQL_AUDITAR,
  SQL_COTACAO_VALIDA,
  SQL_EMITIR,
  SQL_PESQUISAR,
  SQL_PUBLICAR,
  SQL_TERMOS,
  SQL_TERMOS_PARA_ESCRITA,
} from "./consultas.ts";

export {
  DISPONIBILIDADE,
  MOEDA_DE_APRESENTACAO,
  PREFIXO_A_PARTIR_DE,
  SEPARADOR_DE_MILHARES,
  SUFIXO_DA_MOEDA,
  TEXTO_SOB_CONSULTA,
  avisosDaOferta,
  formatarMinor,
  precoDisplay,
  precoTipoEfectivo,
  precoVencido,
  stockPorConfirmar,
  vistaDaOferta,
} from "./formato.ts";

export {
  ORIGENS,
  SEPARADOR,
  auditarPreco,
  auditarStock,
  canonico,
  textoDoHash,
  type Instantaneo,
  type Origem,
} from "./auditoria.ts";

export {
  emitirPrecoAlterado,
  emitirProdutoAlterado,
  emitirStockAjustado,
  emitirStockBaixo,
  payloadDoPreco,
  payloadDoProduto,
  payloadDoStock,
  payloadDoStockBaixo,
} from "./eventos.ts";

export {
  aceitarCotacao,
  ajustarStock,
  confirmacaoValida,
  emitirCotacao,
  getOfferView,
  getValidQuote,
  publishProduct,
  searchOffers,
  upsertProductDraft,
  vistaDaOfertaCompleta,
} from "./produtos.ts";
