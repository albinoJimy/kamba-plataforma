/**
 * Transacções com contexto de tenant (KAM-004, ADR-015).
 *
 * A base tem RLS `FORCE` em todas as tabelas com `tenant_id`: sem contexto,
 * devolve zero linhas. Este módulo é a forma de **dar** esse contexto, e é o
 * espelho de `kamba_core.tenant_guard` em Python — as duas implementações têm de
 * recusar as mesmas coisas pela mesma ordem.
 *
 *     await comTenant(cliente, tenant, async (c) => {
 *       await c.query("SELECT ... FROM platform.tenant_channels");
 *     });
 *
 * `comTenant` abre a transacção, executa
 * `SELECT set_config('app.tenant_id', $1, true)` — o equivalente parametrizável
 * de `SET LOCAL` — corre a função, confirma, e desfaz em caso de erro. O
 * terceiro argumento `true` é o que importa: o valor morre com a transacção,
 * pelo que uma ligação devolvida a um *pool* não leva o contexto de um tenant
 * para o pedido seguinte. **Nunca** `SET` de sessão (`docs/tecnica/08` §3.3).
 *
 * O módulo não depende de nenhum *driver*: recebe um cliente com um método
 * `query(sql, parametros)`, que é a forma do `pg` e a de quase todos. E **não
 * regista nada** — nem o tenant, nem a consulta, nem o erro: o DoD proíbe
 * associar `tenant_id` a conteúdo em *logs*.
 *
 * **O cliente tem de ser UMA ligação, nunca um *pool*.** Um *pool* também tem
 * `query`, e cada chamada pode ir a uma ligação diferente: o `BEGIN` numa, o
 * `set_config` noutra, e a consulta numa terceira — **sem contexto**. Não falha:
 * devolve zero linhas, ou pior, corre numa ligação onde outra transacção deixou
 * contexto. É o erro mais fácil de cometer com este módulo, e por isso é
 * recusado à entrada quando se reconhece um *pool* (`PoolRecusadoError`). A
 * detecção é por forma (`totalCount`, `idleCount`, `waitingCount` — o `pg.Pool`)
 * e não cobre todos os *drivers*: a regra é de quem chama, e a detecção é a rede.
 *
 * **E uma transacção de cada vez por ligação.** Dois `comTenant` concorrentes
 * sobre o mesmo cliente — o erro mais comum com `pg`: um `Client` partilhado
 * entre pedidos — ou um dentro do outro **não** abrem duas transacções: o
 * segundo `BEGIN` é um aviso, o segundo `set_config` sobrepõe o primeiro, e o
 * pedido de um tenant lê as linhas de outro. A revisão adversarial do KAM-004
 * reproduziu-o contra um PostgreSQL real. A segunda entrada no mesmo cliente
 * lança `LigacaoEmUsoError` antes de qualquer consulta. Reconhece-se o **mesmo
 * objecto**; um invólucro diferente à volta da mesma ligação não é reconhecido.
 */

/** O mínimo de um cliente SQL de que este módulo precisa. */
export interface ClienteSql {
  query(sql: string, parametros?: readonly unknown[]): Promise<unknown>;
}

export const VARIAVEL = "app.tenant_id";

/** `set_config(nome, valor, is_local)`. Com `is_local = true` é um `SET LOCAL`. */
export const SQL_DEFINIR_CONTEXTO = "SELECT set_config('app.tenant_id', $1, true)";

/** Transacções de tenant pedidas sem contexto (recusadas). */
export const METRICA_SEM_CONTEXTO = "rls_context_missing_total";
/** Prefixo do contador de usos de `kamba_batch`; o sufixo é o nome do job. */
export const METRICA_BATCH = "kamba_batch_tx_total";

/** Pediu-se uma transacção de tenant sem dizer qual. */
export class ContextoEmFaltaError extends Error {
  constructor() {
    super(
      "transaccao de tenant sem tenant: a base devolveria zero linhas. " +
        "Para trabalho sem contexto de tenant, `comBatch` com o nome do job.",
    );
    this.name = "ContextoEmFaltaError";
  }
}

/** O tenant dado não é um UUID. A mensagem não repete o valor. */
export class TenantInvalidoError extends Error {
  constructor(tipo: string, comprimento: number) {
    super(
      "o tenant tem de ser um UUID na forma canonica " +
        `(recebido: ${tipo} com ${comprimento} caracteres)`,
    );
    this.name = "TenantInvalidoError";
  }
}

/** Recebeu-se um *pool* onde tinha de vir uma ligação. */
export class PoolRecusadoError extends Error {
  constructor() {
    super(
      "o cliente parece um pool, e nao uma ligacao: cada `query` podia ir a uma " +
        "ligacao diferente, e a consulta correria sem o contexto de tenant. " +
        "Obtenha uma ligacao (`pool.connect()`) e passe essa.",
    );
    this.name = "PoolRecusadoError";
  }
}

/** O cliente já está numa transacção deste módulo (reentrância ou partilha). */
export class LigacaoEmUsoError extends Error {
  constructor() {
    super(
      "este cliente ja esta dentro de uma transaccao de `tenant_guard`: uma " +
        "segunda sobrepunha o contexto de tenant da primeira. Uma ligacao por " +
        "pedido, e uma transaccao de cada vez por ligacao.",
    );
    this.name = "LigacaoEmUsoError";
  }
}

/** `comBatch` exige o nome do job: é o que torna o uso auditável. */
export class JobSemNomeError extends Error {
  constructor() {
    super(
      "o job tem de ter um nome em minusculas e snake_case (3 a 63 " +
        "caracteres): e ele que fica no registo de usos de `kamba_batch`",
    );
    this.name = "JobSemNomeError";
  }
}

/** Contadores em memória. Só números. */
export class Contadores {
  readonly #valores = new Map<string, number>();

  incrementar(nome: string): void {
    this.#valores.set(nome, (this.#valores.get(nome) ?? 0) + 1);
  }

  ler(): Record<string, number> {
    return Object.fromEntries(this.#valores);
  }

  repor(): void {
    this.#valores.clear();
  }
}

export const CONTADORES = new Contadores();

const UUID_CANONICO = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const NOME_DE_JOB = /^[a-z][a-z0-9_]{2,62}$/;

/**
 * O tenant como texto canónico de UUID, ou lança.
 *
 * Aceita só a forma textual canónica (em qualquer caixa). Nada mais: nem
 * números, nem a forma sem hífenes — duas escritas do mesmo tenant são duas
 * chaves de *cache* e dois valores diferentes mais adiante.
 */
export function normalizarTenant(tenant: unknown): string {
  if (tenant === null || tenant === undefined || tenant === "") {
    CONTADORES.incrementar(METRICA_SEM_CONTEXTO);
    throw new ContextoEmFaltaError();
  }
  if (typeof tenant === "string") {
    const minusculas = tenant.toLowerCase();
    if (UUID_CANONICO.test(minusculas)) {
      return minusculas;
    }
  }
  // O comprimento só se mede a texto: `String(x)` num objecto chamava o
  // `toString` de quem o passou, com efeitos e erros que não são deste módulo.
  throw new TenantInvalidoError(typeof tenant, typeof tenant === "string" ? tenant.length : 0);
}

/** Verdadeiro para o que tem a forma de um `pg.Pool`. */
function pareceUmPool(cliente: ClienteSql): boolean {
  const forma = cliente as unknown as Record<string, unknown>;
  return (
    typeof forma.totalCount === "number" ||
    typeof forma.idleCount === "number" ||
    typeof forma.waitingCount === "number"
  );
}

/** Clientes com uma transacção deste módulo aberta, por identidade. */
const EM_USO = new WeakSet<object>();

async function emTransaccao<T>(
  cliente: ClienteSql,
  preparar: (() => Promise<unknown>) | null,
  trabalho: (cliente: ClienteSql) => Promise<T>,
): Promise<T> {
  if (pareceUmPool(cliente)) {
    throw new PoolRecusadoError();
  }
  // Síncrono, antes do primeiro `await`: dois pedidos concorrentes não passam
  // os dois por aqui antes de um deles marcar o cliente.
  if (EM_USO.has(cliente)) {
    throw new LigacaoEmUsoError();
  }
  EM_USO.add(cliente);
  try {
    await cliente.query("BEGIN");
    try {
      if (preparar !== null) {
        await preparar();
      }
      const resultado = await trabalho(cliente);
      await cliente.query("COMMIT");
      return resultado;
    } catch (erro) {
      try {
        await cliente.query("ROLLBACK");
      } catch {
        // O `ROLLBACK` tambem pode falhar (ligacao perdida). O erro que interessa
        // a quem chama e o primeiro: sem isto, a causa ficava escondida atras de
        // «nao foi possivel desfazer».
      }
      throw erro;
    }
  } finally {
    EM_USO.delete(cliente);
  }
}

/** Transacção com `app.tenant_id` definido. */
export async function comTenant<T>(
  cliente: ClienteSql,
  tenant: unknown,
  trabalho: (cliente: ClienteSql) => Promise<T>,
): Promise<T> {
  const canonico = normalizarTenant(tenant);
  return emTransaccao(
    cliente,
    () => cliente.query(SQL_DEFINIR_CONTEXTO, [canonico]),
    trabalho,
  );
}

/**
 * Transacção **sem** contexto de tenant, para `kamba_batch`. Exige o job.
 *
 * Não verifica o papel da ligação: com outro papel a RLS devolve zero linhas,
 * que é a falha certa. O que isto garante é que não há uso sem nome nem sem
 * contagem.
 */
export async function comBatch<T>(
  cliente: ClienteSql,
  job: unknown,
  trabalho: (cliente: ClienteSql) => Promise<T>,
): Promise<T> {
  if (typeof job !== "string" || !NOME_DE_JOB.test(job)) {
    throw new JobSemNomeError();
  }
  CONTADORES.incrementar(`${METRICA_BATCH}:${job}`);
  return emTransaccao(cliente, null, trabalho);
}
