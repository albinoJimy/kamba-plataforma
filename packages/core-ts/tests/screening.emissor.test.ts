/**
 * O adaptador da porta `EmissorDeViolacoes` ao *outbox* (KAM-191).
 *
 * O que só a base prova — a linha no *outbox* na mesma transacção da decisão, e
 * a decisão desfeita quando a escrita falha — está em
 * `db/tests/test_screening_schema.py` (`TestViolacao`), que corre o
 * `SQL_EMITIR_VIOLACAO` deste módulo tal como está escrito. Aqui prova-se o
 * mapeamento, a validação contra o contrato e a ligação à re-análise: que o
 * emissor e o escritor escrevem pelo **mesmo** cliente, o da transacção do
 * produto.
 */

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, it } from "node:test";

import { CATALOGO } from "@kamba/contracts";

import { validarPayload } from "../src/eventos/contratos.ts";
import {
  AGREGADO_VIOLACAO,
  CLASSE_PII_VIOLACAO,
  dependenciasDaReanalise,
  type ClienteSql,
  conteudoSha256,
  EmissorSql,
  FINALIDADES_VIOLACAO,
  payloadDaViolacao,
  politicaCorrente,
  sha256EmBase32,
  reanalisar,
  SQL_EMITIR_VIOLACAO,
  SQL_GRAVAR,
  TIPO_VIOLACAO,
  VERSAO_VIOLACAO,
  type Violacao,
} from "../src/screening/index.ts";

const TENANT = "00000000-0000-0000-0000-0000000000aa";
const ENTRADA = { categoria_declarada: "moda", textos: ["vinho tinto"] };

function violacao(): Violacao {
  return {
    tenantId: TENANT,
    sku: "SKU-1",
    regras: ["alcool"],
    versaoPolitica: "1.0.0+m.2",
    conteudoSha256: conteudoSha256(ENTRADA),
  };
}

interface Consulta {
  readonly sql: string;
  readonly valores: readonly unknown[];
}

/** Um cliente que guarda as consultas e responde ao `evt_emitir`. */
function cliente(resposta: () => unknown = () => ({ event_id: "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44" })) {
  const consultas: Consulta[] = [];
  const c: ClienteSql = {
    query: async <T,>(sql: string, valores: readonly unknown[] = []) => {
      consultas.push({ sql, valores });
      const linha = sql === SQL_EMITIR_VIOLACAO ? resposta() : undefined;
      return { rows: (linha === undefined ? [] : [linha]) as T[] };
    },
  };
  return { c, consultas };
}

describe("o payload de screening.violation_detected", () => {
  it("leva sku, regras, versao_politica e o sha256 em base32, e nada mais", () => {
    const p = payloadDaViolacao(violacao());
    assert.deepEqual(Object.keys(p).sort(), ["regras", "sha256", "sku", "versao_politica"]);
    assert.equal(p.sku, "SKU-1");
    assert.deepEqual(p.regras, ["alcool"]);
    assert.equal(p.versao_politica, "1.0.0+m.2");
    // O oraculo e o sha256 do JSON canonico, calculado aqui e nao importado:
    // trocar o `conteudoSha256` do modulo por outro resumo poe isto vermelho.
    // A codificacao e verificada a parte, contra os vectores do RFC 4648.
    const esperado = createHash("sha256")
      .update(JSON.stringify([ENTRADA.categoria_declarada, ENTRADA.textos]), "utf8")
      .digest();
    assert.equal(p.sha256, sha256EmBase32(esperado));
    assert.match(p.sha256, /^[a-z2-7]{52}$/);
  });

  it("o base32 e o do RFC 4648 (seccao 10), em minusculas e sem `=`", () => {
    const vectores: [string, string][] = [
      ["", ""],
      ["f", "my"],
      ["fo", "mzxq"],
      ["foo", "mzxw6"],
      ["foob", "mzxw6yq"],
      ["fooba", "mzxw6ytb"],
      ["foobar", "mzxw6ytboi"],
    ];
    for (const [entrada, saida] of vectores) {
      assert.equal(sha256EmBase32(Buffer.from(entrada, "utf8")), saida, entrada);
    }
  });

  it("(F1) um resumo nunca casa a guarda de telefone do evt_emitir, e o hexadecimal casava", () => {
    // As duas expressoes da revisao 0004, copiadas do SQL e nao importadas.
    const guarda = [/\+?244 ?9[0-9]{8}/, /"\+[0-9]{9,15}"/];
    // O conteudo que a revisao adversarial encontrou: o hexadecimal do resumo
    // dele tem `244` seguido de `9` e de oito algarismos. Com hexadecimal, o
    // evt_emitir recusava o evento, a decisao desfazia-se, e a re-analise
    // voltava a parar no mesmo produto em todas as execucoes.
    const entrada = { categoria_declarada: "moda", textos: ["vinho tinto 65521"] };
    const octetos = conteudoSha256(entrada);
    const hex = Buffer.from(octetos).toString("hex");
    assert.ok(guarda[0]!.test(hex), "o caso deixou de reproduzir o defeito do hexadecimal");
    const payload = JSON.stringify(payloadDaViolacao({ ...violacao(), conteudoSha256: octetos }));
    for (const expressao of guarda) assert.ok(!expressao.test(payload), payload);
    // Por construcao, e nao so neste caso: o alfabeto nao tem `9` nem `+`.
    assert.ok(!/[0189+]/.test(sha256EmBase32(octetos)));
  });

  it("nao leva o texto do produto em campo nenhum", () => {
    const serializado = JSON.stringify(payloadDaViolacao(violacao()));
    assert.ok(!serializado.includes("vinho"), serializado);
    assert.ok(!serializado.includes(TENANT), "o tenant vai no envelope, nao no payload");
  });

  it("passa no validador do contrato, nas duas versoes publicadas", () => {
    assert.deepEqual(CATALOGO[TIPO_VIOLACAO].versoes, [1, 2]);
    for (const versao of CATALOGO[TIPO_VIOLACAO].versoes) {
      assert.doesNotThrow(() => validarPayload(TIPO_VIOLACAO, versao, payloadDaViolacao(violacao())));
    }
  });
});

describe("EmissorSql", () => {
  it("chama o evt_emitir com o tipo, a versao, o tenant, o produto e o payload", async () => {
    const { c, consultas } = cliente();
    await new EmissorSql(c).emitir(violacao());
    assert.equal(consultas.length, 1);
    const [tipo, versao, tenant, agregadoTipo, agregadoId, payload, classe, finalidades] =
      consultas[0]!.valores;
    assert.equal(consultas[0]!.sql, SQL_EMITIR_VIOLACAO);
    assert.equal(tipo, "screening.violation_detected");
    assert.equal(versao, VERSAO_VIOLACAO);
    assert.equal(tenant, TENANT);
    assert.equal(agregadoTipo, AGREGADO_VIOLACAO);
    assert.equal(agregadoId, "SKU-1");
    assert.deepEqual(JSON.parse(payload as string), payloadDaViolacao(violacao()));
    assert.equal(classe, CLASSE_PII_VIOLACAO);
    assert.deepEqual(finalidades, [...FINALIDADES_VIOLACAO]);
  });

  it("os valores fixos sao os que os contratos declaram", () => {
    // `agregado.tipo` e `classe_pii` sao `const`/`enum` nos dois contratos; um
    // valor diferente aqui era um evento que o contrato recusa.
    assert.equal(AGREGADO_VIOLACAO, "product");
    assert.equal(CLASSE_PII_VIOLACAO, "P0");
    assert.deepEqual([...FINALIDADES_VIOLACAO], ["transacao"]);
    assert.equal(VERSAO_VIOLACAO, 1);
  });

  it("falha alto se o evt_emitir nao devolver um event_id", async () => {
    const { c } = cliente(() => ({ event_id: null }));
    await assert.rejects(new EmissorSql(c).emitir(violacao()), /event_id/);
  });

  it("uma falha da base sobe", async () => {
    const c: ClienteSql = { query: async () => Promise.reject(new Error("outbox em baixo")) };
    await assert.rejects(new EmissorSql(c).emitir(violacao()), /outbox em baixo/);
  });
});

describe("a re-analise montada pela dependenciasDaReanalise", () => {
  /**
   * Um cliente que regista o que lhe chega e falha o `evt_emitir` quando se
   * lhe pede. A transaccao **nao** e simulada: e o `comTenant` real, por
   * dentro do `porProdutoSql`, que escreve o `BEGIN`, o contexto, e o `COMMIT`
   * ou o `ROLLBACK`. O que so a base prova — que o `ROLLBACK` leva a decisao —
   * esta no `TestViolacao` da suite de base de dados.
   */
  function montar(falharEmissao: boolean) {
    const consultas: Consulta[] = [];
    const c: ClienteSql = {
      query: async <T,>(sql: string, valores: readonly unknown[] = []) => {
        consultas.push({ sql, valores });
        if (sql === SQL_EMITIR_VIOLACAO && falharEmissao) throw new Error("evt_emitir recusou");
        const linhas = sql === SQL_EMITIR_VIOLACAO ? [{ event_id: "e1" }] : [];
        return { rows: linhas as T[] };
      },
    };
    const produtos = [
      { tenantId: TENANT, sku: "SKU-1", categoriaDeclarada: "moda", textos: ["vinho tinto"] },
      { tenantId: TENANT, sku: "SKU-2", categoriaDeclarada: "moda", textos: ["camisola de la"] },
    ];
    // O catalogo vem de **outra** ligacao, a do `kamba_batch`, e devolve as
    // linhas na forma do `SQL_POR_REANALISAR`.
    let lido = false;
    const batch: ClienteSql = {
      query: async <T,>() => {
        const linhas = lido
          ? []
          : produtos.map((p) => ({
              tenant_id: p.tenantId,
              sku: p.sku,
              nome: p.textos[0],
              categoria_declarada: p.categoriaDeclarada,
            }));
        lido = true;
        return { rows: linhas as T[] };
      },
    };
    const deps = dependenciasDaReanalise({
      app: c,
      batch,
      politica: politicaCorrente(),
      classificador: null,
    });
    /** A sequencia, com o SQL de cada passo trocado por um nome legivel. */
    const passos = () =>
      consultas.map((q) =>
        q.sql === SQL_GRAVAR
          ? `gravar ${String(q.valores[3])} ${String(q.valores[4])}`
          : q.sql === SQL_EMITIR_VIOLACAO
            ? `emitir ${String(q.valores[4])}`
            : q.sql.includes("set_config")
              ? `contexto ${String(q.valores[0])}`
              : q.sql,
      );
    return { deps, consultas, passos };
  }

  it("uma bloqueada grava e emite dentro da mesma transaccao do produto, e confirma", async () => {
    const { deps, consultas, passos } = montar(false);
    const r = await reanalisar(deps, { tamanhoDoLote: 5, maximoPorExecucao: 5 });
    assert.equal(r.violacoes, 1);
    assert.deepEqual(passos(), [
      "BEGIN",
      `contexto ${TENANT}`,
      "gravar SKU-1 bloqueada",
      "emitir SKU-1",
      "COMMIT",
      // A camisola nao e bloqueada: grava e nao chega ao evt_emitir.
      "BEGIN",
      `contexto ${TENANT}`,
      "gravar SKU-2 condicional",
      "COMMIT",
    ]);
    const gravar = consultas.find((q) => q.sql === SQL_GRAVAR)!;
    const emitir = consultas.find((q) => q.sql === SQL_EMITIR_VIOLACAO)!;
    // O sha256 do evento e o da decisao gravada: o mesmo conteudo, a mesma prova
    // (a codificacao, verificada contra o RFC 4648 no seu proprio ensaio).
    const payload = JSON.parse(emitir.valores[5] as string) as Record<string, unknown>;
    assert.equal(payload["sha256"], sha256EmBase32(new Uint8Array(gravar.valores[8] as Buffer)));
  });

  it("uma falha da escrita no outbox desfaz a transaccao com a decisao, e para a execucao", async () => {
    const { deps, passos } = montar(true);
    await assert.rejects(reanalisar(deps, { tamanhoDoLote: 5, maximoPorExecucao: 5 }), /evt_emitir recusou/);
    assert.deepEqual(passos(), [
      "BEGIN",
      `contexto ${TENANT}`,
      "gravar SKU-1 bloqueada",
      "emitir SKU-1",
      "ROLLBACK",
    ]);
  });
});
