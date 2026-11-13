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
  EfeitosPorReaplicar,
  EstadoDoCaso,
  Evidencia,
  FiltroDaFila,
  OnboardingDaRevisao,
  OnboardingsDaRevisao,
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
 * Um conjunto de ligações (o `pg.Pool`): responde a consultas soltas e empresta
 * uma ligação **dedicada** para uma transacção. O trinco da quota precisa da
 * segunda — um `BEGIN` mandado ao conjunto ia para uma ligação e o resto da
 * transacção para outras.
 */
export interface ConjuntoSql extends ClienteSql {
  connect(): Promise<ClienteSql & { release(erro?: Error | boolean): void }>;
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

/**
 * A transição que reinicia o prazo e o alerta: a saída da triagem (com a
 * entrada na fila nova, `$4`) e a abertura do recurso (com `$4` nulo, que
 * mantém a entrada — a primeira decisão mede-se a partir dela).
 */
export const SQL_TRANSITAR_COM_SLA = `UPDATE platform.review_case
  SET estado = $3, fila_at = coalesce($4, fila_at), sla_alerta_at = $5, sla_due_at = $6, sla_alertado_at = NULL
  WHERE id = $1 AND estado = $2 RETURNING id`;

/**
 * Um envio repetido sobre um caso pendente. A prioridade só fica **mais**
 * urgente — `least` aqui, e o *trigger* da `0048` recusa o contrário a quem
 * escreva sem esta instrução.
 */
export const SQL_REFORCAR = `UPDATE platform.review_case
  SET prioridade = least(prioridade, $2), motivo_interno = $3, evidencias = $4::jsonb, recomendacao = $5
  WHERE id = $1
    AND estado IN ('em_triagem_automatica', 'aberto', 'em_analise', 'escalado', 'recurso_aberto')
  RETURNING id`;

/** O `tenant_id` lê-se do caso, na mesma instrução: a FK composta prende os dois. */
export const SQL_REGISTAR_DECISAO = `INSERT INTO platform.review_decision_log
  (case_id, tenant_id, revisor_id, decisao, instancia, regra, nota_enc)
  SELECT r.id, r.tenant_id, $2, $3, $4, $5, $6 FROM platform.review_case r WHERE r.id = $1
  RETURNING id, case_id, revisor_id, decisao, instancia, regra, nota_enc, em`;

export const SQL_DECISOES = `SELECT id, case_id, revisor_id, decisao, instancia, regra, nota_enc, em
  FROM platform.review_decision_log WHERE case_id = $1 ORDER BY em, id`;

export const SQL_CASOS_DO_ONBOARDING = `SELECT id, tipo, onboarding_id, tenant_id, motivo_codigo, motivo_interno, motivo_publico,
  evidencias, recomendacao, estado, prioridade, fila_at, sla_alerta_at, sla_due_at, sla_alertado_at, criado_at FROM platform.review_case
  WHERE onboarding_id = $1 ORDER BY criado_at, id`;

/**
 * A quota: casos **deste** dia que entraram na vista humana vindos da mesma
 * origem — o `ip_prefix_hash` do onboarding, ou o `device_hash` na falta dele.
 * Uma origem nula conta com as outras nulas: não ter origem não dá quota
 * própria.
 *
 * A contagem e a escrita que ela decide correm dentro do trinco da chave
 * (`SQL_TRINCO_DA_QUOTA`, `RevisaoSql.emTrinco`, KAM-198): duas aberturas
 * concorrentes da mesma origem, mesmo em processos diferentes, não passam as
 * duas no limite.
 */
export const SQL_CONTAR_NA_FILA = `SELECT count(*)::int AS n
  FROM platform.review_case r JOIN platform.onboarding_case c ON c.id = r.onboarding_id
  WHERE coalesce(c.ip_prefix_hash, c.device_hash) IS NOT DISTINCT FROM $1::bytea
    AND r.estado <> 'em_triagem_automatica' AND r.fila_at >= $2`;

/** A quota de um tenant para os casos sem onboarding, fora as auditorias. */
export const SQL_CONTAR_NA_FILA_DO_TENANT = `SELECT count(*)::int AS n FROM platform.review_case
  WHERE tenant_id = $1 AND onboarding_id IS NULL AND tipo <> 'auditoria'
    AND estado <> 'em_triagem_automatica' AND fila_at >= $2`;

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

/**
 * O trinco da quota entre processos (KAM-198). **Dentro** de uma transacção: o
 * `pg_advisory_xact_lock` larga-se no `COMMIT`, e fora de uma transacção cada
 * instrução é a sua e o trinco larga-se na seguinte — o mesmo que não existir.
 *
 * **A forma de dois argumentos, e não a de um `bigint`.** O primeiro é o espaço
 * desta fila (`ESPACO_DO_TRINCO_DA_QUOTA`) e o segundo o `hashtext` da chave da
 * quota (`o:<origem>`, `t:<tenant>`). As duas formas são espaços de chaves que o
 * PostgreSQL não sobrepõe, pelo que nenhum `hashtextextended` dos trincos de
 * conversa (`../modos/consultas.ts`) nem o `7101` do publicador colidem com
 * este. Duas origens com o mesmo `hashtext` partilham o trinco: serializam-se
 * sem necessidade, e a contagem continua a ser a de cada uma.
 */
export const SQL_TRINCO_DA_QUOTA = `SELECT pg_advisory_xact_lock($1::int, hashtext($2::text))`;

/** O espaço do trinco da quota na forma de dois argumentos. O número do ticket. */
export const ESPACO_DO_TRINCO_DA_QUOTA = 7198;

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

/** O trinco da quota pedido a uma ligação solta, que não segura transacção nenhuma. */
export class TrincoSemConjuntoError extends Error {
  override readonly name = "TrincoSemConjuntoError";

  constructor() {
    super("o trinco da quota precisa de um conjunto de ligacoes (pg.Pool): uma ligacao solta nao segura a transaccao");
  }
}

export class RevisaoSql implements RepositorioDeRevisao {
  readonly #c: ClienteSql;
  readonly #conjunto: ConjuntoSql | null;

  /**
   * Com `conjunto`, o `emTrinco` empresta dele uma ligação dedicada para a
   * transacção do trinco; sem ele, recusa-o (`TrincoSemConjuntoError`) em vez de
   * abrir um `BEGIN` numa ligação que outras consultas partilham. **Explícito, e
   * não adivinhado pelo `connect`**: um `pg.Client` também tem `connect`, e
   * chamá-lo outra vez numa ligação aberta falha.
   */
  constructor(cliente: ClienteSql, opcoes: { readonly conjunto?: ConjuntoSql } = {}) {
    this.#c = cliente;
    this.#conjunto = opcoes.conjunto ?? null;
  }

  /**
   * A contagem e a escrita de uma abertura (ou de uma drenagem) com a chave da
   * quota trancada **entre processos** (KAM-198, critério 5). O `trabalho` corre
   * sobre um `RevisaoSql` da ligação emprestada, dentro da transacção que segura
   * o trinco; um erro reverte-a e devolve a ligação.
   */
  async emTrinco<T>(chave: string, trabalho: (repositorio: RepositorioDeRevisao) => Promise<T>): Promise<T> {
    if (this.#conjunto === null) throw new TrincoSemConjuntoError();
    const ligacao = await this.#conjunto.connect();
    let partida: Error | undefined;
    try {
      await ligacao.query("BEGIN");
      try {
        await ligacao.query(SQL_TRINCO_DA_QUOTA, [ESPACO_DO_TRINCO_DA_QUOTA, chave]);
        const resultado = await trabalho(new RevisaoSql(ligacao));
        await ligacao.query("COMMIT");
        return resultado;
      } catch (erro) {
        try {
          await ligacao.query("ROLLBACK");
        } catch (falhou) {
          // Uma ligação que nem reverte não volta ao conjunto: devolvê-la
          // deixava a transacção aberta à espera do próximo que a emprestasse.
          partida = falhou instanceof Error ? falhou : new Error("rollback falhou");
        }
        throw erro;
      }
    } finally {
      ligacao.release(partida);
    }
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
            sla.filaEm ?? null,
            sla.slaAlertaAt,
            sla.slaDueAt,
          ]);
    return r.rows.length === 1;
  }

  async reforcar(
    id: string,
    r: { prioridade: number; motivoInterno: string; evidencias: readonly Evidencia[]; recomendacao: CasoDeRevisao["recomendacao"] },
  ): Promise<boolean> {
    const q = await this.#c.query(SQL_REFORCAR, [id, r.prioridade, r.motivoInterno, JSON.stringify(r.evidencias), r.recomendacao]);
    return q.rows.length === 1;
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

  async casosDoOnboarding(onboardingId: string): Promise<readonly CasoDeRevisao[]> {
    return (await this.#c.query<Linha>(SQL_CASOS_DO_ONBOARDING, [onboardingId])).rows.map(casoDe);
  }

  async contarNaFilaDoTenantDesde(tenantId: string, desde: Date): Promise<number> {
    const r = await this.#c.query<{ n: number }>(SQL_CONTAR_NA_FILA_DO_TENANT, [tenantId, desde]);
    return Number(r.rows[0]?.n ?? 0);
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
 * Os onboardings que a fila lê e cuja fase muda (KAM-198), sobre a
 * `platform.onboarding_case` da `0043`. Corre como `kamba_batch`, que tem
 * `SELECT` e `UPDATE (fase, …)` nela (`db/kyc.py`): a fila atravessa tenants, e
 * um onboarding de outro tenant é o que ela lê por natureza.
 *
 * Os quatro *hashes* saem em hexadecimal, que é a forma da porta: a quota
 * devolve-os à base com `Buffer.from(origem, "hex")`.
 */
export const SQL_ONBOARDING_POR_ID = `SELECT id, tenant_id, fase, fase_at, ip_prefix_hash, device_hash, nif_hmac, phone_hmac
  FROM platform.onboarding_case WHERE id = $1`;

export const SQL_ONBOARDING_POR_TENANT = `SELECT id, tenant_id, fase, fase_at, ip_prefix_hash, device_hash, nif_hmac, phone_hmac
  FROM platform.onboarding_case WHERE tenant_id = $1`;

/** O `fase_at` mantém-no o *trigger* da `0043`. */
export const SQL_MARCAR_FASE = `UPDATE platform.onboarding_case SET fase = $2 WHERE id = $1 RETURNING id`;

interface LinhaDoOnboarding {
  id: string;
  tenant_id: string;
  fase: string;
  fase_at: Date;
  ip_prefix_hash: Uint8Array | null;
  device_hash: Uint8Array | null;
  nif_hmac: Uint8Array;
  phone_hmac: Uint8Array;
}

const hex = (v: Uint8Array): string => Buffer.from(v).toString("hex");

function onboardingDe(l: LinhaDoOnboarding): OnboardingDaRevisao {
  return {
    id: l.id,
    tenantId: l.tenant_id,
    fase: l.fase,
    redeHmac: l.ip_prefix_hash === null ? null : hex(l.ip_prefix_hash),
    dispositivoHmac: l.device_hash === null ? null : hex(l.device_hash),
    nifHmac: hex(l.nif_hmac),
    telefoneHmac: hex(l.phone_hmac),
    faseEm: l.fase_at instanceof Date ? l.fase_at : new Date(l.fase_at),
  };
}

export class OnboardingsSql implements OnboardingsDaRevisao {
  readonly #c: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#c = cliente;
  }

  async porId(id: string): Promise<OnboardingDaRevisao | null> {
    const r = await this.#c.query<LinhaDoOnboarding>(SQL_ONBOARDING_POR_ID, [id]);
    return r.rows[0] === undefined ? null : onboardingDe(r.rows[0]);
  }

  async porTenant(tenantId: string): Promise<OnboardingDaRevisao | null> {
    const r = await this.#c.query<LinhaDoOnboarding>(SQL_ONBOARDING_POR_TENANT, [tenantId]);
    return r.rows[0] === undefined ? null : onboardingDe(r.rows[0]);
  }

  async marcarFase(id: string, fase: "aprovado" | "rejeitado" | "kyc_pendente"): Promise<boolean> {
    return (await this.#c.query(SQL_MARCAR_FASE, [id, fase])).rows.length === 1;
  }
}

/**
 * A marca de «efeito por aplicar» de um caso (KAM-198, revisão `0053`). O
 * `kamba_batch` tem `UPDATE` só desta coluna.
 *
 * **Marcar renova o instante, e resolver só limpa o instante que leu.** Dois
 * processos tocam na mesma marca: o que decide (marca, corre os efeitos,
 * resolve) e o lote (lê os pendentes, reaplica, resolve). Se o lote reaplicasse
 * uma decisão antiga enquanto uma nova marcava e falhava, um `resolver`
 * incondicional apagava a marca nova — e o efeito novo perdia-se. Com a
 * comparação, o `resolver` do lote não encontra a linha e a marca nova fica.
 *
 * O instante viaja como **texto** e não como `Date`: a coluna tem microssegundos
 * e o `Date` do JavaScript tem milissegundos, pelo que um `Date` relido nunca
 * era igual ao que está na base. Um caso cuja marca este processo não leu
 * limpa-se sem comparar (`$2` nulo).
 *
 * **E os pendentes só aparecem depois de uma carência** (`$2` do
 * `SQL_EFEITOS_PENDENTES`, dois minutos por omissão): quem decide marca
 * **antes** de correr os efeitos, e sem carência o lote via a marca e corria os
 * mesmos efeitos em paralelo — e o aviso, que não é idempotente, saía duas
 * vezes (achado 3 da revisão adversarial). Uma reaplicação que falha remarca o
 * caso, pelo que a carência é também o intervalo entre tentativas.
 */
export const SQL_MARCAR_EFEITO = `UPDATE platform.review_case SET efeito_pendente_at = clock_timestamp()
  WHERE id = $1 RETURNING efeito_pendente_at::text AS marca`;

export const SQL_EFEITOS_PENDENTES = `SELECT id, efeito_pendente_at::text AS marca FROM platform.review_case
  WHERE efeito_pendente_at IS NOT NULL
    AND efeito_pendente_at <= clock_timestamp() - make_interval(secs => $2::double precision)
  ORDER BY efeito_pendente_at, id LIMIT $1`;

/** A carência por omissão entre a marca e o lote a ver o caso. */
export const CARENCIA_DOS_EFEITOS_MS = 120_000;

/** Com `$2` nulo (uma marca que este processo não leu), limpa sem comparar. */
export const SQL_RESOLVER_EFEITO = `UPDATE platform.review_case SET efeito_pendente_at = NULL
  WHERE id = $1 AND ($2::text IS NULL OR efeito_pendente_at = $2::timestamptz)`;

export class EfeitosPorReaplicarSql implements EfeitosPorReaplicar {
  readonly #c: ClienteSql;
  /** A marca que este processo escreveu ou leu, por caso: é a que o `resolver` limpa. */
  readonly #marcas = new Map<string, string>();
  readonly #carenciaMs: number;

  constructor(cliente: ClienteSql, opcoes: { readonly carenciaMs?: number } = {}) {
    this.#c = cliente;
    this.#carenciaMs = opcoes.carenciaMs ?? CARENCIA_DOS_EFEITOS_MS;
  }

  async marcar(casoId: string): Promise<void> {
    const r = await this.#c.query<{ marca: string }>(SQL_MARCAR_EFEITO, [casoId]);
    if (r.rows[0] !== undefined) this.#marcas.set(casoId, r.rows[0].marca);
  }

  async pendentes(limite: number): Promise<readonly string[]> {
    const r = await this.#c.query<{ id: string; marca: string }>(SQL_EFEITOS_PENDENTES, [
      limite,
      this.#carenciaMs / 1000,
    ]);
    for (const l of r.rows) this.#marcas.set(l.id, l.marca);
    return r.rows.map((l) => l.id);
  }

  async resolver(casoId: string): Promise<void> {
    const marca = this.#marcas.get(casoId) ?? null;
    await this.#c.query(SQL_RESOLVER_EFEITO, [casoId, marca]);
    this.#marcas.delete(casoId);
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

  async gravar(r: RegistoDeAuditoria): Promise<void> {
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
