/**
 * Uma base falsa para as baterias dos modos no *gate* 4 (KAM-018).
 *
 * **O que esta base prova e o que ela não prova**, dito à cabeça, porque é a
 * confusão que o `db/tests_chr/test_chr.py` já teve de escrever para o CHR: uma
 * base falsa devolve o que se lhe mandou devolver, e um teste de concorrência
 * ou de isolamento sobre ela não prova concorrência nem isolamento nenhum. O
 * que ela prova é a **ordem** — que o *lock* é pedido antes da leitura, que o
 * predicado da tabela vai no `UPDATE`, que a supressão é escrita antes de o
 * `false` ser devolvido — e isso é exactamente o que se não consegue ver numa
 * base real sem instrumentar o servidor.
 *
 * A corrida das 100 intercalações, o *lock* a serializar de verdade, a RLS e o
 * privilégio do `mode` provam-se em `tests_bd/modos.bd.test.ts`, contra o
 * PostgreSQL 18.6 do *gate* 8.
 */

import type { ClienteSql, ComTenant, Modo } from "../src/modos/index.ts";

/** Uma instrução vista pela base falsa: o texto e os parâmetros. */
export interface Vista {
  readonly sql: string;
  readonly parametros: readonly unknown[];
}

/** O estado de uma conversa na base falsa. */
export interface Linha {
  contact_id: string;
  mode: Modo;
  last_human_activity_at: Date | null;
}

/**
 * Uma base falsa que entende as sete consultas de `modos/consultas.ts`.
 *
 * Reconhece-as por um fragmento do texto **delas** e não por uma cópia: o
 * `#qual` compara com as constantes importadas, pelo que renomear uma consulta
 * ou mudar-lhe o corpo não deixa este duplo a responder ao que já não existe.
 */
export class BaseFalsa {
  readonly vistas: Vista[] = [];
  readonly conversas = new Map<string, Linha>();
  /** As chaves de idempotência já suprimidas, para o `ON CONFLICT`. */
  readonly suprimidas = new Set<string>();
  /** `true` depois de o *lock* ter sido pedido nesta transacção. */
  trancada = false;
  /** Quantas transacções `comTenant` se abriram. */
  transaccoes = 0;
  /** Se definido, o `UPDATE` do modo não casa linha nenhuma: corrida perdida. */
  perderCorrida = false;
  /** Corre antes de cada instrução. É onde um teste intercala outra coisa. */
  antesDe: ((sql: string) => void) | null = null;

  #contador = 0;

  /**
   * As oito constantes de `modos/consultas.ts`, por nome curto.
   *
   * Campo e atribuicao e nao propriedade de construtor (`private readonly` no
   * parametro): o `erasableSyntaxOnly` do `tsconfig` recusa essa forma, porque
   * ela **emite codigo** e o projecto compila TypeScript por apagamento.
   */
  readonly consultas: {
    readonly trancar: string;
    readonly contacto: string;
    readonly ler: string;
    readonly doContacto: string;
    readonly mudar: string;
    readonly actividade: string;
    readonly pausar: string;
    readonly suprimir: string;
    readonly emitir: string;
  };

  constructor(consultas: BaseFalsa["consultas"]) {
    this.consultas = consultas;
  }

  /** Põe uma conversa na base falsa e devolve o `id`. */
  semear(id: string, linha: Linha): string {
    this.conversas.set(id, { ...linha });
    return id;
  }

  /** O `ComTenant` que as dependências pedem. */
  comTenant(): ComTenant {
    return async (tenantId, trabalho) => {
      if (tenantId === "") throw new Error("contexto de tenant em falta");
      this.transaccoes += 1;
      this.trancada = false;
      return trabalho(this as unknown as ClienteSql);
    };
  }

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ readonly rows: readonly Readonly<Record<string, unknown>>[] }> {
    this.antesDe?.(sql);
    this.vistas.push({ sql, parametros });
    const c = this.consultas;
    if (sql === c.trancar) {
      this.trancada = true;
      return { rows: [{}] };
    }
    if (sql === c.contacto) {
      // **Sem *lock***, e é o único caso: é a leitura que descobre a chave do
      // *lock*, e tem de correr antes dele. Ver `SQL_CONTACTO_DA_CONVERSA`.
      const linha = this.conversas.get(String(parametros[1]));
      return { rows: linha === undefined ? [] : [{ contact_id: linha.contact_id }] };
    }
    if (sql === c.ler) {
      // **Exige o *lock***, e é a asserção central desta base falsa: esta é a
      // leitura que **decide**, e decidir antes de trancar é decidir fora da
      // secção crítica — coisa que nenhuma base real denuncia.
      this.#exigirTranca(sql);
      const linha = this.conversas.get(String(parametros[1]));
      return {
        rows: [
          { mode: linha?.mode, last_human_activity_at: linha?.last_human_activity_at },
        ].filter(() => linha !== undefined),
      };
    }
    if (sql === c.doContacto) {
      this.#exigirTranca(sql);
      const contacto = String(parametros[1]);
      const rows = [...this.conversas.entries()]
        .filter(([, l]) => l.contact_id === contacto)
        .map(([id, l]) => ({ id, mode: l.mode, last_human_activity_at: l.last_human_activity_at }));
      return { rows };
    }
    if (sql === c.mudar) {
      this.#exigirTranca(sql);
      if (this.perderCorrida) return { rows: [] };
      const id = String(parametros[1]);
      const para = parametros[2] as Modo;
      const origens = parametros[3] as readonly Modo[];
      const actividade = parametros[4] as Date | null;
      const linha = this.conversas.get(id);
      if (linha === undefined || !origens.includes(linha.mode)) return { rows: [] };
      const antes = linha.mode;
      linha.mode = para;
      linha.last_human_activity_at = maior(linha.last_human_activity_at, actividade);
      return { rows: [{ modo_antes: antes, modo_depois: para }] };
    }
    if (sql === c.actividade) {
      this.#exigirTranca(sql);
      const linha = this.conversas.get(String(parametros[1]));
      if (linha === undefined) return { rows: [] };
      linha.last_human_activity_at = maior(
        linha.last_human_activity_at,
        parametros[2] as Date | null,
      );
      return { rows: [{ mode: linha.mode }] };
    }
    if (sql === c.pausar) {
      const limite = parametros[1] as Date;
      const origens = parametros[2] as readonly Modo[];
      const para = parametros[3] as Modo;
      const rows: { id: string; contact_id: string }[] = [];
      for (const [id, linha] of this.conversas) {
        if (!origens.includes(linha.mode)) continue;
        // A base falsa não tem `handoffs`: o `COALESCE` resolve-se só pela
        // actividade humana, e uma conversa sem ela não é pausada — que é
        // exactamente o que o SQL faz quando também não há *handoff*.
        const desde = linha.last_human_activity_at;
        if (desde === null || desde.getTime() >= limite.getTime()) continue;
        linha.mode = para;
        rows.push({ id, contact_id: linha.contact_id });
      }
      return { rows };
    }
    if (sql === c.suprimir) {
      this.#exigirTranca(sql);
      const chave = `${String(parametros[0])}\u0000${String(parametros[4])}`;
      if (this.suprimidas.has(chave)) return { rows: [] };
      this.suprimidas.add(chave);
      this.#contador += 1;
      return { rows: [{ id: `sup-${this.#contador}` }] };
    }
    if (sql === c.emitir) {
      this.#contador += 1;
      return { rows: [{ event_id: `evt-${this.#contador}` }] };
    }
    throw new Error(`a base falsa nao conhece esta instrucao:\n${sql}`);
  }

  /** O texto de tudo o que passou, para procurar um canário. */
  emTexto(): string {
    return this.vistas
      .map(({ sql, parametros }) => [sql, ...parametros.map((p) => String(p))].join("\u0000"))
      .join("\n");
  }

  #exigirTranca(sql: string): void {
    if (this.trancada) return;
    throw new Error(
      "esta instrucao correu sem o `pg_advisory_xact_lock` da conversa, e o " +
        `criterio 2 do KAM-018 exige-o:\n${sql}`,
    );
  }
}

function maior(a: Date | null, b: Date | null): Date | null {
  if (a === null) return b;
  if (b === null) return a;
  return a.getTime() >= b.getTime() ? a : b;
}
