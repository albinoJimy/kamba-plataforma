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
 * Os doze métodos devolvem `NOT_IMPLEMENTED` — cada um com o ticket dono
 * escrito em `docs/com/port-coverage.md`, e cada um com um teste que falha no
 * dia em que a implementação chegar sem o teste de isolamento ao lado
 * (critério 6). O que **não** é adiado, porque é a costura e não a
 * funcionalidade:
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
  erro,
  exigirCtx,
  naoImplementado,
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
} from "../../port/contrato.ts";
import {
  idsDoRegisto,
  repoBase,
  type IdsDoRegisto,
  type RepoBase,
} from "../../repo-base/index.ts";
import {
  RELOGIO_DO_SISTEMA,
  confirmacaoValida,
  getOfferView as getOfferViewDoModulo,
  publishProduct as publishProductDoModulo,
  upsertProductDraft as upsertProductDraftDoModulo,
  type RascunhoDeProduto,
  type Relogio,
} from "../../produtos/index.ts";

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
   * **O que a mantém estreita é a revisão**, e fica dito em vez de ser dado por
   * fechado: o tipo é o mesmo `ClienteSql`, e nada no compilador impede alguém
   * de lhe passar `SELECT * FROM product`. O que impede é esta nota e o facto de
   * cada uso ser uma linha visível — e as cadeias que o módulo `produtos` lhe
   * envia são **duas**, as duas constantes (`SQL_EMITIR`, `SQL_AUDITAR`), as
   * duas chamadas de função, e as duas lidas pelo *gate* 8 do próprio ficheiro
   * TypeScript. A revisão adversarial do KAM-042 recusou o cliente cru ao lado
   * do `repo` por este caminho ser mais largo do que o necessário; este é o
   * estreito que ele obriga a abrir, com o nome do que faz.
   */
  readonly emitir: ClienteSql;
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
      emitir: cliente,
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

    async createOrder(ctx: Ctx, i: OrderIntent): Promise<Resultado<OrderRef>> {
      exigirCtx(ctx);
      void i;
      return naoImplementado();
    },

    async requestOwnerConfirmation(
      ctx: Ctx,
      orderId: string,
    ): Promise<Resultado<void>> {
      exigirCtx(ctx);
      void orderId;
      return naoImplementado();
    },

    async reserveStock(
      ctx: Ctx,
      orderId: string,
      ttl: Duration,
    ): Promise<Resultado<readonly Reservation[]>> {
      exigirCtx(ctx);
      void orderId;
      void ttl;
      return naoImplementado();
    },

    async extendReservation(
      ctx: Ctx,
      orderId: string,
      until: string,
    ): Promise<Resultado<void>> {
      exigirCtx(ctx);
      void orderId;
      void until;
      return naoImplementado();
    },

    async commitReservation(
      ctx: Ctx,
      orderId: string,
    ): Promise<Resultado<void>> {
      exigirCtx(ctx);
      void orderId;
      return naoImplementado();
    },

    async releaseReservation(
      ctx: Ctx,
      orderId: string,
      motivo: MotivoDeLibertacao,
    ): Promise<Resultado<void>> {
      exigirCtx(ctx);
      void orderId;
      void motivo;
      return naoImplementado();
    },

    async transition(
      ctx: Ctx,
      orderId: string,
      to: OrderState,
      expectedVersion: number,
      causa: Cause,
    ): Promise<Resultado<OrderRef>> {
      exigirCtx(ctx);
      void orderId;
      void to;
      void expectedVersion;
      void causa;
      return naoImplementado();
    },

    async getOrder(ctx: Ctx, orderId: string): Promise<Resultado<OrderView>> {
      exigirCtx(ctx);
      void orderId;
      return naoImplementado();
    },

    async listOrders(
      ctx: Ctx,
      f: OrderFilter,
    ): Promise<Resultado<Page<OrderView>>> {
      exigirCtx(ctx);
      void f;
      return naoImplementado();
    },
  };
}
