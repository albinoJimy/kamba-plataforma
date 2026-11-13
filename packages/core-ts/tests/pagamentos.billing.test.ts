/**
 * Billing da plataforma (KAM-059): o que se mede sem PostgreSQL.
 *
 * As barreiras — um ciclo por período, a conta da KAMBÁ, o `paga` atado ao
 * ledger, a dupla de ops, a sombra — medem-se contra a base em
 * `db/tests_pagamentos/test_billing.py`, com as cadeias SQL deste módulo. Aqui
 * mede-se o período, o preço em vigor, a validade, o cálculo da sombra, e a
 * **ordem** e a atomicidade dos *jobs* com uma ligação falsa que regista o que
 * recebe.
 */

import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, it } from "node:test";

import {
  HORAS_DE_VALIDADE,
  MotivoEmFalta,
  PeriodoInvalido,
  SQL_BILLING_ABRIR_CICLO,
  SQL_BILLING_CICLO_EMITIDO,
  SQL_BILLING_COBRANCA,
  SQL_BILLING_CONFIRMAR_OPS,
  SQL_BILLING_CONTEXTO,
  SQL_BILLING_EMITIR,
  SQL_BILLING_PRECARIO,
  SQL_BILLING_SUBSCRICOES,
  SQL_MUDAR_PLANO,
  SQL_SOMBRA_GRAVAR,
  SQL_SOMBRA_POR_MEDIR,
  SubscricaoInexistente,
  TaxaInvalida,
  type LinhaDoPrecario,
  abrirCiclos,
  acumularSombra,
  aprovarPorOps,
  comissaoEmSombra,
  dataEmLuanda,
  emissorManual,
  mudarPlano,
  periodoDe,
  precoEmVigor,
  validadeDaCobranca,
} from "../src/pagamentos/index.ts";
import type { ClienteSql } from "../src/eventos/publicador.ts";
import { capturarAsync } from "./apoio/capturar.ts";

type Resposta = { rows: Record<string, unknown>[]; rowCount: number | null };

/** Uma ligação que regista as instruções e responde por regra. */
class BaseFalsa implements ClienteSql {
  readonly chamadas: { sql: string; parametros: readonly unknown[] }[] = [];
  readonly responder: (sql: string, p: readonly unknown[]) => Resposta;
  constructor(responder: (sql: string, p: readonly unknown[]) => Resposta) {
    this.responder = responder;
  }
  async query(sql: string, parametros: readonly unknown[] = []): Promise<Resposta> {
    this.chamadas.push({ sql, parametros });
    return this.responder(sql, parametros);
  }
  get sqls(): string[] {
    return this.chamadas.map((c) => c.sql);
  }
}

const vazio: Resposta = { rows: [], rowCount: 0 };
const TENANT = "00000000-0000-4000-8000-0000000000a1";
const SUB = "00000000-0000-4000-8000-0000000000b1";
const CONTA = { id: "00000000-0000-4000-8000-0000000000c1", provider: "manual" };

function linha(plano: string, valor: bigint, de: string, ate: string | null = null): LinhaDoPrecario {
  return { id: `${plano}-${de}`, plano, valorMinor: valor, validoDe: de, validoAte: ate };
}

describe("billing: o periodo", () => {
  it("vai de dia a dia do mes seguinte, meio-aberto", () => {
    assert.deepEqual(periodoDe("2026-03-09", 10), { inicio: "2026-02-10", fim: "2026-03-10" });
    assert.deepEqual(periodoDe("2026-03-10", 10), { inicio: "2026-03-10", fim: "2026-04-10" });
  });

  it("atravessa o ano nos dois sentidos", () => {
    assert.deepEqual(periodoDe("2027-01-03", 5), { inicio: "2026-12-05", fim: "2027-01-05" });
    assert.deepEqual(periodoDe("2026-12-20", 5), { inicio: "2026-12-05", fim: "2027-01-05" });
  });

  it("o dia 28 existe em Fevereiro, e o dia 1 e a omissao", () => {
    assert.deepEqual(periodoDe("2027-02-28", 28), { inicio: "2027-02-28", fim: "2027-03-28" });
    assert.deepEqual(periodoDe("2026-11-13", 1), { inicio: "2026-11-01", fim: "2026-12-01" });
  });

  it("recusa um dia fora de 1..28 e uma data que nao existe", () => {
    for (const dia of [0, 29, 31, 1.5]) {
      assert.throws(() => periodoDe("2026-11-13", dia), PeriodoInvalido);
    }
    assert.throws(() => periodoDe("2026-02-30", 1), PeriodoInvalido);
    assert.throws(() => periodoDe("13/11/2026", 1), PeriodoInvalido);
  });

  it("o dia conta-se em Luanda (UTC+1): 23:30 UTC ja e o dia seguinte", () => {
    assert.equal(dataEmLuanda(new Date("2026-11-30T23:30:00Z")), "2026-12-01");
    assert.equal(dataEmLuanda(new Date("2026-11-30T22:59:59Z")), "2026-11-30");
  });
});

describe("billing: o preco em vigor (criterio 6)", () => {
  const linhas = [
    linha("base", 1_000_000n, "2026-01-01"),
    linha("base", 1_200_000n, "2026-11-15"),
    linha("outro", 9n, "2026-01-01"),
  ];

  it("e o do inicio do periodo, e nao o do dia do job", () => {
    assert.equal(precoEmVigor(linhas, "base", "2026-11-01")?.valorMinor, 1_000_000n);
    assert.equal(precoEmVigor(linhas, "base", "2026-12-01")?.valorMinor, 1_200_000n);
  });

  it("no proprio valido_de ja vale", () => {
    assert.equal(precoEmVigor(linhas, "base", "2026-11-15")?.valorMinor, 1_200_000n);
  });

  it("o valido_ate e exclusivo, e sem linha nao ha preco", () => {
    const comFim = [linha("fim", 5n, "2026-01-01", "2026-06-01")];
    assert.equal(precoEmVigor(comFim, "fim", "2026-05-31")?.valorMinor, 5n);
    assert.equal(precoEmVigor(comFim, "fim", "2026-06-01"), null);
    assert.equal(precoEmVigor(linhas, "base", "2025-12-31"), null);
    assert.equal(precoEmVigor(linhas, "inexistente", "2026-11-01"), null);
  });

  it("nao se engana pela ordem das linhas", () => {
    assert.equal(precoEmVigor([...linhas].reverse(), "base", "2026-12-01")?.valorMinor, 1_200_000n);
  });
});

describe("billing: validade e sombra", () => {
  it("a cobranca vale 72 h", () => {
    assert.equal(HORAS_DE_VALIDADE, 72);
    const agora = new Date("2026-11-13T10:00:00Z");
    assert.equal(validadeDaCobranca(agora).toISOString(), "2026-11-16T10:00:00.000Z");
  });

  it("a sombra e o floor em bigint, e a taxa nao tem omissao", () => {
    assert.equal(comissaoEmSombra(1_250_000n, 250), 31_250n);
    assert.equal(comissaoEmSombra(999n, 1), 0n);
    assert.equal(comissaoEmSombra(0n, 10_000), 0n);
    for (const taxa of [-1, 10_001, 2.5]) {
      assert.throws(() => comissaoEmSombra(100n, taxa), TaxaInvalida);
    }
    assert.throws(() => comissaoEmSombra(-1n, 10), TaxaInvalida);
  });

  it("o emissor do Piloto e transferencia, sem referencia", async () => {
    const emissao = await emissorManual({
      chargeId: "x",
      tenantId: TENANT,
      valorMinor: 1n,
      conta: CONTA,
    });
    assert.deepEqual(emissao, { metodo: "manual", referencia: null });
  });
});

function baseDoJob(opcoes: { cicloNovo: boolean; preco?: string; falhaNa?: string }): BaseFalsa {
  return new BaseFalsa((sql) => {
    if (opcoes.falhaNa !== undefined && sql === opcoes.falhaNa) throw new Error("falha forcada");
    if (sql === SQL_BILLING_SUBSCRICOES) {
      return {
        rows: [{ id: SUB, tenant_id: TENANT, plano: "base", estado: "ativa", periodo_dia: 1 }],
        rowCount: 1,
      };
    }
    if (sql === SQL_BILLING_PRECARIO) {
      return opcoes.preco === undefined
        ? vazio
        : {
            rows: [
              { id: "p1", plano: "base", valor_minor: opcoes.preco, valido_de: "2026-01-01", valido_ate: null },
            ],
            rowCount: 1,
          };
    }
    if (sql === SQL_BILLING_ABRIR_CICLO) {
      return opcoes.cicloNovo ? { rows: [{ id: "ciclo-1" }], rowCount: 1 } : vazio;
    }
    return vazio;
  });
}

const AGORA = new Date("2026-11-13T10:00:00Z");

describe("billing: o job de abertura (criterio 2)", () => {
  it("abre o ciclo, a cobranca de 72 h, emite no ledger e marca o ciclo, numa transaccao", async () => {
    const bd = baseDoJob({ cicloNovo: true, preco: "1000000" });
    const relatorio = await abrirCiclos(bd, {
      agora: AGORA,
      conta: CONTA,
      emissor: emissorManual,
      gerarId: () => "cobranca-1",
    });
    assert.deepEqual(relatorio, { abertos: ["ciclo-1"], jaAbertos: 0, semPreco: [], falhas: [] });
    assert.deepEqual(bd.sqls.slice(2), [
      "BEGIN",
      SQL_BILLING_CONTEXTO,
      SQL_BILLING_ABRIR_CICLO,
      SQL_BILLING_COBRANCA,
      SQL_BILLING_EMITIR,
      SQL_BILLING_CICLO_EMITIDO,
      "COMMIT",
    ]);
    const ciclo = bd.chamadas.find((c) => c.sql === SQL_BILLING_ABRIR_CICLO);
    assert.deepEqual(ciclo?.parametros, [SUB, TENANT, "2026-11-01", "2026-12-01", "1000000"]);
    const cobranca = bd.chamadas.find((c) => c.sql === SQL_BILLING_COBRANCA);
    assert.deepEqual(cobranca?.parametros, [
      "cobranca-1",
      TENANT,
      "ciclo-1",
      CONTA.id,
      "manual",
      "manual",
      null,
      "1000000",
      "2026-11-16T10:00:00.000Z",
    ]);
    const contexto = bd.chamadas.find((c) => c.sql === SQL_BILLING_CONTEXTO);
    assert.deepEqual(contexto?.parametros, [TENANT]);
  });

  it("um ciclo que ja existe nao abre cobranca nenhuma", async () => {
    const bd = baseDoJob({ cicloNovo: false, preco: "1000000" });
    const relatorio = await abrirCiclos(bd, {
      agora: AGORA,
      conta: CONTA,
      emissor: emissorManual,
      gerarId: () => "nunca",
    });
    assert.equal(relatorio.jaAbertos, 1);
    assert.deepEqual(relatorio.abertos, []);
    assert.ok(!bd.sqls.includes(SQL_BILLING_COBRANCA));
    assert.equal(bd.sqls.at(-1), "COMMIT");
  });

  it("sem preco, ou com preco zero, nao abre e diz quem ficou de fora", async () => {
    for (const preco of [undefined, "0"]) {
      const bd = baseDoJob({ cicloNovo: true, ...(preco === undefined ? {} : { preco }) });
      const relatorio = await abrirCiclos(bd, {
        agora: AGORA,
        conta: CONTA,
        emissor: emissorManual,
        gerarId: () => "nunca",
      });
      assert.deepEqual(relatorio.semPreco, [SUB]);
      assert.ok(!bd.sqls.includes("BEGIN"));
    }
  });

  it("uma falha a meio reverte a transaccao e nao para as outras subscricoes", async () => {
    const bd = baseDoJob({ cicloNovo: true, preco: "1000000", falhaNa: SQL_BILLING_EMITIR });
    const relatorio = await abrirCiclos(bd, {
      agora: AGORA,
      conta: CONTA,
      emissor: emissorManual,
      gerarId: () => "cobranca-1",
    });
    assert.equal(relatorio.falhas.length, 1);
    assert.equal(relatorio.falhas[0]?.subscricao, SUB);
    assert.match(relatorio.falhas[0]?.erro ?? "", /falha forcada/);
    assert.equal(bd.sqls.at(-1), "ROLLBACK");
    assert.ok(!bd.sqls.includes("COMMIT"));
  });

  it("le o precario uma vez por plano", async () => {
    const bd = new BaseFalsa((sql) => {
      if (sql === SQL_BILLING_SUBSCRICOES) {
        return {
          rows: [
            { id: "s1", tenant_id: "t1", plano: "base", estado: "ativa", periodo_dia: 1 },
            { id: "s2", tenant_id: "t2", plano: "base", estado: "em_atraso", periodo_dia: 1 },
          ],
          rowCount: 2,
        };
      }
      if (sql === SQL_BILLING_PRECARIO) return vazio;
      return vazio;
    });
    const relatorio = await abrirCiclos(bd, {
      agora: AGORA,
      conta: CONTA,
      emissor: emissorManual,
      gerarId: () => "x",
    });
    assert.equal(bd.sqls.filter((s) => s === SQL_BILLING_PRECARIO).length, 1);
    assert.deepEqual(relatorio.semPreco, ["s1", "s2"]);
  });
});

describe("billing: mudar o plano (criterio 8)", () => {
  const modulos = [{ modulo: "vendedor", ativo: true, limites: { msgs_ai_mes: 1000 } }];

  it("uma instrucao, numa transaccao, com o mapa do plano em JSON", async () => {
    const bd = new BaseFalsa((sql) =>
      sql === SQL_MUDAR_PLANO
        ? { rows: [{ subscricoes: 1, tenants: 1, garantidos: 1, desactivados: 2 }], rowCount: 1 }
        : vazio,
    );
    const r = await mudarPlano(bd, TENANT, "base", modulos);
    assert.deepEqual(r, { garantidos: 1, desactivados: 2 });
    assert.deepEqual(bd.sqls, ["BEGIN", SQL_MUDAR_PLANO, "COMMIT"]);
    assert.deepEqual(bd.chamadas[1]?.parametros, [TENANT, "base", JSON.stringify(modulos)]);
  });

  it("um tenant sem subscricao reverte, e os entitlements nao mudam", async () => {
    const bd = new BaseFalsa((sql) =>
      sql === SQL_MUDAR_PLANO
        ? { rows: [{ subscricoes: 0, tenants: 1, garantidos: 1, desactivados: 0 }], rowCount: 1 }
        : vazio,
    );
    await assert.rejects(mudarPlano(bd, TENANT, "base", modulos), SubscricaoInexistente);
    assert.deepEqual(bd.sqls, ["BEGIN", SQL_MUDAR_PLANO, "ROLLBACK"]);
  });

  it("sem linha devolvida tambem reverte", async () => {
    const bd = new BaseFalsa(() => vazio);
    await assert.rejects(mudarPlano(bd, TENANT, "base", modulos), SubscricaoInexistente);
  });
});

describe("billing: a aprovacao de ops (criterio 5)", () => {
  const pedido = {
    tenantId: TENANT,
    chargeId: "cobranca-1",
    actorId: "00000000-0000-4000-8000-0000000000d1",
    motivo: "extracto de 13/11",
    valorMinor: 1_000_000n,
  };

  it("poe o contexto do tenant e chama a porta", async () => {
    const bd = new BaseFalsa((sql) =>
      sql === SQL_BILLING_CONFIRMAR_OPS
        ? { rows: [{ aprovacoes: 1, concluida: false, repetida: false }], rowCount: 1 }
        : vazio,
    );
    const r = await aprovarPorOps(bd, pedido);
    assert.deepEqual(r, { aprovacoes: 1, concluida: false, repetida: false });
    assert.deepEqual(bd.sqls, ["BEGIN", SQL_BILLING_CONTEXTO, SQL_BILLING_CONFIRMAR_OPS, "COMMIT"]);
    assert.deepEqual(bd.chamadas[2]?.parametros, [
      "cobranca-1",
      pedido.actorId,
      pedido.motivo,
      "1000000",
    ]);
  });

  it("sem motivo nem chega a base", async () => {
    const bd = new BaseFalsa(() => vazio);
    const erro = await capturarAsync(() => aprovarPorOps(bd, { ...pedido, motivo: "  " }));
    assert.ok(erro instanceof MotivoEmFalta);
    assert.deepEqual(bd.sqls, []);
  });

  it("uma recusa da base reverte", async () => {
    const bd = new BaseFalsa((sql) => {
      if (sql === SQL_BILLING_CONFIRMAR_OPS) throw new Error("23514");
      return vazio;
    });
    await assert.rejects(aprovarPorOps(bd, pedido), /23514/);
    assert.equal(bd.sqls.at(-1), "ROLLBACK");
  });

  it("uma resposta sem linha nao conclui", async () => {
    const bd = new BaseFalsa(() => vazio);
    const r = await aprovarPorOps(bd, pedido);
    assert.equal(r.concluida, false);
    assert.equal(r.repetida, false);
  });
});

describe("billing: a sombra da comissao (criterio 7)", () => {
  it("grava uma linha por pagamento autenticado, com a taxa e o calculo", async () => {
    const bd = new BaseFalsa((sql) => {
      if (sql === SQL_SOMBRA_POR_MEDIR) {
        return { rows: [{ id: "71", order_id: "enc-1", valor_minor: "1250000" }], rowCount: 1 };
      }
      if (sql === SQL_SOMBRA_GRAVAR) return { rows: [], rowCount: 1 };
      return vazio;
    });
    const n = await acumularSombra(bd, { tenants: [TENANT], taxaBps: 250, lote: 100 });
    assert.equal(n, 1);
    const gravar = bd.chamadas.find((c) => c.sql === SQL_SOMBRA_GRAVAR);
    assert.deepEqual(gravar?.parametros, [TENANT, "enc-1", "71", "1250000", 250, "31250"]);
    assert.deepEqual(bd.chamadas.find((c) => c.sql === SQL_SOMBRA_POR_MEDIR)?.parametros, [100]);
  });

  it("uma taxa invalida recusa antes de abrir transaccao", async () => {
    const bd = new BaseFalsa(() => vazio);
    await assert.rejects(acumularSombra(bd, { tenants: [TENANT], taxaBps: -5, lote: 1 }), TaxaInvalida);
    assert.deepEqual(bd.sqls, []);
  });

  it("uma repeticao que o UNIQUE absorve nao conta, e uma falha reverte", async () => {
    const repetida = new BaseFalsa((sql) =>
      sql === SQL_SOMBRA_POR_MEDIR
        ? { rows: [{ id: "71", order_id: "enc-1", valor_minor: "10" }], rowCount: 1 }
        : { rows: [], rowCount: null },
    );
    assert.equal(await acumularSombra(repetida, { tenants: [TENANT], taxaBps: 1, lote: 1 }), 0);

    const falha = new BaseFalsa((sql) => {
      if (sql === SQL_SOMBRA_POR_MEDIR) throw new Error("rls");
      return vazio;
    });
    await assert.rejects(acumularSombra(falha, { tenants: [TENANT], taxaBps: 1, lote: 1 }), /rls/);
    assert.equal(falha.sqls.at(-1), "ROLLBACK");
  });
});

// --------------------------------------------------------------------------
// Criterio 9 (C-04): nenhum documento fiscal sai deste repositorio.
// --------------------------------------------------------------------------

const RAIZ = resolve(import.meta.dirname, "..", "..", "..");
const ARVORES = ["packages", "services", "libs"];
const FORA = new Set(["node_modules", "dist", ".venv", "coverage", "__pycache__"]);

function ficheirosDeCodigo(dir: string, saida: string[] = []): string[] {
  for (const nome of readdirSync(dir)) {
    if (FORA.has(nome)) continue;
    const caminho = join(dir, nome);
    if (statSync(caminho).isDirectory()) {
      ficheirosDeCodigo(caminho, saida);
    } else if (/\.(ts|py)$/.test(nome) && /[\\/]src[\\/]/.test(caminho)) {
      saida.push(caminho);
    }
  }
  return saida;
}

describe("billing: criterio 9 — nao ha emissao de factura (C-04)", () => {
  const ficheiros = ARVORES.flatMap((arvore) => ficheirosDeCodigo(join(RAIZ, arvore)));

  it("o varrimento ve o codigo de producao (um zero aqui nao diria nada)", () => {
    assert.ok(ficheiros.length > 100, `so ${ficheiros.length} ficheiros`);
    assert.ok(ficheiros.some((f) => f.endsWith(join("pagamentos", "billing.ts"))));
  });

  it("nenhuma classe implementa a InvoiceProvider", () => {
    const achados = ficheiros.filter((f) =>
      /implements\s+[^{]*\bInvoiceProvider\b/.test(readFileSync(f, "utf-8")),
    );
    assert.deepEqual(achados.map((f) => relative(RAIZ, f)), []);
  });

  it("nenhuma funcao emite factura, e nenhuma rota a serve", () => {
    const funcao =
      /\b(?:function|def|async\s+function)\s+(?:issue_?invoice\w*|emitir_?factura\w*|emitirFactura\w*|issueInvoice\w*)/i;
    const metodo = /^\s*(?:async\s+)?issueInvoiceReceipt\s*\([^)]*\)\s*[:{][^;]*\{/m;
    const rota = /\.(?:get|post|put|patch|delete|route)\s*\(\s*["'`][^"'`]*(?:factura|invoice)/i;
    const achados = ficheiros.filter((f) => {
      const texto = readFileSync(f, "utf-8");
      return funcao.test(texto) || metodo.test(texto) || rota.test(texto);
    });
    assert.deepEqual(achados.map((f) => relative(RAIZ, f)), []);
  });

  it("e os tres detectores mordem num texto que emite", () => {
    const funcao = /\b(?:function|def|async\s+function)\s+(?:issue_?invoice\w*|emitir_?factura\w*|emitirFactura\w*|issueInvoice\w*)/i;
    const rota = /\.(?:get|post|put|patch|delete|route)\s*\(\s*["'`][^"'`]*(?:factura|invoice)/i;
    assert.ok(funcao.test("export async function emitirFactura(x) {}"));
    assert.ok(funcao.test("def issue_invoice(pedido):"));
    assert.ok(rota.test('app.post("/billing/factura", h)'));
  });
});
