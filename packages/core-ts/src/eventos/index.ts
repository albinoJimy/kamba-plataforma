/**
 * Eventos: envelope v1, outbox e publicador (KAM-005).
 *
 * O que entra aqui e o que não entra:
 *
 *     envelope.ts       forma do envelope v1, leitura e recusa
 *     pii.ts            guarda de padrão de telefone (espelho do `evt_emitir`)
 *     particao.ts       nomes de fila `evt.<consumer>.p<0..15>`
 *     conversor.ts      gancho de conversão de versão — **vazio**
 *     consultas.ts      o SQL do publicador
 *     filas.ts          a porta das filas, e uma fila em memória para testes
 *     filas_bullmq.ts   a implementação sobre BullMQ
 *     metricas.ts       as três métricas do critério 8
 *     publicador.ts     o laço: ler, entregar, arquivar, marcar
 *
 * O **envelope constrói-se em SQL** (`platform.evt_emitir`): não há construtor
 * aqui, de propósito, para não haver duas fontes para a mesma forma. Os
 * consumidores, a `events_consumed` e a DLQ são o KAM-006; o catálogo de
 * schemas e o teste de compatibilidade são o KAM-007.
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
  METRICA_ATRASO,
  METRICA_ERROS,
  METRICA_LIDER,
  METRICA_PUBLICADOS,
  MOTIVOS,
  Metricas,
  type Motivo,
} from "./metricas.ts";

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
