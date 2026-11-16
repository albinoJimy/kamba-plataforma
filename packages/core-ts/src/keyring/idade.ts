/**
 * A idade de cada segredo, `secret_age_days{segredo}`, e o limiar de 80% do
 * prazo (KAM-072, critério 7).
 *
 * O `ops/secrets-inventory.yaml` tem o `rotacao_dias` de cada segredo e **não
 * tem** a data da última rotação — e não deve ter: o inventário é versionado e
 * a data é estado operacional. A data vem do registo de rotação
 * (`rotacao.ts`), que é o mesmo sítio que o critério 7 manda auditar. Uma só
 * fonte para «quando rodou» e «que idade tem» é o que impede as duas de
 * divergirem.
 *
 * ## O que este ficheiro entrega, e o que não
 *
 * Entrega o **cálculo** e as **amostras**: a idade em dias, o prazo, o estado
 * (`ok`, `a_expirar` a partir de 80%, `vencido` a partir de 100%) e as duas
 * séries que uma regra de alerta precisa — `secret_age_days` e
 * `secret_rotation_period_days`, ambas com a etiqueta `segredo`. A etiqueta é
 * de domínio fechado: os `id` do inventário (41 hoje), abaixo do tecto de 64 da
 * política do `ops/metricas/catalogo.yaml`.
 *
 * **Não** as expõe num `/metrics` e **não** escreve a regra do Prometheus: o
 * `obs_lint` recusa uma regra que cite uma métrica que nenhum processo serve, e
 * o processo que corre a rotação ainda não existe (é operação manual pelo
 * RB-K07). Fica dito no catálogo, com credor, em vez de publicar zeros.
 */

import type { RegistoDeRotacao } from "./rotacao.ts";
import { DIA_MS } from "./rotacao.ts";

/** A fracção do prazo a partir da qual o segredo está «a expirar». */
export const LIMIAR_DE_ALERTA = 0.8;

/** A política de rotação de um segredo, como o inventário a declara. */
export interface PoliticaDeRotacao {
  readonly segredo: string;
  /** `null` quando a rotação é por evento e não por calendário. */
  readonly rotacaoDias: number | null;
}

/** O estado de um segredo face ao seu prazo. */
export type EstadoDaIdade =
  | "ok"
  | "a_expirar"
  | "vencido"
  /** Rotação por evento: não há prazo, logo não há alerta de idade. */
  | "por_evento"
  /** Nunca rodou pelo rotador: a idade não se sabe, e isso alerta. */
  | "sem_registo";

/** A idade de um segredo. */
export interface IdadeDoSegredo {
  readonly segredo: string;
  readonly idadeDias: number | null;
  readonly prazoDias: number | null;
  readonly estado: EstadoDaIdade;
}

/** O estado para uma idade e um prazo. Fecha no limite: 80% exacto já alerta. */
export function estadoDa(idadeDias: number | null, prazoDias: number | null): EstadoDaIdade {
  if (prazoDias === null) return "por_evento";
  if (idadeDias === null) return "sem_registo";
  if (idadeDias >= prazoDias) return "vencido";
  if (idadeDias >= LIMIAR_DE_ALERTA * prazoDias) return "a_expirar";
  return "ok";
}

/**
 * A idade de cada segredo em `agora`, a partir da última rotação registada.
 *
 * Uma revogação **não** rejuvenesce o segredo: retirar a anterior não muda a
 * idade da actual. Contam a rotação planeada e a de emergência.
 */
export async function idadesDosSegredos(
  politicas: readonly PoliticaDeRotacao[],
  registo: RegistoDeRotacao,
  agora: Date,
): Promise<readonly IdadeDoSegredo[]> {
  const idades: IdadeDoSegredo[] = [];
  for (const { segredo, rotacaoDias } of politicas) {
    if (rotacaoDias !== null && (!Number.isFinite(rotacaoDias) || rotacaoDias <= 0)) {
      throw new RangeError(`o prazo de ${segredo} tem de ser um número de dias positivo`);
    }
    const rotacoes = (await registo.entradas(segredo)).filter(
      (entrada) => entrada.accao !== "revogacao",
    );
    const ultima = rotacoes[rotacoes.length - 1];
    const idadeDias =
      ultima === undefined
        ? null
        : Math.max(0, (agora.getTime() - ultima.em.getTime()) / DIA_MS);
    idades.push({ segredo, idadeDias, prazoDias: rotacaoDias, estado: estadoDa(idadeDias, rotacaoDias) });
  }
  return idades;
}

/** Uma amostra de série temporal, na forma neutra que um *exporter* traduz. */
export interface Amostra {
  readonly nome: "secret_age_days" | "secret_rotation_period_days";
  readonly etiquetas: { readonly segredo: string };
  readonly valor: number;
}

/**
 * As amostras das duas séries. Um segredo sem registo não tem amostra de idade
 * — publicar zero diria «acabou de rodar» —; tem a do prazo, e a regra de
 * alerta apanha-o pela ausência (`absent`/`unless`), que é o estado
 * `sem_registo`.
 */
export function amostras(idades: readonly IdadeDoSegredo[]): readonly Amostra[] {
  const saida: Amostra[] = [];
  for (const { segredo, idadeDias, prazoDias } of idades) {
    if (prazoDias === null) continue;
    saida.push({ nome: "secret_rotation_period_days", etiquetas: { segredo }, valor: prazoDias });
    if (idadeDias !== null) {
      saida.push({ nome: "secret_age_days", etiquetas: { segredo }, valor: idadeDias });
    }
  }
  return saida;
}
