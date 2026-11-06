/**
 * Os contadores do lembrete (KAM-048, critério 8).
 *
 * O que vale a pena medir aqui não é a soma — é a **recusa**. O
 * `MetricasDaSaida` do KAM-015 levanta para uma métrica ou uma etiqueta fora da
 * lista fechada, e a razão está escrita lá: uma etiqueta com um erro de letra
 * produzia uma série nova e silenciosa, e o painel somava dois nomes para a
 * mesma coisa sem ninguém ver. Este ficheiro prende esse comportamento, e prende
 * também a propriedade que torna as etiquetas admissíveis: **nenhuma cresce com
 * o tráfego**.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CANAIS_DO_LEMBRETE,
  CONTADORES,
  DESFECHOS_DO_AGENDAMENTO,
  METRICA_AGENDADOS,
  METRICA_ENVIADOS,
  METRICA_TRAVADOS,
  MOTIVOS_DE_BLOQUEIO,
  MOTIVOS_TRAVADOS,
  MetricaDesconhecidaError,
  MetricasDoLembrete,
  SufixoInvalidoError,
} from "../src/servicos/reminders/index.ts";

test("conta por etiqueta, e cada serie e independente", () => {
  const m = new MetricasDoLembrete();
  m.contar(METRICA_ENVIADOS, "service");
  m.contar(METRICA_ENVIADOS, "service");
  m.contar(METRICA_ENVIADOS, "utility");

  assert.equal(m.ler(METRICA_ENVIADOS, "service"), 2);
  assert.equal(m.ler(METRICA_ENVIADOS, "utility"), 1);
  assert.equal(m.ler(METRICA_TRAVADOS, "SEM_OPT_IN"), 0);
});

test("uma metrica que nao existe levanta", () => {
  const m = new MetricasDoLembrete();
  assert.throws(
    () => m.contar("booking_reminder_inventado_total", "service"),
    MetricaDesconhecidaError,
  );
});

test("uma etiqueta fora da lista fechada levanta", () => {
  const m = new MetricasDoLembrete();
  // Um erro de letra: `sevice` em vez de `service`. Sem a recusa, era uma serie
  // nova e silenciosa ao lado da certa.
  assert.throws(() => m.contar(METRICA_ENVIADOS, "sevice"), SufixoInvalidoError);
  // E uma etiqueta **em falta** numa metrica que a exige levanta pela mesma
  // razao: `booking_reminder_sent_total` sem canal nao diz o que se enviou.
  assert.throws(() => m.contar(METRICA_ENVIADOS), SufixoInvalidoError);
});

test("os motivos travados sao a uniao dos nossos portoes com os do Outbound", () => {
  // Derivada e nao escrita ao lado: um motivo novo em qualquer das duas listas
  // entra aqui sozinho. Sem esta assercao, o `SufixoInvalidoError` passava a ser
  // a maneira de descobrir que alguem acrescentou um.
  for (const motivo of MOTIVOS_DE_BLOQUEIO) {
    assert.ok(MOTIVOS_TRAVADOS.includes(motivo));
  }
  assert.ok(MOTIVOS_TRAVADOS.includes("WINDOW_CLOSED"));
  assert.ok(MOTIVOS_TRAVADOS.includes("TEMPLATE_NOT_APPROVED"));
  assert.ok(MOTIVOS_TRAVADOS.includes("MARKETING_NOT_ALLOWED"));

  const m = new MetricasDoLembrete();
  for (const motivo of MOTIVOS_TRAVADOS) {
    m.contar(METRICA_TRAVADOS, motivo);
    assert.equal(m.ler(METRICA_TRAVADOS, motivo), 1);
  }
});

test("o desfecho do agendamento cobre agendado e cada motivo de nao agendar", () => {
  const m = new MetricasDoLembrete();
  assert.ok(DESFECHOS_DO_AGENDAMENTO.includes("agendado"));
  for (const desfecho of DESFECHOS_DO_AGENDAMENTO) {
    m.contar(METRICA_AGENDADOS, desfecho);
  }
  assert.equal(m.ler(METRICA_AGENDADOS, "agendado"), 1);
  assert.equal(m.ler(METRICA_AGENDADOS, "antecedencia_curta"), 1);
});

test("nenhuma etiqueta cresce com o trafego", () => {
  // A propriedade que as torna admissiveis (`OBS-I`, X-11 do gate 6). Nenhuma
  // leva `tenant_id`, `contact_id`, `booking_id`, `channel_id` nem `wamid`, e a
  // forma de o provar e os dominios serem **fechados e pequenos**.
  assert.equal(CANAIS_DO_LEMBRETE.length, 2);
  assert.ok(DESFECHOS_DO_AGENDAMENTO.length < 10);
  assert.ok(MOTIVOS_TRAVADOS.length < 32);
});

test("a exposicao traz HELP, TYPE e uma linha por valor de etiqueta", () => {
  const m = new MetricasDoLembrete();
  m.contar(METRICA_ENVIADOS, "utility");
  const texto = m.exposicao();

  for (const metrica of CONTADORES) {
    assert.ok(texto.includes(`# HELP ${metrica} `), `falta o HELP de ${metrica}`);
    assert.ok(texto.includes(`# TYPE ${metrica} counter`));
  }
  assert.ok(texto.includes('booking_reminder_sent_total{canal="utility"} 1'));
  // **As series a zero aparecem**, e nao e enfeite: um painel que so veja as
  // series com valor nao distingue «nenhum lembrete travado» de «a metrica nao
  // existe» — a licao que o `consent_accepted_ratio` do KAM-022 pagou.
  assert.ok(texto.includes('booking_reminder_sent_total{canal="service"} 0'));
  assert.ok(texto.includes('booking_reminder_blocked_total{motivo="SEM_OPT_IN"} 0'));
  assert.ok(texto.endsWith("\n"));
});
