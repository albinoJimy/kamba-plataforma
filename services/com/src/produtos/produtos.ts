/**
 * As operações do módulo `produtos` (KAM-043).
 *
 * Três delas **são** métodos da porta `CommerceRegistry` — o
 * `upsertProductDraft`, o `publishProduct` e o `getOfferView`, que o
 * `docs/com/port-coverage.md` §2 atribui a este ticket. As outras não estão na
 * porta e não vão estar: o §3.39 do dicionário fecha-a em doze métodos, pinados
 * por `port.contrato.test.ts`, e o critério 8 diz por escrito que o contrato não
 * expõe a pesquisa a longo prazo.
 *
 * ```text
 * upsertProductDraft   porta    rascunho, e nunca publica (critério 4)
 * publishProduct       porta    com OwnerConfirmation válida (critério 4)
 * getOfferView         porta    a vista com o modo (critérios 2 e 3)
 * searchOffers         módulo   stand-in da Fase 0, descartável (critério 8)
 * getValidQuote        módulo   a cotação viva, ou nada (critério 6)
 * emitirCotacao        módulo   só actor `dono` (critério 6)
 * ajustarStock         módulo   auditado e emitido (critério 5)
 * ```
 *
 * ## Tudo entra pelo repo-base, e nada abre transacção
 *
 * Cada operação recebe o `Registo` que o `comRegisto` do adaptador monta — um
 * `repo` que **não consegue** emitir uma consulta sem o filtro de tenant, um
 * `ids` que só existe se o provisionamento tiver corrido, e o `ctx` validado.
 * Não há caminho por onde estas funções cheguem à base sem passar por lá: o
 * `ClienteSql` cru não está no `Registo`, e a revisão adversarial do KAM-042
 * mostrou porquê — com ele ao lado, este ticket escrevia
 * `r.cliente.query("SELECT * FROM product")` e a frase «não há caminho» era a
 * única barreira.
 *
 * O preço e o evento precisam do cliente cru (o `evt_emitir` e o `audit_append`
 * são chamadas de função, que o repo-base recusa por não terem `WHERE`), e por
 * isso o `Registo` ganhou um `emitir` — uma porta estreita que o adaptador
 * fornece, e não o cliente inteiro. Ver `adapters/medusa/index.ts`.
 *
 * ## A idempotência do critério 5 é uma leitura trancada, e não uma comparação
 *
 * O DoD pede que «`publishProduct` e ajustes de stock repetidos não dupliquem
 * efeitos nem eventos». A forma é sempre a mesma nas três escritas:
 *
 * ```text
 * 1. ler a linha com FOR UPDATE        (SQL_TERMOS_PARA_ESCRITA)
 * 2. comparar o antes com o pedido
 * 3. se nada muda, sair sem escrever, sem auditar e sem emitir
 * 4. se muda, escrever + auditar + emitir, na mesma transacção
 * ```
 *
 * O passo 1 é o que a torna verdadeira **sob concorrência**, e não só na
 * repetição em série: sem a tranca, duas transacções leem o mesmo «antes», as
 * duas concluem que mudou, e saem dois eventos para uma alteração.
 */

import {
  erro,
  ok,
  type OfferView,
  type OwnerConfirmation,
  type ProductRef,
  type Resultado,
} from "../port/contrato.ts";
import {
  MAXIMO_DE_RESULTADOS,
  MOEDA,
  STOCK_BAIXO_LIMIAR,
  SOB_CONSULTA,
  type AjusteDeStock,
  type Cotacao,
  type EstadoDaOferta,
  type PedidoDeCotacao,
  type RascunhoDeProduto,
  type Relogio,
  type ResultadoDaPesquisa,
  type TermosDaOferta,
  type VistaDaOferta,
} from "./contrato.ts";
import {
  SQL_ACEITAR_COTACAO,
  SQL_ACTUALIZAR_TERMOS,
  SQL_AJUSTAR_STOCK,
  SQL_COTACAO_VALIDA,
  SQL_PESQUISAR,
  SQL_PUBLICAR,
  SQL_TERMOS,
  SQL_TERMOS_PARA_ESCRITA,
} from "./consultas.ts";
import { auditarPreco, auditarStock } from "./auditoria.ts";
import {
  emitirPrecoAlterado,
  emitirProdutoAlterado,
  emitirStockAjustado,
  emitirStockBaixo,
} from "./eventos.ts";
import { vistaDaOferta } from "./formato.ts";
import type { Registo } from "../adapters/medusa/index.ts";

/** A tabela que o `inserirNoTenant` do repo-base constrói. */
const TABELA = "platform.offer_terms";

/** A tabela das cotações. */
const TABELA_DE_COTACOES = "platform.price_quotes";

/**
 * Uma linha de `offer_terms` como o módulo a lê.
 *
 * O `preco_minor` chega do *driver* como `string` ou `number` e não como
 * `bigint` — o `pg` de Node devolve `bigint` do PostgreSQL como `string` por
 * omissão, para não perder precisão. Converter aqui, e não no sítio onde se usa,
 * é o que mantém o `bigint` como o único tipo de dinheiro dentro do módulo.
 */
function lerTermos(linha: Readonly<Record<string, unknown>>): TermosDaOferta {
  return {
    sku: String(linha["sku"]),
    nome: String(linha["nome"]),
    precoTipo: linha["preco_tipo"] as TermosDaOferta["precoTipo"],
    precoMinor: emMinor(linha["preco_minor"]),
    currency: String(linha["currency"]),
    precoAtualizadoAt: emInstante(linha["preco_atualizado_at"]),
    precoValidoAte: emInstante(linha["preco_valido_ate"]),
    stockModo: linha["stock_modo"] as TermosDaOferta["stockModo"],
    stockVerificadoAt: emInstante(linha["stock_verificado_at"]),
    estado: linha["estado"] as EstadoDaOferta,
    categoriaRestrita:
      linha["categoria_restrita"] === null ||
      linha["categoria_restrita"] === undefined
        ? null
        : String(linha["categoria_restrita"]),
    atualizadoAt: emInstante(linha["atualizado_at"]) ?? "",
  };
}

/**
 * Um valor em unidade menor como `bigint`, ou `null`.
 *
 * **Não aceita `number` com parte decimal.** Um `preco_minor` que chegasse como
 * `1200.5` vinha de uma coluna que não é `bigint`, e `BigInt(1200.5)` lança —
 * mas lança com `RangeError: The number 1200.5 cannot be converted to a BigInt`,
 * que não diz de onde veio. Esta mensagem diz.
 */
function emMinor(valor: unknown): bigint | null {
  if (valor === null || valor === undefined) return null;
  if (typeof valor === "bigint") return valor;
  if (typeof valor === "number") {
    if (!Number.isInteger(valor)) {
      throw new TypeError(
        `preco_minor nao inteiro vindo da base: ${valor}. A coluna e bigint na ` +
          "revisao 0028, pelo que isto veio de outro sitio (KAM-043)",
      );
    }
    return BigInt(valor);
  }
  return BigInt(String(valor));
}

/** Uma coluna de texto anulavel como `string` ou `null`. */
function emTexto(valor: unknown): string | null {
  return valor === null || valor === undefined ? null : String(valor);
}

/** Um `timestamptz` como ISO-8601, ou `null`. */
function emInstante(valor: unknown): string | null {
  if (valor === null || valor === undefined) return null;
  if (valor instanceof Date) return valor.toISOString();
  return String(valor);
}

// ------------------------------------------------------- critério 4: rascunho

/**
 * Escreve ou actualiza o rascunho de um produto. **Nunca publica** (critério 4).
 *
 * «Nunca publica» é imposto em dois sítios e nenhum deles é um `if`:
 *
 *   * na inserção, o `estado` não vai na lista de colunas — nasce `'rascunho'`
 *     pela omissão da coluna na revisão `0028`;
 *   * na actualização, o `SQL_ACTUALIZAR_TERMOS` **não tem a coluna `estado`**
 *     na cláusula `SET`.
 *
 * Com um `if`, o próximo chamador podia esquecê-lo; sem a coluna na instrução,
 * não há como. Um produto já publicado cujos termos mudam continua publicado — o
 * que é o comportamento certo, e é por isso que esta operação também audita e
 * emite quando o preço muda.
 *
 * O `ON CONFLICT` desempata por `(tenant_id, sku)`, que é a chave primária.
 */
export async function upsertProductDraft(
  r: Registo,
  rascunho: RascunhoDeProduto,
): Promise<Resultado<ProductRef>> {
  const invalido = validarRascunho(rascunho);
  if (invalido !== null) return erro(invalido);

  const antes = await lerParaEscrita(r, rascunho.sku);
  const precoMinor = rascunho.precoMinor ?? null;
  const stockModo = rascunho.stockModo ?? "indicativo";

  if (antes === null) {
    // Linha nova. O `estado` **não** vai: nasce `rascunho` pela omissão.
    const linhas = await r.repo.inserirNoTenant({
      tabela: TABELA,
      valores: {
        sku: rascunho.sku,
        nome: rascunho.nome,
        preco_tipo: rascunho.precoTipo,
        preco_minor: precoMinor,
        preco_valido_ate: rascunho.precoValidoAte ?? null,
        stock_modo: stockModo,
        preco_atualizado_at: new Date().toISOString(),
      },
      sufixo: "RETURNING sku, medusa_variant_id",
    });
    const linha = linhas[0];
    if (linha === undefined) {
      throw new Error(
        "o INSERT em offer_terms nao devolveu linha: sem ON CONFLICT, isto " +
          "significa que a politica tenant_iso recusou o WITH CHECK — o " +
          "app.tenant_id da transaccao nao e o do ctx (KAM-043)",
      );
    }
    // Um rascunho novo é um produto novo: o evento de produto sai, com o estado
    // que a linha tem. **Sem preço nem stock no payload** (critério 5).
    await emitirProdutoAlterado(r.emitir, r.ctx.tenantId, rascunho.sku, "rascunho");
    await registarAlteracaoDePreco(
      r,
      rascunho.sku,
      null,
      { preco_tipo: rascunho.precoTipo, preco_minor: precoMinor },
      "upsert_rascunho",
    );
    return ok({
      sku: rascunho.sku,
      // `medusa_variant_id`, que e texto e nao instante: nulo em toda a Fase 0,
      // porque o Registo da opcao B nao existe em `infra/compose/`.
      registoId: emTexto(linha["medusa_variant_id"]),
    });
  }

  // Linha existente. O `estado` fica onde está — ver a nota acima.
  const linhas = await r.repo.noTenant(SQL_ACTUALIZAR_TERMOS, [
    rascunho.sku,
    rascunho.nome,
    rascunho.precoTipo,
    precoMinor,
    rascunho.precoValidoAte ?? null,
    stockModo,
  ]);
  if (linhas.length === 0) return erro("NOT_FOUND");

  const mudouOPreco =
    antes.precoTipo !== rascunho.precoTipo || antes.precoMinor !== precoMinor;
  if (mudouOPreco) {
    await registarAlteracaoDePreco(
      r,
      rascunho.sku,
      { preco_tipo: antes.precoTipo, preco_minor: antes.precoMinor },
      { preco_tipo: rascunho.precoTipo, preco_minor: precoMinor },
      "upsert_rascunho",
    );
  }
  // **O evento de produto só sai se algo do produto mudou.** Uma repetição
  // exacta do mesmo rascunho não emite nada — é a idempotência do DoD.
  if (antes.nome !== rascunho.nome || mudouOPreco || antes.stockModo !== stockModo) {
    await emitirProdutoAlterado(r.emitir, r.ctx.tenantId, rascunho.sku, antes.estado);
  }
  return ok({ sku: rascunho.sku, registoId: null });
}

/** O que o módulo recusa antes de falar com a base. */
function validarRascunho(
  rascunho: RascunhoDeProduto,
): "VALIDATION_ERROR" | null {
  if (rascunho.sku.trim().length === 0) return "VALIDATION_ERROR";
  if (rascunho.nome.trim().length === 0) return "VALIDATION_ERROR";
  const temPreco = (rascunho.precoMinor ?? null) !== null;
  // **A mesma equivalência do `offer_terms_preco_ck`, nos dois sentidos.** A
  // base recusa-a de qualquer modo, e isto não é redundância: um `23514` chega
  // ao chamador como excepção e não como `VALIDATION_ERROR`, e a porta devolve
  // recusas de domínio como resposta (ver o `Resultado` do contrato).
  if (rascunho.precoTipo === SOB_CONSULTA && temPreco) return "VALIDATION_ERROR";
  if (rascunho.precoTipo !== SOB_CONSULTA && !temPreco) return "VALIDATION_ERROR";
  if ((rascunho.precoMinor ?? 0n) < 0n) return "VALIDATION_ERROR";
  return null;
}

/**
 * Audita e emite uma alteração de preço, na transacção de quem chama.
 *
 * As duas juntas e numa função só porque o critério 5 as pede juntas, e separá-las
 * deixava um chamador a fazer uma e a esquecer a outra.
 */
async function registarAlteracaoDePreco(
  r: Registo,
  sku: string,
  antes: { preco_tipo: string; preco_minor: bigint | null } | null,
  depois: { preco_tipo: string; preco_minor: bigint | null },
  origem: "upsert_rascunho" | "publicacao" | "cotacao_do_dono",
): Promise<void> {
  await auditarPreco(
    r.emitir,
    r.ctx.tenantId,
    r.ctx.actor,
    sku,
    antes ?? {},
    depois,
    origem,
  );
  await emitirPrecoAlterado(
    r.emitir,
    r.ctx.tenantId,
    sku,
    depois.preco_tipo as TermosDaOferta["precoTipo"],
    depois.preco_minor,
    MOEDA,
  );
}

// ----------------------------------------------------- critério 4: publicação

/**
 * Publica um produto. Exige `OwnerConfirmation` válida; categoria restrita não
 * publica (critério 4).
 *
 * A confirmação verifica-se **aqui** e não no predicado do `UPDATE`, e a razão é
 * que não há coluna onde ela viva: a `offer_terms` do §5.4 não tem onde a
 * guardar, e inventar-lhe uma era escopo de outro ticket — o fluxo conversacional
 * de `confirmar_dono` é o KAM-046. O que fica provado por máquina é que uma
 * publicação **sem** confirmação válida falha; o rasto dela fica na linha de
 * `audit_log`, com o actor que confirmou.
 *
 * A categoria restrita, essa, **está** no predicado — é a base que a recusa, e
 * não um `if` que o próximo chamador pode esquecer.
 */
export async function publishProduct(
  r: Registo,
  ref: ProductRef,
  confirmacao: OwnerConfirmation,
): Promise<Resultado<void>> {
  if (!confirmacaoValida(confirmacao)) return erro("VALIDATION_ERROR");

  const antes = await lerParaEscrita(r, ref.sku);
  if (antes === null) return erro("NOT_FOUND");

  // **Idempotência:** publicar o que já está publicado não escreve, não audita e
  // não emite. Sem isto, cada repetição emitia um `catalog.product_changed` e o
  // IDX reindexava por nada.
  if (antes.estado === "publicado") return ok(undefined);

  // A categoria restrita é uma recusa de domínio e não uma falha: o agente tem
  // de a poder mostrar ao dono. Lê-se antes para distinguir as razões, e o
  // predicado do `UPDATE` continua a ser quem a impõe.
  if (antes.categoriaRestrita !== null) return erro("VALIDATION_ERROR");

  const linhas = await r.repo.noTenant(SQL_PUBLICAR, [ref.sku]);
  if (linhas.length === 0) {
    // Zero linhas com a oferta a existir e sem categoria restrita: sobra o
    // `estado <> 'arquivado'` do predicado. Arquivar é terminal.
    return erro("VALIDATION_ERROR");
  }

  await auditarPreco(
    r.emitir,
    r.ctx.tenantId,
    // **O actor da auditoria é o que confirmou, e não o que chamou.** É a
    // diferença que o critério 4 quer guardar: a publicação é o acto que põe um
    // preço à frente de um cliente, e quem responde por ele é o dono que a
    // confirmou — não o agente que carregou no botão.
    confirmacao.actor,
    ref.sku,
    { estado: antes.estado },
    { estado: "publicado", confirmado_em: confirmacao.em },
    "publicacao",
  );
  await emitirProdutoAlterado(r.emitir, r.ctx.tenantId, ref.sku, "publicado");
  return ok(undefined);
}

/**
 * Uma `OwnerConfirmation` só é válida com os três pedaços do critério 4.
 *
 * «sem `OwnerConfirmation` válida (id da mensagem, hora, versão do texto)
 * falha». O tipo da porta dá dois campos — `actor` e `em` —, e o `actor.id` é o
 * id da mensagem que confirmou. **A versão do texto não tem campo**, e isso é
 * uma caixa que não se marca à letra: ver a verificação do bloco. O que se
 * verifica é o que existe.
 *
 * **E o actor tem de ser `dono`.** Um `agente` a confirmar a sua própria
 * publicação era a confirmação do dono a ser dada por quem ela existe para
 * travar — e nenhuma coluna o impediria, porque não há coluna.
 *
 * **Exportada, e chamada em dois sítios** — aqui e no adaptador, antes do
 * `comRegisto`. Não são duas fontes para a mesma regra: é uma função e duas
 * chamadas, como o `exigirCtx`, que o adaptador também chama por fora da
 * transacção e o `comRegisto` repete por dentro. A de fora existe para que uma
 * confirmação inválida **não custe uma ligação** — era a nota que o próprio
 * adaptador já tinha escrito para o `ctx` («o que falha, falha antes de custar
 * uma ligação»), e a primeira versão deste ticket não a seguiu: o teste do
 * critério 4 apanhou-o, com o cliente de ensaio a explodir por ter sido
 * chamado. A de dentro existe porque quem usa o módulo sem a porta — e o
 * `db/tests_produtos/` usa — tem de ter a mesma barreira.
 */
export function confirmacaoValida(c: OwnerConfirmation): boolean {
  if (c === null || c === undefined) return false;
  if (c.actor?.kind !== "dono") return false;
  if (String(c.actor?.id ?? "").trim().length === 0) return false;
  const em = Date.parse(String(c.em ?? ""));
  return Number.isFinite(em);
}

// -------------------------------------------- critérios 2 e 3: a vista da oferta

/**
 * A vista da oferta, formatada com o modo (critérios 2 e 3).
 *
 * Devolve a `OfferView` da porta — **seis campos**, que é o que o §3.39 declara.
 * Os `avisos` do critério 3 são o sétimo e saem pelo `vistaDaOfertaCompleta`,
 * porque acrescentá-los ao tipo da porta era alargar um contrato fechado que o
 * KAM-042 pinou num teste.
 */
export async function getOfferView(
  r: Registo,
  sku: string,
  agora: Date,
): Promise<Resultado<OfferView>> {
  const vista = await vistaDaOfertaCompleta(r, sku, agora);
  if (vista.tipo === "erro") return erro(vista.erro);
  const { avisos: _avisos, ...seisCampos } = vista.valor;
  return ok(seisCampos);
}

/** A mesma vista, com os avisos. Para quem consome o módulo e não a porta. */
export async function vistaDaOfertaCompleta(
  r: Registo,
  sku: string,
  agora: Date,
): Promise<Resultado<VistaDaOferta>> {
  const linhas = await r.repo.noTenant(SQL_TERMOS, [sku]);
  const linha = linhas[0];
  // **Zero linhas é `NOT_FOUND` e não uma lista vazia**, e a razão é o ISO-01..08:
  // com o `ctx` do tenant A sobre um `sku` do tenant B, a RLS devolve zero linhas
  // e a resposta certa é «não encontrei» — nunca a linha de B, e nunca uma vista
  // com campos vazios que o agente lesse como um produto sem preço.
  if (linha === undefined) return erro("NOT_FOUND");
  // Um produto que não está publicado não se oferece a um cliente. O
  // `getOfferView` é a vista que o agente cita, e um rascunho citado era um preço
  // à frente de um cliente sem o dono o ter publicado — que é exactamente o que o
  // critério 4 existe para impedir no outro sentido.
  const termos = lerTermos(linha);
  if (termos.estado !== "publicado") return erro("NOT_FOUND");
  return ok(vistaDaOferta(termos, agora));
}

// --------------------------------------------------- critério 5: ajuste de stock

/**
 * Ajusta o stock de um SKU: audita, emite, e emite `stock.low` abaixo do limiar.
 *
 * **A quantidade não tem coluna em `offer_terms`**, e não é omissão da revisão
 * `0028`: o §5.4 põe o stock no Registo e dá a esta tabela o **modo** e o
 * instante da última conferência, que é o que governa o que o agente pode dizer.
 * A quantidade atravessa esta função e sai no payload do `stock.adjusted`, que é
 * quem a leva ao DAT — e é por isso que um ajuste é auditável e emitido sem haver
 * coluna para ele.
 *
 * Isso tem uma consequência que fica dita: **a idempotência deste caminho é
 * parcial**. O que esta função não duplica é o efeito na tabela
 * (`stock_verificado_at` e `stock_modo`, com a tranca) e o `stock.adjusted` de um
 * ajuste que não muda o modo nem a quantidade pedida. O que ela não pode afirmar
 * é que a **quantidade** no Registo não foi aplicada duas vezes, porque o Registo
 * não existe. Quem o fechar é o ticket que ligar o inventário.
 */
export async function ajustarStock(
  r: Registo,
  ajuste: AjusteDeStock,
  stockModo?: TermosDaOferta["stockModo"],
): Promise<Resultado<void>> {
  if (!Number.isInteger(ajuste.qty) || ajuste.qty < 0) {
    return erro("VALIDATION_ERROR");
  }
  const antes = await lerParaEscrita(r, ajuste.sku);
  if (antes === null) return erro("NOT_FOUND");

  const modo = stockModo ?? antes.stockModo;
  const linhas = await r.repo.noTenant(SQL_AJUSTAR_STOCK, [ajuste.sku, modo]);
  if (linhas.length === 0) return erro("NOT_FOUND");

  await auditarStock(
    r.emitir,
    r.ctx.tenantId,
    r.ctx.actor,
    ajuste.sku,
    { stock_modo: antes.stockModo, stock_verificado_at: antes.stockVerificadoAt },
    { stock_modo: modo, qty: ajuste.qty },
    "ajuste_de_stock",
  );
  await emitirStockAjustado(
    r.emitir,
    r.ctx.tenantId,
    ajuste.sku,
    ajuste.qty,
    ajuste.motivo,
  );
  // O `stock.low` é **adicional** e não substitui o `stock.adjusted`: o
  // consumidor do aviso ao dono (AGR) subscreve um, e o DAT subscreve o outro.
  // O limiar é *proposta* — ver `STOCK_BAIXO_LIMIAR`.
  if (ajuste.qty < STOCK_BAIXO_LIMIAR) {
    await emitirStockBaixo(r.emitir, r.ctx.tenantId, ajuste.sku, ajuste.qty);
  }
  return ok(undefined);
}

// ---------------------------------------------------- critério 6: as cotações

/**
 * A cotação válida de um `(sku, qty)`, ou **nada** (critério 6).
 *
 * Devolve `null` e não um erro quando não há: «não há cotação» é uma resposta e
 * não uma falha, e o chamador que precisa de uma recusa é o `createOrder`
 * (KAM-046), que sabe o que fazer com a ausência.
 *
 * O instante vai como argumento e não é `now()` na consulta, para que o teste do
 * critério possa pôr a fronteira numa igualdade exacta em vez de dormir.
 */
export async function getValidQuote(
  r: Registo,
  sku: string,
  qty: number,
  agora: Date,
): Promise<Resultado<Cotacao | null>> {
  if (!Number.isInteger(qty) || qty <= 0) return erro("VALIDATION_ERROR");
  const linhas = await r.repo.noTenant(SQL_COTACAO_VALIDA, [
    sku,
    qty,
    agora.toISOString(),
  ]);
  const linha = linhas[0];
  if (linha === undefined) return ok(null);
  return ok({
    id: String(linha["id"]),
    sku: String(linha["sku"]),
    qty: Number(linha["qty"]),
    precoTotalMinor: emMinor(linha["preco_total_minor"]) ?? 0n,
    currency: String(linha["currency"]),
    validaAte: emInstante(linha["valida_ate"]) ?? "",
    estado: linha["estado"] as Cotacao["estado"],
  });
}

/**
 * Emite uma cotação. **Só actor `dono` autenticado** (critério 6).
 *
 * «`price_quotes` (cotação do dono) só é criada por actor `dono` autenticado, com
 * `valida_ate`». O `actor.kind` vem do `ctx`, que vem do estado do agente ou da
 * sessão autenticada e **nunca** do texto do cliente — é a regra da porta, e é o
 * que torna esta verificação uma barreira e não uma formalidade.
 *
 * A validade tem de ser **futura**: uma cotação emitida já vencida não é uma
 * cotação, e aceitá-la deixava uma linha que o `getValidQuote` nunca devolve a
 * ocupar a tabela com a aparência de uma oferta feita.
 *
 * O `emitida_por` é o `actor.id` do `ctx` e não um argumento: com um argumento,
 * o chamador escrevia o id de outro dono na cotação.
 */
export async function emitirCotacao(
  r: Registo,
  pedido: PedidoDeCotacao,
  agora: Date,
): Promise<Resultado<Cotacao>> {
  if (r.ctx.actor.kind !== "dono") return erro("VALIDATION_ERROR");
  if (!Number.isInteger(pedido.qty) || pedido.qty <= 0) {
    return erro("VALIDATION_ERROR");
  }
  if (pedido.precoTotalMinor < 0n) return erro("VALIDATION_ERROR");
  const validaAte = Date.parse(pedido.validaAte);
  if (!Number.isFinite(validaAte) || validaAte <= agora.getTime()) {
    return erro("VALIDATION_ERROR");
  }

  const linhas = await r.repo.inserirNoTenant({
    tabela: TABELA_DE_COTACOES,
    valores: {
      contact_id: pedido.contactId,
      sku: pedido.sku,
      qty: pedido.qty,
      preco_total_minor: pedido.precoTotalMinor.toString(),
      valida_ate: pedido.validaAte,
      emitida_por: r.ctx.actor.id,
    },
    sufixo:
      "RETURNING id, sku, qty, preco_total_minor, currency, valida_ate, estado",
  });
  const linha = linhas[0];
  if (linha === undefined) {
    throw new Error(
      "o INSERT em price_quotes nao devolveu linha: a politica tenant_iso " +
        "recusou o WITH CHECK (KAM-043, criterio 6)",
    );
  }
  // A cotação é um preço que o dono deu: audita-se, com a origem que a distingue
  // de uma alteração no painel.
  await auditarPreco(
    r.emitir,
    r.ctx.tenantId,
    r.ctx.actor,
    pedido.sku,
    {},
    {
      qty: pedido.qty,
      preco_total_minor: pedido.precoTotalMinor,
      valida_ate: pedido.validaAte,
    },
    "cotacao_do_dono",
  );
  return ok({
    id: String(linha["id"]),
    sku: String(linha["sku"]),
    qty: Number(linha["qty"]),
    precoTotalMinor: emMinor(linha["preco_total_minor"]) ?? 0n,
    currency: String(linha["currency"]),
    validaAte: emInstante(linha["valida_ate"]) ?? "",
    estado: linha["estado"] as Cotacao["estado"],
  });
}

/** Marca uma cotação como aceite. Só sai de `emitida`. */
export async function aceitarCotacao(
  r: Registo,
  id: string,
): Promise<Resultado<void>> {
  const linhas = await r.repo.noTenant(SQL_ACEITAR_COTACAO, [id]);
  return linhas.length === 0 ? erro("NOT_FOUND") : ok(undefined);
}

// ------------------------------------------------------- critério 8: pesquisa

/**
 * A pesquisa lexical mínima. **Descartável** — sai no KAM-061 (critério 8).
 *
 * ≤ 5 resultados, só do tenant, só publicados, e **sem preço**: o §6.2 do
 * `docs/tecnica/02` diz que o `search_catalog` «devolve candidatos (sku, nome)
 * sem preço no ranking», e quem quer o preço chama o `getOfferView`, que o
 * formata com o modo. Uma pesquisa que devolvesse `preco_minor` dava ao agente um
 * número sem modo ao lado — que é o que o validador de citação existe para
 * apanhar.
 *
 * O termo vai duas vezes (`$2` e `$3`) e não é descuido: o operador `%` usa o
 * índice de trigramas e o `similarity()` ordena, e os dois querem o mesmo texto.
 * Repetir `$2` era o natural e **não funciona** na suite do *gate* 8: o `pg8000`
 * é posicional e não tem equivalente para o mesmo argumento usado duas vezes,
 * pelo que o `args()` do `ConsultaDoTypeScript` o recusa.
 */
export async function searchOffers(
  r: Registo,
  termo: string,
): Promise<Resultado<readonly ResultadoDaPesquisa[]>> {
  const limpo = termo.trim();
  // Um termo vazio devolve nada e não tudo. É a mesma propriedade do ISO-10
  // noutra superfície: um filtro vazio não lista o catálogo inteiro.
  if (limpo.length === 0) return ok([]);
  const linhas = await r.repo.noTenant(SQL_PESQUISAR, [
    limpo,
    limpo,
    MAXIMO_DE_RESULTADOS,
  ]);
  return ok(
    linhas.map((linha) => ({
      sku: String(linha["sku"]),
      nome: String(linha["nome"]),
    })),
  );
}

// ------------------------------------------------------------------ auxiliares

/** A linha trancada, ou `null`. É o passo 1 da idempotência — ver o módulo. */
async function lerParaEscrita(
  r: Registo,
  sku: string,
): Promise<TermosDaOferta | null> {
  const linhas = await r.repo.noTenant(SQL_TERMOS_PARA_ESCRITA, [sku]);
  const linha = linhas[0];
  return linha === undefined ? null : lerTermos(linha);
}
