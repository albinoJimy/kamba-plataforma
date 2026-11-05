/**
 * O `propose_cart` e as decisões do fluxo do dono, sem base de dados (KAM-046).
 *
 * **O cliente falso não é uma base falsa**, e vale repetir a razão que o
 * `orders.modulo.test.ts` escreveu: ele devolve as linhas que o teste lhe der e
 * grava o SQL que recebeu, pelo que serve para medir *que decisão* o módulo toma
 * e *que texto* envia — nunca para afirmar que o texto funciona. Essa afirmação
 * é do *gate* 8, que corre as mesmas constantes contra o motor
 * (`db/tests_encomendas/`).
 *
 * O que está aqui é a **resolução de preço**, que é a parte do critério 1 que
 * não precisa de PostgreSQL: qual das duas fontes vale por linha, o que recusa,
 * e como se soma. O que não está é a idempotência, que precisa de transacções a
 * sério.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CONFIRMACOES_DO_DONO,
  ERROS_DA_CRIACAO,
  ESTADOS_POR_PAGAR,
  MINUTOS_PARA_O_DONO,
  MINUTOS_PARA_O_LEMBRETE,
  MOEDA,
  ORIGENS_DE_PRECO,
  STOCK_QUE_EXIGE_O_DONO,
  decidirPorSilencio,
  precoValido,
  proposeCart,
  resolverLinha,
  totalDaProposta,
  type AnelDoSegredo,
  type Leitura,
  type LinhaResolvida,
  type RascunhoDoCarrinho,
} from "../src/orders/index.ts";
import { SQL_PEDIDO_POR_PAGAR } from "../src/orders/consultas.ts";
import { ORDER_STATES } from "../src/port/contrato.ts";

const TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60";
const CONTACTO = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e";
/** O contacto Y, **do mesmo tenant**. É nele que o KAM-179 se mede. */
const OUTRO_CONTACTO = "9b2e4f6a-1c3d-4e5f-8a9b-0c1d2e3f4a5b";
const AGORA = new Date("2026-11-04T10:00:00.000Z");
const ANEL: AnelDoSegredo = [`v2:${Buffer.alloc(32, 7).toString("base64")}`, null];

const RASCUNHO: RascunhoDoCarrinho = {
  contactId: CONTACTO,
  draftId: "d".repeat(64),
  draftVersion: 1,
  linhas: [{ sku: "arroz-5kg", qty: 2 }],
  entregaModo: "levantamento",
};

/** Uma linha de `offer_terms`, como a revisão `0028` a tem. */
function termos(campos: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    sku: "arroz-5kg",
    nome: "Arroz 5 kg",
    preco_tipo: "fixo",
    preco_minor: 125_000,
    currency: MOEDA,
    preco_atualizado_at: "2026-11-01T00:00:00.000Z",
    preco_valido_ate: null,
    stock_modo: "garantido",
    stock_verificado_at: "2026-11-04T09:00:00.000Z",
    estado: "publicado",
    categoria_restrita: null,
    atualizado_at: "2026-11-01T00:00:00.000Z",
    ...campos,
  };
}

/** Uma linha de `price_quotes`. O `preco_total_minor` é o total da linha. */
function cotacao(campos: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "c0ffee00-0000-4000-8000-000000000001",
    contact_id: CONTACTO,
    sku: "arroz-5kg",
    qty: 2,
    preco_total_minor: 200_000,
    currency: MOEDA,
    valida_ate: "2026-11-04T11:00:00.000Z",
    estado: "emitida",
    ...campos,
  };
}

/**
 * Uma `Leitura` falsa, com as respostas por ordem e o SQL gravado.
 *
 * O `inserirNoTenant` **explode**: é a forma mais forte de medir «sem efeitos»
 * do critério 1 — se alguma vez o `propose_cart` escrever, o teste não falha num
 * `assert` que alguém pode apagar, falha na própria chamada.
 */
function leitura(respostas: Record<string, unknown>[][]): {
  l: Leitura;
  vistas: { sql: string; valores: readonly unknown[] }[];
} {
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  let n = 0;
  return {
    vistas,
    l: {
      ctx: { tenantId: TENANT, actor: { kind: "agente", id: "a-1" }, traceId: "t-1" },
      repo: {
        tenantId: TENANT,
        async noTenant(sql: string, valores: readonly unknown[] = []) {
          vistas.push({ sql, valores });
          return respostas[n++] ?? [];
        },
        async inserirNoTenant() {
          throw new Error(
            "o propose_cart escreveu: o criterio 1 diz «sem efeitos» (KAM-046)",
          );
        },
      },
    },
  };
}

// --------------------------------------------------- o domínio dos nomes

test("os dois valores de origem_preco são os do dicionário §3.40", () => {
  assert.deepEqual([...ORIGENS_DE_PRECO], ["offer_terms", "cotacao_dono"]);
});

test("os erros da criação são todos valores de tool_audit.error_code (§3.27)", () => {
  // Os **treze** da lista fechada do §3.27, desde a emenda 1.47. O que este
  // caso afirma é que esta operação **não inventa nome nenhum**: nenhum valor
  // novo entra no dicionário por causa dela. Se alguém acrescentar um, fica
  // vermelho e diz que a lista do dicionário é que tem de mudar primeiro.
  const DO_DICIONARIO = new Set([
    "NOT_FOUND",
    "OUT_OF_STOCK",
    "PRICE_CHANGED",
    "LIMIT_EXCEEDED",
    "ENTITLEMENT_DENIED",
    "TOOL_NOT_ALLOWED",
    "TENANT_MISMATCH",
    "UPSTREAM_TIMEOUT",
    "UPSTREAM_DOWN",
    "VALIDATION_ERROR",
    "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
    "SLOT_TAKEN",
    "HOLD_EXPIRED",
  ]);
  for (const codigo of ERROS_DA_CRIACAO) {
    assert.equal(DO_DICIONARIO.has(codigo), true, codigo);
  }
  // E os quatro que os critérios 4 e 6 nomeiam **estão** lá.
  for (const exigido of [
    "PRICE_CHANGED",
    "OUT_OF_STOCK",
    "LIMIT_EXCEEDED",
    "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
  ] as const) {
    assert.equal(
      (ERROS_DA_CRIACAO as readonly string[]).includes(exigido),
      true,
      exigido,
    );
  }
});

// ------------------------------------------------------- a validade do preço

test("o preço sem validade declarada não caduca, e o instante igual é vencido", () => {
  const base = { sku: "x", nome: "x", precoTipo: "fixo", precoMinor: 1n, currency: MOEDA, stockModo: "garantido", estado: "publicado" };
  assert.equal(precoValido({ ...base, precoValidoAte: null }, AGORA), true);
  // A fronteira exacta: `preco_valido_ate === agora` conta como vencido, que é a
  // mesma escolha que o KAM-043 mediu para a vista da oferta.
  assert.equal(
    precoValido({ ...base, precoValidoAte: AGORA.toISOString() }, AGORA),
    false,
  );
  assert.equal(
    precoValido(
      { ...base, precoValidoAte: new Date(AGORA.getTime() + 1).toISOString() },
      AGORA,
    ),
    true,
  );
  // Um instante ilegível é vencido e não «sem validade»: tratá-lo como válido
  // era deixar uma coluna corrompida valer como preço eterno.
  assert.equal(precoValido({ ...base, precoValidoAte: "nao-e-data" }, AGORA), false);
});

// ------------------------------------------------- a resolução de uma linha

test("um fixo publicado com preço válido resolve por offer_terms", async () => {
  const { l } = leitura([[termos()], []]);
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 2 }, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.origemPreco, "offer_terms");
  assert.equal(r.valor.precoMinor, 125_000n);
  assert.equal(r.valor.qty, 2);
});

test("um sob_consulta sem cotação é recusado e não devolve número", async () => {
  // O critério 1, à letra: «item `sob_consulta` sem cotação é recusado».
  const { l } = leitura([[termos({ preco_tipo: "sob_consulta", preco_minor: null })], []]);
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 2 }, AGORA);
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("um sob_consulta com cotação válida resolve por cotacao_dono", async () => {
  const { l } = leitura([
    [termos({ preco_tipo: "sob_consulta", preco_minor: null })],
    [cotacao()],
  ]);
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 2 }, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.origemPreco, "cotacao_dono");
  assert.equal(r.valor.precoMinor, 200_000n);
});

test("um a_partir_de sem cotação é recusado, como o sob_consulta", async () => {
  // A decisão está escrita no módulo: um «a partir de» é um **mínimo** que o
  // dono declarou, e somá-lo dava ao cliente um número que o dono não prometeu.
  const { l } = leitura([[termos({ preco_tipo: "a_partir_de" })], []]);
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 1 }, AGORA);
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("um fixo com preço vencido é recusado e não soma", async () => {
  const { l } = leitura([
    [termos({ preco_valido_ate: "2026-11-04T09:59:59.000Z" })],
    [],
  ]);
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 1 }, AGORA);
  assert.deepEqual(r, { tipo: "erro", erro: "VALIDATION_ERROR" });
});

test("um fixo com preço vencido mas com cotação válida resolve pela cotação", async () => {
  // A cotação é o caminho do §7.2 para o preço que caducou, e por isso ela
  // ganha: o dono voltou a dar um preço para aquela quantidade.
  const { l } = leitura([
    [termos({ preco_valido_ate: "2026-11-04T09:59:59.000Z" })],
    [cotacao()],
  ]);
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 2 }, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.origemPreco, "cotacao_dono");
});

test("um rascunho não publicado e um sku que não existe dão NOT_FOUND", async () => {
  const semLinha = leitura([[], []]);
  assert.deepEqual(
    await resolverLinha(semLinha.l, CONTACTO, { sku: "nao-existe", qty: 1 }, AGORA),
    { tipo: "erro", erro: "NOT_FOUND" },
  );
  const rascunho = leitura([[termos({ estado: "rascunho" })], []]);
  assert.deepEqual(
    await resolverLinha(rascunho.l, CONTACTO, { sku: "arroz-5kg", qty: 1 }, AGORA),
    { tipo: "erro", erro: "NOT_FOUND" },
  );
});

// ------------- KAM-179: a cotação que resolve a linha é a do próprio contacto

/**
 * Uma `Leitura` cuja base **honra o predicado de contacto** da consulta.
 *
 * O `leitura()` acima devolve as respostas pela ordem das chamadas e ignora os
 * `valores`, pelo que não consegue expressar «a cotação é de outro contacto» —
 * uma cotação volta a quem quer que a peça. Esta devolve a cotação **só** ao
 * contacto dela, e é o que torna os casos abaixo uma medição da propriedade.
 *
 * **E lê o texto do SQL para decidir se filtra**, que é a parte que não é
 * detalhe: um *fake* que filtre sempre pela posição do argumento fica verde com
 * o `AND contact_id = $2` apagado da instrução — mede a forma da chamada e não o
 * predicado. Achado da revisão adversarial, e é exactamente o defeito que esta
 * casa já apanhou uma vez num ensaio citado como prova de uma barreira. Sem o
 * predicado no texto, esta base faz o que o PostgreSQL faria: devolve a linha.
 */
function leituraQueHonraOContacto(
  linhaDeTermos: Record<string, unknown>,
  linhaDeCotacao: Record<string, unknown> | null,
): { l: Leitura; vistas: { sql: string; valores: readonly unknown[] }[] } {
  const vistas: { sql: string; valores: readonly unknown[] }[] = [];
  return {
    vistas,
    l: {
      ctx: { tenantId: TENANT, actor: { kind: "agente", id: "a-1" }, traceId: "t-1" },
      repo: {
        tenantId: TENANT,
        async noTenant(sql: string, valores: readonly unknown[] = []) {
          vistas.push({ sql, valores });
          if (!sql.includes("platform.price_quotes")) return [linhaDeTermos];
          if (linhaDeCotacao === null) return [];
          if (!/contact_id\s*=\s*\$2/.test(sql)) return [linhaDeCotacao];
          return valores[0] === linhaDeCotacao["contact_id"] ? [linhaDeCotacao] : [];
        },
        async inserirNoTenant() {
          throw new Error("o propose_cart escreveu (criterio 1, KAM-046)");
        },
      },
    },
  };
}

test("KAM-179: o contacto desce à leitura da cotação, como o $2 do SQL", async () => {
  // Este é **o caminho que cobra**: a cotação ganha ao `offer_terms`, pelo que
  // sem o predicado o contacto X pagava o total negociado para Y, e o
  // `origem_preco='cotacao_dono'` da linha dizia que o dono o prometeu. O `repo`
  // de ensaio **é** o repo-base, pelo que o `tenant_id` do `$1` não aparece nos
  // `valores`: o contacto é o primeiro que a chamada passa, e o `$2` da consulta.
  const { l, vistas } = leitura([[termos()], [cotacao()]]);
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 2 }, AGORA);
  assert.equal(r.tipo, "ok");
  assert.equal(vistas.length, 2);
  assert.deepEqual(vistas[1]?.valores, [
    CONTACTO,
    "arroz-5kg",
    2,
    AGORA.toISOString(),
  ]);
});

test("KAM-179: a cotação de outro contacto não resolve a linha do carrinho", async () => {
  // A propriedade, e não a forma da chamada: a cotação existe, está `emitida`,
  // não venceu, é do mesmo tenant e do mesmo `(sku, qty)` — e é de Y. A linha de
  // X resolve pelo `offer_terms` e **com o preço do `offer_terms`**, nunca com o
  // total negociado para Y.
  const { l } = leituraQueHonraOContacto(
    termos(),
    cotacao({ contact_id: OUTRO_CONTACTO, preco_total_minor: 900 }),
  );
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 2 }, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.origemPreco, "offer_terms");
  assert.equal(r.valor.precoMinor, 125_000n);
});

test("KAM-179: a cotação do próprio contacto continua a ganhar ao offer_terms", async () => {
  // A sonda positiva da anterior, na mesma base: sem ela, «resolveu pelo
  // `offer_terms`» ficava verde com uma base que nunca devolvesse cotação
  // nenhuma, e nada estava medido.
  const { l } = leituraQueHonraOContacto(termos(), cotacao());
  const r = await resolverLinha(l, CONTACTO, { sku: "arroz-5kg", qty: 2 }, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.origemPreco, "cotacao_dono");
  assert.equal(r.valor.precoMinor, 200_000n);
});

test("KAM-179: o propose_cart leva o contacto do rascunho, e não um qualquer", async () => {
  // **O único sítio em que o contacto verdadeiro entra no caminho que cobra** é
  // o `resolverLinha(l, rascunho.contactId, …)` do `proposeCart`, e nada o
  // media: os casos acima chamam o `resolverLinha` directamente e passam-lhe o
  // contacto à mão, pelo que medem o argumento que o próprio ensaio escreveu.
  // Trocar aquele argumento por um literal deixava tudo verde — e é a mutação
  // que reabre o defeito inteiro. Achado da revisão adversarial.
  //
  // Aqui a cotação é do contacto do rascunho: se a ligação passar outra coisa, a
  // base não a devolve, a linha resolve pelo `offer_terms` e o total muda.
  const { l, vistas } = leituraQueHonraOContacto(termos(), cotacao());
  const r = await proposeCart(l, ANEL, RASCUNHO, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.linhas[0]?.origemPreco, "cotacao_dono");
  assert.equal(r.valor.totalMinor, 200_000n);
  // E o valor que chegou à consulta é o do rascunho, lido do rascunho.
  assert.equal(vistas[1]?.valores[0], RASCUNHO.contactId);
});

test("KAM-179: um rascunho de outro contacto não apanha esta cotação", async () => {
  // A outra direcção do caso acima, que é o que o torna uma medição: o mesmo
  // `(sku, qty)`, a mesma cotação, outro contacto no rascunho — e o preço que
  // sai é o do `offer_terms`.
  const { l } = leituraQueHonraOContacto(termos(), cotacao());
  const r = await proposeCart(
    l,
    ANEL,
    { ...RASCUNHO, contactId: OUTRO_CONTACTO },
    AGORA,
  );
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.linhas[0]?.origemPreco, "offer_terms");
  assert.equal(r.valor.totalMinor, 250_000n);
});

test("KAM-179: um contactId inutilizavel não chega à base", async () => {
  // A mesma propriedade do `sku` vazio, e pela mesma razão: recusa-se antes de
  // falar com a base, e um `contact_id` que não casa com nada **por acaso** em
  // vez de por desenho é um predicado cuja protecção muda com os dados. As
  // formas malformadas não vazias entraram com a revisão adversarial: era por
  // elas que o `22P02` do motor atravessava a porta como excepção.
  const { l, vistas } = leitura([]);
  for (const mau of [
    "",
    "   ",
    "nao-e-um-uuid",
    "7c1d5e3a-2b4f-4a6c-8d0e",
    "' OR 1=1 --",
  ]) {
    assert.deepEqual(
      await resolverLinha(l, mau, { sku: "arroz-5kg", qty: 2 }, AGORA),
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      JSON.stringify(mau),
    );
  }
  assert.equal(vistas.length, 0, "nenhuma consulta devia ter saído");
});

test("um sku vazio e um qty que não é inteiro positivo não chegam à base", async () => {
  const { l, vistas } = leitura([]);
  for (const mau of [
    { sku: "  ", qty: 1 },
    { sku: "x", qty: 0 },
    { sku: "x", qty: -2 },
    { sku: "x", qty: 1.5 },
  ]) {
    assert.deepEqual(await resolverLinha(l, CONTACTO, mau, AGORA), {
      tipo: "erro",
      erro: "VALIDATION_ERROR",
    });
  }
  assert.equal(vistas.length, 0, "nenhuma consulta devia ter saído");
});

// ---------------------------------------------------------------- o total

test("o qty multiplica o offer_terms e não a cotação", () => {
  // A distinção do §7.2: o `preco_minor` da `offer_terms` é unitário e o
  // `preco_total_minor` da cotação é o total da linha. Multiplicar a cotação
  // cobrava dez vezes o preço de dez.
  const linhas: LinhaResolvida[] = [
    { sku: "a", nome: "a", qty: 3, precoMinor: 100n, precoTipo: "fixo", origemPreco: "offer_terms", stockModo: "garantido" },
    { sku: "b", nome: "b", qty: 10, precoMinor: 700n, precoTipo: "sob_consulta", origemPreco: "cotacao_dono", stockModo: "garantido" },
  ];
  assert.equal(totalDaProposta(linhas), 300n + 700n);
});

test("o total é bigint e não perde precisão acima de 2^53", () => {
  const linhas: LinhaResolvida[] = [
    { sku: "a", nome: "a", qty: 2, precoMinor: 9_007_199_254_740_993n, precoTipo: "fixo", origemPreco: "offer_terms", stockModo: "garantido" },
  ];
  assert.equal(totalDaProposta(linhas), 18_014_398_509_481_986n);
});

// --------------------------------------------------------- o propose_cart

test("o propose_cart soma no backend e devolve cart_id, total e as linhas", async () => {
  const { l } = leitura([[termos()], []]);
  const r = await proposeCart(l, ANEL, RASCUNHO, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.totalMinor, 250_000n);
  assert.equal(r.valor.currency, MOEDA);
  assert.match(r.valor.cartId, /^[0-9A-HJKMNP-TV-Z]{26}$/);
  assert.equal(r.valor.linhas.length, 1);
  assert.equal(r.valor.draftHash.length, 32);
});

test("o propose_cart não escreve: o inserirNoTenant explodia se escrevesse", async () => {
  // Ver a nota do `leitura`. O que isto mede é «sem efeitos» do critério 1 por
  // execução e não por leitura do código.
  const { l, vistas } = leitura([[termos()], []]);
  const r = await proposeCart(l, ANEL, RASCUNHO, AGORA);
  assert.equal(r.tipo, "ok");
  for (const vista of vistas) {
    assert.match(vista.sql.trim().slice(0, 6).toUpperCase(), /SELECT/);
  }
});

test("uma linha que não resolve recusa o carrinho inteiro", async () => {
  // Não se devolve um carrinho parcial: o total de um carrinho a que falta uma
  // linha é um número que o cliente leria como o preço do que pediu.
  const { l } = leitura([
    [termos({ sku: "arroz-5kg" })],
    [],
    [], // a segunda linha não existe
    [],
  ]);
  const r = await proposeCart(
    l,
    ANEL,
    {
      ...RASCUNHO,
      linhas: [
        { sku: "arroz-5kg", qty: 1 },
        { sku: "zzz", qty: 1 },
      ],
    },
    AGORA,
  );
  assert.deepEqual(r, { tipo: "erro", erro: "NOT_FOUND" });
});

test("uma linha confirmar_dono marca o carrinho como a exigir o dono", async () => {
  const { l } = leitura([[termos({ stock_modo: STOCK_QUE_EXIGE_O_DONO })], []]);
  const r = await proposeCart(l, ANEL, RASCUNHO, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.equal(r.valor.exigeConfirmacaoDoDono, true);
});

test("um rascunho sem linhas e uma linha inválida são VALIDATION_ERROR", async () => {
  const { l } = leitura([]);
  assert.deepEqual(
    await proposeCart(l, ANEL, { ...RASCUNHO, linhas: [] }, AGORA),
    { tipo: "erro", erro: "VALIDATION_ERROR" },
  );
  assert.deepEqual(
    await proposeCart(
      l,
      ANEL,
      { ...RASCUNHO, linhas: [{ sku: "", qty: 1 }] },
      AGORA,
    ),
    { tipo: "erro", erro: "VALIDATION_ERROR" },
  );
});

test("as linhas voltam pela ordem canónica e não pela ordem do pedido", async () => {
  // É a mesma ordem que entra no `draft_hash`, pelo que quem compare a resposta
  // com o `lines_snapshot` da encomenda vê a mesma sequência.
  const { l } = leitura([
    [termos({ sku: "arroz-5kg" })],
    [],
    [termos({ sku: "sabao-azul", nome: "Sabão" })],
    [],
  ]);
  const itens = [
    { sku: "sabao-azul", qty: 1 },
    { sku: "arroz-5kg", qty: 1 },
  ];
  const r = await proposeCart(l, ANEL, { ...RASCUNHO, linhas: itens }, AGORA);
  assert.equal(r.tipo, "ok");
  if (r.tipo !== "ok") return;
  assert.deepEqual(
    r.valor.linhas.map((linha) => linha.sku),
    ["arroz-5kg", "sabao-azul"],
  );
});

// ---------------------------------------------- o silêncio do dono (critério 7)

test("a decisão do silêncio: aguardar, lembrar aos 5 min, expirar aos 15", () => {
  const pedido = new Date("2026-11-04T10:00:00.000Z");
  const em = (minutos: number) =>
    new Date(pedido.getTime() + minutos * 60_000);
  assert.equal(decidirPorSilencio(pedido, em(0), false), "aguardar");
  assert.equal(decidirPorSilencio(pedido, em(4.99), false), "aguardar");
  // A fronteira é `>=` nos dois limiares: aos cinco exactos lembra, aos quinze
  // exactos expira. Com `>`, uma encomenda ficava um instante em cada lado sem
  // acção nenhuma, e o varrimento que corresse nesse instante não fazia nada.
  assert.equal(decidirPorSilencio(pedido, em(MINUTOS_PARA_O_LEMBRETE), false), "lembrar");
  assert.equal(decidirPorSilencio(pedido, em(14.99), false), "lembrar");
  assert.equal(decidirPorSilencio(pedido, em(MINUTOS_PARA_O_DONO), false), "expirar");
  assert.equal(decidirPorSilencio(pedido, em(60), false), "expirar");
});

test("o lembrete não se repete, e a expiração ignora se ele foi enviado", () => {
  const pedido = new Date("2026-11-04T10:00:00.000Z");
  const em = (minutos: number) =>
    new Date(pedido.getTime() + minutos * 60_000);
  assert.equal(decidirPorSilencio(pedido, em(7), true), "aguardar");
  assert.equal(decidirPorSilencio(pedido, em(16), true), "expirar");
});

test("os ESTADOS_POR_PAGAR são exactamente os três que a consulta filtra", () => {
  // **Uma constante sem consumidor é uma declaração morta**, e o dicionário
  // §3.44 nomeia esta lista: sem este caso, ela e o `IN (...)` do
  // `SQL_PEDIDO_POR_PAGAR` eram duas fontes para a mesma regra e podiam
  // divergir sem ninguém ver — que é o modo de falha que esta casa já pagou
  // quatro vezes noutro eixo (as contagens em prosa).
  //
  // **Nos dois sentidos**, como o `EXERCITADAS` da suite do *gate* 8: um estado
  // na constante que a consulta não filtre, e um na consulta que a constante não
  // declare, reprovam os dois.
  const naConsulta = [...SQL_PEDIDO_POR_PAGAR.matchAll(/'([a-z_]+)'/g)].map(
    (m) => m[1],
  );
  const doEstado = naConsulta.filter((v) =>
    (ESTADOS_POR_PAGAR as readonly string[]).includes(v as string),
  );
  assert.deepEqual(
    [...new Set(doEstado)].sort(),
    [...ESTADOS_POR_PAGAR].sort(),
    "a constante e o IN (...) da consulta divergiram",
  );
  // E os três são estados do domínio da coluna (os doze do dicionário §3.3).
  for (const estado of ESTADOS_POR_PAGAR) {
    assert.ok(
      (ORDER_STATES as readonly string[]).includes(estado),
      `${estado} não é um dos doze ORDER_STATES`,
    );
  }
  // **Três e não «tudo menos `paga`»**: uma encomenda `cancelada` ou `expirada`
  // não é um pedido por pagar, e afirmar isto impede que alguém «simplifique» a
  // consulta para `estado <> 'paga'`.
  for (const fora of ["paga", "cancelada", "expirada", "entregue"] as const) {
    assert.equal(
      (ESTADOS_POR_PAGAR as readonly string[]).includes(fora),
      false,
      fora,
    );
  }
});

test("os cinco CONFIRMACOES_DO_DONO são o domínio do CHECK da revisão 0030", () => {
  // A mesma razão: a lista existe para que o módulo e a base digam o mesmo, e
  // sem um caso que a prenda ela é uma cópia que ninguém confronta. O domínio a
  // sério é o `orders_mirror_confirmacao_ck`, e quem o mede contra o motor é o
  // `db/tests_encomendas/test_idempotencia.py`.
  assert.deepEqual(
    [...CONFIRMACOES_DO_DONO],
    ["nao_aplicavel", "pendente", "confirmada", "recusada", "expirada"],
  );
  // O valor de omissão da coluna e o que o critério 7 exige são destes cinco.
  assert.ok((CONFIRMACOES_DO_DONO as readonly string[]).includes("pendente"));
  assert.ok(
    (CONFIRMACOES_DO_DONO as readonly string[]).includes("nao_aplicavel"),
  );
});
