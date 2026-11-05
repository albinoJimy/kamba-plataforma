/**
 * Os duplos da saga de provisioning (KAM-091).
 *
 * ## A regra que governa este ficheiro: um duplo **não decide**
 *
 * Cada inventário aqui é um `Map` com duas operações — `procurar` e `criar` — e
 * um **contador de criações**. Nenhum deles sabe o que é idempotência: se o
 * código de produção chamar `criar` duas vezes com a mesma chave, o inventário
 * cria duas vezes e o contador vai a 2.
 *
 * É esta a diferença entre medir o predicado e medir o duplo. Um duplo com
 * `ensureX(tenantId)` que devolvesse sempre o mesmo objecto fazia os critérios
 * 1 e 4 passar **com a procura-antes-de-criar apagada do código de produção** —
 * o duplo tapava o defeito. Com o inventário burro, apagá-la põe o contador a 2
 * e há asserções sobre esse número.
 *
 * O `ArmazemFalso` segue a mesma regra: modela o `UNIQUE(onboarding_id, step)`
 * e o incremento de `attempt` e mais nada. Não «sabe» que três tentativas
 * escalam — isso é do `saga.ts`, e é lá que se mede.
 *
 * **Nada aqui prova o Chatwoot, o LiteLLM ou o Medusa.** Prova a máquina de
 * estados. Os três não estão a correr neste repositório (ver a nota do
 * `src/provisioning/contrato.ts`), e um duplo apresentado como prova deles era
 * pior do que uma caixa vazia.
 */

import {
  ETIQUETA_DA_SAGA,
  type ArmazemDePassos,
  type CanalDoCliente,
  type Caso,
  type ChaveDeLlm,
  type ClienteSql,
  type Entitlements,
  type EstadoDePasso,
  type Espera,
  type InboxDeAtendimento,
  type LinhaDePasso,
  type Passo,
  type RefExterna,
  type RegistoDeCanalDeComercio,
  type RegistoDoCaso,
  type RotaDoCanal,
  type TesteDeCanal,
  Metricas,
} from "../../src/provisioning/index.ts";
import type { ContaDeAtendimento, HandoffProvider } from "../../src/hnd/contrato.ts";
import { Logger } from "../../src/logger/index.ts";

export const TENANT = "11111111-1111-4111-8111-111111111111";
export const ONBOARDING = "99999999-9999-4999-8999-999999999999";
export const WABA = "waba-de-ensaio";
export const NUMERO = "phone-number-de-ensaio";

export const CASO: Caso = {
  onboardingId: ONBOARDING,
  tenantId: TENANT,
  plano: "piloto",
  vertical: "vendedor",
  // Um nome de negócio inventado. **Nunca um nome de pessoa nem de uma loja
  // real:** o repositório é público.
  nomeDoNegocio: "Loja de Ensaio",
};

/** Uma linha mutável do armazém. */
interface Linha {
  onboarding_id: string;
  tenant_id: string;
  step: Passo;
  status: EstadoDePasso;
  attempt: number;
  external_id: string | null;
  error_code: string | null;
  espera: Espera | null;
}

/**
 * O `provisioning_step` em memória.
 *
 * Modela três coisas da tabela e nada mais: a chave `UNIQUE(onboarding_id,
 * step)`, o incremento de `attempt` no `abrir`, e o facto de o
 * `marcarConcluido` ser **uma segunda escrita** depois do *ensure* — que é a
 * janela do critério 4.
 */
export class ArmazemFalso implements ArmazemDePassos {
  readonly #linhas = new Map<string, Linha>();
  /** A ordem em que as escritas aconteceram. Para medir a ordem da compensação. */
  readonly escritas: string[] = [];
  /**
   * Faz o `marcarConcluido` deste passo levantar **uma vez**.
   *
   * É o *crash* do critério 4, e cai **exactamente** na janela entre o *ensure*
   * ter devolvido e a linha ter ficado `concluido`. Falhar noutro ponto media
   * outra coisa.
   */
  falharNoConcluir: Passo | null = null;

  #chave(onboardingId: string, passo: Passo): string {
    return `${onboardingId}:${passo}`;
  }

  async abrir(caso: Caso, passo: Passo): Promise<LinhaDePasso> {
    const chave = this.#chave(caso.onboardingId, passo);
    const anterior = this.#linhas.get(chave);
    const linha: Linha = anterior ?? {
      onboarding_id: caso.onboardingId,
      tenant_id: caso.tenantId,
      step: passo,
      status: "em_curso",
      attempt: 0,
      external_id: null,
      error_code: null,
      espera: null,
    };
    linha.status = "em_curso";
    linha.attempt += 1;
    this.#linhas.set(chave, linha);
    this.escritas.push(`abrir:${passo}:${linha.attempt}`);
    return { ...linha };
  }

  async marcarConcluido(
    onboardingId: string,
    passo: Passo,
    externalId: string | null,
  ): Promise<void> {
    if (this.falharNoConcluir === passo) {
      // Levanta **uma vez**: a repetição tem de poder passar, senão o ensaio
      // media «falha para sempre» em vez de «retoma sem duplicar».
      this.falharNoConcluir = null;
      this.escritas.push(`crash:${passo}`);
      throw new Error("crash_entre_criar_e_gravar");
    }
    const linha = this.#exigir(onboardingId, passo);
    linha.status = "concluido";
    linha.external_id = externalId;
    linha.error_code = null;
    linha.espera = null;
    this.escritas.push(`concluido:${passo}`);
  }

  async marcarFalhado(onboardingId: string, passo: Passo, codigo: string): Promise<void> {
    const linha = this.#exigir(onboardingId, passo);
    linha.status = "falhado";
    linha.error_code = codigo;
    this.escritas.push(`falhado:${passo}:${codigo}`);
  }

  async marcarEscalado(onboardingId: string, passo: Passo, codigo: string): Promise<void> {
    const linha = this.#exigir(onboardingId, passo);
    linha.status = "escalado";
    linha.error_code = codigo;
    this.escritas.push(`escalado:${passo}`);
  }

  async marcarCompensado(onboardingId: string, passo: Passo): Promise<void> {
    const linha = this.#exigir(onboardingId, passo);
    linha.status = "compensado";
    this.escritas.push(`compensado:${passo}`);
  }

  /**
   * Põe o passo em espera e **repõe o `attempt` a zero**.
   *
   * O critério 6 diz que as esperas não são falhas; se o `attempt` ficasse, três
   * passagens com o dono por agir escalavam o caso.
   */
  async marcarEspera(onboardingId: string, passo: Passo, espera: Espera): Promise<void> {
    const linha = this.#exigir(onboardingId, passo);
    linha.status = "em_curso";
    linha.espera = espera;
    linha.attempt = 0;
    this.escritas.push(`espera:${passo}:${espera}`);
  }

  /**
   * **Todas** as linhas, em qualquer estado e por uma ordem que não é nem a de
   * `PASSOS` nem a sua inversa.
   *
   * As três escolhas são deliberadas, e a terceira é a correcção de um defeito
   * que a revisão adversarial apanhou:
   *
   * - **não filtra** porque o «só os `done`» do critério 3 é do `saga.ts`;
   * - **não ordena pela ordem de execução**, porque um `SELECT` sem `ORDER BY`
   *   não garante ordem nenhuma;
   * - e **não devolve a ordem inversa já feita**. Devolvia: era
   *   `linhas.reverse()` sobre a ordem de inserção, que é a de `PASSOS` — isto
   *   é, o duplo entregava exactamente a ordem que a compensação devia
   *   calcular. Com isso, apagar a chamada a `ordemInversa` do `compensar`
   *   deixava as *suites* **verdes** (medido: `for (const linha of concluidos)`
   *   → 81/81), e a asserção do critério 3 media o `.reverse()` do duplo. O
   *   comentário que aqui estava avisava deste defeito exacto e o código tinha-o.
   *
   * Agora devolve-as na **ordem de inserção**, que é a ordem de **execução** —
   * e essa é a mais hostil que existe para uma asserção sobre a ordem
   * *inversa*: se o `compensar` não chamar o `ordemInversa`, a compensação sai
   * exactamente ao contrário do que o critério 3 exige, e o ensaio fica
   * vermelho.
   *
   * Ordenar por nome também não servia, e foi a segunda tentativa: para os três
   * passos que o ensaio do critério 3 compensa (`tenant_e_caso`, `chave_llm`,
   * `canal_comercio`), o alfabeto **coincide** com a ordem inversa — a mutação
   * voltou a sobreviver. Duas vezes o mesmo defeito, por duas coincidências
   * diferentes; a ordem de execução não pode coincidir com a sua inversa.
   *
   * A ordenação a partir de uma ordem arbitrária fica medida à parte, pelo
   * ensaio puro do `ordemInversa`, que lhe dá as linhas embaralhadas.
   */
  async passosDoCaso(onboardingId: string): Promise<readonly LinhaDePasso[]> {
    return [...this.#linhas.values()]
      .filter((l) => l.onboarding_id === onboardingId)
      .map((l) => ({ ...l }));
  }

  async passo(onboardingId: string, passo: Passo): Promise<LinhaDePasso | null> {
    const linha = this.#linhas.get(this.#chave(onboardingId, passo));
    return linha === undefined ? null : { ...linha };
  }

  /** Para as asserções: o estado de um passo, ou `null`. */
  estadoDe(passo: Passo): EstadoDePasso | null {
    return this.#linhas.get(this.#chave(ONBOARDING, passo))?.status ?? null;
  }

  esperaDe(passo: Passo): Espera | null {
    return this.#linhas.get(this.#chave(ONBOARDING, passo))?.espera ?? null;
  }

  tentativaDe(passo: Passo): number {
    return this.#linhas.get(this.#chave(ONBOARDING, passo))?.attempt ?? 0;
  }

  erroDe(passo: Passo): string | null {
    return this.#linhas.get(this.#chave(ONBOARDING, passo))?.error_code ?? null;
  }

  #exigir(onboardingId: string, passo: Passo): Linha {
    const linha = this.#linhas.get(this.#chave(onboardingId, passo));
    if (linha === undefined) {
      throw new Error(`o passo ${passo} nao foi aberto: o UNIQUE nao tem linha`);
    }
    return linha;
  }
}

/**
 * Um inventário burro. **A base dos duplos externos.**
 *
 * `procurar` lê o `Map`; `criar` escreve e soma 1 ao contador. Não deduplica:
 * duas chamadas a `criar` com a mesma chave dão `criadas === 2`, e é esse número
 * que os critérios 1 e 4 afirmam ser 1.
 */
export class InventarioFalso<TChave> {
  readonly #itens = new Map<string, RefExterna>();
  criadas = 0;
  procuras = 0;
  readonly #chaveDe: (c: TChave) => string;
  readonly #idDe: (c: TChave) => string;

  constructor(chaveDe: (c: TChave) => string, idDe: (c: TChave) => string) {
    this.#chaveDe = chaveDe;
    this.#idDe = idDe;
  }

  async procurar(chave: TChave): Promise<RefExterna | null> {
    this.procuras += 1;
    return this.#itens.get(this.#chaveDe(chave)) ?? null;
  }

  async criar(chave: TChave): Promise<RefExterna> {
    this.criadas += 1;
    // O `id` leva o número da criação: duas criações dão dois identificadores
    // diferentes, e um ensaio que compare o `external_id` das duas passagens
    // apanha a duplicação mesmo sem olhar para o contador.
    const ref: RefExterna = { id: `${this.#idDe(chave)}-${this.criadas}`, nosso: true };
    this.#itens.set(this.#chaveDe(chave), ref);
    return ref;
  }

  /** Semeia um recurso como se já existisse lá fora, sem contar criação. */
  semear(chave: TChave, id: string, nosso = true): void {
    this.#itens.set(this.#chaveDe(chave), { id, nosso });
  }

  apagar(chave: TChave): void {
    this.#itens.delete(this.#chaveDe(chave));
  }

  get quantos(): number {
    return this.#itens.size;
  }
}

/** A chave virtual do LiteLLM. */
export class ChaveDeLlmFalsa implements ChaveDeLlm {
  readonly inventario = new InventarioFalso<{ alias: string; orcamento: number }>(
    (c) => c.alias,
    (c) => c.alias,
  );
  readonly revogadas: string[] = [];

  procurar = (c: { alias: string; orcamento: number }) => this.inventario.procurar(c);
  criar = (c: { alias: string; orcamento: number }) => this.inventario.criar(c);

  async revogar(id: string): Promise<void> {
    this.revogadas.push(id);
  }
}

/** O canal de comércio. **Sem implementação real:** credor D3 / KAM-042. */
export class ComercioFalso implements RegistoDeCanalDeComercio {
  readonly inventario = new InventarioFalso<{ tenantId: string }>(
    (c) => c.tenantId,
    () => "canal",
  );
  readonly arquivados: string[] = [];
  readonly apagados: string[] = [];
  /** Um canal com encomendas não se apaga (critério 7). */
  estaVazio = true;

  procurar = (c: { tenantId: string }) => this.inventario.procurar(c);
  criar = (c: { tenantId: string }) => this.inventario.criar(c);

  async arquivar(id: string): Promise<void> {
    this.arquivados.push(id);
  }

  async apagarSeVazio(id: string): Promise<boolean> {
    if (!this.estaVazio) return false;
    this.apagados.push(id);
    return true;
  }
}

/** A *inbox* de tipo API e a rota do CHR. */
export class InboxFalsa implements InboxDeAtendimento {
  readonly inventario = new InventarioFalso<{ tenantId: string; phoneNumberId: string }>(
    (c) => `${c.tenantId}:${c.phoneNumberId}`,
    () => "inbox",
  );
  readonly desligadas: string[] = [];

  procurar = (c: { tenantId: string; phoneNumberId: string }) => this.inventario.procurar(c);
  criar = (c: { tenantId: string; phoneNumberId: string }) => this.inventario.criar(c);

  async desligar(id: string): Promise<void> {
    this.desligadas.push(id);
  }
}

/**
 * O canal do cliente: o WABA, o número, a subscrição e a rota.
 *
 * **Tem as duas operações destrutivas de propósito** (`apagarWaba`,
 * `apagarNumero`), e cada uma soma a um contador. Sem elas, o critério 7
 * provava-se por impossibilidade de escrever o erro — e o ticket pede um ensaio
 * que *fique vermelho* se alguém puser lá um `DELETE`.
 */
export class CanalDoClienteFalso implements CanalDoCliente {
  /** `null` até o dono agir: é o estado de espera do critério 6. */
  numero: string | null = NUMERO;
  waba: string | null = WABA;
  readonly subscritos: string[] = [];
  readonly subscricoesCanceladas: string[] = [];
  readonly rotasRemovidas: string[] = [];
  /** **Têm de ficar a zero.** São as asserções do critério 7. */
  wabasApagados = 0;
  numerosApagados = 0;

  async numeroDoTenant(): Promise<string | null> {
    return this.numero;
  }

  async subscreverWebhooks(wabaId: string): Promise<void> {
    this.subscritos.push(wabaId);
  }

  async cancelarSubscricao(wabaId: string): Promise<void> {
    this.subscricoesCanceladas.push(wabaId);
  }

  async removerRota(phoneNumberId: string): Promise<void> {
    this.rotasRemovidas.push(phoneNumberId);
  }

  async apagarWaba(): Promise<void> {
    this.wabasApagados += 1;
  }

  async apagarNumero(): Promise<void> {
    this.numerosApagados += 1;
  }
}

/**
 * A rota do CHR: a linha de `platform.tenant_channels`.
 *
 * **Guarda o pedido inteiro**, para que um ensaio possa afirmar que o
 * `wabaId` nunca chega vazio — era o defeito que a revisão adversarial apanhou
 * no `INSERT` directo que aqui estava antes (`waba_id` é `NOT NULL`).
 */
export class RotaFalsa implements RotaDoCanal {
  readonly garantidas: {
    tenantId: string;
    phoneNumberId: string;
    wabaId: string;
    vertical: string;
  }[] = [];
  readonly removidas: string[] = [];

  async garantir(pedido: {
    tenantId: string;
    phoneNumberId: string;
    wabaId: string;
    vertical: string;
  }): Promise<void> {
    this.garantidas.push({ ...pedido });
  }

  async remover(phoneNumberId: string): Promise<void> {
    this.removidas.push(phoneNumberId);
  }
}

/** Os entitlements. Idempotente por `(tenant_id, modulo)` — como a porta promete. */
export class EntitlementsFalsos implements Entitlements {
  readonly garantidos = new Map<string, number>();
  readonly desactivados: string[] = [];

  async garantir(tenantId: string): Promise<readonly string[]> {
    this.garantidos.set(tenantId, (this.garantidos.get(tenantId) ?? 0) + 1);
    return ["catalogo", "encomendas"];
  }

  async desactivar(tenantId: string): Promise<void> {
    this.desactivados.push(tenantId);
  }
}

/**
 * O `HandoffProvider`, **como caixa preta** (KAM-019).
 *
 * O `ensureAccount` real procura antes de criar (`src/hnd/provedor.ts:210`) e
 * tem *suite* própria; aqui conta-se quantas vezes foi **chamado** e devolve-se
 * sempre a mesma conta, porque é essa a garantia que a porta dá. O que este
 * duplo mede é o número de chamadas por passagem, não a idempotência dele.
 */
export class HandoffFalso implements HandoffProvider {
  chamadas = 0;
  readonly contasApagadas: string[] = [];

  async ensureAccount(): Promise<ContaDeAtendimento> {
    this.chamadas += 1;
    return {
      accountId: "conta-7",
      inboxId: "inbox-7",
      botId: "bot-7",
      providerUserId: "user-7",
    } as unknown as ContaDeAtendimento;
  }

  async mirrorMessage(): Promise<void> {}
  async openHandoff(): Promise<never> {
    throw new Error("nao usado pela saga");
  }
  async setBotMuted(): Promise<void> {}
  onHumanEvent(): void {}
  async close(): Promise<void> {}
}

/** O teste ponta a ponta do passo 8. `null` é espera, `false` é falha. */
export class TesteDeCanalFalso implements TesteDeCanal {
  valor: boolean | null = true;
  async resultado(): Promise<boolean | null> {
    return this.valor;
  }
}

/** O registo do caso. Sem implementação real: credor KAM-086. */
export class RegistoDoCasoFalso implements RegistoDoCaso {
  readonly cancelados: string[] = [];
  async marcarCancelado(onboardingId: string): Promise<void> {
    this.cancelados.push(onboardingId);
  }
}

/**
 * Uma base que registra as consultas e **modela a RLS pela única coisa que
 * importa aqui**: sem `app.tenant_id` definido, uma escrita devolve zero linhas.
 *
 * Devolvia sempre `{rows: []}` e registrava o texto — o que era pior do que
 * inútil: as consultas nunca eram executadas e o `ensure` não olhava para o
 * resultado, pelo que a saga marcava o passo `concluido` sobre uma base que não
 * foi escrita. A revisão adversarial chamou-lhe «o modo de falha mais perigoso
 * do ticket», e tinha razão: é silencioso e **declara sucesso**.
 *
 * Isto não substitui a *suite* de base de dados — contra um Postgres real há
 * RLS a sério, políticas e papéis, e nada aqui o imita. O que isto torna
 * medível é a propriedade do **nosso** código: que a escrita corre sob
 * contexto, e que zero linhas é um erro em vez de um `concluido`.
 */
export class SqlFalso implements ClienteSql {
  readonly consultas: { texto: string; valores: readonly unknown[] }[] = [];
  /** `false` simula a ligação sem contexto: as escritas filtram para zero linhas. */
  honraOContexto = true;
  #contexto: string | null = null;

  async query<T>(texto: string, valores: readonly unknown[] = []): Promise<{ rows: readonly T[] }> {
    this.consultas.push({ texto, valores });
    const t = texto.trim();
    if (t === "BEGIN") {
      this.#contexto = null;
      return { rows: [] };
    }
    if (t === "COMMIT" || t === "ROLLBACK") {
      this.#contexto = null;
      return { rows: [] };
    }
    if (t.includes("set_config('app.tenant_id'")) {
      this.#contexto = this.honraOContexto ? String(valores[0] ?? "") : null;
      return { rows: [] };
    }
    // Uma escrita só «vê» a linha com o contexto do mesmo tenant — que é o que
    // a política `tenant_iso` faz (`id = app.tenant_id`).
    const doTenant = String(valores[0] ?? "");
    if (this.#contexto === null || this.#contexto !== doTenant) return { rows: [] };
    return { rows: [{ id: doTenant } as unknown as T] };
  }

  /** As consultas que não são de transacção nem de contexto. Para as asserções. */
  get escritas(): { texto: string; valores: readonly unknown[] }[] {
    return this.consultas.filter(
      (c) =>
        !["BEGIN", "COMMIT", "ROLLBACK"].includes(c.texto.trim()) &&
        !c.texto.includes("set_config('app.tenant_id'"),
    );
  }
}

/**
 * Um `Logger` **em modo estrito**, com destino em memória.
 *
 * Modo estrito porque é o do CI: nele, `log.excepcao` com um campo fora da
 * lista branca ou com um valor fora de forma **levanta** `CampoRejeitadoError`.
 * As chamadas da saga estão dentro de `catch`, depois do `marcarEscalado` — uma
 * rejeição fazia a excepção escapar e a escalada deixava de devolver
 * `{estado: "escalada"}`. Sem um `Logger` injectado, nada disto era exercido:
 * o `log?.excepcao` era um *no-op* nas quatro *suites*, e a metade «logs» da
 * DoD não tinha medição executada. Encontrado pela revisão adversarial.
 */
export function loggerDeEnsaio(linhas: Record<string, unknown>[]): Logger {
  return new Logger("provisioning", {
    estrito: true,
    destino: {
      write(texto: string) {
        linhas.push(JSON.parse(texto) as Record<string, unknown>);
        return true;
      },
    },
  });
}

/** Tudo montado, com os duplos acessíveis para as asserções. */
export interface Montagem {
  readonly armazem: ArmazemFalso;
  readonly sql: SqlFalso;
  readonly chaveDeLlm: ChaveDeLlmFalsa;
  readonly comercio: ComercioFalso;
  readonly handoff: HandoffFalso;
  readonly entitlements: EntitlementsFalsos;
  readonly canalDoCliente: CanalDoClienteFalso;
  readonly inbox: InboxFalsa;
  readonly rota: RotaFalsa;
  readonly teste: TesteDeCanalFalso;
  readonly registoDoCaso: RegistoDoCasoFalso;
  readonly contasApagadas: string[];
  readonly dormidas: number[];
  /** As linhas que o `Logger` em modo estrito aceitou. */
  readonly linhasDeLog: Record<string, unknown>[];
  /** Um registo por montagem: o `METRICAS` do processo é partilhado. */
  readonly metricas: Metricas;
}

/**
 * Monta os duplos e as dependências da saga.
 *
 * O `dormir` **não dorme**: registra o atraso pedido. O *backoff* do critério 5
 * mede-se pelos números que a saga pediu, não por tempo de parede — um ensaio
 * que esperasse 3 s por passo levava minutos e media o `setTimeout` do Node.
 */
export function montar(): Montagem & { dependencias: Record<string, unknown> } {
  const armazem = new ArmazemFalso();
  const sql = new SqlFalso();
  const chaveDeLlm = new ChaveDeLlmFalsa();
  const comercio = new ComercioFalso();
  const handoff = new HandoffFalso();
  const entitlements = new EntitlementsFalsos();
  const canalDoCliente = new CanalDoClienteFalso();
  const inbox = new InboxFalsa();
  const rota = new RotaFalsa();
  const teste = new TesteDeCanalFalso();
  const registoDoCaso = new RegistoDoCasoFalso();
  const contasApagadas: string[] = [];
  const dormidas: number[] = [];
  // **Um relógio falso**, para a `saga_step_duration_ms` ser medível: com o
  // `Date.now` real um passo rápido dava 0 e a asserção não distinguia
  // «mediu zero» de «não mediu».
  let relogio = 1_000;
  const linhasDeLog: Record<string, unknown>[] = [];
  // **Um registo de métricas por montagem, e não o do processo.** O `METRICAS`
  // exportado é um singleton: com ele, cada ensaio somava aos contadores dos
  // anteriores e `saga_first_attempt_total{passou="sim"}` valia 13 em vez de 1.
  // Um ensaio que afirme sobre um contador tem de ter o contador só para si.
  const metricas = new Metricas();

  const dependencias = {
    armazem,
    sql,
    metricas,
    registoDoCaso,
    chaveDeLlm,
    comercio,
    handoff,
    entitlements,
    canalDoCliente,
    inbox,
    rota,
    teste,
    apagarContaDeAtendimento: async (id: string) => {
      contasApagadas.push(id);
    },
    orcamentoDoPlano: () => 30,
    wabaDoTenant: async () => canalDoCliente.waba,
    dormir: async (ms: number) => {
      dormidas.push(ms);
    },
    agora: () => {
      relogio += 7;
      return relogio;
    },
    // **Um `Logger` a sério, em modo estrito.** Nenhum dos ensaios injectava
    // um, pelo que o `log?.excepcao` era um *no-op* e a metade «logs» da DoD
    // não tinha medição executada — e, em modo estrito, um campo recusado
    // **levanta**, o que fazia a escalada deixar de devolver `escalada`.
    log: loggerDeEnsaio(linhasDeLog),
  };

  return {
    armazem,
    sql,
    chaveDeLlm,
    comercio,
    handoff,
    entitlements,
    canalDoCliente,
    inbox,
    rota,
    teste,
    registoDoCaso,
    contasApagadas,
    dormidas,
    metricas,
    linhasDeLog,
    dependencias,
  };
}

export { ETIQUETA_DA_SAGA };
