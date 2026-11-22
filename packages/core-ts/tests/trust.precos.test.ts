/**
 * A varredura do preço anómalo (KAM-209): a forma, sobre uma base falsa.
 *
 * O que só a base prova — a mediana pelo `kamba_batch` contra ofertas reais de
 * vários tenants, as fronteiras gravadas na `ts_signal`, a escada que não sobe,
 * o `kamba_app` a não ver as referências — está em `../tests_bd/trust.bd.test.ts`.
 * Aqui mede-se a regra de quem é referência de quem, o que o sinal diz, e a
 * corrida no ciclo.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { ConjuntoSql } from "../src/revisao/sql.ts";
import {
  CATEGORIAS_DE_PRODUTO,
  CicloDoTrust,
  DIAS_DA_JANELA_DO_PRECO,
  FONTE_DAS_REFERENCIAS,
  LOJAS_MINIMAS_DAS_REFERENCIAS,
  MetricasDoTrust,
  POLITICA_DE_RISCO,
  SQL_AUDITAR_VARREDURA,
  SQL_GRAVAR_SINAL,
  SQL_OFERTAS_COM_PRECO,
  SQL_OFERTAS_SEM_CATEGORIA,
  SQL_PRECOS_JA_SINALIZADOS,
  ServicoDeTrust,
  RepositorioDeTrustEmMemoria,
  refDaJanela,
  refDoPreco,
  varrerPrecos,
} from "../src/trust/index.ts";

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const AGORA = new Date("2026-11-21T10:00:00Z");

interface Linha {
  readonly tenant_id: string;
  readonly sku: string;
  readonly categoria: string;
  readonly currency?: string;
  readonly preco_tipo?: string;
  readonly preco_minor: string;
}

/** Uma base falsa: as ofertas, as chaves já gravadas, e o que se gravou. */
class BaseFalsa {
  readonly gravados: { tenant: string; ref: string; detalhe: Record<string, unknown> }[] = [];
  readonly chavesPedidas: unknown[] = [];
  readonly ofertas: readonly Linha[];
  readonly jaGravados: readonly string[];
  readonly semCategoria: number;
  constructor(ofertas: readonly Linha[], jaGravados: readonly string[] = [], semCategoria = 0) {
    this.ofertas = ofertas;
    this.jaGravados = jaGravados;
    this.semCategoria = semCategoria;
  }

  async query(sql: string, p: readonly unknown[] = []): Promise<{ readonly rows: readonly Record<string, unknown>[] }> {
    if (sql === SQL_OFERTAS_COM_PRECO) return { rows: this.ofertas.map((o) => ({ currency: "AOA", preco_tipo: "fixo", ...o })) };
    if (sql === SQL_PRECOS_JA_SINALIZADOS) {
      // Honra o `ANY($1)` da instrução: só devolve as pedidas que já existem.
      this.chavesPedidas.push(p[0]);
      const pedidas = new Set(p[0] as readonly string[]);
      return { rows: this.jaGravados.filter((r) => pedidas.has(r)).map((r) => ({ ref_evento: r })) };
    }
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

/** `n` referências repartidas por três lojas (B, C e D), ao mesmo preço. */
function referencias(n: number, preco: number, categoria = "moda"): Linha[] {
  const lojas = [B, C, D];
  return Array.from({ length: n }, (_, i) => ({
    tenant_id: lojas[i % 3]!,
    sku: `ref-${categoria}-${i}`,
    categoria,
    preco_minor: String(preco),
  }));
}

const alvo = (preco: number, categoria = "moda", sku = "alvo"): Linha => ({ tenant_id: A, sku, categoria, preco_minor: String(preco) });

async function varrer(base: BaseFalsa) {
  return varrerPrecos(base, { relogio: () => AGORA });
}

describe("preço anómalo: quem é referência de quem", () => {
  it("19 referências não avaliam; 20 avaliam", async () => {
    const com19 = new BaseFalsa([alvo(1), ...referencias(19, 100_000)]);
    assert.equal((await varrer(com19)).sinais, 0);
    assert.equal(com19.gravados.length, 0);
    const com20 = new BaseFalsa([alvo(1), ...referencias(20, 100_000)]);
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
      const base = new BaseFalsa([alvo(preco), ...referencias(20, 100_000)]);
      assert.equal((await varrer(base)).sinais, anomalo ? 1 : 0, `preço ${preco}`);
    }
  });

  it("as ofertas do próprio tenant nunca são referência", async () => {
    const base = new BaseFalsa([alvo(1), ...ofertas(A, 25, 100_000)]);
    assert.equal((await varrer(base)).sinais, 0);
    const mista = new BaseFalsa([alvo(1), ...ofertas(A, 20, 100_000), ...referencias(19, 100_000)]);
    assert.equal((await varrer(mista)).sinais, 0);
  });

  it("uma loja com 20 ofertas a 1 Kz não fixa a mediana: abaixo de três lojas não se avalia, e conta-se", async () => {
    assert.equal(LOJAS_MINIMAS_DAS_REFERENCIAS, 3);
    // B publica vinte a 1 Kz: sem o mínimo de lojas, o preço normal de A era anómalo.
    const uma = new BaseFalsa([alvo(100_000), ...ofertas(B, 20, 100)]);
    const r = await varrer(uma);
    assert.equal(r.sinais, 0);
    assert.equal(r.poucasLojas, 1, "a oferta de A não se avaliou, e conta-se");
    // Duas lojas também não chegam.
    const duas = new BaseFalsa([alvo(100_000), ...ofertas(B, 10, 100), ...ofertas(C, 10, 100)]);
    assert.equal((await varrer(duas)).sinais, 0);
    // Três lojas chegam.
    const tres = new BaseFalsa([alvo(100_000), ...ofertas(B, 10, 100), ...ofertas(C, 5, 100), ...ofertas(D, 5, 100)]);
    assert.equal((await varrer(tres)).sinais, 1);
    // E abaixo das vinte é «sem referência», não «poucas lojas».
    assert.equal((await varrer(new BaseFalsa([alvo(1), ...ofertas(B, 19, 100)]))).poucasLojas, 0);
  });

  it("um `a_partir_de` avalia-se contra as de preço fixo, e não é referência", async () => {
    const aPartirDe = (n: number, preco: number): Linha[] =>
      referencias(n, preco).map((o) => ({ ...o, sku: `ap-${o.sku}`, preco_tipo: "a_partir_de" }));
    const avaliado = new BaseFalsa([{ ...alvo(1), preco_tipo: "a_partir_de" }, ...referencias(20, 100_000)]);
    assert.equal((await varrer(avaliado)).sinais, 1);
    const naoConta = new BaseFalsa([alvo(1), ...aPartirDe(20, 100_000)]);
    assert.equal((await varrer(naoConta)).sinais, 0);
    const quase = new BaseFalsa([alvo(1), ...referencias(19, 100_000), ...aPartirDe(1, 100_000)]);
    assert.equal((await varrer(quase)).sinais, 0);
  });

  it("as referências de várias lojas avaliam cada uma contra as outras", async () => {
    const base = new BaseFalsa([...referencias(21, 100_000), alvo(50_000_000)]);
    assert.equal((await varrer(base)).sinais, 1);
    assert.equal(base.gravados[0]?.tenant, A);
  });

  it("a mesma categoria e a mesma moeda: outra categoria não é referência", async () => {
    const base = new BaseFalsa([alvo(1), ...referencias(20, 100_000, "beleza")]);
    assert.equal((await varrer(base)).sinais, 0);
  });

  it("a `outra` e uma categoria fora da lista não se avaliam nem são referência", async () => {
    assert.ok((CATEGORIAS_DE_PRODUTO as readonly string[]).includes("outra"));
    const outra = new BaseFalsa([alvo(1, "outra"), ...referencias(20, 100_000, "outra")]);
    assert.equal((await varrer(outra)).sinais, 0);
    const fora = new BaseFalsa([alvo(1, "inventada"), ...referencias(20, 100_000, "inventada")]);
    assert.equal((await varrer(fora)).sinais, 0);
  });
});

describe("preço anómalo: o sinal", () => {
  it("doze SKUs anómalos de uma loja são um sinal, com a contagem, a fonte e a versão — e mais nada", async () => {
    const doze = Array.from({ length: 12 }, (_, i) => alvo(1, "moda", `alvo-${i}`));
    const base = new BaseFalsa([...doze, ...referencias(21, 100_000)]);
    assert.equal((await varrer(base)).sinais, 1);
    assert.equal(base.gravados.length, 1);
    assert.deepEqual(base.gravados[0]?.detalhe, {
      contagem: 12,
      fonte: FONTE_DAS_REFERENCIAS,
      versao_politica: POLITICA_DE_RISCO.versao,
    });
    assert.equal(FONTE_DAS_REFERENCIAS, "plataforma/1");
    // Nem o tenant das referências, nem um preço, nem a mediana.
    const texto = JSON.stringify(base.gravados[0]);
    assert.doesNotMatch(texto, new RegExp(`${B}|${C}|${D}`));
    assert.doesNotMatch(texto, /100000/);
  });

  it("a chave é a da janela de 30 dias da loja: as anomalias de várias categorias somam-se num sinal", async () => {
    assert.equal(DIAS_DA_JANELA_DO_PRECO, 30);
    assert.equal(refDoPreco(A, AGORA), refDaJanela(A, "preco_anomalo", AGORA, 30));
    const base = new BaseFalsa([alvo(1), alvo(1, "beleza", "b"), ...referencias(20, 100_000), ...referencias(20, 100_000, "beleza")]);
    await varrer(base);
    assert.equal(base.gravados.length, 1);
    assert.equal(base.gravados[0]?.ref, refDoPreco(A, AGORA));
    assert.equal(base.gravados[0]?.detalhe["contagem"], 2);
  });

  it("uma loja já sinalizada nesta janela não se grava outra vez; na janela seguinte sim", async () => {
    const ja = new BaseFalsa([alvo(1), ...referencias(20, 100_000)], [refDoPreco(A, AGORA)]);
    assert.equal((await varrer(ja)).sinais, 0);
    assert.equal(ja.gravados.length, 0);
    assert.deepEqual(ja.chavesPedidas, [[refDoPreco(A, AGORA)]], "só se perguntam as chaves desta volta");
    const depois = new Date(AGORA.getTime() + 31 * 86_400_000);
    assert.notEqual(refDoPreco(A, depois), refDoPreco(A, AGORA));
    const seguinte = new BaseFalsa([alvo(1), ...referencias(20, 100_000)], [refDoPreco(A, AGORA)]);
    assert.equal((await varrerPrecos(seguinte, { relogio: () => depois })).sinais, 1);
  });

  it("conta as ofertas publicadas sem categoria", async () => {
    assert.equal((await varrerPrecos(new BaseFalsa([], [], 7), { relogio: () => AGORA })).semCategoria, 7);
  });

  it("o peso é o 5 do KAM-097: com doze SKUs anómalos, o sinal sozinho não dá aviso nem limitação", async () => {
    assert.equal(POLITICA_DE_RISCO.pesos.preco_anomalo, 5);
    const s = new ServicoDeTrust({ repositorio: new RepositorioDeTrustEmMemoria(() => AGORA), relogio: () => AGORA });
    const r = await s.sinalizar({ tenantId: A, tipo: "preco_anomalo", refEvento: refDoPreco(A, AGORA), detalhe: { contagem: 12, fonte: FONTE_DAS_REFERENCIAS, versao_politica: "1.0.0" }, ocorridoEm: AGORA });
    assert.equal(r.sinal.severidade, "baixa");
    assert.deepEqual(r.sancoes, []);
  });
});

/** Um `pg.Pool` falso para o ciclo: cada ligação regista o que correu. */
class ConjuntoFalso implements ConjuntoSql {
  readonly consultas: { ligacao: string; texto: string; valores: readonly unknown[] }[] = [];
  #n = 0;
  readonly base: { query: BaseFalsa["query"] };
  constructor(base: { query: BaseFalsa["query"] }) {
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
  it("corre como `precos`, com a linha batch.run na mesma ligação e as não avaliadas no payload e no /metrics", async () => {
    const base = new BaseFalsa([alvo(1), ...referencias(20, 100_000), alvo(100_000, "beleza", "b"), ...ofertas(B, 20, 100, "beleza")], [], 3);
    const lote = new ConjuntoFalso(base);
    const metricas = new MetricasDoTrust();
    const servico = new ServicoDeTrust({ repositorio: new RepositorioDeTrustEmMemoria(() => AGORA), relogio: () => AGORA });
    const r = await new CicloDoTrust({ lote, servico, metricas, relogio: () => AGORA }).correr();
    assert.equal(r.feitas.precos, 1);
    assert.deepEqual(r.naoAvaliadas, { semCategoria: 3, poucasLojas: 1 });
    assert.ok(!r.falhas.includes("precos"));
    const leitura = lote.consultas.find((c) => c.texto === SQL_OFERTAS_COM_PRECO);
    const auditoria = lote.consultas.find((c) => c.texto === SQL_AUDITAR_VARREDURA && c.valores[1] === "precos");
    assert.ok(leitura !== undefined && auditoria !== undefined);
    assert.equal(auditoria.ligacao, leitura.ligacao);
    assert.equal(auditoria.valores[2], "precos:1:sem_categoria:3:poucas_lojas:1");
    const corpo = metricas.exposicao();
    assert.match(corpo, /^ts_varreduras_total\{varredura="precos",desfecho="concluida"\} 1$/m);
    assert.match(corpo, /^ts_sinais_total\{tipo="preco_anomalo"\} 1$/m);
    assert.match(corpo, /^# TYPE ts_ofertas_nao_avaliadas gauge$/m);
    assert.match(corpo, /^ts_ofertas_nao_avaliadas\{motivo="sem_categoria"\} 3$/m);
    assert.match(corpo, /^ts_ofertas_nao_avaliadas\{motivo="poucas_lojas"\} 1$/m);
  });

  it("o gauge nasce a zero e não muda numa volta em que os preços falham", async () => {
    const metricas = new MetricasDoTrust();
    assert.match(metricas.exposicao(), /^ts_ofertas_nao_avaliadas\{motivo="sem_categoria"\} 0$/m);
    assert.match(metricas.exposicao(), /^ts_ofertas_nao_avaliadas\{motivo="poucas_lojas"\} 0$/m);
    const base = new BaseFalsa([], [], 4);
    const falha = {
      async query(sql: string, p: readonly unknown[] = []) {
        if (sql === SQL_OFERTAS_SEM_CATEGORIA) throw new Error("base em baixo");
        return base.query(sql, p);
      },
    };
    const lote = new ConjuntoFalso(falha);
    const servico = new ServicoDeTrust({ repositorio: new RepositorioDeTrustEmMemoria(() => AGORA), relogio: () => AGORA });
    const r = await new CicloDoTrust({ lote, servico, metricas, relogio: () => AGORA }).correr();
    assert.ok(r.falhas.includes("precos"));
    assert.equal(r.naoAvaliadas, undefined);
    assert.match(metricas.exposicao(), /^ts_ofertas_nao_avaliadas\{motivo="sem_categoria"\} 0$/m);
  });
});
