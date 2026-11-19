/**
 * A recusa da base sobre o tecto de confiança, vista do lado da aplicação
 * (KAM-219).
 *
 * ```text
 * tenant_guard_tecto_recusado_total  counter  42501 sobre platform.trust_level
 * ```
 *
 * **Porque é que se conta aqui, e não na base.** O KAM-096 tirou ao `kamba_app`
 * o `INSERT`, o `UPDATE` e o `DELETE` em `platform.trust_level`, e a recusa por
 * privilégio acontece **antes** de qualquer *trigger*: nenhum objecto da base vê
 * a tentativa nem a pode contar, e o compose não tem quem recolha o registo do
 * PostgreSQL (o KAM-203 mediu-o). Quem a vê é quem recebeu o erro. O
 * `comTenant` e o `comBatch` são o sítio por onde passa toda a transacção da
 * aplicação em TypeScript, e o `catch` deles vê o `42501` antes de o devolver.
 *
 * **O predicado:** `code === "42501"` **e** a mensagem a nomear `trust_level`
 * (`permission denied for table trust_level`). A mensagem traduz-se com o
 * `lc_messages` do servidor, e o nome da tabela não: casa-se o nome, e não a
 * frase. Um `42501` sobre outra tabela não conta — o alerta é do tecto. Conta
 * também a leitura recusada do `motivo`, que dá a mesma mensagem: as duas são a
 * aplicação a tentar o que lhe foi tirado.
 *
 * **Uma vez por erro.** O recálculo da confiança corre um `comTenant` dentro de
 * um `comBatch` (`../confianca/lote.ts`), e o mesmo erro passa pelos dois
 * `catch`: lembra-se o objecto num `WeakSet`, e o segundo não conta.
 *
 * **O limite, dito.** Conta só o que passa por uma transacção destes dois
 * *helpers*, num processo TypeScript que a sirva: uma consulta solta num *pool*,
 * um `catch` dentro do trabalho que engula o erro, um processo Python ou uma
 * ligação directa com a credencial do `kamba_app` não chegam aqui. Ver essas
 * pede o registo do PostgreSQL recolhido — peça nova, com licença por decidir —
 * ou esquema novo: é o credor que o bloco do KAM-219 nomeia. E não distingue o
 * papel: um `42501` do `kamba_batch` sobre o tecto (mudar a moeda, apagar)
 * conta também, e é também um defeito que pede quem olhe.
 *
 * **Sem etiquetas**, logo sem tenant (`OBS-I`): qual tenant lê-se do registo do
 * processo, que diz o passo e não o tenant, e do `audit_log`, que só tem as
 * escritas que passaram. **Nasce a zero**: a série sai desde o arranque, e uma
 * regra com `increase(...)` vê a primeira tentativa (a lição do cabeçalho do
 * `infra/compose/prometheus/regras/kamba.yml`). É um contador do processo, e
 * cada processo que use estes *helpers* serve o seu: o `onboarding-lote`, o
 * `com` e o `worker-canal-entrada`.
 */

export const METRICA_TECTO_RECUSADO = "tenant_guard_tecto_recusado_total";

/** O SQLSTATE da recusa por privilégio (`insufficient_privilege`). */
export const SQLSTATE_PRIVILEGIO = "42501";

/** O nome da tabela, como o PostgreSQL o escreve na mensagem. */
const TABELA_DO_TECTO = /\btrust_level\b/;

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_TECTO_RECUSADO]: [
    "counter",
    "Recusas da base (42501) sobre platform.trust_level vistas numa transaccao do tenant_guard.",
  ],
};

/** Verdadeiro para um `42501` que nomeia `trust_level`. */
export function eRecusaNoTecto(erro: unknown): boolean {
  if (typeof erro !== "object" || erro === null) return false;
  const { code, message } = erro as { code?: unknown; message?: unknown };
  return code === SQLSTATE_PRIVILEGIO && typeof message === "string" && TABELA_DO_TECTO.test(message);
}

export class MetricasDaGuarda {
  #recusas = 0;
  readonly #vistos = new WeakSet<object>();

  /** Conta o erro se for uma recusa no tecto e ainda não tiver sido contado. */
  observar(erro: unknown): void {
    if (!eRecusaNoTecto(erro)) return;
    const objecto = erro as object;
    if (this.#vistos.has(objecto)) return;
    this.#vistos.add(objecto);
    this.#recusas += 1;
  }

  /** O valor do contador. Para os ensaios. */
  recusas(): number {
    return this.#recusas;
  }

  /** O formato de exposição do Prometheus. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`, `# TYPE ${nome} ${tipo}`, `${nome} ${this.#recusas}`);
    }
    return `${linhas.join("\n")}\n`;
  }
}

/** A instância do processo, que o `comTenant` e o `comBatch` alimentam. */
export const METRICAS_DA_GUARDA = new MetricasDaGuarda();
