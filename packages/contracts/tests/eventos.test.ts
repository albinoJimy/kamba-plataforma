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

/**
 * As versões de um tipo, lidas da pasta.
 *
 * Desde o KAM-159 há mais do que uma, e **tudo o que este ficheiro verifica
 * tem de valer para todas**: um contrato novo que entrasse como `v2` sem
 * passar por aqui herdava verde de uma `v1` que ninguém mais escreve.
 */
function versoesDe(tipo: string): number[] {
  const versoes = readdirSync(new URL(`${tipo}/`, CONTRATOS))
    .map((nome) => /^v([1-9][0-9]*)\.schema\.json$/.exec(nome)?.[1])
    .filter((n): n is string => n !== undefined)
    .map(Number)
    .sort((a, b) => a - b);
  assert.ok(versoes.length > 0, `${tipo}: pasta sem nenhum v<N>.schema.json`);
  return versoes;
}

function schemaDe(tipo: string, versao = 1): Record<string, unknown> {
  const caminho = new URL(`${tipo}/v${versao}.schema.json`, CONTRATOS);
  return JSON.parse(readFileSync(caminho, "utf8")) as Record<string, unknown>;
}

function payloadDe(tipo: string, versao = 1): Record<string, unknown> {
  const schema = schemaDe(tipo, versao);
  const propriedades = schema.properties as Record<string, Record<string, unknown>>;
  return propriedades.payload as Record<string, unknown>;
}

/** O nome do exemplo de uma versão. A `v1` mantém o nome histórico. */
function nomeDoExemplo(versao: number): string {
  return versao === 1 ? "exemplo.json" : `exemplo.v${versao}.json`;
}

describe("o catálogo gerado", () => {
  it("tem um tipo por contrato, e nem um a mais", () => {
    const naPasta = readdirSync(CONTRATOS).sort();
    assert.equal(naPasta.length, ESPERADOS);
    assert.deepEqual(Object.keys(CATALOGO).sort(), naPasta);
  });

  it("cada entrada diz as versões que os nomes dos ficheiros dizem", () => {
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      assert.deepEqual([...CATALOGO[tipo].versoes], versoesDe(tipo), tipo);
    }
  });

  it("os obrigatórios e os permitidos são os do schema, em todas as versões", () => {
    // Uma entrada só do catálogo para várias versões **é uma afirmação**: a
    // de que o payload tem os mesmos campos em todas. O gerador recusa gerar
    // quando não tem (`NaoSeiTraduzirError`); aqui verifica-se o resultado,
    // que é onde a afirmação se pagaria se fosse falsa.
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      for (const versao of versoesDe(tipo)) {
        const payload = payloadDe(tipo, versao);
        const obrigatorios = [...((payload.required as string[]) ?? [])].sort();
        const permitidos = Object.keys(
          (payload.properties as Record<string, unknown>) ?? {},
        ).sort();
        const onde = `${tipo} v${versao}`;
        assert.deepEqual([...CATALOGO[tipo].obrigatorios].sort(), obrigatorios, onde);
        assert.deepEqual([...CATALOGO[tipo].permitidos].sort(), permitidos, onde);
      }
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
    // A mesma regra do `tools/contract_diff/pii.py`, escrita outra vez: são
    // dois caminhos até à mesma regra do §7.1, e o dia em que um se desligar
    // o outro continua a gritar.
    //
    // **E é a regra, não a lista de sete.** A primeira versão dos dois
    // comparava os sete nomes do §7.3 por segmento exacto, e deixava passar
    // o plural de cada um (`nomes`, `emails`) e o inglês todo (`phone`,
    // `mail`, `full_name`). Isso não é duas barreiras: são duas cópias do
    // mesmo buraco, e foi a revisão adversarial que o demonstrou (achado C1).
    const raizes = [
      "telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email",
      "phone", "telephone", "mobile", "mail", "address", "name", "firstname",
      "lastname", "fullname", "surname", "username", "birthdate", "dob",
      "endereco", "telemovel", "contacto", "mensagem", "conteudo", "observacao",
      "observacoes", "descricao", "descricoes", "destinatario", "remetente",
      "titular", "apelido", "nascimento", "bilhete", "msg", "waid",
    ];
    // Os nomes de campo com excepção declarada em `ci/contratos-allow.yaml`,
    // sem o prefixo `payload.`. Lê-se a lista aqui à mão porque este pacote
    // não tem leitor de YAML — e uma lista de uma entrada que diverge é mais
    // visível do que uma dependência nova.
    const aprovados = new Set(["phone_number_id"]);
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      for (const campo of CATALOGO[tipo].permitidos) {
        if (aprovados.has(campo)) continue;
        const segmentos = campo.toLowerCase().split(/[^a-z0-9]+/);
        segmentos.push(segmentos.join(""));
        for (const raiz of raizes) {
          assert.ok(
            !segmentos.includes(raiz) && !segmentos.includes(`${raiz}s`),
            `${tipo}.${campo} contém «${raiz}»`,
          );
        }
      }
    }
  });

  it("nenhum contrato admite classe_pii P2", () => {
    // §7.1: «sem PII crua em eventos (P2 proibida)». Os trinta e oito
    // admitiam-na — o `enum` do envelope era `P0|P1|P2` em todos, e a única
    // verificação incidia sobre o exemplo (achado M1).
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      for (const versao of versoesDe(tipo)) {
        const schema = schemaDe(tipo, versao) as unknown as {
          properties: { classe_pii: { enum: string[] }; agregado: { properties: { tipo: { const?: string } } } };
        };
        const onde = `${tipo} v${versao}`;
        assert.ok(!schema.properties.classe_pii.enum.includes("P2"), `${onde} admite P2`);
        assert.ok(
          typeof schema.properties.agregado.properties.tipo.const === "string",
          `${onde}: o agregado ficou livre`,
        );
      }
    }
  });

  it("o exemplo de cada versão só usa campos permitidos", () => {
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      for (const versao of versoesDe(tipo)) {
        const caminho = new URL(`${tipo}/${nomeDoExemplo(versao)}`, CONTRATOS);
        const exemplo = JSON.parse(readFileSync(caminho, "utf8")) as Record<string, unknown>;
        const onde = `${tipo} v${versao}`;
        assert.equal(exemplo.versao, versao, `${onde}: o exemplo diz outra versão`);
        const payload = (exemplo.payload ?? {}) as Record<string, unknown>;
        for (const campo of Object.keys(payload)) {
          assert.ok(
            (CATALOGO[tipo].permitidos as readonly string[]).includes(campo),
            `${onde}: o exemplo tem «${campo}», que o contrato não permite`,
          );
        }
        for (const campo of CATALOGO[tipo].obrigatorios) {
          assert.ok(campo in payload, `${onde}: o exemplo não tem «${campo}»`);
        }
      }
    }
  });

  it("não sobra nenhum exemplo sem versão, nem falta nenhum", () => {
    // Um `exemplo.v3.json` numa pasta sem `v3.schema.json` passaria
    // despercebido para sempre: nada o lê. E um `v3.schema.json` sem exemplo
    // tirava a versão nova de todas as verificações acima sem falhar nenhuma.
    for (const tipo of Object.keys(CATALOGO) as TipoDeEvento[]) {
      const naPasta = readdirSync(new URL(`${tipo}/`, CONTRATOS))
        .filter((nome) => nome.startsWith("exemplo"))
        .sort();
      assert.deepEqual(naPasta, versoesDe(tipo).map(nomeDoExemplo).sort(), tipo);
    }
  });
});
