/**
 * `@kamba/core-ts/keyring` — o anel de chaves e a rotação (KAM-072).
 *
 * Os Detalhes Técnicos do bloco nomeiam `libs/keyring`. Entregou-se em
 * `packages/core-ts/src/keyring/` pela razão que o KAM-010 já registou para
 * `secrets/`: os dois consumidores (GWY e PAY) são TypeScript, e um módulo fora
 * do `rootDir: src` não compila. O desvio é de caminho, não de âmbito.
 */

export {
  type Anel,
  type ChaveDoAnel,
  ChaveVaziaError,
  KidDoAnelInvalidoError,
  KidRepetidoError,
  anelInicial,
  anteriorViva,
  assinar,
  chavesVivas,
  gerarValor,
  kidValido,
  novoKid,
  revogarAnterior,
  rodar,
  valoresIguais,
  valoresVivos,
} from "./anel.ts";
export {
  type AccaoDeRotacao,
  AnelInexistenteError,
  AnelJaIniciadoError,
  type CofreDeAneis,
  CofreEmMemoria,
  DIA_MS,
  type EntradaDeRotacao,
  JANELA_POR_OMISSAO_DIAS,
  JanelaAbertaError,
  KidJaUsadoError,
  type KidsLidos,
  type OpcoesDoRotador,
  type RegistoDeRotacao,
  RegistoEmMemoria,
  type ResultadoDaRotacao,
  RotacaoConcorrenteError,
  Rotador,
  ValorRepetidoError,
  janelaDe,
} from "./rotacao.ts";
export {
  type Amostra,
  type EstadoDaIdade,
  type IdadeDoSegredo,
  LIMIAR_DE_ALERTA,
  type PoliticaDeRotacao,
  amostras,
  estadoDa,
  idadesDosSegredos,
} from "./idade.ts";
export {
  ChavePartilhadaEntreAmbientesError,
  REFS_SEPARADAS_POR_AMBIENTE,
  verificarSeparacaoDeAmbientes,
} from "./separacao.ts";
export {
  type DependenciasDaRecifra,
  LOTE_DA_RECIFRA,
  type Recifra,
  RecifraSemPapelDeLoteError,
  type ResultadoDaRecifra,
  SQL_CANAIS_A_RECIFRAR,
  SQL_PAPEL_ATRAVESSA_TENANTS,
  SQL_TROCAR_TOKEN_REF,
  anelDaKekNoCofre,
  anelPorKid,
  recifrarToken,
  recifrarTokensGuardados,
} from "./tokens.ts";
export {
  ACCAO_DE_REVOGAR,
  ACCAO_DE_RODAR,
  type AuditoriaDeRotacao,
  AuditoriaDeRotacaoSql,
  type ClienteSqlDeAuditoria,
  SQL_AUDITAR_ROTACAO,
  resumoDaAccao,
} from "./auditoria.ts";
