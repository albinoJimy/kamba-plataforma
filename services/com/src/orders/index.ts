/**
 * Módulo `orders` do COM — encomendas: máquina de estados e espelho (KAM-044).
 *
 *     contrato.ts     o vocabulário: tipos, causas, eventos, SQLSTATE
 *     consultas.ts    as cadeias SQL, confrontadas pelo gate 8
 *     graph.ts        o grafo, lido da base, e o predicado
 *     eventos.ts      os cinco eventos de encomenda, pelo outbox
 *     mirror.ts       a criação do espelho e o `order.created`
 *     transition.ts   a primitiva `transition` com CAS por `version`
 *     reconcile.ts    as cinco regras de §10.3 (decisão pura + escrita local)
 *
 * e, do KAM-046, a saga da criação de pedido:
 *
 *     intents.ts            a `intent_key` e o `draft_hash` (critério 2)
 *     cart.ts               o `propose_cart`, leitura e total no backend
 *     create_order.ts       a saga em duas transacções, idempotente pela chave
 *     owner_confirmation.ts o fluxo do dono para itens críticos
 *
 * **Uma operação é método da porta `CommerceRegistry`** — a `transition` —, e o
 * adaptador (`../adapters/medusa/`) é que a liga; o `mirror` é a primitiva de
 * escrita que a `createOrder` do **KAM-046** vai usar, e não a `createOrder`.
 * As outras não estão na porta e não vão estar: o dicionário §3.39 fecha-a em
 * doze métodos, pinados por `port.contrato.test.ts`.
 *
 * O esquema é da revisão `0030`; o grafo, os `CHECK`, a RLS `FORCE` e os três
 * *triggers* vivem lá, e **é lá que as regras são impostas** — não aqui. Este
 * módulo chega-lhes com erros de domínio em vez de SQLSTATE, e é a única coisa
 * que acrescenta.
 */

export {
  ACTOR_DO_PAGAMENTO,
  AGREGADO_ORDER,
  CAUSAS_QUE_PAGAM,
  CAUSA_DA_RECONCILIACAO,
  CHAVE_DO_TECTO_MANUAL,
  CLASSE_PII_ENCOMENDA,
  EVENTO_POR_ESTADO,
  FINALIDADES_ENCOMENDA,
  SQLSTATE_AUTENTICIDADE,
  SQLSTATE_CHECK,
  SQLSTATE_FK,
  SQLSTATE_REGISTO,
  SQLSTATE_SNAPSHOT,
  SQLSTATE_TECTO_MANUAL,
  SQLSTATE_TRANSICAO,
  SQLSTATE_UNICIDADE,
  TIPO_CANCELLED,
  TIPO_CREATED,
  TIPO_DELIVERED,
  TIPO_EXPIRED,
  TIPO_PAID,
  VERSAO_CANCELLED,
  VERSAO_CREATED,
  VERSAO_DELIVERED,
  VERSAO_EXPIRED,
  VERSAO_PAID,
  VIA_POR_CAUSA,
  type CausaDaTransicao,
  type CausaQuePaga,
  type ClienteSql,
  type EspelhoNovo,
  type EstadoDaEncomenda,
  type LinhaDaEncomenda,
  type Transicao,
} from "./contrato.ts";

export {
  SQL_CONCLUIR_INTENCAO,
  SQL_CONFIRMACAO_DO_DONO,
  SQL_DIVERGENCIAS_ABERTAS,
  SQL_EMITIR,
  SQL_FALHAR_INTENCAO,
  SQL_FECHAR_DIVERGENCIA,
  SQL_GRAFO,
  SQL_LER,
  SQL_LISTAR,
  SQL_ENCOMENDA_DA_CHAVE,
  SQL_LER_CONFIRMACAO,
  SQL_LER_INTENCAO,
  SQL_PEDIDO_POR_PAGAR,
  SQL_RETOMAR_INTENCAO,
  SQL_TRANSITAR,
  SQL_VISTA,
} from "./consultas.ts";

export { destinosDe, lerGrafo, transicaoPermitida } from "./graph.ts";

export {
  EMISSOES,
  emitir,
  linhasDoPayload,
  payloadDeCancelada,
  payloadDeCriada,
  payloadDeEntregue,
  payloadDeExpirada,
  payloadDePaga,
} from "./eventos.ts";

export { TABELA_DO_ESPELHO, registar } from "./mirror.ts";

export {
  TABELA_DO_REGISTO,
  comoResultadoDaPorta,
  lerEncomenda,
  pagamentoAutenticado,
  transition,
  type Encomendas,
  type PedidoDeTransicao,
  type RepoDoTenant,
  type ResultadoDaTransicao,
} from "./transition.ts";

export {
  TABELA_DAS_DIVERGENCIAS,
  TIPOS_DE_DIVERGENCIA,
  abertas,
  aplicar,
  fechar,
  reconciliar,
  type Aplicacao,
  type Divergencia,
  type EncomendaNoEspelho,
  type EncomendaNoRegisto,
  type Fotografia,
  type ReservaNoRegisto,
  type TipoDeDivergencia,
} from "./reconcile.ts";

// ------------------------------------------------------------------- KAM-046

export {
  ALFABETO,
  CARACTERES_DA_CHAVE,
  OCTETOS_DO_SEGREDO,
  ParteInvalidaError,
  REF_SEGREDO_DE_INTENTS,
  SegredoMalFormadoError,
  cartId,
  cartIdValido,
  chavesDoAnel,
  concatenar,
  draftHash,
  emBase32,
  intentKey,
  lerSegredo,
  linhasCanonicas,
  mesmoDraftHash,
  type AnelDoSegredo,
  type LinhaDoRascunho,
  type PartesDaIntencao,
  type Rascunho,
  type SegredoVersionado,
} from "./intents.ts";

export {
  MOEDA,
  ORIGENS_DE_PRECO,
  STOCK_QUE_EXIGE_O_DONO,
  precoValido,
  proposeCart,
  resolverLinha,
  totalDaProposta,
  type Leitura,
  type LinhaResolvida,
  type OrigemDePreco,
  type PedidoDeProposta,
  type Proposta,
  type RascunhoDoCarrinho,
} from "./cart.ts";

export {
  CONFIRMACOES_DO_DONO,
  ERROS_DA_CRIACAO,
  ESTADOS_POR_PAGAR,
  INTERVALO_DE_ESPERA_MS,
  MINUTOS_DO_PEDIDO_POR_PAGAR,
  MINUTOS_PARA_RETOMAR,
  TABELA_DAS_INTENCOES,
  TECTO_DE_ESPERA_MS,
  concluirIntencao,
  createOrder,
  decidirSobreRecibo,
  lerRecibos,
  pedidoPorPagar,
  reservarIntencao,
  type AbrirTransaccao,
  type AutoridadeDeStock,
  type ConfirmacaoDoDono,
  type EncomendaCriada,
  type ErroDaCriacao,
  type MontagemDaCriacao,
  type PedidoDeCriacao,
  type PedidoPorPagar,
  type Recibo,
  type ResultadoDaCriacao,
} from "./create_order.ts";

// ------------------------------------------------- KAM-178: as duas leituras

export {
  DOMINIO_DO_CURSOR,
  LIMITE_MAXIMO,
  LIMITE_POR_OMISSAO,
  LISTAGEM_SEM_FILTRO,
  OCTETOS_DA_ASSINATURA,
  cifrarCursor,
  comoVista,
  filtroLido,
  getOrder,
  lerCursor,
  listOrders,
  type FiltroLido,
  type PosicaoDaPagina,
} from "./listagem.ts";

export {
  CAUSA_DA_RECUSA,
  CAUSA_DO_SILENCIO,
  MINUTOS_PARA_O_DONO,
  MINUTOS_PARA_O_LEMBRETE,
  confirmarPeloDono,
  decidirPorSilencio,
  expirarConfirmacao,
  recusarPeloDono,
  requestOwnerConfirmation,
  type AccaoPorSilencio,
  type CancelamentoPeloDono,
  type ResultadoDaConfirmacao,
} from "./owner_confirmation.ts";

// ------------------------------------------------------------------- KAM-050

export {
  EXCEPCOES,
  MOTIVOS_DE_REEMBOLSO,
  TIPO_EXCEPTION,
  TIPO_REFUND_REQUESTED,
  VERSAO_EXCEPTION,
  VERSAO_REFUND_REQUESTED,
  type Excepcao,
  type MotivoDeReembolso,
} from "./contrato.ts";

export {
  SQL_ABRIR_RERESERVA,
  SQL_AUDITAR_REEMBOLSO,
  SQL_DESFAZER_RERESERVA,
  SQL_FECHAR_RERESERVA,
  SQL_MARCAR_EXCEPCAO,
} from "./consultas.ts";

export { payloadDeExcepcao, payloadDeReembolsoPedido } from "./eventos.ts";

export {
  ACTORES_DO_REEMBOLSO,
  CAUSA_DO_REEMBOLSO,
  MOTIVO_POR_ORIGEM,
  REEMBOLSADA,
  actorDoReembolso,
  eFimDeDisputa,
} from "./graph_ext.ts";

export {
  ESTADOS_JA_PAGOS,
  ReReservaRecusadaError,
  aplicarPagamentoExcedente,
  aplicarPagamentoTardio,
  linhasARefazer,
  ramoDoPagamento,
  type DesfechoTardio,
  type PagamentoRecebido,
  type RamoDoPagamento,
} from "./late_payment.ts";

export {
  ACCAO_DO_REEMBOLSO,
  CHAVE_DO_PRAZO,
  ENTIDADE_DO_REEMBOLSO,
  auditarReembolso,
  dentroDoPrazo,
  diasDesdeAEntrega,
  textoDoReembolso,
} from "./refunds.ts";
