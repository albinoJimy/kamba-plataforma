/**
 * Eventos: envelope v1, outbox, publicador (KAM-005) e consumo (KAM-006).
 *
 * O que entra aqui e o que não entra:
 *
 *     envelope.ts            forma do envelope v1, leitura e recusa
 *     pii.ts                 guarda de padrão de telefone (espelho do `evt_emitir`)
 *     particao.ts            nomes de fila `evt.<consumer>.p<0..15>`
 *     conversor.ts           gancho de conversão de versão — **vazio**
 *     consultas.ts           o SQL do publicador
 *     filas.ts               a porta das filas, e uma fila em memória para testes
 *     filas_bullmq.ts        a implementação sobre BullMQ
 *     metricas.ts            as métricas dos dois critérios de observabilidade
 *     publicador.ts          o laço: ler, entregar, arquivar, marcar
 *     consultas_consumo.ts   o SQL do consumidor
 *     estados.ts             a máquina de estados da encomenda (§6.1)
 *     consumo.ts             a transacção do consumo idempotente
 *     accoes.ts              o `once(key, fn)` dos efeitos externos
 *     dlq.ts                 a fila de mortos, e a severidade pelo tipo
 *     reconciliador.ts       a reposição do que a fila perdeu
 *
 * O **envelope constrói-se em SQL** (`platform.evt_emitir`): não há construtor
 * aqui, de propósito, para não haver duas fontes para a mesma forma. O catálogo
 * de schemas e o teste de compatibilidade são o KAM-007; as subscrições
 * concretas das verticais são o KAM-038.
 *
 * O `filas_bullmq.ts` **não** é reexportado daqui: importa `bullmq`, e quem só
 * quer ler um envelope ou validar um nome de fila não tem de pagar essa
 * dependência. Importa-se pelo caminho (`@kamba/core-ts/eventos/filas_bullmq`).
 */

export {
  type Agregado,
  CAMPOS_DO_ENVELOPE,
  CLASSES_PII,
  type ClassePii,
  type Envelope,
  EnvelopeInvalidoError,
  FINALIDADES,
  type Finalidade,
  lerEnvelope,
} from "./envelope.ts";

export {
  E164_ENTRE_ASPAS,
  PADROES_DE_TELEFONE,
  PadraoDeTelefoneError,
  TELEFONE_AO,
  exigirSemTelefone,
  padraoDeTelefoneEm,
} from "./pii.ts";

export {
  DestinoInvalidoError,
  PARTICOES,
  PREFIXO_DA_FILA,
  exigirParticao,
  filasDe,
  nomeDaFila,
} from "./particao.ts";

export {
  CONVERSORES,
  ConversaoInvalidaError,
  type Conversor,
  RegistoDeConversores,
  SemConversorError,
} from "./conversor.ts";

export {
  CANAL_DE_AVISO,
  LOCK_DO_PUBLICADOR,
  SQL_ARQUIVAR,
  SQL_ATRASO,
  SQL_ELEGER,
  SQL_ESCUTAR,
  SQL_LARGAR,
  SQL_MARCAR_PUBLICADO,
  SQL_PENDENTES,
  SQL_RECUAR,
  SQL_SUBSCRICOES,
} from "./consultas.ts";

export {
  type Filas,
  FilasEmMemoria,
  REPETICAO,
  type Repeticao,
  type Trabalho,
} from "./filas.ts";

export {
  DESFECHOS,
  type Desfecho,
  EtiquetaInvalidaError,
  METRICAS,
  DESFECHOS_DO_CONSUMO,
  type DesfechoDoConsumo,
  MAXIMO_DE_TIPOS,
  METRICA_ATRASO,
  METRICA_CONSUMIDOS,
  METRICA_DLQ_ABERTAS,
  METRICA_ERROS,
  METRICA_LIDER,
  METRICA_PUBLICADOS,
  METRICA_RETENTATIVAS,
  MOTIVOS,
  MOTIVOS_DE_RETENTATIVA,
  Metricas,
  type Motivo,
  type MotivoDeRetentativa,
  TIPO_DE_EVENTO,
} from "./metricas.ts";

export {
  type AccaoInvalidaError,
  ESTADOS_DE_ACCAO,
  type EstadoDeAccao,
  type OpcoesDaAccao,
  type ResultadoDaAccao,
  chaveDaAccao,
  once,
} from "./accoes.ts";

export {
  ADIAMENTO_POR_OMISSAO,
  Adiar,
  ESCADA_DO_CONSUMIDOR,
  type Efeito,
  ForaDeOrdem,
  type OpcoesDoConsumo,
  type ResultadoDoConsumo,
  TENTATIVAS,
  atrasoDaTentativaDoConsumidor,
  consumir,
} from "./consumo.ts";

export {
  SQL_ABRIR_ACCAO,
  SQL_APROVADORES,
  SQL_APROVAR_DESCARTE,
  SQL_A_REPOR,
  SQL_DEFINIR_TENANT,
  SQL_DLQ_ABERTAS,
  SQL_DLQ_POR_ID,
  SQL_FECHAR_ACCAO,
  SQL_FECHAR_DLQ,
  SQL_LER_ACCAO,
  SQL_MARCAR_CONSUMIDO,
  SQL_PARA_DLQ,
  SQL_PAYMENT_SEM_ORDEM,
  SQL_ULTIMO_SEQ,
} from "./consultas_consumo.ts";

export {
  type AberturaPorTipo,
  type EntradaDaDlq,
  type Fecho,
  HORAS_ATE_ALERTAR,
  type OpcoesDaDlq,
  PREFIXOS_SEV1,
  type ResultadoDaDlq,
  type Severidade,
  TIPOS_SEV1,
  abertas,
  aprovadores,
  eSev1,
  fechar,
  paraDlq,
  porId,
  publicarAbertas,
  severidade,
} from "./dlq.ts";

export {
  type ClienteDeLeitura,
  ESTADOS_DA_ENCOMENDA,
  ESTADO_PRETENDIDO,
  EstadoDesconhecidoError,
  type EstadoDaEncomenda,
  type MaquinaDeEstados,
  MaquinaNaBase,
  TRANSICOES,
  eEstado,
  podeTransitar,
} from "./estados.ts";

export {
  CARENCIA_POR_OMISSAO,
  INTERVALO_POR_OMISSAO,
  JANELA_POR_OMISSAO,
  LOCK_DO_RECONCILIADOR,
  LOTE_POR_OMISSAO,
  type LinhaAReporar,
  type OpcoesDoReconciliador,
  type ResultadoDaReposicao,
  SQL_PARTICAO,
  reporUmaVez,
} from "./reconciliador.ts";

export {
  type ClienteSql,
  ESCADA_DE_RECUO,
  type LinhaDoOutbox,
  type OpcoesDoPublicador,
  Publicador,
  type ResultadoDoCiclo,
  SemLiderancaError,
  type Subscricao,
  atrasoDaTentativa,
  destinos,
  esperar,
  motivoDoErro,
} from "./publicador.ts";
