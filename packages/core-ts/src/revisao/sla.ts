/**
 * O SLA da fila em dias úteis de Luanda (KAM-089, critério 2).
 *
 * ## A definição, que o bloco não dá
 *
 * «1 dia útil» conta-se como **tempo útil**: só correm as horas dos dias úteis
 * de Luanda, e um dia útil vale 24 h. Um caso aberto sexta às 15:00 vence
 * segunda às 15:00; um aberto sábado vence segunda às 24:00 (terça às 00:00),
 * porque o tempo só começa a correr segunda às 00:00. A alternativa — «o mesmo
 * relógio no dia útil seguinte» — dava ao caso de sábado um prazo de segunda às
 * 10:00 se tivesse entrado às 10:00, isto é, tratava o sábado como meio dia
 * útil. Esta é a leitura que não depende da hora a que o fim-de-semana começou.
 *
 * O alerta (80%, *proposta*) é o instante em que o tempo útil decorrido chega a
 * 80% do prazo, pela mesma conta.
 *
 * ## Luanda é UTC+01:00 o ano inteiro
 *
 * Angola não tem hora de Verão (fuso `Africa/Luanda`, WAT), e a aritmética faz-se
 * com o desvio fixo. Há um ensaio que confronta o dia calculado com o do
 * `Intl.DateTimeFormat` em `Africa/Luanda`, para o dia em que isso deixar de ser
 * verdade.
 *
 * ## Os feriados
 *
 * A tabela é configurável (`Feriados`): os fixos por mês-dia e os móveis por
 * data. **A lista por omissão é NÃO VERIFICADA**: são os feriados nacionais
 * fixos de Angola tal como são correntemente citados, sem a fonte primária (a
 * lei dos feriados no *Diário da República*) lida neste repositório; os móveis
 * (Carnaval, Sexta-feira Santa) e as pontes não se calculam aqui, entram por
 * data. Como validar: conferir contra a lei em vigor e corrigir a configuração.
 */

import type { Sla } from "./contrato.ts";

/** Desvio de Luanda, em milissegundos. Ver a nota do módulo. */
export const DESVIO_DE_LUANDA_MS = 3_600_000;

const DIA_MS = 86_400_000;

/** A tabela de feriados. */
export interface Feriados {
  /** Feriados que se repetem todos os anos, como `MM-DD`. */
  readonly fixos: readonly string[];
  /** Feriados de um só ano (móveis, pontes), como `AAAA-MM-DD`. */
  readonly datas: readonly string[];
}

/** **NÃO VERIFICADO** — ver a nota do módulo. */
export const FERIADOS_POR_OMISSAO: Feriados = {
  fixos: ["01-01", "02-04", "03-08", "03-23", "04-04", "05-01", "09-17", "11-02", "11-11", "12-25"],
  datas: [],
};

/** A data civil de Luanda de um instante, como `AAAA-MM-DD`. */
export function diaEmLuanda(instante: Date): string {
  return new Date(instante.getTime() + DESVIO_DE_LUANDA_MS).toISOString().slice(0, 10);
}

/** O instante UTC da meia-noite de Luanda do dia que contém `instante`. */
export function inicioDoDiaEmLuanda(instante: Date): Date {
  const local = instante.getTime() + DESVIO_DE_LUANDA_MS;
  return new Date(Math.floor(local / DIA_MS) * DIA_MS - DESVIO_DE_LUANDA_MS);
}

/** O dia (`AAAA-MM-DD`, de Luanda) é útil? Segunda a sexta, e não feriado. */
export function diaUtil(dia: string, feriados: Feriados): boolean {
  const semana = new Date(`${dia}T00:00:00Z`).getUTCDay();
  if (semana === 0 || semana === 6) return false;
  if (feriados.datas.includes(dia)) return false;
  return !feriados.fixos.includes(dia.slice(5));
}

/** Tecto de dias que se percorrem antes de desistir: uma tabela sem dias úteis é erro de configuração. */
const DIAS_MAXIMOS = 3660;

/** O instante em que o tempo útil decorrido desde `inicio` chega a `ms`. */
export function somarTempoUtil(inicio: Date, ms: number, feriados: Feriados): Date {
  if (!(ms >= 0) || !Number.isFinite(ms)) throw new RangeError("tempo util invalido");
  let t = inicio.getTime();
  let falta = ms;
  for (let i = 0; i < DIAS_MAXIMOS; i++) {
    const fimDoDia = inicioDoDiaEmLuanda(new Date(t)).getTime() + DIA_MS;
    if (diaUtil(diaEmLuanda(new Date(t)), feriados)) {
      const cabe = fimDoDia - t;
      if (falta <= cabe) return new Date(t + falta);
      falta -= cabe;
    }
    t = fimDoDia;
  }
  throw new RangeError("tabela de feriados sem dias uteis");
}

/** O tempo útil, em milissegundos, entre `de` e `ate`. Zero se `ate` não é posterior. */
export function tempoUtilEntre(de: Date, ate: Date, feriados: Feriados): number {
  let t = de.getTime();
  const fim = ate.getTime();
  let total = 0;
  for (let i = 0; t < fim; i++) {
    if (i >= DIAS_MAXIMOS) throw new RangeError("intervalo demasiado longo");
    const fimDoDia = inicioDoDiaEmLuanda(new Date(t)).getTime() + DIA_MS;
    const ate_ = Math.min(fimDoDia, fim);
    if (diaUtil(diaEmLuanda(new Date(t)), feriados)) total += ate_ - t;
    t = fimDoDia;
  }
  return total;
}

/** O prazo e o alerta de um caso que entra na vista humana em `inicio`. */
export function calcularSla(
  inicio: Date,
  feriados: Feriados,
  diasUteis: number,
  fracaoDoAlerta: number,
): Sla {
  const prazo = diasUteis * DIA_MS;
  return {
    slaDueAt: somarTempoUtil(inicio, prazo, feriados),
    slaAlertaAt: somarTempoUtil(inicio, Math.round(prazo * fracaoDoAlerta), feriados),
  };
}

/**
 * O percentil `p` (em `[0, 1]`) pelo método do *nearest rank*: o valor
 * observado na posição `ceil(p·n)`. Sem interpolação, para que o p90 seja
 * sempre um tempo que algum caso de facto levou. `null` sem amostras.
 */
export function percentil(valores: readonly number[], p: number): number | null {
  if (valores.length === 0) return null;
  const ordenados = [...valores].sort((a, b) => a - b);
  const posicao = Math.max(1, Math.ceil(p * ordenados.length));
  return ordenados[posicao - 1]!;
}
