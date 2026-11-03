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
 * `order_reconciliation_issues`. **E hoje é só isso**, em todas as cinco
 * regras.
 *
 * ## Nenhuma regra tem correcção local, e a razão é por regra
 *
 * A primeira versão deste ficheiro dizia «e, na regra 1, completa o espelho», e
 * tinha um `corrigir` que **nunca corria**: a regra 1 empurra sempre
 * `orderId: null` — é a regra do espelho que **não tem** a linha —, e o
 * `corrigir` saía antes de chegar à `transition`. Código morto, e três sítios a
 * afirmar o contrário. Apanhado pela revisão adversarial; o ramo morto saiu.
 *
 * Regra a regra, e com o credor de cada correcção:
 *
 * ```text
 * 1 orfao_no_registo      completar o espelho é **criar a encomenda** a partir
 *                         das linhas do Registo: é a `createOrder` do §6.3, com
 *                         o recibo de intenção e os preços resolvidos — KAM-046.
 *                         Inventá-la aqui era escrever um `lines_snapshot` que
 *                         nenhum cliente confirmou, e o snapshot é imutável a
 *                         partir daí
 * 2 espelho_sem_encomenda alerta crítico, e **não** correcção: apagar o espelho
 *                         porque o Registo não o tem era deixar o Registo
 *                         decidir o que o §10.1 lhe recusa
 * 3 divergencia_de_linhas vence o `lines_snapshot`, que já está escrito: a
 *                         correcção é do lado do Registo
 * 4 reserva_sem_encomenda libertar ou refazer a reserva é `releaseReservation` /
 *                         `reserveStock` — KAM-045
 * 5 estado_divergente     vence `orders_mirror`, que já está escrito: o que se
 *                         actualiza é o **Registo**
 * ```
 *
 * As quatro correcções que sobram tocam todas o Registo, passam pela porta
 * `CommerceRegistry` e ficam **NÃO VERIFICADAS** enquanto não houver Medusa em
 * `infra/compose/` contra o que as correr. O que este ticket entrega da AC-7 é
 * a **decisão** das cinco regras (medida, função pura), a escrita da
 * divergência e a consulta da métrica.
 *
 * ## E a reconciliação nunca poderia escrever `paga`
 *
 * Vale a pena deixar dito, porque é o que alguém tentaria a seguir: o espelho é
 * **a autoridade do ciclo de vida** (§10.1) e `paga` só é alcançável por evento
 * autenticado do PAY (ADR-013, critério 3). Um Registo a dizer «esta encomenda
 * está paga» é uma projecção, não um pagamento. O *trigger* diferido garante-o
 * — uma transição para `paga` com `causa='reconciliacao'` levanta `KA006` —, e o
 * `test_reconciliacao` mede-o.
 */

import type { LinhaDaEncomenda, OrderState } from "./contrato.ts";
import {
  SQL_DIVERGENCIAS_ABERTAS,
  SQL_FECHAR_DIVERGENCIA,
} from "./consultas.ts";
import type { Encomendas } from "./transition.ts";

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
  /**
   * As linhas **com preço**, e a primeira versão não o tinha.
   *
   * Sem o `precoMinor`, duas linhas com os mesmos `sku`/`qty`, preços unitários
   * diferentes e um total que coincide passavam sem divergência — e a regra 3 é
   * precisamente a que decide **em dinheiro** a favor do `lines_snapshot`. O
   * §10.3 diz «divergência de total **ou de linhas**», e o preço é parte da
   * linha. Apanhado pela revisão adversarial.
   */
  readonly linhas: readonly {
    readonly sku: string;
    readonly qty: number;
    readonly precoMinor: bigint;
  }[];
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

/**
 * Os estados em que uma encomenda tem reserva activa (§10.3, regra 4).
 *
 * **Dois e não um**, e a primeira versão tinha um — o que punha **toda**
 * encomenda em `pendente_confirmacao` com reserva viva a produzir uma
 * `reserva_sem_encomenda`, contra uma métrica que é «divergências abertas > 5
 * min = 0». A própria revisão `0030` diz quais são, no índice parcial do
 * varrimento de expiração: `WHERE estado IN ('aguarda_pagamento',
 * 'pendente_confirmacao')`. E o grafo tem `pendente_confirmacao →
 * aguarda_pagamento`, isto é, a encomenda vai e volta sem perder a reserva.
 *
 * Apanhado pela revisão adversarial, como inconsistência interna ao próprio
 * diff.
 */
const COM_RESERVA: readonly OrderState[] = [
  "aguarda_pagamento",
  "pendente_confirmacao",
];

/**
 * As linhas como `(sku, qty, preço)` ordenado, para comparar.
 *
 * **O preço entra na assinatura**, pela razão escrita no `EncomendaNoRegisto`:
 * sem ele, a regra 3 não via a divergência que é só de dinheiro.
 */
function assinaturaDasLinhas(
  linhas: readonly {
    readonly sku: string;
    readonly qty: number;
    readonly precoMinor: bigint;
  }[],
): string {
  return [...linhas]
    .map((l) => `${l.sku}:${l.qty}:${l.precoMinor}`)
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
    if (encomenda === undefined || !COM_RESERVA.includes(encomenda.estado)) {
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
    if (COM_RESERVA.includes(encomenda.estado) && !comReserva.has(encomenda.orderId)) {
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
    feitas.push({ divergencia, issueId: String(linhas[0]?.["id"]) });
  }
  return feitas;
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
