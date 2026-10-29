/**
 * As sete operações do `ServicosModule`, contra um cliente SQL de ensaio.
 *
 * **O que isto prova e o que não prova.** Não prova nenhuma das barreiras: a
 * sobreposição é da restrição de exclusão, a idempotência da confirmação é do
 * `WHERE` de um `UPDATE`, o isolamento é da RLS — e as três só se provam contra
 * um PostgreSQL verdadeiro, em `db/tests_servicos/`. O que se prova aqui é a
 * **tradução**: que um `23P01` vira `SLOT_TAKEN` e não uma excepção, que a ordem
 * das verificações do `holdSlot` é a do KAM-009 (entitlement antes do limite,
 * os dois antes da escrita), que uma remarcação falhada não confirma, e que uma
 * operação sem `ctx` falha fechada **antes** de a ligação ser pedida.
 *
 * O cliente de ensaio regista as consultas por ordem, o que torna «a ordem das
 * verificações» uma asserção e não uma leitura do código.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { test } from "node:test";

import {
  CtxEmFaltaError,
  SQL_CANCELAR,
  SQL_CONFIRMAR_HOLD,
  SQL_CRIAR_HOLD,
  SQL_EXPIRAR_HOLDS,
  SQL_LISTAR_SERVICOS,
  SQL_MARCACAO,
  SQL_MARCACAO_DO_SLOT,
  SQL_MARCACAO_POR_HOLD,
  SQL_REMARCAR,
  SQL_SLOT_OFERECIVEL,
  SQL_TRANCAR_RECURSO,
  criarServicosModule,
  derivarSlotId,
  type ClienteSql,
  type Ctx,
  type Marcacao,
} from "../src/servicos/index.ts";

const SEGREDO = randomBytes(32);
const TENANT = "11111111-1111-4111-8111-111111111111";
const CONTACTO = "22222222-2222-4222-8222-222222222222";
const SERVICO = "33333333-3333-4333-8333-333333333333";
const RECURSO = "44444444-4444-4444-8444-444444444444";
const CTX: Ctx = { tenantId: TENANT, contactId: CONTACTO };

const SLOT = {
  serviceId: SERVICO,
  resourceId: RECURSO,
  inicioAt: "2026-11-02T09:00:00.000Z",
  fimAt: "2026-11-02T09:30:00.000Z",
};
const SLOT_ID = derivarSlotId(SEGREDO, TENANT, SLOT);

/** Uma linha de `bookings` como a base a devolve. */
function linha(sobrepor: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    booking_id: "55555555-5555-4555-8555-555555555555",
    hold_id: "66666666-6666-4666-8666-666666666666",
    contact_id: CONTACTO,
    service_id: SERVICO,
    resource_id: RECURSO,
    slot_id: SLOT_ID,
    inicio_at: SLOT.inicioAt,
    fim_at: SLOT.fimAt,
    estado: "hold",
    hold_expires_at: "2026-11-02T08:10:00.000Z",
    version: 1,
    ...sobrepor,
  };
}

/** Um erro de driver com o `SQLSTATE` dado, na forma do `pg`. */
function erroSql(code: string): Error {
  return Object.assign(new Error("erro de ensaio"), { code });
}

interface Ensaio {
  readonly sqls: string[];
  readonly modulo: ReturnType<typeof criarServicosModule>;
  readonly emitidos: Marcacao[];
  readonly cancelados: Array<{ bookingId: string; motivo: string }>;
}

/**
 * Monta o módulo com um cliente que responde pela ordem das consultas.
 *
 * `respostas` é uma lista de `[predicado, resposta]`: a primeira cujo predicado
 * case com o SQL responde. Uma resposta que seja `Error` é lançada — é assim
 * que se injecta um `23P01` sem uma base.
 */
function ensaio(
  respostas: Array<[(sql: string) => boolean, unknown]>,
  opcoes: { permitido?: boolean; aceite?: boolean } = {},
): Ensaio {
  const sqls: string[] = [];
  const emitidos: Marcacao[] = [];
  const cancelados: Array<{ bookingId: string; motivo: string }> = [];
  const cliente: ClienteSql = {
    async query(sql) {
      sqls.push(sql);
      for (const [casa, resposta] of respostas) {
        if (casa(sql)) {
          if (resposta instanceof Error) throw resposta;
          return { rows: resposta as never };
        }
      }
      return { rows: [] };
    },
  };
  const modulo = criarServicosModule({
    comTenant: async (_tenantId, trabalho) => trabalho(cliente),
    emitirBookingCreated: async (_c, _t, marcacao) => {
      emitidos.push(marcacao);
      return "evento-de-ensaio";
    },
    emitirBookingCancelled: async (_c, _t, bookingId, motivo) => {
      cancelados.push({ bookingId, motivo });
      return "evento-de-cancelamento";
    },
    agora: () => new Date("2026-11-02T08:00:00.000Z"),
    segredoDosSlots: SEGREDO,
    entitlement: async () => ({ permitido: opcoes.permitido ?? true }),
    consumir: async () => ({ aceite: opcoes.aceite ?? true }),
  });
  return { sqls, modulo, emitidos, cancelados };
}

const e = (alvo: string) => (sql: string) => sql === alvo;

/**
 * «O slot ainda é oferecível»: a resposta positiva do `SQL_SLOT_OFERECIVEL`.
 *
 * Entra em todos os ensaios que escrevem na agenda. É deliberado que a omissão
 * do cliente de ensaio (`rows: []`) signifique **não oferecível**: um ensaio
 * que se esqueça desta resposta falha, em vez de medir uma escrita que o módulo
 * em produção já não faria.
 */
const OFERECIVEL: [(sql: string) => boolean, unknown] = [
  e(SQL_SLOT_OFERECIVEL),
  [{ oferecivel: true }],
];

test("sem ctx.tenantId a operacao falha fechada antes de tocar na base", async () => {
  // Critério 8. Lança e **não** devolve `VALIDATION_ERROR`: um `ctx` sem tenant
  // é um erro de quem montou a chamada, e silenciá-lo num código de retorno
  // deixava uma operação correr sem isolamento a parecer um «não encontrei».
  const { modulo, sqls } = ensaio([]);
  for (const mau of [
    {},
    { tenantId: "", contactId: CONTACTO },
    { tenantId: "nao-e-uuid", contactId: CONTACTO },
    { tenantId: TENANT, contactId: "" },
  ]) {
    await assert.rejects(
      () => modulo.listServices(mau as Ctx),
      CtxEmFaltaError,
    );
  }
  assert.deepEqual(sqls, [], "nenhuma consulta pode ter sido enviada");
});

test("listServices devolve os servicos e so a consulta deles", async () => {
  const { modulo, sqls } = ensaio([
    [
      e(SQL_LISTAR_SERVICOS),
      [
        {
          service_id: SERVICO,
          nome: "Corte",
          duracao_min: 30,
          preco_tipo: "sob_consulta",
          preco_minor: null,
          currency: "AOA",
        },
      ],
    ],
  ]);
  const r = await modulo.listServices(CTX);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor[0]?.precoMinor, null);
  assert.equal(r.valor[0]?.duracaoMin, 30);
  assert.deepEqual(sqls, [SQL_LISTAR_SERVICOS]);
});

test("um slot_id que nao verifica nao chega a base", async () => {
  // O guardrail de `02` §8.2 imposto por criptografia: um slot fabricado é
  // recusado **antes** da ligação, e não por a base não o encontrar.
  const { modulo, sqls } = ensaio([]);
  const r = await modulo.holdSlot(CTX, "nao-e-um-slot");
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(sqls, []);
});

test("holdSlot: entitlement antes do limite, e os dois antes da escrita", async () => {
  // A ordem é a do `hook_de_tool` do KAM-009, e é uma asserção e não uma
  // leitura: com a vertical inactiva não se consome uma marcação do balde que o
  // tenant não pôde usar.
  const { modulo, sqls } = ensaio([], { permitido: false });
  const r = await modulo.holdSlot(CTX, SLOT_ID);
  assert.deepEqual(r, { tipo: "erro", erro: "ENTITLEMENT_DENIED" });
  assert.ok(
    !sqls.includes(SQL_CRIAR_HOLD),
    "nao se escreve com a vertical inactiva",
  );
  assert.ok(sqls.includes(SQL_EXPIRAR_HOLDS), "o varrimento corre antes");
});

test("holdSlot com o balde esgotado devolve LIMIT_EXCEEDED e nao escreve", async () => {
  const { modulo, sqls } = ensaio([], { aceite: false });
  const r = await modulo.holdSlot(CTX, SLOT_ID);
  assert.deepEqual(r, { tipo: "erro", erro: "LIMIT_EXCEEDED" });
  assert.ok(!sqls.includes(SQL_CRIAR_HOLD));
});

test("holdSlot recusa um slot que a agenda ja nao oferece", async () => {
  // A assinatura prova que o backend ofereceu o slot; não prova que ainda o
  // ofereceria. Entre a lista e o botão a PME pode ter apagado a regra ou
  // desactivado o recurso — e sem esta recusa a marcação entrava.
  const { modulo, sqls } = ensaio([[e(SQL_CRIAR_HOLD), [linha()]]]);
  const r = await modulo.holdSlot(CTX, SLOT_ID);
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  assert.ok(!sqls.includes(SQL_CRIAR_HOLD), "nao se escreve o que ja nao se oferece");
});

test("holdSlot toma a tranca do recurso antes de inserir", async () => {
  const { modulo, sqls } = ensaio([OFERECIVEL, [e(SQL_CRIAR_HOLD), [linha()]]]);
  const r = await modulo.holdSlot(CTX, SLOT_ID);
  assert.equal(r.tipo, "ok");
  assert.ok(
    sqls.indexOf(SQL_TRANCAR_RECURSO) < sqls.indexOf(SQL_CRIAR_HOLD),
    "sem a tranca antes, as tentativas concorrentes entram em deadlock",
  );
});

test("holdSlot repetido devolve a marcacao que ja existe, sem consumir outra", async () => {
  // A idempotência de `(contact_id, slot_id)` a valer também no hold: sem a
  // leitura, o segundo toque no mesmo botão gastava uma marcação do balde só
  // para bater no índice único.
  const { modulo, sqls } = ensaio([
    [e(SQL_MARCACAO_DO_SLOT), [linha({ estado: "confirmada", hold_expires_at: null })]],
  ]);
  const r = await modulo.holdSlot(CTX, SLOT_ID);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.estado, "confirmada");
  assert.ok(!sqls.includes(SQL_CRIAR_HOLD));
});

test("um 23P01 e um 23505 no hold viram SLOT_TAKEN, e nao excepcao", async () => {
  for (const estado of ["23P01", "23505"]) {
    const { modulo } = ensaio([OFERECIVEL, [e(SQL_CRIAR_HOLD), erroSql(estado)]]);
    const r = await modulo.holdSlot(CTX, SLOT_ID);
    assert.deepEqual(
      r,
      { tipo: "erro", erro: "SLOT_TAKEN" },
      `${estado} tem de ser uma resposta e nao uma excepcao`,
    );
  }
});

test("um erro de infra no hold continua a ser excepcao", async () => {
  // A fronteira: uma recusa de domínio é resposta, uma ligação caída não é.
  // Transformar tudo em `SLOT_TAKEN` era dizer ao cliente que o horário ficou
  // ocupado quando a base esteve em baixo.
  const { modulo } = ensaio([OFERECIVEL, [e(SQL_CRIAR_HOLD), erroSql("08006")]]);
  await assert.rejects(() => modulo.holdSlot(CTX, SLOT_ID));
});

test("confirmBooking emite uma vez e devolve a mesma marcacao na repeticao", async () => {
  const confirmada = linha({ estado: "confirmada", hold_expires_at: null, version: 2 });
  const primeiro = ensaio([[e(SQL_CONFIRMAR_HOLD), [confirmada]]]);
  const r1 = await primeiro.modulo.confirmBooking(CTX, String(confirmada["hold_id"]));
  assert.equal(r1.tipo, "ok");
  if (r1.tipo !== "ok") return;
  assert.equal(r1.valor.confirmou, true);
  assert.equal(r1.valor.eventoId, "evento-de-ensaio");
  assert.equal(primeiro.emitidos.length, 1);

  // A segunda das N: o `UPDATE` não altera nada, lê-se o estado actual.
  const segundo = ensaio([
    [e(SQL_CONFIRMAR_HOLD), []],
    [e(SQL_MARCACAO_POR_HOLD), [confirmada]],
  ]);
  const r2 = await segundo.modulo.confirmBooking(CTX, String(confirmada["hold_id"]));
  assert.equal(r2.tipo, "ok");
  if (r2.tipo !== "ok") return;
  assert.equal(r2.valor.confirmou, false, "so uma das N confirma");
  assert.equal(r2.valor.eventoId, null);
  assert.equal(segundo.emitidos.length, 0, "N confirmacoes, uma mensagem");
});

test("confirmar um hold vencido devolve HOLD_EXPIRED", async () => {
  const { modulo } = ensaio([
    [e(SQL_CONFIRMAR_HOLD), []],
    [e(SQL_MARCACAO_POR_HOLD), [linha({ estado: "expirada", hold_expires_at: null })]],
  ]);
  const r = await modulo.confirmBooking(CTX, "66666666-6666-4666-8666-666666666666");
  assert.deepEqual(r, { tipo: "erro", erro: "HOLD_EXPIRED" });
});

test("confirmar um hold inexistente devolve NOT_FOUND", async () => {
  const { modulo } = ensaio([
    [e(SQL_CONFIRMAR_HOLD), []],
    [e(SQL_MARCACAO_POR_HOLD), []],
  ]);
  const r = await modulo.confirmBooking(CTX, "66666666-6666-4666-8666-666666666666");
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
});

test("confirmar o hold de outro contacto nao escreve e devolve NOT_FOUND", async () => {
  // **O `contact_id` está no `WHERE`**: o `UPDATE` não encontra linha e não
  // escreve nada. A primeira versão confirmava primeiro e conferia depois,
  // lançando para desfazer — uma escrita antes da autorização, que durante a
  // transacção segurava o bloqueio da linha de outro contacto.
  const { modulo, emitidos } = ensaio([
    [e(SQL_CONFIRMAR_HOLD), []],
    [e(SQL_MARCACAO_POR_HOLD), [linha({ contact_id: SERVICO })]],
  ]);
  const r = await modulo.confirmBooking(CTX, "66666666-6666-4666-8666-666666666666");
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  assert.equal(emitidos.length, 0, "nao se emite um evento de uma marcacao alheia");
});

test("um identificador malformado e VALIDATION_ERROR e nao erro de driver", async () => {
  const { modulo, sqls } = ensaio([]);
  const mau = "confirm:abc";
  assert.deepEqual(await modulo.confirmBooking(CTX, mau), {
    tipo: "erro",
    erro: "VALIDATION_ERROR",
  });
  assert.deepEqual(await modulo.cancelBooking(CTX, mau), {
    tipo: "erro",
    erro: "VALIDATION_ERROR",
  });
  assert.deepEqual(await modulo.getBooking(CTX, mau), {
    tipo: "erro",
    erro: "VALIDATION_ERROR",
  });
  assert.deepEqual(sqls, [], "nenhum chega a base");
});

test("cancelBooking emite booking.cancelled com o motivo do cliente", async () => {
  // O critério 5 não pede evento. Sem ele, o agendador de lembretes (KAM-048)
  // continua a achar que a marcação existe e envia um *template utility* pago
  // a lembrar o que o cliente cancelou.
  const { modulo, cancelados } = ensaio([
    [e(SQL_CANCELAR), [linha({ estado: "cancelada", hold_expires_at: null })]],
  ]);
  const r = await modulo.cancelBooking(CTX, "55555555-5555-4555-8555-555555555555");
  assert.equal(r.tipo, "ok");
  assert.deepEqual(cancelados, [
    {
      bookingId: "55555555-5555-4555-8555-555555555555",
      motivo: "cancelado_pelo_cliente",
    },
  ]);
});

test("cancelBooking devolve NOT_FOUND quando nada e alterado", async () => {
  const { modulo } = ensaio([[e(SQL_CANCELAR), []]]);
  const r = await modulo.cancelBooking(CTX, "55555555-5555-4555-8555-555555555555");
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
});

test("getBooking nao devolve a marcacao de outro contacto do mesmo tenant", async () => {
  // X-02: a RLS isola tenants, não contactos — é esta comparação que isola
  // contactos, e por isso não é redundante.
  const { modulo } = ensaio([[e(SQL_MARCACAO), [linha({ contact_id: SERVICO })]]]);
  const r = await modulo.getBooking(CTX, "55555555-5555-4555-8555-555555555555");
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
});

test("rescheduleBooking: o slot novo ocupado devolve SLOT_TAKEN sem confirmar", async () => {
  // «Falha injectada deixa a marcação original intacta» é o `ROLLBACK`: o
  // módulo lança por dentro para que a transacção se desfaça, e converte no
  // fim. Se devolvesse um resultado, a transacção confirmava com o
  // cancelamento já escrito.
  const { modulo, sqls } = ensaio([
    [e(SQL_MARCACAO), [linha()]],
    OFERECIVEL,
    [e(SQL_CANCELAR), [linha({ estado: "cancelada", hold_expires_at: null })]],
    [e(SQL_REMARCAR), erroSql("23P01")],
  ]);
  const r = await modulo.rescheduleBooking(
    CTX,
    "55555555-5555-4555-8555-555555555555",
    SLOT_ID,
  );
  assert.deepEqual(r, { tipo: "erro", erro: "SLOT_TAKEN" });
  assert.ok(
    sqls.indexOf(SQL_TRANCAR_RECURSO) < sqls.indexOf(SQL_CANCELAR),
    "a tranca vem antes do cancelamento, e nao entre as duas metades",
  );
});

test("remarcar uma marcacao confirmada nao a degrada num hold", async () => {
  // O defeito que a revisão adversarial encontrou: com o `SQL_CRIAR_HOLD`, que
  // escreve `'hold'` literal, remarcar uma marcação **confirmada** dava-lhe um
  // prazo de dez minutos — e quem não voltasse a carregar no botão perdia-a em
  // silêncio, expirada pelo varrimento.
  const confirmada = linha({ estado: "confirmada", hold_expires_at: null, version: 2 });
  const { modulo, sqls, emitidos, cancelados } = ensaio([
    [e(SQL_MARCACAO), [confirmada]],
    OFERECIVEL,
    [e(SQL_CANCELAR), [linha({ estado: "cancelada", hold_expires_at: null })]],
    [
      e(SQL_REMARCAR),
      [linha({ estado: "confirmada", hold_expires_at: null, slot_id: SLOT_ID })],
    ],
  ]);
  const r = await modulo.rescheduleBooking(
    CTX,
    "55555555-5555-4555-8555-555555555555",
    SLOT_ID,
  );
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.estado, "confirmada", "quem ja confirmou nao volta a confirmar");
  assert.equal(r.valor.holdExpiresAt, null);
  assert.ok(!sqls.includes(SQL_CRIAR_HOLD), "a remarcacao nao usa o SQL do hold");
  // O KAM-048 precisa dos dois: o novo para reagendar, o antigo para não
  // lembrar uma hora que já não existe.
  assert.equal(emitidos.length, 1, "uma marcacao confirmada nova, um booking.created");
  assert.equal(cancelados.length, 1, "e um booking.cancelled da antiga");
});

test("remarcar um hold mantem-no hold, e nao emite booking.created", async () => {
  const { modulo, emitidos } = ensaio([
    [e(SQL_MARCACAO), [linha()]],
    OFERECIVEL,
    [e(SQL_CANCELAR), [linha({ estado: "cancelada", hold_expires_at: null })]],
    [e(SQL_REMARCAR), [linha({ slot_id: SLOT_ID })]],
  ]);
  const r = await modulo.rescheduleBooking(
    CTX,
    "55555555-5555-4555-8555-555555555555",
    SLOT_ID,
  );
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.estado, "hold");
  assert.equal(emitidos.length, 0, "um hold ainda nao e uma marcacao");
});

test("remarcar com a vertical desactivada e recusado", async () => {
  // O critério 7 só obriga no `holdSlot`, e sem isto um tenant com a vertical
  // desactivada continuava a remarcar.
  const { modulo, sqls } = ensaio([], { permitido: false });
  const r = await modulo.rescheduleBooking(
    CTX,
    "55555555-5555-4555-8555-555555555555",
    SLOT_ID,
  );
  assert.deepEqual(r, { tipo: "erro", erro: "ENTITLEMENT_DENIED" });
  assert.ok(!sqls.includes(SQL_CANCELAR), "nao se cancela o que nao se vai remarcar");
});

test("remarcar entre dois recursos tranca os dois, por ordem", async () => {
  // Sem a ordem total, duas remarcações cruzadas (A: R1→R2, B: R2→R1) tomam as
  // trancas em ordens opostas e fecham uma espera circular — um `40P01` em duas
  // remarcações legítimas.
  const outroRecurso = "00000000-0000-4000-8000-000000000001";
  const slotNoutro = derivarSlotId(SEGREDO, TENANT, {
    ...SLOT,
    resourceId: outroRecurso,
  });
  const { modulo, sqls } = ensaio([
    [e(SQL_MARCACAO), [linha()]],
    OFERECIVEL,
    [e(SQL_CANCELAR), [linha({ estado: "cancelada", hold_expires_at: null })]],
    [e(SQL_REMARCAR), [linha({ resource_id: outroRecurso, slot_id: slotNoutro })]],
  ]);
  const r = await modulo.rescheduleBooking(
    CTX,
    "55555555-5555-4555-8555-555555555555",
    slotNoutro,
  );
  assert.equal(r.tipo, "ok");
  const trancas = sqls.filter((s) => s === SQL_TRANCAR_RECURSO);
  assert.equal(trancas.length, 2, "os dois recursos, o antigo e o novo");
});

test("rescheduleBooking de uma marcacao que nao e do contacto devolve NOT_FOUND", async () => {
  const { modulo, sqls } = ensaio([[e(SQL_MARCACAO), [linha({ contact_id: SERVICO })]]]);
  const r = await modulo.rescheduleBooking(
    CTX,
    "55555555-5555-4555-8555-555555555555",
    SLOT_ID,
  );
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  assert.ok(!sqls.includes(SQL_CANCELAR), "nao se cancela a marcacao de outro");
});

test("expireHolds devolve quantos libertou e exige o tenant", async () => {
  const { modulo } = ensaio([[e(SQL_EXPIRAR_HOLDS), [{ libertados: 3 }]]]);
  assert.equal(await modulo.expireHolds({ tenantId: TENANT }), 3);
  await assert.rejects(
    () => modulo.expireHolds({ tenantId: "" }),
    CtxEmFaltaError,
  );
});

test("getAvailability recusa um intervalo invertido ou ilegivel", async () => {
  const { modulo, sqls } = ensaio([]);
  for (const intervalo of [
    { deAt: "2026-11-03T00:00:00Z", ateAt: "2026-11-02T00:00:00Z" },
    { deAt: "nao-e-data" },
    { ateAt: "tambem-nao" },
  ]) {
    const r = await modulo.getAvailability(CTX, SERVICO, intervalo);
    assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
  }
  assert.deepEqual(sqls, []);
});

test("getAvailability de um servico inactivo ou inexistente devolve NOT_FOUND", async () => {
  for (const linhas of [[], [{ service_id: SERVICO, duracao_min: 30, ativo: false }]]) {
    const { modulo } = ensaio([
      [e(SQL_EXPIRAR_HOLDS), [{ libertados: 0 }]],
      [(sql) => sql.includes("FROM servicos.services"), linhas],
    ]);
    const r = await modulo.getAvailability(CTX, SERVICO);
    assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
  }
});
