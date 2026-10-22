/**
 * A máquina de modos e a guarda pré-envio (KAM-018), no *gate* 4.
 *
 * O que aqui se prova é a **ordem** e o contrato — que o *lock* vem antes de
 * qualquer leitura, que o predicado da tabela vai no `UPDATE`, que uma corrida
 * perdida não emite evento, que a supressão escreve a linha **antes** de
 * devolver o cancelamento, e que o `onOptOut` é por contacto e não por conversa.
 * Com uma base falsa, que é o único sítio onde a ordem se consegue ver.
 *
 * O que **não** se prova aqui: a corrida das 100 intercalações, o *lock* a
 * serializar de verdade, a RLS, o privilégio do `mode` e a independência de duas
 * conversas contra uma base real. Isso é `tests_bd/modos.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  ConversaDesconhecidaError,
  MaquinaDeModos,
  METRICA_REJEITADAS,
  METRICA_SUPRIMIDAS,
  METRICA_TRANSICOES,
  MetricasDosModos,
  GATILHOS,
  SEM_HUMANO_MS,
  SQL_CONTACTO_DA_CONVERSA,
  SQL_CONVERSAS_DO_CONTACTO,
  SQL_CONVERSA_PARA_MODO,
  SQL_EMITIR_MODE_CHANGED,
  SQL_MUDAR_MODO,
  SQL_PAUSAR_POR_INACTIVIDADE,
  SQL_REGISTAR_ACTIVIDADE_HUMANA,
  SQL_SUPRIMIR_ENVIO,
  SQL_TRANCAR_CONVERSA,
  avaliar,
  criarGuarda,
  emitirModoMudado,
  payloadDoModo,
  registoDaSupressao,
} from "../src/modos/index.ts";
import { Logger } from "../src/logger/index.ts";
import type { Pedido } from "../src/outbound/index.ts";
import { BaseFalsa } from "./modos.base_falsa.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONTACTO = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50";
const CONVERSA = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44";
const CANAL = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";
const T0 = new Date("2026-11-02T14:00:00.000Z");

const CONSULTAS = {
  trancar: SQL_TRANCAR_CONVERSA,
  contacto: SQL_CONTACTO_DA_CONVERSA,
  ler: SQL_CONVERSA_PARA_MODO,
  doContacto: SQL_CONVERSAS_DO_CONTACTO,
  mudar: SQL_MUDAR_MODO,
  actividade: SQL_REGISTAR_ACTIVIDADE_HUMANA,
  pausar: SQL_PAUSAR_POR_INACTIVIDADE,
  suprimir: SQL_SUPRIMIR_ENVIO,
  emitir: SQL_EMITIR_MODE_CHANGED,
};

let bd: BaseFalsa;
let metricas: MetricasDosModos;

function maquina(agora = () => T0): MaquinaDeModos {
  return new MaquinaDeModos({
    comTenant: bd.comTenant(),
    emitir: emitirModoMudado,
    metricas,
    agora,
  });
}

function pedido(troca: Partial<Pedido> = {}): Pedido {
  return {
    tenantId: TENANT,
    channelId: CANAL,
    contactId: CONTACTO,
    conversationId: CONVERSA,
    phoneNumberId: "pnid-1",
    idempotencyKey: "turno-1",
    corpo: { tipo: "texto", texto: "ola" },
    doBot: true,
    turnoIniciadoEm: T0,
    ...troca,
  };
}

beforeEach(() => {
  bd = new BaseFalsa(CONSULTAS);
  metricas = new MetricasDosModos();
});

describe("o lock vem primeiro (criterio 2)", () => {
  it("trancar e a primeira instrucao da guarda", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    await avaliar({ comTenant: bd.comTenant(), metricas }, pedido());
    assert.equal(bd.vistas[0]?.sql, SQL_TRANCAR_CONVERSA);
    assert.deepEqual(bd.vistas[0]?.parametros, [TENANT, CONTACTO]);
  });

  it("a chave do lock e (tenant_id, contact_id) e nao a conversa", () => {
    // É o que o critério 2 escreve — `hash(tenant_id, contact_id)` — e é o que
    // faz o `onOptOut` poder travar todas as conversas de um contacto de uma
    // vez. A cadeia tem de mencionar os dois e **não** a conversa.
    assert.match(SQL_TRANCAR_CONVERSA, /pg_advisory_xact_lock/);
    assert.match(SQL_TRANCAR_CONVERSA, /hashtextextended\(\$1::text \|\| ':' \|\| \$2::text, 0\)/);
  });

  it("a maquina tranca antes de decidir, e nao decide com a leitura de antes", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    await maquina().disparar({ tenantId: TENANT, conversationId: CONVERSA }, "handoff_pedido");
    // A primeira leitura traz **só** o `contact_id`; o `trancar` vem a seguir;
    // e a leitura que decide é a terceira instrução, já dentro do *lock*. A
    // base falsa recusa o `SQL_CONVERSA_PARA_MODO` antes do *lock*, pelo que
    // trocar estes dois passos não dá uma ordem diferente: dá um erro.
    assert.deepEqual(bd.vistas.map((v) => v.sql), [
      SQL_CONTACTO_DA_CONVERSA,
      SQL_TRANCAR_CONVERSA,
      SQL_CONVERSA_PARA_MODO,
      SQL_MUDAR_MODO,
      SQL_EMITIR_MODE_CHANGED,
    ]);
  });

  it("a guarda e a maquina pedem o mesmo lock, e isso e o que as serializa", () => {
    // Se as duas cadeias divergirem, as duas tomam *locks* diferentes e a
    // secção crítica deixa de existir — sem nenhum teste a falhar, que é o
    // pior dos casos. É uma constante só, e é esta asserção que o garante.
    assert.equal(CONSULTAS.trancar, SQL_TRANCAR_CONVERSA);
  });
});

describe("a maquina de modos", () => {
  it("uma transicao escreve, conta e emite", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    const r = await maquina().disparar(
      { tenantId: TENANT, conversationId: CONVERSA },
      "handoff_resolvido",
    );
    assert.equal(r.mudou, true);
    assert.equal(r.ganhou, true);
    assert.equal(r.modo, "bot");
    assert.equal(r.eventoId, "evt-1");
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:handoff_resolvido`], 1);
  });

  it("o UPDATE leva o predicado da tabela, e nao «qualquer modo menos o destino»", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    await maquina().disparar(
      { tenantId: TENANT, conversationId: CONVERSA },
      "handoff_resolvido",
    );
    const mudar = bd.vistas.find((v) => v.sql === SQL_MUDAR_MODO);
    assert.deepEqual(mudar?.parametros[3], ["humano"]);
    assert.match(SQL_MUDAR_MODO, /AND antes\.mode = ANY\(\$4::text\[\]\)/);
  });

  it("uma corrida perdida nao emite evento nem conta transicao", async () => {
    // Zero linhas no `UPDATE`: outro processo transitou primeiro. É a mesma
    // leitura do `SQL_AVANCAR_ESTADO` do KAM-015 — emitir a partir da leitura
    // prévia publicava duas mudanças para uma transição.
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    bd.perderCorrida = true;
    const r = await maquina().disparar(
      { tenantId: TENANT, conversationId: CONVERSA },
      "handoff_resolvido",
    );
    assert.equal(r.ganhou, false);
    assert.equal(r.mudou, false);
    assert.equal(r.eventoId, null);
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:handoff_resolvido`], undefined);
    assert.equal(bd.vistas.filter((v) => v.sql === SQL_EMITIR_MODE_CHANGED).length, 0);
  });

  it("um gatilho rejeitado nao escreve nada, e conta-se", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    const r = await maquina().disparar(
      { tenantId: TENANT, conversationId: CONVERSA },
      "comando_bot",
    );
    assert.equal(r.resposta.tipo, "rejeitada");
    assert.equal(bd.conversas.get(CONVERSA)?.mode, "humano");
    assert.equal(bd.conversas.get(CONVERSA)?.last_human_activity_at, null);
    assert.equal(metricas.ler()[`${METRICA_REJEITADAS}:comando_bot`], 1);
  });

  it("um echo numa conversa ja em `dono` escreve a actividade e nao o modo", async () => {
    // **É o defeito que adiava o silêncio do dono.** Sem esta escrita, o
    // `silencio_dono_min` contava-se do primeiro *echo* e o bot retomava a
    // palavra a meio de uma conversa que o dono estava a fazer.
    const antes = new Date(T0.getTime() - 60_000);
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "dono", last_human_activity_at: antes });
    const r = await maquina().disparar(
      { tenantId: TENANT, conversationId: CONVERSA },
      "echo_do_dono",
    );
    assert.equal(r.resposta.tipo, "sem_efeito");
    assert.equal(r.mudou, false);
    assert.equal(bd.conversas.get(CONVERSA)?.mode, "dono");
    assert.deepEqual(bd.conversas.get(CONVERSA)?.last_human_activity_at, T0);
  });

  it("um gatilho sem efeito que nao e actividade humana nao escreve nada", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    await maquina().disparar({ tenantId: TENANT, conversationId: CONVERSA }, "cliente_escreveu");
    assert.equal(bd.vistas.filter((v) => v.sql === SQL_REGISTAR_ACTIVIDADE_HUMANA).length, 0);
    assert.equal(bd.vistas.filter((v) => v.sql === SQL_MUDAR_MODO).length, 0);
  });

  it("o `handoff_pedido` nao e actividade humana: a coluna fica a NULL", async () => {
    // Quem pede é o grafo ou o cliente. Escrevê-la aqui tornava a coluna «o
    // instante em que uma pessoa passou a ter a palavra», e o relógio das 24 h
    // contaria de um momento em que ninguém respondeu.
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    await maquina().disparar({ tenantId: TENANT, conversationId: CONVERSA }, "handoff_pedido");
    assert.equal(bd.conversas.get(CONVERSA)?.mode, "humano");
    assert.equal(bd.conversas.get(CONVERSA)?.last_human_activity_at, null);
  });

  it("sem porta de emissao, a maquina funciona e nao emite", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    const m = new MaquinaDeModos({ comTenant: bd.comTenant(), emitir: null, metricas });
    const r = await m.disparar({ tenantId: TENANT, conversationId: CONVERSA }, "opt_out");
    assert.equal(r.mudou, true);
    assert.equal(r.eventoId, null);
  });
});

describe("onOptOut: por contacto e nao por canal (criterio 7)", () => {
  it("pausa as duas conversas do contacto, com um lock so", async () => {
    bd.semear("conv-a", { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    bd.semear("conv-b", { contact_id: CONTACTO, mode: "dono", last_human_activity_at: T0 });
    const r = await maquina().onOptOut({ tenantId: TENANT, contactId: CONTACTO });
    assert.equal(r.length, 2);
    assert.ok(r.every((x) => x.modo === "pausada" && x.mudou));
    assert.equal(bd.vistas.filter((v) => v.sql === SQL_TRANCAR_CONVERSA).length, 1);
    assert.equal(bd.transaccoes, 1);
  });

  it("nao toca na conversa de outro contacto", async () => {
    bd.semear("conv-a", { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    bd.semear("conv-outro", { contact_id: "outro", mode: "bot", last_human_activity_at: null });
    await maquina().onOptOut({ tenantId: TENANT, contactId: CONTACTO });
    assert.equal(bd.conversas.get("conv-a")?.mode, "pausada");
    assert.equal(bd.conversas.get("conv-outro")?.mode, "bot");
  });

  it("repetir o PARAR nao escreve nada: a celula `pausada + opt_out` e sem efeito", async () => {
    // **A idempotência é da tabela e não de uma chave**, e é por isso que não há
    // coluna de controlo nenhuma a manter.
    bd.semear("conv-a", { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    await maquina().onOptOut({ tenantId: TENANT, contactId: CONTACTO });
    const antes = bd.vistas.length;
    const segunda = await maquina().onOptOut({ tenantId: TENANT, contactId: CONTACTO });
    assert.deepEqual(
      segunda.map((x) => x.mudou),
      [false],
    );
    // Duas instruções a mais na segunda passagem — o *lock* e a listagem — e
    // nenhum `UPDATE` nem emissão.
    const novas = bd.vistas.slice(antes).map((v) => v.sql);
    assert.deepEqual(novas, [SQL_TRANCAR_CONVERSA, SQL_CONVERSAS_DO_CONTACTO]);
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:opt_out`], 1);
  });

  it("um contacto sem conversas devolve lista vazia e nao rebenta", async () => {
    const r = await maquina().onOptOut({ tenantId: TENANT, contactId: CONTACTO });
    assert.deepEqual(r, []);
  });
});

describe("o job das 24 h (criterio 7)", () => {
  it("pausa o que passou das 24 h e deixa o resto", async () => {
    const velha = new Date(T0.getTime() - SEM_HUMANO_MS - 1);
    const recente = new Date(T0.getTime() - SEM_HUMANO_MS + 1);
    bd.semear("velha", { contact_id: CONTACTO, mode: "humano", last_human_activity_at: velha });
    bd.semear("recente", { contact_id: CONTACTO, mode: "humano", last_human_activity_at: recente });
    bd.semear("em-bot", { contact_id: CONTACTO, mode: "bot", last_human_activity_at: velha });
    const r = await maquina().pausarPorInactividade(TENANT);
    assert.deepEqual(r.ids, ["velha"]);
    assert.equal(r.pausadas, 1);
    assert.equal(bd.conversas.get("recente")?.mode, "humano");
    assert.equal(bd.conversas.get("em-bot")?.mode, "bot");
  });

  it("correr duas vezes seguidas pausa N e depois 0 (idempotente)", async () => {
    const velha = new Date(T0.getTime() - SEM_HUMANO_MS - 1);
    bd.semear("velha", { contact_id: CONTACTO, mode: "humano", last_human_activity_at: velha });
    const m = maquina();
    assert.equal((await m.pausarPorInactividade(TENANT)).pausadas, 1);
    assert.equal((await m.pausarPorInactividade(TENANT)).pausadas, 0);
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:sem_humano_24h`], 1);
  });

  it("sao 24 h, e nao a janela de servico da Meta", () => {
    assert.equal(SEM_HUMANO_MS, 24 * 60 * 60 * 1000);
  });

  it("o predicado do SQL vem da tabela e nao de um modo escrito a mao", async () => {
    bd.semear("velha", {
      contact_id: CONTACTO,
      mode: "humano",
      last_human_activity_at: new Date(T0.getTime() - SEM_HUMANO_MS - 1),
    });
    await maquina().pausarPorInactividade(TENANT);
    const pausar = bd.vistas.find((v) => v.sql === SQL_PAUSAR_POR_INACTIVIDADE);
    assert.deepEqual(pausar?.parametros[2], ["humano"]);
    assert.equal(pausar?.parametros[3], "pausada");
    // E o SQL não tem nenhum modo literal: se tivesse, divergia da tabela sem
    // nenhum teste a notar.
    assert.ok(!/'humano'|'pausada'|'bot'|'dono'/.test(SQL_PAUSAR_POR_INACTIVIDADE));
  });

  it("conta das 24 h a partir do handoff quando nao houve actividade humana", () => {
    // A base falsa não tem `handoffs`; o que se afirma aqui é que o SQL **vai**
    // buscar o `opened_at` do *handoff* mais recente. A prova de que funciona é
    // contra a base real (`tests_bd/modos.bd.test.ts`).
    assert.match(SQL_PAUSAR_POR_INACTIVIDADE, /COALESCE\(/);
    assert.match(SQL_PAUSAR_POR_INACTIVIDADE, /max\(h\.opened_at\)/);
    assert.match(SQL_PAUSAR_POR_INACTIVIDADE, /platform\.handoffs/);
  });
});

describe("a porta MudarModo do ConsentGate (KAM-022)", () => {
  it("`humano` dispara o handoff e `pausada` dispara o opt-out", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    const porta = maquina().portaDoConsentGate();
    await porta(TENANT, CONVERSA, "humano");
    assert.equal(bd.conversas.get(CONVERSA)?.mode, "humano");
    await porta(TENANT, CONVERSA, "pausada");
    assert.equal(bd.conversas.get(CONVERSA)?.mode, "pausada");
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:handoff_pedido`], 1);
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:opt_out`], 1);
  });

  it("uma conversa que nao existe nao desfaz o PARAR: a porta engole essa so", async () => {
    // O gate chama esta porta **depois** de escrever a prova *append-only* e de
    // enviar o aviso. A retenção do KAM-071 pode ter purgado a conversa entre a
    // mensagem e esta chamada; deixar a excepção subir fazia o `tratar` falhar
    // com os dois já escritos, e o *job* repetia-se sobre um estado que nunca
    // vai melhorar.
    const porta = maquina().portaDoConsentGate();
    await porta(TENANT, "conversa-que-nao-existe", "pausada");
    // E **só** essa: um modo que o código não conhece é defeito nosso e sobe.
    bd.semear(CONVERSA, {
      contact_id: CONTACTO,
      mode: "inventado" as never,
      last_human_activity_at: null,
    });
    await assert.rejects(() => porta(TENANT, CONVERSA, "pausada"), /modo desconhecido/);
  });

  it("o `ConversaDesconhecidaError` e o tipo que a porta apanha", async () => {
    // Pelo tipo e não pela mensagem: um `instanceof` que mude de classe sem
    // ninguém notar é o defeito que este teste fecha.
    await assert.rejects(
      () => maquina().disparar({ tenantId: TENANT, conversationId: "nao-existe" }, "opt_out"),
      ConversaDesconhecidaError,
    );
  });

  it("um modo que a tabela recuse nao lanca: o PARAR nao se desfaz", async () => {
    // Um `registar_revogacao` sobre uma conversa já `pausada` é «sem efeito»; o
    // que importa é que a porta não lança — a prova *append-only* do KAM-022 e o
    // aviso já enviado não se desfazem por causa do modo.
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "pausada", last_human_activity_at: null });
    const porta = maquina().portaDoConsentGate();
    await porta(TENANT, CONVERSA, "pausada");
    assert.equal(bd.conversas.get(CONVERSA)?.mode, "pausada");
  });
});

describe("o registo nao levanta, e foi um defeito medido", () => {
  /** Uma saída de *log* que guarda as linhas, como a de `logger.test.ts`. */
  class SaidaDeLog {
    texto = "";
    write(pedaco: string): void {
      this.texto += pedaco;
    }
    linhas(): Record<string, unknown>[] {
      return this.texto
        .split("\n")
        .filter((l) => l !== "")
        .map((l) => JSON.parse(l) as Record<string, unknown>);
    }
  }

  it("um gatilho rejeitado em modo ESTRITO nao levanta, nem com o `sem_humano_24h`", async () => {
    // **O defeito que este teste fecha.** A primeira versão escrevia
    // `outcome: \`modo_rejeitado_${gatilho}\``, e um dos oito gatilhos não cabe
    // na gramática do campo: um segmento é letras com até três dígitos **no
    // fim**, ou um número, e o `24h` do `sem_humano_24h` não é nenhum dos dois
    // (`logger/politica.ts`). Em modo estrito — o do CI — o `Logger` levanta, e
    // uma transição rejeitada, que é um **resultado** normal desta função,
    // passava a excepção não tratada no caminho de um *webhook*.
    //
    // Os oito gatilhos, todos, e sobre um modo em que cada um é rejeitado ou
    // sem efeito: nenhum pode fazer o registo levantar.
    const saida = new SaidaDeLog();
    const log = new Logger("chr", { destino: saida, estrito: true });
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "pausada", last_human_activity_at: null });
    const m = new MaquinaDeModos({
      comTenant: bd.comTenant(),
      emitir: null,
      metricas,
      log,
      agora: () => T0,
    });
    for (const gatilho of GATILHOS) {
      await m.disparar({ tenantId: TENANT, conversationId: CONVERSA }, gatilho);
    }
    // E o `outcome` que saiu é o fixo, sem o gatilho: o gatilho está na
    // etiqueta da métrica, que é onde a lista é fechada.
    const rejeitados = saida.linhas().filter((l) => l.outcome === "modo_rejeitado");
    assert.ok(rejeitados.length > 0, "nenhuma rejeicao foi registada");
    assert.ok(
      !saida.linhas().some((l) => String(l.outcome).startsWith("modo_rejeitado_")),
      "o gatilho voltou ao `outcome`",
    );
  });

  it("a supressao e a transicao tambem nao levantam em modo estrito", async () => {
    const saida = new SaidaDeLog();
    const log = new Logger("com", { destino: saida, estrito: true });
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    await avaliar({ comTenant: bd.comTenant(), metricas, log }, pedido());
    const m = new MaquinaDeModos({
      comTenant: bd.comTenant(),
      emitir: null,
      metricas,
      log,
      agora: () => T0,
    });
    await m.disparar({ tenantId: TENANT, conversationId: CONVERSA }, "handoff_resolvido");
    await m.disparar({ tenantId: TENANT, conversationId: CONVERSA }, "opt_out");
    const desfechos = saida.linhas().map((l) => l.outcome);
    assert.ok(desfechos.includes("suprimido_modo"));
    assert.ok(desfechos.includes("modo_humano_para_bot"));
    assert.ok(desfechos.includes("modo_bot_para_pausada"));
  });
});

describe("a metrica nao conta o que a transaccao desfez", () => {
  it("se a emissao levantar, `conv_mode_transitions_total` nao sobe", async () => {
    // As duas escritas vivem na mesma transacção: se a emissão levantar, o
    // `UPDATE` é desfeito. Um contador em memória **não** é desfeito com ela,
    // pelo que contar antes deixava a métrica a afirmar transições que a base
    // nunca guardou. A prova de que a transição é desfeita é contra a base
    // real; o que aqui se prova é que o contador não subiu.
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    const m = new MaquinaDeModos({
      comTenant: bd.comTenant(),
      emitir: async () => {
        throw new Error("falha de ensaio na emissao");
      },
      metricas,
      agora: () => T0,
    });
    await assert.rejects(
      () => m.disparar({ tenantId: TENANT, conversationId: CONVERSA }, "opt_out"),
      /falha de ensaio na emissao/,
    );
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:opt_out`], undefined);
  });

  it("no job das 24 h vale o mesmo", async () => {
    bd.semear("velha", {
      contact_id: CONTACTO,
      mode: "humano",
      last_human_activity_at: new Date(T0.getTime() - SEM_HUMANO_MS - 1),
    });
    const m = new MaquinaDeModos({
      comTenant: bd.comTenant(),
      emitir: async () => {
        throw new Error("falha de ensaio na emissao");
      },
      metricas,
      agora: () => T0,
    });
    await assert.rejects(() => m.pausarPorInactividade(TENANT), /falha de ensaio/);
    assert.equal(metricas.ler()[`${METRICA_TRANSICOES}:sem_humano_24h`], undefined);
  });
});

describe("a guarda pre-envio (criterio 2)", () => {
  it("em `bot` e sem actividade humana depois do turno, passa", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    const d = await avaliar({ comTenant: bd.comTenant(), metricas }, pedido());
    assert.equal(d.passa, true);
    assert.equal(d.motivo, null);
    assert.equal(bd.vistas.filter((v) => v.sql === SQL_SUPRIMIR_ENVIO).length, 0);
  });

  for (const modo of ["dono", "humano", "pausada"] as const) {
    it(`em \`${modo}\` descarta, com motivo \`modo\``, async () => {
      bd.semear(CONVERSA, { contact_id: CONTACTO, mode: modo, last_human_activity_at: null });
      const d = await avaliar({ comTenant: bd.comTenant(), metricas }, pedido());
      assert.equal(d.passa, false);
      assert.equal(d.motivo, "modo");
      assert.equal(d.suprimida, "sup-1");
    });
  }

  it("actividade humana depois do inicio do turno descarta, mesmo em `bot`", async () => {
    // É a corrida do §10.3: o turno começou em t0, o *echo* chegou em t0+1 s, a
    // resposta ficou pronta em t0+2 s.
    bd.semear(CONVERSA, {
      contact_id: CONTACTO,
      mode: "bot",
      last_human_activity_at: new Date(T0.getTime() + 1_000),
    });
    const d = await avaliar({ comTenant: bd.comTenant(), metricas }, pedido());
    assert.equal(d.passa, false);
    assert.equal(d.motivo, "actividade_humana");
    assert.equal(metricas.ler()[`${METRICA_SUPRIMIDAS}:actividade_humana`], 1);
  });

  it("actividade humana ANTERIOR ao turno deixa passar", async () => {
    // Uma conversa retomada do Chatwoot tem `last_human_activity_at` do momento
    // em que foi resolvida. Se o guarda a comparasse com «houve alguma», o bot
    // ficava calado para sempre nessa conversa.
    bd.semear(CONVERSA, {
      contact_id: CONTACTO,
      mode: "bot",
      last_human_activity_at: new Date(T0.getTime() - 1),
    });
    assert.equal((await avaliar({ comTenant: bd.comTenant(), metricas }, pedido())).passa, true);
  });

  it("no mesmo instante do inicio do turno deixa passar: e estritamente posterior", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: T0 });
    assert.equal((await avaliar({ comTenant: bd.comTenant(), metricas }, pedido())).passa, true);
  });

  it("um envio do bot sem o inicio do turno descarta, e conta-se como defeito", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    // O campo **não se passa a `undefined`**: com `exactOptionalPropertyTypes`
    // isso é um erro de tipos, e é o que se quer — o que se ensaia é um
    // `Pedido` em que a propriedade não existe, que é o caso real de um
    // chamador que não a liga.
    const { turnoIniciadoEm: _, ...semTurno } = pedido();
    const d = await avaliar({ comTenant: bd.comTenant(), metricas }, semTurno);
    assert.equal(d.passa, false);
    assert.equal(d.motivo, "sem_turno");
    assert.equal(metricas.ler()[`${METRICA_SUPRIMIDAS}:sem_turno`], 1);
  });

  it("um instante ilegivel suprime, e nao passa por causa de um NaN", async () => {
    // **Um fail-open de um caracter.** Um `new Date("lixo")` dá um `Date` cujo
    // `getTime()` é `NaN`, e **qualquer** comparação com `NaN` é falsa — um
    // `last_human_activity_at` que não se consiga ler deixava passar o envio em
    // vez de o suprimir. Não se adivinha um instante para deixar o assistente
    // falar.
    bd.semear(CONVERSA, {
      contact_id: CONTACTO,
      mode: "bot",
      last_human_activity_at: "nao-e-uma-data" as never,
    });
    const d = await avaliar({ comTenant: bd.comTenant(), metricas }, pedido());
    assert.equal(d.passa, false);
    assert.equal(d.motivo, "actividade_humana");

    // E um `Date` invalido — que e o que um `new Date(NaN)` produz — vale o
    // mesmo: a verificacao e do `getTime()` e nao do `instanceof`.
    bd.semear("outra", {
      contact_id: CONTACTO,
      mode: "bot",
      last_human_activity_at: new Date(Number.NaN),
    });
    const outra = await avaliar(
      { comTenant: bd.comTenant(), metricas },
      { ...pedido(), conversationId: "outra", idempotencyKey: "turno-nan" },
    );
    assert.equal(outra.passa, false);
    assert.equal(outra.motivo, "actividade_humana");
  });

  it("uma conversa que a RLS nao ve descarta em vez de rebentar, e sem escrever", async () => {
    // **E sem linha de supressao**: a `outbound_messages_conversation_fk` é
    // composta com o `tenant_id`, e um `INSERT` que aponte para uma conversa
    // que este tenant não tem morre com `23503`. Um `throw` no passo 3 de sete
    // do adapter deixava o turno sem resposta **e** sem registo.
    const d = await avaliar({ comTenant: bd.comTenant(), metricas }, pedido());
    assert.equal(d.passa, false);
    assert.equal(d.motivo, "modo");
    assert.equal(d.suprimida, null);
    assert.equal(bd.vistas.filter((v) => v.sql === SQL_SUPRIMIR_ENVIO).length, 0);
    // O contador conta: é onde isto fica visível.
    assert.equal(metricas.ler()[`${METRICA_SUPRIMIDAS}:modo`], 1);
  });

  it("a linha de supressao e escrita ANTES de o cancelamento ser devolvido", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    const guarda = criarGuarda({ comTenant: bd.comTenant(), metricas });
    assert.equal(await guarda(pedido()), false);
    // A ordem: *lock*, leitura, supressão. Nada depois.
    assert.deepEqual(bd.vistas.map((v) => v.sql), [
      SQL_TRANCAR_CONVERSA,
      SQL_CONVERSA_PARA_MODO,
      SQL_SUPRIMIR_ENVIO,
    ]);
  });

  it("a mesma chave suprimida duas vezes deixa uma linha", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    const deps = { comTenant: bd.comTenant(), metricas };
    const primeira = await avaliar(deps, pedido());
    const segunda = await avaliar(deps, pedido());
    assert.equal(primeira.suprimida, "sup-1");
    // `RETURNING` vazio: a chave já tinha linha. Continua a ser uma supressão.
    assert.equal(segunda.suprimida, null);
    assert.equal(segunda.passa, false);
    assert.equal(bd.suprimidas.size, 1);
    // A métrica conta as **duas**: foram dois envios descartados.
    assert.equal(metricas.ler()[`${METRICA_SUPRIMIDAS}:modo`], 2);
  });

  it("a supressao escreve o estado `suppressed_by_human`", () => {
    assert.match(SQL_SUPRIMIR_ENVIO, /'suppressed_by_human'/);
    assert.match(SQL_SUPRIMIR_ENVIO, /ON CONFLICT \(tenant_id, idempotency_key\) DO NOTHING/);
  });

  it("um corpo livre registra-se como `service` e um template como `utility`", () => {
    // A `outbound_messages_template_ck` exige o par: `service` sem template, o
    // resto com. Ver a nota de `registoDaSupressao`.
    assert.deepEqual(registoDaSupressao(pedido()), { kind: "service", templateName: null });
    assert.deepEqual(
      registoDaSupressao(
        pedido({ corpo: { tipo: "template", nome: "aviso", idioma: "pt_PT", parametros: [] } }),
      ),
      { kind: "utility", templateName: "aviso" },
    );
  });

  it("nada do interlocutor vai para o registo nem para as metricas", async () => {
    // O DoD «Privacidade»: sem conteúdo nem telefone. O que vai para a base
    // leva `contact_id` (é uma coluna, e é a referência opaca do KAM-008); o que
    // **não** pode levar é o texto da mensagem, e o `corpo` não entra em
    // consulta nenhuma.
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "humano", last_human_activity_at: null });
    await avaliar({ comTenant: bd.comTenant(), metricas }, pedido({ corpo: { tipo: "texto", texto: "CANARIO-999123456" } }));
    assert.ok(!bd.emTexto().includes("CANARIO-999123456"));
    assert.ok(!JSON.stringify(metricas.ler()).includes(CONTACTO));
    assert.ok(!JSON.stringify(metricas.ler()).includes(TENANT));
  });
});

describe("o evento `conversation.mode_changed` (criterio 6)", () => {
  it("os quatro modos cabem em tres valores, e `dono` e `humano` colapsam", () => {
    // **A perda é real e está declarada.** Um consumidor do barramento não
    // distingue o dono na app de um agente no Chatwoot.
    assert.deepEqual(payloadDoModo("t:c", "bot"), { thread_id: "t:c", channel_mode: "ai" });
    assert.deepEqual(payloadDoModo("t:c", "dono"), { thread_id: "t:c", channel_mode: "humano" });
    assert.deepEqual(payloadDoModo("t:c", "humano"), { thread_id: "t:c", channel_mode: "humano" });
    assert.deepEqual(payloadDoModo("t:c", "pausada"), {
      thread_id: "t:c",
      channel_mode: "desligado",
    });
  });

  it("o payload passa a validacao do contrato publicado", async () => {
    // O `validarPayload` corre **antes** do SQL (regra do KAM-007): se o
    // payload não bater, não há escrita nenhuma.
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    const r = await maquina().disparar({ tenantId: TENANT, conversationId: CONVERSA }, "opt_out");
    assert.equal(r.eventoId, "evt-1");
    const emitir = bd.vistas.find((v) => v.sql === SQL_EMITIR_MODE_CHANGED);
    assert.equal(emitir?.parametros[0], "conversation.mode_changed");
    assert.equal(emitir?.parametros[1], 2);
    assert.equal(emitir?.parametros[3], "conversa");
    assert.equal(emitir?.parametros[4], CONVERSA);
    assert.equal(
      emitir?.parametros[5],
      JSON.stringify({ thread_id: `${TENANT}:${CONTACTO}`, channel_mode: "desligado" }),
    );
  });

  it("o payload que se monta e exactamente o que o contrato exige, nos dois sentidos", async () => {
    // **Esta e a proteccao real da validacao**, e a prova por mutacao mostrou
    // porque: apagar o `validarPayload` do `emitirModoMudado` nao faz nenhum
    // teste falhar, porque o `payloadDoModo` e tipado e nao consegue produzir um
    // payload invalido **hoje**. O que a validacao protege e o **amanha** — uma
    // divergencia entre o que montamos e o que o contrato publicado exige —, e
    // isso mede-se comparando as duas listas, nos dois sentidos, como o
    // `chr/invocacao.ts` ja faz para o `agent_invocation`.
    const { CATALOGO } = await import("@kamba/contracts");
    const entrada = (CATALOGO as Record<string, {
      versoes: readonly number[];
      obrigatorios: readonly string[];
      permitidos: readonly string[];
    }>)["conversation.mode_changed"];
    assert.ok(entrada !== undefined, "o tipo saiu do catalogo");
    assert.ok(entrada.versoes.includes(2), "a v2 saiu do catalogo");
    const montado = Object.keys(payloadDoModo("t:c", "bot")).sort();
    assert.deepEqual(montado, [...entrada.obrigatorios].sort(), "falta um campo obrigatorio");
    assert.deepEqual(montado, [...entrada.permitidos].sort(), "monta-se um campo a mais");
  });

  it("a emissao corre na mesma transaccao da escrita", async () => {
    bd.semear(CONVERSA, { contact_id: CONTACTO, mode: "bot", last_human_activity_at: null });
    await maquina().disparar({ tenantId: TENANT, conversationId: CONVERSA }, "opt_out");
    // Uma transacção só, e o `evt_emitir` depois do `UPDATE`: as duas escritas
    // confirmam juntas ou não confirma nenhuma.
    assert.equal(bd.transaccoes, 1);
    const ordem = bd.vistas.map((v) => v.sql);
    assert.ok(ordem.indexOf(SQL_MUDAR_MODO) < ordem.indexOf(SQL_EMITIR_MODE_CHANGED));
  });
});
