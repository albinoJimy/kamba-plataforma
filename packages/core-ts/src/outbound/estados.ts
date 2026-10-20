/**
 * Ingestão monótona de estados e contagem de custo (KAM-015, critérios 3 e 4).
 *
 * ## A monotonia, e porque é que não é uma comparação de números
 *
 * O critério 3: «`delivered` seguido de `sent` mantém `delivered`; `failed` é
 * terminal; duplicados do mesmo estado são *no-op*». A Meta entrega os
 * `statuses` **sem ordem garantida e com entrega concorrente** (CONFIRMADO,
 * `E1` §5), pelo que a ordem de chegada não é a ordem dos acontecimentos.
 *
 * A tentação é dar um número a cada estado e comparar. Não serve, e o
 * `ORDEM_DOS_ESTADOS` do contrato explica-o: `failed` e `suppressed_by_human`
 * **não são «depois de `read`»**, são saídas. Comparar por índice daria
 * «`failed` é depois de `read`», que é verdade por acidente, e
 * «`suppressed_by_human` é depois de `failed`», que não é verdade nenhuma.
 *
 * Por isso há três regras e não uma:
 *
 * 1. de um estado **terminal** não se sai — nem para outro terminal;
 * 2. para um estado terminal vai-se de qualquer estado não-terminal;
 * 3. entre os não-terminais, avança-se pela ordem e nunca para trás.
 *
 * ## O custo conta-se na entrega, e uma vez
 *
 * CONFIRMADO (`E1` §1): a cobrança é por mensagem **entregue**, não por
 * mensagem enviada. Logo o custo soma-se quando um `delivered` **novo** chega —
 * e «novo» é a palavra que faz o trabalho: um `delivered` repetido não soma
 * outra vez, e é por isso que o custo se decide a partir da **transição** e não
 * do estado.
 *
 * Um `read` que chegue depois de um `delivered` não soma nada: é a mesma
 * mensagem entregue. Um `read` que chegue **antes** de um `delivered` (a ordem
 * não é garantida) soma, porque ler implica ter sido entregue — e o
 * `delivered` que chegar depois já não avança o estado, logo não soma segunda
 * vez. Esta é a parte que um teste com estados em ordem não apanha.
 */

import {
  ORDEM_DOS_ESTADOS,
  TERMINAIS,
  type Estado,
  type Pricing,
} from "./contrato.ts";
import { categoriaDesconhecida, microUsdDe } from "./tarifas.ts";

/** O que uma transição produziu. */
export interface Transicao {
  /** O estado depois da transição. Igual ao anterior quando não avançou. */
  readonly estado: Estado;
  /** `true` quando o estado mudou. */
  readonly avancou: boolean;
  /**
   * `true` quando **esta** transição é a que torna a mensagem entregue.
   *
   * É a única condição que soma custo, e é por transição e não por estado: um
   * `delivered` repetido não a tem.
   */
  readonly entregou: boolean;
}

/** `true` quando não se sai deste estado. */
export function terminal(estado: Estado): boolean {
  return TERMINAIS.includes(estado);
}

/**
 * A transição de `actual` para `recebido`, pelas três regras do módulo.
 *
 * Nunca lança: um estado que não avance é um `no-op`, não um erro. A Meta
 * reenvia, e um erro aqui transformava uma repetição normal numa falha.
 */
export function avancar(actual: Estado, recebido: Estado): Transicao {
  // Regra 1: de um terminal não se sai.
  if (terminal(actual)) {
    return { estado: actual, avancou: false, entregou: false };
  }
  // Regra 2: para um terminal vai-se de qualquer não-terminal. Não «entrega»:
  // um `failed` é o contrário de uma entrega.
  if (terminal(recebido)) {
    return { estado: recebido, avancou: true, entregou: false };
  }
  // Regra 3: entre não-terminais, só para a frente.
  const de = ORDEM_DOS_ESTADOS[actual];
  const para = ORDEM_DOS_ESTADOS[recebido];
  if (para <= de) {
    return { estado: actual, avancou: false, entregou: false };
  }
  // **A entrega conta-se ao atravessar o `delivered`**, e não ao chegar a ele.
  // Um `read` que salte o `delivered` — a Meta não garante ordem — atravessa-o,
  // e é aqui que isso se diz. Sem este `de < delivered`, uma mensagem cujo
  // `read` chegasse primeiro nunca somava custo; com um `=== "delivered"`,
  // somava duas vezes quando o `delivered` chegasse depois do `read`.
  const ordemDoDelivered = ORDEM_DOS_ESTADOS.delivered;
  const entregou = de < ordemDoDelivered && para >= ordemDoDelivered;
  return { estado: recebido, avancou: true, entregou };
}

/** O que a ingestão de um `statuses` produziu. */
export interface Ingestao extends Transicao {
  /** O custo em micro-dólares que **esta** transição acrescenta. */
  readonly microUsd: number;
  /** `true` quando o `pricing` trouxe uma categoria que não conhecemos. */
  readonly categoriaDesconhecida: boolean;
  /** `true` quando o custo foi contado dentro do *free tier* e por isso é 0. */
  readonly dentroDoFreeTier: boolean;
}

/** O que se sabe do *free tier* no momento da ingestão. */
export interface FreeTier {
  readonly usadas: number;
  readonly tecto: number;
}

/**
 * Ingere um estado e devolve a transição e o custo.
 *
 * O *free tier* entra por valor e não se actualiza aqui: quem o mantém é o
 * KAM-023. O que este módulo faz é **não contar** o que cai dentro dele, que é
 * o que o critério 4 pede («um estado com categoria *service* **acima do free
 * tier** incrementa»).
 *
 * `freeTier` a `null` significa «não sei», e nesse caso **conta-se**. É a
 * leitura conservadora: subestimar o custo é pior do que sobrestimar, porque
 * uma factura maior do que o painel é uma surpresa e o contrário é uma folga.
 */
export function ingerir(
  actual: Estado,
  recebido: Estado,
  pricing: Pricing | null,
  freeTier: FreeTier | null,
): Ingestao {
  const transicao = avancar(actual, recebido);
  if (!transicao.entregou) {
    return {
      ...transicao,
      microUsd: 0,
      categoriaDesconhecida: false,
      dentroDoFreeTier: false,
    };
  }

  const desconhecida = categoriaDesconhecida(pricing);
  // O *free tier* só se aplica a `service` (CONFIRMADO, `E1` §1: «grátis até
  // 1.000 por número e mês»). Uma `utility` dentro da janela **é paga** desde
  // 2026-10-01, e é por isso que a verificação olha para a categoria do
  // `pricing` e não só para a contagem.
  const eService = pricing !== null && pricing.category === "service";
  const dentro =
    eService && freeTier !== null && freeTier.usadas < freeTier.tecto;

  return {
    ...transicao,
    microUsd: dentro ? 0 : microUsdDe(pricing),
    categoriaDesconhecida: desconhecida,
    dentroDoFreeTier: dentro,
  };
}
