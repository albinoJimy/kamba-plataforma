/**
 * O *job* da fila de revisão (KAM-196, critério 6).
 *
 * «A fila corre num *job* nomeado com credenciais de lote: `drenarTriagem` e
 * `alertarSla` agendados, `amostrar` chamado sobre cada aprovação automática (a
 * que o KAM-092 conhece), `reaplicarEfeitos` sobre as decisões cujo efeito
 * falhou, e as métricas do §3.61 servidas.»
 *
 * ```text
 * correr()              uma volta: drenar, alertar, reaplicar, medir
 * agendar(ms)           a volta a cada intervalo; devolve o que a pára
 * aprovacaoAutomatica   o gancho do KAM-092: amostra uma aprovação automática
 * efeitoFalhou(caso)    quem decidiu e viu um efeito falhar marca o caso aqui
 * ```
 *
 * ## Cada passo corre mesmo que o anterior falhe
 *
 * Um alerta que rebenta não pode deixar a triagem por drenar, nem um efeito
 * por reaplicar deixar as métricas paradas. Cada passo tem o seu `try`, e o
 * resultado da volta diz quais falharam, por **nome do passo** — nunca pela
 * mensagem do erro, que pode trazer o que não deve sair.
 *
 * ## O que é «um efeito que falhou»
 *
 * A decisão e os efeitos não são uma transacção (ver `reaplicarEfeitos` no
 * `./servico.ts`): o caso fecha, e depois a fase do onboarding, o screening e o
 * aviso podem falhar. Quem sabe disso é quem chamou `decidir` e viu o erro — a
 * consola (`services/onboarding-web/src/equipa/rotas.ts`) —, e marca o caso
 * aqui. O ciclo reaplica-o; um caso que afinal não fechou (`estado_invalido`)
 * ou que não existe sai da lista, porque não há efeito a reaplicar; qualquer
 * outro erro deixa-o na lista para a volta seguinte.
 *
 * ***shortcut:*** a lista de efeitos por reaplicar é em memória, como tudo o
 * que o `onboarding-web` tem: perde-se no reinício, e então o caso fica
 * decidido com o efeito por aplicar até alguém o reaplicar à mão. Revê-se com
 * o processo de lote da fila (o `kamba_batch` sobre a `RevisaoSql`), que é onde
 * esta lista passa a ser uma consulta aos casos decididos sem efeito.
 */

import type { Feriados } from "./sla.ts";
import { FERIADOS_POR_OMISSAO } from "./sla.ts";
import { CasoInexistenteError, RevisaoRecusadaError } from "./contrato.ts";
import { MetricasDaRevisao, type Contador, type LinhaDaVista } from "./metricas.ts";
import type { ResultadoDaAbertura, ServicoDeRevisao } from "./servico.ts";
import { SQL_CONTADORES, SQL_VISTA_SLA, type ClienteSql } from "./sql.ts";

/** O que as métricas lêem da fila: a `v_review_sla` e o `SQL_CONTADORES`. */
export interface LeitorDaFila {
  vista(): Promise<readonly LinhaDaVista[]>;
  contadores(): Promise<readonly Contador[]>;
}

/** Os casos decididos com um efeito por aplicar. */
export interface EfeitosPorReaplicar {
  marcar(casoId: string): Promise<void>;
  pendentes(limite: number): Promise<readonly string[]>;
  resolver(casoId: string): Promise<void>;
}

export class EfeitosPorReaplicarEmMemoria implements EfeitosPorReaplicar {
  readonly #ids = new Set<string>();

  async marcar(casoId: string): Promise<void> {
    this.#ids.add(casoId);
  }

  async pendentes(limite: number): Promise<readonly string[]> {
    return [...this.#ids].slice(0, limite);
  }

  async resolver(casoId: string): Promise<void> {
    this.#ids.delete(casoId);
  }
}

/** Os passos de uma volta. É por estes nomes que uma falha se diz. */
export const PASSOS_DO_CICLO = ["drenar", "alertar", "reaplicar", "medir"] as const;
export type PassoDoCiclo = (typeof PASSOS_DO_CICLO)[number];

export interface ResultadoDoCiclo {
  readonly entraram: number;
  readonly alertas: number;
  readonly reaplicados: number;
  /** Casos cujo efeito voltou a falhar e ficam para a volta seguinte. */
  readonly porReaplicar: number;
  readonly falhas: readonly PassoDoCiclo[];
}

/** O que o ciclo usa do serviço. */
export type ServicoDoCiclo = Pick<ServicoDeRevisao, "drenarTriagem" | "alertarSla" | "reaplicarEfeitos" | "amostrar">;

export interface OpcoesDoCiclo {
  readonly servico: ServicoDoCiclo;
  readonly leitor: LeitorDaFila;
  readonly efeitos?: EfeitosPorReaplicar;
  readonly metricas?: MetricasDaRevisao;
  readonly feriados?: Feriados;
  /** Quantos casos da triagem, e quantos efeitos, numa volta. */
  readonly limite?: number;
}

export class CicloDaFila {
  readonly metricas: MetricasDaRevisao;
  readonly efeitos: EfeitosPorReaplicar;
  readonly #o: OpcoesDoCiclo;
  #aCorrer: Promise<ResultadoDoCiclo> | null = null;

  constructor(opcoes: OpcoesDoCiclo) {
    this.#o = opcoes;
    this.metricas = opcoes.metricas ?? new MetricasDaRevisao();
    this.efeitos = opcoes.efeitos ?? new EfeitosPorReaplicarEmMemoria();
  }

  /**
   * Uma volta. **Duas voltas não se sobrepõem**: uma chamada durante outra
   * devolve a que já corre, em vez de drenar a mesma triagem duas vezes.
   */
  correr(): Promise<ResultadoDoCiclo> {
    if (this.#aCorrer !== null) return this.#aCorrer;
    this.#aCorrer = this.#volta().finally(() => {
      this.#aCorrer = null;
    });
    return this.#aCorrer;
  }

  async #volta(): Promise<ResultadoDoCiclo> {
    const limite = this.#o.limite ?? 500;
    const falhas: PassoDoCiclo[] = [];
    let entraram = 0;
    let alertas = 0;
    let reaplicados = 0;
    let porReaplicar = 0;
    try {
      entraram = await this.#o.servico.drenarTriagem(limite);
    } catch {
      falhas.push("drenar");
    }
    try {
      alertas = await this.#o.servico.alertarSla();
    } catch {
      falhas.push("alertar");
    }
    try {
      for (const id of await this.efeitos.pendentes(limite)) {
        try {
          await this.#o.servico.reaplicarEfeitos(id);
          await this.efeitos.resolver(id);
          reaplicados++;
        } catch (erro) {
          if (
            erro instanceof CasoInexistenteError ||
            (erro instanceof RevisaoRecusadaError && erro.motivo === "estado_invalido")
          ) {
            await this.efeitos.resolver(id);
          } else {
            porReaplicar++;
          }
        }
      }
      if (porReaplicar > 0) falhas.push("reaplicar");
    } catch {
      falhas.push("reaplicar");
    }
    try {
      const [vista, contadores] = await Promise.all([this.#o.leitor.vista(), this.#o.leitor.contadores()]);
      this.metricas.actualizar(vista, contadores, this.#o.feriados ?? FERIADOS_POR_OMISSAO);
    } catch {
      falhas.push("medir");
    }
    return { entraram, alertas, reaplicados, porReaplicar, falhas };
  }

  /** Marca um caso cujo efeito falhou depois de ele fechar. */
  efeitoFalhou(casoId: string): Promise<void> {
    return this.efeitos.marcar(casoId);
  }

  /**
   * O gancho da aprovação automática. Quem a conhece é o KAM-092, e é ele que o
   * chama; aqui só se passa ao `amostrar`, que decide se a aprovação entra na
   * amostra.
   */
  aprovacaoAutomatica(onboardingId: string, tenantId: string): Promise<ResultadoDaAbertura | null> {
    return this.#o.servico.amostrar(onboardingId, tenantId);
  }

  /**
   * Corre uma volta a cada `intervaloMs`, e devolve a função que pára. O
   * temporizador não segura o processo (`unref`), e o resultado de cada volta
   * vai para `aoTerminar` — um passo que falhou diz-se lá, não se engole.
   */
  agendar(intervaloMs: number, aoTerminar: (r: ResultadoDoCiclo) => void): () => void {
    if (!Number.isInteger(intervaloMs) || intervaloMs < 1_000) throw new RangeError("intervalo do ciclo abaixo de 1 s");
    const t = setInterval(() => {
      void this.correr().then(aoTerminar);
    }, intervaloMs);
    t.unref();
    return () => clearInterval(t);
  }
}

interface LinhaSqlDaVista {
  tipo: LinhaDaVista["tipo"];
  estado: LinhaDaVista["estado"];
  fila_at: Date | string;
  primeira_decisao_at: Date | string | null;
}

interface LinhaSqlDoContador {
  tipo: Contador["tipo"];
  motivo: string;
  decisao: Contador["decisao"];
  n: number;
}

const data = (v: Date | string): Date => (v instanceof Date ? v : new Date(v));

/**
 * O leitor das métricas sobre a base, pelas duas consultas que a `0048` já
 * serve (`SQL_VISTA_SLA`, `SQL_CONTADORES`). Corre com as credenciais de lote,
 * como a `RevisaoSql`: só o lote e a auditoria lêem a vista.
 */
export class LeitorDaFilaSql implements LeitorDaFila {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async vista(): Promise<readonly LinhaDaVista[]> {
    const r = await this.#cliente.query<LinhaSqlDaVista>(SQL_VISTA_SLA);
    return r.rows.map((l) => ({
      tipo: l.tipo,
      estado: l.estado,
      filaEm: data(l.fila_at),
      primeiraDecisaoEm: l.primeira_decisao_at === null ? null : data(l.primeira_decisao_at),
    }));
  }

  async contadores(): Promise<readonly Contador[]> {
    const r = await this.#cliente.query<LinhaSqlDoContador>(SQL_CONTADORES);
    return r.rows.map((l) => ({ tipo: l.tipo, motivo: l.motivo, decisao: l.decisao, n: Number(l.n) }));
  }
}
