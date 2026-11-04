/**
 * `propose_cart` — a proposta de carrinho, **sem efeitos** (KAM-046, critério 1).
 *
 * ```text
 * propose_cart(items[]) -> { cart_id, total_minor, currency, linhas }
 * ```
 *
 * Três propriedades, e as três são o critério:
 *
 * ```text
 * LÊ E NÃO ESCREVE    nenhuma instrução deste ficheiro muda uma linha
 * SOMA NO BACKEND     o total é calculado aqui e devolvido como facto (ADR-007)
 * PREÇO DE QUEM DEVE  offer_terms, ou cotação válida com origem_preco='cotacao_dono'
 * ```
 *
 * ## O modelo nunca soma, e a propriedade é da assinatura
 *
 * O ADR-007 e a caixa de DoD «números só de tools» dizem que o total é calculado
 * no backend e devolvido como *fact*. Aqui isso é uma propriedade do código e
 * não uma intenção: **nenhuma operação deste módulo aceita um preço do
 * chamador** — é a regra 4 do §3.2 da porta, que o `produtos` do KAM-043 já
 * segue —, e o `PedidoDeProposta` tem `sku` e `qty` e mais nada. Um preço vindo
 * de fora não tem por onde entrar.
 *
 * **O que sai daqui não é um `Fact`, e isso tem de ficar dito.** O `Fact` do
 * §3.27 é do contrato da ToolLayer (`kind` fechado nos quatro do §6.2, com
 * proveniência), e a ToolLayer é Python (`services/agr/src/kamba_agr/tls/`). O
 * que este módulo entrega é o **número com a proveniência ao lado** — o
 * `totalMinor` e o `origemPreco` de cada linha —, e quem o embrulha em `Fact` é
 * a tool `propose_cart` (KAM-029/KAM-031). Construir aqui um `Fact` era uma
 * segunda fonte para uma forma que vive do outro lado da fronteira.
 *
 * ## `sob_consulta` sem cotação **não passa**, e passa a `a_partir_de`
 *
 * O critério 1 recusa o `sob_consulta` sem cotação, e o §7.1 do
 * `docs/tecnica/03` manda tratar um preço **vencido** como `a_partir_de`. São
 * duas regras diferentes e nenhuma dispensa a outra:
 *
 * ```text
 * sob_consulta  sem cotação válida  -> VALIDATION_ERROR, sem total
 * sob_consulta  com cotação válida  -> preço da cotação, origem_preco=cotacao_dono
 * a_partir_de   sem cotação válida  -> VALIDATION_ERROR, sem total
 * fixo          preço vencido       -> VALIDATION_ERROR, sem total
 * fixo          preço válido        -> preco_minor, origem_preco=offer_terms
 * ```
 *
 * **O `a_partir_de` entra na mesma recusa que o `sob_consulta`**, e é uma
 * decisão que vale a pena escrever: um «a partir de 12 500 Kz» é um preço que o
 * dono declarou como **mínimo**, e somá-lo num total dava ao cliente um número
 * que o dono não prometeu — que é exactamente o que o validador de citação do
 * KAM-032 existe para apanhar do outro lado. O caminho dele é a cotação, como o
 * §7.2 escreve para o `sob_consulta`.
 *
 * E o preço **vencido** de um `fixo` cai na mesma recusa pela razão do §7.1: a
 * vista da oferta trata-o como `a_partir_de`, e o que é `a_partir_de` não soma.
 * A caixa que isto não fecha é a do KAM-043 («marca pedido de confirmação ao
 * dono»), e o credor continua a ser quem escreveu o critério — o que este
 * módulo faz é recusar em vez de somar um preço caduco.
 *
 * ## O que este ficheiro **não** faz
 *
 * Não escreve, não reserva (KAM-045), não emite evento nenhum e não toca no
 * `order_intents`: a *saga* é o `create_order.ts`. O `cart_id` que ele devolve é
 * derivado e não guardado — ver a nota do `intents.ts` para a razão de não ser a
 * `intent_key`.
 *
 * ## As duas cadeias SQL são as do `produtos`, e é reuso e não cópia
 *
 * O `SQL_TERMOS` e o `SQL_COTACAO_VALIDA` vêm de `../produtos/consultas.ts`, que
 * é o módulo dono da `offer_terms` e da `price_quotes` (KAM-043) e cujo texto o
 * *gate* 8 já exercita em `db/tests_produtos/`. Reescrevê-las aqui dava duas
 * fontes para a mesma leitura, e foi essa divergência que a dívida 37 descreve
 * noutro eixo. O que este módulo acrescenta é a **resolução**: qual das duas
 * vale, por linha.
 */

import {
  SQL_COTACAO_VALIDA,
  SQL_TERMOS,
} from "../produtos/consultas.ts";
import { erro, eUuid, ok, type Resultado } from "../port/contrato.ts";
import type { ClienteSql, Ctx, LinhaDaEncomenda } from "./contrato.ts";
import {
  cartId,
  draftHash,
  linhasCanonicas,
  type AnelDoSegredo,
  type PartesDaIntencao,
  type Rascunho,
} from "./intents.ts";
import type { RepoDoTenant } from "./transition.ts";

/** Os dois valores de `origem_preco` (dicionário §3.40). Lista **fechada**. */
export const ORIGENS_DE_PRECO = ["offer_terms", "cotacao_dono"] as const;
export type OrigemDePreco = (typeof ORIGENS_DE_PRECO)[number];

/**
 * O `stock_modo` que obriga a confirmação do dono (critério 7).
 *
 * É um dos três `STOCK_MODOS` da porta, e o único que o critério 7 nomeia: uma
 * linha `confirmar_dono` deixa a encomenda `criada` com
 * `confirmacao_dono='pendente'`, **sem referência nem reserva**.
 */
export const STOCK_QUE_EXIGE_O_DONO = "confirmar_dono";

/** Uma linha do pedido de proposta. **Não leva preço** — ver a nota do módulo. */
export interface PedidoDeProposta {
  readonly sku: string;
  readonly qty: number;
}

/**
 * O rascunho que o grafo mantém no *checkpoint*, com a identidade dele (§6.3).
 *
 * **As linhas vêm daqui e de mais nenhum sítio**, e isso é uma correcção que
 * custou um achado de revisão adversarial. A primeira versão passava as linhas
 * **duas** vezes — o `rascunho.linhas`, de onde saía o `draft_hash`, e um
 * `itens[]` separado, de onde saíam os preços e o total —, e nada confrontava os
 * dois. Medido: um pedido com `rascunho.linhas` de 2 unidades e `itens` de 5
 * criava uma encomenda de **5** com o `draft_hash` de **2**, e o toque seguinte
 * com os itens certos recebia essa encomenda como repetição — a barreira do
 * critério 4 nunca disparava, porque o conteúdo que mudava não estava no *hash*.
 *
 * A correcção não é comparar os dois: é não haver dois. Uma fonte, e o defeito
 * deixa de ser possível em vez de ser apanhado.
 */
export interface RascunhoDoCarrinho extends Rascunho {
  readonly draftId: string;
  readonly draftVersion: number;
  readonly contactId: string;
}

/**
 * O que o `propose_cart` precisa para ler. **Menos do que o `Encomendas`**: não
 * precisa do `emitir`, porque não emite, nem das bandeiras.
 */
export interface Leitura {
  readonly ctx: Ctx;
  readonly repo: RepoDoTenant;
}

/** O resultado de uma linha resolvida, pronto para o `lines_snapshot` (§5.4). */
export interface LinhaResolvida extends LinhaDaEncomenda {
  /** O `stock_modo` da oferta, que decide o critério 7. Não entra no snapshot. */
  readonly stockModo: string;
}

/** A proposta: o que a tool devolve ao grafo. */
export interface Proposta {
  readonly cartId: string;
  readonly totalMinor: bigint;
  readonly currency: string;
  readonly linhas: readonly LinhaResolvida[];
  /** `true` se alguma linha é `confirmar_dono`. Ver o critério 7. */
  readonly exigeConfirmacaoDoDono: boolean;
  /** O `draft_hash` do rascunho proposto. O `createOrder` compara-o. */
  readonly draftHash: Buffer;
}

/** A moeda, sempre uma. O domínio do `orders_mirror_currency_ck` é `{AOA}`. */
export const MOEDA = "AOA";

/** Os termos de uma oferta, na parte que a resolução de preço usa. */
interface Termos {
  readonly sku: string;
  readonly nome: string;
  readonly precoTipo: string;
  readonly precoMinor: bigint | null;
  readonly currency: string;
  readonly precoValidoAte: string | null;
  readonly stockModo: string;
  readonly estado: string;
}

/** Um valor em unidade menor, como `bigint`. A mesma guarda do `produtos`. */
function emMinor(valor: unknown): bigint | null {
  if (valor === null || valor === undefined) return null;
  if (typeof valor === "bigint") return valor;
  if (typeof valor === "number") {
    if (!Number.isInteger(valor)) {
      throw new TypeError(
        `preco_minor nao inteiro vindo da base: ${valor}. A coluna e bigint na ` +
          "revisao 0028, pelo que isto veio de outro sitio (KAM-046)",
      );
    }
    return BigInt(valor);
  }
  return BigInt(String(valor));
}

function emInstante(valor: unknown): string | null {
  if (valor === null || valor === undefined) return null;
  if (valor instanceof Date) return valor.toISOString();
  return String(valor);
}

function lerTermos(linha: Readonly<Record<string, unknown>>): Termos {
  return {
    sku: String(linha["sku"]),
    nome: String(linha["nome"] ?? ""),
    precoTipo: String(linha["preco_tipo"]),
    precoMinor: emMinor(linha["preco_minor"]),
    currency: String(linha["currency"] ?? MOEDA),
    precoValidoAte: emInstante(linha["preco_valido_ate"]),
    stockModo: String(linha["stock_modo"]),
    estado: String(linha["estado"]),
  };
}

/**
 * `true` se o preço desta oferta ainda vale neste instante.
 *
 * A fronteira é a do §7.1 e a mesma que o `produtos` do KAM-043 mediu: o
 * instante **igual** conta como vencido. Sem `preco_valido_ate` o preço não
 * caduca — é a omissão da coluna na revisão `0028` e quer dizer «sem validade
 * declarada», não «vencido».
 */
export function precoValido(termos: Termos, agora: Date): boolean {
  if (termos.precoValidoAte === null) return true;
  const limite = Date.parse(termos.precoValidoAte);
  if (!Number.isFinite(limite)) return false;
  return limite > agora.getTime();
}

/**
 * Resolve o preço de **uma** linha. Ver a tabela da nota do módulo.
 *
 * A cotação lê-se **antes** de se decidir, e não só no caminho do
 * `sob_consulta`: o §7.2 diz que a cotação do dono resolve «`sob_consulta` e
 * negociação», e uma cotação emitida para um `fixo` é o dono a dar um preço
 * para aquela quantidade — ignorá-la era perder a negociação que ele fez. A
 * cotação **ganha** ao `offer_terms` quando existe, que é o sentido de ela
 * existir.
 *
 * **E é por a cotação ganhar que o `contactId` desce até aqui** (KAM-179). Este
 * é o caminho que põe o preço na encomenda: sem o predicado de contacto na
 * leitura, o contacto X que pedisse o mesmo `(sku, qty)` pagava o total
 * negociado para Y, com `origem_preco='cotacao_dono'` a dizer que o dono o
 * prometeu. O valor estava à mão desde sempre — o `RascunhoDoCarrinho.contactId`
 * —, e o que faltava era descê-lo.
 */
export async function resolverLinha(
  l: Leitura,
  contactId: string,
  pedido: PedidoDeProposta,
  agora: Date,
): Promise<Resultado<LinhaResolvida>> {
  // A forma canónica, pela razão escrita no `getValidQuote` do `produtos.ts`:
  // o `exigirPartes` deste módulo já exige o `eUuid` para o mesmo
  // identificador, e duas formas para o mesmo campo é a assimetria por onde a
  // barreira desaparece.
  if (!eUuid(contactId)) return erro("VALIDATION_ERROR");
  if (typeof pedido?.sku !== "string" || pedido.sku.trim().length === 0) {
    return erro("VALIDATION_ERROR");
  }
  if (!Number.isInteger(pedido?.qty) || pedido.qty <= 0) {
    return erro("VALIDATION_ERROR");
  }

  const linhas = await l.repo.noTenant(SQL_TERMOS, [pedido.sku]);
  const bruta = linhas[0];
  // Zero linhas é `NOT_FOUND` e não uma linha vazia, pela razão do ISO-01..08: o
  // `ctx` de A sobre o `sku` de B vê zero pela RLS, e a resposta certa é «não
  // encontrei» e nunca um carrinho com uma linha sem preço.
  if (bruta === undefined) return erro("NOT_FOUND");
  const termos = lerTermos(bruta);
  // Um rascunho não se vende. É a mesma barreira que o `getOfferView` do KAM-043
  // põe, e pela mesma razão: um preço à frente de um cliente sem o dono o ter
  // publicado é o que o critério 4 daquele ticket existe para impedir.
  if (termos.estado !== "publicado") return erro("NOT_FOUND");

  const cotacoes = await l.repo.noTenant(SQL_COTACAO_VALIDA, [
    contactId,
    pedido.sku,
    pedido.qty,
    agora.toISOString(),
  ]);
  const cotacao = cotacoes[0];
  if (cotacao !== undefined) {
    const total = emMinor(cotacao["preco_total_minor"]);
    if (total === null || total < 0n) return erro("VALIDATION_ERROR");
    // **A moeda verifica-se nos dois caminhos**, e não só no do `offer_terms`.
    // Hoje é inofensivo — o `price_quotes_currency_ck` e o
    // `offer_terms_currency_ck` da revisão `0028` fecham os dois em `{AOA}` —,
    // mas uma assimetria entre dois caminhos que resolvem a mesma coisa é como
    // uma barreira desaparece quando o domínio alargar. Achado da revisão
    // adversarial.
    if (String(cotacao["currency"] ?? MOEDA) !== MOEDA) {
      return erro("VALIDATION_ERROR");
    }
    return ok({
      sku: termos.sku,
      nome: termos.nome,
      qty: pedido.qty,
      // **O total da cotação é o da linha inteira e não o unitário**, e é o que
      // o §7.2 significa: «um preço total para `(sku, qty)`». Por isso o
      // `preco_minor` desta linha é o total da cotação, e o `qty` ao lado dele
      // não o multiplica — ver o `totalDaProposta`.
      precoMinor: total,
      precoTipo: termos.precoTipo,
      origemPreco: "cotacao_dono",
      stockModo: termos.stockModo,
    });
  }

  // Sem cotação: só um `fixo` com preço válido soma. Ver a tabela do módulo.
  if (termos.precoTipo !== "fixo") return erro("VALIDATION_ERROR");
  if (termos.precoMinor === null || termos.precoMinor < 0n) {
    return erro("VALIDATION_ERROR");
  }
  if (!precoValido(termos, agora)) return erro("VALIDATION_ERROR");
  if (termos.currency !== MOEDA) return erro("VALIDATION_ERROR");
  return ok({
    sku: termos.sku,
    nome: termos.nome,
    qty: pedido.qty,
    precoMinor: termos.precoMinor,
    precoTipo: termos.precoTipo,
    origemPreco: "offer_terms",
    stockModo: termos.stockModo,
  });
}

/**
 * O total, somado no backend. **`bigint` e não `number`.**
 *
 * `packages/core-ts/src/pagamentos/tipos.ts` declara `type Minor = bigint`, e um
 * `number` perdia precisão acima de 2^53 cêntimos sem avisar — é a mesma
 * fronteira que o `OrderView.totalMinor` da porta já escreve.
 *
 * **O `qty` multiplica o `offer_terms` e não a cotação**, e a distinção é a do
 * §7.2: o `preco_minor` da `offer_terms` é unitário e o `preco_total_minor` da
 * cotação é o total da linha (é por isso que uma cotação é para uma quantidade,
 * e «dez unidades cotadas não dizem nada sobre três», como o
 * `SQL_COTACAO_VALIDA` escreve). Multiplicar a cotação pelo `qty` cobrava dez
 * vezes o preço de dez.
 */
export function totalDaProposta(linhas: readonly LinhaResolvida[]): bigint {
  let total = 0n;
  for (const linha of linhas) {
    total +=
      linha.origemPreco === "cotacao_dono"
        ? linha.precoMinor
        : linha.precoMinor * BigInt(linha.qty);
  }
  return total;
}

/**
 * `propose_cart`: resolve as linhas, soma, e devolve o `cart_id` e o total.
 *
 * **Lê e não escreve.** A assinatura recebe o `Leitura`, que não tem `emitir`
 * nem bandeiras, pelo que não há por onde emitir um evento nem escrever no
 * outbox; e as duas cadeias que ela corre são `SELECT`. É a forma mais forte de
 * «sem efeitos» que este módulo consegue dar sem inventar um tipo de cliente
 * só-de-leitura — o que seria uma barreira a mais sobre o repo-base, que já
 * recusa um `INSERT` por execução.
 *
 * A ordem das linhas na resposta é a **canónica** e não a do pedido, e é
 * deliberado: é a mesma ordem que entra no `draft_hash`, pelo que quem compare a
 * resposta com o `lines_snapshot` da encomenda vê a mesma sequência. Ver o
 * `linhasCanonicas` do `intents.ts`.
 */
export async function proposeCart(
  l: Leitura,
  anel: AnelDoSegredo,
  rascunho: RascunhoDoCarrinho,
  agora: Date,
): Promise<Resultado<Proposta>> {
  if (!Array.isArray(rascunho?.linhas) || rascunho.linhas.length === 0) {
    return erro("VALIDATION_ERROR");
  }

  let canonicos: readonly PedidoDeProposta[];
  let hash: Buffer;
  let partes: PartesDaIntencao;
  try {
    // A canonicalização corre **antes** das leituras, e não depois: ela é que
    // valida as linhas (sku não vazio, qty inteiro positivo), e validar depois
    // de N idas à base era pagar a base para recusar o que a forma já recusa.
    //
    // E é a **mesma** chamada que alimenta o `draft_hash` e a resolução de
    // preços, pela razão escrita no `RascunhoDoCarrinho`: uma fonte.
    canonicos = linhasCanonicas(
      rascunho.linhas.map((linha) => ({ sku: linha.sku, qty: linha.qty })),
    );
    hash = draftHash({ linhas: canonicos, entregaModo: rascunho.entregaModo });
    partes = {
      tenantId: l.ctx.tenantId,
      contactId: rascunho.contactId,
      draftId: rascunho.draftId,
      draftVersion: rascunho.draftVersion,
    };
  } catch {
    // Uma parte sem forma é um pedido inválido e não uma excepção a atravessar a
    // porta: é a mesma escolha do `emitirCotacao` do KAM-043 para o `contactId`
    // de outro tenant, e a razão é a do §3.2 — uma recusa de domínio é uma
    // resposta, porque o grafo tem de a poder mostrar ao cliente.
    return erro("VALIDATION_ERROR");
  }

  const resolvidas: LinhaResolvida[] = [];
  for (const item of canonicos) {
    const linha = await resolverLinha(l, rascunho.contactId, item, agora);
    // **Uma linha que não resolve recusa o carrinho inteiro**, e não se devolve
    // um carrinho parcial: o total de um carrinho a que falta uma linha é um
    // número que o cliente leria como o preço do que pediu.
    if (linha.tipo === "erro") return erro(linha.erro);
    resolvidas.push(linha.valor);
  }

  return ok({
    cartId: cartId(anel[0], partes),
    totalMinor: totalDaProposta(resolvidas),
    currency: MOEDA,
    linhas: resolvidas,
    exigeConfirmacaoDoDono: resolvidas.some(
      (linha) => linha.stockModo === STOCK_QUE_EXIGE_O_DONO,
    ),
    draftHash: hash,
  });
}
