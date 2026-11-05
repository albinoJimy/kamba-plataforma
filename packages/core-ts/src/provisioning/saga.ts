/**
 * A saga de provisioning: execução, *backoff*, escalada e compensação inversa
 * (KAM-091).
 *
 * A saga é dirigida por eventos (`tenant.approved`, ADR-009) e o consumidor é
 * idempotente por `event_id` (`events_consumed`, KAM-006) — essa parte é do
 * KAM-092 e não daqui. O que está aqui é a máquina de estados, e é ela que se
 * pode provar inteira sem Chatwoot, sem LiteLLM e sem Medusa a correr:
 *
 * - **idempotência por passo** (critérios 1 e 4),
 * - **ordem inversa da compensação** (critério 3),
 * - ***backoff* sem retry infinito** (critério 5),
 * - **esperas que não gastam tentativa** (critério 6),
 * - **o WABA e o número do cliente nunca se apagam** (critério 7).
 *
 * ## O `attempt` lê-se da base e não de uma variável
 *
 * O `abrir` incrementa e devolve a linha; o `correr` decide pelo número que
 * veio de lá. Um contador em memória reiniciava com o processo, e a saga corre
 * num consumidor de fila que reinicia — três tentativas tornavam-se infinitas
 * sem que nada no código mudasse. É a mesma razão pela qual o
 * `onboarding/metricas.ts` recusa um contador em memória para a janela de sete
 * dias.
 */

import {
  ESPERA_DO_PASSO,
  PASSOS,
  AguardaEntradaError,
  SagaEscaladaError,
  type AccaoDeCompensacao,
  type ArmazemDePassos,
  type CanalDoCliente,
  type Caso,
  type ChaveDeLlm,
  type Entitlements,
  type InboxDeAtendimento,
  type LinhaDePasso,
  type Passo,
  type RegistoDeCanalDeComercio,
  type RegistoDoCaso,
} from "./contrato.ts";
import { executarNoCanalDoCliente, verificar } from "./compensacao.ts";
import { montarPassos, type DefinicaoDePasso, type Dependencias as DependenciasDosPassos } from "./passos.ts";
import {
  METRICA_COMPENSADO,
  METRICA_ESCALADO,
  METRICA_FALHAS,
  METRICA_PRIMEIRA_TENTATIVA,
  Metricas,
  METRICAS,
} from "./metricas.ts";
import type { Logger } from "../logger/index.ts";

/** O tecto de tentativas do critério 5. **Três, e não há quarta.** */
export const TENTATIVAS = 3;

/** A base do *backoff* exponencial, em milissegundos. */
export const BACKOFF_BASE_MS = 1_000;

/**
 * O atraso antes da tentativa `n` (1-based). Exponencial, **com tecto**.
 *
 * `n = 1` dá zero: a primeira tentativa não espera. Depois é
 * `base * 2^(n-2)` — 1 s antes da 2.ª e 2 s antes da 3.ª.
 *
 * Função pura e exportada **de propósito**: o critério 5 tem duas metades («1–3
 * com *backoff* exponencial» e «sem retry infinito») e são provas diferentes. A
 * primeira mede-se aqui, com números, sem relógio nem fila; a segunda mede-se
 * no `correr`, contando chamadas. Juntá-las num só teste obrigava a esperar
 * segundos reais para medir uma multiplicação.
 */
export function atrasoDaTentativa(n: number): number {
  if (n <= 1) return 0;
  return BACKOFF_BASE_MS * 2 ** (n - 2);
}

/** O que a saga devolve ao fim de uma passagem. */
export interface Desfecho {
  /** `concluida` quando os oito passos estão `concluido`. */
  readonly estado: "concluida" | "aguarda" | "falhou" | "escalada";
  /** O passo onde parou, ou `null` se terminou. */
  readonly passo: Passo | null;
  /** Em quantas tentativas o passo que parou está. */
  readonly tentativa: number;
  /** `true` quando os oito passos passaram **todos à primeira tentativa**. */
  readonly primeiraTentativa: boolean;
}

export interface Dependencias extends DependenciasDosPassos {
  readonly armazem: ArmazemDePassos;
  readonly registoDoCaso: RegistoDoCaso;
  readonly log?: Logger;
  readonly metricas?: Metricas;
  /** Injectável para os ensaios não esperarem segundos reais. */
  readonly dormir?: (ms: number) => Promise<void>;
}

/** A saga. */
export class Saga {
  readonly #d: Dependencias;
  readonly #passos: ReadonlyMap<Passo, DefinicaoDePasso>;
  readonly #m: Metricas;
  readonly #dormir: (ms: number) => Promise<void>;

  constructor(dependencias: Dependencias) {
    this.#d = dependencias;
    this.#passos = montarPassos(dependencias);
    this.#m = dependencias.metricas ?? METRICAS;
    this.#dormir = dependencias.dormir ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  }

  get metricas(): Metricas {
    return this.#m;
  }

  /**
   * Corre a saga do princípio, saltando o que já está `concluido`.
   *
   * **Saltar o `concluido` é a idempotência do critério 1**: entregar o
   * `tenant.approved` duas vezes corre isto duas vezes, e na segunda passagem
   * os oito passos já estão `concluido` — nenhum *ensure* é chamado e não há
   * segunda conta, segunda chave nem segundo canal. A contagem está presa num
   * ensaio que afirma sobre os contadores dos inventários.
   *
   * Pára no primeiro passo que não concluir, e devolve porquê. **Não compensa
   * por si**: quem decide compensar é quem lê o desfecho (o consumidor do
   * KAM-092), porque uma espera não é uma falha e a saga não sabe se o dono
   * ainda vai agir.
   */
  async correr(caso: Caso): Promise<Desfecho> {
    let primeiraTentativa = true;
    for (const nome of PASSOS) {
      const jaFeito = await this.#d.armazem.passo(caso.onboardingId, nome);
      if (jaFeito?.status === "concluido") {
        if (jaFeito.attempt > 1) primeiraTentativa = false;
        continue;
      }
      if (jaFeito?.status === "escalado") {
        // **Terminal.** Um passo escalado não se volta a tentar sem
        // intervenção: se se tentasse, o «sem retry infinito» do critério 5
        // valia só até à próxima entrega do evento — e o evento entrega-se
        // *at-least-once*.
        return {
          estado: "escalada",
          passo: nome,
          tentativa: jaFeito.attempt,
          primeiraTentativa: false,
        };
      }

      const desfecho = await this.#correrPasso(caso, nome);
      if (desfecho.tentativa > 1) primeiraTentativa = false;
      if (desfecho.estado !== "concluida") {
        return { ...desfecho, primeiraTentativa: false };
      }
    }
    this.#m.contar(METRICA_PRIMEIRA_TENTATIVA, primeiraTentativa ? "sim" : "nao");
    return { estado: "concluida", passo: null, tentativa: 1, primeiraTentativa };
  }

  /**
   * Corre um passo, com as três tentativas e o *backoff* entre elas.
   *
   * A ordem das três coisas dentro do `try` é a janela do critério 4, e é
   * deliberada: o `ensure` fala com o mundo e **depois** o `marcarConcluido`
   * grava. Se o processo cair no meio, o recurso existe lá fora e a linha ficou
   * em `em_curso`/`falhado` — e a repetição encontra-o pela chave natural em
   * vez de criar um segundo. É o que o `tests/provisioning.crash.test.ts` mede,
   * falhando **exactamente** nessa janela e não noutro ponto.
   */
  async #correrPasso(caso: Caso, nome: Passo): Promise<Desfecho> {
    const definicao = this.#passos.get(nome);
    if (definicao === undefined) throw new Error(`passo sem definicao: ${nome}`);

    for (;;) {
      const linha = await this.#d.armazem.abrir(caso, nome);
      await this.#dormir(atrasoDaTentativa(linha.attempt));
      try {
        const externalId = await definicao.ensure(caso);
        await this.#d.armazem.marcarConcluido(caso.onboardingId, nome, externalId);
        return { estado: "concluida", passo: nome, tentativa: linha.attempt, primeiraTentativa: true };
      } catch (erro) {
        if (erro instanceof AguardaEntradaError) {
          // **A espera não gasta tentativa, e é o critério 6.** O `marcarEspera`
          // põe o passo no estado de espera e **repõe o `attempt`**: sem isso,
          // três noites de reconciliação com o dono por agir escalavam o caso
          // para operações por uma coisa que ninguém podia ter feito. Ver a
          // nota do `marcarEspera` no contrato.
          await this.#d.armazem.marcarEspera(caso.onboardingId, nome, erro.espera);
          return {
            estado: "aguarda",
            passo: nome,
            tentativa: linha.attempt,
            primeiraTentativa: linha.attempt === 1,
          };
        }
        const codigo = codigoDoErro(erro);
        this.#m.contar(METRICA_FALHAS, nome);
        if (linha.attempt >= TENTATIVAS) {
          // **O 3.º falhanço escala e não levanta.** Levantar fazia a fila
          // repetir o *job* — e o critério diz «sem retry infinito». O
          // `review_case` do KAM-089 não existe (ver o `contrato.ts`): grava-se
          // o estado terminal e conta-se a métrica, que é o alerta.
          await this.#d.armazem.marcarEscalado(caso.onboardingId, nome, codigo);
          this.#m.contar(METRICA_ESCALADO, nome);
          // **Só os campos da lista branca** (`docs/tecnica/08` §7.3, imposta
          // pelo `SoCampos` do *logger*): o passo vai no `outcome`, que é um
          // domínio fechado de oito valores, e o `attempt` não vai a sítio
          // nenhum — a coluna `provisioning_step.attempt` já o tem, e é lá que
          // ele pertence. O `error_code` leva o código opaco do `codigoDoErro`.
          this.#d.log?.excepcao(erro, codigo, {
            tenant_id: caso.tenantId,
            outcome: `saga_escalada_${nome}`,
          });
          return {
            estado: "escalada",
            passo: nome,
            tentativa: linha.attempt,
            primeiraTentativa: false,
          };
        }
        await this.#d.armazem.marcarFalhado(caso.onboardingId, nome, codigo);
      }
    }
  }

  /**
   * Desfaz os passos `concluido` **em ordem inversa**. O critério 3.
   *
   * ## A lista vem da base, não de memória
   *
   * `passosConcluidos` lê o `provisioning_step`. Um processo que caia a meio da
   * saga deixa a lista escrita, e quem retomar compensa o que ficou sem ter
   * estado presente — é o que faz desta compensação uma operação **retomável**
   * e não uma limpeza de variáveis locais. É a mesma escolha que o
   * `onboarding/onboarding.ts::compensar` fez, e pela mesma razão.
   *
   * ## Só os `concluido`, e o filtro é **aqui**
   *
   * Um passo `falhado` pode ter deixado recurso lá fora (é a janela do critério
   * 4), e compensar por aí era adivinhar. Quem apanha esse caso é a
   * reconciliação nocturna, que olha para o mundo em vez de olhar para a nossa
   * tabela — e é por isso que o critério 3 pede as duas coisas na mesma frase:
   * «a compensação dos passos 3, 2, 1 em ordem inversa (só os `done`) **e** a
   * reconciliação nocturna seguinte reporta 0 órfãos».
   *
   * O filtro corre **nesta função** e não na consulta, e isso é a correcção de
   * um defeito que um ensaio de mutação encontrou: com a porta a devolver só os
   * `concluido`, a propriedade vivia no armazém, e mutar o `saga.ts` deixava o
   * ensaio verde — ele media o filtro do duplo e não o nosso código. A porta
   * devolve tudo; quem decide é este `filter`.
   *
   * ## Cada acção é tolerante à ausência, e uma falha pára as seguintes
   *
   * Pára, e isto é deliberado: a compensação é retomável porque a lista não se
   * esvazia, e insistir depois de um erro podia desfazer um recurso de que o
   * seguinte ainda precisa. Quem voltar lê o que ficou.
   */
  async compensar(caso: Caso, motivo: string): Promise<readonly AccaoDeCompensacao[]> {
    const todas = await this.#d.armazem.passosDoCaso(caso.onboardingId);
    const concluidos = todas.filter((l) => l.status === "concluido");
    const executadas: AccaoDeCompensacao[] = [];
    for (const linha of ordemInversa(concluidos)) {
      const definicao = this.#passos.get(linha.step);
      if (definicao === undefined) continue;
      const accoes = await definicao.compensar(caso, linha.external_id);
      try {
        for (const accao of accoes) {
          await this.#executar(accao, linha.step);
          executadas.push(accao);
          this.#m.contar(METRICA_COMPENSADO, accao.recurso);
        }
        await this.#d.armazem.marcarCompensado(caso.onboardingId, linha.step);
      } catch (erro) {
        // O `error_code` leva a classe do erro e o passo, e mais nada: uma
        // `SecretRef` ou um `external_id` numa linha de log era um identificador
        // fora da lista branca do `docs/tecnica/08` §7.3.
        // A forma é a do `onboarding/onboarding.ts::compensar`: o que varia vai
        // no `error_code` e o `outcome` é fixo. O `motivo` **não** entra — não
        // está na lista branca, e vem de quem chama, pelo que podia trazer
        // texto livre para uma linha de *log*.
        this.#d.log?.excepcao(erro, `compensacao_falhou_${linha.step}`, {
          tenant_id: caso.tenantId,
          outcome: "compensacao_falhou",
        });
        return executadas;
      }
    }
    return executadas;
  }

  /**
   * Executa uma acção de compensação, **depois de a verificar**.
   *
   * O `verificar` corre para **todas** as acções e não só para as do canal do
   * cliente, e é esse o ponto: o critério 7 é uma propriedade do conjunto, não
   * de um passo. Um `{tipo: "apagar", recurso: "phone_number"}` escrito na
   * compensação de qualquer passo levanta aqui.
   */
  async #executar(accao: AccaoDeCompensacao, passo: Passo): Promise<void> {
    verificar(accao, passo);
    switch (accao.recurso) {
      case "tenant":
        // **`marcar_cancelado`, nunca `apagar`**: «sem apagar histórico»
        // (`docs/tecnica/10` §5.2, passo 1).
        await this.#d.registoDoCaso.marcarCancelado(accao.ref);
        return;
      case "chave_llm":
        await this.#d.chaveDeLlm.revogar(accao.ref);
        return;
      case "canal_comercio":
        if (accao.tipo === "arquivar") {
          await this.#d.comercio.arquivar(accao.ref);
          return;
        }
        // «só apagado se vazio» (critério 7). A porta pergunta antes, e um
        // canal com encomendas fica arquivado — o que é o desfecho correcto.
        await this.#d.comercio.apagarSeVazio(accao.ref);
        return;
      case "conta_atendimento":
        // A conta é **nossa** (criada pela nossa chave da Platform API), e por
        // isso `apagar` é legítimo — ao contrário do WABA. Ver a nota do
        // `apagarContaDeAtendimento` no `passos.ts`: a operação não está no
        // `HandoffProvider` e entra por porta própria.
        await this.#d.apagarContaDeAtendimento(accao.ref);
        return;
      case "entitlement":
        await this.#d.entitlements.desactivar(accao.ref);
        return;
      case "inbox":
        await this.#d.inbox.desligar(accao.ref);
        return;
      case "rota_chr":
        await this.#d.canalDoCliente.removerRota(accao.ref);
        return;
      case "waba":
      case "phone_number":
        // O único caminho até ao canal do cliente, e ele verifica outra vez.
        await executarNoCanalDoCliente(this.#d.canalDoCliente, accao, passo);
        return;
      default:
        throw new Error(`recurso sem compensacao: ${accao.recurso}`);
    }
  }
}

/**
 * A lista ordenada pela **ordem inversa de `PASSOS`**.
 *
 * Ordena pelo índice em `PASSOS` e inverte — **não** confia na ordem em que a
 * base devolveu as linhas. Um `SELECT` sem `ORDER BY` não garante ordem
 * nenhuma, e a consulta deste módulo ordena; mas a compensação é o critério 3 e
 * depender da cláusula de uma consulta que vive noutro ficheiro era pôr a
 * propriedade fora do alcance deste ensaio. Pura e exportada para poder ser
 * medida sozinha, com as linhas embaralhadas à entrada.
 */
export function ordemInversa(linhas: readonly LinhaDePasso[]): readonly LinhaDePasso[] {
  const indice = (p: Passo): number => PASSOS.indexOf(p);
  return [...linhas].sort((a, b) => indice(b.step) - indice(a.step));
}

/**
 * O código de erro que vai para o `provisioning_step.error_code`.
 *
 * **A classe do erro, nunca a mensagem.** A mensagem de um erro de terceiros
 * pode trazer um corpo de resposta, e um corpo de resposta do LiteLLM ou da
 * Platform API do Chatwoot pode trazer a chave — e a DoD deste ticket diz
 * «nada de chaves em logs, *traces* ou `provisioning_step`, *scan* limpo». O
 * `String(e)` do esboço do `docs/tecnica/10` §5.2 fazia exactamente isso, e é
 * a razão de esta função existir em vez de se escrever o erro directamente.
 */
export function codigoDoErro(erro: unknown): string {
  if (erro instanceof Error && erro.name !== "" && erro.name !== "Error") return erro.name;
  if (erro instanceof Error) {
    // Um `Error` genérico não tem classe que diga nada. Aceita-se a mensagem
    // **só** se ela for um identificador curto em `snake_case` — que é a forma
    // que os nossos próprios `throw` usam (`teste_ponta_a_ponta_falhou`). Tudo
    // o mais é opaco de propósito.
    return /^[a-z][a-z0-9_]{2,63}$/.test(erro.message) ? erro.message : "erro_opaco";
  }
  return "erro_nao_error";
}

export { SagaEscaladaError, ESPERA_DO_PASSO };
