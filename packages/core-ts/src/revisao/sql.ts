/**
 * O adaptador PostgreSQL da fila de revisão (KAM-089).
 *
 * As consultas são constantes exportadas: a suite de base de dados
 * (`db/tests/test_revisao_schema.py`) executa **estas** cadeias pela
 * `ConsultaDoTypeScript`, e não uma cópia delas.
 *
 * ## Corre como `kamba_batch`
 *
 * A fila atravessa tenants — o revisor vê casos de todos, e a quota conta uma
 * origem através de casos de tenants diferentes —, e é por isso que corre no
 * papel com `BYPASSRLS`, que é o auditado. O `kamba_app` não tem privilégio
 * nenhum nas duas tabelas: um defeito no `onboarding-web` não mostra ao dono o
 * motivo interno do seu caso.
 */

import { createHash } from "node:crypto";

import type {
  Auditoria,
  CasoDeRevisao,
  CasoNovo,
  DecisaoNova,
  DecisaoRegistada,
  EstadoDoCaso,
  Evidencia,
  FiltroDaFila,
  RegistoDeAuditoria,
  RepositorioDeRevisao,
  Sla,
} from "./contrato.ts";

export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * `ON CONFLICT DO NOTHING` sobre a chave de abertura (critério 9): reentregar o
 * mesmo evento não cria segundo caso. Sem linha devolvida houve conflito, e
 * quem chama relê pela chave.
 */
export const SQL_ABRIR = `INSERT INTO platform.review_case
  (tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico, evidencias,
   recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at)
  VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12, $13)
  ON CONFLICT ON CONSTRAINT review_case_abertura_uq DO NOTHING
  RETURNING id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at`;

export const SQL_POR_CHAVE = `SELECT id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at FROM platform.review_case
  WHERE tipo = $1 AND tenant_id = $2 AND onboarding_id IS NOT DISTINCT FROM $3 AND motivo_codigo = $4`;

export const SQL_POR_ID = `SELECT id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at FROM platform.review_case WHERE id = $1`;

/** Só se o estado actual for o esperado: duas decisões concorrentes não passam as duas. */
export const SQL_TRANSITAR = `UPDATE platform.review_case SET estado = $3
  WHERE id = $1 AND estado = $2 RETURNING id`;

/** A transição que reinicia o prazo: a saída da triagem e a abertura do recurso. */
export const SQL_TRANSITAR_COM_SLA = `UPDATE platform.review_case
  SET estado = $3, fila_at = $4, sla_alerta_at = $5, sla_due_at = $6, sla_alertado_at = NULL
  WHERE id = $1 AND estado = $2 RETURNING id`;

/** O `tenant_id` lê-se do caso, na mesma instrução: a FK composta prende os dois. */
export const SQL_REGISTAR_DECISAO = `INSERT INTO platform.review_decision_log
  (case_id, tenant_id, revisor_id, decisao, instancia, regra, nota_enc)
  SELECT r.id, r.tenant_id, $2, $3, $4, $5, $6 FROM platform.review_case r WHERE r.id = $1
  RETURNING id, case_id, revisor_id, decisao, instancia, regra, nota_enc, em`;

export const SQL_DECISOES = `SELECT id, case_id, revisor_id, decisao, instancia, regra, nota_enc, em
  FROM platform.review_decision_log WHERE case_id = $1 ORDER BY em, id`;

export const SQL_PENDENTES_DO_ONBOARDING = `SELECT id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at FROM platform.review_case
  WHERE onboarding_id = $1
    AND estado IN ('em_triagem_automatica', 'aberto', 'em_analise', 'escalado', 'recurso_aberto')`;

/**
 * A quota: casos **deste** dia que entraram na vista humana vindos da mesma
 * origem — o `ip_prefix_hash` do onboarding, ou o `device_hash` na falta dele.
 * Uma origem nula conta com as outras nulas: não ter origem não dá quota
 * própria.
 *
 * ***shortcut:*** sem trinco, duas aberturas concorrentes da mesma origem podem
 * passar as duas no limite, e a quota excede-se pelo número de pedidos em
 * paralelo; aceitável enquanto a abertura vier de passos sequenciais por caso
 * (KYC, guia). Revê-se se a fila passar a ser alimentada em paralelo, com um
 * `pg_advisory_xact_lock` sobre a origem.
 */
export const SQL_CONTAR_NA_FILA = `SELECT count(*)::int AS n
  FROM platform.review_case r JOIN platform.onboarding_case c ON c.id = r.onboarding_id
  WHERE coalesce(c.ip_prefix_hash, c.device_hash) IS NOT DISTINCT FROM $1::bytea
    AND r.estado <> 'em_triagem_automatica' AND r.fila_at >= $2`;

export const SQL_EM_TRIAGEM = `SELECT id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at FROM platform.review_case
  WHERE estado = 'em_triagem_automatica' ORDER BY criado_at, id LIMIT $1`;

export const SQL_ALERTAS_DEVIDOS = `SELECT id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at FROM platform.review_case
  WHERE estado IN ('aberto', 'em_analise', 'escalado', 'recurso_aberto')
    AND sla_alertado_at IS NULL AND sla_alerta_at <= $1`;

export const SQL_MARCAR_ALERTADO = `UPDATE platform.review_case SET sla_alertado_at = $2
  WHERE id = $1 AND sla_alertado_at IS NULL`;

/** Uma página da vista humana. Sem triagem; por prioridade e prazo. */
export const SQL_PAGINA = `SELECT id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at FROM platform.review_case
  WHERE estado <> 'em_triagem_automatica'
    AND ($1::text IS NULL OR tipo = $1) AND ($2::text IS NULL OR estado = $2)
  ORDER BY prioridade, sla_due_at, id LIMIT $3 OFFSET $4`;

/** As linhas da vista do SLA, para as métricas. */
export const SQL_VISTA_SLA = `SELECT case_id, tipo, estado, fila_at, sla_due_at, primeira_decisao_at, dentro_do_sla
  FROM platform.v_review_sla`;

/**
 * Os contadores por tipo, motivo e decisão (critério 8). O motivo conta-se pela
 * **família** — a parte antes dos dois pontos —, porque `screening:<sha256>` e
 * `amostra:<onboarding>` são um motivo por caso. A decisão é a **última** da
 * instância mais alta; `null` para o caso ainda sem decisão.
 */
export const SQL_CONTADORES = `SELECT r.tipo, split_part(r.motivo_codigo, ':', 1) AS motivo, d.decisao, count(*)::int AS n
  FROM platform.review_case r
  LEFT JOIN LATERAL (
    SELECT l.decisao FROM platform.review_decision_log l WHERE l.case_id = r.id
    ORDER BY (l.instancia = 'recurso') DESC, l.em DESC, l.id DESC LIMIT 1
  ) d ON true
  GROUP BY 1, 2, 3 ORDER BY 1, 2, 3`;

/** O `audit_log` (KAM-012), pela função do `0006`. O ator é sempre `staff`. */
export const SQL_AUDITAR = `SELECT platform.audit_append($1, 'staff', $2, $3, $4, $5, NULL, $6)`;

interface Linha {
  id: string;
  tipo: CasoDeRevisao["tipo"];
  onboarding_id: string | null;
  tenant_id: string;
  motivo_codigo: string;
  motivo_interno: string;
  motivo_publico: CasoDeRevisao["motivoPublico"];
  evidencias: Evidencia[] | string;
  recomendacao: CasoDeRevisao["recomendacao"];
  estado: EstadoDoCaso;
  prioridade: number;
  fila_at: Date;
  sla_alerta_at: Date;
  sla_due_at: Date;
  sla_alertado_at: Date | null;
  criado_at: Date;
}

function casoDe(l: Linha): CasoDeRevisao {
  return {
    id: l.id,
    tipo: l.tipo,
    onboardingId: l.onboarding_id,
    tenantId: l.tenant_id,
    motivoCodigo: l.motivo_codigo,
    motivoInterno: l.motivo_interno,
    motivoPublico: l.motivo_publico,
    evidencias: typeof l.evidencias === "string" ? (JSON.parse(l.evidencias) as Evidencia[]) : l.evidencias,
    recomendacao: l.recomendacao,
    estado: l.estado,
    prioridade: Number(l.prioridade),
    filaEm: l.fila_at,
    slaAlertaAt: l.sla_alerta_at,
    slaDueAt: l.sla_due_at,
    slaAlertadoEm: l.sla_alertado_at,
    criadoEm: l.criado_at,
  };
}

interface LinhaDeDecisao {
  id: string;
  case_id: string;
  revisor_id: string;
  decisao: DecisaoRegistada["decisao"];
  instancia: DecisaoRegistada["instancia"];
  regra: string | null;
  nota_enc: Uint8Array | null;
  em: Date;
}

function decisaoDe(l: LinhaDeDecisao): DecisaoRegistada {
  return {
    id: l.id,
    casoId: l.case_id,
    revisorId: l.revisor_id,
    decisao: l.decisao,
    instancia: l.instancia,
    regra: l.regra,
    notaCifrada: l.nota_enc === null ? null : new Uint8Array(l.nota_enc),
    em: l.em,
  };
}

export class RevisaoSql implements RepositorioDeRevisao {
  readonly #c: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#c = cliente;
  }

  async abrir(n: CasoNovo): Promise<{ caso: CasoDeRevisao; repetido: boolean }> {
    const r = await this.#c.query<Linha>(SQL_ABRIR, [
      n.tipo,
      n.onboardingId,
      n.tenantId,
      n.motivoCodigo,
      n.motivoInterno,
      n.motivoPublico,
      JSON.stringify(n.evidencias),
      n.recomendacao,
      n.estado,
      n.prioridade,
      n.filaEm,
      n.slaAlertaAt,
      n.slaDueAt,
    ]);
    if (r.rows[0] !== undefined) return { caso: casoDe(r.rows[0]), repetido: false };
    const ja = await this.#c.query<Linha>(SQL_POR_CHAVE, [n.tipo, n.tenantId, n.onboardingId, n.motivoCodigo]);
    if (ja.rows[0] === undefined) throw new Error("review_case nao inserido nem encontrado pela chave");
    return { caso: casoDe(ja.rows[0]), repetido: true };
  }

  async porId(id: string): Promise<CasoDeRevisao | null> {
    const r = await this.#c.query<Linha>(SQL_POR_ID, [id]);
    return r.rows[0] === undefined ? null : casoDe(r.rows[0]);
  }

  async transitar(id: string, de: EstadoDoCaso, para: EstadoDoCaso, sla?: Sla & { filaEm?: Date }): Promise<boolean> {
    const r =
      sla === undefined
        ? await this.#c.query(SQL_TRANSITAR, [id, de, para])
        : await this.#c.query(SQL_TRANSITAR_COM_SLA, [
            id,
            de,
            para,
            sla.filaEm ?? new Date(),
            sla.slaAlertaAt,
            sla.slaDueAt,
          ]);
    return r.rows.length === 1;
  }

  async registarDecisao(n: DecisaoNova): Promise<DecisaoRegistada> {
    const r = await this.#c.query<LinhaDeDecisao>(SQL_REGISTAR_DECISAO, [
      n.casoId,
      n.revisorId,
      n.decisao,
      n.instancia,
      n.regra,
      n.notaCifrada === null ? null : Buffer.from(n.notaCifrada),
    ]);
    if (r.rows[0] === undefined) throw new Error("review_decision_log nao inserido: o caso nao existe");
    return decisaoDe(r.rows[0]);
  }

  async decisoes(casoId: string): Promise<readonly DecisaoRegistada[]> {
    return (await this.#c.query<LinhaDeDecisao>(SQL_DECISOES, [casoId])).rows.map(decisaoDe);
  }

  async pendentesDoOnboarding(onboardingId: string): Promise<readonly CasoDeRevisao[]> {
    return (await this.#c.query<Linha>(SQL_PENDENTES_DO_ONBOARDING, [onboardingId])).rows.map(casoDe);
  }

  async contarNaFilaDesde(origem: string | null, desde: Date): Promise<number> {
    const r = await this.#c.query<{ n: number }>(SQL_CONTAR_NA_FILA, [
      origem === null ? null : Buffer.from(origem, "hex"),
      desde,
    ]);
    return Number(r.rows[0]?.n ?? 0);
  }

  async emTriagem(limite: number): Promise<readonly CasoDeRevisao[]> {
    return (await this.#c.query<Linha>(SQL_EM_TRIAGEM, [limite])).rows.map(casoDe);
  }

  async alertasDevidos(agora: Date): Promise<readonly CasoDeRevisao[]> {
    return (await this.#c.query<Linha>(SQL_ALERTAS_DEVIDOS, [agora])).rows.map(casoDe);
  }

  async marcarAlertado(id: string, em: Date): Promise<void> {
    await this.#c.query(SQL_MARCAR_ALERTADO, [id, em]);
  }

  async pagina(filtro: FiltroDaFila, limite: number, depoisDe: number): Promise<readonly CasoDeRevisao[]> {
    return (
      await this.#c.query<Linha>(SQL_PAGINA, [filtro.tipo ?? null, filtro.estado ?? null, limite, depoisDe])
    ).rows.map(casoDe);
  }
}

/**
 * O `audit_log` pela `platform.audit_append`. O `payload_hash` é o SHA-256 do
 * detalhe: o que se prova sem o guardar — o motivo da recusa, o campo revelado.
 */
export class AuditoriaSql implements Auditoria {
  readonly #c: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#c = cliente;
  }

  async registar(r: RegistoDeAuditoria): Promise<void> {
    await this.#c.query(SQL_AUDITAR, [
      r.tenantId,
      r.actorId,
      r.accao,
      r.entidade,
      r.entidadeId,
      createHash("sha256").update(r.detalhe, "utf8").digest(),
    ]);
  }
}
