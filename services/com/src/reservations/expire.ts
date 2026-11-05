/**
 * A expiração das reservas, com a consulta final ao PAY (KAM-045).
 *
 * ```text
 * varrer   lê as vencidas (FOR UPDATE SKIP LOCKED), consulta o PAY, decide
 * decidir  função PURA: o que fazer com uma reserva vencida e um estado do PAY
 * ```
 *
 * O `decidir` é puro de propósito: é a regra do critério 5, e uma regra que só
 * se possa exercitar com um PostgreSQL e um facilitador a responder é uma regra
 * que ninguém mede nos casos que importam. O `varrer` é a casca que lê, chama e
 * escreve.
 *
 * ## A expiração **não decide pagamento**, e isso tem consequências na letra
 *
 * A caixa da Definition of Done é explícita — «a expiração não decide pagamento;
 * só consulta o PAY (ADR-013)» — e o critério 5 diz que, com pagamento
 * confirmado, «a encomenda segue para `paga` e a reserva fica `consumida`,
 * **não** expira».
 *
 * **As duas metades não se cumprem da mesma maneira, e uma delas não se cumpre
 * aqui.** O que este varrimento faz:
 *
 * ```text
 * «não expira»                 cumprido: não liberta, e a reserva fica consumida
 * «a reserva fica consumida»   cumprido: é stock, e stock é deste ticket
 * «a encomenda segue para paga» NÃO cumprido aqui, e não pode ser
 * ```
 *
 * Levar a encomenda a `paga` exige, pela revisão `0030`, um `actor_kind`
 * `sistema` **e** um `evento_id` que exista em `platform.events_consumed` — é o
 * `CONSTRAINT TRIGGER` diferido `order_estado_exige_log`, que recusa com `KA006`
 * no `COMMIT`. Um varrimento não tem evento autenticado nenhum: tem a resposta
 * de uma consulta HTTP. O `providerEventId` que o `ProviderStatus` traz **não**
 * é um `events_consumed`; quem escreve essa linha é o consumidor de eventos do
 * EVT, e o dono do consumo de `payment.*` é o **KAM-055**.
 *
 * Isto não é uma limitação a contornar: é a barreira a funcionar. Se o
 * varrimento conseguisse escrever `paga`, a caixa da DoD era falsa — haveria uma
 * via para `paga` que não passa por evento autenticado, e seria esta. Por isso o
 * varrimento **para** onde a sua autoridade acaba: protege o stock (não o
 * liberta, consome-o) e deixa o dinheiro ao caminho que o pode decidir.
 *
 * A metade «a encomenda segue para `paga`» fica **devolvida a quem escreveu o
 * critério**, com o credor nomeado: **KAM-055**, dono do consumidor de
 * `payment.confirmed`. Enquanto ele não existir, uma encomenda cujo pagamento o
 * PAY confirme na varredura fica em `aguarda_pagamento` com a reserva
 * `consumida` — que é o estado honesto: o stock está comprometido e o dinheiro
 * está por confirmar pela via que o confirma.
 *
 * ## `desconhecida` **não** liberta, e é o lado seguro do erro
 *
 * O `ProviderStatus.estado` tem seis valores, e `desconhecida` é um deles — é o
 * que sai quando o facilitador não responde ou não reconhece a referência.
 * Tratá-lo como «não pago» era deixar a indisponibilidade do PAY libertar stock
 * de encomendas pagas, que é exactamente o que o Contexto do bloco diz para não
 * fazer («a expiração **nunca** liberta stock sem consulta final ao PAY»).
 *
 * «Sem consulta» inclui «com uma consulta que não respondeu». Por isso só
 * libertam os estados que **afirmam** que não houve pagamento — `expirada`,
 * `falhada`, `cancelada` — e o `pendente`, que afirma que a cobrança existe e
 * não foi paga. O `desconhecida` **adia**: a reserva fica como está e o
 * varrimento seguinte volta a perguntar.
 *
 * O preço disso fica dito: com o PAY em baixo prolongado, as reservas vencidas
 * acumulam e o stock fica preso. É o lado seguro do erro (menos stock à venda,
 * nunca stock vendido duas vezes), e o que o resolve é um alerta sobre a idade
 * da fila — que é do **KAM-080**, dono das métricas e alertas.
 */

import type { ProviderStatus } from "@kamba/core-ts/pagamentos";

import {
  SQL_ATRASO_DA_LIBERTACAO,
  SQL_CONSUMIR,
  SQL_DEVOLVER_STOCK,
  SQL_LIBERTAR_UMA,
  SQL_VENCIDAS,
} from "./consultas.ts";
import type { MotivoDeLibertacao } from "./contrato.ts";

/**
 * Quantas reservas um varrimento leva por volta.
 *
 * **Limite e não «todas»**: o `SQL_VENCIDAS` tranca as linhas que devolve
 * (`FOR UPDATE`), e um varrimento sem limite trancava a tabela inteira numa
 * transacção só — com o *job* seguinte a esperar por ela em vez de repartir
 * trabalho com ela, que é o contrário do que o `SKIP LOCKED` existe para fazer.
 *
 * Cem é *proposta*. Calibra-se com o volume do Piloto; o que a sustenta hoje é
 * só a aritmética do critério 4 (p99 ≤ 60 s com o *job* a cada minuto exige que
 * uma volta caiba bem dentro do minuto).
 */
export const LOTE_DO_VARRIMENTO = 100;

/**
 * A consulta final ao PAY, **como porto estreito deste módulo**.
 *
 * ## Porque é que não é o `PaymentProvider` directamente
 *
 * **Achado da revisão adversarial, e era um defeito a sério.** A primeira versão
 * chamava `v.provedor.status({ orderId: vencida.orderId } as never)` — e o
 * `ProviderRef` do contrato é `{ providerId, providerChargeId?, referencia? }`.
 * O objecto passado não tinha **nenhum** desses campos, e o `as never` apagava o
 * erro de tipo. Contra um adaptador real a referência não resolveria: no melhor
 * caso `desconhecida` para sempre (nada expira nunca), no pior uma excepção que
 * o `catch` converte em `adiar` — em silêncio, e indistinguível do PAY em baixo.
 *
 * O `as never` era o sinal. Uma reserva **não conhece** um `ProviderRef`: ela
 * conhece o `order_id`, e quem sabe traduzir encomenda → referência de cobrança
 * é quem tem a `platform.payment_charges`, que é do **KAM-055**. Por isso o
 * porto recebe o que a reserva tem e devolve o que a decisão precisa, e a
 * **implementação** — que faz a tradução e chama o `PaymentProvider.status` —
 * é de quem monta o varrimento.
 *
 * É a mesma escolha do `FilaDeExpiracao` do `./scheduler.ts`, e pela mesma
 * razão: quando o contrato partilhado não responde à pergunta que este módulo
 * tem, o porto é estreito e a divergência fica escrita em vez de ser calada por
 * um `as never`.
 *
 * O tipo do resultado é o `ProviderStatus["estado"]` e não um domínio novo: os
 * seis valores são os do contrato do KAM-052, e inventar outros seis era dar
 * dois nomes à mesma coisa.
 *
 * **O `reconcile` que o Contexto do bloco nomeia não existe** no contrato — ele
 * tem `status(ref)` e o `cancelCharge?` opcional. Divergência registada na
 * emenda do dicionário deste ticket.
 */
export type ConsultaFinalAoPay = (
  vencida: Vencida,
) => Promise<ProviderStatus["estado"]>;

/** Uma reserva vencida, como o varrimento a lê. */
export interface Vencida {
  readonly reservationId: string;
  readonly tenantId: string;
  readonly orderId: string;
  readonly lineNo: number;
  readonly sku: string;
  readonly qty: number;
  readonly expiraAt: string;
  readonly confirmadaAt: string | null;
  readonly version: number;
}

/** O que fazer com uma reserva vencida. Ver o `decidir`. */
export type Desfecho =
  | { readonly tipo: "libertar"; readonly motivo: MotivoDeLibertacao }
  | { readonly tipo: "consumir"; readonly porque: "pay_confirmou" }
  | { readonly tipo: "adiar"; readonly porque: "pay_nao_respondeu" };

/**
 * **O critério 5, como função pura.** O que fazer com uma vencida e um estado.
 *
 * Ver a nota do módulo para a razão de `desconhecida` adiar e para o que
 * «consumir» cumpre e não cumpre.
 *
 * Os seis estados do `ProviderStatus` estão todos tratados, e o `switch` é
 * exaustivo de propósito: um estado novo no contrato do PAY faz o TypeScript
 * recusar este ficheiro em vez de cair num `else` que liberta.
 */
export function decidir(estado: ProviderStatus["estado"]): Desfecho {
  switch (estado) {
    case "paga":
      return { tipo: "consumir", porque: "pay_confirmou" };
    case "pendente":
    case "expirada":
    case "falhada":
      // A cobrança existe (ou existiu) e não foi paga: a reserva liberta-se
      // com `expirada`, que é o motivo do ciclo de vida e não o estado do PAY.
      return { tipo: "libertar", motivo: "expirada" };
    case "cancelada":
      // O PAY diz que a cobrança foi cancelada. O motivo da libertação é
      // `cancelada`, que é um dos três do critério 6 — e não `expirada`:
      // confundi-los perdia a razão pela qual o stock voltou, que é o que a
      // reconciliação da regra 4 do §10.3 lê.
      return { tipo: "libertar", motivo: "cancelada" };
    case "desconhecida":
      return { tipo: "adiar", porque: "pay_nao_respondeu" };
  }
}

/**
 * A reserva provisória do **critério 3**: sem `charge.issued`, liberta-se.
 *
 * Uma reserva com `confirmada_at` nulo nunca teve cobrança — pelo que não há
 * nada que o PAY possa confirmar, e consultá-lo seria perguntar por uma
 * referência que não existe (a resposta seria `desconhecida`, e o `decidir`
 * adiava-a para sempre).
 *
 * **Por isso a consulta final não se aplica às provisórias**, e isso não
 * contradiz «nunca liberta sem consulta final»: aquela regra protege uma
 * encomenda que **pode** ter sido paga, e uma sem cobrança emitida não pode.
 * Confirmá-lo pela coluna é mais forte do que confiar na ausência de referência:
 * o `confirmada_at` só fica não-nulo pelo `SQL_CONFIRMAR`, que é o consumidor
 * de `charge.issued`.
 */
export function provisoria(vencida: Vencida): boolean {
  return vencida.confirmadaAt === null;
}

/** O que o varrimento recebe. */
export interface Varrimento {
  /**
   * Corre uma instrução **sem filtro de tenant**, como o `kamba_batch`.
   *
   * Não é o repo-base: o varrimento atravessa tenants por desenho (é um *job*
   * de plataforma) e o repo-base recusaria as suas consultas por não terem
   * `tenant_id = $1`. O que o autoriza é o papel, que tem `BYPASSRLS`.
   */
  readonly semTenant: (
    sql: string,
    parametros?: readonly unknown[],
  ) => Promise<readonly Readonly<Record<string, unknown>>[]>;
  /**
   * A consulta final ao PAY. **Ausente é motivo para não libertar nada.**
   *
   * Sem ela, o varrimento **adia tudo** em vez de libertar: é a mesma regra do
   * `desconhecida`, e pela mesma razão. Um varrimento que libertasse sem
   * consultar porque ninguém lhe deu com quem consultar era precisamente o que
   * o Contexto do bloco proíbe.
   */
  readonly consultar?: ConsultaFinalAoPay;
  /** O relógio. Injectável para o ensaio do critério 3 com relógio simulado. */
  readonly agora?: () => Date;
  readonly lote?: number;
}

/** O que uma volta do varrimento fez. */
export interface Resultado {
  readonly vistas: number;
  readonly libertadas: number;
  readonly consumidas: number;
  readonly adiadas: number;
  /**
   * Libertações cujo stock **não** voltou: o `SQL_DEVOLVER_STOCK` casou zero
   * linhas porque o `stock_reservada >= $3` recusou. Ver o laço do `varrer`.
   *
   * Conta-se à parte de `libertadas` de propósito: uma libertação cujo stock
   * não voltou não é uma libertação completa, e somar as duas escondia
   * exactamente a divergência que esta contagem existe para mostrar.
   */
  readonly divergencias: number;
}

function comoVencida(linha: Readonly<Record<string, unknown>>): Vencida {
  return {
    reservationId: String(linha["id"]),
    tenantId: String(linha["tenant_id"]),
    orderId: String(linha["order_id"]),
    lineNo: Number(linha["line_no"]),
    sku: String(linha["sku"]),
    qty: Number(linha["qty"]),
    expiraAt: String(linha["expira_at"]),
    confirmadaAt:
      linha["confirmada_at"] === null ? null : String(linha["confirmada_at"]),
    version: Number(linha["version"]),
  };
}

/**
 * Uma volta do varrimento. **Idempotente, e é o critério 4.**
 *
 * «*Job* repetível (1 min) e *delayed job* por reserva são idempotentes
 * (execução dupla = 1 libertação, CAS por `version`).» Três coisas garantem-no,
 * e nenhuma delas é «o *job* corre uma vez só»:
 *
 * ```text
 * FOR UPDATE SKIP LOCKED   dois varrimentos vêem conjuntos DISJUNTOS
 * estado = 'ativa'         quem chega depois não casa linha nenhuma
 * version = $4             e se casasse, o CAS recusava
 * ```
 *
 * A primeira é a que faz dos «dois *workers* a varrer em simultâneo» dos
 * *Testes Requeridos* dois conjuntos disjuntos em vez de um a esperar pelo
 * outro; as outras duas são a barreira para o caso em que a tranca já caiu (o
 * *delayed job* da mesma reserva, numa transacção que começou depois de a
 * primeira confirmar).
 *
 * **Corre dentro da transacção de quem chama**, como todo este módulo: a tranca
 * do `FOR UPDATE` só vale até ao `COMMIT`, e um varrimento que confirmasse a
 * meio largava as linhas que ainda não tratou.
 */
export async function varrer(v: Varrimento): Promise<Resultado> {
  const agora = (v.agora ?? (() => new Date()))();
  const lote = v.lote ?? LOTE_DO_VARRIMENTO;
  const linhas = await v.semTenant(SQL_VENCIDAS, [agora.toISOString(), lote]);
  const vencidas = linhas.map(comoVencida);

  let libertadas = 0;
  let consumidas = 0;
  let adiadas = 0;
  let divergencias = 0;

  // **As encomendas já consumidas nesta volta, e isso é uma correcção.**
  //
  // O `SQL_CONSUMIR` opera por `order_id` e marca **todas** as activas da
  // encomenda; o `SQL_VENCIDAS` tranca **linhas**. Duas linhas da mesma
  // encomenda no mesmo lote faziam o `consumir` correr duas vezes — a segunda
  // casava zero linhas e, pior, pagava outra consulta ao PAY e contava
  // `consumidas += 1` outra vez, dando duas consumições para uma. Achado da
  // revisão adversarial.
  //
  // O que isto **não** resolve, e fica dito: dois varredores que levem linhas
  // **diferentes** da mesma encomenda continuam a escrever um sobre as linhas
  // que o outro tranca, e o PostgreSQL resolve isso abortando uma das voltas.
  // O `SKIP LOCKED` dá conjuntos disjuntos na **leitura** e esta escrita é por
  // agregado, pelo que a disjunção não a cobre. Fechá-lo a sério é trancar por
  // encomenda (`SELECT … FOR UPDATE` sobre o `orders_mirror`) ou varrer por
  // encomenda em vez de por linha, e as duas mudam a forma do `SQL_VENCIDAS` —
  // **NÃO VERIFICADO** se acontece com carga real, e é o que se mede antes de
  // escolher.
  const consumidasNestaVolta = new Set<string>();

  for (const vencida of vencidas) {
    if (consumidasNestaVolta.has(vencida.orderId)) continue;
    const desfecho = await desfechoDe(v, vencida);
    if (desfecho.tipo === "adiar") {
      adiadas += 1;
      continue;
    }
    if (desfecho.tipo === "consumir") {
      // Pelo `order_id`: uma encomenda paga consome as linhas todas, e
      // tratá-las uma a uma deixava a encomenda meia consumida se o varrimento
      // parasse no meio — e as outras linhas seriam libertadas na volta
      // seguinte, sobre uma encomenda que o PAY já disse estar paga.
      await v.semTenant(SQL_CONSUMIR, [vencida.tenantId, vencida.orderId]);
      consumidasNestaVolta.add(vencida.orderId);
      consumidas += 1;
      continue;
    }
    const mudadas = await v.semTenant(SQL_LIBERTAR_UMA, [
      vencida.tenantId,
      vencida.reservationId,
      desfecho.motivo,
      vencida.version,
    ]);
    if (mudadas.length === 0) {
      // O CAS recusou: outro varrimento tratou esta reserva entre a leitura e
      // a escrita. **Não é erro e não se repete** — é a idempotência a
      // funcionar, e contá-la como libertação inflacionava a métrica.
      adiadas += 1;
      continue;
    }
    const devolvidas = await v.semTenant(SQL_DEVOLVER_STOCK, [
      vencida.tenantId,
      vencida.sku,
      vencida.qty,
    ]);
    if (devolvidas.length === 0) {
      // **O predicado `stock_reservada >= $3` recusou, e isto conta-se.**
      //
      // A primeira versão descartava o resultado e contava `libertadas += 1` —
      // e o `releaseReservation` do `./reserve.ts`, para o mesmo caso, recusa a
      // operação. A assimetria era o caminho pelo qual o contador divergia **em
      // silêncio**, e no sítio em que isso é mais provável: o varrimento de
      // plataforma. Achado da revisão adversarial.
      //
      // A reserva fica `libertada` (terminal, irreversível pelo `KA009`) e o
      // `stock_reservada` não desceu: é o lado menos mau da divergência (menos
      // stock à venda do que há), e é **reconstruível** pela reconciliação da
      // regra 4 do §10.3 — mas só se alguém a registar. Conta-se à parte de
      // `libertadas`, porque uma libertação cujo stock não voltou não é uma
      // libertação completa.
      //
      // **Não se tenta emendar aqui**, pela razão que o `releaseReservation`
      // escreve: o módulo não sabe qual dos dois lados está certo.
      divergencias += 1;
      continue;
    }
    libertadas += 1;
  }

  return {
    vistas: vencidas.length,
    libertadas,
    consumidas,
    adiadas,
    divergencias,
  };
}

/**
 * O desfecho de uma vencida: a provisória sem consulta, as outras com ela.
 *
 * Ver o `provisoria` para a razão de a consulta final não se aplicar a uma
 * reserva sem cobrança, e o `Varrimento.provedor` para a razão de a ausência de
 * provedor adiar em vez de libertar.
 */
async function desfechoDe(v: Varrimento, vencida: Vencida): Promise<Desfecho> {
  if (provisoria(vencida)) {
    // **O critério 3.** Sem `charge.issued` em dois minutos, liberta-se — e o
    // motivo é `expirada`, que é o do prazo e não o de um cancelamento.
    return { tipo: "libertar", motivo: "expirada" };
  }
  if (v.consultar === undefined) {
    return { tipo: "adiar", porque: "pay_nao_respondeu" };
  }
  let estado: ProviderStatus["estado"];
  try {
    estado = await v.consultar(vencida);
  } catch {
    // Uma excepção da consulta é indistinguível de `desconhecida` para esta
    // decisão, e trata-se igual: **adia**. Deixá-la subir abortava a
    // transacção e com ela as reservas que a volta já tratou.
    return { tipo: "adiar", porque: "pay_nao_respondeu" };
  }
  return decidir(estado);
}

/**
 * O `reservation_release_lag` do critério 4, lido da base.
 *
 * Devolve os atrasos em segundos, **ordenados**, para que quem chama calcule o
 * percentil que quiser. Não devolve o p99 calculado: o critério pede «p99 ≤
 * 60 s» e o cálculo de um percentil sobre uma amostra pequena depende da
 * convenção de interpolação — devolver a amostra deixa a convenção visível em
 * quem a usa em vez de a esconder aqui.
 *
 * Ver o `SQL_ATRASO_DA_LIBERTACAO` para a razão de se medir sobre a base e não
 * no processo.
 */
export async function atrasosDaLibertacao(
  v: Varrimento,
  desde: Date,
): Promise<readonly number[]> {
  const linhas = await v.semTenant(SQL_ATRASO_DA_LIBERTACAO, [
    desde.toISOString(),
  ]);
  return linhas.map((linha) => Number(linha["atraso_s"]));
}

/**
 * O percentil de uma amostra **já ordenada**, pelo método do mais próximo.
 *
 * `p` em [0, 1]. Com amostra vazia devolve `null` e não zero: zero era um
 * atraso que ninguém mediu, e num critério «p99 ≤ 60 s» um zero inventado
 * passava a caixa sem nenhuma libertação ter acontecido.
 */
export function percentil(
  ordenados: readonly number[],
  p: number,
): number | null {
  if (ordenados.length === 0) return null;
  const indice = Math.ceil(p * ordenados.length) - 1;
  const limitado = Math.min(Math.max(indice, 0), ordenados.length - 1);
  return ordenados[limitado] as number;
}
