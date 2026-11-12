/**
 * O screening de categorias (KAM-088): a política Meta ∪ lei como
 * *policy-as-code*, o motor de regras com classificador barato, o `screen`, o
 * `assertPublishable` e a re-análise por versão.
 *
 * A política vem de `policy/categorias/politica.yaml`, compilada no módulo
 * gerado; `politicaCorrente()` devolve-a já compilada, e falha alto se o
 * gerado não compilar.
 */

import { POLITICA } from "./politica.gerada.ts";
import { compilar, type PoliticaCompilada } from "./regras.ts";

export { POLITICA };

let compilada: PoliticaCompilada | undefined;

/** A política da versão corrente, compilada uma vez. */
export function politicaCorrente(): PoliticaCompilada {
  compilada ??= compilar(POLITICA);
  return compilada;
}

export * from "./tipos.ts";
export { normalizar, MINIMO_PARA_COMPACTA, type TextoNormalizado } from "./normalizar.ts";
export {
  avaliarRegras,
  bloqueadasEm,
  compilar,
  CONFIANCA,
  fundirSobreposicao,
  grau,
  LIMIAR_DE_CONFIANCA,
  LIMITES_DA_ENTRADA,
  maxRestricao,
  PREFIXO_APROXIMADO,
  REGRA_ENTRADA_EXCEDIDA,
  VERSAO_DO_MOTOR,
  PoliticaInvalidaError,
  REGRA_NAO_LISTADA,
  SobreposicaoRelaxaError,
  type DecisaoDasRegras,
  type EntradaCompilada,
  type EntradaDaSobreposicao,
  type PoliticaCompilada,
  type Sobreposicao,
} from "./regras.ts";
export {
  ALIAS_DO_CLASSIFICADOR,
  cabeNoPedido,
  classificadorPorProxy,
  ESQUEMA_DA_RESPOSTA,
  INSTRUCOES,
  LIMITES_DO_PEDIDO,
  lerVeredicto,
  prepararPedido,
  semDadosPessoais,
  tecto,
  VeredictoInvalidoError,
  type ClassificadorDeCategorias,
  type OpcoesDoProxy,
  type PedidoAoClassificador,
  type VeredictoDoClassificador,
} from "./classificador.ts";
export {
  assertPublishable,
  conteudoSha256,
  NaoPublicavelError,
  REGRA_CLASSIFICADOR,
  REGRA_CLASSIFICADOR_INDISPONIVEL,
  REGRA_CLASSIFICADOR_PARCIAL,
  screen,
  type ChaveDaDecisao,
  type DependenciasDoScreen,
  type EscritorDeDecisoes,
  type LeitorDeDecisoes,
  type LinhaDeDecisao,
  type ProdutoAPublicar,
  type Sujeito,
} from "./motor.ts";
export {
  reanalisar,
  type EmissorDeViolacoes,
  type LeitorDoCatalogo,
  type Orcamento,
  type PorProduto,
  type ProdutoPublicado,
  type ResultadoDaReanalise,
  type Violacao,
} from "./reanalise.ts";
export { CatalogoSql, EscritorSql, LeitorSql, SQL_DECISOES, SQL_GRAVAR, SQL_POR_REANALISAR, type ClienteSql } from "./sql.ts";
