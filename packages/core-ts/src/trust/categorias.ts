/**
 * As categorias de produto de uma oferta: a lista fechada (KAM-209).
 *
 * A fonte é `policy/categorias_de_produto.yaml`, decisão do fundador de
 * 2026-11-21; isto é a cópia que o COM (a recusa de um rascunho fora dela) e a
 * varredura do preço anómalo (as que não se avaliam) usam. O
 * `libs/py-core/tests/test_categorias_de_produto.py` lê o ficheiro e recusa esta
 * cópia se divergir, como recusa o `CHECK offer_terms_categoria_ck` da revisão
 * `0088` e a cópia Python do catálogo por IA.
 *
 * Os termos que levam o texto livre a um `id` não estão aqui: só o catálogo por
 * IA os usa (`kamba_core.catalogo.categorias`).
 */

/** A versão da lista, a do ficheiro da política. */
export const VERSAO_DAS_CATEGORIAS = "1.0.0";

/** A categoria de quem não cabe nas outras. Não se avalia. */
export const CATEGORIA_OUTRA = "outra";

/** A lista fechada, pela ordem da política. */
export const CATEGORIAS_DE_PRODUTO = [
  "moda",
  "mercearia",
  "restauracao",
  "beleza",
  "electronica",
  "servicos",
  "material_construcao",
  CATEGORIA_OUTRA,
] as const;

export type CategoriaDeProduto = (typeof CATEGORIAS_DE_PRODUTO)[number];

export function eCategoriaDeProduto(valor: unknown): valor is CategoriaDeProduto {
  return typeof valor === "string" && (CATEGORIAS_DE_PRODUTO as readonly string[]).includes(valor);
}

/** As que a varredura do preço anómalo avalia: todas menos a `outra`. */
export function avaliaPreco(categoria: CategoriaDeProduto): boolean {
  return categoria !== CATEGORIA_OUTRA;
}
