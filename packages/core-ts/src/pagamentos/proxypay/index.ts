/**
 * O adaptador ProxyPay (KAM-056) e as duas *flags* que o guardam.
 *
 * Os «Detalhes Tecnicos» do bloco escrevem
 * `services/pay/src/adapters/proxypay/{rps,opg,verify,reconcile}.ts`, e
 * `services/pay/` **nao existe** nesta arvore: e a divida documental 148, e a
 * mesma decisao do KAM-052, que pos o `pay-core` em `packages/core-ts/src/pagamentos/`.
 * Os quatro modulos tem os nomes do bloco, e o `http.ts` e o transporte que
 * os tres primeiros partilham.
 *
 * ## As duas *flags*, e porque nenhuma basta sozinha
 *
 *     proxypay_enabled       sem contrato (D4, KAM-103) fica `false` e o
 *                            Piloto segue em `ManualProvider`
 *     proxypay_opg_enabled   a segunda *flag* do Objectivo; exige a primeira
 *
 * Ligar uma *flag* nao activa o adaptador: o `activar` do registo continua a
 * exigir a suite de conformidade verde **no sandbox** (§3.5), e essa e a
 * corrida que so o `ext:KAM-103` torna possivel. E o OPG, sem consulta
 * confirmada por escrito, e recusado com `ADAPTER_CANNOT_CONFIRM` mesmo com as
 * duas ligadas.
 */

import type { RegistoDeProviders } from "../registo.ts";
import type { PaymentProvider } from "../tipos.ts";

export type FlagsProxyPay = {
  readonly proxypayEnabled: boolean;
  readonly proxypayOpgEnabled: boolean;
};

/** As omissoes: as duas desligadas (criterio 9). */
export const FLAGS_PROXYPAY_OMISSAO: FlagsProxyPay = {
  proxypayEnabled: false,
  proxypayOpgEnabled: false,
};

export const PROXYPAY_DESLIGADO = "PROXYPAY_DESLIGADO";

export class ProxyPayDesligado extends Error {
  readonly codigo = PROXYPAY_DESLIGADO;
  constructor(mensagem: string) {
    super(mensagem);
    this.name = "ProxyPayDesligado";
  }
}

/**
 * Activa no registo os adaptadores que as *flags* deixam. Um adaptador
 * oferecido com a *flag* dele desligada **recusa**, em vez de ser ignorado: um
 * arranque que pedisse o OPG e seguisse sem ele escondia uma configuracao
 * errada.
 */
export function activarProxyPay(
  registo: RegistoDeProviders,
  flags: FlagsProxyPay,
  adaptadores: { readonly rps?: PaymentProvider; readonly opg?: PaymentProvider },
): void {
  if (adaptadores.rps !== undefined) {
    if (!flags.proxypayEnabled) {
      throw new ProxyPayDesligado(
        "proxypay_enabled=false: o adaptador RPS so se activa com contrato (D4, KAM-103); " +
          "sem ele o Piloto segue em ManualProvider (criterio 9)",
      );
    }
    registo.activar(adaptadores.rps);
  }
  if (adaptadores.opg !== undefined) {
    if (!flags.proxypayEnabled || !flags.proxypayOpgEnabled) {
      throw new ProxyPayDesligado(
        "o OPG exige proxypay_enabled e proxypay_opg_enabled (criterio 8)",
      );
    }
    registo.activar(adaptadores.opg);
  }
}

export {
  APROVACAO_OPG_MS,
  AVISO_ANTI_PHISHING,
  CriacaoIncerta,
  EXPIRACAO_OPG_MS,
  ID_PROXYPAY_OPG,
  JANELA_DE_IDEMPOTENCIA_OPG_MS,
  ProxyPayOpg,
  TentativasOpgEmMemoria,
  capacidadesOpg,
  estadoDaTransaccao,
  mensagemOpg,
  type ContaOpg,
  type MensagemOpg,
  type OpcoesOpg,
  type TentativaOpg,
  type TentativasOpg,
} from "./opg.ts";
export {
  ALVO_DO_LAG_P99_MS,
  PAGINAS_POR_VOLTA,
  PERIODO_DA_RECONCILIACAO_MS,
  ExpiracaoAdiada,
  Reconciliador,
  antesDeExpirar,
  percentil,
  reconciliarConta,
  type CobrancaNossa,
  type ContaParaReconciliar,
  type DecisaoDeExpiracao,
  type DependenciasDaReconciliacao,
  type FilaRps,
  type ResultadoDaReconciliacao,
  type VoltaDaReconciliacao,
} from "./reconcile.ts";
export {
  AMOUNT_MAXIMO_RPS,
  AMOUNT_MINIMO_RPS,
  CAPACIDADES_RPS,
  ID_PROXYPAY_RPS,
  PAGINA_DA_FILA,
  ProxyPayRps,
  ReferenciasEmMemoria,
  baseSegura,
  type ContaProxyPay,
  type ContasProxyPay,
  type OpcoesRps,
  type ReferenciaEmitida,
  type ReferenciasEmitidas,
  type ResolverDeChave,
} from "./rps.ts";
export {
  CABECALHO_X_SIGNATURE,
  assinaturaRps,
  assinaturaVerifica,
  chaveUtilizavel,
  eventoDoPagamento,
  exigirAssinatura,
  lerPagamentoRps,
  payloadDoPagamento,
  type PagamentoRps,
} from "./verify.ts";
export {
  ErroDeTransporte,
  RECUO_PROPOSTO,
  codigoDoEstado,
  comRecuo,
  pedir,
  recuoComJitter,
  transporteFetch,
  type ParametrosDeRecuo,
  type PedidoHttp,
  type RespostaHttp,
  type Transporte,
} from "./http.ts";
