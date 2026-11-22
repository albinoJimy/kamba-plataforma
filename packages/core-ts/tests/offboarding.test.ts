/**
 * O off-boarding sem base (KAM-098): o calendário D0–D30, as duas
 * confirmações, e o canal e a revogação sobre uma base falsa que responde pelo
 * **texto** de cada instrução (a lição do KAM-070). O que só a base prova está
 * em `tests_bd/offboarding.bd.test.ts`.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AVISO_DA_APP_BUSINESS,
  ConfirmacaoIncompletaError,
  DIA_DA_FASE,
  FASES,
  FaseForaDeOrdemError,
  PedidoError,
  SQL_CANAIS_LIGADOS,
  SQL_DESLIGAR_CANAL,
  SQL_DESLIGAR_ENTITLEMENTS,
  SQL_EMITIR,
  SQL_ENCERRAR_CANAIS,
  SQL_ESTADO_DO_TENANT,
  SQL_FASES,
  SQL_MARCAR_FASE,
  SQL_PENDENTES,
  SQL_RECURSOS_DA_SAGA,
  SQL_SANCAO_DE_ENCERRAMENTO,
  SQL_TRANSITAR,
  abrirPedido,
  cancelavel,
  desligarCanal,
  podeComecar,
  PASSOS_DA_REVOGACAO,
  prazos,
  revogar,
  type CanalDaMeta,
  type ClienteSql,
  type PortasDaRevogacao,
} from "../src/offboarding/index.ts";

const MS = 86_400_000;
const D0 = new Date("2026-10-01T09:00:00Z");
const dia = (n: number) => new Date(D0.getTime() + n * MS);
const T = "11111111-1111-4111-8111-111111111111";

describe("o calendário D0–D30 (proposta)", () => {
  it("cada fase tem o seu prazo, contado do pedido", () => {
    const p = prazos(D0);
    assert.deepEqual(Object.keys(p), [...FASES]);
    assert.equal(p.canal.getTime(), dia(1).getTime());
    assert.equal(p.exportacao.getTime(), dia(7).getTime());
    assert.equal(p.purga.getTime(), dia(30).getTime());
    assert.equal(DIA_DA_FASE.certificado, 30);
  });

  it("o pedido cancela-se até ao D7 exclusive, e a revogação só começa no D7", () => {
    assert.equal(cancelavel(D0, dia(6.99)), true);
    assert.equal(cancelavel(D0, dia(7)), false);
    assert.equal(podeComecar("revogacao", D0, dia(6.99)), false);
    assert.equal(podeComecar("revogacao", D0, dia(7)), true);
    assert.equal(podeComecar("canal", D0, D0), true);
    assert.equal(podeComecar("purga", D0, dia(29)), false);
  });

  it("o aviso não tem dígitos nem nomes: o mesmo texto para todos", () => {
    assert.doesNotMatch(AVISO_DA_APP_BUSINESS.replace("7 dias", ""), /\d/);
    assert.match(AVISO_DA_APP_BUSINESS, /WhatsApp Business volta a funcionar normalmente/);
  });
});

/** Uma base falsa: as fases e os canais em memória, pelo texto de cada instrução. */
class BaseFalsa implements ClienteSql {
  readonly fases = new Map<string, { estado: string; prazo_at: Date; resultado: Record<string, unknown> }>();
  readonly canais = [{ id: "c1", waba_id: "waba-1", estado: "ativo" }];
  readonly instrucoes: string[] = [];
  estadoDoTenant = "ativo";
  eventos = 0;
  pendentes = { encomendas: 0, disputas: 0, reservas: 0, reembolsos: 0 };
  sancoes = new Set<string>();
  recursosDaSaga: { step: string; external_id: string }[] = [{ step: "chave_llm", external_id: "llm-1" }];
  /** Chamado quando a Meta é tocada: o ensaio da corrida cancela aqui. */
  aoTocarNaMeta: () => void = () => {};

  constructor(estados: Record<string, string> = {}) {
    for (const f of FASES) {
      this.fases.set(f, {
        estado: f === "verificacao" ? "concluida" : (estados[f] ?? "pendente"),
        prazo_at: prazos(D0)[f],
        resultado: f === "verificacao" ? { origem: "titular" } : {},
      });
    }
  }

  async query(sql: string, p: readonly unknown[] = []) {
    this.instrucoes.push(sql);
    if (sql === SQL_FASES) {
      return { rows: [...this.fases].map(([fase, l]) => ({ fase, ...l })) };
    }
    if (sql === SQL_MARCAR_FASE) {
      const l = this.fases.get(String(p[1]))!;
      this.fases.set(String(p[1]), { ...l, estado: String(p[2]), resultado: JSON.parse(String(p[3])) });
      return { rows: [], rowCount: 1 };
    }
    if (sql === SQL_CANAIS_LIGADOS) return { rows: this.canais.filter((c) => c.estado === "ativo").map((c) => ({ ...c })) };
    if (sql === SQL_DESLIGAR_CANAL) {
      const c = this.canais.find((x) => x.id === p[0] && x.estado === p[2]);
      if (c) c.estado = "desligado";
      return { rows: [], rowCount: c ? 1 : 0 };
    }
    if (sql === SQL_PENDENTES) return { rows: [{ ...this.pendentes }] };
    if (sql === SQL_RECURSOS_DA_SAGA) return { rows: this.recursosDaSaga.map((r) => ({ ...r })) };
    if (sql === SQL_ESTADO_DO_TENANT) return { rows: [{ estado: this.estadoDoTenant }] };
    if (sql === SQL_SANCAO_DE_ENCERRAMENTO) return { rows: this.sancoes.has(String(p[0])) ? [{ "?column?": 1 }] : [] };
    if (sql === SQL_TRANSITAR) {
      const mudou = this.estadoDoTenant !== "encerrado";
      this.estadoDoTenant = "encerrado";
      return { rows: [{ mudou }] };
    }
    if (sql === SQL_EMITIR) {
      this.eventos += 1;
      return { rows: [{ event_id: "e" }] };
    }
    if (sql === SQL_DESLIGAR_ENTITLEMENTS || sql === SQL_ENCERRAR_CANAIS) return { rows: [], rowCount: 1 };
    return { rows: [], rowCount: 0 };
  }
}

/** As portas da revogação, a registar cada chamada com o argumento. */
function portasEspias(
  chamadas: string[],
  o: { readonly chave?: "revogada" | "inexistente"; readonly conta?: "arquivada" | "inexistente" | "sem_conta" } = {},
) {
  return {
    chaveDeLlm: {
      revogar: async (id: string) => void chamadas.push(`revogar:${id}`),
      revogarDoTenant: async (t: string) => {
        chamadas.push(`alias:${t}`);
        return o.chave ?? "revogada";
      },
    },
    canalDeComercio: { arquivar: async (id: string) => void chamadas.push(`arquivar:${id}`) },
    inbox: { desligar: async (id: string) => void chamadas.push(`desligar:${id}`) },
    contaDeAtendimento: {
      archiveAccount: async (t: string) => {
        chamadas.push(`arquivar-conta:${t}`);
        return o.conta ?? "arquivada";
      },
    },
    sessoesDoPainel: {
      revogarDoTenant: async (t: string, ate: number) => void chamadas.push(`painel:${t}:${ate}`),
    },
  } satisfies PortasDaRevogacao;
}

function metaEspia() {
  const chamadas: string[] = [];
  const canal: CanalDaMeta = {
    numeroDoTenant: async () => null,
    subscreverWebhooks: async (w) => void chamadas.push(`subscrever:${w}`),
    cancelarSubscricao: async (w) => void chamadas.push(`cancelar:${w}`),
    removerRota: async (p) => void chamadas.push(`remover_rota:${p}`),
    apagarWaba: async (w) => void chamadas.push(`APAGAR_WABA:${w}`),
    apagarNumero: async (p) => void chamadas.push(`APAGAR_NUMERO:${p}`),
  };
  return { canal, chamadas };
}

describe("o pedido, o canal e a revogação sobre a base falsa", () => {
  it("sem as duas provas, o pedido é recusado antes de tocar na base", async () => {
    const bd = new BaseFalsa();
    const provas = { otpConfere: async () => true, ligacaoDoEmailConfere: async () => false };
    await assert.rejects(
      abrirPedido(bd, { tenantId: T, origem: "titular", otp: "1", tokenDoEmail: "x", agora: D0 }, provas),
      ConfirmacaoIncompletaError,
    );
    assert.deepEqual(bd.instrucoes, []);
    // Sem a porta, também não: as provas verifica-as o processo, não o pedido.
    await assert.rejects(
      abrirPedido(bd, { tenantId: T, origem: "titular", otp: "1", tokenDoEmail: "x", agora: D0 }),
      ConfirmacaoIncompletaError,
    );
  });

  it("o canal cancela a subscrição pelo guarda, e nunca chama o que apaga", async () => {
    const bd = new BaseFalsa();
    const meta = metaEspia();
    assert.equal((await desligarCanal(bd, { tenantId: T, canal: meta.canal, agora: D0 })).desligados, 1);
    assert.deepEqual(meta.chamadas, ["cancelar:waba-1"]);
    assert.equal(bd.fases.get("canal")?.estado, "concluida");
    assert.deepEqual(bd.fases.get("canal")?.resultado.canais, [{ id: "c1", waba_id: "waba-1", de: "ativo" }]);
  });

  it("os pendentes: uma reserva ativa deixa a fase em curso; a disputa não impede e fica escrita", async () => {
    const { verificarPendentes } = await import("../src/offboarding/index.ts");
    const bd = new BaseFalsa();
    bd.pendentes = { encomendas: 0, disputas: 0, reservas: 1, reembolsos: 0 };
    assert.equal((await verificarPendentes(bd, { tenantId: T, agora: dia(1) })).concluida, false);
    assert.equal(bd.fases.get("pendentes")?.estado, "em_curso");
    assert.equal(bd.fases.get("pendentes")?.resultado.reservas, 1);
    bd.pendentes = { encomendas: 0, disputas: 2, reservas: 0, reembolsos: 0 };
    assert.equal((await verificarPendentes(bd, { tenantId: T, agora: dia(2) })).concluida, true);
    assert.equal(bd.fases.get("pendentes")?.resultado.disputa, true);
  });

  it("um pedido cancelado não corre fase nenhuma", async () => {
    const bd = new BaseFalsa();
    bd.fases.get("verificacao")!.resultado = { origem: "titular", cancelado_at: "x" };
    await assert.rejects(desligarCanal(bd, { tenantId: T, canal: metaEspia().canal, agora: D0 }), FaseForaDeOrdemError);
  });

  it("a revogação corre os passos uma vez, encerra com um evento, e o recurso sem saga é sem_recurso", async () => {
    const bd = new BaseFalsa({ exportacao: "concluida", canal: "concluida" });
    const chamadas: string[] = [];
    const portas = portasEspias(chamadas);
    const r = await revogar(bd, { tenantId: T, portas, agora: dia(7) });
    assert.equal(r.encerrado, true);
    // A chave da saga pelo token dela, e nunca também pelo alias; a conta e o
    // painel sem saga; o canal e a inbox sem registo não chegam à porta.
    assert.deepEqual(chamadas, [
      "revogar:llm-1",
      `arquivar-conta:${T}`,
      `painel:${T}:${Math.floor(dia(7).getTime() / 1000)}`,
    ]);
    assert.deepEqual(r.passos, {
      chave_llm: "concluido",
      canal_comercio: "sem_recurso",
      inbox: "sem_recurso",
      conta_atendimento: "concluido",
      entitlements: "concluido",
      canais: "concluido",
      sessoes_do_painel: "concluido",
      encerramento: "concluido",
    });
    assert.deepEqual(Object.keys(r.passos), [...PASSOS_DA_REVOGACAO]);
    assert.equal(bd.eventos, 1);
    const outra = await revogar(bd, { tenantId: T, portas, agora: dia(8) });
    assert.equal(outra.encerrado, false);
    assert.equal(bd.eventos, 1);
    assert.equal(chamadas.length, 3);
  });

  it("sem a chave na saga, revoga pelo alias; já não estar lá é inexistente, e a conta que falta é sem_recurso", async () => {
    const bd = new BaseFalsa({ exportacao: "concluida", canal: "concluida" });
    bd.recursosDaSaga = [];
    const chamadas: string[] = [];
    const portas = portasEspias(chamadas, { chave: "inexistente", conta: "sem_conta" });
    const r = await revogar(bd, { tenantId: T, portas, agora: dia(7) });
    assert.equal(chamadas[0], `alias:${T}`);
    assert.ok(!chamadas.some((c) => c.startsWith("revogar:")));
    assert.equal(r.passos.chave_llm, "inexistente");
    assert.equal(r.passos.conta_atendimento, "sem_recurso");
    const outraBd = new BaseFalsa({ exportacao: "concluida", canal: "concluida" });
    outraBd.recursosDaSaga = [];
    const r2 = await revogar(outraBd, { tenantId: T, portas: portasEspias([], { chave: "revogada", conta: "inexistente" }), agora: dia(7) });
    assert.equal(r2.passos.chave_llm, "concluido");
    assert.equal(r2.passos.conta_atendimento, "inexistente");
  });

  it("uma porta que falha pára a fase nesse passo, sem encerrar, e retoma nele", async () => {
    const bd = new BaseFalsa({ exportacao: "concluida", canal: "concluida" });
    bd.recursosDaSaga = [];
    const chamadas: string[] = [];
    const portas = portasEspias(chamadas);
    let falhar = true;
    const alias = portas.chaveDeLlm.revogarDoTenant;
    portas.chaveDeLlm.revogarDoTenant = async (t: string) => {
      if (falhar) throw new Error("DB not connected");
      return alias(t);
    };
    await assert.rejects(revogar(bd, { tenantId: T, portas, agora: dia(7) }), /DB not connected/);
    assert.equal(bd.eventos, 0);
    assert.equal(bd.estadoDoTenant, "ativo");
    assert.deepEqual(chamadas, [], "nenhum passo depois da chave correu");
    falhar = false;
    const r = await revogar(bd, { tenantId: T, portas, agora: dia(8) });
    assert.equal(r.encerrado, true);
    assert.equal(chamadas[0], `alias:${T}`);
  });

  it("a revogação recusa antes do D7 e sem exportação", async () => {
    const portas = portasEspias([]);
    await assert.rejects(revogar(new BaseFalsa({ exportacao: "concluida", canal: "concluida" }), { tenantId: T, portas, agora: dia(6) }), FaseForaDeOrdemError);
    await assert.rejects(revogar(new BaseFalsa({ canal: "concluida" }), { tenantId: T, portas, agora: dia(7) }), FaseForaDeOrdemError);
    // Sem o canal desligado (achado 2 da revisão adversarial).
    await assert.rejects(revogar(new BaseFalsa({ exportacao: "concluida" }), { tenantId: T, portas, agora: dia(7) }), /canal/);
    // Um tenant restrito não se encerra, e recusa-se antes de qualquer porta (achado 3).
    const restrito = new BaseFalsa({ exportacao: "concluida", canal: "concluida" });
    restrito.estadoDoTenant = "restrito";
    const tocadas: string[] = [];
    await assert.rejects(revogar(restrito, { tenantId: T, portas: portasEspias(tocadas), agora: dia(7) }), /restrito/);
    assert.deepEqual(tocadas, []);
  });

  it("um cancelamento que ganha a corrida depois da Meta desfaz a dessubscrição (achado 5)", async () => {
    const bd = new BaseFalsa();
    const meta = metaEspia();
    const cancelar = meta.canal.cancelarSubscricao;
    meta.canal.cancelarSubscricao = async (w) => {
      await cancelar(w);
      // O titular cancela entre a Meta e a escrita.
      bd.fases.get("verificacao")!.resultado = { origem: "titular", cancelado_at: "x" };
    };
    await assert.rejects(desligarCanal(bd, { tenantId: T, canal: meta.canal, agora: D0 }), FaseForaDeOrdemError);
    assert.deepEqual(meta.chamadas, ["cancelar:waba-1", "subscrever:waba-1"]);
    assert.equal(bd.canais[0]?.estado, "ativo", "o canal não ficou desligado");
  });

  it("T&S precisa de uma sanção de encerramento em vigor, com o tenant suspenso", async () => {
    const bd = new BaseFalsa();
    bd.fases.clear();
    bd.estadoDoTenant = "suspenso";
    const sancao = "22222222-2222-4222-8222-222222222222";
    await assert.rejects(
      abrirPedido(bd, { tenantId: T, origem: "trust_safety", decisaoRef: "texto", agora: D0 }),
      ConfirmacaoIncompletaError,
    );
    await assert.rejects(
      abrirPedido(bd, { tenantId: T, origem: "trust_safety", decisaoRef: sancao, agora: D0 }),
      /sancao_de_encerramento/,
    );
    bd.sancoes.add(sancao);
    assert.equal((await abrirPedido(bd, { tenantId: T, origem: "trust_safety", decisaoRef: sancao, agora: D0 })).aberto, true);
  });

  it("um pedido que não existe não se cancela nem revoga", async () => {
    const bd = new BaseFalsa();
    bd.fases.clear();
    const { cancelarPedido } = await import("../src/offboarding/index.ts");
    await assert.rejects(cancelarPedido(bd, { tenantId: T, canal: metaEspia().canal, agora: D0 }), PedidoError);
  });
});
