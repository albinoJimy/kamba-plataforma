/**
 * As reservas de stock: prazos, decisão da expiração, agendamento (KAM-045).
 *
 * O que **não** está aqui, de propósito: a concorrência do critério 1 e as
 * barreiras da revisão `0033`. Essas medem-se contra um PostgreSQL real, em
 * `db/tests_encomendas/test_reservas.py` e `test_downgrade_0033.py` — um
 * `Promise.all` sobre um objecto em memória não tem transacções para
 * serializar, e um ensaio aqui que dissesse «mil paralelas dão dez» media o
 * laço que o próprio ensaio escreveu.
 *
 * O que está aqui é o que **não** precisa de base: as funções puras dos
 * critérios 2, 3, 5 e 7, a política de agendamento do critério 4, e o caminho
 * do módulo contra uma base de ensaio que **lê o texto da instrução**.
 *
 * ## A base de ensaio lê o SQL, não a posição do argumento
 *
 * É a lição do achado 2 da revisão adversarial do KAM-179, e vale letra por
 * letra aqui: uma base que decidisse por `valores[1] === ...` ficava **verde com
 * o predicado apagado da instrução**, enquanto o comentário ao lado afirmava o
 * contrário. Por isso a `ofertaQueHonraOPredicado` faz o que o PostgreSQL faria:
 * procura o predicado aritmético **no texto** do `SQL_RESERVAR` e, se ele não
 * estiver lá, deixa passar.
 *
 * O resultado é que a mutação da barreira deixa ensaios vermelhos **nas duas
 * suites** — aqui e no *gate* 8 —, e por razões diferentes: aqui porque o
 * predicado deixou de estar no texto, lá porque mil transacções reais
 * sobrevendem.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  FOLGA_MS,
  FilaDeExpiracaoEmMemoria,
  varrer,
  INTERVALO_DO_VARRIMENTO_MS,
  PROVISORIA_MS,
  SQL_RESERVAR,
  TTL_EXPRESS_MS,
  TTL_MAXIMO_MS,
  TTL_MINIMO_MS,
  TTL_OMISSAO_MS,
  agendarExpiracoes,
  atrasoAte,
  atrasosDaLibertacao,
  autoridadeDeStock,
  commitReservation,
  decidir,
  extendReservation,
  fimDaValidade,
  fixarPrazo,
  jobIdDaReserva,
  lerReservas,
  terminal,
  percentil,
  prazoDaReserva,
  prazoDoEvento,
  prazoProvisorio,
  provisoria,
  releaseReservation,
  reserveStock,
  trabalhoDaReserva,
  ttlAceitavel,
  type Reserva,
  type Vencida,
} from "../src/reservations/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const ENCOMENDA = "22222222-2222-4222-8222-222222222222";
const RESERVA = "33333333-3333-4333-8333-333333333333";
const AGORA = new Date("2026-11-05T10:00:00.000Z");

const HORA = 60 * 60 * 1000;

// --------------------------------------------------------------- critério 2

test("KAM-045 critério 2: o expira_at é o fim da validade mais 15 min", () => {
  const prazo = prazoDaReserva(AGORA, TTL_OMISSAO_MS);
  assert.equal(
    prazo.getTime() - AGORA.getTime(),
    TTL_OMISSAO_MS + FOLGA_MS,
    "48 h de omissão mais a folga de 15 min",
  );
});

test("KAM-045 critério 2: o fim da validade é limitado às 72 h", () => {
  // Um TTL de uma semana não produz uma reserva de uma semana: o `min(now +
  // ttl, now + 72 h)` do critério corta, e é o tecto do critério 7 a valer já
  // na criação.
  const semana = 7 * 24 * HORA;
  assert.equal(
    fimDaValidade(AGORA, semana).getTime() - AGORA.getTime(),
    TTL_MAXIMO_MS,
    "o min() do critério 2 corta nas 72 h",
  );
});

test("KAM-045 critério 2: a banda [24 h, 72 h] é imposta e não corrigida", () => {
  assert.equal(ttlAceitavel(TTL_MINIMO_MS, "referencia"), true);
  assert.equal(ttlAceitavel(TTL_MAXIMO_MS, "referencia"), true);
  assert.equal(ttlAceitavel(TTL_OMISSAO_MS, "referencia"), true);
  assert.equal(
    ttlAceitavel(HORA, "referencia"),
    false,
    "uma hora está abaixo do mínimo: recusa-se em vez de se subir para 24 h — " +
      "corrigir em silêncio era a plataforma a decidir um prazo que ninguém pediu",
  );
  assert.equal(ttlAceitavel(8 * 24 * HORA, "referencia"), false);
  assert.equal(ttlAceitavel(0, "referencia"), false);
  assert.equal(ttlAceitavel(-1, "referencia"), false);
});

test("KAM-045 critério 2: o Express é a excepção declarada, não um buraco", () => {
  // 30 min está **abaixo** do mínimo de 24 h de propósito: a cobrança push dura
  // minutos (E2 §1.2). Por isso a pergunta é feita com a via.
  assert.equal(ttlAceitavel(TTL_EXPRESS_MS, "express"), true);
  assert.equal(
    ttlAceitavel(TTL_EXPRESS_MS, "referencia"),
    false,
    "os mesmos 30 min numa referência ATM são recusados",
  );
  assert.equal(
    ttlAceitavel(TTL_OMISSAO_MS, "express"),
    false,
    "e 48 h num Express também: o tecto do Express é os 30 min",
  );
});

// --------------------------------------------------------------- critério 3

test("KAM-045 critério 3: a reserva provisória vive dois minutos", () => {
  assert.equal(
    prazoProvisorio(AGORA).getTime() - AGORA.getTime(),
    PROVISORIA_MS,
  );
  assert.equal(PROVISORIA_MS, 2 * 60 * 1000, "dois minutos, a letra do critério");
});

test("KAM-045 critério 3: o charge.issued manda, e a cobrança ganha ao ttl", () => {
  // O prazo vem do fim da validade da **referência**, não do nosso ttl:
  // reservar stock por mais tempo do que a referência vive era prender stock
  // para uma cobrança que já não pode ser paga.
  const validaAte = new Date(AGORA.getTime() + 30 * HORA).toISOString();
  const prazo = prazoDoEvento(AGORA, { orderId: ENCOMENDA, validaAte }, TTL_OMISSAO_MS);
  assert.equal(
    prazo.getTime() - AGORA.getTime(),
    30 * HORA + FOLGA_MS,
    "30 h da referência mais a folga, e não as 48 h do ttl",
  );
});

test("KAM-045 critério 7: o tecto de 72 h vale também para o prazo do evento", () => {
  // Uma referência que o facilitador emitisse com validade de uma semana não
  // autoriza uma reserva de uma semana: o limite é do nosso desenho.
  const validaAte = new Date(AGORA.getTime() + 7 * 24 * HORA).toISOString();
  const prazo = prazoDoEvento(AGORA, { orderId: ENCOMENDA, validaAte }, TTL_OMISSAO_MS);
  assert.equal(prazo.getTime() - AGORA.getTime(), TTL_MAXIMO_MS + FOLGA_MS);
});

test("KAM-045 critério 3: sem prazo no evento, cai-se no ttl limitado", () => {
  const prazo = prazoDoEvento(AGORA, { orderId: ENCOMENDA }, TTL_OMISSAO_MS);
  assert.equal(prazo.getTime() - AGORA.getTime(), TTL_OMISSAO_MS + FOLGA_MS);
  // E um prazo que não é uma data trata-se como ausente, não como zero: um
  // `new Date("lixo")` dá `NaN`, e somar-lhe a folga dava `Invalid Date` numa
  // coluna `NOT NULL`.
  const comLixo = prazoDoEvento(
    AGORA,
    { orderId: ENCOMENDA, validaAte: "nao-e-uma-data" },
    TTL_OMISSAO_MS,
  );
  assert.equal(comLixo.getTime() - AGORA.getTime(), TTL_OMISSAO_MS + FOLGA_MS);
});

// --------------------------------------------------------------- critério 5

test("KAM-045 critério 5: com o PAY a confirmar, consome e não expira", () => {
  assert.deepEqual(decidir("paga"), {
    tipo: "consumir",
    porque: "pay_confirmou",
  });
});

test("KAM-045 critério 5: o desconhecida ADIA, e é o lado seguro do erro", () => {
  // «A expiração **nunca** liberta stock sem consulta final ao PAY» — e «sem
  // consulta» inclui «com uma consulta que não respondeu». Tratar
  // `desconhecida` como «não pago» deixava a indisponibilidade do PAY libertar
  // stock de encomendas pagas.
  assert.deepEqual(decidir("desconhecida"), {
    tipo: "adiar",
    porque: "pay_nao_respondeu",
  });
});

test("KAM-045 critério 5: só os estados que AFIRMAM não-pagamento libertam", () => {
  for (const estado of ["pendente", "expirada", "falhada"] as const) {
    assert.deepEqual(
      decidir(estado),
      { tipo: "libertar", motivo: "expirada" },
      `${estado} liberta com motivo expirada`,
    );
  }
  assert.deepEqual(
    decidir("cancelada"),
    { tipo: "libertar", motivo: "cancelada" },
    "e o cancelada liberta com o SEU motivo: confundi-los perdia a razão " +
      "pela qual o stock voltou, que é o que a reconciliação lê",
  );
});

test("KAM-045 critério 3: uma provisória é a que não tem confirmada_at", () => {
  const base: Vencida = {
    reservationId: RESERVA,
    tenantId: TENANT,
    orderId: ENCOMENDA,
    lineNo: 0,
    sku: "arroz-5kg",
    qty: 1,
    expiraAt: AGORA.toISOString(),
    confirmadaAt: null,
    version: 1,
  };
  assert.equal(provisoria(base), true);
  assert.equal(
    provisoria({ ...base, confirmadaAt: AGORA.toISOString() }),
    false,
    "com cobrança emitida deixa de ser provisória, e passa pela consulta final",
  );
});

// --------------------------------------------------------------- critério 4

test("KAM-045 critério 4: o jobId leva a version, e é o que faz o extend funcionar", () => {
  assert.notEqual(
    jobIdDaReserva(RESERVA, 1),
    jobIdDaReserva(RESERVA, 2),
    "sem a version no jobId, prolongar o prazo deixava agendado o despertar " +
      "do prazo ANTIGO — a fila deduplicava o job novo contra o velho",
  );
  assert.equal(jobIdDaReserva(RESERVA, 1), jobIdDaReserva(RESERVA, 1));
});

test("KAM-045 critério 4: enfileirar o mesmo job duas vezes deixa um", async () => {
  const fila = new FilaDeExpiracaoEmMemoria();
  const reserva = reservaActiva();
  const trabalho = trabalhoDaReserva(AGORA, TENANT, reserva);
  assert.notEqual(trabalho, null);
  await fila.agendarAdiado(trabalho!);
  await fila.agendarAdiado(trabalho!);
  assert.equal(fila.chamadas, 2, "chamou-se duas vezes");
  assert.equal(fila.contar(), 1, "e ficou um job: é a idempotência por jobId");
});

test("KAM-045 critério 4: uma reserva terminal não se agenda", () => {
  for (const estado of ["consumida", "libertada"] as const) {
    assert.equal(
      trabalhoDaReserva(AGORA, TENANT, { ...reservaActiva(), estado }),
      null,
      `uma reserva ${estado} não expira: agendar-lhe um despertar era pôr na ` +
        "fila trabalho que a chegada só pode recusar",
    );
  }
});

test("KAM-045 critério 4: o atraso nunca é negativo", () => {
  const passado = new Date(AGORA.getTime() - HORA).toISOString();
  assert.equal(atrasoAte(AGORA, passado), 0, "já venceu: corre já");
  assert.equal(atrasoAte(AGORA, "nao-e-uma-data"), 0);
  assert.equal(
    atrasoAte(AGORA, new Date(AGORA.getTime() + HORA).toISOString()),
    HORA,
  );
});

test("KAM-045 critério 4: o repetível é de um minuto, a letra do critério", () => {
  assert.equal(INTERVALO_DO_VARRIMENTO_MS, 60_000);
});

test("KAM-045 critério 4: o percentil de uma amostra vazia é null, não zero", () => {
  assert.equal(
    percentil([], 0.99),
    null,
    "zero era um atraso que ninguém mediu, e passava a caixa «p99 <= 60 s» " +
      "sem nenhuma libertação ter acontecido",
  );
  assert.equal(percentil([1, 2, 3, 4, 5], 0.99), 5);
  assert.equal(percentil([10], 0.5), 10);
});

// ------------------------------------------- o módulo, contra o texto do SQL

/** Uma reserva activa, para os ensaios do agendamento. */
function reservaActiva(): Reserva {
  return {
    reservationId: RESERVA,
    orderId: ENCOMENDA,
    lineNo: 0,
    sku: "arroz-5kg",
    qty: 1,
    estado: "ativa",
    motivo: null,
    expiraAt: new Date(AGORA.getTime() + 48 * HORA).toISOString(),
    confirmadaAt: null,
    version: 1,
  };
}

/**
 * Uma base de ensaio que **honra o predicado aritmético se ele estiver no texto**.
 *
 * Ver a nota do módulo: é o que impede este ensaio de ficar verde com a
 * barreira apagada. O estado do stock é mutável, para que duas reservas
 * seguidas vejam o efeito da primeira — sem isso, «a segunda é recusada» era
 * uma afirmação sobre uma fotografia.
 */
function ofertaQueHonraOPredicado(
  quantidade: number | null,
  reservada = 0,
  modo = "garantido",
) {
  const estado = { quantidade, reservada };
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  const repo = {
    tenantId: TENANT,
    async noTenant(sql: string, valores: readonly unknown[] = []) {
      vistas.push({ sql, valores });
      if (sql.includes("UPDATE platform.offer_terms")) {
        const pedida = Number(valores[1]);
        const temPredicado =
          /stock_quantidade\s*-\s*stock_reservada\s*>=\s*\$3/.test(sql);
        if (
          temPredicado &&
          estado.quantidade !== null &&
          estado.quantidade - estado.reservada < pedida
        ) {
          // O que o PostgreSQL faria: zero linhas.
          return [];
        }
        estado.reservada += pedida;
        return [
          {
            sku: valores[0],
            stock_modo: modo,
            stock_quantidade: estado.quantidade,
            stock_reservada: estado.reservada,
          },
        ];
      }
      if (sql.includes("FROM platform.offer_terms")) {
        return [
          {
            sku: valores[0],
            nome: "Arroz 5 kg",
            stock_modo: modo,
            stock_quantidade: estado.quantidade,
            stock_reservada: estado.reservada,
            estado: "publicado",
          },
        ];
      }
      return [];
    },
    async inserirNoTenant(insercao: {
      readonly valores: Readonly<Record<string, unknown>>;
    }) {
      return [
        {
          id: RESERVA,
          order_id: insercao.valores["order_id"],
          line_no: insercao.valores["line_no"],
          sku: insercao.valores["sku"],
          qty: insercao.valores["qty"],
          estado: "ativa",
          motivo: null,
          expira_at: insercao.valores["expira_at"],
          confirmada_at: null,
          version: 1,
        },
      ];
    },
  };
  return { r: { repo, agora: () => AGORA }, estado, vistas };
}

test("KAM-045: o SQL_RESERVAR leva o predicado aritmético no texto", () => {
  // O ensaio que pina a barreira. Se este falhar, os dois seguintes deixam de
  // medir o que dizem medir — e é por isso que ele é explícito em vez de
  // implícito na base de ensaio.
  assert.match(
    SQL_RESERVAR,
    /stock_quantidade\s*-\s*stock_reservada\s*>=\s*\$3/,
    "é esta a barreira do critério 1 no caminho do módulo",
  );
  assert.doesNotMatch(
    SQL_RESERVAR,
    /FOR UPDATE/,
    "e não leva FOR UPDATE: sob READ COMMITTED o próprio UPDATE serializa, " +
      "medido no test_concorrencia do KAM-044",
  );
});

test("KAM-045 critério 1: sem stock, o módulo devolve OUT_OF_STOCK", async () => {
  const { r } = ofertaQueHonraOPredicado(1);
  const primeira = await reserveStock(r, {
    orderId: ENCOMENDA,
    linhas: [{ lineNo: 0, sku: "arroz-5kg", qty: 1 }],
    ttlMs: TTL_OMISSAO_MS,
  });
  assert.equal(primeira.tipo, "ok");

  const segunda = await reserveStock(r, {
    orderId: ENCOMENDA,
    linhas: [{ lineNo: 1, sku: "arroz-5kg", qty: 1 }],
    ttlMs: TTL_OMISSAO_MS,
  });
  assert.equal(segunda.tipo, "erro");
  assert.equal(
    segunda.tipo === "erro" ? segunda.erro : null,
    "OUT_OF_STOCK",
    "e é OUT_OF_STOCK e não NOT_FOUND: o SKU existe, o stock é que acabou",
  );
});

test("KAM-045 critério 8: sem quantidade declarada, reserva sem tecto", async () => {
  // «`stock_modo='indicativo'` reserva internamente sem promessa de
  // exclusividade»: a reserva é **contada** e não limitada.
  const { r, estado } = ofertaQueHonraOPredicado(null, 0, "indicativo");
  for (let i = 0; i < 5; i += 1) {
    const resultado = await reserveStock(r, {
      orderId: ENCOMENDA,
      linhas: [{ lineNo: i, sku: "feijao-1kg", qty: 1 }],
      ttlMs: TTL_OMISSAO_MS,
    });
    assert.equal(resultado.tipo, "ok", `a ${i + 1}.ª passa`);
  }
  assert.equal(estado.reservada, 5, "contadas, e é o que «sem promessa» significa");
});

test("KAM-045 critério 2: um ttl fora da banda é recusado antes de escrever", async () => {
  const { r, vistas } = ofertaQueHonraOPredicado(10);
  const resultado = await reserveStock(r, {
    orderId: ENCOMENDA,
    linhas: [{ lineNo: 0, sku: "arroz-5kg", qty: 1 }],
    ttlMs: HORA,
  });
  assert.equal(resultado.tipo, "erro");
  assert.equal(
    vistas.length,
    0,
    "recusou **antes de escrever**: nenhuma instrução chegou à base",
  );
});

test("KAM-045 critério 1: a atomicidade é por encomenda, e o erro sai na 1.ª linha", async () => {
  // Stock 1 e duas linhas de 1: a primeira passa, a segunda não. O módulo
  // devolve `OUT_OF_STOCK` **sem tentar a terceira** — continuar a reservar
  // depois de saber que a encomenda vai ser recusada era prometer stock que o
  // `rollback` vai devolver.
  const { r, vistas } = ofertaQueHonraOPredicado(1);
  const resultado = await reserveStock(r, {
    orderId: ENCOMENDA,
    linhas: [
      { lineNo: 0, sku: "arroz-5kg", qty: 1 },
      { lineNo: 1, sku: "arroz-5kg", qty: 1 },
      { lineNo: 2, sku: "arroz-5kg", qty: 1 },
    ],
    ttlMs: TTL_OMISSAO_MS,
  });
  assert.equal(resultado.tipo, "erro");
  const updates = vistas.filter((v) => v.sql.includes("UPDATE platform.offer_terms"));
  assert.equal(
    updates.length,
    2,
    "duas tentativas de reserva e não três: parou na linha que falhou",
  );
});

test("KAM-045 critério 6: libertar duas vezes devolve stock uma vez", async () => {
  // A idempotência do critério 4, no caminho do módulo. O `estado = 'ativa'` do
  // predicado faz a segunda chamada mudar zero linhas, pelo que ela não tem
  // `(sku, qty)` nenhum para devolver.
  let activas = [{ id: RESERVA, line_no: 0, sku: "arroz-5kg", qty: 2, estado: "libertada", expira_at: AGORA.toISOString(), confirmada_at: null, version: 2 }];
  const devolucoes: unknown[][] = [];
  const repo = {
    tenantId: TENANT,
    async noTenant(sql: string, valores: readonly unknown[] = []) {
      if (sql.includes("UPDATE platform.stock_reservations")) {
        const saida = activas;
        activas = [];
        return saida;
      }
      if (sql.includes("stock_reservada = stock_reservada - $3")) {
        devolucoes.push([...valores]);
        return [{ sku: valores[0], stock_quantidade: 10, stock_reservada: 0 }];
      }
      return [];
    },
    async inserirNoTenant() {
      return [];
    },
  };
  const r = { repo, agora: () => AGORA };

  const primeira = await releaseReservation(r, ENCOMENDA, "expirada");
  assert.equal(primeira.tipo, "ok");
  assert.equal(primeira.tipo === "ok" ? primeira.valor.length : -1, 1);
  assert.equal(devolucoes.length, 1, "devolveu stock uma vez");

  const segunda = await releaseReservation(r, ENCOMENDA, "expirada");
  assert.equal(segunda.tipo, "ok", "a segunda não é erro: é um não-evento");
  assert.equal(segunda.tipo === "ok" ? segunda.valor.length : -1, 0);
  assert.equal(
    devolucoes.length,
    1,
    "e **não** devolveu stock outra vez: execução dupla = 1 libertação",
  );
});

test("KAM-045 critério 6: consumir não devolve stock", async () => {
  const devolucoes: unknown[][] = [];
  const repo = {
    tenantId: TENANT,
    async noTenant(sql: string, valores: readonly unknown[] = []) {
      if (sql.includes("estado = 'consumida'")) {
        return [
          {
            id: RESERVA,
            line_no: 0,
            sku: "arroz-5kg",
            qty: 2,
            estado: "consumida",
            expira_at: AGORA.toISOString(),
            confirmada_at: null,
            version: 2,
          },
        ];
      }
      if (sql.includes("stock_reservada = stock_reservada - $3")) {
        devolucoes.push([...valores]);
        return [{}];
      }
      return [];
    },
    async inserirNoTenant() {
      return [];
    },
  };
  const resultado = await commitReservation({ repo, agora: () => AGORA }, ENCOMENDA);
  assert.equal(resultado.tipo, "ok");
  assert.equal(
    devolucoes.length,
    0,
    "uma reserva consumida é stock que saiu: devolvê-lo era pô-lo outra vez à " +
      "venda depois de o cliente o ter pago",
  );
});

// ------------------------------------------------------- o varrimento (crit. 5)

/**
 * Um varrimento com uma vencida e um PAY que responde o que se lhe disser.
 *
 * O `semTenant` devolve a vencida na primeira chamada e nada depois: é o que o
 * `SQL_VENCIDAS` faria com uma reserva já tratada, e é o que impede o laço de
 * tratar a mesma linha duas vezes dentro da mesma volta.
 */
function varrimentoCom(estadoDoPay: "paga" | "pendente" | "desconhecida") {
  const feitas: string[] = [];
  let entregou = false;
  return {
    feitas,
    v: {
      async semTenant(sql: string) {
        feitas.push(sql);
        if (sql.includes("FROM platform.stock_reservations") && !entregou) {
          entregou = true;
          return [
            {
              id: RESERVA,
              tenant_id: TENANT,
              order_id: ENCOMENDA,
              line_no: 0,
              sku: "arroz-5kg",
              qty: 1,
              expira_at: AGORA.toISOString(),
              confirmada_at: AGORA.toISOString(),
              version: 1,
            },
          ];
        }
        if (sql.includes("UPDATE platform.stock_reservations")) {
          return [{ id: RESERVA, order_id: ENCOMENDA, line_no: 0, sku: "arroz-5kg", qty: 1, estado: "libertada", version: 2 }];
        }
        return [{}];
      },
      provedor: {
        id: "fake",
        capabilities: {} as never,
        async status() {
          return { estado: estadoDoPay } as never;
        },
      } as never,
      agora: () => AGORA,
    },
  };
}

test("KAM-045 critério 5: callback atrasado durante a varredura NÃO expira", async () => {
  // «Teste: callback atrasado durante a varredura.» O PAY confirma a meio do
  // varrimento: a reserva é **consumida** e não libertada, e não se devolve
  // stock nenhum.
  const { v, feitas } = varrimentoCom("paga");
  const resultado = await varrer(v);
  assert.deepEqual(resultado, { vistas: 1, libertadas: 0, consumidas: 1, adiadas: 0 });
  assert.equal(
    feitas.some((sql) => sql.includes("stock_reservada = stock_reservada - $3")),
    false,
    "não devolveu stock: a encomenda foi paga, o stock saiu",
  );
  assert.equal(
    feitas.some((sql) => sql.includes("estado = 'consumida'")),
    true,
  );
});

test("KAM-045 critério 5: o PAY em baixo ADIA, e não liberta nada", async () => {
  const { v, feitas } = varrimentoCom("desconhecida");
  const resultado = await varrer(v);
  assert.deepEqual(resultado, { vistas: 1, libertadas: 0, consumidas: 0, adiadas: 1 });
  assert.equal(
    feitas.some((sql) => sql.includes("estado = 'libertada'")),
    false,
    "«nunca liberta stock sem consulta final ao PAY» inclui «com uma consulta " +
      "que não respondeu»",
  );
});

test("KAM-045 critério 4: com o PAY a dizer pendente, liberta e devolve stock", async () => {
  const { v, feitas } = varrimentoCom("pendente");
  const resultado = await varrer(v);
  assert.deepEqual(resultado, { vistas: 1, libertadas: 1, consumidas: 0, adiadas: 0 });
  assert.equal(
    feitas.some((sql) => sql.includes("stock_reservada = stock_reservada - $3")),
    true,
    "a cobrança existe e não foi paga: o stock volta",
  );
});

test("KAM-045 critério 5: sem provedor o varrimento adia em vez de libertar", async () => {
  // Um varrimento que libertasse sem consultar porque ninguém lhe deu com quem
  // consultar era precisamente o que o Contexto do bloco proíbe.
  const { v } = varrimentoCom("pendente");
  const semProvedor = { semTenant: v.semTenant, agora: v.agora };
  const resultado = await varrer(semProvedor);
  assert.deepEqual(resultado, { vistas: 1, libertadas: 0, consumidas: 0, adiadas: 1 });
});

// ------------------------------- os caminhos que faltavam ao estrato `restante`

test("KAM-045 critério 7: o extendReservation recusa um instante que não é data", async () => {
  const { r, vistas } = ofertaQueHonraOPredicado(10);
  const resultado = await extendReservation(r, ENCOMENDA, "nao-e-uma-data");
  assert.equal(resultado.tipo, "erro");
  assert.equal(
    vistas.length,
    0,
    "recusou antes de escrever: um Invalid Date numa coluna NOT NULL era um " +
      "erro do motor onde devia haver um erro de domínio",
  );
});

test("KAM-045 critério 7: o extendReservation passa o tecto em horas ao SQL", async () => {
  // As quatro condições do `SQL_ESTENDER` medem-se contra a base no *gate* 8; o
  // que se mede aqui é o que o módulo **envia**: o tecto como intervalo, em
  // horas, derivado do `TTL_MAXIMO_MS` e não escrito à mão.
  const movidas: unknown[][] = [];
  const repo = {
    tenantId: TENANT,
    async noTenant(sql: string, valores: readonly unknown[] = []) {
      movidas.push([...valores]);
      if (sql.includes("criado_at + $4::interval")) {
        return [
          {
            id: RESERVA,
            line_no: 0,
            sku: "arroz-5kg",
            qty: 1,
            expira_at: "2026-11-07T10:00:00.000Z",
            confirmada_at: AGORA.toISOString(),
            version: 2,
          },
        ];
      }
      return [];
    },
    async inserirNoTenant() {
      return [];
    },
  };
  const resultado = await extendReservation(
    { repo, agora: () => AGORA },
    ENCOMENDA,
    "2026-11-07T10:00:00.000Z",
  );
  assert.equal(resultado.tipo, "ok");
  assert.deepEqual(movidas[0]?.[2], "72 hours", "o tecto vai em horas");
  if (resultado.tipo === "ok") {
    assert.equal(
      resultado.valor[0]?.confirmadaAt,
      AGORA.toISOString(),
      "e o confirmada_at vem do RETURNING: devolver null afirmava que a " +
        "reserva não tem cobrança, o contrário do que a tornou elegível",
    );
  }
});

test("KAM-045 critério 3: o fixarPrazo envia o prazo calculado e recusa id vazio", async () => {
  const enviados: unknown[][] = [];
  const repo = {
    tenantId: TENANT,
    async noTenant(_sql: string, valores: readonly unknown[] = []) {
      enviados.push([...valores]);
      return [
        {
          id: RESERVA,
          line_no: 0,
          sku: "arroz-5kg",
          qty: 1,
          expira_at: valores[1],
          version: 2,
        },
      ];
    },
    async inserirNoTenant() {
      return [];
    },
  };
  const r = { repo, agora: () => AGORA };
  const resultado = await fixarPrazo(r, { orderId: ENCOMENDA }, TTL_OMISSAO_MS);
  assert.equal(resultado.tipo, "ok");
  assert.equal(
    enviados[0]?.[1],
    new Date(AGORA.getTime() + TTL_OMISSAO_MS + FOLGA_MS).toISOString(),
    "sem prazo no evento, o módulo envia o ttl limitado mais a folga",
  );

  const vazio = await fixarPrazo(r, { orderId: "   " }, TTL_OMISSAO_MS);
  assert.equal(vazio.tipo, "erro");
});

test("KAM-045: o lerReservas e o terminal lêem o que a base devolve", async () => {
  const repo = {
    tenantId: TENANT,
    async noTenant() {
      return [
        {
          id: RESERVA,
          order_id: ENCOMENDA,
          line_no: 0,
          sku: "arroz-5kg",
          qty: 2,
          estado: "libertada",
          motivo: "cancelada",
          expira_at: AGORA.toISOString(),
          confirmada_at: null,
          version: 3,
        },
      ];
    },
    async inserirNoTenant() {
      return [];
    },
  };
  const reservas = await lerReservas({ repo }, ENCOMENDA);
  assert.equal(reservas.length, 1);
  assert.equal(reservas[0]?.motivo, "cancelada");
  assert.equal(reservas[0]?.confirmadaAt, null, "o nulo atravessa como nulo");
  assert.equal(terminal("libertada"), true);
  assert.equal(terminal("consumida"), true);
  assert.equal(terminal("ativa"), false, "só os dois terminais são terminais");
});

test("KAM-045 critério 4: o agendarExpiracoes salta as terminais e não falha sem fila", async () => {
  const fila = new FilaDeExpiracaoEmMemoria();
  const agendados = await agendarExpiracoes(fila, AGORA, TENANT, [
    reservaActiva(),
    { ...reservaActiva(), reservationId: "outra", estado: "libertada" },
  ]);
  assert.equal(agendados.length, 1, "a libertada não se agenda");
  assert.equal(fila.contar(), 1);
  await fila.agendarRepetivel(INTERVALO_DO_VARRIMENTO_MS);
  assert.equal(fila.intervalo, INTERVALO_DO_VARRIMENTO_MS);
});

test("KAM-045 critério 4: os atrasos vêm da base, em segundos e ordenados", async () => {
  const semTenant = async () => [{ atraso_s: 12 }, { atraso_s: 48 }];
  const atrasos = await atrasosDaLibertacao({ semTenant }, AGORA);
  assert.deepEqual([...atrasos], [12, 48]);
  assert.equal(
    percentil(atrasos, 0.99),
    48,
    "o p99 de dois é o maior, e o critério pede <= 60 s",
  );
});

// ------------------------------------------------- a autoridade do OUT_OF_STOCK

test("KAM-045: a autoridade de stock recusa quando não chega", async () => {
  const { r } = ofertaQueHonraOPredicado(2, 1);
  const autoridade = autoridadeDeStock(r);
  assert.equal(
    await autoridade([
      { sku: "arroz-5kg", nome: "Arroz", qty: 1, precoMinor: 1n, precoTipo: "fixo", origemPreco: "offer_terms" },
    ]),
    true,
    "1 pedido, 1 disponível: chega",
  );
  assert.equal(
    await autoridade([
      { sku: "arroz-5kg", nome: "Arroz", qty: 2, precoMinor: 1n, precoTipo: "fixo", origemPreco: "offer_terms" },
    ]),
    false,
    "2 pedidos, 1 disponível: é o OUT_OF_STOCK do createOrder",
  );
});

test("KAM-045: sem quantidade declarada a autoridade deixa passar", async () => {
  // O *fail-open* consciente que o `AutoridadeDeStock` já descrevia: recusar
  // tudo por não haver número fechava o caminho da encomenda para todo o
  // catálogo que ainda não declarou stock.
  const { r } = ofertaQueHonraOPredicado(null, 0, "indicativo");
  assert.equal(
    await autoridadeDeStock(r)([
      { sku: "feijao-1kg", nome: "Feijão", qty: 99, precoMinor: 1n, precoTipo: "fixo", origemPreco: "offer_terms" },
    ]),
    true,
  );
});
