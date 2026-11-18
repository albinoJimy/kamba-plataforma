/**
 * O recálculo da confiança gradual a correr (KAM-203).
 *
 * ```text
 * RecalculoDaConfianca   um tenant: uma transacção kamba_batch em READ COMMITTED,
 *                        com a leitura dos pedidos num kamba_app sob o tenant
 * CicloDaConfianca       correr: a volta diária sobre cada tenant com caso
 *                        aprovado, e uma linha batch.run no audit_log por volta
 *                        descer: a varredura curta dos que têm de descer
 * ```
 *
 * Quem chama o `RecalculoDaConfianca` é o processo de lote do onboarding
 * (`services/onboarding-web/src/lote/processo.ts`), em quatro sítios: a volta
 * diária (`diario`), o `order.delivered` consumido pelo consumidor de T&S
 * (`entrega`), a aprovação do tenant (`aprovacao`) e a varredura das descidas
 * (`descida`). O recálculo é idempotente (`decidirNivel` devolve `null` quando
 * nada muda, e a base não reescreve uma linha igual), pelo que quatro sítios a
 * chamar o mesmo tenant não escrevem quatro vezes.
 *
 * ## A sanção chega à base sem esperar pelo dia seguinte (critério 4)
 *
 * Uma sanção grava-se por vários caminhos — o consumidor de T&S (como
 * `kamba_app`, dentro da transacção do consumo), as varreduras de não-entrega e
 * das mudanças de conta, e as decisões da fila —, e um gancho em cada um era um
 * gancho por esquecer no caminho seguinte. Em vez disso, a varredura `descer`
 * corre a cada volta do processo (um minuto por omissão) e pergunta à base quem
 * está acima do nível 0 com um facto negativo **posterior** ao nível: uma
 * sanção `limitacao` ou acima sem recurso provido, um sinal de severidade alta,
 * ou uma disputa aceite. São os três de `decidirNivel`; o recálculo de cada um
 * decide. Um tenant no nível 0 nunca é candidato, pelo que a varredura vazia é
 * a normal e não custa mais do que a consulta.
 *
 * ## Uma transacção por tenant, e duas ligações
 *
 * O `ServicoDeConfianca` tranca o tenant e lê tudo na transacção do
 * `kamba_batch`, que é o único papel que escreve `trust_level`. Os pedidos
 * entregues e a independência de cada um lêem-se como `kamba_app`, com o
 * `app.tenant_id` do tenant (a nota do `./sql.ts` diz porquê: o comprador
 * canónico sai do cofre de identidade). As duas transacções abrem-se juntas e
 * fecham-se pela ordem inversa: o `COMMIT` do `kamba_batch`, que é o que
 * escreve, vem primeiro, e uma falha em qualquer ponto desfaz as duas.
 *
 * O `READ COMMITTED` é explícito (`SQL_READ_COMMITTED`, a primeira instrução da
 * transacção do lote) e não a omissão da base: uma `default_transaction_isolation`
 * mudada no servidor não muda o que o critério 1 pede.
 *
 * ## Uma linha `batch.run` por volta, e não por tenant
 *
 * Como as varreduras de T&S (`../trust/lote.ts`): o `tenant_id` é nulo (cadeia
 * da plataforma), o `entity` é `trust_level`, o `entity_id` é
 * `recalculo_diario`, e o `payload_hash` é o SHA-256 de
 * `recalculo_diario:<tenants>:<mudaram>:<falhas>`. Cada mudança de nível tem a
 * sua própria linha `trust.tecto`, escrita pelo *trigger* da `0065`; uma volta
 * que não muda nada não escreve nenhuma — e é isso que «reexecutar não escreve
 * outra linha» quer dizer: a linha da corrida é uma por corrida.
 */

import { RepositorioDeTrustSql } from "../trust/sql.ts";
import { ServicoDeTrust } from "../trust/servico.ts";
import type { ConjuntoSql } from "../revisao/sql.ts";
import { comBatch, comTenant } from "../tenant_guard/index.ts";
import type { ConfiguracaoDaConfianca } from "./config.ts";
import type { ContadoresDaConfianca, OrigemDoRecalculo } from "./metricas.ts";
import { ServicoDeConfianca, type ResultadoDoRecalculo } from "./niveis.ts";
import { RepositorioDeConfiancaSql, type ClienteSql as ClienteDaConfianca } from "./sql.ts";

/** O nome do *job* do `comBatch` (a contagem `tenant_guard_batch_total`). */
export const JOB_DO_RECALCULO = "confianca_recalculo";

/** O actor da linha `batch.run`: o processo, e não uma pessoa. */
export const ACTOR_DO_RECALCULO = "onboarding-lote";

/** Uma volta por dia (critério 1). */
export const INTERVALO_DA_CONFIANCA_POR_OMISSAO_MS = 86_400_000;

/** A primeira instrução da transacção do lote. */
export const SQL_READ_COMMITTED = `SET TRANSACTION ISOLATION LEVEL READ COMMITTED`;

/**
 * Os tenants da volta diária: os que já têm nível — para que uma descida chegue
 * mesmo a quem o caso mudou depois — e os que têm o caso aprovado ou adiante
 * dele, que é onde nasce o nível 0. As fases são as do §3.57 a partir de
 * `aprovado`, menos as mortas.
 */
export const SQL_TENANTS_A_RECALCULAR = `
  SELECT l.tenant_id::text AS tenant_id FROM platform.trust_level l
  UNION
  SELECT c.tenant_id::text AS tenant_id FROM platform.onboarding_case c
   WHERE c.fase IN ('aprovado', 'provisionando', 'aguarda_es', 'lista_espera',
                    'aguarda_catalogo', 'aguarda_teste', 'activo')
  ORDER BY 1
`;

/**
 * Os tenants que têm de descer: acima do nível 0, com um dos três factos
 * negativos de `decidirNivel` gravado depois do `desde` do nível. A sanção conta
 * sem recurso provido — um recurso negado não a tira de vigor —, e o sinal pelo
 * `criado_at`, como no `SQL_FACTOS_NEGATIVOS`.
 */
export const SQL_TENANTS_A_DESCER = `
  SELECT l.tenant_id::text AS tenant_id
    FROM platform.trust_level l
   WHERE l.nivel > 0
     AND (EXISTS (SELECT 1 FROM platform.ts_sanction s
                   WHERE s.tenant_id = l.tenant_id AND s.recurso_de IS NULL
                     AND s.passo IN ('limitacao', 'suspensao', 'encerramento') AND s.em > l.desde
                     AND NOT EXISTS (SELECT 1 FROM platform.ts_sanction r
                                      WHERE r.tenant_id = s.tenant_id AND r.recurso_de = s.id
                                        AND r.recurso_estado = 'provido'))
          OR EXISTS (SELECT 1 FROM platform.ts_signal g
                      WHERE g.tenant_id = l.tenant_id AND g.severidade = 'alta' AND g.criado_at > l.desde)
          OR EXISTS (SELECT 1 FROM platform.order_state_log o
                      WHERE o.tenant_id = l.tenant_id AND o.de = 'em_disputa' AND o.para = 'reembolso_pendente'
                        AND o.em > l.desde))
   ORDER BY 1
`;

/** A corrida de uma volta no `audit_log`, na cadeia da plataforma. */
export const SQL_AUDITAR_RECALCULO = `
  SELECT platform.audit_append(
           NULL, 'system', $1, 'batch.run', 'trust_level', $2, NULL,
           sha256(convert_to($3, 'UTF8')))
`;

export interface OpcoesDoRecalculo {
  /** O conjunto de ligações do `kamba_batch`. */
  readonly lote: ConjuntoSql;
  /** O conjunto de ligações do `kamba_app`. */
  readonly app: ConjuntoSql;
  /**
   * O `events_consumed.consumer` do consumidor de T&S, que marca a
   * independência. Vem da subscrição do processo (critério 5), e não de um
   * literal escrito aqui.
   */
  readonly consumidorDeTrust: string;
  readonly metricas: ContadoresDaConfianca;
  readonly configuracao?: ConfiguracaoDaConfianca;
  readonly relogio?: () => Date;
}

/** O recálculo de um tenant, sobre a base. */
export class RecalculoDaConfianca {
  readonly #o: OpcoesDoRecalculo;

  constructor(o: OpcoesDoRecalculo) {
    // Falha no arranque, e não no primeiro tenant: o `ServicoDeConfianca`
    // valida o nome e a configuração.
    this.#servico(o, o.lote, o.lote);
    this.#o = o;
  }

  /** O nome do consumidor de T&S com que este recálculo lê a independência. */
  get consumidorDeTrust(): string {
    return this.#o.consumidorDeTrust;
  }

  /**
   * Recalcula o tenant e conta depois do `COMMIT`. Uma falha conta como
   * `falhou` e sobe: quem chama decide se a engole (a volta diária, a
   * aprovação) ou se a deixa repetir (o consumidor).
   */
  async recalcular(tenantId: string, origem: OrigemDoRecalculo): Promise<ResultadoDoRecalculo> {
    let r: ResultadoDoRecalculo;
    try {
      r = await this.#numaTransaccao(tenantId);
    } catch (erro) {
      this.#o.metricas.recalculo(origem, "falhou");
      throw erro;
    }
    this.#o.metricas.recalculo(origem, r.mudou ? "mudou" : "sem_mudanca");
    if (r.mudou && r.motivo !== null) this.#o.metricas.mudanca(r.motivo);
    return r;
  }

  /**
   * O serviço sobre as duas ligações da transacção. **O `as` é dos tipos, e não
   * do valor**: o `ConjuntoSql` da fila promete `{rows}` e o adaptador da
   * confiança pede também o `rowCount` — o `pg` cumpre os dois, e os dois tipos
   * não se cumprem um ao outro (a mesma nota do KAM-200 sobre os três
   * `ClienteSql` do `core-ts`).
   */
  #servico(o: OpcoesDoRecalculo, lote: unknown, app: unknown): ServicoDeConfianca {
    const loteSql = lote as ClienteDaConfianca;
    const appSql = app as ClienteDaConfianca;
    return new ServicoDeConfianca({
      repositorio: new RepositorioDeConfiancaSql(loteSql, appSql),
      independencia: new RepositorioDeTrustSql(appSql, "app"),
      restricoes: new ServicoDeTrust({ repositorio: new RepositorioDeTrustSql(loteSql, "lote") }),
      consumidorDeTrust: o.consumidorDeTrust,
      ...(o.configuracao === undefined ? {} : { configuracao: o.configuracao }),
      ...(o.relogio === undefined ? {} : { relogio: o.relogio }),
    });
  }

  async #numaTransaccao(tenantId: string): Promise<ResultadoDoRecalculo> {
    const lote = await this.#o.lote.connect();
    let app: Awaited<ReturnType<ConjuntoSql["connect"]>> | undefined;
    let estragada: Error | undefined;
    try {
      app = await this.#o.app.connect();
      const aplicacao = app;
      // O `comTenant` por fora: o `COMMIT` do lote (a escrita) vem primeiro, e
      // uma falha nele desfaz também a leitura da aplicação.
      return await comTenant(aplicacao, tenantId, () =>
        comBatch(lote, JOB_DO_RECALCULO, async () => {
          await lote.query(SQL_READ_COMMITTED);
          return this.#servico(this.#o, lote, aplicacao).recalcular(tenantId);
        }),
      );
    } catch (erro) {
      // O `comTenant` e o `comBatch` engolem uma falha do `ROLLBACK`, e então
      // não se sabe se a transacção ficou fechada: as ligações devolvem-se com
      // o erro, e o `pg` descarta-as (a regra do `escritorHumanoDeScreening`).
      estragada = erro instanceof Error ? erro : new Error("recalculo da confianca falhou");
      throw erro;
    } finally {
      app?.release(estragada);
      lote.release(estragada);
    }
  }
}

export interface ResultadoDoCicloDaConfianca {
  /** Quantos tenants a volta tentou. */
  readonly tenants: number;
  /** Quantos mudaram de nível ou de tecto. */
  readonly mudaram: number;
  /** Quantos falharam. Uma falha não pára os seguintes. */
  readonly falhas: number;
}

/** A volta diária (critério 1). */
export class CicloDaConfianca {
  readonly #lote: ConjuntoSql;
  readonly #recalculo: RecalculoDaConfianca;
  #aCorrer: Promise<ResultadoDoCicloDaConfianca> | null = null;
  #aDescer: Promise<ResultadoDoCicloDaConfianca> | null = null;

  constructor(o: { readonly lote: ConjuntoSql; readonly recalculo: RecalculoDaConfianca }) {
    this.#lote = o.lote;
    this.#recalculo = o.recalculo;
  }

  /** A volta diária. Duas pedidas ao mesmo tempo são uma. */
  correr(): Promise<ResultadoDoCicloDaConfianca> {
    if (this.#aCorrer !== null) return this.#aCorrer;
    this.#aCorrer = this.#volta(SQL_TENANTS_A_RECALCULAR, "diario", "recalculo_diario", true).finally(() => {
      this.#aCorrer = null;
    });
    return this.#aCorrer;
  }

  /**
   * A varredura das descidas (critério 4). **Só audita quando recalculou
   * alguém**: corre a cada minuto, e uma linha `batch.run` por minuto sem nada
   * feito eram 1440 linhas por dia na cadeia da plataforma a dizer «nada». Cada
   * descida tem a sua linha `trust.tecto`, do *trigger*.
   */
  descer(): Promise<ResultadoDoCicloDaConfianca> {
    if (this.#aDescer !== null) return this.#aDescer;
    this.#aDescer = this.#volta(SQL_TENANTS_A_DESCER, "descida", "recalculo_descida", false).finally(() => {
      this.#aDescer = null;
    });
    return this.#aDescer;
  }

  /** Agenda uma das duas voltas; devolve quem a pára. */
  agendar(
    qual: "correr" | "descer",
    intervaloMs: number,
    aoTerminar: (r: ResultadoDoCicloDaConfianca) => void,
    aoFalhar: (erro: unknown) => void,
  ): () => void {
    if (!Number.isInteger(intervaloMs) || intervaloMs < 1_000) throw new RangeError("intervalo do ciclo abaixo de 1 s");
    const t = setInterval(() => {
      void (qual === "correr" ? this.correr() : this.descer()).then(aoTerminar, aoFalhar);
    }, intervaloMs);
    t.unref();
    return () => clearInterval(t);
  }

  async #volta(
    consulta: string,
    origem: OrigemDoRecalculo,
    entidade: string,
    auditarSempre: boolean,
  ): Promise<ResultadoDoCicloDaConfianca> {
    const tenants = (await this.#lote.query(consulta)).rows.map((l) => String(l["tenant_id"]));
    let mudaram = 0;
    let falhas = 0;
    for (const tenantId of tenants) {
      try {
        if ((await this.#recalculo.recalcular(tenantId, origem)).mudou) mudaram++;
      } catch {
        // Contada pelo `recalcular` (`desfecho="falhou"`) e pela linha de
        // auditoria; o tenant seguinte corre.
        falhas++;
      }
    }
    if (auditarSempre || tenants.length > 0) {
      await this.#lote.query(SQL_AUDITAR_RECALCULO, [
        ACTOR_DO_RECALCULO,
        entidade,
        `${entidade}:${tenants.length}:${mudaram}:${falhas}`,
      ]);
    }
    return { tenants: tenants.length, mudaram, falhas };
  }
}
