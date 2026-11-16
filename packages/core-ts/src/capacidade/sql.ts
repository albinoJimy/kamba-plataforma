/**
 * O adaptador PostgreSQL da lista de espera (KAM-095).
 *
 * As consultas são constantes exportadas e **literais**, de propósito: a suite
 * de base de dados (`db/tests/test_lista_espera_schema.py`) executa **estas**
 * cadeias pela `ConsultaDoTypeScript`, e não uma cópia delas — e uma constante
 * com `${...}` chegava lá com o `$` literal.
 *
 * ## Corre como `kamba_batch`
 *
 * A vaga é uma conta sobre **todos** os casos à espera, de todos os *tenants*:
 * o limite é da nossa app perante a Meta, não de uma loja. Com a RLS `FORCE`
 * da `waitlist_entry`, o `kamba_app` de um caso contaria só o seu — e contaria
 * mal, que é pior do que não contar, porque parece certo. É a mesma razão por
 * que o `es_onboardings_7d` do KAM-016 e o `phash` do KAM-087 correm com
 * `BYPASSRLS`. O dono nunca chega a esta porta: chega à rota, que só aceita o
 * caso da sessão.
 *
 * ## A tranca, e porque não é o `SKIP LOCKED` dos Detalhes Técnicos
 *
 * O bloco escreve «`SELECT ... FOR UPDATE SKIP LOCKED` sobre a fila». Isso
 * serve para **distribuir trabalho** — cada trabalhador apanha uma linha que
 * nenhum outro tem —, e aqui o recurso disputado não é uma linha, é a **vaga**,
 * que é uma conta sobre a tabela inteira. Com `SKIP LOCKED`, dois trabalhadores
 * com uma vaga livre trancavam cada um uma cabeça diferente e convidavam as
 * duas: o critério 9 falhava, e a fila deixava de ser FIFO, porque o segundo
 * saltava a cabeça trancada. Por isso cada transacção começa por um
 * `pg_advisory_xact_lock` da fila, e dentro dela as leituras são simples.
 *
 * **A forma de dois inteiros, e não a de um `bigint`**: o PostgreSQL guarda as
 * duas em espaços de chaves distintos, e as trancas desta casa (o
 * `hashtextextended` dos modos, KAM-018) são todas de um `bigint`. E não um
 * `LOCK TABLE`: os modos que se excluem a si próprios exigem `UPDATE` **da
 * tabela**, e o `kamba_batch` só tem `UPDATE` por coluna — que é o que o deixa
 * não poder reescrever o `aprovado_em`.
 *
 * ***shortcut:*** as leituras da vaga e da posição varrem a tabela sem índice
 * parcial. À escala do limite (dez vagas por semana, uma fila de centenas) é
 * irrelevante; revê-se se a fila passar de 10 000 entradas.
 */

import type {
  Campos,
  Entrada,
  EstadoDaEntrada,
  Fotografia,
  Limite,
  OperacoesDaLista,
  OrigemDoLimite,
  RepositorioDaLista,
} from "./contrato.ts";
import { ESTADOS_DA_ENTRADA } from "./contrato.ts";

/** O cliente de base de dados, como nos outros módulos. */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/** Um conjunto de ligações: a transacção precisa de uma ligação só. */
export interface ConjuntoSql extends ClienteSql {
  connect(): Promise<ClienteSql & { release(erro?: Error | boolean): void }>;
}

/** A tranca da fila. Ver a nota do módulo. */
export const SQL_TRANCAR = `SELECT pg_advisory_xact_lock(hashtext('platform.waitlist_entry'), 0)`;

export const SQL_LIMITE = `SELECT es_max_por_7d, origem, fundamento FROM platform.onboarding_capacity`;

export const SQL_ENTRADA = `SELECT onboarding_id, estado, aprovado_em, na_fila_desde, convite_hash, convidado_em,
  convite_expira_em, tentativas, concluido_em, criado_em
  FROM platform.waitlist_entry WHERE onboarding_id = $1`;

/**
 * Só casos aprovados entram, e **o `aprovado_em` não vem de quem chama**: o
 * *trigger* `waitlist_entry_do_caso` lê-o do caso e recusa uma fase fora de
 * `aprovado`/`aguarda_es`. O filtro aqui é para a recusa ser um «sem linha»
 * (`null`) e não uma excepção; a barreira é o *trigger*.
 */
export const SQL_INSERIR = `INSERT INTO platform.waitlist_entry (onboarding_id, tenant_id)
  SELECT c.id, c.tenant_id FROM platform.onboarding_case c
   WHERE c.id = $1 AND c.fase IN ('aprovado', 'aguarda_es')
  ON CONFLICT (onboarding_id) DO NOTHING
  RETURNING onboarding_id, estado, aprovado_em, na_fila_desde, convite_hash, convidado_em,
    convite_expira_em, tentativas, concluido_em, criado_em`;

/** Vagas ocupadas: concluídos na janela (`$1` = desde) e convites vivos (`$2` = agora). */
export const SQL_OCUPADAS = `SELECT count(*)::int AS n FROM platform.waitlist_entry
  WHERE (estado = 'concluido' AND concluido_em > $1)
     OR (estado = 'convidado' AND convite_expira_em > $2)`;

export const SQL_ELEGIVEL = `SELECT EXISTS (SELECT 1 FROM platform.onboarding_case
  WHERE id = $1 AND fase IN ('aprovado', 'aguarda_es')) AS elegivel`;

/** Quantos estão à frente, pela ordem `(na_fila_desde, onboarding_id)`. */
export const SQL_A_FRENTE = `SELECT count(*)::int AS n FROM platform.waitlist_entry w
  JOIN platform.waitlist_entry eu ON eu.onboarding_id = $1
  WHERE w.estado = 'aguardando'
    AND (w.na_fila_desde, w.onboarding_id) < (eu.na_fila_desde, eu.onboarding_id)`;

export const SQL_CABECA = `SELECT onboarding_id, estado, aprovado_em, na_fila_desde, convite_hash, convidado_em,
  convite_expira_em, tentativas, concluido_em, criado_em
  FROM platform.waitlist_entry WHERE estado = 'aguardando'
  ORDER BY na_fila_desde, onboarding_id LIMIT 1`;

/**
 * A transição, *compare-and-set* sobre o estado (`$2`).
 *
 * **O convite e o `concluido_em` derivam do estado de destino**, e não de quem
 * chama: o *hash* e o prazo só ficam em `convidado`, o `concluido_em` só em
 * `concluido`. É a mesma regra que as restrições `waitlist_entry_convite_ck` e
 * `waitlist_entry_concluido_ck` impõem — aqui escrita para que nenhuma
 * transição as possa violar por esquecimento. As outras colunas mantêm-se
 * quando o parâmetro vem a nulo.
 */
export const SQL_TRANSITAR = `UPDATE platform.waitlist_entry SET
  estado = $3::text,
  na_fila_desde = coalesce($4::timestamptz, na_fila_desde),
  convidado_em = coalesce($5::timestamptz, convidado_em),
  tentativas = coalesce($6::smallint, tentativas),
  convite_hash = CASE WHEN $3::text = 'convidado' THEN $7::bytea END,
  convite_expira_em = CASE WHEN $3::text = 'convidado' THEN $8::timestamptz END,
  concluido_em = CASE WHEN $3::text = 'concluido' THEN $9::timestamptz END
  WHERE onboarding_id = $1 AND estado = $2::text`;

export const SQL_POR_CONVITE = `SELECT onboarding_id, estado, aprovado_em, na_fila_desde, convite_hash, convidado_em,
  convite_expira_em, tentativas, concluido_em, criado_em
  FROM platform.waitlist_entry WHERE convite_hash = $1`;

export const SQL_VENCIDOS = `SELECT onboarding_id FROM platform.waitlist_entry
  WHERE estado = 'convidado' AND convite_expira_em <= $1 ORDER BY convite_expira_em, onboarding_id`;

/** O caso passa a `abandonado`, só a partir de uma fase da fila. */
export const SQL_ABANDONAR_CASO = `UPDATE platform.onboarding_case SET fase = 'abandonado'
  WHERE id = $1 AND fase IN ('aprovado', 'aguarda_es')`;

export const SQL_POR_ESTADO = `SELECT estado, count(*)::int AS n FROM platform.waitlist_entry GROUP BY estado`;

export const SQL_CONCLUIDOS_NA_JANELA = `SELECT concluido_em,
  extract(epoch FROM concluido_em - greatest(criado_em, na_fila_desde))::float8 AS espera
  FROM platform.waitlist_entry WHERE estado = 'concluido' AND concluido_em > $1
  ORDER BY concluido_em`;

interface Linha {
  onboarding_id: string;
  estado: EstadoDaEntrada;
  aprovado_em: Date;
  na_fila_desde: Date;
  convite_hash: Uint8Array | null;
  convidado_em: Date | null;
  convite_expira_em: Date | null;
  tentativas: number;
  concluido_em: Date | null;
  criado_em: Date;
}

function entradaDe(l: Linha): Entrada {
  return {
    onboardingId: l.onboarding_id,
    estado: l.estado,
    aprovadoEm: l.aprovado_em,
    naFilaDesde: l.na_fila_desde,
    convidadoEm: l.convidado_em,
    conviteExpiraEm: l.convite_expira_em,
    tentativas: Number(l.tentativas),
    concluidoEm: l.concluido_em,
    criadoEm: l.criado_em,
  };
}

function limiteDe(rows: readonly { es_max_por_7d: number; origem: OrigemDoLimite; fundamento: string }[]): Limite {
  const l = rows[0];
  // Sem a linha não há limite, e a fila **fecha**: zero vagas, ninguém entra
  // à frente de ninguém. Inventar um 10 aqui era a constante que o critério 3
  // tirou do código.
  if (l === undefined) return { maximo: 0, origem: "nao_verificado", fundamento: "sem linha em onboarding_capacity" };
  return { maximo: Number(l.es_max_por_7d), origem: l.origem, fundamento: l.fundamento };
}

function operacoes(c: ClienteSql): OperacoesDaLista {
  const uma = async (texto: string, valores: readonly unknown[]): Promise<Entrada | null> => {
    const r = await c.query<Linha>(texto, valores);
    return r.rows[0] === undefined ? null : entradaDe(r.rows[0]);
  };
  const contar = async (texto: string, valores: readonly unknown[]): Promise<number> => {
    const r = await c.query<{ n: number }>(texto, valores);
    return Number(r.rows[0]?.n ?? 0);
  };
  return {
    limite: async () => limiteDe((await c.query<{ es_max_por_7d: number; origem: OrigemDoLimite; fundamento: string }>(SQL_LIMITE)).rows),
    entrada: (id) => uma(SQL_ENTRADA, [id]),
    inserir: (id) => uma(SQL_INSERIR, [id]),
    ocupadas: (desde, agora) => contar(SQL_OCUPADAS, [desde, agora]),
    elegivel: async (id) =>
      (await c.query<{ elegivel: boolean }>(SQL_ELEGIVEL, [id])).rows[0]?.elegivel === true,
    aFrente: (id) => contar(SQL_A_FRENTE, [id]),
    cabeca: () => uma(SQL_CABECA, []),
    transitar: async (id: string, de: EstadoDaEntrada, para: EstadoDaEntrada, campos: Campos) => {
      const r = await c.query(SQL_TRANSITAR, [
        id,
        de,
        para,
        campos.naFilaDesde ?? null,
        campos.convidadoEm ?? null,
        campos.tentativas ?? null,
        typeof campos.conviteHash === "string" ? Buffer.from(campos.conviteHash, "hex") : null,
        campos.conviteExpiraEm ?? null,
        campos.concluidoEm ?? null,
      ]);
      return ((r as { rowCount?: number | null }).rowCount ?? 0) === 1;
    },
    porConvite: (hash) => uma(SQL_POR_CONVITE, [Buffer.from(hash, "hex")]),
    vencidos: async (agora) =>
      (await c.query<{ onboarding_id: string }>(SQL_VENCIDOS, [agora])).rows.map((l) => l.onboarding_id),
    abandonarCaso: async (id) => {
      await c.query(SQL_ABANDONAR_CASO, [id]);
    },
  };
}

/** O repositório da lista sobre PostgreSQL. */
export class ListaSql implements RepositorioDaLista {
  readonly #conjunto: ConjuntoSql;

  constructor(conjunto: ConjuntoSql) {
    this.#conjunto = conjunto;
  }

  async emTransaccao<T>(fazer: (operacoes: OperacoesDaLista) => Promise<T>): Promise<T> {
    const c = await this.#conjunto.connect();
    let falhou: Error | undefined;
    try {
      await c.query("BEGIN");
      await c.query(SQL_TRANCAR);
      const resultado = await fazer(operacoes(c));
      await c.query("COMMIT");
      return resultado;
    } catch (erro) {
      falhou = erro instanceof Error ? erro : new Error(String(erro));
      try {
        await c.query("ROLLBACK");
      } catch {
        // A ligação partida devolve-se ao conjunto marcada como tal, abaixo.
      }
      throw erro;
    } finally {
      c.release(falhou);
    }
  }

  async fotografia(desde: Date): Promise<Fotografia> {
    const porEstado = Object.fromEntries(ESTADOS_DA_ENTRADA.map((e) => [e, 0])) as Record<EstadoDaEntrada, number>;
    for (const l of (await this.#conjunto.query<{ estado: EstadoDaEntrada; n: number }>(SQL_POR_ESTADO)).rows) {
      porEstado[l.estado] = Number(l.n);
    }
    const concluidos = (await this.#conjunto.query<{ concluido_em: Date; espera: number }>(SQL_CONCLUIDOS_NA_JANELA, [desde])).rows;
    const limite = limiteDe((await this.#conjunto.query<{ es_max_por_7d: number; origem: OrigemDoLimite; fundamento: string }>(SQL_LIMITE)).rows);
    return {
      porEstado,
      concluidosNaJanela: concluidos.map((l) => l.concluido_em),
      esperaMediaSegundos:
        concluidos.length === 0 ? null : concluidos.reduce((a, l) => a + Number(l.espera), 0) / concluidos.length,
      limite,
    };
  }
}
