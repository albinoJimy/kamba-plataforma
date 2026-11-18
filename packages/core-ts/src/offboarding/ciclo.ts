/**
 * O ciclo do off-boarding no processo de lote (KAM-210, critério 1).
 *
 * ```text
 * uma volta   lê as fases deste lado que já podem correr, corre-as por tenant e
 *             pela ordem do calendário, e recalcula as métricas das sete fases
 * ```
 *
 * ## Que fases, e quando
 *
 * As quatro fases deste lado são as do `encerramento.ts`. A `verificacao` corre-a
 * o pedido, e não o ciclo. As outras três, pela base:
 *
 *   canal       logo no D0: `pendente` ou `em_curso`
 *   pendentes   logo no D0, e outra vez a cada volta enquanto houver o que fechar
 *   revogacao   a partir do D7, com a exportação e o canal concluídos
 *
 * A `exportacao`, a `purga` e o `certificado` são do lado dos dados
 * (`libs/py-core/src/kamba_core/offboarding/`), que corre no processo Python do
 * off-boarding (`python -m kamba_core.offboarding`). **As métricas são das sete**:
 * a contagem lê a tabela inteira, e o alerta de uma fase parada vê-a onde ela
 * estiver, seja qual for o processo que a corre.
 *
 * ## Só o pedido vivo
 *
 * A consulta das fases por correr exige a `verificacao` concluída e sem
 * `cancelado_at`, que é a mesma pergunta do `exigirPedidoVivo` — e a fase
 * pergunta-a outra vez sob trinco, porque um cancelamento pode acabar entre as
 * duas.
 *
 * ## Uma fase que falha não pára as outras
 *
 * Como no `CicloDoTrust`: cada chamada tem o seu `try`, e o resultado diz quais
 * falharam **pelo nome da fase**, nunca pela mensagem nem pelo tenant (`OBS-I`).
 * Uma fase que falha fica onde estava — `pendente` ou `em_curso` — e a volta
 * seguinte tenta-a outra vez: cada uma é idempotente e retoma no passo seguinte
 * (KAM-098, critério 9). Se continuar a falhar, passa o prazo e a folga, e o
 * alerta `offboarding_fase_parada` dispara.
 *
 * ## Uma ligação por chamada
 *
 * As fases abrem e fecham as suas transacções (`BEGIN`/`COMMIT`) numa ligação
 * só; num conjunto, cada `query` podia ir a uma ligação diferente. Cada chamada
 * pede a sua ao conjunto do `kamba_batch` e devolve-a com o erro, para o `pg` a
 * descartar em vez de a dar ao próximo com uma transacção aberta.
 */

import { comBatch } from "../tenant_guard/index.ts";
import type { ConjuntoSql } from "../revisao/sql.ts";
import { DIAS_DE_CANCELAMENTO, ESTADOS_DA_FASE, FASES, type CanalDaMeta, type EstadoDaFase, type Fase, type PortasDaRevogacao } from "./contrato.ts";
import { desligarCanal, revogar, verificarPendentes, type ClienteSql } from "./encerramento.ts";
import { FASES_DO_CICLO, type FaseDoCiclo, type MetricasDoOffboarding } from "./metricas.ts";

/** Uma volta a cada 15 minutos: o prazo mais curto que este ciclo mede é de um dia (*proposta*). */
export const INTERVALO_DO_OFFBOARDING_POR_OMISSAO_MS = 900_000;

/** Quantas chamadas de fase numa volta. O resto fica para a seguinte, pela ordem do D0. */
export const LIMITE_POR_VOLTA = 100;

/**
 * Quanto uma fase pode passar do prazo antes de contar como parada, em horas.
 * Cobre a volta deste ciclo e a do lado dos dados com folga larga. *Proposta*.
 */
export const FOLGA_DA_FASE_HORAS = 24;

/**
 * As fases deste lado que já podem correr, pela ordem do D0 e do calendário.
 *
 * A revogação só entra a partir do D7 (`$2` dias depois do D0) e com a exportação
 * e o canal concluídos — as condições do `revogar`, que as volta a perguntar sob
 * trinco. Sem elas aqui, um tenant à espera do D7 entrava em todas as voltas e,
 * acima do limite, tapava os pedidos novos.
 */
export const SQL_FASES_POR_CORRER = `
  SELECT o.tenant_id::text AS tenant_id, o.fase
    FROM platform.offboarding_run o
    JOIN platform.offboarding_run v
      ON v.tenant_id = o.tenant_id AND v.fase = 'verificacao'
   WHERE v.estado = 'concluida'
     AND NOT (v.resultado ? 'cancelado_at')
     AND o.fase IN ('canal', 'pendentes', 'revogacao')
     AND o.estado IN ('pendente', 'em_curso')
     AND (o.fase <> 'revogacao' OR (
           v.prazo_at + make_interval(days => $2) <= $1
           AND EXISTS (SELECT 1 FROM platform.offboarding_run x
                        WHERE x.tenant_id = o.tenant_id AND x.fase = 'exportacao' AND x.estado = 'concluida')
           AND EXISTS (SELECT 1 FROM platform.offboarding_run c
                        WHERE c.tenant_id = o.tenant_id AND c.fase = 'canal' AND c.estado = 'concluida')))
   ORDER BY v.prazo_at, o.tenant_id, array_position(ARRAY['canal', 'pendentes', 'revogacao'], o.fase)
   LIMIT $3
`;

/**
 * A contagem das sete fases, por estado, e quantas estão **paradas**: `falhada`,
 * ou `pendente`/`em_curso` com o prazo passado há mais do que a folga. A
 * `suspensa_disputa` não está parada: espera uma disputa, e é o que deve fazer.
 */
export const SQL_CONTAGEM_DAS_FASES = `
  SELECT fase, estado, count(*)::int AS n,
         count(*) FILTER (
           WHERE estado = 'falhada'
              OR (estado IN ('pendente', 'em_curso') AND prazo_at + make_interval(hours => $2) < $1)
         )::int AS paradas
    FROM platform.offboarding_run
   GROUP BY fase, estado
`;

/**
 * Uma porta sem adaptador neste ambiente. A fase que precisa dela **falha**, e
 * fica onde estava: um encerramento «feito» sem a Meta ter recebido nada era o
 * defeito que este ticket fecha. O alerta da fase parada di-lo à equipa.
 */
export class PortaSemAdaptadorError extends Error {
  override readonly name = "PortaSemAdaptadorError";

  constructor(porta: string) {
    super(`a porta ${porta} do off-boarding nao tem adaptador neste processo`);
  }
}

function semAdaptador(porta: string): () => Promise<never> {
  return async () => {
    throw new PortaSemAdaptadorError(porta);
  };
}

/**
 * O canal da Meta sem adaptador: o que o processo de lote monta enquanto não
 * houver leitor do cofre para o *token* de cada WABA (ver `meta.ts`).
 */
export const CANAL_SEM_ADAPTADOR: CanalDaMeta = {
  numeroDoTenant: semAdaptador("meta"),
  subscreverWebhooks: semAdaptador("meta"),
  cancelarSubscricao: semAdaptador("meta"),
  removerRota: semAdaptador("meta"),
  apagarWaba: semAdaptador("meta"),
  apagarNumero: semAdaptador("meta"),
};

/**
 * As portas da revogação sem adaptador. **Só se chamam quando a saga deixou o
 * recurso** (`external_id` no `provisioning_step`); sem ele, o passo é
 * `sem_recurso` e não chega à porta. Enquanto a saga também não tiver
 * adaptadores, nenhum tenant tem o recurso, e a revogação conclui sem as chamar.
 */
export const REVOGACAO_SEM_ADAPTADOR: PortasDaRevogacao = {
  chaveDeLlm: { revogar: semAdaptador("litellm") },
  canalDeComercio: { arquivar: semAdaptador("medusa") },
  inbox: { desligar: semAdaptador("chatwoot") },
};

/** As portas que as fases deste lado usam. As da revogação são as da saga. */
export interface PortasDoCiclo {
  readonly canal: CanalDaMeta;
  readonly revogacao: PortasDaRevogacao;
}

export interface OpcoesDoCicloDoOffboarding {
  /** O conjunto de ligações do `kamba_batch`. */
  readonly lote: ConjuntoSql;
  readonly portas: PortasDoCiclo;
  readonly metricas: MetricasDoOffboarding;
  readonly relogio?: () => Date;
  readonly limite?: number;
}

export interface ResultadoDoCicloDoOffboarding {
  /** Quantas chamadas de fase correram, por fase. */
  readonly feitas: Readonly<Partial<Record<FaseDoCiclo, number>>>;
  /** As fases que falharam nesta volta, pelo nome, sem repetição. `contagem` se a leitura das métricas falhou. */
  readonly falhas: readonly (FaseDoCiclo | "listagem" | "contagem")[];
}

function eDoCiclo(fase: string): fase is FaseDoCiclo {
  return (FASES_DO_CICLO as readonly string[]).includes(fase);
}

export class CicloDoOffboarding {
  readonly #o: OpcoesDoCicloDoOffboarding;
  #aCorrer: Promise<ResultadoDoCicloDoOffboarding> | null = null;

  constructor(o: OpcoesDoCicloDoOffboarding) {
    this.#o = o;
  }

  /** Uma volta. Duas pedidas ao mesmo tempo são uma. */
  correr(): Promise<ResultadoDoCicloDoOffboarding> {
    if (this.#aCorrer !== null) return this.#aCorrer;
    this.#aCorrer = this.#volta().finally(() => {
      this.#aCorrer = null;
    });
    return this.#aCorrer;
  }

  agendar(intervaloMs: number, aoTerminar: (r: ResultadoDoCicloDoOffboarding) => void): () => void {
    if (!Number.isInteger(intervaloMs) || intervaloMs < 1_000) throw new RangeError("intervalo do ciclo abaixo de 1 s");
    const t = setInterval(() => {
      void this.correr().then(aoTerminar);
    }, intervaloMs);
    t.unref();
    return () => clearInterval(t);
  }

  #agora(): Date {
    return this.#o.relogio?.() ?? new Date();
  }

  async #volta(): Promise<ResultadoDoCicloDoOffboarding> {
    const feitas: Partial<Record<FaseDoCiclo, number>> = {};
    const falhas = new Set<FaseDoCiclo | "listagem" | "contagem">();
    const agora = this.#agora();
    let porCorrer: { tenant: string; fase: FaseDoCiclo }[] = [];
    try {
      const { rows } = await this.#o.lote.query(SQL_FASES_POR_CORRER, [
        agora,
        DIAS_DE_CANCELAMENTO,
        this.#o.limite ?? LIMITE_POR_VOLTA,
      ]);
      porCorrer = rows.flatMap((r) => {
        const fase = String(r.fase);
        return eDoCiclo(fase) ? [{ tenant: String(r.tenant_id), fase }] : [];
      });
    } catch {
      falhas.add("listagem");
    }
    for (const { tenant, fase } of porCorrer) {
      try {
        const desfecho = await this.#comLigacao((bd) => this.#fase(bd, tenant, fase, agora));
        this.#o.metricas.execucao(fase, desfecho);
        feitas[fase] = (feitas[fase] ?? 0) + 1;
      } catch {
        this.#o.metricas.execucao(fase, "falhou");
        falhas.add(fase);
      }
    }
    try {
      await this.#contar(agora);
    } catch {
      falhas.add("contagem");
    }
    return { feitas, falhas: [...falhas] };
  }

  async #fase(bd: ClienteSql, tenantId: string, fase: FaseDoCiclo, agora: Date): Promise<"concluida" | "em_curso"> {
    const { portas } = this.#o;
    if (fase === "canal") {
      await desligarCanal(bd, { tenantId, canal: portas.canal, agora });
      return "concluida";
    }
    if (fase === "pendentes") {
      const r = await verificarPendentes(bd, { tenantId, agora });
      return r.concluida ? "concluida" : "em_curso";
    }
    await revogar(bd, { tenantId, portas: portas.revogacao, agora });
    return "concluida";
  }

  async #comLigacao<T>(trabalho: (bd: ClienteSql) => Promise<T>): Promise<T> {
    const ligacao = await this.#o.lote.connect();
    let estragada: Error | undefined;
    try {
      // O `ClienteSql` da revisão não declara o `rowCount` que as fases leem; a
      // ligação do `pg` tem-no. São dois tipos para o mesmo objecto (a armadilha
      // dos três `ClienteSql` do `core-ts`, registada no KAM-200).
      return await trabalho(ligacao as unknown as ClienteSql);
    } catch (erro) {
      estragada = erro instanceof Error ? erro : new Error("fase do off-boarding falhou");
      throw erro;
    } finally {
      ligacao.release(estragada);
    }
  }

  async #contar(agora: Date): Promise<void> {
    const ligacao = await this.#o.lote.connect();
    let estragada: Error | undefined;
    try {
      const rows = await comBatch(ligacao, "offboarding_metricas", async () =>
        (await ligacao.query(SQL_CONTAGEM_DAS_FASES, [agora, FOLGA_DA_FASE_HORAS])).rows,
      );
      this.#o.metricas.fixar(
        rows.flatMap((r) => {
          const fase = String(r.fase);
          const estado = String(r.estado);
          if (!(FASES as readonly string[]).includes(fase)) return [];
          if (!(ESTADOS_DA_FASE as readonly string[]).includes(estado)) return [];
          return [{ fase: fase as Fase, estado: estado as EstadoDaFase, n: Number(r.n ?? 0), paradas: Number(r.paradas ?? 0) }];
        }),
      );
    } catch (erro) {
      estragada = erro instanceof Error ? erro : new Error("contagem do off-boarding falhou");
      throw erro;
    } finally {
      ligacao.release(estragada);
    }
  }
}
