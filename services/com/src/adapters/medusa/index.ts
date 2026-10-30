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
  exigirCtx,
  naoImplementado,
  type Cause,
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
export function adaptadorMedusa(deps: Dependencias): CommerceRegistry {
  // O `deps` fica capturado para as implementações que chegarem; hoje o que o
  // usa é o `comRegisto`, exportado acima e exercitado pelos testes.
  void deps;

  return {
    async upsertProductDraft(
      ctx: Ctx,
      d: ProductDraft,
    ): Promise<Resultado<ProductRef>> {
      exigirCtx(ctx);
      void d;
      return naoImplementado();
    },

    async publishProduct(
      ctx: Ctx,
      ref: ProductRef,
      c: OwnerConfirmation,
    ): Promise<Resultado<void>> {
      exigirCtx(ctx);
      void ref;
      void c;
      return naoImplementado();
    },

    async getOfferView(ctx: Ctx, sku: string): Promise<Resultado<OfferView>> {
      exigirCtx(ctx);
      void sku;
      return naoImplementado();
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
