/**
 * Trust & Safety — o contrato (KAM-097).
 *
 * Depois da activação, o registo falso mostra-se no comportamento: a PME que
 * cobra e não entrega, a listagem copiada, a auto-compra para fabricar
 * histórico. Este módulo transforma eventos e varreduras em **sinais**
 * (`ts_signal`), compõe-nos num risco, e executa uma **escada** de sanções
 * registada e recorrível (`ts_sanction`).
 *
 * ```text
 * evento ──► efeito (kamba_app) ──► ts_signal ──► risco ──► aviso | limitacao   (automáticos)
 * varredura (kamba_batch) ───────► ts_signal
 * proposta humana ──► review_case 'trust' ──► decisão (KAM-089) ──► suspensao | encerramento
 * recurso ──► review_case ('recurso' ou o recurso do próprio caso) ──► provido | negado
 * ```
 *
 * ## A decisão grave é sempre humana, e passa pela fila
 *
 * `suspensao` e `encerramento` não têm caminho automático: a máquina propõe, e
 * a proposta é um caso `trust` da fila de revisão (`../revisao/`), decidido por
 * T&S com papel e MFA. **`rejeitar` o caso aplica a sanção** — a decisão é
 * sobre o tenant, como num caso `kyc` —, e `aprovar` deixa-o como está. É essa
 * leitura que faz o recurso cair no mecanismo que a fila já tem: um recurso por
 * decisão, só de uma rejeição, decidido por quem não decidiu a primeira.
 *
 * Os passos automáticos (`aviso`, `limitacao`) recorrem-se por um caso
 * `recurso` com o `motivo_codigo` `sancao:<id>`: a chave da fila faz dele único,
 * e a fila recusa recorrer de um recurso.
 *
 * ## O dono nunca lê a heurística
 *
 * O que sai para o dono é um código de `MOTIVOS_PUBLICOS_DA_SANCAO`, com texto
 * fixo. O motivo interno, a regra e os sinais ficam no T&S, e a base nem os
 * deixa ler ao `kamba_app`.
 */

import { LIMIARES_POR_OMISSAO } from "../revisao/contrato.ts";
import type { Passo, PoliticaDeRisco, Severidade, TipoDeSinal } from "./regras.ts";

/** As chaves que o `detalhe` de um sinal admite. A base fecha-as por `CHECK`. */
export const CHAVES_DO_DETALHE = ["order_id", "coincidencia", "contagem", "sku", "versao_politica", "pedidos"] as const;
export type ChaveDoDetalhe = (typeof CHAVES_DO_DETALHE)[number];
export type DetalheDoSinal = Readonly<Partial<Record<ChaveDoDetalhe, string | number | readonly string[]>>>;

/** Um sinal por gravar. A severidade não vem de quem grava: é a do tipo. */
export interface SinalNovo {
  readonly tenantId: string;
  readonly tipo: TipoDeSinal;
  /** O evento, ou o agregado quando o sinal é por agregado (uma encomenda, uma ingestão). */
  readonly refEvento: string;
  readonly detalhe: DetalheDoSinal;
  readonly ocorridoEm: Date;
}

export interface SinalGravado extends SinalNovo {
  readonly id: string;
  readonly severidade: Severidade;
}

/** As origens de uma sanção. Domínio de `ts_sanction.origem`. */
export const ORIGENS = ["automatica", "humana"] as const;
export type Origem = (typeof ORIGENS)[number];

/** O desfecho de um recurso. Domínio de `ts_sanction.recurso_estado`. */
export const DESFECHOS_DO_RECURSO = ["provido", "negado"] as const;
export type DesfechoDoRecurso = (typeof DESFECHOS_DO_RECURSO)[number];

/**
 * O que o dono lê. Lista **fechada**, com texto fixo: quem decide não escreve
 * texto livre para o dono, e o ensaio «nunca se revela a heurística» é
 * verdadeiro por construção. Domínio de `ts_sanction.motivo_publico`.
 */
export const MOTIVOS_PUBLICOS_DA_SANCAO = [
  "conduta_em_analise",
  "actividade_limitada",
  "loja_suspensa",
  "loja_encerrada",
  "recurso_aceite",
  "recurso_mantido",
] as const;
export type MotivoPublicoDaSancao = (typeof MOTIVOS_PUBLICOS_DA_SANCAO)[number];

/** O motivo público de cada passo. */
export const MOTIVO_DO_PASSO: Readonly<Record<Passo, MotivoPublicoDaSancao>> = {
  aviso: "conduta_em_analise",
  limitacao: "actividade_limitada",
  suspensao: "loja_suspensa",
  encerramento: "loja_encerrada",
};

/** ASCII e curto: é também o corpo do SMS (`../sms/modelos.ts`). */
export const TEXTO_DO_MOTIVO_DA_SANCAO: Readonly<Record<MotivoPublicoDaSancao, string>> = {
  conduta_em_analise: "A actividade da sua loja esta em analise pela equipa KAMBA. Pode recorrer uma vez.",
  actividade_limitada: "A sua loja nao pode publicar produtos novos ate nova analise. Pode recorrer uma vez.",
  loja_suspensa: "A sua loja foi suspensa pela equipa KAMBA. Pode recorrer uma vez.",
  loja_encerrada: "A equipa KAMBA decidiu encerrar a sua loja. Pode recorrer uma vez.",
  recurso_aceite: "O seu recurso foi aceite e a medida foi levantada.",
  recurso_mantido: "O seu recurso foi analisado e a medida mantem-se. Esta decisao e final.",
};

/** Uma sanção por gravar: um passo, ou o desfecho de um recurso. */
export interface SancaoNova {
  readonly tenantId: string;
  /** `auto:…`, `caso:<review_case>` ou `recurso:<ts_sanction>`. A idempotência. */
  readonly chave: string;
  readonly passo: Passo;
  readonly origem: Origem;
  /** Só para T&S. Nunca sai para o dono. */
  readonly motivoInterno: string;
  readonly motivoPublico: MotivoPublicoDaSancao;
  /** O `revisor.id` de quem decidiu, ou `sistema:<versão da política>`. */
  readonly autor: string;
  readonly regra: string | null;
  /** Os `ts_signal.id` em que a sanção assenta. */
  readonly sinais: readonly string[];
  readonly casoId: string | null;
  readonly justificacaoDoSalto: string | null;
  readonly recursoDe: string | null;
  readonly recursoEstado: DesfechoDoRecurso | null;
}

export interface SancaoGravada extends SancaoNova {
  readonly id: string;
  readonly em: Date;
}

/**
 * Onde os sinais e as sanções vivem. Duas implementações: `./sql.ts` (sobre um
 * cliente que já está na transacção certa) e `./memoria.ts` (os ensaios).
 *
 * Gravar é idempotente pela chave: `repetido` diz se a linha já existia, e o
 * que volta é **a que existia**.
 */
export interface RepositorioDeTrust {
  gravarSinal(s: SinalNovo): Promise<{ readonly sinal: SinalGravado; readonly repetido: boolean }>;
  sinaisDoTenant(tenantId: string): Promise<readonly SinalGravado[]>;
  gravarSancao(s: SancaoNova): Promise<{ readonly sancao: SancaoGravada; readonly repetido: boolean }>;
  sancoesDoTenant(tenantId: string): Promise<readonly SancaoGravada[]>;
}

/**
 * O estado do tenant, para as duas transições desta escada que mudam o estado.
 * A base só tem um escritor, o `kamba_batch` (`0007`); `transitar` é um CAS:
 * muda só se o estado actual é um dos `de`.
 */
export interface EstadoDosTenants {
  estado(tenantId: string): Promise<string | null>;
  transitar(tenantId: string, de: readonly string[], para: string): Promise<boolean>;
}

/** O aviso ao dono de um passo ou de um recurso. Nunca leva a heurística. */
export interface AvisoDeSancao {
  avisar(pedido: { readonly tenantId: string; readonly motivo: MotivoPublicoDaSancao }): Promise<void>;
}

/** Os limiares do lado do serviço. Todos *proposta*. */
export interface LimiaresDoServico {
  /** Dias depois de um `encerramento` sem recurso em que o tenant passa a `encerrado`. */
  readonly diasDoRecurso: number;
  /** Prioridade do caso de uma proposta grave (1 é a mais urgente). */
  readonly prioridadeDaProposta: number;
}

/**
 * O prazo de recurso é o da fila (`diasDoRecursoDeTrust`), e não um segundo
 * número: com dois, a fila aceitava um recurso depois de o encerramento fechar.
 */
export const LIMIARES_DO_SERVICO: LimiaresDoServico = {
  diasDoRecurso: LIMIARES_POR_OMISSAO.diasDoRecursoDeTrust,
  prioridadeDaProposta: 3,
};

export type Relogio = () => Date;

export interface ConfiguracaoDoTrust {
  readonly politica?: PoliticaDeRisco;
  readonly limiares?: LimiaresDoServico;
  readonly relogio?: Relogio;
}

/** Porque é que uma operação de T&S se recusou. */
export const MOTIVOS_DE_RECUSA_DO_TRUST = [
  "sem_motivo",
  "salto_sem_justificacao",
  "grave_automatica",
  "passo_desconhecido",
  "nao_e_grave",
  "sancao_inexistente",
  "recurso_ja_usado",
  "detalhe_invalido",
] as const;
export type MotivoDeRecusaDoTrust = (typeof MOTIVOS_DE_RECUSA_DO_TRUST)[number];

export class TrustRecusadoError extends Error {
  override readonly name = "TrustRecusadoError";
  readonly motivo: MotivoDeRecusaDoTrust;
  constructor(motivo: MotivoDeRecusaDoTrust) {
    super(`trust & safety recusou: ${motivo}`);
    this.motivo = motivo;
  }
}

/** A independência de um pedido, como o KAM-096 a lê. Sem avaliação, não conta. */
export type Independencia = "independente" | "nao_independente" | "por_avaliar";

/** O que está em vigor num tenant, para quem tem de o fazer cumprir. */
export interface RestricoesEmVigor {
  readonly passo: Passo | null;
  /** `limitacao` ou acima: sem produtos nem listas novos (o catálogo cumpre). */
  readonly semNovosProdutos: boolean;
  /** `limitacao` ou acima: o tecto volta ao nível 0 (o KAM-096 cumpre). */
  readonly tectoNoNivelZero: boolean;
}

/** O `autor` de uma sanção automática. */
export function autorDoSistema(p: PoliticaDeRisco): string {
  return `sistema:${p.versao}`;
}
