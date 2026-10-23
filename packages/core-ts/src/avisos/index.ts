/**
 * O aviso ao dono por canal alternativo: o KAM-115.
 *
 * O que um serviço importa daqui é a `AvisoAoDono` — é ela o `OwnerNotifier` dos
 * *Detalhes Técnicos*, e é a ela que o CHR entrega os eventos de falha de canal
 * que o KAM-017 (`desligado`, `channel.inactivity_warning`), o KAM-021
 * (`restrito` por qualidade) e o KAM-023 (`motivo_restricao='payment_method'`)
 * emitem. O resto é exportado porque os ensaios e os tickets a jusante o
 * consomem: o `decidir` é a tabela dos limites do critério 4, e o `construir` é
 * a lista branca de modelos do critério 5.
 *
 * **Este é o último ticket do EPIC-02, e fecha a lacuna R16** — «sem ticket para
 * avisar o dono por canal alternativo em `PARTNER_REMOVED`, inactividade ou
 * falha de pagamento Meta». Os emissores existiam desde o KAM-017; o que não
 * existia era quem entrega.
 *
 * ## Uma caixa fica por marcar, e não por falta de trabalho
 *
 * * **O alvo de «≥ 95% dos tenants `ativo` com contacto verificado»** (critério
 *   6) é uma medição sobre tenants reais, e não há nenhum: a métrica que o mede
 *   está entregue (`owner_alt_contact_missing`, com numerador e denominador), a
 *   varredura que a alimenta também, e o número sai no Piloto. Afirmar a
 *   percentagem contra dois tenants de ensaio era afirmar 100% de nada.
 * * **A escolha do fornecedor de e-mail** (critério 8) é um subprocessador com
 *   contrato e procedimento APD (KAM-069, ADR-008), e não há escolha feita —
 *   fazê-la num ficheiro de código era exactamente o que o ADR-008 existe para
 *   impedir. O que o critério deixa como alternativa está **entregue**: o
 *   `fornecedor.ts` lê a declaração do ambiente e, em `prod`, com o fornecedor
 *   fora de Angola ou por escolher e sem `apd_ref`, **o serviço não arranca**.
 *   O valor por omissão é `pendente`, e `pendente` em `prod` é um arranque
 *   recusado. A caixa marca-se por isso, e o que fica por decidir é **qual** o
 *   fornecedor — que não é trabalho deste ticket.
 *
 * O SMS não é uma caixa vazia: o próprio critério 8 e os *Fora de âmbito*
 * mandam-no para o KAM-116, e o lugar dele é a interface `Notificador`.
 */

export {
  ATRASO_DO_LEMBRETE_MS,
  CANAIS,
  CANAIS_COM_ENDERECO,
  ESTADOS,
  GATILHOS,
  JANELA_DIARIA_MS,
  JANELA_DO_GATILHO_MS,
  LATENCIA_ALVO_MS,
  LEMBRETE_MAXIMO,
  LEMBRETES,
  LIMIAR_DO_PAINEL_MS,
  MOTIVOS_DE_FALHA,
  MOTIVOS_DE_INVALIDEZ,
  MOTIVOS_DE_SUPRESSAO,
  OCTETOS_DE_RESUMO,
  OCTETOS_DO_TOKEN,
  PRAZO_DA_CONFIRMACAO_MS,
  TECTO_DIARIO,
  type AbrirTarefa,
  type Aviso,
  type AvisoRenderizado,
  type Canal,
  type ClienteSql,
  type Contacto,
  type Decifrar,
  type Estado,
  type Gatilho,
  type Lembrete,
  type LembreteDevido,
  type MotivoDeFalha,
  type MotivoDeSupressao,
  type Notificador,
  type NovoToken,
  type Relogio,
  type ResultadoDaEntrega,
  type ResultadoDaVarredura,
  type ResultadoDoAviso,
} from "./contrato.ts";

export {
  chaveDoEpisodio,
  condenaOEndereco,
  confirmacaoValida,
  contactoUtilizavel,
  decidir,
  gatilhoConhecido,
  lembreteDevido,
  lembretesEsgotados,
  precisaDeEndereco,
  resumoDoToken,
  type Decisao,
} from "./decisao.ts";

export {
  construir,
  gatilhosComModelo,
  mascarar,
  MASCARA,
  MAXIMO_DA_LOJA,
  ModeloEmFaltaError,
  PARAMETROS,
  ParametroInvalidoError,
  prepararLoja,
  type Parametro,
  type Parametros,
} from "./modelos.ts";

export {
  CORTES_DA_LATENCIA,
  CONTADORES,
  GAUGES,
  HISTOGRAMAS,
  METRICA_ENVIADOS,
  METRICA_FALHADOS,
  METRICA_LATENCIA,
  METRICA_SEM_CONTACTO,
  METRICA_SUPRIMIDOS,
  METRICAS_DO_AVISO,
  MetricaDesconhecidaError,
  MetricasDoAviso,
  SufixoInvalidoError,
  type Contador,
} from "./metricas.ts";

export {
  AvisoAoDono,
  CanalDesconhecidoError,
  CanalDuplicadoError,
  ESTADOS_NO_TEXTO,
  EstadoInvalidoError,
  horaDeLuanda,
  PainelInvalidoError,
  type EstadoNoTexto,
  type PedidoDeAviso,
} from "./avisos.ts";

export {
  AMBIENTE_BLOQUEANTE,
  DeclaracaoInvalidaError,
  FORNECEDOR_PENDENTE,
  fornecedorDeEmail,
  FornecedorSemApdRefError,
  PAIS_SEM_TRANSFERENCIA,
  VARIAVEIS,
  type Declaracao,
  type ProcessEnv,
  type Subprocessador,
} from "./fornecedor.ts";

export {
  SQL_CONFIRMAR,
  SQL_CONTACTO,
  SQL_EMITIR_CONFIRMACAO,
  SQL_ENTREGUE,
  SQL_EPISODIOS_PARA_LEMBRETE,
  SQL_FALHOU,
  SQL_HISTORICO,
  SQL_INVALIDAR,
  SQL_NOME_DA_LOJA,
  SQL_REGISTAR,
  SQL_TENANTS_ATIVOS,
  SQL_TENANTS_SEM_CONTACTO,
} from "./consultas.ts";
