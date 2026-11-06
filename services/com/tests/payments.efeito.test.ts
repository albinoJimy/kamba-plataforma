/**
 * O efeito do consumidor de `payment.*` (KAM-055).
 *
 * ## O duplo da base **honra o predicado**, e isso não é zelo
 *
 * É o achado 2 da revisão adversarial do KAM-179, e o módulo
 * `reservations.test.ts` já o escreve: um duplo que decida por
 * `valores[2]` fica **verde com o predicado apagado da instrução**. O
 * `SQL_TRANSITAR` é um *compare-and-set* — `WHERE id = $2 AND version = $3 AND
 * estado = $4` —, e a coisa que este ficheiro tem de medir é precisamente que o
 * CAS está lá. Por isso o duplo lê o **texto** do SQL antes de responder: sem
 * `version = $3` e `estado = $4` no predicado, recusa-se a responder e o teste
 * falha.
 *
 * ## E não há PostgreSQL aqui, de propósito
 *
 * Nenhum teste de `services/com/tests/` levanta base de dados (medido: o único
 * `process.env` da pasta é o `KAMBA_COMMIT_SHA` do `healthz.test.ts`). O que
 * precisa de motor — a FK composta, a barreira `order_estado_exige_log`, a
 * cadeia do ledger — vive em `db/tests_pagamentos/` e corre no *gate* 8. Aqui
 * mede-se o que é decisão do TypeScript: a ordem dos passos, a comparação de
 * valor, o `payload` do `payment.failed` e as recusas.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  MaquinaNaBase,
  SQL_DEFINIR_TENANT,
  SQL_MARCAR_CONSUMIDO,
  SQL_ULTIMO_SEQ,
  consumir,
} from "@kamba/core-ts/eventos";
import type { Envelope } from "@kamba/core-ts/eventos";

import {
  SQL_EMITIR,
  SQL_GRAFO,
  SQL_LER,
  SQL_TRANSITAR,
} from "../src/orders/consultas.ts";
import { VIA_POR_CAUSA } from "../src/orders/contrato.ts";
import {
  ConflitoDeTransicaoError,
  EncomendaAusenteError,
  MOTIVO_DE_VALOR,
  PROVIDER_MANUAL,
  PagamentoIncoerenteError,
  PagamentoNaoAutenticadoError,
  efeitoDePagamento,
  lagEmSegundos,
  payloadDeFalha,
} from "../src/payments/efeito.ts";
import { CORTES_DO_LAG, Lag } from "../src/payments/metricas.ts";
import { SQL_CONSUMIR } from "../src/reservations/consultas.ts";
import { SQL_MERCHANT_DO_TENANT } from "../src/repo-base/index.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const ORDEM = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50";
const EVENTO = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44";
const MERCHANT = "merch-de-ensaio";
const CONSUMER = "com_pagamentos";
const VALOR = 24_500_000;
const AGORA = new Date("2026-11-06T10:00:05.000Z");

/** O núcleo do grafo que a revisão `0030` semeia, na parte que importa. */
const GRAFO = [
  { de: "criada", para: "aguarda_pagamento", flag: null },
  { de: "aguarda_pagamento", para: "paga", flag: null },
  { de: "pendente_confirmacao", para: "paga", flag: null },
  { de: "aguarda_pagamento", para: "expirada", flag: null },
];

function envelopeDe(
  tipo: string,
  payload: Record<string, unknown>,
  parciais: Partial<Envelope> = {},
): Envelope {
  return {
    id: EVENTO,
    tipo,
    versao: 1,
    tenant_id: TENANT,
    ocorrido_em: "2026-11-06T10:00:00.000Z",
    registado_em: "2026-11-06T10:00:00.100Z",
    produtor: "pay@0.1.0",
    agregado: { tipo: "order", id: ORDEM, seq: 2 },
    correlacao_id: null,
    causa_id: null,
    trace_id: null,
    classe_pii: "P0",
    finalidades: ["transacao"],
    payload,
    ...parciais,
  } as Envelope;
}

function payloadConfirmado(valor = VALOR): Record<string, unknown> {
  return {
    order_id: ORDEM,
    provider: "facilitador_x",
    referencia: "102345678",
    valor_minor: valor,
    currency: "AOA",
    autenticacao: { authn_method: "hmac", authn_ok: true },
  };
}

function payloadManual(valor = VALOR): Record<string, unknown> {
  return {
    order_id: ORDEM,
    valor_minor: valor,
    currency: "AOA",
    autenticacao: { authn_method: "manual", authn_ok: true },
  };
}

interface Estado {
  estado: string;
  version: number;
  total_minor: string;
}

/**
 * A base falsa que **lê a instrução** antes de responder.
 *
 * O `SQL_TRANSITAR` só devolve linha quando o texto tem o CAS inteiro e quando
 * os valores batem no estado que este duplo guarda. Tirar `AND version = $3` da
 * constante faz este duplo lançar — e é essa a diferença entre medir o CAS e
 * medir uma posição de argumento.
 */
function baseFalsa(inicial: Estado, depoisDeLer?: () => void) {
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  let estado = { ...inicial };
  let reservasConsumidas = 0;
  /** Quantas vezes o `events_consumed` foi tentado. A primeira escreve. */
  let consumos = 0;

  const cliente = {
    async query(sql: string, valores: readonly unknown[] = []) {
      vistas.push({ sql, valores });

      if (sql === SQL_MERCHANT_DO_TENANT) {
        return {
          rows: [
            { medusa_merchant_id: MERCHANT, medusa_sales_channel_id: null },
          ],
          rowCount: 1,
        };
      }
      if (sql === SQL_GRAFO) return { rows: GRAFO, rowCount: GRAFO.length };
      // A consulta da `MaquinaNaBase`, construída por ela a partir do nome da
      // tabela. **Sem filtro de tenant**, e isso é desenho: quem isola é a RLS
      // sobre o `app.tenant_id` que o `consumir` definiu nesta transacção — que
      // é exactamente a razão de o `estadoDe` receber o `bd` por argumento.
      if (/^\s*SELECT estado AS estado FROM platform\.orders_mirror\b/.test(sql)) {
        if (valores[0] !== ORDEM) return { rows: [], rowCount: 0 };
        return { rows: [{ estado: estado.estado }], rowCount: 1 };
      }
      if (sql === SQL_LER) {
        assert.equal(valores[0], TENANT, "o SQL_LER filtra pelo tenant");
        if (valores[1] !== ORDEM) return { rows: [], rowCount: 0 };
        const lido = {
          id: ORDEM,
          numero_publico: "ABCD1234",
          estado: estado.estado,
          version: estado.version,
          total_minor: estado.total_minor,
          currency: "AOA",
          contact_id: "c-1",
          origem: "pme",
          entrega_modo: "levantamento",
          expira_at: null,
          paga_at: null,
          paga_via: null,
          entregue_at: null,
          entrega_confirmada_por: null,
          confirmacao_dono: "nao_aplicavel",
          lines_snapshot: [],
        };
        // O gancho corre **depois** da leitura e antes do `UPDATE`: é por aqui
        // que o ensaio do CAS faz outra transacção ganhar a corrida.
        depoisDeLer?.();
        return { rows: [lido], rowCount: 1 };
      }
      if (sql === SQL_TRANSITAR) {
        // **O predicado, lido do texto.** Sem isto o duplo decidia por
        // posição e dava verde a um `UPDATE` sem CAS.
        for (const pedaco of [
          "WHERE tenant_id = $1",
          "AND id = $2",
          "AND version = $3",
          "AND estado = $4",
        ]) {
          assert.ok(
            sql.includes(pedaco),
            `o SQL_TRANSITAR perdeu "${pedaco}": sem ele nao e um CAS`,
          );
        }
        const [, id, version, de, para, pagaAt, pagaVia] = valores;
        if (id !== ORDEM || version !== estado.version || de !== estado.estado) {
          return { rows: [], rowCount: 0 };
        }
        estado = {
          ...estado,
          estado: String(para),
          version: estado.version + 1,
        };
        return {
          rows: [
            {
              id: ORDEM,
              numero_publico: "ABCD1234",
              estado: estado.estado,
              version: estado.version,
              total_minor: estado.total_minor,
              currency: "AOA",
              expira_at: null,
              paga_via: pagaVia ?? null,
              entrega_confirmada_por: null,
              paga_at: pagaAt ?? null,
            },
          ],
          rowCount: 1,
        };
      }
      if (sql === SQL_CONSUMIR) {
        reservasConsumidas += 1;
        return { rows: [], rowCount: 0 };
      }
      if (sql === SQL_EMITIR) {
        return { rows: [{ event_id: "evt-emitido" }], rowCount: 1 };
      }
      // A transacção do `consumir`, para o ensaio dos duplicados. O
      // `events_consumed` responde `1` à primeira e `0` depois — que é
      // exactamente o que o `ON CONFLICT DO NOTHING` faz na base.
      if (/^\s*(BEGIN|COMMIT|ROLLBACK)\b/i.test(sql)) {
        return { rows: [], rowCount: 0 };
      }
      if (sql === SQL_DEFINIR_TENANT) {
        return { rows: [{ set_config: TENANT }], rowCount: 1 };
      }
      if (sql === SQL_MARCAR_CONSUMIDO) {
        consumos += 1;
        return { rows: [], rowCount: consumos === 1 ? 1 : 0 };
      }
      if (sql === SQL_ULTIMO_SEQ) {
        return { rows: [{ ultimo: null }], rowCount: 1 };
      }
      if (/^\s*INSERT\b/i.test(sql)) return { rows: [], rowCount: 1 };
      throw new Error(`o duplo nao conhece esta instrucao: ${sql}`);
    },
  };

  return {
    cliente,
    vistas,
    /** Simula outra transacção a ganhar a corrida. Só para o ensaio do CAS. */
    forcarVersao(version: number) {
      estado = { ...estado, version };
    },
    get estado() {
      return estado;
    },
    get reservasConsumidas() {
      return reservasConsumidas;
    },
  };
}

function efeito(parciais: Partial<Parameters<typeof efeitoDePagamento>[0]> = {}) {
  return efeitoDePagamento({
    consumer: CONSUMER,
    agora: () => AGORA,
    ...parciais,
  });
}

/** As instruções emitidas, pela ordem, filtradas pelo que interessa. */
function emissoes(vistas: { sql: string; valores: readonly unknown[] }[]) {
  return vistas
    .filter((v) => v.sql === SQL_EMITIR)
    .map((v) => ({ tipo: v.valores[0], payload: JSON.parse(String(v.valores[5])) }));
}

test("o caminho feliz transita, consome as reservas e emite um order.paid", async () => {
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 3,
    total_minor: String(VALOR),
  });

  await efeito()(
    base.cliente,
    envelopeDe("payment.confirmed", payloadConfirmado()),
  );

  assert.equal(base.estado.estado, "paga");
  assert.equal(base.estado.version, 4);
  assert.equal(base.reservasConsumidas, 1, "o SQL_CONSUMIR correu uma vez");

  // **O `paga_at`**, que é o `$6` do `SQL_TRANSITAR`. Entrou porque a célula do
  // critério 5 o nomeava neste ensaio e ninguém o afirmava: o duplo registava o
  // valor e nada o lia. Vem do relógio injectado, pelo que a igualdade é
  // exacta — e isso é a propriedade, não a data: o `paga_at` sai do `agora` das
  // dependências e não de um `now()` que cada chamada moveria.
  //
  // **E vai como cadeia ISO e não como `Date`**, que foi o que a primeira versão
  // desta asserção não sabia: o parâmetro é `$6::timestamptz`, e comparar com o
  // `Date` dava `'2026-…Z'` contra `2026-…Z` — o mesmo instante e tipos
  // diferentes. Afirmar a cadeia prende as duas coisas, o valor e a forma em que
  // ele chega ao condutor.
  const transitado = base.vistas.find((v) => v.sql === SQL_TRANSITAR);
  assert.equal(
    transitado?.valores[5],
    AGORA.toISOString(),
    "o paga_at e o agora injectado, em ISO",
  );

  const emitidos = emissoes(base.vistas);
  assert.deepEqual(
    emitidos.map((e) => e.tipo),
    ["order.paid"],
    "**um** order.paid, e nenhum payment.failed",
  );
  assert.equal(emitidos[0]?.payload.paga_via, "provider_autenticado");
  assert.equal(emitidos[0]?.payload.valor_minor, VALOR);

  // O registo de estado entra na mesma transacção, e é a barreira
  // `order_estado_exige_log` da revisão `0030` que o exige no `COMMIT`.
  const registos = base.vistas.filter((v) =>
    v.sql.includes("platform.order_state_log"),
  );
  assert.equal(registos.length, 1);
  assert.ok(
    String(registos[0]?.sql).startsWith("INSERT INTO platform.order_state_log"),
  );
});

test("a via de pagamento deriva da causa, e nao de um argumento", async () => {
  for (const [tipo, payload, via] of [
    ["payment.confirmed", payloadConfirmado(), "provider_autenticado"],
    ["payment.manual_confirmed", payloadManual(), "manual_auditado"],
  ] as const) {
    const base = baseFalsa({
      estado: tipo === "payment.confirmed" ? "aguarda_pagamento" : "pendente_confirmacao",
      version: 2,
      total_minor: String(VALOR),
    });
    await efeito()(base.cliente, envelopeDe(tipo, payload));
    const transitado = base.vistas.find((v) => v.sql === SQL_TRANSITAR);
    assert.equal(transitado?.valores[6], via, `${tipo} paga por ${via}`);
    assert.equal(VIA_POR_CAUSA[tipo], via, "e o mapa do contrato diz o mesmo");
  }
});

test("um valor diferente do total nao transita e emite payment.failed", async () => {
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 3,
    total_minor: String(VALOR + 1),
  });

  await efeito()(
    base.cliente,
    envelopeDe("payment.confirmed", payloadConfirmado(VALOR)),
  );

  assert.equal(base.estado.estado, "aguarda_pagamento", "nao transita");
  assert.equal(base.estado.version, 3);
  assert.equal(base.reservasConsumidas, 0, "e nao consome reservas");
  assert.equal(
    base.vistas.filter((v) => v.sql === SQL_TRANSITAR).length,
    0,
    "nem tenta o CAS",
  );
  const emitidos = emissoes(base.vistas);
  assert.deepEqual(emitidos.map((e) => e.tipo), ["payment.failed"]);
  assert.equal(emitidos[0]?.payload.motivo, MOTIVO_DE_VALOR);
  assert.equal(emitidos[0]?.payload.order_id, ORDEM);
});

test("um valor maior do que 2^53 compara-se sem arredondar", async () => {
  // O `total_minor` é `bigint`: dois valores que diferem de **um** acima do
  // inteiro seguro são iguais em `Number`. Um `Number()` aqui dava o caminho
  // feliz a um pagamento a menos.
  const total = "9007199254740993";
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: total,
  });
  await efeito()(
    base.cliente,
    envelopeDe("payment.confirmed", {
      ...payloadConfirmado(),
      valor_minor: 9_007_199_254_740_992,
    }),
  );
  assert.equal(base.estado.estado, "aguarda_pagamento");
  assert.deepEqual(emissoes(base.vistas).map((e) => e.tipo), ["payment.failed"]);
});

test("o payload que nao bate o agregado do envelope e recusado", async () => {
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  await assert.rejects(
    () =>
      efeito()(
        base.cliente,
        envelopeDe("payment.confirmed", payloadConfirmado(), {
          agregado: { tipo: "order", id: "11111111-2222-4333-8444-555555555555", seq: 1 },
        }),
      ),
    PagamentoIncoerenteError,
  );
  assert.equal(base.vistas.length, 0, "recusa antes de tocar na base");
});

test("um payload que o contrato recusa nao escreve nada", async () => {
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  const semValor = { ...payloadConfirmado() };
  delete semValor.valor_minor;
  await assert.rejects(() =>
    efeito()(base.cliente, envelopeDe("payment.confirmed", semValor)),
  );
  assert.equal(base.vistas.length, 0, "o validarPayload corre antes do SQL");
});

test("um confirmado com authn_ok falso nao paga a encomenda", async () => {
  // O furo que a revisão adversarial encontrou. O `validarPayload` compara o
  // conjunto de nomes de campo **de topo**, e `autenticacao` é um objecto
  // encaixado: um `authn_ok: false` lá dentro tem os nomes todos certos, bate o
  // `order_id`, bate o valor — e, sem esta guarda, o efeito pagava a encomenda
  // apesar de o contrato publicado declarar `authn_ok` com `"const": true`.
  //
  // **Nenhuma das três barreiras da caixa 2 do DoD o apanhava**, porque as três
  // são do lado do produtor ou da base. O lado que aplica o dinheiro não lia o
  // `payload`.
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  const payload = {
    ...payloadConfirmado(),
    autenticacao: { authn_method: "hmac", authn_ok: false },
  };
  await assert.rejects(
    () => efeito()(base.cliente, envelopeDe("payment.confirmed", payload)),
    PagamentoNaoAutenticadoError,
  );
  assert.equal(base.estado.estado, "aguarda_pagamento", "nao transita");
  assert.equal(base.estado.version, 1);
  assert.equal(base.reservasConsumidas, 0);
  assert.equal(
    base.vistas.filter((v) => v.sql === SQL_TRANSITAR).length,
    0,
    "nem tenta o CAS",
  );
  assert.deepEqual(emissoes(base.vistas).map((e) => e.tipo), [], "e nao emite");
});

test("o authn_ok tem de ser true e nao so verdadeiro-ish", async () => {
  // **`!== true` e não `=== false`.** Num caminho de dinheiro, «não me foi dito
  // que correu bem» é uma recusa e não uma coerção — e cada uma destas formas
  // passaria num `=== false`. O `manual_confirmed` entra na lista porque o
  // contrato dele declara o mesmo `const: true`.
  const formas: readonly unknown[] = [
    { authn_method: "hmac" },
    { authn_method: "hmac", authn_ok: null },
    { authn_method: "hmac", authn_ok: "true" },
    { authn_method: "hmac", authn_ok: 1 },
    null,
    "hmac",
  ];
  for (const autenticacao of formas) {
    const base = baseFalsa({
      estado: "aguarda_pagamento",
      version: 1,
      total_minor: String(VALOR),
    });
    await assert.rejects(
      () =>
        efeito()(
          base.cliente,
          envelopeDe("payment.confirmed", {
            ...payloadConfirmado(),
            autenticacao,
          }),
        ),
      PagamentoNaoAutenticadoError,
      `${JSON.stringify(autenticacao)} nao e authn_ok true`,
    );
    assert.equal(base.estado.estado, "aguarda_pagamento");
  }
});

test("um tipo que nao paga e recusado em vez de transitar", async () => {
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  await assert.rejects(() =>
    efeito()(base.cliente, envelopeDe("payment.expired", { order_id: ORDEM })),
  );
  assert.equal(base.vistas.length, 0);
});

test("a encomenda que nao existe levanta em vez de passar em claro", async () => {
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  await assert.rejects(
    () =>
      efeito()(
        base.cliente,
        envelopeDe(
          "payment.confirmed",
          { ...payloadConfirmado(), order_id: "11111111-2222-4333-8444-555555555555" },
          {
            agregado: {
              tipo: "order",
              id: "11111111-2222-4333-8444-555555555555",
              seq: 1,
            },
          },
        ),
      ),
    EncomendaAusenteError,
  );
});

test("um CAS perdido levanta, e nunca forca a transicao", async () => {
  // Outra transacção ganha a corrida entre a leitura e o `UPDATE`: a `version`
  // que o efeito leu deixa de bater, e o §6.2 manda **reler e reavaliar, nunca
  // forçar**. Sem o CAS no predicado, este `UPDATE` passava por cima dela.
  //
  // O `SQL_LER` corre **duas** vezes: uma no efeito, que lê a `version` para o
  // CAS, e outra dentro do `transition`, que a compara. O gancho avança a
  // versão depois da primeira, que é exactamente a corrida real.
  let leituras = 0;
  const base: ReturnType<typeof baseFalsa> = baseFalsa(
    { estado: "aguarda_pagamento", version: 3, total_minor: String(VALOR) },
    () => {
      leituras += 1;
      if (leituras === 1) base.forcarVersao(9);
    },
  );

  await assert.rejects(
    () =>
      efeito()(
        base.cliente,
        envelopeDe("payment.confirmed", payloadConfirmado()),
      ),
    ConflitoDeTransicaoError,
  );
  assert.equal(base.reservasConsumidas, 0, "nada depois do CAS corre");
  assert.equal(base.estado.estado, "aguarda_pagamento", "e nao transitou");
});

test("o lag so se observa no caminho que paga", async () => {
  const observados: number[] = [];
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  await efeito({ observarLag: (s) => observados.push(s) })(
    base.cliente,
    envelopeDe("payment.confirmed", payloadConfirmado()),
  );
  assert.deepEqual(observados, [5], "cinco segundos entre o evento e agora");

  const falha = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR + 1),
  });
  await efeito({ observarLag: (s) => observados.push(s) })(
    falha.cliente,
    envelopeDe("payment.confirmed", payloadConfirmado()),
  );
  assert.deepEqual(observados, [5], "um payment.failed nao e um order.paid");
});

// ------------------------------------------------------------- funções puras

test("lagEmSegundos devolve null em vez de NaN com um instante ilegivel", () => {
  const bom = envelopeDe("payment.confirmed", payloadConfirmado());
  assert.equal(lagEmSegundos(bom, AGORA), 5);
  const mau = envelopeDe("payment.confirmed", payloadConfirmado(), {
    ocorrido_em: "nao e uma data",
  });
  assert.equal(lagEmSegundos(mau, AGORA), null);
});

test("payloadDeFalha omite a referencia que nao vem e nomeia o manual", () => {
  const comReferencia = payloadDeFalha(
    envelopeDe("payment.confirmed", payloadConfirmado()),
    ORDEM,
    MOTIVO_DE_VALOR,
  );
  assert.deepEqual(sorted(comReferencia), [
    "motivo",
    "order_id",
    "provider",
    "referencia",
  ]);
  assert.equal(comReferencia.provider, "facilitador_x");

  // O `payment.manual_confirmed` **não tem** `provider` nem `referencia` no
  // payload, e o `payment.failed` exige o primeiro: um `null` ali era um campo
  // que o esquema recusa.
  const manual = payloadDeFalha(
    envelopeDe("payment.manual_confirmed", payloadManual()),
    ORDEM,
    MOTIVO_DE_VALOR,
  );
  assert.deepEqual(sorted(manual), ["motivo", "order_id", "provider"]);
  assert.equal(manual.provider, PROVIDER_MANUAL);
});

function sorted(objecto: Record<string, unknown>): string[] {
  return Object.keys(objecto).sort();
}

// ----------------------------------------------------------------- métricas

test("o histograma do lag ignora o que nao e um atraso", () => {
  const lag = new Lag();
  lag.observar(Number.NaN);
  lag.observar(-1);
  lag.observar(Number.POSITIVE_INFINITY);
  assert.equal(lag.contagem, 0, "nada disto entra");
  assert.equal(lag.p95(), null, "e sem observacoes o p95 nao se inventa");
});

test("o p95 le-se do histograma e o corte de 5 s esta nos cestos", () => {
  assert.ok(CORTES_DO_LAG.includes(5), "o alvo do criterio 9 e um corte");
  const lag = new Lag();
  // 95 observações rápidas e 5 lentas: o p95 é o corte que cobre 95.
  for (let i = 0; i < 95; i += 1) lag.observar(1);
  for (let i = 0; i < 5; i += 1) lag.observar(100);
  assert.equal(lag.contagem, 100);
  assert.equal(lag.p95(), 1);

  // Seis lentas em cem e o p95 passa do alvo: o número muda, e é isso que o
  // critério 9 lê.
  const apertado = new Lag();
  for (let i = 0; i < 94; i += 1) apertado.observar(1);
  for (let i = 0; i < 6; i += 1) apertado.observar(100);
  assert.equal(apertado.p95(), 300);
});

test("a exposicao traz os cestos, o +Inf, a soma e a contagem", () => {
  const lag = new Lag();
  lag.observar(2);
  const texto = lag.exposicao();
  assert.ok(texto.includes('com_payment_to_paid_seconds_bucket{le="5"} 1'));
  assert.ok(texto.includes('com_payment_to_paid_seconds_bucket{le="1"} 0'));
  assert.ok(texto.includes('com_payment_to_paid_seconds_bucket{le="+Inf"} 1'));
  assert.ok(texto.includes("com_payment_to_paid_seconds_sum 2"));
  assert.ok(texto.includes("com_payment_to_paid_seconds_count 1"));
  assert.ok(!texto.includes("tenant"), "nenhuma etiqueta identifica ninguem");
  assert.ok(!texto.includes("consumer"), "o consumer nao e etiqueta (OBS-I)");
});

// --------------------------------------------- o critério 3: duplicados ×10

test("o mesmo evento dez vezes produz uma transicao, um order.paid e um consumo", async () => {
  // **Com o `consumir` da biblioteca e não só com o efeito**, porque é ali que
  // a idempotência vive: o `INSERT … ON CONFLICT DO NOTHING` em
  // `events_consumed` devolve zero linhas à segunda entrega e o efeito **não
  // corre**. Testar só o efeito dez vezes media a função errada — ela não é
  // idempotente, e não tem de ser.
  //
  // O que isto não cobre é a base: a unicidade `(consumer, event_id)` e a RLS
  // são medidas em `db/tests_eventos_consumo/`. Aqui mede-se que este efeito
  // está montado atrás daquela porta, e que a porta morde.
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 3,
    total_minor: String(VALOR),
  });
  const env = envelopeDe("payment.confirmed", payloadConfirmado());
  const desfechos: string[] = [];

  for (let i = 0; i < 10; i += 1) {
    const { desfecho } = await consumir(
      {
        bd: base.cliente,
        consumer: CONSUMER,
        envelope: env,
        exigeOrdem: true,
        maquina: new MaquinaNaBase("orders_mirror"),
      },
      efeito(),
    );
    desfechos.push(desfecho);
  }

  assert.deepEqual(
    desfechos,
    ["aplicado", ...Array.from({ length: 9 }, () => "duplicado")],
    "uma aplicacao e nove duplicados",
  );
  assert.equal(base.estado.estado, "paga");
  assert.equal(base.estado.version, 4, "**uma** transicao, e nao dez");
  assert.equal(base.reservasConsumidas, 1, "e um consumo de reservas");
  assert.deepEqual(
    emissoes(base.vistas).map((e) => e.tipo),
    ["order.paid"],
    "**um** order.paid",
  );
  assert.equal(
    base.vistas.filter((v) => v.sql === SQL_MARCAR_CONSUMIDO).length,
    10,
    "dez tentativas de marca — e so a primeira escreveu",
  );
  assert.equal(
    base.vistas.filter((v) => v.sql.includes("platform.order_state_log")).length,
    1,
    "uma linha de registo de estado",
  );
});

test("a maquina real le a orders_mirror pela ligacao da transacao", async () => {
  // O `estadoDe` recebe o `bd` por argumento desde o KAM-055, e esta é a
  // propriedade que isso compra: a leitura do estado sai **pela mesma ligação**
  // em que o `consumir` definiu o `app.tenant_id`. Com o cliente no construtor,
  // a `MaquinaNaBase` lia por outra sessão — sem contexto, e sob RLS `FORCE`
  // isso devolve `null` sempre, o que a pré-condição lê como «a encomenda ainda
  // não existe» e adia até à DLQ.
  const base = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  const maquina = new MaquinaNaBase("orders_mirror");
  const estado = await maquina.estadoDe("order", ORDEM, base.cliente);
  assert.equal(estado, "aguarda_pagamento");
  assert.equal(
    base.vistas.length,
    1,
    "uma leitura, e pela ligacao que lhe foi dada",
  );
  assert.ok(String(base.vistas[0]?.sql).includes("platform.orders_mirror"));

  // E um agregado que não é `order` devolve `null` sem ir à base: é o que faz o
  // agregado errado adiar em vez de transitar a encomenda de alguém.
  const outra = baseFalsa({
    estado: "aguarda_pagamento",
    version: 1,
    total_minor: String(VALOR),
  });
  assert.equal(
    await maquina.estadoDe("payment_charge", ORDEM, outra.cliente),
    null,
  );
  assert.equal(outra.vistas.length, 0);
});
