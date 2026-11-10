/**
 * Os casos *allow/deny* da política (KAM-088, critério 6 e Testes Requeridos
 * «golden/política»), sobre `policy/categorias/casos/*.jsonl`.
 *
 * **Os casos foram escritos por um agente que não leu o motor** (ver o
 * `LEIA-ME.md` da pasta): se fossem derivados do código, mediam o código.
 *
 * **Medem as regras sozinhas.** O classificador destes ensaios responde sempre
 * `permitida` com confiança 1 — o pior modelo possível, ou um modelo
 * convencido por uma injecção. Como o classificador só sobe a restrição, o que
 * passa aqui passa com qualquer modelo; e o que só o modelo apanharia não
 * conta a favor.
 *
 * Os limiares são os do critério 6: **0** `permitida` no conjunto canónico,
 * **≥ 95%** `condicional` ou `bloqueada` no disfarçado (*proposta* de
 * arranque) e **0** `permitida` nos 20 casos de severidade alta. Os falsos
 * `bloqueada` nos permitidos **medem-se e não bloqueiam**, como os Testes
 * Requeridos pedem — mas têm um tecto, para que uma política que bloqueasse
 * tudo não passasse este ficheiro a verde.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  type ClassificadorDeCategorias,
  type Decisao,
  type EscritorDeDecisoes,
  politicaCorrente,
  screen,
} from "../src/screening/index.ts";

interface Caso {
  readonly id: string;
  readonly conjunto: "canonico" | "disfarcado" | "permitido";
  readonly categoria_declarada: string;
  readonly textos: readonly string[];
  readonly esperado: readonly Decisao[];
  readonly alvo: string;
  readonly severidade: "alta" | "normal";
}

const PASTA = new URL("../../../policy/categorias/casos/", import.meta.url);

function ler(nome: string): Caso[] {
  return readFileSync(new URL(nome, PASTA), "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Caso);
}

const SEMPRE_PERMITIDA: ClassificadorDeCategorias = {
  classificar: async () => ({ decisao: "permitida", confianca: 1 }),
};
const SEM_ESCRITA: EscritorDeDecisoes = { gravar: async () => {} };

async function decidir(caso: Caso): Promise<Decisao> {
  const r = await screen(
    { tenantId: "00000000-0000-0000-0000-000000000001", sujeitoTipo: "produto", sujeitoRef: caso.id },
    { categoria_declarada: caso.categoria_declarada, textos: caso.textos },
    { politica: politicaCorrente(), classificador: SEMPRE_PERMITIDA, escritor: SEM_ESCRITA },
  );
  return r.decisao;
}

async function medir(casos: readonly Caso[]) {
  const falhas: string[] = [];
  for (const caso of casos) {
    const decisao = await decidir(caso);
    if (!caso.esperado.includes(decisao)) falhas.push(`${caso.id} → ${decisao}: ${caso.textos.join(" | ")}`);
  }
  return falhas;
}

const CANONICO = ler("canonico.jsonl");
const DISFARCADO = ler("disfarcado.jsonl");
const PERMITIDO = ler("permitido.jsonl");

describe("golden: os casos allow/deny da politica", () => {
  it("tem os tamanhos que o criterio 6 e os Testes Requeridos pedem", () => {
    assert.ok(CANONICO.length >= 100, `canonico: ${CANONICO.length}`);
    assert.ok(DISFARCADO.length >= 100, `disfarcado: ${DISFARCADO.length}`);
    assert.ok(CANONICO.length + DISFARCADO.length + PERMITIDO.length >= 200);
    assert.equal(DISFARCADO.filter((c) => c.severidade === "alta").length, 20);
    const ids = [...CANONICO, ...DISFARCADO, ...PERMITIDO].map((c) => c.id);
    assert.equal(new Set(ids).size, ids.length, "ids repetidos");
  });

  it("canonico: zero permitida, e cada caso bloqueado", async () => {
    const permitidas = [];
    for (const caso of CANONICO) if ((await decidir(caso)) === "permitida") permitidas.push(caso.id);
    assert.deepEqual(permitidas, []);
    assert.deepEqual(await medir(CANONICO), []);
  });

  it("disfarcado: >= 95% condicional ou bloqueada, e zero permitida nos 20 de severidade alta", async (t) => {
    const falhas = await medir(DISFARCADO);
    const taxa = 1 - falhas.length / DISFARCADO.length;
    t.diagnostic(`disfarcado apanhado: ${DISFARCADO.length - falhas.length}/${DISFARCADO.length}`);
    for (const f of falhas) t.diagnostic(f);
    assert.ok(taxa >= 0.95, `taxa ${(taxa * 100).toFixed(1)}%; falharam:\n${falhas.join("\n")}`);
    const graves = DISFARCADO.filter((c) => c.severidade === "alta");
    const gravesPermitidas = [];
    for (const caso of graves) if ((await decidir(caso)) === "permitida") gravesPermitidas.push(caso.id);
    assert.deepEqual(gravesPermitidas, []);
  });

  it("controlo: o conjunto do revisor adversarial, que o autor nao viu ao escrever as regras", async (t) => {
    // Escrito pela revisao adversarial depois de a politica estar afinada: e a
    // medida de generalizacao. **Mede-se e reporta-se**, e so os dezasseis
    // truques de escrita (homoglifos, enchimentos, letras partidas) sao
    // exigidos — sao o trabalho do normalizador, e foram corrigidos a partir
    // deste conjunto, pelo que deixaram de ser cegos. O resto sao marcas e
    // eufemismos que nenhuma lista de termos generaliza: e o trabalho do
    // classificador, que nao esta ligado (credor KAM-040).
    const controlo = ler("controlo.jsonl") as (Caso & { grupo: string; truque_de_escrita: boolean })[];
    const contagem: Record<string, Record<Decisao, number>> = {};
    const truquesFalhados: string[] = [];
    let gravesPermitidas = 0;
    for (const caso of controlo) {
      const decisao = await decidir(caso);
      (contagem[caso.grupo] ??= { permitida: 0, condicional: 0, bloqueada: 0 })[decisao] += 1;
      if (caso.truque_de_escrita && decisao === "permitida") truquesFalhados.push(caso.id);
      if (caso.grupo === "evasao" && decisao === "permitida" && ["armas", "medicamentos_saude"].includes(caso.alvo)) {
        gravesPermitidas += 1;
      }
    }
    t.diagnostic(`controlo por grupo: ${JSON.stringify(contagem)}`);
    t.diagnostic(`armas e medicamentos disfarcados que ficaram permitida: ${gravesPermitidas}`);
    assert.equal(controlo.filter((c) => c.truque_de_escrita).length, 16);
    assert.deepEqual(truquesFalhados, []);
  });

  it("permitido: falsos bloqueios medidos, com tecto de 15%", async (t) => {
    const falhas = await medir(PERMITIDO);
    const bloqueadas = falhas.filter((f) => f.includes("→ bloqueada"));
    t.diagnostic(`falsos nao-permitida: ${falhas.length}/${PERMITIDO.length}`);
    for (const f of falhas) t.diagnostic(f);
    assert.ok(falhas.length / PERMITIDO.length <= 0.15, `${falhas.length} de ${PERMITIDO.length}:\n${falhas.join("\n")}`);
    assert.ok(bloqueadas.length <= falhas.length);
  });
});
