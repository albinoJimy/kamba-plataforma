/**
 * `@kamba/core-ts/identity` — identidade de contacto em duas camadas (KAM-008).
 *
 * ```ts
 * import { EnvKeyProvider, Identidade } from "@kamba/core-ts/identity";
 *
 * const identidade = await Identidade.arrancar({
 *   chaves: new EnvKeyProvider({ ambiente: "dev" }),
 * });
 * const { contactId } = await identidade.resolveContact(cliente, {
 *   tenantId, bsuid: mensagem.from_user_id, telefone: mensagem.from,
 * });
 * ```
 *
 * `cliente` é uma ligação de `kamba_identity`. O que sai daqui para o resto da
 * plataforma é o `contact_id` — e mais nada. Ver `docs/identidade.md`.
 */

export {
  AmbienteDeIdentidadeError,
  ChaveDesconhecidaError,
  ChaveMalFormadaError,
  EmbrulhoInvalidoError,
  EnvKeyProvider,
  EpocaInvalidaError,
  KeyProviderDeAmbienteError,
  OCTETOS_DE_CHAVE,
  REF_CHAVE_DE_EPOCA,
  REF_CHAVE_DE_PESQUISA,
  REF_KEK,
  SecretsKeyProvider,
  VARIAVEL_DE_AMBIENTE,
  epocaDe,
  epocaValida,
  exigirKeyProviderDeCofre,
  gerarChaveVersionada,
  kidValido,
} from "./chaves.ts";
export type {
  DekEmbrulhada,
  EnvKeyProviderOpcoes,
  KeyProvider,
  SecretsKeyProviderOpcoes,
} from "./chaves.ts";

export {
  CifraInvalidaError,
  IdentificadorInvalidoError,
  OCTETOS_DE_HMAC,
  OCTETOS_DE_SUJEITO_REF,
  TIPOS,
  cifrar,
  contextoDaCifra,
  contextoDoEmbrulho,
  decifrar,
  hmacDePesquisa,
  normalizarBsuid,
  normalizarTelefone,
  normalizarUuid,
  novaDek,
  sujeitoRefDe,
} from "./cripto.ts";
export type { CampoCifrado, Tipo } from "./cripto.ts";

export {
  CONTADORES_DE_IDENTIDADE,
  ClienteInvalidoError,
  ContactoApagadoError,
  ContactoDesconhecidoError,
  DekDestruidaError,
  FINALIDADES,
  Identidade,
  IdentidadeInconsistenteError,
  KidInvalidoError,
  KidNaoActualError,
  KidReutilizadoError,
  LOTE_DE_ROTACAO,
  METRICA_APAGAR,
  METRICA_LER,
  METRICA_REPETICOES,
  METRICA_RESOLVER,
  METRICA_RODAR,
  PedidoSemIdentificadorError,
  RetencaoInvalidaError,
  RotacaoEmCursoError,
  SemChaveActualError,
  TENTATIVAS,
} from "./contactos.ts";
export type {
  ClienteDeIdentidade,
  ContactoResolvido,
  ContextoDeFusao,
  Desfecho,
  EndpointsDoContacto,
  EventoContactMerged,
  Finalidade,
  GanchoDeFusao,
  Linha,
  OpcoesDeIdentidade,
  OpcoesDeRotacao,
  PedidoDeResolucao,
  ResultadoDaRotacao,
  ResultadoDeIniciarRotacao,
  ResultadoDoApagamento,
  ResultadoSql,
} from "./contactos.ts";

export * as CONSULTAS from "./consultas.ts";
