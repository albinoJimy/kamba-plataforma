/**
 * O vocabulário do módulo `produtos` — preço opaco e stock não-garantido (KAM-043).
 *
 * Os domínios fechados, os tipos e as constantes. O SQL está em
 * `consultas.ts`, a formatação em `formato.ts`, os eventos em `eventos.ts`, a
 * auditoria em `auditoria.ts` e as operações em `produtos.ts`.
 *
 * ## É `precoTipo`, e não `precoModo`
 *
 * O bloco KAM-043 escrevia `preco_modo` no critério 1 e nas Enumerações; o
 * dicionário §3.3 põe `preco_modo` na coluna «Substitui» desde a emenda 1.12, e
 * o §5.4 e o §7.1/§7.3 do `docs/tecnica/03` já escrevem `preco_tipo`. O
 * dicionário é a fonte 4 e o bloco é a 8, pelo que o lado errado era o bloco —
 * corrigido pelo PR deste ticket, com o conflito registado lá e na emenda 1.52.
 * Os domínios não se redeclaram aqui: importam-se da porta (`PRECO_TIPOS`,
 * `STOCK_MODOS`), que já os tem, porque dois `as const` com os mesmos três
 * valores são duas fontes para a mesma regra.
 *
 * ## Os nomes dos eventos são os do catálogo publicado, não os do critério
 *
 * O critério 5 escreve `price.changed`, `stock.changed`, `stock.low`,
 * `product.published` e `product.updated`. Desses, **só o `stock.low` existe**:
 * o dicionário §3.5 fixa os tipos do Piloto desde a emenda 1.11, e
 * o KAM-007 publicou cada um em `contratos/eventos/<tipo>/v1.schema.json` com
 * `additionalProperties: false`. Os que servem este ticket chamam-se
 * `catalog.price_changed`, `stock.adjusted`, `stock.low` e
 * `catalog.product_changed`.
 *
 * Resolve-se a favor do dicionário (fonte 4) contra o bloco (fonte 8) e contra o
 * §12 do `docs/tecnica/03` (fonte 9) — e **a ordem das fontes não é o argumento
 * mais forte**: emitir com os nomes do critério produzia um envelope que o
 * `validarPayload` recusa com `TipoDesconhecidoError` antes de o *gate* 7 chegar
 * a vê-lo. É a mesma resolução que o `servicos/eventos.ts` registou para o
 * `booking.created`, e a divergência já estava escrita em
 * `docs/dividas-documentais.md` (dívida 37) antes deste ticket.
 *
 * **Dois tipos do critério colapsam num:** `product.published` e
 * `product.updated` são os dois o `catalog.product_changed`, cujo payload leva
 * `{sku, estado}` — o estado distingue-os, e é melhor do que dois tipos, porque
 * um consumidor que queira as duas coisas subscreve um e não dois.
 *
 * ## O `catalog.price_changed` **leva** o preço, e isso não contradiz o ADR-007
 *
 * Vale a pena escrevê-lo porque a leitura contrária é fácil de fazer e estava
 * feita na própria tarefa que abriu este ticket. O ADR-007, à letra
 * (`docs/tecnica/00` §8): «**Preço e stock nunca em embeddings nem em
 * prompts;** vêm de tool calls com validador de citação pós-geração». Não diz
 * «nem no corpo dos eventos». O `docs/tecnica/06` diz onde a regra morde — §44:
 * «o IDX não precisa de preço (ADR-007) e não deve reindexar a cada alteração de
 * preço» — e o mesmo documento manda o DAT **construir** o `preco_obs` a partir
 * deste evento (§5 e §445: «Observações de preço da PME (dado comercial, não
 * pessoal) a partir de `catalog.price_changed`»). Um `catalog.price_changed` sem
 * `preco_minor` deixava o consumidor documentado sem nada para observar.
 *
 * O que o critério 5 proíbe é mais estreito e cumpre-se: **os eventos de
 * produto** não levam preço nem stock. O contrato do `catalog.product_changed`
 * impõe-o por máquina — `properties` tem `sku` e `estado` e mais nada, com
 * `additionalProperties: false`.
 */

import {
  PRECO_TIPOS,
  STOCK_MODOS,
  type Actor,
  type ActorKind,
  type ClienteSql,
  type PrecoTipo,
  type StockModo,
} from "../port/contrato.ts";

export { PRECO_TIPOS, STOCK_MODOS };
export type { ClienteSql, PrecoTipo, StockModo };

/** O modo de preço que **nunca** devolve número (critério 2). */
export const SOB_CONSULTA: PrecoTipo = "sob_consulta";

/** O modo de preço que um preço vencido passa a ter na leitura (§7.1, regra 2). */
export const A_PARTIR_DE: PrecoTipo = "a_partir_de";

/**
 * Os quatro estados de uma oferta (`offer_terms.estado`, revisão `0028`).
 *
 * O mesmo domínio que o `payload.estado` do contrato `catalog.product_changed`
 * v1 fecha, e é de propósito: o evento que anuncia a publicação e a coluna que a
 * guarda não podem ter domínios diferentes.
 */
export const ESTADOS_DA_OFERTA = [
  "rascunho",
  "publicado",
  "pausado",
  "arquivado",
] as const;
export type EstadoDaOferta = (typeof ESTADOS_DA_OFERTA)[number];

/** Os quatro estados de uma cotação (`price_quotes.estado`). */
export const ESTADOS_DA_COTACAO = [
  "emitida",
  "aceite",
  "expirada",
  "revogada",
] as const;
export type EstadoDaCotacao = (typeof ESTADOS_DA_COTACAO)[number];

/** A única moeda (dicionário §3.4). Alargá-la é emenda, não `ALTER`. */
export const MOEDA = "AOA";

/**
 * As duas origens possíveis do preço de uma linha (dicionário §3.40).
 *
 * Quem o escreve no `lines_snapshot` é o **KAM-046**; o par fecha-se aqui porque
 * é este ticket que cria as duas origens.
 */
export const ORIGENS_DE_PRECO = ["offer_terms", "cotacao_dono"] as const;
export type OrigemDePreco = (typeof ORIGENS_DE_PRECO)[number];

/**
 * Os avisos que a vista da oferta pode levar. Lista **fechada**.
 *
 * **Qualificados pela superfície**, como o `state.avisos` do dicionário §3.31 e
 * os seis erros do `ServicosModule` (§3.3): **não** entram em
 * `tool_audit.error_code`, cuja lista o §3.27 declara fechada. São sinais de
 * leitura e não recusas — um `preco_vencido` não impede nada, diz ao agente que
 * tem de pedir confirmação ao dono.
 */
export const AVISOS = [
  "preco_vencido",
  "stock_por_confirmar",
  "confirmacao_dono_necessaria",
] as const;
export type Aviso = (typeof AVISOS)[number];

/**
 * O tecto do stock indicativo por confirmar, em milissegundos. **24 h.**
 *
 * ```text
 * HIPÓTESE
 * - Hipótese: 24 h é o prazo a partir do qual um `stock_modo='indicativo'`
 *   deixa de ser citável sem aviso.
 * - Evidência que a sustenta: o §7.3 do `docs/tecnica/03` escreve «aviso se
 *   `stock_verificado_at` > 24 h».
 * - Estado: INDÍCIO. O §7.3 dá o número e não dá a medição que o produziu; o
 *   objectivo de produto que o calibra é o H8 (≥ 60% de catálogos correctos).
 * - Como validar: a auditoria de divergências do Piloto, por tenant.
 * ```
 *
 * Fica no módulo e não no DDL, pela razão do `TTL_DO_HOLD_MS` do KAM-047: um
 * número no SQL obrigava a uma revisão de base de dados para o calibrar.
 */
export const STOCK_POR_CONFIRMAR_MS = 24 * 60 * 60 * 1000;

/**
 * O limiar abaixo do qual se emite `stock.low`. **Cinco unidades**, *proposta*.
 *
 * O critério 5 di-lo por escrito («*proposta*»). Por tenant quando houver
 * entitlement que o leve; hoje é a omissão do módulo, pela mesma razão do
 * `STOCK_POR_CONFIRMAR_MS`.
 */
export const STOCK_BAIXO_LIMIAR = 5;

/** O máximo de resultados do `searchOffers` (critério 8). */
export const MAXIMO_DE_RESULTADOS = 5;

// ------------------------------------------------------------------- eventos

/** O agregado dos dois eventos de catálogo: o `const` dos contratos v1. */
export const AGREGADO_PRODUTO = "product";

/** O agregado dos dois eventos de stock: o `const` dos contratos v1. */
export const AGREGADO_SKU = "sku";

export const TIPO_PRICE_CHANGED = "catalog.price_changed";
export const VERSAO_PRICE_CHANGED = 1;

export const TIPO_PRODUCT_CHANGED = "catalog.product_changed";
export const VERSAO_PRODUCT_CHANGED = 1;

export const TIPO_STOCK_ADJUSTED = "stock.adjusted";
export const VERSAO_STOCK_ADJUSTED = 1;

export const TIPO_STOCK_LOW = "stock.low";
export const VERSAO_STOCK_LOW = 1;

/**
 * A classe de PII dos quatro: **P0** nos quatro.
 *
 * É o que o `docs/tecnica/06` §5 dá aos dois de catálogo e o que os contratos v1
 * dos quatro fecham (`classe_pii` com `enum: ["P0"]`). E é a classe certa:
 * nenhum dos payloads liga o evento a um contacto — levam `sku`, e um `sku` é
 * uma referência de produto. É a diferença face ao `booking.created`, que é P1
 * porque leva `contact_id`.
 */
export const CLASSE_PII_CATALOGO = "P0";

/** A finalidade dos quatro. `transacao`, como o `booking.created`. */
export const FINALIDADES_CATALOGO = ["transacao"] as const;

/**
 * Os motivos de um `stock.adjusted`. Domínio **fechado**.
 *
 * O `motivo` do contrato v1 é texto livre, e deixá-lo assim era convidar a que
 * cada chamador escrevesse o seu — a mesma lição que o
 * `MOTIVOS_DE_CANCELAMENTO` do KAM-047 escreveu. Dois valores: o dono a
 * actualizar e a conferência que renova o `stock_verificado_at`.
 */
export const MOTIVOS_DE_AJUSTE = ["ajuste_do_dono", "conferencia"] as const;
export type MotivoDeAjuste = (typeof MOTIVOS_DE_AJUSTE)[number];

// ----------------------------------------------------------------- auditoria

/**
 * As duas acções de `audit_log` que este módulo escreve.
 *
 * **Não são nomes novos:** o dicionário §3.2 fecha `action` em **sete** desde a
 * emenda 1.14 (KAM-012), no `CHECK` da revisão `0006`, e estas são duas delas. A
 * primeira versão da emenda 1.52 repetia-as como domínio de dois numa linha do
 * dicionário, e o `canon_lint` do *gate* 3b ficou **vermelho**: ele lê o `CHECK`
 * da `0006` contra o domínio da página e encontrou dois onde há sete. Um domínio
 * fechado tem **um** sítio.
 */
export const ACCAO_PRECO = "price.update";
export const ACCAO_STOCK = "stock.adjust";

/** A `entity` das linhas de auditoria deste módulo. O `entity_id` é o `sku`. */
export const ENTIDADE_AUDITADA = "offer_terms";

/**
 * O mapa do `actor.kind` da porta para o `actor_type` do `audit_log`.
 *
 * **Dois domínios fechados que não coincidem, e nenhum se alarga.** A porta tem
 * quatro valores portugueses (`agente`, `dono`, `sistema`, `ops`, dicionário
 * §3.39) e o `audit_log` tem cinco em inglês (`contact`, `owner`, `staff`,
 * `agent`, `system`, §3.2, `CHECK` da revisão `0006`). O mapa é **total** nos
 * quatro da porta e deixa o `contact` de fora — que é o correcto: um cliente
 * nunca altera preço nem stock, e dar-lhe um caminho para uma linha de
 * auditoria de preço era afirmar que pode.
 *
 * O `ops` vai a `staff` e não a `system`: um operador é uma pessoa, e a
 * diferença entre «a equipa mudou o preço» e «um processo mudou o preço» é
 * exactamente o que quem audita precisa de distinguir.
 */
export const ACTOR_AUDITADO: Readonly<Record<ActorKind, string>> = {
  agente: "agent",
  dono: "owner",
  sistema: "system",
  ops: "staff",
};

// -------------------------------------------------------------------- tipos

/** Os termos comerciais de um SKU, como a base os devolve. */
export interface TermosDaOferta {
  readonly sku: string;
  readonly nome: string;
  readonly precoTipo: PrecoTipo;
  /** `null` se e só se `precoTipo === 'sob_consulta'` (o `CHECK` do critério 1). */
  readonly precoMinor: bigint | null;
  readonly currency: string;
  readonly precoAtualizadoAt: string | null;
  readonly precoValidoAte: string | null;
  readonly stockModo: StockModo;
  readonly stockVerificadoAt: string | null;
  readonly estado: EstadoDaOferta;
  readonly categoriaRestrita: string | null;
  readonly atualizadoAt: string;
}

/**
 * A vista da oferta, com os avisos.
 *
 * **Estende a `OfferView` da porta em vez de a substituir.** A porta declara
 * seis campos (dicionário §3.39) e o `getOfferView` devolve-a tal e qual; os
 * `avisos` são o sétimo e vivem aqui, porque acrescentá-los ao tipo da porta era
 * alargar um contrato fechado que o KAM-042 pinou num teste. Quem consome a
 * porta vê seis campos; quem consome o módulo vê sete.
 */
export interface VistaDaOferta {
  readonly sku: string;
  readonly precoTipo: PrecoTipo;
  readonly precoDisplay: string | null;
  readonly stockModo: StockModo;
  readonly disponibilidade: string;
  readonly atualizadoAt: string;
  readonly avisos: readonly Aviso[];
}

/** Uma cotação do dono, como a base a devolve. */
export interface Cotacao {
  readonly id: string;
  readonly sku: string;
  readonly qty: number;
  readonly precoTotalMinor: bigint;
  readonly currency: string;
  readonly validaAte: string;
  readonly estado: EstadoDaCotacao;
}

/** O que o `searchOffers` devolve por linha. **Sem preço**: ver `produtos.ts`. */
export interface ResultadoDaPesquisa {
  readonly sku: string;
  readonly nome: string;
}

/** O rascunho que o `upsertProductDraft` escreve, já com os termos. */
export interface RascunhoDeProduto {
  readonly sku: string;
  readonly nome: string;
  readonly precoTipo: PrecoTipo;
  readonly precoMinor?: bigint | null;
  readonly precoValidoAte?: string | null;
  readonly stockModo?: StockModo;
}

/** O ajuste de stock do critério 5. */
export interface AjusteDeStock {
  readonly sku: string;
  readonly qty: number;
  readonly motivo: MotivoDeAjuste;
}

// ------------------------------------------------ KAM-099: o painel do dono

/**
 * Quantas ofertas a lista do painel devolve de uma vez. ***Proposta***: 200.
 *
 * Um catálogo de PME do Piloto tem dezenas de produtos, não milhares, e uma
 * lista sem tecto era uma consulta cujo custo cresce com o tenant. Acima disto
 * a resposta diz `truncada` em vez de cortar em silêncio.
 */
export const LIMITE_DO_PAINEL = 200;

/** Uma oferta como o painel a mostra: termos, stock da `0033` e a versão. */
export interface OfertaDoPainel {
  readonly sku: string;
  readonly nome: string;
  readonly precoTipo: PrecoTipo;
  readonly precoMinor: bigint | null;
  readonly currency: string;
  readonly precoValidoAte: string | null;
  readonly stockModo: StockModo;
  /** A `stock_quantidade` da `0033`. `null` quando o dono nunca a declarou. */
  readonly stockQuantidade: number | null;
  readonly stockReservada: number;
  readonly stockVerificadoAt: string | null;
  readonly estado: EstadoDaOferta;
  /** O `atualizado_at` com microssegundos: a versão optimista. */
  readonly versao: string;
}

/** A lista do painel. `truncada` quando havia mais do que `LIMITE_DO_PAINEL`. */
export interface ListaDoPainel {
  readonly itens: readonly OfertaDoPainel[];
  readonly truncada: boolean;
}

/**
 * O que o dono pede ao gravar uma oferta no painel.
 *
 * **O preço inteiro, e não uma diferença**: o painel mostra o valor e o dono
 * grava o que vê. O `stock`, se vier, é o **nível** — a mesma leitura do
 * `AjusteDeStock`.
 */
export interface AlteracaoDeOferta {
  readonly sku: string;
  readonly precoTipo: PrecoTipo;
  readonly precoMinor: bigint | null;
  readonly stock?: number | undefined;
  /** A versão que o dono viu. Com outra na linha, a resposta é `conflito`. */
  readonly versao: string;
}

/** Quem emite uma cotação, e para quem. */
export interface PedidoDeCotacao {
  readonly sku: string;
  readonly qty: number;
  readonly contactId: string;
  readonly precoTotalMinor: bigint;
  readonly validaAte: string;
}

/**
 * O relógio, injectável.
 *
 * Os critérios 2 e 3 dependem do instante — «preço com `preco_valido_ate`
 * ultrapassado», «`stock_verificado_at` > 24 h» —, e um teste que os prove
 * contra `Date.now()` tem de semear datas relativas ao presente. Com o relógio
 * à vista, o caso de fronteira escreve-se como igualdade exacta.
 */
export type Relogio = () => Date;

export const RELOGIO_DO_SISTEMA: Relogio = () => new Date();

/** O actor de uma operação, tal como a porta o dá. */
export type { Actor, ActorKind };
