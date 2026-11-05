/**
 * A reconciliação nocturna: classifica órfãos e recursos em falta (KAM-091,
 * critério 8).
 *
 * Compara `tenants` com estado ≠ `encerrado` contra o que está lá fora — contas
 * de atendimento, chaves do LiteLLM, canais de comércio e `tenant_channels` — e
 * classifica cada divergência numa de duas classes:
 *
 * - **`orfao_externo`**: está lá fora e nenhum tenant vivo o reclama.
 * - **`externo_em_falta`**: um tenant vivo tem o passo `concluido` e lá fora
 *   não está.
 *
 * ## Porque são duas classes e não um número
 *
 * Porque a acção é **oposta**. Um órfão compensa-se (se for nosso e o caso
 * estiver cancelado há mais de 24 h); um recurso em falta **recria-se**,
 * correndo a saga outra vez. Um contador único de «divergências» levava quem o
 * lesse a limpar o que faltava — e o que falta não se limpa, cria-se.
 *
 * ## As três condições da compensação automática, e porque são três
 *
 * O critério 8 diz: «compensa automaticamente **só** recursos de casos
 * `cancelado` há > 24 h (*proposta*) e **apenas** os criados por esta saga
 * (etiqueta)». São três filtros e nenhum é redundante:
 *
 * 1. **`orfao_externo`** — nunca se compensa um `externo_em_falta`, que não
 *    está lá para ser compensado.
 * 2. **`nosso`** (a `ETIQUETA_DA_SAGA`) — sem ela, uma noite de reconciliação
 *    apagava uma conta que a equipa criou à mão no Chatwoot para suporte. É o
 *    filtro que distingue «órfão» de «não é nosso».
 * 3. **caso `cancelado` há > 24 h** — um recurso cujo caso ainda está em
 *    `provisionando` **não é órfão**: é um passo a decorrer. Compensá-lo era a
 *    reconciliação a desfazer a saga enquanto ela corre, e as duas correm à
 *    mesma hora numa noite com falha injectada.
 *
 * O limiar de 24 h é ***proposta*** e está por calibrar no Piloto, como todos
 * os limiares deste epic.
 */

import {
  ETIQUETA_DA_SAGA,
  type Caso,
  type ClasseDeDivergencia,
  type Divergencia,
  type InventarioExterno,
  type LeitorDeCasos,
  type RecursoInventariado,
  type RelatorioDeReconciliacao,
} from "./contrato.ts";
import { METRICA_COMPENSADO, Metricas, METRICAS } from "./metricas.ts";
import type { Logger } from "../logger/index.ts";

/** O limiar do critério 8, em horas. ***Proposta***, calibra-se no Piloto. */
export const HORAS_PARA_COMPENSAR = 24;

/** O que um tenant vivo diz esperar lá fora: o que os passos `concluido` gravaram. */
export interface EsperadoDoTenant {
  readonly tenantId: string;
  /** As referências externas que o `provisioning_step` tem como `concluido`. */
  readonly refs: readonly { readonly recurso: RecursoInventariado["recurso"]; readonly ref: string }[];
}

export interface Dependencias {
  readonly casos: LeitorDeCasos;
  readonly inventario: InventarioExterno;
  /** O que os passos `concluido` dos tenants vivos dizem existir. */
  esperado(): Promise<readonly EsperadoDoTenant[]>;
  /** Desfaz um recurso órfão. Recebe a acção já classificada e autorizada. */
  compensarOrfao(recurso: RecursoInventariado): Promise<void>;
  readonly log?: Logger;
  readonly metricas?: Metricas;
}

/**
 * Classifica. **Pura**, e é de propósito.
 *
 * A classificação é a substância do critério 8 e não precisa de base de dados,
 * de rede nem de relógio para ser medida: recebe os dois lados e devolve as
 * divergências. O que precisa de mundo é a compensação, e essa é a outra
 * função. Separá-las deixa a classificação provável com uma tabela de casos —
 * incluindo o que o critério pede explicitamente: «recurso não criado por nós é
 * **ignorado**».
 *
 * @param foraDeCa o que o inventário externo listou
 * @param esperado o que os tenants vivos têm como `concluido`
 */
export function classificar(
  foraDeCa: readonly RecursoInventariado[],
  esperado: readonly EsperadoDoTenant[],
): readonly Divergencia[] {
  const vivos = new Set(esperado.map((e) => e.tenantId));
  const esperadas = new Set<string>();
  for (const e of esperado) for (const r of e.refs) esperadas.add(`${r.recurso}:${r.ref}`);

  const presentes = new Set(foraDeCa.map((r) => `${r.recurso}:${r.ref}`));
  const divergencias: Divergencia[] = [];

  // ------------------------------------------------- lá fora e ninguém reclama
  for (const recurso of foraDeCa) {
    if (esperadas.has(`${recurso.recurso}:${recurso.ref}`)) continue;
    // **Um recurso de um tenant vivo que ainda não está no `provisioning_step`
    // não é órfão.** É a janela do critério 4 vista do outro lado: o recurso
    // existe lá fora e o `markDone` não gravou. Classificá-lo como órfão fazia
    // a reconciliação apagar o que a saga acabou de criar e está a meio de
    // registar — e as duas correm à mesma hora.
    if (recurso.tenantId !== null && vivos.has(recurso.tenantId)) continue;
    divergencias.push({
      classe: "orfao_externo",
      recurso: recurso.recurso,
      ref: recurso.ref,
      tenantId: recurso.tenantId,
      nosso: recurso.nosso,
      compensado: false,
    });
  }

  // ------------------------------------------------- esperado e não está lá
  for (const e of esperado) {
    for (const r of e.refs) {
      if (presentes.has(`${r.recurso}:${r.ref}`)) continue;
      divergencias.push({
        classe: "externo_em_falta",
        recurso: r.recurso,
        ref: r.ref,
        tenantId: e.tenantId,
        // O que falta lá fora foi criado por nós por definição: está no nosso
        // `provisioning_step` como `concluido`.
        nosso: true,
        compensado: false,
      });
    }
  }

  return divergencias;
}

/**
 * Decide se uma divergência se compensa automaticamente. **Pura.**
 *
 * As três condições da nota do módulo, nesta ordem. Separada para que o ensaio
 * possa medir cada uma a negar sozinha — um predicado composto testado só pelo
 * caso verdadeiro passa com qualquer das três apagadas.
 */
export function compensavel(
  divergencia: Divergencia,
  canceladosHaMais: ReadonlySet<string>,
): boolean {
  if (divergencia.classe !== "orfao_externo") return false;
  if (!divergencia.nosso) return false;
  if (divergencia.tenantId === null) return false;
  return canceladosHaMais.has(divergencia.tenantId);
}

/** Corre a reconciliação nocturna inteira. */
export async function reconciliar(d: Dependencias): Promise<RelatorioDeReconciliacao> {
  const m = d.metricas ?? METRICAS;
  const [foraDeCa, esperado, cancelados] = await Promise.all([
    d.inventario.listar(),
    d.esperado(),
    d.casos.canceladosHaMaisDe(HORAS_PARA_COMPENSAR),
  ]);
  const canceladosHaMais = new Set(cancelados.map((c: Caso) => c.tenantId));

  const classificadas = classificar(foraDeCa, esperado);
  const finais: Divergencia[] = [];
  for (const divergencia of classificadas) {
    if (!compensavel(divergencia, canceladosHaMais)) {
      finais.push(divergencia);
      continue;
    }
    try {
      await d.compensarOrfao({
        recurso: divergencia.recurso,
        ref: divergencia.ref,
        tenantId: divergencia.tenantId,
        nosso: divergencia.nosso,
      });
      m.contar(METRICA_COMPENSADO, divergencia.recurso);
      finais.push({ ...divergencia, compensado: true });
    } catch (erro) {
      // Uma compensação que falha **não** pára as outras aqui, ao contrário da
      // compensação da saga. A diferença é que estes recursos são
      // independentes: são órfãos de casos diferentes, sem ordem entre si, e
      // nenhum é a credencial com que outro se desfaz. Na saga a ordem é a
      // substância (critério 3); aqui não há ordem.
      // Só os campos da lista branca: o recurso vai no `error_code` e não num
      // campo próprio. Sem `tenant_id` aqui de propósito — a reconciliação
      // atravessa tenants e a linha é da plataforma, não de uma loja.
      d.log?.excepcao(erro, `reconciliacao_falhou_${divergencia.recurso}`, {
        outcome: "orfao_nao_compensado",
      });
      finais.push(divergencia);
    }
  }

  const orfaos = finais.filter((x) => x.classe === "orfao_externo" && !x.compensado).length;
  const emFalta = finais.filter((x) => x.classe === "externo_em_falta").length;
  m.medirDivergencias({ orfao_externo: orfaos, externo_em_falta: emFalta });
  return {
    divergencias: finais,
    orfaos,
    emFalta,
    compensados: finais.filter((x) => x.compensado).length,
  };
}

export { ETIQUETA_DA_SAGA };
