/**
 * A régua de cobrança (KAM-058): o que se mede sem PostgreSQL.
 *
 * A unicidade, a porta de transição do KAM-092, o evento na mesma transacção e
 * o CHR a ler o estado novo medem-se contra a base em
 * `db/tests_pagamentos/test_regua_de_cobranca.py`, com as cadeias SQL deste
 * módulo. Aqui mede-se o calendário com o relógio injectado, a configuração
 * versionada, o *template*, o canal, e a **ordem** e a atomicidade do motor
 * contra uma base falsa que guarda estado e reverte no `ROLLBACK`.
 *
 * A base falsa responde às cadeias **pela identidade**: uma instrução que o
 * motor mande e que ela não conheça levanta, para que um SQL novo não passe
 * aqui sem ninguém lhe dar semântica.
 */

import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";
import { describe, it } from "node:test";

import type { ClienteSql } from "../src/eventos/publicador.ts";
import {
  AVISO_ANTI_PHISHING,
  COMISSAO_SEM_PARECER,
  CanalD10Fechado,
  ConfiguracaoDaReguaInvalida,
  FLAGS_OMISSAO,
  COMISSAO_OMISSAO,
  ENTIDADES_DA_KAMBA,
  INTERVALO_DA_REGUA_MS,
  LIMIAR_DE_SUSPENSOES_POR_DIA,
  METRICA_PASSOS,
  METRICA_SUSPENSOES,
  MOTIVO_DA_SUSPENSAO,
  MOTIVO_NO_EVENTO,
  PASSOS_DA_REGUA,
  ProcessoDaCobranca,
  REFERENCIA_EXPIRADA,
  RegistoDeProviders,
  SEM_REFERENCIA,
  SQL_BILLING_CONTEXTO,
  SQL_BILLING_SUBSCRICOES,
  SQL_REGUA_AUDITAR,
  SQL_REGUA_CICLOS,
  SQL_REGUA_COBRANCA,
  SQL_REGUA_DE_ONDE_VEIO,
  SQL_REGUA_EMITIR,
  SQL_REGUA_ESTADO_DO_CICLO,
  SQL_REGUA_EM_ATRASO,
  SQL_REGUA_ESTADO_DO_TENANT,
  SQL_REGUA_GRAVAR_PASSO,
  SQL_REGUA_LISTA_DE_OPS,
  SQL_REGUA_PASSO_GRAVADO,
  SQL_REGUA_POR_REPOR,
  SQL_REGUA_SUBSCRICAO_REPOSTA,
  SQL_REGUA_SUBSCRICOES_EM_DIA,
  SQL_REGUA_SUSPENSA,
  SQL_REGUA_SUSPENSOES_NO_DIA,
  SQL_REGUA_TRANCAR,
  SQL_REGUA_TRANSITAR,
  VERSOES_DA_REGUA,
  type CobrancaDoCiclo,
  type NotificadorDaRegua,
  type PedidoDaRegua,
  type VersaoDaRegua,
  accoesDoCiclo,
  agendar,
  dataEmLuanda,
  diasDeAvisoPrevio,
  camposDaCobranca,
  correrRegua,
  diasEntre,
  emissorManual,
  listaDeOps,
  mensagemDoPasso,
  notificadorDeOps,
  notificadorPeloDono,
  numerosForaDosCampos,
  validarVersoes,
  versaoDoCiclo,
} from "../src/pagamentos/index.ts";
import { tenantGate } from "../src/ten/estados.ts";
import { capturar, capturarAsync } from "./apoio/capturar.ts";

type Linha = Record<string, unknown>;
type Resposta = { rows: Linha[]; rowCount: number | null };

const TENANT = "11111111-1111-4111-8111-111111111111";
const SUBSCRICAO = "22222222-2222-4222-8222-222222222222";
const CICLO = "33333333-3333-4333-8333-333333333333";
/** O dia 0 do ciclo de ensaio. Um relógio injectado, e nunca o `now()`. */
const INICIO = "2026-12-01";

/**
 * As oito arestas da `0058`, **para a base falsa** responder como o
 * `transition_tenant`. Não é o grafo do motor — o motor não tem grafo: pede
 * `suspenso` e `ativo`, e quem decide é a função da base, medida contra o
 * PostgreSQL na suite Python.
 */
const ARESTAS = new Set([
  "onboarding>ativo",
  "ativo>restrito",
  "restrito>ativo",
  "ativo>suspenso",
  "restrito>suspenso",
  "suspenso>ativo",
  "ativo>encerrado",
  "suspenso>encerrado",
]);

type Estado = {
  ciclos: { id: string; tenantId: string; subscriptionId: string; estado: string; inicio: string }[];
  cobrancas: { cicloId: string; metodo: string; referencia: string | null; valor: string; validaAte: Date }[];
  passos: {
    tenantId: string;
    cicloId: string;
    passo: string;
    executadoAt: string;
    resultado: string;
    canal: string | null;
    versao: string;
  }[];
  tenants: Record<string, string>;
  subscricoes: Record<string, { tenantId: string; estado: string }>;
  registo: { tenantId: string; de: string; para: string; motivo: string; seq?: number }[];
  eventos: { tipo: string; tenantId: string; payload: unknown }[];
  auditoria: { tenantId: string; actor: string; resumo: string }[];
  /** As sancoes de T&S (KAM-097), com o `seq` que as ordena contra o registo. */
  sancoes: { tenantId: string; passo: string; seq: number; recursoProvido: boolean }[];
  seq: number;
};

/** Uma base que guarda estado, com transacções, e responde às cadeias da régua. */
class BaseDaRegua implements ClienteSql {
  e: Estado = {
    ciclos: [],
    cobrancas: [],
    passos: [],
    tenants: {},
    subscricoes: {},
    registo: [],
    eventos: [],
    auditoria: [],
    sancoes: [],
    seq: 0,
  };
  #copia: Estado | null = null;
  readonly chamadas: string[] = [];
  /** Uma instrução que levanta uma vez — o *crash* a meio de um passo. */
  falharUmaVezEm: string | null = null;
  /**
   * Corre uma vez depois da instrução: o que **outra** transacção confirmou
   * entretanto. Aplica-se também à cópia do `BEGIN`, porque o `ROLLBACK` desta
   * transacção não desfaz o que a outra fez.
   */
  depoisDe = new Map<string, (e: Estado) => void>();

  /** Uma sancao de T&S, que o Trust escreve sem passar pelo registo de estados. */
  sancionar(passo: string, tenant: string = TENANT): void {
    this.e.seq += 1;
    this.e.sancoes.push({ tenantId: tenant, passo, seq: this.e.seq, recursoProvido: false });
  }

  semear(opcoes: { estado?: string; tenant?: string; ciclo?: string; subscricao?: string; inicio?: string } = {}): void {
    const tenant = opcoes.tenant ?? TENANT;
    const ciclo = opcoes.ciclo ?? CICLO;
    const subscricao = opcoes.subscricao ?? SUBSCRICAO;
    this.e.tenants[tenant] = opcoes.estado ?? "ativo";
    this.e.subscricoes[subscricao] = { tenantId: tenant, estado: "ativa" };
    this.e.ciclos.push({
      id: ciclo,
      tenantId: tenant,
      subscriptionId: subscricao,
      estado: "cobranca_emitida",
      inicio: opcoes.inicio ?? INICIO,
    });
    this.e.cobrancas.push({
      cicloId: ciclo,
      metodo: "referencia",
      referencia: "987654321",
      valor: "1500000",
      validaAte: new Date(Date.parse(`${opcoes.inicio ?? INICIO}T00:00:00Z`) + 72 * 3_600_000),
    });
  }

  pagar(ciclo: string = CICLO): void {
    const c = this.e.ciclos.find((x) => x.id === ciclo);
    if (c === undefined) throw new Error("ciclo inexistente");
    c.estado = "paga";
  }

  async query(sql: string, p: readonly unknown[] = []): Promise<Resposta> {
    const resposta = await this.#responder(sql, p);
    const depois = this.depoisDe.get(sql);
    if (depois !== undefined) {
      this.depoisDe.delete(sql);
      depois(this.e);
      if (this.#copia !== null) depois(this.#copia);
    }
    return resposta;
  }

  async #responder(sql: string, p: readonly unknown[]): Promise<Resposta> {
    this.chamadas.push(sql);
    if (this.falharUmaVezEm === sql) {
      this.falharUmaVezEm = null;
      throw new Error("falha a meio do passo");
    }
    const r = (rows: Linha[]): Resposta => ({ rows, rowCount: rows.length });
    const e = this.e;
    switch (sql) {
      case "BEGIN":
        this.#copia = structuredClone(e);
        return r([]);
      case "COMMIT":
        this.#copia = null;
        return r([]);
      case "ROLLBACK":
        if (this.#copia !== null) this.e = this.#copia;
        this.#copia = null;
        return r([]);
      case SQL_BILLING_CONTEXTO:
      case SQL_REGUA_TRANCAR:
        return r([]);
      case SQL_REGUA_CICLOS: {
        const todos = p[0] as string[];
        return r(
          e.ciclos
            .map((c) => ({ c, passos: e.passos.filter((x) => x.cicloId === c.id).map((x) => x.passo) }))
            .filter(({ c, passos }) =>
              ["cobranca_emitida", "em_atraso"].includes(c.estado) ||
              (["paga", "anulado"].includes(c.estado) && passos.length > 0 && !todos.every((t) => passos.includes(t))),
            )
            .map(({ c, passos }) => {
              const aviso = e.passos.find(
                (x) => x.cicloId === c.id && x.passo === "aviso" && x.resultado === "notificado",
              );
              return {
                id: c.id,
                tenant_id: c.tenantId,
                subscription_id: c.subscriptionId,
                estado: c.estado,
                inicio: c.inicio,
                aviso_em: aviso === undefined ? null : dataEmLuanda(new Date(aviso.executadoAt)),
                passos,
              };
            }),
        );
      }
      case SQL_REGUA_ESTADO_DO_CICLO:
        return r(e.ciclos.filter((c) => c.id === p[0]).map((c) => ({ estado: c.estado })));
      case SQL_REGUA_DE_ONDE_VEIO:
        return r(e.registo.filter((l) => l.tenantId === p[0]).slice(-1).map((l) => ({ de: l.de })));
      case SQL_REGUA_PASSO_GRAVADO:
        return r(e.passos.filter((x) => x.cicloId === p[0] && x.passo === p[1]).map(() => ({ existe: 1 })));
      case SQL_REGUA_COBRANCA:
        return r(
          e.cobrancas
            .filter((x) => x.cicloId === p[0])
            .slice(-1)
            .map((x) => ({
              metodo: x.metodo,
              referencia: x.referencia,
              amount_minor: x.valor,
              currency: "AOA",
              valid_until: x.validaAte,
            })),
        );
      case SQL_REGUA_EM_ATRASO: {
        const s = e.subscricoes[p[0] as string];
        if (s !== undefined && s.estado === "ativa") s.estado = "em_atraso";
        return r([]);
      }
      case SQL_REGUA_ESTADO_DO_TENANT:
        return r([{ estado: e.tenants[p[0] as string] }]);
      case SQL_REGUA_TRANSITAR: {
        const [tenant, para, motivo] = p as [string, string, string];
        const de = e.tenants[tenant] ?? "";
        if (de === para) return r([{ mudou: false }]);
        if (!ARESTAS.has(`${de}>${para}`)) throw new Error(`23514 ${de} -> ${para}`);
        e.tenants[tenant] = para;
        e.seq += 1;
        e.registo.push({ tenantId: tenant, de, para, motivo, seq: e.seq });
        return r([{ mudou: true }]);
      }
      case SQL_REGUA_AUDITAR:
        e.auditoria.push({ tenantId: p[0] as string, actor: p[1] as string, resumo: p[2] as string });
        return r([{ audit_append: null }]);
      case SQL_REGUA_EMITIR:
        e.eventos.push({ tipo: p[0] as string, tenantId: p[2] as string, payload: JSON.parse(p[5] as string) });
        return r([{ event_id: "e" }]);
      case SQL_REGUA_SUSPENSA: {
        const s = e.subscricoes[p[0] as string];
        if (s !== undefined && ["ativa", "em_atraso"].includes(s.estado)) s.estado = "suspensa";
        return r([]);
      }
      case SQL_REGUA_GRAVAR_PASSO: {
        const [tenantId, cicloId, passo, executadoAt, resultado, canal, versao] = p as string[];
        if (e.passos.some((x) => x.cicloId === cicloId && x.passo === passo)) return r([]);
        e.passos.push({
          tenantId: tenantId ?? "",
          cicloId: cicloId ?? "",
          passo: passo ?? "",
          executadoAt: executadoAt ?? "",
          resultado: resultado ?? "",
          canal: (canal as string | null) ?? null,
          versao: versao ?? "",
        });
        return r([{ id: "p" }]);
      }
      case SQL_REGUA_POR_REPOR: {
        const [motivo, so] = p as [string, string | null];
        return r(
          Object.entries(e.tenants)
            .filter(([id, estado]) => {
              if (estado !== "suspenso" || (so !== null && so !== id)) return false;
              const doTenant = e.registo.filter((l) => l.tenantId === id);
              const ultima = doTenant.at(-1);
              const ultimaSuspensao = doTenant.filter((l) => l.para === "suspenso").at(-1);
              if (ultima?.para !== "suspenso" || ultimaSuspensao?.motivo !== motivo) return false;
              const sancionado = e.sancoes.some(
                (x) =>
                  x.tenantId === id &&
                  ["suspensao", "encerramento"].includes(x.passo) &&
                  !x.recursoProvido &&
                  x.seq >= (ultimaSuspensao.seq ?? 0),
              );
              if (sancionado) return false;
              return !e.ciclos.some(
                (c) =>
                  c.tenantId === id &&
                  ["cobranca_emitida", "em_atraso"].includes(c.estado) &&
                  e.passos.some((x) => x.cicloId === c.id && x.passo === "suspensao"),
              );
            })
            .map(([id]) => ({ tenant_id: id })),
        );
      }
      case SQL_REGUA_SUBSCRICAO_REPOSTA:
        for (const s of Object.values(e.subscricoes)) {
          if (s.tenantId === p[0] && ["em_atraso", "suspensa"].includes(s.estado)) s.estado = "ativa";
        }
        return r([]);
      case SQL_REGUA_SUBSCRICOES_EM_DIA: {
        const mudadas: Linha[] = [];
        for (const [id, s] of Object.entries(e.subscricoes)) {
          const deve = e.ciclos.some(
            (c) =>
              c.subscriptionId === id &&
              ["cobranca_emitida", "em_atraso"].includes(c.estado) &&
              e.passos.some((x) => x.cicloId === c.id),
          );
          if (s.estado === "em_atraso" && !deve) {
            s.estado = "ativa";
            mudadas.push({ id });
          }
        }
        return r(mudadas);
      }
      case SQL_REGUA_SUSPENSOES_NO_DIA:
        return r([
          {
            n: e.passos.filter(
              (x) =>
                x.passo === "suspensao" &&
                x.resultado === "suspenso" &&
                x.executadoAt >= (p[0] as string) &&
                x.executadoAt < (p[1] as string),
            ).length,
          },
        ]);
      case SQL_REGUA_LISTA_DE_OPS:
        return r(
          e.passos
            .filter((x) => x.canal === "ops" && x.executadoAt >= (p[0] as string) && x.executadoAt < (p[1] as string))
            .map((x) => {
              const c = e.ciclos.find((y) => y.id === x.cicloId);
              const cob = e.cobrancas.filter((y) => y.cicloId === x.cicloId).at(-1);
              return {
                tenant_id: x.tenantId,
                billing_cycle_id: x.cicloId,
                passo: x.passo,
                config_versao: x.versao,
                inicio: c?.inicio,
                metodo: cob?.metodo,
                referencia: cob?.referencia,
                amount_minor: cob?.valor,
                currency: "AOA",
                valid_until: cob?.validaAte.toISOString(),
              };
            }),
        );
      default:
        throw new Error(`a base falsa nao conhece esta instrucao: ${sql.slice(0, 80)}`);
    }
  }
}

/** 10:00 em Luanda (09:00 UTC) do dia `d` do ciclo. */
function diaDoCiclo(d: number, inicio: string = INICIO): Date {
  return new Date(Date.parse(`${inicio}T09:00:00Z`) + d * 86_400_000);
}

const V1 = VERSOES_DA_REGUA[0] as VersaoDaRegua;

describe("régua: configuração versionada (critério 4)", () => {
  it("os dias propostos são 3, 7 e 10, e a versão carrega-se sem erro", () => {
    assert.deepEqual(V1.dias, { lembrete: 3, aviso: 7, suspensao: 10 });
    validarVersoes(VERSOES_DA_REGUA);
  });

  it("recusa versões sem ordem, repetidas, com dígitos ou com campos desconhecidos", () => {
    const outra = (m: Partial<VersaoDaRegua>): VersaoDaRegua => ({ ...V1, ...m });
    const casos: [string, readonly VersaoDaRegua[]][] = [
      ["vazia", []],
      ["repetida", [V1, outra({ validaDe: "2027-01-01" })]],
      ["fora de ordem", [V1, outra({ versao: "b", validaDe: "2026-01-01" })]],
      ["data", [outra({ validaDe: "16/11/2026" })]],
      ["dias", [outra({ dias: { lembrete: 3, aviso: 3, suspensao: 10 } })]],
      ["dia zero", [outra({ dias: { lembrete: 0, aviso: 7, suspensao: 10 } })]],
      ["digito", [outra({ textos: { ...V1.textos, aviso: "pague 5000 Kz até {prazo}" } })]],
      ["campo", [outra({ textos: { ...V1.textos, lembrete: "{telefone}" } })]],
    ];
    for (const [nome, versoes] of casos) {
      assert.throws(() => validarVersoes(versoes), ConfiguracaoDaReguaInvalida, nome);
    }
  });

  it("mudar um valor aplica-se só aos ciclos que abrem depois", () => {
    const v2: VersaoDaRegua = { ...V1, versao: "2027-01-01.1", validaDe: "2027-01-01", dias: { lembrete: 5, aviso: 9, suspensao: 12 } };
    const versoes = [V1, v2];
    validarVersoes(versoes);
    assert.equal(versaoDoCiclo(versoes, "2026-12-01").versao, V1.versao);
    assert.equal(versaoDoCiclo(versoes, "2027-01-01").versao, v2.versao);
    assert.equal(versaoDoCiclo(versoes, "2025-01-01").versao, V1.versao, "antes da primeira, a primeira");
    // O ciclo de Dezembro suspende no D+10 mesmo com a v2 em vigor no dia em que o motor corre.
    assert.deepEqual(accoesDoCiclo("em_atraso", ["lembrete", "aviso"], versaoDoCiclo(versoes, "2026-12-01"), 10, 3), [
      { passo: "suspensao", accao: "executar" },
    ]);
    assert.deepEqual(accoesDoCiclo("em_atraso", ["lembrete", "aviso"], v2, 10), []);
  });

  it("diasEntre conta dias civis, também a atravessar o fim do ano", () => {
    assert.equal(diasEntre("2026-12-28", "2027-01-07"), 10);
    assert.equal(diasEntre("2026-12-01", "2026-12-01"), 0);
  });
});

describe("régua: o calendário dos passos", () => {
  it("D+2 nada, D+3 o lembrete, D+7 o aviso, D+10 a suspensão", () => {
    assert.deepEqual(accoesDoCiclo("cobranca_emitida", [], V1, 2), []);
    assert.deepEqual(accoesDoCiclo("cobranca_emitida", [], V1, 3), [{ passo: "lembrete", accao: "executar" }]);
    assert.deepEqual(accoesDoCiclo("em_atraso", ["lembrete"], V1, 7), [{ passo: "aviso", accao: "executar" }]);
    assert.deepEqual(accoesDoCiclo("em_atraso", ["lembrete", "aviso"], V1, 10, 3), [
      { passo: "suspensao", accao: "executar" },
    ]);
  });

  it("um motor que esteve em baixo salta os passos atrasados e só executa o último", () => {
    assert.deepEqual(accoesDoCiclo("cobranca_emitida", [], V1, 8), [
      { passo: "lembrete", accao: "saltar" },
      { passo: "aviso", accao: "executar" },
    ]);
  });

  it("um ciclo pago ou anulado cancela os passos em falta", () => {
    assert.deepEqual(accoesDoCiclo("paga", ["lembrete", "aviso"], V1, 9), [{ passo: "suspensao", accao: "cancelar" }]);
    assert.deepEqual(accoesDoCiclo("anulado", ["lembrete"], V1, 4), [
      { passo: "aviso", accao: "cancelar" },
      { passo: "suspensao", accao: "cancelar" },
    ]);
  });
});

describe("régua: o template (critério 5)", () => {
  const agora = diaDoCiclo(3);
  const cobranca = (m: Partial<CobrancaDoCiclo> = {}): CobrancaDoCiclo => ({
    metodo: "referencia",
    referencia: "987654321",
    valorMinor: 1_500_000n,
    currency: "AOA",
    validaAte: diaDoCiclo(5),
    ...m,
  });

  it("os números de cada mensagem são todos campos da cobrança, e o aviso anti-phishing vai em todas", () => {
    for (const c of [cobranca(), cobranca({ metodo: "manual", referencia: null }), cobranca({ validaAte: diaDoCiclo(1) })]) {
      const campos = camposDaCobranca(c, V1, INICIO, agora);
      for (const passo of PASSOS_DA_REGUA) {
        const m = mensagemDoPasso(passo, V1, campos);
        assert.deepEqual(numerosForaDosCampos(m, campos), [], `${passo}: ${m}`);
        assert.ok(m.endsWith(AVISO_ANTI_PHISHING));
      }
    }
  });

  it("o valor, a referência e o prazo saem da cobrança e da versão", () => {
    const campos = camposDaCobranca(cobranca(), V1, INICIO, agora);
    assert.deepEqual(campos, { valor: "15000.00 Kz", referencia: "referência 987654321", prazo: "11/12/2026" });
    assert.equal(camposDaCobranca(cobranca({ metodo: "manual", referencia: null }), V1, INICIO, agora).referencia, SEM_REFERENCIA);
    assert.equal(camposDaCobranca(cobranca({ validaAte: diaDoCiclo(2) }), V1, INICIO, agora).referencia, REFERENCIA_EXPIRADA);
    assert.equal(camposDaCobranca(cobranca({ currency: "USD" }), V1, INICIO, agora).valor, "15000.00 USD");
  });

  it("controlo: o detector morde num número que não é campo", () => {
    const campos = camposDaCobranca(cobranca(), V1, INICIO, agora);
    const m = `${mensagemDoPasso("lembrete", V1, campos)} Ligue para 999123456.`;
    assert.deepEqual(numerosForaDosCampos(m, campos), ["999123456"]);
  });

  it("um campo em falta levanta em vez de sair um placeholder cru", () => {
    assert.throws(() => mensagemDoPasso("lembrete", V1, { valor: "1" }), ConfiguracaoDaReguaInvalida);
  });
});

describe("régua: o canal (critério 6)", () => {
  const pedido: PedidoDaRegua = { tenantId: TENANT, billingCycleId: CICLO, passo: "lembrete", mensagem: "m", chave: "k" };

  it("o notificador por omissão é o de ops e não sai mensagem nenhuma", async () => {
    assert.equal(await notificadorDeOps.entregar(pedido), "ops");
  });

  it("o caminho pelo OwnerNotifier não se constrói sem a decisão D10", () => {
    const dono = { avisar: async () => {} };
    for (const ref of [null, "", "  "]) {
      assert.throws(() => notificadorPeloDono(dono, async () => "c", ref), CanalD10Fechado);
    }
  });

  it("com a decisão, avisa pelo contact_id; sem contacto, fica tarefa de ops", async () => {
    const avisos: [string, string][] = [];
    const dono = { avisar: async (c: string, m: string) => void avisos.push([c, m]) };
    const com = notificadorPeloDono(dono, async () => "contacto-do-dono", "D10-ref");
    assert.equal(await com.entregar(pedido), "dono");
    assert.deepEqual(avisos, [["contacto-do-dono", "m"]]);
    const sem = notificadorPeloDono(dono, async () => null, "D10-ref");
    assert.equal(await sem.entregar(pedido), "ops");
    assert.equal(avisos.length, 1);
  });
});

describe("régua: o motor contra uma base com estado", () => {
  it("critério 8 — onze dias com o relógio injectado, cinco voltas por dia, em menos de 5 s", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    const contadas: [string, Record<string, string>][] = [];
    const t0 = performance.now();
    for (let d = 0; d <= 11; d += 1) {
      if (d === 11) bd.pagar();
      for (let volta = 0; volta < 5; volta += 1) {
        const rel = await correrRegua(bd, {
          agora: diaDoCiclo(d),
          metricas: { contar: (nome, etiquetas) => void contadas.push([nome, { ...etiquetas }]) },
        });
        assert.deepEqual(rel.falhas, []);
      }
    }
    const ms = performance.now() - t0;
    assert.ok(ms < 5_000, `onze dias levaram ${ms} ms`);

    // Critério 1: exactamente os três passos, um de cada.
    assert.deepEqual(
      bd.e.passos.map((p) => [p.passo, p.resultado, p.canal, p.executadoAt.slice(0, 10)]),
      [
        ["lembrete", "notificado", "ops", "2026-12-04"],
        ["aviso", "notificado", "ops", "2026-12-08"],
        ["suspensao", "suspenso", "ops", "2026-12-11"],
      ],
    );
    assert.ok(bd.e.passos.every((p) => p.versao === V1.versao));
    // Critério 2: uma suspensão, um evento sem PII, e o registo da transição.
    assert.deepEqual(bd.e.eventos, [
      { tipo: "tenant.suspended", tenantId: TENANT, payload: { motivo: MOTIVO_NO_EVENTO } },
      { tipo: "tenant.reactivated", tenantId: TENANT, payload: {} },
    ]);
    assert.deepEqual(
      bd.e.registo.map((l) => [l.de, l.para, l.motivo]),
      [
        ["ativo", "suspenso", MOTIVO_DA_SUSPENSAO],
        ["suspenso", "ativo", "regua_de_cobranca_regularizada"],
      ],
    );
    // Critério 2: as duas transições no `audit_log`, sem nada do dono.
    assert.deepEqual(
      bd.e.auditoria.map((a) => [a.actor, a.resumo]),
      [
        ["kamba_batch:regua_de_cobranca", "ativo>suspenso:regua_de_cobranca"],
        ["kamba_batch:regua_de_cobranca", "suspenso>ativo:regua_de_cobranca_regularizada"],
      ],
    );
    // Critério 3: o pagamento no D+11 repõe na primeira volta seguinte.
    assert.equal(bd.e.tenants[TENANT], "ativo");
    assert.equal(bd.e.subscricoes[SUBSCRICAO]?.estado, "ativa");
    // DoD: as métricas, uma por passo e uma suspensão.
    assert.deepEqual(contadas, [
      [METRICA_PASSOS, { passo: "lembrete", resultado: "notificado" }],
      [METRICA_PASSOS, { passo: "aviso", resultado: "notificado" }],
      [METRICA_PASSOS, { passo: "suspensao", resultado: "suspenso" }],
      [METRICA_SUSPENSOES, {}],
    ]);
  });

  it("o lembrete põe a subscrição em_atraso, e a suspensão em suspensa", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    await correrRegua(bd, { agora: diaDoCiclo(3) });
    assert.equal(bd.e.subscricoes[SUBSCRICAO]?.estado, "em_atraso");
    assert.equal(bd.e.tenants[TENANT], "ativo", "em atraso mantém o tenant e os limites");
    await correrRegua(bd, { agora: diaDoCiclo(7) });
    await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.equal(bd.e.subscricoes[SUBSCRICAO]?.estado, "suspensa");
  });

  it("critério 3 — o pagamento no D+9 cancela o passo pendente e o tenant não é suspenso", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 8; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    bd.pagar();
    for (let d = 9; d <= 12; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    assert.deepEqual(
      bd.e.passos.map((p) => [p.passo, p.resultado]),
      [
        ["lembrete", "notificado"],
        ["aviso", "notificado"],
        ["suspensao", "cancelado"],
      ],
    );
    assert.equal(bd.e.tenants[TENANT], "ativo");
    assert.deepEqual(bd.e.eventos, []);
    assert.equal(bd.e.subscricoes[SUBSCRICAO]?.estado, "ativa", "em_atraso volta a ativa quando o ciclo está pago");
  });

  it("idempotência — uma falha a meio da suspensão reverte tudo, e a volta seguinte faz o passo uma vez", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 9; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    bd.falharUmaVezEm = SQL_REGUA_SUSPENSA;
    const falhou = await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.equal(falhou.falhas.length, 1);
    assert.equal(bd.e.tenants[TENANT], "ativo", "a transição reverteu com a falha");
    assert.deepEqual(bd.e.eventos, [], "o evento reverteu com a falha");
    assert.equal(bd.e.passos.length, 2);
    await correrRegua(bd, { agora: diaDoCiclo(10) });
    await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.equal(bd.e.tenants[TENANT], "suspenso");
    assert.equal(bd.e.eventos.length, 1);
    assert.equal(bd.e.passos.length, 3);
  });

  it("critério 7 — um tenant restrito não é suspenso nem sai do restrito; a suspensão espera e vem quando a restrição sai", async () => {
    const bd = new BaseDaRegua();
    bd.semear({ estado: "restrito" });
    let adiados = 0;
    for (let d = 0; d <= 12; d += 1) {
      adiados += (await correrRegua(bd, { agora: diaDoCiclo(d) })).suspensoesAdiadas.length;
    }
    assert.equal(bd.e.tenants[TENANT], "restrito");
    assert.deepEqual(bd.e.eventos, []);
    assert.deepEqual(bd.e.passos.map((p) => p.passo), ["lembrete", "aviso"], "nada se grava enquanto adia");
    assert.equal(adiados, 3, "D+10, D+11 e D+12");
    // A Meta levanta a restrição com a dívida por pagar: a régua suspende.
    bd.e.tenants[TENANT] = "ativo";
    await correrRegua(bd, { agora: diaDoCiclo(13) });
    assert.equal(bd.e.tenants[TENANT], "suspenso");
    assert.deepEqual(bd.e.passos.at(-1)?.resultado, "suspenso");
  });

  it("um tenant encerrado fica sem_transicao e sem aviso", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 9; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    bd.e.tenants[TENANT] = "encerrado";
    await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.deepEqual(bd.e.passos.at(-1), {
      tenantId: TENANT,
      cicloId: CICLO,
      passo: "suspensao",
      executadoAt: diaDoCiclo(10).toISOString(),
      resultado: "sem_transicao",
      canal: null,
      versao: V1.versao,
    });
  });

  it("achado 2 — sem aviso notificado, a suspensão espera o aviso prévio inteiro", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    // O motor só corre pela primeira vez no D+10.
    await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.deepEqual(
      bd.e.passos.map((p) => [p.passo, p.resultado]),
      [
        ["lembrete", "saltado"],
        ["aviso", "notificado"],
      ],
    );
    assert.equal(bd.e.tenants[TENANT], "ativo");
    const espera = diasDeAvisoPrevio(V1);
    for (let d = 11; d < 10 + espera; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    assert.equal(bd.e.tenants[TENANT], "ativo", "ainda dentro do aviso prévio");
    await correrRegua(bd, { agora: diaDoCiclo(10 + espera) });
    assert.equal(bd.e.tenants[TENANT], "suspenso");
  });

  it("achado 2 — o calendário puro: a suspensão só com o aviso há dias suficientes", () => {
    assert.deepEqual(accoesDoCiclo("em_atraso", ["lembrete"], V1, 10, null), [{ passo: "aviso", accao: "executar" }]);
    assert.deepEqual(accoesDoCiclo("em_atraso", ["lembrete", "aviso"], V1, 10, 2), []);
    assert.deepEqual(accoesDoCiclo("em_atraso", ["lembrete", "aviso"], V1, 10, 3), [
      { passo: "suspensao", accao: "executar" },
    ]);
  });

  it("achado 5 — um pagamento que entra entre a leitura e o passo cancela-o em vez de suspender", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 9; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    bd.depoisDe.set(SQL_REGUA_CICLOS, (e) => {
      const c = e.ciclos.find((x) => x.id === CICLO);
      if (c !== undefined) c.estado = "paga";
    });
    await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.equal(bd.e.tenants[TENANT], "ativo");
    assert.deepEqual(bd.e.eventos, []);
    assert.equal(bd.e.passos.at(-1)?.resultado, "cancelado");
  });

  it("achado 9 — uma restrição que chega entre a leitura e a transição reverte o passo", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 9; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    bd.depoisDe.set(SQL_REGUA_ESTADO_DO_TENANT, (e) => {
      e.tenants[TENANT] = "restrito";
    });
    const rel = await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.equal(rel.falhas.length, 1);
    assert.match(rel.falhas[0]?.erro ?? "", /de restrito/);
    assert.equal(bd.e.tenants[TENANT], "restrito", "a transicao reverteu");
    assert.deepEqual(bd.e.eventos, []);
  });

  it("achado 1 — uma sanção de T&S depois da suspensão da régua prende a reposição; o recurso provido solta-a", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 10; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    assert.equal(bd.e.tenants[TENANT], "suspenso");
    bd.sancionar("suspensao");
    bd.pagar();
    await correrRegua(bd, { agora: diaDoCiclo(11) });
    assert.equal(bd.e.tenants[TENANT], "suspenso", "pagar a assinatura nao levanta a sancao");
    const sancao = bd.e.sancoes[0];
    if (sancao !== undefined) sancao.recursoProvido = true;
    await correrRegua(bd, { agora: diaDoCiclo(11) });
    assert.equal(bd.e.tenants[TENANT], "ativo");
  });

  it("um tenant suspenso por outra razão não é reposto por um pagamento", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    bd.e.tenants[TENANT] = "suspenso";
    bd.e.registo.push({ tenantId: TENANT, de: "ativo", para: "suspenso", motivo: "sancao" });
    for (let d = 0; d <= 10; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    assert.deepEqual(bd.e.passos.map((p) => p.passo), ["lembrete", "aviso"], "a suspensao adia");
    bd.pagar();
    await correrRegua(bd, { agora: diaDoCiclo(11) });
    assert.equal(bd.e.tenants[TENANT], "suspenso");
    assert.equal(bd.e.passos.at(-1)?.resultado, "cancelado");
    assert.deepEqual(bd.e.eventos, []);
  });

  it("um tenant reposto e depois suspenso por outra razão fica suspenso", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 10; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    bd.pagar();
    await correrRegua(bd, { agora: diaDoCiclo(11) });
    bd.e.tenants[TENANT] = "suspenso";
    bd.e.registo.push({ tenantId: TENANT, de: "ativo", para: "suspenso", motivo: "sancao" });
    await correrRegua(bd, { agora: diaDoCiclo(12) });
    assert.equal(bd.e.tenants[TENANT], "suspenso");
  });

  it("um motor que volta no D+8 salta o lembrete, executa o aviso e põe a subscrição em atraso", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    await correrRegua(bd, { agora: diaDoCiclo(8) });
    assert.equal(bd.e.subscricoes[SUBSCRICAO]?.estado, "em_atraso");
    assert.deepEqual(
      bd.e.passos.map((p) => [p.passo, p.resultado, p.canal]),
      [
        ["lembrete", "saltado", null],
        ["aviso", "notificado", "ops"],
      ],
    );
  });

  it("o notificador recebe a mensagem com a chave do passo, e o canal fica gravado", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    const pedidos: PedidoDaRegua[] = [];
    const notificador: NotificadorDaRegua = {
      entregar: async (p) => {
        pedidos.push(p);
        return "dono";
      },
    };
    await correrRegua(bd, { agora: diaDoCiclo(3), notificador });
    assert.equal(pedidos.length, 1);
    assert.equal(pedidos[0]?.chave, `regua:${CICLO}:lembrete`);
    assert.ok(pedidos[0]?.mensagem.includes("15000.00 Kz"));
    assert.equal(bd.e.passos[0]?.canal, "dono");
  });

  it("um ciclo sem cobrança falha o passo e não grava nada", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    bd.e.cobrancas = [];
    const rel = await correrRegua(bd, { agora: diaDoCiclo(3) });
    assert.equal(rel.falhas.length, 1);
    assert.deepEqual(bd.e.passos, []);
  });

  it("uma falha na reposição vai ao relatório e não pára a volta", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 10; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    bd.pagar();
    bd.falharUmaVezEm = SQL_REGUA_SUBSCRICAO_REPOSTA;
    const rel = await correrRegua(bd, { agora: diaDoCiclo(11) });
    assert.equal(rel.falhas.length, 1);
    assert.equal(bd.e.tenants[TENANT], "suspenso");
    const outra = await correrRegua(bd, { agora: diaDoCiclo(11) });
    assert.deepEqual(outra.repostos, [TENANT]);
  });

  it("o alerta dispara acima do limiar de suspensões do dia", async () => {
    const bd = new BaseDaRegua();
    const n = LIMIAR_DE_SUSPENSOES_POR_DIA + 1;
    for (let i = 0; i < n; i += 1) {
      const sufixo = `${i}`.padStart(12, "0");
      bd.semear({
        tenant: `aaaaaaaa-aaaa-4aaa-8aaa-${sufixo}`,
        ciclo: `cccccccc-cccc-4ccc-8ccc-${sufixo}`,
        subscricao: `bbbbbbbb-bbbb-4bbb-8bbb-${sufixo}`,
      });
    }
    await correrRegua(bd, { agora: diaDoCiclo(7) });
    const rel = await correrRegua(bd, { agora: diaDoCiclo(10) });
    assert.equal(rel.suspensoesHoje, n);
    assert.equal(rel.alertaDeSuspensoes, true);
    const tenantsSuspensos = Object.values(bd.e.tenants).filter((e) => e === "suspenso").length;
    assert.equal(tenantsSuspensos, n);
  });

  it("a lista diária de ops refaz a mensagem do ledger", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    await correrRegua(bd, { agora: diaDoCiclo(3) });
    const tarefas = await listaDeOps(bd, diaDoCiclo(3));
    assert.equal(tarefas.length, 1);
    assert.equal(tarefas[0]?.passo, "lembrete");
    assert.ok(tarefas[0]?.mensagem.includes("15000.00 Kz"));
    assert.ok(tarefas[0]?.mensagem.endsWith(AVISO_ANTI_PHISHING));
    assert.deepEqual(await listaDeOps(bd, diaDoCiclo(4)), []);
  });

  it("critério 7 — o motor não apaga nada: nenhuma instrução dele é um DELETE ou um TRUNCATE", async () => {
    const bd = new BaseDaRegua();
    bd.semear();
    for (let d = 0; d <= 11; d += 1) await correrRegua(bd, { agora: diaDoCiclo(d) });
    assert.ok(bd.chamadas.length > 0);
    for (const sql of new Set(bd.chamadas)) assert.doesNotMatch(sql, /\b(DELETE|TRUNCATE|DROP)\b/i);
  });

  it("critério 2 — o CHR recusa um tenant suspenso antes do AGR, e responde com a mensagem estática", () => {
    assert.equal(tenantGate("suspenso", "ativo", "processar_entrada").permitido, false);
    assert.equal(tenantGate("suspenso", "ativo", "mensagem_estatica").permitido, true);
    assert.equal(tenantGate("ativo", "ativo", "processar_entrada").permitido, true);
  });
});

describe("processo: arranque e agendamento (recebido do KAM-059)", () => {
  const arranque = {
    flags: FLAGS_OMISSAO,
    registo: new RegistoDeProviders(),
    contas: [],
    daKamba: ENTIDADES_DA_KAMBA,
    comissao: COMISSAO_OMISSAO,
  };
  const conta = { id: "44444444-4444-4444-8444-444444444444", provider: "manual" };

  it("o arranque recusa-se com a comissão ligada sem parecer", () => {
    const erro = capturar<Error & { codigo: string }>(
      () =>
        new ProcessoDaCobranca({
          arranque: { ...arranque, flags: { ...FLAGS_OMISSAO, commissionEnabled: true } },
          bdDoPay: new BaseDaRegua(),
          bdDeLote: new BaseDaRegua(),
          relogio: () => diaDoCiclo(0),
          conta,
          emissor: emissorManual,
          gerarId: () => "x",
        }),
    );
    assert.equal(erro.codigo, COMISSAO_SEM_PARECER);
  });

  it("a abertura corre uma vez por dia de Luanda, a régua em todas as voltas, e a sombra só com taxa", async () => {
    const pay = new BaseDaRegua();
    const responder = pay.query.bind(pay);
    pay.query = async (sql, p) => (sql === SQL_BILLING_SUBSCRICOES ? { rows: [], rowCount: 0 } : responder(sql, p));
    const lote = new BaseDaRegua();
    let agora = diaDoCiclo(0);
    let tenantsPedidos = 0;
    const processo = new ProcessoDaCobranca({
      arranque,
      bdDoPay: pay,
      bdDeLote: lote,
      relogio: () => agora,
      conta,
      emissor: emissorManual,
      gerarId: () => "x",
      sombra: {
        taxaBps: 100n,
        lote: 10,
        tenants: async () => {
          tenantsPedidos += 1;
          return [];
        },
      },
      notificador: notificadorDeOps,
      metricas: { contar: () => {} },
    });
    const primeira = await processo.volta();
    assert.notEqual(primeira.abertura, null);
    assert.deepEqual(primeira.falhasDosJobs, []);
    assert.equal(primeira.sombra, 0);
    const segunda = await processo.volta();
    assert.equal(segunda.abertura, null);
    assert.equal(segunda.sombra, null);
    agora = diaDoCiclo(1);
    assert.notEqual((await processo.volta()).abertura, null);
    assert.equal(tenantsPedidos, 2);
    assert.equal(lote.chamadas.filter((s) => s === SQL_REGUA_CICLOS).length, 3);

    const semSombra = new ProcessoDaCobranca({
      arranque,
      bdDoPay: pay,
      bdDeLote: lote,
      relogio: () => agora,
      conta,
      emissor: emissorManual,
      gerarId: () => "x",
    });
    assert.equal((await semSombra.volta()).sombra, null);
  });

  it("agendar dá voltas sem as sobrepor, entrega a falha e pára", async () => {
    assert.equal(INTERVALO_DA_REGUA_MS, 30_000);
    let voltas = 0;
    let emCurso = false;
    let sobrepostas = 0;
    const erros: unknown[] = [];
    let terceira: () => void = () => {};
    const chegouATerceira = new Promise<void>((resolve) => {
      terceira = resolve;
    });
    const parar = agendar(
      {
        volta: async () => {
          if (emCurso) sobrepostas += 1;
          emCurso = true;
          voltas += 1;
          await new Promise((resolve) => setTimeout(resolve, 5));
          emCurso = false;
          if (voltas === 3) terceira();
          if (voltas === 2) throw new Error("volta falhada");
          return {} as never;
        },
      },
      1,
      (e) => void erros.push(e),
    );
    // Pela terceira volta, e não por um tempo: com a máquina carregada um
    // relógio fixo dava uma volta só (medido).
    await chegouATerceira;
    parar();
    const depois = voltas;
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(voltas, depois, "parou");
    assert.equal(sobrepostas, 0, "uma volta nao comeca antes de a anterior acabar");
    assert.equal(erros.length, 1, "a falha da segunda volta foi entregue e as seguintes correram");
  });

  it("achado 4 — uma abertura que falha não pára a régua, e repete-se na volta seguinte", async () => {
    const pay = new BaseDaRegua();
    let falhar = true;
    pay.query = async () => {
      if (falhar) throw new Error("kamba_pay em baixo");
      return { rows: [], rowCount: 0 };
    };
    const lote = new BaseDaRegua();
    lote.semear();
    const processo = new ProcessoDaCobranca({
      arranque,
      bdDoPay: pay,
      bdDeLote: lote,
      relogio: () => diaDoCiclo(3),
      conta,
      emissor: emissorManual,
      gerarId: () => "x",
      sombra: {
        taxaBps: 100n,
        lote: 10,
        tenants: async () => {
          if (falhar) throw new Error("kamba_pay em baixo");
          return [];
        },
      },
    });
    const v = await processo.volta();
    assert.deepEqual(v.falhasDosJobs, ["abertura: kamba_pay em baixo", "sombra: kamba_pay em baixo"]);
    assert.equal(v.regua.passos.length, 1, "a regua correu na mesma");
    falhar = false;
    const outra = await processo.volta();
    assert.notEqual(outra.abertura, null, "o dia nao avancou com a abertura falhada");
    assert.deepEqual(outra.falhasDosJobs, []);
  });

  it("achado 4 — agendar entrega o relatório de cada volta", async () => {
    const relatorios: unknown[] = [];
    let chegou: () => void = () => {};
    const primeiro = new Promise<void>((resolve) => {
      chegou = resolve;
    });
    const parar = agendar(
      { volta: async () => ({ marca: 1 }) as never },
      1,
      () => {},
      (r) => {
        relatorios.push(r);
        chegou();
      },
    );
    await primeiro;
    parar();
    assert.deepEqual(relatorios[0], { marca: 1 });
  });

  it("agendar com a omissão de intervalo e de falha pára antes da primeira volta", () => {
    let voltas = 0;
    const parar = agendar({
      volta: async () => {
        voltas += 1;
        return {} as never;
      },
    });
    parar();
    assert.equal(voltas, 0);
  });

  it("a falha propaga-se pelo capturarAsync quando a régua não conhece a instrução", async () => {
    const bd = new BaseDaRegua();
    const erro = await capturarAsync(() => bd.query("SELECT 1"));
    assert.match(erro.message, /nao conhece/);
  });
});
