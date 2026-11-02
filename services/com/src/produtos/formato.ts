/**
 * A apresentação de preço e de disponibilidade — funções puras (KAM-043).
 *
 * É aqui que vivem os critérios 2 e 3, e vivem em funções puras de propósito: o
 * que eles afirmam é uma correspondência entre o estado de uma linha e o texto
 * que o agente pode dizer, e isso prova-se sem base de dados, sem relógio
 * global e sem porta. O que precisa de PostgreSQL — o `CHECK`, a RLS, a
 * auditoria — está noutros ficheiros e noutra suite.
 *
 * ## Porque é que a formatação é do backend e não do modelo
 *
 * O §7.1, regra 1: «a TLS devolve `OfferView.precoDisplay` já formatado **com o
 * modo**, para o validador de citação (ADR-007) verificar que “a partir de” não
 * é citado como fixo e que `sob_consulta` não leva número». O princípio 3 do
 * `docs/tecnica/00` di-lo mais curto: «o número é prova, o texto não».
 *
 * Isso torna estas três funções a fronteira onde o preço opaco é imposto, e não
 * descrito. Um `precoDisplay` que devolvesse «12 500 Kz» para um `a_partir_de`
 * punha o validador a comparar um número certo com um modo errado — e o validador
 * **não apanha** essa classe: a nota do ADR-007 na tabela do §8 diz, por escrito,
 * que «o validador não cobre “produto errado com preço certo”». A barreira é
 * aqui.
 */

import {
  A_PARTIR_DE,
  AVISOS,
  MOEDA,
  SOB_CONSULTA,
  STOCK_POR_CONFIRMAR_MS,
  type Aviso,
  type PrecoTipo,
  type StockModo,
  type TermosDaOferta,
  type VistaDaOferta,
} from "./contrato.ts";

/**
 * O separador de milhares: **espaço fino inquebrável** (U+202F).
 *
 * Inquebrável porque «12 500» partido no fim de uma linha de WhatsApp lia-se
 * como dois números, e fino porque é a largura que a convenção PT-AO usa. Não é
 * o espaço normal (U+0020) nem o ponto: um ponto é separador **decimal** em
 * PT-AO, e «12.500 Kz» lia-se como doze vírgula quinhentos para metade dos
 * leitores.
 */
export const SEPARADOR_DE_MILHARES = " ";

/**
 * O sufixo que o cliente lê. **`Kz` e não `AOA`.**
 *
 * O código ISO é para a coluna `currency` e para o payload de um evento; o que
 * uma pessoa lê numa conversa é `Kz`. São as duas formas da mesma moeda e o
 * dicionário §3.4 fixa o código; esta constante é a apresentação dele.
 */
export const SUFIXO_DA_MOEDA = "Kz";

/** O prefixo de um preço que é mínimo e não final (§7.1). */
export const PREFIXO_A_PARTIR_DE = "a partir de ";

/** O que se diz quando não há número para dizer (critério 2). */
export const TEXTO_SOB_CONSULTA = "preço sob consulta";

/**
 * As três formas de disponibilidade (§7.3).
 *
 * As duas primeiras são a letra do §7.3 («em stock» pode ser dito; «disponível,
 * a confirmar»). A terceira é ***proposta***: o §7.3 dá o comportamento do
 * `confirmar_dono` — a encomenda fica `criada` com `confirmacao_dono='pendente'`
 * e não se emite referência — e **não dá o texto**. Este vem do diagrama de
 * sequência do mesmo §7.3, onde o AGR responde ao cliente «a confirmar com a
 * loja».
 */
export const DISPONIBILIDADE: Readonly<Record<StockModo, string>> = {
  garantido: "em stock",
  indicativo: "disponível, a confirmar",
  confirmar_dono: "a confirmar com a loja",
};

/**
 * `12500n` → `«12 500 Kz»`. Unidade menor para apresentação.
 *
 * 1 Kz = 100 cêntimos (critério 1), pelo que a unidade menor divide-se por 100.
 * A divisão é **inteira sobre `bigint`** e o resto formata-se à parte: converter
 * para `number` para dividir perdia precisão acima de 2^53 cêntimos sem avisar,
 * que é a razão pela qual `packages/core-ts/src/pagamentos/tipos.ts` declara
 * `type Minor = bigint` e pela qual o KAM-052 escreveu um *lint* para isto.
 *
 * **Os cêntimos só aparecem se não forem zero.** Um preço de «12 500,00 Kz»
 * numa conversa de WhatsApp é ruído: no comércio informal angolano os preços são
 * redondos, e mostrar duas casas em todos fazia o caso comum pagar pelo raro. Um
 * preço com cêntimos mostra-os, com a **vírgula** decimal do PT-AO.
 */
export function formatarMinor(minor: bigint): string {
  if (minor < 0n) {
    throw new RangeError(
      `preco_minor negativo: ${minor}. O offer_terms_preco_nao_negativo_ck da ` +
        "revisao 0028 recusa-o na base, pelo que uma linha com ele nao existe — " +
        "se chegou aqui, veio de um calculo e nao de uma leitura (KAM-043)",
    );
  }
  const kwanzas = minor / 100n;
  const centimos = minor % 100n;
  const inteiro = agruparMilhares(kwanzas.toString());
  const corpo =
    centimos === 0n
      ? inteiro
      : `${inteiro},${centimos.toString().padStart(2, "0")}`;
  return `${corpo}${SEPARADOR_DE_MILHARES}${SUFIXO_DA_MOEDA}`;
}

/** `"12500"` → `"12 500"`. Da direita para a esquerda, de três em três. */
function agruparMilhares(digitos: string): string {
  const grupos: string[] = [];
  for (let fim = digitos.length; fim > 0; fim -= 3) {
    grupos.unshift(digitos.slice(Math.max(0, fim - 3), fim));
  }
  return grupos.join(SEPARADOR_DE_MILHARES);
}

/**
 * O preço apresentado, **com o modo**. As três formas do critério 2.
 *
 * ```text
 * fixo         «12 500 Kz»
 * a_partir_de  «a partir de 12 500 Kz»
 * sob_consulta «preço sob consulta»
 * ```
 *
 * **O `sob_consulta` devolve texto e não `null`, e é uma divergência resolvida.**
 * O critério 2 enumera as três formas acima e põe «preço sob consulta» entre
 * elas, como valor de `precoDisplay`; o comentário do `OfferView` em
 * `port/contrato.ts` dizia «ou `null` em `sob_consulta`». Ganha o critério, por
 * duas razões e não por uma: é a letra do ticket que é dono desta implementação
 * (fonte 8), e o comentário foi escrito pelo KAM-042 — que **não** implementou o
 * `getOfferView` e disse por extenso que «a implementação é deles». Era uma
 * previsão sobre o comportamento deste método, não um contrato sobre ele. O
 * comentário fica corrigido no PR deste ticket.
 *
 * E a outra metade do critério continua verdadeira: «`sob_consulta` nunca
 * devolve número» — «preço sob consulta» não tem dígito nenhum, pelo que o
 * validador de citação (KAM-032) não encontra lá número para confrontar.
 *
 * **O tipo continua `string | null`**, e não se estreita: é o da porta, que este
 * módulo não possui. Esta implementação nunca devolve `null`; outro adaptador,
 * contra outro Registo, pode não ter display para dar, e estreitar o tipo
 * obrigava-o a mentir. Quem consome continua a ter de tratar o `null`.
 *
 * O `precoTipo` que entra aqui é o **efectivo** (ver `precoTipoEfectivo`) e não o
 * da coluna: um preço vencido já chega como `a_partir_de`.
 */
export function precoDisplay(
  precoTipo: PrecoTipo,
  precoMinor: bigint | null,
): string | null {
  if (precoTipo === SOB_CONSULTA) return TEXTO_SOB_CONSULTA;
  if (precoMinor === null) {
    // O `offer_terms_preco_ck` da revisão `0028` torna este par impossível na
    // base, nos dois sentidos. Se chegou aqui, a linha não veio da base — veio
    // de um objecto construído em código, e devolver «null» em silêncio fazia um
    // `fixo` passar por `sob_consulta` e o agente dizer «preço sob consulta»
    // sobre um produto com preço publicado.
    throw new TypeError(
      `preco_tipo='${precoTipo}' com preco_minor nulo: o offer_terms_preco_ck ` +
        "da revisao 0028 recusa este par na base, nos dois sentidos. Um " +
        "a_partir_de sem minimo nao tem nada para citar (KAM-043, criterio 1)",
    );
  }
  const numero = formatarMinor(precoMinor);
  return precoTipo === A_PARTIR_DE
    ? `${PREFIXO_A_PARTIR_DE}${numero}`
    : numero;
}

/**
 * O modo de preço **efectivo**: o da coluna, ou `a_partir_de` se venceu.
 *
 * O §7.1, regra 2: «preços têm `preco_atualizado_at` e `preco_valido_ate` —
 * passado o prazo, o agente trata o preço como `a_partir_de` e pede confirmação
 * ao dono». O critério 3 repete-o.
 *
 * **A coluna não muda, e isso é a substância.** O que o dono escolheu continua
 * escrito em `preco_tipo`; o que muda é a leitura. Escrever `a_partir_de` na
 * coluna quando o prazo passa perdia a escolha do dono para sempre — e no dia em
 * que ele renovasse o preço, ninguém sabia se o `a_partir_de` era dele ou do
 * relógio.
 *
 * **Um `sob_consulta` vencido continua `sob_consulta`.** Promovê-lo a
 * `a_partir_de` era pior do que não fazer nada: dava um mínimo a um produto que
 * nunca teve preço — e a base garante que não há número (`preco_minor` nulo),
 * pelo que o `precoDisplay` rebentava. A regra do §7.1 é sobre preços que
 * existem.
 *
 * Sem `preco_valido_ate` não há prazo, e um preço sem prazo não vence: é o caso
 * comum, porque a coluna é anulável no §5.4.
 */
export function precoTipoEfectivo(
  termos: TermosDaOferta,
  agora: Date,
): PrecoTipo {
  if (termos.precoTipo === SOB_CONSULTA) return SOB_CONSULTA;
  if (termos.precoValidoAte === null) return termos.precoTipo;
  return Date.parse(termos.precoValidoAte) <= agora.getTime()
    ? A_PARTIR_DE
    : termos.precoTipo;
}

/**
 * Verdadeiro se o preço desta oferta já passou o prazo.
 *
 * Separado do `precoTipoEfectivo` porque o aviso e a leitura são duas coisas: um
 * `a_partir_de` que vence continua a ler-se `a_partir_de` — o modo não muda — e
 * **ainda assim** leva o aviso, porque o critério 3 manda «marcar pedido de
 * confirmação ao dono». Com o aviso derivado da mudança de modo, esse caso ficava
 * em silêncio.
 */
export function precoVencido(termos: TermosDaOferta, agora: Date): boolean {
  if (termos.precoTipo === SOB_CONSULTA) return false;
  if (termos.precoValidoAte === null) return false;
  return Date.parse(termos.precoValidoAte) <= agora.getTime();
}

/**
 * Verdadeiro se um stock `indicativo` está por confirmar há mais de 24 h.
 *
 * Só se aplica ao `indicativo` (§7.3): no `garantido` o sistema é a verdade e no
 * `confirmar_dono` a confirmação é obrigatória de qualquer modo, pelo que o aviso
 * não acrescentava nada em nenhum dos dois.
 *
 * **Nunca conferido conta como por confirmar.** `stock_verificado_at` nulo é uma
 * oferta cujo stock ninguém verificou — que é mais incerto do que uma verificada
 * há 25 h, e tratá-lo como fresco por falta de data era o erro na direcção
 * errada.
 */
export function stockPorConfirmar(
  termos: TermosDaOferta,
  agora: Date,
): boolean {
  if (termos.stockModo !== "indicativo") return false;
  if (termos.stockVerificadoAt === null) return true;
  return (
    agora.getTime() - Date.parse(termos.stockVerificadoAt) >
    STOCK_POR_CONFIRMAR_MS
  );
}

/**
 * Os avisos desta oferta, pela ordem de `AVISOS`.
 *
 * Pela ordem da constante e não pela ordem em que se calculam: uma lista cuja
 * ordem depende da implementação obrigava cada teste a ordenar antes de comparar,
 * e o primeiro que se esquecesse ficava intermitente.
 */
export function avisosDaOferta(
  termos: TermosDaOferta,
  agora: Date,
): readonly Aviso[] {
  const presentes = new Set<Aviso>();
  if (precoVencido(termos, agora)) presentes.add("preco_vencido");
  if (stockPorConfirmar(termos, agora)) presentes.add("stock_por_confirmar");
  if (termos.stockModo === "confirmar_dono") {
    presentes.add("confirmacao_dono_necessaria");
  }
  return AVISOS.filter((aviso) => presentes.has(aviso));
}

/**
 * A vista completa de uma oferta: o que o agente pode dizer (critérios 2 e 3).
 *
 * O `atualizadoAt` é a coluna `atualizado_at` e não um `greatest` dos dois
 * instantes anuláveis do §5.4 — ver a razão na revisão `0028`.
 */
export function vistaDaOferta(
  termos: TermosDaOferta,
  agora: Date,
): VistaDaOferta {
  const efectivo = precoTipoEfectivo(termos, agora);
  return {
    sku: termos.sku,
    precoTipo: efectivo,
    precoDisplay: precoDisplay(efectivo, termos.precoMinor),
    stockModo: termos.stockModo,
    // **A disponibilidade é só sobre stock**, nos três modos do §7.3, e não
    // muda com o preço: «preço sob consulta» é o `precoDisplay` (critério 2) e
    // não a disponibilidade. Um produto `sob_consulta` pode estar em stock, e
    // dizer-lhe «preço sob consulta» no campo da disponibilidade escondia-o.
    disponibilidade: DISPONIBILIDADE[termos.stockModo],
    atualizadoAt: termos.atualizadoAt,
    avisos: avisosDaOferta(termos, agora),
  };
}

/** A moeda de apresentação, para quem precisar de a afirmar. */
export const MOEDA_DE_APRESENTACAO = MOEDA;
