/**
 * A publicação com a decisão do screening conferida (KAM-119), pela montagem
 * do `operacoesDoCom`: o `screen` do sujeito `produto`, o `assertPublishable`
 * e o `publishProduct` do módulo com o `nomeEsperado`.
 *
 * ```text
 * sem decisao, bloqueada, condicional       VALIDATION_ERROR, e nada se escreve
 * permitida para o mesmo conteudo           publica, uma vez
 * permitida para outro nome ou categoria    VALIDATION_ERROR
 * a decisao do /internal/screen             e a que a publicacao confere (mesmo resumo)
 * o nome muda antes da tranca               conflito, e nada se escreve
 * confirmacao invalida                      VALIDATION_ERROR, sem ligacao
 * oferta de outro tenant ou inexistente     NOT_FOUND
 * a base falha ao conferir                  UPSTREAM_DOWN
 * ```
 *
 * ## O que a base de ensaio decide, e o que não decide
 *
 * As consultas reconhecem-se pela **constante** (`SQL_NOME_DA_OFERTA`,
 * `SQL_CATEGORIA_DO_TENANT`, `SQL_DECISOES`, `SQL_GRAVAR`), e não por um
 * pedaço de texto: uma consulta nova que esta montagem fizesse sem ser uma
 * delas cai no `throw` do fim. O `SQL_DECISOES` filtra aqui pelos cinco
 * parâmetros, e isso é o duplo e não o predicado: o predicado mede-se contra o
 * PostgreSQL em `db/tests/test_screening_schema.py`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import {
  conteudoSha256,
  politicaCorrente,
  SQL_DECISOES,
  SQL_GRAVAR,
  type ClassificadorDeCategorias,
  type Decisao,
  type Origem,
} from "@kamba/core-ts/screening";

import { operacoesDoCom } from "../src/adapters/medusa/index.ts";
import type { ClienteSql, ComTenant, Ctx } from "../src/port/index.ts";
import { TIPO_PRODUCT_CHANGED } from "../src/produtos/index.ts";
import {
  operacaoDePublicar,
  SQL_CATEGORIA_DO_TENANT,
  SQL_DESPUBLICAR,
  SQL_NOME_DA_OFERTA,
  SUJEITO_DO_PRODUTO,
} from "../src/screening/index.ts";

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SKU = "vestido-01";
const NOME = "Vestido de festa azul";
const CTX: Ctx = { tenantId: TENANT, actor: { kind: "agente", id: "grafo-dono" }, traceId: "t-119" };
const CONFIRMACAO = { actor: { kind: "dono", id: "msg-1" }, em: "2026-11-19T10:00:00Z" } as const;
const ANEL = [`v1:${Buffer.alloc(32, 7).toString("base64")}`, null] as const;
const VERSAO = politicaCorrente().versao;

interface Decisoes {
  sujeitoTipo: string;
  sujeitoRef: string;
  versao: string;
  sha: Buffer;
  decisao: Decisao;
  origem: Origem;
}

interface Opcoes {
  readonly categoria?: string;
  readonly estado?: "rascunho" | "publicado";
  readonly semOferta?: boolean;
  /** Corre no início da transacção número `n` (1 = ler e conferir, 2 = publicar). */
  readonly naTransaccao?: (n: number, oferta: { nome: string }) => void;
  readonly falhaAoConferir?: boolean;
}

function base(opcoes: Opcoes = {}) {
  const oferta = { nome: NOME };
  const decisoes: Decisoes[] = [];
  const escritas: string[] = [];
  const eventos: string[] = [];
  let transaccoes = 0;

  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql === SQL_NOME_DA_OFERTA) {
        assert.deepEqual(parametros, [TENANT, SKU]);
        return { rows: opcoes.semOferta ? [] : [{ nome: oferta.nome }] };
      }
      if (sql === SQL_CATEGORIA_DO_TENANT) {
        return { rows: opcoes.categoria === undefined ? [] : [{ sujeito_ref: opcoes.categoria }] };
      }
      if (sql === SQL_DECISOES) {
        if (opcoes.falhaAoConferir) throw new Error("ligacao caiu a meio");
        const [tenant, tipo, ref, versao, sha] = parametros as [string, string, string, string, Buffer];
        assert.equal(tenant, TENANT);
        return {
          rows: decisoes
            .filter((d) => d.sujeitoTipo === tipo && d.sujeitoRef === ref && d.versao === versao && d.sha.equals(sha))
            .map((d) => ({ decisao: d.decisao, origem: d.origem })),
        };
      }
      if (sql === SQL_GRAVAR) {
        decisoes.push({
          sujeitoTipo: String(parametros[2]),
          sujeitoRef: String(parametros[3]),
          decisao: parametros[4] as Decisao,
          versao: String(parametros[6]),
          origem: parametros[7] as Origem,
          sha: Buffer.from(parametros[8] as Uint8Array),
        });
        return { rows: [] };
      }
      // O caminho do `comRegisto` e do `publishProduct` do módulo.
      if (sql.includes("platform.tenants")) {
        return { rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }] };
      }
      if (sql.includes("audit_append")) return { rows: [{}] };
      if (sql.includes("evt_emitir")) {
        eventos.push(String(parametros[0]));
        return { rows: [{ event_id: `evt-${eventos.length}` }] };
      }
      if (sql.includes("platform.offer_terms")) {
        // A saida de publicado do `screen` (KAM-245) nao e uma publicacao.
        if (sql === SQL_DESPUBLICAR) {
          escritas.push("despublicar");
          return { rows: [{ sku: SKU }] };
        }
        if (/^\s*UPDATE/i.test(sql)) {
          escritas.push("publicar");
          return { rows: [{ sku: SKU, estado: "publicado", atualizado_at: "x" }] };
        }
        if (/FOR UPDATE/.test(sql)) {
          // A tranca do `screen` (KAM-245) so ve a oferta publicada.
          const soPublicada = sql.includes("estado = 'publicado'") && (opcoes.estado ?? "rascunho") !== "publicado";
          return {
            rows: opcoes.semOferta || soPublicada
              ? []
              : [
                  {
                    sku: SKU,
                    nome: oferta.nome,
                    preco_tipo: "fixo",
                    preco_minor: "1250000",
                    currency: "AOA",
                    preco_atualizado_at: null,
                    preco_valido_ate: null,
                    stock_modo: "indicativo",
                    stock_verificado_at: null,
                    estado: opcoes.estado ?? "rascunho",
                    categoria_restrita: null,
                    // KAM-209: sem categoria o COM não publica.
                    categoria: "moda",
                    atualizado_at: "2026-11-19T09:00:00.000Z",
                  },
                ],
          };
        }
      }
      throw new Error(`consulta inesperada: ${sql}`);
    },
  };
  const comTenant: ComTenant = async (tenantId, trabalho) => {
    assert.equal(tenantId, TENANT);
    transaccoes += 1;
    opcoes.naTransaccao?.(transaccoes, oferta);
    // Uma transaccao que lanca desfaz-se: o que escreveu e o que emitiu saem,
    // como na base (KAM-231, para medir a recusa do ajuste de stock).
    const antes = { eventos: eventos.length, escritas: escritas.length };
    try {
      return await trabalho(cliente);
    } catch (e) {
      eventos.length = antes.eventos;
      escritas.length = antes.escritas;
      throw e;
    }
  };
  /** Uma decisão gravada à mão para o conteúdo `(categoria, nome)`. */
  const decidir = (decisao: Decisao, categoria: string, nome: string, origem: Origem = "regra") =>
    decisoes.push({
      sujeitoTipo: SUJEITO_DO_PRODUTO,
      sujeitoRef: SKU,
      versao: VERSAO,
      sha: Buffer.from(conteudoSha256({ categoria_declarada: categoria, textos: [nome] })),
      decisao,
      origem,
    });
  return {
    comTenant,
    decisoes,
    escritas,
    eventos,
    decidir,
    get transaccoes() {
      return transaccoes;
    },
  };
}

function classificador(decisao: Decisao): ClassificadorDeCategorias {
  return { async classificar() { return { decisao, confianca: 0.95 }; } } as unknown as ClassificadorDeCategorias;
}

function publicar(b: ReturnType<typeof base>, classificadorDoCom: ClassificadorDeCategorias | null = null) {
  return operacoesDoCom({ comTenant: b.comTenant, anel: ANEL, classificador: classificadorDoCom }).publicarProduto(CTX, {
    sku: SKU,
    confirmacao: CONFIRMACAO,
  });
}

test("KAM-119: sem decisao para o conteudo, a publicacao recusa e nada se escreve", async () => {
  const b = base({ categoria: "moda" });
  assert.deepEqual(await publicar(b), { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(b.escritas, []);
  assert.deepEqual(b.eventos, []);
  // Uma transacção só, a de ler e conferir: a de publicar não chega a abrir.
  assert.equal(b.transaccoes, 1);
});

test("KAM-119: com uma permitida para o mesmo conteudo, publica uma vez", async () => {
  const b = base({ categoria: "moda" });
  b.decidir("permitida", "moda", NOME);
  assert.deepEqual(await publicar(b), { tipo: "ok", valor: undefined });
  assert.deepEqual(b.escritas, ["publicar"]);
  assert.deepEqual(b.eventos, [TIPO_PRODUCT_CHANGED]);
  assert.equal(b.transaccoes, 2);
});

test("KAM-231: a quantidade do dono vai ao Registo com a publicacao, na mesma transaccao", async () => {
  const b = base({ categoria: "moda" });
  b.decidir("permitida", "moda", NOME);
  const operar = operacoesDoCom({ comTenant: b.comTenant, anel: ANEL }).publicarProduto;
  assert.deepEqual(await operar(CTX, { sku: SKU, confirmacao: CONFIRMACAO, stock: 500 }), {
    tipo: "ok",
    valor: undefined,
  });
  // A publicacao e o ajuste, os dois na transaccao de publicar: o `stock.adjusted`
  // sai depois do `product.changed`, e nao ha terceira transaccao.
  assert.deepEqual(b.eventos, [TIPO_PRODUCT_CHANGED, "stock.adjusted"]);
  assert.equal(b.transaccoes, 2);
});

test("KAM-231: sem quantidade, a publicacao nao ajusta o stock", async () => {
  const b = base({ categoria: "moda" });
  b.decidir("permitida", "moda", NOME);
  assert.deepEqual(await publicar(b), { tipo: "ok", valor: undefined });
  assert.ok(!b.eventos.includes("stock.adjusted"));
});

test("KAM-231: um ajuste de stock recusado desfaz a publicacao", async () => {
  const b = base({ categoria: "moda" });
  b.decidir("permitida", "moda", NOME);
  const operar = operacoesDoCom({ comTenant: b.comTenant, anel: ANEL }).publicarProduto;
  // Um `qty` que o `ajustarStock` recusa (a API interna ja o recusaria antes): a
  // publicacao que correu na mesma transaccao desfaz-se, e nada sai.
  assert.deepEqual(await operar(CTX, { sku: SKU, confirmacao: CONFIRMACAO, stock: -1 }), {
    tipo: "erro",
    erro: "VALIDATION_ERROR",
  });
  assert.deepEqual(b.eventos, []);
  assert.deepEqual(b.escritas, []);
});

test("KAM-231: uma publicacao recusada nao ajusta o stock", async () => {
  const b = base({ categoria: "moda" });
  const operar = operacoesDoCom({ comTenant: b.comTenant, anel: ANEL }).publicarProduto;
  assert.deepEqual(await operar(CTX, { sku: SKU, confirmacao: CONFIRMACAO, stock: 500 }), {
    tipo: "erro",
    erro: "VALIDATION_ERROR",
  });
  assert.deepEqual(b.eventos, []);
});

test("KAM-119: uma linha bloqueada ou condicional para o conteudo recusa, mesmo com uma permitida ao lado", async () => {
  for (const outra of ["bloqueada", "condicional"] as const) {
    const b = base({ categoria: "moda" });
    b.decidir("permitida", "moda", NOME);
    b.decidir(outra, "moda", NOME);
    assert.deepEqual(await publicar(b), { tipo: "erro", erro: "VALIDATION_ERROR" }, outra);
    assert.deepEqual(b.escritas, [], outra);
  }
  // Só uma condicional, sem permitida nenhuma: também recusa.
  const so = base({ categoria: "moda" });
  so.decidir("condicional", "moda", NOME);
  assert.deepEqual(await publicar(so), { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("KAM-119: uma permitida para outro nome, ou com outra categoria, nao serve", async () => {
  const outroNome = base({ categoria: "moda" });
  outroNome.decidir("permitida", "moda", "Vestido de festa");
  assert.deepEqual(await publicar(outroNome), { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(outroNome.escritas, []);

  // A categoria é a do tenant **agora**: uma decisão sobre a de antes é sobre
  // outro conteúdo.
  const outraCategoria = base({ categoria: "electronica" });
  outraCategoria.decidir("permitida", "moda", NOME);
  assert.deepEqual(await publicar(outraCategoria), { tipo: "erro", erro: "VALIDATION_ERROR" });

  // Um tenant sem decisão de categoria confere com a categoria vazia.
  const semCategoria = base();
  semCategoria.decidir("permitida", "", NOME);
  assert.deepEqual(await publicar(semCategoria), { tipo: "ok", valor: undefined });
});

test("KAM-119: a ultima decisao humana manda, como no assertPublishable", async () => {
  const b = base({ categoria: "moda" });
  b.decidir("condicional", "moda", NOME);
  b.decidir("permitida", "moda", NOME, "humano");
  assert.deepEqual(await publicar(b), { tipo: "ok", valor: undefined });
});

test("KAM-119: a decisao que o screen do produto grava e a que a publicacao confere", async () => {
  // A ligação entre as duas rotas: `/internal/screen` com `sujeito_tipo:
  // produto`, `categoria_declarada` nula e `textos: [nome]` grava o resumo que
  // a publicação lê. Se uma das duas montasse a entrada de outra maneira, esta
  // publicação recusava por `sem_decisao`.
  const b = base({ categoria: "moda" });
  const com = operacoesDoCom({ comTenant: b.comTenant, anel: ANEL, classificador: classificador("permitida") });
  const decidido = await com.screen(CTX, {
    finalidade: "classificacao_de_catalogo",
    prazoMs: 10_000,
    sujeitoTipo: SUJEITO_DO_PRODUTO,
    sujeitoRef: SKU,
    categoriaDeclarada: null,
    textos: [NOME],
  });
  assert.equal(decidido.tipo, "ok");
  if (decidido.tipo === "ok") assert.equal(decidido.valor.decisao, "permitida");
  assert.equal(b.decisoes.length, 1);
  assert.equal(b.decisoes[0]!.sujeitoTipo, SUJEITO_DO_PRODUTO);
  const publicado = await com.publicarProduto(CTX, { sku: SKU, confirmacao: CONFIRMACAO });
  assert.deepEqual(publicado, { tipo: "ok", valor: undefined });
  assert.deepEqual(b.escritas, ["publicar"]);
  // E a publicação não fez outro `screen`: continua a haver uma decisão só.
  assert.equal(b.decisoes.length, 1);
});

test("KAM-119: o nome muda entre a conferencia e a tranca, e a publicacao devolve conflito sem escrever", async () => {
  const b = base({
    categoria: "moda",
    // Um `upsertProductDraft` concorrente: o texto muda depois da conferência e
    // antes de o `publishProduct` trancar a linha.
    naTransaccao: (n, oferta) => {
      if (n === 2) oferta.nome = "Vestido de festa azul (com garrafa de vinho)";
    },
  });
  b.decidir("permitida", "moda", NOME);
  assert.deepEqual(await publicar(b), { tipo: "conflito", valor: undefined });
  assert.deepEqual(b.escritas, []);
  assert.deepEqual(b.eventos, []);
});

test("KAM-119: um produto ja publicado tambem e conferido, e so com decisao responde ok", async () => {
  // Sem decisão para o texto publicado (o dono mudou-o depois de publicar):
  // a rota não diz «publicado» sobre um texto que nunca passou pelo screen.
  const semDecisao = base({ categoria: "moda", estado: "publicado" });
  assert.deepEqual(await publicar(semDecisao), { tipo: "erro", erro: "VALIDATION_ERROR" });
  // Com ela, a idempotência do módulo: ok, sem escrever nem emitir.
  const comDecisao = base({ categoria: "moda", estado: "publicado" });
  comDecisao.decidir("permitida", "moda", NOME);
  assert.deepEqual(await publicar(comDecisao), { tipo: "ok", valor: undefined });
  assert.deepEqual(comDecisao.escritas, []);
  assert.deepEqual(comDecisao.eventos, []);
});

test("KAM-119: uma confirmacao que nao e do dono, ou sem instante, recusa sem abrir ligacao", async () => {
  for (const confirmacao of [
    { actor: { kind: "agente", id: "msg-1" }, em: "2026-11-19T10:00:00Z" },
    { actor: { kind: "dono", id: "msg-1" }, em: "ontem" },
    { actor: { kind: "dono", id: "" }, em: "2026-11-19T10:00:00Z" },
  ] as const) {
    const b = base({ categoria: "moda" });
    b.decidir("permitida", "moda", NOME);
    const operar = operacaoDePublicar({
      comTenant: b.comTenant,
      politica: politicaCorrente(),
      publicar: async () => {
        throw new Error("nao devia publicar");
      },
    });
    assert.deepEqual(await operar(CTX, { sku: SKU, confirmacao }), { tipo: "erro", erro: "VALIDATION_ERROR" });
    assert.equal(b.transaccoes, 0);
  }
});

test("KAM-119: sem a oferta neste tenant e NOT_FOUND, e a base em baixo e UPSTREAM_DOWN", async () => {
  const semOferta = base({ categoria: "moda", semOferta: true });
  assert.deepEqual(await publicar(semOferta), { tipo: "erro", erro: "NOT_FOUND" });

  const caiu = base({ categoria: "moda", falhaAoConferir: true });
  caiu.decidir("permitida", "moda", NOME);
  assert.deepEqual(await publicar(caiu), { tipo: "erro", erro: "UPSTREAM_DOWN" });
  assert.deepEqual(caiu.escritas, []);
});

test("KAM-119: um ctx sem tenant levanta antes de abrir ligacao", async () => {
  const b = base({ categoria: "moda" });
  const operar = operacoesDoCom({ comTenant: b.comTenant, anel: ANEL }).publicarProduto;
  await assert.rejects(operar({ ...CTX, tenantId: "nao-e-uuid" }, { sku: SKU, confirmacao: CONFIRMACAO }));
  assert.equal(b.transaccoes, 0);
});

test("KAM-119, criterio 5: os cem primeiros casos canonicos de categoria bloqueada dao zero publicacoes", async () => {
  // O corpus do KAM-088 (`policy/categorias/casos/canonico.jsonl`), escrito por
  // quem nao leu o motor. O nome publicado e o texto do caso; a categoria e a
  // do tenant («moda», uma permitida), e o `screen` corre a politica real.
  const linhas = readFileSync(
    join(import.meta.dirname, "..", "..", "..", "policy", "categorias", "casos", "canonico.jsonl"),
    "utf-8",
  )
    .split("\n")
    .filter((l) => l.trim().length > 0)
    .map((l) => JSON.parse(l) as { id: string; textos: string[] });
  assert.ok(linhas.length >= 100);
  let publicadas = 0;
  for (const caso of linhas.slice(0, 100)) {
    const nome = caso.textos.join(". ");
    const b = base({ categoria: "moda", naTransaccao: (_n, oferta) => { oferta.nome = nome; } });
    const com = operacoesDoCom({ comTenant: b.comTenant, anel: ANEL, classificador: classificador("permitida") });
    const decidido = await com.screen(CTX, {
      finalidade: "classificacao_de_catalogo",
      prazoMs: 10_000,
      sujeitoTipo: SUJEITO_DO_PRODUTO,
      sujeitoRef: SKU,
      categoriaDeclarada: null,
      textos: [nome],
    });
    assert.equal(decidido.tipo, "ok", caso.id);
    assert.equal(decidido.tipo === "ok" && decidido.valor.publicavel, false, caso.id);
    const publicada = await publicar(b);
    // A recusa e a mesma para todos, sem o motivo nem a regra no corpo.
    assert.deepEqual(publicada, { tipo: "erro", erro: "VALIDATION_ERROR" }, caso.id);
    publicadas += b.escritas.length;
  }
  assert.equal(publicadas, 0);
});
