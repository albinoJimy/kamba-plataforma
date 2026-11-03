/**
 * A reconciliação Registo ↔ espelho: as cinco regras de §10.3 (critério 7).
 *
 * ```text
 * 1 orfao_no_registo        encomenda no Registo sem linha no espelho  -> completar
 * 2 espelho_sem_encomenda   espelho com medusa_order_id sem Registo    -> alerta critico
 * 3 divergencia_de_linhas   total ou linhas != lines_snapshot          -> vence o snapshot
 * 4 reserva_sem_encomenda   reserva activa sem aguarda_pagamento       -> corrigir pelo COM
 * 5 estado_divergente       estado do Registo != estado do espelho     -> vence o espelho
 * ```
 *
 * ## A decisão é **pura** e a escrita é separada
 *
 * `reconciliar` não toca na base nem no Registo: recebe as duas fotografias e
 * devolve as divergências. É o que torna as cinco regras mediáveis sem
 * PostgreSQL e sem Medusa — e **não haver Medusa é um facto**, não uma
 * conveniência: o KAM-042 registou que «o Registo da opção B é um Medusa que não
 * existe em `infra/compose/`», e o KAM-043 repetiu-o. Uma regra escrita dentro
 * de um cliente HTTP que ninguém pode correr era uma regra não medida.
 *
 * `aplicar` escreve o que é **local**: abre a divergência em
 * `order_reconciliation_issues` e, na regra 1, completa o espelho. As
 * correcções que tocam o Registo — a projecção do estado da regra 5, a
 * libertação da reserva da regra 4 — passam pela porta `CommerceRegistry`, e
 * ficam **NÃO VERIFICADAS** enquanto não houver Registo contra o que as correr.
 * Está dito aqui e na verificação do bloco.
 *
 * ## A regra 1 não pode escrever `paga`, e isso é a regra e não um limite
 *
 * «Completar» o espelho de uma encomenda que o Registo tem e o espelho não é
 * inserir a linha e levá-la ao estado que o Registo implica. Só que o espelho é
 * **a autoridade do ciclo de vida** (§10.1) e `paga` só é alcançável por evento
 * autenticado do PAY (ADR-013, critério 3): um Registo a dizer «esta encomenda
 * está paga» não é um pagamento autenticado — é uma projecção, e a matriz de
 * §10.1 diz que o estado de pagamento é do PAY e que «o COM só aplica».
 *
 * Por isso a reconciliação completa até onde o grafo a deixa com causa
 * `reconciliacao` e, se o Registo reclamar `paga` ou um estado a jusante,
 * **pára e deixa a divergência aberta**. É o *trigger* diferido que o garante —
 * uma tentativa de escrever `paga` com `causa='reconciliacao'` levanta `KA006` —,
 * e o `test_reconciliacao` mede as duas metades.
 */

import {
  CAUSA_DA_RECONCILIACAO,
  type LinhaDaEncomenda,
  type OrderState,
} from "./contrato.ts";
import {
  SQL_DIVERGENCIAS_ABERTAS,
  SQL_FECHAR_DIVERGENCIA,
} from "./consultas.ts";
import type { Encomendas } from "./transition.ts";
import { transition } from "./transition.ts";

/** A tabela das divergências. */
export const TABELA_DAS_DIVERGENCIAS = "order_reconciliation_issues";

/** Os cinco tipos, pela ordem em que o §10.3 escreve as regras. */
export const TIPOS_DE_DIVERGENCIA = [
  "orfao_no_registo",
  "espelho_sem_encomenda",
  "divergencia_de_linhas",
  "reserva_sem_encomenda",
  "estado_divergente",
] as const;
export type TipoDeDivergencia = (typeof TIPOS_DE_DIVERGENCIA)[number];

/** A encomenda como o Registo a projecta. */
export interface EncomendaNoRegisto {
  readonly intentKey: string;
  readonly registoId: string;
  /** O estado que o Registo projecta, ou `null` se não projectar nenhum. */
  readonly estado: OrderState | null;
  readonly totalMinor: bigint;
  readonly linhas: readonly { readonly sku: string; readonly qty: number }[];
}

/** A encomenda como o espelho a tem. */
export interface EncomendaNoEspelho {
  readonly orderId: string;
  readonly intentKey: string;
  readonly medusaOrderId: string | null;
  readonly estado: OrderState;
  readonly version: number;
  readonly totalMinor: bigint;
  readonly linhas: readonly LinhaDaEncomenda[];
}

/** Uma reserva activa, como o Registo a tem. */
export interface ReservaNoRegisto {
  readonly orderId: string;
  readonly sku: string;
}

/** O que `reconciliar` devolve: uma divergência por regra disparada. */
export interface Divergencia {
  readonly tipo: TipoDeDivergencia;
  /** `null` na regra 1, onde o espelho ainda não tem linha. */
  readonly orderId: string | null;
  /** O que divergia. **Sem PII**: chaves, SKUs, totais e estados. */
  readonly detalhe: Readonly<Record<string, unknown>>;
}

/** As duas fotografias e as reservas, no instante da passagem. */
export interface Fotografia {
  readonly registo: readonly EncomendaNoRegisto[];
  readonly espelho: readonly EncomendaNoEspelho[];
  readonly reservas: readonly ReservaNoRegisto[];
}

/** O estado em que uma encomenda tem reserva activa (§10.3, regra 4). */
const COM_RESERVA: OrderState = "aguarda_pagamento";

/** Os estados que já não são alcançáveis por reconciliação. Ver a nota. */
const ALEM_DA_RECONCILIACAO: readonly OrderState[] = [
  "paga",
  "em_entrega",
  "entrega_falhada",
  "entregue",
  "em_disputa",
  "reembolso_pendente",
  "reembolsada",
];

/** As linhas de uma encomenda como par ordenado `(sku, qty)`, para comparar. */
function assinaturaDasLinhas(
  linhas: readonly { readonly sku: string; readonly qty: number }[],
): string {
  return [...linhas]
    .map((l) => `${l.sku}:${l.qty}`)
    .sort()
    .join("|");
}

/**
 * As cinco regras, sobre as duas fotografias. Função pura.
 *
 * A ordem das divergências devolvidas é a das regras, e não a dos dados: quem
 * as aplica trata primeiro o que completa o espelho (regra 1), porque as outras
 * quatro falam de linhas que já existem.
 */
export function reconciliar(foto: Fotografia): readonly Divergencia[] {
  const divergencias: Divergencia[] = [];
  const porIntentKey = new Map(foto.espelho.map((o) => [o.intentKey, o]));
  const registoPorId = new Map(foto.registo.map((o) => [o.registoId, o]));
  const porOrderId = new Map(foto.espelho.map((o) => [o.orderId, o]));

  // Regra 1: no Registo e não no espelho.
  for (const encomenda of foto.registo) {
    if (!porIntentKey.has(encomenda.intentKey)) {
      divergencias.push({
        tipo: "orfao_no_registo",
        orderId: null,
        detalhe: {
          intent_key: encomenda.intentKey,
          registo_id: encomenda.registoId,
          estado_no_registo: encomenda.estado,
        },
      });
    }
  }

  // Regra 2: no espelho, com id do Registo, e o Registo não a tem. **Alerta
  // crítico** e não correcção: o espelho é a autoridade do ciclo de vida, e
  // apagá-lo por o Registo não a ter era deixar o Registo decidir o que o §10.1
  // lhe recusa.
  for (const encomenda of foto.espelho) {
    if (
      encomenda.medusaOrderId !== null &&
      !registoPorId.has(encomenda.medusaOrderId)
    ) {
      divergencias.push({
        tipo: "espelho_sem_encomenda",
        orderId: encomenda.orderId,
        detalhe: {
          medusa_order_id: encomenda.medusaOrderId,
          estado: encomenda.estado,
          critico: true,
        },
      });
    }
  }

  // Regras 3 e 5, sobre as que existem nos dois.
  for (const encomenda of foto.espelho) {
    const noRegisto = foto.registo.find(
      (o) => o.intentKey === encomenda.intentKey,
    );
    if (noRegisto === undefined) continue;

    const assinaturaDoEspelho = assinaturaDasLinhas(encomenda.linhas);
    const assinaturaDoRegisto = assinaturaDasLinhas(noRegisto.linhas);
    if (
      encomenda.totalMinor !== noRegisto.totalMinor ||
      assinaturaDoEspelho !== assinaturaDoRegisto
    ) {
      divergencias.push({
        tipo: "divergencia_de_linhas",
        orderId: encomenda.orderId,
        detalhe: {
          // **Vence o `lines_snapshot`** (§10.3, regra 3): é o que o cliente
          // confirmou no instante da encomenda, e é imutável desde
          // `aguarda_pagamento`.
          vence: "lines_snapshot",
          total_no_espelho: encomenda.totalMinor.toString(),
          total_no_registo: noRegisto.totalMinor.toString(),
          linhas_no_espelho: assinaturaDoEspelho,
          linhas_no_registo: assinaturaDoRegisto,
        },
      });
    }

    if (noRegisto.estado !== null && noRegisto.estado !== encomenda.estado) {
      divergencias.push({
        tipo: "estado_divergente",
        orderId: encomenda.orderId,
        detalhe: {
          // **Vence `orders_mirror`** (§10.3, regra 5): o Registo é
          // actualizado, e é a matriz de §10.1 à letra.
          vence: "orders_mirror",
          estado_no_espelho: encomenda.estado,
          estado_no_registo: noRegisto.estado,
        },
      });
    }
  }

  // Regra 4: reserva activa sem encomenda em `aguarda_pagamento` — **e o
  // contrário**, que o §10.3 escreve entre parênteses («ou vice-versa») e que
  // uma leitura apressada deixa cair.
  const comReserva = new Set(foto.reservas.map((r) => r.orderId));
  for (const reserva of foto.reservas) {
    const encomenda = porOrderId.get(reserva.orderId);
    if (encomenda === undefined || encomenda.estado !== COM_RESERVA) {
      divergencias.push({
        tipo: "reserva_sem_encomenda",
        orderId: encomenda === undefined ? null : encomenda.orderId,
        detalhe: {
          sku: reserva.sku,
          order_id_da_reserva: reserva.orderId,
          estado: encomenda?.estado ?? null,
          sentido: "reserva_sem_estado",
        },
      });
    }
  }
  for (const encomenda of foto.espelho) {
    if (encomenda.estado === COM_RESERVA && !comReserva.has(encomenda.orderId)) {
      divergencias.push({
        tipo: "reserva_sem_encomenda",
        orderId: encomenda.orderId,
        detalhe: {
          estado: encomenda.estado,
          sentido: "estado_sem_reserva",
        },
      });
    }
  }

  return divergencias;
}

/** O que `aplicar` fez, por divergência. */
export interface Aplicacao {
  readonly divergencia: Divergencia;
  /** O id da linha de `order_reconciliation_issues`. */
  readonly issueId: string;
  /**
   * `true` quando a correcção local correu; `false` quando ficou só a
   * divergência aberta — o que é o caso das regras 2, 3, 4 e 5, e da 1 quando o
   * Registo reclama um estado que a reconciliação não pode escrever.
   */
  readonly corrigida: boolean;
}

/**
 * Abre as divergências e corrige o que é local.
 *
 * As correcções que tocam o Registo passam pela porta e **não** estão aqui: ver
 * a nota do módulo. O que fica garantido é o que o critério 7 pede por escrito —
 * as cinco regras cobertas, a divergência registada, e a causa
 * `reconciliacao` em toda a transição que a reconciliação provoque.
 */
export async function aplicar(
  e: Encomendas,
  divergencias: readonly Divergencia[],
): Promise<readonly Aplicacao[]> {
  const feitas: Aplicacao[] = [];
  for (const divergencia of divergencias) {
    // **Pelo repo-base e não pela porta estreita**, e a diferença é quem
    // escreve o `tenant_id`: o `inserirNoTenant` constrói o `INSERT` com a
    // coluna do filtro, e a porta estreita existe para chamadas de função
    // (`evt_emitir`, `ten_tecto`), que não têm `WHERE` nem coluna de tenant.
    // Abrir uma divergência por lá era um `INSERT` cujo `tenant_id` vem do
    // chamador — o caminho que a revisão adversarial do KAM-042 fechou.
    const linhas = await e.repo.inserirNoTenant({
      tabela: TABELA_DAS_DIVERGENCIAS,
      valores: {
        order_id: divergencia.orderId,
        tipo: divergencia.tipo,
        detalhe: JSON.stringify(divergencia.detalhe),
      },
      sufixo: "RETURNING id",
    });
    const issueId = String(linhas[0]?.["id"]);
    feitas.push({
      divergencia,
      issueId,
      corrigida: await corrigir(e, divergencia),
    });
  }
  return feitas;
}

/**
 * A correcção local de uma divergência, quando existe.
 *
 * Só a regra 5 tem correcção local possível hoje, e é a **inversa** do que o
 * nome sugere: «vence `orders_mirror`» quer dizer que é o **Registo** que se
 * actualiza, e isso é do outro lado da porta. O que esta função faz é o caso da
 * regra 1 descrito na nota do módulo.
 */
async function corrigir(e: Encomendas, divergencia: Divergencia): Promise<boolean> {
  if (divergencia.tipo !== "orfao_no_registo") return false;
  const alvo = divergencia.detalhe["estado_no_registo"];
  if (typeof alvo !== "string") return false;
  if (ALEM_DA_RECONCILIACAO.includes(alvo as OrderState)) {
    // O Registo reclama um estado que a reconciliação não pode escrever. A
    // divergência fica aberta e é a métrica do bloco que a vê.
    return false;
  }
  const orderId = divergencia.orderId;
  if (orderId === null) {
    // A linha ainda não existe: quem a cria é a `createOrder` do KAM-046, com
    // as linhas resolvidas pelo Registo. A reconciliação **não** inventa
    // linhas de encomenda — inventá-las era escrever um `lines_snapshot` que
    // nenhum cliente confirmou, e o snapshot é imutável a partir daí.
    return false;
  }
  const r = await transition(e, {
    orderId,
    para: alvo as OrderState,
    expectedVersion: 1,
    causa: { causa: CAUSA_DA_RECONCILIACAO },
  });
  return r.tipo === "ok";
}

/**
 * Fecha uma divergência resolvida. A métrica é «abertas > 5 min = 0».
 *
 * Pelo repo-base: o `SQL_FECHAR_DIVERGENCIA` tem `tenant_id = $1` depois do
 * primeiro `WHERE`, que é o que ele exige, pelo que o `$1` é injectado e o
 * `issueId` entra como `$2`.
 */
export async function fechar(e: Encomendas, issueId: string): Promise<boolean> {
  const linhas = await e.repo.noTenant(SQL_FECHAR_DIVERGENCIA, [issueId]);
  return linhas.length > 0;
}

/** As divergências abertas de um tenant, as mais antigas primeiro. */
export async function abertas(
  e: Encomendas,
): Promise<readonly Readonly<Record<string, unknown>>[]> {
  return e.repo.noTenant(SQL_DIVERGENCIAS_ABERTAS, []);
}
