/**
 * O adaptador da **opção B** — Medusa puro + módulo `merchant` (KAM-042).
 *
 * ## A opção B é a recomendação do KAM-041, não uma decisão ratificada
 *
 * ```text
 * HIPÓTESE
 * - Hipótese: o Registo do Piloto é um Medusa v2 único com um módulo custom
 *   `merchant`, e o isolamento entre vendedores é imposto pelo COM (opção B).
 * - Evidência que a sustenta: o spike KAM-041 (2026-10-27) percorreu a árvore
 *   do `docs/tecnica/03` §4.5 e **recomenda** a opção B, com a autoridade da
 *   reserva no `platform`. O harness saiu `1`: AC-1 e AC-8 vermelhos; AC-5,
 *   AC-6, AC-9 e AC-10 não medidos.
 * - Estado: NÃO VERIFICADO como decisão. A D3 em `docs/tecnica/00` §13.3
 *   diz, por escrito, que «falta a assinatura do Arquitecto de Plataforma e do
 *   Responsável de Segurança, e a ratificação do fundador».
 * - Como validar: as duas assinaturas e a ratificação do fundador.
 * ```
 *
 * **E o ADR-003 não nomeia a opção C como fallback — nomeia a B.** A primeira
 * versão deste cabeçalho dizia o contrário, e a revisão adversarial foi ler:
 * o texto do ADR-003 (`docs/tecnica/00` §8) é «Medusa v2 como registo de
 * comércio, condicionado a spike de 5 dias com testes de isolamento entre
 * vendedores; **fallback Medusa puro + `merchant_id`**», mais «Spike feito
 * (KAM-041, 2026-10-27): a recomendação é a opção B (...). **Ratificação
 * pendente do fundador**». Logo o *fallback* do ADR-003 **é** a opção B, que é
 * o que este adaptador implementa; a opção C é o «Fallback 2» do
 * `docs/tecnica/03` §4.5 e não aparece no ADR. A conclusão não muda — este
 * ficheiro não contradiz nem substitui o ADR-003 — mas a razão era falsa, e uma
 * razão falsa a sustentar uma conclusão certa é um defeito, porque o próximo
 * leitor confia nela.
 *
 * É por isso que a porta (`services/com/src/port/contrato.ts`) e o repo-base
 * (`services/com/src/repo-base/`) **não** vivem aqui: nada neles muda entre a opção B e a
 * C, e é onde está o valor que sobrevive à decisão. O que está neste ficheiro é
 * o que a opção B custa.
 *
 * ## O que este adaptador faz hoje
 *
 * **Sete dos doze métodos estão ligados** (KAM-178): os três do catálogo
 * (KAM-043) mais o `requestOwnerConfirmation`, o `transition`, o `getOrder` e o
 * `listOrders`. Os outros cinco devolvem `NOT_IMPLEMENTED` — cada um com o
 * ticket dono escrito em `docs/com/port-coverage.md`, e cada um com um teste
 * que falha no dia em que a implementação chegar sem o teste de isolamento ao
 * lado (critério 6 do KAM-042).
 *
 * **Quatro são as reservas e esperam pelo KAM-045.** O quinto é o `createOrder`,
 * e o credor dele não é um ticket de implementação: é uma **decisão** sobre o
 * §3.39 que ninguém tomou, e está escrita no comentário desse método abaixo. A
 * *saga* do §6.3 **existe e serve-se** — pela API interna (`../../api/interna.ts`),
 * que é a superfície do COM e não a porta.
 *
 * O que **não** é adiado, porque é a costura e não a funcionalidade:
 *
 *   1. o `ctx` verifica-se nas doze, antes de qualquer outra coisa (ISO-09);
 *   2. o `merchant_id` resolve-se de `platform.tenants` e nunca de um
 *      argumento, e um tenant sem ele **falha** em vez de consultar o Registo
 *      inteiro (critério 5);
 *   3. nenhuma consulta ao Registo sai sem `merchant_id = $1` — e isso é do
 *      repo-base, que recusa a consulta que não o nomeie (critério 4).
 *
 * **Não importa o SDK do Medusa**, e aqui dentro ainda não há nenhum import
 * porque o que falta é a ratificação e não o pacote. O que a máquina verifica é
 * outra coisa, e a distinção é da revisão adversarial: o `lint_arch medusa`
 * recusa um `@medusajs/*` **fora** de `services/com/` — o dia em que este
 * ficheiro importar o SDK, nenhum *gate* o impede, porque é ele o dono. A
 * ausência de hoje é uma escolha, não uma propriedade imposta.
 */

import {
  conflito,
  erro,
  eUuid,
  exigirCtx,
  naoImplementado,
  ok,
  PRECO_TIPOS,
  STOCK_MODOS,
  type Cause,
  type ClienteSql,
  type CommerceRegistry,
  type ComTenant,
  type Ctx,
  type Duration,
  type MotivoDeLibertacao,
  type OfferView,
  type OrderFilter,
  type OrderIntent,
  type OrderRef,
  type OrderState,
  type OrderView,
  type OwnerConfirmation,
  type Page,
  type ProductDraft,
  type ProductRef,
  type Reservation,
  type Resultado,
  type ResultadoFinal,
} from "../../port/contrato.ts";
import {
  comoResultadoDaPorta,
  createOrder as createOrderDaSaga,
  filtroLido,
  getOrder as getOrderDoModulo,
  lerEncomenda as lerEncomendaDoModulo,
  listOrders as listOrdersDoModulo,
  proposeCart as proposeCartDoModulo,
  requestOwnerConfirmation as requestOwnerConfirmationDoModulo,
  transition as transitionDoModulo,
  type AnelDoSegredo,
  type AutoridadeDeStock,
  type Encomendas,
  type PedidoDeCriacao,
  type Proposta,
  type RascunhoDoCarrinho,
  type ResultadoDaCriacao,
} from "../../orders/index.ts";
// As quatro primitivas de reserva (KAM-045), mais a autoridade de stock que
// fecha o `OUT_OF_STOCK` do `createOrder`. Os nomes levam `DoModulo` como os do
// `orders`, para que a chamada diga de onde vem.
import {
  autoridadeDeStock as autoridadeDeStockDoModulo,
  commitReservation as commitReservationDoModulo,
  extendReservation as extendReservationDoModulo,
  releaseReservation as releaseReservationDoModulo,
  reserveStock as reserveStockDoModulo,
} from "../../reservations/index.ts";
import {
  idsDoRegisto,
  repoBase,
  type IdsDoRegisto,
  type RepoBase,
} from "../../repo-base/index.ts";
import { SQL_TECTO } from "@kamba/core-ts/ten";

import { SQL_GRAFO } from "../../orders/consultas.ts";
import type { ClienteSql as ClienteSqlDoModulo } from "../../orders/contrato.ts";
import {
  RELOGIO_DO_SISTEMA,
  SQL_AUDITAR,
  SQL_EMITIR,
  confirmacaoValida,
  getOfferView as getOfferViewDoModulo,
  publishProduct as publishProductDoModulo,
  upsertProductDraft as upsertProductDraftDoModulo,
  type RascunhoDeProduto,
  type Relogio,
} from "../../produtos/index.ts";

/**
 * As cadeias que o `Registo.emitir` aceita. Lista **fechada**, e **quatro**
 * desde o KAM-178.
 *
 * As duas primeiras são chamadas de função que escrevem (`evt_emitir`,
 * `audit_append`). As duas que entram agora são **leituras sem filtro de
 * tenant**, e nenhuma é uma excepção aberta a quem vier depois:
 *
 * ```text
 * SQL_TECTO   SELECT platform.ten_tecto($1, $2)   chamada de funcao, nao le tabela
 * SQL_GRAFO   platform.order_state_graph          tabela SEM coluna tenant_id
 * ```
 *
 * O `SQL_TECTO` é do `@kamba/core-ts/ten` e é por onde o `transition` e o
 * `reservarIntencao` lêem o tecto do tenant — o **mínimo** entre os módulos
 * activos, que uma leitura directa a `entitlements.limites` perdia. O
 * `SQL_GRAFO` é o grafo de transições, e o `orders/consultas.ts` já escreveu
 * por que razão ele vem por aqui: «não tem filtro de tenant porque a tabela não
 * tem `tenant_id`: as transições válidas de um sistema não são configuração de
 * tenant. Por isso **não** entra pelo repo-base — entra pela porta estreita das
 * chamadas de função, como o `evt_emitir`». Esta lista é o que faz dessa frase
 * uma propriedade em vez de uma intenção.
 *
 * **Sem elas, ligar a porta era impossível e falhava em execução:** o
 * `checkCeiling` e o `lerGrafo` recebem o `emitir` e levantavam
 * `ChamadaNaoPermitidaError` na primeira transição para `pendente_confirmacao`
 * e em toda a transição — isto é, a barreira recusava o uso correcto, que é o
 * defeito que o `repo-base/index.ts` nomeia («uma barreira que recusa o uso
 * correcto e aceita o contorno não protege: ensina o contorno»).
 *
 * A comparação continua a ser por **igualdade com a constante**, pelo que
 * acrescentar um nome aqui é uma linha visível em revisão — e não um padrão que
 * passa a aceitar uma família de consultas.
 */
const CHAMADAS_PERMITIDAS: readonly string[] = [
  SQL_EMITIR,
  SQL_AUDITAR,
  SQL_TECTO,
  SQL_GRAFO,
];

/** Uma consulta chegou ao `Registo.emitir` que não é uma das duas chamadas. */
export class ChamadaNaoPermitidaError extends Error {
  override readonly name = "ChamadaNaoPermitidaError";
  constructor(sql: string) {
    super(
      "o Registo.emitir aceita quatro cadeias e mais nenhuma: o " +
        "platform.evt_emitir, o platform.audit_append, o platform.ten_tecto e " +
        "o SELECT do platform.order_state_graph. Nao e um cliente " +
        "SQL — e a porta estreita para as duas chamadas de funcao que o " +
        "repo-base nao pode verificar, porque nao tem WHERE. Uma leitura de " +
        "tabela por aqui saia sem filtro de tenant, sem o contador de recusas " +
        "e, no Registo da opcao B, sem RLS atras (KAM-043; KAM-042 criterio 4). " +
        `Usa o r.repo. SQL recusado: ${sql.replace(/\s+/g, " ").trim().slice(0, 120)}`,
    );
  }
}

/**
 * O cliente embrulhado: só as **quatro** cadeias da lista passam.
 *
 * A comparação é por **igualdade com a constante** e não por padrão: um
 * `includes("evt_emitir")` deixava passar
 * `SELECT * FROM product; -- evt_emitir`, e o que se quer afirmar é que o texto
 * é exactamente um dos quatro que este repositório escreveu.
 *
 * **Eram duas e a mensagem do erro dizia duas depois de serem quatro** — achado
 * da revisão adversarial, e não é cosmético: quem estiver a depurar uma
 * `ChamadaNaoPermitidaError` procura as cadeias que a mensagem nomeia, e duas
 * de quatro mandam-no procurar no sítio errado.
 *
 * **Devolve `rowCount` e o `ClienteSql` da porta não o tem.** A forma larga é a
 * do `orders/contrato.ts`, e é a que o `checkCeiling` do `ten` exige na
 * assinatura — com a estreita, o `tsc` recusa a passagem (`TS2345`, medido no
 * *gate* 2 e escrito naquele ficheiro). O `pg` devolve as duas; quando o
 * cliente por baixo não der `rowCount`, usa-se o número de linhas, e isso é
 * exacto para as quatro cadeias desta lista porque **as quatro são `SELECT`**.
 * Nenhuma é um `UPDATE` sem `RETURNING`, que é o único caso em que as duas
 * contagens divergem.
 */
function chamadasDeFuncao(cliente: ClienteSql): ClienteSqlDoModulo {
  return {
    async query(sql: string, parametros?: readonly unknown[]) {
      if (!CHAMADAS_PERMITIDAS.includes(sql)) {
        throw new ChamadaNaoPermitidaError(sql);
      }
      const resposta = await cliente.query(sql, parametros);
      const linhas = resposta.rows as Record<string, unknown>[];
      const contagem = (resposta as { rowCount?: number | null }).rowCount;
      return { rows: linhas, rowCount: contagem ?? linhas.length };
    },
  };
}

/**
 * O `ProductDraft` da porta como rascunho do módulo, ou `null` se não serve.
 *
 * **Os termos de preço vêm do `atributos`**, que é o único campo aberto que o
 * `ProductDraft` do §3.2 dá. É deliberado e não um atalho: o §3.39 do dicionário
 * fecha a porta em doze métodos e o `ProductDraft` em cinco campos, pinados por
 * `port.contrato.test.ts`; acrescentar `precoTipo` e `precoMinor` ao tipo era
 * alargar um contrato que outro ticket fechou, por um ticket que é dono da
 * implementação e não da forma.
 *
 * O que fica dito, porque é uma fronteira e não um detalhe: um `atributos` sem
 * `preco_tipo` é recusado em vez de assumir `sob_consulta`. Assumir punha «preço
 * sob consulta» num produto que o dono queria publicar com preço — e o dono só
 * descobria quando um cliente perguntasse.
 *
 * O `preco_minor` aceita `bigint`, `number` inteiro e `string` de dígitos, e
 * **recusa** um `number` com parte decimal: a coluna é `bigint` e 1200,5
 * cêntimos não existe. `BigInt(1200.5)` lança sozinho, mas lança sem dizer de
 * onde veio.
 */
export function rascunhoDoDraft(d: ProductDraft): RascunhoDeProduto | null {
  if (d === null || d === undefined) return null;
  const atributos = (d.atributos ?? {}) as Readonly<Record<string, unknown>>;

  const precoTipo = atributos["preco_tipo"];
  if (
    typeof precoTipo !== "string" ||
    !(PRECO_TIPOS as readonly string[]).includes(precoTipo)
  ) {
    return null;
  }

  const stockBruto = atributos["stock_modo"];
  if (
    stockBruto !== undefined &&
    (typeof stockBruto !== "string" ||
      !(STOCK_MODOS as readonly string[]).includes(stockBruto))
  ) {
    return null;
  }

  let precoMinor: bigint | null;
  try {
    precoMinor = emMinorDoAtributo(atributos["preco_minor"]);
  } catch {
    return null;
  }

  const validoAte = atributos["preco_valido_ate"];
  if (validoAte !== undefined && validoAte !== null) {
    if (typeof validoAte !== "string" || !Number.isFinite(Date.parse(validoAte))) {
      return null;
    }
  }

  // O `stockModo` entra **só se vier**, e não como `undefined` explícito: o
  // `tsconfig` deste repositório tem `exactOptionalPropertyTypes: true`, pelo
  // que `{stockModo: undefined}` e `{}` são tipos diferentes — e o certo aqui é
  // o segundo, porque quem decide a omissão (`indicativo`) é o módulo e não o
  // adaptador, e passar `undefined` obrigava-o a tratar os dois casos.
  const base = {
    sku: String(d.sku ?? ""),
    nome: String(d.nome ?? ""),
    precoTipo: precoTipo as RascunhoDeProduto["precoTipo"],
    precoMinor,
    precoValidoAte: typeof validoAte === "string" ? validoAte : null,
  };
  return stockBruto === undefined
    ? base
    : {
        ...base,
        // `NonNullable` e nao o tipo da propriedade: ela e opcional, pelo que
        // `RascunhoDeProduto["stockModo"]` inclui `undefined` — e com
        // `exactOptionalPropertyTypes` isso nao e atribuivel a si mesmo neste
        // ramo, onde ja sabemos que ha valor.
        stockModo: stockBruto as NonNullable<RascunhoDeProduto["stockModo"]>,
      };
}

/** O `preco_minor` de um atributo, ou `null`. Lança sobre o que não serve. */
function emMinorDoAtributo(valor: unknown): bigint | null {
  if (valor === null || valor === undefined) return null;
  if (typeof valor === "bigint") return valor;
  if (typeof valor === "number") {
    if (!Number.isInteger(valor)) {
      throw new TypeError("preco_minor nao inteiro");
    }
    return BigInt(valor);
  }
  if (typeof valor === "string" && /^[0-9]+$/.test(valor)) return BigInt(valor);
  throw new TypeError("preco_minor nao e um inteiro em unidade menor");
}

/** O nome do módulo custom do Medusa que a opção B exige (§3.3). */
export const MODULO_MERCHANT = "merchant";

/** O que o adaptador precisa que lhe dêem. */
export interface Dependencias {
  /**
   * A transacção com `app.tenant_id` definido.
   *
   * O papel é o `kamba_app` (critério 8): `NOBYPASSRLS`, sem DDL. Quem o liga
   * é o serviço, e não este ficheiro — ver o `ComTenant`.
   */
  readonly comTenant: ComTenant;
  /**
   * O anel `[actual, anterior]` do `segredo_intents` (§3.44).
   *
   * **Obrigatório, e é o que torna o arranque sem segredo um arranque que não
   * serve pedidos** (KAM-178, critério 6): sem anel não há `intent_key`, não há
   * `cart_id` e não há cursor assinado. Quem o lê do cofre é o serviço, pelo
   * `Secrets.getRing` do KAM-010 — este ficheiro não fala com o cofre, pela
   * mesma razão por que não escolhe ligações.
   */
  readonly anel: AnelDoSegredo;
  /**
   * As bandeiras ligadas, para o grafo de estados do `transition`.
   *
   * Vazio no Piloto, onde o `COM_DELIVERY_ENABLED` está desligado. A base
   * confirma-as por `current_setting('app.com_delivery_enabled')` e, se as duas
   * não concordarem, **ganha a base**.
   */
  readonly bandeiras?: readonly string[];
  /**
   * A autoridade do stock. **Ausente na Fase 0**, e é dito.
   *
   * Ver a `AutoridadeDeStock` do `create_order.ts`: a `offer_terms` não tem
   * coluna de quantidade e o Registo da opção B não existe em `infra/compose/`.
   * Credor: **KAM-045**.
   */
  readonly stockDisponivel?: AutoridadeDeStock;
}

/**
 * O que uma operação do Registo recebe, já com as barreiras postas.
 *
 * Quem a escrever — KAM-043, KAM-044, KAM-045 — recebe um `repo` que **não
 * consegue** emitir uma consulta sem filtro, e um `ids` que só existe se o
 * provisionamento tiver corrido. Não há caminho por onde uma implementação
 * futura chegue à base sem passar por aqui, e é essa a forma do critério 4.
 */
export interface Registo {
  readonly repo: RepoBase;
  readonly ids: IdsDoRegisto;
  readonly ctx: ReturnType<typeof exigirCtx>;
  /**
   * A porta estreita para as **chamadas de função** da transacção.
   *
   * **Não é o `ClienteSql` cru de volta**, e a diferença é o que ela deixa
   * fazer. O repo-base recusa, por desenho, uma consulta sem `WHERE` — e
   * `SELECT platform.evt_emitir(...)` e `SELECT platform.audit_append(...)` não
   * têm `WHERE` nenhum, porque não leem tabela: são chamadas a funções que
   * escrevem no outbox e na cadeia de auditoria, as duas com a sua própria
   * barreira de tenant. O `evt_emitir` é `SECURITY INVOKER` de propósito, para
   * que o `WITH CHECK` da política `tenant_iso` do `events_outbox` continue a
   * aplicar-se; o `audit_append` escreve numa tabela com RLS `FORCE`, e o
   * `audit_encadear` é quem escreve a cadeia.
   *
   * Sem isto, as três escritas deste ticket tinham de sair da transacção da
   * escrita de negócio — e então o preço mudava sem evento, ou o evento saía sem
   * o preço ter mudado, que é precisamente o que o outbox existe para impedir.
   *
   * **E é estreito por execução, não por nota.** A primeira versão deste
   * ticket punha aqui o `cliente` cru e dizia que o que a mantinha estreita era
   * «esta nota e a revisão» — e a revisão adversarial respondeu o que era
   * preciso responder: um ticket futuro escreve
   * `r.emitir.query("SELECT * FROM product WHERE sku = $1", [sku])`, sem filtro
   * de tenant, sem o contador `com_repo_filtro_em_falta_total` a disparar e,
   * no Registo da opção B, **sem RLS atrás**. Era reabrir com outro nome o
   * caminho que a revisão adversarial do KAM-042 fechou — «uma barreira que é
   * uma frase não é uma barreira», e esta era uma frase.
   *
   * Agora o `comRegisto` passa um `ClienteSql` **embrulhado** que recusa
   * qualquer SQL que não seja uma das duas constantes (`chamadasDeFuncao`), e a
   * recusa é uma excepção com a razão escrita. O tipo continua a ser
   * `ClienteSql` de propósito: é o que o `evt_emitir` e o `audit_append` do
   * módulo `produtos` precisam, e mudá-lo obrigava aqueles dois ficheiros a
   * conhecer esta fronteira. O que mudou é que a fronteira passou a morder.
   */
  readonly emitir: ClienteSqlDoModulo;
}

/*
 * **O `ClienteSql` cru não está aqui, e esteve.** A primeira versão passava-o
 * ao lado do `repo`, e a revisão adversarial mostrou o que isso vale: o KAM-043
 * escrevia `r.cliente.query("SELECT * FROM product")` — sem filtro, sem recusa,
 * sem contador — e a frase «não há caminho por onde uma implementação futura
 * chegue à base sem passar por aqui» passava a ser a única barreira. Uma
 * barreira que é uma frase não é uma barreira. Quem precisar do cliente cru
 * tem de o pedir ao `comTenant`, que é uma linha visível em revisão.
 *
 * O que fica ao alcance é o `repoBase`, exportado do `repo-base/` porque os
 * testes dele o constroem. Chamá-lo com um `merchant_id` que não venha do
 * `idsDoRegisto` é possível e é o que a prosa daquele ficheiro proíbe — e isso
 * é disciplina, não tipo. Fica dito em vez de ser dado por fechado.
 */

/**
 * Abre uma operação: valida o `ctx`, entra na transacção, resolve o Registo.
 *
 * **Esta é a função que torna o critério 1 e o critério 5 executáveis.** O
 * `exigirCtx` corre **fora** do `comTenant`, de propósito: um `ctx` sem
 * `tenantId` nunca chega a abrir transacção, e por isso ISO-09 não depende de
 * haver base de dados. O que falha, falha antes de custar uma ligação.
 */
export async function comRegisto<T>(
  deps: Dependencias,
  ctx: Ctx,
  trabalho: (r: Registo) => Promise<T>,
): Promise<T> {
  const validado = exigirCtx(ctx);
  return deps.comTenant(validado.tenantId, async (cliente) => {
    const ids = await idsDoRegisto(cliente, validado.tenantId);
    return trabalho({
      ids,
      ctx: validado,
      repo: repoBase(cliente, validado.tenantId, ids.merchantId),
      emitir: chamadasDeFuncao(cliente),
    });
  });
}

/**
 * O adaptador da opção B.
 *
 * Os doze métodos verificam o `ctx` e devolvem `NOT_IMPLEMENTED`. **A
 * verificação não é cerimónia:** sem ela, um chamador que montasse o `ctx` mal
 * só descobria o defeito no dia em que a implementação chegasse, e descobria-o
 * como um resultado errado em vez de uma excepção. Com ela, o primeiro teste do
 * KAM-043 já corre contra a barreira que vai existir.
 *
 * A resolução do `merchant_id` **não** corre nos métodos vazios: custava uma ida
 * à base para devolver um erro que não depende dela. Corre no `comRegisto`, que
 * é por onde cada implementação entra, e prova-se no seu próprio teste.
 */
export function adaptadorMedusa(
  deps: Dependencias,
  agora: Relogio = RELOGIO_DO_SISTEMA,
): CommerceRegistry {
  return {
    /**
     * KAM-043, critério 4. **Implementado** — já não é `NOT_IMPLEMENTED`.
     *
     * O `ProductDraft` da porta tem `sku`, `nome`, `descricao`, `categoria` e
     * `atributos`; o módulo escreve os três primeiros campos que a
     * `offer_terms` tem e os termos de preço e de stock. A `descricao`, a
     * `categoria` e os `atributos` **não têm coluna** na revisão `0028` e não se
     * perdem em silêncio: pertencem ao Registo, que é quem guarda o produto
     * (§3.3), e o perfil de completude que os valida é o **KAM-049**. Ver a
     * verificação do bloco.
     *
     * Os termos de preço entram pelo `d.atributos`, que é o único campo aberto
     * que a porta dá — e é assim e não com um método novo porque o §3.39 fecha a
     * porta em doze. Um `atributos` sem `preco_tipo` é `VALIDATION_ERROR`: o
     * `offer_terms_preco_ck` exige o par, e adivinhar `sob_consulta` punha
     * preço nenhum num produto que o dono queria publicar com preço.
     */
    async upsertProductDraft(
      ctx: Ctx,
      d: ProductDraft,
    ): Promise<Resultado<ProductRef>> {
      const rascunho = rascunhoDoDraft(d);
      if (rascunho === null) {
        // O `exigirCtx` corre primeiro de qualquer modo (dentro do
        // `comRegisto`), e corre aqui também para que um `ctx` mal montado
        // **não** se esconda atrás de um erro de validação do `d`: a ordem das
        // duas barreiras é a do ISO-09, e é a que o teste afirma.
        exigirCtx(ctx);
        return erro("VALIDATION_ERROR");
      }
      return comRegisto(deps, ctx, (r) =>
        upsertProductDraftDoModulo(r, rascunho),
      );
    },

    /**
     * KAM-043, critério 4. **Implementado.**
     *
     * A confirmação verifica-se **antes** do `comRegisto`, pela razão que este
     * ficheiro já escreveu para o `exigirCtx`: «o que falha, falha antes de
     * custar uma ligação». O módulo repete a verificação por dentro, para quem
     * o use sem a porta — é uma função e duas chamadas, não duas regras.
     */
    async publishProduct(
      ctx: Ctx,
      ref: ProductRef,
      c: OwnerConfirmation,
    ): Promise<Resultado<void>> {
      if (!confirmacaoValida(c)) {
        // O `ctx` primeiro, pela ordem do ISO-09: um `ctx` mal montado não se
        // esconde atrás de um erro de validação do argumento.
        exigirCtx(ctx);
        return erro("VALIDATION_ERROR");
      }
      return comRegisto(deps, ctx, (r) => publishProductDoModulo(r, ref, c));
    },

    /** KAM-043, critérios 2 e 3. **Implementado.** */
    async getOfferView(ctx: Ctx, sku: string): Promise<Resultado<OfferView>> {
      return comRegisto(deps, ctx, (r) =>
        getOfferViewDoModulo(r, sku, agora()),
      );
    },

    /**
     * **Continua `NOT_IMPLEMENTED`, e o credor não é um ticket: é uma decisão.**
     *
     * A *saga* do §6.3 existe, está medida e **serve-se** — pelo
     * `POST /internal/create-order` da API interna (`../../api/interna.ts`), que é
     * a superfície do COM. O que não se consegue ligar é **este método**, e a
     * razão está no tipo do argumento e não em trabalho que falte.
     *
     * O `OrderIntent` do §3.2 tem quatro campos — `intentKey`, `contactId`,
     * `linhas`, `entregaModo` — e o `createOrder` do KAM-046 precisa de três
     * que ele não tem:
     *
     * ```text
     * draftId, draftVersion    a `intent_key` DERIVA-SE deles (§6.3), e o
     *                          modulo recusa uma chave do chamador por escrito:
     *                          «nenhum dos dois se aceita do chamador»
     * totalEsperadoMinor       e por ele que se mede o PRICE_CHANGED; sem ele a
     *                          revalidacao nao tem com o que comparar
     * ```
     *
     * E o terceiro **não é uma omissão a preencher**: o `OrderIntent` diz, na
     * sua própria nota, «nenhuma linha leva preço, e é regra da porta e não
     * omissão» (§3.2, regra 4). O total que o cliente confirmou é um número do
     * chamador, e acrescentá-lo contradiz essa regra escrita.
     *
     * Logo ligar este método pede um **terceiro movimento** no §3.39 — alargar o
     * `OrderIntent` e resolver, por escrito, a tensão com a regra 4 —, e a
     * decisão de 2026-11-04 autoriza **dois**: os nove códigos e o terceiro caso
     * do `Resultado`. Alargá-lo por conta própria era resolver em silêncio um
     * conflito entre o §3.39 e o §3.44, que é o defeito que a ordem das fontes
     * existe para impedir. Fica **devolvido com o credor escrito** na
     * verificação do bloco KAM-178, e em `docs/com/port-coverage.md` §2.
     */
    async createOrder(ctx: Ctx, i: OrderIntent): Promise<Resultado<OrderRef>> {
      exigirCtx(ctx);
      void i;
      return naoImplementado();
    },

    /**
     * **Ligado** ao `owner_confirmation.ts` do KAM-046 (KAM-178, critério 3).
     *
     * Os três casos do módulo atravessam a porta um a um — e o `conflito` é o
     * terceiro caso do `Resultado` e não um `VALIDATION_ERROR`: a encomenda já
     * saiu de `criada`, ou o subestado é outro, e o que quem chama tem de fazer
     * é reler.
     *
     * **O limite, que fica dito:** o `Resultado<void>` do §3.2 não leva o
     * subestado relido, porque o `void` não tem onde o levar. Quem o precisa
     * lê-o com o `getOrder`. Ver a nota do `Conflito` no `../../port/contrato.ts`.
     */
    async requestOwnerConfirmation(
      ctx: Ctx,
      orderId: string,
    ): Promise<Resultado<void>> {
      return comRegisto(deps, ctx, async (r) => {
        const resultado = await requestOwnerConfirmationDoModulo(
          encomendasDe(deps, r),
          orderId,
        );
        if (resultado.tipo === "ok") return ok(undefined);
        if (resultado.tipo === "erro") return erro(resultado.erro);
        return conflito(undefined);
      });
    },

    /**
     * **Ligado** ao `reservations/reserve.ts` do KAM-045 (critérios 1 e 2).
     *
     * As linhas vêm do `lines_snapshot` da encomenda e **não** do chamador: o
     * `reserveStock(ctx, orderId, ttl)` do §3.2 não leva linhas, e tem razão —
     * as linhas de uma encomenda são as que ela tem, e aceitá-las do chamador
     * deixava reservar stock de um SKU que a encomenda não pede.
     *
     * O `line_no` é o **índice** no `lines_snapshot`, que é o que lhe dá
     * identidade: aquele `jsonb` é uma lista sem chaves próprias (§10.1), e a
     * `stock_reservations_linha_uq` da revisão `0033` fixa o par
     * `(order_id, line_no)`.
     *
     * **A atomicidade por encomenda é do `comTenant`**, que abre uma
     * transacção: uma linha sem stock devolve `OUT_OF_STOCK` e o `rollback`
     * desfaz as que já tinham passado. Ver a nota do módulo das reservas para a
     * razão de não haver compensação em código.
     */
    async reserveStock(
      ctx: Ctx,
      orderId: string,
      ttl: Duration,
    ): Promise<Resultado<readonly Reservation[]>> {
      return comRegisto(deps, ctx, async (r) => {
        const encomenda = await lerEncomendaDoModulo(
          encomendasDe(deps, r),
          orderId,
        );
        if (encomenda === null) return erro("NOT_FOUND");
        const snapshot = encomenda["lines_snapshot"];
        if (!Array.isArray(snapshot)) return erro("VALIDATION_ERROR");
        const linhas = snapshot.map((linha, indice) => ({
          lineNo: indice,
          sku: String((linha as Record<string, unknown>)["sku"] ?? ""),
          qty: Number((linha as Record<string, unknown>)["qty"] ?? 0),
        }));
        const resultado = await reserveStockDoModulo({ repo: r.repo }, {
          orderId,
          linhas,
          ttlMs: ttl,
        });
        if (resultado.tipo === "erro") return erro(resultado.erro);
        return ok(
          resultado.valor.map((reserva) => ({
            reservationId: reserva.reservationId,
            sku: reserva.sku,
            qty: reserva.qty,
            expiraAt: reserva.expiraAt,
          })),
        );
      });
    },

    /**
     * **Ligado** ao `reservations/reserve.ts` (critério 7).
     *
     * **A condição «só em `aguarda_pagamento`» é imposta aqui**, e é dito por
     * escrito no módulo: ele não lê o `orders_mirror`, e esta é a camada que já
     * tem o estado da encomenda em mão. As outras duas condições do critério —
     * o tecto de 72 h e «exige cobrança com validade correspondente» — estão no
     * `SQL_ESTENDER`, contra a base.
     */
    async extendReservation(
      ctx: Ctx,
      orderId: string,
      until: string,
    ): Promise<Resultado<void>> {
      return comRegisto(deps, ctx, async (r) => {
        const encomenda = await lerEncomendaDoModulo(
          encomendasDe(deps, r),
          orderId,
        );
        if (encomenda === null) return erro("NOT_FOUND");
        if (String(encomenda["estado"]) !== "aguarda_pagamento") {
          return erro("VALIDATION_ERROR");
        }
        const resultado = await extendReservationDoModulo(
          { repo: r.repo },
          orderId,
          until,
        );
        if (resultado.tipo === "erro") return erro(resultado.erro);
        return ok(undefined);
      });
    },

    /**
     * **Ligado** ao `reservations/reserve.ts` (critério 6, lado `consumida`).
     *
     * Idempotente: a segunda chamada muda zero linhas e devolve `ok`, porque
     * «já estava consumida» é o estado que quem chama queria. Ver a nota do
     * `commitReservation` do módulo.
     */
    async commitReservation(
      ctx: Ctx,
      orderId: string,
    ): Promise<Resultado<void>> {
      return comRegisto(deps, ctx, async (r) => {
        // **A encomenda lê-se antes, e é o ISO-01..08 e não zelo.**
        //
        // O módulo devolve `ok` com zero reservas mudadas, e tem de o fazer: é
        // a idempotência do critério 4 («já estava consumida» é o estado que
        // quem chama queria). Mas `ok` para uma encomenda que **não é do
        // chamador** confundia duas coisas diferentes — «não havia nada a
        // consumir» e «isso não é teu» —, e o critério 6 do KAM-042 pede que a
        // segunda seja `NOT_FOUND`.
        //
        // Com a leitura, as duas ficam distintas: a encomenda existe e é do
        // tenant do `ctx`, pelo que zero linhas é mesmo idempotência. Custa
        // uma leitura por chamada e é o que separa um caminho seguro de um
        // caminho que **parece** seguro.
        const encomenda = await lerEncomendaDoModulo(
          encomendasDe(deps, r),
          orderId,
        );
        if (encomenda === null) return erro("NOT_FOUND");
        const resultado = await commitReservationDoModulo(
          { repo: r.repo },
          orderId,
        );
        if (resultado.tipo === "erro") return erro(resultado.erro);
        return ok(undefined);
      });
    },

    /**
     * **Ligado** ao `reservations/reserve.ts` (critério 6, lado `libertada`).
     *
     * O `motivo` atravessa intacto: o domínio dele é o `MOTIVOS_DE_LIBERTACAO`
     * do `../../port/contrato.ts` e o `stock_reservations_motivo_ck` da revisão
     * `0033`, e os dois têm os mesmos três nomes.
     */
    async releaseReservation(
      ctx: Ctx,
      orderId: string,
      motivo: MotivoDeLibertacao,
    ): Promise<Resultado<void>> {
      return comRegisto(deps, ctx, async (r) => {
        // A leitura primeiro, pela razão do `commitReservation` acima: separa
        // «não havia nada a libertar» de «isso não é teu».
        const encomenda = await lerEncomendaDoModulo(
          encomendasDe(deps, r),
          orderId,
        );
        if (encomenda === null) return erro("NOT_FOUND");
        const resultado = await releaseReservationDoModulo(
          { repo: r.repo },
          orderId,
          motivo,
        );
        if (resultado.tipo === "erro") return erro(resultado.erro);
        return ok(undefined);
      });
    },

    /**
     * **Ligado** à primitiva do KAM-044 (KAM-178, critério 3).
     *
     * O `comoResultadoDaPorta` leva os três casos intactos, com o `conflito` a
     * trazer a releitura: é o segundo movimento da decisão de 2026-11-04, e é o
     * que torna o §6.2 («falha de CAS ⇒ reler e reavaliar, nunca forçar»)
     * observável do lado de quem chama a porta.
     *
     * **Duas transições não são alcançáveis por aqui, e é do tipo e não do
     * módulo:** o `entregue` exige `entrega_confirmada_por` (o contrato do
     * `order.delivered` e o `orders_mirror_entregue_exige_quem_ck`) e o
     * `expirada` exige um instante quando a encomenda não tem `expira_at`. O
     * `Cause` do §3.2 é `{causa, eventoId}` e não leva nenhum dos dois, pelo que
     * as duas respondem `VALIDATION_ERROR` por esta via. É o mesmo credor do
     * `createOrder` — uma decisão sobre o §3.39 — e está escrito na verificação
     * do bloco; as duas alcançam-se pelo módulo, que é por onde o KAM-050 e o
     * varrimento de expiração as vão chamar.
     */
    async transition(
      ctx: Ctx,
      orderId: string,
      to: OrderState,
      expectedVersion: number,
      causa: Cause,
    ): Promise<Resultado<OrderRef>> {
      return comRegisto(deps, ctx, async (r) => {
        const resultado = await transitionDoModulo(encomendasDe(deps, r), {
          orderId,
          para: to,
          expectedVersion,
          causa: { causa: causa?.causa ?? "", eventoId: causa?.eventoId ?? null },
        });
        return comoResultadoDaPorta(resultado);
      });
    },

    /**
     * **Ligado** ao `listagem.ts` (KAM-178, critério 3).
     *
     * O `orderId` verifica-se **antes** do `comRegisto`, pela regra que este
     * ficheiro já escreve para o `exigirCtx` e para a `OwnerConfirmation`: «o
     * que falha, falha antes de custar uma ligação». O módulo repete a
     * verificação por dentro, para quem o use sem a porta.
     */
    async getOrder(ctx: Ctx, orderId: string): Promise<Resultado<OrderView>> {
      if (!eUuid(orderId)) {
        // O `ctx` primeiro, pela ordem do ISO-09: um `ctx` mal montado não se
        // esconde atrás de um erro de validação do argumento.
        exigirCtx(ctx);
        return erro("VALIDATION_ERROR");
      }
      return comRegisto(deps, ctx, (r) =>
        getOrderDoModulo({ ctx: r.ctx, repo: r.repo }, orderId),
      );
    },

    /**
     * **Ligado** ao `listagem.ts`, com o cursor opaco (KAM-178, critérios 3 e 4).
     *
     * O anel vem das dependências e não do argumento: é com ele que o cursor se
     * assina, e um cursor cuja chave viesse de fora era um cursor que quem chama
     * pode fabricar.
     */
    async listOrders(
      ctx: Ctx,
      f: OrderFilter,
    ): Promise<Resultado<Page<OrderView>>> {
      // **Os três casos do ISO-10 recusam-se aqui, antes da transacção**, e é
      // uma correcção que um caso vermelho apanhou: com a validação só dentro
      // do módulo, um filtro vazio pagava uma ida à base (o `idsDoRegisto` do
      // `comRegisto`) para devolver um erro que não depende dela. O `filtroLido`
      // é puro e precisa só do anel e do tenant, que existem antes de haver
      // ligação.
      const validado = exigirCtx(ctx);
      const lido = filtroLido(deps.anel, validado.tenantId, f);
      if (lido.tipo === "erro") return lido;
      return comRegisto(deps, ctx, (r) =>
        listOrdersDoModulo({ ctx: r.ctx, repo: r.repo }, deps.anel, f),
      );
    },
  };
}

/**
 * O `Encomendas` que os módulos do KAM-044 e do KAM-046 recebem.
 *
 * O `Registo` do `comRegisto` já tem as três peças — `ctx` validado, `repo` que
 * recusa uma consulta sem filtro, `emitir` estreito às quatro cadeias — e esta
 * função só lhes dá o nome que aqueles módulos esperam. As bandeiras vêm das
 * dependências porque são **configuração do serviço** e não argumento de
 * negócio, e entram **só se vierem**: com `exactOptionalPropertyTypes`,
 * `{bandeiras: undefined}` e `{}` são tipos diferentes, e o certo é o segundo —
 * quem decide a omissão é o módulo.
 */
function encomendasDe(deps: Dependencias, r: Registo): Encomendas {
  const base = { ctx: r.ctx, repo: r.repo, emitir: r.emitir };
  return deps.bandeiras === undefined
    ? base
    : { ...base, bandeiras: deps.bandeiras };
}

/**
 * As operações do COM: a porta, mais as duas que a porta não nomeia.
 *
 * ## Porque é que isto existe, e porque é que não é um décimo-terceiro método
 *
 * O §3.39 fecha a porta em **doze** métodos, e a contagem está presa num teste.
 * Duas operações que a API interna serve não estão lá:
 *
 * ```text
 * proposeCart   le e nao escreve; e a tool `propose_cart` do §6.2, e o
 *               `cart.ts` do KAM-046 e que a implementa
 * createOrder   a saga do §6.3, com as DUAS transaccoes e o pedido completo
 *               (`PedidoDeCriacao`), que o `OrderIntent` do §3.2 nao expressa
 * ```
 *
 * Acrescentá-las à porta era alargar um contrato que o dicionário fecha — a
 * mesma recusa que o `rascunhoDoDraft` deste ficheiro já escreveu para o
 * `precoTipo`. Por isso a API interna consome **esta** interface, e a porta
 * continua a ser a costura do PA-03-1: trocar de Registo troca o adaptador, e
 * estas duas vêm com ele.
 */
export interface OperacoesDoCom {
  /** A porta, com os sete métodos ligados. */
  readonly porta: CommerceRegistry;
  /** O `propose_cart` do §6.2. Lê e não escreve. */
  proposeCart(
    ctx: Ctx,
    rascunho: RascunhoDoCarrinho,
  ): Promise<ResultadoFinal<Proposta>>;
  /** A *saga* do §6.3, idempotente por `intent_key`. */
  createOrder(ctx: Ctx, pedido: PedidoDeCriacao): Promise<ResultadoDaCriacao>;
}

/**
 * As operações do COM, montadas sobre o adaptador da opção B.
 *
 * **O `abrir` da *saga* é `comRegisto` chamado outra vez**, e é o que lhe dá as
 * duas transacções do §6.3: cada chamada entra num `comTenant` novo, que
 * confirma quando o trabalho devolve um valor. As chamadas da *saga* são
 * **sequenciais** e nunca aninhadas — é o que o `LigacaoEmUsoError` do
 * `tenant_guard` exige de quem partilha uma ligação —, e o `esperarPorOutra`
 * dela corre fora de transacção de propósito, porque sob `READ COMMITTED` uma
 * transacção aberta lê o mesmo recibo quantas vezes o leia.
 */
export function operacoesDoCom(
  deps: Dependencias,
  agora: Relogio = RELOGIO_DO_SISTEMA,
): OperacoesDoCom {
  return {
    porta: adaptadorMedusa(deps, agora),

    async proposeCart(ctx: Ctx, rascunho: RascunhoDoCarrinho) {
      return comRegisto(deps, ctx, (r) =>
        proposeCartDoModulo(
          { ctx: r.ctx, repo: r.repo },
          deps.anel,
          rascunho,
          agora(),
        ),
      );
    },

    async createOrder(ctx: Ctx, pedido: PedidoDeCriacao) {
      // O `exigirCtx` corre **antes** da primeira transacção, como em todo o
      // resto deste ficheiro: um `ctx` sem tenant não abre ligação nenhuma
      // (ISO-09), e aqui isso vale duas vezes porque a saga abre três.
      exigirCtx(ctx);
      const montagem = {
        abrir: <T>(trabalho: (e: Encomendas) => Promise<T>): Promise<T> =>
          comRegisto(deps, ctx, (r) => trabalho(encomendasDe(deps, r))),
        anel: deps.anel,
        agora: () => agora(),
        // **A fonte do `OUT_OF_STOCK`, e é a dívida que o KAM-045 vem pagar.**
        //
        // O `AutoridadeDeStock` do `../../orders/create_order.ts` é um *hook*
        // desde o KAM-046 e a nota dele dizia «a **passagem** do código está
        // implementada e medida … e a **fonte** falta. Credor: o **KAM-045**».
        // Com a `offer_terms.stock_quantidade` da revisão `0033`, a fonte
        // existe: o `autoridadeDeStock` lê quantidade menos reservada por SKU.
        //
        // O `deps.stockDisponivel` continua a ganhar quando vem dado, e isso
        // não é indecisão: é o que deixa um ensaio injectar uma autoridade que
        // recusa sem precisar de uma base com stock, e é o que deixará o
        // inventário do Registo substituir esta leitura sem tocar aqui.
        //
        // **O que deixou de existir é o caso «sem autoridade nenhuma».** Era um
        // *fail-open* consciente enquanto não havia fonte; com fonte, deixá-lo
        // de pé era escolher não olhar para o número que agora temos.
        stockDisponivel:
          deps.stockDisponivel ??
          ((linhas) =>
            comRegisto(deps, ctx, (r) =>
              autoridadeDeStockDoModulo({ repo: r.repo })(linhas),
            )),
      };
      return createOrderDaSaga(montagem, pedido);
    },
  };
}
