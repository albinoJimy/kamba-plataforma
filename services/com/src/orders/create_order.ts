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
  type Ctx,
  type LinhaDaEncomenda,
  type OrderState,
} from "./contrato.ts";
import {
  SQL_CONCLUIR_INTENCAO,
  SQL_FALHAR_INTENCAO,
  SQL_LER_INTENCAO,
  SQL_PEDIDO_POR_PAGAR,
  SQL_RETOMAR_INTENCAO,
} from "./consultas.ts";
import {
  chavesDoAnel,
  draftHash,
  mesmoDraftHash,
  type AnelDoSegredo,
  type PartesDaIntencao,
} from "./intents.ts";
import { registar } from "./mirror.ts";
import { lerEncomenda, type Encomendas } from "./transition.ts";

/** A tabela do recibo de intenção (revisão `0030`). */
export const TABELA_DAS_INTENCOES = "order_intents";

/**
 * Os códigos que esta operação devolve. Lista **fechada**, e nenhum é novo.
 *
 * **Qualificada pela superfície**, como o `ServicosModule.erro` do §3.3 e os
 * `OfferView.avisos` do §3.40: os oito valores são os do `tool_audit.error_code`
 * do §3.27, que o dicionário fecha em **treze** desde a emenda 1.47, e
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

/** O pedido de criação. **Não leva `intent_key` nem preço** — ver as notas. */
export interface PedidoDeCriacao {
  readonly rascunho: RascunhoDoCarrinho;
  readonly itens: readonly PedidoDeProposta[];
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

/** Um recibo de `order_intents`, como a base o tem. */
interface Recibo {
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

/** A encomenda que um recibo `concluida` aponta, na forma da resposta. */
async function encomendaDoRecibo(
  e: Encomendas,
  orderId: string,
  porPagar: PedidoPorPagar | null,
): Promise<EncomendaCriada | null> {
  const linha = await lerEncomenda(e, orderId);
  if (linha === null) return null;
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

/** O que a fase 1 decidiu. Exactamente um dos três vale. */
type DesfechoDaFase1 =
  | { readonly tipo: "nosso"; readonly proposta: Proposta }
  | { readonly tipo: "repeticao"; readonly orderId: string }
  | { readonly tipo: "erro"; readonly erro: ErroDaCriacao };

/**
 * A fase 1 do §6.3: reserva o recibo, ou lê o que já existe e decide.
 *
 * Corre **inteira** numa transacção que confirma antes de a fase 2 começar, e é
 * essa confirmação que torna o `em_curso` observável. Ver a nota do módulo.
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

  const inseridas = await e.repo.inserirNoTenant({
    tabela: TABELA_DAS_INTENCOES,
    valores: { intent_key: chaveActual, draft_hash: hash },
    sufixo:
      "ON CONFLICT (tenant_id, intent_key) DO NOTHING " +
      "RETURNING intent_key, draft_hash, estado, order_id, criado_at",
  });

  if (inseridas.length === 0) {
    const recibos = await lerRecibos(e, chaves);
    const recibo = recibos[0];
    if (recibo === undefined) {
      // O `INSERT` não escreveu e não há recibo: só sobra a linha ter sido
      // apagada entre as duas instruções (a retenção do KAM-071 corre como
      // `kamba_batch`). Reler outra vez era um laço; quem chama repete.
      return { tipo: "erro", erro: "UPSTREAM_DOWN" };
    }
    // **O `draft_hash` compara-se primeiro**, antes do estado: um recibo
    // `em_curso` com conteúdo diferente não é uma saga a correr para este
    // pedido, e esperar por ela três segundos era esperar pelo trabalho de
    // outro rascunho para depois recusar de qualquer forma (critério 4).
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
      // Abandonada: fecha-se e reabre-se, as duas por `UPDATE` condicional.
      const falhadas = await e.repo.noTenant(SQL_FALHAR_INTENCAO, [
        recibo.intentKey,
        new Date(agora.getTime() - MINUTOS_PARA_RETOMAR * 60_000).toISOString(),
      ]);
      if (falhadas.length === 0) {
        // Outro retomou-a entretanto. Não se insiste: o estado dele é que vale.
        return { tipo: "erro", erro: "UPSTREAM_TIMEOUT" };
      }
    }
    const retomadas = await e.repo.noTenant(SQL_RETOMAR_INTENCAO, [
      recibo.intentKey,
    ]);
    if (retomadas.length === 0) {
      return { tipo: "erro", erro: "UPSTREAM_TIMEOUT" };
    }
  }

  // O recibo é nosso. Agora revalida-se, e **antes** de escrever o espelho.
  const proposta = await proposeCart(
    e,
    m.anel,
    pedido.rascunho,
    pedido.itens,
    agora,
  );
  if (proposta.tipo === "erro") {
    return { tipo: "erro", erro: doDominio(proposta.erro) };
  }
  const valor = proposta.valor;

  if (pedido.cartId !== undefined && pedido.cartId !== valor.cartId) {
    // Um `cart_id` que não se re-deriva não é deste rascunho. Era o caminho pelo
    // qual o carrinho de outro contacto resolvia a intenção deste (ISO-57..60).
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

  return { tipo: "nosso", proposta: valor };
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

  const estado = await registar(e, {
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
      chaveActual,
      fase1.proposta,
      pedido.rascunho,
      porPagar,
    );
  });
}

/** O `Ctx` reexportado, para não obrigar quem usa este módulo a importar a porta. */
export type { Ctx };
