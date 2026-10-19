/**
 * TEN — entitlements, limites e a matriz de estados do CHR (KAM-009).
 *
 * TEN decide o que cada tenant pode usar: que modulos (verticais) estao
 * activos e que limites tem. O REG consulta o entitlement ao activar uma
 * vertical (`docs/tecnica/02` §5.2); a ToolLayer verifica limites em cada
 * `invoke` (§6.1, passo 2); o CHR usa a matriz de estados (`01` §7.2).
 *
 *     checkEntitlement   falha fechada: sem linha, inactivo, ou tenant
 *                        `onboarding`/`suspenso`/`encerrado` -> negado
 *     consumeLimit       atomico e idempotente, porque chama `ten_consumir`.
 *                        **So baldes por periodo** (`x-kamba-consumivel`)
 *     checkCeiling       «este valor cabe no tecto?». **So tectos por
 *                        pedido**, e nao escreve nada
 *     tenantGate         a matriz do §7.2, com os **dois** estados
 *     guardaHttp         403 ENTITLEMENT_DISABLED / 403 e 429 LIMIT_EXCEEDED
 *     CacheDeEntitlements  TTL; a alteracao fica visivel em <= 60 s
 *     MetricasDoTen      ten_limit_denied_total / ten_entitlement_denied_total
 *
 * **A regra nao vive aqui.** A aritmetica de limites e o fuso do periodo estao
 * na revisao `0007` (`platform.ten_consumir`, `platform.ten_periodo`) e o
 * criterio do entitlement esta no `SQL_ENTITLEMENT` do `consultas.ts`. Este
 * pacote chama; o espelho em `kamba_core.ten` chama o mesmo, e ha testes que
 * confrontam os dois como texto.
 *
 * Nao se re-exporta pelo `src/index.ts` da raiz: esse so leva o que **todos**
 * os servicos precisam. Importa-se por `@kamba/core-ts/ten`.
 */

export {
  SQL_CONSUMIR,
  SQL_ENTITLEMENT,
  SQL_PERIODO,
  SQL_TECTO,
} from "./consultas.ts";

export {
  CATEGORIA_CONTADOR,
  CATEGORIA_TECTO_POR_JANELA,
  CATEGORIA_TECTO_POR_PEDIDO,
  CHAVES_DE_LIMITE,
  CODIGO_ENTITLEMENT_HTTP,
  CODIGO_ENTITLEMENT_TOOL,
  CODIGO_LIMITE,
  CacheDeEntitlements,
  ChaveDeEspecieErradaError,
  ChaveDeIdempotenciaInvalidaError,
  ChaveDesconhecidaError,
  ConflitoDeIdempotenciaError,
  HTTP_ENTITLEMENT,
  HTTP_LIMITE,
  HTTP_TECTO,
  MAXIMO_DE_ENTRADAS,
  NOME_CANONICO,
  NomeInvalidoError,
  QuantidadeInvalidaError,
  RespostaIlegivelError,
  SQLSTATE_CONFLITO_DE_IDEMPOTENCIA,
  TTL_POR_OMISSAO_MS,
  agoraMs,
  checkCeiling,
  checkEntitlement,
  consumeLimit,
  derivarChaveDeIdempotencia,
  especieDaChave,
  exigirConsumivel,
  exigirNome,
  exigirTecto,
  inteiro,
  periodo,
  sqlstateDe,
  type CategoriaDaChave,
  type ChaveDeLimite,
  type ClienteSql,
  type Consumo,
  type Entitlement,
  type MotivoDaRecusa,
  type Tecto,
} from "./entitlements.ts";

export {
  ACCOES,
  ESTADOS_DO_CANAL,
  ESTADOS_DO_TENANT,
  EstadoDesconhecidoError,
  REGIMES,
  REGIMES_E_ACCOES,
  REGIME_DO_CANAL,
  REGIME_DO_TENANT,
  maisRestritivo,
  regimeDe,
  tenantGate,
  type Accao,
  type DecisaoDoGate,
  type EstadoDoCanal,
  type EstadoDoTenant,
  type Regime,
} from "./estados.ts";

export {
  ETIQUETA,
  EtiquetaInvalidaError,
  MAXIMO_DE_SERIES,
  METRICA_ENTITLEMENT_NEGADO,
  METRICA_LIMITE_NEGADO,
  METRICAS,
  MetricasDoTen,
} from "./metricas.ts";

export {
  CABECALHO_DE_IDEMPOTENCIA,
  guardaHttp,
  type ContextoDoPedido,
  type OpcoesDoMiddleware,
  type Pedido,
  type Recusa,
} from "./middleware.ts";
