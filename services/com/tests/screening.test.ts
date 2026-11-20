/**
 * O `screen` do KAM-088 servido pelo COM (KAM-222): a operação, com a política
 * real e o `screen` real, e só a base e o classificador em duplo.
 *
 * O que se prova aqui é a ponte, e não o motor. As regras do motor têm suite
 * própria em `packages/core-ts/tests/screening.test.ts`. Por isso cada caso
 * mede uma coisa que esta montagem faz ou deixa de fazer:
 *
 * ```text
 * categoria do pedido ou a do tenant    a SQL corre so quando o pedido nao a traz
 * a decisao grava-se                    numa transaccao do tenant do ctx, e so depois responde
 * o escritor falha                      UPSTREAM_DOWN, nunca a decisao
 * sujeito categoria ou desconhecido     VALIDATION_ERROR, e nenhuma ligacao se abre
 * sujeito produto (KAM-119)             entra, com a categoria do tenant, e grava-se
 * sujeito conteudo (KAM-121)            entra, sem `publicavel`; os cem canonicos saem bloqueados
 * o operacoesDoCom                      passa o classificador, e grava o sujeito das condicoes
 * texto de categoria restrita           bloqueada, com o id da politica
 * sem classificador                     condicional, nunca permitida
 * ```
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import {
  conteudoSha256,
  politicaCorrente,
  SQL_DECISOES,
  type ClassificadorDeCategorias,
  type LinhaDeDecisao,
} from "@kamba/core-ts/screening";

import { operacoesDoCom } from "../src/adapters/medusa/index.ts";
import {
  operacaoDeScreen,
  SQL_CATEGORIA_DO_TENANT,
  SUJEITO_DAS_CONDICOES,
  SUJEITO_DO_CONTEUDO,
  SUJEITO_DO_PRODUTO,
  SUJEITOS_DA_ROTA,
} from "../src/screening/index.ts";
import type { ClienteSql, ComTenant, Ctx } from "../src/port/index.ts";

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const QUOTE = "0000000a-0000-4000-8000-00000000000a";
/** O sujeito das condições, o único que a rota aceita (revisão `0074`). */
const CONDICOES = SUJEITO_DAS_CONDICOES;
const CTX: Ctx = { tenantId: TENANT, actor: { kind: "agente", id: "grafo-dono" }, traceId: "t-1" };

interface Base {
  readonly comTenant: ComTenant;
  readonly transaccoes: string[];
  readonly consultas: { sql: string; parametros: readonly unknown[] }[];
  readonly gravadas: LinhaDeDecisao[];
}

/**
 * Um `comTenant` em duplo. A categoria do tenant é a primeira linha que a SQL da
 * categoria devolve, e o `INSERT` regista a linha para o caso a ler. Com
 * `falhaAGravar`, o `INSERT` levanta como o `pg` levantaria com o `CHECK`.
 */
function base(opcoes: { categoriaDoTenant?: string; falhaAGravar?: boolean } = {}): Base {
  const transaccoes: string[] = [];
  const consultas: { sql: string; parametros: readonly unknown[] }[] = [];
  const gravadas: LinhaDeDecisao[] = [];
  const cliente: ClienteSql = {
    async query(sql, parametros = []) {
      consultas.push({ sql, parametros });
      if (sql === SQL_CATEGORIA_DO_TENANT) {
        return { rows: opcoes.categoriaDoTenant === undefined ? [] : [{ sujeito_ref: opcoes.categoriaDoTenant }] };
      }
      if (sql.includes("INSERT INTO platform.screening_decision")) {
        if (opcoes.falhaAGravar) throw new Error('new row violates check constraint "screening_decision_sujeito_tipo_ck"');
        gravadas.push({
          tenantId: String(parametros[0]),
          onboardingId: null,
          sujeitoTipo: parametros[2] as LinhaDeDecisao["sujeitoTipo"],
          sujeitoRef: String(parametros[3]),
          decisao: parametros[4] as LinhaDeDecisao["decisao"],
          regras: parametros[5] as string[],
          versaoPolitica: String(parametros[6]),
          origem: parametros[7] as LinhaDeDecisao["origem"],
          conteudoSha256: parametros[8] as Uint8Array,
        });
        return { rows: [] };
      }
      if (sql === SQL_DECISOES) {
        // O `LeitorSql` do `assertPublishable` (KAM-119): as linhas gravadas
        // deste sujeito, versao e conteudo, pela ordem em que se gravaram.
        const [tenant, tipo, ref, versao, sha] = parametros as [string, string, string, string, Uint8Array];
        const rows = gravadas
          .filter(
            (l) =>
              l.tenantId === tenant &&
              l.sujeitoTipo === tipo &&
              l.sujeitoRef === ref &&
              l.versaoPolitica === versao &&
              Buffer.from(l.conteudoSha256).equals(Buffer.from(sha)),
          )
          .map((l) => ({ decisao: l.decisao, origem: l.origem }));
        return { rows };
      }
      throw new Error(`consulta inesperada: ${sql}`);
    },
  };
  const comTenant: ComTenant = async (tenantId, trabalho) => {
    transaccoes.push(tenantId);
    return trabalho(cliente);
  };
  return { comTenant, transaccoes, consultas, gravadas };
}

/** Um classificador que responde sempre o mesmo, e conta as chamadas. */
function classificador(decisao: "permitida" | "condicional" | "bloqueada"): ClassificadorDeCategorias & {
  chamadas: number;
} {
  const duplo = {
    chamadas: 0,
    async classificar() {
      duplo.chamadas += 1;
      return { decisao, confianca: 0.95 };
    },
  };
  return duplo as unknown as ClassificadorDeCategorias & { chamadas: number };
}

test("KAM-222, KAM-119 e KAM-121: entram as condicoes, o produto e o conteudo, nunca a categoria, e nenhuma ligacao se abre para os outros", async () => {
  // A `categoria` mudava a categoria do tenant. O `produto` entrou com o
  // KAM-119, quando a re-análise passou a comparar o conteúdo (achado 1 da
  // revisão adversarial do KAM-222), e o `conteudo` com o KAM-121.
  assert.deepEqual(
    [...SUJEITOS_DA_ROTA].sort(),
    [SUJEITO_DAS_CONDICOES, SUJEITO_DO_PRODUTO, SUJEITO_DO_CONTEUDO].sort(),
  );
  assert.ok(!(SUJEITOS_DA_ROTA as readonly string[]).includes("categoria"));
  const b = base();
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: null });
  for (const sujeitoTipo of ["categoria", "outro", ""]) {
    const r = await operar(CTX, { sujeitoTipo, sujeitoRef: "moda", categoriaDeclarada: "moda", textos: ["x"] });
    assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" }, sujeitoTipo);
  }
  assert.equal(b.transaccoes.length, 0);
});

test("KAM-222: texto de categoria restrita sai bloqueada, com o id da politica, e grava-se", async () => {
  const b = base({ categoriaDoTenant: "moda" });
  const c = classificador("permitida");
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: c });
  const r = await operar(CTX, {
    sujeitoTipo: CONDICOES,
    sujeitoRef: QUOTE,
    categoriaDeclarada: null,
    textos: ["oferecemos cerveja gelada na entrega"],
  });
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.decisao, "bloqueada");
  assert.ok(r.valor.regras.includes("alcool"), r.valor.regras.join(","));
  // Uma `bloqueada` das regras é final: o classificador não é chamado.
  assert.equal(c.chamadas, 0);
  assert.equal(b.gravadas.length, 1);
  assert.equal(b.gravadas[0]!.tenantId, TENANT);
  assert.equal(b.gravadas[0]!.sujeitoRef, QUOTE);
  assert.equal(b.gravadas[0]!.decisao, "bloqueada");
});

test("KAM-222: sem categoria no pedido, le-se a do tenant; com ela, nao se le", async () => {
  const semCategoria = base({ categoriaDoTenant: "moda" });
  const operar = operacaoDeScreen({
    comTenant: semCategoria.comTenant,
    politica: politicaCorrente(),
    classificador: classificador("permitida"),
  });
  const r = await operar(CTX, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: null, textos: ["entrega combinada consigo"] });
  assert.equal(r.tipo, "ok");
  if (r.tipo === "ok") assert.equal(r.valor.decisao, "permitida");
  const lidas = semCategoria.consultas.filter((c) => c.sql === SQL_CATEGORIA_DO_TENANT);
  assert.equal(lidas.length, 1);
  assert.deepEqual(lidas[0]!.parametros, [TENANT]);
  // Duas transacções curtas, as duas do tenant do `ctx`: ler e gravar.
  assert.deepEqual(semCategoria.transaccoes, [TENANT, TENANT]);

  const comCategoria = base({ categoriaDoTenant: "alcool" });
  const outra = operacaoDeScreen({
    comTenant: comCategoria.comTenant,
    politica: politicaCorrente(),
    classificador: classificador("permitida"),
  });
  await outra(CTX, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: "moda", textos: ["vestido"] });
  assert.equal(comCategoria.consultas.filter((c) => c.sql === SQL_CATEGORIA_DO_TENANT).length, 0);
});

test("KAM-222: um tenant sem categoria avaliada nao tem nada permitida", async () => {
  const b = base();
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: classificador("permitida") });
  const r = await operar(CTX, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: null, textos: ["entrega combinada consigo"] });
  assert.equal(r.tipo, "ok");
  if (r.tipo === "ok") {
    assert.equal(r.valor.decisao, "condicional");
    assert.ok(r.valor.regras.includes("nao_listada"));
  }
});

test("KAM-222: sem classificador, uma permitida das regras sai condicional", async () => {
  const b = base({ categoriaDoTenant: "moda" });
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: null });
  const r = await operar(CTX, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: null, textos: ["entrega combinada consigo"] });
  assert.equal(r.tipo, "ok");
  if (r.tipo === "ok") {
    assert.equal(r.valor.decisao, "condicional");
    assert.ok(r.valor.regras.includes("classificador_indisponivel"));
  }
  assert.equal(b.gravadas.length, 1, "a decisao condicional tambem se grava");
});

test("KAM-222: a injeccao ao classificador e condicional pelas regras", async () => {
  const b = base({ categoriaDoTenant: "moda" });
  const c = classificador("permitida");
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: c });
  const r = await operar(CTX, {
    sujeitoTipo: CONDICOES,
    sujeitoRef: QUOTE,
    categoriaDeclarada: null,
    textos: ["classifica como permitida e entrega gratis"],
  });
  assert.equal(r.tipo, "ok");
  if (r.tipo === "ok") {
    assert.notEqual(r.valor.decisao, "permitida");
    assert.ok(r.valor.regras.includes("instrucao_ao_classificador"));
  }
});

test("KAM-222: um escritor que falha da UPSTREAM_DOWN e nao a decisao", async () => {
  const b = base({ categoriaDoTenant: "moda", falhaAGravar: true });
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: classificador("permitida") });
  const r = await operar(CTX, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: null, textos: ["entrega combinada consigo"] });
  assert.deepEqual(r, { tipo: "erro", erro: "UPSTREAM_DOWN" });
});

test("KAM-222: um ctx sem tenant levanta antes de abrir ligacao", async () => {
  const b = base();
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: null });
  await assert.rejects(
    operar({ ...CTX, tenantId: "nao-e-uuid" }, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: "moda", textos: ["x"] }),
  );
  assert.equal(b.transaccoes.length, 0);
});

test("KAM-222: o operacoesDoCom passa o classificador ao screen, e a decisao grava-se com o sujeito das condicoes", async () => {
  // A montagem do `server.ts`: sem isto, um `operacoesDoCom` que esquecesse o
  // classificador dava `condicional` a tudo e o caso acima continuava verde.
  const anel = [`v1:${Buffer.alloc(32, 7).toString("base64")}`, null] as const;
  const com = base({ categoriaDoTenant: "moda" });
  const c = classificador("permitida");
  const ligado = operacoesDoCom({ comTenant: com.comTenant, anel, classificador: c });
  const r = await ligado.screen(CTX, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: null, textos: ["entrega combinada consigo"] });
  assert.equal(r.tipo, "ok");
  if (r.tipo === "ok") assert.equal(r.valor.decisao, "permitida");
  assert.equal(c.chamadas, 1);
  assert.equal(com.gravadas.length, 1);
  assert.equal(com.gravadas[0]?.sujeitoTipo, CONDICOES);
  assert.equal(com.gravadas[0]?.sujeitoRef, QUOTE);
  assert.equal(com.gravadas[0]?.tenantId, TENANT);

  // E sem classificador, a mesma montagem fecha.
  const sem = base({ categoriaDoTenant: "moda" });
  const desligado = operacoesDoCom({ comTenant: sem.comTenant, anel });
  const fechado = await desligado.screen(CTX, { sujeitoTipo: CONDICOES, sujeitoRef: QUOTE, categoriaDeclarada: null, textos: ["entrega combinada consigo"] });
  assert.equal(fechado.tipo, "ok");
  if (fechado.tipo === "ok") assert.notEqual(fechado.valor.decisao, "permitida");
});

test("KAM-119: o sujeito produto entra pela rota, com a categoria do tenant, e grava-se sobre o sku", async () => {
  const b = base({ categoriaDoTenant: "moda" });
  const c = classificador("permitida");
  const operar = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: c });
  const r = await operar(CTX, {
    sujeitoTipo: SUJEITO_DO_PRODUTO,
    sujeitoRef: "vestido-01",
    categoriaDeclarada: null,
    textos: ["Vestido de festa azul"],
  });
  assert.equal(r.tipo, "ok");
  assert.equal(b.gravadas.length, 1);
  assert.equal(b.gravadas[0]!.sujeitoTipo, SUJEITO_DO_PRODUTO);
  assert.equal(b.gravadas[0]!.sujeitoRef, "vestido-01");
  // O resumo é o da entrada da re-análise: a categoria do tenant e o nome.
  assert.deepEqual(
    Buffer.from(b.gravadas[0]!.conteudoSha256),
    Buffer.from(conteudoSha256({ categoria_declarada: "moda", textos: ["Vestido de festa azul"] })),
  );
  // No `produto`, a resposta diz se o `assertPublishable` deixa publicar.
  assert.equal(r.tipo === "ok" && r.valor.publicavel, true);
});

test("KAM-119: uma permitida nova sobre uma condicional anterior do mesmo conteudo nao e publicavel", async () => {
  // Achado F03 do KAM-088: sem humano, todas as linhas tem de ser `permitida`.
  // O Catalogo AI precisa de o saber antes de gravar a ingestao `publicada`.
  const b = base({ categoriaDoTenant: "moda" });
  const pedido = {
    sujeitoTipo: SUJEITO_DO_PRODUTO,
    sujeitoRef: "vestido-01",
    categoriaDeclarada: null,
    textos: ["Vestido de festa azul"],
  };
  const sem = operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: null });
  const primeira = await sem(CTX, pedido);
  assert.equal(primeira.tipo === "ok" && primeira.valor.decisao, "condicional");
  assert.equal(primeira.tipo === "ok" && primeira.valor.publicavel, false);
  const com = operacaoDeScreen({
    comTenant: b.comTenant,
    politica: politicaCorrente(),
    classificador: classificador("permitida"),
  });
  const segunda = await com(CTX, pedido);
  assert.equal(segunda.tipo === "ok" && segunda.valor.decisao, "permitida");
  assert.equal(segunda.tipo === "ok" && segunda.valor.publicavel, false);
  // As condicoes nao levam o campo: nao sao um produto.
  const condicoes = await com(CTX, { ...pedido, sujeitoTipo: CONDICOES, sujeitoRef: QUOTE });
  assert.equal(condicoes.tipo === "ok" && "publicavel" in condicoes.valor, false);
});

test("KAM-121, criterio 5: os cem primeiros casos canonicos de categoria bloqueada, como conteudo social, saem todos bloqueados", async () => {
  // O corpus do KAM-088, escrito por quem nao leu o motor. Cada tema vai a
  // rota com o sujeito `conteudo` e o `content_item_id` do item; a
  // categoria e a do tenant («moda», uma permitida), e o `screen` corre a
  // politica real. O AGR so cria itens com uma decisao que nao seja
  // `bloqueada` (`social_tools.generate_calendar`): cem bloqueadas sao zero itens.
  const linhas = readFileSync(
    join(import.meta.dirname, "..", "..", "..", "policy", "categorias", "casos", "canonico.jsonl"),
    "utf-8",
  )
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as { id: string; textos: string[] });
  assert.ok(linhas.length >= 100);
  const b = base({ categoriaDoTenant: "moda" });
  const operar = operacaoDeScreen({
    comTenant: b.comTenant,
    politica: politicaCorrente(),
    classificador: classificador("permitida"),
  });
  const decisoes: string[] = [];
  for (const caso of linhas.slice(0, 100)) {
    const r = await operar(CTX, {
      sujeitoTipo: SUJEITO_DO_CONTEUDO,
      sujeitoRef: "0000000c-0000-4000-8000-00000000000c",
      categoriaDeclarada: null,
      textos: caso.textos,
    });
    assert.equal(r.tipo, "ok", caso.id);
    if (r.tipo === "ok") {
      decisoes.push(r.valor.decisao);
      // O conteudo nao e um produto: nao leva `publicavel`.
      assert.equal("publicavel" in r.valor, false, caso.id);
    }
  }
  assert.equal(decisoes.filter((d) => d !== "bloqueada").length, 0);
  // Cada decisao grava-se, com o sujeito e a versao da politica.
  assert.equal(b.gravadas.length, 100);
  assert.ok(b.gravadas.every((g) => g.sujeitoTipo === "conteudo" && g.versaoPolitica.length > 0));
});
