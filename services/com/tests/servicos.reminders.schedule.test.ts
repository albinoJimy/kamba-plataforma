/**
 * O agendamento do lembrete, com relógio simulado (KAM-048, critérios 1 e 4).
 *
 * **Tudo aqui corre com um relógio dado**, e é essa a razão de este ficheiro
 * existir à parte: a política do critério 1 é inteiramente sobre instantes — 24
 * h antes, menos de 2 h, já começou — e um ensaio que use `new Date()` mede o
 * dia em que corre. Nenhuma função de `schedule.ts` chama `Date.now()`, pelo que
 * o relógio é um argumento e não uma dependência a injectar.
 *
 * ## O que isto prova e o que não prova
 *
 * Prova a **política**: que instante se escolhe, que atraso sai, e em que casos
 * não se agenda nada. Prova a **desduplicação por `jobId`** contra a fila em
 * memória, e que uma remarcação produz um `jobId` novo — que é a primeira metade
 * do critério 4.
 *
 * **Não prova** a segunda metade, que é o disparo reverificar o estado e o
 * `inicio` contra a base: isso está em `servicos.reminders.deliver.test.ts`, e
 * nenhuma das duas substitui a outra. Nem prova nada sobre BullMQ: a
 * implementação do porto não existe e tem credor escrito (KAM-071), e a fila em
 * memória mede a propriedade que a de verdade também tem — o primeiro `jobId`
 * ganha.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ANTECEDENCIA_MS,
  ESTADO_QUE_LEMBRA,
  FilaDeLembretesEmMemoria,
  JOB_DO_LEMBRETE,
  MINIMO_PARA_ENVIO_MS,
  agendamentoDaMarcacao,
  agendarLembrete,
  atrasoAte,
  instanteDoLembrete,
  jobIdDoLembrete,
} from "../src/servicos/reminders/index.ts";
import { ESTADOS, type Estado } from "../src/servicos/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const BOOKING = "55555555-5555-4555-8555-555555555555";

/** `2026-11-10T09:00:00Z` — a marcação de referência. */
const INICIO = "2026-11-10T09:00:00.000Z";

function marcacao(sobrepor: { inicioAt?: string; estado?: Estado } = {}) {
  return {
    bookingId: BOOKING,
    inicioAt: sobrepor.inicioAt ?? INICIO,
    estado: sobrepor.estado ?? ("confirmada" as Estado),
  };
}

/** Um instante relativo ao início da marcação de referência. */
function antesDoInicio(ms: number): Date {
  return new Date(new Date(INICIO).getTime() - ms);
}

test("o instante do lembrete e o inicio menos a antecedencia", () => {
  const alvo = instanteDoLembrete(INICIO);
  assert.ok(alvo !== null);
  assert.equal(
    (alvo as Date).toISOString(),
    new Date(new Date(INICIO).getTime() - ANTECEDENCIA_MS).toISOString(),
  );
  // E a antecedencia e de 24 h: o numero vive numa constante, e a asserção
  // prende-o ao que o critério 1 escreve.
  assert.equal(ANTECEDENCIA_MS, 24 * 60 * 60 * 1_000);
});

test("um inicio_at que nao e data nao agenda, e nao levanta", () => {
  assert.equal(instanteDoLembrete("nao e uma data"), null);
  const decisao = agendamentoDaMarcacao(
    antesDoInicio(ANTECEDENCIA_MS * 2),
    TENANT,
    marcacao({ inicioAt: "nao e uma data" }),
  );
  assert.equal(decisao.agenda, false);
  assert.equal(decisao.agenda === false ? decisao.motivo : null, "inicio_invalido");
});

test("com 48 h de antecedencia, acorda 24 h antes do inicio", () => {
  const agora = antesDoInicio(48 * 60 * 60 * 1_000);
  const decisao = agendamentoDaMarcacao(agora, TENANT, marcacao());

  assert.equal(decisao.agenda, true);
  if (!decisao.agenda) return;
  assert.equal(decisao.trabalho.nome, JOB_DO_LEMBRETE);
  assert.equal(decisao.trabalho.atrasoMs, 24 * 60 * 60 * 1_000);
  assert.equal(decisao.trabalho.dados.tenantId, TENANT);
  assert.equal(decisao.trabalho.dados.inicioAt, INICIO);
});

test("criada com menos de 24 h de antecedencia, o lembrete e imediato", () => {
  // A primeira metade da segunda frase do critério 1: «agenda o lembrete
  // imediato». O instante do lembrete ja passou, logo o atraso certo e zero.
  const agora = antesDoInicio(5 * 60 * 60 * 1_000);
  const decisao = agendamentoDaMarcacao(agora, TENANT, marcacao());

  assert.equal(decisao.agenda, true);
  if (!decisao.agenda) return;
  assert.equal(decisao.trabalho.atrasoMs, 0);
});

test("o limiar de antecedencia minima e de 2 h, e nao um valor qualquer", () => {
  // **A ancora, e ela faltava.** O ensaio abaixo corre a fronteira toda relativa
  // a `MINIMO_PARA_ENVIO_MS`, pelo que era verdadeiro para **qualquer** valor
  // dela: a revisao adversarial poe-lhe 4 h e os 52 ensaios ficam verdes, com
  // uma marcacao para daqui a tres horas a deixar de ser lembrada e o criterio 1
  // violado a letra. A antecedencia de 24 h ja tinha a sua ancora; esta nao, e a
  // diferenca entre as duas era exactamente esta linha.
  assert.equal(MINIMO_PARA_ENVIO_MS, 2 * 60 * 60 * 1_000);
});

test("com o inicio a menos de 2 h, nao se agenda nada", () => {
  // A segunda metade: «so se o inicio estiver a mais de 2 h, caso contrario nao
  // envia». O limite e **estrito** no sentido de «mais de»: exactamente 2 h nao
  // agenda, que e a leitura conservadora — um template pago para dizer a alguem
  // o que ele escreveu ha minutos.
  for (const falta of [MINIMO_PARA_ENVIO_MS, MINIMO_PARA_ENVIO_MS - 1, 60_000]) {
    const decisao = agendamentoDaMarcacao(antesDoInicio(falta), TENANT, marcacao());
    assert.equal(decisao.agenda, false, `agendou com ${falta} ms de antecedencia`);
    assert.equal(
      decisao.agenda === false ? decisao.motivo : null,
      "antecedencia_curta",
    );
  }
  // E um milissegundo acima do limiar **agenda**: sem esta metade, um limiar
  // posto a `Infinity` passava o ensaio de cima.
  const decisao = agendamentoDaMarcacao(
    antesDoInicio(MINIMO_PARA_ENVIO_MS + 1),
    TENANT,
    marcacao(),
  );
  assert.equal(decisao.agenda, true);
});

test("uma marcacao que ja comecou nao leva lembrete", () => {
  for (const passado of [0, 1_000, 60 * 60 * 1_000]) {
    const agora = new Date(new Date(INICIO).getTime() + passado);
    const decisao = agendamentoDaMarcacao(agora, TENANT, marcacao());
    assert.equal(decisao.agenda, false);
    assert.equal(decisao.agenda === false ? decisao.motivo : null, "ja_comecou");
  }
});

test("so a marcacao confirmada leva lembrete, e os outros tres estados nao", () => {
  // Exaustivo sobre o domínio da revisão `0025`, e nao sobre dois estados
  // escolhidos a mao: um estado novo no `CHECK` da coluna aparece aqui.
  const agora = antesDoInicio(48 * 60 * 60 * 1_000);
  let confirmados = 0;
  for (const estado of ESTADOS) {
    const decisao = agendamentoDaMarcacao(agora, TENANT, marcacao({ estado }));
    if (estado === ESTADO_QUE_LEMBRA) {
      assert.equal(decisao.agenda, true);
      confirmados += 1;
      continue;
    }
    assert.equal(decisao.agenda, false, `o estado ${estado} agendou lembrete`);
    assert.equal(
      decisao.agenda === false ? decisao.motivo : null,
      "nao_confirmada",
    );
  }
  assert.equal(confirmados, 1);
});

test("o jobId leva o inicio_at, logo uma remarcacao reagenda", () => {
  // A primeira metade do critério 4. Sem o `inicio_at` no `jobId`, a fila
  // deduplicava o *job* novo contra o antigo e o lembrete saia a hora **antiga**.
  const novoInicio = "2026-11-12T15:00:00.000Z";
  assert.notEqual(jobIdDoLembrete(BOOKING, INICIO), jobIdDoLembrete(BOOKING, novoInicio));
  // E duas marcacoes diferentes nunca partilham `jobId`, mesmo a mesma hora.
  assert.notEqual(
    jobIdDoLembrete(BOOKING, INICIO),
    jobIdDoLembrete("66666666-6666-4666-8666-666666666666", INICIO),
  );
});

test("agendar duas vezes o mesmo par deixa um job; remarcar deixa dois", async () => {
  const fila = new FilaDeLembretesEmMemoria();
  const agora = antesDoInicio(48 * 60 * 60 * 1_000);

  await agendarLembrete(fila, agora, TENANT, marcacao());
  await agendarLembrete(fila, agora, TENANT, marcacao());
  assert.equal(fila.chamadas, 2);
  assert.equal(fila.contar(), 1, "a desduplicacao por jobId nao morde");

  // A remarcacao: o `jobId` muda, logo ha um *job* novo. O antigo fica na fila
  // e **nao produz mensagem** — quem o mata e a reverificacao do disparo, e nao
  // esta fila. Ver `servicos.reminders.deliver.test.ts`.
  const novoInicio = "2026-11-12T15:00:00.000Z";
  await agendarLembrete(fila, agora, TENANT, marcacao({ inicioAt: novoInicio }));
  assert.equal(fila.contar(), 2);

  // Os dois atrasos, **calculados e não escritos à mão**: a primeira versão
  // deste ensaio pôs `72 h` para o segundo e eram `78 h` — de `2026-11-08T09:00Z`
  // até `2026-11-11T15:00Z`. Um número escrito à mão num ensaio de aritmética
  // mede a aritmética de quem o escreveu.
  const esperados = [INICIO, novoInicio]
    .map((inicio) => new Date(inicio).getTime() - ANTECEDENCIA_MS - agora.getTime())
    .sort((a, b) => a - b);
  const atrasos = [...fila.adiados().values()].map((t) => t.atrasoMs).sort((a, b) => a - b);
  assert.deepEqual(atrasos, esperados);
  // E o primeiro é mesmo 24 h, que é a âncora que torna o cálculo acima
  // verificável em vez de circular.
  assert.equal(atrasos[0], 24 * 60 * 60 * 1_000);
});

test("uma marcacao que nao agenda nao chega a tocar na fila", async () => {
  const fila = new FilaDeLembretesEmMemoria();
  const decisao = await agendarLembrete(
    fila,
    antesDoInicio(48 * 60 * 60 * 1_000),
    TENANT,
    marcacao({ estado: "cancelada" }),
  );
  assert.equal(decisao.agenda, false);
  assert.equal(fila.chamadas, 0);
  assert.equal(fila.contar(), 0);
});

test("o atraso nunca e negativo", () => {
  const agora = new Date("2026-11-10T09:00:00.000Z");
  assert.equal(atrasoAte(agora, new Date("2026-11-10T08:00:00.000Z")), 0);
  assert.equal(atrasoAte(agora, agora), 0);
  assert.equal(atrasoAte(agora, new Date("2026-11-10T10:00:00.000Z")), 60 * 60 * 1_000);
});
