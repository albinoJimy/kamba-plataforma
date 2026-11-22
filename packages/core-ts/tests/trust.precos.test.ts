/**
 * A varredura do preço anómalo (KAM-209): a forma, sobre uma base falsa.
 *
 * O que só a base prova — a mediana pelo `kamba_batch` contra ofertas reais de
 * vários tenants, as fronteiras gravadas na `ts_signal`, o `kamba_app` a não
 * ver as referências — está em `../tests_bd/trust.bd.test.ts`. Aqui mede-se a
 * regra de quem é referência de quem, o que o sinal diz, e a corrida no ciclo.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { ConjuntoSql } from "../src/revisao/sql.ts";
import {
  CATEGORIAS_DE_PRODUTO,
  CicloDoTrust,
  FONTE_DAS_REFERENCIAS,
  MetricasDoTrust,
  POLITICA_DE_RISCO,
  SQL_AUDITAR_VARREDURA,
  SQL_GRAVAR_SINAL,
  SQL_OFERTAS_DE_PRECO_FIXO,
  SQL_OFERTAS_SEM_CATEGORIA,
  SQL_PRECOS_JA_SINALIZADOS,
  ServicoDeTrust,
  RepositorioDeTrustEmMemoria,
  refDoPreco,
  varrerPrecos,
} from "../src/trust/index.ts";

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const AGORA = new Date("2026-11-21T10:00:00Z");

interface Linha {
  readonly tenant_id: string;
  readonly sku: string;
  readonly categoria: string;
  readonly currency?: string;
  readonly preco_minor: string;
}

/** Uma base falsa: as ofertas, as chaves já gravadas, e o que se gravou. */
class BaseFalsa {
  readonly gravados: { tenant: string; ref: string; detalhe: Record<string, unknown> }[] = [];
  readonly consultas: string[] = [];
  readonly ofertas: readonly Linha[];
  readonly jaGravados: readonly string[];
  readonly semCategoria: number;
  constructor(ofertas: readonly Linha[], jaGravados: readonly string[] = [], semCategoria = 0) {
    this.ofertas = ofertas;
    this.jaGravados = jaGravados;
    this.semCategoria = semCategoria;
  }

  async query(sql: string, p: readonly unknown[] = []): Promise<{ readonly rows: readonly Record<string, unknown>[] }> {
    this.consultas.push(sql);
    if (sql === SQL_OFERTAS_DE_PRECO_FIXO) return { rows: this.ofertas.map((o) => ({ currency: "AOA", ...o })) };
    if (sql === SQL_PRECOS_JA_SINALIZADOS) return { rows: this.jaGravados.map((r) => ({ ref_evento: r })) };
    if (sql === SQL_OFERTAS_SEM_CATEGORIA) return { rows: [{ n: this.semCategoria }] };
    if (sql === SQL_GRAVAR_SINAL) {
      this.gravados.push({ tenant: String(p[0]), ref: String(p[3]), detalhe: JSON.parse(String(p[4])) as Record<string, unknown> });
      return { rows: [{ id: `00000000-0000-4000-8000-${String(this.gravados.length).padStart(12, "0")}` }] };
    }
    return { rows: [] };
  }
}

/** `n` ofertas de `tenant` na categoria, todas ao mesmo preço. */
function ofertas(tenant: string, n: number, preco: number, categoria = "moda"): Linha[] {
  return Array.from({ length: n }, (_, i) => ({ tenant_id: tenant, sku: `${tenant.slice(0, 1)}-${categoria}-${i}`, categoria, preco_minor: String(preco) }));
}

const alvo = (preco: number, categoria = "moda"): Linha => ({ tenant_id: A, sku: "alvo", categoria, preco_minor: String(preco) });

async function varrer(base: BaseFalsa) {
  return varrerPrecos(base, { relogio: () => AGORA });
}

describe("preço anómalo: quem é referência de quem", () => {
  it("19 referências não avaliam; 20 avaliam", async () => {
    const com19 = new BaseFalsa([alvo(1), ...ofertas(B, 19, 100_000)]);
    assert.equal((await varrer(com19)).sinais, 0);
    assert.equal(com19.gravados.length, 0);
    const com20 = new BaseFalsa([alvo(1), ...ofertas(B, 20, 100_000)]);
    assert.equal((await varrer(com20)).sinais, 1);
    assert.equal(com20.gravados[0]?.tenant, A);
  });

  it("1% e 100× da mediana são as fronteiras, e ficam dentro", async () => {
    const casos: readonly [number, boolean][] = [
      [1_000, false],
      [999, true],
      [10_000_000, false],
      [10_000_001, true],
    ];
    for (const [preco, anomalo] of casos) {
      const base = new BaseFalsa([alvo(preco), ...ofertas(B, 20, 100_000)]);
      assert.equal((await varrer(base)).sinais, anomalo ? 1 : 0, `preço ${preco}`);
    }
  });

  it("as ofertas do próprio tenant nunca são referência", async () => {
    // Vinte e cinco ofertas de A a 100 000, e uma de A a 1: sem outros tenants,
    // não há referência, e nenhuma é anómala.
    const base = new BaseFalsa([alvo(1), ...ofertas(A, 25, 100_000)]);
    assert.equal((await varrer(base)).sinais, 0);
    // E com dezanove de B e vinte de A, continua a não chegar a vinte.
    const mista = new BaseFalsa([alvo(1), ...ofertas(A, 20, 100_000), ...ofertas(B, 19, 100_000)]);
    assert.equal((await varrer(mista)).sinais, 0);
  });

  it("as referências são de várias lojas, e cada uma é avaliada contra as outras", async () => {
    const base = new BaseFalsa([...ofertas(B, 10, 100_000), ...ofertas(C, 10, 100_000), alvo(50_000_000)]);
    assert.equal((await varrer(base)).sinais, 1);
    assert.equal(base.gravados[0]?.detalhe["contagem"], 20);
    // As de B avaliam-se contra as de C e a de A: 11 < 20, nada.
    assert.equal(base.gravados.length, 1);
  });

  it("a mesma categoria e a mesma moeda: outra categoria não é referência", async () => {
    const base = new BaseFalsa([alvo(1), ...ofertas(B, 20, 100_000, "beleza")]);
    assert.equal((await varrer(base)).sinais, 0);
  });

  it("a `outra` e uma categoria fora da lista não se avaliam nem são referência", async () => {
    assert.ok((CATEGORIAS_DE_PRODUTO as readonly string[]).includes("outra"));
    const outra = new BaseFalsa([alvo(1, "outra"), ...ofertas(B, 20, 100_000, "outra")]);
    assert.equal((await varrer(outra)).sinais, 0);
    const fora = new BaseFalsa([alvo(1, "inventada"), ...ofertas(B, 20, 100_000, "inventada")]);
    assert.equal((await varrer(fora)).sinais, 0);
  });
});

describe("preço anómalo: o sinal", () => {
  it("diz o sku desta loja, a contagem, a fonte e a versão da política — e mais nada", async () => {
    const base = new BaseFalsa([alvo(1), ...ofertas(B, 21, 100_000)]);
    await varrer(base);
    assert.deepEqual(base.gravados[0]?.detalhe, {
      sku: "alvo",
      contagem: 21,
      fonte: FONTE_DAS_REFERENCIAS,
      versao_politica: POLITICA_DE_RISCO.versao,
    });
    assert.equal(FONTE_DAS_REFERENCIAS, "plataforma/1");
    // Nem o tenant das referências, nem um preço, nem a mediana.
    const texto = JSON.stringify(base.gravados[0]);
    assert.doesNotMatch(texto, new RegExp(B));
    assert.doesNotMatch(texto, /100000/);
  });

  it("um preço já sinalizado não se grava outra vez; outro preço do mesmo produto sim", async () => {
    const ref = refDoPreco({ tenantId: A, sku: "alvo", categoria: "moda", currency: "AOA", precoMinor: 1 });
    const repetida = new BaseFalsa([alvo(1), ...ofertas(B, 20, 100_000)], [ref]);
    assert.equal((await varrer(repetida)).sinais, 0);
    assert.equal(repetida.gravados.length, 0);
    const outroPreco = new BaseFalsa([alvo(2), ...ofertas(B, 20, 100_000)], [ref]);
    assert.equal((await varrer(outroPreco)).sinais, 1);
    assert.notEqual(outroPreco.gravados[0]?.ref, ref);
  });

  it("a chave é determinística e muda com cada parte", () => {
    const o = { tenantId: A, sku: "alvo", categoria: "moda", currency: "AOA", precoMinor: 1 };
    assert.equal(refDoPreco(o), refDoPreco({ ...o }));
    assert.match(refDoPreco(o), /^[0-9a-f]{8}-[0-9a-f]{4}-8[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    for (const mudado of [{ tenantId: B }, { sku: "b" }, { categoria: "beleza" }, { currency: "USD" }, { precoMinor: 2 }]) {
      assert.notEqual(refDoPreco({ ...o, ...mudado }), refDoPreco(o));
    }
  });

  it("conta as ofertas publicadas sem categoria", async () => {
    assert.equal((await varrerPrecos(new BaseFalsa([], [], 7), { relogio: () => AGORA })).semCategoria, 7);
  });

  it("o peso é o 5 do KAM-097 e o sinal não sobe a escada sozinho", async () => {
    assert.equal(POLITICA_DE_RISCO.pesos.preco_anomalo, 5);
    const s = new ServicoDeTrust({ repositorio: new RepositorioDeTrustEmMemoria(() => AGORA), relogio: () => AGORA });
    const r = await s.sinalizar({ tenantId: A, tipo: "preco_anomalo", refEvento: refDoPreco({ tenantId: A, sku: "x", categoria: "moda", currency: "AOA", precoMinor: 1 }), detalhe: { sku: "x", contagem: 20, fonte: FONTE_DAS_REFERENCIAS, versao_politica: "1.0.0" }, ocorridoEm: AGORA });
    assert.equal(r.sinal.severidade, "baixa");
    assert.deepEqual(r.sancoes, []);
  });
});

/** Um `pg.Pool` falso para o ciclo: cada ligação regista o que correu. */
class ConjuntoFalso implements ConjuntoSql {
  readonly consultas: { ligacao: string; texto: string; valores: readonly unknown[] }[] = [];
  #n = 0;
  readonly base: BaseFalsa;
  constructor(base: BaseFalsa) {
    this.base = base;
  }
  async query<T = Record<string, unknown>>(texto: string, valores: readonly unknown[] = []) {
    this.consultas.push({ ligacao: "conjunto", texto, valores });
    return (await this.base.query(texto, valores)) as unknown as { readonly rows: readonly T[] };
  }
  async connect() {
    const nome = `ligacao-${++this.#n}`;
    const self = this;
    return {
      async query<T = Record<string, unknown>>(texto: string, valores: readonly unknown[] = []) {
        self.consultas.push({ ligacao: nome, texto, valores });
        return (await self.base.query(texto, valores)) as unknown as { readonly rows: readonly T[] };
      },
      release() {},
    };
  }
}

describe("preço anómalo no ciclo do lote", () => {
  it("corre como `precos`, com a linha `batch.run` na mesma ligação e as sem categoria no payload", async () => {
    const base = new BaseFalsa([alvo(1), ...ofertas(B, 20, 100_000)], [], 3);
    const lote = new ConjuntoFalso(base);
    const metricas = new MetricasDoTrust();
    const servico = new ServicoDeTrust({ repositorio: new RepositorioDeTrustEmMemoria(() => AGORA), relogio: () => AGORA });
    const r = await new CicloDoTrust({ lote, servico, metricas, relogio: () => AGORA }).correr();
    assert.equal(r.feitas.precos, 1);
    assert.equal(r.ofertasSemCategoria, 3);
    assert.ok(!r.falhas.includes("precos"));
    const leitura = lote.consultas.find((c) => c.texto === SQL_OFERTAS_DE_PRECO_FIXO);
    const auditoria = lote.consultas.find((c) => c.texto === SQL_AUDITAR_VARREDURA && c.valores[1] === "precos");
    assert.ok(leitura !== undefined && auditoria !== undefined);
    assert.equal(auditoria.ligacao, leitura.ligacao);
    assert.equal(auditoria.valores[2], "precos:1:sem_categoria:3");
    assert.match(metricas.exposicao(), /^ts_varreduras_total\{varredura="precos",desfecho="concluida"\} 1$/m);
    assert.match(metricas.exposicao(), /^ts_sinais_total\{tipo="preco_anomalo"\} 1$/m);
  });
});
