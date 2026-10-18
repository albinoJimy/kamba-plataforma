/**
 * TEN: entitlements, limites, a matriz do §7.2 e o *middleware* (KAM-009).
 *
 * Aqui prova-se o que e **logica**: que SQL corre e com que parametros, o que
 * a biblioteca faz com cada resposta da base, a matriz celula a celula, o TTL
 * da cache e o que o *middleware* devolve.
 *
 * O que **nao** se prova aqui, e onde se prova: que 1 000 chamadas paralelas
 * contra um limite de 100 aceitam exactamente 100 (criterio 3), que repetir a
 * `idempotencyKey` nao consome duas vezes (criterio 4) e que o mes fecha as
 * 00:00 de `Africa/Luanda` (criterio 5) e tudo SQL — vive em
 * `platform.ten_consumir`, da revisao `0007`, e prova-se contra um PostgreSQL
 * real no gate 8. Uma base falsa devolve o que se lhe mandou devolver; um
 * teste de atomicidade sobre ela nao prova atomicidade nenhuma, prova a
 * fixture. O que estes testes garantem e que **a biblioteca chama a regra e
 * nao escreve outra**.
 *
 * A base falsa regista as instrucoes pela ordem em que as recebe: e essa lista
 * que torna a ordem verificavel, e e o mesmo padrao do
 * `eventos.consumo.test.ts`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeEach, describe, it } from "node:test";

import {
  ACCOES,
  CABECALHO_DE_IDEMPOTENCIA,
  CODIGO_ENTITLEMENT_HTTP,
  CODIGO_ENTITLEMENT_TOOL,
  CODIGO_LIMITE,
  CacheDeEntitlements,
  ChaveDeIdempotenciaInvalidaError,
  type ClienteSql,
  ESTADOS_DO_CANAL,
  ESTADOS_DO_TENANT,
  EstadoDesconhecidoError,
  ETIQUETA,
  EtiquetaInvalidaError,
  HTTP_ENTITLEMENT,
  HTTP_LIMITE,
  MAXIMO_DE_SERIES,
  METRICA_ENTITLEMENT_NEGADO,
  METRICA_LIMITE_NEGADO,
  METRICAS,
  MetricasDoTen,
  NOME_CANONICO,
  NomeInvalidoError,
  QuantidadeInvalidaError,
  REGIMES,
  REGIMES_E_ACCOES,
  REGIME_DO_CANAL,
  REGIME_DO_TENANT,
  RespostaIlegivelError,
  SQL_CONSUMIR,
  SQL_ENTITLEMENT,
  SQL_PERIODO,
  TTL_POR_OMISSAO_MS,
  agoraMs,
  checkEntitlement,
  consumeLimit,
  exigirNome,
  guardaHttp,
  inteiro,
  maisRestritivo,
  periodo,
  regimeDe,
  tenantGate,
} from "../src/ten/index.ts";
import { ContextoEmFaltaError, TenantInvalidoError } from "../src/tenant_guard/index.ts";

const A = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const B = "7a2d5b11-9c33-4f07-8e21-0c5d9a3b7e14";

/** Uma linha de `SQL_ENTITLEMENT` como o PostgreSQL a devolve. */
function linhaDeEntitlement(
  parcial: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    estado_tenant: "ativo",
    tem_linha: true,
    ativo: true,
    permitido: true,
    ...parcial,
  };
}

/** Uma linha de `platform.ten_consumir`. Os `bigint` vem como texto, do `pg`. */
function linhaDeConsumo(
  parcial: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return { aceite: true, valor: "1", repetido: false, limite: "100", ...parcial };
}

class BaseFalsa implements ClienteSql {
  readonly chamadas: { sql: string; parametros: readonly unknown[] }[] = [];
  readonly respostas: Record<string, unknown>[][] = [];

  responder(linhas: Record<string, unknown>[]): this {
    this.respostas.push(linhas);
    return this;
  }

  async query(
    sql: string,
    parametros: readonly unknown[] = [],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }> {
    this.chamadas.push({ sql, parametros });
    const rows = this.respostas.shift() ?? [];
    return { rows, rowCount: rows.length };
  }
}

let metricas: MetricasDoTen;

beforeEach(() => {
  metricas = new MetricasDoTen();
  METRICAS.repor();
});

describe("checkEntitlement — falha fechada (criterio 2)", () => {
  it("permite quando a base diz que permite, e corre o SQL do modulo", async () => {
    const bd = new BaseFalsa().responder([linhaDeEntitlement()]);
    const decisao = await checkEntitlement(bd, A, "vendedor", { metricas });
    assert.equal(decisao.permitido, true);
    assert.equal(decisao.motivo, null);
    assert.equal(decisao.modulo, "vendedor");
    assert.equal(decisao.estadoTenant, "ativo");
    assert.deepEqual(bd.chamadas, [{ sql: SQL_ENTITLEMENT, parametros: [A, "vendedor"] }]);
    assert.deepEqual(metricas.ler(), {});
  });

  it("zero linhas nega com `sem_tenant` — e o caso da RLS de outro tenant", async () => {
    const bd = new BaseFalsa().responder([]);
    const decisao = await checkEntitlement(bd, A, "vendedor", { metricas });
    assert.equal(decisao.permitido, false);
    assert.equal(decisao.motivo, "sem_tenant");
    assert.equal(decisao.estadoTenant, null);
    assert.deepEqual(metricas.ler(), { [`${METRICA_ENTITLEMENT_NEGADO}:vendedor`]: 1 });
  });

  it("sem linha de entitlement nega com `sem_entitlement`", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeEntitlement({ tem_linha: false, ativo: false, permitido: false }),
    ]);
    const decisao = await checkEntitlement(bd, A, "servicos", { metricas });
    assert.equal(decisao.motivo, "sem_entitlement");
  });

  it("`ativo = false` nega com `entitlement_inactivo`", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeEntitlement({ ativo: false, permitido: false }),
    ]);
    const decisao = await checkEntitlement(bd, A, "servicos", { metricas });
    assert.equal(decisao.motivo, "entitlement_inactivo");
  });

  it("entitlement activo e tenant suspenso nega com `estado_do_tenant`", async () => {
    // Quem decidiu foi o SQL: a coluna `permitido` veio falsa com `ativo`
    // verdadeiro. A biblioteca nao tem a lista dos tres estados.
    const bd = new BaseFalsa().responder([
      linhaDeEntitlement({ estado_tenant: "suspenso", permitido: false }),
    ]);
    const decisao = await checkEntitlement(bd, A, "vendedor", { metricas });
    assert.equal(decisao.motivo, "estado_do_tenant");
    assert.equal(decisao.ativo, true);
  });

  it("le os booleanos de um controlador que os devolve como texto", async () => {
    const bd = new BaseFalsa().responder([
      { estado_tenant: "ativo", tem_linha: "t", ativo: "true", permitido: "t" },
    ]);
    const decisao = await checkEntitlement(bd, A, "vendedor", { metricas });
    assert.equal(decisao.permitido, true);
  });

  it("um estado que nao e texto nao vira estado", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeEntitlement({ estado_tenant: 7, permitido: false, ativo: false }),
    ]);
    const decisao = await checkEntitlement(bd, A, "vendedor", { metricas });
    assert.equal(decisao.estadoTenant, null);
  });

  it("conta na instancia global quando nao lhe dao outra", async () => {
    const bd = new BaseFalsa().responder([]);
    await checkEntitlement(bd, A, "vendedor");
    assert.deepEqual(METRICAS.ler(), { [`${METRICA_ENTITLEMENT_NEGADO}:vendedor`]: 1 });
  });

  it("recusa um tenant que nao e UUID canonico, antes de tocar na base", async () => {
    const bd = new BaseFalsa();
    await assert.rejects(() => checkEntitlement(bd, "nao-e-uuid", "vendedor"), TenantInvalidoError);
    await assert.rejects(() => checkEntitlement(bd, "", "vendedor"), ContextoEmFaltaError);
    assert.deepEqual(bd.chamadas, []);
  });

  it("recusa um modulo que nao casa a gramatica", async () => {
    const bd = new BaseFalsa();
    await assert.rejects(() => checkEntitlement(bd, A, "Vendedor"), NomeInvalidoError);
    await assert.rejects(() => checkEntitlement(bd, A, 7), NomeInvalidoError);
    assert.deepEqual(bd.chamadas, []);
  });
});

describe("a cache — TTL e isolamento (criterio 6)", () => {
  it("a segunda leitura nao volta a base", async () => {
    const cache = new CacheDeEntitlements();
    const bd = new BaseFalsa().responder([linhaDeEntitlement()]);
    await checkEntitlement(bd, A, "vendedor", { cache, metricas });
    await checkEntitlement(bd, A, "vendedor", { cache, metricas });
    assert.equal(bd.chamadas.length, 1);
  });

  it("**nunca devolve dados de outro tenant** — teste cruzado", async () => {
    const cache = new CacheDeEntitlements();
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeEntitlement({ permitido: false, ativo: false, tem_linha: false })]);
    const deA = await checkEntitlement(bd, A, "vendedor", { cache, metricas });
    const deB = await checkEntitlement(bd, B, "vendedor", { cache, metricas });
    assert.equal(deA.permitido, true);
    assert.equal(deB.permitido, false);
    // Duas idas a base: a entrada de A nao serviu B.
    assert.equal(bd.chamadas.length, 2);
    assert.deepEqual(bd.chamadas[0]?.parametros, [A, "vendedor"]);
    assert.deepEqual(bd.chamadas[1]?.parametros, [B, "vendedor"]);
    assert.equal(cache.ler(B, "vendedor")?.permitido, false);
    assert.equal(cache.ler(A, "vendedor")?.permitido, true);
  });

  it("duas escritas do mesmo tenant sao a mesma chave", () => {
    const cache = new CacheDeEntitlements();
    const decisao = {
      modulo: "vendedor",
      permitido: true,
      estadoTenant: "ativo",
      ativo: true,
      motivo: null,
    } as const;
    cache.guardar(A, "vendedor", decisao, 0);
    assert.equal(cache.ler(A.toUpperCase(), "vendedor", 1)?.permitido, true);
    assert.equal(cache.tamanho, 1);
  });

  it("um modulo diferente e uma entrada diferente", () => {
    const cache = new CacheDeEntitlements();
    const decisao = {
      modulo: "vendedor",
      permitido: true,
      estadoTenant: "ativo",
      ativo: true,
      motivo: null,
    } as const;
    cache.guardar(A, "vendedor", decisao, 0);
    assert.equal(cache.ler(A, "servicos", 1), undefined);
  });

  it("a entrada morre ao fim do TTL, e o TTL por omissao e 60 s", () => {
    assert.equal(TTL_POR_OMISSAO_MS, 60_000);
    const cache = new CacheDeEntitlements();
    const decisao = {
      modulo: "vendedor",
      permitido: true,
      estadoTenant: "ativo",
      ativo: true,
      motivo: null,
    } as const;
    cache.guardar(A, "vendedor", decisao, 0);
    assert.notEqual(cache.ler(A, "vendedor", 59_999), undefined);
    assert.equal(cache.ler(A, "vendedor", 60_000), undefined);
    // E a entrada expirada sai do mapa, nao fica a ocupar lugar.
    assert.equal(cache.tamanho, 0);
  });

  it("depois do TTL a biblioteca volta a base — e assim que a alteracao aparece", async () => {
    const cache = new CacheDeEntitlements(10);
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeEntitlement({ ativo: false, permitido: false })]);
    assert.equal((await checkEntitlement(bd, A, "vendedor", { cache, metricas })).permitido, true);
    // O `ler` com relogio explicito deita fora a entrada: e o que a expiracao faz.
    assert.equal(cache.ler(A, "vendedor", agoraMs() + 1_000), undefined);
    assert.equal((await checkEntitlement(bd, A, "vendedor", { cache, metricas })).permitido, false);
    assert.equal(bd.chamadas.length, 2);
  });

  it("uma recusa em cache continua a contar na metrica", async () => {
    const cache = new CacheDeEntitlements();
    const bd = new BaseFalsa().responder([
      linhaDeEntitlement({ ativo: false, permitido: false }),
    ]);
    await checkEntitlement(bd, A, "vendedor", { cache, metricas });
    await checkEntitlement(bd, A, "vendedor", { cache, metricas });
    assert.deepEqual(metricas.ler(), { [`${METRICA_ENTITLEMENT_NEGADO}:vendedor`]: 2 });
    assert.equal(bd.chamadas.length, 1);
  });

  it("`invalidar` apaga so as entradas desse tenant", () => {
    const cache = new CacheDeEntitlements();
    const decisao = {
      modulo: "x",
      permitido: true,
      estadoTenant: "ativo",
      ativo: true,
      motivo: null,
    } as const;
    cache.guardar(A, "vendedor", decisao, 0);
    cache.guardar(A, "servicos", decisao, 0);
    cache.guardar(B, "vendedor", decisao, 0);
    cache.invalidar(A);
    assert.equal(cache.tamanho, 1);
    assert.notEqual(cache.ler(B, "vendedor", 1), undefined);
  });

  it("`repor` esvazia tudo", () => {
    const cache = new CacheDeEntitlements();
    const decisao = {
      modulo: "x",
      permitido: true,
      estadoTenant: "ativo",
      ativo: true,
      motivo: null,
    } as const;
    cache.guardar(A, "vendedor", decisao, 0);
    cache.repor();
    assert.equal(cache.tamanho, 0);
  });

  it("acima do maximo deita fora primeiro as expiradas e depois as mais antigas", () => {
    const cache = new CacheDeEntitlements(1_000, 2);
    const decisao = {
      modulo: "x",
      permitido: true,
      estadoTenant: "ativo",
      ativo: true,
      motivo: null,
    } as const;
    cache.guardar(A, "um", decisao, 0);
    cache.guardar(A, "dois", decisao, 0);
    // Em t = 2 000 as duas ja expiraram: a terceira entra sem despejar vivas.
    cache.guardar(A, "tres", decisao, 2_000);
    assert.equal(cache.tamanho, 1);
    // Agora tres vivas para dois lugares: sai a primeira a entrar.
    cache.guardar(A, "quatro", decisao, 2_000);
    cache.guardar(A, "cinco", decisao, 2_000);
    assert.equal(cache.tamanho, 2);
    assert.equal(cache.ler(A, "tres", 2_001), undefined);
    assert.notEqual(cache.ler(A, "cinco", 2_001), undefined);
  });

  it("um TTL ou um maximo absurdos sao recusados a construcao", () => {
    assert.throws(() => new CacheDeEntitlements(0), RangeError);
    assert.throws(() => new CacheDeEntitlements(Number.NaN), RangeError);
    assert.throws(() => new CacheDeEntitlements(60_000, 0), RangeError);
    assert.throws(() => new CacheDeEntitlements(60_000, 1.5), RangeError);
  });

  it("o relogio por omissao e monotonico e anda para a frente", () => {
    const antes = agoraMs();
    assert.equal(Number.isFinite(antes), true);
    assert.equal(agoraMs() >= antes, true);
  });
});

describe("consumeLimit — chama a regra, nao a reescreve (criterios 3 e 4)", () => {
  it("corre `SQL_CONSUMIR` com os seis argumentos pela ordem da `0007`", async () => {
    const bd = new BaseFalsa().responder([linhaDeConsumo()]);
    const quando = new Date("2026-11-30T22:59:59.000Z");
    await consumeLimit(bd, A, "msgs_ai_mes", 1, "k-1", {
      limite: 50,
      agora: quando,
      metricas,
    });
    assert.deepEqual(bd.chamadas, [
      { sql: SQL_CONSUMIR, parametros: [A, "msgs_ai_mes", 1, "k-1", 50, quando] },
    ]);
  });

  it("sem tecto de quem chama e sem relogio passa `null` nos dois", async () => {
    const bd = new BaseFalsa().responder([linhaDeConsumo()]);
    await consumeLimit(bd, A, "msgs_ai_mes", 2, "k-2", { metricas });
    assert.deepEqual(bd.chamadas[0]?.parametros, [A, "msgs_ai_mes", 2, "k-2", null, null]);
  });

  it("aceite: le os `bigint` que o `pg` devolve como texto", async () => {
    const bd = new BaseFalsa().responder([linhaDeConsumo({ valor: "42", limite: "100" })]);
    const consumo = await consumeLimit(bd, A, "msgs_ai_mes", 1, "k", { metricas });
    assert.deepEqual(consumo, {
      aceite: true,
      valor: 42,
      repetido: false,
      limite: 100,
      motivo: null,
    });
    assert.deepEqual(metricas.ler(), {});
  });

  it("repetido: aceite, sem consumir, e nada conta", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeConsumo({ aceite: true, repetido: true, valor: "1" }),
    ]);
    const consumo = await consumeLimit(bd, A, "msgs_ai_mes", 1, "k", { metricas });
    assert.equal(consumo.repetido, true);
    assert.equal(consumo.aceite, true);
    assert.equal(consumo.motivo, null);
    assert.deepEqual(metricas.ler(), {});
  });

  it("tecto excedido: nega, e conta `ten_limit_denied_total{key}`", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeConsumo({ aceite: false, repetido: false, valor: "100", limite: "100" }),
    ]);
    const consumo = await consumeLimit(bd, A, "msgs_ai_mes", 1, "k", { metricas });
    assert.equal(consumo.aceite, false);
    assert.equal(consumo.motivo, "limite_excedido");
    assert.deepEqual(metricas.ler(), { [`${METRICA_LIMITE_NEGADO}:msgs_ai_mes`]: 1 });
  });

  it("`limite = NULL` e falta de entitlement, e nao tecto excedido", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeConsumo({ aceite: false, valor: "0", limite: null }),
    ]);
    const consumo = await consumeLimit(bd, A, "msgs_ai_mes", 1, "k", { metricas });
    assert.equal(consumo.limite, null);
    assert.equal(consumo.motivo, "sem_entitlement");
    // Sem modulo nao ha etiqueta possivel: nao se inventa uma.
    assert.deepEqual(metricas.ler(), {});
  });

  it("com o modulo, a falta de entitlement conta no contador do modulo", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeConsumo({ aceite: false, valor: "0", limite: null }),
    ]);
    await consumeLimit(bd, A, "msgs_ai_mes", 1, "k", { modulo: "vendedor", metricas });
    assert.deepEqual(metricas.ler(), { [`${METRICA_ENTITLEMENT_NEGADO}:vendedor`]: 1 });
  });

  it("recusa quantidades que nao sao inteiros positivos, sem ir a base", async () => {
    const bd = new BaseFalsa();
    for (const mau of [0, -1, 1.5, "1", Number.NaN]) {
      await assert.rejects(
        () => consumeLimit(bd, A, "msgs_ai_mes", mau, "k"),
        QuantidadeInvalidaError,
      );
    }
    assert.deepEqual(bd.chamadas, []);
  });

  it("recusa um tecto de quem chama negativo ou fraccionario", async () => {
    const bd = new BaseFalsa();
    await assert.rejects(
      () => consumeLimit(bd, A, "msgs_ai_mes", 1, "k", { limite: -1 }),
      QuantidadeInvalidaError,
    );
    await assert.rejects(
      () => consumeLimit(bd, A, "msgs_ai_mes", 1, "k", { limite: 0.5 }),
      QuantidadeInvalidaError,
    );
  });

  it("recusa uma chave de idempotencia vazia", async () => {
    const bd = new BaseFalsa();
    await assert.rejects(
      () => consumeLimit(bd, A, "msgs_ai_mes", 1, "   "),
      ChaveDeIdempotenciaInvalidaError,
    );
    await assert.rejects(
      () => consumeLimit(bd, A, "msgs_ai_mes", 1, 7),
      ChaveDeIdempotenciaInvalidaError,
    );
  });

  it("recusa uma chave de limite que nao casa a gramatica", async () => {
    const bd = new BaseFalsa();
    await assert.rejects(() => consumeLimit(bd, A, "Msgs", 1, "k"), NomeInvalidoError);
  });

  it("zero linhas da funcao e erro, e nunca «aceite»", async () => {
    const bd = new BaseFalsa().responder([]);
    await assert.rejects(
      () => consumeLimit(bd, A, "msgs_ai_mes", 1, "k"),
      RespostaIlegivelError,
    );
  });
});

describe("a leitura de inteiros — um tecto mal lido e dinheiro errado", () => {
  it("aceita numero, texto decimal e bigint dentro do seguro", () => {
    assert.equal(inteiro("x", 7), 7);
    assert.equal(inteiro("x", "-12"), -12);
    assert.equal(inteiro("x", 9n), 9);
  });

  it("recusa o que nao se consegue ler sem adivinhar", () => {
    for (const mau of [1.5, "1.5", "", null, undefined, {}, true]) {
      assert.throws(() => inteiro("x", mau), RespostaIlegivelError);
    }
  });

  it("recusa inteiros acima do seguro em vez de os arredondar", () => {
    assert.throws(() => inteiro("x", "9007199254740993"), RespostaIlegivelError);
    assert.throws(() => inteiro("x", 2n ** 62n), RespostaIlegivelError);
    assert.throws(() => inteiro("x", -(2n ** 62n)), RespostaIlegivelError);
  });
});

describe("periodo — pergunta-se a base, nao se calcula", () => {
  it("passa o instante e devolve a data em ISO", async () => {
    const bd = new BaseFalsa().responder([{ periodo: new Date("2026-11-01T00:00:00Z") }]);
    const quando = new Date("2026-11-30T22:59:59.000Z");
    assert.equal(await periodo(bd, quando), "2026-11-01");
    assert.deepEqual(bd.chamadas, [{ sql: SQL_PERIODO, parametros: [quando] }]);
  });

  it("aceita a data ja como texto (e o que alguns controladores dao)", async () => {
    const bd = new BaseFalsa().responder([{ periodo: "2026-12-01" }]);
    assert.equal(await periodo(bd), "2026-12-01");
    assert.deepEqual(bd.chamadas[0]?.parametros, [null]);
  });

  it("uma resposta que nao e data levanta", async () => {
    const bd = new BaseFalsa().responder([{ periodo: 7 }]);
    await assert.rejects(() => periodo(bd), RespostaIlegivelError);
  });
});

describe("o SQL — a regra vive na `0007`, e nao aqui", () => {
  const fonte = readFileSync(new URL("../src/ten/consultas.ts", import.meta.url), "utf8");

  it("chama as duas funcoes da revisao `0007` pelo nome", () => {
    assert.match(SQL_PERIODO, /platform\.ten_periodo\(\$1\)/);
    assert.match(SQL_CONSUMIR, /platform\.ten_consumir\(\$1, \$2, \$3, \$4, \$5,/);
  });

  it("os marcadores aparecem por ordem ascendente — o espelho e posicional", () => {
    for (const sql of [SQL_PERIODO, SQL_ENTITLEMENT, SQL_CONSUMIR]) {
      const ordem = [...sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1]));
      assert.deepEqual(ordem, [...ordem].sort((a, b) => a - b), sql);
    }
  });

  it("nenhuma consulta soma, subtrai ou compara um limite", () => {
    for (const sql of [SQL_PERIODO, SQL_ENTITLEMENT, SQL_CONSUMIR]) {
      assert.doesNotMatch(sql, /\bvalor\s*[+-]/);
      assert.doesNotMatch(sql, /date_trunc/);
      assert.doesNotMatch(sql, /Africa\/Luanda/);
    }
  });

  it("a lista dos tres estados que negam existe no SQL, e so la", () => {
    assert.match(SQL_ENTITLEMENT, /'onboarding', 'suspenso', 'encerrado'/);
    const outros = [
      readFileSync(new URL("../src/ten/entitlements.ts", import.meta.url), "utf8"),
      readFileSync(new URL("../src/ten/middleware.ts", import.meta.url), "utf8"),
    ];
    for (const texto of outros) {
      const codigo = texto.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
      assert.doesNotMatch(codigo, /"onboarding"/, "a lista nao se repete em codigo");
    }
  });

  it("tudo parametrizado: nenhuma consulta interpola", () => {
    assert.doesNotMatch(fonte, /\$\{/);
  });
});

describe("tenantGate — a matriz do §7.2 com os dois estados (criterio 6)", () => {
  it("os dominios tem cinco e seis estados, e por isso e que a tabela nao chega", () => {
    assert.equal(ESTADOS_DO_TENANT.length, 5);
    assert.equal(ESTADOS_DO_CANAL.length, 6);
    assert.equal(REGIMES.length, 6);
    // `desligado` e so do canal; `onboarding` e so do tenant.
    assert.equal(ESTADOS_DO_TENANT.includes("desligado" as never), false);
    assert.equal(ESTADOS_DO_CANAL.includes("onboarding" as never), false);
  });

  it("cada estado dos dois dominios tem regime, e cada regime e uma linha", () => {
    for (const estado of ESTADOS_DO_TENANT) {
      assert.equal(REGIMES.includes(REGIME_DO_TENANT[estado]), true, estado);
    }
    for (const estado of ESTADOS_DO_CANAL) {
      assert.equal(REGIMES.includes(REGIME_DO_CANAL[estado]), true, estado);
    }
    assert.deepEqual(Object.keys(REGIMES_E_ACCOES).sort(), [...REGIMES].sort());
    for (const regime of REGIMES) {
      assert.deepEqual(Object.keys(REGIMES_E_ACCOES[regime]).sort(), [...ACCOES].sort());
    }
  });

  it("a ordem de precedencia e a proposta, e `maisRestritivo` segue-a", () => {
    assert.deepEqual(
      [...REGIMES],
      ["encerrado", "suspenso", "desligado", "pendente", "restrito", "ativo"],
    );
    assert.equal(maisRestritivo("ativo", "encerrado"), "encerrado");
    assert.equal(maisRestritivo("encerrado", "ativo"), "encerrado");
    assert.equal(maisRestritivo("restrito", "pendente"), "pendente");
    assert.equal(maisRestritivo("suspenso", "desligado"), "suspenso");
    assert.equal(maisRestritivo("ativo", "ativo"), "ativo");
  });

  it("o caso que a tabela de um parametro nao tem: tenant `ativo`, canal `desligado`", () => {
    const decisao = tenantGate("ativo", "desligado", "registar_entrada");
    assert.equal(decisao.regime, "desligado");
    assert.equal(decisao.permitido, false);
    assert.equal(decisao.origem, "canal");
  });

  it("o inverso: tenant `suspenso`, canal `ativo` — manda o tenant", () => {
    const decisao = tenantGate("suspenso", "ativo", "mensagem_estatica");
    assert.equal(decisao.regime, "suspenso");
    assert.equal(decisao.permitido, true);
    assert.equal(decisao.origem, "tenant");
  });

  it("os dois no mesmo regime dizem `ambos` — e `onboarding` cai em `pendente`", () => {
    const decisao = tenantGate("onboarding", "pendente", "registar_entrada");
    assert.equal(decisao.regime, "pendente");
    assert.equal(decisao.origem, "ambos");
    assert.equal(decisao.permitido, true);
  });

  it("as seis linhas do §7.2, celula a celula", () => {
    const esperado: Record<string, Record<string, boolean>> = {
      pendente: {
        registar_entrada: true,
        processar_entrada: false,
        responder_sessao: false,
        enviar_template_utilidade: false,
        enviar_template_marketing: false,
        mensagem_estatica: false,
        mensagem_de_teste: true,
      },
      ativo: {
        registar_entrada: true,
        processar_entrada: true,
        responder_sessao: true,
        enviar_template_utilidade: true,
        enviar_template_marketing: true,
        mensagem_estatica: true,
        mensagem_de_teste: true,
      },
      restrito: {
        registar_entrada: true,
        processar_entrada: true,
        responder_sessao: true,
        enviar_template_utilidade: false,
        enviar_template_marketing: false,
        mensagem_estatica: true,
        mensagem_de_teste: false,
      },
      desligado: {
        registar_entrada: false,
        processar_entrada: false,
        responder_sessao: false,
        enviar_template_utilidade: false,
        enviar_template_marketing: false,
        mensagem_estatica: false,
        mensagem_de_teste: false,
      },
      suspenso: {
        registar_entrada: true,
        processar_entrada: false,
        responder_sessao: false,
        enviar_template_utilidade: false,
        enviar_template_marketing: false,
        mensagem_estatica: true,
        mensagem_de_teste: false,
      },
      encerrado: {
        registar_entrada: true,
        processar_entrada: false,
        responder_sessao: false,
        enviar_template_utilidade: false,
        enviar_template_marketing: false,
        mensagem_estatica: false,
        mensagem_de_teste: false,
      },
    };
    for (const regime of REGIMES) {
      for (const accao of ACCOES) {
        assert.equal(
          REGIMES_E_ACCOES[regime][accao],
          esperado[regime]?.[accao],
          `${regime} × ${accao}`,
        );
      }
    }
  });

  it("os exemplos que o criterio 6 nomeia", () => {
    // «`restrito` nao envia marketing»
    assert.equal(
      tenantGate("restrito", "ativo", "enviar_template_marketing").permitido,
      false,
    );
    // «`suspenso` so mensagem estatica»
    assert.equal(tenantGate("suspenso", "ativo", "mensagem_estatica").permitido, true);
    assert.equal(tenantGate("suspenso", "ativo", "responder_sessao").permitido, false);
    // «`encerrado` descarta» — regista a entrada e mais nada.
    assert.equal(tenantGate("encerrado", "ativo", "registar_entrada").permitido, true);
    for (const accao of ACCOES) {
      if (accao === "registar_entrada") continue;
      assert.equal(tenantGate("encerrado", "ativo", accao).permitido, false, accao);
    }
  });

  it("todos os 30 pares de estados dao um regime conhecido", () => {
    let pares = 0;
    for (const t of ESTADOS_DO_TENANT) {
      for (const c of ESTADOS_DO_CANAL) {
        assert.equal(REGIMES.includes(regimeDe(t, c)), true, `${t}/${c}`);
        pares += 1;
      }
    }
    assert.equal(pares, 30);
  });

  it("um estado ou uma accao fora da lista levanta — nao se adivinha", () => {
    assert.throws(() => tenantGate("pausado", "ativo", "registar_entrada"), EstadoDesconhecidoError);
    assert.throws(() => tenantGate("ativo", "revogado", "registar_entrada"), EstadoDesconhecidoError);
    assert.throws(() => tenantGate("ativo", "ativo", "fazer_tudo"), EstadoDesconhecidoError);
    assert.throws(() => tenantGate(null, "ativo", "registar_entrada"), EstadoDesconhecidoError);
    assert.throws(() => tenantGate("ativo", 7, "registar_entrada"), EstadoDesconhecidoError);
    assert.throws(() => tenantGate("ativo", "ativo", 7), EstadoDesconhecidoError);
  });
});

describe("as metricas — nenhuma etiqueta leva identificadores", () => {
  it("um `tenant_id` nao passa a gramatica", () => {
    assert.equal(ETIQUETA.test(A), false);
    assert.throws(() => metricas.contar(METRICA_LIMITE_NEGADO, A), EtiquetaInvalidaError);
    assert.throws(
      () => metricas.contar(METRICA_ENTITLEMENT_NEGADO, A),
      EtiquetaInvalidaError,
    );
  });

  it("recusa etiquetas mal formadas e metricas desconhecidas", () => {
    for (const ma of ["", "A", "1msgs", "msgs-ai", "x".repeat(64), 7 as never]) {
      assert.throws(() => metricas.contar(METRICA_LIMITE_NEGADO, ma), EtiquetaInvalidaError);
    }
    assert.throws(() => metricas.contar("outra_coisa_total", "x"), EtiquetaInvalidaError);
  });

  it("conta, soma e repoe", () => {
    metricas.contar(METRICA_LIMITE_NEGADO, "msgs_ai_mes");
    metricas.contar(METRICA_LIMITE_NEGADO, "msgs_ai_mes", 4);
    metricas.contar(METRICA_ENTITLEMENT_NEGADO, "vendedor");
    assert.deepEqual(metricas.ler(), {
      [`${METRICA_LIMITE_NEGADO}:msgs_ai_mes`]: 5,
      [`${METRICA_ENTITLEMENT_NEGADO}:vendedor`]: 1,
    });
    metricas.repor();
    assert.deepEqual(metricas.ler(), {});
  });

  it("tem tecto de series, e o tecto e por metrica", () => {
    for (let i = 0; i < MAXIMO_DE_SERIES; i += 1) {
      metricas.contar(METRICA_LIMITE_NEGADO, `chave_${i}`);
    }
    assert.throws(() => metricas.contar(METRICA_LIMITE_NEGADO, "mais_uma"), RangeError);
    // Uma serie que ja existe continua a poder contar.
    metricas.contar(METRICA_LIMITE_NEGADO, "chave_0");
    // E a outra metrica tem o seu proprio tecto.
    metricas.contar(METRICA_ENTITLEMENT_NEGADO, "vendedor");
  });

  it("a exposicao mostra as duas metricas, a zero quando ninguem foi recusado", () => {
    const texto = metricas.exposicao();
    assert.match(texto, /# TYPE ten_limit_denied_total counter/);
    assert.match(texto, /^ten_limit_denied_total 0$/m);
    assert.match(texto, /^ten_entitlement_denied_total 0$/m);
  });

  it("a exposicao escreve as etiquetas com o nome do criterio 7", () => {
    metricas.contar(METRICA_LIMITE_NEGADO, "msgs_ai_mes", 3);
    metricas.contar(METRICA_ENTITLEMENT_NEGADO, "vendedor");
    const texto = metricas.exposicao();
    assert.match(texto, /^ten_limit_denied_total\{key="msgs_ai_mes"\} 3$/m);
    assert.match(texto, /^ten_entitlement_denied_total\{modulo="vendedor"\} 1$/m);
    assert.doesNotMatch(texto, new RegExp(A));
  });
});

describe("o middleware HTTP — 403 e 429 (criterios 2, 3 e 7)", () => {
  const pedido = {
    metodo: "POST",
    caminho: "/v1/pedidos",
    cabecalhos: { "idempotency-key": "req-1" },
  };
  const contexto = { tenantId: A };

  it("deixa passar quando o entitlement permite e nao ha chave de limite", async () => {
    const bd = new BaseFalsa().responder([linhaDeEntitlement()]);
    const recusa = await guardaHttp(bd, pedido, contexto, { modulo: "vendedor", metricas });
    assert.equal(recusa, null);
    assert.equal(bd.chamadas.length, 1);
  });

  it("403 ENTITLEMENT_DISABLED quando o entitlement nega, e **sem consumir**", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeEntitlement({ ativo: false, permitido: false }),
    ]);
    const recusa = await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      chave: "msgs_ai_mes",
      metricas,
    });
    assert.deepEqual(recusa, {
      estado: HTTP_ENTITLEMENT,
      corpo: { error: CODIGO_ENTITLEMENT_HTTP, modulo: "vendedor" },
      cabecalhos: {},
    });
    assert.equal(HTTP_ENTITLEMENT, 403);
    // Uma so chamada: o consumo nao chegou a acontecer.
    assert.equal(bd.chamadas.length, 1);
  });

  it("429 LIMIT_EXCEEDED quando o tecto recusa", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo({ aceite: false, valor: "100", limite: "100" })]);
    const recusa = await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      chave: "msgs_ai_mes",
      quantidade: 1,
      metricas,
    });
    assert.deepEqual(recusa, {
      estado: HTTP_LIMITE,
      corpo: { error: CODIGO_LIMITE, key: "msgs_ai_mes" },
      cabecalhos: {},
    });
    assert.equal(HTTP_LIMITE, 429);
    assert.deepEqual(metricas.ler(), { [`${METRICA_LIMITE_NEGADO}:msgs_ai_mes`]: 1 });
  });

  it("`limite = NULL` no consumo da 403, e nao 429", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo({ aceite: false, valor: "0", limite: null })]);
    const recusa = await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      chave: "marcacoes_mes",
      metricas,
    });
    assert.equal(recusa?.estado, HTTP_ENTITLEMENT);
    assert.equal(recusa?.corpo.error, CODIGO_ENTITLEMENT_HTTP);
    assert.equal(recusa?.corpo.key, "marcacoes_mes");
  });

  it("deixa passar quando o consumo e aceite", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo()]);
    assert.equal(
      await guardaHttp(bd, pedido, contexto, {
        modulo: "vendedor",
        chave: "msgs_ai_mes",
        metricas,
      }),
      null,
    );
  });

  it("a chave de idempotencia sai do cabecalho, e o cabecalho e configuravel", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo()]);
    await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      chave: "msgs_ai_mes",
      metricas,
    });
    assert.equal(bd.chamadas[1]?.parametros[3], "req-1");
    assert.equal(CABECALHO_DE_IDEMPOTENCIA, "idempotency-key");

    const outro = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo()]);
    await guardaHttp(
      outro,
      { ...pedido, cabecalhos: { "x-pedido-id": "abc" } },
      contexto,
      {
        modulo: "vendedor",
        chave: "msgs_ai_mes",
        cabecalhoDeIdempotencia: "X-Pedido-Id",
        metricas,
      },
    );
    assert.equal(outro.chamadas[1]?.parametros[3], "abc");
  });

  it("a chave dada em opcoes ganha ao cabecalho (`02` §6.3)", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo()]);
    await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      chave: "msgs_ai_mes",
      idempotencyKey: "sha256-derivada",
      metricas,
    });
    assert.equal(bd.chamadas[1]?.parametros[3], "sha256-derivada");
  });

  it("sem chave de idempotencia nenhuma levanta — nao inventa um terceiro codigo", async () => {
    const bd = new BaseFalsa().responder([linhaDeEntitlement()]);
    await assert.rejects(
      () =>
        guardaHttp(bd, { ...pedido, cabecalhos: {} }, contexto, {
          modulo: "vendedor",
          chave: "msgs_ai_mes",
          metricas,
        }),
      ChaveDeIdempotenciaInvalidaError,
    );
  });

  it("passa o tecto de quem chama e o relogio ao consumo", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo()]);
    const quando = new Date("2026-12-01T00:00:00.000Z");
    await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      chave: "msgs_ai_mes",
      quantidade: 3,
      limite: 10,
      agora: quando,
      metricas,
    });
    assert.deepEqual(bd.chamadas[1]?.parametros, [
      A,
      "msgs_ai_mes",
      3,
      "req-1",
      10,
      quando,
    ]);
  });

  it("usa a cache que lhe derem", async () => {
    const cache = new CacheDeEntitlements();
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeEntitlement()]);
    await guardaHttp(bd, pedido, contexto, { modulo: "vendedor", cache, metricas });
    await guardaHttp(bd, pedido, contexto, { modulo: "vendedor", cache, metricas });
    assert.equal(bd.chamadas.length, 1);
  });

  it("funciona sem metricas proprias (usa a instancia do processo)", async () => {
    const bd = new BaseFalsa().responder([
      linhaDeEntitlement({ ativo: false, permitido: false }),
    ]);
    await guardaHttp(bd, pedido, contexto, { modulo: "vendedor" });
    assert.deepEqual(METRICAS.ler(), { [`${METRICA_ENTITLEMENT_NEGADO}:vendedor`]: 1 });
  });

  it("**o tenant vem do contexto e nao do pedido** (criterio 7)", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([linhaDeConsumo()]);
    // O cliente tenta dizer que e o B por todos os caminhos que um pedido tem.
    const hostil = {
      metodo: "POST",
      caminho: `/v1/pedidos?tenant_id=${B}`,
      cabecalhos: {
        "idempotency-key": "req-1",
        "x-tenant-id": B,
        "x-merchant-id": B,
        tenant_id: B,
      },
    };
    await guardaHttp(bd, hostil, { tenantId: A }, {
      modulo: "vendedor",
      chave: "msgs_ai_mes",
      metricas,
    });
    for (const chamada of bd.chamadas) {
      assert.equal(chamada.parametros[0], A, "o SQL correu com o tenant do contexto");
      assert.equal(JSON.stringify(chamada.parametros).includes(B), false);
    }
  });

  it("**o middleware nao le tenant nenhum do pedido** — lido da fonte", () => {
    const fonte = readFileSync(new URL("../src/ten/middleware.ts", import.meta.url), "utf8");
    const codigo = fonte.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    // So ha uma leitura de `pedido.` em todo o ficheiro, e e a do cabecalho de
    // idempotencia. Qualquer outra — `pedido.query`, `pedido.corpo`, um
    // `pedido.cabecalhos["x-tenant-id"]` — faz este teste falhar.
    const leituras = [...codigo.matchAll(/pedido\.(\w+)/g)].map((m) => m[1]);
    assert.deepEqual(leituras, ["cabecalhos"]);
    // E o tenant sai do contexto, numa linha so.
    assert.deepEqual(
      [...codigo.matchAll(/contexto\.(\w+)/g)].map((m) => m[1]),
      ["tenantId"],
    );
  });
});

describe("os codigos e a gramatica — o que esta em proposta fica dito", () => {
  it("os tres codigos sao os do ticket e os do `02` §6.5", () => {
    assert.equal(CODIGO_ENTITLEMENT_HTTP, "ENTITLEMENT_DISABLED");
    assert.equal(CODIGO_ENTITLEMENT_TOOL, "ENTITLEMENT_DENIED");
    assert.equal(CODIGO_LIMITE, "LIMIT_EXCEEDED");
    // Os dois nomes do entitlement sao diferentes de proposito: um e do
    // criterio 2 (proposta), o outro e do documento. Se alguem os unificar sem
    // decidir, este teste cai.
    assert.notEqual(CODIGO_ENTITLEMENT_HTTP, CODIGO_ENTITLEMENT_TOOL);
  });

  it("a proposta do TTL e dos estados HTTP esta escrita nos ficheiros", () => {
    const entitlements = readFileSync(
      new URL("../src/ten/entitlements.ts", import.meta.url),
      "utf8",
    );
    for (const frase of [
      "em proposta",
      "**Proposta**",
      // O catalogo nao tem `entitlement.*`: a visibilidade e so por TTL, e a
      // criacao do evento fica proposta e nao feita.
      "`entitlement.updated`",
    ]) {
      assert.ok(entitlements.includes(frase), frase);
    }
    const estados = readFileSync(new URL("../src/ten/estados.ts", import.meta.url), "utf8");
    assert.ok(estados.includes("**PROPOSTA**"));
    assert.ok(estados.includes("devolve-se ao dono do"));
  });

  it("`exigirNome` e `NOME_CANONICO` sao a gramatica do `CHECK` da base", () => {
    assert.equal(exigirNome("modulo", "msgs_ai_mes"), "msgs_ai_mes");
    assert.equal(NOME_CANONICO.test("valor_max_pedido_minor"), true);
    assert.equal(NOME_CANONICO.test("a"), false);
    assert.throws(() => exigirNome("modulo", "_x"), NomeInvalidoError);
  });
});
