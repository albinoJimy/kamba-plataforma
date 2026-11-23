/**
 * A violação de um produto publicado que um `screen` posterior bloqueia
 * (KAM-245), pela operação do `/internal/screen` com a política real.
 *
 * A base é um duplo que **lê o texto da instrução** da oferta: cada predicado
 * do `SQL_PUBLICADO_SOB_TRANCA` e do `SQL_DESPUBLICAR` só filtra se estiver
 * escrito, e o canário no fim prova que tirá-lo muda o resultado. As
 * transacções desfazem-se quando o trabalho lança, como no PostgreSQL, e cada
 * escrita fica marcada com a transacção em que entrou.
 *
 * ```text
 * publicado, conteudo exacto, bloqueada       uma violacao, rascunho e product_changed, numa transaccao
 * a repeticao do mesmo screen                 nenhuma segunda violacao
 * a bloqueada que a re-analise ja emitiu      nenhuma violacao, e despublica
 * a re-analise de uma mudanca de politica     emite, e nao despublica (KAM-191, criterio 4)
 * o recurso humano                            a permitida humana deixa republicar
 * uma permitida humana anterior               nenhuma violacao, e fica publicado
 * rascunho, outro nome, outra categoria       nada
 * o mesmo conteudo noutro tenant              so o tenant do ctx, e o outro fica intacto
 * a emissao ou a escrita falha                UPSTREAM_DOWN, e tudo se desfaz
 * a tranca                                    antes de ler as decisoes e de gravar
 * ```
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CatalogoSql,
  conteudoSha256,
  EmissorSql,
  EscritorSql,
  FINALIDADE_DO_CATALOGO,
  politicaCorrente,
  reanalisar,
  sha256EmBase32,
  SQL_DECISOES,
  SQL_POR_REANALISAR,
  TIPO_VIOLACAO,
  type LinhaDeDecisao,
} from "@kamba/core-ts/screening";

import {
  operacaoDePublicar,
  operacaoDeScreen,
  SQL_CATEGORIA_DO_TENANT,
  SQL_DESPUBLICAR,
  SQL_PUBLICADO_SOB_TRANCA,
  SUJEITO_DO_PRODUTO,
} from "../src/screening/index.ts";
import { ok, type ClienteSql, type ComTenant, type Ctx } from "../src/port/index.ts";

const TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const OUTRO = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const SKU = "bebida-01";
const NOME = "Cerveja gelada 33cl";
const VERSAO = politicaCorrente().versao;
const PRODUCT_CHANGED = "catalog.product_changed";
const CONFIRMACAO = { actor: { kind: "dono", id: "msg-1" }, em: "2026-11-23T10:00:00Z" } as const;

type EstadoDaOferta = "rascunho" | "publicado" | "arquivado";

interface Oferta {
  tenantId: string;
  sku: string;
  nome: string;
  estado: EstadoDaOferta;
  apagada?: boolean;
}

interface Evento {
  tipo: string;
  versao: number;
  tenantId: string;
  agregadoTipo: string;
  agregadoId: string;
  payload: Record<string, unknown>;
  transaccao: number;
}

interface Estado {
  ofertas: Oferta[];
  decisoes: (LinhaDeDecisao & { transaccao: number })[];
  eventos: Evento[];
  /** As transacções em que uma oferta mudou de estado. */
  despublicacoes: number[];
}

interface Base {
  readonly comTenant: ComTenant;
  readonly estado: Estado;
  readonly consultas: string[];
  readonly cliente: ClienteSql;
}

/** Os predicados de uma instrução sobre a oferta: cada um só filtra se estiver no texto. */
function casa(sql: string, o: Oferta, tenant: unknown, sku: unknown, tenantDaTransaccao: string | null): boolean {
  return (
    (!sql.includes("tenant_id = $1") || o.tenantId === tenant) &&
    (!sql.includes("sku = $2") || o.sku === sku) &&
    (!sql.includes("estado = 'publicado'") || o.estado === "publicado") &&
    (!sql.includes("deleted_at IS NULL") || !o.apagada) &&
    // A RLS: o duplo só mostra o tenant da transacção.
    o.tenantId === tenantDaTransaccao
  );
}

function base(opcoes: {
  ofertas: Oferta[];
  categorias?: Record<string, string>;
  decisoes?: LinhaDeDecisao[];
  /** O `evt_emitir` deste tipo recusa. */
  falhaAEmitir?: string;
  /** Reescreve a instrução antes de a ler: é o canário. */
  mutar?: (sql: string) => string;
}): Base {
  const categorias = opcoes.categorias ?? {};
  const estado: Estado = {
    ofertas: opcoes.ofertas.map((o) => ({ ...o })),
    decisoes: (opcoes.decisoes ?? []).map((d) => ({ ...d, transaccao: 0 })),
    eventos: [],
    despublicacoes: [],
  };
  const consultas: string[] = [];
  let tenantDaTransaccao: string | null = null;
  let transaccao = 0;
  const cliente: ClienteSql = {
    async query(original, parametros = []) {
      const sql = opcoes.mutar ? opcoes.mutar(original) : original;
      consultas.push(original);
      const [p1, p2] = parametros;
      if (sql.includes("UPDATE platform.offer_terms")) {
        const alvo = estado.ofertas.filter((o) => casa(sql, o, p1, p2, tenantDaTransaccao));
        for (const o of alvo) {
          if (sql.includes("estado = 'rascunho'")) o.estado = "rascunho";
          estado.despublicacoes.push(transaccao);
        }
        return { rows: alvo.map((o) => ({ sku: o.sku })) };
      }
      // A da re-análise também lê a `offer_terms`, e tem o seu ramo abaixo.
      if (sql.includes("FROM platform.offer_terms") && sql !== SQL_POR_REANALISAR) {
        const linhas = estado.ofertas.filter((o) => casa(sql, o, p1, p2, tenantDaTransaccao));
        return { rows: linhas.map((o) => ({ nome: o.nome })) };
      }
      if (sql === SQL_CATEGORIA_DO_TENANT) {
        const categoria = categorias[String(p1)];
        return { rows: categoria === undefined ? [] : [{ sujeito_ref: categoria }] };
      }
      if (sql.includes("INSERT INTO platform.screening_decision")) {
        estado.decisoes.push({
          tenantId: String(parametros[0]),
          onboardingId: null,
          sujeitoTipo: parametros[2] as LinhaDeDecisao["sujeitoTipo"],
          sujeitoRef: String(parametros[3]),
          decisao: parametros[4] as LinhaDeDecisao["decisao"],
          regras: parametros[5] as string[],
          versaoPolitica: String(parametros[6]),
          origem: parametros[7] as LinhaDeDecisao["origem"],
          conteudoSha256: new Uint8Array(parametros[8] as Uint8Array),
          transaccao,
        });
        return { rows: [] };
      }
      if (sql === SQL_DECISOES) {
        const [tenant, tipo, ref, versao, sha] = parametros as [string, string, string, string, Uint8Array];
        const rows = estado.decisoes
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
      if (sql === SQL_POR_REANALISAR) {
        // A re-análise: os publicados sem decisão para a versão e para o conteúdo.
        const versao = String(p1);
        const rows = estado.ofertas
          .filter((o) => o.estado === "publicado" && !o.apagada)
          .map((o) => ({ o, categoria: categorias[o.tenantId] ?? "" }))
          .filter(
            ({ o, categoria }) =>
              !estado.decisoes.some(
                (d) =>
                  d.tenantId === o.tenantId &&
                  d.sujeitoTipo === "produto" &&
                  d.sujeitoRef === o.sku &&
                  d.versaoPolitica === versao &&
                  Buffer.from(d.conteudoSha256).equals(
                    Buffer.from(conteudoSha256({ categoria_declarada: categoria, textos: [o.nome] })),
                  ),
              ),
          )
          .slice(0, Number(p2))
          .map(({ o, categoria }) => ({
            tenant_id: o.tenantId,
            sku: o.sku,
            nome: o.nome,
            categoria_declarada: categoria,
          }));
        return { rows };
      }
      if (sql.includes("platform.evt_emitir(")) {
        const [tipo, versao, tenant, agregadoTipo, agregadoId, payload] = parametros as [
          string,
          number,
          string,
          string,
          string,
          string,
        ];
        if (opcoes.falhaAEmitir === tipo) throw new Error("evt_emitir recusou o payload");
        estado.eventos.push({
          tipo,
          versao,
          tenantId: tenant,
          agregadoTipo,
          agregadoId,
          payload: JSON.parse(payload) as Record<string, unknown>,
          transaccao,
        });
        return { rows: [{ event_id: `evt-${estado.eventos.length}` }] };
      }
      throw new Error(`consulta inesperada: ${sql}`);
    },
  };
  const comTenant: ComTenant = async (tenantId, trabalho) => {
    const antes = {
      ofertas: estado.ofertas.map((o) => ({ ...o })),
      decisoes: [...estado.decisoes],
      eventos: [...estado.eventos],
      despublicacoes: [...estado.despublicacoes],
    };
    tenantDaTransaccao = tenantId;
    transaccao += 1;
    try {
      return await trabalho(cliente);
    } catch (excepcao) {
      estado.ofertas = antes.ofertas;
      estado.decisoes = antes.decisoes;
      estado.eventos = antes.eventos;
      estado.despublicacoes = antes.despublicacoes;
      throw excepcao;
    } finally {
      tenantDaTransaccao = null;
    }
  };
  return { comTenant, estado, consultas, cliente };
}

function ctx(tenantId: string): Ctx {
  return { tenantId, actor: { kind: "agente", id: "grafo-dono" }, traceId: "t-245" };
}

function pedido(textos: readonly string[] = [NOME], categoriaDeclarada: string | null = null) {
  return {
    sujeitoTipo: SUJEITO_DO_PRODUTO,
    sujeitoRef: SKU,
    categoriaDeclarada,
    textos,
    finalidade: FINALIDADE_DO_CATALOGO,
    prazoMs: 10_000,
  } as const;
}

function operar(b: Base) {
  // Sem classificador: a `bloqueada` do álcool é das regras, e é final.
  return operacaoDeScreen({ comTenant: b.comTenant, politica: politicaCorrente(), classificador: null });
}

function publicado(tenantId = TENANT, nome = NOME): Oferta {
  return { tenantId, sku: SKU, nome, estado: "publicado" };
}

/** Uma decisão já gravada do conteúdo publicado, nesta versão. */
function decisao(decisao: LinhaDeDecisao["decisao"], origem: LinhaDeDecisao["origem"]): LinhaDeDecisao {
  return {
    tenantId: TENANT,
    onboardingId: null,
    sujeitoTipo: "produto",
    sujeitoRef: SKU,
    decisao,
    regras: decisao === "bloqueada" ? ["alcool"] : [],
    versaoPolitica: VERSAO,
    origem,
    conteudoSha256: conteudoSha256({ categoria_declarada: "moda", textos: [NOME] }),
  };
}

function tipos(b: Base): string[] {
  return b.estado.eventos.map((e) => e.tipo);
}

test("KAM-245, criterio 1: a bloqueada do conteudo exacto de um publicado emite a violacao uma vez, com o sku e a regra", async () => {
  const b = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" } });
  const r = await operar(b)(ctx(TENANT), pedido());
  assert.equal(r.tipo, "ok");
  assert.equal(r.tipo === "ok" && r.valor.decisao, "bloqueada");
  assert.equal(b.estado.decisoes.length, 1);
  const violacoes = b.estado.eventos.filter((e) => e.tipo === TIPO_VIOLACAO);
  assert.equal(violacoes.length, 1);
  const [evento] = violacoes;
  assert.equal(evento!.versao, 1);
  assert.equal(evento!.tenantId, TENANT);
  assert.equal(evento!.agregadoTipo, "product");
  assert.equal(evento!.agregadoId, SKU);
  assert.equal(evento!.payload["sku"], SKU);
  assert.ok((evento!.payload["regras"] as string[]).includes("alcool"));
  assert.equal(evento!.payload["versao_politica"], VERSAO);
  // O resumo é o do conteúdo publicado: a categoria do tenant e o nome.
  assert.equal(
    evento!.payload["sha256"],
    sha256EmBase32(conteudoSha256({ categoria_declarada: "moda", textos: [NOME] })),
  );
  // E não leva o texto do produto.
  assert.ok(!JSON.stringify(evento!.payload).includes("Cerveja"));
});

test("KAM-245, decisao A: o publicado que o screen bloqueia fica rascunho e sai do indice na mesma transaccao", async () => {
  const b = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" } });
  await operar(b)(ctx(TENANT), pedido());
  assert.equal(b.estado.ofertas[0]!.estado, "rascunho");
  assert.deepEqual(tipos(b), [TIPO_VIOLACAO, PRODUCT_CHANGED]);
  const alterado = b.estado.eventos[1]!;
  // O que o IDX lê para esconder o documento: o sku e o estado, sem texto.
  assert.deepEqual(alterado.payload, { sku: SKU, estado: "rascunho" });
  assert.equal(alterado.tenantId, TENANT);
  assert.equal(alterado.agregadoId, SKU);
  // A decisão, a violação, a saída de publicado e o evento do produto: uma só transacção.
  const transaccoes = new Set([
    ...b.estado.decisoes.map((d) => d.transaccao),
    ...b.estado.eventos.map((e) => e.transaccao),
    ...b.estado.despublicacoes,
  ]);
  assert.equal(transaccoes.size, 1, [...transaccoes].join(","));
});

test("KAM-245, criterio 1: tambem emite e despublica sobre uma permitida anterior do motor", async () => {
  const b = base({
    ofertas: [publicado()],
    categorias: { [TENANT]: "moda" },
    decisoes: [decisao("permitida", "llm")],
  });
  await operar(b)(ctx(TENANT), pedido());
  assert.deepEqual(tipos(b), [TIPO_VIOLACAO, PRODUCT_CHANGED]);
  assert.equal(b.estado.ofertas[0]!.estado, "rascunho");
});

test("KAM-245, criterio 3: a repeticao do mesmo screen nao emite segunda violacao", async () => {
  const b = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" } });
  const op = operar(b);
  await op(ctx(TENANT), pedido());
  const segunda = await op(ctx(TENANT), pedido());
  assert.equal(segunda.tipo === "ok" && segunda.valor.decisao, "bloqueada");
  assert.equal(b.estado.decisoes.length, 2, "a decisao grava-se as duas vezes");
  assert.deepEqual(tipos(b), [TIPO_VIOLACAO, PRODUCT_CHANGED]);
});

test("KAM-245, criterio 3: a bloqueada que a re-analise ja emitiu nao emite outra, e o screen despublica", async () => {
  // O publicado que a re-análise deixou visível (KAM-191, critério 4): o
  // `screen` posterior do mesmo conteúdo tira-o, sem repetir a violação.
  const b = base({
    ofertas: [publicado()],
    categorias: { [TENANT]: "moda" },
    decisoes: [decisao("bloqueada", "regra")],
  });
  await operar(b)(ctx(TENANT), pedido());
  assert.deepEqual(tipos(b), [PRODUCT_CHANGED]);
  assert.equal(b.estado.ofertas[0]!.estado, "rascunho");
});

test("KAM-245, decisao A: a re-analise de uma mudanca de politica continua a emitir sem despublicar", async () => {
  // A mesma base e as mesmas peças de produção do `reanalisar` (o escritor e o
  // emissor sobre o cliente da transacção do produto): a re-análise não toca
  // na oferta, e a assimetria com o `/internal/screen` é a do bloco.
  const b = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" } });
  const resultado = await reanalisar(
    {
      politica: politicaCorrente(),
      classificador: null,
      escritor: new EscritorSql(b.cliente as never),
      emissor: new EmissorSql(b.cliente as never),
      catalogo: new CatalogoSql(b.cliente as never),
      porProduto: (tenantId, trabalho) => b.comTenant(tenantId, () => trabalho()),
    },
    { tamanhoDoLote: 10, maximoPorExecucao: 10 },
  );
  assert.equal(resultado.violacoes, 1);
  assert.deepEqual(tipos(b), [TIPO_VIOLACAO]);
  assert.equal(b.estado.ofertas[0]!.estado, "publicado");
  assert.equal(b.estado.despublicacoes.length, 0);
  assert.ok(!b.consultas.some((c) => c.includes("UPDATE platform.offer_terms")));
});

test("KAM-245, decisao A: o recurso humano deixa o dono republicar o que o screen tirou", async () => {
  const b = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" } });
  await operar(b)(ctx(TENANT), pedido());
  assert.equal(b.estado.ofertas[0]!.estado, "rascunho");
  const publicadas: string[] = [];
  const publicar = operacaoDePublicar({
    comTenant: b.comTenant,
    politica: politicaCorrente(),
    publicar: async (_ctx, ref) => {
      publicadas.push(ref.sku);
      b.estado.ofertas[0]!.estado = "publicado";
      return ok(undefined);
    },
  });
  // Sem recurso, a `bloqueada` recusa a republicação.
  assert.deepEqual(await publicar(ctx(TENANT), { sku: SKU, confirmacao: CONFIRMACAO }), {
    tipo: "erro",
    erro: "VALIDATION_ERROR",
  });
  assert.equal(publicadas.length, 0);
  // A T&S aprova o recurso: uma `permitida` de `humano`, que só o lote grava
  // (revisão `0080`). A última humana decide, e o rascunho volta a publicar.
  b.estado.decisoes.push({ ...decisao("permitida", "humano"), transaccao: 0 });
  assert.deepEqual(await publicar(ctx(TENANT), { sku: SKU, confirmacao: CONFIRMACAO }), ok(undefined));
  assert.deepEqual(publicadas, [SKU]);
  assert.equal(b.estado.ofertas[0]!.estado, "publicado");
});

test("KAM-245: uma permitida humana anterior continua a ganhar, sem violacao e sem despublicar", async () => {
  const b = base({
    ofertas: [publicado()],
    categorias: { [TENANT]: "moda" },
    decisoes: [decisao("permitida", "humano")],
  });
  await operar(b)(ctx(TENANT), pedido());
  assert.deepEqual(tipos(b), []);
  assert.equal(b.estado.ofertas[0]!.estado, "publicado");
});

test("KAM-245, criterio 2: o screen de um rascunho, de um arquivado ou de um apagado nao emite", async () => {
  for (const oferta of [
    { ...publicado(), estado: "rascunho" as const },
    { ...publicado(), estado: "arquivado" as const },
    { ...publicado(), apagada: true },
  ]) {
    const b = base({ ofertas: [oferta], categorias: { [TENANT]: "moda" } });
    const r = await operar(b)(ctx(TENANT), pedido());
    assert.equal(r.tipo === "ok" && r.valor.decisao, "bloqueada");
    assert.equal(b.estado.decisoes.length, 1, "a decisao grava-se na mesma");
    assert.deepEqual(tipos(b), [], JSON.stringify(oferta));
    assert.equal(b.estado.ofertas[0]!.estado, oferta.estado);
  }
});

test("KAM-245, criterio 2: o screen de outro conteudo nao emite — outro nome, ou outra categoria no pedido", async () => {
  const outroNome = base({ ofertas: [publicado(TENANT, "Sumo de laranja")], categorias: { [TENANT]: "moda" } });
  await operar(outroNome)(ctx(TENANT), pedido());
  assert.deepEqual(tipos(outroNome), []);
  assert.equal(outroNome.estado.ofertas[0]!.estado, "publicado");

  // O mesmo nome, mas com uma categoria que não é a do tenant: o resumo é
  // outro, e a decisão não é sobre o que está publicado.
  const outraCategoria = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" } });
  const r = await operar(outraCategoria)(ctx(TENANT), pedido([NOME], "mercearia"));
  assert.equal(r.tipo === "ok" && r.valor.decisao, "bloqueada");
  assert.deepEqual(tipos(outraCategoria), []);
  assert.equal(outraCategoria.estado.ofertas[0]!.estado, "publicado");

  // E uma permitida de um publicado não emite nada.
  const permitida = base({ ofertas: [publicado(TENANT, "Vestido azul")], categorias: { [TENANT]: "moda" } });
  await operacaoDeScreen({
    comTenant: permitida.comTenant,
    politica: politicaCorrente(),
    classificador: {
      classificar: async () => ({ decisao: "permitida", confianca: 0.95 }),
    } as never,
  })(ctx(TENANT), pedido(["Vestido azul"]));
  assert.deepEqual(tipos(permitida), []);
});

test("KAM-245, adversarial: o mesmo conteudo noutro tenant", async () => {
  // O outro tenant tem o mesmo sku publicado com o mesmo nome e a mesma
  // categoria. O `screen` do primeiro, sem oferta dele, não emite nada a
  // ninguém nem tira nada; com oferta dele, só a dele.
  const soNoOutro = base({ ofertas: [publicado(OUTRO)], categorias: { [TENANT]: "moda", [OUTRO]: "moda" } });
  await operar(soNoOutro)(ctx(TENANT), pedido());
  assert.deepEqual(tipos(soNoOutro), []);
  assert.equal(soNoOutro.estado.ofertas[0]!.estado, "publicado");
  assert.ok(soNoOutro.estado.decisoes.every((d) => d.tenantId === TENANT));

  const nosDois = base({
    ofertas: [publicado(OUTRO), publicado(TENANT)],
    categorias: { [TENANT]: "moda", [OUTRO]: "moda" },
  });
  await operar(nosDois)(ctx(TENANT), pedido());
  assert.ok(nosDois.estado.eventos.every((e) => e.tenantId === TENANT));
  assert.deepEqual(
    nosDois.estado.ofertas.map((o) => [o.tenantId, o.estado]),
    [
      [OUTRO, "publicado"],
      [TENANT, "rascunho"],
    ],
  );
  // A bloqueada do primeiro não esconde a do segundo: o outro tenant tem a sua.
  await operar(nosDois)(ctx(OUTRO), pedido());
  assert.deepEqual(
    nosDois.estado.eventos.filter((e) => e.tipo === TIPO_VIOLACAO).map((e) => e.tenantId),
    [TENANT, OUTRO],
  );
  assert.equal(nosDois.estado.ofertas[0]!.estado, "rascunho");
});

test("KAM-245: uma emissao que falha da UPSTREAM_DOWN e desfaz a decisao e a saida de publicado", async () => {
  for (const tipo of [TIPO_VIOLACAO, PRODUCT_CHANGED]) {
    const b = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" }, falhaAEmitir: tipo });
    const r = await operar(b)(ctx(TENANT), pedido());
    assert.deepEqual(r, { tipo: "erro", erro: "UPSTREAM_DOWN" }, tipo);
    assert.equal(b.estado.decisoes.length, 0, `${tipo}: sem a violacao, a decisao nao confirma`);
    assert.deepEqual(tipos(b), [], tipo);
    assert.equal(b.estado.ofertas[0]!.estado, "publicado", tipo);
  }
});

test("KAM-245: a tranca da oferta vem antes de ler as decisoes e de gravar", async () => {
  const b = base({ ofertas: [publicado()], categorias: { [TENANT]: "moda" } });
  await operar(b)(ctx(TENANT), pedido());
  assert.ok(SQL_PUBLICADO_SOB_TRANCA.trimEnd().endsWith("FOR UPDATE"));
  const tranca = b.consultas.indexOf(SQL_PUBLICADO_SOB_TRANCA);
  const leitura = b.consultas.indexOf(SQL_DECISOES);
  const gravacao = b.consultas.findIndex((c) => c.includes("INSERT INTO platform.screening_decision"));
  const saida = b.consultas.indexOf(SQL_DESPUBLICAR);
  assert.ok(
    tranca >= 0 && tranca < leitura && leitura < gravacao && gravacao < saida,
    b.consultas.map((c) => c.trim().slice(0, 30)).join(" | "),
  );
});

test("KAM-245, canario do predicado: sem cada predicado da oferta, a violacao sai onde nao devia", async () => {
  // O duplo lê o texto: tirar o predicado da instrução tem de mudar o que
  // acontece. Se algum destes ficasse igual, os ensaios de cima passavam com a
  // instrução partida.
  const casos: { predicado: string; ofertas: Oferta[] }[] = [
    { predicado: "estado = 'publicado'", ofertas: [{ ...publicado(), estado: "rascunho" }] },
    { predicado: "deleted_at IS NULL", ofertas: [{ ...publicado(), apagada: true }] },
    { predicado: "sku = $2", ofertas: [{ ...publicado(), sku: "outro-sku" }] },
  ];
  for (const caso of casos) {
    const intacta = base({ ofertas: caso.ofertas, categorias: { [TENANT]: "moda" } });
    const certo = await operar(intacta)(ctx(TENANT), pedido());
    assert.equal(certo.tipo, "ok", `intacta: ${caso.predicado}`);
    assert.deepEqual(tipos(intacta), [], `intacta: ${caso.predicado}`);
    // Partida só na tranca: a oferta errada entra, a saída de publicado não a
    // encontra, e a operação recusa em vez de confirmar em silêncio.
    const soATranca = base({
      ofertas: caso.ofertas,
      categorias: { [TENANT]: "moda" },
      mutar: (sql) => (sql === SQL_PUBLICADO_SOB_TRANCA ? sql.replace(caso.predicado, "true") : sql),
    });
    assert.deepEqual(await operar(soATranca)(ctx(TENANT), pedido()), { tipo: "erro", erro: "UPSTREAM_DOWN" }, `so a tranca: ${caso.predicado}`);
    // Partida nas duas: a violação sai sobre a oferta que não devia.
    const asDuas = base({
      ofertas: caso.ofertas,
      categorias: { [TENANT]: "moda" },
      mutar: (sql) =>
        sql === SQL_PUBLICADO_SOB_TRANCA || sql === SQL_DESPUBLICAR ? sql.replace(caso.predicado, "true") : sql,
    });
    await operar(asDuas)(ctx(TENANT), pedido());
    assert.ok(tipos(asDuas).includes(TIPO_VIOLACAO), `as duas: ${caso.predicado}`);
  }
  // O do `SQL_DESPUBLICAR`: sem o `sku`, a saída de publicado levava outra
  // oferta do tenant com ela.
  const vizinha: Oferta = { tenantId: TENANT, sku: "vizinha-02", nome: "Pao", estado: "publicado" };
  const despublicaTudo = base({
    ofertas: [publicado(), vizinha],
    categorias: { [TENANT]: "moda" },
    mutar: (sql) => (sql === SQL_DESPUBLICAR ? sql.replace("sku = $2", "true") : sql),
  });
  const r = await operar(despublicaTudo)(ctx(TENANT), pedido());
  // Duas linhas em vez de uma: a operação recusa e desfaz tudo.
  assert.deepEqual(r, { tipo: "erro", erro: "UPSTREAM_DOWN" });
  assert.equal(despublicaTudo.estado.ofertas[1]!.estado, "publicado");
  const certa = base({ ofertas: [publicado(), vizinha], categorias: { [TENANT]: "moda" } });
  await operar(certa)(ctx(TENANT), pedido());
  assert.deepEqual(
    certa.estado.ofertas.map((o) => o.estado),
    ["rascunho", "publicado"],
  );
  // O `tenant_id = $1` mede-se pelo duplo, que só mostra o tenant da
  // transacção (a RLS): o predicado está escrito nas duas, como em todo o COM.
  assert.ok(SQL_PUBLICADO_SOB_TRANCA.includes("tenant_id = $1"));
  assert.ok(SQL_DESPUBLICAR.includes("tenant_id = $1"));
});
