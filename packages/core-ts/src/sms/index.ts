/**
 * O agregador de SMS para OTP e avisos: o KAM-116.
 *
 * O que um serviço importa daqui é a `SmsProvider` — é ela que o KAM-086 liga ao
 * `OtpProvider` (`sms_local`) e que o KAM-115 usa como `SmsNotifier` — e o
 * `FakeSmsProvider`, que é o que CI e `staging` usam. O resto é exportado porque
 * os ensaios e os tickets a jusante o consomem.
 *
 * ## Metade deste ticket não é código, e não está aqui
 *
 * O bloco do KAM-116 tem duas metades. A primeira é esta: a porta, o *fake*, a
 * idempotência, o recibo autenticado, os modelos, os segredos e as métricas. A
 * segunda é **trabalho humano com credor nomeado**, e nenhuma linha de código a
 * substitui:
 *
 * * **As cotações escritas de ≥ 2 candidatos, a escolha do agregador e o
 *   contrato** são do **fundador** — ele é a única autoridade para contratar
 *   fornecedores. O que está entregue é a **matriz de decisão** com a forma
 *   pronta e os números em falta (`../../../../docs/evidencia/KAM-116.md`).
 * * **O teste de entrega com números reais** (≥ 40 envios por operadora, em ≥ 2
 *   dias e horas distintas) é medição com titulares consentidos. O que está
 *   entregue é o **protocolo** e o **relatório com a forma pronta**, com os
 *   destinos só em HMAC. O repositório é público: nenhum número real entra em
 *   ficheiro nenhum.
 * * **A autorização do subprocessador com `apd_ref`** é do **KAM-069**. O que
 *   está entregue é o *gate*: em `prod`, sem estado `autorizado`, o serviço não
 *   arranca (`fornecedor.ts`).
 * * **O enquadramento legal do tratamento do telefone no estrangeiro** é do
 *   **KAM-104**, a confirmar por parecer.
 *
 * ## Dois números que este módulo mede e **não afirma**
 *
 * A taxa mínima de entrega (**≥ 95% por operadora**) e a latência (**p95 ≤
 * 30 s**) são ***propostas***. A entrega de SMS para a Unitel e a Africell é
 * **NÃO VERIFICADA** (`../../../../docs/tecnica/01` L10;
 * `../../../../docs/tecnica/10` §6.3), e a amostra de 40 envios é **sinal e não
 * prova** — está escrito no critério 3 do próprio bloco. As constantes
 * (`MINIMO_DE_ENTREGA_CENTESIMOS`, o corte de 30 s nos baldes) são o instrumento
 * que as vai medir no Piloto, não a sua confirmação.
 *
 * ## O número operacional da KAMBÁ **não** é assumido
 *
 * O OTP por WhatsApp entra apenas como alternativa condicionada a **D10** e ao
 * **KAM-101**, e o fluxo do KAM-086 não muda por causa dela. Este módulo não
 * tem caminho de WhatsApp, e isso não é omissão: é o que o critério 4 permite e
 * a D10 impede.
 *
 * ## O adaptador do agregador não existe
 *
 * Não há agregador escolhido. Escrever um adaptador para um agregador
 * hipotético era inventar a API dele — nomes de parâmetros, formato do recibo,
 * códigos de erro —, e o ticket diz por escrito «não inventes o facto». O que
 * está entregue é a fronteira que o adaptador vai preencher: a função
 * `Entregar` de `envio.ts` e a `exigirEnvioReal` de `fornecedor.ts`.
 */

export {
  CHAVE,
  CODIGOS_DE_ERRO,
  ChaveInvalidaError,
  ESTADOS,
  OPERADORAS,
  REPETIVEIS,
  SmsError,
  validarChave,
  type CodigoDeErro,
  type Desligar,
  type Estado,
  type Operadora,
  type OuvinteDeRecibo,
  type Recibo,
  type Relogio,
  type ResultadoDeEnvio,
  type SmsProvider,
} from "./contrato.ts";

export { MASCARA, Opaco, INSPECCIONAR } from "./opaco.ts";

export {
  CodigoInvalidoError,
  CodigoOtp,
  DIGITOS_MAXIMOS,
  DIGITOS_MINIMOS,
} from "./codigo.ts";

export {
  ALGARISMOS_NACIONAIS,
  CARACTERES_DO_PREFIXO,
  ChaveDeHmacInvalidaError,
  DOMINIO,
  Destino,
  DestinoInvalidoError,
  INDICATIVO,
  MOTIVOS,
  OCTETOS_DE_HMAC,
  cunharDestino,
  destinoCorresponde,
  normalizarDestino,
  type MotivoDaRecusa,
} from "./destino.ts";

export {
  CARACTERES_POR_SEGMENTO,
  CorpoLongoError,
  CorpoNaoAsciiError,
  FINALIDADES,
  MODELOS,
  ModeloDesconhecidoError,
  NOMES_DE_MODELO,
  PARAMETROS,
  ParametroInvalidoError,
  VALIDADE_MAXIMA_MIN,
  VALIDADE_MINIMA_MIN,
  comprimentoNoPiorCaso,
  construir,
  marcadoresDoModelo,
  type Finalidade,
  type Modelo,
  type NomeDeModelo,
  type Parametro,
  type Parametros,
} from "./modelos.ts";

export {
  ID_DE_RECIBO,
  IdDeReciboInvalidoError,
  RegistoDeEnviosEmMemoria,
  RegistoDeRecibosEmMemoria,
  ReservaInexistenteError,
  type Registo,
  type RegistoDeEnvios,
  type RegistoDeRecibos,
  type Reserva,
} from "./idempotencia.ts";

export {
  ESQUEMAS,
  MOTIVO_MAXIMO,
  PREFIXO,
  RECUSAS,
  RedeInvalidaError,
  autenticado,
  compilarRedes,
  ipPermitido,
  normalizarAssinatura,
  normalizarRecibo,
  receberPedido,
  type Autenticacao,
  type CorpoDeRecibo,
  type Esquema,
  type EntregarRecibo,
  type Interpretar,
  type OpcoesDoPedido,
  type Pedido,
  type Recusa,
  type Rede,
  type Veredicto,
} from "./recibo.ts";

export { Envios, INSTANTES_GUARDADOS, type Entrega, type Entregar, type OpcoesDeEnvios } from "./envio.ts";

export { CORPOS_GUARDADOS, FakeSmsProvider, type EnvioFalso, type OpcoesDoFake } from "./fake.ts";

export {
  AMBIENTE_BLOQUEANTE,
  AgregadorNaoAutorizadoError,
  DADOS,
  DeclaracaoInvalidaError,
  ESTADOS_DO_SUBPROCESSADOR,
  FINALIDADE,
  FORNECEDOR_PENDENTE,
  PAIS_SEM_TRANSFERENCIA,
  VARIAVEIS,
  agregadorDeSms,
  exigirEnvioReal,
  type Declaracao,
  type EstadoDoSubprocessador,
  type ProcessEnv,
  type Subprocessador,
} from "./fornecedor.ts";

export { REFERENCIAS, REF_CREDENCIAL, REF_PEPPER, REF_RECIBO } from "./refs.ts";

export {
  PepperMalFormadoError,
  anelDaCredencial,
  anelDoPepper,
  anelDoRecibo,
} from "./segredos.ts";

export {
  CORTES_DA_LATENCIA,
  EtiquetaInvalidaError,
  JANELA_DO_ALERTA,
  METRICAS_DE_SMS,
  METRICA_ABAIXO,
  METRICA_CUSTO,
  METRICA_ENTREGA,
  METRICA_ENVIADOS,
  METRICA_LATENCIA,
  METRICA_PROBLEMA,
  METRICA_SEM_RECIBO,
  MINIMO_DE_ENTREGA_CENTESIMOS,
  MINOR_POR_KZ,
  MetricasDeSms,
  PROBLEMAS,
  RESULTADOS,
  kzDeMinor,
  razaoDeCentesimos,
  type Problema,
  type Resultado,
} from "./metricas.ts";
