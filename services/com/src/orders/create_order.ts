/**
 * A *saga* de `createOrder`, idempotente por `intent_key` (KAM-046).
 *
 * ```text
 * T1  INSERT order_intents … ON CONFLICT (tenant_id, intent_key) DO NOTHING
 *     perdeu?  ->  lê o recibo e decide (quatro casos)
 *     ganhou?  ->  revalida preço e stock, confronta o tecto do tenant
 * --  Registo: criar a encomenda com metadata.intent_key   (não existe na Fase 0)
 * T2  escreve orders_mirror + order.created no outbox, e fecha o recibo
 * ```
 *
 * ## São **duas** transacções e não uma, e é isso que faz disto uma *saga*
 *
 * Com uma transacção só, o recibo e o espelho entravam juntos e o
 * `order_intents` **nunca** ficava `em_curso`: o processo que morresse a meio
 * abortava a transacção e o recibo desaparecia com ela. E então o estado
 * `em_curso` do `CHECK` da revisão `0030`, a retoma dos dois minutos do critério
 * 5 e a reconciliação do §10.3 descreviam um estado inalcançável — três
 * mecanismos a guardar uma porta que não existia.
 *
 * O §6.3 escreve a saga em três passos e o passo do meio é **fora da base**:
 * criar a encomenda no Registo. É por isso que o recibo confirma primeiro, só, e
 * o espelho depois: entre os dois há um sistema que pode falhar, e o recibo
 * `em_curso` é a prova de que alguém começou. Na Fase 0 não há Medusa em
 * `infra/compose/` (o KAM-042 registou-o, e o `medusa_order_id` é nulo em toda a
 * fase), pelo que o passo do meio não faz nada — e as duas transacções ficam de
 * propósito, porque é delas que sai a propriedade e não do que corre entre elas.
 *
 * ## O `ON CONFLICT DO NOTHING` é que serializa as cinquenta
 *
 * Não é um `SELECT` antes do `INSERT`, e a diferença é medível: cinquenta
 * leituras concorrentes vêem todas zero linhas e inserem todas. Com
 * `ON CONFLICT DO NOTHING` o PostgreSQL **espera** pela transacção que inseriu a
 * linha em conflito e só depois decide — salta se ela confirmou, insere se ela
 * abortou. É a mesma propriedade que o `upsertProductDraft` do KAM-043 comprou
 * para o SKU novo, e pela mesma razão: um `FOR UPDATE` não tranca uma linha que
 * ainda não existe.
 *
 * Com a T1 a confirmar sozinha, as quarenta e nove que perdem leem o recibo e
 * encontram-no `em_curso` — a T2 do vencedor ainda não correu. Esperam até
 * `TECTO_DE_ESPERA_MS`, releem, e devolvem **a mesma resposta** que o vencedor
 * escreveu. É o critério 3 e a terceira metade do critério 5 na mesma
 * mecânica.
 *
 * ## Os quatro casos de um recibo que já existe
 *
 * | O que o recibo diz | O que se faz |
 * |---|---|
 * | `draft_hash` diferente | `INTENT_REUSED_WITH_DIFFERENT_CONTENT`, **sem** criar nada (critério 4) |
 * | `concluida` | devolve-se a encomenda que ele aponta, com `repeticao: true` (critério 3) |
 * | `em_curso` recente | espera-se até `TECTO_DE_ESPERA_MS` e relê-se; ao fim, `UPSTREAM_TIMEOUT` **sem criar** |
 * | `em_curso` há mais de `MINUTOS_PARA_RETOMAR` | marca-se `falhada` e retoma-se (critério 5) |
 * | `falhada` | retoma-se por `UPDATE` condicional e segue-se |
 *
 * **A retoma é por `UPDATE` condicional e não por leitura-e-escrita**, porque
 * dois leitores de um recibo `falhada` liam os dois `falhada` e corriam os dois
 * a saga. O `WHERE estado = 'falhada'` deixa passar um. É a mesma lição que o
 * `idempotency.py` da TLS escreveu para a barreira do outro lado.
 *
 * ## O que esta função **não** faz, e o credor de cada um
 *
 * * **não reserva stock** — o `reserveStock` e a `stock_reservations` são do
 *   **KAM-045**, e o critério 7 deste bloco diz por extenso que a encomenda do
 *   `confirmar_dono` fica «sem referência nem reserva»;
 * * **não emite `charge.requested`** — esse tipo **não existe** no catálogo
 *   publicado (`contratos/eventos/` tem trinta e oito e nenhum é ele; o §3.5 do
 *   dicionário também não), e emiti-lo levantava `TipoDesconhecidoError` no
 *   `validarPayload` antes de o *gate* 7 ver o envelope. A divergência está na
 *   dívida documental **37** desde o KAM-007: o §12 do `docs/tecnica/03` é um
 *   segundo catálogo de eventos e discorda do `docs/tecnica/06` §5. Credor: o
 *   ticket que acrescentar o trigésimo-nono contrato — **KAM-054/055**, que são
 *   os donos do consumidor;
 * * **não emite estado de pagamento** — é a caixa de DoD «pagamento só por
 *   evento», e aqui é uma propriedade da assinatura: a `registar` do `mirror.ts`
 *   não passa `estado` nenhum (a omissão é `criada`, imposta pelo *trigger*
 *   `order_nasce_criada`) e esta função não chama a `transition`.
 */

import { checkCeiling } from "@kamba/core-ts/ten";

import {
  proposeCart,
  type PedidoDeProposta,
  type Proposta,
  type RascunhoDoCarrinho,
} from "./cart.ts";
import type { Erro } from "../port/contrato.ts";
import {
  CHAVE_DO_TECTO_MANUAL,
  SQLSTATE_UNICIDADE,
  type Ctx,
  type LinhaDaEncomenda,
  type OrderState,
} from "./contrato.ts";
import {
  SQL_CONCLUIR_INTENCAO,
  SQL_ENCOMENDA_DA_CHAVE,
  SQL_FALHAR_INTENCAO,
  SQL_LER_INTENCAO,
  SQL_PEDIDO_POR_PAGAR,
  SQL_RETOMAR_INTENCAO,
} from "./consultas.ts";
import {
  cartIdValido,
  chavesDoAnel,
  draftHash,
  mesmoDraftHash,
  type AnelDoSegredo,
  type PartesDaIntencao,
} from "./intents.ts";
import { registar } from "./mirror.ts";
import { lerEncomenda, type Encomendas } from "./transition.ts";

/**
 * A tabela do recibo de intenção (revisão `0030`), **qualificada pelo esquema**.
 *
 * `platform.order_intents` e não `order_intents`, e não é estilo: o `inserir` do
 * repo-base **constrói** o `INSERT` com o nome que esta constante dá, e nada
 * neste repositório põe o `search_path` — o `comTenant` só corre
 * `set_config('app.tenant_id', …)` e o `db/bootstrap.py` registra que um
 * `ALTER ROLE … SET search_path` é apagado pelo `RESET ALL`. Com o `search_path`
 * por omissão, o `platform` não está lá e o `INSERT` morre em `42P01`. Achado da
 * revisão adversarial.
 *
 * **E as três constantes irmãs do KAM-044 não estão qualificadas** — o
 * `TABELA_DO_ESPELHO` do `mirror.ts`, o `TABELA_DO_REGISTO` do `transition.ts` e
 * o `TABELA_DAS_DIVERGENCIAS` do `reconcile.ts`. Nenhuma está neste diff e
 * corrigi-las é mexer nos ficheiros daquele ticket, pelo que fica **relatado** e
 * não corrigido aqui: é o mesmo defeito latente em três sítios, e nenhum é
 * alcançável hoje porque a porta não está ligada e nada chama estes módulos em
 * produção.
 */
export const TABELA_DAS_INTENCOES = "platform.order_intents";

/**
 * Os códigos que esta operação devolve. Lista **fechada**, e nenhum é novo.
 *
 * **Qualificada pela superfície**, como o `ServicosModule.erro` do §3.3 e os
 * `OfferView.avisos` do §3.40: os **nove** valores são os do
 * `tool_audit.error_code` do §3.27, que o dicionário fecha em **treze** desde a
 * emenda 1.47, e
 * **importam-se** de lá pelo nome em vez de serem redeclarados com significado
 * novo. Nenhum nome novo entra no dicionário por causa desta lista.
 *
 * **E não são os cinco `ERROS` da porta `CommerceRegistry`** (§3.39). Essa lista
 * fecha em `NOT_IMPLEMENTED`, `NOT_FOUND`, `TENANT_MISMATCH`,
 * `VALIDATION_ERROR` e `UPSTREAM_DOWN`, e **nenhum** dos quatro códigos que os
 * critérios 4 e 6 nomeiam cabe lá: um `PRICE_CHANGED` traduzido para
 * `VALIDATION_ERROR` dizia ao cliente que o pedido dele não serve, quando o que
 * mudou foi o preço e o que ele tem de fazer é ver o novo. É exactamente a
 * mesma tensão que o KAM-044 encontrou com o `conflito` do CAS, e resolve-se da
 * mesma forma: o módulo tem o seu domínio, e **ligar isto aos métodos 4 e 5 da
 * porta é alterar o §3.39** — o que é canon e não é deste ticket. Fica registado
 * em `docs/com/port-coverage.md` §2 com o credor.
 */
export const ERROS_DA_CRIACAO = [
  "NOT_FOUND",
  "VALIDATION_ERROR",
  "TENANT_MISMATCH",
  "PRICE_CHANGED",
  "OUT_OF_STOCK",
  "LIMIT_EXCEEDED",
  "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
  "UPSTREAM_TIMEOUT",
  "UPSTREAM_DOWN",
] as const;
export type ErroDaCriacao = (typeof ERROS_DA_CRIACAO)[number];

/**
 * Ao fim de quantos minutos um recibo `em_curso` se considera **abandonado**.
 *
 * Dois, que é o `MINUTOS_PARA_RETOMAR` do §3.28 do dicionário e o ponto 4 do
 * §6.3 do `docs/tecnica/03`: «intenções `em_curso` > 2 min são retomadas ou
 * marcadas `falhada`». **Dois e não os 8,5 s do tecto da classe `money`:** o
 * tecto diz quanto a operação *pode* demorar, e retomar por cima de uma saga
 * viva é o que duplica o efeito.
 */
export const MINUTOS_PARA_RETOMAR = 2;

/**
 * Quanto se espera por um recibo `em_curso` de outro. O «poll ≤ 3 s» do §6.3.
 *
 * É o `TECTO_DE_ESPERA_MS` do §3.28, e **não** é variável de ambiente, pela
 * razão que aquela linha escreve: vem do desenho e não da afinação de um
 * ambiente.
 */
export const TECTO_DE_ESPERA_MS = 3_000;

/**
 * Quanto se dorme entre leituras. Não é configurável: o que o critério nomeia é
 * o tecto, e este valor só decide quantas leituras cabem dentro dele.
 */
export const INTERVALO_DE_ESPERA_MS = 50;

/**
 * A janela do «já tem o pedido K7H3Q9 por pagar» (critério 8).
 *
 * Trinta minutos, e é o mesmo número que a validade do carrinho do §3.31
 * (*proposta*, emenda 1.40): passados trinta minutos o carrinho anterior já não
 * é confirmável, pelo que perguntar por ele era oferecer ao cliente um pedido
 * que ele não consegue pagar sem recomeçar.
 */
export const MINUTOS_DO_PEDIDO_POR_PAGAR = 30;

/** Os três estados em que uma encomenda está «por pagar» (critério 8). */
export const ESTADOS_POR_PAGAR = [
  "criada",
  "aguarda_pagamento",
  "pendente_confirmacao",
] as const;

/** Os cinco subestados de `orders_mirror.confirmacao_dono` (revisão `0030`). */
export const CONFIRMACOES_DO_DONO = [
  "nao_aplicavel",
  "pendente",
  "confirmada",
  "recusada",
  "expirada",
] as const;
export type ConfirmacaoDoDono = (typeof CONFIRMACOES_DO_DONO)[number];

/**
 * Uma transacção com `app.tenant_id` posto, pronta a usar.
 *
 * **Isto é o que torna a saga uma saga**, e é a única peça que este módulo não
 * consegue cumprir com a forma do `transition.ts`: aquela função corre dentro da
 * transacção de quem chama, e aqui são precisas **duas** que confirmem em
 * instantes diferentes. Quem a fornece é quem monta o módulo — o adaptador, com
 * o `comTenant` do `tenant_guard` —, pela mesma razão de sempre: o módulo não
 * escolhe ligações.
 */
export type AbrirTransaccao = <T>(
  trabalho: (e: Encomendas) => Promise<T>,
) => Promise<T>;

/**
 * O pedido de criação. **Não leva `intent_key`, nem preço, nem linhas à parte.**
 *
 * As linhas vêm do `rascunho` e de mais nenhum sítio — ver a nota do
 * `RascunhoDoCarrinho`, que diz o que a primeira versão fez e o que isso custou.
 */
export interface PedidoDeCriacao {
  readonly rascunho: RascunhoDoCarrinho;
  /**
   * O total que o cliente confirmou, em unidade menor.
   *
   * É o que o botão `confirm:{cart_id}` cita e o que o `args_hash` da TLS já
   * fixou (KAM-029, critério 3). **É por ele que se mede o `PRICE_CHANGED`**: a
   * revalidação soma outra vez do `offer_terms` e da cotação, e se o número
   * mudou a encomenda **não** se cria. Sem ele, a revalidação não tinha com o
   * que comparar e o critério 6 era inatingível — recalcular e aceitar o número
   * novo é precisamente cobrar um preço que o cliente não viu.
   */
  readonly totalEsperadoMinor: bigint;
  /** O `cart_id` que o botão citou, para confronto por re-derivação. Opcional. */
  readonly cartId?: string;
}

/** O facto do critério 8. É uma **resposta**, nunca um bloqueio. */
export interface PedidoPorPagar {
  readonly orderId: string;
  readonly numeroPublico: string;
  readonly estado: OrderState;
  readonly totalMinor: bigint;
  readonly currency: string;
  readonly criadoAt: string;
}

/** O que a criação devolve. */
export interface EncomendaCriada {
  readonly orderId: string;
  readonly numeroPublico: string;
  readonly estado: OrderState;
  readonly version: number;
  readonly totalMinor: bigint;
  readonly currency: string;
  readonly confirmacaoDono: ConfirmacaoDoDono;
  readonly linhas: readonly LinhaDaEncomenda[];
  /** `true` quando esta resposta repete uma criação anterior (critério 3). */
  readonly repeticao: boolean;
  /** O facto do critério 8, ou `null`. */
  readonly pedidoPorPagar: PedidoPorPagar | null;
}

/** O resultado, em duas formas. O `erro` é do domínio desta operação. */
export type ResultadoDaCriacao =
  | { readonly tipo: "ok"; readonly valor: EncomendaCriada }
  | { readonly tipo: "erro"; readonly erro: ErroDaCriacao };

function recusar(codigo: ErroDaCriacao): ResultadoDaCriacao {
  return { tipo: "erro", erro: codigo };
}

/**
 * Um erro da porta traduzido para o domínio desta operação.
 *
 * **Quatro dos cinco são o mesmo nome**, porque a porta já os importa do §3.27
 * (ver a nota do `ERROS_DA_CRIACAO`). O quinto — `NOT_IMPLEMENTED` — não é um
 * `tool_audit.error_code` e não pode sair daqui: ele descreve a ausência de uma
 * implementação, pára na API interna do COM e traduz-se para 501 (§3.39). Se
 * chegasse por esta função, chegaria de um módulo que diz não estar
 * implementado — e isso é um defeito de montagem, não uma recusa a mostrar ao
 * cliente, pelo que se levanta em vez de se mascarar num código de domínio.
 *
 * Escreve-se como um `switch` e não com um `as`: um `as` deixava um
 * `NOT_IMPLEMENTED` atravessar sem o `tsc` ver nada.
 */
function doDominio(erroDaPorta: Erro): ErroDaCriacao {
  switch (erroDaPorta) {
    case "NOT_FOUND":
    case "VALIDATION_ERROR":
    case "TENANT_MISMATCH":
    case "UPSTREAM_DOWN":
      return erroDaPorta;
    case "NOT_IMPLEMENTED":
      throw new Error(
        "o propose_cart devolveu NOT_IMPLEMENTED a partir do createOrder: " +
          "aquele codigo nao e um tool_audit.error_code e nao sai para um " +
          "cliente (dicionario 3.39). E defeito de montagem (KAM-046)",
      );
  }
}

/**
 * A autoridade do stock, injectada. **Ausente na Fase 0, e é dito.**
 *
 * O `OUT_OF_STOCK` do critério 6 pede uma autoridade que diga «já não há», e
 * essa autoridade é o Registo: a `offer_terms` do KAM-043 **não tem coluna de
 * quantidade** — o §5.4 põe o stock no Registo e dá àquela tabela o *modo* e o
 * instante da última conferência —, e o Registo da opção B é um Medusa que não
 * existe em `infra/compose/`.
 *
 * Por isso a verificação é um *hook* e não uma consulta: a **passagem** do
 * código está implementada e medida (um *hook* que recusa devolve
 * `OUT_OF_STOCK` e não cria nada), e a **fonte** falta. Credor: o **KAM-045**,
 * que cria a `stock_reservations` e o `UPDATE … WHERE quantidade - reservada >=
 * :q` do §6.4, e o ticket que ligar o inventário do Registo.
 *
 * Sem *hook*, não se recusa — e isso é um *fail-open* consciente e não um
 * descuido: recusar tudo por não haver autoridade fechava o caminho da encomenda
 * em toda a Fase 0, e o que protege o cliente entretanto é o `stock_modo`
 * (`indicativo` diz «a confirmar» e `confirmar_dono` manda perguntar ao dono).
 */
export type AutoridadeDeStock = (
  linhas: readonly LinhaDaEncomenda[],
) => Promise<boolean>;

/** O que o `createOrder` recebe além do pedido. */
export interface MontagemDaCriacao {
  readonly abrir: AbrirTransaccao;
  readonly anel: AnelDoSegredo;
  /** Ver a `AutoridadeDeStock`. Ausente na Fase 0. */
  readonly stockDisponivel?: AutoridadeDeStock;
  /** O relógio. Injectável para que a fronteira da janela seja um ensaio. */
  readonly agora?: () => Date;
  /** A espera. Injectável para que o ensaio do `em_curso` não durma 3 s. */
  readonly dormir?: (ms: number) => Promise<void>;
}

function dormirPorOmissao(ms: number): Promise<void> {
  return new Promise((resolver) => {
    setTimeout(resolver, ms);
  });
}

/**
 * Um recibo de `order_intents`, como a base o tem.
 *
 * **Exportado** porque o `decidirSobreRecibo` o tem na assinatura, e essa
 * função é pura de propósito: a decisão sobre um recibo que já existe mede-se
 * sem base de dados, e só a retoma precisa de uma.
 */
export interface Recibo {
  readonly intentKey: string;
  readonly draftHash: Buffer;
  readonly estado: "em_curso" | "concluida" | "falhada";
  readonly orderId: string | null;
  readonly criadoAt: Date;
}

function lerRecibo(linha: Readonly<Record<string, unknown>>): Recibo {
  const bruto = linha["draft_hash"];
  return {
    intentKey: String(linha["intent_key"]),
    draftHash: Buffer.isBuffer(bruto)
      ? bruto
      : Buffer.from(String(bruto ?? ""), "hex"),
    estado: String(linha["estado"]) as Recibo["estado"],
    orderId: linha["order_id"] === null ? null : String(linha["order_id"]),
    criadoAt:
      linha["criado_at"] instanceof Date
        ? (linha["criado_at"] as Date)
        : new Date(String(linha["criado_at"])),
  };
}

/** Lê o recibo de qualquer das chaves do anel. O mais recente primeiro. */
export async function lerRecibos(
  e: Encomendas,
  chaves: readonly string[],
): Promise<readonly Recibo[]> {
  const linhas = await e.repo.noTenant(SQL_LER_INTENCAO, [[...chaves]]);
  return linhas.map(lerRecibo);
}

/**
 * O facto do critério 8, ou `null`.
 *
 * **Nunca lança e nunca bloqueia.** O critério diz «nunca bloqueia em silêncio»,
 * e a forma de o cumprir é esta: a função devolve um facto, e quem chama
 * põe-no na resposta ao lado da encomenda que criou. O agente é que pergunta.
 */
export async function pedidoPorPagar(
  e: Encomendas,
  contactId: string,
  hash: Buffer,
  chaveActual: string,
  agora: Date,
): Promise<PedidoPorPagar | null> {
  const desde = new Date(
    agora.getTime() - MINUTOS_DO_PEDIDO_POR_PAGAR * 60_000,
  ).toISOString();
  const linhas = await e.repo.noTenant(SQL_PEDIDO_POR_PAGAR, [
    hash,
    contactId,
    desde,
    chaveActual,
  ]);
  const linha = linhas[0];
  if (linha === undefined) return null;
  return {
    orderId: String(linha["id"]),
    numeroPublico: String(linha["numero_publico"]),
    estado: String(linha["estado"]) as OrderState,
    totalMinor: BigInt(String(linha["total_minor"])),
    currency: String(linha["currency"]),
    criadoAt:
      linha["criado_at"] instanceof Date
        ? (linha["criado_at"] as Date).toISOString()
        : String(linha["criado_at"]),
  };
}

/** O SQLSTATE de um erro do *driver*, se ele tiver um. */
function sqlstateDe(erro: unknown): string | null {
  const codigo = (erro as { code?: unknown } | null)?.code;
  return typeof codigo === "string" ? codigo : null;
}

/**
 * A encomenda que **esta chave** já tem, ou `null`. Usada quando o `23505` chega.
 *
 * Lê pela `intent_key` e não pelo `order_id`, porque quando o `23505` chega não
 * se sabe o `order_id`: sabe-se a chave, que é o que a unicidade violada
 * compara.
 */
async function encomendaDaChave(
  e: Encomendas,
  chave: string,
  porPagar: PedidoPorPagar | null,
): Promise<EncomendaCriada | null> {
  const linhas = await e.repo.noTenant(SQL_ENCOMENDA_DA_CHAVE, [chave]);
  const linha = linhas[0];
  return linha === undefined ? null : comoCriada(linha, porPagar);
}

/** A encomenda que um recibo `concluida` aponta, na forma da resposta. */
async function encomendaDoRecibo(
  e: Encomendas,
  orderId: string,
  porPagar: PedidoPorPagar | null,
): Promise<EncomendaCriada | null> {
  const linha = await lerEncomenda(e, orderId);
  return linha === null ? null : comoCriada(linha, porPagar);
}

/**
 * Uma linha de `orders_mirror` na forma da resposta, com `repeticao: true`.
 *
 * **Um projector e não dois**: as duas releituras desta operação — pelo
 * `order_id` de um recibo `concluida` e pela `intent_key` depois de um `23505` —
 * devolvem a mesma forma, e escrevê-la duas vezes era duas fontes para o mesmo
 * mapeamento.
 */
function comoCriada(
  linha: Readonly<Record<string, unknown>>,
  porPagar: PedidoPorPagar | null,
): EncomendaCriada {
  const bruto = linha["lines_snapshot"];
  const snapshot = (
    typeof bruto === "string" ? JSON.parse(bruto) : (bruto ?? [])
  ) as readonly Record<string, unknown>[];
  return {
    orderId: String(linha["id"]),
    numeroPublico: String(linha["numero_publico"]),
    estado: String(linha["estado"]) as OrderState,
    version: Number(linha["version"]),
    totalMinor: BigInt(String(linha["total_minor"])),
    currency: String(linha["currency"]),
    confirmacaoDono: String(linha["confirmacao_dono"]) as ConfirmacaoDoDono,
    linhas: snapshot.map((item) => ({
      sku: String(item["sku"]),
      nome: String(item["nome"] ?? ""),
      qty: Number(item["qty"]),
      precoMinor: BigInt(String(item["preco_minor"])),
      precoTipo: String(item["preco_tipo"]),
      origemPreco: String(item["origem_preco"]),
    })),
    repeticao: true,
    pedidoPorPagar: porPagar,
  };
}

/**
 * O que a fase 1 decidiu. Exactamente um dos três vale.
 *
 * O `nosso` leva a **chave operativa** e não só a proposta, e é por causa do
 * anel: quando o recibo que encontrámos está sob uma versão **anterior** do
 * segredo, é essa chave que a encomenda tem de levar — senão o espelho nasce com
 * uma `intent_key` que o recibo não conhece, e as duas barreiras do Contexto
 * deixam de falar da mesma intenção.
 */
type DesfechoDaFase1 =
  | {
      readonly tipo: "nosso";
      readonly proposta: Proposta;
      readonly chave: string;
    }
  | { readonly tipo: "repeticao"; readonly orderId: string }
  | { readonly tipo: "erro"; readonly erro: ErroDaCriacao };

/**
 * A fase 1 do §6.3: revalida, decide, e **só então** reserva o recibo.
 *
 * Corre inteira numa transacção que confirma antes de a fase 2 começar, e é essa
 * confirmação que torna o `em_curso` observável. Ver a nota do módulo.
 *
 * ## A ordem mudou, e a razão é que a antiga fechava o carrinho por dois minutos
 *
 * A primeira versão reservava o recibo **primeiro** e revalidava depois. O
 * `comTenant` **confirma** quando o trabalho devolve um valor e só desfaz num
 * `throw` (`packages/core-ts/src/tenant_guard/index.ts`), pelo que toda a recusa
 * posterior ao `INSERT` — `PRICE_CHANGED`, `LIMIT_EXCEEDED`, `OUT_OF_STOCK`, o
 * `VALIDATION_ERROR` do `cart_id` — **confirmava** um recibo `em_curso` e
 * devolvia o erro.
 *
 * O que isso fazia, medido: um preço que muda não muda nenhuma das quatro partes
 * da chave nem as linhas do rascunho, pelo que o cliente que aceita o preço novo
 * volta com a **mesma** `intent_key` e o **mesmo** `draft_hash`, encontra o
 * recibo `em_curso` recente, espera três segundos e recebe `UPSTREAM_TIMEOUT`.
 * O caminho normal do critério 6 ficava fechado dois minutos depois de uma
 * recusa legítima, e cada recusa deixava um recibo órfão que ninguém limpa —
 * porque um recibo sem encomenda não é nenhum dos cinco tipos de divergência do
 * §10.3. Achado da revisão adversarial.
 *
 * A correcção é a ordem: **nada se escreve antes de a decisão estar tomada**. As
 * duas leituras que a revalidação paga (os termos e a cotação) são `SELECT`, e
 * N concorrentes pagam-nas N vezes — é o preço de uma recusa não deixar rasto, e
 * é mais barato do que um carrinho envenenado.
 *
 * ## O anel procura-se **antes** do `INSERT`, e só quando há anel
 *
 * O `INSERT … ON CONFLICT (tenant_id, intent_key) DO NOTHING` desempata pela
 * chave **actual**: um recibo derivado com a versão anterior do segredo não
 * gera conflito nenhum, a saga ganha, e nasce uma **segunda** encomenda para o
 * mesmo rascunho — a unicidade da revisão `0030` não junta o que a derivação
 * separou. Medido: duas linhas em `orders_mirror`, e o `SQL_LER_INTENCAO` nunca
 * corrido. Era o anel a ser código morto na saga, com a propriedade contrária
 * escrita no §3.44 do dicionário e no inventário de segredos.
 *
 * Por isso, quando o anel tem mais do que uma versão, procura-se o recibo pelas
 * **antigas** antes de inserir pela actual. Com uma versão só — que é o caso
 * comum e o de sempre até à primeira rotação — não há leitura a mais: o `INSERT`
 * serializa como serializava.
 *
 * A janela que fica é a da própria rotação: dois chamadores concorrentes podem
 * os dois ler o recibo antigo, e aí o que os separa é o estado dele (um replay,
 * ou uma espera, ou o `UPDATE` condicional da retoma). É estreita por construção
 * e está dita.
 */
export async function reservarIntencao(
  e: Encomendas,
  m: MontagemDaCriacao,
  pedido: PedidoDeCriacao,
  chaves: readonly string[],
  hash: Buffer,
  agora: Date,
): Promise<DesfechoDaFase1> {
  const chaveActual = chaves[0] as string;

  // ------------------------------------------- 1. revalidar, sem escrever nada

  const proposta = await proposeCart(e, m.anel, pedido.rascunho, agora);
  if (proposta.tipo === "erro") {
    return { tipo: "erro", erro: doDominio(proposta.erro) };
  }
  const valor = proposta.valor;

  if (
    pedido.cartId !== undefined &&
    !cartIdValido(
      m.anel,
      {
        tenantId: e.ctx.tenantId,
        contactId: pedido.rascunho.contactId,
        draftId: pedido.rascunho.draftId,
        draftVersion: pedido.rascunho.draftVersion,
      },
      pedido.cartId,
    )
  ) {
    // **Pelo `cartIdValido` e não por `!==`**, e são duas diferenças: ele
    // compara em tempo constante — o candidato vem de fora, e uma comparação
    // que sai no primeiro caractere diferente mede quantos acertou — e conhece
    // as **duas** versões do anel, pelo que um `cart_id` emitido antes de uma
    // rotação continua a valer. A primeira versão fazia
    // `pedido.cartId !== valor.cartId`, que não tem nenhuma das duas; achado da
    // revisão adversarial, que notou também que a caixa 5 do DoD afirmava o
    // contrário do que o código fazia.
    return { tipo: "erro", erro: "VALIDATION_ERROR" };
  }

  // O critério 6: «mudança devolve `PRICE_CHANGED` … e não cria».
  if (valor.totalMinor !== pedido.totalEsperadoMinor) {
    return { tipo: "erro", erro: "PRICE_CHANGED" };
  }

  if (m.stockDisponivel !== undefined) {
    const disponivel = await m.stockDisponivel(valor.linhas);
    if (!disponivel) return { tipo: "erro", erro: "OUT_OF_STOCK" };
  }

  // O tecto do tenant: «total acima do limite do tenant devolve
  // `LIMIT_EXCEEDED`». Lê-se por `platform.ten_tecto` pelo `checkCeiling` do
  // `ten`, e **não** por uma consulta nova a `entitlements.limites`: o tecto
  // efectivo é o **mínimo** entre os módulos activos que declaram a chave, e
  // uma leitura directa perdia essa regra. É o mesmo caminho que o
  // `transition.ts` usa para a guarda do `pendente_confirmacao`.
  //
  // O `cabe === false` é recusa, incluindo o `motivo: "sem_entitlement"` — «sem
  // tecto» não quer dizer «sem limite» (critério 2 do KAM-009).
  if (valor.totalMinor > BigInt(Number.MAX_SAFE_INTEGER)) {
    return { tipo: "erro", erro: "VALIDATION_ERROR" };
  }
  const tecto = await checkCeiling(
    e.emitir,
    e.ctx.tenantId,
    CHAVE_DO_TECTO_MANUAL,
    Number(valor.totalMinor),
  );
  if (!tecto.cabe) return { tipo: "erro", erro: "LIMIT_EXCEEDED" };

  // ----------------------------- 2. o anel: há recibo sob uma versão anterior?

  if (chaves.length > 1) {
    const antigo = (await lerRecibos(e, chaves.slice(1)))[0];
    if (antigo !== undefined) {
      return await sobreReciboExistente(e, antigo, valor, hash, agora);
    }
  }

  // --------------------------------------------- 3. reservar o recibo, e só aqui

  const inseridas = await e.repo.inserirNoTenant({
    tabela: TABELA_DAS_INTENCOES,
    valores: { intent_key: chaveActual, draft_hash: hash },
    sufixo:
      "ON CONFLICT (tenant_id, intent_key) DO NOTHING " +
      "RETURNING intent_key, draft_hash, estado, order_id, criado_at",
  });
  if (inseridas.length > 0) {
    return { tipo: "nosso", proposta: valor, chave: chaveActual };
  }

  const recibo = (await lerRecibos(e, chaves))[0];
  if (recibo === undefined) {
    // O `INSERT` não escreveu e não há recibo: só sobra a linha ter sido
    // apagada entre as duas instruções (a retenção do KAM-071 corre como
    // `kamba_batch`). Reler outra vez era um laço; quem chama repete.
    return { tipo: "erro", erro: "UPSTREAM_DOWN" };
  }
  return await sobreReciboExistente(e, recibo, valor, hash, agora);
}

/**
 * O que fazer com um recibo que já existe: decidir e, se for de retomar, retomar.
 *
 * A decisão é pura (`decidirSobreRecibo`) e a retoma é uma escrita, pelo que
 * ficam separadas: a primeira mede-se sem base de dados e a segunda é que precisa
 * de uma.
 */
async function sobreReciboExistente(
  e: Encomendas,
  recibo: Recibo,
  proposta: Proposta,
  hash: Buffer,
  agora: Date,
): Promise<DesfechoDaFase1> {
  const decidido = decidirSobreRecibo(recibo, hash, agora);
  if (decidido.tipo !== "retomar") return decidido;

  // **São duas instruções e não uma**, e cada uma tem o estado esperado no
  // predicado: de N concorrentes passa uma em cada passo. Um `em_curso`
  // abandonado fecha-se primeiro (`em_curso` + velho → `falhada`), e só um
  // `falhada` se reabre — que é a letra do critério 5, «é retomada **ou**
  // marcada `falhada`».
  if (recibo.estado === "em_curso") {
    const falhadas = await e.repo.noTenant(SQL_FALHAR_INTENCAO, [
      recibo.intentKey,
      new Date(agora.getTime() - MINUTOS_PARA_RETOMAR * 60_000).toISOString(),
    ]);
    if (falhadas.length === 0) {
      // Outro fechou-a entretanto. Não se insiste: o estado dele é que vale.
      return { tipo: "erro", erro: "UPSTREAM_TIMEOUT" };
    }
  }
  const retomadas = await e.repo.noTenant(SQL_RETOMAR_INTENCAO, [
    recibo.intentKey,
  ]);
  if (retomadas.length === 0) return { tipo: "erro", erro: "UPSTREAM_TIMEOUT" };
  // A chave operativa é a **do recibo**: com o anel a rodar, a encomenda tem de
  // nascer com a `intent_key` que ele conhece.
  return { tipo: "nosso", proposta, chave: recibo.intentKey };
}

/**
 * O que um recibo que já existe manda fazer. **Função pura**, e por isso medível.
 *
 * Os quatro casos da tabela da nota do módulo, mais um quinto resultado que a
 * tabela não tem porque não é um desfecho: `retomar` quer dizer «é teu, reabre-o»,
 * e quem o faz é quem chama, porque reabrir é escrever.
 *
 * **O `draft_hash` compara-se primeiro**, antes do estado: um recibo `em_curso`
 * com conteúdo diferente não é uma saga a correr para este pedido, e esperar por
 * ela três segundos era esperar pelo trabalho de outro rascunho para depois
 * recusar de qualquer forma (critério 4).
 */
export function decidirSobreRecibo(
  recibo: Recibo,
  hash: Buffer,
  agora: Date,
): DesfechoDaFase1 | { readonly tipo: "retomar" } {
  if (!mesmoDraftHash(recibo.draftHash, hash)) {
    return { tipo: "erro", erro: "INTENT_REUSED_WITH_DIFFERENT_CONTENT" };
  }
  if (recibo.estado === "concluida" && recibo.orderId !== null) {
    return { tipo: "repeticao", orderId: recibo.orderId };
  }
  if (recibo.estado === "em_curso") {
    const idade = agora.getTime() - recibo.criadoAt.getTime();
    if (idade <= MINUTOS_PARA_RETOMAR * 60_000) {
      // Recente: é outra saga a correr. O caminho é esperar, e esse corre
      // **fora** desta transacção — ver o `esperarPorOutra`.
      return { tipo: "erro", erro: "UPSTREAM_TIMEOUT" };
    }
  }
  return { tipo: "retomar" };
}

/**
 * A fase 2 do §6.3: escreve o espelho, emite `order.created` e fecha o recibo.
 *
 * Os três entram na **mesma** transacção, e é o que faz do outbox um outbox: a
 * `registar` do `mirror.ts` emite o evento na transacção de quem chama, e o
 * recibo só diz `concluida` se a encomenda existir — o
 * `order_intents_concluida_exige_encomenda_ck` da revisão `0030` impõe os dois
 * lados ao mesmo tempo.
 *
 * **O `confirmacao_dono` entra no `INSERT` e não num `UPDATE` a seguir** (critério
 * 7): a encomenda nasce `criada` com `pendente` quando alguma linha é
 * `confirmar_dono`, e nasce `nao_aplicavel` quando não é. Num `UPDATE` a seguir
 * havia um instante em que a encomenda estava `criada` com `nao_aplicavel` — e
 * quem a lesse nesse instante concluía que podia emitir referência.
 */
export async function concluirIntencao(
  e: Encomendas,
  chaveActual: string,
  proposta: Proposta,
  rascunho: RascunhoDoCarrinho,
  porPagar: PedidoPorPagar | null,
): Promise<ResultadoDaCriacao> {
  const confirmacao: ConfirmacaoDoDono = proposta.exigeConfirmacaoDoDono
    ? "pendente"
    : "nao_aplicavel";

  let estado;
  try {
      estado = await registar(e, {
      intentKey: chaveActual,
      contactId: rascunho.contactId,
      totalMinor: proposta.totalMinor,
      currency: proposta.currency,
      entregaModo: rascunho.entregaModo,
      linhas: proposta.linhas.map((linha) => ({
      sku: linha.sku,
      nome: linha.nome,
      qty: linha.qty,
      precoMinor: linha.precoMinor,
      precoTipo: linha.precoTipo,
      origemPreco: linha.origemPreco,
      })),
      confirmacaoDono: confirmacao,
      // Nulo em toda a Fase 0: não há Medusa em `infra/compose/` (KAM-042). É a
      // `metadata.intent_key` do §6.3 que ficava do outro lado, e o lado existe
      // quando o Registo existir.
      medusaOrderId: null,
    });
  } catch (erro) {
    // **O `23505` da `orders_mirror_intent_uq` é a resposta, não uma avaria.**
    //
    // Chega aqui quando duas sagas correram para a mesma chave, e isso é
    // alcançável: o `UPDATE_DA_APP_EM_INTENCOES` da revisão `0030` não dá o
    // `criado_at` ao `kamba_app`, pelo que um recibo retomado continua a parecer
    // velho e um segundo chamador pode falhá-lo e retomá-lo por cima de uma saga
    // viva. Quem os separa é a unicidade da base — que é a «segunda barreira
    // independente» que o Contexto do bloco nomeia —, e sem este `catch` ela
    // chegava como **excepção**, fora do `Resultado` que a operação promete:
    // numa operação de classe `money`, um 500 em vez da encomenda que existe.
    //
    // Achado da revisão adversarial. O que ele apanhou não foi a corrida — essa
    // está travada —, foi a **forma** com que o travão chega.
    if (sqlstateDe(erro) !== SQLSTATE_UNICIDADE) throw erro;
    const existente = await encomendaDaChave(e, chaveActual, porPagar);
    if (existente === null) throw erro;
    return { tipo: "ok", valor: existente };
  }

  const fechadas = await e.repo.noTenant(SQL_CONCLUIR_INTENCAO, [
    chaveActual,
    estado.orderId,
  ]);
  if (fechadas.length === 0) {
    // O recibo não estava `em_curso`: outra saga fechou-o entre a fase 1 e a
    // fase 2. **Levanta**, e não devolve um erro: a encomenda que acabámos de
    // escrever nesta transacção ficaria órfã de recibo, e o que tem de acontecer
    // é a transacção reverter inteira — é exactamente o que a reconciliação do
    // §10.3 existe para não ter de limpar.
    throw new Error(
      `platform.order_intents nao fechou o recibo ${chaveActual}: a saga ` +
        "escreveu o espelho e o recibo nao estava em_curso, pelo que outra " +
        "fechou-o entretanto. A transaccao reverte inteira, por desenho " +
        "(KAM-046, criterio 3; docs/tecnica/03 secao 6.3)",
    );
  }

  return {
    tipo: "ok",
    valor: {
      orderId: estado.orderId,
      numeroPublico: estado.numeroPublico,
      estado: estado.estado,
      version: estado.version,
      totalMinor: estado.totalMinor,
      currency: estado.currency,
      confirmacaoDono: confirmacao,
      linhas: proposta.linhas.map((linha) => ({
        sku: linha.sku,
        nome: linha.nome,
        qty: linha.qty,
        precoMinor: linha.precoMinor,
        precoTipo: linha.precoTipo,
        origemPreco: linha.origemPreco,
      })),
      repeticao: false,
      pedidoPorPagar: porPagar,
    },
  };
}

/**
 * Espera que a saga de outro feche, e devolve a encomenda dela.
 *
 * O «poll ≤ 3 s» do §6.3, e corre **fora** de transacção: cada leitura é a sua
 * própria transacção, porque sob `READ COMMITTED` uma transacção aberta vê o
 * mesmo recibo quantas vezes o leia — o `em_curso` nunca mudava, e o laço gastava
 * três segundos a ler uma fotografia.
 */
async function esperarPorOutra(
  m: MontagemDaCriacao,
  chaves: readonly string[],
  contactId: string,
  hash: Buffer,
): Promise<ResultadoDaCriacao> {
  const dormir = m.dormir ?? dormirPorOmissao;
  const relogio = m.agora ?? (() => new Date());
  const chaveActual = chaves[0] as string;
  const limite = relogio().getTime() + TECTO_DE_ESPERA_MS;
  // **O laço tem um tecto de iterações e não só de tempo**, e não é zelo: a
  // saída pelo relógio depende de um relógio **injectado**, e um que não ande
  // deixa este laço sem saída nenhuma. Medido: um ensaio com `agora` fixo e
  // `dormir` que não avança pendurou a suite do COM inteira. Em produção o
  // relógio anda e é o tempo que decide; isto é a barreira para quando não
  // anda, e o tecto é generoso (o dobro das leituras que cabem na janela) para
  // nunca cortar antes do tempo.
  const tecto = Math.ceil(TECTO_DE_ESPERA_MS / INTERVALO_DE_ESPERA_MS) * 2;
  for (let volta = 0; volta < tecto; volta += 1) {
    await dormir(INTERVALO_DE_ESPERA_MS);
    const desfecho = await m.abrir<ResultadoDaCriacao | null>(async (e) => {
      const recibos = await lerRecibos(e, chaves);
      const recibo = recibos[0];
      if (recibo === undefined) return null;
      if (!mesmoDraftHash(recibo.draftHash, hash)) {
        return recusar("INTENT_REUSED_WITH_DIFFERENT_CONTENT");
      }
      if (recibo.estado !== "concluida" || recibo.orderId === null) return null;
      // O facto do critério 8 vale também aqui, e aponta para **outra**
      // encomenda: o `$5` exclui esta chave, pelo que o que ele devolve é um
      // pedido anterior do mesmo contacto com o mesmo rascunho — que é
      // exactamente a pergunta que o agente tem de fazer.
      const porPagar = await pedidoPorPagar(
        e,
        contactId,
        hash,
        chaveActual,
        relogio(),
      );
      const encomenda = await encomendaDoRecibo(e, recibo.orderId, porPagar);
      if (encomenda === null) return recusar("UPSTREAM_DOWN");
      return { tipo: "ok", valor: encomenda };
    });
    if (desfecho !== null) return desfecho;
    if (relogio().getTime() >= limite) break;
  }
  // **`UPSTREAM_TIMEOUT` sem criar nada**, que é a letra do critério 5 do
  // KAM-029 para a barreira do outro lado e a única resposta honesta aqui:
  // criar uma segunda encomenda porque a primeira demora era duplicar
  // exactamente o que esta chave existe para impedir.
  return recusar("UPSTREAM_TIMEOUT");
}

/**
 * `createOrder`: a *saga* do §6.3, idempotente por `intent_key`.
 *
 * Ver a nota do módulo para as duas transacções, para a razão de o
 * `ON CONFLICT DO NOTHING` serializar, e para os quatro casos de um recibo que
 * já existe.
 */
export async function createOrder(
  m: MontagemDaCriacao,
  pedido: PedidoDeCriacao,
): Promise<ResultadoDaCriacao> {
  const relogio = m.agora ?? (() => new Date());
  const agora = relogio();

  let chaves: readonly string[];
  let hash: Buffer;
  try {
    hash = draftHash(pedido.rascunho);
    chaves = await m.abrir(async (e) =>
      chavesDoAnel(m.anel, {
        tenantId: e.ctx.tenantId,
        contactId: pedido.rascunho.contactId,
        draftId: pedido.rascunho.draftId,
        draftVersion: pedido.rascunho.draftVersion,
      } satisfies PartesDaIntencao),
    );
  } catch {
    return recusar("VALIDATION_ERROR");
  }
  const chaveActual = chaves[0] as string;

  const fase1 = await m.abrir((e) =>
    reservarIntencao(e, m, pedido, chaves, hash, agora),
  );

  if (fase1.tipo === "repeticao") {
    return await m.abrir(async (e) => {
      const porPagar = await pedidoPorPagar(
        e,
        pedido.rascunho.contactId,
        hash,
        chaveActual,
        agora,
      );
      const encomenda = await encomendaDoRecibo(e, fase1.orderId, porPagar);
      return encomenda === null
        ? recusar("NOT_FOUND")
        : ({ tipo: "ok", valor: encomenda } as ResultadoDaCriacao);
    });
  }

  if (fase1.tipo === "erro") {
    // O `UPSTREAM_TIMEOUT` da fase 1 **não é a resposta final**: é o sinal de que
    // há uma saga viva com esta chave, e o que o critério 5 manda é esperar por
    // ela até três segundos e devolver a mesma resposta. Os outros códigos são
    // finais.
    if (fase1.erro !== "UPSTREAM_TIMEOUT") return recusar(fase1.erro);
    return await esperarPorOutra(
      m,
      chaves,
      pedido.rascunho.contactId,
      hash,
    );
  }

  // O facto do critério 8 lê-se **antes** de escrever, e com o recibo desta
  // intenção ainda `em_curso`: assim ele não aparece como o seu próprio pedido
  // por pagar. O `$5` do `SQL_PEDIDO_POR_PAGAR` fecha o caso da repetição.
  return await m.abrir(async (e) => {
    const porPagar = await pedidoPorPagar(
      e,
      pedido.rascunho.contactId,
      hash,
      chaveActual,
      agora,
    );
    return await concluirIntencao(
      e,
      // **A chave do desfecho e nao a actual**: com o anel a rodar, a saga
      // pode estar a retomar um recibo sob a versao anterior do segredo, e a
      // encomenda tem de nascer com a `intent_key` que esse recibo conhece.
      fase1.chave,
      fase1.proposta,
      pedido.rascunho,
      porPagar,
    );
  });
}

/** O `Ctx` reexportado, para não obrigar quem usa este módulo a importar a porta. */
export type { Ctx };
