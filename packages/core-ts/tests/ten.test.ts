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
  CATEGORIA_CONTADOR,
  CATEGORIA_TECTO_POR_JANELA,
  CATEGORIA_TECTO_POR_PEDIDO,
  CHAVES_DE_LIMITE,
  CODIGO_ENTITLEMENT_HTTP,
  CODIGO_ENTITLEMENT_TOOL,
  CODIGO_LIMITE,
  CacheDeEntitlements,
  ChaveDeEspecieErradaError,
  ChaveDeIdempotenciaInvalidaError,
  ChaveDesconhecidaError,
  type ClienteSql,
  ConflitoDeIdempotenciaError,
  ESTADOS_DO_CANAL,
  ESTADOS_DO_TENANT,
  EstadoDesconhecidoError,
  ETIQUETA,
  EtiquetaInvalidaError,
  HTTP_ENTITLEMENT,
  HTTP_LIMITE,
  HTTP_TECTO,
  LimiteIlegivelError,
  MARCA_DO_TECTO_ILEGIVEL,
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
  SQLSTATE_CONFLITO_DE_IDEMPOTENCIA,
  SQLSTATE_LIMITE_ILEGIVEL,
  SQL_CONSUMIR,
  SQL_ENTITLEMENT,
  SQL_PERIODO,
  SQL_TECTO,
  TTL_POR_OMISSAO_MS,
  agoraMs,
  checkCeiling,
  checkEntitlement,
  conflitoOuTecto,
  consumeLimit,
  derivarChaveDeIdempotencia,
  especieDaChave,
  exigirConsumivel,
  exigirNome,
  exigirTecto,
  guardaHttp,
  inteiro,
  maisRestritivo,
  periodo,
  regimeDe,
  sqlstateDe,
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

  it("sem instante corre o **mesmo** SQL, e o `coalesce` trata do `null`", async () => {
    // M3: era aqui que os dois lados divergiam. Sem `coalesce`, a funcao
    // recebia `NULL` e devolvia `NULL` — e um `null` em `rows[0].periodo`
    // levantava `RespostaIlegivelError` deste lado enquanto o Python
    // devolvia `None` em silencio. O `null` continua a ir; o que mudou e que
    // o SQL o converte em `now()` antes de chamar a funcao.
    const com = new BaseFalsa().responder([{ periodo: "2026-11-01" }]);
    await periodo(com, new Date("2026-11-30T22:59:59.000Z"));
    const sem = new BaseFalsa().responder([{ periodo: "2026-12-01" }]);
    await periodo(sem);
    assert.equal(com.chamadas[0]?.sql, sem.chamadas[0]?.sql);
    assert.equal(com.chamadas[0]?.sql, SQL_PERIODO);
    assert.match(SQL_PERIODO, /coalesce\(\$1, now\(\)\)/);
  });

  it("uma resposta que nao e data levanta", async () => {
    const bd = new BaseFalsa().responder([{ periodo: 7 }]);
    await assert.rejects(() => periodo(bd), RespostaIlegivelError);
  });
});

describe("o SQL — a regra vive na `0007`, e nao aqui", () => {
  const fonte = readFileSync(new URL("../src/ten/consultas.ts", import.meta.url), "utf8");

  it("chama as duas funcoes da revisao `0007` pelo nome", () => {
    assert.match(SQL_PERIODO, /platform\.ten_periodo\(coalesce\(\$1, now\(\)\)\)/);
    assert.match(SQL_CONSUMIR, /platform\.ten_consumir\(\$1, \$2, \$3, \$4, \$5,/);
  });

  it("os dois `coalesce` existem, e pela mesma razao", () => {
    // Era o M3: o `SQL_PERIODO` nao o tinha, `periodo()` sem instante mandava
    // `NULL` a funcao, e os dois lados tratavam o `NULL` de volta de maneira
    // diferente — `None` em silencio no Python, uma excepcao aqui.
    for (const sql of [SQL_PERIODO, SQL_CONSUMIR]) {
      assert.match(sql, /coalesce\(\$\d+, now\(\)\)/);
    }
    assert.match(fonte, /posicional/);
  });

  it("os marcadores aparecem por ordem ascendente — o espelho e posicional", () => {
    for (const sql of [SQL_PERIODO, SQL_ENTITLEMENT, SQL_CONSUMIR, SQL_TECTO]) {
      const ordem = [...sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1]));
      assert.deepEqual(ordem, [...ordem].sort((a, b) => a - b), sql);
    }
  });

  it("cada marcador aparece uma unica vez — a DB-API e posicional", () => {
    // Um `$2` repetido aqui vira dois `%s` do lado Python, e o espelho
    // passaria a precisar de mais um argumento para dizer o mesmo.
    for (const sql of [SQL_PERIODO, SQL_ENTITLEMENT, SQL_CONSUMIR, SQL_TECTO]) {
      const marcadores = [...sql.matchAll(/\$(\d+)/g)].map((m) => m[1]);
      assert.equal(new Set(marcadores).size, marcadores.length, sql);
    }
  });

  it("nenhuma consulta soma, subtrai ou acumula um contador", () => {
    for (const sql of [SQL_PERIODO, SQL_ENTITLEMENT, SQL_CONSUMIR, SQL_TECTO]) {
      assert.doesNotMatch(sql, /\bvalor\s*[+-]/);
      assert.doesNotMatch(sql, /date_trunc/);
      assert.doesNotMatch(sql, /Africa\/Luanda/);
    }
  });

  it("o `SQL_TECTO` e so uma chamada, e **nunca** escreve", () => {
    for (const proibido of [/INSERT/, /UPDATE/, /DELETE/, /ten_consumir/, /tenant_usage/]) {
      assert.doesNotMatch(SQL_TECTO, proibido);
    }
    // A regra do minimo **nao** esta aqui: esta na `platform.ten_tecto` da
    // revisao, que a `ten_consumir` tambem chama. A primeira versao desta
    // constante trazia o `min(...)` para a biblioteca, e era a unica consulta
    // do ficheiro a infringir o argumento do cabecalho.
    assert.match(SQL_TECTO, /platform\.ten_tecto\(\$1, \$2\)/);
    for (const fora of [/min\(/, /limites/, /platform\.entitlements/, /ativo/]) {
      assert.doesNotMatch(SQL_TECTO, fora);
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

describe("o registo de chaves — a especie e um facto, e nao uma convencao", () => {
  // Le-se o registo **do ficheiro**: era o `x-kamba-consumivel` que nada lia.
  const registo = JSON.parse(
    readFileSync(
      new URL("../../../registry/entitlement_keys.schema.json", import.meta.url),
      "utf8",
    ),
  ) as {
    properties: Record<string, { "x-kamba-categoria": string; "x-kamba-consumivel": boolean }>;
    "x-kamba-categorias": Record<string, string>;
  };

  it("as dez chaves sao as mesmas do registo", () => {
    const doRegisto = Object.keys(registo.properties).sort();
    assert.equal(doRegisto.length, 10);
    assert.deepEqual(Object.keys(CHAVES_DE_LIMITE).sort(), doRegisto);
  });

  it("a categoria e o `x-kamba-consumivel` vem do registo, chave a chave", () => {
    for (const [nome, propriedade] of Object.entries(registo.properties)) {
      const nossa = CHAVES_DE_LIMITE[nome];
      assert.equal(nossa?.nome, nome);
      assert.equal(nossa?.categoria, propriedade["x-kamba-categoria"], nome);
      assert.equal(nossa?.consumivel, propriedade["x-kamba-consumivel"], nome);
    }
  });

  it("as tres categorias sao as que o registo declara", () => {
    assert.deepEqual(Object.keys(registo["x-kamba-categorias"]).sort(), [
      CATEGORIA_CONTADOR,
      CATEGORIA_TECTO_POR_JANELA,
      CATEGORIA_TECTO_POR_PEDIDO,
    ].sort());
  });

  it("so os contadores sao consumiveis — cinco, tres e dois", () => {
    const contagem: Record<string, number> = {};
    for (const chave of Object.values(CHAVES_DE_LIMITE)) {
      assert.equal(chave.consumivel, chave.categoria === CATEGORIA_CONTADOR, chave.nome);
      contagem[chave.categoria] = (contagem[chave.categoria] ?? 0) + 1;
    }
    assert.deepEqual(contagem, {
      [CATEGORIA_CONTADOR]: 5,
      [CATEGORIA_TECTO_POR_PEDIDO]: 3,
      [CATEGORIA_TECTO_POR_JANELA]: 2,
    });
  });

  it("uma chave fora do registo nao se adivinha", () => {
    assert.throws(() => especieDaChave("msgs_ai_semana"), ChaveDesconhecidaError);
    assert.throws(() => especieDaChave("Msgs-AI"), NomeInvalidoError);
    // `constructor` e `tostring` casam a gramatica `^[a-z][a-z0-9_]{1,62}$` e
    // estao no **prototipo** de qualquer objecto: sem `Object.hasOwn`, a
    // consulta devolvia uma funcao e a chave passava por conhecida.
    for (const herdada of ["constructor", "tostring", "valueof"]) {
      assert.throws(() => especieDaChave(herdada), ChaveDesconhecidaError, herdada);
    }
  });
});

describe("a especie da chave — cada funcao recusa a pergunta da outra", () => {
  it("consumir um tecto levanta, e **sem tocar na base**", async () => {
    for (const chave of [
      "valor_max_pedido_minor",
      "manual_max_minor",
      "manual_dupla_acima_minor",
      "manual_daily_max_minor",
      "manual_max_por_contacto_24h",
    ]) {
      const bd = new BaseFalsa().responder([linhaDeConsumo()]);
      await assert.rejects(
        () => consumeLimit(bd, A, chave, 1, "k"),
        ChaveDeEspecieErradaError,
        chave,
      );
      assert.equal(bd.chamadas.length, 0, chave);
    }
  });

  it("perguntar «cabe?» a um balde levanta, e **sem tocar na base**", async () => {
    for (const chave of ["msgs_ai_mes", "marcacoes_mes", "imagens_mes"]) {
      const bd = new BaseFalsa().responder([{ tecto: "1" }]);
      await assert.rejects(
        () => checkCeiling(bd, A, chave, 1),
        ChaveDeEspecieErradaError,
        chave,
      );
      assert.equal(bd.chamadas.length, 0, chave);
    }
  });

  it("as duas chaves de janela nao tem caminho neste ticket, e dizem porque", async () => {
    // O agregado da janela vem de `manual_confirmations` (`04` §4.2 M-6),
    // que este ticket nao constroi. Recusa-se em vez de responder mal.
    for (const chave of ["manual_daily_max_minor", "manual_max_por_contacto_24h"]) {
      await assert.rejects(() => checkCeiling(new BaseFalsa(), A, chave, 1), (erro: unknown) => {
        assert.equal(erro instanceof ChaveDeEspecieErradaError, true);
        assert.match((erro as Error).message, /manual_confirmations/);
        return true;
      });
    }
  });

  it("as tres do tecto por pedido e os cinco baldes passam no seu caminho", () => {
    for (const chave of [
      "valor_max_pedido_minor",
      "manual_max_minor",
      "manual_dupla_acima_minor",
    ]) {
      assert.equal(exigirTecto(chave), chave);
    }
    for (const chave of [
      "msgs_ai_mes",
      "marcacoes_mes",
      "imagens_mes",
      "posts_mes",
      "orcamentos_mes",
    ]) {
      assert.equal(exigirConsumivel(chave), chave);
    }
  });
});

describe("checkCeiling — «este valor cabe?», e **nada** disto escreve", () => {
  it("corre o `SQL_TECTO` com o tenant e a chave, e nada mais", async () => {
    const bd = new BaseFalsa().responder([{ tecto: "5000000" }]);
    const tecto = await checkCeiling(bd, A, "valor_max_pedido_minor", 4_999_999);
    assert.deepEqual(bd.chamadas, [
      { sql: SQL_TECTO, parametros: [A, "valor_max_pedido_minor"] },
    ]);
    assert.deepEqual(tecto, {
      chave: "valor_max_pedido_minor",
      cabe: true,
      valor: 4_999_999,
      tecto: 5_000_000,
      motivo: null,
    });
  });

  it("o valor igual ao tecto cabe; um acima nao, e conta", async () => {
    assert.equal(
      (await checkCeiling(new BaseFalsa().responder([{ tecto: "100" }]), A, "manual_max_minor", 100))
        .cabe,
      true,
    );
    const bd = new BaseFalsa().responder([{ tecto: "100" }]);
    const tecto = await checkCeiling(bd, A, "manual_max_minor", 101, { metricas });
    assert.equal(tecto.cabe, false);
    assert.equal(tecto.motivo, "tecto_excedido");
    assert.deepEqual(metricas.ler(), { [`${METRICA_LIMITE_NEGADO}:manual_max_minor`]: 1 });
  });

  it("sem linha activa que declare a chave **nega** — falha fechada", async () => {
    const respostas: Record<string, unknown>[][] = [[{ tecto: null }], [{}], []];
    for (const resposta of respostas) {
      const tecto = await checkCeiling(
        new BaseFalsa().responder(resposta),
        A,
        "manual_max_minor",
        1,
      );
      assert.equal(tecto.cabe, false);
      assert.equal(tecto.tecto, null);
      assert.equal(tecto.motivo, "sem_entitlement");
    }
  });

  it("a falta conta no contador do modulo quando lho dizem", async () => {
    const bd = new BaseFalsa().responder([{ tecto: null }]);
    await checkCeiling(bd, A, "manual_max_minor", 1, { modulo: "vendedor", metricas });
    assert.deepEqual(metricas.ler(), { [`${METRICA_ENTITLEMENT_NEGADO}:vendedor`]: 1 });
  });

  it("um tecto ilegivel levanta em vez de adivinhar", async () => {
    await assert.rejects(
      () => checkCeiling(new BaseFalsa().responder([{ tecto: "cinco" }]), A, "manual_max_minor", 1),
      RespostaIlegivelError,
    );
  });

  it("zero cabe em qualquer tecto; negativo e fraccionario levantam", async () => {
    assert.equal(
      (await checkCeiling(new BaseFalsa().responder([{ tecto: "0" }]), A, "manual_max_minor", 0))
        .cabe,
      true,
    );
    for (const mau of [-1, 1.5, "10", null, undefined, true]) {
      await assert.rejects(
        () => checkCeiling(new BaseFalsa().responder([{ tecto: "10" }]), A, "manual_max_minor", mau),
        QuantidadeInvalidaError,
      );
    }
  });

  it("recusa um tenant que nao e UUID canonico, antes de tocar na base", async () => {
    const bd = new BaseFalsa().responder([{ tecto: "1" }]);
    await assert.rejects(
      () => checkCeiling(bd, "nao-e-uuid", "manual_max_minor", 1),
      TenantInvalidoError,
    );
    assert.equal(bd.chamadas.length, 0);
  });

  it("`manual_dupla_acima_minor`: `cabe = false` nao e uma recusa", () => {
    // O registo escreve-o: «o unico tecto por pedido cuja comparacao NAO
    // nega». Acima do limiar o pedido exige o segundo confirmador (`04` §4.2
    // M-5). A funcao devolve o facto; quem chama e que decide.
    assert.equal(CHAVES_DE_LIMITE.manual_dupla_acima_minor?.categoria, CATEGORIA_TECTO_POR_PEDIDO);
  });
});

describe("a chave de idempotencia derivada (C1)", () => {
  // O mesmo vector esta no `TestDerivacaoDaChaveDeIdempotencia` do Python, e
  // ha um teste de paridade que o confirma: e assim que os dois digests se
  // comparam sem correr os dois interpretes no mesmo processo.
  const VECTOR = "aecad9b30b59f9439b80d87246a2a8318a3b5f766e899faef810168f503e3df0";

  it("o vector conhecido", () => {
    assert.equal(
      derivarChaveDeIdempotencia("ten.v1", A, "vendedor", "msgs_ai_mes", "req-1"),
      VECTOR,
    );
  });

  it("e determinista, hexadecimal, e cada componente muda-a", () => {
    const base: string[] = ["ten.v1", A, "vendedor", "msgs_ai_mes", "x"];
    assert.equal(derivarChaveDeIdempotencia(...base), derivarChaveDeIdempotencia(...base));
    assert.match(derivarChaveDeIdempotencia(...base), /^[0-9a-f]{64}$/);
    const vistas = new Set([derivarChaveDeIdempotencia(...base)]);
    const trocas: string[] = [B, "servicos", "marcacoes_mes", "y"];
    for (const [indice, outro] of trocas.entries()) {
      const mudado = [...base];
      mudado[indice + 1] = outro;
      vistas.add(derivarChaveDeIdempotencia(...mudado));
    }
    assert.equal(vistas.size, 5);
  });

  it("o separador impede a colisao por concatenacao", () => {
    assert.notEqual(
      derivarChaveDeIdempotencia("ab", "c"),
      derivarChaveDeIdempotencia("a", "bc"),
    );
  });

  it("componentes vazios ou que nao sao texto levantam", () => {
    for (const maus of [[], [""], ["  "], ["a", null], ["a", 7]]) {
      assert.throws(
        () => derivarChaveDeIdempotencia(...maus),
        ChaveDeIdempotenciaInvalidaError,
      );
    }
  });
});

describe("o `KA002` da `0007` — um conflito do pedido, e nao um limite", () => {
  it("le o SQLSTATE das formas conhecidas, e nao inventa nenhuma", () => {
    assert.equal(sqlstateDe({ code: "KA002" }), "KA002");
    assert.equal(sqlstateDe({ sqlstate: "KA002" }), "KA002");
    assert.equal(sqlstateDe({ code: "nao-e-um-sqlstate" }), null);
    assert.equal(sqlstateDe(new Error("sem nada")), null);
    assert.equal(sqlstateDe(null), null);
    assert.equal(SQLSTATE_CONFLITO_DE_IDEMPOTENCIA, "KA002");
    assert.equal(SQLSTATE_LIMITE_ILEGIVEL, "22023");
  });

  it("o `KA002` vira `ConflitoDeIdempotenciaError`", async () => {
    const bd: ClienteSql = {
      async query() {
        const erro = new Error("conflito") as Error & { code: string };
        erro.code = "KA002";
        throw erro;
      },
    };
    await assert.rejects(
      () => consumeLimit(bd, A, "msgs_ai_mes", 1, "k"),
      (erro: unknown) => {
        assert.equal(erro instanceof ConflitoDeIdempotenciaError, true);
        // A mensagem nao repete a chave nem a quantidade (`OBS-I`).
        assert.doesNotMatch((erro as Error).message, /msgs_ai_mes/);
        return true;
      },
    );
  });

  it("os outros SQLSTATE sobem como vieram — so se traduz o que se reconhece", async () => {
    // O `22023` esta aqui de proposito: com uma mensagem que **nao** nomeia a
    // `ten_tecto` e a guarda de `p_agora` da `ten_consumir`, e essa nao e um
    // limite ilegivel. Ver o teste do `LimiteIlegivelError`.
    for (const estado of ["23514", "22023", "40001"]) {
      const bd: ClienteSql = {
        async query() {
          const erro = new Error("da base") as Error & { code: string };
          erro.code = estado;
          throw erro;
        },
      };
      await assert.rejects(
        () => consumeLimit(bd, A, "msgs_ai_mes", 1, "k"),
        (erro: unknown) => {
          assert.equal(erro instanceof ConflitoDeIdempotenciaError, false, estado);
          assert.equal((erro as Error).message, "da base");
          return true;
        },
      );
    }
  });
});

describe("o `22023` da `ten_tecto` — um dado corrompido nao e «nao cabe»", () => {
  // A `platform.ten_tecto` recusa-se a adivinhar um `limites` que nao seja um
  // inteiro nao negativo, e levanta em vez de ignorar a linha — ignora-la
  // tirava um modulo do minimo, e o minimo de menos modulos e **maior**.
  const MENSAGEM =
    "ten_tecto: a chave manual_max_minor tem um limite que nao e um inteiro em entitlements";

  function baseQueLevanta(estado: string, mensagem = "da base"): ClienteSql {
    return {
      async query() {
        const erro = new Error(mensagem) as Error & { code: string };
        erro.code = estado;
        throw erro;
      },
    };
  }

  it("o `22023` no tecto vira `LimiteIlegivelError`", async () => {
    await assert.rejects(
      () => checkCeiling(baseQueLevanta("22023", MENSAGEM), A, "manual_max_minor", 1),
      LimiteIlegivelError,
    );
  });

  it("nao e recusa: nao conta `ten_limit_denied_total`", async () => {
    await assert.rejects(
      () =>
        checkCeiling(baseQueLevanta("22023", MENSAGEM), A, "manual_max_minor", 1, {
          modulo: "vendedor",
          metricas,
        }),
      LimiteIlegivelError,
    );
    assert.deepEqual(metricas.ler(), {});
  });

  it("no tecto traduz sem olhar para a mensagem", async () => {
    // O `SQL_TECTO` nao passa instante nenhum: o `22023` so pode ser este.
    await assert.rejects(
      () => checkCeiling(baseQueLevanta("22023", "outra qualquer"), A, "manual_max_minor", 1),
      LimiteIlegivelError,
    );
  });

  it("no consumo traduz so o que a mensagem nomeia", async () => {
    // A `ten_consumir` usa o mesmo `22023` na guarda de `p_agora`, e um
    // instante absurdo nao e um limite ilegivel.
    await assert.rejects(
      () => consumeLimit(baseQueLevanta("22023", MENSAGEM), A, "msgs_ai_mes", 1, "k"),
      LimiteIlegivelError,
    );
    await assert.rejects(
      () =>
        consumeLimit(
          baseQueLevanta("22023", "ten_consumir: instante fora da janela"),
          A,
          "msgs_ai_mes",
          1,
          "k",
        ),
      (erro: unknown) => {
        assert.equal(erro instanceof LimiteIlegivelError, false);
        return true;
      },
    );
  });

  it("no tecto, o que nao e `22023` sobe como veio", async () => {
    // Traduzir de mais era disfarcar um erro que nao se percebeu.
    for (const estado of ["23514", "KA002", "40001"]) {
      await assert.rejects(
        () => checkCeiling(baseQueLevanta(estado), A, "manual_max_minor", 1),
        (erro: unknown) => {
          assert.equal(erro instanceof LimiteIlegivelError, false, estado);
          assert.equal((erro as Error).message, "da base");
          return true;
        },
      );
    }
  });

  it("a mensagem nao repete o valor guardado (`OBS-I`)", async () => {
    await assert.rejects(
      () => checkCeiling(baseQueLevanta("22023", MENSAGEM), A, "manual_max_minor", 1),
      (erro: unknown) => {
        assert.doesNotMatch((erro as Error).message, /manual_max_minor/);
        assert.match((erro as Error).message, /22023/);
        return true;
      },
    );
  });

  it("`conflitoOuTecto` distingue os dois estados e nao inventa um terceiro", () => {
    assert.equal(conflitoOuTecto({ code: "KA002" }) instanceof ConflitoDeIdempotenciaError, true);
    assert.equal(
      conflitoOuTecto({ code: "22023", message: MENSAGEM }) instanceof LimiteIlegivelError,
      true,
    );
    assert.equal(conflitoOuTecto({ code: "22023", message: "p_agora" }), null);
    assert.equal(conflitoOuTecto({ code: "40001" }), null);
    assert.equal(conflitoOuTecto(null), null);
    assert.equal(MARCA_DO_TECTO_ILEGIVEL, "ten_tecto");
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
    // `desligado` a cabeca: e transporte, e nao politica.
    assert.deepEqual(
      [...REGIMES],
      ["desligado", "encerrado", "suspenso", "pendente", "restrito", "ativo"],
    );
    assert.equal(maisRestritivo("ativo", "encerrado"), "encerrado");
    assert.equal(maisRestritivo("encerrado", "ativo"), "encerrado");
    assert.equal(maisRestritivo("restrito", "pendente"), "pendente");
    assert.equal(maisRestritivo("ativo", "ativo"), "ativo");
    // A correccao: `desligado` ganha aos outros cinco, nos dois sentidos.
    for (const outro of ["encerrado", "suspenso", "pendente", "restrito", "ativo"] as const) {
      assert.equal(maisRestritivo("desligado", outro), "desligado", outro);
      assert.equal(maisRestritivo(outro, "desligado"), "desligado", outro);
    }
  });

  it("o caso que a revisao mediu: `suspenso` + `desligado` nao envia", () => {
    // Era o defeito: a linha `suspenso` permite a mensagem estatica, e com
    // `suspenso` a ganhar o gate autorizava um envio por um canal que o §7.2
    // diz removido.
    const decisao = tenantGate("suspenso", "desligado", "mensagem_estatica");
    assert.equal(decisao.regime, "desligado");
    assert.equal(decisao.permitido, false);
    assert.equal(decisao.origem, "canal");
    for (const estado of ESTADOS_DO_TENANT) {
      for (const accao of ACCOES) {
        assert.equal(
          tenantGate(estado, "desligado", accao).permitido,
          false,
          `${estado}/desligado × ${accao}`,
        );
      }
    }
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

  it("a matriz completa: 5 tenants × 6 canais × 7 accoes, um a um", () => {
    // O regime de cada par, escrito **a mao** a partir da regra — e nao
    // calculado com ela. Um teste que corresse `regimeDe` para construir o
    // esperado verificava que a funcao e igual a si propria.
    const regimeDoPar: Record<string, string> = {
      "onboarding/pendente": "pendente",
      "onboarding/ativo": "pendente",
      "onboarding/restrito": "pendente",
      "onboarding/desligado": "desligado",
      "onboarding/suspenso": "suspenso",
      "onboarding/encerrado": "encerrado",
      "ativo/pendente": "pendente",
      "ativo/ativo": "ativo",
      "ativo/restrito": "restrito",
      "ativo/desligado": "desligado",
      "ativo/suspenso": "suspenso",
      "ativo/encerrado": "encerrado",
      "restrito/pendente": "pendente",
      "restrito/ativo": "restrito",
      "restrito/restrito": "restrito",
      "restrito/desligado": "desligado",
      "restrito/suspenso": "suspenso",
      "restrito/encerrado": "encerrado",
      "suspenso/pendente": "suspenso",
      "suspenso/ativo": "suspenso",
      "suspenso/restrito": "suspenso",
      "suspenso/desligado": "desligado",
      "suspenso/suspenso": "suspenso",
      "suspenso/encerrado": "encerrado",
      "encerrado/pendente": "encerrado",
      "encerrado/ativo": "encerrado",
      "encerrado/restrito": "encerrado",
      "encerrado/desligado": "desligado",
      "encerrado/suspenso": "encerrado",
      "encerrado/encerrado": "encerrado",
    };
    const matriz = REGIMES_E_ACCOES as unknown as Record<
      string,
      Record<string, boolean>
    >;
    let casos = 0;
    for (const t of ESTADOS_DO_TENANT) {
      for (const c of ESTADOS_DO_CANAL) {
        const regime = regimeDoPar[`${t}/${c}`] ?? "sem-par-escrito";
        assert.equal(regimeDe(t, c), regime, `${t}/${c}`);
        for (const accao of ACCOES) {
          casos += 1;
          assert.equal(
            tenantGate(t, c, accao).permitido,
            matriz[regime]?.[accao],
            `${t}/${c} × ${accao}`,
          );
        }
      }
    }
    assert.equal(casos, 5 * 6 * 7);
  });

  it("nenhum par com o canal `desligado` autoriza uma saida", () => {
    const saidas = ACCOES.filter((a) => a !== "registar_entrada");
    for (const t of ESTADOS_DO_TENANT) {
      for (const accao of saidas) {
        assert.equal(tenantGate(t, "desligado", accao).permitido, false, `${t} × ${accao}`);
      }
    }
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
    // O que chega a base e a chave **derivada**, com o cabecalho dentro.
    assert.equal(
      bd.chamadas[1]?.parametros[3],
      derivarChaveDeIdempotencia("ten.v1", A, "vendedor", "msgs_ai_mes", "req-1"),
    );
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
    assert.equal(
      outro.chamadas[1]?.parametros[3],
      derivarChaveDeIdempotencia("ten.v1", A, "vendedor", "msgs_ai_mes", "abc"),
    );
  });

  it("**a chave do cliente nunca e a chave efectiva** (C1)", async () => {
    // Um cliente que mande sempre a mesma constante deixa de poder escolher o
    // ambito da desduplicacao: o tenant, o modulo e a chave de limite sao do
    // servidor, e so o ultimo componente e dele.
    const vistas: unknown[] = [];
    for (const [modulo, chave] of [
      ["vendedor", "msgs_ai_mes"],
      ["servicos", "msgs_ai_mes"],
      ["vendedor", "marcacoes_mes"],
    ] as const) {
      const bd = new BaseFalsa()
        .responder([linhaDeEntitlement()])
        .responder([linhaDeConsumo()]);
      await guardaHttp(
        bd,
        { ...pedido, cabecalhos: { "idempotency-key": "a-mesma-de-sempre" } },
        contexto,
        { modulo, chave, metricas },
      );
      const efectiva = bd.chamadas[1]?.parametros[3];
      assert.notEqual(efectiva, "a-mesma-de-sempre");
      assert.match(String(efectiva), /^[0-9a-f]{64}$/);
      vistas.push(efectiva);
    }
    assert.equal(new Set(vistas).size, 3);
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
    assert.equal(
      bd.chamadas[1]?.parametros[3],
      derivarChaveDeIdempotencia(
        "ten.v1",
        A,
        "vendedor",
        "msgs_ai_mes",
        "sha256-derivada",
      ),
    );
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
      derivarChaveDeIdempotencia("ten.v1", A, "vendedor", "msgs_ai_mes", "req-1"),
      10,
      quando,
    ]);
  });

  it("o tecto por pedido corre **antes** do consumo, e nao escreve", async () => {
    // M5: era o defeito medido. Com o plano `free`, consumir
    // `valor_max_pedido_minor` pela `ten_consumir` gastava num pedido de
    // 50 000 Kz o tecto inteiro. Aqui o tecto le-se, e so se consome depois.
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([{ tecto: "5000000" }])
      .responder([linhaDeConsumo()]);
    assert.equal(
      await guardaHttp(bd, pedido, contexto, {
        modulo: "vendedor",
        chave: "msgs_ai_mes",
        tecto: { chave: "valor_max_pedido_minor", valor: 4_000_000 },
        metricas,
      }),
      null,
    );
    assert.deepEqual(
      bd.chamadas.map((c) => c.sql),
      [SQL_ENTITLEMENT, SQL_TECTO, SQL_CONSUMIR],
    );
  });

  it("403 LIMIT_EXCEEDED quando o tecto por pedido nao chega — e sem consumir", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([{ tecto: "5000000" }]);
    const recusa = await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      chave: "msgs_ai_mes",
      tecto: { chave: "valor_max_pedido_minor", valor: 6_000_000 },
      metricas,
    });
    assert.deepEqual(recusa, {
      // `403` e nao `429`: um tecto por pedido nao reabre no mes seguinte.
      estado: HTTP_TECTO,
      corpo: { error: CODIGO_LIMITE, key: "valor_max_pedido_minor" },
      cabecalhos: {},
    });
    assert.equal(bd.chamadas.length, 2);
    assert.equal(
      bd.chamadas.some((c) => c.sql === SQL_CONSUMIR),
      false,
    );
  });

  it("um tecto sem entitlement que o declare da 403 ENTITLEMENT_DISABLED", async () => {
    const bd = new BaseFalsa()
      .responder([linhaDeEntitlement()])
      .responder([{ tecto: null }]);
    const recusa = await guardaHttp(bd, pedido, contexto, {
      modulo: "vendedor",
      tecto: { chave: "manual_max_minor", valor: 1 },
      metricas,
    });
    assert.deepEqual(recusa, {
      estado: HTTP_ENTITLEMENT,
      corpo: {
        error: CODIGO_ENTITLEMENT_HTTP,
        modulo: "vendedor",
        key: "manual_max_minor",
      },
      cabecalhos: {},
    });
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
