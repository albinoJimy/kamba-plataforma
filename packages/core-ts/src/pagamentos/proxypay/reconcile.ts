/**
 * O *job* de reconciliacao do RPS e a expiracao (KAM-056, criterios 4 e 5).
 *
 * «O *job* de reconciliacao corre de 5 em 5 min por conta activa e antes de
 * expirar uma reserva; so chama `DELETE /payments/{id}` **depois** do *commit*
 * e so para cobrancas nossas; um pagamento desconhecido gera alerta e nao e
 * reconhecido.»
 *
 * ## As duas regras do §8, e onde cada uma morde
 *
 * (a) **Nunca `DELETE` antes do *commit*.** O `processar` e a porta para o
 *     *worker* do §5.1, e o contrato dela e resolver **so depois** do *commit*
 *     no ledger. O `acknowledge` vem a seguir ao `await`, e um `processar` que
 *     levante deixa o pagamento na fila: reaparece na volta seguinte, e o G7
 *     absorve-o se afinal tinha ficado escrito.
 * (b) **So reconhecer cobrancas nossas.** Se a PME usar a mesma conta ProxyPay
 *     noutra integracao (uma loja web), um `DELETE` do nosso *job* roubava-lhe o
 *     pagamento. Um pagamento sem cobranca nossa — ou com um `charge` nos
 *     `custom_fields` que nao e o nosso — e **orfao**: passa pelo `processar`
 *     (que o regista como `pagamento_orfao`, G3) e pelo alerta, e nunca pelo
 *     `DELETE`.
 *
 * ## O que este ficheiro nao e
 *
 * Nao e o *worker* do §5.1, nem escreve no ledger: a reconciliacao «nao tem
 * poder especial» (§8) e passa pelos mesmos G1-G8 que o callback. O agendador
 * de producao vive no servico `pay`, que nao existe nesta arvore (divida 148);
 * o `agendarReconciliacao` daqui e a forma que ele tem de chamar.
 */

import { type AccountSecrets, type Uuid, type VerifiedEvent } from "../tipos.ts";
import { comRecuo, type ParametrosDeRecuo, RECUO_PROPOSTO } from "./http.ts";
import { PAGINA_DA_FILA } from "./rps.ts";
import { eventoDoPagamento, type PagamentoRps } from "./verify.ts";

/** «De 5 em 5 min por conta activa» (§8). */
export const PERIODO_DA_RECONCILIACAO_MS = 5 * 60_000;

/** O alvo do criterio 5: `reconciliation_lag` p99 <= 10 min. */
export const ALVO_DO_LAG_P99_MS = 10 * 60_000;

/**
 * Quantas paginas de 100 le uma volta. **Proposta**: com orfaos na fila, uma
 * pagina pode repetir-se sem progresso, e o ciclo tem de ter fim.
 */
export const PAGINAS_POR_VOLTA = 10;

/** A cobranca nossa a que um pagamento corresponde (G3). */
export type CobrancaNossa = { readonly chargeId: Uuid };

export type FilaRps = {
  pagamentosPorReconhecer(acct: AccountSecrets): Promise<readonly PagamentoRps[]>;
  acknowledge(acct: AccountSecrets, providerPaymentId: string): Promise<void>;
};

export type DependenciasDaReconciliacao = {
  readonly fila: FilaRps;
  /** G3: `payment_charges` por `(account_id, referencia)`. */
  cobrancaNossa(accountId: Uuid, referencia: string): Promise<CobrancaNossa | undefined>;
  /**
   * O *worker* do §5.1 para um evento. **Resolve so depois do *commit***, e e
   * esse o contrato que torna a regra (a) verdadeira. Idempotente pelo G7.
   */
  processar(acct: AccountSecrets, evento: VerifiedEvent, pagamento: PagamentoRps): Promise<void>;
  /** F-03: alerta a ops. Sem PII: o pagamento RPS nao tem pagador. */
  alertarOrfao(accountId: Uuid, pagamento: PagamentoRps): Promise<void>;
  readonly agora?: () => number;
  readonly recuo?: ParametrosDeRecuo;
  readonly dormir?: (ms: number) => Promise<void>;
};

export type VoltaDaReconciliacao = {
  readonly resultados: ReadonlyMap<Uuid, ResultadoDaReconciliacao>;
  readonly falhas: ReadonlyMap<Uuid, unknown>;
};

export type ResultadoDaReconciliacao = {
  /**
   * Uma pagina cheia sem nada que se pudesse reconhecer: a fila nao tem cursor,
   * e cem orfaos (ou falhas) a cabeca tapam o resto dela. Ver o `rps.ts`. Quem
   * destapa e ops; ate la, nenhuma decisao de expirar se toma sobre esta conta.
   */
  readonly filaBloqueada: boolean;
  readonly lidos: number;
  readonly reconhecidos: number;
  readonly orfaos: number;
  readonly falhasDeProcessamento: number;
  readonly falhasDeReconhecimento: number;
  /**
   * `reconciliation_lag` de cada pagamento **nosso** processado: do instante do
   * pagamento ao *commit*. Os orfaos ficam de fora — nao tem lag, ficam na fila
   * de proposito —, e um pagamento reprocessado por um `DELETE` falhado conta
   * outra vez, que e a leitura conservadora. O servico `pay` publica-o.
   */
  readonly lagsMs: readonly number[];
};

/** Uma volta sobre uma conta. Nunca levanta por causa de um pagamento. */
export async function reconciliarConta(
  acct: AccountSecrets,
  deps: DependenciasDaReconciliacao,
): Promise<ResultadoDaReconciliacao> {
  const agora = deps.agora ?? Date.now;
  const vistos = new Set<string>();
  const lagsMs: number[] = [];
  const resultado = {
    filaBloqueada: false,
    lidos: 0,
    reconhecidos: 0,
    orfaos: 0,
    falhasDeProcessamento: 0,
    falhasDeReconhecimento: 0,
    lagsMs,
  };
  for (let pagina = 0; pagina < PAGINAS_POR_VOLTA; pagina += 1) {
    const fila = await comRecuo(
      () => deps.fila.pagamentosPorReconhecer(acct),
      deps.recuo ?? RECUO_PROPOSTO,
      deps.dormir,
    );
    const novos = fila.filter((p) => !vistos.has(p.id));
    if (novos.length === 0) {
      // A pagina repetiu-se inteira: se estava cheia, ha mais fila atras dela
      // que nao se consegue ler.
      resultado.filaBloqueada = fila.length >= PAGINA_DA_FILA;
      break;
    }
    for (const pagamento of novos) {
      vistos.add(pagamento.id);
      resultado.lidos += 1;
      await _umPagamento(acct, pagamento, deps, agora, resultado);
    }
    // Uma pagina incompleta e a fila inteira: nao ha mais nada para ler.
    if (fila.length < PAGINA_DA_FILA) break;
  }
  return resultado;
}

async function _umPagamento(
  acct: AccountSecrets,
  pagamento: PagamentoRps,
  deps: DependenciasDaReconciliacao,
  agora: () => number,
  resultado: {
    reconhecidos: number;
    orfaos: number;
    falhasDeProcessamento: number;
    falhasDeReconhecimento: number;
    lagsMs: number[];
  },
): Promise<void> {
  const nossa = await deps.cobrancaNossa(acct.accountId, pagamento.referencia);
  // O `charge` dos `custom_fields` desempata: um pagamento a mesma referencia
  // com o `charge` de outra integracao nao e nosso.
  // **Sem `charge` nao e nosso**: enviamo-lo sempre, e o E2 §1.2 da como
  // CONFIRMADO que passa para o pagamento. Uma referencia com o mesmo numero
  // posta por outra integracao da PME, sem ele, ia ser apagada da fila dela.
  const ehNossa = nossa !== undefined && pagamento.chargeId === nossa.chargeId;
  try {
    await deps.processar(acct, eventoDoPagamento(pagamento, "consulta"), pagamento);
  } catch {
    // Sem *commit* nao ha `DELETE` (regra a). O pagamento fica na fila e volta.
    resultado.falhasDeProcessamento += 1;
    return;
  }
  if (!ehNossa) {
    resultado.orfaos += 1;
    await deps.alertarOrfao(acct.accountId, pagamento);
    return;
  }
  resultado.lagsMs.push(agora() - Date.parse(pagamento.ocorridoEm));
  try {
    await deps.fila.acknowledge(acct, eventoDoPagamento(pagamento, "consulta").providerEventId);
    resultado.reconhecidos += 1;
  } catch {
    // «Se o `DELETE` falhar, o pagamento reaparece e G7 absorve-o» (criterio 5).
    resultado.falhasDeReconhecimento += 1;
  }
}

/**
 * O percentil `p` (1..100) de uma lista de duracoes, pelo metodo do posto mais
 * proximo. Inteiros, sem `Math`: ver `http.ts`.
 */
export function percentil(valores: readonly number[], p: number): number {
  if (valores.length === 0) return 0;
  const ordenados = [...valores].sort((a, b) => a - b);
  const produto = ordenados.length * p;
  const posto = (produto - (produto % 100)) / 100 + (produto % 100 === 0 ? 0 : 1);
  return ordenados[(posto < 1 ? 1 : posto) - 1] ?? 0;
}

/** Uma conta de pagamento, como o agendador a ve. */
export type ContaParaReconciliar = {
  readonly segredos: AccountSecrets;
  /** `payment_accounts.estado` (§10.2). So `activa` se reconcilia. */
  readonly estado: string;
};

/**
 * O agendador: uma volta por conta activa a cada 5 min, e a forma de pedir uma
 * volta fora de horas («antes de expirar uma reserva», §8).
 *
 * Nunca corre duas voltas sobre a mesma conta ao mesmo tempo: duas voltas
 * concorrentes leriam a mesma pagina e processariam cada pagamento duas vezes
 * — o G7 absorvia, mas o `DELETE` sairia em dobro.
 */
export class Reconciliador {
  readonly #deps: DependenciasDaReconciliacao;
  readonly #contas: () => Promise<readonly ContaParaReconciliar[]>;
  readonly #emCurso = new Map<Uuid, Promise<ResultadoDaReconciliacao>>();

  constructor(
    deps: DependenciasDaReconciliacao,
    contas: () => Promise<readonly ContaParaReconciliar[]>,
  ) {
    this.#deps = deps;
    this.#contas = contas;
  }

  /**
   * Uma volta sobre cada conta activa. **Uma conta que falhe nao para as
   * outras**: uma chave revogada numa PME deixava sem reconciliacao todas as
   * que vem depois dela na lista, de 5 em 5 min e em silencio. A falha fica em
   * `falhas`, e o `agendar` entrega-a ao `aoFalhar`.
   */
  async volta(): Promise<VoltaDaReconciliacao> {
    const resultados = new Map<Uuid, ResultadoDaReconciliacao>();
    const falhas = new Map<Uuid, unknown>();
    for (const conta of await this.#contas()) {
      if (conta.estado !== "activa") continue;
      try {
        resultados.set(conta.segredos.accountId, await this.conta(conta.segredos));
      } catch (erro) {
        falhas.set(conta.segredos.accountId, erro);
      }
    }
    return { resultados, falhas };
  }

  /**
   * Uma volta sobre uma conta; se ja houver uma a correr, espera por ela.
   *
   * `fresca` pede uma volta que **comece depois** deste pedido: a que ja corria
   * pode ter lido a fila antes de um pagamento chegar. E a que o
   * `antesDeExpirar` usa. A exclusao e so dentro deste processo.
   */
  async conta(acct: AccountSecrets, fresca = false): Promise<ResultadoDaReconciliacao> {
    const emCurso = this.#emCurso.get(acct.accountId);
    if (emCurso !== undefined) {
      if (!fresca) return emCurso;
      await emCurso.catch(() => undefined);
      return this.conta(acct, fresca);
    }
    const nova = reconciliarConta(acct, this.#deps).finally(() => this.#emCurso.delete(acct.accountId));
    this.#emCurso.set(acct.accountId, nova);
    return nova;
  }

  /**
   * Arranca o relogio. Devolve a funcao que o para. O `programar` e o
   * `setInterval` em producao; nos ensaios e um relogio falso.
   */
  agendar(
    aoFalhar: (erro: unknown, accountId?: Uuid) => void,
    programar: (fn: () => void, ms: number) => () => void = _setInterval,
  ): () => void {
    return programar(() => {
      this.volta()
        .then(({ falhas }) => {
          for (const [accountId, erro] of falhas) aoFalhar(erro, accountId);
        })
        .catch((erro: unknown) => aoFalhar(erro));
    }, PERIODO_DA_RECONCILIACAO_MS);
  }
}

function _setInterval(fn: () => void, ms: number): () => void {
  const id = setInterval(fn, ms);
  return () => clearInterval(id);
}

/** O estado a que a expiracao chega. */
export type DecisaoDeExpiracao = "paga" | "expirar";

/**
 * «Antes de expirar uma reserva» (§8, e 03 §6.5): reconcilia a conta e so
 * depois decide.
 *
 * A ordem e o que importa. Um pagamento cujo callback se perdeu esta na fila do
 * facilitador e nao no ledger; expirar sem ler a fila era expirar uma encomenda
 * paga e soltar o stock de um cliente que ja pagou. A volta poe-no no ledger
 * (pelo `processar`), e a decisao le-se **depois**, do ledger.
 *
 * **E so decide sobre uma volta limpa.** Se algum `processar` falhou, ou a
 * fila esta bloqueada, o pagamento desta cobranca pode ser precisamente o que
 * nao entrou — e a Multicaixa nao admite devolucao. Levanta, e quem chama
 * volta a tentar em vez de expirar.
 */
export async function antesDeExpirar(
  reconciliador: Reconciliador,
  acct: AccountSecrets,
  estaPaga: () => Promise<boolean>,
): Promise<DecisaoDeExpiracao> {
  const volta = await reconciliador.conta(acct, true);
  if (await estaPaga()) return "paga";
  if (volta.falhasDeProcessamento > 0 || volta.filaBloqueada) {
    throw new ExpiracaoAdiada(acct.accountId, volta.filaBloqueada ? "fila bloqueada" : "processamento falhado");
  }
  return "expirar";
}

/** A volta antes de expirar nao foi limpa: nao se decide sobre ela. */
export class ExpiracaoAdiada extends Error {
  readonly accountId: Uuid;
  constructor(accountId: Uuid, motivo: string) {
    super(`a reconciliacao antes de expirar nao foi limpa (${motivo}): a expiracao fica adiada`);
    this.name = "ExpiracaoAdiada";
    this.accountId = accountId;
  }
}
