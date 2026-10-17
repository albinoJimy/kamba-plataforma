/**
 * O catálogo de eventos gerado, contra os contratos que o geraram (KAM-007).
 *
 * O `eventos.gerado.ts` sai de `python -m contract_diff gerar` e o gate 7
 * falha se estiver desactualizado — mas o gate corre em Python, e quem
 * **usa** o catálogo é TypeScript. Esta bateria é o lado de cá: carrega o
 * ficheiro gerado e confronta-o com os `v1.schema.json` no disco.
 *
 * Carregá-lo tem um segundo efeito, e vale dizê-lo porque não é acidente: um
 * ficheiro em `packages/*‍/src/**` que nenhum teste carrega entra na medição
 * de cobertura a **0%** das suas linhas (`ci/thresholds.yaml`, desde o
 * KAM-132). Quatrocentas linhas geradas e nunca lidas baixavam o estrato sem
 * nada estar errado. Aqui são lidas, e são lidas a verificar alguma coisa.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { CATALOGO, type TipoDeEvento } from "../src/eventos.gerado.ts";

/** A pasta dos contratos, a partir deste ficheiro. */
const CONTRATOS = new URL("../../../contratos/eventos/", import.meta.url);

/** Os trinta e oito do dicionário §3.5, emenda 1.11. */
const ESPERADOS = 38;

function schemaDe(tipo: string): Record<string, unknown> {
  const caminho = new URL(`${tipo}/v1.schema.json`, CONTRATOS);
  return JSON.parse(readFileSync(caminho, "utf8")) as Record<string, unknown>;
}

function payloadDe(tipo: string): Record<string, unknown> {
  const schema = schemaDe(tipo);
  const propriedades = schema.properties as Record<string, Record<string, unknown>>;
  return propriedades.payload as Record<string, unknown>;
}

describe("o catálogo gerado", () => {
  it("tem um tipo por contrato, e nem um a mais", () => {
    const naPasta = readdirSync(CONTRATOS).sort();
    assert.equal(naPasta.length, ESPERADOS);
    assert.deepEqual(Object.keys(CATALOGO).sort(), naPasta);
  });

  it("cada entrada diz a versão que o nome do ficheiro diz", () => {
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      assert.equal(CATALOGO[tipo].versao, 1, tipo);
    }
  });

  it("os obrigatórios e os permitidos são os do schema", () => {
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      const payload = payloadDe(tipo);
      const obrigatorios = [...((payload.required as string[]) ?? [])].sort();
      const permitidos = Object.keys(
        (payload.properties as Record<string, unknown>) ?? {},
      ).sort();
      assert.deepEqual([...CATALOGO[tipo].obrigatorios].sort(), obrigatorios, tipo);
      assert.deepEqual([...CATALOGO[tipo].permitidos].sort(), permitidos, tipo);
    }
  });

  it("todo o obrigatório é permitido", () => {
    // Um `required` que nomeie um campo que `properties` não declara é um
    // schema impossível de satisfazer, e o catálogo herdava-o em silêncio.
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      for (const campo of CATALOGO[tipo].obrigatorios) {
        assert.ok(
          (CATALOGO[tipo].permitidos as readonly string[]).includes(campo),
          `${tipo}: «${campo}» é obrigatório e não está declarado`,
        );
      }
    }
  });

  it("nenhum campo tem nome de dado pessoal", () => {
    // A mesma lista do §7.3 que o `tools/contract_diff/pii.py` usa. Está aqui
    // outra vez de propósito: são dois caminhos independentes até à mesma
    // regra, e o dia em que um deles se desligar o outro continua a gritar.
    const proibidos = ["telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email"];
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      for (const campo of CATALOGO[tipo].permitidos) {
        const segmentos = campo.toLowerCase().split(/[^a-z0-9]+/);
        for (const mau of proibidos) {
          assert.ok(!segmentos.includes(mau), `${tipo}.${campo} contém «${mau}»`);
        }
      }
    }
  });

  it("o exemplo de cada contrato só usa campos permitidos", () => {
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      const caminho = new URL(`${tipo}/exemplo.json`, CONTRATOS);
      const exemplo = JSON.parse(readFileSync(caminho, "utf8")) as Record<string, unknown>;
      const payload = (exemplo.payload ?? {}) as Record<string, unknown>;
      for (const campo of Object.keys(payload)) {
        assert.ok(
          (CATALOGO[tipo].permitidos as readonly string[]).includes(campo),
          `${tipo}: o exemplo tem «${campo}», que o contrato não permite`,
        );
      }
      for (const campo of CATALOGO[tipo].obrigatorios) {
        assert.ok(campo in payload, `${tipo}: o exemplo não tem «${campo}»`);
      }
    }
  });
});
