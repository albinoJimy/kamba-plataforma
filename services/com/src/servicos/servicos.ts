/**
 * O módulo `servicos`: as sete operações ctx-first (KAM-047).
 *
 * Tudo o que decide está aqui; o vocabulário está em `contrato.ts`, o SQL em
 * `consultas.ts`, o corte em slots em `disponibilidade.ts`, o token opaco em
 * `slots.ts` e a emissão em `eventos.ts`.
 *
 * ## Três regras que valem para as sete operações
 *
 * **O `tenantId` vem do `ctx`, e toda a operação corre dentro de `comTenant`.**
 * Sem contexto não há consulta: `exigirCtx` lança antes de a ligação ser pedida,
 * e a RLS `FORCE` da revisão `0025` é a segunda barreira — sem
 * `app.tenant_id`, a base devolve zero linhas (critério 8).
 *
 * **Nenhuma recusa de domínio é uma excepção.** O grafo tem de poder dizer «esse
 * horário acabou de ficar ocupado» ao cliente, e um `throw` obrigava cada
 * chamador a distinguir isso de uma ligação caída pelo nome de uma classe. As
 * recusas saem em `Resultado.erro`; as excepções ficam para o que é defeito.
 *
 * **Nenhuma barreira é de código.** A sobreposição é da restrição de exclusão, a
 * idempotência da confirmação é do `WHERE` de um `UPDATE`, a idempotência do
 * slot é de um índice único parcial, e o limite é da `platform.ten_consumir`. O
 * que este ficheiro faz é traduzir `SQLSTATE` em códigos de recusa — não é ele
 * que garante nada, e é essa a diferença que o critério 1 escreve por extenso.
 *
 * ## O varrimento é oportunista, e isso é o que o torna mensurável
 *
 * `getAvailability`, `holdSlot` e `rescheduleBooking` chamam `expireHolds` antes
 * de decidir. Não é uma optimização: é o que faz com que um intervalo cujo hold
 * venceu esteja livre para **o próximo que pergunte**, sem esperar por um
 * agendador que este repositório ainda não tem (KAM-071). O varrimento tem
 * tecto de linhas e repete-se até esgotar, com tecto de voltas; nunca segura a
 * transacção de quem está a marcar.
 *
 * **O preço disto é que o `getAvailability` escreve**, e diz-se em vez de se
 * esconder: o varrimento altera linhas e emite no *outbox* dentro do que o
 * chamador lê como uma leitura. Três consequências — a consulta de
 * disponibilidade falha se o outbox recusar a escrita, não corre numa réplica,
 * e não corre numa transacção só de leitura. É escolha deliberada, e a
 * alternativa era pior: sem ela, num tenant sem tráfego nocturno um intervalo
 * cujo hold venceu às 23h10 ficava ocupado até ao primeiro pedido da manhã.
 */

import {
  CHAVE_DE_LIMITE,
  CtxEmFaltaError,
  HOLDS_POR_VARRIMENTO,
  MODULO,
  TTL_DO_HOLD_MS,
  erro,
  exigirCtx,
  ok,
  type ClienteSql,
  type ComTenant,
  type Confirmacao,
  type Ctx,
  type Dependencias,
  type Estado,
  type Marcacao,
  type Opcao,
  type PrecoTipo,
  type Resultado,
  type Servico,
  type ServicosModule,
} from "./contrato.ts";
import {
  SQLSTATE_SOBREPOSICAO,
  SQLSTATE_UNICIDADE,
  SQL_CANCELAR,
  SQL_CONFIRMAR_HOLD,
  SQL_CRIAR_HOLD,
  SQL_EXPIRAR_HOLDS,
  SQL_GRELHA,
  SQL_LISTAR_SERVICOS,
  SQL_MARCACAO,
  SQL_MARCACAO_DO_SLOT,
  SQL_MARCACAO_POR_HOLD,
  SQL_OCUPADO,
  SQL_REMARCAR,
  SQL_SERVICO,
  SQL_SLOT_OFERECIVEL,
  SQL_TRANCAR_RECURSO,
} from "./consultas.ts";
import { emitirBookingCancelled, emitirBookingCreated } from "./eventos.ts";
import {
  opcoesComSlotId,
  slotsLivres,
  type Janela,
  type Ocupacao,
} from "./disponibilidade.ts";
import { HORIZONTE_DE_DIAS, VARRIMENTOS_POR_PEDIDO, eUuid } from "./contrato.ts";
import { checkEntitlement, consumeLimit } from "@kamba/core-ts/ten";
import { lerSlotId, type Slot } from "./slots.ts";

/**
 * O `SQLSTATE` de um erro de driver, ou `null`.
 *
 * Lê as duas formas que este repositório vê: o `code` do `pg` e o `S`/`C` do
 * `pg8000`, porque as baterias de base de dados usam o segundo. **Nunca lê a
 * mensagem**: a mensagem de um conflito de exclusão cita a chave em conflito —
 * o recurso e o intervalo —, e procurar texto nela era fazer do registo de erro
 * um caminho por onde esses valores passam a sair.
 */
function sqlstateDe(erroDoDriver: unknown): string | null {
  if (typeof erroDoDriver !== "object" || erroDoDriver === null) return null;
  const forma = erroDoDriver as Record<string, unknown>;
  if (typeof forma["code"] === "string") return forma["code"];
  const args = forma["args"];
  if (Array.isArray(args) && typeof args[0] === "object" && args[0] !== null) {
    const mapa = args[0] as Record<string, unknown>;
    if (typeof mapa["C"] === "string") return mapa["C"];
  }
  return null;
}

/** Uma linha de `bookings` como `Marcacao`. Nomes do dicionário → nomes do TS. */
function marcacaoDe(linha: Readonly<Record<string, unknown>>): Marcacao {
  return {
    bookingId: String(linha["booking_id"]),
    holdId: String(linha["hold_id"]),
    contactId: String(linha["contact_id"]),
    serviceId: String(linha["service_id"]),
    resourceId: String(linha["resource_id"]),
    slotId: String(linha["slot_id"]),
    inicioAt: instante(linha["inicio_at"]),
    fimAt: instante(linha["fim_at"]),
    estado: String(linha["estado"]) as Estado,
    holdExpiresAt:
      linha["hold_expires_at"] === null || linha["hold_expires_at"] === undefined
        ? null
        : instante(linha["hold_expires_at"]),
    version: Number(linha["version"]),
  };
}

/**
 * Um `timestamptz` como ISO-8601 em UTC.
 *
 * O `pg` devolve `Date` e o `pg8000` devolve `datetime`, que chega como texto.
 * Normaliza-se para **uma** forma, e em UTC: o critério 2 pede «instante UTC», e
 * a apresentação em `Africa/Luanda` é de quem renderiza.
 */
function instante(valor: unknown): string {
  if (valor instanceof Date) return valor.toISOString();
  const texto = String(valor);
  const analisado = Date.parse(texto);
  if (Number.isNaN(analisado)) {
    throw new TypeError(`instante ilegivel vindo da base: ${typeof valor}`);
  }
  return new Date(analisado).toISOString();
}

function servicoDe(linha: Readonly<Record<string, unknown>>): Servico {
  const precoMinor = linha["preco_minor"];
  return {
    serviceId: String(linha["service_id"]),
    nome: String(linha["nome"]),
    duracaoMin: Number(linha["duracao_min"]),
    precoTipo: String(linha["preco_tipo"]) as PrecoTipo,
    precoMinor:
      precoMinor === null || precoMinor === undefined ? null : Number(precoMinor),
    currency: String(linha["currency"]),
  };
}

/** As dependências que o módulo precisa, mais o que a TLS traz por chamada. */
export interface Opcoes extends Dependencias {
  /** O segredo dos `slot_id`, do cofre (KAM-010). */
  readonly segredoDosSlots: Buffer;
  /**
   * `checkEntitlement` e `consumeLimit` de `@kamba/core-ts/ten`, injectados.
   *
   * Injectados e não importados directamente por uma razão de prova: o critério
   * 7 pede que um limite esgotado devolva `LIMIT_EXCEEDED`, e as baterias do
   * gate 4 têm de poder forçar esse caso sem semear um mês de consumo. Em
   * produção passam-se os verdadeiros, e o gate 8 prova-os contra a base.
   */
  readonly entitlement: (
    cliente: ClienteSql,
    tenantId: string,
    modulo: string,
  ) => Promise<{ readonly permitido: boolean }>;
  readonly consumir: (
    cliente: ClienteSql,
    tenantId: string,
    chave: string,
    quantidade: number,
    idempotencyKey: string,
  ) => Promise<{ readonly aceite: boolean }>;
}

/**
 * O módulo montado com as portas verdadeiras.
 *
 * Existe para que haja **um** sítio onde o `criarServicosModule` é chamado com
 * o que ele espera em produção — e não só nas baterias. Sem isto, as sete
 * operações eram 500 linhas sem chamador nenhum, que foi o que a revisão
 * adversarial encontrou: nada garantia que as portas injectadas tivessem a
 * forma que o módulo pede, porque ninguém as injectava a sério.
 *
 * O `checkEntitlement` e o `consumeLimit` vêm de `@kamba/core-ts/ten` e chamam
 * a mesma regra SQL que o espelho em Python chama (KAM-009); a emissão vai pelo
 * `platform.evt_emitir` (KAM-005). O que quem monta ainda tem de dar é a
 * transacção com contexto (`comTenant` de `@kamba/core-ts/tenant_guard`, ligado
 * a uma **ligação** e nunca a um *pool*) e o segredo dos *slots*, do cofre.
 */
export function servicosComPortasReais(
  comTenant: ComTenant,
  segredoDosSlots: Buffer,
  agora?: () => Date,
): ServicosModule {
  return criarServicosModule({
    comTenant,
    segredoDosSlots,
    ...(agora === undefined ? {} : { agora }),
    emitirBookingCreated,
    emitirBookingCancelled,
    entitlement: (cliente, tenantId, modulo) =>
      checkEntitlement(cliente as never, tenantId, modulo),
    consumir: (cliente, tenantId, chave, quantidade, idempotencyKey) =>
      consumeLimit(cliente as never, tenantId, chave, quantidade, idempotencyKey),
  });
}

export function criarServicosModule(opcoes: Opcoes): ServicosModule {
  const agora = opcoes.agora ?? (() => new Date());

  /**
   * Liberta os holds vencidos deste tenant, **até esgotar**.
   *
   * Em ciclo e não uma vez, e isso mudou com a revisão adversarial: a função da
   * base tem tecto de linhas (para nunca segurar a transacção de quem marca), e
   * uma chamada só deixava os restantes em `hold` — o `SQL_OCUPADO` conta-os, e
   * a hora que o cliente queria aparecia ocupada. A promessa escrita era «um
   * intervalo cujo hold venceu está livre para o próximo que pergunte», e com
   * uma chamada isso só valia abaixo do tecto.
   *
   * O ciclo tem fim por duas vias: pára quando um varrimento liberta menos do
   * que o tecto (não há mais), e tem um número máximo de voltas, para que um
   * produtor de holds mais rápido do que o varrimento não prenda aqui o pedido
   * de quem está a marcar.
   */
  async function varrer(cliente: ClienteSql): Promise<number> {
    let total = 0;
    for (let volta = 0; volta < VARRIMENTOS_POR_PEDIDO; volta += 1) {
      const { rows } = await cliente.query(SQL_EXPIRAR_HOLDS, [
        HOLDS_POR_VARRIMENTO,
      ]);
      const libertados = Number(rows[0]?.["libertados"] ?? 0);
      total += libertados;
      if (libertados < HOLDS_POR_VARRIMENTO) break;
    }
    return total;
  }

  /** O *slot* ainda é oferecível? Ver `SQL_SLOT_OFERECIVEL`. */
  async function oferecivel(cliente: ClienteSql, slot: Slot): Promise<boolean> {
    const { rows } = await cliente.query(SQL_SLOT_OFERECIVEL, [
      slot.serviceId,
      slot.resourceId,
      slot.inicioAt,
      slot.fimAt,
    ]);
    return rows[0]?.["oferecivel"] === true;
  }

  /**
   * Toma a tranca de um ou dois recursos, **por ordem do identificador**.
   *
   * A ordem é o que impede o ciclo: numa remarcação que mude de recurso há dois
   * a trancar, e duas remarcações cruzadas (A→B e B→A em paralelo) tomavam-nos
   * em ordens opostas e fechavam uma espera circular — um `40P01` em duas
   * remarcações perfeitamente legítimas, que é exactamente o que esta tranca
   * existe para evitar. Com uma ordem total sobre os identificadores, duas
   * transacções pedem sempre o mesmo primeiro.
   */
  async function trancar(
    cliente: ClienteSql,
    tenantId: string,
    recursos: readonly string[],
  ): Promise<void> {
    for (const recurso of [...new Set(recursos)].sort()) {
      await cliente.query(SQL_TRANCAR_RECURSO, [tenantId, recurso]);
    }
  }

  return {
    async listServices(ctx: Ctx): Promise<Resultado<readonly Servico[]>> {
      const { tenantId } = exigirCtx(ctx);
      return opcoes.comTenant(tenantId, async (cliente) => {
        const { rows } = await cliente.query(SQL_LISTAR_SERVICOS, []);
        return ok(rows.map(servicoDe));
      });
    },

    async getAvailability(
      ctx: Ctx,
      serviceId: string,
      intervalo?: { readonly deAt?: string; readonly ateAt?: string },
    ): Promise<Resultado<readonly Opcao[]>> {
      const { tenantId } = exigirCtx(ctx);
      const instanteInicial = agora();
      const de =
        intervalo?.deAt === undefined
          ? instanteInicial
          : new Date(Date.parse(intervalo.deAt));
      const ate =
        intervalo?.ateAt === undefined
          ? new Date(de.getTime() + HORIZONTE_DE_DIAS * 24 * 60 * 60 * 1000)
          : new Date(Date.parse(intervalo.ateAt));
      if (Number.isNaN(de.getTime()) || Number.isNaN(ate.getTime()) || ate <= de) {
        return erro("VALIDATION_ERROR");
      }

      return opcoes.comTenant(tenantId, async (cliente) => {
        // Antes de calcular: um hold vencido não pode esconder uma hora livre.
        await varrer(cliente);

        const servico = await cliente.query(SQL_SERVICO, [serviceId]);
        const linha = servico.rows[0];
        if (linha === undefined || linha["ativo"] !== true) {
          return erro("NOT_FOUND");
        }
        const duracaoMin = Number(linha["duracao_min"]);

        const grelha = await cliente.query(SQL_GRELHA, [
          de.toISOString(),
          ate.toISOString(),
        ]);
        const janelas: Janela[] = grelha.rows.map((l) => ({
          resourceId: String(l["resource_id"]),
          abreAt: new Date(Date.parse(instante(l["abre_at"]))),
          fechaAt: new Date(Date.parse(instante(l["fecha_at"]))),
        }));

        const ocupadas = await cliente.query(SQL_OCUPADO, [
          de.toISOString(),
          ate.toISOString(),
        ]);
        const ocupado: Ocupacao[] = ocupadas.rows.map((l) => ({
          resourceId: String(l["resource_id"]),
          inicioAt: new Date(Date.parse(instante(l["inicio_at"]))),
          fimAt: new Date(Date.parse(instante(l["fim_at"]))),
        }));

        // O limite inferior é o máximo entre «agora» e o início pedido: um
        // intervalo que comece no passado não devolve horas passadas. O
        // superior é o `ateAt`, e **faltava**: sem ele o `ateAt` só servia para
        // gerar dias, e quem pedisse «esta manhã» recebia a tarde — a grelha do
        // dia inteiro entrava e só o passado era filtrado.
        const limite = de > instanteInicial ? de : instanteInicial;
        const slots = slotsLivres(janelas, ocupado, duracaoMin, limite, ate);
        return ok(
          opcoesComSlotId(opcoes.segredoDosSlots, tenantId, serviceId, slots),
        );
      });
    },

    async holdSlot(ctx: Ctx, slotId: string): Promise<Resultado<Marcacao>> {
      const { tenantId, contactId } = exigirCtx(ctx);
      const slot = lerSlotId(opcoes.segredoDosSlots, tenantId, slotId);
      if (slot === null) return erro("VALIDATION_ERROR");

      return opcoes.comTenant(tenantId, async (cliente) => {
        await varrer(cliente);

        // **O entitlement antes do limite, e os dois antes da escrita.** A
        // ordem é a do `hook_de_tool` do KAM-009: uma vertical inactiva
        // devolve `ENTITLEMENT_DENIED` e **não consome** uma marcação do balde
        // — consumir primeiro cobrava ao tenant uma marcação que ele não pôde
        // fazer.
        const ent = await opcoes.entitlement(cliente, tenantId, MODULO);
        if (!ent.permitido) return erro("ENTITLEMENT_DENIED");

        // Já tem marcação activa para este slot? Devolve-a, sem consumir outra
        // vez: é a idempotência de `(contact_id, slot_id)` do critério 4 a
        // valer também no hold, e sem esta leitura o segundo toque no mesmo
        // botão gastava uma marcação do balde para bater no índice único.
        const existente = await cliente.query(SQL_MARCACAO_DO_SLOT, [
          contactId,
          slotId,
        ]);
        const jaTem = existente.rows[0];
        if (jaTem !== undefined) return ok(marcacaoDe(jaTem));

        // A chave de idempotência do consumo é o par `(contacto, slot)`: o
        // mesmo cliente a tocar duas vezes no mesmo botão consome **uma**
        // marcação, e a `platform.ten_consumir` garante-o na base.
        const consumo = await opcoes.consumir(
          cliente,
          tenantId,
          CHAVE_DE_LIMITE,
          1,
          `servicos:hold:${contactId}:${slotId}`,
        );
        if (!consumo.aceite) return erro("LIMIT_EXCEEDED");

        // **O slot ainda é oferecível?** A assinatura prova que o backend o
        // ofereceu, não que ainda o ofereceria: entre a lista e o botão a PME
        // pode ter apagado a regra, desactivado o recurso ou mudado a duração.
        // Ver a nota do `SQL_SLOT_OFERECIVEL`.
        if (!(await oferecivel(cliente, slot))) return erro("NOT_FOUND");

        // Em fila por recurso, **depois** do limite e antes da escrita: ver a
        // nota do `SQL_TRANCAR_RECURSO`. Não decide nada; evita o *deadlock*
        // que 486 execuções mediram.
        await trancar(cliente, tenantId, [slot.resourceId]);

        const expira = new Date(agora().getTime() + TTL_DO_HOLD_MS);
        try {
          const { rows } = await cliente.query(SQL_CRIAR_HOLD, [
            tenantId,
            contactId,
            slot.serviceId,
            slot.resourceId,
            slotId,
            slot.inicioAt,
            slot.fimAt,
            expira.toISOString(),
          ]);
          const criada = rows[0];
          if (criada === undefined) {
            throw new Error(
              "SQL_CRIAR_HOLD nao devolveu linha: um INSERT ... RETURNING que " +
                "nao devolve nada e um defeito, nao um slot ocupado",
            );
          }
          return ok(marcacaoDe(criada));
        } catch (falha) {
          const estado = sqlstateDe(falha);
          // `23P01` é a restrição de exclusão: outra transacção ficou com o
          // intervalo. `23505` é o índice único do par `(contacto, slot)`: foi
          // o próprio contacto, em paralelo. As duas são `SLOT_TAKEN` para quem
          // pediu — e **as duas desfazem o consumo**, porque o `ROLLBACK` da
          // transacção de `comTenant` leva consigo a linha de `usage_ledger`.
          if (estado === SQLSTATE_SOBREPOSICAO || estado === SQLSTATE_UNICIDADE) {
            return erro("SLOT_TAKEN");
          }
          throw falha;
        }
      });
    },

    async confirmBooking(ctx: Ctx, holdId: string): Promise<Resultado<Confirmacao>> {
      const { tenantId, contactId } = exigirCtx(ctx);
      // Um identificador malformado e uma recusa de dominio e nao uma excepcao
      // de driver: sem isto, um `confirm:abc` vindo do grafo subia como
      // `22P02 invalid input syntax for type uuid` em vez de
      // `VALIDATION_ERROR`, que e o codigo que o modulo declara para isso.
      if (!eUuid(holdId)) return erro("VALIDATION_ERROR");
      return opcoes.comTenant<Resultado<Confirmacao>>(tenantId, async (cliente) => {
        // **O contacto está no `WHERE`**, e não numa conferência posterior:
        // ver a nota do `SQL_CONFIRMAR_HOLD`. A distinção entre `HOLD_EXPIRED`
        // e `NOT_FOUND` resolve-se na leitura de baixo, sem escrever primeiro.
        const { rows } = await cliente.query(SQL_CONFIRMAR_HOLD, [
          holdId,
          contactId,
        ]);
        const confirmada = rows[0];
        if (confirmada !== undefined) {
          const marcacao = marcacaoDe(confirmada);
          const eventoId =
            opcoes.emitirBookingCreated === null
              ? null
              : await opcoes.emitirBookingCreated(cliente, tenantId, marcacao);
          return ok({ marcacao, confirmou: true, eventoId });
        }

        // Não alterou nada: ou já estava confirmada (e então as outras 49
        // chamadas do critério 4 devolvem a mesma marcação), ou venceu, ou não
        // existe.
        const actual = await cliente.query(SQL_MARCACAO_POR_HOLD, [holdId]);
        const linha = actual.rows[0];
        if (linha === undefined) return erro("NOT_FOUND");
        const marcacao = marcacaoDe(linha);
        if (marcacao.contactId !== contactId) return erro("NOT_FOUND");
        if (marcacao.estado === "confirmada") {
          return ok({ marcacao, confirmou: false, eventoId: null });
        }
        if (marcacao.estado === "hold" || marcacao.estado === "expirada") {
          return erro("HOLD_EXPIRED");
        }
        return erro("NOT_FOUND");
      });
    },

    async cancelBooking(ctx: Ctx, bookingId: string): Promise<Resultado<Marcacao>> {
      const { tenantId, contactId } = exigirCtx(ctx);
      if (!eUuid(bookingId)) return erro("VALIDATION_ERROR");
      return opcoes.comTenant<Resultado<Marcacao>>(tenantId, async (cliente) => {
        const { rows } = await cliente.query(SQL_CANCELAR, [bookingId, contactId]);
        const linha = rows[0];
        if (linha === undefined) return erro("NOT_FOUND");
        const marcacao = marcacaoDe(linha);
        // **Emite**, e o critério 5 não o pede: sem um evento de cancelamento,
        // o agendador de lembretes (KAM-048) continua a achar que a marcação
        // existe e envia um *template utility* pago a lembrar o que o cliente
        // cancelou. Na mesma transacção, como tudo o que vai pelo outbox.
        if (opcoes.emitirBookingCancelled !== null) {
          await opcoes.emitirBookingCancelled(
            cliente,
            tenantId,
            marcacao.bookingId,
            "cancelado_pelo_cliente",
          );
        }
        return ok(marcacao);
      });
    },

    async rescheduleBooking(
      ctx: Ctx,
      bookingId: string,
      slotId: string,
    ): Promise<Resultado<Marcacao>> {
      const { tenantId, contactId } = exigirCtx(ctx);
      if (!eUuid(bookingId)) return erro("VALIDATION_ERROR");
      const slot = lerSlotId(opcoes.segredoDosSlots, tenantId, slotId);
      if (slot === null) return erro("VALIDATION_ERROR");

      // **Uma transacção para as duas metades** (critério 5). O `comTenant`
      // abre-a, e qualquer falha a seguir — incluindo a sobreposição do slot
      // novo — desfaz o cancelamento: «falha injectada deixa a marcação
      // original intacta» é o `ROLLBACK`, e não um passo de compensação.
      return opcoes.comTenant<Resultado<Marcacao>>(tenantId, async (cliente) => {
        await varrer(cliente);

        // **O entitlement confere-se, e o balde não se consome.** O critério 7
        // só obriga no `holdSlot`, e a letra estava cumprida — mas sem isto um
        // tenant com a vertical desactivada continuava a remarcar. Não consome
        // porque uma remarcação **move** uma marcação e não cria outra; cobrar
        // uma do balde por cada mudança de hora fazia do limite mensal um
        // limite de indecisão.
        const ent = await opcoes.entitlement(cliente, tenantId, MODULO);
        if (!ent.permitido) return erro("ENTITLEMENT_DENIED");

        // Lê-se a original **antes** de cancelar: é dela que sai o estado em
        // que a nova nasce (ver abaixo) e o recurso antigo a trancar.
        const antes = await cliente.query(SQL_MARCACAO, [bookingId]);
        const linhaAntiga = antes.rows[0];
        if (linhaAntiga === undefined) return erro("NOT_FOUND");
        const original = marcacaoDe(linhaAntiga);
        if (original.contactId !== contactId) return erro("NOT_FOUND");
        if (original.estado !== "hold" && original.estado !== "confirmada") {
          return erro("NOT_FOUND");
        }

        if (!(await oferecivel(cliente, slot))) return erro("NOT_FOUND");

        // **Os dois recursos, por ordem do identificador.** Antes trancava-se
        // só o novo, e o antigo era libertado sem tranca nenhuma: duas
        // remarcações cruzadas (A: R1→R2, B: R2→R1) tomavam-nos em ordens
        // opostas e fechavam uma espera circular — um `40P01` em duas
        // remarcações legítimas, que é precisamente o que esta tranca existe
        // para evitar. Ver a nota do `trancar`.
        await trancar(cliente, tenantId, [original.resourceId, slot.resourceId]);

        const cancelada = await cliente.query(SQL_CANCELAR, [bookingId, contactId]);
        if (cancelada.rows[0] === undefined) return erro("NOT_FOUND");

        // **A nova nasce no estado da original**, e isto foi um defeito: com o
        // `SQL_CRIAR_HOLD`, que escreve `'hold'` literal, remarcar uma marcação
        // **confirmada** degradava-a num hold de dez minutos — e quem não
        // voltasse a carregar no botão perdia-a em silêncio, expirada pelo
        // varrimento. Quem já confirmou não volta a confirmar por ter mudado de
        // hora.
        const continuaHold = original.estado === "hold";
        const expira = continuaHold
          ? new Date(agora().getTime() + TTL_DO_HOLD_MS).toISOString()
          : null;
        try {
          const { rows } = await cliente.query(SQL_REMARCAR, [
            tenantId,
            contactId,
            slot.serviceId,
            slot.resourceId,
            slotId,
            slot.inicioAt,
            slot.fimAt,
            original.estado,
            expira,
          ]);
          const nova = rows[0];
          if (nova === undefined) {
            throw new Error("SQL_REMARCAR nao devolveu linha na remarcacao");
          }
          const marcacao = marcacaoDe(nova);
          // Uma remarcação de uma marcação **confirmada** produz outra
          // confirmada: o KAM-048 tem de reagendar o lembrete para a hora nova,
          // e sem `booking.created` o que ele tem é o da hora antiga.
          if (!continuaHold && opcoes.emitirBookingCreated !== null) {
            await opcoes.emitirBookingCreated(cliente, tenantId, marcacao);
          }
          if (opcoes.emitirBookingCancelled !== null) {
            await opcoes.emitirBookingCancelled(
              cliente,
              tenantId,
              original.bookingId,
              "cancelado_pelo_cliente",
            );
          }
          return ok(marcacao);
        } catch (falha) {
          const estado = sqlstateDe(falha);
          if (estado === SQLSTATE_SOBREPOSICAO || estado === SQLSTATE_UNICIDADE) {
            // Lança em vez de devolver `SLOT_TAKEN`, e a razão é o critério: a
            // marcação original **tem** de ficar intacta, e devolver um
            // resultado aqui confirmava a transacção com ela já cancelada. Quem
            // chama volta a receber `SLOT_TAKEN`, convertido no `catch` de
            // baixo.
            throw new SlotOcupadoNaRemarcacaoError();
          }
          throw falha;
        }
      }).catch((falha: unknown) => {
        if (falha instanceof SlotOcupadoNaRemarcacaoError) {
          return erro<Marcacao>("SLOT_TAKEN");
        }
        throw falha;
      });
    },

    async getBooking(ctx: Ctx, bookingId: string): Promise<Resultado<Marcacao>> {
      const { tenantId, contactId } = exigirCtx(ctx);
      if (!eUuid(bookingId)) return erro("VALIDATION_ERROR");
      return opcoes.comTenant(tenantId, async (cliente) => {
        const { rows } = await cliente.query(SQL_MARCACAO, [bookingId]);
        const linha = rows[0];
        if (linha === undefined) return erro("NOT_FOUND");
        const marcacao = marcacaoDe(linha);
        // Um contacto não lê a marcação de outro **dentro do mesmo tenant** —
        // o X-02 do critério 6. A RLS isola tenants; isto isola contactos.
        if (marcacao.contactId !== contactId) return erro("NOT_FOUND");
        return ok(marcacao);
      });
    },

    async expireHolds(ctx: Pick<Ctx, "tenantId">): Promise<number> {
      const tenantId = String(ctx?.tenantId ?? "").toLowerCase();
      // `eUuid` e nao `!== ""`: com a forma por validar, um `tenantId` que nao
      // fosse um UUID chegava ao `set_config` e rebentava no `::uuid` da
      // politica — e o `tenant_guard` ja o recusa, mas esta porta tinha a
      // verificacao mais fraca das sete.
      if (!eUuid(tenantId)) throw new CtxEmFaltaError("tenantId");
      return opcoes.comTenant(tenantId, varrer);
    },
  };
}

/**
 * O slot novo de uma remarcação estava ocupado.
 *
 * Interna: nasce para desfazer a transacção e é convertida em `SLOT_TAKEN` pelo
 * `catch` de `rescheduleBooking`. Nunca sai do módulo.
 */
class SlotOcupadoNaRemarcacaoError extends Error {
  override readonly name = "SlotOcupadoNaRemarcacaoError";
  constructor() {
    super("o slot novo da remarcacao esta ocupado; a marcacao original fica");
  }
}

