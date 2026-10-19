/**
 * A assinatura dos webhooks da Meta (KAM-013, critérios 2 e 3).
 *
 * O que estes testes prendem, por ordem de importância:
 *
 * 1. **A assinatura é sobre os bytes recebidos.** O teste do corpo
 *    re-serializado é a letra do critério 2, e é o único que distingue uma
 *    implementação correcta de uma que assina o que o `JSON.stringify`
 *    devolveu — que é o erro fácil, porque passa com todos os corpos que o
 *    próprio teste gerar.
 * 2. **O anel aceita dois e recusa o terceiro** (critério 3).
 * 3. **Um anel mal configurado recusa tudo**, em vez de aceitar tudo.
 */

import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { describe, it } from "node:test";

import {
  CABECALHO_DA_ASSINATURA,
  PREFIXO_DA_ASSINATURA,
  RESUMO_BYTES,
  assinaturaValida,
  resumoDoCabecalho,
  sha256Hex,
} from "../src/entrada/assinatura.ts";

const ACTUAL = "segredo-actual-da-meta";
const ANTERIOR = "segredo-anterior-da-meta";
const TERCEIRO = "segredo-que-nao-e-nosso";

/** O cabeçalho que a Meta mandaria para este corpo e este segredo. */
function assinar(corpo: Uint8Array, segredo: string): string {
  const resumo = createHmac("sha256", segredo).update(corpo).digest("hex");
  return `${PREFIXO_DA_ASSINATURA}${resumo}`;
}

function bytes(texto: string): Uint8Array {
  return new Uint8Array(Buffer.from(texto, "utf8"));
}

const ANEL: readonly (string | null)[] = [ACTUAL, ANTERIOR];

describe("assinatura do webhook", () => {
  const corpo = bytes('{"object":"whatsapp_business_account","entry":[]}');

  it("aceita a assinatura feita com o segredo actual", () => {
    assert.equal(assinaturaValida(corpo, assinar(corpo, ACTUAL), ANEL), true);
  });

  it("aceita a assinatura feita com o segredo anterior (criterio 3)", () => {
    assert.equal(assinaturaValida(corpo, assinar(corpo, ANTERIOR), ANEL), true);
  });

  it("recusa a assinatura feita com um terceiro segredo (criterio 3)", () => {
    assert.equal(assinaturaValida(corpo, assinar(corpo, TERCEIRO), ANEL), false);
  });

  it("recusa a assinatura ausente", () => {
    assert.equal(assinaturaValida(corpo, undefined, ANEL), false);
    assert.equal(assinaturaValida(corpo, "", ANEL), false);
  });

  it("recusa um cabecalho sem o prefixo `sha256=`", () => {
    const resumo = createHmac("sha256", ACTUAL).update(corpo).digest("hex");
    assert.equal(assinaturaValida(corpo, resumo, ANEL), false);
    assert.equal(assinaturaValida(corpo, `sha1=${resumo}`, ANEL), false);
  });

  it("recusa um cabecalho com hexadecimais de maiusculas", () => {
    // A Meta escreve minúsculas. Aceitar maiúsculas era aceitar mais superfície
    // do que a fonte primária descreve.
    const assinatura = assinar(corpo, ACTUAL).toUpperCase();
    assert.equal(assinaturaValida(corpo, assinatura, ANEL), false);
  });

  it("recusa um cabecalho do comprimento errado sem lancar", () => {
    // `timingSafeEqual` lança com buffers de comprimentos diferentes, e o
    // comprimento do cabeçalho é escolhido por quem chama. Isto é a prova de
    // que a forma se valida antes da comparação.
    for (const sufixo of ["", "ab", "0".repeat(63), "0".repeat(65), "0".repeat(1024)]) {
      assert.equal(
        assinaturaValida(corpo, `${PREFIXO_DA_ASSINATURA}${sufixo}`, ANEL),
        false,
        `${sufixo.length} hexadecimais deviam recusar`,
      );
    }
  });

  it("recusa um cabecalho com caracteres que nao sao hexadecimais", () => {
    assert.equal(
      assinaturaValida(corpo, `${PREFIXO_DA_ASSINATURA}${"z".repeat(64)}`, ANEL),
      false,
    );
  });

  // --- O critério 2, na sua forma exacta ------------------------------------
  //
  // «a assinatura é calculada sobre os bytes recebidos antes de `JSON.parse`
  // (um corpo re-serializado com espaços diferentes e a mesma assinatura é
  // rejeitado)».

  it("recusa o mesmo JSON re-serializado com a assinatura do original", () => {
    const original = bytes('{"a":1,"b":"x"}');
    const assinatura = assinar(original, ACTUAL);
    assert.equal(assinaturaValida(original, assinatura, ANEL), true);

    for (const variante of [
      '{ "a": 1, "b": "x" }', // espaços
      '{"b":"x","a":1}', // outra ordem
      '{"a":1,"b":"x"} ', // um espaço no fim
      '{"a":1.0,"b":"x"}', // o mesmo número, outra forma
    ]) {
      // O `JSON.parse` dá o **mesmo** valor para o original e para a variante —
      // menos na ordem, que o `parse` também normaliza em significado — e a
      // assinatura tem de recusar de qualquer maneira.
      assert.equal(
        assinaturaValida(bytes(variante), assinatura, ANEL),
        false,
        `${variante} devia recusar`,
      );
    }
  });

  it("o corpo re-serializado a partir do parse nao bate com o original", () => {
    // O defeito que isto apanha: assinar `JSON.stringify(JSON.parse(corpo))` em
    // vez do corpo. Com este par, as duas formas são diferentes.
    const original = '{ "a": 1 }';
    const reserializado = JSON.stringify(JSON.parse(original));
    assert.notEqual(original, reserializado);
    assert.equal(
      assinaturaValida(bytes(reserializado), assinar(bytes(original), ACTUAL), ANEL),
      false,
    );
  });

  it("um corpo vazio assina-se e verifica-se como qualquer outro", () => {
    const vazio = new Uint8Array(0);
    assert.equal(assinaturaValida(vazio, assinar(vazio, ACTUAL), ANEL), true);
    assert.equal(assinaturaValida(vazio, assinar(corpo, ACTUAL), ANEL), false);
  });

  it("bytes que nao sao UTF-8 validos assinam-se como quaisquer outros", () => {
    // O corpo é bytes e não texto: a assinatura nunca passa por uma
    // descodificação que possa trocar um byte por um carácter de substituição.
    const invalidos = new Uint8Array([0x7b, 0xff, 0xfe, 0x7d]);
    assert.equal(assinaturaValida(invalidos, assinar(invalidos, ACTUAL), ANEL), true);
  });

  // --- Um anel mal configurado falha fechado --------------------------------

  it("um anel vazio recusa tudo", () => {
    assert.equal(assinaturaValida(corpo, assinar(corpo, ACTUAL), []), false);
  });

  it("um anel de segredos nulos ou vazios recusa tudo", () => {
    for (const anel of [[null], [""], [null, null], ["", null]]) {
      assert.equal(assinaturaValida(corpo, assinar(corpo, ACTUAL), anel), false);
      // E, em especial, não valida uma assinatura feita com o segredo vazio:
      // um HMAC com chave vazia é um HMAC válido, e aceitá-lo era aceitar
      // qualquer pedido de quem souber que o cofre está vazio.
      assert.equal(assinaturaValida(corpo, assinar(corpo, ""), anel), false);
    }
  });

  it("um anel com o anterior a null aceita so o actual", () => {
    const anel = [ACTUAL, null];
    assert.equal(assinaturaValida(corpo, assinar(corpo, ACTUAL), anel), true);
    assert.equal(assinaturaValida(corpo, assinar(corpo, ANTERIOR), anel), false);
  });
});

describe("resumoDoCabecalho", () => {
  it("devolve 32 bytes de um cabecalho bem formado", () => {
    const corpo = bytes("x");
    const resumo = resumoDoCabecalho(assinar(corpo, ACTUAL));
    assert.notEqual(resumo, null);
    assert.equal(resumo?.length, RESUMO_BYTES);
  });

  it("devolve null em vez de lancar para tudo o que nao e uma assinatura", () => {
    for (const valor of [undefined, "", "sha256=", "nada", `${PREFIXO_DA_ASSINATURA}zz`]) {
      assert.equal(resumoDoCabecalho(valor), null, `${String(valor)} devia dar null`);
    }
  });

  it("o nome do cabecalho e o que o Hono devolve, em minusculas", () => {
    assert.equal(CABECALHO_DA_ASSINATURA, "x-hub-signature-256");
  });
});

describe("sha256Hex", () => {
  it("e o jobId: determinista e sensivel a cada byte", () => {
    const a = bytes('{"a":1}');
    const b = bytes('{"a":2}');
    assert.equal(sha256Hex(a), sha256Hex(bytes('{"a":1}')));
    assert.notEqual(sha256Hex(a), sha256Hex(b));
    assert.match(sha256Hex(a), /^[0-9a-f]{64}$/);
  });

  it("distingue corpos que o `JSON.parse` iguala", () => {
    // É isto que faz o `jobId` deduplicar re-entregas **byte-a-byte** e não
    // mais do que isso: dois corpos com o mesmo significado são dois *jobs*, e
    // é o `UNIQUE (kind, event_key)` que os junta depois.
    assert.notEqual(sha256Hex(bytes('{"a":1}')), sha256Hex(bytes('{ "a": 1 }')));
  });
});
