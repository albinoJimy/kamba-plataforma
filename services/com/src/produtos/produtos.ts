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
 * efeitos nem eventos». A forma é a mesma nas três escritas:
 *
 * ```text
 * 1. ler a linha com FOR UPDATE        (SQL_TERMOS_PARA_ESCRITA)
 * 2. comparar o antes com o pedido
 * 3. se nada muda, sair sem escrever, sem auditar e sem emitir
 * 4. se muda, escrever + auditar + emitir, na mesma transacção
 * ```
 *
 * O passo 1 é o que a tornaria verdadeira **sob concorrência**, e não só na
 * repetição em série: sem a tranca, duas transacções leem o mesmo «antes», as
 * duas concluem que mudou, e saem dois eventos para uma alteração.
 *
 * **Duas ressalvas, as duas medidas, e as duas na verificação do bloco:**
 *
 *   * o passo 1 **não tranca uma linha que não existe**, pelo que o caminho de
 *     inserção do `upsertProductDraft` se defende com
 *     `ON CONFLICT … DO NOTHING` e uma releitura, e não com a tranca;
 *   * o `ajustarStock` cumpre os passos 2 e 3 **só na parte que esta tabela
 *     permite** — o modo e a conferência. A mesma quantidade repetida não é
 *     detectada, porque `offer_terms` não tem coluna de quantidade: o stock é do
 *     Registo (§5.4). A caixa de DoD fica **vazia** por causa disso.
 *
 * E a concorrência em si **não está medida**: um `Promise.all` sobre um objecto
 * em memória não tem transacções para serializar, e a prova pede duas ligações a
 * um PostgreSQL real. É **NÃO VERIFICADO**, e está escrito onde se afirma.
 */

import {
  conflito,
  erro,
  eUuid,
  ok,
  PRECO_TIPOS,
  type OfferView,
  type OwnerConfirmation,
  type ProductRef,
  type Resultado,
} from "../port/contrato.ts";
import {
  LIMITE_DO_PAINEL,
  MAXIMO_DE_RESULTADOS,
  MOEDA,
  STOCK_BAIXO_LIMIAR,
  SOB_CONSULTA,
  type AjusteDeStock,
  type AlteracaoDeOferta,
  type Cotacao,
  type ListaDoPainel,
  type OfertaDoPainel,
  type EstadoDaOferta,
  type PedidoDeCotacao,
  type RascunhoDeProduto,
  type Relogio,
  type ResultadoDaPesquisa,
  type TermosDaOferta,
  type VistaDaOferta,
} from "./contrato.ts";
import {
  SQLSTATE_CHECK,
  SQLSTATE_FK,
  SQLSTATE_UNICIDADE,
  SQL_ACEITAR_COTACAO,
  SQL_ACTUALIZAR_TERMOS,
  SQL_ALTERAR_OFERTA,
  SQL_AJUSTAR_STOCK,
  SQL_COTACAO_VALIDA,
  SQL_LISTAR_OFERTAS,
  SQL_OFERTA_DO_PAINEL,
  SQL_PESQUISAR,
  SQL_PUBLICAR,
  SQL_TERMOS,
  SQL_TERMOS_PARA_ESCRITA,
} from "./consultas.ts";
import {
  auditarPreco,
  auditarStock,
  type Instantaneo,
} from "./auditoria.ts";
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
 * O `ON CONFLICT (tenant_id, sku) DO NOTHING` desempata com quem inserir ao
 * mesmo tempo o **mesmo SKU novo**: um `FOR UPDATE` não tranca uma linha que não
 * existe, pelo que duas chamadas concorrentes viam as duas `antes === null`. Sem
 * ele, uma recebia `23505` como **excepção** — fora do `Resultado` que a porta
 * promete. Com ele, recebe zero linhas, relê e segue pelo caminho da
 * actualização. Achado da revisão adversarial, que também notou que dois
 * comentários afirmavam o `ON CONFLICT` que não existia.
 */
export async function upsertProductDraft(
  r: Registo,
  rascunho: RascunhoDeProduto,
): Promise<Resultado<ProductRef>> {
  const invalido = validarRascunho(rascunho);
  if (invalido !== null) return erro(invalido);

  const precoMinor = rascunho.precoMinor ?? null;
  const stockModo = rascunho.stockModo ?? "indicativo";
  const antes = await lerParaEscrita(r, rascunho.sku);

  if (antes === null) {
    // Linha nova. O `estado` **não** vai: nasce `rascunho` pela omissão.
    const linhas = await comRecusaDeDominio(() =>
      r.repo.inserirNoTenant({
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
        sufixo:
          "ON CONFLICT (tenant_id, sku) DO NOTHING " +
          "RETURNING sku, medusa_variant_id",
      }),
    );
    if (linhas.tipo === "erro") return erro(linhas.erro);
    const linha = linhas.valor[0];
    if (linha !== undefined) {
      // Um rascunho novo é um produto novo: o evento de produto sai, com o
      // estado que a linha tem. **Sem preço nem stock no payload** (critério 5).
      await emitirProdutoAlterado(
        r.emitir,
        r.ctx.tenantId,
        rascunho.sku,
        "rascunho",
      );
      await registarAlteracaoDePreco(
        r,
        rascunho.sku,
        null,
        { preco_tipo: rascunho.precoTipo, preco_minor: precoMinor },
        "upsert_rascunho",
      );
      return ok({
        sku: rascunho.sku,
        // `medusa_variant_id`, que é texto e não instante: nulo em toda a Fase
        // 0, porque o Registo da opção B não existe em `infra/compose/`.
        registoId: emTexto(linha["medusa_variant_id"]),
      });
    }
    // Zero linhas com `DO NOTHING`: outra transacção criou-a entre o
    // `lerParaEscrita` e o `INSERT`. Relê — agora com a tranca a servir — e
    // segue pelo caminho da actualização.
    const criadaPorOutro = await lerParaEscrita(r, rascunho.sku);
    if (criadaPorOutro === null) {
      // Inalcançável sem uma terceira transacção a apagar a linha no intervalo.
      // `UPSTREAM_DOWN` e não `NOT_FOUND`: o chamador pediu uma escrita que a
      // base aceitou e desfez, e repetir é a resposta certa — um `NOT_FOUND`
      // dizia-lhe que o produto não existe, que é falso.
      return erro("UPSTREAM_DOWN");
    }
    return actualizarTermos(r, criadaPorOutro, rascunho, precoMinor, stockModo);
  }

  return actualizarTermos(r, antes, rascunho, precoMinor, stockModo);
}

/**
 * O caminho da actualização, e a sua idempotência.
 *
 * **Se nada muda, não escreve.** Era o passo 3 que o cabeçalho deste módulo
 * prometia e que a primeira versão não cumpria: o `UPDATE` corria sempre, pelo
 * que uma repetição byte-a-byte reescrevia o `atualizado_at` e o
 * `preco_atualizado_at` — e o `OfferView.atualizadoAt` mudava sem nada ter
 * mudado. Agora a comparação é anterior à escrita, e a repetição exacta é
 * **inteiramente** sem efeito: sem `UPDATE`, sem auditoria e sem evento.
 *
 * **O `preco_valido_ate` entra na comparação do preço**, e faltava. Sem ele,
 * passar a validade de futuro para passado mudava a linha, fazia o
 * `getOfferView` ler `a_partir_de` com aviso (critério 3) e **não** emitia
 * `catalog.price_changed` nem escrevia `audit_log` — uma alteração do preço
 * citável sem rasto, contra o critério 5. Achado da revisão adversarial.
 */
async function actualizarTermos(
  r: Registo,
  antes: TermosDaOferta,
  rascunho: RascunhoDeProduto,
  precoMinor: bigint | null,
  stockModo: TermosDaOferta["stockModo"],
): Promise<Resultado<ProductRef>> {
  const validoAte = rascunho.precoValidoAte ?? null;
  const mudouOPreco =
    antes.precoTipo !== rascunho.precoTipo ||
    antes.precoMinor !== precoMinor ||
    antes.precoValidoAte !== validoAte;
  const mudouAlgo =
    mudouOPreco ||
    antes.nome !== rascunho.nome ||
    antes.stockModo !== stockModo;

  if (!mudouAlgo) {
    // Nada muda: sai sem escrever, sem auditar e sem emitir.
    return ok({ sku: antes.sku, registoId: null });
  }

  // O `preco_atualizado_at` só avança se o preço mudou — senão a coluna que
  // significa «quando o preço foi posto» passava a significar «quando alguém
  // reescreveu o rascunho». O `estado` não vai na instrução, e é isso que faz
  // do «nunca publica» uma propriedade e não um `if`.
  const precoAtualizadoAt = mudouOPreco
    ? new Date().toISOString()
    : antes.precoAtualizadoAt;

  const escrita = await comRecusaDeDominio(() =>
    r.repo.noTenant(SQL_ACTUALIZAR_TERMOS, [
      rascunho.sku,
      rascunho.nome,
      rascunho.precoTipo,
      precoMinor,
      validoAte,
      stockModo,
      precoAtualizadoAt,
    ]),
  );
  if (escrita.tipo === "erro") return erro(escrita.erro);
  if (escrita.valor.length === 0) return erro("NOT_FOUND");

  if (mudouOPreco) {
    await registarAlteracaoDePreco(
      r,
      rascunho.sku,
      {
        preco_tipo: antes.precoTipo,
        preco_minor: antes.precoMinor,
        preco_valido_ate: antes.precoValidoAte,
      },
      {
        preco_tipo: rascunho.precoTipo,
        preco_minor: precoMinor,
        preco_valido_ate: validoAte,
      },
      "upsert_rascunho",
    );
  }
  // O evento de produto sai com o estado que a linha **tem** — esta operação
  // nunca o muda.
  await emitirProdutoAlterado(r.emitir, r.ctx.tenantId, rascunho.sku, antes.estado);
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
  // O instantâneo é um `Instantaneo` e não uma forma fixa: o que entra nele
  // depende do que mudou, e o `canonico()` ordena as chaves para que dois
  // objectos com os mesmos pares em ordem diferente dêem o mesmo *hash*. Fixar
  // dois campos aqui obrigava a mentir no terceiro — o `preco_valido_ate` entrou
  // na comparação do preço com um achado da revisão adversarial, e não cabia.
  antes: Instantaneo | null,
  depois: Instantaneo & { preco_tipo: string; preco_minor: bigint | null },
  origem: "upsert_rascunho" | "publicacao" | "cotacao_do_dono" | "painel_do_dono",
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

  // **O actor da linha é quem chamou; a confirmação vai no instantâneo.**
  //
  // A primeira versão passava `confirmacao.actor` como actor da auditoria, com o
  // argumento de que quem responde pela publicação é o dono que a confirmou. A
  // revisão adversarial mostrou o que isso custava, e o argumento era errado por
  // uma razão concreta: o `actor.id` de uma `OwnerConfirmation` é o **id da
  // mensagem** que confirmou — é como o critério 4 pede «id da mensagem» —, pelo
  // que a linha ficava com `actor_id = <id de mensagem>` e **quem efectivamente
  // chamou não era gravado em sítio nenhum**. Quem auditasse «as acções do actor
  // X» não encontrava publicações.
  //
  // O `actor` é agora o do `ctx` e a confirmação entra no `depois`, que é onde um
  // id de mensagem pertence: a linha passa a responder às duas perguntas — quem
  // publicou, e com que confirmação.
  await auditarPreco(
    r.emitir,
    r.ctx.tenantId,
    r.ctx.actor,
    ref.sku,
    { estado: antes.estado },
    {
      estado: "publicado",
      confirmado_em: confirmacao.em,
      confirmado_por: confirmacao.actor.id,
    },
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
 * ## A idempotência deste caminho é **parcial**, e a parte que falta é medida
 *
 * O `qty` é o **nível** de stock e não um delta — é o que o payload do
 * `stock.adjusted` e do `stock.low` significa —, pelo que «pôr o nível a 3» duas
 * vezes **devia** ser sem efeito à segunda. Não é, e a razão é que não há onde
 * comparar: `offer_terms` não tem coluna de quantidade, porque o §5.4 põe o
 * stock no Registo e dá a esta tabela só o **modo** e o instante da última
 * conferência.
 *
 * **Esta operação não desduplica, e a escolha é deliberada.** Dois ajustes
 * iguais seguidos escrevem duas vezes, auditam duas vezes e emitem duas vezes.
 *
 * O caminho que não se tomou, e porquê: cortar quando o `stock_modo` não muda
 * engolia em silêncio o caso **comum** — o dono a corrigir a quantidade sem
 * mudar o modo —, porque a quantidade não está nesta tabela para ser comparada.
 * **Suprimir sem poder comparar é pior do que duplicar:** um nível emitido duas
 * vezes é visível a jusante e o consumidor é idempotente por `evento.id`
 * (ADR-009); um ajuste engolido não é visível em sítio nenhum, e o agente passa
 * a citar um stock que o dono já corrigiu.
 *
 * O que fecha isto é uma coluna de quantidade em `offer_terms` ou uma chave de
 * idempotência por ajuste — e nenhuma das duas é deste ticket: o §5.4 põe o
 * stock no Registo, e esta tabela tem o **modo** e o instante da conferência. A
 * caixa de DoD «ajustes de stock repetidos não duplicam efeitos nem eventos»
 * fica **vazia** por isto, com a razão escrita na verificação do bloco.
 *
 * A primeira versão deste ticket não comparava nada **e dois docstrings
 * afirmavam que comparava**. O achado é da revisão adversarial; o que mudou foi
 * a caixa e a prosa, não o comportamento — porque o comportamento estava certo
 * e a afirmação sobre ele estava errada.
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

  // **Não há passo 2 aqui, e a tentativa de o haver foi retirada.** Ver a nota
  // desta função: a quantidade não tem coluna onde ser comparada, e **suprimir
  // sem a poder comparar é pior do que duplicar**. Uma versão intermédia deste
  // ticket cortava quando o modo não mudava e o motivo não era `conferencia` — e
  // isso engolia em silêncio um ajuste do dono que mudou a quantidade, que é o
  // caso comum desta operação. Perder um ajuste real é um defeito maior do que
  // emitir duas vezes o mesmo nível, porque o segundo é visível a jusante e o
  // primeiro não.
  const escrita = await comRecusaDeDominio(() =>
    r.repo.noTenant(SQL_AJUSTAR_STOCK, [ajuste.sku, modo]),
  );
  if (escrita.tipo === "erro") return erro(escrita.erro);
  if (escrita.valor.length === 0) return erro("NOT_FOUND");

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
 * A cotação válida de um `(contacto, sku, qty)`, ou **nada** (critério 6).
 *
 * Devolve `null` e não um erro quando não há: «não há cotação» é uma resposta e
 * não uma falha, e o chamador que precisa de uma recusa é o `createOrder`
 * (KAM-046), que sabe o que fazer com a ausência.
 *
 * **O `contactId` é um argumento e não um campo do `ctx`** (KAM-179): o `Ctx` da
 * porta leva `tenantId`, `actor` e `traceId`, e o contacto chega por chamada —
 * como no `OrderIntent.contactId` e no `OrderFilter.contactId`. A assinatura é a
 * do §3.40 do dicionário, emendado por este ticket.
 *
 * Um `contactId` vazio é `VALIDATION_ERROR` e não `ok(null)`: «não há cotação
 * para este cliente» e «o chamador não disse de que cliente se trata» são coisas
 * diferentes, e responder `null` à segunda escondia o defeito de quem chama por
 * trás de uma resposta legítima.
 *
 * O instante vai como argumento e não é `now()` na consulta, para que o teste do
 * critério possa pôr a fronteira numa igualdade exacta em vez de dormir.
 */
export async function getValidQuote(
  r: Registo,
  contactId: string,
  sku: string,
  qty: number,
  agora: Date,
): Promise<Resultado<Cotacao | null>> {
  // **A forma canónica, e não «não vazio»** (KAM-179). A primeira versão deste
  // ticket aceitava qualquer cadeia não vazia, e isso reabria pelo lado um
  // caminho que o módulo já tinha fechado: um `contactId` malformado chegava à
  // base, o motor devolvia `22P02` — que não é nenhum dos três `SQLSTATE` que
  // este módulo traduz — e a excepção **atravessava a porta**. As outras
  // guardas de `contactId` deste serviço usam o `eUuid` (o `exigirPartes` do
  // `orders/intents.ts` e o `exigirCtx` do `servicos/contrato.ts`), e uma
  // segunda forma para o mesmo identificador era a assimetria por onde a
  // barreira desaparece. Achado da revisão adversarial.
  if (!eUuid(contactId)) return erro("VALIDATION_ERROR");
  if (!Number.isInteger(qty) || qty <= 0) return erro("VALIDATION_ERROR");
  const linhas = await r.repo.noTenant(SQL_COTACAO_VALIDA, [
    contactId,
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

  // O `contactId` **não** se valida aqui, e é a FK composta que o recusa: a
  // `price_quotes_contacto_do_mesmo_tenant_fk` da `0028` existe exactamente para
  // isto (ISO-58), e uma verificação em código ao lado dela era uma segunda
  // fonte para a mesma regra — a mais fraca das duas. O que faltava era
  // **traduzir** o `23503` dela, que saía da porta como excepção.
  const inserido = await comRecusaDeDominio(() =>
    r.repo.inserirNoTenant({
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
    }),
  );
  if (inserido.tipo === "erro") return erro(inserido.erro);
  const linha = inserido.valor[0];
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

/**
 * Marca uma cotação como aceite. Só sai de `emitida` **e só se não venceu**.
 *
 * **O instante é um argumento e faltava.** O critério 6 diz «cotação expirada
 * não é aceite», e a primeira versão filtrava só por `estado = 'emitida'` — o
 * que não basta precisamente pela razão que este módulo escreve em todo o lado:
 * a expiração é por `valida_ate` e não pelo estado. Uma cotação de Janeiro com
 * `estado='emitida'` passava a `aceite` em Novembro. Achado da revisão
 * adversarial, que usou contra o código o argumento do comentário ao lado dele.
 *
 * `NOT_FOUND` cobre os **quatro** casos em que não há o que aceitar — não
 * existe, é de outro contacto, já não está `emitida`, ou venceu — e isso é
 * deliberado: distingui-los dava a quem chama um oráculo sobre cotações que a
 * RLS já esconde. O quarto caso entrou com o KAM-179, e é o que impede X de pôr
 * a cotação de Y a `aceite` com o `id` que a leitura lhe devolveu.
 */
export async function aceitarCotacao(
  r: Registo,
  contactId: string,
  id: string,
  agora: Date,
): Promise<Resultado<void>> {
  // A forma canónica, pela razão escrita no `getValidQuote`.
  if (!eUuid(contactId)) return erro("VALIDATION_ERROR");
  const linhas = await r.repo.noTenant(SQL_ACEITAR_COTACAO, [
    contactId,
    id,
    agora.toISOString(),
  ]);
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

// ------------------------------------------------ KAM-099: o painel do dono

/**
 * As ofertas do tenant, para a lista do painel (KAM-099, critério 2).
 *
 * **Lê pelo repo-base, como todas as outras**: o tenant é o do `ctx`, e é a
 * única coisa que decide de quem são as linhas. Não há argumento por onde um
 * pedido escolha outro tenant.
 */
export async function listarOfertas(r: Registo): Promise<Resultado<ListaDoPainel>> {
  const linhas = await r.repo.noTenant(SQL_LISTAR_OFERTAS, [LIMITE_DO_PAINEL + 1]);
  return ok({
    itens: linhas.slice(0, LIMITE_DO_PAINEL).map(lerOferta),
    truncada: linhas.length > LIMITE_DO_PAINEL,
  });
}

/**
 * A forma de uma versão: o `to_char` do `SQL_OFERTA_DO_PAINEL`, e nada mais.
 *
 * Uma cadeia qualquer chegava ao `$5::timestamptz` e o PostgreSQL recusava-a
 * com `22007` — uma **excepção**, fora do `Resultado`. Recusada aqui é
 * `VALIDATION_ERROR`, e não custa uma ida à base.
 */
const FORMA_DA_VERSAO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;

/**
 * Grava o preço e, se vier, o stock de uma oferta, **com CAS** (KAM-099).
 *
 * ```text
 * 1. valida                         VALIDATION_ERROR, sem ir à base
 * 2. lê a linha com FOR UPDATE      NOT_FOUND se não existe neste tenant
 * 3. nada muda                      ok se a versão casa, conflito se não
 * 4. SQL_ALTERAR_OFERTA             zero linhas => conflito, com a releitura
 * 5. preço mudou                    audit_log + catalog.price_changed
 * 6. stock veio                     o ajustarStock: audit_log + stock.adjusted
 * ```
 *
 * **O CAS corre sempre que alguma coisa muda, incluindo só o stock**: é a
 * instrução que move a versão, e um ajuste de stock que não passasse por ela
 * gravava sobre uma linha que o dono não viu.
 *
 * **O nível de stock não fica na `stock_quantidade`.** O `ajustarStock` audita
 * e emite o `stock.adjusted` com a quantidade, e não a grava: o `GRANT UPDATE`
 * da `0033` não inclui a coluna, e conceder-lho é uma revisão de base de dados
 * (credor: **KAM-043/049**, que é quem a `0033` nomeia). A lista continua a
 * mostrar o que a coluna tem. É a caixa do stock que fica parcial.
 */
export async function alterarOferta(
  r: Registo,
  a: AlteracaoDeOferta,
): Promise<Resultado<OfertaDoPainel>> {
  // **Só o dono grava pelo painel.** A origem da auditoria é `painel_do_dono`, e
  // um `agente` ou um `sistema` com a credencial interna gravava preços com a
  // origem errada. Achado da revisão adversarial.
  if (r.ctx.actor.kind !== "dono") return erro("VALIDATION_ERROR");
  if (typeof a.sku !== "string" || a.sku.trim().length === 0) return erro("VALIDATION_ERROR");
  if (!(PRECO_TIPOS as readonly string[]).includes(a.precoTipo)) return erro("VALIDATION_ERROR");
  const temPreco = a.precoMinor !== null;
  if (a.precoTipo === SOB_CONSULTA && temPreco) return erro("VALIDATION_ERROR");
  if (a.precoTipo !== SOB_CONSULTA && !temPreco) return erro("VALIDATION_ERROR");
  if (temPreco && (a.precoMinor as bigint) < 0n) return erro("VALIDATION_ERROR");
  if (a.stock !== undefined && (!Number.isSafeInteger(a.stock) || a.stock < 0)) {
    return erro("VALIDATION_ERROR");
  }
  if (typeof a.versao !== "string" || !FORMA_DA_VERSAO.test(a.versao)) {
    return erro("VALIDATION_ERROR");
  }

  const antes = await lerParaEscrita(r, a.sku);
  if (antes === null || antes.estado === "arquivado") return erro("NOT_FOUND");

  // **Um preço com validade conta como mudança**, mesmo com o valor igual: o dono
  // que grava no painel está a pôr o preço **agora**, e o `SQL_ALTERAR_OFERTA`
  // limpa o `preco_valido_ate`. Sem isto, um preço vencido continuava a ler-se
  // `a_partir_de` com aviso depois de o dono o confirmar (critério 4). Achado da
  // revisão adversarial.
  const mudouOPreco =
    antes.precoTipo !== a.precoTipo || antes.precoMinor !== a.precoMinor || antes.precoValidoAte !== null;
  if (!mudouOPreco && a.stock === undefined) {
    // Nada a gravar. A versão continua a decidir a resposta: um dono com uma
    // página velha não recebe «gravado» só porque o valor coincide.
    const actual = await lerOfertaDoPainel(r, a.sku);
    if (actual === null) return erro("NOT_FOUND");
    return actual.versao === a.versao ? ok(actual) : conflito(actual);
  }

  const escrita = await comRecusaDeDominio(() =>
    r.repo.noTenant(SQL_ALTERAR_OFERTA, [a.sku, a.precoTipo, a.precoMinor, a.versao, mudouOPreco]),
  );
  if (escrita.tipo === "erro") return erro(escrita.erro);
  if (escrita.valor.length === 0) {
    // A versão não casou: outra escrita chegou entre a leitura do dono e esta.
    // «Relê e reavalia», com a releitura no corpo.
    const actual = await lerOfertaDoPainel(r, a.sku);
    return actual === null ? erro("NOT_FOUND") : conflito(actual);
  }

  if (mudouOPreco) {
    await registarAlteracaoDePreco(
      r,
      a.sku,
      { preco_tipo: antes.precoTipo, preco_minor: antes.precoMinor, preco_valido_ate: antes.precoValidoAte },
      { preco_tipo: a.precoTipo, preco_minor: a.precoMinor, preco_valido_ate: null },
      "painel_do_dono",
    );
  }
  if (a.stock !== undefined) {
    const ajuste = await ajustarStock(r, { sku: a.sku, qty: a.stock, motivo: "ajuste_do_dono" });
    if (ajuste.tipo !== "ok") {
      // Inalcançável: a quantidade foi validada no passo 1 e a linha está
      // trancada desde o passo 2. **Lança, para desfazer a transacção**: um
      // `erro` devolvido confirmava o preço gravado sem o stock que vinha com ele.
      throw new Error(`o ajuste de stock do painel falhou depois do CAS: ${ajuste.tipo}`);
    }
  }
  const depois = await lerOfertaDoPainel(r, a.sku);
  return depois === null ? erro("NOT_FOUND") : ok(depois);
}

/** Uma oferta na forma do painel, ou `null`. */
async function lerOfertaDoPainel(r: Registo, sku: string): Promise<OfertaDoPainel | null> {
  const linha = (await r.repo.noTenant(SQL_OFERTA_DO_PAINEL, [sku]))[0];
  return linha === undefined ? null : lerOferta(linha);
}

/** Uma linha das duas leituras do painel. */
function lerOferta(linha: Readonly<Record<string, unknown>>): OfertaDoPainel {
  const quantidade = linha["stock_quantidade"];
  return {
    sku: String(linha["sku"]),
    nome: String(linha["nome"]),
    precoTipo: linha["preco_tipo"] as OfertaDoPainel["precoTipo"],
    precoMinor: emMinor(linha["preco_minor"]),
    currency: String(linha["currency"]),
    precoValidoAte: emInstante(linha["preco_valido_ate"]),
    stockModo: linha["stock_modo"] as OfertaDoPainel["stockModo"],
    stockQuantidade:
      quantidade === null || quantidade === undefined ? null : Number(quantidade),
    stockReservada: Number(linha["stock_reservada"] ?? 0),
    stockVerificadoAt: emInstante(linha["stock_verificado_at"]),
    estado: linha["estado"] as EstadoDaOferta,
    versao: String(linha["versao"]),
  };
}

// ------------------------------------------------------------------ auxiliares

/**
 * Corre uma escrita e traduz as recusas **de domínio** da base em `Resultado`.
 *
 * **Isto faltava, e a sua falta quebrava o contrato da porta.** O módulo
 * declarava os três `SQLSTATE` (`consultas.ts`) e não os usava em sítio nenhum —
 * medido por busca pela revisão adversarial —, pelo que uma violação de `CHECK`,
 * de chave estrangeira ou de unicidade saía da porta como **excepção**, e não
 * como o `Resultado` que o `contrato.ts` promete a quem chama. Dois caminhos
 * alcançáveis: um `contactId` de outro tenant numa cotação (`23503`, a FK
 * composta que a `0028` existe para impor) e dois upserts concorrentes do mesmo
 * SKU novo (`23505`).
 *
 * **Só estes três, e deliberadamente.** Uma ligação em baixo, um `40001` ou um
 * `42501` **não** são recusas de domínio: o primeiro é infra-estrutura, o
 * segundo pede retentativa e o terceiro é um privilégio que falta — e traduzir
 * qualquer deles para `VALIDATION_ERROR` dizia ao chamador que os dados dele
 * estavam mal quando o problema era outro. Esses continuam a subir, que é a
 * forma do `CtxEmFaltaError`: um erro de quem montou a chamada ou do ambiente
 * não é uma resposta de domínio que o grafo deva mostrar a um cliente.
 *
 * O `42501` da política `tenant_iso` sobre um `INSERT` é o caso de fronteira, e
 * sobe por desenho: um `WITH CHECK` recusado significa que o `app.tenant_id` da
 * transacção não é o do `ctx`, o que é um defeito de montagem e não um dado
 * inválido.
 */
async function comRecusaDeDominio<T>(
  trabalho: () => Promise<T>,
): Promise<Resultado<T>> {
  try {
    return ok(await trabalho());
  } catch (excepcao) {
    const codigo = (excepcao as { code?: unknown })?.code;
    if (
      codigo === SQLSTATE_CHECK ||
      codigo === SQLSTATE_FK ||
      codigo === SQLSTATE_UNICIDADE
    ) {
      return erro("VALIDATION_ERROR");
    }
    throw excepcao;
  }
}

/** A linha trancada, ou `null`. É o passo 1 da idempotência — ver o módulo. */
async function lerParaEscrita(
  r: Registo,
  sku: string,
): Promise<TermosDaOferta | null> {
  const linhas = await r.repo.noTenant(SQL_TERMOS_PARA_ESCRITA, [sku]);
  const linha = linhas[0];
  return linha === undefined ? null : lerTermos(linha);
}
