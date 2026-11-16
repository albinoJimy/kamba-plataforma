/**
 * Os adaptadores SQL da activação (KAM-094).
 *
 *     CatalogoSql.produtos   a `offer_terms` com a ingestão confirmada do
 *                            KAM-049 (`catalog_ingestions` em `publicada`)
 *     CategoriaSql           a categoria declarada, como o `SQL_POR_REANALISAR`
 *     GatesSql               o `onboarding_gate` e o `onboarding_gates_em_falta`
 *     MaquinaSql             o `advance_case` do KAM-092
 *     RegistoDoTesteSql      as tentativas na `onboarding_smoke` (revisão do
 *                            catálogo mínimo)
 *     MarcadorSql            a `conversations.is_test`
 *
 * **Dois papéis, com o `app.tenant_id` do caso posto por quem os monta.** As
 * leituras do catálogo e da categoria correm pela ligação da aplicação
 * (`comTenant`): o `kamba_batch` não lê a `catalog_ingestions` (revisão do
 * Catálogo AI). Os gates, a máquina, o fecho das tentativas e a marca
 * `is_test` correm como `kamba_batch` (`comBatch`): o `onboarding_gate` só o
 * lote o escreve, e o `advance_case` recusa fora do contexto do tenant do caso.
 *
 * **As escritas na oferta não estão aqui.** Publicar, retirar e renomear uma
 * oferta é do COM (`publishProduct` com `OwnerConfirmation`, `audit_log` e o
 * `catalog.product_changed`); um segundo escritor da `offer_terms.estado` em
 * `core-ts` era um caminho sem auditoria nem evento. A porta
 * `CatalogoDoTenant` fica com o duplo, e o adaptador de escrita é credor: a
 * rota interna do COM que o processo de lote chame.
 */

import type { ClienteSql } from "../screening/sql.ts";
import type {
  CasoDeActivacao,
  CausaDoTeste,
  MarcadorDeTeste,
  RegistoDoTeste,
  TentativaDoTeste,
  CategoriaDoTenant,
  FaseDoCaso,
  GateDeActivacao,
  GateDoKam094,
  GatesDaActivacao,
  MaquinaDoCaso,
  PrecoTipo,
  EstadoDaOferta,
  ProdutoDoCatalogo,
} from "./contrato.ts";

/**
 * Os produtos do tenant, com a confirmação e a categoria da ingestão.
 *
 * O `tenant_id = $1` não é redundante com a RLS: o `kamba_batch` não tem RLS
 * por tenant em todas as tabelas, e o predicado é a barreira que não depende
 * do papel.
 */
export const SQL_PRODUTOS = `
SELECT o.tenant_id::text AS tenant_id, o.sku, o.nome, o.preco_tipo, o.estado,
       o.categoria_restrita, o.deleted_at IS NOT NULL AS apagado,
       i.categoria, i.sku IS NOT NULL AS confirmado
  FROM platform.offer_terms o
  LEFT JOIN LATERAL (
    SELECT c.sku, nullif(btrim(c.extraido -> 'categoria' ->> 'valor'), '') AS categoria
      FROM platform.catalog_ingestions c
     WHERE c.tenant_id = o.tenant_id AND c.sku = o.sku AND c.estado = 'publicada'
     ORDER BY c.confirmado_at DESC
     LIMIT 1) i ON true
 WHERE o.tenant_id = $1
 ORDER BY o.sku`;

export const SQL_CATEGORIA_DECLARADA = `
SELECT coalesce((SELECT c.sujeito_ref FROM platform.screening_decision c
                  WHERE c.tenant_id = $1 AND c.sujeito_tipo = 'categoria'
                  ORDER BY c.criado_at DESC, c.id DESC LIMIT 1), '') AS categoria`;

/** O `em` é do *trigger* da revisão 0058; a evidência é um identificador curto. */
export const SQL_MARCAR_GATE = `
INSERT INTO platform.onboarding_gate (onboarding_id, tenant_id, gate, ok, evidencia_ref)
SELECT c.id, c.tenant_id, $2, $3, $4 FROM platform.onboarding_case c WHERE c.id = $1
ON CONFLICT (onboarding_id, gate) DO UPDATE SET ok = EXCLUDED.ok, evidencia_ref = EXCLUDED.evidencia_ref`;

export const SQL_GATES_EM_FALTA = "SELECT platform.onboarding_gates_em_falta($1) AS em_falta";

export const SQL_LER_CASO = `
SELECT c.id::text AS onboarding_id, c.tenant_id::text AS tenant_id, c.fase
  FROM platform.onboarding_case c WHERE c.id = $1`;

export const SQL_AVANCAR = "SELECT platform.advance_case($1, $2, $3) AS fase";

/**
 * Abre uma tentativa. Corre como `kamba_app` (a página do dono): a aplicação
 * só tem `INSERT` nestas quatro colunas, e o `resultado` nasce `pendente`.
 */
export const SQL_INICIAR_TENTATIVA = `
INSERT INTO platform.onboarding_smoke (onboarding_id, tenant_id, iniciada_em, expira_em)
SELECT c.id, c.tenant_id, $2, $3 FROM platform.onboarding_case c WHERE c.id = $1
RETURNING onboarding_id::text AS onboarding_id, iniciada_em, expira_em, resultado, causa`;

export const SQL_TENTATIVA_CORRENTE = `
SELECT onboarding_id::text AS onboarding_id, iniciada_em, expira_em, resultado, causa
  FROM platform.onboarding_smoke
 WHERE onboarding_id = $1
 ORDER BY iniciada_em DESC, id DESC
 LIMIT 1`;

/** Fecha a tentativa corrente, se ainda estiver pendente. Corre como `kamba_batch`. */
export const SQL_FECHAR_TENTATIVA = `
UPDATE platform.onboarding_smoke
   SET resultado = $2, causa = $3, fechada_em = clock_timestamp()
 WHERE id = (SELECT s.id FROM platform.onboarding_smoke s WHERE s.onboarding_id = $1
              ORDER BY s.iniciada_em DESC, s.id DESC LIMIT 1)
   AND resultado = 'pendente'`;

/**
 * As falhas desde a última tentativa `ok` ou a última que levou o caso à fila.
 * Um `$1` só, pela CTE: um marcador repetido é o que a suite do gate 8 lê pior.
 */
export const SQL_FALHAS_SEGUIDAS = `
WITH t AS (SELECT resultado, levou_a_fila, iniciada_em FROM platform.onboarding_smoke
            WHERE onboarding_id = $1)
SELECT count(*)::int AS falhas FROM t
 WHERE t.resultado = 'falhou'
   AND t.iniciada_em > coalesce((SELECT max(b.iniciada_em) FROM t b
                                  WHERE b.resultado = 'ok' OR b.levou_a_fila), '-infinity')`;

/** Marca a falha corrente como a que abriu o `review_case`. Corre como `kamba_batch`. */
export const SQL_ZERAR_FALHAS = `
UPDATE platform.onboarding_smoke SET levou_a_fila = true
 WHERE id = (SELECT s.id FROM platform.onboarding_smoke s WHERE s.onboarding_id = $1
              ORDER BY s.iniciada_em DESC, s.id DESC LIMIT 1)
   AND resultado = 'falhou'`;

/** A conversa do teste sai das métricas. Corre como `kamba_batch`. */
export const SQL_MARCAR_CONVERSA_DE_TESTE = `
UPDATE platform.conversations SET is_test = true WHERE tenant_id = $1 AND id = $2`;

export class CatalogoSql {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async produtos(tenantId: string): Promise<readonly ProdutoDoCatalogo[]> {
    const { rows } = await this.#cliente.query<{
      tenant_id: string;
      sku: string;
      nome: string;
      preco_tipo: PrecoTipo | null;
      estado: EstadoDaOferta;
      categoria_restrita: string | null;
      apagado: boolean;
      categoria: string | null;
      confirmado: boolean;
    }>(SQL_PRODUTOS, [tenantId]);
    return rows.map((l) => ({
      tenantId: l.tenant_id,
      sku: l.sku,
      nome: l.nome,
      precoTipo: l.preco_tipo,
      estado: l.estado,
      categoriaRestrita: l.categoria_restrita,
      apagado: l.apagado,
      categoria: l.categoria,
      confirmadoPeloDono: l.confirmado,
    }));
  }
}

export class CategoriaSql implements CategoriaDoTenant {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async declarada(tenantId: string): Promise<string> {
    const { rows } = await this.#cliente.query<{ categoria: string }>(SQL_CATEGORIA_DECLARADA, [tenantId]);
    return rows[0]?.categoria ?? "";
  }
}

export class GatesSql implements GatesDaActivacao {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async marcar(onboardingId: string, gate: GateDoKam094, ok: boolean, evidencia: string): Promise<void> {
    await this.#cliente.query(SQL_MARCAR_GATE, [onboardingId, gate, ok, evidencia]);
  }

  async emFalta(onboardingId: string): Promise<readonly GateDeActivacao[]> {
    const { rows } = await this.#cliente.query<{ em_falta: GateDeActivacao[] }>(SQL_GATES_EM_FALTA, [onboardingId]);
    return rows[0]?.em_falta ?? [];
  }
}

type LinhaDaTentativa = {
  onboarding_id: string;
  iniciada_em: Date;
  expira_em: Date;
  resultado: TentativaDoTeste["resultado"];
  causa: CausaDoTeste | null;
};

function tentativa(l: LinhaDaTentativa): TentativaDoTeste {
  return {
    onboardingId: l.onboarding_id,
    iniciadaEm: new Date(l.iniciada_em),
    expiraEm: new Date(l.expira_em),
    resultado: l.resultado,
    causa: l.causa,
  };
}

/**
 * As tentativas na `onboarding_smoke`. **Dois papéis**: o `iniciar` corre pela
 * ligação da aplicação; o `fechar`, o `falhasSeguidas` e o `zerar` pela do lote.
 * Quem monta o `SmokeOwnerAssisted` dá a cada lado o cliente do seu papel.
 */
export class RegistoDoTesteSql implements RegistoDoTeste {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async iniciar(onboardingId: string, iniciadaEm: Date, expiraEm: Date): Promise<TentativaDoTeste> {
    const { rows } = await this.#cliente.query<LinhaDaTentativa>(SQL_INICIAR_TENTATIVA, [onboardingId, iniciadaEm, expiraEm]);
    const l = rows[0];
    if (l === undefined) throw new Error("caso de onboarding nao existe");
    return tentativa(l);
  }

  async corrente(onboardingId: string): Promise<TentativaDoTeste | null> {
    const { rows } = await this.#cliente.query<LinhaDaTentativa>(SQL_TENTATIVA_CORRENTE, [onboardingId]);
    return rows[0] === undefined ? null : tentativa(rows[0]);
  }

  async fechar(onboardingId: string, resultado: "ok" | "falhou", causa: CausaDoTeste | null): Promise<void> {
    await this.#cliente.query(SQL_FECHAR_TENTATIVA, [onboardingId, resultado, causa]);
  }

  async falhasSeguidas(onboardingId: string): Promise<number> {
    const { rows } = await this.#cliente.query<{ falhas: number }>(SQL_FALHAS_SEGUIDAS, [onboardingId]);
    return Number(rows[0]?.falhas ?? 0);
  }

  async zerar(onboardingId: string): Promise<void> {
    await this.#cliente.query(SQL_ZERAR_FALHAS, [onboardingId]);
  }
}

export class MarcadorSql implements MarcadorDeTeste {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async marcar(tenantId: string, conversationId: string): Promise<void> {
    await this.#cliente.query(SQL_MARCAR_CONVERSA_DE_TESTE, [tenantId, conversationId]);
  }
}

export class MaquinaSql implements MaquinaDoCaso {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async ler(onboardingId: string): Promise<CasoDeActivacao | null> {
    const { rows } = await this.#cliente.query<{ onboarding_id: string; tenant_id: string; fase: string }>(
      SQL_LER_CASO,
      [onboardingId],
    );
    const l = rows[0];
    return l === undefined ? null : { onboardingId: l.onboarding_id, tenantId: l.tenant_id, fase: l.fase };
  }

  async avancar(onboardingId: string, evento: "catalogo_minimo" | "activar", actor: string): Promise<FaseDoCaso> {
    const { rows } = await this.#cliente.query<{ fase: string }>(SQL_AVANCAR, [onboardingId, evento, actor]);
    const fase = rows[0]?.fase;
    if (fase === undefined) throw new Error("advance_case sem resposta");
    return fase;
  }
}
