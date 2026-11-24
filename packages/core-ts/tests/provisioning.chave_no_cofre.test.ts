/**
 * O passo `chave_llm` da saga do KAM-091 grava o valor no cofre (KAM-250).
 *
 * **Canário:** «a segunda passagem nao reemite e o valor do cofre continua a
 * autenticar». Um passo que gerasse valor novo a cada passagem passava os outros
 * ensaios de «grava no cofre» e partia o critério 3: a chave anterior deixava de
 * valer a cada repetição da saga.
 *
 * O que **não** se prova aqui: o LiteLLM. O `id` do duplo é o SHA-256 do valor,
 * como a imagem fixada o devolve (medido, `docs/evidencia/KAM-250.md`).
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import {
  Saga,
  montarPassos,
  refDaChaveDoTenant,
  resumoDaChave,
} from "../src/provisioning/index.ts";
import { CASO, TENANT, montar } from "./apoio/provisioning-falsos.ts";

type Montagem = ReturnType<typeof montar>;

const REF = `litellm_virtual_key/${TENANT}`;
const ALIAS = `tenant-${TENANT}`;

function passoDaChave(m: Montagem) {
  const passo = montarPassos(m.dependencias as never).get("chave_llm");
  assert.ok(passo !== undefined);
  return passo;
}

describe("KAM-250 — o passo `chave_llm` grava o valor no cofre", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  it("a referencia e a do inventario", () => {
    assert.equal(refDaChaveDoTenant(TENANT), REF);
  });

  it("o valor que o proxy recebe e o que ficou no cofre, e o id e o resumo dele", async () => {
    const id = await passoDaChave(m).ensure(CASO);
    const valor = m.cofreDeChaves.segredos.get(REF);
    assert.ok(valor !== undefined && valor.startsWith("sk-"));
    assert.deepEqual(m.chaveDeLlm.valores, [valor]);
    assert.equal(id, resumoDaChave(valor));
  });

  it("o cofre e escrito antes do proxy: sem cofre nao se cria chave nenhuma", async () => {
    m.cofreDeChaves.falharEscrita = true;
    await assert.rejects(passoDaChave(m).ensure(CASO), /cofre_indisponivel/);
    assert.equal(m.chaveDeLlm.criadas, 0);
  });

  it("a segunda passagem nao reemite e o valor do cofre continua a autenticar", async () => {
    const primeiro = await passoDaChave(m).ensure(CASO);
    const valor = m.cofreDeChaves.segredos.get(REF);
    const segundo = await passoDaChave(m).ensure(CASO);
    assert.equal(segundo, primeiro);
    assert.equal(m.chaveDeLlm.criadas, 1);
    assert.equal(m.cofreDeChaves.escritas, 1);
    assert.deepEqual(m.chaveDeLlm.revogadas, []);
    assert.equal(m.cofreDeChaves.segredos.get(REF), valor);
  });

  it("uma queda depois do cofre retoma com o valor que la esta, sem gravar outro", async () => {
    m.cofreDeChaves.segredos.set(REF, "sk-caiu-antes");
    const id = await passoDaChave(m).ensure(CASO);
    assert.equal(m.cofreDeChaves.escritas, 0);
    assert.deepEqual(m.chaveDeLlm.valores, ["sk-caiu-antes"]);
    assert.equal(id, resumoDaChave("sk-caiu-antes"));
  });

  it("uma chave que o cofre nao autentica e revogada e reemitida", async () => {
    m.chaveDeLlm.semear(ALIAS, "sk-valor-perdido");
    const id = await passoDaChave(m).ensure(CASO);
    assert.deepEqual(m.chaveDeLlm.revogadas, [resumoDaChave("sk-valor-perdido")]);
    const valor = m.cofreDeChaves.segredos.get(REF);
    assert.ok(valor !== undefined);
    assert.equal(id, resumoDaChave(valor));
    assert.equal(m.chaveDeLlm.quantos, 1);
  });

  it("um valor no cofre que nao bate reemite com esse valor", async () => {
    m.chaveDeLlm.semear(ALIAS, "sk-outro");
    m.cofreDeChaves.segredos.set(REF, "sk-o-do-cofre");
    const id = await passoDaChave(m).ensure(CASO);
    assert.equal(m.cofreDeChaves.escritas, 0);
    assert.equal(id, resumoDaChave("sk-o-do-cofre"));
  });

  it("nenhum valor de chave no log nem na base", async () => {
    await new Saga(m.dependencias as never).correr(CASO);
    await new Saga(m.dependencias as never).correr(CASO);
    const valor = m.cofreDeChaves.segredos.get(REF);
    assert.ok(valor !== undefined);
    const naBase = JSON.stringify(m.sql.consultas);
    const noLog = JSON.stringify(m.linhasDeLog);
    assert.ok(!naBase.includes(valor), "o valor foi para a base");
    assert.ok(!noLog.includes(valor), "o valor foi para o log");
    // O que vai para a base e o resumo — o `litellm_key_id` —, e nunca o valor.
    assert.ok(naBase.includes(resumoDaChave(valor)));
  });
});
