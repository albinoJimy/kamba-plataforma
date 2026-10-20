/**
 * Uma base falsa para os testes do CHR (KAM-014).
 *
 * Registra as instruções pela ordem em que as recebe — é essa lista que torna a
 * ordem verificável — e responde pelo que se lhe mandou responder. É o mesmo
 * padrão do `ten.test.ts` e do `eventos.consumo.test.ts`, e o limite é o mesmo:
 * **uma base falsa não prova nada sobre a base**. O que estes testes garantem é
 * que a biblioteca faz as perguntas certas e trata cada resposta como devia; o
 * que corre contra um PostgreSQL real vive em `db/tests_chr/`.
 */

export interface InstrucaoRegistada {
  readonly sql: string;
  readonly parametros: readonly unknown[];
}

type Resposta =
  | { readonly rows: readonly Readonly<Record<string, unknown>>[] }
  | Error;

/**
 * Responde à primeira instrução cujo SQL contenha a chave, pela ordem em que as
 * chaves foram registadas.
 *
 * A correspondência é por **excerto** e não por igualdade: o SQL das consultas
 * tem indentação e comentários, e um teste que o copiasse por inteiro provava a
 * cópia.
 */
export class BaseFalsa {
  readonly instrucoes: InstrucaoRegistada[] = [];
  readonly #respostas: [string, Resposta[]][] = [];

  /** Regista respostas para as instruções que contenham `excerto`, por ordem. */
  responde(excerto: string, ...respostas: Resposta[]): this {
    this.#respostas.push([excerto, respostas]);
    return this;
  }

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ readonly rows: readonly Readonly<Record<string, unknown>>[] }> {
    this.instrucoes.push({ sql, parametros });
    for (const [excerto, respostas] of this.#respostas) {
      if (!sql.includes(excerto)) continue;
      const resposta = respostas.length > 1 ? respostas.shift() : respostas[0];
      if (resposta === undefined) break;
      if (resposta instanceof Error) throw resposta;
      return resposta;
    }
    return { rows: [] };
  }

  /** Os SQL registados, por ordem, reduzidos à primeira palavra-chave útil. */
  get vistas(): string[] {
    return this.instrucoes.map((i) => i.sql.trim().split(/\s+/).slice(0, 3).join(" "));
  }

  quantas(excerto: string): number {
    return this.instrucoes.filter((i) => i.sql.includes(excerto)).length;
  }
}

/** Uma linha de `SQL_CANAL` com valores válidos, mais o que se quiser trocar. */
export function linhaDeCanal(
  troca: Readonly<Record<string, unknown>> = {},
): Readonly<Record<string, unknown>> {
  return {
    tenant_id: "11111111-1111-4111-8111-111111111111",
    channel_id: "22222222-2222-4222-8222-222222222222",
    vertical: "vendedor",
    plano: "free",
    estado_tenant: "ativo",
    estado_canal: "ativo",
    channel_mode: "coexistencia",
    origem: "pme",
    tipo_tenant: "pme",
    ...troca,
  };
}

/** Um `EventoDeEntrada` de `message`, mais o que se quiser trocar. */
export function mensagemDe(troca: Readonly<Record<string, unknown>> = {}): {
  readonly kind: "message";
  readonly eventKey: string;
  readonly wabaId: string;
  readonly phoneNumberId: string | null;
  readonly waType: "text";
  readonly interlocutor: { readonly bsuid: string | null; readonly telefone: string | null };
} {
  return {
    kind: "message",
    eventKey: "wamid.AAA",
    wabaId: "waba-1",
    phoneNumberId: "pnid-1",
    waType: "text",
    interlocutor: { bsuid: "bsuid-1", telefone: "999100000001" },
    ...troca,
  } as never;
}
