/**
 * O critério 6 e a idempotência do DoD do KAM-043, medidos sobre as operações.
 *
 * Duas coisas que nenhum dos outros ficheiros deste ticket mede:
 *
 *   critério 6   `price_quotes` só por actor `dono` autenticado, com
 *                `valida_ate`; cotação expirada não é aceite; o `getValidQuote`
 *                devolve a cotação válida **ou nada**
 *   DoD          «`publishProduct` e ajustes de stock repetidos não duplicam
 *                efeitos nem eventos»
 *
 * ## A base de ensaio **registra** o que lhe mandam, e é isso que a torna útil
 *
 * Uma base falsa que devolva linhas plausíveis prova que o código corre. O que
 * estes casos precisam de afirmar é o contrário: que em certas condições o
 * código **não escreve, não audita e não emite**. Por isso esta base guarda cada
 * chamada por categoria — escritas, auditorias, eventos — e as asserções são
 * sobre as contagens.
 *
 * O que ela **não** pode provar, e fica dito: que o `FOR UPDATE` serializa duas
 * transacções concorrentes. Isso é do motor, e um `Promise.all` em JavaScript
 * sobre um objecto em memória não tem transacções para serializar. A
 * idempotência que estes casos medem é a da **repetição** — a mesma chamada duas
 * vezes, em série —, que é a letra do DoD. A da concorrência é uma lacuna
 * nomeada na verificação do bloco: fecha-se com duas ligações a um PostgreSQL
 * real, como o `tests_servicos` faz para as mil paralelas, e este ticket não a
 * entrega.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type ClienteSql,
  type Ctx,
} from "../src/port/index.ts";
import {
  ChamadaNaoPermitidaError,
  adaptadorMedusa,
  comRegisto,
  type Dependencias,
} from "../src/adapters/medusa/index.ts";
import {
  SQL_AUDITAR,
  SQL_EMITIR,
  TIPO_PRICE_CHANGED,
  TIPO_PRODUCT_CHANGED,
  TIPO_STOCK_ADJUSTED,
  TIPO_STOCK_LOW,
  aceitarCotacao,
  ajustarStock,
  emitirCotacao,
  getValidQuote,
  searchOffers,
} from "../src/produtos/index.ts";

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const CONTACTO = "0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c";
const SKU = "arroz-5kg";
const AGORA = new Date("2026-11-02T12:00:00.000Z");

/** O que a base de ensaio viu, por categoria. */
interface Registo {
  readonly escritas: string[];
  readonly auditorias: unknown[][];
  readonly eventos: string[];
}

interface Opcoes {
  /** A oferta existe? Se não, o `lerParaEscrita` devolve nada. */
  readonly oferta?: Partial<Record<string, unknown>> | null;
  /** A cotação que o `SQL_COTACAO_VALIDA` devolve, ou nada. */
  readonly cotacao?: Record<string, unknown> | null;
}

function base(opcoes: Opcoes = {}): {
  cliente: ClienteSql;
  visto: Registo;
} {
  const visto: Registo = { escritas: [], auditorias: [], eventos: [] };
  const oferta =
    opcoes.oferta === undefined
      ? {
          sku: SKU,
          nome: "Arroz 5 kg",
          preco_tipo: "fixo",
          preco_minor: "1250000",
          currency: "AOA",
          preco_atualizado_at: "2026-11-01T00:00:00.000Z",
          preco_valido_ate: null,
          stock_modo: "garantido",
          stock_verificado_at: "2026-11-02T11:00:00.000Z",
          estado: "publicado",
          categoria_restrita: null,
          atualizado_at: "2026-11-02T11:00:00.000Z",
        }
      : opcoes.oferta;

  const cliente: ClienteSql = {
    async query(sql: string, parametros: readonly unknown[] = []) {
      if (sql.includes("platform.tenants")) {
        return {
          rows: [{ medusa_merchant_id: "merch", medusa_sales_channel_id: null }],
        };
      }
      if (sql.includes("audit_append")) {
        visto.auditorias.push([...parametros]);
        return { rows: [{}] };
      }
      if (sql.includes("evt_emitir")) {
        visto.eventos.push(String(parametros[0]));
        return { rows: [{ event_id: `evt-${visto.eventos.length}` }] };
      }
      if (sql.includes("platform.price_quotes")) {
        if (/^\s*INSERT/i.test(sql)) {
          visto.escritas.push("insert price_quotes");
          return {
            rows: [
              {
                id: "q1",
                sku: SKU,
                qty: 10,
                preco_total_minor: "12500000",
                currency: "AOA",
                valida_ate: "2026-11-03T12:00:00.000Z",
                estado: "emitida",
              },
            ],
          };
        }
        return { rows: opcoes.cotacao ? [opcoes.cotacao] : [] };
      }
      if (sql.includes("platform.offer_terms")) {
        if (/^\s*UPDATE/i.test(sql)) {
          visto.escritas.push("update offer_terms");
          return { rows: [{ sku: SKU, estado: "publicado", atualizado_at: "x" }] };
        }
        if (/^\s*INSERT/i.test(sql)) {
          visto.escritas.push("insert offer_terms");
          return { rows: [{ sku: SKU, medusa_variant_id: null }] };
        }
        return { rows: oferta === null ? [] : [oferta] };
      }
      return { rows: [] };
    },
  };
  return { cliente, visto };
}

function deps(cliente: ClienteSql): Dependencias {
  return { comTenant: async (_t, trabalho) => trabalho(cliente) };
}

function ctx(kind: "agente" | "dono" | "sistema" | "ops" = "dono"): Ctx {
  return {
    tenantId: TENANT,
    actor: { kind, id: `actor-${kind}` },
    traceId: "trace-operacoes",
  };
}

// ----------------------------------------------- critério 6: as cotações

test("criterio 6: so um actor dono cria uma cotacao", async () => {
  for (const kind of ["agente", "sistema", "ops"] as const) {
    const { cliente, visto } = base();
    const resultado = await comRegisto(deps(cliente), ctx(kind), (r) =>
      emitirCotacao(
        r,
        {
          sku: SKU,
          qty: 10,
          contactId: CONTACTO,
          precoTotalMinor: 12_500_000n,
          validaAte: "2026-11-03T12:00:00.000Z",
        },
        AGORA,
      ),
    );
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      `o actor '${kind}' nao pode cotar`,
    );
    // **E não escreve nada.** Uma recusa que já tivesse inserido a linha era
    // uma recusa depois do facto.
    assert.deepEqual(visto.escritas, [], kind);
    assert.deepEqual(visto.auditorias, [], kind);
  }
});

test("criterio 6: o dono cria, e a cotacao fica auditada", async () => {
  const { cliente, visto } = base();
  const resultado = await comRegisto(deps(cliente), ctx("dono"), (r) =>
    emitirCotacao(
      r,
      {
        sku: SKU,
        qty: 10,
        contactId: CONTACTO,
        precoTotalMinor: 12_500_000n,
        validaAte: "2026-11-03T12:00:00.000Z",
      },
      AGORA,
    ),
  );
  assert.equal(resultado.tipo, "ok");
  assert.deepEqual(visto.escritas, ["insert price_quotes"]);
  // O `emitida_por` é o `actor.id` do `ctx` e **não** um argumento: com um
  // argumento, o chamador escrevia o id de outro dono na cotação.
  assert.equal(visto.auditorias.length, 1);
  assert.equal(visto.auditorias[0]?.[1], "owner");
  assert.equal(visto.auditorias[0]?.[2], "actor-dono");
  // **Uma cotação não emite evento de catálogo.** O preço dela não é o preço
  // publicado do produto, e um `catalog.price_changed` dizia ao DAT que o preço
  // da oferta mudou quando o que houve foi uma cotação para um cliente.
  assert.deepEqual(visto.eventos, []);
});

test("criterio 6: uma cotacao emitida ja vencida e recusada", async () => {
  // Aceitá-la deixava uma linha que o `getValidQuote` nunca devolve a ocupar a
  // tabela com a aparência de uma oferta feita ao cliente.
  for (const validaAte of [
    "2026-11-02T12:00:00.000Z", // === AGORA: a fronteira exacta
    "2026-11-01T00:00:00.000Z", // passado
    "nao-e-uma-hora",
  ]) {
    const { cliente, visto } = base();
    const resultado = await comRegisto(deps(cliente), ctx("dono"), (r) =>
      emitirCotacao(
        r,
        {
          sku: SKU,
          qty: 10,
          contactId: CONTACTO,
          precoTotalMinor: 12_500_000n,
          validaAte,
        },
        AGORA,
      ),
    );
    assert.deepEqual(
      resultado,
      { tipo: "erro", erro: "VALIDATION_ERROR" },
      validaAte,
    );
    assert.deepEqual(visto.escritas, [], validaAte);
  }
});

test("criterio 6: uma quantidade nula ou negativa e recusada", async () => {
  for (const qty of [0, -1, 1.5]) {
    const { cliente } = base();
    const resultado = await comRegisto(deps(cliente), ctx("dono"), (r) =>
      emitirCotacao(
        r,
        {
          sku: SKU,
          qty,
          contactId: CONTACTO,
          precoTotalMinor: 1n,
          validaAte: "2026-11-03T12:00:00.000Z",
        },
        AGORA,
      ),
    );
    assert.deepEqual(resultado, { tipo: "erro", erro: "VALIDATION_ERROR" }, String(qty));
  }
});

test("criterio 6: getValidQuote devolve nada quando nao ha, e nao um erro", async () => {
  // «Não há cotação» é uma **resposta** e não uma falha: o chamador que precisa
  // de uma recusa é o `createOrder` (KAM-046), que sabe o que fazer com a
  // ausência. Um erro obrigava-o a distinguir «não há» de «a ligação caiu».
  const { cliente } = base({ cotacao: null });
  const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
    getValidQuote(r, SKU, 10, AGORA),
  );
  assert.deepEqual(resultado, { tipo: "ok", valor: null });
});

test("criterio 6: getValidQuote devolve a cotacao viva, com o total em bigint", async () => {
  const { cliente } = base({
    cotacao: {
      id: "q1",
      sku: SKU,
      qty: 10,
      preco_total_minor: "12500000",
      currency: "AOA",
      valida_ate: "2026-11-03T12:00:00.000Z",
      estado: "emitida",
    },
  });
  const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
    getValidQuote(r, SKU, 10, AGORA),
  );
  assert.equal(resultado.tipo, "ok");
  if (resultado.tipo === "ok" && resultado.valor !== null) {
    // **`bigint` e não `number`.** O *driver* devolve o `bigint` do PostgreSQL
    // como `string` para não perder precisão, e é aqui que ele volta a ser
    // dinheiro.
    assert.equal(typeof resultado.valor.precoTotalMinor, "bigint");
    assert.equal(resultado.valor.precoTotalMinor, 12_500_000n);
    assert.equal(resultado.valor.qty, 10);
  }
});

test("criterio 6: getValidQuote recusa uma quantidade que nao e inteiro positivo", async () => {
  for (const qty of [0, -1, 2.5]) {
    const { cliente } = base();
    const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
      getValidQuote(r, SKU, qty, AGORA),
    );
    assert.deepEqual(resultado, { tipo: "erro", erro: "VALIDATION_ERROR" }, String(qty));
  }
});

// ------------------------------------------------- DoD: a idempotência

test("DoD: publicar o que ja esta publicado nao escreve, nao audita e nao emite", async () => {
  // Sem isto, cada repetição emitia um `catalog.product_changed` e o IDX
  // reindexava por nada — e a linha de auditoria dizia que houve uma
  // publicação que não houve.
  const { cliente, visto } = base();
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const confirmacao = {
    actor: { kind: "dono", id: "msg-1" },
    em: "2026-11-01T10:00:00Z",
  } as const;

  const primeira = await porta.publishProduct(
    ctx(),
    { sku: SKU, registoId: null },
    confirmacao,
  );
  assert.deepEqual(primeira, { tipo: "ok", valor: undefined });
  assert.deepEqual(visto.escritas, []);
  assert.deepEqual(visto.auditorias, []);
  assert.deepEqual(visto.eventos, []);
});

test("DoD: publicar um rascunho escreve, audita e emite — uma vez de cada", async () => {
  const { cliente, visto } = base({
    oferta: {
      sku: SKU,
      nome: "Arroz 5 kg",
      preco_tipo: "fixo",
      preco_minor: "1250000",
      currency: "AOA",
      preco_atualizado_at: null,
      preco_valido_ate: null,
      stock_modo: "garantido",
      stock_verificado_at: null,
      estado: "rascunho",
      categoria_restrita: null,
      atualizado_at: "2026-11-02T11:00:00.000Z",
    },
  });
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const resultado = await porta.publishProduct(
    ctx(),
    { sku: SKU, registoId: null },
    { actor: { kind: "dono", id: "msg-1" }, em: "2026-11-01T10:00:00Z" },
  );
  assert.deepEqual(resultado, { tipo: "ok", valor: undefined });
  assert.deepEqual(visto.escritas, ["update offer_terms"]);
  assert.equal(visto.auditorias.length, 1);
  assert.deepEqual(visto.eventos, [TIPO_PRODUCT_CHANGED]);
  // **O actor auditado é quem chamou, e a confirmação vai no instantâneo.**
  //
  // A primeira versão gravava `confirmacao.actor.id` como `actor_id`, e a
  // revisão adversarial mostrou o custo: o `actor.id` de uma `OwnerConfirmation`
  // é o **id da mensagem** que confirmou, pelo que a linha ficava com um id de
  // mensagem no campo do actor e **quem chamou não era gravado em sítio nenhum**
  // — quem auditasse «as acções do actor X» não encontrava publicações.
  assert.equal(visto.auditorias[0]?.[1], "owner");
  assert.equal(visto.auditorias[0]?.[2], "actor-dono");
  // E o id da mensagem entra no texto resumido pelo `depois`, que é onde um id
  // de mensagem pertence.
  assert.equal(
    String(visto.auditorias[0]?.[7]).includes("msg-1"),
    true,
    "o id da confirmacao tem de entrar no instantaneo `depois`",
  );
});

test("criterio 4: um produto com categoria restrita nao publica", async () => {
  const { cliente, visto } = base({
    oferta: {
      sku: SKU,
      nome: "Produto restrito",
      preco_tipo: "fixo",
      preco_minor: "1000",
      currency: "AOA",
      preco_atualizado_at: null,
      preco_valido_ate: null,
      stock_modo: "garantido",
      stock_verificado_at: null,
      estado: "rascunho",
      categoria_restrita: "medicamentos",
      atualizado_at: "x",
    },
  });
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const resultado = await porta.publishProduct(
    ctx(),
    { sku: SKU, registoId: null },
    { actor: { kind: "dono", id: "msg-1" }, em: "2026-11-01T10:00:00Z" },
  );
  assert.deepEqual(resultado, { tipo: "erro", erro: "VALIDATION_ERROR" });
  assert.deepEqual(visto.escritas, []);
  assert.deepEqual(visto.eventos, []);
});

test("DoD: um upsert que nao muda nada nao escreve, nao audita e nao emite", async () => {
  // A repetição exacta do mesmo rascunho: o preço, o nome e o modo de stock são
  // os mesmos. **Nem o `UPDATE` corre.**
  //
  // A primeira versão corria-o — era uma instrução só — e a revisão adversarial
  // mostrou o que isso custava: o `atualizado_at` e o `preco_atualizado_at` eram
  // reescritos, pelo que o `OfferView.atualizadoAt` mudava sem nada ter mudado, e
  // a coluna que a `0028` documenta como «quando o preço foi posto» passava a
  // significar «quando alguém reescreveu o rascunho». A comparação passou a ser
  // **anterior** à escrita.
  const { cliente, visto } = base();
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const resultado = await porta.upsertProductDraft(ctx(), {
    sku: SKU,
    nome: "Arroz 5 kg",
    atributos: {
      preco_tipo: "fixo",
      preco_minor: 1_250_000,
      stock_modo: "garantido",
    },
  });
  assert.equal(resultado.tipo, "ok");
  assert.deepEqual(visto.escritas, [], "nada mudou: nao ha o que escrever");
  assert.deepEqual(visto.auditorias, [], "nada mudou: nao ha o que auditar");
  assert.deepEqual(visto.eventos, [], "nada mudou: nao ha o que anunciar");
});

test("DoD: um upsert que muda **so** o preco_valido_ate audita e emite", async () => {
  // **O caso que a revisão adversarial encontrou.** O `preco_valido_ate` não
  // entrava na comparação do preço: passá-lo de nulo para uma data mudava a
  // linha, fazia o `getOfferView` passar a ler `a_partir_de` com aviso (critério
  // 3) e **não** emitia `catalog.price_changed` nem escrevia `audit_log` — uma
  // alteração do preço citável sem rasto, contra o critério 5.
  const { cliente, visto } = base();
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const resultado = await porta.upsertProductDraft(ctx(), {
    sku: SKU,
    nome: "Arroz 5 kg",
    atributos: {
      preco_tipo: "fixo",
      preco_minor: 1_250_000, // o mesmo
      stock_modo: "garantido", // o mesmo
      preco_valido_ate: "2026-11-01T00:00:00.000Z", // era nulo
    },
  });
  assert.equal(resultado.tipo, "ok");
  assert.deepEqual(visto.escritas, ["update offer_terms"]);
  assert.equal(visto.auditorias.length, 1, "o preco mudou: audita");
  assert.equal(visto.auditorias[0]?.[3], "price.update");
  assert.deepEqual(
    [...visto.eventos].sort(),
    [TIPO_PRICE_CHANGED, TIPO_PRODUCT_CHANGED].sort(),
  );
});

test("DoD: um upsert que muda o preco audita e emite exactamente uma vez cada", async () => {
  const { cliente, visto } = base();
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const resultado = await porta.upsertProductDraft(ctx(), {
    sku: SKU,
    nome: "Arroz 5 kg",
    atributos: {
      preco_tipo: "fixo",
      preco_minor: 1_500_000, // era 1 250 000
      stock_modo: "garantido",
    },
  });
  assert.equal(resultado.tipo, "ok");
  assert.equal(visto.auditorias.length, 1, "uma linha de auditoria");
  assert.equal(visto.auditorias[0]?.[3], "price.update");
  // Dois eventos e não um, e são de tipos diferentes: o preço mudou
  // (`catalog.price_changed`, que vai para o DAT) e o produto mudou
  // (`catalog.product_changed`, que vai para o IDX). Um só não servia os dois
  // consumidores, e o do IDX **não leva preço**.
  assert.deepEqual(
    [...visto.eventos].sort(),
    [TIPO_PRICE_CHANGED, TIPO_PRODUCT_CHANGED].sort(),
  );
});

test("criterio 5: um ajuste de stock audita e emite, e o stock.low entra abaixo do limiar", async () => {
  const { cliente, visto } = base();
  const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
    ajustarStock(r, { sku: SKU, qty: 3, motivo: "ajuste_do_dono" }),
  );
  assert.equal(resultado.tipo, "ok");
  assert.equal(visto.auditorias.length, 1);
  assert.equal(visto.auditorias[0]?.[3], "stock.adjust");
  // Três está abaixo do limiar de cinco (*proposta*), logo saem os dois.
  assert.deepEqual(visto.eventos, [TIPO_STOCK_ADJUSTED, TIPO_STOCK_LOW]);
});

test("DoD: um ajuste de stock repetido **duplica**, e e por isso que a caixa fica vazia", async () => {
  // **Este caso afirma o que NAO se cumpre, e e deliberado.** A caixa de DoD
  // «ajustes de stock repetidos não duplicam efeitos nem eventos» **não se
  // marca**, e a razão é que a quantidade não tem coluna em `offer_terms` onde
  // ser comparada: o §5.4 põe o stock no Registo.
  //
  // O caminho que não se tomou foi cortar quando o `stock_modo` não muda — e
  // engolia em silêncio o caso **comum**, o dono a corrigir a quantidade sem
  // mudar o modo. Suprimir sem poder comparar é pior do que duplicar: um nível
  // emitido duas vezes é visível a jusante e o consumidor é idempotente por
  // `evento.id` (ADR-009), e um ajuste engolido não é visível em sítio nenhum.
  //
  // Um teste que afirma o que não se cumpre vale mais do que uma caixa vazia
  // sozinha: no dia em que alguém der quantidade a esta tabela, este caso fica
  // vermelho e diz-lhe que a caixa passou a ser marcável.
  const { cliente, visto } = base();
  for (const _tentativa of [1, 2]) {
    const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
      ajustarStock(r, { sku: SKU, qty: 3, motivo: "ajuste_do_dono" }),
    );
    assert.equal(resultado.tipo, "ok");
  }
  assert.equal(visto.auditorias.length, 2, "duas linhas de auditoria, hoje");
  assert.deepEqual(visto.eventos, [
    TIPO_STOCK_ADJUSTED,
    TIPO_STOCK_LOW,
    TIPO_STOCK_ADJUSTED,
    TIPO_STOCK_LOW,
  ]);
});

test("criterio 5: acima do limiar o stock.low nao sai", async () => {
  const { cliente, visto } = base();
  const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
    ajustarStock(r, { sku: SKU, qty: 50, motivo: "conferencia" }),
  );
  assert.equal(resultado.tipo, "ok");
  assert.deepEqual(visto.eventos, [TIPO_STOCK_ADJUSTED]);
});

test("criterio 5: um ajuste sobre uma oferta que nao existe nao audita nem emite", async () => {
  const { cliente, visto } = base({ oferta: null });
  const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
    ajustarStock(r, { sku: SKU, qty: 3, motivo: "ajuste_do_dono" }),
  );
  assert.deepEqual(resultado, { tipo: "erro", erro: "NOT_FOUND" });
  assert.deepEqual(visto.auditorias, []);
  assert.deepEqual(visto.eventos, []);
});

test("criterio 5: uma quantidade negativa ou fraccionada e recusada antes de escrever", async () => {
  for (const qty of [-1, 2.5]) {
    const { cliente, visto } = base();
    const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
      ajustarStock(r, { sku: SKU, qty, motivo: "ajuste_do_dono" }),
    );
    assert.deepEqual(resultado, { tipo: "erro", erro: "VALIDATION_ERROR" }, String(qty));
    assert.deepEqual(visto.escritas, [], String(qty));
  }
});

// ------------------------------------- critério 2: a porta devolve seis campos

test("criterio 2: o getOfferView da porta devolve os seis campos do contrato", async () => {
  // Os `avisos` do critério 3 são o sétimo e **não** saem pela porta: o §3.39
  // do dicionário fecha a `OfferView` em seis, e acrescentá-los era alargar um
  // contrato que o KAM-042 pinou num teste. Quem os quer chama o módulo.
  const { cliente } = base();
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const resultado = await porta.getOfferView(ctx(), SKU);
  assert.equal(resultado.tipo, "ok");
  if (resultado.tipo === "ok") {
    assert.deepEqual(Object.keys(resultado.valor).sort(), [
      "atualizadoAt",
      "disponibilidade",
      "precoDisplay",
      "precoTipo",
      "sku",
      "stockModo",
    ]);
  }
});

test("criterio 2: um rascunho nao se oferece a um cliente", async () => {
  // O `getOfferView` é a vista que o agente cita. Um rascunho citado era um
  // preço à frente de um cliente sem o dono o ter publicado — o critério 4 ao
  // contrário.
  const { cliente } = base({
    oferta: {
      sku: SKU,
      nome: "Arroz 5 kg",
      preco_tipo: "fixo",
      preco_minor: "1250000",
      currency: "AOA",
      preco_atualizado_at: null,
      preco_valido_ate: null,
      stock_modo: "garantido",
      stock_verificado_at: null,
      estado: "rascunho",
      categoria_restrita: null,
      atualizado_at: "x",
    },
  });
  const porta = adaptadorMedusa(deps(cliente), () => AGORA);
  const resultado = await porta.getOfferView(ctx(), SKU);
  assert.deepEqual(resultado, { tipo: "erro", erro: "NOT_FOUND" });
});

// ------------------------------------------- a barreira do `Registo.emitir`

test("o Registo.emitir recusa qualquer coisa que nao sejam as duas chamadas", async () => {
  // **O canário da barreira do achado 9 da revisão adversarial.** Sem este
  // caso, o embrulho era uma frase: a revisão mostrou que um ticket futuro
  // escrevia `r.emitir.query("SELECT * FROM product …")` e saía sem filtro de
  // tenant, sem o contador de recusas e — no Registo da opção B — **sem RLS
  // atrás**.
  const { cliente } = base();
  await comRegisto(deps(cliente), ctx(), async (r) => {
    for (const sql of [
      "SELECT * FROM product WHERE sku = $1",
      "SELECT * FROM platform.offer_terms",
      // E o contorno óbvio: o nome da função dentro de um comentário. É por
      // isto que a comparação é por igualdade com a constante e não por
      // `includes`.
      "SELECT * FROM product; -- platform.evt_emitir",
    ]) {
      await assert.rejects(
        () => r.emitir.query(sql, []),
        ChamadaNaoPermitidaError,
        sql,
      );
    }
  });
});

test("o Registo.emitir deixa passar as duas chamadas, e so as duas", async () => {
  // O caminho legítimo. **Sem ele, o caso de cima ficava verde sobre um embrulho
  // que recusava tudo** — e era o que os dois ficheiros que dependem dele
  // descobriam no primeiro evento real. É a terceira vez neste repositório que
  // um caso do uso correcto é que apanha a barreira demasiado estreita.
  const { cliente, visto } = base();
  await comRegisto(deps(cliente), ctx(), async (r) => {
    await r.emitir.query(SQL_EMITIR, [
      TIPO_PRODUCT_CHANGED,
      1,
      TENANT,
      "product",
      SKU,
      JSON.stringify({ sku: SKU, estado: "rascunho" }),
      "P0",
      ["transacao"],
    ]);
    await r.emitir.query(SQL_AUDITAR, [
      TENANT,
      "owner",
      "o-dono",
      "price.update",
      "offer_terms",
      SKU,
      null,
      "x",
    ]);
  });
  assert.deepEqual(visto.eventos, [TIPO_PRODUCT_CHANGED]);
  assert.equal(visto.auditorias.length, 1);
});

// --------------------------------- critério 6: a cotação vencida nao se aceita

test("criterio 6: aceitar uma cotacao vencida nao a aceita", async () => {
  // **O achado 2 da revisão adversarial.** O `SQL_ACEITAR_COTACAO` filtrava só
  // por `estado = 'emitida'`, e isso não bastava precisamente pela razão que o
  // módulo escreve em todo o lado: a expiração é por `valida_ate` e não pelo
  // estado, pelo que uma cotação de Janeiro com `estado='emitida'` passava a
  // `aceite` em Novembro.
  //
  // A base de ensaio devolve zero linhas, que é o que o predicado novo faz
  // contra uma vencida. O que este caso afirma é que a assinatura **leva o
  // instante**: sem ele não há terceiro parâmetro, e o teste nem compilava — que
  // é a forma de o tipo guardar a correcção.
  const { cliente } = base({ cotacao: null });
  const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
    aceitarCotacao(r, "q1", AGORA),
  );
  assert.deepEqual(resultado, { tipo: "erro", erro: "NOT_FOUND" });
});

// --------------------------------------------- critério 8: a pesquisa mínima

test("criterio 8: um termo vazio devolve nada, e nao o catalogo inteiro", async () => {
  // A mesma propriedade do ISO-10 noutra superfície: um filtro vazio não lista
  // o catálogo inteiro. E recusa **antes** de falar com a base.
  const { cliente } = base();
  for (const termo of ["", "   ", "\t"]) {
    const resultado = await comRegisto(deps(cliente), ctx(), (r) =>
      searchOffers(r, termo),
    );
    assert.deepEqual(
      resultado,
      { tipo: "ok", valor: [] },
      JSON.stringify(termo),
    );
  }
});
