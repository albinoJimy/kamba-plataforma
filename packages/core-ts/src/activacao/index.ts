/**
 * O último troço do onboarding — catálogo mínimo, teste ponta a ponta e
 * activação (KAM-094).
 *
 * O que um serviço importa daqui é a `Activacao`, o `CatalogoMinimo` e o
 * `SmokeOwnerAssisted`, com as portas que eles pedem. Os duplos são exportados
 * pela razão do `../guia/`: CI e `dev` correm sobre eles.
 */

export {
  ActivacaoRecusadaError,
  CATALOGO_MINIMO,
  CAUSAS_DO_TESTE,
  FALHAS_ATE_A_FILA,
  GATES_DE_ACTIVACAO,
  MENSAGEM_DE_FALHA_AO_DONO,
  PALAVRA_DO_TESTE,
  PRAZO_DO_TESTE_S,
  REMETENTES_DO_TESTE,
  RemetenteVedadoError,
  TesteNaoIniciadoError,
} from "./contrato.ts";
export type {
  CasoDeActivacao,
  CatalogoDoTenant,
  CategoriaDoTenant,
  CausaDoTeste,
  EstadoDaOferta,
  FactosDoTeste,
  FaseDoCaso,
  FilaDoTeste,
  GateDeActivacao,
  GateDoKam094,
  GatesDaActivacao,
  MaquinaDoCaso,
  MarcadorDeTeste,
  ObservadorDoTeste,
  PrecoTipo,
  ProdutoDoCatalogo,
  RegistoDoTeste,
  RemetenteDoTeste,
  SmokeProbe,
  TentativaDoTeste,
} from "./contrato.ts";

export { CatalogoMinimo, motivoDeExclusao } from "./catalogo_minimo.ts";
export type { Contagem, DependenciasDoCatalogo, MotivoDeExclusao, ResultadoDaPublicacao } from "./catalogo_minimo.ts";

export {
  causaDosFactos,
  eMensagemDeTeste,
  identificaAssistenteELoja,
  mensagemAoDono,
  normalizarTexto,
  remetenteDoTeste,
  SmokeOwnerAssisted,
  tipoDaFila,
} from "./smoke.ts";
export type { DependenciasDoTeste } from "./smoke.ts";

export { ACTOR_DA_ACTIVACAO, Activacao } from "./gates.ts";
export { filaDoTeste } from "./fila.ts";
export type { DependenciasDaActivacao } from "./gates.ts";

export {
  CatalogoSql,
  CategoriaSql,
  GatesSql,
  MaquinaSql,
  MarcadorSql,
  RegistoDoTesteSql,
  SQL_AVANCAR,
  SQL_CATEGORIA_DECLARADA,
  SQL_FALHAS_SEGUIDAS,
  SQL_FECHAR_TENTATIVA,
  SQL_GATES_EM_FALTA,
  SQL_INICIAR_TENTATIVA,
  SQL_LER_CASO,
  SQL_MARCAR_CONVERSA_DE_TESTE,
  SQL_MARCAR_GATE,
  SQL_PRODUTOS,
  SQL_TENTATIVA_CORRENTE,
  SQL_ZERAR_FALHAS,
} from "./sql.ts";

export {
  CicloDaActivacao,
  INTERVALO_DA_ACTIVACAO_POR_OMISSAO_MS,
  PASSOS_DA_ACTIVACAO,
  SQL_CASOS_DA_ACTIVACAO,
} from "./ciclo.ts";
export type { OpcoesDoCicloDaActivacao, PassoDaActivacao, ResultadoDoCicloDaActivacao } from "./ciclo.ts";

export { ObservadorPorWebhook } from "./observador.ts";
export type { LojaDoTeste } from "./observador.ts";

export {
  CatalogoEmMemoria,
  CategoriaEmMemoria,
  FilaDoTesteEmMemoria,
  GatesEmMemoria,
  MaquinaEmMemoria,
  MarcadorEmMemoria,
  RegistoDoTesteEmMemoria,
} from "./memoria.ts";
