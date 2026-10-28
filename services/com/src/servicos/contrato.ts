/**
 * Vocabulário do módulo `servicos` (KAM-047).
 *
 * Aqui só tipos, domínios fechados e constantes. Nenhuma consulta e nenhuma
 * decisão — é o ficheiro que se lê para saber o que as palavras significam, e é
 * o que as cinco implementações ao lado importam em vez de reescreverem.
 *
 * A interface é **ctx-first**: o `tenantId` nunca vem do texto do utilizador,
 * vem do `ctx` que o CHR resolveu, e toda a operação corre dentro de uma
 * transacção com `app.tenant_id` definido (`comTenant` de
 * `@kamba/core-ts/tenant_guard`). Uma operação sem `ctx.tenantId` **falha
 * fechada** antes de tocar na base — critério 8.
 *
 * ## Os códigos de recusa são deste módulo, e não de `tool_audit`
 *
 * O dicionário §3.28 tem um domínio **fechado** de onze valores para
 * `tool_audit.error_code`, e `SLOT_TAKEN` e `HOLD_EXPIRED` não estão lá. Não se
 * acrescentam aqui, e a razão é de escopo e não de preguiça: alargar aquele
 * domínio obriga a um `ALTER` ao `CHECK` das revisões `0021` e `0022`, que são
 * de outro ticket, e quem precisa dos dois códigos no registo da ToolLayer é
 * quem ligar o `book_slot` ao grafo — **KAM-035**, que este ticket tem ordem
 * para não expandir.
 *
 * Por isso `ERROS` é o domínio fechado **deste módulo**, declarado no
 * dicionário como `ServicosModule.erro`, à maneira qualificada que o §3.28 já
 * usa (`tool_audit.error_code=NOT_FOUND`). O `LIMIT_EXCEEDED` e o
 * `ENTITLEMENT_DENIED` **importam-se** da semântica que o `hook_de_tool` do
 * KAM-009 já devolve — não se redeclaram com outro significado.
 *
 * Fica escrito o que KAM-035 terá de fazer: pôr `SLOT_TAKEN` e `HOLD_EXPIRED`
 * em `tool_audit.error_code` quando registar as invocações de `book_slot` e de
 * `get_availability`, com a emenda ao dicionário que isso exige.
 *
 * ## O TTL do hold é *proposta*
 *
 * Dez minutos, do critério 3, e **a calibrar**: ninguém mediu quanto tempo um
 * cliente de WhatsApp leva entre ver as horas e tocar no botão. Está aqui, numa
 * constante com a unidade no nome, e não no DDL — um número no `CHECK` de uma
 * coluna obrigava a uma revisão de base de dados para o calibrar.
 */

/** O mínimo de um cliente SQL de que este módulo precisa. */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ readonly rows: readonly Readonly<Record<string, unknown>>[] }>;
}

/**
 * Transacção com `app.tenant_id` definido.
 *
 * **Não recebe o cliente**, para ser atribuível ao `comTenant` de
 * `@kamba/core-ts/tenant_guard` depois de ligado a uma ligação: quem monta o
 * módulo decide de onde vem a ligação, e o módulo nunca a escolhe.
 */
export type ComTenant = <T>(
  tenantId: string,
  trabalho: (cliente: ClienteSql) => Promise<T>,
) => Promise<T>;

/** O contexto que o CHR resolveu. O `tenantId` nunca vem do texto. */
export interface Ctx {
  readonly tenantId: string;
  readonly contactId: string;
  /** Correlação para o envelope do evento. Opcional. */
  readonly traceId?: string | null;
}

/** Os quatro estados de uma marcação (revisão `0025`, dicionário §3.3). */
export const ESTADOS = ["hold", "confirmada", "cancelada", "expirada"] as const;
export type Estado = (typeof ESTADOS)[number];

/** Os dois estados que ocupam o intervalo: o predicado da restrição de exclusão. */
export const ESTADOS_ACTIVOS = ["hold", "confirmada"] as const;

/** O modo de preço de um serviço (dicionário §3.3; **`preco_tipo`**). */
export const PRECO_TIPOS = ["fixo", "a_partir_de", "sob_consulta"] as const;
export type PrecoTipo = (typeof PRECO_TIPOS)[number];

/**
 * Os códigos de recusa deste módulo. Lista **fechada** — ver a nota do módulo.
 *
 *     SLOT_TAKEN          o intervalo foi ocupado entre a oferta e o pedido
 *     HOLD_EXPIRED        o hold venceu antes de alguém o confirmar
 *     LIMIT_EXCEEDED      `marcacoes_mes` esgotado (KAM-009)
 *     ENTITLEMENT_DENIED  a vertical `servicos` não está activa para o tenant
 *     NOT_FOUND           o serviço, o recurso ou a marcação não existem
 *     VALIDATION_ERROR    o `slot_id` não foi emitido por este backend
 */
export const ERROS = [
  "SLOT_TAKEN",
  "HOLD_EXPIRED",
  "LIMIT_EXCEEDED",
  "ENTITLEMENT_DENIED",
  "NOT_FOUND",
  "VALIDATION_ERROR",
] as const;
export type Erro = (typeof ERROS)[number];

/**
 * O resultado de uma operação, como união discriminada.
 *
 * **Não se lança para recusar.** Uma recusa de domínio é uma resposta e não uma
 * excepção: o grafo tem de a poder mostrar ao cliente, e um `throw` obrigava
 * cada chamador a distinguir «o intervalo foi ocupado» de «a ligação caiu» pelo
 * nome da classe. As excepções ficam para erros de programação e de infra.
 */
export type Resultado<T> =
  | { readonly tipo: "ok"; readonly valor: T }
  | { readonly tipo: "erro"; readonly erro: Erro };

export function ok<T>(valor: T): Resultado<T> {
  return { tipo: "ok", valor };
}

export function erro<T>(codigo: Erro): Resultado<T> {
  return { tipo: "erro", erro: codigo };
}

/** Um serviço marcável. */
export interface Servico {
  readonly serviceId: string;
  readonly nome: string;
  readonly duracaoMin: number;
  readonly precoTipo: PrecoTipo;
  /** `null` exactamente quando `precoTipo === "sob_consulta"`. */
  readonly precoMinor: number | null;
  readonly currency: string;
}

/**
 * Uma opção de disponibilidade.
 *
 * O `inicioAt` e o `fimAt` são **instantes UTC** em ISO-8601. A apresentação em
 * `Africa/Luanda` é da camada de renderização (critério 2): este módulo nunca
 * formata uma hora para um humano, e por isso nunca escolhe um fuso.
 */
export interface Opcao {
  readonly slotId: string;
  readonly serviceId: string;
  readonly resourceId: string;
  readonly inicioAt: string;
  readonly fimAt: string;
}

/** Um hold ou uma marcação. */
export interface Marcacao {
  readonly bookingId: string;
  readonly holdId: string;
  readonly contactId: string;
  readonly serviceId: string;
  readonly resourceId: string;
  readonly slotId: string;
  readonly inicioAt: string;
  readonly fimAt: string;
  readonly estado: Estado;
  /** `null` exactamente quando `estado !== "hold"` (revisão `0025`). */
  readonly holdExpiresAt: string | null;
  readonly version: number;
}

/** O que `confirmBooking` devolve, para quem precisa de saber se foi o primeiro. */
export interface Confirmacao {
  readonly marcacao: Marcacao;
  /**
   * `false` quando esta chamada encontrou a marcação **já** confirmada.
   *
   * O criterio 4 pede «50 confirmações concorrentes produzem 1 marcação
   * confirmada»: as 50 devolvem `tipo: "ok"` com a **mesma** marcação, e só uma
   * traz `confirmou: true`. Sem este campo, o chamador não sabia se tinha de
   * emitir o evento — e cinquenta emissões era cinquenta mensagens.
   */
  readonly confirmou: boolean;
  /** `null` quando esta chamada não emitiu (porque outra já tinha emitido). */
  readonly eventoId: string | null;
}

/**
 * O máximo de opções que `getAvailability` devolve.
 *
 * **CONFIRMADO, e não *proposta*:** é o limite de linhas de uma lista
 * interactiva da Meta (`docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §7), e
 * mudá-lo não é uma calibração nossa — é mudar o que a Meta aceita.
 */
export const MAXIMO_DE_OPCOES = 10;

/**
 * Quanto tempo um hold segura o intervalo. **Dez minutos, *proposta*.**
 *
 * Calibra-se com dados do Piloto: o que falta medir é o tempo entre a lista
 * interactiva chegar ao cliente e o toque no botão. Curto demais, o cliente
 * perde o slot a escrever; longo demais, um recurso fica ocupado por quem
 * desistiu. A unidade está no nome e não num comentário.
 */
export const TTL_DO_HOLD_MS = 10 * 60 * 1000;

/**
 * Quantos holds vencidos um varrimento liberta de cada vez. *Proposta*.
 *
 * Tecto e não alvo: o varrimento é oportunista e repete-se. O que ele evita é
 * uma chamada a segurar a transacção de quem está a marcar — ver
 * `servicos.expirar_holds` na revisão `0025`.
 */
export const HOLDS_POR_VARRIMENTO = 100;

/**
 * Quantas voltas de varrimento um pedido paga, no máximo. *Proposta*.
 *
 * O varrimento repete-se até libertar menos do que o tecto — é assim que
 * «o intervalo está livre para o próximo que pergunte» vale acima de
 * `HOLDS_POR_VARRIMENTO`, e não só abaixo. Mas repetir sem limite punha um
 * pedido de disponibilidade a pagar uma fila de holds que outro produziu, pelo
 * que há um tecto de voltas: cinco, que são 500 holds por pedido. Acima disso
 * sobra para o pedido seguinte.
 */
export const VARRIMENTOS_POR_PEDIDO = 5;

/**
 * O horizonte de dias que `getAvailability` percorre quando ninguém dá
 * intervalo. *Proposta*.
 *
 * Catorze dias: duas semanas da grelha semanal, que é o que faz com que um
 * recurso com disponibilidade só às terças tenha sempre pelo menos duas
 * ocorrências para oferecer.
 */
export const HORIZONTE_DE_DIAS = 14;

/** O módulo de entitlement desta vertical (dicionário §3.7). */
export const MODULO = "servicos";

/** A chave de limite do critério 7 (dicionário §3.2; balde por período). */
export const CHAVE_DE_LIMITE = "marcacoes_mes";

/** O tipo e a versão do evento que este módulo emite (dicionário §3.5). */
export const TIPO_BOOKING_CREATED = "booking.created";
export const VERSAO_BOOKING_CREATED = 1;
export const AGREGADO_BOOKING = "booking";

/**
 * A classe de PII de `booking.created`. **`P1`, e é *proposta*.**
 *
 * O `docs/tecnica/06` §5 dá a classe de cada tipo de evento e **não lista
 * nenhum dos três de marcação** — a lacuna fica em
 * `docs/dividas-documentais.md`. A leitura que esta constante escreve: o payload
 * leva `contact_id`, que liga o evento a uma pessoa identificável na
 * plataforma, e é a mesma propriedade que põe o `order.created` em `P1` naquela
 * tabela. Não há telefone, nome nem morada — isso seria `P2`, e o `evt_emitir`
 * recusa-o por padrão.
 */
export const CLASSE_PII_BOOKING_CREATED = "P1";

/** O tipo e a versão do evento de cancelamento (dicionário §3.5). */
export const TIPO_BOOKING_CANCELLED = "booking.cancelled";
export const VERSAO_BOOKING_CANCELLED = 1;

/**
 * A classe de PII de `booking.cancelled`. **`P0`, e é *proposta*.**
 *
 * Pela mesma leitura que põe o `booking.created` em `P1` e o `payment.*` em
 * `P0` no `docs/tecnica/06` §5: o payload leva só o identificador da marcação e
 * o motivo, e não liga o evento a pessoa nenhuma sem a tabela.
 */
export const CLASSE_PII_BOOKING_CANCELLED = "P0";

/** A finalidade do envelope. `transacao`: a marcação é o acto comercial. */
export const FINALIDADES_BOOKING_CREATED = ["transacao"] as const;

/** Pediu-se uma operação sem contexto de tenant. Falha fechada (critério 8). */
export class CtxEmFaltaError extends Error {
  override readonly name = "CtxEmFaltaError";
  constructor(campo: string) {
    super(
      `o modulo servicos exige ctx.${campo}: sem ele a base devolveria zero ` +
        "linhas e a operacao parecia ter corrido sobre uma agenda vazia " +
        "(KAM-047, criterio 8)",
    );
  }
}

const UUID_CANONICO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * O `ctx` como par de UUID canónicos, ou lança.
 *
 * Aceita só a forma textual canónica, em qualquer caixa. **Lança e não devolve
 * `VALIDATION_ERROR`**: um `ctx` sem tenant não é uma recusa de domínio que o
 * grafo deva mostrar ao cliente — é um erro de quem montou a chamada, e
 * silenciá-lo num código de retorno era deixar uma operação correr sem
 * isolamento e parecer um «não encontrei».
 */
export function exigirCtx(ctx: Ctx): { tenantId: string; contactId: string } {
  const tenantId = String(ctx?.tenantId ?? "").toLowerCase();
  const contactId = String(ctx?.contactId ?? "").toLowerCase();
  if (!UUID_CANONICO.test(tenantId)) throw new CtxEmFaltaError("tenantId");
  if (!UUID_CANONICO.test(contactId)) throw new CtxEmFaltaError("contactId");
  return { tenantId, contactId };
}

/** Verdadeiro para a forma canónica de um UUID. */
export function eUuid(valor: unknown): valor is string {
  return typeof valor === "string" && UUID_CANONICO.test(valor.toLowerCase());
}

/**
 * A porta de emissão de `booking.created`.
 *
 * **Recebe o cliente**, para correr na transacção de quem chama: o evento e a
 * marcação entram ou não entram juntos (outbox transaccional, ADR-009). `null`
 * no sítio desta porta significa «não emite», e é o que as baterias do gate 4
 * usam para exercitar a lógica sem uma base.
 */
export type EmitirBookingCreated = (
  cliente: ClienteSql,
  tenantId: string,
  marcacao: Marcacao,
) => Promise<string>;

/**
 * A porta de emissão de `booking.cancelled`.
 *
 * Como a de `booking.created`: recebe o cliente, para correr na transacção de
 * quem chama. `null` significa «não emite», e é o que as baterias do gate 4
 * usam para exercitar a lógica sem uma base.
 */
export type EmitirBookingCancelled = (
  cliente: ClienteSql,
  tenantId: string,
  bookingId: string,
  motivo: "hold_expirado" | "cancelado_pelo_cliente",
) => Promise<string>;

/** O que o módulo precisa que lhe dêem para funcionar. */
export interface Dependencias {
  readonly comTenant: ComTenant;
  readonly emitirBookingCreated: EmitirBookingCreated | null;
  readonly emitirBookingCancelled: EmitirBookingCancelled | null;
  /** O relógio, injectável para que os testes de TTL não durmam. */
  readonly agora?: () => Date;
}

/** A interface que a TLS consome (bloco KAM-047, Detalhes Técnicos). */
export interface ServicosModule {
  listServices(ctx: Ctx): Promise<Resultado<readonly Servico[]>>;
  getAvailability(
    ctx: Ctx,
    serviceId: string,
    intervalo?: { readonly deAt?: string; readonly ateAt?: string },
  ): Promise<Resultado<readonly Opcao[]>>;
  holdSlot(ctx: Ctx, slotId: string): Promise<Resultado<Marcacao>>;
  confirmBooking(ctx: Ctx, holdId: string): Promise<Resultado<Confirmacao>>;
  cancelBooking(ctx: Ctx, bookingId: string): Promise<Resultado<Marcacao>>;
  rescheduleBooking(
    ctx: Ctx,
    bookingId: string,
    slotId: string,
  ): Promise<Resultado<Marcacao>>;
  getBooking(ctx: Ctx, bookingId: string): Promise<Resultado<Marcacao>>;
  /** O varrimento do critério 3. Devolve quantos holds libertou. */
  expireHolds(ctx: Pick<Ctx, "tenantId">): Promise<number>;
}
