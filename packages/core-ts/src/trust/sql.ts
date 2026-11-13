/**
 * O adaptador PostgreSQL de Trust & Safety (KAM-097).
 *
 * As consultas são constantes **literais** exportadas: a suite de base de dados
 * (`db/tests/test_trust_schema.py`) executa estas cadeias pela
 * `ConsultaDoTypeScript`, e não uma cópia delas — e um `${...}` dentro de uma
 * delas chegava ao PostgreSQL tal e qual (a armadilha do KAM-089).
 *
 * ## Dois papéis, e o que cada um lê
 *
 * * **`kamba_app`** — o consumidor de eventos. Corre na transacção do
 *   `consumir`, com o `app.tenant_id` do envelope, e lê só o seu tenant. Na
 *   `ts_signal` e na `ts_sanction` lê **as colunas que a escada precisa** e não
 *   o motivo interno, a regra, os sinais nem o `detalhe` (revisão `0053`): por
 *   isso o modo `app` devolve esses campos vazios.
 * * **`kamba_batch`** — a fila de revisão e as varreduras. Lê tudo, e é o único
 *   que muda o estado do tenant (`0007`).
 */

import type { ClienteSql } from "../eventos/publicador.ts";
import type {
  DesfechoDoRecurso,
  EstadoDosTenants,
  Independencia,
  MotivoPublicoDaSancao,
  Origem,
  RepositorioDeTrust,
  SancaoGravada,
  SancaoNova,
  SinalGravado,
  SinalNovo,
} from "./contrato.ts";
import { SEVERIDADE_DO_TIPO, type Passo, type Severidade, type TipoDeSinal } from "./regras.ts";

export type { ClienteSql };

/** Grava um sinal; zero linhas quando a chave já existe. */
export const SQL_GRAVAR_SINAL = `
  INSERT INTO platform.ts_signal (tenant_id, tipo, severidade, ref_evento, detalhe, ocorrido_em)
  VALUES ($1, $2, $3, $4, $5::jsonb, $6)
  ON CONFLICT (tenant_id, tipo, ref_evento) DO NOTHING
  RETURNING id::text AS id
`;

/** O sinal que já tinha a chave. Só colunas que o `kamba_app` lê. */
export const SQL_SINAL_POR_CHAVE = `
  SELECT id::text AS id, ocorrido_em
    FROM platform.ts_signal
   WHERE tenant_id = $1 AND tipo = $2 AND ref_evento = $3
`;

/** Os sinais de um tenant, para o risco. Ordem total, para a resposta não depender do plano. */
export const SQL_SINAIS_DO_TENANT = `
  SELECT id::text AS id, tipo, severidade, ref_evento::text AS ref_evento, ocorrido_em
    FROM platform.ts_signal
   WHERE tenant_id = $1
   ORDER BY ocorrido_em, id
`;

export const SQL_GRAVAR_SANCAO = `
  INSERT INTO platform.ts_sanction
    (tenant_id, chave, passo, origem, motivo_interno, motivo_publico, autor, regra, sinais,
     case_id, justificacao_salto, recurso_de, recurso_estado)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13)
  ON CONFLICT (tenant_id, chave) DO NOTHING
  RETURNING id::text AS id, em
`;

/** As sanções de um tenant, com as colunas que o `kamba_app` lê. */
export const SQL_SANCOES_DO_TENANT_APP = `
  SELECT id::text AS id, tenant_id::text AS tenant_id, chave, passo, origem, motivo_publico,
         recurso_de::text AS recurso_de, recurso_estado, em
    FROM platform.ts_sanction
   WHERE tenant_id = $1
   ORDER BY em, id
`;

/** As sanções de um tenant, inteiras. Só o lote. */
export const SQL_SANCOES_DO_TENANT_LOTE = `
  SELECT id::text AS id, tenant_id::text AS tenant_id, chave, passo, origem, motivo_interno,
         motivo_publico, autor, regra, sinais, case_id::text AS case_id, justificacao_salto,
         recurso_de::text AS recurso_de, recurso_estado, em
    FROM platform.ts_sanction
   WHERE tenant_id = $1
   ORDER BY em, id
`;

/**
 * Os encerramentos cujo prazo de recurso passou: passo `encerramento`, sem
 * desfecho de recurso, e com o caso ainda em `decidido` — um caso em
 * `recurso_aberto` está a ser recorrido e não fecha.
 */
export const SQL_ENCERRAMENTOS_POR_FECHAR = `
  SELECT s.id::text AS id, s.tenant_id::text AS tenant_id, s.chave, s.passo, s.origem,
         s.motivo_interno, s.motivo_publico, s.autor, s.regra, s.sinais,
         s.case_id::text AS case_id, s.justificacao_salto, s.recurso_de::text AS recurso_de,
         s.recurso_estado, s.em
    FROM platform.ts_sanction s
    JOIN platform.review_case c ON c.id = s.case_id AND c.tenant_id = s.tenant_id
   WHERE s.passo = 'encerramento' AND s.recurso_de IS NULL AND s.em <= $1
     AND c.estado = 'decidido'
     AND NOT EXISTS (SELECT 1 FROM platform.ts_sanction r
                      WHERE r.tenant_id = s.tenant_id AND r.recurso_de = s.id)
   ORDER BY s.em, s.id
   LIMIT 500
`;

export const SQL_ESTADO_DO_TENANT = `
  SELECT estado FROM platform.tenants WHERE id = $1
`;

/** O CAS do estado do tenant. Só o `kamba_batch` tem `UPDATE` no `estado` (`0007`). */
export const SQL_TRANSITAR_TENANT = `
  UPDATE platform.tenants SET estado = $3
   WHERE id = $1 AND estado = ANY ($2::text[])
  RETURNING id
`;

/**
 * A independência de um pedido, como o KAM-096 a lê. **Fail-closed**: sem o
 * `order.paid` consumido por este consumidor, o pedido está `por_avaliar` e
 * não conta. Avaliado e sem sinal de auto-compra, é independente.
 */
export const SQL_INDEPENDENCIA = `
  SELECT
    EXISTS (SELECT 1 FROM platform.ts_signal s
             WHERE s.tenant_id = $1 AND s.tipo = 'auto_compra'
               AND s.ref_evento = CAST($2::text AS uuid)) AS auto,
    EXISTS (SELECT 1 FROM platform.events_consumed c
              JOIN platform.events_log l ON l.event_id = c.event_id AND l.tenant_id = c.tenant_id
             WHERE c.consumer = $3 AND c.tenant_id = $1 AND c.agregado_tipo = 'order'
               AND c.agregado_id = $2::text AND l.tipo = 'order.paid') AS avaliado
`;

// ------------------------------------------------------- factos do consumidor

/**
 * Os contactos que são o dono neste tenant: o `owner_contact_id` e os
 * confirmadores com papel `dono` activos (KAM-054), cada um levado ao seu
 * contacto **canónico** pela cadeia de fusões (`merged_into`). É a resolução de
 * identidade (KAM-008) que junta o mesmo telefone em formatos diferentes, e o
 * mesmo BSUID, no mesmo contacto: comparar o canónico é comparar os HMAC sem os
 * ler — o `kamba_app` não tem `SELECT` no `phone_hmac` nem no `bsuid_hmac`.
 */
export const SQL_CONTACTOS_DO_DONO = `
  WITH RECURSIVE dono(contact_id) AS (
      SELECT t.owner_contact_id FROM platform.tenants t
       WHERE t.id = $1 AND t.owner_contact_id IS NOT NULL
      UNION
      SELECT pc.contact_id FROM platform.payment_confirmers pc
       WHERE pc.tenant_id = $1 AND pc.papel = 'dono' AND pc.ativo
    ), cadeia(origem, actual, passos) AS (
      SELECT d.contact_id, d.contact_id, 0 FROM dono d
      UNION ALL
      SELECT k.origem, c.merged_into, k.passos + 1
        FROM cadeia k
        JOIN platform.contacts c ON c.tenant_id = $1 AND c.contact_id = k.actual
       WHERE c.merged_into IS NOT NULL AND k.passos < 8
    )
  SELECT DISTINCT actual::text AS contact_id FROM cadeia
`;

/** O contacto canónico de um contacto (a mesma cadeia), e o pedido de que ele é comprador. */
export const SQL_PEDIDO_E_COMPRADOR = `
  WITH RECURSIVE cadeia(actual, passos) AS (
      SELECT o.contact_id, 0 FROM platform.orders_mirror o WHERE o.tenant_id = $1 AND o.id = $2
      UNION ALL
      SELECT c.merged_into, k.passos + 1
        FROM cadeia k
        JOIN platform.contacts c ON c.tenant_id = $1 AND c.contact_id = k.actual
       WHERE c.merged_into IS NOT NULL AND k.passos < 8
    )
  SELECT o.id::text AS order_id, o.total_minor, o.paga_via, o.criado_at, o.paga_at,
         array(SELECT k.actual::text FROM cadeia k) AS contactos
    FROM platform.orders_mirror o
   WHERE o.tenant_id = $1 AND o.id = $2
`;

/** A activação e o tecto por pedido do tenant (o menor dos entitlements activos). */
export const SQL_TENANT_E_TECTO = `
  SELECT t.primeira_activacao_at,
         (SELECT min((e.limites ->> 'valor_max_pedido_minor')::bigint)
            FROM platform.entitlements e
           WHERE e.tenant_id = $1 AND e.ativo AND e.limites ? 'valor_max_pedido_minor') AS tecto
    FROM platform.tenants t
   WHERE t.id = $1
`;

/** Os pedidos pagos por confirmação manual desde um instante. */
export const SQL_PEDIDOS_MANUAIS = `
  SELECT id::text AS order_id, total_minor, criado_at, paga_at
    FROM platform.orders_mirror
   WHERE tenant_id = $1 AND paga_via = 'manual_auditado' AND paga_at IS NOT NULL
     AND criado_at >= $2
   ORDER BY criado_at, id
`;

/**
 * As queixas e disputas da janela, com o contacto de quem as fez: o
 * `query.handoff` de motivo `reclamacao_grave` (o contacto é o da conversa do
 * agregado) e cada passagem de uma encomenda a `em_disputa`. Mais os
 * compradores pagos do tenant, que são os únicos cujas queixas contam.
 */
export const SQL_QUEIXAS = `
  SELECT cv.contact_id::text AS contact_id, l.ocorrido_em AS em
    FROM platform.events_log l
    JOIN platform.conversations cv ON cv.tenant_id = l.tenant_id AND cv.id::text = l.agregado_id
   WHERE l.tenant_id = $1 AND l.tipo = 'query.handoff' AND l.ocorrido_em >= $2
     AND l.envelope -> 'payload' ->> 'motivo' = 'reclamacao_grave'
  UNION ALL
  SELECT o.contact_id::text AS contact_id, s.em
    FROM platform.order_state_log s
    JOIN platform.orders_mirror o ON o.tenant_id = s.tenant_id AND o.id = s.order_id
   WHERE s.tenant_id = $1 AND s.para = 'em_disputa' AND s.em >= $2
`;

export const SQL_COMPRADORES_PAGOS = `
  SELECT DISTINCT contact_id::text AS contact_id
    FROM platform.orders_mirror
   WHERE tenant_id = $1 AND paga_at IS NOT NULL
`;

// ------------------------------------------------------------- varreduras (lote)

/**
 * Encomendas `paga` sem entrega há mais de N dias, de todos os tenants, **que
 * ainda não têm o sinal**: sem isso as já sinalizadas ocupavam a cabeça do
 * `LIMIT` para sempre, e as novas nunca chegavam a ser lidas (achado 11). A
 * foto repetida, pela mesma razão.
 */
export const SQL_NAO_ENTREGUES = `
  SELECT o.tenant_id::text AS tenant_id, o.id::text AS order_id, o.paga_at
    FROM platform.orders_mirror o
   WHERE o.estado = 'paga' AND o.entregue_at IS NULL AND o.paga_at < $1
     AND NOT EXISTS (SELECT 1 FROM platform.ts_signal s
                      WHERE s.tenant_id = o.tenant_id AND s.tipo = 'nao_entrega'
                        AND s.ref_evento = o.id)
   ORDER BY o.paga_at, o.id
   LIMIT 1000
`;

/**
 * As fotos de um tenant cujo *phash* coincide **exactamente** com o de outro
 * tenant — a correlação entre tenants que o bloco manda fazer só por papel
 * auditado e só como sinal. Devolve a ingestão **deste** tenant e quantas
 * alheias coincidem; nunca qual nem de quem. «Repetido» é o *phash* igual, a
 * mesma leitura do critério 2 do KAM-049.
 */
export const SQL_FOTOS_REPETIDAS = `
  SELECT a.tenant_id::text AS tenant_id, a.id::text AS ingestao_id, count(*)::int AS contagem
    FROM platform.catalog_ingestions a
    JOIN platform.catalog_ingestions b ON b.phash = a.phash AND b.tenant_id <> a.tenant_id
   WHERE a.phash IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM platform.ts_signal s
                      WHERE s.tenant_id = a.tenant_id AND s.tipo = 'foto_repetida'
                        AND s.ref_evento = a.id)
   GROUP BY a.tenant_id, a.id
   ORDER BY a.tenant_id, a.id
   LIMIT 1000
`;

// ------------------------------------------------------------------ adaptadores

type Linha = Record<string, unknown>;

function data(v: unknown): Date {
  return v instanceof Date ? v : new Date(String(v));
}

function textoOuNulo(v: unknown): string | null {
  return v === null || v === undefined ? null : String(v);
}

/** Os modos de leitura: o do consumidor (colunas restritas) e o do lote. */
export type ModoDoRepositorio = "app" | "lote";

export class RepositorioDeTrustSql implements RepositorioDeTrust {
  readonly #bd: ClienteSql;
  readonly #modo: ModoDoRepositorio;

  constructor(bd: ClienteSql, modo: ModoDoRepositorio) {
    this.#bd = bd;
    this.#modo = modo;
  }

  async gravarSinal(s: SinalNovo): Promise<{ readonly sinal: SinalGravado; readonly repetido: boolean }> {
    const severidade = SEVERIDADE_DO_TIPO[s.tipo];
    const r = await this.#bd.query(SQL_GRAVAR_SINAL, [
      s.tenantId,
      s.tipo,
      severidade,
      s.refEvento,
      JSON.stringify(s.detalhe),
      s.ocorridoEm,
    ]);
    const nova = r.rows[0];
    if (nova !== undefined) return { sinal: { ...s, id: String(nova["id"]), severidade }, repetido: false };
    const e = (await this.#bd.query(SQL_SINAL_POR_CHAVE, [s.tenantId, s.tipo, s.refEvento])).rows[0];
    if (e === undefined) throw new Error("ts_signal: conflito sem linha");
    return { sinal: { ...s, id: String(e["id"]), severidade, ocorridoEm: data(e["ocorrido_em"]) }, repetido: true };
  }

  async sinaisDoTenant(tenantId: string): Promise<readonly SinalGravado[]> {
    const r = await this.#bd.query(SQL_SINAIS_DO_TENANT, [tenantId]);
    return r.rows.map((l: Linha) => ({
      id: String(l["id"]),
      tenantId,
      tipo: l["tipo"] as TipoDeSinal,
      severidade: l["severidade"] as Severidade,
      refEvento: String(l["ref_evento"]),
      detalhe: {},
      ocorridoEm: data(l["ocorrido_em"]),
    }));
  }

  async gravarSancao(s: SancaoNova): Promise<{ readonly sancao: SancaoGravada; readonly repetido: boolean }> {
    const r = await this.#bd.query(SQL_GRAVAR_SANCAO, [
      s.tenantId,
      s.chave,
      s.passo,
      s.origem,
      s.motivoInterno,
      s.motivoPublico,
      s.autor,
      s.regra,
      JSON.stringify(s.sinais),
      s.casoId,
      s.justificacaoDoSalto,
      s.recursoDe,
      s.recursoEstado,
    ]);
    const nova = r.rows[0];
    if (nova !== undefined) return { sancao: { ...s, id: String(nova["id"]), em: data(nova["em"]) }, repetido: false };
    const e = (await this.sancoesDoTenant(s.tenantId)).find((x) => x.chave === s.chave);
    if (e === undefined) throw new Error("ts_sanction: conflito sem linha");
    return { sancao: e, repetido: true };
  }

  async sancoesDoTenant(tenantId: string): Promise<readonly SancaoGravada[]> {
    const lote = this.#modo === "lote";
    const r = await this.#bd.query(lote ? SQL_SANCOES_DO_TENANT_LOTE : SQL_SANCOES_DO_TENANT_APP, [tenantId]);
    return r.rows.map((l: Linha) => sancaoDaLinha(l, lote));
  }

  /** Para o `fecharEncerramentos`. Só no modo do lote. */
  async encerramentosPorFechar(ate: Date): Promise<readonly SancaoGravada[]> {
    if (this.#modo !== "lote") throw new Error("so o lote fecha encerramentos");
    return (await this.#bd.query(SQL_ENCERRAMENTOS_POR_FECHAR, [ate])).rows.map((l: Linha) => sancaoDaLinha(l, true));
  }

  /** A independência de um pedido (KAM-096). `consumer` é o nome deste consumidor. */
  async independencia(tenantId: string, orderId: string, consumer: string): Promise<Independencia> {
    const l = (await this.#bd.query(SQL_INDEPENDENCIA, [tenantId, orderId, consumer])).rows[0];
    if (l === undefined || l["avaliado"] !== true) return "por_avaliar";
    return l["auto"] === true ? "nao_independente" : "independente";
  }
}

function sancaoDaLinha(l: Linha, lote: boolean): SancaoGravada {
  const sinais = lote && Array.isArray(l["sinais"]) ? (l["sinais"] as unknown[]).map(String) : [];
  return {
    id: String(l["id"]),
    tenantId: String(l["tenant_id"]),
    chave: String(l["chave"]),
    passo: l["passo"] as Passo,
    origem: l["origem"] as Origem,
    motivoInterno: lote ? String(l["motivo_interno"]) : "",
    motivoPublico: l["motivo_publico"] as MotivoPublicoDaSancao,
    autor: lote ? String(l["autor"]) : "",
    regra: lote ? textoOuNulo(l["regra"]) : null,
    sinais,
    casoId: lote ? textoOuNulo(l["case_id"]) : null,
    justificacaoDoSalto: lote ? textoOuNulo(l["justificacao_salto"]) : null,
    recursoDe: textoOuNulo(l["recurso_de"]),
    recursoEstado: textoOuNulo(l["recurso_estado"]) as DesfechoDoRecurso | null,
    em: data(l["em"]),
  };
}

/** O estado do tenant pelo `kamba_batch`. */
export class EstadoDosTenantsSql implements EstadoDosTenants {
  readonly #bd: ClienteSql;
  constructor(bd: ClienteSql) {
    this.#bd = bd;
  }

  async estado(tenantId: string): Promise<string | null> {
    const l = (await this.#bd.query(SQL_ESTADO_DO_TENANT, [tenantId])).rows[0];
    return l === undefined ? null : String(l["estado"]);
  }

  async transitar(tenantId: string, de: readonly string[], para: string): Promise<boolean> {
    const r = await this.#bd.query(SQL_TRANSITAR_TENANT, [tenantId, [...de], para]);
    return r.rows.length === 1;
  }
}
