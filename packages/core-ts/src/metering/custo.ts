/**
 * As contas do *free tier*: estimativa de custo, rácio, flanco e suspeita
 * (KAM-023, critérios 3, 4, 5 e 7).
 *
 * Tudo aqui é função pura. O estado vive na base (`consultas.ts`) e o que este
 * módulo faz é decidir, a partir de números, o que se avisa e quanto se
 * estima. É a divisão que o `estados.ts` do KAM-015 já usa, e serve a mesma
 * finalidade: estas regras provam-se sem base de dados, e o que precisa de base
 * prova-se contra uma base verdadeira.
 */

import {
  FREE_TIER_DE_SERVICE,
  MICRO_USD_POR_CATEGORIA,
} from "../outbound/index.ts";

import {
  FALHAS_PARA_SUSPEITA,
  FRACCAO_DE_AVISO,
  JANELA_DE_FALHAS,
  type Nivel,
} from "./contrato.ts";

/**
 * O número de mensagens a que se avisa: 80% do tecto.
 *
 * Derivado e não literal, para não poder divergir do tecto — ver a nota de
 * `FRACCAO_DE_AVISO`. Com o tecto de 1.000 do `E1` §1, dá **800**, que é o
 * número que o `docs/tecnica/09` (RB-K05) e o `docs/tecnica/08` §3.7 escrevem.
 *
 * `Math.floor` e não `Math.round`: avisa-se **ao atingir** 80%, e com um tecto
 * que não seja múltiplo de 5 arredondar para cima punha o aviso acima da
 * fracção que ele promete.
 */
export const AVISO_EM = Math.floor(FREE_TIER_DE_SERVICE * FRACCAO_DE_AVISO);

/**
 * O custo estimado acima do *free tier*, em micro-dólares **inteiros**.
 *
 * `max(0, n − 1000) × 4 000`, que é o critério 4 por extenso: 1.200 mensagens
 * dão 200 × 4 000 = 800 000 micro-dólares, ou seja **0,80 USD**.
 *
 * ## A unidade, outra vez, e porquê
 *
 * Micro-dólares inteiros, como o `tarifas.ts` do KAM-015 e pela mesma razão
 * medida: 0,004 não é representável em binário e somar mil vezes `0.004` em
 * `float64` **não dá 4,00**. Aqui há uma multiplicação e não uma soma, pelo que
 * a deriva seria menor — mas o número sai deste módulo para a mesma métrica e
 * para a mesma reconciliação que o do KAM-015, e dois acumuladores de custo na
 * mesma unidade é a única forma de os poder subtrair.
 *
 * ## É uma estimativa, e o nome di-lo
 *
 * O que a Meta cobra é o que vem no `pricing` de cada `statuses`; isto é o que
 * **nós** calculamos a partir do nosso contador. Os dois existem de propósito e
 * não são redundantes — é a diferença entre eles que o critério 7 mede. Ver a
 * nota de `metricas.ts` sobre `meta_cost_usd_estimate` contra
 * `meta_cost_usd_total`.
 *
 * Usa a tarifa de `service` e só essa: o *free tier* é de *service messages*
 * (CONFIRMADO, `E1` §1), e uma `utility` acima dele não entra nesta conta
 * porque nunca esteve dentro do *free tier* — desde 2026-10-01 ela é paga
 * mesmo dentro da janela.
 */
export function microUsdEstimado(usadas: number): number {
  const acima = Math.max(0, Math.trunc(usadas) - FREE_TIER_DE_SERVICE);
  return acima * MICRO_USD_POR_CATEGORIA.service;
}

/**
 * A fracção do *free tier* já consumida.
 *
 * **Não é dinheiro, e por isso é fraccionário.** O §2 do dicionário proíbe
 * vírgula flutuante em dinheiro, e a razão é a deriva de um acumulador; um
 * rácio não se acumula — calcula-se de um inteiro e mostra-se. Sobre ele não se
 * soma nada.
 *
 * **Não se limita a 1.** Um canal em 1.200/1.000 tem rácio `1,2`, e é isso que
 * se quer ver: limitar a `1` fazia um painel mostrar «100%» tanto para quem
 * acabou de esgotar como para quem vai no dobro, que é a diferença entre
 * vigiar e já estar a pagar.
 */
export function racioDoFreeTier(usadas: number): number {
  return Math.trunc(usadas) / FREE_TIER_DE_SERVICE;
}

/**
 * O nível que **este** incremento atravessou, se algum (critério 3).
 *
 * É o flanco e não o valor, e é isso que dá o «sem repetição no mesmo mês» sem
 * guardar estado nenhum: o número 800 é atravessado por exactamente um
 * incremento, e por isso o aviso sai uma vez. Um `usadas >= 800` em vez da
 * travessia avisava a cada mensagem a partir da 800.ª — duzentos avisos por
 * mês e por canal.
 *
 * `reiniciou` põe o `antes` a zero, e sem isso o reinício mensal tinha dois
 * defeitos de sinais opostos: um canal que fechou o mês em 1.500 começava o
 * seguinte com `antes = 1500`, e nenhuma travessia dos 800 era detectada todo o
 * mês; e um canal que fechou em 500 e recebesse um `depois` de 1 comparava 500
 * com 1 — sem consequência hoje, mas é a mesma confusão entre dois meses.
 *
 * O `esgotado` tem precedência sobre o `aviso` porque um incremento que
 * atravesse os dois é um incremento que esgotou — só acontece se o tecto e o
 * aviso ficarem a menos de uma mensagem de distância, mas devolver o menos
 * grave dos dois era a escolha errada.
 */
export function nivelAtingido(
  antes: number,
  depois: number,
  reiniciou: boolean,
): Nivel | null {
  const de = reiniciou ? 0 : Math.trunc(antes);
  const para = Math.trunc(depois);
  if (de < FREE_TIER_DE_SERVICE && para >= FREE_TIER_DE_SERVICE) return "esgotado";
  if (de < AVISO_EM && para >= AVISO_EM) return "aviso";
  return null;
}

/** O que se observou na janela de mensagens recentes de um canal. */
export interface Janela {
  /** Mensagens com destino já conhecido na janela. */
  readonly total: number;
  /** Quantas dessas falharam. */
  readonly falhas: number;
}

/**
 * `true` quando a taxa de falhas sugere falta de método de pagamento
 * (critério 5).
 *
 * Três condições, e as três são necessárias:
 *
 * 1. **o *free tier* está esgotado** (`usadas >= 1000`). É o que o `E1` §1
 *    torna CONFIRMADO: sem método de pagamento a Meta entrega as do *free
 *    tier* e deixa de entregar **depois**. Antes do tecto, uma rajada de
 *    falhas é outra coisa qualquer — número inválido, janela fechada, qualidade
 *    — e atribuí-la ao pagamento era mandar o dono procurar um cartão por causa
 *    de um defeito nosso;
 * 2. **a janela está cheia** (`total >= 20`). Uma falha em uma mensagem é 100%
 *    de falhas e não é sinal de nada. Sem este mínimo, o primeiro `failed` de
 *    um canal recém-esgotado disparava o alerta;
 * 3. **as falhas atingem o limiar** (`>= 4` em 20, ou seja 20%).
 *
 * Os números 20 e 4 são **proposta** — a palavra é do próprio critério — e o
 * que os calibra é o critério 7 e os códigos de erro que a detecção recolher.
 * O código concreto da falta de pagamento é **NÃO VERIFICADO** em toda a
 * evidência: o `E1` nomeia `2593109`, `130429` e `131049`, e nenhum é de
 * pagamento.
 *
 * **Isto é uma suspeita e não um diagnóstico, e o critério escreve-o assim**
 * («possível método de pagamento ausente ou inválido»). A verificação de que o
 * método existe no Billing Hub é o KAM-093; aqui só a detecção em *runtime*.
 */
export function suspeitaDePagamento(usadas: number, janela: Janela): boolean {
  if (Math.trunc(usadas) < FREE_TIER_DE_SERVICE) return false;
  if (janela.total < JANELA_DE_FALHAS) return false;
  return janela.falhas >= FALHAS_PARA_SUSPEITA;
}

/**
 * A divergência relativa entre dois contadores, em fracção.
 *
 * `null` quando o denominador é zero: dividir por zero dava `Infinity`, e um
 * `Infinity` num painel é indistinguível de uma divergência enorme. «Não sei»
 * é informação melhor do que um número errado, e é a mesma escolha que o
 * `-1` dos *gauges* do KAM-015 faz por outra razão.
 *
 * Em valor absoluto: o critério 7 pede «diverge ≤ 2%» e não diz em que
 * sentido. Contar a mais e contar a menos são os dois defeitos, e um sinal
 * fazia um deles passar o limiar por ser negativo.
 */
export function divergencia(nosso: number, medido: number): number | null {
  if (medido === 0) return null;
  return Math.abs(nosso - medido) / medido;
}
