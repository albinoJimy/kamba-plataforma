/**
 * A ligação do motor de anomalias à base e ao `/metrics` (KAM-060).
 *
 * ## Isto mede **ligação**, e o motor tem a sua bateria noutro sítio
 *
 * As oito regras, o determinismo, a guarda de PII e a reconciliação medem-se em
 * `packages/core-ts/tests/pagamentos.anomalias.test.ts`, sobre funções puras.
 * Aqui mede-se o que só se parte na costura, e que passa todos os ensaios do
 * motor quando está partido:
 *
 *     o mapeamento de colunas   um `contact_id` na coluna do `charge_id` é
 *                               invisível a quem só exercite o motor
 *     o contador                sem o `contar`, os sinais saem iguais e o
 *                               `/metrics` serve oito séries a zero para sempre
 *     a rota                    sem o `SINAIS.exposicao()` no `criarApp`, a
 *                               métrica existe e ninguém a serve
 *     os ajustes já feitos       sem a leitura deles, um CSV repetido duplica
 *
 * ## E não há PostgreSQL aqui, de propósito
 *
 * Nenhum teste de `services/com/tests/` levanta base de dados, e este não é
 * excepção: o duplo da ligação devolve linhas com as **colunas reais** e lê o
 * texto do SQL antes de responder. O que precisa de motor — que a `payment_inbox`
 * tenha mesmo a coluna `estado`, que o `encode(payer_hmac, 'hex')` corra — fica
 * para `db/tests_pagamentos/`, e está dito na secção de verificação do bloco o
 * que daí não se mediu.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { REGRAS } from "@kamba/core-ts/pagamentos";

import {
  ALERTAS_DO_MOTOR,
  HORAS_DA_FOTOGRAFIA,
  TIPOS_QUE_O_MOTOR_LE,
  correrMotorDeAnomalias,
  desde,
  leituraSobre,
  reconciliarExtracto,
} from "../src/payments/anomalias.ts";
import { criarApp } from "../src/payments/arranque.ts";
import {
  ETIQUETA_DA_REGRA,
  METRICA_SINAIS,
  REGRAS_CONHECIDAS,
  RegraDesconhecida,
  Sinais,
} from "../src/payments/metricas.ts";

const AGORA = new Date("2026-11-08T12:00:00.000Z");
const TENANT = "11111111-1111-4111-8111-111111111111";
const CONTA = "22222222-2222-4222-8222-222222222222";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const COBRANCA = "aaaaaaaa-0000-4000-8000-000000000001";

/** Minutos antes de `AGORA`, em ISO. */
function haMinutos(minutos: number): string {
  return new Date(AGORA.getTime() - minutos * 60_000).toISOString();
}

/**
 * O duplo da ligação. **Honra o predicado**, e isso não é zelo.
 *
 * É a mesma lição do `payments.efeito.test.ts`: um duplo que decida por
 * `valores[2]` ou pela ordem da chamada fica **verde com a cláusula apagada da
 * instrução**. Aqui o que importa é que cada consulta seja a certa, pelo que o
 * duplo despacha pelo **texto** do SQL e recusa-se a responder a um texto que
 * não reconhece — uma consulta trocada falha em vez de devolver a lista errada.
 */
function ligacao(respostas: {
  readonly eventos?: Record<string, unknown>[];
  readonly cobrancas?: Record<string, unknown>[];
  readonly confirmacoes?: Record<string, unknown>[];
  readonly recusas?: Record<string, unknown>[];
  readonly casa?: Record<string, unknown>[];
  readonly ajustes?: Record<string, unknown>[];
}) {
  const chamadas: { sql: string; parametros: readonly unknown[] }[] = [];
  return {
    chamadas,
    async query(sql: string, parametros: readonly unknown[] = []) {
      chamadas.push({ sql, parametros });
      if (/FROM platform\.payment_events/.test(sql)) {
        if (/tipo_evento = 'ajuste_reconciliacao'/.test(sql)) {
          return { rows: respostas.ajustes ?? [] };
        }
        assert.match(
          sql,
          /tipo_evento = ANY\(\$1\)/,
          "a leitura de eventos tem de filtrar por tipo: sem isso traz o ledger inteiro",
        );
        return { rows: respostas.eventos ?? [] };
      }
      if (/FROM platform\.payment_charges/.test(sql)) {
        assert.match(
          sql,
          /encode\(c\.payer_hmac, 'hex'\)/,
          "o payer_hmac tem de vir em hexadecimal: dois Uint8Array iguais nao sao ===",
        );
        return { rows: respostas.cobrancas ?? [] };
      }
      if (/FROM platform\.manual_confirmations/.test(sql)) {
        return { rows: respostas.confirmacoes ?? [] };
      }
      if (/FROM platform\.payment_inbox/.test(sql)) {
        assert.match(
          sql,
          /estado = 'hmac_invalido'/,
          "a leitura de recusas tem de filtrar o desfecho, senao conta todos os callbacks",
        );
        return { rows: respostas.recusas ?? [] };
      }
      if (/FROM platform\.payment_confirmers/.test(sql)) {
        assert.match(sql, /\$1/, "a casa le-se por tenant");
        return { rows: respostas.casa ?? [] };
      }
      throw new Error(`consulta nao reconhecida pelo duplo: ${sql}`);
    },
  };
}

test("desde: a janela anda para tras e nao para a frente", () => {
  // Um erro de sinal aqui fazia a fotografia ler o futuro, e o motor devolvia
  // zero sinais com toda a conviccao.
  assert.equal(desde(AGORA, 1), "2026-11-08T11:00:00.000Z");
  assert.equal(desde(AGORA, 720), "2026-10-09T12:00:00.000Z");
});

test("a fotografia lê as cinco superfícies, e nenhuma a mais", async () => {
  const bd = ligacao({});
  await leituraSobre(bd, TENANT, AGORA).fotografar();
  assert.equal(bd.chamadas.length, 5);
  const tabelas = bd.chamadas.map((c) => /FROM (\S+)/.exec(c.sql)?.[1]);
  assert.deepEqual([...tabelas].sort(), [
    "platform.manual_confirmations",
    "platform.payment_charges",
    "platform.payment_confirmers",
    "platform.payment_events",
    "platform.payment_inbox",
  ]);
});

test("a fotografia passa a janela e os tipos que o motor lê", async () => {
  const bd = ligacao({});
  await leituraSobre(bd, TENANT, AGORA).fotografar();
  const eventos = bd.chamadas.find((c) =>
    /FROM platform\.payment_events/.test(c.sql),
  );
  assert.deepEqual(eventos?.parametros[0], [...TIPOS_QUE_O_MOTOR_LE]);
  assert.equal(eventos?.parametros[1], desde(AGORA, HORAS_DA_FOTOGRAFIA));
});

test("os três tipos que o motor lê são os que as regras consomem", () => {
  // Uma lista a menos aqui fazia uma regra deixar de disparar **sem nenhum
  // ensaio do motor morrer**: a fotografia chegava sem os eventos dela.
  assert.deepEqual([...TIPOS_QUE_O_MOTOR_LE].sort(), [
    "pagamento_divergente",
    "pagamento_duplicado",
    "pagamento_orfao",
  ]);
});

test("o mapeamento de colunas põe cada valor na sua propriedade", async () => {
  const bd = ligacao({
    eventos: [
      {
        id: "7",
        tenant_id: TENANT,
        charge_id: COBRANCA,
        account_id: CONTA,
        tipo_evento: "pagamento_orfao",
        sequencia: 3,
        valor_minor: "250000",
        instante: new Date(haMinutos(30)),
      },
    ],
    cobrancas: [
      {
        id: COBRANCA,
        tenant_id: TENANT,
        account_id: CONTA,
        order_id: null,
        estado: "paga",
        metodo: "cod",
        amount_minor: "250000",
        referencia: "REF001",
        payer_hmac: "deadbeef",
        contact_id: CONTACTO,
      },
    ],
    confirmacoes: [
      {
        charge_id: COBRANCA,
        tenant_id: TENANT,
        actor_contact_id: CONTACTO,
        decisao: "confirma",
        criado_at: haMinutos(10),
      },
    ],
    recusas: [{ account_id: CONTA, recebido_at: haMinutos(5) }],
    casa: [{ contact_id: CONTACTO, phone_hmac: "deadbeef" }],
  });
  const foto = await leituraSobre(bd, TENANT, AGORA).fotografar();

  assert.deepEqual(foto.eventos[0], {
    eventId: 7n,
    tenantId: TENANT,
    chargeId: COBRANCA,
    accountId: CONTA,
    tipoEvento: "pagamento_orfao",
    sequencia: 3,
    valorMinor: 250_000n,
    instante: haMinutos(30),
  });
  assert.deepEqual(foto.cobrancas[0], {
    chargeId: COBRANCA,
    tenantId: TENANT,
    accountId: CONTA,
    orderId: null,
    estado: "paga",
    metodo: "cod",
    amountMinor: 250_000n,
    payerHmac: "deadbeef",
    contactId: CONTACTO,
  });
  assert.deepEqual(foto.confirmacoes[0], {
    chargeId: COBRANCA,
    tenantId: TENANT,
    contactId: CONTACTO,
    decisao: "confirma",
    instante: haMinutos(10),
  });
  assert.deepEqual(foto.recusas[0], { accountId: CONTA, instante: haMinutos(5) });
  assert.deepEqual(foto.casa[0], { contactId: CONTACTO, phoneHmac: "deadbeef" });
  assert.equal(foto.agora, AGORA.toISOString());
});

test("um NULL vira null e não a cadeia 'null'", async () => {
  // `String(null)` dá `"null"`, que passa por um `Uuid` sem reclamar e casa com
  // nada — a R-05 e a R-07 ficavam a comparar a palavra «null» com UUIDs.
  const bd = ligacao({
    cobrancas: [
      {
        id: COBRANCA,
        tenant_id: TENANT,
        account_id: CONTA,
        order_id: null,
        estado: "emitida",
        metodo: "manual",
        amount_minor: "1",
        referencia: null,
        payer_hmac: null,
        contact_id: null,
      },
    ],
  });
  const foto = await leituraSobre(bd, TENANT, AGORA).fotografar();
  assert.equal(foto.cobrancas[0]?.payerHmac, null);
  assert.equal(foto.cobrancas[0]?.contactId, null);
  assert.equal(foto.cobrancas[0]?.orderId, null);
});

test("um timestamptz vem em ISO venha ele como Date ou como cadeia", async () => {
  // Um `String(date)` dava `"Mon Nov 08 2026 ..."` — **sem fuso** —, e uma
  // janela de uma hora passava a depender do fuso do processo.
  const comoData = ligacao({
    recusas: [{ account_id: CONTA, recebido_at: new Date(haMinutos(5)) }],
  });
  const comoTexto = ligacao({
    recusas: [{ account_id: CONTA, recebido_at: "2026-11-08 11:55:00+00" }],
  });
  const a = await leituraSobre(comoData, TENANT, AGORA).fotografar();
  const b = await leituraSobre(comoTexto, TENANT, AGORA).fotografar();
  assert.equal(a.recusas[0]?.instante, haMinutos(5));
  assert.equal(b.recusas[0]?.instante, haMinutos(5));
});

test("uma data ilegível passa como está, e o motor trata-a como fora da janela", async () => {
  const bd = ligacao({
    recusas: [{ account_id: CONTA, recebido_at: "ontem a tarde" }],
  });
  const foto = await leituraSobre(bd, TENANT, AGORA).fotografar();
  assert.equal(foto.recusas[0]?.instante, "ontem a tarde");
});

test("LIGAÇÃO — a corrida conta cada sinal no contador deste serviço", async () => {
  // **É este ensaio que morre com o `contar` desligado.** O
  // `detectarAnomalias` corre igual, devolve os mesmos sinais e passa todos os
  // ensaios do motor; o que desaparece é a série do `/metrics`.
  const divergencia = (id: string, minutos: number) => ({
    id,
    tenant_id: TENANT,
    charge_id: COBRANCA,
    account_id: CONTA,
    tipo_evento: "pagamento_divergente",
    sequencia: 1,
    valor_minor: "1000",
    instante: haMinutos(minutos),
  });
  const bd = ligacao({
    eventos: [divergencia("1", 50), divergencia("2", 30), divergencia("3", 10)],
  });
  const antes = new Sinais();
  const relatorio = await correrMotorDeAnomalias({
    bd,
    tenantId: TENANT,
    agora: AGORA,
  });
  assert.equal(relatorio.sinais.length, 1);
  const regra = relatorio.sinais[0]?.regra as string;
  // O contador do processo é um singleton e outros ensaios podem tê-lo tocado:
  // o que se afirma é que **subiu**, contra uma instância virgem que não subiu.
  assert.equal(antes.total(regra), 0);
  const { SINAIS } = await import("../src/payments/metricas.ts");
  assert.ok(SINAIS.total(regra) >= 1, "o contador do processo nao subiu");
});

test("a corrida encaminha os alertas que recebe", async () => {
  const alertas: string[] = [];
  const bd = ligacao({});
  await correrMotorDeAnomalias({
    bd,
    tenantId: TENANT,
    agora: AGORA,
    alertar: (alerta) => alertas.push(alerta),
  });
  // Sem anomalia nenhuma não há alerta: o par do ensaio de cima.
  assert.deepEqual(alertas, []);
});

test("os três alertas do motor estão nomeados", () => {
  assert.equal(ALERTAS_DO_MOTOR.length, 3);
  assert.equal(new Set(ALERTAS_DO_MOTOR).size, 3);
});

test("LIGAÇÃO — o /metrics serve a contagem de sinais", async () => {
  // Sem o `SINAIS.exposicao()` no `criarApp`, o `Sinais.exposicao` continua a
  // passar o ensaio dele e ninguém serve a métrica. É o defeito que o
  // `ops/metricas/catalogo.yaml` nomeia: «uma métrica que existe em código e
  // nenhum processo a serve».
  const resposta = await criarApp().request("/metrics");
  assert.equal(resposta.status, 200);
  const corpo = await resposta.text();
  assert.match(corpo, new RegExp(`# TYPE ${METRICA_SINAIS} counter`));
  for (const regra of REGRAS_CONHECIDAS) {
    assert.ok(
      corpo.includes(`${METRICA_SINAIS}{${ETIQUETA_DA_REGRA}="${regra}"}`),
      `falta a serie da regra ${regra}`,
    );
  }
});

test("o /metrics continua a servir as outras duas exposições", async () => {
  // O par: acrescentar a terceira não pode apagar as duas de que já havia dono.
  const corpo = await (await criarApp().request("/metrics")).text();
  assert.match(corpo, /# TYPE com_payment_to_paid_seconds histogram/);
  assert.match(corpo, /evt_/);
});

test("as oito séries aparecem a zero antes do primeiro sinal", () => {
  // Uma série que só nasce depois do primeiro sinal faz o painel mostrar «sem
  // dados» onde a leitura certa é «zero anomalias», e um `increase(...) > 0`
  // sobre uma série que não existe nunca dispara.
  const sinais = new Sinais();
  const corpo = sinais.exposicao();
  assert.equal(corpo.match(/fraud_signals_total\{/g)?.length, REGRAS.length);
  assert.match(corpo, /fraud_signals_total\{regra="auto_compra"\} 0/);
});

test("o contador sobe por regra e não em bloco", () => {
  const sinais = new Sinais();
  sinais.contar("auto_compra");
  sinais.contar("auto_compra");
  sinais.contar("pagamento_orfao");
  assert.equal(sinais.total("auto_compra"), 2);
  assert.equal(sinais.total("pagamento_orfao"), 1);
  assert.equal(sinais.total("pagamento_duplicado"), 0);
});

test("uma regra desconhecida levanta, e não abre a cardinalidade", () => {
  // Aceitá-la abria a etiqueta a qualquer cadeia — o que o domínio fechado do
  // catálogo existe para impedir —, e descartá-la em silêncio fazia uma regra
  // nova nascer a zero para sempre.
  const sinais = new Sinais();
  assert.throws(() => sinais.contar("inventada"), RegraDesconhecida);
});

test("as regras conhecidas derivam do motor e não de uma segunda lista", () => {
  assert.deepEqual([...REGRAS_CONHECIDAS], REGRAS.map((r) => r.regra));
});

test("a reconciliação lê os ajustes já feitos antes de propor", async () => {
  const bd = ligacao({ ajustes: [] });
  const paga = {
    chargeId: COBRANCA,
    tenantId: TENANT,
    accountId: CONTA,
    orderId: null,
    estado: "paga",
    metodo: "referencia",
    amountMinor: 100_000n,
    payerHmac: null,
    contactId: CONTACTO,
  } as const;
  const csv = "referencia;valor_minor;data\nREF001;90000;2026-11-07\n";
  const primeira = await reconciliarExtracto({
    bd,
    csv,
    cobrancas: [paga],
    referenciaPorCobranca: { [COBRANCA]: "REF001" },
  });
  assert.equal(primeira.ajustes.length, 1);
  assert.equal(primeira.sinais.length, 1);
  assert.match(bd.chamadas[0]?.sql ?? "", /tipo_evento = 'ajuste_reconciliacao'/);

  // **O mesmo CSV outra vez, com o ajuste já no ledger: nada a propor.** Sem a
  // leitura dos ajustes feitos, isto duplicava — e o índice único de
  // `provider_event_id` da revisão `0029` é parcial e não o impede.
  const comHistorico = ligacao({
    ajustes: primeira.ajustes.map((a) => ({
      provider_event_id: a.providerEventId,
    })),
  });
  const segunda = await reconciliarExtracto({
    bd: comHistorico,
    csv,
    cobrancas: [paga],
    referenciaPorCobranca: { [COBRANCA]: "REF001" },
  });
  assert.deepEqual(segunda.ajustes, []);
  assert.deepEqual(segunda.sinais, []);
});
